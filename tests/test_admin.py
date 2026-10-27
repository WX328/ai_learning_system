"""RBAC and status changes with real JWTs in an independent in-memory database."""
from datetime import datetime, timedelta, timezone
import unittest
import io
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.jwt import create_access_token, ALGORITHM, SECRET_KEY
from app.database import Base, get_db
from app.models import (AdminAuditLog, LearningMaterial, Question,
                        QuestionAttempt, User)
from app.routers import admin, auth, user, study, adaptive, question, rag, coach, learning_material
from app.schemas.user import UserCreate
from app.services.admin import bootstrap_admin, set_user_status


class AdminTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread":False})
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose); self.addCleanup(self.db.close)
        self.admin = User(username="admin-one", password_hash="HASH-SECRET", role="admin")
        self.user = User(username="learner", password_hash="HASH-SECRET", total_xp=120, level=2)
        self.disabled = User(username="disabled", password_hash="HASH-SECRET", is_active=False)
        self.db.add_all([self.admin,self.user,self.disabled]); self.db.flush()
        self.material = LearningMaterial(user_id=self.user.id,title="PRIVATE TITLE",content="PRIVATE CONTENT")
        self.db.add(self.material); self.db.flush()
        self.question = Question(material_id=self.material.id,question="PRIVATE QUESTION",answer="A",explanation="PRIVATE EXPLANATION")
        self.db.add(self.question); self.db.flush()
        self.db.add(QuestionAttempt(user_id=self.user.id,question_id=self.question.id,user_answer="A",is_correct=True))
        self.db.commit()
        self.app = FastAPI()
        for routes in (admin,auth,user,study,adaptive,question,rag,coach,learning_material):
            self.app.include_router(routes.router)
        self.app.dependency_overrides[get_db] = lambda:self.db
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.admin_id, self.user_id = self.admin.id, self.user.id
        self.headers = self.token(self.admin)
        self.old_user_token = self.token(self.user)

    def token(self, account):
        return {"Authorization":"Bearer " + create_access_token(account.id,account.auth_version)}

    def status(self, target, active, headers=None):
        return self.client.patch(f"/admin/users/{target}/status",headers=self.headers if headers is None else headers,json={"is_active":active})

    def get(self,path):
        response=self.client.get("/admin/"+path,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_all_admin_routes_require_login_and_server_role(self):
        for method,path,body in [("GET","/stats",None),("GET","/users",None),
                                  ("GET",f"/users/{self.user_id}",None),("GET","/audit-logs",None),
                                  ("PATCH",f"/users/{self.user_id}/status",{"is_active":False})]:
            for headers,expected in [({},401),(self.old_user_token,403)]:
                with self.subTest(path=path,expected=expected):
                    response=self.client.request(method,"/admin"+path,headers=headers,json=body)
                    self.assertEqual(response.status_code,expected,response.text)

    def test_search_pagination_filters_and_validation(self):
        data=self.get("users?page=1&page_size=2")
        self.assertEqual(data["total"],3); self.assertEqual(len(data["items"]),2)
        self.assertEqual(len(self.get("users?page=2&page_size=2")["items"]),1)
        self.assertEqual(self.get("users?search=learn&role=user&is_active=true")["total"],1)
        self.assertEqual(self.get("users?is_active=false")["items"][0]["id"],self.disabled.id)
        self.assertEqual(self.get("users?search=%25")["total"],0,"Search wildcards are literal")
        for query in ["page=0","page_size=101","role=owner","is_active=invalid"]:
            self.assertEqual(self.client.get("/admin/users?"+query,headers=self.headers).status_code,422)

    def test_safe_detail_and_real_statistics(self):
        detail=self.get(f"users/{self.user_id}")
        self.assertEqual(detail["statistics"]["material_count"],1)
        self.assertEqual(detail["statistics"]["answer_count"],1)
        self.assertEqual(detail["statistics"]["correct_rate"],100)
        stats=self.get("stats")
        self.assertEqual((stats["total_users"],stats["enabled_users"],stats["disabled_users"]),(3,2,1))
        self.assertEqual(stats["active_users_30d"],1)
        self.assertEqual(stats["material_count"],1); self.assertEqual(stats["question_count"],1)
        for path in ["users",f"users/{self.user_id}","stats","audit-logs"]:
            response=self.client.get("/admin/"+path,headers=self.headers)
            self.assertIn("no-store",response.headers["Cache-Control"])
            for secret in ["password_hash","HASH-SECRET","PRIVATE", "access_token", "auth_version"]:
                self.assertNotIn(secret,response.text)
        self.assertEqual(self.client.get("/admin/users/9999",headers=self.headers).status_code,404)

    def test_disable_revokes_old_tokens_on_learning_endpoints_and_reenable_does_not_restore_them(self):
        response=self.status(self.user_id,False)
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()["is_active"])
        for path in ["/auth/me","/study/summary","/learning-materials","/rag/history","/coach/sessions",
                     f"/adaptive/recommendation?material_id={self.material.id}"]:
            self.assertEqual(self.client.get(path,headers=self.old_user_token).status_code,401,path)
        self.assertEqual(self.client.post(f"/questions/{self.question.id}/answer",headers=self.old_user_token,json={"answer":"A"}).status_code,401)
        self.assertEqual(self.status(self.user_id,True).status_code,200)
        self.assertEqual(self.client.get("/auth/me",headers=self.old_user_token).status_code,401)
        fresh=self.token(self.db.get(User,self.user_id))
        self.assertEqual(self.client.get("/study/summary",headers=fresh).status_code,200)
        self.assertEqual(self.db.get(User,self.user_id).total_xp,120)
        self.assertEqual(self.db.query(QuestionAttempt).count(),1)

    @patch("app.routers.auth.verify_password",return_value=True)
    def test_disabled_account_cannot_login_even_with_correct_password(self,_verify):
        response=self.client.post("/auth/login",data={"username":self.disabled.username,"password":"never-logged"})
        self.assertEqual(response.status_code,401)
        self.assertNotIn("access_token",response.json())

    @patch("app.routers.auth.verify_password",return_value=True)
    def test_fresh_login_includes_current_revocation_version(self,_verify):
        self.status(self.user_id,False); self.status(self.user_id,True)
        response=self.client.post("/auth/login",data={"username":"learner","password":"never-logged"})
        self.assertEqual(response.status_code,200,response.text)
        token=response.json()["access_token"]
        self.assertEqual(jwt.decode(token,SECRET_KEY,algorithms=[ALGORITHM])["ver"],2)
        me=self.client.get("/auth/me",headers={"Authorization":"Bearer "+token})
        self.assertEqual(me.json()["role"],"user")

    def test_registration_and_payloads_cannot_set_roles(self):
        body={"username":"new-learner","password":"a unique strong phrase for testing"}
        for extra in [{"role":"admin"},{"is_active":True},{"auth_version":9},{"password_hash":"evil"}]:
            self.assertEqual(self.client.post("/users",json={**body,**extra}).status_code,422)
        created=self.client.post("/users?role=admin&is_active=true",json=body)
        self.assertEqual(created.status_code,200,created.text)
        saved=self.db.get(User,created.json()["id"])
        self.assertEqual(saved.role,"user"); self.assertTrue(saved.is_active)
        self.assertEqual(self.client.patch(f"/users/{self.user_id}",headers=self.old_user_token,json={"role":"admin"}).status_code,404)
        invalid=self.client.patch(f"/admin/users/{self.user_id}/status",headers=self.headers,json={"is_active":False,"role":"admin"})
        self.assertEqual(invalid.status_code,422)
        for value in ["false",0,None]:
            self.assertEqual(self.status(self.user_id,value).status_code,422)

    def test_jwt_role_claim_is_ignored_and_tampering_rejected(self):
        payload={"sub":str(self.user_id),"role":"admin","is_active":True,"exp":datetime.now(timezone.utc)+timedelta(hours=1)}
        for secret,expected in [(SECRET_KEY,403),("wrong-secret-for-test",401)]:
            token=jwt.encode(payload,secret,algorithm=ALGORITHM)
            self.assertEqual(self.client.get("/admin/stats",headers={"Authorization":"Bearer "+token}).status_code,expected)
        self.status(self.user_id,False)
        self.assertEqual(self.client.get("/auth/me",headers={"Authorization":"Bearer "+jwt.encode(payload,SECRET_KEY,algorithm=ALGORITHM)}).status_code,401)

    def test_last_admin_and_self_protection_are_audited(self):
        response=self.status(self.admin_id,False)
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.get("audit-logs")["items"][0]["result"],"denied_last_admin")
        other=User(username="admin-two",password_hash="HASH",role="admin")
        self.db.add(other); self.db.commit()
        self.assertEqual(self.status(self.admin_id,False).status_code,409)
        self.assertEqual(self.get("audit-logs")["items"][0]["result"],"denied_self")
        self.assertEqual(self.status(other.id,False).status_code,200)
        self.assertTrue(self.db.get(User,self.admin_id).is_active)
        self.assertEqual(self.status(self.admin_id,False).status_code,409)

    def test_status_change_and_repeated_request_are_auditable(self):
        self.assertEqual(self.status(self.user_id,False).status_code,200)
        version=self.db.get(User,self.user_id).auth_version
        self.assertEqual(self.status(self.user_id,False).status_code,200)
        self.assertEqual(self.db.get(User,self.user_id).auth_version,version)
        logs=self.get("audit-logs?page_size=1")
        self.assertEqual(logs["total"],2); self.assertEqual(logs["items"][0]["result"],"unchanged")
        changed=self.get("audit-logs?page=2&page_size=1")["items"][0]
        self.assertEqual(changed["actor_user_id"],self.admin_id)
        self.assertEqual(changed["target_user_id"],self.user_id)
        self.assertTrue(changed["before_active"]); self.assertFalse(changed["after_active"])
        self.assertTrue(changed["created_at"].endswith("+00:00"))

    def test_failed_audit_commit_rolls_back_account_change(self):
        with patch.object(self.db,"commit",side_effect=RuntimeError("database unavailable")):
            with self.assertRaises(RuntimeError):
                set_user_status(self.db,self.admin_id,0,self.user_id,False)
        self.assertTrue(self.db.get(User,self.user_id).is_active)
        self.assertEqual(self.db.query(AdminAuditLog).count(),0)

    def test_mutation_rechecks_actor_after_acquiring_write_lock(self):
        self.admin.is_active=False; self.db.commit()
        with self.assertRaises(Exception) as caught:
            set_user_status(self.db,self.admin_id,0,self.user_id,False)
        self.assertEqual(caught.exception.status_code,401)
        self.assertTrue(self.db.get(User,self.user_id).is_active)


