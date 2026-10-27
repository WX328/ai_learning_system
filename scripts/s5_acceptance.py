"""Real HTTP/JWT/SQLite workflow checks. Provider source must be explicitly labelled.

Run ONLY against a disposable deployment. Registers synthetic accounts and toggles
their status; never run against a database containing real learners.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx

NOTES = """FastAPI 学习资料（工程验收用合成资料，不是学习实验）。
依赖注入：FastAPI 使用 Depends 声明依赖，框架调用依赖函数并注入返回值。
依赖函数可以提供数据库 Session、当前登录用户和权限验证。
检索增强生成：资料先分块并生成向量。查询也转为向量，检索相似片段，
然后将证据片段和问题传给语言模型，回答应引用资料来源。
JWT 认证：服务端签名 Token，认证请求必须验证签名、有效期和用户状态。
用户只能访问属于自己的学习资料。管理员权限必须在服务端验证。
账号禁用后，旧 Token 不能继续操作；重新启用后需要重新登录。
"""


class Acceptance:
    def __init__(self, url, credentials, source):
        self.client = httpx.Client(base_url=url, timeout=180)
        self.credentials, self.source = credentials, source
        self.steps, self.tokens = [], {}

    def call(self, name, method, path, *, as_user=None, expected=200, **kwargs):
        time.sleep(.24)  # Cooperate with the local proxy's per-address limit.
        headers = {}
        if as_user:
            headers["Authorization"] = "Bearer " + self.tokens[as_user]
        started = time.monotonic()
        response = self.client.request(method, path, headers=headers, **kwargs)
        self.steps.append({"name": name, "status": response.status_code,
                           "expected": expected, "passed": response.status_code == expected,
                           "seconds": round(time.monotonic()-started, 3)})
        if response.status_code != expected:
            raise AssertionError(f"{name}: HTTP {response.status_code}, expected {expected}")
        return response.json() if response.content else None

    def verify(self, name, result):
        self.steps.append({"name": name, "passed": bool(result), "kind": "assertion"})
        if not result:
            raise AssertionError(name)

    def login(self, account, name):
        credential = self.credentials[account]
        data = self.call(name, "POST", "/auth/login", data=credential)
        self.tokens[account] = data["access_token"]

    def run(self):
        self.call("readiness", "GET", "/health/ready")
        for path in ("/auth/me", "/admin/users", "/admin/stats", "/admin/audit-logs"):
            self.call("anonymous denied " + path, "GET", path, expected=401)
        for account in ("learner", "other"):
            self.call("register " + account, "POST", "/users", json=self.credentials[account])
            self.login(account, "login " + account)
        forged = {**self.credentials["learner"], "username":"forged-"+uuid4().hex[:8], "role":"admin"}
        self.call("registration cannot set role", "POST", "/users", json=forged, expected=422)
        self.call("learner admin denied", "GET", "/admin/users", as_user="learner", expected=403)
        self.login("admin", "admin login")
        admin = self.call("admin identity", "GET", "/auth/me", as_user="admin")
        learner = self.call("learner identity", "GET", "/auth/me", as_user="learner")
        self.verify("DB role is user", learner["role"] == "user")
        upload = self.call("upload TXT", "POST", "/learning-materials/upload", as_user="learner",
                           files={"files":("s5-notes.txt", NOTES.encode(), "text/plain")})
        material = upload[0] if isinstance(upload, list) else upload["materials"][0]
        mid = material["id"]
        self.call("vector index", "POST", f"/learning-materials/{mid}/index", as_user="learner")
        topics = self.call("extract topics", "POST", f"/learning-materials/{mid}/extract-topics", as_user="learner")
        self.verify("topics saved", len(topics) >= 1)
        repeated = self.call("topics idempotent", "POST", f"/learning-materials/{mid}/extract-topics", as_user="learner")
        self.verify("topic IDs stable", [t["id"] for t in topics] == [t["id"] for t in repeated])
        rec = self.call("new topic recommendation", "GET", f"/adaptive/recommendation?material_id={mid}", as_user="learner")
        self.verify("no history is unknown", rec["mastery_score"] is None and rec["recent_correct_rate"] is None)
        rag = self.call("RAG ask", "POST", "/rag/ask", as_user="learner",
                        json={"material_id":mid, "query":"FastAPI 如何通过 Depends 实现依赖注入？"})
        self.verify("RAG answered with evidence", rag["status"] == "answered" and bool(rag["sources"]))
        q = self.call("generate topic question", "POST", "/questions/generate", as_user="learner",
                      json={"material_id":mid, "topic_id":topics[0]["id"], "topic":topics[0]["name"], "count":1, "difficulty":2})[0]
        self.verify("question hides answer", "answer" not in q and q["topic_id"] == topics[0]["id"])
        result = self.call("submit answer and local feedback", "POST", f"/questions/{q['id']}/answer",
                           as_user="learner", json={"answer":"B"})
        self.verify("local feedback durable", bool(result["feedback"]))
        self.call("duplicate first answer denied", "POST", f"/questions/{q['id']}/answer",
                  as_user="learner", json={"answer":"B"}, expected=400)
        self.call("optional model feedback", "POST", f"/questions/{q['id']}/feedback", as_user="learner")
        self.call("cached feedback", "POST", f"/questions/{q['id']}/feedback", as_user="learner")
        xp_before = self.call("XP and achievements", "GET", "/study/summary", as_user="learner")
        self.verify("answer count and seeded achievement XP", xp_before["answered_count"] == 1 and xp_before["total_xp"] >= 5)
        if not result["is_correct"]:
            mistakes = self.call("mistake list", "GET", "/study/mistakes", as_user="learner")
            correct = next(m["correct_answer"] for m in mistakes if m["id"] == q["id"])
            payload = {"request_id":str(uuid4()), "answer":correct}
            review = self.call("correct mistake review", "POST", f"/study/mistakes/{q['id']}/review",
                               as_user="learner", json=payload)
            self.call("review idempotent", "POST", f"/study/mistakes/{q['id']}/review", as_user="learner", json=payload)
            self.verify("review XP stays zero", review["is_correct"] and review["earned_xp"] == 0)
            after = self.call("XP after review", "GET", "/study/summary", as_user="learner")
            self.verify("review does not farm XP", after["total_xp"] == xp_before["total_xp"] and after["review_count"] == 1)
        else:
            self.steps.append({"name":"mistake review", "status":"not_exercised_correct_live_answer"})
        knowledge = self.call("knowledge map", "GET", "/study/map", as_user="learner")
        nodes = next(m for m in knowledge if m["id"] == mid)["topics"]
        self.verify("rules_v2 mastery updated", next(t for t in nodes if t["id"] == q["topic_id"])["mastery_score"] is not None)
        rec = self.call("recommendation refresh", "GET", f"/adaptive/recommendation?material_id={mid}", as_user="learner")
        node = next(t for t in nodes if t["id"] == rec["topic"]["id"])
        self.verify("map and recommendation agree", node["mastery_score"] == rec["mastery_score"])
        adaptive = self.call("adaptive next question", "GET", f"/adaptive/next-question?material_id={mid}", as_user="learner")
        pending = self.call("reuse pending adaptive question", "GET", f"/adaptive/next-question?material_id={mid}", as_user="learner")
        self.verify("pending question reused", adaptive["question"]["id"] == pending["question"]["id"])
        self.call("adaptive answer", "POST", f"/questions/{adaptive['question']['id']}/answer",
                  as_user="learner", json={"answer":"A"})
        coach = self.call("coach plan", "POST", "/coach/sessions", as_user="learner",
                          json={"request_id":str(uuid4()), "material_id":mid, "goal":"理解 Depends 并练习", "minutes":10})
        sid = coach["id"]
        def turn(action, **values):
            nonlocal coach
            coach = self.call("coach "+action, "POST", f"/coach/sessions/{sid}/turns", as_user="learner",
                json={"request_id":str(uuid4()), "revision":coach["revision"], "action":action, **values})
        turn("message", message="解释 Depends 依赖注入")
        self.verify("coach explanation not degraded", not coach["state"]["degraded"])
        turn("message", message="请给我一道练习")
        self.verify("coach practice question exists", coach["question"] is not None)
        turn("answer", answer="A")
        turn("finish")
        self.verify("coach finished", coach["status"] == "completed")
        records = self.call("learning records", "GET", "/study/records", as_user="learner")
        self.verify("records include answer and chat", {"answer","chat"}.issubset({r["type"] for r in records}))
        for method, path, payload in (
            ("GET",f"/learning-materials/{mid}/topics",None),
            ("GET",f"/adaptive/recommendation?material_id={mid}",None),
            ("POST","/rag/ask",{"material_id":mid,"query":"Depends"}),
            ("POST",f"/questions/{q['id']}/answer",{"answer":"A"}),
            ("GET",f"/coach/sessions/{sid}",None),
        ):
            options = {"json":payload} if payload else {}
            self.call("cross-user denied "+path, method, path, as_user="other",
                      expected=403 if path.startswith("/questions/") else 404, **options)
        users = self.call("admin pagination search", "GET", "/admin/users?page=1&page_size=1&search="+learner["username"], as_user="admin")
        self.verify("user filter", users["total"] == 1)
        detail = self.call("admin minimal user detail", "GET", f"/admin/users/{learner['id']}", as_user="admin")
        self.verify("private content excluded", not {"password_hash","token","content","messages"}.intersection(detail))
        self.call("admin stats", "GET", "/admin/stats", as_user="admin")
        self.call("self or last admin disable denied", "PATCH", f"/admin/users/{admin['id']}/status", as_user="admin",
                  json={"is_active":False}, expected=409)
        self.call("disable learner", "PATCH", f"/admin/users/{learner['id']}/status", as_user="admin", json={"is_active":False})
        self.call("old JWT disabled", "GET", "/study/summary", as_user="learner", expected=401)
        self.call("disabled login denied", "POST", "/auth/login", data=self.credentials["learner"], expected=401)
        self.call("enable learner", "PATCH", f"/admin/users/{learner['id']}/status", as_user="admin", json={"is_active":True})
        self.call("old JWT still revoked", "GET", "/auth/me", as_user="learner", expected=401)
        self.login("learner", "fresh login after enable")
        self.call("data retained", "GET", "/study/summary", as_user="learner")
        audit = self.call("admin audit", "GET", "/admin/audit-logs?page_size=100", as_user="admin")
        self.verify("changes audited", {"disable_user","enable_user"}.issubset({r["action"] for r in audit["items"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--credentials-file", type=Path, required=True,
                        help="Private JSON {admin,learner,other}: {username,password}; never commit")
    parser.add_argument("--model-source", choices=["mocked_provider_http","live_provider"], required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    credentials = json.loads(args.credentials_file.read_text(encoding="utf-8"))
    for name in ("learner", "other"):
        credentials[name]["username"] += "-"+uuid4().hex[:5]
    check = Acceptance(args.base_url, credentials, args.model_source)
    failure = None
    try:
        check.run()
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}" if isinstance(exc, AssertionError) else type(exc).__name__
    finally:
        check.client.close()
    report = {"created_at":datetime.now(timezone.utc).isoformat(), "source":"synthetic_engineering_acceptance",
        "transport":"real HTTP, JWT, SQLite", "models":args.model_source,
        "real_participants":0, "learning_effect_evaluated":False, "passed":failure is None,
        "failure":failure, "steps":check.steps}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"checks":len(check.steps),"failure":failure},ensure_ascii=False))
    raise SystemExit(0 if failure is None else 1)


if __name__ == "__main__":
    main()
