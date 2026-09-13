"""Campaign configuration, scoring profile, and manifest hashing (TASK-021).

Implements FR-007: when a campaign starts, the system freezes and hashes
the complete evaluation configuration.  After start the configuration is
immutable; changing any item requires cloning the campaign (a new
``DRAFT`` campaign) so prior results are never silently re-interpreted.

The default scoring profile follows TECHNICAL_ARCHITECTURE.md §10 and is
an implementation assumption (ADR-016 / OQ-005): it is versioned
configuration, never hard-coded financial truth.  Underlying metrics are
always reported alongside the scalar.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from decimal import Decimal
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

SCORING_PROFILE_VERSION = "1.0.0"
"""Version of the default scoring profile (TECHNICAL_ARCHITECTURE.md §10)."""

ROBUSTNESS_PROFILE_VERSION = "1.0.0"
"""Version of the canonical robustness suite configuration."""

CANONICAL_ROBUSTNESS_CASES: tuple[str, ...] = (
    "WORSE_FILLS",
    "PREMIUM_INFLATION",
    "DECISION_DELAY",
    "PARAMETER_PERTURBATION",
    "LEAVE_ONE_REGIME_OUT",
    "DOMINANT_EVENT_REMOVAL",
    "BASIS_PERTURBATION",
    "SYNTHETIC_CRASH",
)
"""Canonical robustness suite cases; arbitrary ad-hoc cases are rejected."""

EVALUATOR_VERSION = "1.0.0"
"""Evaluator/backtester version recorded at campaign freeze time.

The OCI evaluator image digest (``tailhedge.research.evaluator``) is
resolved at campaign start and recorded alongside this logical version.
"""

# Default scoring weights (implementation assumption, versioned config).
DEFAULT_CAGR_WEIGHT = 1.0
DEFAULT_DRAWDOWN_WEIGHT = 0.25
DEFAULT_ROBUST_MEDIAN_WEIGHT = 1.0
DEFAULT_ROBUST_STDEV_PENALTY_WEIGHT = 0.50
DEFAULT_COMPLEXITY_FREE_PARAMETER_THRESHOLD = 4
DEFAULT_COMPLEXITY_FREE_PARAMETER_PENALTY = 0.00025
DEFAULT_COMPLEXITY_BRANCH_PENALTY = 0.00010

IMMUTABLE_CONFIG_FIELDS: tuple[str, ...] = (
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
)
"""Config columns that are frozen once the campaign leaves DRAFT (FR-007).

``annual_premium_cap`` is included because it is a gate input that changes
evaluation semantics; it is validated within the application safety cap at
validation time (OQ-004/ADR-024).
"""

# Keys that must never appear in frozen agent configuration (no secrets).
_AGENT_CONFIG_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "api_secret",
        "secret",
        "password",
        "token",
        "credentials",
        "database_url",
        "session_secret",
        "broker_password",
        "ibkr_password",
        "holdout",
        "holdout_metrics",
    }
)


class CampaignStatus(StrEnum):
    """Campaign lifecycle states (DATA_MODEL.md §4.1)."""

    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CampaignConfigError(ValueError):
    """Raised when campaign configuration is invalid."""


class CampaignStateError(Exception):
    """Raised when a state transition is not permitted."""


class CampaignImmutableError(Exception):
    """Raised when an update would mutate a started campaign's frozen config."""


class AgentConfigSecretError(CampaignConfigError):
    """Raised when agent configuration contains a secret-looking key."""


