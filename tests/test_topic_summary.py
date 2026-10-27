"""Regressions for short documents with more topics than indexed chunks; offline."""
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import LearningChunk, LearningMaterial, Topic, User
from app.schemas.rag import RAGAskResponse
from app.services import rag, retriever
from app.services.embedding import EmbeddingError
from app.services.chunker import split_text
from app.services.topic_scope import markdown_sections, mentions_topic


class TopicSummaryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.db.add_all([User(id=1, username="owner", password_hash="test"),
                         User(id=2, username="other", password_hash="test")])
        self.db.flush()
        self.parts = [
            "# React\nReact is a UI library built with components.\n"
            "## State\nState stores mutable component data with useState.\n"
            "## Props\nProps pass read-only data from parent to child.\n"
            "## useEffect\nuseEffect synchronizes a component with external systems.",
            "## TypeScript\nTypeScript describes static types.\n"
            "## Ant Design\nAnt Design provides reusable UI components.",
        ]
        self.db.add_all([
            LearningMaterial(id=10, user_id=1, title="React notes", content="\n".join(self.parts)),
            LearningMaterial(id=20, user_id=2, title="Private notes", content="PRIVATE OTHER MATERIAL"),
        ])
        self.db.flush()
        self.names = ["React", "State", "Props", "useEffect", "TypeScript", "Ant Design"]
        self.db.add_all([Topic(id=101 + i, material_id=10, name=name, description=name)
                         for i, name in enumerate(self.names)])
        self.db.add_all([
            Topic(id=107, material_id=10, name="Absent concept", description="no source"),
            Topic(id=201, material_id=20, name="State", description="other owner"),
        ])
        self.db.flush()
        self.db.add_all([
            LearningChunk(id=1, material_id=10, topic_id=101, chunk_index=0,
                          content=self.parts[0], embedding=json.dumps([0, 1])),
            LearningChunk(id=2, material_id=10, topic_id=105, chunk_index=1,
                          content=self.parts[1], embedding=None),
            LearningChunk(id=3, material_id=20, topic_id=201, chunk_index=0,
                          content="## State\nPRIVATE OTHER MATERIAL", embedding=json.dumps([1, 0])),
        ])
        self.db.commit()
        self.embed = patch.object(retriever, "embed_text", return_value=[1, 0]).start()
        self.answer = patch.object(rag, "_call_llm", return_value="Grounded topic summary").start()
        self.rank = patch.object(rag, "rerank_chunks").start()
        self.addCleanup(patch.stopall)

    def test_generic_summary_works_for_all_six_topics_in_two_legacy_chunks(self):
        with patch.dict("os.environ", {"RAG_RETRIEVAL_METHOD": "vector", "RAG_RERANK_ENABLED": "true"}):
            for index, name in enumerate(self.names):
                with self.subTest(topic=name):
                    result = rag.rag_answer("请总结这份资料的核心知识点。", 10, self.db, topic_id=101 + index)
                    payload = RAGAskResponse.model_validate({"history_id": None, "question": "summary", **result})
                    self.assertEqual(payload.status, "answered")
                    self.assertEqual(payload.retrieval.retrieval_method, "topic")
                    self.assertTrue(payload.sources)
                    self.assertTrue(all(source.chunk_id in {1, 2} for source in payload.sources))
                    context, question = self.answer.call_args.args
                    self.assertIn(name, context)
                    self.assertIn("「" + name + "」", question)
                    self.assertNotIn("PRIVATE OTHER MATERIAL", context)
        self.embed.assert_not_called()
        self.rank.assert_not_called()
        self.assertEqual(self.db.get(LearningChunk, 1).topic_id, 101, "Reading must not rewrite old links")

    def test_summary_uses_only_matching_section_and_keeps_real_source_id(self):
        result = rag.rag_answer("总结 State", 10, self.db, topic_id=102)
        source = result["sources"][0]
        self.assertEqual(source["chunk_id"], 1)
        self.assertIsNone(source["similarity"])
        self.assertEqual(source["retrieval_methods"], ["topic"])
        context = self.answer.call_args.args[0]
        self.assertIn("mutable component data", context)
        self.assertNotIn("read-only data", context)
        self.assertNotIn("external systems", context)
        self.assertNotIn("Props", source["excerpt"])

    def test_every_topic_accepts_examples_beginner_questions_and_arbitrary_wording(self):
        questions = [
            "请用一个生活中的例子解释知识点「{name}」。",
            "不知道这个知识点", "这个怎么理解？", "能给个代码示例吗？",
            "它和之前的概念有什么关系？", "explain this to a beginner",
        ]
        for method in ("vector", "bm25", "hybrid"):
            with patch.dict("os.environ", {"RAG_RETRIEVAL_METHOD": method, "RAG_RERANK_ENABLED": "true"}):
                for index, name in enumerate(self.names):
                    for template in questions:
                        query = template.format(name=name)
                        with self.subTest(method=method, topic=name, query=query):
                            result = rag.rag_answer(query, 10, self.db, topic_id=101 + index)
                            self.assertEqual(result["status"], "answered")
                            self.assertEqual(result["retrieval"]["retrieval_method"], "topic")
                            self.assertFalse(result["retrieval"]["rerank_requested"])
                            context, question = self.answer.call_args.args
                            self.assertIn(name, context)
                            self.assertIn("「" + name + "」", question)
                            self.assertTrue(question.endswith(query), "Keep the user's original question")
                            self.assertNotIn("PRIVATE OTHER MATERIAL", context)
        self.embed.assert_not_called()
        self.rank.assert_not_called()

    def long_state_topic(self):
        for index in range(7):
            self.db.add(LearningChunk(id=10 + index, material_id=10, topic_id=102,
                                     chunk_index=index + 2,
                                     content=f"## State\nState detail {index}.",
                                     embedding=json.dumps([0, 1])))
        self.db.flush()

    def test_large_topic_ranks_specific_question_with_the_selected_topic_in_query(self):
        self.long_state_topic()
        self.db.get(LearningChunk, 16).embedding = json.dumps([1, 0])
        self.db.get(LearningChunk, 16).content = "## State\nDetailed answer at the end of a long topic."
        self.rank.side_effect = lambda query, candidates, top_n: candidates[:top_n]
        with patch.dict("os.environ", {"RAG_RETRIEVAL_METHOD": "vector", "RAG_RERANK_ENABLED": "true"}):
            result = rag.rag_answer("解释最后的细节", 10, self.db, topic_id=102)
        self.assertEqual(result["status"], "answered")
        self.assertEqual([source["chunk_id"] for source in result["sources"]], [16])
        self.embed.assert_called_once_with("State\n解释最后的细节")
        self.assertEqual(self.rank.call_args.args[0], "State\n解释最后的细节")
        self.assertIn("Detailed answer at the end", self.answer.call_args.args[0])
        self.assertIn("「State」", self.answer.call_args.args[1])

    def test_large_topic_semantic_miss_and_embedding_failure_use_known_topic_sources(self):
        self.long_state_topic()
        for failure in (None, EmbeddingError("provider unavailable")):
            with self.subTest(failure=failure):
                self.embed.side_effect = failure
                with patch.dict("os.environ", {"RAG_RETRIEVAL_METHOD": "vector", "RAG_RERANK_ENABLED": "true"}):
                    result = rag.rag_answer("不知道这个知识点", 10, self.db, topic_id=102)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(result["retrieval"]["retrieval_method"], "topic")
                self.assertEqual(len(result["sources"]), 6)
                self.assertFalse(result["retrieval"]["rerank_requested"])
                context = self.answer.call_args.args[0]
                self.assertNotIn("Props", context)
                self.assertNotIn("PRIVATE OTHER MATERIAL", context)
        self.rank.assert_not_called()

    def test_unembedded_known_topic_and_missing_context_are_distinguished_for_any_question(self):
        self.db.get(LearningChunk, 1).embedding = None
        result = rag.rag_answer("不知道这个知识点", 10, self.db, topic_id=104)
        self.assertEqual(result["status"], "answered")
        self.assertIn("external systems", self.answer.call_args.args[0])
        self.answer.reset_mock()
        result = rag.rag_answer("请举一个生活例子", 10, self.db, topic_id=107)
        self.assertEqual(result["status"], "no_context")
        self.answer.assert_not_called()
        self.embed.assert_not_called()

    def test_topic_prompt_allows_labeled_examples_without_inventing_document_facts(self):
        rag.rag_answer("举一个生活例子", 10, self.db, topic_id=103)
        prompt = rag._build_prompt(*self.answer.call_args.args)
        self.assertIn("「Props」", prompt)
        self.assertIn("生活类比", prompt)
        self.assertIn("不要声称示例来自原文", prompt)
        self.assertIn("不知道", prompt)
        self.assertIn("明显超出当前知识点", prompt)

    def test_model_assigned_source_without_literal_topic_name_remains_available(self):
        self.db.get(LearningChunk, 1).content = "A component retains data between renders."
        result = rag.rag_answer("总结 React", 10, self.db, topic_id=101)
        self.assertEqual(result["status"], "answered")
        self.assertIn("retains data", self.answer.call_args.args[0])

    def test_missing_topic_context_does_not_silently_use_whole_document(self):
        result = rag.rag_answer("总结这个知识点", 10, self.db, topic_id=107)
        self.assertEqual(result["status"], "no_context")
        self.assertEqual(result["sources"], [])
        self.answer.assert_not_called()
        self.embed.assert_not_called()

    def test_wrong_material_topic_cannot_expand_scope(self):
        self.assertEqual(retriever.topic_summary_chunks(10, 201, self.db), [])
        self.assertEqual(retriever.search_similar_chunks("State", 10, self.db, topic_id=201), [])
        self.embed.assert_not_called()

    def test_ordinary_bm25_question_can_find_an_unassigned_topic_in_shared_chunk(self):
        rows = retriever.search_similar_chunks("mutable", 10, self.db, topic_id=102, method="bm25")
        self.assertEqual([row["chunk"].id for row in rows], [1])
        self.assertNotIn("Props", rows[0]["content"])
        self.assertEqual(retriever.search_similar_chunks("read-only", 10, self.db, topic_id=102, method="bm25"), [])
        self.embed.assert_not_called()

    def test_ordinary_vector_question_keeps_similarity_threshold(self):
        rows = retriever.search_similar_chunks("What is State?", 10, self.db, topic_id=102)
        self.assertEqual(rows, [])
        self.embed.assert_called_once()


