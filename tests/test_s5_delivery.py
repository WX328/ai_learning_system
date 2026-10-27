"""Isolated deployment, resource and transaction regressions. No paid providers."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.models import User, Question, QuestionAttempt, LearningMaterial, LearningRecord, Achievement, UserAchievement, Topic, LearningChunk
from app.services.answer_submission import record_answer
from app.core.resource_limits import BodyLimitMiddleware, ModelRequestBudget
from app.core.dependencies import get_current_user
from app.routers.learning_record import router as records_router
from app.routers.learning_material import extract_uploaded_text
from scripts.data_backup import backup, restore
from app.core.settings import validate_startup_settings
from app.services.topic_chunk import assign_chunks_to_topics


class S5ResourceTest(unittest.TestCase):
    def test_production_rejects_plain_http_model_endpoints(self):
        env = {"APP_ENV":"production", "SECRET_KEY":"x"*48, "DEEPSEEK_API_KEY":"test", "DASHSCOPE_API_KEY":"test",
               "DASHSCOPE_EMBEDDING_BASE_URL":"https://embedding.invalid/v1", "DEEPSEEK_BASE_URL":"https://chat.invalid"}
        for key in ("DEEPSEEK_BASE_URL","DASHSCOPE_EMBEDDING_BASE_URL"):
            with self.subTest(key=key), patch.dict(os.environ,{**env,key:"http://insecure.invalid"}):
                with self.assertRaises(RuntimeError):
                    validate_startup_settings()

    def test_chunked_body_rejected_before_endpoint(self):
        app = FastAPI()
        calls = []
        app.add_middleware(BodyLimitMiddleware, limit=16)
        @app.post("/")
        async def endpoint(request: Request):
            calls.append(True)
            return {"size": len(await request.body())}
        with TestClient(app) as client:
            response = client.post("/", content=iter([b"a"*8, b"b"*9]))
            self.assertEqual(response.status_code, 413)
            self.assertEqual(calls, [])
            self.assertEqual(client.post("/", content=b"ok").json(), {"size": 2})

    def test_model_budget_concurrency_user_rate_and_window(self):
        now = [0.]
        budget = ModelRequestBudget(limit=2, concurrent=1, clock=lambda: now[0])
        budget.enter(1)
        with self.assertRaises(HTTPException) as busy:
            budget.enter(2)
        self.assertEqual(busy.exception.status_code, 429)
        budget.leave()
        budget.enter(1)
        budget.leave()
        with self.assertRaises(HTTPException):
            budget.enter(1)
        now[0] = 61
        budget.enter(1)
        budget.leave()

    def test_docx_decompression_limit(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", "x"*(5*1024*1024+1))
        with self.assertRaises(HTTPException) as caught:
            extract_uploaded_text("large.docx", stream.getvalue())
        self.assertEqual(caught.exception.status_code, 413)


class S5ConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        engine = create_engine("sqlite:///"+(Path(self.folder.name)/"test.db").as_posix(), connect_args={"check_same_thread":False, "timeout":10})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.factory = sessionmaker(bind=engine)
        with self.factory() as db:
            user = User(username="isolated", password_hash="not-a-login")
            other = User(username="other", password_hash="not-a-login")
            db.add_all([user, other]); db.flush()
            material = LearningMaterial(user_id=user.id, title="Isolated", content="Test")
            db.add(material); db.flush()
            db.add_all([Question(material_id=material.id, question=f"Q{i}", answer="A", explanation="Test") for i in range(2)])
            db.add(Achievement(name="Test first answer", description="Test", condition_type="answer_count", condition_value=1, xp_reward=5))
            db.commit()
            self.user_id, self.other_id, self.material_id = user.id, other.id, material.id
            self.question_ids = [q.id for q in db.query(Question).order_by(Question.id)]

    def concurrent(self, question_ids):
        gate = Barrier(2)
        def submit(question_id):
            with self.factory() as db:
                user = db.get(User, self.user_id)  # Both workers hold a stale user snapshot.
                gate.wait(timeout=5)
                try:
                    record_answer(question_id, "A", user, db)
                    return 200
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as workers:
            return list(workers.map(submit, question_ids))

    def test_duplicate_first_answer_only_awards_once(self):
        self.assertEqual(sorted(self.concurrent([self.question_ids[0]]*2)), [200,400])
        with self.factory() as db:
            self.assertEqual(db.query(QuestionAttempt).count(), 1)
            self.assertEqual(db.query(UserAchievement).count(), 1)
            self.assertEqual(db.query(LearningRecord).count(), 1)
            self.assertEqual(db.get(User, self.user_id).total_xp, 25)

    def test_different_answers_do_not_lose_xp_or_duplicate_achievement(self):
        self.assertEqual(self.concurrent(self.question_ids), [200,200])
        with self.factory() as db:
            self.assertEqual(db.query(QuestionAttempt).count(), 2)
            self.assertEqual(db.query(UserAchievement).count(), 1)
            self.assertEqual(db.get(User, self.user_id).total_xp, 45)
            self.assertEqual(db.get(User, self.user_id).correct_streak, 2)

    def test_learning_record_foreign_resource_rejected(self):
        app = FastAPI()
        app.include_router(records_router)
        def database():
            with self.factory() as db:
                yield db
        def user():
            with self.factory() as db:
                return db.get(User, self.other_id)
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = user
        with TestClient(app) as client:
            for kind, identity in (("material", self.material_id), ("question", self.question_ids[0])):
                response = client.post("/learning-records", json={"content_type":kind, "content_id":identity})
                self.assertEqual(response.status_code, 404)
        with self.factory() as db:
            self.assertEqual(db.query(LearningRecord).count(), 0)

    def test_optional_chunk_assignment_has_model_call_budget(self):
        with self.factory() as db:
            topic = Topic(material_id=self.material_id, name="Test topic", description="Fixture")
            db.add(topic)
            db.add_all([LearningChunk(material_id=self.material_id,chunk_index=i,content="Test chunk") for i in range(12)])
            db.commit()
            with patch("app.services.topic_chunk.match_chunk_to_topic", return_value=1) as call:
                chunks = assign_chunks_to_topics(self.material_id, db)
                self.assertEqual(call.call_count,8)
                self.assertEqual(sum(c.topic_id == topic.id for c in chunks),8)
                self.assertEqual(sum(c.topic_id is None for c in chunks),4)

    def test_chunk_assignment_stops_before_new_call_after_deadline(self):
        with self.factory() as db:
            db.add(Topic(material_id=self.material_id,name="Test topic",description="Fixture"))
            db.add(LearningChunk(material_id=self.material_id,chunk_index=0,content="Test chunk"))
            db.commit()
            with patch("app.services.topic_chunk.time.monotonic",side_effect=[0,46]), patch("app.services.topic_chunk.match_chunk_to_topic") as call:
                chunks=assign_chunks_to_topics(self.material_id, db)
                call.assert_not_called()
                self.assertIsNone(chunks[0].topic_id)


class S5BackupTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "source" / "learning.db"
        self.database.parent.mkdir()
        self.db = sqlite3.connect(self.database)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE example(value TEXT)")
        self.db.execute("INSERT INTO example VALUES ('private-test')")
        self.db.commit()
        uploads = self.database.parent / "uploads"
        uploads.mkdir()
        (uploads/"sample.txt").write_text("isolated upload", encoding="utf-8")

    def test_live_wal_backup_and_empty_directory_restore(self):
        bundle = self.root/"bundle"
        manifest = backup(self.database, bundle)
        self.assertIn("uploads/sample.txt", manifest["files"])
        destination = self.root/"restored"
        restore(bundle, destination)
        with closing(sqlite3.connect(destination/"learning.db")) as db:
            self.assertEqual(db.execute("SELECT value FROM example").fetchone()[0], "private-test")
        self.assertEqual((destination/"uploads/sample.txt").read_text(), "isolated upload")
        with self.assertRaisesRegex(ValueError, "empty"):
            restore(bundle, destination)

    def test_backup_refuses_recursive_upload_destination(self):
        destination=self.database.parent/"uploads"/"recursive-backup"
        with self.assertRaisesRegex(ValueError,"outside uploads"):
            backup(self.database,destination)
        self.assertFalse(destination.exists())

    def test_corrupt_backup_refused_before_destination_write(self):
        bundle = self.root/"bundle"
        backup(self.database, bundle)
        (bundle/"uploads/sample.txt").write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            restore(bundle, self.root/"restored")
        self.assertFalse((self.root/"restored").exists())

    def test_traversal_manifest_refused(self):
        bundle = self.root/"bundle"
        backup(self.database, bundle)
        path = bundle/"manifest.json"
        data = json.loads(path.read_text())
        data["files"]["../outside"] = "invalid"
        (self.root/"outside").write_text("outside")
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            restore(bundle, self.root/"restored")

    def test_fresh_container_migration_and_repeat_backup_in_independent_directory(self):
        data = self.root/"deployment-data"
        env = {**os.environ, "APP_DATA_DIR":str(data), "APP_BACKUP_DIR":str(self.root/"snapshots"), "SQLITE_WAL":"true"}
        for _ in range(2):
            result = subprocess.run([sys.executable,"-X","utf8","-m","scripts.container_start"], env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
        with closing(sqlite3.connect(data/"learning.db")) as db:
            self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone()[0], "0005")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM achievements").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        self.assertEqual(len(list((self.root/"snapshots").glob("*/manifest.json"))), 1)
