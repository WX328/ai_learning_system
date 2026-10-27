"""Tests for safe, batched Bailian reindexing; no API key or network is used."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user
from app.database import Base, get_db
from app.models import (
    LearningChunk,
    LearningMaterial,
    LearningRecord,
    QAHistory,
    Question,
    QuestionAttempt,
    ReviewAttempt,
    Topic,
    TopicMastery,
    User,
)
from app.routers.learning_material import router
from app.services.chunker import split_text, split_text_legacy
from app.services.embedding import EmbeddingError, embed_texts, embedding_client


class FakeEmbeddings:
    def __init__(self):
        self.batches = []

    def create(self, **kwargs):
        self.batches.append(kwargs["input"])
        return SimpleNamespace(data=[SimpleNamespace(index=index, embedding=[index + 1.0] * 4)
                                    for index, _ in reversed(list(enumerate(kwargs["input"])))])


class FakeClient:
    def __init__(self):
        self.embeddings = FakeEmbeddings()


class EmbeddingBatchTest(unittest.TestCase):
    def setUp(self):
        embedding_client.cache_clear()

    def tearDown(self):
        embedding_client.cache_clear()

    @patch("app.services.embedding.embedding_dimensions", return_value=4)
    @patch("app.services.embedding.embedding_client")
    def test_batches_ten_inputs_and_restores_response_order(self, client, dimensions):
        fake = FakeClient()
        client.return_value = fake
        vectors = embed_texts([f"text {index}" for index in range(21)])
        self.assertEqual([len(batch) for batch in fake.embeddings.batches], [10, 10, 1])
        self.assertEqual(len(vectors), 21)
        self.assertTrue(all(len(vector) == 4 for vector in vectors))
        self.assertTrue(all(abs(sum(value * value for value in vector) - 1) < 1e-10 for vector in vectors))

    def test_rejects_blank_text_without_a_provider_call(self):
        with self.assertRaises(EmbeddingError):
            embed_texts(["valid", "   "])


class ReindexEndpointTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(username="owner", password_hash="unused")
        self.other = User(username="other", password_hash="unused")
        self.db.add_all([self.user, self.other]); self.db.flush()
        self.material = LearningMaterial(user_id=self.user.id, title="Notes", content="first\nsecond")
        self.other_material = LearningMaterial(user_id=self.other.id, title="Private", content="private")
        self.db.add_all([self.material, self.other_material]); self.db.flush()
        self.topic = Topic(material_id=self.material.id, name="Topic", description="Description")
        self.db.add(self.topic); self.db.flush()
        for index, content in enumerate(split_text(self.material.content)):
            self.db.add(LearningChunk(material_id=self.material.id, chunk_index=index, content=content,
                                      embedding=json.dumps([0.1] * 512), topic_id=self.topic.id))
        self.db.commit()
        app = FastAPI(); app.include_router(router)
        def database():
            yield self.db
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def chunks(self):
        return self.db.query(LearningChunk).order_by(LearningChunk.chunk_index).all()

    @patch("app.routers.learning_material.embedding_dimensions", return_value=1024)
    @patch("app.routers.learning_material.embedding_model", return_value="text-embedding-v4")
    @patch("app.routers.learning_material.embed_texts")
    def test_force_replaces_vectors_and_preserves_topics(self, embed, model, dimensions):
        embed.side_effect = lambda texts: [[float(index + 1)] * 1024 for index, _ in enumerate(texts)]
        response = self.client.post(f"/learning-materials/{self.material.id}/index?force=true")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["reindexed"])
        self.assertEqual(embed.call_count, 1)
        for index, chunk in enumerate(self.chunks()):
            self.assertEqual(chunk.topic_id, self.topic.id)
            self.assertEqual(len(json.loads(chunk.embedding)), 1024)
            self.assertEqual(json.loads(chunk.embedding)[0], float(index + 1))

    @patch("app.routers.learning_material.embed_texts")
    def test_existing_index_is_reused_without_force(self, embed):
        response = self.client.post(f"/learning-materials/{self.material.id}/index")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["reused"])
        embed.assert_not_called()

    @patch("app.routers.learning_material.embed_texts")
    def test_force_preserves_legacy_markdown_chunks_after_splitter_upgrade(self, embed):
        self.material.content = "## React\nComponents.\n\n## State\nMutable data.\n\n## Props\nRead-only inputs."
        old_chunks = split_text_legacy(self.material.content)
        self.assertNotEqual(old_chunks, split_text(self.material.content))
        self.db.query(LearningChunk).delete()
        self.db.add_all([LearningChunk(material_id=self.material.id, topic_id=self.topic.id,
                                      chunk_index=index, content=content, embedding="[0.1]")
                         for index, content in enumerate(old_chunks)])
        self.db.commit()
        previous_ids = [chunk.id for chunk in self.chunks()]
        embed.side_effect = lambda texts: [[0.2] * 1024 for _ in texts]
        response = self.client.post(f"/learning-materials/{self.material.id}/index?force=true")
        self.assertEqual(response.status_code, 200, response.text)
        embed.assert_called_once_with(old_chunks)
        self.assertEqual([chunk.id for chunk in self.chunks()], previous_ids)
        self.assertTrue(all(chunk.topic_id == self.topic.id for chunk in self.chunks()))

    @patch("app.routers.learning_material.embed_texts", side_effect=EmbeddingError("provider unavailable"))
    def test_provider_error_does_not_overwrite_old_vectors(self, embed):
        previous = [chunk.embedding for chunk in self.chunks()]
        response = self.client.post(f"/learning-materials/{self.material.id}/index?force=true")
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual([chunk.embedding for chunk in self.chunks()], previous)

    @patch("app.routers.learning_material.embed_texts")
    def test_force_rejects_changed_chunk_layout_without_mutating_data(self, embed):
        self.chunks()[0].content = "different"; self.db.commit()
        previous = [chunk.embedding for chunk in self.chunks()]
        response = self.client.post(f"/learning-materials/{self.material.id}/index?force=true")
        self.assertEqual(response.status_code, 409, response.text)
        embed.assert_not_called()
        self.assertEqual([chunk.embedding for chunk in self.chunks()], previous)

    def test_other_users_material_is_not_reindexable(self):
        response = self.client.post(f"/learning-materials/{self.other_material.id}/index?force=true")
        self.assertEqual(response.status_code, 404, response.text)

    def test_delete_removes_visible_group_and_related_learning_data(self):
        self.user.total_xp = 430
        duplicate = LearningMaterial(user_id=self.user.id, title="Old copy", content=self.material.content)
        survivor = LearningMaterial(user_id=self.user.id, title="Keep", content="keep this material")
        self.db.add_all([duplicate, survivor]); self.db.flush()
        duplicate_topic = Topic(material_id=duplicate.id, name="Duplicate topic", description="Old")
        self.db.add(duplicate_topic); self.db.flush()
        self.db.add_all([
            LearningChunk(material_id=duplicate.id, chunk_index=0, content="first", embedding="[0.1]",
                          topic_id=duplicate_topic.id),
            Question(material_id=self.material.id, topic_id=self.topic.id, question="Original question",
                     answer="A", explanation="Because", difficulty=1),
            Question(material_id=duplicate.id, topic_id=duplicate_topic.id, question="Duplicate question",
                     answer="B", explanation="Because", difficulty=1),
        ])
        self.db.flush()
        questions = self.db.query(Question).filter(Question.material_id.in_([self.material.id, duplicate.id])).all()
        self.db.add_all([
            QAHistory(user_id=self.user.id, material_id=self.material.id, question="What?", answer="Answer"),
            QAHistory(user_id=self.user.id, material_id=duplicate.id, question="Also?", answer="Also answer"),
            LearningRecord(user_id=self.user.id, content_type="material", content_id=self.material.id,
                           study_time=5, progress=30),
            LearningRecord(user_id=self.user.id, content_type="learning_material", content_id=duplicate.id,
                           study_time=6, progress=60),
            LearningRecord(user_id=self.user.id, content_type="question", content_id=questions[0].id,
                           study_time=0, progress=100),
            QuestionAttempt(user_id=self.user.id, question_id=questions[0].id, user_answer="A",
                            is_correct=True, earned_xp=10),
            ReviewAttempt(user_id=self.user.id, question_id=questions[1].id,
                          request_id="delete-test-request", user_answer="B", is_correct=True),
            TopicMastery(user_id=self.user.id, topic_id=self.topic.id, mastery_score=80,
                         correct_rate=1, attempt_count=1),
            TopicMastery(user_id=self.user.id, topic_id=duplicate_topic.id, mastery_score=40,
                         correct_rate=0.5, attempt_count=2),
        ])
        self.db.commit()

        material_id = self.material.id
        duplicate_id = duplicate.id
        topic_ids = [self.topic.id, duplicate_topic.id]
        question_ids = [question.id for question in questions]

        response = self.client.delete(f"/learning-materials/{material_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()["deleted_material_ids"]), {material_id, duplicate_id})
        self.assertEqual(response.json()["deleted_material_count"], 2)
        self.assertEqual(self.db.query(LearningMaterial).filter(
            LearningMaterial.id.in_([material_id, duplicate_id])).count(), 0)
        self.assertEqual(self.db.query(LearningMaterial).filter(LearningMaterial.id == survivor.id).count(), 1)
        self.assertEqual(self.db.query(LearningMaterial).filter(
            LearningMaterial.id == self.other_material.id).count(), 1)
        self.assertEqual(self.db.query(LearningChunk).filter(LearningChunk.material_id.in_(
            [material_id, duplicate_id])).count(), 0)
        self.assertEqual(self.db.query(Topic).filter(Topic.material_id.in_(
            [material_id, duplicate_id])).count(), 0)
        self.assertEqual(self.db.query(Question).filter(Question.material_id.in_(
            [material_id, duplicate_id])).count(), 0)
        self.assertEqual(self.db.query(QAHistory).filter(QAHistory.material_id.in_(
            [material_id, duplicate_id])).count(), 0)
        self.assertEqual(self.db.query(QuestionAttempt).filter(
            QuestionAttempt.question_id.in_(question_ids)).count(), 0)
        self.assertEqual(self.db.query(ReviewAttempt).filter(
            ReviewAttempt.question_id.in_(question_ids)).count(), 0)
        self.assertEqual(self.db.query(LearningRecord).filter(
            LearningRecord.content_id.in_([material_id, duplicate_id, *question_ids])
        ).count(), 0)
        self.assertEqual(self.db.query(TopicMastery).filter(TopicMastery.topic_id.in_(
            topic_ids)).count(), 0)
        self.db.refresh(self.user)
        self.assertEqual(self.user.total_xp, 430)

    def test_delete_rejects_another_users_material(self):
        response = self.client.delete(f"/learning-materials/{self.other_material.id}")
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.db.query(LearningMaterial).filter(
            LearningMaterial.id == self.other_material.id).count(), 1)


if __name__ == "__main__":
    unittest.main()
