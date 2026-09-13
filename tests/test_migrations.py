"""Integration test: a fresh database migrates cleanly (TASK-003)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, make_url, text

from tests.integration import TEST_DATABASE_URL, requires_postgres

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.engine import Engine

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "app_user",
    "portfolio",
    "holding_definition",
    "job",
    "job_attempt",
    "audit_event",
    "alembic_version",
}


@pytest.fixture
def scratch_db(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[Engine, Config], None, None]:
    """Create a scratch database, run with Alembic pointed at it, clean up."""
    assert TEST_DATABASE_URL is not None
    base_url = make_url(TEST_DATABASE_URL)
    scratch_name = f"tailhedge_migration_{uuid.uuid4().hex[:8]}"
    # str(URL) masks the password; render the real password for env.py.
    scratch_url = base_url.set(database=scratch_name).render_as_string(
        hide_password=False
    )

    admin = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{scratch_name}"'))
    admin.dispose()

    # Point Alembic's env.py at the scratch database
    monkeypatch.setenv("TAILHEDGE_SECRET_DATABASE_URL", str(scratch_url))
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        str(REPO_ROOT / "src/tailhedge/persistence/migrations"),
    )

    engine = create_engine(str(scratch_url))
    try:
        yield engine, cfg
    finally:
        engine.dispose()
        cleanup = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
        with cleanup.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch_name}" WITH (FORCE)'))
        cleanup.dispose()


def test_fresh_database_migrates(
    scratch_db: tuple[Engine, Config],
) -> None:
    engine, cfg = scratch_db

    command.upgrade(cfg, "head")

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert tables >= EXPECTED_TABLES

    with engine.connect() as conn:
        version = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert version == "003"


def test_fresh_database_downgrade(
    scratch_db: tuple[Engine, Config],
) -> None:
    engine, cfg = scratch_db

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    inspector = inspect(engine)
    # Alembic retains its version table; all application tables are dropped
    assert set(inspector.get_table_names()) - {"alembic_version"} == set()
