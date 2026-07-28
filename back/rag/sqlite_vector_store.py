"""基于 SQLite 的向量存储，支持文档级元数据管理与删除。

替代 JsonlVectorStore：
- search 接口签名保持一致，main.py 改动最小
- 额外提供 add_document / delete_document / list_documents 等 API
- 向量以 JSON 文本存入 chunks.embedding 列；检索仍为内存余弦（小规模足够）
"""
import json
import math
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .vector_store import SearchResult, VectorRecord, chunk_text


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    source      TEXT PRIMARY KEY,
    path        TEXT,
    category    TEXT,
    chunk_count INTEGER DEFAULT 0,
    created_at  TEXT,
    file_mtime  REAL,
    file_size   INTEGER
);

CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embedding   TEXT NOT NULL,
    metadata    TEXT NOT NULL,
    FOREIGN KEY (source) REFERENCES documents(source) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
"""


@dataclass(frozen=True)
class DocumentInfo:
    source: str
    path: str
    category: str
    chunk_count: int
    created_at: str
    file_mtime: float = 0.0
    file_size: int = 0


class SqliteVectorStore:
    """SQLite 后端向量库，线程安全（每个线程独立连接）。

    检索策略：一次性把 chunks 全量载入内存（与 JsonlVectorStore 行为一致），
    走纯 Python 余弦相似度。对小规模知识库（几千分片）足够，避免引入额外依赖。
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._ensure_schema()
        # 内存缓存：(VectorRecord, ) 列表，供 search 使用
        self._records: List[VectorRecord] = []
        self._loaded = False

    # ---------- 连接管理 ----------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()

    # ---------- 载入缓存 ----------
    def load(self) -> "SqliteVectorStore":
        """全量载入 chunks 到内存缓存。"""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, text, embedding, metadata FROM chunks"
            ).fetchall()
        self._records = [
            VectorRecord(
                id=row[0],
                text=row[1],
                embedding=json.loads(row[2]),
                metadata=json.loads(row[3]),
            )
            for row in rows
        ]
        self._loaded = True
        return self

    @property
    def records(self) -> List[VectorRecord]:
        if not self._loaded:
            self.load()
        return self._records

    # ---------- 检索 ----------
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 4,
        min_score: float = 0.0,
        source_filter: Optional[str] = None,
    ) -> List[SearchResult]:
        if top_k <= 0:
            return []
        records = self.records
        if source_filter:
            records = [r for r in records if r.metadata.get("source") == source_filter]
        results = [
            SearchResult(record=r, score=_cosine_similarity(query_embedding, r.embedding))
            for r in records
        ]
        results = [r for r in results if r.score >= min_score]
        return sorted(results, key=lambda r: r.score, reverse=True)[:top_k]

    # ---------- 文档级 API ----------
    def add_document(
        self,
        source: str,
        text: str,
        embedding_fn,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        path: str = "",
        category: str = "APQP",
        metadata_extra: Optional[Dict[str, Any]] = None,
        file_mtime: float = 0.0,
        file_size: int = 0,
    ) -> int:
        """写入一个文档及其分片。返回新增分片数。

        embedding_fn: 签名 (text: str) -> List[float]
        file_mtime: 文件修改时间戳，用于检测更新
        file_size: 文件大小（字节），用于检测更新
        """
        chunks = chunk_text(text, chunk_size, chunk_overlap)
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            # 先清理旧数据（如果同名文档已存在）
            conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
            conn.execute(
                "INSERT OR REPLACE INTO documents(source, path, category, chunk_count, created_at, file_mtime, file_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source, path, category, len(chunks), now, file_mtime, file_size),
            )
            rows = []
            for idx, chunk in enumerate(chunks, start=1):
                base_meta = {
                    "source": source,
                    "path": path,
                    "chunk_index": idx,
                    "category": category,
                }
                if metadata_extra:
                    base_meta.update(metadata_extra)
                chunk_id = f"{source}__chunk_{idx:04d}"
                rows.append(
                    (
                        chunk_id,
                        source,
                        idx,
                        chunk,
                        json.dumps(embedding_fn(chunk), ensure_ascii=False),
                        json.dumps(base_meta, ensure_ascii=False),
                    )
                )
            conn.executemany(
                "INSERT INTO chunks(id, source, chunk_index, text, embedding, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        # 刷新内存缓存
        self.load()
        return len(chunks)

    def delete_document(self, source: str) -> int:
        """删除指定文档及其全部分片。返回被删除的分片数。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT chunk_count FROM documents WHERE source = ?", (source,)
            ).fetchone()
            deleted = row[0] if row else 0
            conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
            conn.execute("DELETE FROM documents WHERE source = ?", (source,))
            conn.commit()
        if deleted:
            self.load()
        return deleted

    def list_documents(self) -> List[DocumentInfo]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT source, path, category, chunk_count, created_at, file_mtime, file_size "
                "FROM documents ORDER BY created_at DESC"
            ).fetchall()
        return [
            DocumentInfo(
                source=r[0], path=r[1], category=r[2], chunk_count=r[3],
                created_at=r[4], file_mtime=r[5] or 0.0, file_size=r[6] or 0
            )
            for r in rows
        ]

    def get_document(self, source: str) -> Optional[DocumentInfo]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT source, path, category, chunk_count, created_at, file_mtime, file_size FROM documents WHERE source = ?",
                (source,),
            ).fetchone()
        if not row:
            return None
        return DocumentInfo(
            source=row[0], path=row[1], category=row[2], chunk_count=row[3],
            created_at=row[4], file_mtime=row[5] or 0.0, file_size=row[6] or 0
        )

    def find_source_by_text_keyword(self, keyword: str) -> Optional[str]:
        """在所有分片的文本中查找包含关键词的文档，返回第一个匹配的 source。

        用于精确匹配场景，如根据8D编号查找对应的文档。
        关键词匹配大小写不敏感。
        同时匹配文档内容（text）和文档文件名（source）。
        """
        keyword_lower = keyword.lower()
        records = self.records
        for record in records:
            # 优先匹配文件名（source）
            source = record.metadata.get("source", "")
            if source and keyword_lower in source.lower():
                return source
            # 其次匹配文档内容
            if keyword_lower in record.text.lower():
                return source
        return None

    def get_source_chunks(self, source: str) -> List[VectorRecord]:
        """获取指定文档的所有分片，按 chunk_index 排序。"""
        records = self.records
        return sorted(
            [r for r in records if r.metadata.get("source") == source],
            key=lambda r: r.metadata.get("chunk_index", 0),
        )

    def count_chunks(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0]) if row else 0


def _cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(v * v for v in left))
    right_norm = math.sqrt(sum(v * v for v in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