# ---------------------------------------------------------------------------
# Scoring profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoringProfile:
    """Versioned scoring profile frozen per campaign (ADR-016).

    Defaults implement TECHNICAL_ARCHITECTURE.md §10::

        fold_utility = (hedged_CAGR - unhedged_CAGR)
                     + 0.25 * (abs(unhedged_dd) - abs(hedged_dd))

        robust_score = median(fold_utility)
                     - 0.50 * stdev(fold_utility)
                     - complexity_penalty

    All rates are decimals.  Premium cost is already reflected in hedged
    CAGR and bounded separately by the annual premium cap, avoiding
    double counting in the base score.
    """

    profile_version: str = SCORING_PROFILE_VERSION
    drawdown_weight: float = DEFAULT_DRAWDOWN_WEIGHT
    robust_median_weight: float = DEFAULT_ROBUST_MEDIAN_WEIGHT
    robust_stdev_penalty_weight: float = DEFAULT_ROBUST_STDEV_PENALTY_WEIGHT
    complexity_free_parameter_threshold: int = (
        DEFAULT_COMPLEXITY_FREE_PARAMETER_THRESHOLD
    )
    complexity_free_parameter_penalty: float = DEFAULT_COMPLEXITY_FREE_PARAMETER_PENALTY
    complexity_branch_penalty: float = DEFAULT_COMPLEXITY_BRANCH_PENALTY

    def __post_init__(self) -> None:
        if self.drawdown_weight < 0:
            msg = f"drawdown_weight must be non-negative, got {self.drawdown_weight}"
            raise CampaignConfigError(msg)
        if self.robust_stdev_penalty_weight < 0:
            msg = (
                f"robust_stdev_penalty_weight must be non-negative, "
                f"got {self.robust_stdev_penalty_weight}"
            )
            raise CampaignConfigError(msg)
        if self.complexity_free_parameter_penalty < 0 or (
            self.complexity_branch_penalty < 0
        ):
            msg = "complexity penalties must be non-negative"
            raise CampaignConfigError(msg)
        if self.complexity_free_parameter_threshold < 0:
            msg = "complexity_free_parameter_threshold must be non-negative"
            raise CampaignConfigError(msg)

    def to_json_dict(self) -> dict[str, Any]:
        """Serialise for persistence in ``scoring_profile_json``."""
        return {
            "profile_version": self.profile_version,
            "drawdown_weight": self.drawdown_weight,
            "robust_median_weight": self.robust_median_weight,
            "robust_stdev_penalty_weight": self.robust_stdev_penalty_weight,
            "complexity_free_parameter_threshold": (
                self.complexity_free_parameter_threshold
            ),
            "complexity_free_parameter_penalty": (
                self.complexity_free_parameter_penalty
            ),
            "complexity_branch_penalty": self.complexity_branch_penalty,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> ScoringProfile:
        """Reconstruct a profile from persisted JSON."""
        return cls(
            profile_version=data.get("profile_version", SCORING_PROFILE_VERSION),
            drawdown_weight=data.get("drawdown_weight", DEFAULT_DRAWDOWN_WEIGHT),
            robust_median_weight=data.get(
                "robust_median_weight", DEFAULT_ROBUST_MEDIAN_WEIGHT
            ),
            robust_stdev_penalty_weight=data.get(
                "robust_stdev_penalty_weight",
                DEFAULT_ROBUST_STDEV_PENALTY_WEIGHT,
            ),
            complexity_free_parameter_threshold=data.get(
                "complexity_free_parameter_threshold",
                DEFAULT_COMPLEXITY_FREE_PARAMETER_THRESHOLD,
            ),
            complexity_free_parameter_penalty=data.get(
                "complexity_free_parameter_penalty",
                DEFAULT_COMPLEXITY_FREE_PARAMETER_PENALTY,
            ),
            complexity_branch_penalty=data.get(
                "complexity_branch_penalty", DEFAULT_COMPLEXITY_BRANCH_PENALTY
            ),
        )


def complexity_penalty(
    profile: ScoringProfile,
    free_parameter_count: int,
    conditional_branch_count: int,
) -> float:
    """Compute the complexity penalty (TECHNICAL_ARCHITECTURE.md §10)."""
    excess = max(0, free_parameter_count - profile.complexity_free_parameter_threshold)
    return (
        profile.complexity_free_parameter_penalty * excess
        + profile.complexity_branch_penalty * conditional_branch_count
    )


def fold_utility(
    hedged_cagr: float,
    unhedged_cagr: float,
    hedged_max_drawdown: float,
    unhedged_max_drawdown: float,
    profile: ScoringProfile | None = None,
) -> float:
    """Compute fold utility from hedged/unhedged metrics.

    ``(hedged_CAGR - unhedged_CAGR) + w * drawdown reduction``.  Drawdown
    reduction = ``abs(unhedged_dd) - abs(hedged_dd)``; drawdowns are
    negative decimals per ``tailhedge.backtest.metrics``.
    """
    w = profile.drawdown_weight if profile is not None else DEFAULT_DRAWDOWN_WEIGHT
    cagr_delta = hedged_cagr - unhedged_cagr
    dd_reduction = abs(unhedged_max_drawdown) - abs(hedged_max_drawdown)
    return cagr_delta + w * dd_reduction


def robust_score(
    fold_utilities: list[float],
    free_parameter_count: int,
    conditional_branch_count: int,
    profile: ScoringProfile | None = None,
) -> float:
    """Compute the robust score from per-fold utilities.

    ``median(fold_utility) - k * stdev(fold_utility) - complexity_penalty``.
    With a single fold the stdev term is zero.
    """
    p = profile if profile is not None else ScoringProfile()
    if not fold_utilities:
        msg = "robust_score requires at least one fold utility"
        raise CampaignConfigError(msg)
    n = len(fold_utilities)
    mean = sum(fold_utilities) / n
    if n > 1:
        variance = sum((u - mean) ** 2 for u in fold_utilities) / (n - 1)
        stdev = variance**0.5
    else:
        stdev = 0.0
    ordered = sorted(fold_utilities)
    if n % 2 == 1:
        median = ordered[n // 2]
    else:
        median = (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    penalty = complexity_penalty(p, free_parameter_count, conditional_branch_count)
    result = (
        p.robust_median_weight * median
        - p.robust_stdev_penalty_weight * stdev
        - penalty
    )
    return float(result)


# ---------------------------------------------------------------------------
# Frozen configuration
# ---------------------------------------------------------------------------


@dataclass
class CampaignConfig:
    """The complete frozen evaluation configuration of a campaign (FR-007).

    Field values are JSON-serialisable dictionaries/strings; the campaign
    manifest hash is computed over the canonical JSON encoding so that any
    semantic change produces a different hash.
    """

    dataset_id: uuid.UUID
    portfolio_proxy_json: dict[str, Any]
    split_config_json: dict[str, Any]
    scoring_profile_json: dict[str, Any]
    execution_cost_profile_json: dict[str, Any]
    robustness_profile_json: dict[str, Any]
    feature_allowlist_json: dict[str, Any]
    strategy_bounds_json: dict[str, Any]
    agent_config_redacted_json: dict[str, Any]
    evaluator_version: str
    max_iterations: int | None = None
    annual_premium_cap: float | None = None

    def __post_init__(self) -> None:
        if self.max_iterations is not None and self.max_iterations < 1:
            msg = f"max_iterations must be >= 1, got {self.max_iterations}"
            raise CampaignConfigError(msg)
        _reject_secret_keys(self.agent_config_redacted_json)

    @property
    def scoring_profile(self) -> ScoringProfile:
        """Reconstruct the scoring profile from its frozen JSON."""
        return ScoringProfile.from_json_dict(self.scoring_profile_json)

    def as_field_values(self) -> dict[str, Any]:
        """Return field/value mapping for persistence and diffing."""
        return {name: getattr(self, name) for name in IMMUTABLE_CONFIG_FIELDS}

    def manifest_sha256(self) -> str:
        """Compute the SHA-256 manifest hash over the frozen configuration.

        Canonical encoding: sorted keys, compact separators, UTF-8.  UUIDs
        are serialised explicitly; any value that is not JSON-serialisable
        raises instead of being silently stringified (fail closed).
        """
        try:
            payload = {
                name: _json_safe(getattr(self, name))
                for name in IMMUTABLE_CONFIG_FIELDS
            }
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except TypeError as exc:
            msg = f"campaign config contains non-serialisable value: {exc}"
            raise CampaignConfigError(msg) from exc
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    """Convert a config value to a canonically JSON-encodable form.

    UUIDs become their canonical string form (the same textual form used
    everywhere at the persistence boundary, so a UUID and its string form
    hash identically — they denote the same dataset).  ``Decimal`` becomes
    ``float`` so a value loaded from a NUMERIC column hashes the same as
    the float it was frozen from.  Anything else non-serialisable raises
    ``TypeError`` for the caller to wrap (fail closed).
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    msg = f"non-serialisable config value of type {type(value).__name__}"
    raise TypeError(msg)


def _reject_secret_keys(agent_config: dict[str, Any]) -> None:
    """Fail closed if agent configuration contains secret-looking keys.

    The check is recursive: nested objects (e.g. per-provider settings) are
    walked as well, so a credential cannot hide one level down.
    """
    _reject_secret_keys_in_value(agent_config, context="agent_config_redacted_json")


def _reject_secret_keys_in_value(value: Any, *, context: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _AGENT_CONFIG_FORBIDDEN_KEYS:
                msg = (
                    f"{context} key {key!r} looks like a secret; "
                    f"agent_config_redacted_json must never contain credentials"
                )
                raise AgentConfigSecretError(msg)
            _reject_secret_keys_in_value(nested, context=f"{context}[{key!r}]")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secret_keys_in_value(item, context=f"{context}[{index}]")


def default_scoring_profile_json() -> dict[str, Any]:
    """Return the default scoring profile JSON (architecture spec §10)."""
    return ScoringProfile().to_json_dict()


def default_robustness_profile_json() -> dict[str, Any]:
    """Return the default robustness profile JSON."""
    return {
        "profile_version": ROBUSTNESS_PROFILE_VERSION,
        "suite": list(CANONICAL_ROBUSTNESS_CASES),
    }


def default_feature_allowlist_json() -> dict[str, Any]:
    """Return the default (empty) feature allowlist JSON."""
    return {"allowed_features": []}


def default_strategy_bounds_json() -> dict[str, Any]:
    """Return the default strategy bounds JSON."""
    return {
        "max_free_parameters": 8,
        "max_conditional_branches": 4,
    }


def validate_feature_allowlist(feature_allowlist_json: dict[str, Any]) -> None:
    """Validate the feature allowlist against the SDK feature surface."""
    from tailhedge.domain.strategy_sdk import StrategyFeature

    allowed = feature_allowlist_json.get("allowed_features")
    if not isinstance(allowed, list):
        msg = "feature_allowlist_json['allowed_features'] must be a list"
        raise CampaignConfigError(msg)
    known = {f.value for f in StrategyFeature}
    for name in allowed:
        if name not in known:
            msg = f"unknown strategy feature {name!r}; known: {sorted(known)}"
            raise CampaignConfigError(msg)


def validate_scoring_profile_json(scoring_profile_json: Any) -> ScoringProfile:
    """Validate the frozen scoring profile JSON (SB-002 precondition).

    Must be an object whose numeric fields have numeric types; rebuilds the
    profile so the non-negativity checks in ``ScoringProfile.__post_init__``
    run.  Returns the reconstructed profile.
    """
    if not isinstance(scoring_profile_json, dict):
        msg = "scoring_profile_json must be a JSON object"
        raise CampaignConfigError(msg)
    profile_version = scoring_profile_json.get("profile_version")
    if profile_version is not None and not isinstance(profile_version, str):
        msg = "scoring_profile_json['profile_version'] must be a string"
        raise CampaignConfigError(msg)
    for field in (
        "drawdown_weight",
        "robust_median_weight",
        "robust_stdev_penalty_weight",
        "complexity_free_parameter_penalty",
        "complexity_branch_penalty",
    ):
        raw = scoring_profile_json.get(field)
        if raw is not None and (
            isinstance(raw, bool) or not isinstance(raw, (int, float))
        ):
            msg = f"scoring_profile_json[{field!r}] must be a number"
            raise CampaignConfigError(msg)
    threshold = scoring_profile_json.get("complexity_free_parameter_threshold")
    if threshold is not None and (
        isinstance(threshold, bool) or not isinstance(threshold, int)
    ):
        msg = (
            "scoring_profile_json['complexity_free_parameter_threshold'] "
            "must be an integer"
        )
        raise CampaignConfigError(msg)
    profile = ScoringProfile.from_json_dict(scoring_profile_json)
    profile.to_json_dict()
    return profile


def validate_execution_cost_profile_json(execution_cost_profile_json: Any) -> None:
    """Validate the frozen execution-cost profile JSON.

    Keys must match the ``FillConfig`` surface (unknown keys fail closed so
    a typo cannot silently change fill semantics); numeric values must be
    numbers in valid ranges.
    """
    if not isinstance(execution_cost_profile_json, dict):
        msg = "execution_cost_profile_json must be a JSON object"
        raise CampaignConfigError(msg)

    from tailhedge.backtest.fill_model import FillConfig

    known_fields = {f.name for f in dataclass_fields(FillConfig)}
    for key, value in execution_cost_profile_json.items():
        if key not in known_fields:
            msg = (
                f"execution_cost_profile_json[{key!r}] is not a FillConfig "
                f"field; known: {sorted(known_fields)}"
            )
            raise CampaignConfigError(msg)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            msg = f"execution_cost_profile_json[{key!r}] must be a number"
            raise CampaignConfigError(msg)
    for key in ("base_fill_spread_fraction", "stress_fill_spread_fraction"):
        raw = execution_cost_profile_json.get(key)
        if raw is not None and not 0 <= float(raw) <= 1:
            msg = f"execution_cost_profile_json[{key!r}] must be within [0, 1]"
            raise CampaignConfigError(msg)
    for key in ("max_relative_spread", "commission_per_contract", "tick_size"):
        raw = execution_cost_profile_json.get(key)
        if raw is not None and float(raw) < 0:
            msg = f"execution_cost_profile_json[{key!r}] must be non-negative"
            raise CampaignConfigError(msg)
    age = execution_cost_profile_json.get("max_quote_age_seconds")
    if age is not None and (isinstance(age, bool) or not isinstance(age, int)):
        msg = "execution_cost_profile_json['max_quote_age_seconds'] must be an integer"
        raise CampaignConfigError(msg)


_CANONICAL_ROBUSTNESS_CASES: frozenset[str] = frozenset(CANONICAL_ROBUSTNESS_CASES)


def validate_robustness_profile_json(robustness_profile_json: Any) -> None:
    """Validate the frozen robustness profile JSON (SB-002 precondition).

    The suite may only contain canonical case names; arbitrary ad-hoc tests
    cannot be smuggled in under the canonical gate (API_SPEC §6).
    """
    if not isinstance(robustness_profile_json, dict):
        msg = "robustness_profile_json must be a JSON object"
        raise CampaignConfigError(msg)
    profile_version = robustness_profile_json.get("profile_version")
    if not isinstance(profile_version, str) or not profile_version:
        msg = "robustness_profile_json['profile_version'] must be a non-empty string"
        raise CampaignConfigError(msg)
    suite = robustness_profile_json.get("suite")
    if not isinstance(suite, list):
        msg = "robustness_profile_json['suite'] must be a list"
        raise CampaignConfigError(msg)
    for case in suite:
        if case not in _CANONICAL_ROBUSTNESS_CASES:
            msg = (
                f"robustness_profile_json case {case!r} is not a canonical "
                f"robustness case; known: {sorted(_CANONICAL_ROBUSTNESS_CASES)}"
            )
            raise CampaignConfigError(msg)


def validate_annual_premium_cap(
    annual_premium_cap: float,
    application_cap: float,
) -> None:
    """Validate the campaign annual premium cap (API_SPEC §5).

    Must be > 0 and within the application safety configuration
    (OQ-004 default: 1.0%).
    """
    if isinstance(annual_premium_cap, bool) or not isinstance(
        annual_premium_cap, (int, float)
    ):
        msg = f"annual premium cap must be a number, got {annual_premium_cap!r}"
        raise CampaignConfigError(msg)
    if annual_premium_cap <= 0:
        msg = f"annual premium cap must be > 0, got {annual_premium_cap}"
        raise CampaignConfigError(msg)
    if annual_premium_cap > application_cap:
        msg = (
            f"annual premium cap {annual_premium_cap} exceeds the "
            f"application safety cap {application_cap}"
        )
        raise CampaignConfigError(msg)


@dataclass(frozen=True)
class FrozenCampaign:
    """A campaign snapshot after ``start`` freezes its configuration.

    Carries the manifest hash and evaluator digest verified before every
    evaluation iteration (SB-002 step 5).
    """

    config: CampaignConfig
    manifest_sha256: str
    evaluator_image_digest: str | None = None
    frozen_at: str | None = None

    def verify_hash(self) -> bool:
        """Return True if the frozen config still hashes to the manifest."""
        return self.config.manifest_sha256() == self.manifest_sha256


@dataclass
class ConfigDiff:
    """Difference between two campaign configurations."""

    field_name: str
    old_value: Any = None
    new_value: Any = None


def diff_configs(
    old: CampaignConfig,
    new: CampaignConfig,
) -> list[ConfigDiff]:
    """Return the differing fields between two campaign configurations."""
    diffs: list[ConfigDiff] = []
    for name in IMMUTABLE_CONFIG_FIELDS:
        old_value = getattr(old, name)
        new_value = getattr(new, name)
        if old_value != new_value:
            diffs.append(
                ConfigDiff(
                    field_name=name,
                    old_value=old_value,
                    new_value=new_value,
                )
            )
    return diffs


def validate_split_frozen_config(split_config_json: dict[str, Any]) -> None:
    """Validate a frozen split config JSON for internal consistency.

    When the config carries fold/holdout date ranges, checks that the
    final holdout does not overlap train/validation ranges (API_SPEC §5).
    Missing fold detail is acceptable — the canonical split objects in
    ``tailhedge.backtest.splits`` perform the full purge/embargo checks.
    """
    folds = split_config_json.get("folds")
    if folds is None:
        return
    if not isinstance(folds, list):
        msg = "split_config_json['folds'] must be a list"
        raise CampaignConfigError(msg)

    def _parse_range(raw: dict[str, Any], label: str) -> tuple[str, str]:
        try:
            return raw["start_date"], raw["end_date"]
        except (KeyError, TypeError) as exc:
            msg = f"{label} must have start_date/end_date"
            raise CampaignConfigError(msg) from exc

    def _overlaps(a: tuple[str, str], b: tuple[str, str]) -> bool:
        return a[0] <= b[1] and b[0] <= a[1]

    research_ranges: list[tuple[str, str]] = []
    for fold in folds:
        train = _parse_range(fold.get("train_range", {}), "train_range")
        validation = _parse_range(fold.get("validation_range", {}), "validation_range")
        if train[0] > train[1] or validation[0] > validation[1]:
            msg = "fold date ranges must have start_date <= end_date"
            raise CampaignConfigError(msg)
        if _overlaps(train, validation):
            msg = "fold train/validation ranges must not overlap"
            raise CampaignConfigError(msg)
        research_ranges.extend((train, validation))

    holdout = split_config_json.get("holdout")
    if holdout:
        holdout_range = _parse_range(holdout, "holdout")
        if holdout_range[0] > holdout_range[1]:
            msg = "holdout range must have start_date <= end_date"
            raise CampaignConfigError(msg)
        for r in research_ranges:
            if _overlaps(r, holdout_range):
                msg = "final holdout must not overlap train/validation (FR-010)"
                raise CampaignConfigError(msg)
