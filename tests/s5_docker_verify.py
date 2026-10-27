"""Check only the named disposable test Compose project. No formal DB access."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import re
from uuid import uuid4
import httpx


PROJECT = os.getenv("S5_PROJECT", "zhixing-s5-20261026")
if not re.fullmatch(r"zhixing-(s5|s6|demo)-[a-z0-9-]+", PROJECT):
    raise RuntimeError("Only named disposable test projects are allowed")
COMPOSE = ["docker","compose","-p",PROJECT,"-f","compose.yaml","-f","deploy/compose.acceptance.yaml"]
if os.getenv("S5_COMPOSE_EXTRA"):
    COMPOSE += ["-f", os.environ["S5_COMPOSE_EXTRA"]]
ENV = {**os.environ,"APP_ENV_FILE":os.getenv("APP_ENV_FILE",".s5-local/acceptance.env"),"APP_PORT":os.getenv("APP_PORT","18080")}


def run(args):
    result = subprocess.run(args,env=ENV,capture_output=True,text=True,encoding="utf-8",errors="replace")
    if result.returncode:
        raise RuntimeError("Command failed: "+" ".join(args[:8])+"\n"+result.stderr[-1500:])
    return result.stdout


def python(code):
    return json.loads(run(COMPOSE+["exec","-T","app","python","-c",code]))


def snapshot():
    return python("import sqlite3,json; db=sqlite3.connect('/data/learning.db'); tables=['users','learning_materials','topics','questions','question_attempts','review_attempts','qa_histories','coach_sessions','admin_audit_logs']; print(json.dumps({t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in tables})); db.close()")


def main():
    report = {"source":"synthetic_docker_engineering_acceptance","created_at":datetime.now(timezone.utc).isoformat(),
              "project":PROJECT,"models":"mocked_provider_http","checks":[],"passed":False}
    def check(name, condition, details=None):
        report["checks"].append({"name":name,"passed":bool(condition),"details":details})
        if not condition:
            raise AssertionError(name)
    try:
        before = snapshot()
        report["counts_before_restart"] = before
        check("nonempty synthetic deployment", before["users"]>=3 and before["question_attempts"]>=3)
        isolated = python("import os,pathlib,json; import jieba; from app.services.lexical_retriever import tokenize; print(json.dumps({'uid':os.getuid(),'keys_in_code':pathlib.Path('/opt/learning/.env').exists(),'database_in_image':pathlib.Path('/opt/learning/learning.db').exists(),'research_in_image':pathlib.Path('/opt/learning/evaluation').exists(),'chinese_tokens':len(tokenize('依赖注入与学习资料'))}))")
        check("non-root image excludes private files and supports Chinese", isolated["uid"]==10001 and not any(isolated[k] for k in ("keys_in_code","database_in_image","research_in_image")) and isolated["chinese_tokens"]>0, isolated)
        app_id=run(COMPOSE+["ps","-q","app"]).strip()
        proxy_id=run(COMPOSE+["ps","-q","proxy"]).strip()
        inspections=[]
        for identity in (app_id,proxy_id):
            data=json.loads(run(["docker","inspect",identity]))[0]
            inspections.append({"service":data["Config"]["Labels"]["com.docker.compose.service"],
                "user":data["Config"]["User"],"read_only":data["HostConfig"]["ReadonlyRootfs"],
                "cap_drop":data["HostConfig"]["CapDrop"],"ports":data["HostConfig"]["PortBindings"],
                "image_id":data["Image"]})
        check("containers read-only and capabilities dropped", all(i["read_only"] and "ALL" in i["cap_drop"] for i in inspections), inspections)
        check("backend has no host port", not inspections[0]["ports"])
        bindings=inspections[1]["ports"]["8080/tcp"]
        check("proxy bound only to loopback", all(b["HostIp"]=="127.0.0.1" for b in bindings))
        run(COMPOSE+["exec","-T","proxy","nginx","-t"])
        check("nginx syntax", True)
        code = """import json,sqlite3
from uuid import uuid4
from pathlib import Path
from scripts.data_backup import backup,restore
bundle=Path('/backups')/('s5-restore-proof-'+uuid4().hex[:8])
manifest=backup('/data/learning.db',bundle)
destination=Path('/tmp/s5-restored')
result=restore(bundle,destination)
db=sqlite3.connect(destination/'learning.db')
counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['users','learning_materials','topics','questions','question_attempts','review_attempts','qa_histories','coach_sessions','admin_audit_logs']}
integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
db.close()
refused=False
try: restore(bundle,destination)
except ValueError: refused=True
print(json.dumps({'counts':counts,'integrity':integrity,'nonempty_refused':refused,'heads':result['sqlite_heads'],'backup_name':bundle.name}))"""
        restored=python(code)
        check("live WAL backup restores all rows", restored["counts"]==before and restored["integrity"]=="ok",restored)
        check("restore refuses overwriting data",restored["nonempty_refused"])
        # Exercise documented upgrade order: stop writers -> migrate/backup -> start.
        run(COMPOSE+["stop","proxy","app"])
        migration=run(COMPOSE+["run","--rm","--no-deps","migrate"])
        check("update creates pre-migration backup", "Pre-migration backup created" in migration)
        run(COMPOSE+["up","-d","--wait","--wait-timeout","90"])
        after=snapshot()
        report["counts_after_restart"]=after
        check("restart preserves users and learning rows",before==after)
        # Database schema agrees with ORM in the actual Linux container.
        run(COMPOSE+["exec","-T","app","python","-m","alembic","check"])
        check("alembic schema matches ORM",True)
        restore_compose=COMPOSE+["-f","deploy/compose.restore.yaml"]
        ENV["RESTORE_VOLUME_NAME"]=PROJECT+"-restore-"+uuid4().hex[:8]
        report["restored_volume"]=ENV["RESTORE_VOLUME_NAME"]
        run(COMPOSE+["stop","proxy","app"])
        run(restore_compose+["run","--rm","--no-deps","maintenance","python","-m","scripts.data_backup","restore",
                            "--backup","/backups/"+restored["backup_name"],"--target-data-dir","/data"])
        run(restore_compose+["up","-d","--wait","--wait-timeout","90"])
        check("restore overlay boots real application",snapshot()==before and
              httpx.get("http://127.0.0.1:"+ENV["APP_PORT"]+"/health/ready",timeout=10).status_code==200)
        report["environment"]={"docker_server":run(["docker","version","--format","{{.Server.Version}}"]).strip(),
            "compose":run(["docker","compose","version","--short"]).strip(),
            "runtime":python("import platform,json; print(json.dumps({'python':platform.python_version(),'system':platform.system(),'machine':platform.machine()}))")}
        report["passed"]=True
    except Exception as exc:
        report["failure"]=str(exc)
    path=Path(os.getenv("S5_REPORT", "evaluation/reports/s5/docker-deployment.json"))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"checks":len(report["checks"]),"failure":report.get("failure")},ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__=="__main__":
    main()
