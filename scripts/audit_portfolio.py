"""Read-only Git release audit. Reports locations/types, NEVER matched secrets.

Covers working candidates, index, all commits reachable from local refs and their
messages. Not a credential validity check, binary OCR or a remote hosting audit.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess


PLACEHOLDER = re.compile(r"(?i)(example|placeholder|change[-_ ]?me|replace|your[-_ ]|test|mock|stub|dummy|development|engineering|^x+$|^\*+$|填写|替换)")
PROVIDER = re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")
OTHER_KEY = re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b")
JWT = re.compile(rb"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b")
ASSIGNMENT = re.compile(rb'''(?i)(?:["']?(?:[A-Z_]*API_KEY|SECRET_KEY|PASSWORD|ACCESS_TOKEN|PRIVATE_KEY)["']?)\s*[:=]\s*["']([^\r\n"']{8,})["']''')
PRIVATE_PARTS = {".evaluation-private", ".s5-local", ".s6-local", ".backups", ".private-backups", ".taste-skill", ".ua"}


def private_path(name):
    path = Path(name)
    return (bool(set(path.parts) & PRIVATE_PARTS)
            or bool(re.search(r"(?i)\.(?:db|sqlite|sqlite3)(?:[.-].*)?$", name))
            or (path.name.startswith(".env") and not path.name.endswith(".example"))
            or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"})


def findings_for(data, known=()):
    """Return no raw matches or secret fingerprints; identical types are deduped."""
    result = set()
    for value in known:
        if value in data:
            result.add("matches_local_runtime_credential")
    for match in PROVIDER.finditer(data):
        if not PLACEHOLDER.search(match[0].decode("ascii")):
            result.add("provider_key_candidate")
    if JWT.search(data):
        result.add("jwt_literal_candidate")
    if OTHER_KEY.search(data):
        result.add("other_service_key_candidate")
    if re.search(rb"-----BEGIN (?:RSA )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{32,}-----END (?:RSA )?PRIVATE KEY-----", data):
        result.add("private_key_material")
    for match in ASSIGNMENT.finditer(data):
        value = match[1].decode("utf-8", errors="replace")
        if not PLACEHOLDER.search(value) and not value.startswith(("os.", "${", "{", "<")):
            result.add("credential_literal_review")
    if data.startswith(b"SQLite format 3\x00"):
        result.add("sqlite_database")
    return sorted(result)


def git(root, *args, ok=(0,)):
    result = subprocess.run(["git", "-C", str(root), *args], cwd=root, capture_output=True)
    if result.returncode not in ok:
        # Git errors could quote URLs/content. Never relay arbitrary stderr.
        raise RuntimeError("Git command failed: " + args[0] + " (exit " + str(result.returncode) + ")")
    return result


def runtime_values(root):
    values = set()
    for path in (root / ".env", root / ".env.docker"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.partition("=")
            value = value.strip().strip("\"'")
            if sep and re.search(r"(KEY|PASSWORD|TOKEN|SECRET)$", key.strip()) and len(value) >= 16 and not PLACEHOLDER.search(value):
                values.add(value.encode())
    return values


def audit(root):
    known = runtime_values(root)
    tracked = git(root, "ls-files", "-z").stdout.decode().split("\0")[:-1]
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout.decode().split("\0")[:-1]
    candidates = sorted(set(tracked + untracked))
    findings = []
    for name in candidates:
        path = root / name
        if private_path(name):
            findings.append({"scope": "working_tree", "path": name, "type": "private_file_candidate"})
        if path.is_symlink():
            findings.append({"scope": "working_tree", "path": name, "type": "symlink_manual_review"})
            continue
        if path.is_file():
            for kind in findings_for(path.read_bytes(), known):
                findings.append({"scope": "working_tree", "path": name, "type": kind})
    index_rows = git(root, "ls-files", "--stage", "-z").stdout.decode().split("\0")[:-1]
    objects = {row.split()[0] for row in git(root, "rev-list", "--objects", "--all").stdout.decode().splitlines()}
    objects.update(row.split("\t", 1)[0].split()[1] for row in index_rows)
    batch = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], cwd=root,
                           input=("\n".join(sorted(objects))+"\n").encode(), capture_output=True)
    if batch.returncode:
        raise RuntimeError("Git object batch read failed")
    cache, position = {}, 0
    while position < len(batch.stdout):
        end = batch.stdout.index(b"\n", position)
        oid, _, size = batch.stdout[position:end].split()
        start = end + 1
        cache[oid.decode()] = batch.stdout[start:start+int(size)]
        position = start + int(size) + 1
    index_count = 0
    for row in index_rows:
        meta, name = row.split("\t", 1)
        oid = meta.split()[1]
        index_count += 1
        if private_path(name):
            findings.append({"scope": "index", "path": name, "type": "private_file_candidate"})
        for kind in findings_for(cache[oid], known):
            findings.append({"scope": "index", "path": name, "type": kind})
    commits = git(root, "rev-list", "--all").stdout.decode().splitlines()
    seen = set()
    history_paths = set()
    for commit in commits:
        for kind in findings_for(cache[commit], known):
            findings.append({"scope": "commit_message", "commit": commit, "type": kind})
        for row in git(root, "ls-tree", "-rz", commit).stdout.split(b"\0"):
            if not row:
                continue
            meta, raw_name = row.split(b"\t", 1)
            _, kind, raw_oid = meta.split()
            name, oid = raw_name.decode(), raw_oid.decode()
            history_paths.add(name)
            if (oid, name) in seen or kind != b"blob":
                continue
            seen.add((oid, name))
            if private_path(name):
                findings.append({"scope": "reachable_history", "commit": commit, "path": name, "type": "private_file_candidate"})
            for finding in findings_for(cache[oid], known):
                findings.append({"scope": "reachable_history", "commit": commit, "path": name, "type": finding})
    # Annotated tag messages may also contain secrets.
    tag_count = 0
    for ref in git(root, "for-each-ref", "--format=%(objecttype) %(objectname)", "refs/tags").stdout.decode().splitlines():
        kind, oid = ref.split()
        if kind == "tag":
            tag_count += 1
            for finding in findings_for(cache[oid], known):
                findings.append({"scope": "tag_message", "object": oid, "type": finding})
    configs = {}
    for key in ("core.autocrlf", "core.eol", "core.safecrlf", "core.bare", "core.worktree"):
        value = git(root, "config", "--show-origin", "--get", key, ok=(0, 1)).stdout.decode().strip()
        configs[key] = value or None
    checks = {}
    for name, args in (("working_diff", ("diff", "--check")), ("staged_diff", ("diff", "--cached", "--check"))):
        result = git(root, *args, ok=(0, 1, 2))
        # --check contains locations and error descriptions, never patch bodies.
        checks[name] = {"exit_code": result.returncode, "diagnostics": result.stdout.decode().splitlines(),
                        "line_ending_warning_count": result.stderr.count(b"will be replaced")}
    eols = git(root, "ls-files", "--eol").stdout.decode().splitlines()
    remotes = git(root, "remote").stdout.decode().splitlines()
    remote_has_embedded_credential = False
    for name in remotes:
        url = git(root, "remote", "get-url", name).stdout.decode()
        remote_has_embedded_credential |= bool(re.search(r"https?://[^/\s]+@", url))
    return {
        "schema_version": "portfolio_audit_v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True, "paid_model_calls": 0,
        "counts": {"tracked_files": len(tracked), "untracked_candidates": len(untracked), "index_entries": index_count,
                   "reachable_commits": len(commits), "history_blob_path_versions": len(seen), "history_paths": len(history_paths),
                   "annotated_tags": tag_count, "remotes": len(remotes),
                   "mixed_worktree_endings": sum("w/mixed" in line for line in eols)},
        "head": git(root, "rev-parse", "HEAD").stdout.decode().strip(),
        "git_configuration": configs, "remote_has_embedded_credential": remote_has_embedded_credential,
        "diff_checks": checks, "findings": findings,
        "status": git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout.decode().splitlines(),
        "candidate_files": candidates,
        "limits": ["Only local refs, index and non-ignored working candidates; no remote request or credential validation.",
                   "No reflog-only/unreachable objects, binary OCR, encrypted archives or semantic privacy guarantee.",
                   "Credential-shaped literals need human classification; test fixtures are not automatically trusted.",
                   "Ignored local runtime env is read in memory only to match known credentials, never exported."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": report["counts"], "finding_count": len(report["findings"]),
                      "diff_checks": report["diff_checks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
