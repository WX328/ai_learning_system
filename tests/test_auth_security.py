"""Authentication rejects malformed tokens and throttles repeated guesses."""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.jwt import ALGORITHM, SECRET_KEY
from app.core.login_throttle import LoginThrottle
from app.database import Base, get_db
from app.models import User
from app.routers.auth import router
from app.schemas.user import UserCreate


class AuthenticationSecurityTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        self.db = sessionmaker(bind=engine)()
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.db.add(User(username="learner", password_hash="mocked"))
        self.db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_malformed_subject_returns_401(self):
        for subject in ("not-a-number", "-1", "0", "9" * 30):
            token = jwt.encode({"sub": subject}, SECRET_KEY, algorithm=ALGORITHM)
            response = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 401, subject)

    def test_login_returns_429_after_failed_attempts(self):
        limiter = LoginThrottle(account_limit=2, address_limit=10)
        with patch("app.routers.auth.login_throttle", limiter), patch(
                "app.routers.auth.verify_password", return_value=False):
            statuses = [self.client.post("/auth/login", data={
                "username": "learner", "password": "wrong",
            }).status_code for _ in range(3)]
        self.assertEqual(statuses, [401, 401, 429])

    def test_window_expires(self):
        now = [0.0]
        limiter = LoginThrottle(window_seconds=60, account_limit=2,
                                address_limit=3, clock=lambda: now[0])
        for _ in range(2):
            self.assertTrue(limiter.allowed("learner", "test-ip"))
            limiter.failed("learner", "test-ip")
        self.assertFalse(limiter.allowed("learner", "other-ip"))
        now[0] = 61.0
        self.assertTrue(limiter.allowed("learner", "test-ip"))

    def test_registration_rejects_short_and_obvious_passwords(self):
        for password in ("too-short", "password123456789", "a" * 15):
            with self.assertRaises(ValidationError):
                UserCreate(username="learner", password=password)
        valid = UserCreate(username=" learner ", password="a long unique passphrase 2026")
        self.assertEqual(valid.username, "learner")
