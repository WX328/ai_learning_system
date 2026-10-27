"""Offline retrieval metrics for the local RAG evaluation dataset.

This module is deliberately independent from FastAPI and provider clients so its
metric calculations can be tested without calling an embedding model.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any


DEFAULT_CUTOFFS = (1, 3, 5)


def _unique_ids(values: Iterable[Any]) -> list[int]:
    """Convert IDs to integers while preserving their first occurrence."""
    result = []
    seen = set()
    for value in values:
        value = int(value)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate labelled retrieval cases from a JSON file."""
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    rows = raw["cases"] if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("评测文件必须是数组，或包含 cases 数组的对象")

    cases = []
    case_ids = set()
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {position} 条评测数据必须是对象")
        required = ("id", "question", "material_id", "relevant_chunk_ids")
        missing = [key for key in required if key not in row]
        if missing:
            raise ValueError(f"第 {position} 条评测数据缺少字段：{', '.join(missing)}")
        case_id = str(row["id"]).strip()
        question = str(row["question"]).strip()
        relevant_ids = _unique_ids(row["relevant_chunk_ids"])
        if not case_id or not question or not relevant_ids:
            raise ValueError(f"第 {position} 条评测数据的 id、question、relevant_chunk_ids 不能为空")
        if case_id in case_ids:
            raise ValueError(f"评测 ID 重复：{case_id}")
        case_ids.add(case_id)
        cases.append({
            "id": case_id,
            "question": question,
            "material_id": int(row["material_id"]),
            "relevant_chunk_ids": relevant_ids,
            "topic_id": int(row["topic_id"]) if row.get("topic_id") is not None else None,
            "notes": str(row.get("notes", "")).strip(),
        })
    return cases


def metrics_for_ranking(
    retrieved_chunk_ids: Sequence[int],
    relevant_chunk_ids: Sequence[int],
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
) -> dict[str, float]:
    """Calculate Recall@K, Precision@K and MRR for a single retrieval ranking."""
    relevant = set(_unique_ids(relevant_chunk_ids))
    if not relevant:
        raise ValueError("relevant_chunk_ids 不能为空")
    retrieved = _unique_ids(retrieved_chunk_ids)
    metrics: dict[str, float] = {}
    for cutoff in cutoffs:
        if cutoff < 1:
            raise ValueError("cutoff 必须大于 0")
        hits = len(set(retrieved[:cutoff]) & relevant)
        metrics[f"recall_at_{cutoff}"] = hits / len(relevant)
        # A result list shorter than K is still evaluated as a K-sized request.
        metrics[f"precision_at_{cutoff}"] = hits / cutoff

    metrics["mrr"] = 0.0
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant:
            metrics["mrr"] = 1.0 / rank
            break
    return metrics


def evaluate_cases(
    cases: Sequence[dict[str, Any]],
    retrieve: Callable[[dict[str, Any]], Sequence[dict[str, Any]]],
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
    rerank: Callable | None = None,
) -> dict[str, Any]:
    """Run a retrieval callable over labelled cases and aggregate its metrics.

    ``retrieve`` must return dictionaries containing ``chunk_id`` and may include
    a numeric ``similarity``. It is injected to keep this module model-agnostic.
    """
    if not cases:
        raise ValueError("评测集为空，至少需要一条已标注问题")

    rows = []
    totals = {f"recall_at_{cutoff}": 0.0 for cutoff in cutoffs}
    totals.update({f"precision_at_{cutoff}": 0.0 for cutoff in cutoffs})
    totals["mrr"] = 0.0
    total_latency_ms = 0.0
    baseline_rows = []
    total_rerank_ms = 0.0

    for case in cases:
        started = perf_counter()
        results = list(retrieve(case))
        latency_ms = (perf_counter() - started) * 1000
        retrieval_ms = latency_ms
        rerank_ms = 0.0
        if rerank is not None:
            baseline_ids = _unique_ids(result["chunk_id"] for result in results)
            baseline_rows.append({
                "id": case["id"], "question": case["question"],
                "material_id": case["material_id"],
                "relevant_chunk_ids": case["relevant_chunk_ids"],
                "retrieved_chunk_ids": baseline_ids, "retrieved": results,
                "latency_ms": round(retrieval_ms, 2),
                "metrics": metrics_for_ranking(baseline_ids, case["relevant_chunk_ids"], cutoffs),
            })
            started = perf_counter()
            results = list(rerank(case, results))
            rerank_ms = (perf_counter() - started) * 1000
            if (len(results) != len(baseline_ids) or
                    {result["chunk_id"] for result in results} != set(baseline_ids)):
                raise ValueError("对比评测必须保留同一批候选，不能截断、重复或添加片段")
            total_rerank_ms += rerank_ms
            latency_ms += rerank_ms
        retrieved_ids = _unique_ids(result["chunk_id"] for result in results)
        metrics = metrics_for_ranking(retrieved_ids, case["relevant_chunk_ids"], cutoffs)
        for key, value in metrics.items():
            totals[key] += value
        total_latency_ms += latency_ms
        rows.append({
            "id": case["id"],
            "question": case["question"],
            "material_id": case["material_id"],
            "relevant_chunk_ids": case["relevant_chunk_ids"],
            "retrieved_chunk_ids": retrieved_ids,
            "retrieved": results,
            "latency_ms": round(latency_ms, 2),
            "retrieval_latency_ms": round(retrieval_ms, 2),
            "rerank_latency_ms": round(rerank_ms, 2),
            "metrics": {key: round(value, 4) for key, value in metrics.items()},
        })

    count = len(rows)
    summary = {key: round(value / count, 4) for key, value in totals.items()}
    summary["average_retrieval_latency_ms"] = round(total_latency_ms / count, 2)
    summary["case_count"] = count
    report = {"summary": summary, "cases": rows}
    if rerank is not None:
        baseline_summary = {key: round(sum(row["metrics"][key] for row in baseline_rows) / count, 4)
                            for key in totals}
        baseline_summary["case_count"] = count
        baseline_summary["average_retrieval_latency_ms"] = round(
            sum(row["latency_ms"] for row in baseline_rows) / count, 2)
        summary["average_rerank_latency_ms"] = round(total_rerank_ms / count, 2)
        summary["average_total_latency_ms"] = summary["average_retrieval_latency_ms"]
        summary["average_retrieval_latency_ms"] = baseline_summary["average_retrieval_latency_ms"]
        report["baseline"] = {"summary": baseline_summary, "cases": baseline_rows}
    return report
