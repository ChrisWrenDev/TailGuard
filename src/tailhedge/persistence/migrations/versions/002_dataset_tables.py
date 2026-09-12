"""dataset tables

Revision ID: 002
Revises: 001
Create Date: 2026-09-12

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # research_dataset
    op.create_table(
        "research_dataset",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_vendor", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(50), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("default_snapshot_time", sa.String(10), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "row_count", sa.BigInteger, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("manifest_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_uri", sa.Text, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="INGESTING"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # dataset_file
    op.create_table(
        "dataset_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_dataset.id"),
            nullable=False,
        ),
        sa.Column("relative_path", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("row_count", sa.BigInteger, nullable=True),
        sa.Column("source_role", sa.String(50), nullable=False),
        sa.UniqueConstraint("dataset_id", "relative_path", name="uq_dataset_file_path"),
    )

    # dataset_validation_result
    op.create_table(
        "dataset_validation_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_dataset.id"),
            nullable=False,
        ),
        sa.Column("validator_version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("summary_json", postgresql.JSONB, nullable=False),
        sa.Column("report_artifact_uri", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("dataset_validation_result")
    op.drop_table("dataset_file")
    op.drop_table("research_dataset")
