"""Boot the DEFAULT production Compose in a fresh local project. No model calls."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
from dotenv import dotenv_values
import httpx


def main():
    values=dotenv_values(".env")
    selected={k:v for k,v in values.items() if v is not None and
        (k.startswith("DEEPSEEK_") or k.startswith("DASHSCOPE_"))}
    selected["SECRET_KEY"]=secrets.token_urlsafe(48)
    path=Path(".s5-local/production-boot.env")
    path.parent.mkdir(exist_ok=True)
    # JSON string values are valid double-quoted dotenv values.
    path.write_text("\n".join(k+"="+json.dumps(v) for k,v in selected.items())+"\n",encoding="utf-8")
    env={**os.environ,"APP_ENV_FILE":str(path),"APP_PORT":"18081"}
    compose=["docker","compose","-p","zhixing-s5-production-20261026","-f","compose.yaml"]
    result=subprocess.run(compose+["up","-d","--wait","--wait-timeout","90"],env=env,capture_output=True,text=True,encoding="utf-8",errors="replace")
    report={"source":"synthetic_production_config_boot","created_at":datetime.now(timezone.utc).isoformat(),
        "models":"not_called","real_participants":0,"project":"zhixing-s5-production-20261026",
        "checks":[],"passed":False}
    try:
        assert result.returncode==0, "Production Compose did not become healthy"
        report["checks"].append("production Compose healthy using runtime HTTPS provider configuration")
        with httpx.Client(base_url="http://127.0.0.1:18081",timeout=10) as client:
            assert client.get("/health/ready").json()["status"]=="ready"
            assert client.get("/app").status_code==200
            assert client.get("/admin/users").status_code==401
            credential={"username":"s5-boot-"+secrets.token_hex(3),"password":secrets.token_urlsafe(24)}
            assert client.post("/users",json=credential).status_code==200
            token=client.post("/auth/login",data=credential).json()["access_token"]
            headers={"Authorization":"Bearer "+token}
            assert client.get("/auth/me",headers=headers).json()["role"]=="user"
            assert client.get("/admin/users",headers=headers).status_code==403
            assert client.get("/study/summary",headers=headers).json()["answered_count"]==0
        report["checks"]+=["readiness and frontend HTTP 200","anonymous admin denied 401",
                           "real registration/login/current user","ordinary user admin denied 403","fresh DB has no learning attempts"]
        report["passed"]=True
    except Exception as exc:
        report["failure"]=str(exc)
    finally:
        # Stop only this dedicated acceptance project; retain its named volumes.
        subprocess.run(compose+["stop"],env=env,capture_output=True)
    target=Path("evaluation/reports/s5/production-boot.json")
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"checks":len(report["checks"]),"failure":report.get("failure")}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__=="__main__":
    main()
