"""Contract and RAG integration tests. All provider calls are mocked."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from app.services.reranker import RerankError, rerank_chunks, rerank_url
from app.services.rag_evaluation import evaluate_cases
from app.schemas.rag import RAGAskResponse


def candidates():
    return [{"chunk": SimpleNamespace(id=i, chunk_index=i, content=f"passage {i}"),
             "similarity": 0.9 - i / 100} for i in (41, 52, 63)]


class RagResponseSchemaTest(unittest.TestCase):
    def test_sources_and_retrieval_metadata_are_part_of_public_response(self):
        response = RAGAskResponse.model_validate({
            "history_id": 5,
            "question": "q",
            "answer": "a",
            "status": "answered",
            "context_source": "retrieval",
            "sources": [{
                "rank": 1, "chunk_id": 63, "chunk_index": 2, "topic_id": None,
                "excerpt": "passage", "similarity": 0.8, "rerank_score": 0.9,
            }],
            "retrieval": {
                "candidate_count": 10, "source_count": 1,
                "rerank_requested": True, "rerank_applied": True, "rerank_fallback": False,
                "retrieval_latency_ms": 12.3, "rerank_latency_ms": 45.6,
                "total_latency_ms": 57.9,
            },
        })
        self.assertEqual(response.sources[0].chunk_id, 63)
        self.assertTrue(response.retrieval.rerank_applied)


class RerankerTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "DASHSCOPE_API_KEY": "test-only", "DASHSCOPE_RERANK_API_KEY": "",
            "DASHSCOPE_RERANK_URL": "https://example.test/reranks",
            "DASHSCOPE_RERANK_MODEL": "qwen3-rerank", "DASHSCOPE_RERANK_TIMEOUT": "2",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client_patch = patch("app.services.reranker._client")
        self.client = self.client_patch.start().return_value
        self.addCleanup(self.client_patch.stop)

    def response(self, rows):
        self.client.post.return_value = httpx.Response(
            200, json={"results": rows}, request=httpx.Request("POST", "https://example.test"))

    def test_maps_position_to_original_chunk_and_preserves_similarity(self):
        original = candidates()
        self.response([{"index": 2, "relevance_score": 0.98},
                       {"index": 0, "relevance_score": 0.2}])
        result = rerank_chunks("question", original, top_n=2)
        self.assertEqual([row["chunk"].id for row in result], [63, 41])
        self.assertIs(result[0]["chunk"], original[2]["chunk"])
        self.assertEqual(result[0]["similarity"], original[2]["similarity"])
        self.assertNotIn("rerank_score", original[2])
        request = self.client.post.call_args.kwargs["json"]
        self.assertEqual(request["documents"], [row["chunk"].content for row in original])
        self.assertEqual(request["top_n"], 2)
        self.assertNotIn("input", request)

    def test_empty_candidates_skip_model(self):
        self.assertEqual(rerank_chunks("q", []), [])
        self.client.post.assert_not_called()

    def test_invalid_partial_duplicate_scores_and_indices_fail(self):
        for rows in ([], [{"index": 0, "relevance_score": 0.5}],
                     [{"index": 0, "relevance_score": 0.5}] * 3,
                     [{"index": i, "relevance_score": 0.5} for i in (0, 1, 99)],
                     [{"index": i, "relevance_score": "0.5"} for i in range(3)]):
            with self.subTest(rows=rows):
                self.response(rows)
                with self.assertRaises(RerankError):
                    rerank_chunks("q", candidates())

    def test_timeout_and_http_errors_do_not_expose_provider_body(self):
        self.client.post.side_effect = httpx.ReadTimeout("private body")
        with self.assertRaisesRegex(RerankError, "超时"):
            rerank_chunks("q", candidates())
        self.client.post.side_effect = None
        self.client.post.return_value = httpx.Response(403, text="private body",
            request=httpx.Request("POST", "https://example.test"))
        with self.assertRaisesRegex(RerankError, "HTTP 403") as caught:
            rerank_chunks("q", candidates())
        self.assertNotIn("private body", str(caught.exception))

    def test_workspace_endpoint_derivation_and_other_host_rejected(self):
        with patch.dict(os.environ, {"DASHSCOPE_RERANK_URL": "",
                "DASHSCOPE_EMBEDDING_BASE_URL": "https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"}):
            self.assertEqual(rerank_url(), "https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-api/v1/reranks")
        with patch.dict(os.environ, {"DASHSCOPE_RERANK_URL": "", "DASHSCOPE_EMBEDDING_BASE_URL": "https://elsewhere.test/v1"}):
            with self.assertRaises(RerankError):
                rerank_url()


class RagIntegrationTest(unittest.TestCase):
    def setUp(self):
        # The existing module creates the answer client on import, but never calls it here.
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}):
            from app.services import rag
        self.rag = rag
        self.search = patch.object(rag, "search_similar_chunks", return_value=candidates()).start()
        self.rank = patch.object(rag, "rerank_chunks", return_value=[candidates()[2]]).start()
        self.answer = patch.object(rag, "_call_llm", return_value="answer").start()
        self.addCleanup(patch.stopall)

    def test_rag_uses_reranked_context_and_keeps_material_topic_filters(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=81, name="State")
        with patch.dict(os.environ, {"RAG_RERANK_ENABLED": "true"}), \
                patch.object(self.rag, "topic_context_chunks", return_value=candidates() * 3):
            result = self.rag.rag_answer("q", 24, db, topic_id=81)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["context_source"], "retrieval")
        self.assertEqual(result["sources"][0]["chunk_id"], 63)
        self.assertEqual(result["sources"][0]["excerpt"], "passage 63")
        self.assertEqual(result["retrieval"]["candidate_count"], 3)
        self.assertEqual(result["retrieval"]["source_count"], 1)
        self.assertTrue(result["retrieval"]["rerank_requested"])
        self.assertTrue(result["retrieval"]["rerank_applied"])
        self.assertFalse(result["retrieval"]["rerank_fallback"])
        self.assertEqual(self.search.call_args.kwargs["top_k"], 10)
        self.assertEqual(self.search.call_args.kwargs["topic_id"], 81)
        self.assertEqual(self.search.call_args.kwargs["material_id"], 24)
        self.assertEqual(self.search.call_args.kwargs["query"], "State\nq")
        self.assertEqual(self.answer.call_args.args[0], "passage 63")
        self.assertIn("「State」", self.answer.call_args.args[1])
        self.assertTrue(self.answer.call_args.args[1].endswith("q"))

    def test_rag_failure_falls_back_but_records_warning(self):
        self.rank.side_effect = RerankError("timeout")
        with patch.dict(os.environ, {"RAG_RERANK_ENABLED": "true"}), self.assertLogs(self.rag.logger, level="WARNING"):
            result = self.rag.rag_answer("q", 24, Mock(), top_k=2)
        self.answer.assert_called_once_with("passage 41\n\npassage 52", "q")
        self.assertEqual([row["chunk_id"] for row in result["sources"]], [41, 52])
        self.assertFalse(result["retrieval"]["rerank_applied"])
        self.assertTrue(result["retrieval"]["rerank_fallback"])

    def test_provider_error_does_not_expose_exception_text(self):
        self.answer.side_effect = RuntimeError("provider body with token")
        with patch.dict(os.environ, {"RAG_RERANK_ENABLED": "false"}):
            result = self.rag.rag_answer("q", 24, Mock())
        self.assertEqual(result["status"], "provider_error")
        self.assertEqual(result["context_source"], "retrieval")
        self.assertNotIn("token", result["answer"])

    def test_disabled_flag_skips_rerank(self):
        with patch.dict(os.environ, {"RAG_RERANK_ENABLED": "false"}):
            result = self.rag.rag_answer("q", 24, Mock())
        self.rank.assert_not_called()
        self.assertEqual(self.search.call_args.kwargs["top_k"], 6)
        self.assertFalse(result["retrieval"]["rerank_requested"])
        self.assertEqual(result["retrieval"]["source_count"], 3)

    def test_source_excerpt_is_normalized_and_bounded(self):
        long_text = "first\n\n" + "x" * 300
        rows = [{"chunk": SimpleNamespace(id=7, chunk_index=2, topic_id=9, content=long_text),
                 "similarity": 0.81234567, "rerank_score": 0.92345678}]
        source = self.rag._source_rows(rows)[0]
        self.assertNotIn("\n", source["excerpt"])
        self.assertLessEqual(len(source["excerpt"]), 241)
        self.assertTrue(source["excerpt"].endswith("…"))
        self.assertEqual(source["topic_id"], 9)
        self.assertEqual(source["similarity"], 0.812346)
        self.assertEqual(source["rerank_score"], 0.923457)


class ComparisonTest(unittest.TestCase):
    def setUp(self):
        self.cases = [{"id": "case", "question": "q", "material_id": 24,
                       "relevant_chunk_ids": [63], "topic_id": None}]

    def test_one_retrieval_same_candidates_and_separate_timings(self):
        retrieve = Mock(return_value=[{"chunk_id": i} for i in (41, 52, 63)])
        report = evaluate_cases(self.cases, retrieve, rerank=lambda case, rows: list(reversed(rows)))
        retrieve.assert_called_once()
        self.assertEqual(report["summary"]["mrr"], 1)
        self.assertEqual(report["baseline"]["summary"]["mrr"], 0.3333)
        self.assertEqual(report["cases"][0]["retrieved_chunk_ids"], [63, 52, 41])
        self.assertEqual(report["baseline"]["cases"][0]["retrieved_chunk_ids"], [41, 52, 63])
        self.assertIn("average_rerank_latency_ms", report["summary"])

    def test_evaluation_errors_never_silently_fallback(self):
        with self.assertRaises(RerankError):
            evaluate_cases(self.cases, lambda _: [{"chunk_id": 63}],
                           rerank=Mock(side_effect=RerankError("provider failed")))
        with self.assertRaisesRegex(ValueError, "同一批候选"):
            evaluate_cases(self.cases, lambda _: [{"chunk_id": 63}], rerank=lambda case, rows: [])

    def test_stale_labels_fail_before_retrieval(self):
        from scripts.evaluate_rag import validate_labels
        db = Mock()
        db.get.return_value = None
        with self.assertRaisesRegex(ValueError, "资料不存在"):
            validate_labels(self.cases, db)


if __name__ == "__main__":
    unittest.main()
