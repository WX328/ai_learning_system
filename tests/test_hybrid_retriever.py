"""Scoped SQL retrieval and hybrid-ranking contracts; no provider calls."""
import json
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.database import Base
from app.models import LearningChunk, LearningMaterial, Topic, User
from app.services import lexical_retriever, retriever


def ids(rows):
    return [row["chunk"].id for row in rows]


class ScopedHybridRetrieverTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.db.add_all([
            User(id=1, username="owner", password_hash="test-only"),
            User(id=2, username="other", password_hash="test-only"),
        ])
        self.db.flush()
        self.db.add_all([
            LearningMaterial(id=10, user_id=1, title="selected", content="material"),
            LearningMaterial(id=20, user_id=2, title="other material", content="material"),
        ])
        self.db.flush()
        self.db.add_all([
            Topic(id=101, material_id=10, name="selected topic", description="topic"),
            Topic(id=102, material_id=10, name="other topic", description="topic"),
            Topic(id=201, material_id=20, name="other material topic", description="topic"),
        ])
        self.db.flush()
        self.embed = patch.object(retriever, "embed_text", return_value=[1.0, 0.0]).start()
        self.addCleanup(patch.stopall)
        # ASCII corpora exercise the real lexical retriever without loading jieba.
        lexical_retriever._build_index.cache_clear()
        self.addCleanup(lexical_retriever._build_index.cache_clear)

    def chunk(self, chunk_id, text, vector=None, material_id=10, topic_id=101):
        row = LearningChunk(
            id=chunk_id, material_id=material_id, topic_id=topic_id,
            chunk_index=chunk_id, content=text,
            embedding=json.dumps(vector) if vector is not None else None,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def search(self, query="max_steps", **kwargs):
        return retriever.search_similar_chunks(query, 10, self.db, **kwargs)

    def test_default_vector_keeps_cosine_order_threshold_and_top_k(self):
        self.chunk(30, "unrelated", [0.6, 0.8])
        self.chunk(20, "unrelated", [10.0, 0.0])
        self.chunk(10, "unrelated", [1.0, 0.0])
        self.chunk(40, "max_steps", [0.0, 1.0])
        self.chunk(50, "max_steps", None)
        self.chunk(60, "max_steps", [1.0, 0.0], material_id=20, topic_id=201)
        results = self.search(top_k=2, similarity_threshold=0.35)
        self.assertEqual(ids(results), [10, 20])
        self.assertEqual([row["similarity"] for row in results], [1.0, 1.0])
        self.assertEqual(results.metadata["retrieval_method"], "vector")
        self.assertEqual(results.metadata["bm25_candidate_count"], 0)
        self.embed.assert_called_once_with("max_steps")
        self.assertEqual(ids(self.search(top_k=10)), [10, 20, 30])

    def test_hybrid_rescues_exact_identifier_below_vector_threshold(self):
        self.chunk(1, "semantic distractor", [1.0, 0.0])
        self.chunk(2, "max_steps stops the loop", [0.0, 1.0])
        self.assertEqual(ids(self.search()), [1])
        results = self.search(method="hybrid", top_k=10)
        by_id = {row["chunk"].id: row for row in results}
        self.assertEqual(set(by_id), {1, 2})
        self.assertEqual(by_id[2]["retrieval_methods"], ["bm25"])
        self.assertEqual(by_id[2]["similarity"], 0.0)
        self.assertGreater(by_id[2]["bm25_score"], 0)
        self.assertEqual(results.metadata["vector_candidate_count"], 1)
        self.assertEqual(results.metadata["bm25_candidate_count"], 1)

    def test_hybrid_rescues_exact_identifier_without_embedding(self):
        self.chunk(1, "semantic distractor", [1.0, 0.0])
        self.chunk(2, "max_steps stops the loop")
        results = self.search(method="hybrid")
        source = next(row for row in results if row["chunk"].id == 2)
        self.assertIsNone(source["similarity"])
        self.assertGreater(source["bm25_score"], 0)
        self.assertEqual(source["retrieval_methods"], ["bm25"])

    def test_material_and_topic_scope_apply_to_both_branches(self):
        self.chunk(1, "max_steps", [1.0, 0.0])
        self.chunk(2, "max_steps", [1.0, 0.0], topic_id=102)
        self.chunk(3, "max_steps", [1.0, 0.0], material_id=20, topic_id=201)
        for method in ("vector", "bm25", "hybrid"):
            with self.subTest(method=method):
                self.assertEqual(ids(self.search(method=method, topic_id=101)), [1])
                self.assertEqual(set(ids(self.search(method=method))), {1, 2})

    def test_bm25_never_calls_embedding_and_keeps_exact_ascii_identifier(self):
        self.chunk(1, "MAX_STEPS limits execution")
        self.chunk(2, "steps execution")
        self.embed.side_effect = AssertionError("BM25 must not contact embedding provider")
        results = self.search(method="bm25")
        self.assertEqual(ids(results), [1])
        self.assertIsNone(results[0]["similarity"])
        self.assertEqual(results.metadata["embedding_latency_ms"], 0.0)
        self.embed.assert_not_called()

    def test_empty_scope_and_blank_query_skip_embedding(self):
        self.chunk(1, "max_steps", [1.0, 0.0])
        for method in ("vector", "bm25", "hybrid"):
            with self.subTest(method=method):
                self.assertEqual(self.search(method=method, topic_id=201), [])
                self.assertEqual(self.search(query=" \t ", method=method), [])
        self.embed.assert_not_called()

    def test_paired_candidates_reuse_one_embedding_and_fixed_budget(self):
        for chunk_id in range(1, 26):
            self.chunk(chunk_id, "max_steps", [1.0, 0.0])
        rankings, timings = retriever.search_candidate_rankings("max_steps", 10, self.db)
        self.embed.assert_called_once_with("max_steps")
        self.assertEqual(set(rankings), {"vector", "bm25", "hybrid"})
        for method, rows in rankings.items():
            with self.subTest(method=method):
                self.assertEqual(len(rows), 10)
                self.assertEqual(ids(rows), list(range(1, 11)))
                self.assertEqual(len(set(ids(rows))), len(rows))
        self.assertEqual(set(timings), {"db_latency_ms", "embedding_latency_ms",
            "vector_latency_ms", "bm25_latency_ms", "fusion_latency_ms"})
        self.assertTrue(all(value >= 0 and math.isfinite(value) for value in timings.values()))

    def test_bad_vector_json_dimensions_and_nonfinite_values_never_leak_scores(self):
        self.chunk(1, "max_steps valid", [1.0, 0.0])
        for chunk_id, embedding in enumerate(("{broken", "[1, 0, 0]", "[NaN, 0]",
                                               "[Infinity, 0]", "null", "{\"x\": 1}"), 2):
            row = self.chunk(chunk_id, "max_steps corrupted")
            row.embedding = embedding
        self.db.flush()
        self.assertEqual(ids(self.search(top_k=10)), [1])
        hybrid = self.search(method="hybrid", top_k=10)
        self.assertEqual(set(ids(hybrid)), set(range(1, 8)))
        for result in hybrid:
            for key in ("similarity", "bm25_score", "rrf_score"):
                if result.get(key) is not None:
                    self.assertTrue(math.isfinite(result[key]), (result["chunk"].id, key))
            if result["chunk"].id != 1:
                self.assertIsNone(result["similarity"])
        # Starlette's JSONResponse also rejects NaN; enforce that public rows can serialize.
        json.dumps([{key: value for key, value in row.items() if key != "chunk"}
                    for row in hybrid], allow_nan=False)

    def test_overflowing_finite_vector_cannot_produce_nan_source_similarity(self):
        self.embed.return_value = [0.5, 0.5, 0.5, 0.5]
        self.chunk(1, "max_steps overflow", [1e308, 1e308, 1e308, 1e308])
        rows = self.search(method="hybrid")
        self.assertEqual(ids(rows), [1])
        value = rows[0].get("similarity")
        self.assertTrue(value is None or math.isfinite(value), value)
        json.dumps([{key: value for key, value in row.items() if key != "chunk"}
                    for row in rows], allow_nan=False)


class ReciprocalRankFusionTest(unittest.TestCase):
    def row(self, chunk_id, **scores):
        return {"chunk": SimpleNamespace(id=chunk_id), **scores}

    def test_rank_formula_uses_each_branch_rank_and_keeps_raw_scores_separate(self):
        vector = [self.row(9, similarity=0.01), self.row(3, similarity=0.99)]
        lexical = [self.row(3, bm25_score=0.001), self.row(7, bm25_score=1e6)]
        result = retriever.fuse_rankings(vector, lexical, top_k=10, rrf_k=60)
        self.assertEqual(ids(result), [3, 9, 7])
        by_id = {row["chunk"].id: row for row in result}
        self.assertAlmostEqual(by_id[3]["rrf_score"], 1 / 62 + 1 / 61)
        self.assertAlmostEqual(by_id[9]["rrf_score"], 1 / 61)
        self.assertAlmostEqual(by_id[7]["rrf_score"], 1 / 62)
        self.assertEqual(by_id[3]["retrieval_methods"], ["vector", "bm25"])
        self.assertEqual(by_id[3]["similarity"], 0.99)
        self.assertEqual(by_id[3]["bm25_score"], 0.001)

    def test_duplicate_hits_have_one_contribution_per_branch(self):
        vector = [self.row(1, similarity=0.9), self.row(1, similarity=0.8),
                  self.row(2, similarity=0.7)]
        lexical = [self.row(1, bm25_score=4), self.row(1, bm25_score=3),
                   self.row(2, bm25_score=2)]
        result = retriever.fuse_rankings(vector, lexical, top_k=10, rrf_k=60)
        self.assertEqual(ids(result), [1, 2])
        self.assertAlmostEqual(result[0]["rrf_score"], 2 / 61)
        self.assertAlmostEqual(result[1]["rrf_score"], 2 / 62)
        self.assertEqual(result[0]["retrieval_methods"], ["vector", "bm25"])

    def test_ties_are_deterministic_by_chunk_id_and_top_k_is_global_budget(self):
        vector = [self.row(8, similarity=1), self.row(10, similarity=0.9)]
        lexical = [self.row(2, bm25_score=1), self.row(4, bm25_score=0.9)]
        self.assertEqual(ids(retriever.fuse_rankings(vector, lexical, top_k=3)), [2, 8, 4])
        self.assertEqual(ids(retriever.fuse_rankings(vector, lexical, top_k=1)), [2])
        self.assertEqual(ids(retriever.fuse_rankings([], lexical, top_k=1)), [2])


if __name__ == "__main__":
    unittest.main()
