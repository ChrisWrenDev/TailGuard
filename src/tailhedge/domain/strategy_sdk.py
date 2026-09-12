"""Strategy SDK and target-plan contract.

Implements FR-006: a versioned pure-policy interface that consumes only
permitted ``StrategyContext`` fields and returns a ``TargetHedgePlan``.

A strategy must not:
- receive broker credentials, secret holdout data, evaluator internals,
  filesystem paths outside its sandbox, or network access;
- produce order intents, broker references, or any broker-side action;
- access any feature not explicitly enabled in its feature allowlist.

The SDK enforces:
1. ``StrategyContext`` contains only time-appropriate, permitted features.
2. ``TargetHedgePlan`` output is declarative and schema-validated.
3. Prohibited output fields are rejected at validation time.
4. Versioned interface ensures forward compatibility without silent breaks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Feature flags — what a strategy may see
# ---------------------------------------------------------------------------


class StrategyFeature(StrEnum):
    """Allowed feature surface for strategy context.

    Each feature corresponds to a specific category of data that a strategy
    may access.  Features must be explicitly enabled per campaign; absent
    features are excluded from the context.
    """

    CURRENT_PORTFOLIO = "CURRENT_PORTFOLIO"
    """Current portfolio snapshot: cash, units, benchmark value."""

    EXISTING_HEDGE_POSITIONS = "EXISTING_HEDGE_POSITIONS"
    """Currently held long-put positions with entry premiums."""

    OPTION_CHAIN_QUOTES = "OPTION_CHAIN_QUOTES"
    """Current option-chain quotes (bid/ask/underlying) for eligible
    contracts."""

    ROLL_ELIGIBILITY = "ROLL_ELIGIBILITY"
    """DTE-based roll eligibility signals."""

    MONETISATION_SIGNALS = "MONETISATION_SIGNALS"
    """Profitability indicators for existing positions."""

    BUDGET_CONSUMPTION = "BUDGET_CONSUMPTION"
    """Annual hedge budget consumed-to-date and remaining allowance."""

    UNDERLYING_CLOSE = "UNDERLYING_CLOSE"
    """Current underlying price (SPX/SPX index close)."""


# ---------------------------------------------------------------------------
# Portfolio snapshot (subset exposed to strategy)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Subset of portfolio state exposed to the strategy.

    Does NOT include raw broker references, account IDs, or credentials.
    """

    total_value: float
    """Combined portfolio value (cash + units * underlying)."""

    cash: float
    """Available cash balance (base currency)."""

    units: float
    """Core portfolio instrument unit count."""

    base_currency: str
    """ISO 4217 base currency code."""

    benchmark_equivalent_exposure: float = 0.0
    """Total benchmark-equivalent exposure across hedge-eligible holdings."""


# ---------------------------------------------------------------------------
# Existing position snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HedgePositionSnapshot:
    """A single long-put position held in the portfolio.

    Exposed to the strategy for roll/monetisation decisions.
    """

    strike: float
    """Strike price of the put."""

    expiration_date: date
    """Expiration date of the put."""

    quantity: int
    """Number of contracts held (positive = long)."""

    entry_premium: float
    """Premium per unit paid at acquisition."""

    current_dte: int
    """Calendar days to expiry as of the context timestamp."""


# ---------------------------------------------------------------------------
# Option quote snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionQuoteSnapshot:
    """A single option-chain quote exposed to the strategy.

    Contains only tradability-relevant fields; no internal identifiers
    or broker references.
    """

    trade_date: date
    """Trade date of the quote."""

    strike: float
    """Strike price."""

    expiration_date: date
    """Expiration date."""

    bid: float
    """Bid price."""

    ask: float
    """Ask price."""

    underlying_price: float
    """Underlying price at the time of the quote."""


