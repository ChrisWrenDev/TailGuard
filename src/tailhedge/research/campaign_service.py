"""Campaign service — CRUD, start freeze, and clone (TASK-021).

Implements FR-007: campaign configuration becomes immutable and hashed at
start; changing any frozen item requires cloning the campaign so prior
results are never silently re-interpreted.

State machine (DATA_MODEL.md §4.1, SB-002)::

    DRAFT -> RUNNING -> (PAUSED | STOPPED | COMPLETED | FAILED)

Only a ``DRAFT`` campaign may be mutated or started.  ``start`` computes
the manifest hash over the frozen configuration, resolves the evaluator
image digest when a container runtime is available, and enqueues the
research job.  Failures fail closed: a campaign that cannot be frozen
stays ``DRAFT``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from tailhedge.persistence.models import (
    AuditEvent,
    Job,
    ResearchCampaign,
    ResearchDataset,
)
from tailhedge.research.campaign_config import (
    EVALUATOR_VERSION,
    IMMUTABLE_CONFIG_FIELDS,
    CampaignConfig,
    CampaignConfigError,
    CampaignImmutableError,
    CampaignStateError,
    default_feature_allowlist_json,
    default_robustness_profile_json,
    default_scoring_profile_json,
    default_strategy_bounds_json,
    validate_annual_premium_cap,
    validate_execution_cost_profile_json,
    validate_feature_allowlist,
    validate_robustness_profile_json,
    validate_scoring_profile_json,
)
from tailhedge.research.campaign_config import (
    validate_split_frozen_config as _validate_split,
)

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

APPLICATION_ANNUAL_PREMIUM_CAP = 0.01
"""Application safety cap: 1.0% of equity per rolling 365 days (OQ-004/ADR-024)."""


class CampaignNotFoundError(Exception):
    """Raised when a campaign does not exist."""


class DatasetNotReadyError(CampaignConfigError):
    """Raised when starting a campaign on a dataset that is not READY."""


class CampaignManifestConflictError(CampaignConfigError):
    """Raised when starting a campaign whose manifest hash already exists.

    Maps to ``CONFIG_HASH_FAILED`` in the API (API_SPEC §5).
    """


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def default_campaign_config(
    *,
    dataset_id: uuid.UUID,
    portfolio_proxy_json: dict[str, Any] | None = None,
    split_config_json: dict[str, Any] | None = None,
    scoring_profile_json: dict[str, Any] | None = None,
    execution_cost_profile_json: dict[str, Any] | None = None,
    robustness_profile_json: dict[str, Any] | None = None,
    feature_allowlist_json: dict[str, Any] | None = None,
    strategy_bounds_json: dict[str, Any] | None = None,
    agent_config_redacted_json: dict[str, Any] | None = None,
    annual_premium_cap: float | None = None,
    max_iterations: int | None = None,
) -> CampaignConfig:
    """Build a ``CampaignConfig`` with architecture-spec defaults.

    Explicit values override defaults; every field remains visible in the
    frozen manifest hash.  ``annual_premium_cap`` defaults to the
    application safety cap (1.0%, OQ-004/ADR-024) and is validated within
    that cap at validation time.
    """
    return CampaignConfig(
        dataset_id=dataset_id,
        portfolio_proxy_json=portfolio_proxy_json or {"benchmark": "SPX", "beta": 1.0},
        split_config_json=split_config_json or {"purge_horizon_days": 60},
        scoring_profile_json=scoring_profile_json or default_scoring_profile_json(),
        execution_cost_profile_json=execution_cost_profile_json
        or {"base_fill_spread_fraction": 0.25},
        robustness_profile_json=robustness_profile_json
        or default_robustness_profile_json(),
        feature_allowlist_json=feature_allowlist_json
        or default_feature_allowlist_json(),
        strategy_bounds_json=strategy_bounds_json or default_strategy_bounds_json(),
        agent_config_redacted_json=agent_config_redacted_json or {},
        evaluator_version=EVALUATOR_VERSION,
        max_iterations=max_iterations,
        annual_premium_cap=(
            annual_premium_cap
            if annual_premium_cap is not None
            else APPLICATION_ANNUAL_PREMIUM_CAP
        ),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_campaign_config(config: CampaignConfig) -> None:
    """Validate campaign configuration for correctness (API_SPEC §5).

    Checks:
    - scoring, execution-cost, and robustness profiles are valid
      (SB-002 precondition: scoring/cost/robustness profiles are valid);
    - feature allowlist is a subset of the SDK feature surface;
    - split config is internally consistent (folds ordered, holdout
      excluded from train/validation ranges when supplied);
    - annual premium cap is present, positive, and within the
      application cap.
    """
    validate_scoring_profile_json(config.scoring_profile_json)
    validate_execution_cost_profile_json(config.execution_cost_profile_json)
    validate_robustness_profile_json(config.robustness_profile_json)
    validate_feature_allowlist(config.feature_allowlist_json)
    _validate_split(config.split_config_json)
    if config.annual_premium_cap is None:
        msg = "annual_premium_cap is required (application safety cap applies)"
        raise CampaignConfigError(msg)
    validate_annual_premium_cap(
        config.annual_premium_cap, APPLICATION_ANNUAL_PREMIUM_CAP
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_campaign(
    session: Session,
    *,
    name: str,
    dataset_id: uuid.UUID,
    config: CampaignConfig,
    description: str | None = None,
    created_by: uuid.UUID | None = None,
) -> ResearchCampaign:
    """Create a new ``DRAFT`` campaign.

    The config is validated but not yet frozen: hashing happens at
    ``start`` so the owner can edit the draft freely.
    """
    if config.dataset_id != dataset_id:
        msg = (
            f"config.dataset_id ({config.dataset_id}) must match the "
            f"dataset_id argument ({dataset_id})"
        )
        raise CampaignConfigError(msg)
    validate_campaign_config(config)

    dataset = session.get(ResearchDataset, dataset_id)
    if dataset is None:
        msg = f"dataset {dataset_id} does not exist"
        raise CampaignConfigError(msg)

    campaign = ResearchCampaign(
        name=name,
        description=description,
        status="DRAFT",
        created_by=created_by,
        **{
            field_name: getattr(config, field_name)
            for field_name in IMMUTABLE_CONFIG_FIELDS
        },
    )
    session.add(campaign)
    session.flush()
    session.add(
        AuditEvent(
            actor_type="USER",
            event_type="CAMPAIGN_CREATED",
            severity="INFO",
            entity_type="research_campaign",
            entity_id=campaign.id,
            summary=f"Campaign {name!r} created in DRAFT state.",
            details_redacted_json={"dataset_id": str(dataset_id)},
        )
    )
    session.commit()
    return campaign


def update_campaign(
    session: Session,
    campaign_id: uuid.UUID,
    updates: dict[str, Any],
) -> ResearchCampaign:
    """Update a campaign; frozen fields on a started campaign are rejected.

    Non-frozen metadata (``name``, ``description``) may be updated in any
    state.  Frozen config fields may only change while ``DRAFT``.
    """
    campaign = get_campaign(session, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found")

    frozen_attempted = sorted(set(updates) & set(IMMUTABLE_CONFIG_FIELDS))
    if frozen_attempted and campaign.status != "DRAFT":
        raise CampaignImmutableError(
            f"Campaign {campaign_id} is {campaign.status}; frozen config "
            f"fields {frozen_attempted} cannot be updated; clone the "
            f"campaign instead (FR-007)."
        )

    for key, value in updates.items():
        if key in ("name", "description") or key in IMMUTABLE_CONFIG_FIELDS:
            setattr(campaign, key, value)
        else:
            msg = f"Unknown campaign field {key!r}"
            raise CampaignConfigError(msg)

    if frozen_attempted:
        # Re-validate the draft config after a permitted pre-start change.
        config = _config_from_campaign(campaign)
        validate_campaign_config(config)

    session.commit()
    return campaign


def get_campaign(
    session: Session,
    campaign_id: uuid.UUID,
) -> ResearchCampaign | None:
    """Return a campaign by ID or None."""
    return session.get(ResearchCampaign, campaign_id)


def list_campaigns(
    session: Session,
    *,
    status: str | None = None,
    dataset_id: uuid.UUID | None = None,
) -> list[ResearchCampaign]:
    """List campaigns with optional status/dataset filters (API_SPEC §5)."""
    stmt = select(ResearchCampaign).order_by(ResearchCampaign.created_at.desc())
    if status is not None:
        stmt = stmt.where(ResearchCampaign.status == status)
    if dataset_id is not None:
        stmt = stmt.where(ResearchCampaign.dataset_id == dataset_id)
    return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Start (freeze)
# ---------------------------------------------------------------------------


def start_campaign(
    session: Session,
    campaign_id: uuid.UUID,
    *,
    enqueue_job: bool = True,
) -> ResearchCampaign:
    """Freeze and hash the campaign config, then transition to RUNNING.

    Steps (SB-002 1-3):
    1. Verify the campaign is ``DRAFT`` (else ``CAMPAIGN_NOT_DRAFT``).
    2. Verify the referenced dataset is ``READY`` (else
       ``DATASET_NOT_READY``).
    3. Validate the config (fail closed on any inconsistency).
    4. Compute the manifest hash and resolve the evaluator image digest
       when a container runtime is available.
    5. Persist hash/digest/status/started_at atomically and enqueue the
       research job.

    On any failure the campaign remains ``DRAFT`` and nothing is enqueued.
    """
    campaign = get_campaign(session, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
    if campaign.status != "DRAFT":
        raise CampaignStateError(
            f"Campaign {campaign_id} is {campaign.status}, not DRAFT "
            f"(CAMPAIGN_NOT_DRAFT)"
        )

    dataset = session.get(ResearchDataset, campaign.dataset_id)
    if dataset is None or dataset.status != "READY":
        actual = dataset.status if dataset is not None else "MISSING"
        raise DatasetNotReadyError(
            f"Dataset {campaign.dataset_id} is {actual}, not READY (DATASET_NOT_READY)"
        )

    config = _config_from_campaign(campaign)
    validate_campaign_config(config)

    manifest_sha256 = config.manifest_sha256()
    evaluator_digest = _resolve_evaluator_digest()

    # The manifest hash is the campaign's unique identity (DATA_MODEL §4.1);
    # a collision means an identical configuration was already started.  Fail
    # closed instead of surfacing a raw DB IntegrityError (CONFIG_HASH_FAILED).
    existing = session.execute(
        select(ResearchCampaign.id).where(
            ResearchCampaign.campaign_manifest_sha256 == manifest_sha256,
            ResearchCampaign.id != campaign.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise CampaignManifestConflictError(
            f"Campaign {campaign_id} cannot start: an identical campaign "
            f"configuration (manifest {manifest_sha256[:16]}…) already exists "
            f"as campaign {existing} (CONFIG_HASH_FAILED). Change the "
            f"configuration before starting."
        )

    campaign.campaign_manifest_sha256 = manifest_sha256
    campaign.evaluator_image_digest = evaluator_digest
    campaign.status = "RUNNING"
    campaign.started_at = datetime.now(UTC)

    if enqueue_job:
        session.add(
            Job(
                type="campaign_run",
                payload_json={
                    "campaign_id": str(campaign.id),
                    "campaign_manifest_sha256": manifest_sha256,
                },
                unique_key=f"campaign_run:{campaign.id}",
            )
        )
    session.add(
        AuditEvent(
            actor_type="USER",
            event_type="CAMPAIGN_STARTED",
            severity="INFO",
            entity_type="research_campaign",
            entity_id=campaign.id,
            summary=(
                f"Campaign {campaign.name!r} started; config frozen with "
                f"manifest {manifest_sha256[:16]}…."
            ),
            details_redacted_json={
                "campaign_manifest_sha256": manifest_sha256,
                "evaluator_version": campaign.evaluator_version,
                "evaluator_image_digest": evaluator_digest,
            },
        )
    )
    session.commit()
    return campaign


def _resolve_evaluator_digest() -> str | None:
    """Resolve the evaluator OCI image digest, or None when unavailable.

    A missing container runtime is not fatal for campaign start (CI/unit
    environments); the evaluator version string remains part of the
    frozen manifest either way.
    """
    try:
        from tailhedge.research.evaluator import get_image_id

        return get_image_id()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not resolve evaluator image digest: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------


def clone_campaign(
    session: Session,
    campaign_id: uuid.UUID,
    *,
    name: str | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> ResearchCampaign:
    """Clone a campaign into a new ``DRAFT`` campaign (FR-007).

    The clone copies the full frozen configuration (optionally overridden
    per field), records ``cloned_from_campaign_id`` for provenance, and
    starts unfrozen: the owner may edit it before re-starting.  The
    source campaign and its results are untouched.
    """
    source = get_campaign(session, campaign_id)
    if source is None:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found")

    values = {
        field_name: getattr(source, field_name)
        for field_name in IMMUTABLE_CONFIG_FIELDS
    }
    for key, value in (config_overrides or {}).items():
        if key not in IMMUTABLE_CONFIG_FIELDS:
            msg = f"Unknown campaign config field {key!r}"
            raise CampaignConfigError(msg)
        values[key] = value

    config = CampaignConfig(**values)
    validate_campaign_config(config)

    dataset = session.get(ResearchDataset, config.dataset_id)
    if dataset is None:
        msg = (
            f"dataset {config.dataset_id} does not exist; clone cannot "
            f"reference a missing dataset"
        )
        raise CampaignConfigError(msg)

    clone = ResearchCampaign(
        name=name or f"{source.name} (clone)",
        description=source.description,
        status="DRAFT",
        created_by=source.created_by,
        cloned_from_campaign_id=source.id,
        **values,
    )
    session.add(clone)
    session.flush()
    session.add(
        AuditEvent(
            actor_type="USER",
            event_type="CAMPAIGN_CLONED",
            severity="INFO",
            entity_type="research_campaign",
            entity_id=clone.id,
            summary=(
                f"Campaign {clone.name!r} cloned from {source.name!r} "
                f"(FR-007 clone path)."
            ),
            details_redacted_json={
                "cloned_from_campaign_id": str(source.id),
                "cloned_manifest_sha256": source.campaign_manifest_sha256,
            },
        )
    )
    session.commit()
    return clone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_from_campaign(campaign: ResearchCampaign) -> CampaignConfig:
    """Rebuild a ``CampaignConfig`` from a persisted campaign row."""
    return CampaignConfig(
        dataset_id=campaign.dataset_id,
        portfolio_proxy_json=campaign.portfolio_proxy_json,
        split_config_json=campaign.split_config_json,
        scoring_profile_json=campaign.scoring_profile_json,
        execution_cost_profile_json=campaign.execution_cost_profile_json,
        robustness_profile_json=campaign.robustness_profile_json,
        feature_allowlist_json=campaign.feature_allowlist_json,
        strategy_bounds_json=campaign.strategy_bounds_json,
        agent_config_redacted_json=campaign.agent_config_redacted_json,
        evaluator_version=campaign.evaluator_version,
        max_iterations=campaign.max_iterations,
        annual_premium_cap=campaign.annual_premium_cap,
    )
