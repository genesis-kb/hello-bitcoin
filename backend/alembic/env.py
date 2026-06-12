"""
Alembic environment — wired to our async SQLAlchemy setup.

Run migrations:
    alembic upgrade head

Auto-generate a new migration after model changes:
    alembic revision --autogenerate -m "describe change"

The DATABASE_URL is read from the environment (same as the app),
so migrations can target both SQLite (dev) and PostgreSQL (prod)
without editing this file.
"""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ensure the backend package is importable when alembic is run from the
# backend/ directory or from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import models so that Base.metadata is fully populated for autogenerate.
from db import Base  # noqa: E402
import models  # noqa: E402, F401  — registers all ORM classes

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the URL from the environment — same logic as config.py.
_db_url = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{Path(__file__).parent.parent}/data/judge.db",
)
config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


# ── Offline mode ──────────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (useful for review/DBA hand-off)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Required for SQLite ALTER TABLE emulation
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (async) ───────────────────────────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # Required for SQLite ALTER TABLE emulation
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
