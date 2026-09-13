"""T-008: Campaign model, frozen config, and scoring profile tests (TASK-021).

Covers FR-007:
- default scoring profile matches the architecture-spec formula
  (TECHNICAL_ARCHITECTURE.md §10) and is versioned configuration;
- campaign manifest hash is deterministic and changes with any frozen item;
- started campaign immutable fields reject update (negative test);
- clone path works: clone is a new DRAFT campaign with provenance, source
  untouched;
- started campaign config hashes verify; tampering fails verification;
- agent configuration rejects secret-looking keys;
- start fails closed on non-DRAFT state and non-READY dataset.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from tailhedge.research.campaign_config import (
    DEFAULT_CAGR_WEIGHT,
    DEFAULT_DRAWDOWN_WEIGHT,
    DEFAULT_ROBUST_STDEV_PENALTY_WEIGHT,
    SCORING_PROFILE_VERSION,
    AgentConfigSecretError,
    CampaignConfig,
    CampaignImmutableError,
    CampaignStateError,
    FrozenCampaign,
    ScoringProfile,
    complexity_penalty,
    default_scoring_profile_json,
    diff_configs,
    fold_utility,
    robust_score,
    validate_annual_premium_cap,
    validate_execution_cost_profile_json,
    validate_feature_allowlist,
    validate_robustness_profile_json,
    validate_scoring_profile_json,
)
from tailhedge.research.campaign_service import (
    APPLICATION_ANNUAL_PREMIUM_CAP,
    CampaignNotFoundError,
    DatasetNotReadyError,
    clone_campaign,
    create_campaign,
    get_campaign,
    list_campaigns,
    start_campaign,
    update_campaign,
    validate_campaign_config,
)
from tests.integration import requires_postgres

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from tailhedge.persistence.models import ResearchCampaign

pytestmark = [requires_postgres]


FIXED_DATASET_ID = uuid.uuid4()


def _config(dataset_id: uuid.UUID | None = None, **overrides: object) -> CampaignConfig:
    base: dict[str, object] = {
        "dataset_id": dataset_id or FIXED_DATASET_ID,
        "portfolio_proxy_json": {"benchmark": "SPX"},
        "split_config_json": {"purge_horizon_days": 60},
        "scoring_profile_json": default_scoring_profile_json(),
        "execution_cost_profile_json": {"base_fill_spread_fraction": 0.25},
        "robustness_profile_json": {"profile_version": "1.0.0", "suite": []},
        "feature_allowlist_json": {"allowed_features": ["UNDERLYING_CLOSE"]},
        "strategy_bounds_json": {"max_free_parameters": 8},
        "agent_config_redacted_json": {"provider": "manual"},
        "evaluator_version": "1.0.0",
        "annual_premium_cap": 0.0025,
    }
    base.update(overrides)
    return CampaignConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scoring profile (TECHNICAL_ARCHITECTURE.md §10)
# ---------------------------------------------------------------------------


class TestScoringProfile:
    def test_default_profile_matches_spec_weights(self) -> None:
        profile = ScoringProfile()
        assert profile.profile_version == SCORING_PROFILE_VERSION
        assert DEFAULT_CAGR_WEIGHT == 1.0
        assert profile.drawdown_weight == DEFAULT_DRAWDOWN_WEIGHT == 0.25
        assert profile.robust_stdev_penalty_weight == 0.5
        assert DEFAULT_ROBUST_STDEV_PENALTY_WEIGHT == 0.50
        assert profile.complexity_free_parameter_threshold == 4
        assert profile.complexity_free_parameter_penalty == 0.00025
        assert profile.complexity_branch_penalty == 0.00010

    def test_fold_utility_matches_architecture_formula(self) -> None:
        # dCAGR + 0.25 x drawdown reduction, hand-calculated.
        u = fold_utility(
            hedged_cagr=0.10,
            unhedged_cagr=0.08,
            hedged_max_drawdown=-0.20,
            unhedged_max_drawdown=-0.40,
        )
        expected = 0.02 + 0.25 * (0.40 - 0.20)
        assert u == pytest.approx(expected)

    def test_fold_utility_matches_metrics_module(self) -> None:
        from tailhedge.backtest.metrics import calculate_fold_utility

        args = (0.10, 0.08, -0.20, -0.40)
        assert fold_utility(*args) == pytest.approx(calculate_fold_utility(*args))

    def test_robust_score_median_minus_stdev(self) -> None:
        utilities = [0.05, 0.10, 0.03]
        score = robust_score(utilities, 0, 0)
        n = len(utilities)
        mean = sum(utilities) / n
        stdev = (sum((u - mean) ** 2 for u in utilities) / (n - 1)) ** 0.5
        assert score == pytest.approx(0.05 - 0.50 * stdev)

    def test_robust_score_single_fold_has_no_stdev_penalty(self) -> None:
        assert robust_score([0.07], 0, 0) == pytest.approx(0.07)

    def test_robust_score_applies_complexity_penalty(self) -> None:
        base = robust_score([0.07], 4, 0)
        with_penalty = robust_score([0.07], 6, 2)
        expected_penalty = 0.00025 * 2 + 0.00010 * 2
        assert base - with_penalty == pytest.approx(expected_penalty)

    def test_complexity_penalty_below_threshold_is_zero(self) -> None:
        assert complexity_penalty(ScoringProfile(), 2, 0) == 0.0

    def test_robust_score_empty_folds_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="at least one fold"):
            robust_score([], 0, 0)

    def test_profile_rejects_negative_weights(self) -> None:
        with pytest.raises(ValueError, match="drawdown_weight"):
            ScoringProfile(drawdown_weight=-0.1)
        with pytest.raises(ValueError, match="robust_stdev_penalty_weight"):
            ScoringProfile(robust_stdev_penalty_weight=-0.1)
        with pytest.raises(ValueError, match="complexity penalties"):
            ScoringProfile(complexity_branch_penalty=-0.001)

    def test_profile_json_round_trip(self) -> None:
        profile = ScoringProfile()
        restored = ScoringProfile.from_json_dict(profile.to_json_dict())
        assert restored == profile

    def test_default_scoring_profile_json_is_versioned(self) -> None:
        data = default_scoring_profile_json()
        assert data["profile_version"] == SCORING_PROFILE_VERSION
        assert data["drawdown_weight"] == 0.25


# ---------------------------------------------------------------------------
# Config hashing / freezing
# ---------------------------------------------------------------------------


class TestCampaignConfigHash:
    def test_manifest_hash_is_deterministic(self) -> None:
        c1 = _config()
        c2 = _config()
        assert c1.manifest_sha256() == c2.manifest_sha256()
        assert len(c1.manifest_sha256()) == 64

    def test_any_frozen_item_change_changes_hash(self) -> None:
        base = _config()
        changed_fields = [
            "portfolio_proxy_json",
            "split_config_json",
            "scoring_profile_json",
            "execution_cost_profile_json",
            "robustness_profile_json",
            "feature_allowlist_json",
            "strategy_bounds_json",
            "agent_config_redacted_json",
            "evaluator_version",
            "max_iterations",
        ]
        for field_name in changed_fields:
            other = _config()
            setattr(other, field_name, {"changed": True})
            assert other.manifest_sha256() != base.manifest_sha256(), field_name

        other = _config(annual_premium_cap=0.005)
        assert other.manifest_sha256() != base.manifest_sha256()

        other = _config()
        other.dataset_id = uuid.uuid4()
        assert other.manifest_sha256() != base.manifest_sha256()

    def test_uuid_and_string_dataset_id_hash_identically(self) -> None:
        dataset_id = uuid.uuid4()
        as_uuid = _config(dataset_id=dataset_id)
        as_string = _config(dataset_id=dataset_id)
        as_string.dataset_id = str(dataset_id)  # type: ignore[assignment]
        assert as_uuid.manifest_sha256() == as_string.manifest_sha256()

    def test_non_serialisable_value_fails_closed(self) -> None:
        config = _config()
        config.split_config_json = {"bad": {1, 2}}
        with pytest.raises(ValueError, match="non-serialisable"):
            config.manifest_sha256()

    def test_frozen_campaign_verify_hash(self) -> None:
        config = _config()
        frozen = FrozenCampaign(config=config, manifest_sha256=config.manifest_sha256())
        assert frozen.verify_hash()

    def test_tampered_frozen_campaign_fails_verification(self) -> None:
        config = _config()
        frozen = FrozenCampaign(config=config, manifest_sha256=config.manifest_sha256())
        config.scoring_profile_json["drawdown_weight"] = 99.0
        assert not frozen.verify_hash()

    def test_max_iterations_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_iterations"):
            _config(max_iterations=0)

    def test_agent_config_rejects_secret_keys(self) -> None:
        for key in ("api_key", "password", "token", "credentials"):
            with pytest.raises(AgentConfigSecretError, match=key):
                _config(agent_config_redacted_json={key: "value"})

    def test_agent_config_rejects_nested_secret_keys(self) -> None:
        with pytest.raises(AgentConfigSecretError, match="api_key"):
            _config(
                agent_config_redacted_json={
                    "provider": "anthropic",
                    "provider_settings": {"api_key": "sk-ant-..."},
                }
            )
        with pytest.raises(AgentConfigSecretError, match="token"):
            _config(agent_config_redacted_json={"providers": [{"token": "x"}]})

    def test_diff_configs_reports_changed_fields(self) -> None:
        old = _config()
        new = _config(scoring_profile_json={"drawdown_weight": 0.5})
        diffs = diff_configs(old, new)
        assert [d.field_name for d in diffs] == ["scoring_profile_json"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_unknown_feature_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown strategy feature"):
            validate_feature_allowlist({"allowed_features": ["NOT_A_FEATURE"]})

    def test_known_feature_accepted(self) -> None:
        validate_feature_allowlist({"allowed_features": ["UNDERLYING_CLOSE"]})

    def test_premium_cap_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="> 0"):
            validate_annual_premium_cap(0.0, APPLICATION_ANNUAL_PREMIUM_CAP)

    def test_premium_cap_within_application_cap(self) -> None:
        validate_annual_premium_cap(0.0025, APPLICATION_ANNUAL_PREMIUM_CAP)
        with pytest.raises(ValueError, match="exceeds"):
            validate_annual_premium_cap(0.02, APPLICATION_ANNUAL_PREMIUM_CAP)

    def test_holdout_overlap_rejected(self) -> None:
        config = _config(
            split_config_json={
                "folds": [
                    {
                        "train_range": {
                            "start_date": "2020-01-01",
                            "end_date": "2020-12-31",
                        },
                        "validation_range": {
                            "start_date": "2021-01-10",
                            "end_date": "2021-12-31",
                        },
                    }
                ],
                "holdout": {"start_date": "2021-06-01", "end_date": "2022-12-31"},
            }
        )
        from tailhedge.research.campaign_config import validate_split_frozen_config

        with pytest.raises(ValueError, match="holdout must not overlap"):
            validate_split_frozen_config(config.split_config_json)

    def test_missing_premium_cap_rejected(self) -> None:
        config = _config()
        config.annual_premium_cap = None
        with pytest.raises(ValueError, match="annual_premium_cap is required"):
            validate_campaign_config(config)

    def test_validate_campaign_config_passes_on_default_config(self) -> None:
        validate_campaign_config(_config())

    def test_scoring_profile_garbage_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            validate_scoring_profile_json("not-a-dict")
        with pytest.raises(ValueError, match="drawdown_weight"):
            validate_scoring_profile_json({"drawdown_weight": "0.25"})
        with pytest.raises(ValueError, match="profile_version"):
            validate_scoring_profile_json({"profile_version": 2})

    def test_execution_cost_profile_unknown_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a FillConfig field"):
            validate_execution_cost_profile_json({"bogus_fill_rule": 1})

    def test_execution_cost_profile_bad_fraction_rejected(self) -> None:
        with pytest.raises(ValueError, match="within \\[0, 1\\]"):
            validate_execution_cost_profile_json({"base_fill_spread_fraction": 1.5})
        with pytest.raises(ValueError, match="must be a number"):
            validate_execution_cost_profile_json({"base_fill_spread_fraction": "0.25"})

    def test_execution_cost_profile_valid(self) -> None:
        validate_execution_cost_profile_json(
            {
                "base_fill_spread_fraction": 0.25,
                "stress_fill_spread_fraction": 0.5,
                "max_quote_age_seconds": 300,
            }
        )

    def test_robustness_profile_unknown_case_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a canonical robustness case"):
            validate_robustness_profile_json(
                {"profile_version": "1.0.0", "suite": ["MY_AD_HOC_TEST"]}
            )

    def test_robustness_profile_garbage_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            validate_robustness_profile_json(["WORSE_FILLS"])
        with pytest.raises(ValueError, match="profile_version"):
            validate_robustness_profile_json({"suite": []})


# ---------------------------------------------------------------------------
# Persistence-backed campaign lifecycle (FR-007, T-008)
# ---------------------------------------------------------------------------


def _seed_dataset(session: Session, *, status: str = "READY"):  # type: ignore[no-untyped-def]
    """Persist a minimal ResearchDataset and return its ID."""
    from datetime import date

    from tailhedge.persistence.models import ResearchDataset

    dataset = ResearchDataset(
        name="test-dataset",
        source_vendor="test",
        schema_version="1",
        timezone="UTC",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        manifest_sha256=uuid.uuid4().hex,
        storage_uri="s3://test",
        status=status,
    )
    session.add(dataset)
    session.commit()
    return dataset.id


def _create(
    session: Session,
    *,
    name: str = "Test Campaign",
    dataset_id: uuid.UUID | None = None,
    config: CampaignConfig | None = None,
) -> ResearchCampaign:
    resolved_dataset_id = (
        dataset_id if dataset_id is not None else _seed_dataset(session)
    )
    return create_campaign(
        session,
        name=name,
        dataset_id=resolved_dataset_id,
        config=config
        if config is not None
        else _config(dataset_id=resolved_dataset_id),
    )


class TestCampaignLifecycle:
    def test_create_campaign_is_draft(self, db_session: Session) -> None:
        campaign = _create(db_session)
        assert campaign.status == "DRAFT"
        assert campaign.campaign_manifest_sha256 is None
        assert campaign.started_at is None

    def test_start_freezes_hash_and_status(self, db_session: Session) -> None:
        campaign = _create(db_session)
        config = _config_from(campaign)
        started = start_campaign(db_session, campaign.id)

        assert started.status == "RUNNING"
        assert started.started_at is not None
        assert started.campaign_manifest_sha256 == config.manifest_sha256()
        assert len(started.campaign_manifest_sha256) == 64

    def test_started_campaign_hash_verifies(self, db_session: Session) -> None:
        campaign = _create(db_session)
        started = start_campaign(db_session, campaign.id)
        config = _config_from(started)
        frozen = FrozenCampaign(
            config=config,
            manifest_sha256=started.campaign_manifest_sha256 or "",
        )
        assert frozen.verify_hash()

    def test_start_is_idempotent_safe_non_draft_rejected(
        self, db_session: Session
    ) -> None:
        campaign = _create(db_session)
        start_campaign(db_session, campaign.id)
        with pytest.raises(CampaignStateError, match="CAMPAIGN_NOT_DRAFT"):
            start_campaign(db_session, campaign.id)

    def test_start_dataset_not_ready_fails_closed(self, db_session: Session) -> None:
        from datetime import date

        from tailhedge.persistence.models import ResearchDataset

        dataset = ResearchDataset(
            name="not ready",
            source_vendor="test",
            schema_version="1",
            timezone="UTC",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            manifest_sha256="a" * 64,
            storage_uri="s3://test",
            status="INGESTING",
        )
        db_session.add(dataset)
        db_session.commit()

        campaign = _create(db_session, dataset_id=dataset.id)
        with pytest.raises(DatasetNotReadyError, match="DATASET_NOT_READY"):
            start_campaign(db_session, campaign.id)
        db_session.refresh(campaign)
        assert campaign.status == "DRAFT"
        assert campaign.campaign_manifest_sha256 is None

    def test_started_campaign_rejects_frozen_field_update(
        self, db_session: Session
    ) -> None:
        campaign = _create(db_session)
        start_campaign(db_session, campaign.id)

        for field_name in (
            "portfolio_proxy_json",
            "split_config_json",
            "scoring_profile_json",
            "execution_cost_profile_json",
            "robustness_profile_json",
            "feature_allowlist_json",
            "strategy_bounds_json",
            "agent_config_redacted_json",
            "evaluator_version",
            "max_iterations",
        ):
            with pytest.raises(CampaignImmutableError, match="clone"):
                update_campaign(db_session, campaign.id, {field_name: {"x": 1}})

        with pytest.raises(CampaignImmutableError, match="clone"):
            update_campaign(db_session, campaign.id, {"dataset_id": uuid.uuid4()})
        with pytest.raises(CampaignImmutableError, match="clone"):
            update_campaign(db_session, campaign.id, {"annual_premium_cap": 0.005})

    def test_create_campaign_persists_premium_cap(self, db_session: Session) -> None:
        campaign = _create(db_session)
        assert campaign.annual_premium_cap == 0.0025

    def test_draft_campaign_allows_frozen_field_update(
        self, db_session: Session
    ) -> None:
        campaign = _create(db_session)
        updated = update_campaign(
            db_session,
            campaign.id,
            {"scoring_profile_json": default_scoring_profile_json()},
        )
        assert updated.status == "DRAFT"

    def test_started_campaign_allows_name_update(self, db_session: Session) -> None:
        campaign = _create(db_session)
        start_campaign(db_session, campaign.id)
        updated = update_campaign(db_session, campaign.id, {"name": "Renamed"})
        assert updated.name == "Renamed"
        # Manifest untouched by metadata rename.
        assert updated.campaign_manifest_sha256 is not None

    def test_update_rejects_unknown_field(self, db_session: Session) -> None:
        campaign = _create(db_session)
        with pytest.raises(ValueError, match="Unknown campaign field"):
            update_campaign(db_session, campaign.id, {"nonsense": 1})


class TestCampaignClone:
    def test_clone_creates_new_draft_with_provenance(self, db_session: Session) -> None:
        campaign = _create(db_session)
        started = start_campaign(db_session, campaign.id)
        source_config = _config_from(started)

        clone = clone_campaign(db_session, campaign.id)

        assert clone.id != started.id
        assert clone.status == "DRAFT"
        assert clone.campaign_manifest_sha256 is None
        assert clone.cloned_from_campaign_id == started.id
        assert clone.name == "Test Campaign (clone)"

        # Full frozen configuration copied.
        for field_name in (
            "dataset_id",
            "portfolio_proxy_json",
            "split_config_json",
            "scoring_profile_json",
            "execution_cost_profile_json",
            "robustness_profile_json",
            "feature_allowlist_json",
            "strategy_bounds_json",
            "agent_config_redacted_json",
            "evaluator_version",
            "max_iterations",
            "annual_premium_cap",
        ):
            assert getattr(clone, field_name) == getattr(started, field_name)

        # Clone can hash to the same manifest before any edit.
        assert _config_from(clone).manifest_sha256() == source_config.manifest_sha256()

    def test_clone_unchanged_start_conflicts_fail_closed(
        self, db_session: Session
    ) -> None:
        from tailhedge.research.campaign_service import CampaignManifestConflictError

        campaign = _create(db_session)
        start_campaign(db_session, campaign.id)

        clone = clone_campaign(db_session, campaign.id)
        with pytest.raises(CampaignManifestConflictError, match="CONFIG_HASH_FAILED"):
            start_campaign(db_session, clone.id)
        db_session.refresh(clone)
        assert clone.status == "DRAFT"
        assert clone.campaign_manifest_sha256 is None

    def test_clone_source_untouched(self, db_session: Session) -> None:
        campaign = _create(db_session)
        started = start_campaign(db_session, campaign.id)
        original_hash = started.campaign_manifest_sha256
        original_status = started.status

        clone_campaign(db_session, campaign.id)

        db_session.refresh(started)
        assert started.status == original_status
        assert started.campaign_manifest_sha256 == original_hash

    def test_clone_config_override_changes_hash(self, db_session: Session) -> None:
        campaign = _create(db_session)
        start_campaign(db_session, campaign.id)

        clone = clone_campaign(
            db_session,
            campaign.id,
            config_overrides={"scoring_profile_json": {"profile_version": "2.0.0"}},
        )
        assert _config_from(clone).manifest_sha256() != (
            _config_from(_get_started(db_session, campaign.id)).manifest_sha256()
        )

    def test_clone_rejects_unknown_override(self, db_session: Session) -> None:
        campaign = _create(db_session)
        with pytest.raises(ValueError, match="Unknown campaign config field"):
            clone_campaign(db_session, campaign.id, config_overrides={"bogus": 1})

    def test_clone_nonexistent_campaign(self, db_session: Session) -> None:
        with pytest.raises(CampaignNotFoundError):
            clone_campaign(db_session, uuid.uuid4())

    def test_list_campaigns_filters_by_status(self, db_session: Session) -> None:
        c1 = _create(db_session, name="draft-one")
        c2 = _create(db_session, name="started")
        start_campaign(db_session, c2.id)

        all_campaigns = list_campaigns(db_session)
        assert {c.id for c in all_campaigns} == {c1.id, c2.id}
        drafts = list_campaigns(db_session, status="DRAFT")
        assert {c.id for c in drafts} == {c1.id}
        running = list_campaigns(db_session, status="RUNNING")
        assert {c.id for c in running} == {c2.id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_from(campaign: ResearchCampaign) -> CampaignConfig:
    from tailhedge.research.campaign_service import _config_from_campaign

    return _config_from_campaign(campaign)


def _get_started(db_session: Session, campaign_id: uuid.UUID) -> ResearchCampaign:
    started = get_campaign(db_session, campaign_id)
    assert started is not None
    return started


# ---------------------------------------------------------------------------
# HTTP API tests (FR-007, T-008 clone path via API)
# ---------------------------------------------------------------------------


class TestCampaignAPI:
    def _api_session(self) -> tuple[TestClient, str, str]:
        from fastapi.testclient import TestClient

        from tailhedge.web.app import app
        from tailhedge.web.auth import (
            _SESSION_COOKIE,
            create_session_cookie,
            generate_csrf_token,
            generate_session_id,
        )

        session_id = generate_session_id()
        client = TestClient(
            app, cookies={_SESSION_COOKIE: create_session_cookie(session_id, 3600)}
        )
        return client, session_id, generate_csrf_token(session_id)

    def test_campaign_api_requires_auth(self) -> None:
        from fastapi.testclient import TestClient

        from tailhedge.web.app import app

        resp = TestClient(app, follow_redirects=False).get("/api/v1/campaigns")
        assert resp.status_code == 303

    def test_create_start_clone_via_api(self, db_session: Session) -> None:
        from tailhedge.persistence.engine import get_session
        from tailhedge.web.app import app

        dataset_id = _seed_dataset(db_session)

        def override() -> object:
            yield db_session

        app.dependency_overrides[get_session] = override
        try:
            client, _session_id, csrf = self._api_session()

            resp = client.post(
                "/api/v1/campaigns",
                json={"name": "API Campaign", "dataset_id": str(dataset_id)},
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "DRAFT"
            campaign_id = body["id"]
            assert body["scoring_profile_json"]["immutable"] is True

            resp = client.post(
                f"/api/v1/campaigns/{campaign_id}/start",
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "RUNNING"
            assert resp.json()["campaign_manifest_sha256"]

            resp = client.post(
                f"/api/v1/campaigns/{campaign_id}/start",
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 409
            assert resp.json()["detail"] == "CAMPAIGN_NOT_DRAFT"

            resp = client.post(
                f"/api/v1/campaigns/{campaign_id}/clone",
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200
            clone = resp.json()
            assert clone["status"] == "DRAFT"
            assert clone["cloned_from_campaign_id"] == campaign_id
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_create_api_premium_cap_respected_and_validated(
        self, db_session: Session
    ) -> None:
        from tailhedge.persistence.engine import get_session
        from tailhedge.web.app import app

        dataset_id = _seed_dataset(db_session)

        def override() -> object:
            yield db_session

        app.dependency_overrides[get_session] = override
        try:
            client, _session_id, csrf = self._api_session()

            resp = client.post(
                "/api/v1/campaigns",
                json={
                    "name": "Capped Campaign",
                    "dataset_id": str(dataset_id),
                    "annual_premium_cap": 0.0025,
                },
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["annual_premium_cap"]["value"] == 0.0025
            assert body["annual_premium_cap"]["immutable"] is True

            # Cap above the application safety cap fails closed with 422.
            resp = client.post(
                "/api/v1/campaigns",
                json={
                    "name": "Too Generous",
                    "dataset_id": str(dataset_id),
                    "annual_premium_cap": 0.05,
                },
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 422
            assert "exceeds" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_create_api_rejects_bad_numeric_input(self, db_session: Session) -> None:
        from tailhedge.persistence.engine import get_session
        from tailhedge.web.app import app

        dataset_id = _seed_dataset(db_session)

        def override() -> object:
            yield db_session

        app.dependency_overrides[get_session] = override
        try:
            client, _session_id, csrf = self._api_session()

            resp = client.post(
                "/api/v1/campaigns",
                json={
                    "name": "Bad Cap",
                    "dataset_id": str(dataset_id),
                    "annual_premium_cap": "not-a-number",
                },
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 422

            resp = client.post(
                "/api/v1/campaigns",
                json={
                    "name": "Bad Iterations",
                    "dataset_id": str(dataset_id),
                    "max_iterations": "ten",
                },
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_start_clone_unchanged_returns_config_hash_failed(
        self, db_session: Session
    ) -> None:
        from tailhedge.persistence.engine import get_session
        from tailhedge.web.app import app

        dataset_id = _seed_dataset(db_session)

        def override() -> object:
            yield db_session

        app.dependency_overrides[get_session] = override
        try:
            client, _session_id, csrf = self._api_session()

            resp = client.post(
                "/api/v1/campaigns",
                json={"name": "Conflict Campaign", "dataset_id": str(dataset_id)},
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200
            campaign_id = resp.json()["id"]

            resp = client.post(
                f"/api/v1/campaigns/{campaign_id}/start",
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200

            resp = client.post(
                f"/api/v1/campaigns/{campaign_id}/clone",
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200
            clone_id = resp.json()["id"]

            resp = client.post(
                f"/api/v1/campaigns/{clone_id}/start",
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 409
            assert resp.json()["detail"] == "CONFIG_HASH_FAILED"
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_clone_api_rejects_nonexistent_dataset_override(
        self, db_session: Session
    ) -> None:
        from tailhedge.persistence.engine import get_session
        from tailhedge.web.app import app

        dataset_id = _seed_dataset(db_session)

        def override() -> object:
            yield db_session

        app.dependency_overrides[get_session] = override
        try:
            client, _session_id, csrf = self._api_session()

            resp = client.post(
                "/api/v1/campaigns",
                json={"name": "Source Campaign", "dataset_id": str(dataset_id)},
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200
            campaign_id = resp.json()["id"]

            resp = client.post(
                f"/api/v1/campaigns/{campaign_id}/clone",
                headers={"x-csrf-token": csrf},
            )
            assert resp.status_code == 200

            # Override pointing at a missing dataset fails closed (422), not FK 500.
            resp = client.post(
                f"/api/v1/campaigns/{campaign_id}/clone",
                headers={"x-csrf-token": csrf},
                json={"config_overrides": {"dataset_id": str(uuid.uuid4())}},
            )
            assert resp.status_code == 422
            assert "does not exist" in resp.json()["detail"]

            # Unknown override fields also fail closed.
            resp = client.post(
                f"/api/v1/campaigns/{campaign_id}/clone",
                headers={"x-csrf-token": csrf},
                json={"config_overrides": {"bogus_field": 1}},
            )
            assert resp.status_code == 422
            assert "Unknown campaign config field" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_session, None)