class SectionChunkingTest(unittest.TestCase):
    def test_short_peer_sections_remain_separate(self):
        text = "# React notes\n## React\nA component library.\n## State\nMutable data.\n## Props\nRead-only inputs."
        chunks = split_text(text)
        self.assertEqual(len(chunks), 3)
        self.assertIn("# React notes", chunks[0])
        self.assertIn("## State", chunks[1])
        self.assertNotIn("Props", chunks[1])
        self.assertIn("## Props", chunks[2])

    def test_code_comment_does_not_start_a_new_section(self):
        text = "## Hooks\n```python\n# A code comment\nprint('ok')\n```\n## State\nData."
        sections = markdown_sections(text)
        self.assertEqual(len(sections), 2)
        self.assertIn("# A code comment", sections[0])
        self.assertIn("```", split_text(text)[0])

    def test_topic_identifiers_do_not_match_inside_other_identifiers(self):
        self.assertTrue(mentions_topic("## State\ncomponent data", "State"))
        self.assertFalse(mentions_topic("useState Statement state_machine", "State"))
        self.assertFalse(mentions_topic("Reactive", "React"))
        self.assertTrue(mentions_topic("Depends(get_db)", "Depends"))

    def test_plain_text_and_heading_only_documents_are_not_lost(self):
        self.assertEqual(split_text("A paragraph.\n\nAnother paragraph."), ["A paragraph.\nAnother paragraph."])
        self.assertEqual(split_text("# Only a heading"), ["# Only a heading"])
        self.assertEqual(split_text(""), [])


if __name__ == "__main__":
    unittest.main()
