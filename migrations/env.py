"""Alembic environment for the application's SQLite database."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.database import Base, DATABASE_URL
import app.models  # noqa: F401 - register all mapped tables

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
database_url = config.attributes.get("database_url") or os.getenv("ALEMBIC_DATABASE_URL", DATABASE_URL)


def run_migrations_offline() -> None:
    context.configure(url=database_url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"},
                      render_as_batch=database_url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
