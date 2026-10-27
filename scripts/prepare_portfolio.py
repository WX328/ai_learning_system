"""Copy reviewed source candidates to a NEW local directory. Never stage/publish.

Private/runtime paths and the Git database are excluded even if tracked. Source
selection is a whitelist; this is not proof of privacy, licensing or security.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from scripts.audit_portfolio import findings_for, git, private_path, runtime_values

ROOT_FILES = {".dockerignore", ".gitattributes", ".gitignore", ".env.example", ".env.docker.example",
              "alembic.ini", "compose.yaml", "Dockerfile", "pyproject.toml", "requirements.txt", "requirements.lock",
              "rebuild_embeddings.py"}
PUBLIC_DIRS = {"app", "frontend", "migrations", "deploy", "scripts", "tests", "evaluation", "docs"}
PUBLIC_SUFFIXES = {".py", ".js", ".mjs", ".html", ".css", ".svg", ".png", ".jpg", ".jpeg", ".pdf",
                   ".ttf", ".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".conf", ".lock", ".mako", ".log"}
HARD_FINDINGS = {"matches_local_runtime_credential", "provider_key_candidate", "jwt_literal_candidate",
                 "private_key_material", "sqlite_database", "other_service_key_candidate"}


def is_public_path(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or private_path(name):
        return False
    if any(part.startswith(".") or part == "__pycache__" for part in path.parts[:-1]):
        return False
    if len(path.parts) == 1:
        return name in ROOT_FILES or path.suffix == ".md"
    if path.parts[0] not in PUBLIC_DIRS or path.name == "failure.png":
        return False
    return path.suffix.lower() in PUBLIC_SUFFIXES or path.name in {"Dockerfile.stub", "README"}


def prepare(root, output):
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Output must be a new directory; existing data is never overwritten")
    names = set(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout.decode().split("\0")[:-1])
    names = sorted(name for name in names if is_public_path(name) and (root/name).is_file())
    known = runtime_values(root)
    files = []
    for name in names:
        path = root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Symlink/outside source refused: " + name)
        data = path.read_bytes()
        if HARD_FINDINGS.intersection(findings_for(data, known)):
            raise ValueError("Credential/binary data finding; inspect the redacted audit: " + name)
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    output.mkdir(parents=True)
    for item in files:
        destination = output/item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/item["path"], destination)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "source": "local_review_candidate_snapshot",
                "published": False, "contains_git_history": False, "files": files,
                "limits": ["Human approval required before publishing; check screenshots, rights and every added file.",
                           "No runtime secrets, formal database, research observations or Git directory copied.",
                           "The original RAG corpus is not distributed; old chunk-ID evaluations need that exact corpus.",
                           "Manifest excludes itself. This copies the working tree, including uncommitted S1-S6 code."]}
    (output/"RELEASE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.root, args.output_dir)
    print(json.dumps({"copied_files": len(report["files"]), "published": False}))


if __name__ == "__main__":
    main()
