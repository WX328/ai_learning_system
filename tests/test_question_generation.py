"""Question retrieval regression tests with an in-memory DB and mocked providers."""
import json
import math
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.core.dependencies import get_current_user
from app.models import User, LearningMaterial, LearningChunk, Topic, Question
from app.routers.question import router
from app.schemas.question import QuestionAIOutput
from app.services.question_generator import generate_question_from_material, save_generated_question


class QuestionGenerationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(username="test", password_hash="unused")
        self.db.add(self.user)
        self.db.flush()
        self.material = LearningMaterial(user_id=self.user.id, title="SQL",
                                         content="Database notes", material_type="document")
        self.other = LearningMaterial(user_id=self.user.id, title="Other",
                                      content="Other notes", material_type="document")
        self.db.add_all([self.material, self.other])
        self.db.flush()
        self.topic = Topic(material_id=self.material.id, name="Database", description="Storage")
        self.foreign_topic = Topic(material_id=self.other.id, name="Other", description="Other")
        self.db.add_all([self.topic, self.foreign_topic])
        self.db.flush()
        # Below the old 0.6 cutoff, above the shared 0.35 cutoff.
        self.chunk = LearningChunk(material_id=self.material.id, chunk_index=0,
            content="A database stores structured data.",
            embedding=json.dumps([0.4446, math.sqrt(1 - 0.4446 ** 2)]))
        self.foreign_chunk = LearningChunk(material_id=self.other.id, chunk_index=0,
            content="Foreign material must never reach the prompt.", embedding="[1, 0]")
        self.db.add_all([self.chunk, self.foreign_chunk])
        self.db.commit()
        embed = patch("app.services.retriever.embed_text", return_value=[1, 0])
        self.embed = embed.start()
        self.addCleanup(embed.stop)
        provider = patch("app.services.question_generator.generate_question", return_value=QuestionAIOutput(
            question="What does a database store?", option_a="Structured data", option_b="B",
            option_c="C", option_d="D", answer="A", explanation="The notes say so.", difficulty=1))
        self.provider = provider.start()
        self.addCleanup(provider.stop)

    def generate(self, topic_id=None):
        return generate_question_from_material(material_id=self.material.id,
            user_id=self.user.id, topic="Database", db=self.db, topic_id=topic_id)

    def test_unassigned_topic_uses_same_material_and_retains_topic(self):
        self.generate(self.topic.id)
        args = self.provider.call_args.kwargs
        self.assertEqual(args["context"], self.chunk.content)
        self.assertEqual(args["topic"], self.topic.name)
        self.assertIsNone(self.chunk.topic_id)  # No reassignment of user data.

    def test_linked_topic_keeps_scope(self):
        self.chunk.topic_id = self.topic.id
        self.db.add(LearningChunk(material_id=self.material.id, chunk_index=1,
            content="Unselected topic", embedding="[1, 0]"))
        self.db.commit()
        self.generate(self.topic.id)
        self.assertEqual(self.provider.call_args.kwargs["context"], self.chunk.content)

    def test_missing_topic_fails_before_embedding_or_generation(self):
        with self.assertRaises(ValueError):
            self.generate()
        self.embed.assert_not_called()
        self.provider.assert_not_called()

    def test_no_relevant_content_does_not_call_generator(self):
        self.chunk.embedding = "[0, 1]"
        self.db.commit()
        with self.assertRaises(ValueError):
            self.generate(self.topic.id)
        self.provider.assert_not_called()

    def test_foreign_topic_rejected_before_provider_calls(self):
        with self.assertRaises(ValueError):
            self.generate(self.foreign_topic.id)
        self.embed.assert_not_called()
        self.provider.assert_not_called()

    def test_generate_endpoint_saves_selected_topic(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        with TestClient(app) as client:
            response = client.post("/questions/generate", json={
                "material_id": self.material.id, "topic_id": self.topic.id,
                "topic": self.topic.name, "count": 1, "difficulty": 2})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        self.assertNotIn("answer", response.json()[0])
        self.assertNotIn("explanation", response.json()[0])
        saved = self.db.get(Question, response.json()[0]["id"])
        self.assertEqual(saved.topic_id, self.topic.id)
        self.assertEqual(saved.material_id, self.material.id)

    def test_batch_failure_does_not_save_partial_question_set(self):
        self.provider.side_effect = [self.provider.return_value, ValueError("invalid model output")]
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        with TestClient(app) as client:
            response = client.post("/questions/generate", json={
                "material_id": self.material.id, "topic": "Database", "topic_id": self.topic.id, "count": 2,
            })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.query(Question).count(), 0)

    def test_missing_topic_endpoint_never_calls_model(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        with TestClient(app) as client:
            response = client.post("/questions/generate", json={
                "material_id": self.material.id, "topic": self.topic.name})
        self.assertEqual(response.status_code, 400)
        self.provider.assert_not_called()
        self.assertEqual(self.db.query(Question).count(), 0)

    def test_save_layer_rejects_null_or_cross_material_topic(self):
        for topic_id in (None, self.foreign_topic.id, 999999):
            with self.subTest(topic_id=topic_id), self.assertRaises(ValueError):
                save_generated_question(self.material.id, self.provider.return_value, self.db, topic_id=topic_id)
        self.assertEqual(self.db.query(Question).count(), 0)

    def test_service_checks_owner_before_paid_retrieval(self):
        with self.assertRaises(ValueError):
            generate_question_from_material(self.material.id, 999999, "Database", self.db, topic_id=self.topic.id)
        self.embed.assert_not_called()
        self.provider.assert_not_called()

    def test_repeat_topic_extraction_preserves_question_and_chunk_links(self):
        from app.services.topic_extractor import save_topics, extract_and_assign_topics
        from types import SimpleNamespace
        self.chunk.topic_id = self.topic.id
        question = save_generated_question(self.material.id, self.provider.return_value, self.db, topic_id=self.topic.id)
        old_id = self.topic.id
        changed = SimpleNamespace(topics=[SimpleNamespace(name="Replacement", description="new")])
        self.assertEqual([t.id for t in save_topics(self.material.id, changed, self.db)], [old_id])
        with patch("app.services.topic_extractor.extract_topics") as extractor, patch("app.services.topic_extractor.assign_chunks_to_topics") as assign:
            self.assertEqual([t.id for t in extract_and_assign_topics(self.material.id, "text", self.db)], [old_id])
        extractor.assert_not_called()
        assign.assert_not_called()
        self.db.expire_all()
        self.assertEqual(question.topic_id, old_id)
        self.assertEqual(self.chunk.topic_id, old_id)
        self.assertEqual(self.db.get(Topic, old_id).name, "Database")

    def test_invalid_first_extraction_does_not_partially_save(self):
        from app.services.topic_extractor import save_topics
        from types import SimpleNamespace
        empty = LearningMaterial(user_id=self.user.id, title="Empty", content="text", material_type="document")
        self.db.add(empty)
        self.db.commit()
        for names in (("one", "one"), ("one", " "), ()):
            with self.subTest(names=names), self.assertRaises(ValueError):
                save_topics(empty.id, SimpleNamespace(topics=[SimpleNamespace(name=n, description="test") for n in names]), self.db)
        self.assertEqual(self.db.query(Topic).filter_by(material_id=empty.id).count(), 0)

    def test_coach_cannot_omit_topic_id(self):
        from pydantic import ValidationError
        from app.agents.tools import PracticeArgs
        with self.assertRaises(ValidationError):
            PracticeArgs(topic="Database")

    def test_timestamps_are_evaluated_per_row(self):
        self.assertTrue(Question.__table__.c.created_at.default.is_callable)
        self.assertTrue(Topic.__table__.c.created_at.default.is_callable)

    def test_readonly_audit_classifies_null_without_guessing(self):
        from pathlib import Path
        import sqlite3
        import tempfile
        from scripts.audit_learning_links import audit
        legacy = Question(material_id=self.material.id, question="legacy", answer="A", explanation="old")
        self.db.add(legacy)
        save_generated_question(self.material.id, self.provider.return_value, self.db, topic_id=self.topic.id)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "independent.db"
            destination = sqlite3.connect(path)
            self.db.connection().connection.driver_connection.backup(destination)
            destination.close()
            report = audit(path)
        self.assertEqual(report["counts"]["questions"]["categories"], {"null_topic": 1, "valid": 1})
        self.assertEqual(report["database_sha256_before"], report["database_sha256_after"])


if __name__ == "__main__":
    unittest.main()
