"""Release tooling only: temporary Git repos, no learning DB or providers."""
import contextlib
import io
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import unittest

from scripts.audit_portfolio import audit, findings_for, private_path
from scripts.prepare_portfolio import is_public_path, prepare


class PortfolioAuditTests(unittest.TestCase):
    def test_runtime_match_is_redacted(self):
        secret = secrets.token_urlsafe(32).encode()
        result = findings_for(b"prefix " + secret, (secret,))
        self.assertEqual(result, ["matches_local_runtime_credential"])
        self.assertNotIn(secret.decode(), json.dumps(result))

    def test_provider_and_jwt_shapes(self):
        self.assertIn("provider_key_candidate", findings_for(b"sk-" + b"Q" * 32))
        token = b"eyJ" + b"a" * 20 + b"." + b"b" * 20 + b"." + b"c" * 20
        self.assertIn("jwt_literal_candidate", findings_for(token))

    def test_placeholder_is_not_a_live_key(self):
        self.assertEqual(findings_for(b"sk-" + b"placeholder" * 3), [])

    def test_private_path_and_safe_templates(self):
        for name in (".env", ".env.production", "learning.db", "db.sqlite3-wal",
                     ".evaluation-private/study/records.csv", ".s6-local/credentials.json", "secret.pem"):
            self.assertTrue(private_path(name), name)
        for name in (".env.example", ".env.docker.example", "app/database.py", "frontend/icons.svg"):
            self.assertFalse(private_path(name), name)

    def test_database_header(self):
        self.assertEqual(findings_for(b"SQLite format 3\x00dummy"), ["sqlite_database"])

    def test_private_key_needs_payload_not_just_scanner_header(self):
        header = b"-----BEGIN " + b"PRIVATE KEY-----"
        footer = b"-----END " + b"PRIVATE KEY-----"
        self.assertNotIn("private_key_material", findings_for(header))
        self.assertIn("private_key_material", findings_for(header+b"\n"+b"A"*64+b"\n"+footer))

    def test_export_whitelist(self):
        for name in (".git/config", ".vscode/settings.json", ".env", "learning.db", ".s6-local/credentials.json",
                     "evaluation/reports/s5/browser/failure.png", "../outside.md", "personal/records.csv"):
            self.assertFalse(is_public_path(name), name)
        for name in ("README.md", ".env.example", "app/main.py", "deploy/Dockerfile.stub", "deploy/nginx.conf", "docs/portfolio/architecture.svg"):
            self.assertTrue(is_public_path(name), name)

    def test_export_never_overwrites_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "never overwritten"):
                prepare(Path(directory), Path(directory))

    def test_export_copies_nginx_and_excludes_even_tracked_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"source"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            (root/"deploy").mkdir()
            (root/"deploy/nginx.conf").write_text("events {}\n", encoding="utf-8")
            (root/"README.md").write_text("public fixture\n", encoding="utf-8")
            (root/".env").write_text("SECRET_KEY="+secrets.token_urlsafe(32), encoding="utf-8")
            (root/"learning.db").write_bytes(b"SQLite format 3\x00fixture")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
            output = Path(directory)/"snapshot"
            manifest = prepare(root, output)
            self.assertEqual((output/"deploy/nginx.conf").read_text(), "events {}\n")
            self.assertFalse((output/".env").exists())
            self.assertFalse((output/"learning.db").exists())
            self.assertFalse((output/".git").exists())
            self.assertEqual({f["path"] for f in manifest["files"]}, {"README.md", "deploy/nginx.conf"})

    def test_export_rejects_credential_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"source"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            (root/"README.md").write_text("sk-"+secrets.token_hex(20), encoding="utf-8")
            output = Path(directory)/"snapshot"
            with self.assertRaisesRegex(ValueError, "Credential"):
                prepare(root, output)
            self.assertFalse(output.exists())

    def test_deleted_historical_secret_and_unstaged_secret_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
            git("init", "--initial-branch=main")
            git("config", "user.name", "Release Fixture")
            git("config", "user.email", "fixture@example.invalid")
            secret = "sk-" + secrets.token_hex(20)
            (root/"old.py").write_text("API_KEY = '" + secret + "'\n", encoding="utf-8")
            git("add", "old.py")
            git("commit", "-m", "temporary fixture")
            git("rm", "old.py")
            (root/"safe.txt").write_text("public fixture\n", encoding="utf-8")
            git("add", "safe.txt")
            git("commit", "-m", "remove fixture key")
            (root/".env").write_text("DEEPSEEK_API_KEY=" + secret + "\n", encoding="utf-8")
            (root/".gitignore").write_text(".env\n", encoding="utf-8")
            (root/"safe.txt").write_text(secret + "\n", encoding="utf-8")
            before = git("status", "--porcelain=v1").stdout
            with contextlib.redirect_stdout(io.StringIO()) as output:
                report = audit(root)
            self.assertEqual(before, git("status", "--porcelain=v1").stdout)
            self.assertEqual(report["counts"]["reachable_commits"], 2)
            self.assertTrue(any(f["scope"] == "reachable_history" and f["type"] == "matches_local_runtime_credential"
                                for f in report["findings"]))
            self.assertTrue(any(f["scope"] == "working_tree" and f["path"] == "safe.txt" for f in report["findings"]))
            self.assertNotIn(secret, json.dumps(report) + output.getvalue())


if __name__ == "__main__":
    unittest.main()
