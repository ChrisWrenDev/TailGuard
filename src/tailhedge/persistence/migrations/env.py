"""Alembic environment configuration.

Reads the database URL from tailhedge.config.Secrets so the migration
runner never hard-codes credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tailhedge.config import Secrets
from tailhedge.persistence.models import Base

config = context.config

# Override sqlalchemy.url from environment secrets
try:
    secrets = Secrets()
    config.set_main_option("sqlalchemy.url", secrets.database_url.get_secret_value())
except Exception:
    pass  # fall back to alembic.ini default for `alembic init`

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
