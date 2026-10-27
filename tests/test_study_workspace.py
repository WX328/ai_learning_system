"""Run with python -m unittest discover -s tests; uses only an in-memory database."""
import unittest
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.jwt import create_access_token
from app.database import Base, get_db
from app.models import (User, LearningMaterial, LearningChunk, Question, QuestionAttempt,
                        Topic, QAHistory, ReviewAttempt, TopicMastery)
from app.routers.study import router, level_info


class StudyWorkspaceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(username="learner", password_hash="unused", total_xp=120, level=2)
        self.other = User(username="other", password_hash="unused")
        self.db.add_all([self.user, self.other]); self.db.flush()
        self.material = LearningMaterial(user_id=self.user.id, title="Agent notes", content="Agent content")
        self.private = LearningMaterial(user_id=self.other.id, title="Private", content="Secret")
        self.db.add_all([self.material,self.private]); self.db.flush()
        self.topic = Topic(material_id=self.material.id, name="Agent", description="A core topic")
        self.unseen = Topic(material_id=self.material.id, name="Memory", description="Not practiced")
        self.db.add_all([self.topic,self.unseen]); self.db.flush()
        self.questions = []
        for index, material in enumerate([self.material,self.material,self.private]):
            q = Question(material_id=material.id, topic_id=self.topic.id if index < 2 else None,
                         question=f"Question {index}", option_a="one", option_b="two",
                         option_c="three", option_d="four", answer="B", explanation="Because two")
            self.db.add(q); self.db.flush(); self.questions.append(q)
            self.db.add(QuestionAttempt(user_id=material.user_id, question_id=q.id,
                                       user_answer="B" if index == 1 else "A", is_correct=index == 1,
                                       earned_xp=20 if index == 1 else 0))
        self.db.add_all([
            LearningChunk(material_id=self.material.id,chunk_index=0,content="Agent",embedding="[1]",topic_id=self.topic.id),
            LearningChunk(material_id=self.material.id,chunk_index=1,content="Memory",embedding="[1]"),
            QAHistory(user_id=self.user.id,material_id=self.material.id,question="What?",answer="An answer"),
            QAHistory(user_id=self.other.id,material_id=self.private.id,question="Secret?",answer="Private answer"),
        ])
        self.db.commit()
        app = FastAPI(); app.include_router(router)
        def database():
            yield self.db
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer " + create_access_token(self.user.id)}

    def get(self,path):
        response = self.client.get("/study/" + path,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def review(self, answer="B", request_id=None, question=None):
        return self.client.post(f"/study/mistakes/{question or self.questions[0].id}/review",
                                headers=self.headers,json={"answer":answer,"request_id":request_id or str(uuid4())})

    def test_auth_and_account_isolation(self):
        for endpoint in ["summary","mistakes","records","map"]:
            self.assertEqual(self.client.get("/study/"+endpoint).status_code,401)
        self.assertEqual(len(self.get("mistakes")),1)
        self.assertEqual(len(self.get("records")),3)
        self.assertEqual([m["id"] for m in self.get("map")],[self.material.id])
        self.assertEqual(self.review(question=self.questions[2].id).status_code,404)
        self.assertEqual(self.review(question=self.questions[1].id).status_code,404)

    def test_review_persists_without_repeat_xp_and_is_idempotent(self):
        request_id = str(uuid4())
        first = self.review(request_id=request_id)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.review(request_id=request_id).json(),first.json())
        self.assertEqual(self.db.query(ReviewAttempt).count(),1)
        summary = self.get("summary")
        self.assertEqual(summary["total_xp"],120)
        self.assertEqual(summary["answered_count"],2)
        self.assertEqual(summary["correct_rate"],50)
        self.assertEqual(summary["pending_mistakes"],0)
        self.assertTrue(self.get("mistakes")[0]["resolved"])
        self.assertEqual(len(self.get("records")),4)
        self.assertEqual(self.review(answer="A",request_id=request_id).status_code,409)

    def test_latest_review_controls_status_and_map(self):
        self.assertEqual(self.review().status_code,200)
        self.assertEqual(self.get("map")[0]["topics"][0]["mastery_score"],51)
        self.assertEqual(self.db.query(TopicMastery).filter_by(user_id=self.user.id,topic_id=self.topic.id).one().mastery_score,51)
        self.assertEqual(self.review(answer="A").status_code,200)
        self.assertFalse(self.get("mistakes")[0]["resolved"])
        self.assertEqual(self.get("summary")["pending_mistakes"],1)
        self.assertEqual(self.get("map")[0]["topics"][0]["mastery_score"],43)

    def test_unseen_and_partial_association_are_explicit(self):
        material = self.get("map")[0]
        self.assertEqual((material["chunk_count"],material["embedded_count"],material["linked_count"]),(2,2,1))
        unseen = next(t for t in material["topics"] if t["id"] == self.unseen.id)
        self.assertIsNone(unseen["mastery_score"])
        self.assertEqual(unseen["attempt_count"],0)
        self.assertEqual(unseen["chunk_count"],0)

    def test_level_boundaries_and_maximum(self):
        for xp, level in [(0,1),(99,1),(100,2),(249,2),(250,3),(500,4),(1000,5),(1500,5)]:
            self.user.total_xp=xp
            result=level_info(self.user)
            self.assertEqual(result["level"],level)
            self.assertGreaterEqual(result["level_progress"],0)
            self.assertLessEqual(result["level_progress"],100)
            if level == 5:
                self.assertIsNone(result["next_level_xp"])

    def test_validation_and_empty_account(self):
        self.assertEqual(self.review(answer="X").status_code,422)
        self.assertEqual(self.review(request_id="invalid").status_code,422)
        user=User(username="empty",password_hash="unused")
        self.db.add(user); self.db.commit()
        self.headers={"Authorization":"Bearer " + create_access_token(user.id)}
        self.assertIsNone(self.get("summary")["correct_rate"])
        self.assertEqual(self.get("mistakes"),[])
        self.assertEqual(self.get("records"),[])
        self.assertEqual(self.get("map"),[])


if __name__ == "__main__":
    unittest.main()
