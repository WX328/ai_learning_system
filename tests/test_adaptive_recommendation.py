"""Authenticated recommendation/generation integration; SQLite only, no paid APIs."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from jose import jwt

from app.core.jwt import create_access_token, ALGORITHM, SECRET_KEY
from app.database import Base, get_db
from app.models import (LearningMaterial, Question, QuestionAttempt, ReviewAttempt,
                        Topic, TopicMastery, User)
from app.routers.adaptive import router
from app.routers.question import router as question_router
from app.routers.study import router as study_router
from app.schemas.question import QuestionAIOutput
from app.services.adaptive import calculate_next_difficulty, get_next_topic_difficulty, get_next_difficulty


class AdaptiveRecommendationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.engine = engine
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(username="learner", password_hash="unused")
        self.other = User(username="other", password_hash="unused")
        self.db.add_all([self.user, self.other]); self.db.flush()
        self.material = LearningMaterial(user_id=self.user.id, title="FastAPI", content="Notes")
        self.private = LearningMaterial(user_id=self.other.id, title="Private", content="Secret")
        self.db.add_all([self.material, self.private]); self.db.flush()
        self.topic = Topic(material_id=self.material.id, name="依赖注入", description="Dependencies")
        self.db.add(self.topic); self.db.commit()
        app = FastAPI()
        for routes in (router, question_router, study_router):
            app.include_router(routes)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer " + create_access_token(self.user.id)}

    def get(self, endpoint="recommendation", material_id=None, headers=None):
        return self.client.get(f"/adaptive/{endpoint}",
                               params={"material_id": material_id or self.material.id},
                               headers=self.headers if headers is None else headers)

    def recommend(self):
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def history(self, answers, difficulty=2, topic=None, user=None):
        topic = topic or self.topic
        questions = []
        for correct in answers:
            q = Question(material_id=topic.material_id, topic_id=topic.id, question="Choose A",
                         option_a="one", option_b="two", option_c="three", option_d="four",
                         answer="A", explanation="Because A", difficulty=difficulty)
            self.db.add(q); self.db.flush()
            self.db.add(QuestionAttempt(user_id=(user or self.user).id, question_id=q.id,
                                       user_answer="A" if correct else "B", is_correct=correct))
            questions.append(q)
        self.db.commit()
        return questions

    def test_new_user_has_no_fake_zero_or_mastery_write(self):
        data = self.recommend()
        self.assertEqual(data["topic"]["id"], self.topic.id)
        self.assertIsNone(data["mastery_score"])
        self.assertIsNone(data["recent_correct_rate"])
        self.assertFalse(data["has_history"])
        self.assertEqual(data["recent_attempt_count"], 0)
        self.assertEqual(data["recommended_difficulty"], 2)
        self.assertIn("暂无答题记录", data["reason"])
        self.assertEqual(self.db.query(TopicMastery).count(), 0)
        self.assertEqual(get_next_topic_difficulty(self.user.id, self.topic.id, 3, self.db), 3)
        self.assertEqual(get_next_difficulty(self.user.id, 3, self.db), 3)

    def test_accuracy_thresholds_and_bounds(self):
        for rate, current, expected in [(None, 2, 2), (0, 3, 2), (.4, 3, 2),
                                        (.49, 3, 2), (.5, 3, 3), (.6, 3, 3),
                                        (.79, 3, 3), (.8, 3, 4), (1, 3, 4),
                                        (0, 1, 1), (1, 5, 5)]:
            with self.subTest(rate=rate, current=current):
                self.assertEqual(calculate_next_difficulty(rate, current), expected)

    def test_endpoint_accuracy_adjustments(self):
        for correct, current, expected in [(4, 2, 3), (2, 3, 2), (3, 3, 3), (0, 1, 1), (5, 5, 5)]:
            with self.subTest(correct=correct, current=current):
                self.db.query(QuestionAttempt).delete(); self.db.query(Question).delete(); self.db.commit()
                self.history([True] * correct + [False] * (5-correct), current)
                data = self.recommend()
                self.assertEqual(data["recent_correct_rate"], correct / 5)
                self.assertEqual(data["recommended_difficulty"], expected)

    def test_only_latest_five_with_deterministic_timestamp_ties(self):
        self.history([False] * 6 + [True] * 4 + [False], 3)
        tied = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for attempt in self.db.query(QuestionAttempt):
            attempt.created_at = tied
        self.db.commit()
        data = self.recommend()
        self.assertEqual(data["attempt_count"], 11)
        self.assertEqual(data["recent_attempt_count"], 5)
        self.assertEqual(data["recent_correct_rate"], .8)
        self.assertEqual(data["recommended_difficulty"], 4)
        self.assertEqual(data["historical_correct_rate"], 4 / 11)
        self.assertEqual(data["mastery_score"], 52, "Recent improvement now contributes to a smoothed rule score")

    def test_topic_and_user_scoping_do_not_use_overall_accuracy(self):
        self.history([False] * 5, 3)
        strong = Topic(material_id=self.material.id, name="路由", description="Routes")
        self.db.add(strong); self.db.commit()
        self.history([True] * 10, 5, strong)
        self.history([True] * 5, 5, user=self.other)
        data = self.recommend()
        self.assertEqual(data["topic"]["id"], self.topic.id)
        self.assertEqual(data["recent_correct_rate"], 0)
        self.assertEqual(data["recommended_difficulty"], 2)

    def test_unseen_topic_after_weak_topics_and_mastered_fallback(self):
        unseen = Topic(material_id=self.material.id, name="路由", description="Routes")
        self.db.add(unseen); self.db.commit()
        questions = self.history([False])
        self.assertEqual(self.recommend()["topic"]["id"], self.topic.id)
        self.db.add(ReviewAttempt(user_id=self.user.id, question_id=questions[0].id,
                                 request_id=str(uuid4()), user_answer="A", is_correct=True))
        self.db.commit()
        self.assertEqual(self.recommend()["topic"]["id"], self.topic.id,
                         "One corrected familiar question is still insufficient mastery evidence")
        self.history([True] * 8)
        self.assertEqual(self.recommend()["topic"]["id"], unseen.id)
        self.history([True] * 5, topic=unseen)
        data = self.recommend()
        self.assertIsNotNone(data["topic"])
        self.assertIn("均已达到", data["reason"])

    def test_review_updates_mastery_but_does_not_inflate_first_answer_sample(self):
        question = self.history([False])[0]
        before = self.recommend()
        request_id = str(uuid4())
        for _ in range(2):
            response = self.client.post(f"/study/mistakes/{question.id}/review", headers=self.headers,
                                        json={"answer":"A", "request_id":request_id})
            self.assertEqual(response.status_code, 200, response.text)
        after = self.recommend()
        self.assertEqual(before["mastery_score"], 31)
        self.assertEqual(after["mastery_score"], 41)
        self.assertEqual(after["reviewed_question_count"], 1)
        self.assertEqual(after["historical_correct_rate"], 0)
        self.assertEqual(after["recent_correct_rate"], 0)
        self.assertEqual(after["recent_attempt_count"], 1)
        self.assertEqual(self.db.query(ReviewAttempt).count(), 1)
        self.assertEqual(self.user.total_xp, 0)

    def test_jwt_and_ownership_required_for_both_endpoints(self):
        for endpoint in ("recommendation", "next-question"):
            self.assertEqual(self.get(endpoint, headers={}).status_code, 401)
            self.assertEqual(self.get(endpoint, headers={"Authorization":"Bearer invalid"}).status_code, 401)
            self.assertEqual(self.get(endpoint, material_id=self.private.id).status_code, 404)
            self.assertEqual(self.get(endpoint, material_id=999999).status_code, 404)
            foreign = {"Authorization":"Bearer " + create_access_token(self.other.id)}
            self.assertEqual(self.get(endpoint, headers=foreign).status_code, 404)

    def test_expired_token_is_rejected(self):
        token = jwt.encode({"sub":str(self.user.id), "exp":datetime.now(timezone.utc) - timedelta(seconds=1)},
                           SECRET_KEY, algorithm=ALGORITHM)
        for endpoint in ("recommendation", "next-question"):
            self.assertEqual(self.get(endpoint, headers={"Authorization":"Bearer " + token}).status_code, 401)

    def test_repeated_preview_is_read_only_and_never_calls_ai(self):
        self.history([True, False], 3)
        self.db.expire_all()
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", capture)
        self.addCleanup(event.remove, self.engine, "before_cursor_execute", capture)
        with patch("app.services.question_generator.generate_question_from_material") as generator, patch(
                "app.services.question_generator.deepseek_client") as ai:
            responses = [self.recommend() for _ in range(4)]
        self.assertTrue(all(item == responses[0] for item in responses))
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in statements), statements)
        generator.assert_not_called(); ai.assert_not_called()

    def test_no_topics_is_explicit(self):
        self.db.delete(self.topic); self.db.commit()
        data = self.recommend()
        self.assertIsNone(data["topic"])
        self.assertIn("没有知识点", data["reason"])
        self.assertEqual(self.get("next-question").status_code, 404)

    @patch("app.services.question_generator.generate_question_from_material")
    def test_generation_matches_preview_reuses_question_and_advances_after_answer(self, generator):
        self.history([True] * 5, 3)
        preview = self.recommend()
        generator.side_effect = lambda **kwargs: QuestionAIOutput(question="Choose A", option_a="one",
            option_b="two", option_c="three", option_d="four", answer="A", explanation="A", difficulty=1)
        first = self.get("next-question")
        self.assertEqual(first.status_code, 200, first.text)
        question = first.json()["question"]
        self.assertEqual(question["topic_id"], preview["topic"]["id"])
        self.assertEqual(question["difficulty"], preview["recommended_difficulty"])
        self.assertNotIn("answer", question)
        self.assertNotIn("explanation", question)
        self.assertFalse(generator.call_args.kwargs["adapt_difficulty"])
        self.assertEqual(self.get("next-question").json(), first.json())
        generator.assert_called_once()
        pending = self.recommend()
        self.assertEqual(pending["pending_question_id"], question["id"])
        self.assertEqual(pending["recommended_difficulty"], question["difficulty"])
        answered = self.client.post(f"/questions/{question['id']}/answer", headers=self.headers, json={"answer":"A"})
        self.assertEqual(answered.status_code, 200, answered.text)
        xp = self.user.total_xp
        after = self.recommend()
        self.assertIsNone(after["pending_question_id"])
        self.assertEqual(after["current_difficulty"], 4)
        self.assertEqual(after["recommended_difficulty"], 5)
        self.assertEqual(self.client.post(f"/questions/{question['id']}/answer", headers=self.headers,
                                         json={"answer":"A"}).status_code, 400)
        self.assertEqual(self.user.total_xp, xp)
        self.assertEqual(self.recommend(), after)

    @patch("app.services.question_generator.generate_question_from_material")
    def test_new_user_can_start_adaptive_practice(self, generator):
        generator.return_value = QuestionAIOutput(question="Choose A", option_a="one", option_b="two",
            option_c="three", option_d="four", answer="A", explanation="A", difficulty=2)
        response = self.get("next-question")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["question"]["topic_id"], self.topic.id)
        self.assertEqual(generator.call_args.kwargs["current_difficulty"], 2)

    @patch("app.services.question_generator.search_similar_chunks")
    @patch("app.services.question_generator.generate_question")
    def test_existing_generator_applies_recommended_level_exactly_once(self, provider, retrieval):
        self.history([True] * 5, 3)
        retrieval.return_value = [{"chunk":SimpleNamespace(content="Depends 声明依赖") }]
        provider.return_value = QuestionAIOutput(question="Choose A", option_a="one", option_b="two",
            option_c="three", option_d="four", answer="A", explanation="A", difficulty=4)
        response = self.get("next-question")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(provider.call_args.kwargs["difficulty"], 4)
        self.assertEqual(provider.call_args.kwargs["topic"], self.topic.name)
        self.assertEqual(response.json()["question"]["difficulty"], 4)
        provider.assert_called_once()


if __name__ == "__main__":
    unittest.main()
