"""Shared fixtures for TailHedge tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tailhedge.persistence.models import Base
from tests.integration import TEST_DATABASE_URL

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Fresh PostgreSQL session with a clean schema for each test."""
    if TEST_DATABASE_URL is None:
        pytest.skip(
            "Set TAILHEDGE_TEST_DATABASE_URL to run PostgreSQL integration tests"
        )
    engine: Engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def auth_db() -> Generator[sessionmaker[Session], None, None]:
    """Seed an owner user and point the web app's DB dependency at it."""
    from tailhedge.persistence.engine import get_session
    from tailhedge.persistence.models import AppUser
    from tailhedge.web import app as web_app
    from tailhedge.web.auth import hash_password

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[AppUser.__table__])  # type: ignore[list-item]
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            AppUser(
                username="owner",
                password_hash=hash_password("correct-horse-battery"),
                role="OWNER",
            )
        )
        session.commit()

    def override() -> Generator[Session, None, None]:
        with factory() as s:
            yield s

    web_app.app.dependency_overrides[get_session] = override
    yield factory
    web_app.app.dependency_overrides.pop(get_session, None)
    engine.dispose()


@pytest.fixture
def auth_db_with_datasets() -> Generator[sessionmaker[Session], None, None]:
    """Auth fixture with dataset tables for data page tests.

    Uses PostgreSQL (from TAILHEDGE_TEST_DATABASE_URL) or skips.
    """
    from tailhedge.persistence.engine import get_session
    from tailhedge.persistence.models import AppUser
    from tailhedge.web import app as web_app
    from tailhedge.web.auth import hash_password

    if TEST_DATABASE_URL is None:
        pytest.skip(
            "Data page tests require PostgreSQL; set TAILHEDGE_TEST_DATABASE_URL"
        )
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            AppUser(
                username="owner",
                password_hash=hash_password("correct-horse-battery"),
                role="OWNER",
            )
        )
        session.commit()

    def override() -> Generator[Session, None, None]:
        with factory() as s:
            yield s

    web_app.app.dependency_overrides[get_session] = override
    yield factory
    web_app.app.dependency_overrides.pop(get_session, None)
    engine.dispose()


@pytest.fixture
def mock_db_ready() -> Generator[None, None, None]:
    """Stub the readiness check so /readyz passes without a live database."""
    from tailhedge.web import app as web_app

    web_app.app.dependency_overrides[web_app.check_database_ready] = lambda: None
    yield
    web_app.app.dependency_overrides.pop(web_app.check_database_ready, None)
