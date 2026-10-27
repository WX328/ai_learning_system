"""Hybrid retrieval through RAG and the public response schema, offline only."""
import json
import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import LearningChunk, LearningMaterial, Topic, User
from app.schemas.rag import RAGAskResponse
from app.services import lexical_retriever, rag, retriever


class HybridRagIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.db.add(User(id=1, username="owner", password_hash="test-only"))
        self.db.flush()
        self.db.add(LearningMaterial(id=10, user_id=1, title="selected",
                                     content="Entire material fallback text."))
        self.db.flush()
        self.db.add_all([
            Topic(id=101, material_id=10, name="selected topic", description="scope"),
            Topic(id=102, material_id=10, name="other topic", description="scope"),
        ])
        self.db.flush()
        self.env = patch.dict(os.environ, {"RAG_RETRIEVAL_METHOD": "hybrid",
            "RAG_RRF_K": "27", "RAG_RERANK_ENABLED": "true"})
        self.env.start()
        self.embed = patch.object(retriever, "embed_text", return_value=[1.0, 0.0]).start()
        self.answer = patch.object(rag, "_call_llm", return_value="grounded answer").start()
        self.search = patch.object(rag, "search_similar_chunks",
                                   wraps=retriever.search_similar_chunks).start()
        self.rank = patch.object(rag, "rerank_chunks").start()
        self.addCleanup(patch.stopall)
        lexical_retriever._build_index.cache_clear()
        self.addCleanup(lexical_retriever._build_index.cache_clear)

    def chunk(self, chunk_id, content, embedding=None, topic_id=101):
        self.db.add(LearningChunk(id=chunk_id, material_id=10, topic_id=topic_id,
            chunk_index=chunk_id, content=content,
            embedding=json.dumps(embedding) if embedding is not None else None))
        self.db.flush()

    def validate_response(self, result, question="max_steps"):
        model = RAGAskResponse.model_validate({"history_id": None,
            "question": question, **result})
        payload = model.model_dump(mode="json")
        # Match strict HTTP JSON serialization, not permissive Python NaN output.
        json.dumps(payload, allow_nan=False)
        self.assertEqual(json.loads(model.model_dump_json()), payload)
        return payload

    def test_hybrid_scoped_call_metadata_nullable_scores_and_rerank_survive_schema(self):
        self.chunk(1, "semantic explanation", [1.0, 0.0])
        self.chunk(2, "max_steps limits execution")
        for index in range(3, 8):
            self.chunk(index, f"additional detail {index}", [0.0, 1.0])

        def rerank(query, candidates, top_n=None):
            self.assertEqual(query, "selected topic\nmax_steps")
            return [{**row, "rerank_score": 0.95 - index / 10}
                    for index, row in enumerate(reversed(candidates))][:top_n]

        self.rank.side_effect = rerank
        result = rag.rag_answer("max_steps", 10, self.db, topic_id=101)
        self.assertEqual(self.search.call_args.kwargs["method"], "hybrid")
        self.assertEqual(self.search.call_args.kwargs["rrf_k"], 27)
        self.assertEqual(self.search.call_args.kwargs["material_id"], 10)
        self.assertEqual(self.search.call_args.kwargs["topic_id"], 101)
        self.assertEqual(self.search.call_args.kwargs["top_k"], 10)
        self.embed.assert_called_once_with("selected topic\nmax_steps")
        self.rank.assert_called_once()
        self.assertEqual(self.answer.call_args.args[0], "max_steps limits execution\n\nsemantic explanation")
        self.assertIn("「selected topic」", self.answer.call_args.args[1])
        self.assertTrue(self.answer.call_args.args[1].endswith("max_steps"))
        payload = self.validate_response(result)
        self.assertEqual(payload["status"], "answered")
        self.assertEqual(payload["context_source"], "retrieval")
        self.assertEqual([row["chunk_id"] for row in payload["sources"]], [2, 1])
        lexical_source, vector_source = payload["sources"]
        self.assertIsNone(lexical_source["similarity"])
        self.assertGreater(lexical_source["bm25_score"], 0)
        self.assertEqual(lexical_source["retrieval_methods"], ["bm25"])
        self.assertEqual(lexical_source["rerank_score"], 0.95)
        self.assertAlmostEqual(lexical_source["rrf_score"], round(1 / 28, 6))
        self.assertEqual(vector_source["similarity"], 1.0)
        self.assertIsNone(vector_source["bm25_score"])
        self.assertEqual(vector_source["retrieval_methods"], ["vector"])
        meta = payload["retrieval"]
        self.assertEqual(meta["retrieval_method"], "hybrid")
        self.assertEqual(meta["vector_candidate_count"], 1)
        self.assertEqual(meta["bm25_candidate_count"], 1)
        self.assertEqual(meta["candidate_count"], 2)
        self.assertEqual(meta["source_count"], 2)
        self.assertTrue(meta["rerank_applied"])
        self.assertFalse(meta["rerank_fallback"])
        for field in ("db_latency_ms", "embedding_latency_ms", "vector_latency_ms",
                      "bm25_latency_ms", "fusion_latency_ms", "retrieval_latency_ms",
                      "rerank_latency_ms", "total_latency_ms"):
            self.assertGreaterEqual(meta[field], 0, field)

    def test_known_topic_sources_remain_available_without_using_other_topic_or_whole_material(self):
        self.chunk(1, "unrelated topic content", [0.0, 1.0], topic_id=101)
        self.chunk(2, "max_steps related outside scope", [1.0, 0.0], topic_id=102)
        result = rag.rag_answer("max_steps", 10, self.db, topic_id=101)
        payload = self.validate_response(result)
        self.assertEqual(payload["status"], "answered")
        self.assertEqual(payload["context_source"], "retrieval")
        self.assertEqual([source["chunk_id"] for source in payload["sources"]], [1])
        self.assertEqual(payload["retrieval"]["retrieval_method"], "topic")
        self.assertFalse(payload["retrieval"]["rerank_applied"])
        self.assertEqual(self.answer.call_args.args[0], "unrelated topic content")
        self.assertIn("明显超出当前知识点", self.answer.call_args.args[1])
        self.embed.assert_not_called()
        self.rank.assert_not_called()

    def test_empty_topic_scope_skips_all_model_calls_and_accepts_no_context_schema(self):
        self.chunk(1, "max_steps outside scope", [1.0, 0.0], topic_id=102)
        result = rag.rag_answer("max_steps", 10, self.db, topic_id=101)
        self.assertEqual(self.validate_response(result)["status"], "no_context")
        self.embed.assert_not_called()
        self.answer.assert_not_called()
        self.rank.assert_not_called()

    def test_bm25_match_answers_from_unembedded_chunk_without_any_embedding_call(self):
        self.chunk(1, "max_steps limits execution")
        self.embed.side_effect = AssertionError("Pure BM25 must not call embedding")
        with patch.dict(os.environ, {"RAG_RETRIEVAL_METHOD": "bm25",
                                     "RAG_RERANK_ENABLED": "false"}):
            result = rag.rag_answer("max_steps", 10, self.db)
        payload = self.validate_response(result)
        self.assertEqual(payload["status"], "answered")
        self.assertEqual(payload["context_source"], "retrieval")
        self.assertEqual(payload["retrieval"]["retrieval_method"], "bm25")
        self.assertEqual(payload["retrieval"]["vector_candidate_count"], 0)
        self.assertEqual(payload["retrieval"]["bm25_candidate_count"], 1)
        self.assertIsNone(payload["sources"][0]["similarity"])
        self.assertIsNone(payload["sources"][0]["rrf_score"])
        self.assertEqual(payload["sources"][0]["retrieval_methods"], ["bm25"])
        self.answer.assert_called_once_with("max_steps limits execution", "max_steps")
        self.embed.assert_not_called()
        self.rank.assert_not_called()

    def test_bm25_miss_does_not_misreport_missing_vectors(self):
        self.chunk(1, "unmatched text without any embedding")
        with patch.dict(os.environ, {"RAG_RETRIEVAL_METHOD": "bm25",
                                     "RAG_RERANK_ENABLED": "false"}):
            result = rag.rag_answer("max_steps", 10, self.db)
        payload = self.validate_response(result)
        self.assertEqual(payload["status"], "answered")
        self.assertEqual(payload["context_source"], "document_fallback")
        self.assertNotIn("重建向量", payload["answer"])
        self.assertEqual(payload["sources"], [])
        self.answer.assert_called_once_with("Entire material fallback text.", "max_steps")
        self.embed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
