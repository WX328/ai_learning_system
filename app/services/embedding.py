"""Embedding access through Alibaba Cloud Model Studio (Bailian)."""
import math
import os
from collections.abc import Sequence
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI
from app.core.settings import timeout_seconds

load_dotenv()

DEFAULT_MODEL = "text-embedding-v4"
DEFAULT_DIMENSIONS = 1024
# Bailian permits at most ten text inputs per synchronous text-embedding-v4 call.
MAX_BATCH_SIZE = 10


class EmbeddingError(RuntimeError):
    """A configuration or response problem from the embedding provider."""


def embedding_model() -> str:
    return os.getenv("DASHSCOPE_EMBEDDING_MODEL", DEFAULT_MODEL)


def embedding_dimensions() -> int:
    raw_value = os.getenv("DASHSCOPE_EMBEDDING_DIMENSIONS", str(DEFAULT_DIMENSIONS))
    try:
        dimensions = int(raw_value)
    except ValueError as exc:
        raise EmbeddingError("DASHSCOPE_EMBEDDING_DIMENSIONS 必须是整数") from exc
    if dimensions <= 0:
        raise EmbeddingError("DASHSCOPE_EMBEDDING_DIMENSIONS 必须大于 0")
    return dimensions


@lru_cache(maxsize=1)
def embedding_client() -> OpenAI:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("DASHSCOPE_EMBEDDING_BASE_URL")
    if not api_key:
        raise EmbeddingError("未配置 DASHSCOPE_API_KEY")
    if not base_url:
        raise EmbeddingError("未配置 DASHSCOPE_EMBEDDING_BASE_URL")
    return OpenAI(api_key=api_key, base_url=base_url,
                  timeout=timeout_seconds("DASHSCOPE_EMBEDDING_TIMEOUT", 30.0), max_retries=0)


def normalize(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        raise EmbeddingError("百炼返回了空向量")
    return [value / norm for value in values]


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Generate normalized embeddings while preserving input order."""
    inputs = list(texts)
    if not inputs:
        return []
    if any(not isinstance(text, str) or not text.strip() for text in inputs):
        raise EmbeddingError("不能为无内容的文本生成向量")

    vectors: list[list[float]] = []
    client = embedding_client()
    try:
        for start in range(0, len(inputs), MAX_BATCH_SIZE):
            batch = inputs[start:start + MAX_BATCH_SIZE]
            response = client.embeddings.create(
                model=embedding_model(),
                input=batch,
                dimensions=embedding_dimensions(),
                encoding_format="float",
            )
            data = sorted(response.data, key=lambda item: item.index)
            if len(data) != len(batch):
                raise EmbeddingError("百炼返回的向量数量与输入文本数量不一致")
            for item in data:
                vector = normalize(item.embedding)
                if len(vector) != embedding_dimensions():
                    raise EmbeddingError(
                        f"百炼返回的向量维度为 {len(vector)}，期望 {embedding_dimensions()}"
                    )
                vectors.append(vector)
    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError(f"百炼向量请求失败：{exc}") from exc

    return vectors


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
