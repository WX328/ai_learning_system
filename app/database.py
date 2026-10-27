import os
from pathlib import Path
from dotenv import load_dotenv

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase,sessionmaker
from collections.abc import Generator

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv()
DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR))).expanduser().resolve()
DATABASE_PATH = DATA_DIR / "learning.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread":False, "timeout":30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def configure_sqlite(connection, _record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    if os.getenv("SQLITE_WAL", "false").lower() == "true":
        cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

class Base(DeclarativeBase):
    pass

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)

def get_db() -> Generator:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
