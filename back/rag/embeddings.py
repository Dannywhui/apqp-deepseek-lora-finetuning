"""嵌入模型集合。

提供两套实现：
- HashingEmbeddingModel: 纯哈希，无任何依赖（兜底）
- SemanticEmbeddingModel: 基于 sentence-transformers 的中文语义嵌入（默认）

工厂函数 get_embedding_model() 按 EMBEDDING_BACKEND 环境变量选择，
semantic 模式加载失败时自动回退到 hashing。
"""
import hashlib
import logging
import math
import os
import re
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)


class HashingEmbeddingModel:
    """Deterministic local embedding fallback with no model download required."""

    def __init__(self, dimension: int = 384):
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def embed(self, text: str) -> List[float]:
        vector = [0.0] * self.dimension
        for token in self._tokens(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _tokens(self, text: str) -> List[str]:
        raw_tokens = re.findall(r"[\w]+", text.lower(), flags=re.UNICODE)
        tokens: List[str] = []
        for token in raw_tokens:
            tokens.append(token)
            cjk_chars = [char for char in token if "\u4e00" <= char <= "\u9fff"]
            if len(cjk_chars) > 1:
                tokens.extend("".join(cjk_chars[index : index + 2]) for index in range(len(cjk_chars) - 1))
        return tokens


class SemanticEmbeddingModel:
    """基于 sentence-transformers 的中文语义嵌入模型。

    默认使用 BAAI/bge-small-zh-v1.5（512 维，中文优化，约 93MB）。
    模型采用懒加载：首次调用 embed() 时从 HuggingFace 下载并载入，
    之后缓存在内存中复用。

    设计要点：
    - 与 HashingEmbeddingModel 保持相同接口（embed/dimension）
    - 加载失败抛出 RuntimeError，由调用方（get_embedding_model）决定是否回退
    - 多线程首次加载加锁保护，避免重复下载

    模型路径优先级（高→低）：
    1. __init__ 显式传入的 model_name / model_path
    2. 环境变量 EMBEDDING_MODEL_PATH
    3. DEFAULT_MODEL（HF 仓库名，要求可联网）
    """

    DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
    DIMENSION = 512  # bge-small-zh-v1.5 固定输出维度

    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        # 模型解析：env > 参数 > 默认
        env_path = os.getenv("EMBEDDING_MODEL_PATH")
        if env_path and not model_name:
            self.model_name = env_path
            self._from_local = True
        elif model_name:
            self.model_name = model_name
            # 包含路径分隔符视为本地路径
            self._from_local = (os.sep in model_name) or ("/" in model_name) or (":" in model_name)
        else:
            self.model_name = self.DEFAULT_MODEL
            self._from_local = False
        self._dimension = self.DIMENSION
        self._model = None
        self._lock = threading.Lock()
        # 设备选择：有 CUDA 用 GPU，否则 CPU
        if device is None:
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        self._device = device

    @property
    def dimension(self) -> int:
        return self._dimension

    def _ensure_loaded(self):
        """懒加载模型（线程安全）。"""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers 未安装，请先执行: pip install sentence-transformers"
                ) from exc
            src = "本地路径" if self._from_local else "HuggingFace"
            logger.info(
                "正在加载语义嵌入模型 %s (%s, device=%s)...",
                self.model_name, src, self._device,
            )
            self._model = SentenceTransformer(self.model_name, device=self._device)
            logger.info("语义嵌入模型加载完成: %s", self.model_name)

    def embed(self, text: str) -> List[float]:
        self._ensure_loaded()
        # normalize_embeddings=True 让余弦相似度等价于内积，加快检索
        vector = self._model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vector.astype(float).tolist()


def get_embedding_model(
    prefer: Optional[str] = None,
    semantic_model: Optional[str] = None,
    fallback_dimension: int = 384,
) -> "HashingEmbeddingModel | SemanticEmbeddingModel":
    """嵌入模型工厂。

    参数:
        prefer: "semantic" / "hashing" / None
                - None 时从环境变量 EMBEDDING_BACKEND 读取，默认 "semantic"
        semantic_model: 覆盖默认的 bge-small-zh-v1.5
        fallback_dimension: 回退到哈希时使用的维度

    返回:
        SemanticEmbeddingModel（默认）或 HashingEmbeddingModel

    若 prefer=semantic 但 sentence-transformers 未安装或模型加载失败，
    会自动回退到 HashingEmbeddingModel 并打印 warning。
    """
    backend = (prefer or os.getenv("EMBEDDING_BACKEND", "semantic")).lower()
    if backend == "hashing":
        logger.info("使用哈希嵌入（HashingEmbeddingModel, dim=%d）", fallback_dimension)
        return HashingEmbeddingModel(dimension=fallback_dimension)

    # semantic 模式：先实例化（不触发模型下载），用一次 warm-up 来确认可用
    try:
        model = SemanticEmbeddingModel(model_name=semantic_model) if semantic_model else SemanticEmbeddingModel()
        # 预热：触发模型加载
        _ = model.embed("warmup")
        return model
    except Exception as exc:
        logger.warning(
            "语义嵌入不可用（%s: %s），自动回退到 HashingEmbeddingModel(dim=%d)",
            type(exc).__name__, exc, fallback_dimension,
        )
        return HashingEmbeddingModel(dimension=fallback_dimension)