class AdminBootstrapTest(unittest.TestCase):
    def test_bootstrap_creates_one_admin_and_audit_and_refuses_reuse(self):
        engine=create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        with sessionmaker(bind=engine)() as db:
            with patch("app.services.admin.hash_password",return_value="argon2-digest"):
                first=bootstrap_admin(db,"first-admin","a unique runtime passphrase")
                with self.assertRaises(ValueError):
                    bootstrap_admin(db,"second-admin","another unique runtime passphrase")
            self.assertEqual(db.query(User).count(),1)
            self.assertEqual(db.get(User,first).role,"admin")
            self.assertEqual(db.get(User,first).password_hash,"argon2-digest")
            self.assertEqual(db.query(AdminAuditLog).one().action,"bootstrap_admin")

    def test_cli_refuses_noninteractive_credentials_without_printing_secrets(self):
        from scripts.init_admin import main
        with patch("scripts.init_admin.sys.stdin.isatty",return_value=False), patch("scripts.init_admin.getpass.getpass") as prompt:
            self.assertEqual(main(),1); prompt.assert_not_called()

    def test_registration_schema_forbids_extra_role_fields(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            UserCreate(username="a-user",password="a valid unique passphrase",role="admin")

    def test_cli_validates_without_echoing_sensitive_input(self):
        from scripts.init_admin import main
        engine=create_engine("sqlite://");Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        with sessionmaker(bind=engine)() as db:
            output=io.StringIO()
            with patch("scripts.init_admin.sys.stdin.isatty",return_value=True), patch(
                    "scripts.init_admin.SessionLocal",return_value=db), patch(
                    "scripts.init_admin.MigrationContext.configure") as context, patch(
                    "scripts.init_admin.ScriptDirectory.from_config") as directory, patch(
                    "scripts.init_admin.getpass.getpass",side_effect=["runtime-admin","short-secret","short-secret"]), patch(
                    "scripts.init_admin.sys.stderr",output):
                context.return_value.get_current_heads.return_value=("0005",)
                directory.return_value.get_heads.return_value=("0005",)
                self.assertEqual(main(),1)
            self.assertNotIn("short-secret",output.getvalue())
            self.assertEqual(db.query(User).count(),0)
