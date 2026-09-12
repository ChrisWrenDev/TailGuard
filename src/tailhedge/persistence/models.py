"""SQLAlchemy ORM models — initial operational schema foundations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all TailHedge models."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# app_user — single-owner authentication record
# ---------------------------------------------------------------------------


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="OWNER")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


# ---------------------------------------------------------------------------
# portfolio — logical portfolio definition
# ---------------------------------------------------------------------------


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="GBP")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    holdings: Mapped[list[HoldingDefinition]] = relationship(back_populates="portfolio")


# ---------------------------------------------------------------------------
# holding_definition — configuration describing hedge treatment per holding
# ---------------------------------------------------------------------------


class HoldingDefinition(Base):
    __tablename__ = "holding_definition"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "instrument_key", name="uq_holding_portfolio_instrument"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("portfolio.id"), nullable=False
    )
    instrument_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="MANUAL")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    asset_class: Mapped[str] = mapped_column(
        String(50), nullable=False, default="EQUITY"
    )
    hedge_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hedge_benchmark: Mapped[str | None] = mapped_column(Text, nullable=True)
    hedge_beta: Mapped[float | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="holdings")


# ---------------------------------------------------------------------------
# job / job_attempt — durable background work queue
# ---------------------------------------------------------------------------


class Job(Base):
    __tablename__ = "job"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    unique_key: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    job_attempts: Mapped[list[JobAttempt]] = relationship(back_populates="job")


class JobAttempt(Base):
    __tablename__ = "job_attempt"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_no", name="uq_job_attempt_job_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("job.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="RUNNING")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[Job] = relationship(back_populates="job_attempts")


# ---------------------------------------------------------------------------
# audit_event — append-only material event log
# ---------------------------------------------------------------------------


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details_redacted_json: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )


# ---------------------------------------------------------------------------
# research_dataset — imported historical dataset metadata
# ---------------------------------------------------------------------------


class ResearchDataset(Base):
    __tablename__ = "research_dataset"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_vendor: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    default_snapshot_time: Mapped[str | None] = mapped_column(String(10), nullable=True)
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(nullable=False, default=0)
    manifest_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="INGESTING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    dataset_files: Mapped[list[DatasetFile]] = relationship(back_populates="dataset")
    validation_results: Mapped[list[DatasetValidationResult]] = relationship(
        back_populates="dataset"
    )


# ---------------------------------------------------------------------------
# dataset_file — per-file hash and metadata within a dataset
# ---------------------------------------------------------------------------


class DatasetFile(Base):
    __tablename__ = "dataset_file"
    __table_args__ = (
        UniqueConstraint("dataset_id", "relative_path", name="uq_dataset_file_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_dataset.id"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(nullable=False)
    row_count: Mapped[int | None] = mapped_column(nullable=True)
    source_role: Mapped[str] = mapped_column(String(50), nullable=False)

    dataset: Mapped[ResearchDataset] = relationship(back_populates="dataset_files")


# ---------------------------------------------------------------------------
# dataset_validation_result — validation checks for an imported dataset
# ---------------------------------------------------------------------------


class DatasetValidationResult(Base):
    __tablename__ = "dataset_validation_result"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("research_dataset.id"), nullable=False
    )
    validator_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    summary_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    report_artifact_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    dataset: Mapped[ResearchDataset] = relationship(back_populates="validation_results")
