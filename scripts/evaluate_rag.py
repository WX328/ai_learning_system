"""Run labelled retrieval evaluation against the current V2 knowledge base."""
from __future__ import annotations

import argparse
import json
import hashlib
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import LearningChunk, LearningMaterial
from app.services.embedding import embedding_model, embedding_dimensions
from app.services.reranker import rerank_chunks, rerank_model, RerankError
from app.services.rag_evaluation import DEFAULT_CUTOFFS, evaluate_cases, load_cases
from app.services.retriever import search_similar_chunks


def display(report: dict[str, Any], cutoffs: tuple[int, ...]) -> None:
    summary = report["summary"]
    print(f"评测题数：{summary['case_count']}")
    for cutoff in cutoffs:
        print(f"Recall@{cutoff}：{summary[f'recall_at_{cutoff}']:.2%}")
    for cutoff in cutoffs:
        print(f"Precision@{cutoff}：{summary[f'precision_at_{cutoff}']:.2%}")
    print(f"MRR@{report.get('top_k', 10)}：{summary['mrr']:.4f}")
    if "candidate_recall" in summary:
        print(f"候选 Recall@{report.get('top_k', 10)}：{summary['candidate_recall']:.2%}")
    print(f"平均检索耗时：{summary['average_retrieval_latency_ms']:.2f} ms")
    if "average_rerank_latency_ms" in summary:
        print(f"平均重排耗时：{summary['average_rerank_latency_ms']:.2f} ms")
        print(f"平均总耗时：{summary['average_total_latency_ms']:.2f} ms")
    failed = [row for row in report["cases"] if row["metrics"]["recall_at_5"] == 0]
    if failed:
        print("\nRecall@5 为 0 的问题：")
        for row in failed:
            print(f"- {row['id']}：{row['question']}")


def validate_labels(cases, db):
    """Reject stale/out-of-scope ground truth before incurring provider calls."""
    if not cases:
        raise ValueError("评测集不能为空")
    for case in cases:
        if db.get(LearningMaterial, case["material_id"]) is None:
            raise ValueError(f"{case['id']}：资料不存在，请更新评测标签")
        for chunk_id in case["relevant_chunk_ids"]:
            chunk = db.get(LearningChunk, chunk_id)
            if (chunk is None or chunk.material_id != case["material_id"] or
                    (case["topic_id"] is not None and chunk.topic_id != case["topic_id"])):
                raise ValueError(f"{case['id']}：标注分段 {chunk_id} 不存在或不在检索范围内")


def serialize_results(results):
    serialized = []
    for row in results:
        similarity = row.get("similarity")
        item = {
            "chunk_id": row["chunk"].id,
            "chunk_index": row["chunk"].chunk_index,
            "similarity": round(float(similarity), 6) if similarity is not None else None,
        }
        for field in ("rerank_score", "bm25_score", "rrf_score", "retrieval_methods"):
            if field in row:
                item[field] = row[field]
        serialized.append(item)
    return serialized


def add_candidate_recall(report: dict[str, Any]) -> None:
    """Measure candidate coverage independently of the final ranking order."""
    recalls = []
    for row in report["cases"]:
        relevant = set(row["relevant_chunk_ids"])
        recall = len(relevant & set(row["retrieved_chunk_ids"])) / len(relevant)
        recalls.append(recall)
        row["metrics"]["candidate_recall"] = round(recall, 4)
    report["summary"]["candidate_recall"] = round(
        sum(recalls) / len(recalls), 4,
    )
    if "baseline" in report:
        add_candidate_recall(report["baseline"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评测当前 RAG 检索的 Recall、Precision、MRR 与耗时")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation" / "rag_eval_100.json")
    parser.add_argument("--top-k", type=int, default=10, help="每题实际召回的最大数量，至少为 5")
    parser.add_argument("--threshold", type=float, default=0.35, help="沿用检索器的相似度阈值")
    parser.add_argument("--output", type=Path, help="可选：把完整报告写为 JSON")
    parser.add_argument("--dry-run", action="store_true", help="仅校验并列出评测题，不调用 Embedding API")
    parser.add_argument("--rerank", action="store_true", help="对同一批候选重排，报告中同时保存原始基线")
    parser.add_argument("--retrieval", choices=("vector", "bm25", "hybrid"), default="vector",
                        help="召回方式；默认 vector 保持原来的向量基线")
    parser.add_argument("--rrf-k", type=int, default=60, help="混合检索 RRF 排名常数，必须为正整数")
    args = parser.parse_args(argv)
    if args.top_k < max(DEFAULT_CUTOFFS):
        parser.error(f"--top-k 至少为 {max(DEFAULT_CUTOFFS)}")
    if not math.isfinite(args.threshold) or not -1 <= args.threshold <= 1:
        parser.error("--threshold 必须在 -1 到 1 之间")
    if args.rrf_k < 1:
        parser.error("--rrf-k 必须为正整数")
    if args.output and args.output.exists():
        parser.error("报告已存在，请使用新的 --output 文件名以保留历史结果")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = load_cases(args.dataset)
    db = SessionLocal()
    try:
        validate_labels(cases, db)
        if args.dry_run:
            print(f"评测集和数据库标签有效：{len(cases)} 题；不会调用模型 API。")
            return 0
        candidates_by_case = {}
        def retrieve(case: dict[str, Any]) -> list[dict[str, Any]]:
            results = search_similar_chunks(
                query=case["question"], material_id=case["material_id"], db=db,
                topic_id=case["topic_id"], top_k=args.top_k, similarity_threshold=args.threshold,
                method=args.retrieval, rrf_k=args.rrf_k,
            )
            candidates_by_case[case["id"]] = results
            print(f"已召回：{case['id']}（{len(results)} 段）", flush=True)
            return serialize_results(results)

        def rerank(case, _results):
            try:
                return serialize_results(rerank_chunks(case["question"], candidates_by_case[case["id"]]))
            except RerankError as exc:
                raise RerankError(f"{case['id']} 重排失败，评测停止（不会以原始排序冒充重排结果）：{exc}") from None

        report = evaluate_cases(cases, retrieve, DEFAULT_CUTOFFS, rerank if args.rerank else None)
        add_candidate_recall(report)
    except (ValueError, RerankError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.close()

    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["dataset"] = str(args.dataset)
    report["top_k"] = args.top_k
    report["similarity_threshold"] = args.threshold
    report["mode"] = ("rerank" if args.rerank else "vector") if args.retrieval == "vector" else (
        f"{args.retrieval}_rerank" if args.rerank else args.retrieval
    )
    report["retrieval_method"] = args.retrieval
    report["rrf_k"] = args.rrf_k if args.retrieval == "hybrid" else None
    report["tokenizer"] = "jieba+ascii-identifiers" if args.retrieval != "vector" else None
    report["similarity_threshold_scope"] = "vector_branch" if args.retrieval == "hybrid" else (
        "vector" if args.retrieval == "vector" else "not_used"
    )
    report["embedding_model"] = embedding_model() if args.retrieval != "bm25" else None
    report["embedding_dimensions"] = embedding_dimensions() if args.retrieval != "bm25" else None
    report["rerank_model"] = rerank_model() if args.rerank else None
    report["dataset_sha256"] = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    report["mrr_cutoff"] = args.top_k
    if args.rerank:
        report["baseline"]["top_k"] = args.top_k
        print(f"\n原始 {args.retrieval} 排序（同一批候选）：")
        display(report["baseline"], DEFAULT_CUTOFFS)
        print("\n重排结果：")
    display(report, DEFAULT_CUTOFFS)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完整报告已写入：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
