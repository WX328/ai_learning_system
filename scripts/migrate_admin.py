"""Back up the configured SQLite database, upgrade, verify original data.

Run: python -m scripts.migrate_admin
No credentials or private row values are printed.
"""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from app.database import DATABASE_PATH


def fingerprint(db, table, columns):
    identifiers = ','.join('"' + c.replace('"','""') + '"' for c in columns)
    digest, count = hashlib.sha256(), 0
    for row in db.execute(f'SELECT {identifiers} FROM "{table}" ORDER BY rowid'):
        digest.update(repr(row).encode("utf-8")); count += 1
    return count, digest.hexdigest()


def backup_and_migrate(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise RuntimeError("数据库不存在，拒绝在错误位置创建空库")
    backup_dir = path.parent / ".backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_dir / f"{path.stem}-before-admin-{stamp}.db"
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as destination:
        source.backup(destination)
    with closing(sqlite3.connect(backup)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("备份完整性检查失败，未运行迁移")
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')")]
        columns = {t:[r[1] for r in db.execute(f'PRAGMA table_info("{t}")')] for t in tables}
        snapshots = {t:fingerprint(db, t, columns[t]) for t in tables}
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = "sqlite:///" + path.as_posix()
    command.upgrade(config, "head")
    with closing(sqlite3.connect(path)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or list(db.execute("PRAGMA foreign_key_check")):
            raise RuntimeError(f"迁移后完整性检查失败，备份位于 {backup}")
        for table in tables:
            if fingerprint(db, table, columns[table]) != snapshots[table]:
                raise RuntimeError(f"原有数据发生变化（可能有同时写入）：{table}。请检查备份 {backup}")
    return backup, len(tables)


if __name__ == "__main__":
    backup, count = backup_and_migrate(DATABASE_PATH)
    print(f"迁移完成。备份：{backup}\n已验证 {count} 张原有表的全部原始字段和记录，完整性与外键检查通过。")
