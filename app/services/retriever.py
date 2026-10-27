"""Scoped vector/BM25 retrieval and reciprocal rank fusion."""
import json
import math
import os
from time import perf_counter
from types import SimpleNamespace

import numpy as np

from app.models import LearningChunk
from app.services.embedding import embed_text
from app.services.lexical_retriever import search_bm25_chunks
from app.services.topic_scope import scoped_topic_chunks


class RetrievalResults(list):
    """List-compatible results with request-local diagnostics."""

    def __init__(self, rows=(), metadata=None):
        super().__init__(rows)
        self.metadata = metadata or {}


def retrieval_method():
    method = os.getenv("RAG_RETRIEVAL_METHOD", "vector").strip().lower()
    if method not in {"vector", "bm25", "hybrid"}:
        raise ValueError("RAG_RETRIEVAL_METHOD 必须是 vector、bm25 或 hybrid")
    return method


def retrieval_rrf_k():
    try:
        value = int(os.getenv("RAG_RRF_K", "60"))
    except ValueError:
        raise ValueError("RAG_RRF_K 必须是正整数") from None
    if value < 1:
        raise ValueError("RAG_RRF_K 必须是正整数")
    return value


def cosine_similarity(vector1, vector2):
    """Explicit normalization; malformed embeddings are skipped by callers."""
    v1 = np.asarray(vector1, dtype=float)
    v2 = np.asarray(vector2, dtype=float)
    if v1.ndim != 1 or v2.ndim != 1 or v1.shape != v2.shape:
        raise ValueError("向量维度不一致")
    if not np.isfinite(v1).all() or not np.isfinite(v2).all():
        raise ValueError("向量包含无效数值")
    scale1 = float(np.max(np.abs(v1), initial=0.0))
    scale2 = float(np.max(np.abs(v2), initial=0.0))
    if scale1 == 0 or scale2 == 0:
        return 0.0
    # Scaling avoids overflowing the norm/dot product for finite large vectors.
    v1, v2 = v1 / scale1, v2 / scale2
    v1, v2 = v1 / np.linalg.norm(v1), v2 / np.linalg.norm(v2)
    return float(np.clip(np.dot(v1, v2), -1.0, 1.0))


def fuse_rankings(vector_results, bm25_results, top_k=10, rrf_k=60):
    """Fuse ranks, never raw BM25/cosine scores; deduplicate by chunk id."""
    if type(rrf_k) is not int or rrf_k < 1:
        raise ValueError("rrf_k 必须是正整数")
    merged = {}
    for method, rows in (("vector", vector_results), ("bm25", bm25_results)):
        seen = set()
        rank = 0
        for row in rows:
            chunk_id = row["chunk"].id
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            rank += 1
            item = merged.setdefault(chunk_id, {
                "chunk": row["chunk"], "similarity": None,
                "bm25_score": None, "rrf_score": 0.0, "retrieval_methods": [],
            })
            if row.get("similarity") is not None:
                item["similarity"] = row["similarity"]
            if row.get("bm25_score") is not None:
                item["bm25_score"] = row["bm25_score"]
            item["rrf_score"] += 1.0 / (rrf_k + rank)
            item["retrieval_methods"].append(method)
    ranked = sorted(merged.values(), key=lambda row: (-row["rrf_score"], row["chunk"].id))
    return ranked[:top_k]


def _validate_search(method, top_k, similarity_threshold, rrf_k):
    if method not in {"vector", "bm25", "hybrid"}:
        raise ValueError("method 必须是 vector、bm25 或 hybrid")
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k 必须是正整数")
    if not math.isfinite(similarity_threshold) or not -1 <= similarity_threshold <= 1:
        raise ValueError("similarity_threshold 必须在 -1 到 1 之间")
    if type(rrf_k) is not int or rrf_k < 1:
        raise ValueError("rrf_k 必须是正整数")


