"""Rule invariants and cross-surface integration; no real DB or model calls."""
from datetime import datetime, timedelta, timezone
from itertools import product
import json
from pathlib import Path
from types import SimpleNamespace as Item
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.jwt import create_access_token
from app.database import Base, get_db
from app.models import (User, LearningMaterial, Topic, Question, QuestionAttempt,
                        ReviewAttempt, TopicMastery, CoachSession)
from app.services.topic_mastery import (assess_topic, get_material_topic_performance,
                                       update_topic_mastery)
from app.services.adaptive import (explain_difficulty, get_next_topic_difficulty,
                                   get_weakest_topic)
from app.agents.tools import profile, execute_tool
from app.routers import adaptive, study, coach, question

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def sequence(values, difficulty=2):
    return [(Item(id=i+1, question_id=i+1, is_correct=bool(value), created_at=START+timedelta(minutes=i)),
             Item(id=i+1, difficulty=difficulty)) for i,value in enumerate(values)]


def review(correct=True, *, id=1, question_id=1, when=None):
    return Item(id=id, question_id=question_id, is_correct=correct,
                created_at=when or START+timedelta(days=1, minutes=id))


class MasteryRuleTest(unittest.TestCase):
    def test_comparison_report_is_reproducible_and_demonstrates_old_failures(self):
        from scripts.evaluate_mastery import evaluate_cases
        dataset = json.loads((Path(__file__).resolve().parents[1]/"evaluation/mastery_s2_sequences.json").read_text(encoding="utf-8"))
        first=evaluate_cases(dataset)
        self.assertEqual(first,evaluate_cases(dataset))
        rows={r["id"]:r for r in first["cases"]}
        self.assertEqual(rows["one_correct"]["old_mastery_score"],100)
        self.assertEqual(rows["one_correct"]["assessment"]["mastery_score"],67)
        self.assertEqual(rows["one_correct"]["new_recommended_difficulty"],2)
        self.assertEqual(rows["review_once"]["assessment"],rows["review_repeat"]["assessment"])
        self.assertGreater(rows["improving"]["assessment"]["mastery_score"],rows["declining"]["assessment"]["mastery_score"])
        changed=first["topic_selections"][2]
        self.assertEqual(changed["old_selected"],"improving")
        self.assertEqual(changed["new_selected"],"declining")
        self.assertEqual(first["topic_selections"][3]["new_selected"],"new_topic")

    def test_no_history_is_unknown_even_with_orphan_reviews(self):
        result = assess_topic([], [review()])
        self.assertIsNone(result["mastery_score"])
        self.assertIsNone(result["historical_correct_rate"])
        self.assertIsNone(result["recent_correct_rate"])
        self.assertEqual(result["reviewed_question_count"], 0)
        self.assertEqual(result["mastery_status"], "unseen")
        self.assertIn("不能据此判断薄弱", result["mastery_reason"])

    def test_one_answer_is_not_zero_or_perfect_mastery(self):
        correct, wrong = [assess_topic(sequence([v])) for v in [True,False]]
        self.assertEqual((correct["mastery_score"], wrong["mastery_score"]), (67,31))
        self.assertEqual(correct["historical_correct_rate"], 1)
        self.assertTrue(correct["sample_limited"])
        self.assertIn("初步评估", correct["mastery_reason"])
        self.assertEqual(correct["attempt_count"], 1, "Smoothing is never counted as observed answers")

    def test_more_distinct_successes_accumulate_evidence(self):
        scores = [assess_topic(sequence([True]*n))["mastery_score"] for n in [1,2,5,10,30]]
        self.assertEqual(scores, sorted(set(scores)))
        self.assertLess(scores[0], 80)
        self.assertGreaterEqual(scores[2], 80)

    def test_difficulty_changes_evidence_for_same_outcomes(self):
        for values in [[True]*5, [False]*5, [True,False]*5]:
            with self.subTest(values=values):
                self.assertGreater(assess_topic(sequence(values,5))["mastery_score"],
                                   assess_topic(sequence(values,1))["mastery_score"])

    def test_recent_improvement_and_decline_with_same_overall_accuracy(self):
        improving = assess_topic(sequence([False]*5 + [True]*5))
        declining = assess_topic(sequence([True]*5 + [False]*5))
        self.assertEqual(improving["historical_correct_rate"], declining["historical_correct_rate"])
        self.assertGreater(improving["mastery_score"], declining["mastery_score"])
        self.assertEqual(improving["recent_correct_rate"], 1)
        self.assertEqual(declining["recent_correct_rate"], 0)
        self.assertEqual(improving["attempt_count"], 10)

    def test_latest_review_has_bounded_influence_and_no_repeat_gain(self):
        answers = sequence([False])
        initial = assess_topic(answers)
        corrected = assess_topic(answers, [review()])
        repeated = assess_topic(answers, [review(id=i) for i in range(1,101)])
        self.assertEqual(corrected, repeated)
        self.assertGreater(corrected["mastery_score"], initial["mastery_score"])
        self.assertLess(corrected["mastery_score"], assess_topic(sequence([True]))["mastery_score"])
        self.assertEqual(corrected["historical_correct_rate"], 0)
        self.assertEqual(corrected["recent_correct_rate"], 0)
        self.assertEqual(corrected["attempt_count"], 1)
        self.assertEqual(corrected["reviewed_question_count"], 1)
        self.assertEqual(assess_topic(answers,[review(),review(False,id=101)])["mastery_score"], initial["mastery_score"])

    def test_repeating_old_question_does_not_move_first_answer_window(self):
        answers = sequence([False]+[True]*6)
        first_review = review(when=START+timedelta(minutes=1))
        later = review(id=2)
        self.assertEqual(assess_topic(answers,[first_review]),assess_topic(answers,[first_review,later]))
        self.assertEqual(assess_topic(answers,[later])["recent_attempt_count"],5)

    def test_duplicate_first_rows_never_rewrite_original_or_inflate_sample(self):
        original = sequence([False])
        duplicate = (Item(id=2,question_id=1,is_correct=True,created_at=START+timedelta(days=1)),original[0][1])
        self.assertEqual(assess_topic(original), assess_topic([duplicate,*original]))

    def test_review_order_uses_time_then_id_not_insert_order(self):
        late = review(False,id=1,when=START+timedelta(days=3))
        early = review(True,id=20,when=START+timedelta(days=2))
        self.assertEqual(assess_topic(sequence([False]),[early,late])["review_correct_count"],0)
        tied = review(True,id=21,when=late.created_at.replace(tzinfo=None))
        self.assertEqual(assess_topic(sequence([False]),[late,tied])["review_correct_count"],1)
        self.assertEqual(assess_topic(sequence([False]),[review(when=START-timedelta(days=1))])["reviewed_question_count"],0)

    def test_timestamp_ties_and_difficulty_bounds_are_deterministic(self):
        answers = sequence([False]+[True]*5)
        for a,q in answers:
            a.created_at = START.replace(tzinfo=None)
            q.difficulty = 8
        result = assess_topic(list(reversed(answers)))
        self.assertEqual(result["recent_correct_rate"],1)
        self.assertEqual(result["average_difficulty"],5)
        self.assertEqual(result,assess_topic(answers))

    def test_bounded_monotone_index_over_reproducible_binary_sequences(self):
        for values in product([False,True],repeat=5):
            original = assess_topic(sequence(values))["mastery_score"]
            self.assertTrue(0 <= original <= 100)
            for i,value in enumerate(values):
                if not value:
                    improved = list(values); improved[i]=True
                    self.assertGreaterEqual(assess_topic(sequence(improved))["mastery_score"],original)

    def test_difficulty_rules_use_unique_first_samples_and_bounds(self):
        for rate,count,current,expected in [(None,0,2,2),(1,1,2,2),(1,2,2,2),(1,3,2,3),
                                            (.8,5,3,4),(.6,5,3,3),(.5,4,3,3),(.4,5,3,2),
                                            (0,1,3,2),(0,5,1,1),(1,5,5,5)]:
            with self.subTest(rate=rate,count=count):
                level, reason = explain_difficulty(rate,count,current)
                self.assertEqual(level,expected)
                self.assertTrue(reason)


class MasteryIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://",poolclass=StaticPool,connect_args={"check_same_thread":False})
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose); self.addCleanup(self.db.close)
        self.user = User(username="learner",password_hash="unused")
        self.other = User(username="other",password_hash="unused")
        self.db.add_all([self.user,self.other]); self.db.flush()
        self.material = LearningMaterial(user_id=self.user.id,title="Owned",content="Notes")
        self.foreign = LearningMaterial(user_id=self.other.id,title="Private",content="Private")
        self.db.add_all([self.material,self.foreign]); self.db.flush()
        self.topic = Topic(material_id=self.material.id,name="Topic",description="A topic")
        self.db.add(self.topic); self.db.flush()
        self.q = Question(material_id=self.material.id,topic_id=self.topic.id,question="Choose A",answer="A",explanation="A",difficulty=2)
        self.db.add(self.q); self.db.flush()
        self.db.add(QuestionAttempt(user_id=self.user.id,question_id=self.q.id,user_answer="B",is_correct=False))
        self.cache = TopicMastery(user_id=self.user.id,topic_id=self.topic.id,mastery_score=100,correct_rate=1,attempt_count=99)
        self.db.add(self.cache); self.db.commit()
        app = FastAPI()
        for routes in [adaptive,study,coach,question]:
            app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda:self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization":"Bearer "+create_access_token(self.user.id)}

    def surfaces(self):
        recommendation = self.client.get("/adaptive/recommendation",params={"material_id":self.material.id},headers=self.headers).json()
        node = self.client.get("/study/map",headers=self.headers).json()[0]["topics"][0]
        learner = profile(self.db,self.user.id,self.material.id)["topics"][0]
        weak = get_weakest_topic(self.user.id,self.material.id,self.db)
        return recommendation,node,learner,weak

    def test_all_readers_ignore_stale_cache_and_do_not_write_or_call_models(self):
        statements=[]
        def track(_conn,_cursor,sql,_params,_context,_many):
            if sql.lstrip().upper().startswith(("INSERT","UPDATE","DELETE")):
                statements.append(sql)
        event.listen(self.engine,"before_cursor_execute",track)
        self.addCleanup(event.remove,self.engine,"before_cursor_execute",track)
        with patch("app.services.question_generator.generate_question_from_material") as model:
            for _ in range(3):
                surfaces=self.surfaces()
                self.assertEqual([s["mastery_score"] for s in surfaces],[31]*4)
                self.assertEqual({s["mastery_model"] for s in surfaces},{"rules_v2"})
            model.assert_not_called()
        self.assertEqual(statements,[])
        self.assertEqual(self.cache.mastery_score,100,"GET does not silently migrate the old cache")
        self.assertIn("mastery",surfaces[0]["decision_reasons"])

    def test_review_changes_every_surface_once_and_preserves_xp(self):
        body={"answer":"A","request_id":str(uuid4())}
        for _ in range(2):
            result=self.client.post(f"/study/mistakes/{self.q.id}/review",headers=self.headers,json=body)
            self.assertEqual(result.status_code,200,result.text)
        self.assertEqual([s["mastery_score"] for s in self.surfaces()],[41]*4)
        self.assertEqual(self.db.query(ReviewAttempt).count(),1)
        self.assertEqual(self.cache.mastery_score,41)
        self.assertEqual(self.cache.correct_rate,0)
        self.assertEqual(self.cache.attempt_count,1)
        self.assertEqual(self.user.total_xp,0)
        self.assertEqual(get_next_topic_difficulty(self.user.id,self.topic.id,2,self.db),1)

    def test_old_coach_session_refreshes_assessment_after_external_review(self):
        created = self.client.post("/coach/sessions",headers=self.headers,json={
            "request_id":str(uuid4()),"material_id":self.material.id,"goal":"Review","minutes":10})
        self.assertEqual(created.status_code,200,created.text)
        sid=created.json()["id"]
        self.assertEqual(created.json()["state"]["suggested_topics"][0]["mastery"],31)
        original_revision=created.json()["revision"]
        session=self.db.get(CoachSession,sid)
        with patch("app.agents.coach.complete") as model:
            weak=execute_tool("get_weak_topics",{},self.db,session,session.state)
            self.assertEqual(weak[0]["mastery"],31)
            self.client.post(f"/study/mistakes/{self.q.id}/review",headers=self.headers,json={"answer":"A","request_id":str(uuid4())})
            restored=self.client.get("/coach/sessions/"+sid,headers=self.headers).json()
            model.assert_not_called()
        self.assertEqual(restored["revision"],original_revision)
        self.assertEqual(restored["state"]["suggested_topics"][0]["mastery"],41)

    def test_foreign_attempts_reviews_and_cross_material_links_are_ignored(self):
        self.db.add(QuestionAttempt(user_id=self.other.id,question_id=self.q.id,user_answer="A",is_correct=True))
        self.db.add(ReviewAttempt(user_id=self.other.id,question_id=self.q.id,request_id=str(uuid4()),user_answer="A",is_correct=True))
        invalid=Question(material_id=self.foreign.id,topic_id=self.topic.id,question="Foreign",answer="A",explanation="Private",difficulty=5)
        self.db.add(invalid); self.db.flush()
        self.db.add(QuestionAttempt(user_id=self.user.id,question_id=invalid.id,user_answer="A",is_correct=True))
        self.db.commit()
        self.assertEqual([s["mastery_score"] for s in self.surfaces()],[31]*4)
        self.assertEqual(get_material_topic_performance(self.other.id,self.material.id,self.db),[])

    def test_snapshot_update_can_share_answer_transaction_and_roll_back(self):
        update_topic_mastery(self.user.id,self.topic.id,self.db,commit=False)
        self.assertEqual(self.cache.mastery_score,31)
        self.db.rollback()
        self.assertEqual(self.cache.mastery_score,100)