# ---------------------------------------------------------------------------
# StrategyContext — the input to a strategy's decide() call
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyContext:
    """Versioned context provided to a strategy's ``decide`` method.

    Contains only the features explicitly enabled in the campaign's feature
    allowlist.  Features not in the allowlist are absent (None) and must
    not be accessed by the strategy.

    Security invariants:
    - No broker credentials, account IDs, or secrets.
    - No future data or holdout data.
    - No evaluator internals, file paths, or network access.
    - No ability to produce order intents or broker references.
    """

    trade_date: date
    """Current trade date (decision timestamp)."""

    underlying_close: float
    """Underlying close price on the trade date."""

    schema_version: str = SCHEMA_VERSION
    """SDK schema version."""

    enabled_features: frozenset[StrategyFeature] = field(default_factory=frozenset)
    """Features enabled for this context.  Strategy code should only access
    fields corresponding to enabled features; accessing disabled fields is
    a contract violation."""

    portfolio: PortfolioSnapshot | None = None
    """Current portfolio snapshot (requires CURRENT_PORTFOLIO feature)."""

    positions: tuple[HedgePositionSnapshot, ...] = ()
    """Current hedge positions (requires EXISTING_HEDGE_POSITIONS feature)."""

    option_chain: tuple[OptionQuoteSnapshot, ...] = ()
    """Option chain quotes (requires OPTION_CHAIN_QUOTES feature)."""

    budget_consumed_ytd: float = 0.0
    """Annual hedge premium budget consumed to date
    (requires BUDGET_CONSUMPTION feature)."""

    budget_remaining: float = 0.0
    """Remaining annual hedge premium budget
    (requires BUDGET_CONSUMPTION feature)."""

    budget_cap_pct: float = 0.0
    """Annual budget cap as a fraction of portfolio value
    (requires BUDGET_CONSUMPTION feature)."""

    def has_feature(self, feature: StrategyFeature) -> bool:
        """Check if a feature is enabled in this context."""
        return feature in self.enabled_features

    def require_feature(self, feature: StrategyFeature) -> None:
        """Raise if the feature is not enabled.

        Strategies should call this before accessing feature-specific data.
        """
        if not self.has_feature(feature):
            msg = (
                f"Feature '{feature}' is not enabled in this context; "
                f"enabled features: {sorted(self.enabled_features)}"
            )
            raise FeatureNotEnabledError(msg)


class FeatureNotEnabledError(Exception):
    """Raised when a strategy attempts to access a disabled feature."""


# ---------------------------------------------------------------------------
# Target plan components
# ---------------------------------------------------------------------------


class HedgeAction(StrEnum):
    """Actions a strategy may request for a single hedge tranche."""

    BUY_PUT = "BUY_PUT"
    """Buy a new long-put position."""

    SELL_TO_CLOSE = "SELL_TO_CLOSE"
    """Sell (close) an existing long-put position."""

    ROLL = "ROLL"
    """Roll from one expiry/strike to another (atomic two-leg)."""

    HOLD = "HOLD"
    """Take no action on this tranche."""