def _search_rankings(query, material_id, db, top_k, similarity_threshold, topic_id, method, rrf_k):
    _validate_search(method, top_k, similarity_threshold, rrf_k)
    timings = dict.fromkeys(("db_latency_ms", "embedding_latency_ms", "vector_latency_ms",
                            "bm25_latency_ms", "fusion_latency_ms"), 0.0)
    started = perf_counter()
    if topic_id is not None:
        scoped = scoped_topic_chunks(db, material_id, topic_id)
        chunks = [chunk for chunk, _ in scoped]
        contents = {chunk.id: content for chunk, content in scoped}
    else:
        chunks = db.query(LearningChunk).filter(LearningChunk.material_id == material_id).order_by(
            LearningChunk.id
        ).all()
        contents = {}
    timings["db_latency_ms"] = (perf_counter() - started) * 1000
    vector_results, bm25_results, similarities = [], [], {}
    if not chunks or not query.strip():
        return {"vector": [], "bm25": [], "hybrid": []}, timings

    if method != "bm25":
        started = perf_counter()
        query_vector = embed_text(query)
        timings["embedding_latency_ms"] = (perf_counter() - started) * 1000
        started = perf_counter()
        for chunk in chunks:
            if not chunk.embedding:
                continue
            try:
                similarity = cosine_similarity(query_vector, json.loads(chunk.embedding))
            except (json.JSONDecodeError, TypeError, ValueError, OverflowError):
                continue
            similarities[chunk.id] = similarity
            if similarity >= similarity_threshold:
                vector_results.append({"chunk": chunk, "similarity": similarity})
        vector_results.sort(key=lambda row: (-row["similarity"], row["chunk"].id))
        vector_results = vector_results[:top_k]
        timings["vector_latency_ms"] = (perf_counter() - started) * 1000

    if method != "vector":
        started = perf_counter()
        by_id = {chunk.id: chunk for chunk in chunks}
        corpus = [SimpleNamespace(id=chunk.id, content=contents.get(chunk.id, chunk.content))
                  for chunk in chunks]
        bm25_results = [
            {**row, "chunk": by_id[row["chunk"].id],
             "similarity": similarities.get(row["chunk"].id), "retrieval_methods": ["bm25"]}
            for row in search_bm25_chunks(query, corpus, top_k=top_k)
        ]
        timings["bm25_latency_ms"] = (perf_counter() - started) * 1000

    hybrid_results = []
    if method == "hybrid":
        started = perf_counter()
        hybrid_results = fuse_rankings(vector_results, bm25_results, top_k=top_k, rrf_k=rrf_k)
        timings["fusion_latency_ms"] = (perf_counter() - started) * 1000
    rankings = {"vector": vector_results, "bm25": bm25_results, "hybrid": hybrid_results}
    if contents:
        for rows in rankings.values():
            for row in rows:
                row["content"] = contents[row["chunk"].id]
    return rankings, timings


def topic_context_chunks(material_id: int, topic_id: int, db, top_k: int = 6):
    """Read known topic sources without requiring the question to repeat their words."""
    started = perf_counter()
    scoped = scoped_topic_chunks(db, material_id, topic_id)
    rows = [{"chunk": chunk, "content": content, "similarity": None,
             "retrieval_methods": ["topic"]} for chunk, content in scoped[:top_k]]
    return RetrievalResults(rows, {
        "retrieval_method": "topic", "db_latency_ms": round((perf_counter() - started) * 1000, 2),
        "vector_candidate_count": 0, "bm25_candidate_count": 0,
    })


# Retain the existing helper for callers that request topic summaries directly.
topic_summary_chunks = topic_context_chunks


def search_candidate_rankings(query, material_id, db, top_k=10, similarity_threshold=0.35,
                              topic_id=None, rrf_k=60):
    """Paired evaluation uses one question embedding for all three rankings."""
    return _search_rankings(query, material_id, db, top_k, similarity_threshold,
                            topic_id, "hybrid", rrf_k)


def search_similar_chunks(query: str, material_id: int, db, top_k: int = 6,
                          similarity_threshold: float = 0.35, topic_id: int | None = None,
                          method: str = "vector", rrf_k: int = 60):
    """Existing callers remain vector-only unless they explicitly select hybrid."""
    rankings, timings = _search_rankings(query, material_id, db, top_k,
                                        similarity_threshold, topic_id, method, rrf_k)
    rows = rankings[method]
    metadata = {"retrieval_method": method, "vector_candidate_count": len(rankings["vector"]),
                "bm25_candidate_count": len(rankings["bm25"]),
                **{key: round(value, 2) for key, value in timings.items()}}
    return RetrievalResults(rows, metadata)
