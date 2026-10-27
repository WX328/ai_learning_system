"""One-shot migration: snapshot existing data first, then Alembic; never start HTTP."""
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4
from alembic import command
from alembic.config import Config


def main():
    from app.database import DATA_DIR, DATABASE_PATH, engine
    from scripts.data_backup import backup
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "uploads").mkdir(exist_ok=True)
    is_new = not DATABASE_PATH.exists()
    if not is_new:
        # Every update has a recoverable consistent snapshot, even under WAL.
        root = Path(os.getenv("APP_BACKUP_DIR", str(DATA_DIR / "backups")))
        root.mkdir(parents=True, exist_ok=True)
        folder = root / (datetime.now(timezone.utc).strftime("pre-migration-%Y%m%dT%H%M%SZ-")+uuid4().hex[:8])
        backup(DATABASE_PATH, folder)
        print(f"Pre-migration backup created: {folder.name}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    if is_new:
        from app.database import SessionLocal
        from scripts.seed_achievements import seed
        with SessionLocal() as db:
            seed(db)
    engine.dispose()
    print("Schema ready; API may start")


if __name__ == "__main__":
    main()
