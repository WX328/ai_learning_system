"""Migrate only a disposable database; compare every original row and foreign key."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config


class AdminMigrationTest(unittest.TestCase):
    def test_backup_tool_preserves_a_restorable_copy_and_can_run_again(self):
        from scripts.migrate_admin import backup_and_migrate

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "learning.db"
            config = Config("alembic.ini")
            config.attributes["database_url"] = "sqlite:///" + path.as_posix()
            command.upgrade(config, "0004")
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("INSERT INTO users (username,password_hash,total_xp,level,correct_streak) VALUES ('legacy','private-hash',70,1,2)")
            backup, count = backup_and_migrate(path)
            self.assertGreater(count, 0)
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone()[0], "0004")
                self.assertEqual(db.execute("SELECT username,total_xp FROM users").fetchone(), ("legacy",70))
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT role,is_active,total_xp FROM users").fetchone(), ("user",1,70))
            another, _ = backup_and_migrate(path)
            self.assertNotEqual(backup, another)
            self.assertTrue(backup.is_file())
            self.assertTrue(another.is_file())
            with self.assertRaises(RuntimeError):
                backup_and_migrate(Path(folder) / "missing.db")

    def test_upgrade_preserves_all_legacy_rows_and_repeated_upgrade_is_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "migration.db"
            with patch.dict(os.environ, {"ALEMBIC_DATABASE_URL":"sqlite:///" + path.as_posix()}):
                config = Config("alembic.ini")
                command.upgrade(config, "0004")
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("INSERT INTO users (id,username,password_hash,total_xp,level,correct_streak) VALUES (1,'legacy','private-hash',120,2,3)")
                    db.execute("INSERT INTO learning_materials (id,user_id,title,content,material_type,created_at) VALUES (1,1,'Private','Private content','text',CURRENT_TIMESTAMP)")
                    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')")]
                    snapshots = {t:list(db.execute(f'SELECT * FROM "{t}" ORDER BY 1')) for t in tables}
                    columns = {t:[r[1] for r in db.execute(f'PRAGMA table_info("{t}")')] for t in tables}
                command.upgrade(config, "head")
                command.upgrade(config, "head")
                with closing(sqlite3.connect(path)) as db, db:
                    for table in tables:
                        names = ','.join('"' + c + '"' for c in columns[table])
                        self.assertEqual(list(db.execute(f'SELECT {names} FROM "{table}" ORDER BY 1')), snapshots[table])
                    self.assertEqual(db.execute("SELECT role,is_active,created_at,auth_version FROM users").fetchone(), ('user',1,None,0))
                    self.assertEqual(list(db.execute("PRAGMA foreign_key_check")), [])
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute("UPDATE users SET role='owner'")
                command.downgrade(config, "0004")
                command.upgrade(config, "head")
