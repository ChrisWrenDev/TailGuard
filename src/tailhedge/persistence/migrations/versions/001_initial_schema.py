"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-09-12

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # app_user
    op.create_table(
        "app_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="OWNER"),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # portfolio
    op.create_table(
        "portfolio",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="GBP"),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # holding_definition
    op.create_table(
        "holding_definition",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "portfolio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("portfolio.id"),
            nullable=False,
        ),
        sa.Column("instrument_key", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("source", sa.String(50), nullable=False, server_default="MANUAL"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "asset_class", sa.String(50), nullable=False, server_default="EQUITY"
        ),
        sa.Column(
            "hedge_eligible",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("hedge_benchmark", sa.Text, nullable=True),
        sa.Column("hedge_beta", sa.Numeric(12, 6), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "portfolio_id", "instrument_key", name="uq_holding_portfolio_instrument"
        ),
    )

    # job
    op.create_table(
        "job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("payload_json", postgresql.JSONB, nullable=True),
        sa.Column("unique_key", sa.Text, nullable=True, unique=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.Text, nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "max_attempts", sa.Integer, nullable=False, server_default=sa.text("3")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # job_attempt
    op.create_table(
        "job_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job.id"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="RUNNING"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_detail_redacted", sa.Text, nullable=True),
    )

    # audit_event
    op.create_table(
        "audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_type", sa.String(50), nullable=False),
        sa.Column("actor_ref", sa.Text, nullable=True),
        sa.Column("event_type", sa.String(200), nullable=False),
        sa.Column("severity", sa.String(50), nullable=False),
        sa.Column("correlation_id", sa.Text, nullable=True),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("details_redacted_json", postgresql.JSONB, nullable=True),
    )
    op.create_index("ix_audit_event_occurred_at", "audit_event", ["occurred_at"])
    op.create_index(
        "ix_audit_event_entity", "audit_event", ["entity_type", "entity_id"]
    )
    op.create_index(
        "ix_audit_event_type_time", "audit_event", ["event_type", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_table("audit_event")
    op.drop_table("job_attempt")
    op.drop_table("job")
    op.drop_table("holding_definition")
    op.drop_table("portfolio")
    op.drop_table("app_user")
