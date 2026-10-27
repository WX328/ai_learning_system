"""Paired comparison checks with offline embeddings, rankings, and database."""
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.services import retriever
from app.models import LearningChunk, Topic
from app.services.embedding import EmbeddingError
from app.services.reranker import RerankError
from scripts import compare_retrieval as comparison


def cases():
    return [
        {"id": "one", "question": "alpha", "material_id": 21, "topic_id": None,
         "relevant_chunk_ids": [1], "notes": ""},
        {"id": "two", "question": "beta", "material_id": 21, "topic_id": None,
         "relevant_chunk_ids": [2], "notes": ""},
        {"id": "three", "question": "gamma", "material_id": 24, "topic_id": 81,
         "relevant_chunk_ids": [3], "notes": ""},
    ]


def chunks():
    return [SimpleNamespace(id=i, chunk_index=i - 1, topic_id=81, content=f"token_{i}",
                            embedding=json.dumps([1, i / 20])) for i in range(1, 13)]


def rankings():
    rows = chunks()
    return {
        "vector": [{"chunk": row, "similarity": 0.9} for row in rows[:5]],
        "bm25": [{"chunk": row, "bm25_score": 0.5, "similarity": None} for row in rows[-5:]],
        "hybrid": [{"chunk": row, "rrf_score": 0.02, "similarity": 0.8} for row in rows[2:7]],
    }


TIMINGS = {"db_latency_ms": 2.0, "embedding_latency_ms": 100.0,
           "vector_latency_ms": 3.0, "bm25_latency_ms": 4.0, "fusion_latency_ms": 5.0}


