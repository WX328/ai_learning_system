"""Inject random test credentials ONLY into a named disposable test project."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import re


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="zhixing-s5-20261026")
    project=parser.parse_args().project
    if not re.fullmatch(r"zhixing-(s5|s6|demo)-[a-z0-9-]+", project):
        raise SystemExit("Only named disposable s5/s6/demo projects are allowed")
    credentials=json.loads(Path(".s5-local/acceptance-credentials.json").read_text(encoding="utf-8"))
    env={**os.environ,"APP_ENV_FILE":".s5-local/acceptance.env","APP_PORT":os.getenv("APP_PORT","18080")}
    code = """import json,os,sys
assert os.getenv('APP_ENV')=='test', 'Fixture refused outside test deployment'
from app.database import SessionLocal
from app.services.admin import bootstrap_admin
credential=json.load(sys.stdin)
with SessionLocal() as db:
    bootstrap_admin(db,credential['username'],credential['password'])
print('Isolated test fixture initialized')
"""
    result=subprocess.run(["docker","compose","-p",project,"-f","compose.yaml",
        "-f","deploy/compose.acceptance.yaml","exec","-T","app","python","-c",code],
        input=json.dumps(credentials["admin"]),text=True,encoding="utf-8",env=env,capture_output=True)
    print("Isolated test fixture initialized" if result.returncode==0 else
          "Fixture not created. Verify test project, migration and whether already initialized.")
    raise SystemExit(result.returncode)


if __name__=="__main__":
    main()