@dataclass(frozen=True)
class TargetTranche:
    """A single tranche within a ``TargetHedgePlan``.

    Each tranche specifies one action (buy/sell/roll/hold) with the
    corresponding contract parameters.  The deterministic risk gate
    translates tranches into broker-neutral order intents; the strategy
    does not name order types or broker references.
    """

    action: HedgeAction
    """Action to take for this tranche."""

    strike: float | None = None
    """Target strike price (required for BUY_PUT and target leg of ROLL)."""

    expiration_date: date | None = None
    """Target expiration date (required for BUY_PUT and target leg of ROLL)."""

    quantity: int = 0
    """Number of contracts.  Must be positive for BUY_PUT; may be zero
    for HOLD."""

    # Roll-specific fields
    from_strike: float | None = None
    """Strike of the position being closed (required for ROLL and
    SELL_TO_CLOSE)."""

    from_expiration_date: date | None = None
    """Expiration of the position being closed (required for ROLL and
    SELL_TO_CLOSE)."""

    from_quantity: int = 0
    """Quantity of the leg being closed (for ROLL / SELL_TO_CLOSE)."""

    # Monetisation / reinvestment
    reinvest_fraction: float = 0.0
    """Fraction of sell proceeds to reinvest into core portfolio (0..1]."""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        """Validate tranche consistency."""
        if self.action == HedgeAction.BUY_PUT:
            if self.strike is None or self.expiration_date is None:
                msg = "BUY_PUT tranche requires strike and expiration_date"
                raise ValueError(msg)
            if self.quantity <= 0:
                msg = "BUY_PUT quantity must be positive"
                raise ValueError(msg)
        elif self.action in (HedgeAction.SELL_TO_CLOSE, HedgeAction.ROLL):
            if self.from_strike is None or self.from_expiration_date is None:
                msg = (
                    f"{self.action} tranche requires from_strike and "
                    f"from_expiration_date"
                )
                raise ValueError(msg)
            if self.from_quantity <= 0:
                msg = f"{self.action} from_quantity must be positive"
                raise ValueError(msg)
            if self.action == HedgeAction.ROLL:
                if self.strike is None or self.expiration_date is None:
                    msg = "ROLL tranche requires target strike and expiration_date"
                    raise ValueError(msg)
                if self.quantity <= 0:
                    msg = "ROLL target quantity must be positive"
                    raise ValueError(msg)
                if self.expiration_date <= self.from_expiration_date:
                    msg = "ROLL target expiration must be after the leg being closed"
                    raise ValueError(msg)
        elif self.action == HedgeAction.HOLD:
            if self.quantity != 0:
                msg = "HOLD tranche must have quantity=0"
                raise ValueError(msg)

        if not (0.0 <= self.reinvest_fraction <= 1.0):
            msg = f"reinvest_fraction must be in [0, 1], got {self.reinvest_fraction}"
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# TargetHedgePlan — the output from a strategy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetHedgePlan:
    """Declarative output from a strategy's ``decide`` call.

    The plan contains one or more ``TargetTranche`` entries describing
    the desired hedge actions for the trade date.  The deterministic
    risk gate translates these into broker-neutral order intents.

    Security invariants:
    - The strategy does not name broker order IDs or choose order types.
    - The plan is declarative only; no imperative broker calls.
    - Schema validation rejects prohibited fields.
    """

    trade_date: date
    """Trade date this plan applies to."""

    schema_version: str = SCHEMA_VERSION
    """Schema version of this plan."""

    tranches: tuple[TargetTranche, ...] = ()
    """Target hedge tranches for this trade date."""

    reasoning: str = ""
    """Optional free-text reasoning from the strategy (untrusted
    commentary, never used as quantitative evidence)."""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        """Validate plan-level invariants."""
        if not self.tranches:
            return  # Empty plan is valid (NO_ACTION)

        for i, tranche in enumerate(self.tranches):
            if tranche.action == HedgeAction.BUY_PUT:
                continue  # Validated by TargetTranche
            if tranche.action == HedgeAction.SELL_TO_CLOSE:
                pass  # SELL_TO_CLOSE of a not-yet-expired position is fine
            elif (
                tranche.action == HedgeAction.ROLL
                and tranche.from_expiration_date is not None
                and tranche.from_expiration_date <= self.trade_date
            ):
                msg = (
                    f"Tranche {i}: cannot roll an already-expired "
                    f"position ({tranche.from_expiration_date} <= "
                    f"{self.trade_date})"
                )
                raise ValueError(msg)

    @property
    def is_no_action(self) -> bool:
        """True if the plan has no actionable tranches."""
        return not self.tranches or all(
            t.action == HedgeAction.HOLD for t in self.tranches
        )

    @property
    def total_buy_quantity(self) -> int:
        """Total number of contracts to buy across all tranches."""
        return sum(t.quantity for t in self.tranches if t.action == HedgeAction.BUY_PUT)

    @property
    def total_sell_quantity(self) -> int:
        """Total number of contracts to sell across all tranches."""
        return sum(
            t.from_quantity
            for t in self.tranches
            if t.action in (HedgeAction.SELL_TO_CLOSE, HedgeAction.ROLL)
        )

    def to_json(self) -> str:
        """Serialize the plan to JSON (deterministic key order)."""
        return json.dumps(self._to_dict(), sort_keys=True, separators=(",", ":"))

    def _to_dict(self) -> dict:  # type: ignore[type-arg]
        """Convert to a plain dictionary for serialization."""
        return {
            "schema_version": self.schema_version,
            "trade_date": self.trade_date.isoformat(),
            "tranches": [self._tranche_to_dict(t) for t in self.tranches],
            "reasoning": self.reasoning,
        }

    @staticmethod
    def _tranche_to_dict(t: TargetTranche) -> dict:  # type: ignore[type-arg]
        d: dict = {  # type: ignore[type-arg]
            "action": t.action.value,
        }
        if t.strike is not None:
            d["strike"] = t.strike
        if t.expiration_date is not None:
            d["expiration_date"] = t.expiration_date.isoformat()
        if t.quantity:
            d["quantity"] = t.quantity
        if t.from_strike is not None:
            d["from_strike"] = t.from_strike
        if t.from_expiration_date is not None:
            d["from_expiration_date"] = t.from_expiration_date.isoformat()
        if t.from_quantity:
            d["from_quantity"] = t.from_quantity
        if t.reinvest_fraction:
            d["reinvest_fraction"] = t.reinvest_fraction
        return d


