"""Bailian qwen3-rerank; preserves candidate identity and original similarity."""
import math
import os
from functools import lru_cache
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

load_dotenv()


class RerankError(RuntimeError):
    pass


def rerank_model():
    return os.getenv("DASHSCOPE_RERANK_MODEL", "qwen3-rerank")


def rerank_url():
    explicit = os.getenv("DASHSCOPE_RERANK_URL", "").strip()
    if explicit:
        return explicit
    # Only infer the documented workspace endpoint; never guess other hosts.
    base = urlsplit(os.getenv("DASHSCOPE_EMBEDDING_BASE_URL", ""))
    if (base.scheme == "https" and base.hostname and
            base.hostname.endswith(".maas.aliyuncs.com") and
            not base.username and not base.password and not base.port):
        return f"https://{base.hostname}/compatible-api/v1/reranks"
    raise RerankError("请配置 DASHSCOPE_RERANK_URL（完整的重排序接口地址）")


def rerank_enabled():
    return os.getenv("RAG_RERANK_ENABLED", "false").lower() in {"true", "1", "yes"}


@lru_cache(maxsize=4)
def _client(timeout):
    return httpx.Client(timeout=timeout, follow_redirects=False)


def rerank_chunks(query, candidates, top_n=None):
    """Strict mode: invalid, partial or failed provider results raise RerankError.

    Candidates have the same shape as search_similar_chunks results. Returned
    index is an input-list position, never a database chunk ID. No DB writes.
    """
    candidates = list(candidates)
    if not candidates:
        return []
    limit = len(candidates) if top_n is None else top_n
    if type(limit) is not int or limit < 1:
        raise RerankError("top_n 必须是正整数")
    limit = min(limit, len(candidates))
    if not isinstance(query, str) or not query.strip():
        raise RerankError("重排问题不能为空")
    documents = [item.get("content", item["chunk"].content) for item in candidates]
    if any(not isinstance(doc, str) or not doc.strip() for doc in documents):
        raise RerankError("候选片段内容不能为空")
    api_key = os.getenv("DASHSCOPE_RERANK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RerankError("未配置 DASHSCOPE_API_KEY 或 DASHSCOPE_RERANK_API_KEY")
    try:
        timeout = float(os.getenv("DASHSCOPE_RERANK_TIMEOUT", "15"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        raise RerankError("DASHSCOPE_RERANK_TIMEOUT 必须是正数") from None
    url = rerank_url()
    try:
        response = _client(timeout).post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": rerank_model(), "query": query, "documents": documents,
                  "top_n": limit},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Avoid logging API keys, candidate text or raw provider error bodies.
        raise RerankError(f"百炼重排 HTTP {exc.response.status_code}，请检查模型权限、地址或限流") from None
    except httpx.RequestError:
        raise RerankError("百炼重排连接失败或超时") from None
    try:
        rows = response.json()["results"]
        if not isinstance(rows, list) or len(rows) != limit:
            raise ValueError
        seen = set()
        ranked = []
        for row in rows:
            index = row["index"]
            score = row["relevance_score"]
            if (type(index) is not int or index in seen or not 0 <= index < len(candidates)
                    or isinstance(score, bool) or not isinstance(score, (float, int))
                    or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError
            seen.add(index)
            ranked.append({**candidates[index], "rerank_score": float(score)})
        return sorted(ranked, key=lambda item: item["rerank_score"], reverse=True)
    except (KeyError, TypeError, ValueError):
        raise RerankError("百炼重排响应不完整或格式异常") from None
