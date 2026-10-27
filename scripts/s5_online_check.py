"""Opt-in live provider acceptance in a fresh temporary database.

Uses local .env credentials at runtime, may incur provider charges.
Never connects to the formal learning.db; deletes synthetic data on exit.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

from dotenv import load_dotenv
import httpx
from scripts.s5_acceptance import Acceptance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True,
                        help="Explicitly enable calls billed by configured providers")
    parser.add_argument("--report", type=Path, default=Path("evaluation/reports/s5/online.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root/".env")
    env = dict(os.environ)
    for name in ("SECRET_KEY","DEEPSEEK_API_KEY","DASHSCOPE_API_KEY","DASHSCOPE_EMBEDDING_BASE_URL"):
        if not env.get(name):
            parser.error("Missing runtime configuration: "+name)
    # Ignore any previous test substitution. Both live URLs must be HTTPS.
    from urllib.parse import urlparse
    env["DEEPSEEK_BASE_URL"] = env.get("DEEPSEEK_BASE_URL","https://api.deepseek.com")
    for name in ("DEEPSEEK_BASE_URL","DASHSCOPE_EMBEDDING_BASE_URL"):
        if urlparse(env[name]).scheme != "https":
            parser.error("Live verification requires HTTPS: "+name)
    accounts = {kind:{"username":"s5-live-"+kind+"-"+secrets.token_hex(3),"password":secrets.token_urlsafe(24)}
                for kind in ("admin","learner","other")}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port = sock.getsockname()[1]
    failure, check = None, None
    with tempfile.TemporaryDirectory(prefix="zhixing-s5-live-", ignore_cleanup_errors=True) as folder:
        data = Path(folder)
        env.update(APP_ENV="production", APP_DATA_DIR=str(data/"data"),
                   APP_BACKUP_DIR=str(data/"backups"), SQLITE_WAL="true", SECRET_KEY=secrets.token_urlsafe(48))
        setup = subprocess.run([sys.executable,"-m","scripts.container_start"],cwd=root,env=env,capture_output=True)
        if setup.returncode:
            raise RuntimeError("Isolated migration failed")
        bootstrap = "import json,sys; from app.database import SessionLocal; from app.services.admin import bootstrap_admin; c=json.load(sys.stdin); db=SessionLocal(); bootstrap_admin(db,c['username'],c['password']); db.close()"
        result = subprocess.run([sys.executable,"-c",bootstrap],input=json.dumps(accounts["admin"]).encode(),
                                cwd=root,env=env,capture_output=True)
        if result.returncode:
            raise RuntimeError("Isolated admin fixture failed")
        with (data/"server.log").open("wb") as log:
            process = subprocess.Popen([sys.executable,"-m","uvicorn","app.main:app","--host","127.0.0.1","--port",str(port)],
                cwd=root,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(80):
                    if process.poll() is not None:
                        raise RuntimeError("Isolated server exited")
                    try:
                        if httpx.get(base+"/health/ready",timeout=1).status_code==200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.2)
                check = Acceptance(base, accounts, "live_provider")
                check.run()
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}" if isinstance(exc,AssertionError) else type(exc).__name__
            finally:
                if check:
                    check.client.close()
                if os.name == "nt":
                    # The Windows venv launcher can own a Python child process.
                    subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True)
                else:
                    process.terminate()
                process.wait(timeout=15)
    report = {"created_at":datetime.now(timezone.utc).isoformat(),"source":"synthetic_engineering_acceptance",
        "transport":"real HTTP, JWT, temporary SQLite","models":"live_provider",
        "providers":["configured DeepSeek HTTPS","configured Bailian HTTPS"],
        "real_participants":0,"learning_effect_evaluated":False,
        "passed":failure is None,"failure":failure,"steps":check.steps if check else [],
        "note":"Provider response success verifies integration only; content accuracy and learning benefit are not established."}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"steps":len(report["steps"]),"failure":failure},ensure_ascii=False))
    raise SystemExit(0 if failure is None else 1)


if __name__ == "__main__":
    main()
