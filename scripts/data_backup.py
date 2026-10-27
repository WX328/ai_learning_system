"""Consistent SQLite + uploads backup. Restore only into a new empty data directory."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            value.update(chunk)
    return value.hexdigest()


def check_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity_check failed")
        if not db.execute("SELECT name FROM sqlite_master WHERE name='alembic_version'").fetchone():
            return []  # Legacy unversioned snapshots can still be backed up safely.
        return [r[0] for r in db.execute("SELECT version_num FROM alembic_version")]


def backup(database, output):
    source = Path(database).resolve(strict=True)
    output = Path(output).resolve()
    uploads = source.parent / "uploads"
    if output == uploads or uploads in output.parents:
        raise ValueError("Backup destination must be outside uploads")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "learning.db"
    with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True)) as reader:
        reader.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(snapshot)) as writer:
            reader.backup(writer)
            writer.execute("PRAGMA journal_mode=DELETE")
    heads = check_database(snapshot)
    if uploads.exists():
        if uploads.is_symlink() or any(p.is_symlink() for p in uploads.rglob("*")):
            raise ValueError("Uploads symlinks require manual inspection; backup refused")
        shutil.copytree(uploads, output / "uploads")
    files = {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*")) if p.is_file()}
    manifest = {"format": "zhixing_backup_v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "sqlite_heads": heads, "files": files,
        "note": "Contains private learning data; keep access-controlled and encrypted off-device."}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return manifest


def restore(bundle, destination):
    bundle = Path(bundle).resolve(strict=True)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "zhixing_backup_v1" or "learning.db" not in manifest.get("files", {}):
        raise ValueError("Unsupported or incomplete backup")
    validated = []
    for name, expected in manifest["files"].items():
        relative = PurePosixPath(name)
        source = (bundle / name).resolve(strict=True)
        if "\\" in name or relative.is_absolute() or ".." in relative.parts or bundle not in source.parents:
            raise ValueError("Unsafe backup path")
        if name != "learning.db" and (not relative.parts or relative.parts[0] != "uploads"):
            raise ValueError("Unexpected backup content")
        if sha(source) != expected:
            raise ValueError("Backup checksum mismatch")
        validated.append((name, source))
    check_database(bundle / "learning.db")
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Restore destination must be empty; stop the app and use a new volume/directory")
    destination.mkdir(parents=True, exist_ok=True)
    for name, source in validated:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return {"restored_files": len(validated), "sqlite_heads": check_database(destination / "learning.db")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    save = commands.add_parser("backup")
    save.add_argument("--database", type=Path, default=Path(os.getenv("APP_DATA_DIR", ".")) / "learning.db")
    save.add_argument("--output-dir", type=Path, required=True)
    load = commands.add_parser("restore")
    load.add_argument("--backup", type=Path, required=True)
    load.add_argument("--target-data-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = backup(args.database, args.output_dir) if args.action == "backup" else restore(args.backup, args.target_data_dir)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
