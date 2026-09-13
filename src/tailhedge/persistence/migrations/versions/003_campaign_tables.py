"""campaign tables

Revision ID: 003
Revises: 002
Create Date: 2026-09-13

"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_dataset.id"),
            nullable=False,
        ),
        sa.Column("portfolio_proxy_json", postgresql.JSONB, nullable=False),
        sa.Column("split_config_json", postgresql.JSONB, nullable=False),
        sa.Column("scoring_profile_json", postgresql.JSONB, nullable=False),
        sa.Column("execution_cost_profile_json", postgresql.JSONB, nullable=False),
        sa.Column("robustness_profile_json", postgresql.JSONB, nullable=False),
        sa.Column("feature_allowlist_json", postgresql.JSONB, nullable=False),
        sa.Column("strategy_bounds_json", postgresql.JSONB, nullable=False),
        sa.Column("agent_config_redacted_json", postgresql.JSONB, nullable=False),
        sa.Column("evaluator_version", sa.Text, nullable=False),
        sa.Column(
            "campaign_manifest_sha256", sa.String(64), nullable=True, unique=True
        ),
        sa.Column("evaluator_image_digest", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="DRAFT"),
        sa.Column("max_iterations", sa.BigInteger, nullable=True),
        sa.Column("annual_premium_cap", sa.Float, nullable=True),
        sa.Column(
            "cloned_from_campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_campaign.id"),
            nullable=True,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_research_campaign_status", "research_campaign", ["status"])


def downgrade() -> None:
    op.drop_index("ix_research_campaign_status", table_name="research_campaign")
    op.drop_table("research_campaign")
