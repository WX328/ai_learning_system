"""Paired vector/BM25/hybrid evaluation with one question embedding per case."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.services.embedding import EmbeddingError, embedding_dimensions, embedding_model
from app.services.rag_evaluation import DEFAULT_CUTOFFS, evaluate_cases, load_cases
from app.services.reranker import RerankError, rerank_chunks, rerank_model
from app.services.retriever import search_candidate_rankings, search_similar_chunks
from scripts.evaluate_rag import add_candidate_recall, display, serialize_results, validate_labels


COMPONENTS = {
    "vector": ("db_latency_ms", "embedding_latency_ms", "vector_latency_ms"),
    "bm25": ("db_latency_ms", "bm25_latency_ms"),
    "hybrid": ("db_latency_ms", "embedding_latency_ms", "vector_latency_ms",
               "bm25_latency_ms", "fusion_latency_ms"),
}


def _apply_measured_timings(report, method, timings_by_case):
    """Replace replay lookup latency with the original measured retrieval work."""
    for row in report["cases"]:
        components = {name: timings_by_case[row["id"]][name] for name in COMPONENTS[method]}
        retrieval_ms = sum(components.values())
        rerank_ms = row.get("rerank_latency_ms", 0.0)
        row["retrieval_components_ms"] = {name: round(value, 2) for name, value in components.items()}
        row["retrieval_latency_ms"] = round(retrieval_ms, 2)
        row["rerank_latency_ms"] = rerank_ms
        row["latency_ms"] = round(retrieval_ms + rerank_ms, 2)
    count = len(report["cases"])
    summary = report["summary"]
    summary["average_retrieval_latency_ms"] = round(
        sum(sum(timings_by_case[row["id"]][name] for name in COMPONENTS[method])
            for row in report["cases"]) / count, 2)
    summary["average_total_latency_ms"] = round(
        sum(row["latency_ms"] for row in report["cases"]) / count, 2)
    if "baseline" in report:
        _apply_measured_timings(report["baseline"], method, timings_by_case)


def compare_cases(cases, db, *, top_k=10, threshold=0.35, rrf_k=60,
                  rerank=False, warm_index=True) -> dict[str, Any]:
    """Share retrieval work, then independently score each ranking and reranking."""
    if not cases:
        raise ValueError("评测集不能为空")
    warmup_started = perf_counter()
    warmed_scopes = set()
    if warm_index:
        for case in cases:
            scope = (case["material_id"], case["topic_id"])
            if scope not in warmed_scopes:
                search_similar_chunks(
                    query=case["question"], material_id=case["material_id"],
                    topic_id=case["topic_id"], db=db, top_k=top_k,
                    similarity_threshold=threshold, method="bm25", rrf_k=rrf_k,
                )
                warmed_scopes.add(scope)
    warmup_ms = (perf_counter() - warmup_started) * 1000 if warm_index else 0.0

    rankings_by_case, timings_by_case = {}, {}
    for case in cases:
        rankings, timings = search_candidate_rankings(
            query=case["question"], material_id=case["material_id"], db=db,
            topic_id=case["topic_id"], top_k=top_k,
            similarity_threshold=threshold, rrf_k=rrf_k,
        )
        for method in COMPONENTS:
            rows = rankings[method]
            ids = [row["chunk"].id for row in rows]
            if len(rows) > top_k or len(set(ids)) != len(ids):
                raise ValueError(f"{case['id']}：{method} 候选必须唯一且不超过 top_k")
        if any(not math.isfinite(timings[name]) or timings[name] < 0
               for name in COMPONENTS["hybrid"]):
            raise ValueError(f"{case['id']}：检索耗时无效")
        rankings_by_case[case["id"]] = rankings
        timings_by_case[case["id"]] = timings
        print(f"已完成共享召回：{case['id']}", flush=True)

    modes = {}
    for method in COMPONENTS:
        def retrieve(case, method=method):
            return serialize_results(rankings_by_case[case["id"]][method])

        report = evaluate_cases(cases, retrieve, DEFAULT_CUTOFFS)
        _apply_measured_timings(report, method, timings_by_case)
        add_candidate_recall(report)
        report.update(mode=method, retrieval_method=method, top_k=top_k, mrr_cutoff=top_k)
        modes[method] = report

        if rerank and method in {"vector", "hybrid"}:
            def rank(case, _results, method=method):
                try:
                    rows = rerank_chunks(case["question"], rankings_by_case[case["id"]][method])
                    print(f"已完成重排：{case['id']}（{method}）", flush=True)
                    return serialize_results(rows)
                except RerankError as exc:
                    raise RerankError(
                        f"{case['id']} {method} 重排失败，评测停止：{exc}"
                    ) from None

            reranked = evaluate_cases(cases, retrieve, DEFAULT_CUTOFFS, rank)
            _apply_measured_timings(reranked, method, timings_by_case)
            add_candidate_recall(reranked)
            reranked.update(mode=f"{method}_rerank", retrieval_method=method,
                            top_k=top_k, mrr_cutoff=top_k)
            reranked["baseline"]["top_k"] = top_k
            modes[f"{method}_rerank"] = reranked

    return {
        "schema_version": 1, "modes": modes, "top_k": top_k,
        "rrf_k": rrf_k, "similarity_threshold": threshold,
        "similarity_threshold_scope": "vector_branch",
        "paired_question_embedding": True,
        "timing_policy": "shared retrieval components; measured reranking; warmup excluded",
        "index_temperature": "warm" if warm_index else "cold",
        "warmup_scope_count": len(warmed_scopes), "warmup_latency_ms": round(warmup_ms, 2),
        "retrieval_components_by_case": {
            case_id: {name: round(value, 2) for name, value in timings.items()}
            for case_id, timings in timings_by_case.items()
        },
        "tokenizer": "jieba+ascii-identifiers",
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="同题同次 Embedding 比较向量、BM25、RRF 混合检索")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation" / "rag_eval_100.json")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="仅验证标签，不调用模型或预热")
    parser.add_argument("--rerank", action="store_true", help="额外比较 vector_rerank 与 hybrid_rerank")
    parser.add_argument("--cold-index", action="store_true", help="不预热 BM25 索引")
    args = parser.parse_args(argv)
    if args.top_k < max(DEFAULT_CUTOFFS):
        parser.error(f"--top-k 至少为 {max(DEFAULT_CUTOFFS)}")
    if not math.isfinite(args.threshold) or not -1 <= args.threshold <= 1:
        parser.error("--threshold 必须在 -1 到 1 之间")
    if args.rrf_k < 1:
        parser.error("--rrf-k 必须为正整数")
    if args.output and args.output.exists():
        parser.error("报告已存在，请使用新的 --output 文件名")
    return args


def main(argv=None):
    args = parse_args(argv)
    db = SessionLocal()
    try:
        cases = load_cases(args.dataset)
        validate_labels(cases, db)
        if args.dry_run:
            print(f"评测集和数据库标签有效：{len(cases)} 题；不会调用模型 API。")
            return 0
        report = compare_cases(cases, db, top_k=args.top_k, threshold=args.threshold,
                               rrf_k=args.rrf_k, rerank=args.rerank,
                               warm_index=not args.cold_index)
        dataset_hash = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
        report.update(
            generated_at=datetime.now(timezone.utc).isoformat(), dataset=str(args.dataset),
            dataset_hash=dataset_hash, dataset_sha256=dataset_hash,
            embedding_model=embedding_model(), embedding_dimensions=embedding_dimensions(),
            rerank_model=rerank_model() if args.rerank else None,
        )
        for mode, mode_report in report["modes"].items():
            print(f"\n{mode}：")
            display(mode_report, DEFAULT_CUTOFFS)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also protects against a report created after argument parsing.
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(report, output, ensure_ascii=False, indent=2)
            print(f"\n完整配对报告已写入：{args.output}")
        return 0
    except (ValueError, EmbeddingError, RerankError, OSError) as exc:
        print(f"配对评测停止（不会回退或写入不完整报告）：{exc}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
