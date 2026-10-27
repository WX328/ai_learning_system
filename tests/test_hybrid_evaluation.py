"""Evaluation CLI contracts; providers and database access are mocked."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import evaluate_rag


def candidates():
    return [
        {"chunk": SimpleNamespace(id=11, chunk_index=0), "similarity": 0.71234567,
         "bm25_score": 2.1, "rrf_score": 1 / 61, "retrieval_methods": ["vector", "bm25"]},
        {"chunk": SimpleNamespace(id=12, chunk_index=1), "similarity": None,
         "bm25_score": 1.2, "rrf_score": 1 / 62, "retrieval_methods": ["bm25"]},
    ]


class HybridEvaluationArgumentsTest(unittest.TestCase):
    def test_original_defaults_are_preserved(self):
        args = evaluate_rag.parse_args([])
        self.assertEqual(args.retrieval, "vector")
        self.assertEqual(args.top_k, 10)
        self.assertEqual(args.threshold, 0.35)
        self.assertEqual(args.rrf_k, 60)
        self.assertFalse(args.rerank)

    def test_invalid_arguments_fail_before_model_calls(self):
        for arguments in (["--rrf-k", "0"], ["--rrf-k", "-1"],
                          ["--rrf-k", "1.5"], ["--retrieval", "unknown"],
                          ["--threshold", "nan"], ["--top-k", "4"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    evaluate_rag.parse_args(arguments)
                self.assertEqual(caught.exception.code, 2)

    def test_hybrid_settings_are_explicit(self):
        args = evaluate_rag.parse_args(["--retrieval", "hybrid", "--rrf-k", "30", "--rerank"])
        self.assertEqual(args.retrieval, "hybrid")
        self.assertEqual(args.rrf_k, 30)
        self.assertTrue(args.rerank)


class HybridEvaluationSerializationTest(unittest.TestCase):
    def test_bm25_only_hit_has_no_invented_vector_score(self):
        rows = evaluate_rag.serialize_results(candidates())
        self.assertEqual(rows[0]["similarity"], 0.712346)
        self.assertIsNone(rows[1]["similarity"])
        self.assertEqual(rows[1]["bm25_score"], 1.2)
        self.assertEqual(rows[0]["rrf_score"], 1 / 61)
        self.assertEqual(rows[0]["retrieval_methods"], ["vector", "bm25"])

    def test_vector_result_keeps_legacy_shape(self):
        row = {"chunk": SimpleNamespace(id=5, chunk_index=2), "similarity": 0.8}
        self.assertEqual(evaluate_rag.serialize_results([row]), [
            {"chunk_id": 5, "chunk_index": 2, "similarity": 0.8},
        ])

    def test_candidate_recall_is_independent_of_rank(self):
        cases = [{"id": "q", "question": "q", "material_id": 1,
                  "topic_id": None, "relevant_chunk_ids": [11, 99]}]
        rows = evaluate_rag.serialize_results(candidates())
        report = evaluate_rag.evaluate_cases(cases, lambda _: rows,
                                             rerank=lambda _, rows: list(reversed(rows)))
        evaluate_rag.add_candidate_recall(report)
        self.assertEqual(report["summary"]["candidate_recall"], 0.5)
        self.assertEqual(report["cases"][0]["metrics"]["candidate_recall"], 0.5)
        self.assertEqual(report["baseline"]["summary"]["candidate_recall"], 0.5)
        self.assertNotEqual(report["summary"]["mrr"], report["baseline"]["summary"]["mrr"])


class HybridEvaluationRunTest(unittest.TestCase):
    def run_cli(self, retrieval, rerank=False):
        cases = [{"id": "q", "question": "q", "material_id": 1,
                  "topic_id": None, "relevant_chunk_ids": [11]}]
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "dataset.json"
            output = Path(directory) / "report.json"
            dataset.write_text(json.dumps(cases), encoding="utf-8")
            arguments = ["--dataset", str(dataset), "--output", str(output),
                         "--retrieval", retrieval]
            if rerank:
                arguments.append("--rerank")
            original = candidates()
            ranking = [{**row, "rerank_score": 0.9 - i / 10}
                       for i, row in enumerate(reversed(original))]
            with patch.object(evaluate_rag, "SessionLocal", return_value=Mock()), \
                    patch.object(evaluate_rag, "validate_labels"), \
                    patch.object(evaluate_rag, "search_similar_chunks", return_value=original) as search, \
                    patch.object(evaluate_rag, "rerank_chunks", return_value=ranking) as rank, \
                    patch.object(evaluate_rag, "embedding_model", return_value="test-embedding") as model, \
                    patch.object(evaluate_rag, "embedding_dimensions", return_value=1024), \
                    patch.object(evaluate_rag, "rerank_model", return_value="test-reranker"), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(evaluate_rag.main(arguments), 0)
                report = json.loads(output.read_text(encoding="utf-8"))
                search.assert_called_once()
                self.assertEqual(search.call_args.kwargs["method"], retrieval)
                self.assertEqual(search.call_args.kwargs["top_k"], 10)
                if rerank:
                    rank.assert_called_once_with("q", original)
                    self.assertEqual(set(report["cases"][0]["retrieved_chunk_ids"]),
                                     set(report["baseline"]["cases"][0]["retrieved_chunk_ids"]))
                else:
                    rank.assert_not_called()
                if retrieval == "bm25":
                    model.assert_not_called()
            return report

    def test_hybrid_report_preserves_scores_and_settings(self):
        report = self.run_cli("hybrid", rerank=True)
        self.assertEqual(report["mode"], "hybrid_rerank")
        self.assertEqual(report["retrieval_method"], "hybrid")
        self.assertEqual(report["rrf_k"], 60)
        self.assertEqual(report["similarity_threshold_scope"], "vector_branch")
        self.assertEqual(report["summary"]["candidate_recall"], 1)
        self.assertIn("rerank_score", report["cases"][0]["retrieved"][0])
        self.assertIsNone(report["cases"][0]["retrieved"][0]["similarity"])

    def test_bm25_report_does_not_claim_an_embedding_model(self):
        report = self.run_cli("bm25")
        self.assertEqual(report["mode"], "bm25")
        self.assertIsNone(report["embedding_model"])
        self.assertIsNone(report["embedding_dimensions"])
        self.assertEqual(report["similarity_threshold_scope"], "not_used")

    def test_default_vector_mode_names_remain_compatible(self):
        self.assertEqual(self.run_cli("vector")["mode"], "vector")
        self.assertEqual(self.run_cli("vector", rerank=True)["mode"], "rerank")


if __name__ == "__main__":
    unittest.main()
