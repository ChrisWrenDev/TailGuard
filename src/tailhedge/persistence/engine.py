"""SQLAlchemy engine and session factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tailhedge.config import Secrets

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.engine import Engine

_engine: Engine | None = None
_engine_url: str | None = None
_session_factory: sessionmaker[Session] | None = None


def _resolve_url(url: str | None) -> str:
    if url is not None:
        return url
    secrets = Secrets()
    return secrets.database_url.get_secret_value()


def get_engine(url: str | None = None) -> Engine:
    """Return a singleton engine for the given URL, creating it on first call."""
    global _engine, _engine_url
    resolved = _resolve_url(url)
    if _engine is None or _engine_url != resolved:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine(resolved, pool_pre_ping=True)
        _engine_url = resolved
    return _engine


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    """Return a singleton session factory for the given URL."""
    global _session_factory
    resolved = _resolve_url(url)
    if _session_factory is None or _engine_url != resolved:
        _session_factory = sessionmaker(bind=get_engine(resolved))
    return _session_factory


def get_session(url: str | None = None) -> Generator[Session, None, None]:
    """Yield a session and ensure it is closed after use."""
    factory = get_session_factory(url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Reset singleton state (for testing)."""
    global _engine, _engine_url, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None
    _session_factory = None
