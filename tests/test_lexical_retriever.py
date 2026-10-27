"""Local lexical retrieval tests; no embedding or provider APIs are used."""
from math import log1p
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.services import lexical_retriever as lexical


def chunk(chunk_id, content):
    return SimpleNamespace(id=chunk_id, content=content)


class TokenizeTest(unittest.TestCase):
    def test_preserves_complete_ascii_identifiers_and_casefolds(self):
        self.assertEqual(
            lexical.tokenize("MAX_STEPS app.main FastAPI-v2 404 v2.1.0，！"),
            ["max_steps", "app.main", "fastapi-v2", "404", "v2.1.0"],
        )

    def test_chinese_search_mode_and_mixed_english(self):
        tokens = lexical.tokenize("RAG检索增强生成，中华人民共和国")
        self.assertIn("rag", tokens)
        self.assertIn("检索", tokens)
        self.assertIn("生成", tokens)
        self.assertIn("中华", tokens)
        self.assertIn("共和国", tokens)
        self.assertNotIn("，", tokens)

    def test_empty_and_punctuation_only_text(self):
        for text in ("", " \t\n", "，。：；！？()[] / + - ."):
            self.assertEqual(lexical.tokenize(text), [])


class BM25Test(unittest.TestCase):
    def setUp(self):
        lexical._build_index.cache_clear()
        self.addCleanup(lexical._build_index.cache_clear)

    def test_exact_identifier_is_not_a_partial_match(self):
        chunks = [chunk(1, "max_steps 控制 Agent 终止条件"),
                  chunk(2, "steps 是运行步骤"), chunk(3, "max_steps_extra")]
        result = lexical.search_bm25_chunks("MAX_STEPS", chunks)
        self.assertEqual([row["chunk"].id for row in result], [1])
        self.assertIs(result[0]["chunk"], chunks[0])
        self.assertGreater(result[0]["bm25_score"], 0)

    def test_chinese_question_matches_keyword(self):
        chunks = [chunk(1, "混合检索融合向量召回和关键词检索"),
                  chunk(2, "成就奖励用于学习等级系统")]
        self.assertEqual(lexical.search_bm25_chunks("检索", chunks)[0]["chunk"].id, 1)

    def test_no_match_empty_corpus_or_blank_documents(self):
        for chunks in ([], [chunk(1, "")], [chunk(1, "奖励")]):
            self.assertEqual(lexical.search_bm25_chunks("max_steps", chunks), [])
        self.assertEqual(lexical.search_bm25_chunks("", [chunk(1, "text")]), [])
        self.assertEqual(lexical.search_bm25_chunks("text", [chunk(1, "text")], top_k=0), [])

    def test_single_chunk_common_term_still_has_positive_score(self):
        result = lexical.search_bm25_chunks("rag", [chunk(1, "rag rag rag")])
        self.assertEqual(len(result), 1)
        self.assertGreater(result[0]["bm25_score"], 0)

    def test_known_bm25_formula_including_empty_document(self):
        chunks = [chunk(1, "alpha alpha beta"), chunk(2, "beta"), chunk(3, "")]
        result = lexical.search_bm25_chunks("alpha", chunks)
        average_length = 4 / 3
        expected_idf = log1p((3 - 1 + 0.5) / (1 + 0.5))
        expected = expected_idf * (2 * 2.5) / (2 + 1.5 * (0.25 + 0.75 * 3 / average_length))
        self.assertAlmostEqual(result[0]["bm25_score"], expected)

    def test_ties_sort_by_id_and_top_k_limits_result(self):
        chunks = [chunk(8, "same"), chunk(3, "same"), chunk(5, "same")]
        result = lexical.search_bm25_chunks("same", chunks, top_k=2)
        self.assertEqual([row["chunk"].id for row in result], [3, 5])

    def test_warm_cache_does_not_retokenize_corpus_and_uses_current_objects(self):
        originals = [chunk(1, "alpha beta"), chunk(2, "beta")]
        with patch.object(lexical, "tokenize", wraps=lexical.tokenize) as tokenize:
            lexical.search_bm25_chunks("alpha", originals)
            self.assertEqual(tokenize.call_count, 3)
            replacement_objects = [chunk(2, "beta"), chunk(1, "alpha beta")]
            result = lexical.search_bm25_chunks("alpha", replacement_objects)
            self.assertEqual(tokenize.call_count, 4)
        self.assertIs(result[0]["chunk"], replacement_objects[1])
        self.assertEqual(lexical._build_index.cache_info().hits, 1)

    def test_content_edits_uploads_and_deletions_invalidate_scope_index(self):
        first = chunk(1, "alpha")
        second = chunk(2, "beta")
        lexical.search_bm25_chunks("alpha", [first, second])
        first.content = "gamma"
        self.assertEqual(lexical.search_bm25_chunks("alpha", [first, second]), [])
        added = chunk(3, "alpha")
        self.assertEqual(lexical.search_bm25_chunks("alpha", [first, second, added])[0]["chunk"].id, 3)
        self.assertEqual(lexical.search_bm25_chunks("alpha", [first, second]), [])
        self.assertEqual(lexical.search_bm25_chunks("beta", [first]), [])
        self.assertEqual(lexical._build_index.cache_info().misses, 4)

    def test_index_cache_is_bounded(self):
        for i in range(40):
            lexical.search_bm25_chunks("alpha", [chunk(i, "alpha")])
        self.assertEqual(lexical._build_index.cache_info().currsize, 32)


if __name__ == "__main__":
    unittest.main()