class ComparisonTest(unittest.TestCase):
    def setUp(self):
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_one_shared_embedding_and_chunk_read_per_question(self):
        db, scope, topic_scope = Mock(), Mock(), Mock()
        db.query.side_effect = lambda model: topic_scope if model is Topic else scope
        topic_scope.filter.return_value = topic_scope
        topic_scope.first.return_value = SimpleNamespace(id=81, name="selected topic")
        scope.filter.return_value = scope
        scope.order_by.return_value = scope
        scope.all.return_value = chunks()
        with patch.object(retriever, "embed_text", return_value=[1, 0]) as embed, \
                patch.object(retriever, "search_bm25_chunks", return_value=[
                    {"chunk": row, "bm25_score": 1.0} for row in chunks()[-5:]
                ]) as bm25:
            report = comparison.compare_cases(cases(), db, top_k=5, warm_index=False)
        self.assertEqual(embed.call_count, 3)
        self.assertEqual([call.args[0] for call in embed.call_args_list], ["alpha", "beta", "gamma"])
        self.assertEqual(sum(call.args[0] is LearningChunk for call in db.query.call_args_list), 3)
        self.assertEqual(sum(call.args[0] is Topic for call in db.query.call_args_list), 1)
        self.assertEqual(scope.all.call_count, 3)
        self.assertEqual(scope.filter.call_count, 3)  # One material chunk read per case.
        self.assertEqual(topic_scope.filter.call_count, 1)  # Validate the selected topic and its material.
        self.assertEqual(bm25.call_count, 3)
        self.assertEqual(set(report["modes"]), {"vector", "bm25", "hybrid"})
        for mode_report in report["modes"].values():
            self.assertTrue(all(len(row["retrieved_chunk_ids"]) == 5 for row in mode_report["cases"]))

    def test_prewarms_each_unique_scope_once_without_measured_embedding(self):
        with patch.object(comparison, "search_similar_chunks") as warm, \
                patch.object(comparison, "search_candidate_rankings", return_value=(rankings(), TIMINGS)) as search:
            report = comparison.compare_cases(cases(), Mock(), top_k=5)
        self.assertEqual(warm.call_count, 2)
        self.assertEqual(search.call_count, 3)
        self.assertEqual(report["warmup_scope_count"], 2)
        self.assertEqual(report["index_temperature"], "warm")
        for call in warm.call_args_list:
            self.assertEqual(call.kwargs["method"], "bm25")
        self.assertEqual(warm.call_args_list[0].kwargs["topic_id"], None)
        self.assertEqual(warm.call_args_list[1].kwargs["topic_id"], 81)

    def test_injects_measured_component_timings_instead_of_lookup_latency(self):
        # Each evaluate_cases clock interval is 100 ms, unlike the actual retrieval timings.
        clock = iter(i / 10 for i in range(200))
        def reverse(_query, rows):
            return [{**row, "rerank_score": 0.5} for row in reversed(rows)]
        with patch.object(comparison, "search_candidate_rankings", return_value=(rankings(), TIMINGS)), \
                patch.object(comparison, "rerank_chunks", side_effect=reverse) as rerank, \
                patch("app.services.rag_evaluation.perf_counter", side_effect=lambda: next(clock)):
            report = comparison.compare_cases(cases(), Mock(), top_k=5, rerank=True, warm_index=False)
        self.assertEqual(rerank.call_count, 6)
        self.assertEqual(set(report["modes"]), {"vector", "bm25", "hybrid", "vector_rerank", "hybrid_rerank"})
        for method, retrieval_ms in (("vector", 105), ("bm25", 6), ("hybrid", 114)):
            mode = report["modes"][method]
            self.assertEqual(mode["summary"]["average_retrieval_latency_ms"], retrieval_ms)
            self.assertEqual(mode["summary"]["average_total_latency_ms"], retrieval_ms)
            self.assertTrue(all(row["latency_ms"] == retrieval_ms for row in mode["cases"]))
        for method in ("vector", "hybrid"):
            report_mode = report["modes"][f"{method}_rerank"]
            retrieval_ms = 105 if method == "vector" else 114
            self.assertEqual(report_mode["summary"]["average_retrieval_latency_ms"], retrieval_ms)
            self.assertEqual(report_mode["summary"]["average_rerank_latency_ms"], 100)
            self.assertEqual(report_mode["summary"]["average_total_latency_ms"], retrieval_ms + 100)
            for row, baseline in zip(report_mode["cases"], report_mode["baseline"]["cases"]):
                self.assertEqual(row["retrieval_latency_ms"], retrieval_ms)
                self.assertEqual(row["rerank_latency_ms"], 100)
                self.assertEqual(row["latency_ms"], retrieval_ms + 100)
                self.assertEqual(baseline["latency_ms"], retrieval_ms)
                self.assertEqual(set(row["retrieved_chunk_ids"]), set(baseline["retrieved_chunk_ids"]))

    def test_rerank_failure_is_strict_and_never_falls_back(self):
        with patch.object(comparison, "search_candidate_rankings", return_value=(rankings(), TIMINGS)), \
                patch.object(comparison, "rerank_chunks", side_effect=RerankError("timeout")):
            with self.assertRaisesRegex(RerankError, "one vector 重排失败"):
                comparison.compare_cases(cases(), Mock(), top_k=5, rerank=True, warm_index=False)

    def test_rerank_cannot_drop_candidates(self):
        with patch.object(comparison, "search_candidate_rankings", return_value=(rankings(), TIMINGS)), \
                patch.object(comparison, "rerank_chunks", return_value=[]):
            with self.assertRaisesRegex(ValueError, "同一批候选"):
                comparison.compare_cases(cases(), Mock(), top_k=5, rerank=True, warm_index=False)

    def test_embedding_failure_is_not_replaced_by_bm25(self):
        with patch.object(comparison, "search_candidate_rankings", side_effect=EmbeddingError("offline")), \
                patch.object(comparison, "rerank_chunks") as rerank:
            with self.assertRaises(EmbeddingError):
                comparison.compare_cases(cases(), Mock(), warm_index=False)
        rerank.assert_not_called()

    def test_dry_run_never_calls_retrieval_and_closes_session(self):
        db = Mock()
        with patch.object(comparison, "SessionLocal", return_value=db), \
                patch.object(comparison, "load_cases", return_value=cases()), \
                patch.object(comparison, "validate_labels") as validate, \
                patch.object(comparison, "compare_cases") as compare:
            self.assertEqual(comparison.main(["--dry-run", "--rerank"]), 0)
        validate.assert_called_once_with(cases(), db)
        compare.assert_not_called()
        db.close.assert_called_once()

    def test_refuses_existing_report_output_and_invalid_parameters(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("original", encoding="utf-8")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                comparison.parse_args(["--output", str(output)])
            self.assertEqual(output.read_text(encoding="utf-8"), "original")
        for argv in (["--top-k", "4"], ["--threshold", "nan"], ["--rrf-k", "0"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                comparison.parse_args(argv)

    def test_main_writes_dataset_hash_and_model_metadata(self):
        with TemporaryDirectory() as directory:
            dataset = Path(directory) / "data.json"
            dataset.write_text(json.dumps(cases()), encoding="utf-8")
            output = Path(directory) / "report.json"
            db = Mock()
            with patch.object(comparison, "SessionLocal", return_value=db), \
                    patch.object(comparison, "validate_labels"), \
                    patch.object(comparison, "search_candidate_rankings", return_value=(rankings(), TIMINGS)), \
                    patch.object(comparison, "embedding_model", return_value="test-embedding"), \
                    patch.object(comparison, "embedding_dimensions", return_value=2):
                self.assertEqual(comparison.main(["--dataset", str(dataset), "--output", str(output),
                                                  "--top-k", "5", "--cold-index"]), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(report["dataset_hash"]), 64)
            self.assertEqual(report["dataset_hash"], report["dataset_sha256"])
            self.assertEqual(report["embedding_model"], "test-embedding")
            self.assertEqual(report["rrf_k"], 60)
            self.assertEqual(report["warmup_latency_ms"], 0)
            self.assertIsNone(report["rerank_model"])


if __name__ == "__main__":
    unittest.main()
