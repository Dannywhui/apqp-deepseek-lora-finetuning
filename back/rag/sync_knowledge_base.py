"""同步 knowledge_docs/ 目录到 SQLite 向量库。

扫描 knowledge_docs/ 中的文档，执行三向同步：
- 新增：源目录有但数据库没有的文件 → 入库
- 更新：源文件修改时间或大小变化 → 重新入库
- 删除：数据库有但源目录没有的文件 → 删除向量
"""
import argparse
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional

from .embeddings import get_embedding_model
from .sqlite_vector_store import SqliteVectorStore
from .build_vector_store import _read_document, SUPPORTED_SUFFIXES, _resolve_local_model_path

logger = logging.getLogger(__name__)


def sync_knowledge_base(
    input_dir: str | Path,
    db_path: str | Path,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    embedding_dimension: int = 384,
    skip_pdf: bool = False,
    backend: str = "semantic",
) -> Dict[str, int]:
    """同步目录到向量库。返回统计信息。

    backend: "semantic"（默认，bge-small-zh-v1.5）或 "hashing"（兜底）。
    注意：切换 backend 时，维度也会变（semantic=512, hashing=embedding_dimension），
    调用方应先清空旧库再同步，或自行处理维度不匹配问题。
    """
    source_dir = Path(input_dir)
    store = SqliteVectorStore(db_path)

    if backend == "semantic":
        local_path = _resolve_local_model_path()
        if local_path:
            embedder = get_embedding_model(prefer="semantic", semantic_model=local_path, fallback_dimension=embedding_dimension)
        else:
            embedder = get_embedding_model(prefer="semantic", fallback_dimension=embedding_dimension)
    else:
        embedder = get_embedding_model(prefer="hashing", fallback_dimension=embedding_dimension)

    logger.info("同步配置 backend=%s, dim=%d", backend, embedder.dimension)

    # 获取已有文档列表（带文件元数据）
    existing_docs = {d.source: d for d in store.list_documents()}

    # 扫描源目录文件
    files = sorted(p for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
    if skip_pdf:
        files = [p for p in files if p.suffix.lower() != ".pdf"]

    source_files = {p.name: p for p in files}

    # 三类操作统计
    added_docs, added_chunks = 0, 0
    updated_docs, updated_chunks = 0, 0
    deleted_docs, deleted_chunks = 0, 0
    skipped = 0
    errors = 0

    # 1. 新增和更新检测
    for name, path in source_files.items():
        file_mtime = path.stat().st_mtime
        file_size = path.stat().st_size

        if name not in existing_docs:
            # 新增
            try:
                text = _read_document(path)
            except Exception as e:
                print(f"  [错误] {name}: 解析失败 - {e}")
                errors += 1
                continue

            chunks = store.add_document(
                source=name,
                text=text,
                embedding_fn=embedder.embed,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                path=str(path),
                category="APQP",
                file_mtime=file_mtime,
                file_size=file_size,
            )
            added_docs += 1
            added_chunks += chunks
            print(f"  [新增] {name}: {chunks} chunks")

        else:
            # 检查是否需要更新（mtime 或 size 变化）
            doc = existing_docs[name]
            need_update = (
                abs(doc.file_mtime - file_mtime) > 1.0 or  # 修改时间变化超过1秒
                doc.file_size != file_size  # 文件大小变化
            )

            if need_update:
                try:
                    text = _read_document(path)
                except Exception as e:
                    print(f"  [错误] {name}: 解析失败 - {e}")
                    errors += 1
                    continue

                chunks = store.add_document(
                    source=name,
                    text=text,
                    embedding_fn=embedder.embed,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    path=str(path),
                    category="APQP",
                    file_mtime=file_mtime,
                    file_size=file_size,
                )
                updated_docs += 1
                updated_chunks += chunks
                print(f"  [更新] {name}: {chunks} chunks")
            else:
                skipped += 1

    # 2. 删除检测（数据库有但源目录没有）
    for name in existing_docs:
        if name not in source_files:
            deleted = store.delete_document(name)
            deleted_docs += 1
            deleted_chunks += deleted
            print(f"  [删除] {name}: {deleted} chunks")

    return {
        "total_scanned": len(files),
        "added_documents": added_docs,
        "added_chunks": added_chunks,
        "updated_documents": updated_docs,
        "updated_chunks": updated_chunks,
        "deleted_documents": deleted_docs,
        "deleted_chunks": deleted_chunks,
        "skipped_unchanged": skipped,
        "errors": errors,
        "remaining_documents": len(store.list_documents()),
        "remaining_chunks": store.count_chunks(),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同步 knowledge_docs/ 到 SQLite 向量库（增删改）")
    parser.add_argument("--input-dir", default="knowledge_docs", help="源文档目录")
    parser.add_argument("--db-path", default="knowledge_base/vector_store.sqlite", help="SQLite 数据库路径")
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    parser.add_argument("--dimension", type=int, default=384,
                        help="哈希模式维度；语义模式固定 512")
    parser.add_argument("--skip-pdf", action="store_true", help="跳过 PDF 文件（缺 PyMuPDF 时用）")
    parser.add_argument("--backend", choices=["semantic", "hashing"], default="semantic",
                        help="嵌入后端，默认 semantic (bge-small-zh-v1.5)")
    args = parser.parse_args(argv)

    print(f"同步配置:")
    print(f"  源目录: {args.input_dir}")
    print(f"  数据库: {args.db_path}")
    print(f"  嵌入后端: {args.backend}")
    print(f"  跳过PDF: {args.skip_pdf}")
    print()

    stats = sync_knowledge_base(
        input_dir=args.input_dir,
        db_path=args.db_path,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        embedding_dimension=args.dimension,
        skip_pdf=args.skip_pdf,
        backend=args.backend,
    )

    print(f"\n同步完成:")
    print(f"  扫描文档: {stats['total_scanned']}")
    print(f"  新增: {stats['added_documents']} 文档, {stats['added_chunks']} 分片")
    print(f"  更新: {stats['updated_documents']} 文档, {stats['updated_chunks']} 分片")
    print(f"  删除: {stats['deleted_documents']} 文档, {stats['deleted_chunks']} 分片")
    print(f"  跳过: {stats['skipped_unchanged']} 文档（无变化）")
    if stats['errors']:
        print(f"  错误: {stats['errors']} 文档")
    print(f"  总文档数: {stats['remaining_documents']}")
    print(f"  总分片数: {stats['remaining_chunks']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
