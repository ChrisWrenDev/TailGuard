"""Tests for persistence models and Alembic migration setup (TASK-003)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import IntegrityError

from tailhedge.persistence.models import (
    AppUser,
    AuditEvent,
    Base,
    HoldingDefinition,
    Job,
    JobAttempt,
    Portfolio,
)
from tests.integration import requires_postgres

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TestModelMetadata:
    def test_all_tables_defined(self) -> None:
        table_names = sorted(Base.metadata.tables.keys())
        assert "app_user" in table_names
        assert "portfolio" in table_names
        assert "holding_definition" in table_names
        assert "job" in table_names
        assert "job_attempt" in table_names
        assert "audit_event" in table_names

    def test_models_are_importable(self) -> None:
        assert AppUser.__tablename__ == "app_user"
        assert Portfolio.__tablename__ == "portfolio"
        assert HoldingDefinition.__tablename__ == "holding_definition"
        assert Job.__tablename__ == "job"
        assert JobAttempt.__tablename__ == "job_attempt"
        assert AuditEvent.__tablename__ == "audit_event"


@requires_postgres
class TestSchemaCreation:
    def test_tables_created(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        tables = sorted(inspector.get_table_names())
        assert "app_user" in tables
        assert "portfolio" in tables
        assert "holding_definition" in tables
        assert "job" in tables
        assert "job_attempt" in tables
        assert "audit_event" in tables

    def test_app_user_columns(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        cols = {c["name"] for c in inspector.get_columns("app_user")}
        assert {
            "id",
            "username",
            "password_hash",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        } <= cols

    def test_holding_definition_foreign_key(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        fks = inspector.get_foreign_keys("holding_definition")
        assert any(fk["referred_table"] == "portfolio" for fk in fks)

    def test_job_attempt_foreign_key_cascades(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        fks = inspector.get_foreign_keys("job_attempt")
        matching = [fk for fk in fks if fk["referred_table"] == "job"]
        assert matching
        assert any(
            fk.get("ondelete") == "CASCADE"
            or fk.get("options", {}).get("ondelete") == "CASCADE"
            for fk in matching
        )

    def test_job_attempt_unique_per_attempt_no(self, db_session: Session) -> None:
        job = Job(type="TEST_JOB")
        db_session.add(job)
        db_session.flush()
        db_session.add(JobAttempt(job_id=job.id, attempt_no=1))
        db_session.flush()
        duplicate = JobAttempt(job_id=job.id, attempt_no=1)
        db_session.add(duplicate)
        with pytest.raises(IntegrityError, match="uq_job_attempt_job_no"):
            db_session.flush()
        db_session.rollback()


@requires_postgres
class TestModelCRUD:
    def test_create_app_user(self, db_session: Session) -> None:
        user = AppUser(
            username="owner",
            password_hash="argon2id$...",
            role="OWNER",
        )
        db_session.add(user)
        db_session.flush()
        assert user.id is not None
        assert user.username == "owner"

    def test_create_portfolio_with_holding(self, db_session: Session) -> None:
        portfolio = Portfolio(name="Main Portfolio", base_currency="GBP")
        db_session.add(portfolio)
        db_session.flush()

        holding = HoldingDefinition(
            portfolio_id=portfolio.id,
            instrument_key="SPY",
            display_name="SPDR S&P 500",
            currency="USD",
            asset_class="ETF",
            hedge_eligible=True,
            hedge_benchmark="SPX",
            hedge_beta=1.0,
        )
        db_session.add(holding)
        db_session.flush()
        assert holding.portfolio_id == portfolio.id

        fetched = db_session.execute(
            select(HoldingDefinition).where(
                HoldingDefinition.portfolio_id == portfolio.id
            )
        ).scalar_one()
        assert fetched.instrument_key == "SPY"

    def test_create_job_with_attempt(self, db_session: Session) -> None:
        job = Job(type="DAILY_RUN", payload_json={"run_key": "test:123"})
        db_session.add(job)
        db_session.flush()

        attempt = JobAttempt(job_id=job.id, attempt_no=1)
        db_session.add(attempt)
        db_session.flush()
        assert attempt.job_id == job.id

    def test_create_audit_event(self, db_session: Session) -> None:
        event = AuditEvent(
            actor_type="SYSTEM",
            event_type="APP_START",
            severity="INFO",
            summary="Application started",
        )
        db_session.add(event)
        db_session.flush()
        assert event.id is not None

    def test_job_delete_cascades_to_attempts(self, db_session: Session) -> None:
        job = Job(type="TEST_JOB")
        db_session.add(job)
        db_session.flush()
        db_session.add(JobAttempt(job_id=job.id, attempt_no=1))
        db_session.commit()

        db_session.execute(delete(Job))
        db_session.commit()

        remaining = db_session.execute(select(JobAttempt)).scalars().all()
        assert remaining == []


class TestAlembicSetup:
    def test_alembic_ini_exists(self) -> None:
        ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
        assert ini_path.exists()

    def test_migrations_directory_exists(self) -> None:
        migrations_dir = (
            Path(__file__).resolve().parents[1] / "src/tailhedge/persistence/migrations"
        )
        assert migrations_dir.is_dir()

    def test_initial_migration_exists(self) -> None:
        versions_dir = (
            Path(__file__).resolve().parents[1]
            / "src/tailhedge/persistence/migrations/versions"
        )
        migration_files = list(versions_dir.glob("*.py"))
        assert len(migration_files) >= 1
        assert any("001" in f.name for f in migration_files)

    def test_env_py_exists(self) -> None:
        env_path = (
            Path(__file__).resolve().parents[1]
            / "src/tailhedge/persistence/migrations/env.py"
        )
        assert env_path.exists()
