"""Answer submission stays durable when optional AI feedback fails."""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user
from app.database import Base, get_db
from app.models import (Achievement, LearningMaterial, LearningRecord, Question,
                        QuestionAttempt, User, UserAchievement)
from app.routers.question import router


class QuestionAnswerFlowTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(username="learner", password_hash="unused")
        self.db.add(self.user)
        self.db.flush()
        material = LearningMaterial(user_id=self.user.id, title="Notes",
                                    content="Facts", material_type="document")
        self.db.add(material)
        self.db.flush()
        self.question = Question(material_id=material.id, question="Choose A",
                                 option_a="Correct", option_b="Wrong",
                                 option_c="Wrong", option_d="Wrong",
                                 answer="A", explanation="A is supported by the notes.")
        self.db.add(self.question)
        self.db.add(Achievement(name="First answer", description="Answer once",
                                xp_reward=5, condition_type="answer_count",
                                condition_value=1))
        self.db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    @patch("app.routers.question.generate_answer_feedback", return_value="AI coaching")
    def test_first_answer_unlocks_achievement_and_loads_feedback_separately(self, feedback):
        response = self.client.post(f"/questions/{self.question.id}/answer",
                                    json={"answer": "A"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["feedback_source"], "local")
        feedback.assert_not_called()
        self.assertEqual(self.db.query(QuestionAttempt).count(), 1)
        self.assertEqual(self.db.query(UserAchievement).count(), 1)
        self.assertEqual(self.db.query(LearningRecord).count(), 1)
        self.assertEqual(self.user.total_xp, 25)
        ai_response = self.client.post(f"/questions/{self.question.id}/feedback")
        self.assertEqual(ai_response.json(), {"feedback": "AI coaching", "source": "ai"})
        cached = self.client.post(f"/questions/{self.question.id}/feedback")
        self.assertEqual(cached.json(), ai_response.json())
        feedback.assert_called_once()

    def test_broken_topic_link_rejected_before_xp_or_attempt(self):
        self.question.topic_id = 999999
        self.db.commit()
        response = self.client.post(f"/questions/{self.question.id}/answer", json={"answer": "A"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.db.query(QuestionAttempt).count(), 0)
        self.assertEqual(self.user.total_xp, 0)

    @patch("app.routers.question.generate_answer_feedback", side_effect=TimeoutError())
    def test_provider_failure_does_not_lose_answer(self, _feedback):
        response = self.client.post(f"/questions/{self.question.id}/answer",
                                    json={"answer": "B"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("这题还需要巩固", response.json()["feedback"])
        self.assertEqual(self.db.query(QuestionAttempt).count(), 1)
        self.assertEqual(self.db.query(UserAchievement).count(), 1)
        self.assertEqual(self.db.query(LearningRecord).count(), 1)
        fallback = self.client.post(f"/questions/{self.question.id}/feedback")
        self.assertEqual(fallback.status_code, 200)
        self.assertEqual(fallback.json()["source"], "local")

    @patch("app.routers.question.generate_answer_feedback")
    def test_feedback_requires_owned_answer(self, feedback):
        missing = self.client.post(f"/questions/{self.question.id}/feedback")
        self.assertEqual(missing.status_code, 404)
        self.client.post(f"/questions/{self.question.id}/answer", json={"answer": "A"})
        other = User(username="other", password_hash="unused")
        self.db.add(other)
        self.db.commit()
        self.client.app.dependency_overrides[get_current_user] = lambda: other
        foreign = self.client.post(f"/questions/{self.question.id}/feedback")
        self.assertEqual(foreign.status_code, 404)
        feedback.assert_not_called()