# ---------------------------------------------------------------------------
# Prohibited output fields
# ---------------------------------------------------------------------------

_PROHIBITED_PLAN_FIELDS = frozenset(
    {
        "broker_order_id",
        "order_type",
        "limit_price",
        "order_side",
        "client_order_ref",
        "account_id",
        "broker_account_ref",
        "credentials",
        "api_key",
        "secret",
        "password",
        "token",
        "network_request",
        "file_path",
        "evaluator_path",
        "holdout_path",
    }
)


def validate_plan_not_prohibited(plan_dict: dict) -> list[str]:  # type: ignore[type-arg]
    """Check a serialized plan for prohibited fields.

    Parameters
    ----------
    plan_dict : dict
        The deserialized plan dictionary.

    Returns
    -------
    list[str]
        List of error messages for prohibited fields found.  Empty if
        the plan is clean.
    """
    errors: list[str] = []

    def _check(obj: object, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                current = f"{path}.{key}" if path else key
                if key.lower() in {f.lower() for f in _PROHIBITED_PLAN_FIELDS}:
                    errors.append(f"Prohibited field '{key}' found at '{current}'")
                _check(value, current)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _check(item, f"{path}[{i}]")

    _check(plan_dict)
    return errors


# ---------------------------------------------------------------------------
# Strategy protocol — the versioned interface
# ---------------------------------------------------------------------------


class StrategyProtocol(Protocol):
    """Protocol defining the versioned strategy interface.

    All strategies must implement this interface.  The ``decide`` method
    receives a ``StrategyContext`` containing only permitted features
    and returns a declarative ``TargetHedgePlan``.

    The strategy must not:
    - access features not in the context's ``enabled_features``;
    - produce order intents, broker references, or network calls;
    - modify external state.
    """

    @property
    def strategy_version(self) -> str:
        """Version string for this strategy implementation."""
        ...

    def decide(self, context: StrategyContext) -> TargetHedgePlan:
        """Produce a target hedge plan for the given context.

        Parameters
        ----------
        context : StrategyContext
            The permitted market/portfolio state for the trade date.

        Returns
        -------
        TargetHedgePlan
            Declarative target hedge plan.
        """
        ...


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_context_access(
    context: StrategyContext,
    required_features: set[StrategyFeature],
) -> list[str]:
    """Validate that all required features are present in the context.

    Parameters
    ----------
    context : StrategyContext
        The strategy context to validate.
    required_features : set[StrategyFeature]
        Features the strategy needs.

    Returns
    -------
    list[str]
        Error messages for missing features.  Empty if all features
        are present.
    """
    errors: list[str] = []
    missing = required_features - context.enabled_features
    for feature in sorted(missing):
        errors.append(f"Required feature '{feature}' is not enabled in the context")
    return errors


def validate_plan_schema(plan: TargetHedgePlan) -> list[str]:
    """Validate a plan against the schema contract.

    Returns a list of validation error messages; empty if valid.
    """
    errors: list[str] = []

    if plan.schema_version != SCHEMA_VERSION:
        errors.append(
            f"Plan schema version mismatch: expected {SCHEMA_VERSION}, "
            f"got {plan.schema_version}"
        )

    if not plan.tranches:
        return errors  # Empty plan is valid (NO_ACTION)

    for i, tranche in enumerate(plan.tranches):
        prefix = f"Tranche {i}"
        if tranche.action == HedgeAction.BUY_PUT:
            if tranche.strike is None:
                errors.append(f"{prefix}: BUY_PUT requires strike")
            if tranche.expiration_date is None:
                errors.append(f"{prefix}: BUY_PUT requires expiration_date")
            if tranche.quantity <= 0:
                errors.append(f"{prefix}: BUY_PUT requires positive quantity")
            if tranche.expiration_date is not None and (
                tranche.expiration_date <= plan.trade_date
            ):
                errors.append(f"{prefix}: BUY_PUT expiration must be after trade date")
        elif tranche.action in (HedgeAction.SELL_TO_CLOSE, HedgeAction.ROLL):
            if tranche.from_strike is None:
                errors.append(f"{prefix}: {tranche.action} requires from_strike")
            if tranche.from_expiration_date is None:
                errors.append(
                    f"{prefix}: {tranche.action} requires from_expiration_date"
                )
            if tranche.from_quantity <= 0:
                errors.append(
                    f"{prefix}: {tranche.action} requires positive from_quantity"
                )
            if tranche.action == HedgeAction.ROLL:
                if tranche.strike is None:
                    errors.append(f"{prefix}: ROLL requires target strike")
                if tranche.expiration_date is None:
                    errors.append(f"{prefix}: ROLL requires target expiration_date")
                if tranche.quantity <= 0:
                    errors.append(f"{prefix}: ROLL requires positive target quantity")
                if (
                    tranche.from_expiration_date is not None
                    and tranche.expiration_date is not None
                    and tranche.expiration_date <= tranche.from_expiration_date
                ):
                    errors.append(
                        f"{prefix}: ROLL target expiry must be after "
                        f"the leg being closed"
                    )
        elif tranche.action == HedgeAction.HOLD:
            if tranche.quantity != 0:
                errors.append(f"{prefix}: HOLD must have quantity=0")
        else:
            errors.append(f"{prefix}: unknown action '{tranche.action}'")

        if not (0.0 <= tranche.reinvest_fraction <= 1.0):
            errors.append(
                f"{prefix}: reinvest_fraction must be in [0, 1], "
                f"got {tranche.reinvest_fraction}"
            )

    return errors


def compute_plan_hash(plan: TargetHedgePlan) -> str:
    """Compute a deterministic SHA-256 hash of a plan's content.

    Used for provenance tracking and audit.
    """
    plan_json = plan.to_json()
    return hashlib.sha256(plan_json.encode("utf-8")).hexdigest()


def compute_context_hash(context: StrategyContext) -> str:
    """Compute a deterministic SHA-256 hash of a context.

    Used for provenance tracking: the context is the exact input
    the strategy received.
    """
    # Build a deterministic dict from the context
    d: dict = {  # type: ignore[type-arg]
        "schema_version": context.schema_version,
        "trade_date": context.trade_date.isoformat(),
        "underlying_close": context.underlying_close,
        "enabled_features": sorted(f.value for f in context.enabled_features),
    }
    if context.portfolio is not None:
        d["portfolio"] = {
            "total_value": context.portfolio.total_value,
            "cash": context.portfolio.cash,
            "units": context.portfolio.units,
            "base_currency": context.portfolio.base_currency,
            "benchmark_equivalent_exposure": context.portfolio.benchmark_equivalent_exposure,
        }
    if context.positions:
        d["positions"] = [
            {
                "strike": p.strike,
                "expiration_date": p.expiration_date.isoformat(),
                "quantity": p.quantity,
                "entry_premium": p.entry_premium,
                "current_dte": p.current_dte,
            }
            for p in sorted(
                context.positions,
                key=lambda p: (p.expiration_date, p.strike),
            )
        ]
    if context.option_chain:
        d["option_chain"] = [
            {
                "trade_date": q.trade_date.isoformat(),
                "strike": q.strike,
                "expiration_date": q.expiration_date.isoformat(),
                "bid": q.bid,
                "ask": q.ask,
                "underlying_price": q.underlying_price,
            }
            for q in sorted(
                context.option_chain,
                key=lambda q: (q.expiration_date, q.strike),
            )
        ]
    d["budget_consumed_ytd"] = context.budget_consumed_ytd
    d["budget_remaining"] = context.budget_remaining
    d["budget_cap_pct"] = context.budget_cap_pct

    canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
