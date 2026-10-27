"""Coach integration: authorization, durable progress, bounded tools and idempotency."""
import copy
import json
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletionMessage
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.core.dependencies import get_current_user
from app.models import User, LearningMaterial, Topic, Question, QuestionAttempt, CoachSession, CoachTurn
from app.schemas.question import QuestionAIOutput
from app.routers.coach import router
from app.routers.learning_material import router as materials_router
from app.agents.tools import execute_tool


def reply(text="根据资料继续学习。", name=None, arguments=None):
    data = {"role": "assistant", "content": text}
    if name:
        data["tool_calls"] = [{"id": "call_" + str(uuid4()), "type": "function",
                              "function": {"name": name, "arguments": json.dumps(arguments or {})}}]
    return ChatCompletionMessage.model_validate(data)


QUESTION = QuestionAIOutput(question="依赖注入使用什么？", option_a="Depends",
                            option_b="Print", option_c="Pass", option_d="Break",
                            answer="A", explanation="SECRET_SOLUTION: Depends 声明依赖。", difficulty=2)


class CoachTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(username="learner", password_hash="unused")
        self.other = User(username="other", password_hash="unused")
        self.db.add_all([self.user, self.other])
        self.db.flush()
        self.material = LearningMaterial(user_id=self.user.id, title="FastAPI", content="Depends 声明依赖")
        self.foreign = LearningMaterial(user_id=self.other.id, title="Private", content="private")
        self.db.add_all([self.material, self.foreign])
        self.db.flush()
        self.topic = Topic(material_id=self.material.id, name="依赖注入", description="desc")
        self.foreign_topic = Topic(material_id=self.foreign.id, name="private", description="desc")
        self.db.add_all([self.topic, self.foreign_topic])
        self.db.commit()
        app = FastAPI()
        app.include_router(router)
        app.include_router(materials_router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def create(self, **changes):
        data = {"request_id": str(uuid4()), "material_id": self.material.id,
                "goal": "复习依赖注入", "minutes": 20}
        data.update(changes)
        response = self.client.post("/coach/sessions", json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), data

    def send(self, session, action="message", **changes):
        body = {"request_id": str(uuid4()), "revision": session["revision"], "action": action}
        if action == "message":
            body["message"] = "请给我练习"
        body.update(changes)
        response = self.client.post("/coach/sessions/" + session["id"] + "/turns", json=body)
        return response, body

    def practice(self):
        session, _ = self.create()
        with patch("app.agents.coach.complete", return_value=reply(
            name="create_practice", arguments={"topic": "依赖注入", "topic_id": self.topic.id}
        )) as model, patch("app.agents.tools.generate_question_from_material", return_value=QUESTION):
            response, _ = self.send(session)
        self.assertEqual(response.status_code, 200, response.text)
        model.assert_called_once()
        return response.json()

    def test_create_and_restore_are_idempotent(self):
        session, body = self.create()
        replay = self.client.post("/coach/sessions", json=body)
        self.assertEqual(replay.json()["id"], session["id"])
        self.assertEqual(self.db.query(CoachSession).count(), 1)
        self.assertEqual(sum(p["minutes"] for p in session["state"]["plan"]), 20)
        self.assertIsNone(session["state"]["suggested_topics"][0]["mastery"])
        self.assertEqual(self.client.get("/coach/sessions/" + session["id"]).json(), session)
        body["goal"] = "different"
        self.assertEqual(self.client.post("/coach/sessions", json=body).status_code, 409)

    def test_ownership_applies_to_create_read_command_and_list(self):
        session, _ = self.create()
        bad = {"request_id": str(uuid4()), "material_id": self.foreign.id, "goal": "read", "minutes": 10}
        self.assertEqual(self.client.post("/coach/sessions", json=bad).status_code, 404)
        self.client.app.dependency_overrides[get_current_user] = lambda: self.other
        self.assertEqual(self.client.get("/coach/sessions").json(), [])
        self.assertEqual(self.client.get("/coach/sessions/" + session["id"]).status_code, 404)
        self.assertEqual(self.send(session)[0].status_code, 404)

    def test_generated_question_hides_solution_and_blocks_continuation(self):
        session = self.practice()
        self.assertEqual(session["status"], "waiting_answer")
        self.assertNotIn("SECRET_SOLUTION", json.dumps(session))
        self.assertNotIn("correct_answer", session["question"])
        self.assertNotIn("answer", session["question"])
        self.assertNotIn("explanation", session["question"])
        with patch("app.agents.coach.complete") as model:
            self.assertEqual(self.send(session)[0].status_code, 409)
            model.assert_not_called()
        restored = self.client.get("/coach/sessions/" + session["id"]).json()
        self.assertEqual(restored["question"]["id"], session["question"]["id"])

    def test_answer_retries_do_not_duplicate_grading_or_xp(self):
        session = self.practice()
        with patch("app.agents.coach.complete") as model:
            response, body = self.send(session, "answer", answer="A")
            model.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        answered = response.json()
        self.assertIsNone(answered["question"])
        self.assertEqual(answered["state"]["completed"][0]["correct_answer"], "A")
        self.assertEqual(self.db.query(QuestionAttempt).count(), 1)
        self.assertEqual(self.db.get(User, self.user.id).total_xp, 20)
        replay = self.client.post("/coach/sessions/" + session["id"] + "/turns", json=body)
        self.assertEqual(replay.json(), answered)
        self.assertEqual(self.db.query(QuestionAttempt).count(), 1)
        self.assertEqual(self.user.total_xp, 20)
        body["answer"] = "B"
        self.assertEqual(self.client.post("/coach/sessions/" + session["id"] + "/turns", json=body).status_code, 409)

    def test_model_timeout_preserves_progress_and_allows_retry(self):
        session, _ = self.create()
        with patch("app.agents.coach.complete", side_effect=TimeoutError):
            response, body = self.send(session)
        self.assertEqual(response.status_code, 200)
        session = response.json()
        self.assertTrue(session["state"]["degraded"])
        self.assertFalse(session["busy"])
        with patch("app.agents.coach.complete", return_value=reply("恢复成功")):
            response, _ = self.send(session, message="再试一次")
        self.assertEqual(response.json()["messages"][-1]["content"], "恢复成功")
        self.assertFalse(response.json()["state"]["degraded"])

    def test_stale_revision_and_active_lease_rejected(self):
        session, _ = self.create()
        with patch("app.agents.coach.complete", return_value=reply()):
            updated, _ = self.send(session)
            self.assertEqual(self.send(session)[0].status_code, 409)
        row = self.db.get(CoachSession, session["id"])
        row.lease_until = time.time() + 60
        row.lease_token = str(uuid4())
        self.db.commit()
        self.assertEqual(self.send(updated.json())[0].status_code, 409)

    def test_unknown_and_malformed_tools_are_bounded(self):
        session, _ = self.create()
        with patch("app.agents.coach.complete", return_value=reply(name="run_sql",
                   arguments={"sql": "delete from users"})) as model:
            response, _ = self.send(session)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(model.call_count, 4)
        self.assertTrue(response.json()["state"]["degraded"])
        self.assertEqual(self.db.query(User).count(), 2)

    def test_scoped_tools_reject_injected_identity_and_foreign_topics(self):
        session, _ = self.create()
        row = self.db.get(CoachSession, session["id"])
        for tool, args in [
            ("get_learning_profile", {"user_id": self.other.id}),
            ("search_material", {"query": "x", "material_id": self.foreign.id}),
            ("create_practice", {"topic": "x", "topic_id": self.foreign_topic.id}),
        ]:
            with self.assertRaises(ValueError):
                execute_tool(tool, args, self.db, row, copy.deepcopy(row.state))

    def test_finish_uses_saved_results_without_model(self):
        session = self.practice()
        session = self.send(session, "answer", answer="B")[0].json()
        with patch("app.agents.coach.complete") as model:
            response, _ = self.send(session, "finish")
            model.assert_not_called()
        ended = response.json()
        self.assertEqual(ended["status"], "completed")
        self.assertIn("答对 0 道", ended["state"]["summary"])
        self.assertIn("依赖注入", ended["state"]["summary"])
        self.assertEqual(self.send(ended)[0].status_code, 409)

    def test_material_deletion_cleans_coach_history(self):
        session = self.practice()
        response = self.client.delete("/learning-materials/" + str(self.material.id))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(CoachSession).count(), 0)
        self.assertEqual(self.db.query(CoachTurn).count(), 0)
        self.assertEqual(self.client.get("/coach/sessions/" + session["id"]).status_code, 404)

    def test_lost_lease_rolls_back_generated_question(self):
        session, _ = self.create()
        def lose_lease(db, row, state, message):
            q = Question(material_id=row.material_id, **QUESTION.model_dump())
            db.add(q)
            db.flush()
            db.query(CoachSession).filter_by(id=row.id).update({"lease_token": "replaced"},
                                                            synchronize_session=False)
            return "late reply", False
        with patch("app.routers.coach.run_coach", side_effect=lose_lease):
            response, _ = self.send(session)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.db.query(Question).count(), 0)
        self.assertEqual(self.db.query(CoachTurn).count(), 0)
