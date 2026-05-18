"""Alembic environment — async SQLAlchemy + asyncpg.

``run_migrations_online`` drives migrations through an async engine so the
same ``postgresql+asyncpg://`` URL used by the application works unchanged.
The database URL is read from ``app.core.config.settings`` so that environment
variables (.env / runtime) are respected without duplicating the value.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ensure app package is importable (alembic runs from the backend/ root where
# pyproject.toml sets prepend_sys_path = ".")
from app.core.config import settings
from app.db.models import Base

# ── Alembic Config object ──────────────────────────────────────────────────
config = context.config

# Override the URL from application settings so a single source of truth is
# maintained; the value in alembic.ini is only a documentation placeholder.
config.set_main_option("sqlalchemy.url", settings.database_url)

# ── Logging ───────────────────────────────────────────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Target metadata (all ORM-managed tables) ──────────────────────────────
target_metadata = Base.metadata


# ── Migration helpers ─────────────────────────────────────────────────────


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (--sql mode)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database using an async engine.

    ``NullPool`` is used so the engine is discarded immediately after the
    migration run — important in short-lived CLI invocations.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
