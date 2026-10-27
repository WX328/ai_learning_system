"""Run and record backend and DOM regression tests without modifying learning data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=root/"evaluation"/"reports"/"s5")
    reports = parser.parse_args().output_dir.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    before = digest(root/"learning.db")
    commands = [
        ("backend", [sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"]),
        ("pip-check", [sys.executable, "-m", "pip", "check"]),
    ] + [(path.stem, ["node", "--experimental-vm-modules", str(path)]) for path in sorted((root/"tests").glob("frontend*.mjs"))]
    results = []
    for name, command in commands:
        started = time.monotonic()
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (reports/(name+".log")).write_text(result.stdout+result.stderr, encoding="utf-8")
        results.append({"name":name,"exit_code":result.returncode,"seconds":round(time.monotonic()-started,3),
                        "log":name+".log","command":command[1:]})
        print(name, result.returncode, flush=True)
    summary = {"created_at":datetime.now(timezone.utc).isoformat(),"source":"isolated_automated_regression",
        "models":"mocked_by_test_fixtures", "real_online_models":False,
        "formal_db_sha256_before":before, "formal_db_sha256_after":digest(root/"learning.db"),"results":results}
    (reports/"regression.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    raise SystemExit(0 if all(r["exit_code"]==0 for r in results) and before==summary["formal_db_sha256_after"] else 1)


if __name__ == "__main__":
    main()
