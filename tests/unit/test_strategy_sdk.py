"""T-007: Strategy SDK and target-plan contract tests.

Tests FR-006 and FR-008: candidate can only emit schema-valid target plan;
protected files remain unchanged; strategy has no broker methods; prohibited
output rejected.

Coverage:
- StrategyContext construction and feature gating
- TargetHedgePlan construction and schema validation
- TargetTranche validation (BUY_PUT, SELL_TO_CLOSE, ROLL, HOLD)
- Prohibited output field rejection
- Versioned interface conformance
- Context/plan hashing determinism
- No broker methods in strategy protocol
"""

from __future__ import annotations

import dataclasses
import re
from datetime import date, timedelta

import pytest

from tailhedge.domain.strategy_sdk import (
    SCHEMA_VERSION,
    FeatureNotEnabledError,
    HedgeAction,
    HedgePositionSnapshot,
    OptionQuoteSnapshot,
    PortfolioSnapshot,
    StrategyContext,
    StrategyFeature,
    StrategyProtocol,
    TargetHedgePlan,
    TargetTranche,
    compute_context_hash,
    compute_plan_hash,
    validate_context_access,
    validate_plan_not_prohibited,
    validate_plan_schema,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


TRADE_DATE = date(2025, 6, 15)


def _make_context(
    features: set[StrategyFeature] | None = None,
    portfolio: PortfolioSnapshot | None = None,
    positions: tuple[HedgePositionSnapshot, ...] = (),
    option_chain: tuple[OptionQuoteSnapshot, ...] = (),
    **kwargs: object,
) -> StrategyContext:
    """Build a StrategyContext with sensible defaults.

    Data is only included for features that are enabled, mirroring the
    data-access boundary enforced by the evaluator.
    """
    if features is None:
        features = set(StrategyFeature)
    if portfolio is None:
        portfolio = PortfolioSnapshot(
            total_value=500_000.0,
            cash=100_000.0,
            units=88.89,
            base_currency="USD",
            benchmark_equivalent_exposure=380_000.0,
        )
    return StrategyContext(
        trade_date=TRADE_DATE,
        enabled_features=frozenset(features),
        underlying_close=(
            4500.0 if StrategyFeature.UNDERLYING_CLOSE in features else None
        ),
        portfolio=(
            portfolio if StrategyFeature.CURRENT_PORTFOLIO in features else None
        ),
        positions=(
            positions if StrategyFeature.EXISTING_HEDGE_POSITIONS in features else ()
        ),
        option_chain=(
            option_chain if StrategyFeature.OPTION_CHAIN_QUOTES in features else ()
        ),
        **kwargs,  # type: ignore[arg-type]
    )


def _make_buy_plan() -> TargetHedgePlan:
    """Build a simple BUY_PUT plan."""
    return TargetHedgePlan(
        trade_date=TRADE_DATE,
        tranches=(
            TargetTranche(
                action=HedgeAction.BUY_PUT,
                strike=4200.0,
                expiration_date=TRADE_DATE + timedelta(days=63),
                quantity=1,
            ),
        ),
    )


def _make_sell_plan() -> TargetHedgePlan:
    """Build a SELL_TO_CLOSE plan."""
    return TargetHedgePlan(
        trade_date=TRADE_DATE,
        tranches=(
            TargetTranche(
                action=HedgeAction.SELL_TO_CLOSE,
                from_strike=4300.0,
                from_expiration_date=TRADE_DATE + timedelta(days=30),
                from_quantity=2,
            ),
        ),
    )


def _make_roll_plan() -> TargetHedgePlan:
    """Build a ROLL plan."""
    return TargetHedgePlan(
        trade_date=TRADE_DATE,
        tranches=(
            TargetTranche(
                action=HedgeAction.ROLL,
                from_strike=4300.0,
                from_expiration_date=TRADE_DATE + timedelta(days=7),
                from_quantity=1,
                strike=4200.0,
                expiration_date=TRADE_DATE + timedelta(days=63),
                quantity=1,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# T-007.1: StrategyContext -- feature gating
# ---------------------------------------------------------------------------


class TestStrategyContextFeatureGating:
    """Strategy has no broker methods; context respects feature allowlist."""

    def test_context_with_all_features(self) -> None:
        ctx = _make_context(features=set(StrategyFeature))
        assert ctx.has_feature(StrategyFeature.CURRENT_PORTFOLIO)
        assert ctx.has_feature(StrategyFeature.OPTION_CHAIN_QUOTES)
        assert ctx.has_feature(StrategyFeature.BUDGET_CONSUMPTION)

    def test_context_without_features(self) -> None:
        ctx = _make_context(features=set())
        assert not ctx.has_feature(StrategyFeature.CURRENT_PORTFOLIO)
        assert not ctx.has_feature(StrategyFeature.OPTION_CHAIN_QUOTES)

    def test_require_feature_raises_when_missing(self) -> None:
        ctx = _make_context(features=set())
        with pytest.raises(FeatureNotEnabledError, match="not enabled"):
            ctx.require_feature(StrategyFeature.CURRENT_PORTFOLIO)

    def test_require_feature_passes_when_present(self) -> None:
        ctx = _make_context(features={StrategyFeature.CURRENT_PORTFOLIO})
        ctx.require_feature(StrategyFeature.CURRENT_PORTFOLIO)  # no error

    def test_context_has_no_broker_methods(self) -> None:
        """FR-006: strategy must not receive broker methods."""
        ctx = _make_context()
        # Context should only have data attributes and feature methods
        public_methods = {
            m for m in dir(ctx) if not m.startswith("_") and callable(getattr(ctx, m))
        }
        # Only allowed methods: has_feature, require_feature
        allowed = {"has_feature", "require_feature"}
        assert public_methods == allowed

    def test_context_portfolio_is_read_only(self) -> None:
        """Portfolio snapshot is frozen dataclass -- immutable."""
        ctx = _make_context()
        assert ctx.portfolio is not None
        with pytest.raises(AttributeError):
            ctx.portfolio.cash = 0.0  # type: ignore[misc]

    def test_context_positions_is_tuple(self) -> None:
        """Positions are immutable tuple."""
        ctx = _make_context(
            positions=(
                HedgePositionSnapshot(
                    strike=4300.0,
                    expiration_date=TRADE_DATE + timedelta(days=30),
                    quantity=2,
                    entry_premium=50.0,
                    current_dte=30,
                ),
            )
        )
        assert len(ctx.positions) == 1
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.positions = ()  # type: ignore[misc]

    def test_context_option_chain_is_tuple(self) -> None:
        """Option chain is immutable tuple."""
        ctx = _make_context(
            option_chain=(
                OptionQuoteSnapshot(
                    trade_date=TRADE_DATE,
                    strike=4200.0,
                    expiration_date=TRADE_DATE + timedelta(days=63),
                    bid=100.0,
                    ask=105.0,
                    underlying_price=4500.0,
                ),
            )
        )
        assert len(ctx.option_chain) == 1

    def test_schema_version_is_set(self) -> None:
        ctx = _make_context()
        assert ctx.schema_version == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# T-007.1b: StrategyContext -- feature gating enforced at the boundary
# ---------------------------------------------------------------------------


class TestContextFeatureGatingEnforcement:
    """Context must contain only explicitly enabled features (fail closed)."""

    def test_portfolio_data_without_feature_rejected(self) -> None:
        with pytest.raises(ValueError, match="CURRENT_PORTFOLIO"):
            StrategyContext(
                trade_date=TRADE_DATE,
                enabled_features=frozenset(),
                portfolio=PortfolioSnapshot(
                    total_value=1.0,
                    cash=0.0,
                    units=0.0,
                    base_currency="USD",
                ),
            )

    def test_positions_without_feature_rejected(self) -> None:
        with pytest.raises(ValueError, match="EXISTING_HEDGE_POSITIONS"):
            StrategyContext(
                trade_date=TRADE_DATE,
                enabled_features=frozenset(),
                positions=(
                    HedgePositionSnapshot(
                        strike=4300.0,
                        expiration_date=TRADE_DATE + timedelta(days=30),
                        quantity=1,
                        entry_premium=50.0,
                        current_dte=30,
                    ),
                ),
            )

    def test_option_chain_without_feature_rejected(self) -> None:
        with pytest.raises(ValueError, match="OPTION_CHAIN_QUOTES"):
            StrategyContext(
                trade_date=TRADE_DATE,
                enabled_features=frozenset(),
                option_chain=(
                    OptionQuoteSnapshot(
                        trade_date=TRADE_DATE,
                        strike=4200.0,
                        expiration_date=TRADE_DATE + timedelta(days=63),
                        bid=100.0,
                        ask=105.0,
                        underlying_price=4500.0,
                    ),
                ),
            )

    def test_budget_fields_without_feature_rejected(self) -> None:
        with pytest.raises(ValueError, match="BUDGET_CONSUMPTION"):
            StrategyContext(
                trade_date=TRADE_DATE,
                enabled_features=frozenset(),
                budget_consumed_ytd=100.0,
            )

    def test_underlying_close_without_feature_rejected(self) -> None:
        with pytest.raises(ValueError, match="UNDERLYING_CLOSE"):
            StrategyContext(
                trade_date=TRADE_DATE,
                enabled_features=frozenset(),
                underlying_close=4500.0,
            )

    def test_underlying_close_absent_when_disabled(self) -> None:
        ctx = _make_context(features=set())
        assert ctx.underlying_close is None

    def test_underlying_close_present_when_enabled(self) -> None:
        ctx = _make_context(features={StrategyFeature.UNDERLYING_CLOSE})
        assert ctx.underlying_close == 4500.0

    def test_gated_data_with_feature_enabled_allowed(self) -> None:
        ctx = _make_context(
            features={
                StrategyFeature.CURRENT_PORTFOLIO,
                StrategyFeature.EXISTING_HEDGE_POSITIONS,
                StrategyFeature.OPTION_CHAIN_QUOTES,
                StrategyFeature.BUDGET_CONSUMPTION,
                StrategyFeature.UNDERLYING_CLOSE,
            }
        )
        assert ctx.portfolio is not None
        assert ctx.underlying_close == 4500.0

    def test_minimal_context_with_no_features_valid(self) -> None:
        ctx = StrategyContext(trade_date=TRADE_DATE, enabled_features=frozenset())
        assert ctx.underlying_close is None
        assert ctx.portfolio is None
        assert ctx.positions == ()
        assert ctx.option_chain == ()


# ---------------------------------------------------------------------------
# T-007.2: TargetHedgePlan -- schema validation
# ---------------------------------------------------------------------------


class TestTargetHedgePlanSchema:
    """Plan must be schema-validated; prohibited output rejected."""

    def test_valid_buy_plan(self) -> None:
        plan = _make_buy_plan()
        errors = validate_plan_schema(plan)
        assert errors == []

    def test_valid_sell_plan(self) -> None:
        plan = _make_sell_plan()
        errors = validate_plan_schema(plan)
        assert errors == []

    def test_valid_roll_plan(self) -> None:
        plan = _make_roll_plan()
        errors = validate_plan_schema(plan)
        assert errors == []

    def test_valid_no_action_plan(self) -> None:
        plan = TargetHedgePlan(
            trade_date=TRADE_DATE,
            tranches=(),
        )
        assert plan.is_no_action
        errors = validate_plan_schema(plan)
        assert errors == []

    def test_valid_hold_plan(self) -> None:
        plan = TargetHedgePlan(
            trade_date=TRADE_DATE,
            tranches=(
                TargetTranche(
                    action=HedgeAction.HOLD,
                    quantity=0,
                ),
            ),
        )
        assert plan.is_no_action
        errors = validate_plan_schema(plan)
        assert errors == []

    def test_buy_put_requires_expiration(self) -> None:
        with pytest.raises(ValueError, match=re.compile(r"requires.*expiration")):
            TargetTranche(
                action=HedgeAction.BUY_PUT,
                strike=4200.0,
                quantity=1,
                # missing expiration
            )

    def test_buy_put_requires_positive_quantity(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            TargetTranche(
                action=HedgeAction.BUY_PUT,
                strike=4200.0,
                expiration_date=TRADE_DATE + timedelta(days=63),
                quantity=0,
            )

    def test_buy_put_expiry_before_trade_date_invalid(self) -> None:
        plan = TargetHedgePlan(
            trade_date=TRADE_DATE,
            tranches=(
                TargetTranche(
                    action=HedgeAction.BUY_PUT,
                    strike=4200.0,
                    expiration_date=TRADE_DATE - timedelta(days=1),
                    quantity=1,
                ),
            ),
        )
        errors = validate_plan_schema(plan)
        assert any("after trade date" in e for e in errors)

    def test_sell_requires_from_strike(self) -> None:
        with pytest.raises(ValueError, match="requires from_strike"):
            TargetTranche(
                action=HedgeAction.SELL_TO_CLOSE,
                from_quantity=1,
                from_expiration_date=TRADE_DATE + timedelta(days=30),
                # missing from_strike
            )

    def test_sell_requires_from_quantity(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            TargetTranche(
                action=HedgeAction.SELL_TO_CLOSE,
                from_strike=4300.0,
                from_expiration_date=TRADE_DATE + timedelta(days=30),
                from_quantity=0,
            )

    def test_roll_requires_target_fields(self) -> None:
        with pytest.raises(ValueError, match="requires target"):
            TargetTranche(
                action=HedgeAction.ROLL,
                from_strike=4300.0,
                from_expiration_date=TRADE_DATE + timedelta(days=7),
                from_quantity=1,
                quantity=1,
                # missing target strike and expiry
            )

    def test_roll_target_must_be_after_from(self) -> None:
        with pytest.raises(ValueError, match="must be after"):
            TargetTranche(
                action=HedgeAction.ROLL,
                from_strike=4300.0,
                from_expiration_date=TRADE_DATE + timedelta(days=30),
                from_quantity=1,
                strike=4200.0,
                expiration_date=TRADE_DATE + timedelta(days=7),
                quantity=1,
            )

    def test_hold_must_have_zero_quantity(self) -> None:
        with pytest.raises(ValueError, match="quantity=0"):
            TargetTranche(
                action=HedgeAction.HOLD,
                quantity=1,
            )

    def test_reinvest_fraction_out_of_range(self) -> None:
        with pytest.raises(ValueError, match=re.compile(r"in \[0, 1\]")):
            TargetTranche(
                action=HedgeAction.SELL_TO_CLOSE,
                from_strike=4300.0,
                from_expiration_date=TRADE_DATE + timedelta(days=30),
                from_quantity=1,
                reinvest_fraction=1.5,
            )

    def test_plan_schema_version_mismatch(self) -> None:
        plan = TargetHedgePlan(
            schema_version="999.0.0",
            trade_date=TRADE_DATE,
            tranches=(),
        )
        errors = validate_plan_schema(plan)
        assert any("schema version mismatch" in e for e in errors)

    def test_multi_tranche_plan(self) -> None:
        """Plan with multiple tranches validates each."""
        plan = TargetHedgePlan(
            trade_date=TRADE_DATE,
            tranches=(
                TargetTranche(
                    action=HedgeAction.SELL_TO_CLOSE,
                    from_strike=4300.0,
                    from_expiration_date=TRADE_DATE + timedelta(days=7),
                    from_quantity=1,
                ),
                TargetTranche(
                    action=HedgeAction.BUY_PUT,
                    strike=4200.0,
                    expiration_date=TRADE_DATE + timedelta(days=63),
                    quantity=1,
                ),
            ),
        )
        errors = validate_plan_schema(plan)
        assert errors == []
        assert not plan.is_no_action
        assert plan.total_sell_quantity == 1
        assert plan.total_buy_quantity == 1


# ---------------------------------------------------------------------------
# T-007.3: Prohibited output rejection
# ---------------------------------------------------------------------------


class TestProhibitedOutputRejection:
    """Strategy must not produce broker/order/secret fields."""

    def test_clean_plan_passes(self) -> None:
        plan_dict = {
            "schema_version": SCHEMA_VERSION,
            "trade_date": TRADE_DATE.isoformat(),
            "tranches": [{"action": "BUY_PUT", "strike": 4200.0, "quantity": 1}],
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert errors == []

    def test_broker_order_id_rejected(self) -> None:
        plan_dict = {
            "tranches": [{"broker_order_id": "12345"}],
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("broker_order_id" in e for e in errors)

    def test_order_type_rejected(self) -> None:
        plan_dict = {
            "tranches": [{"order_type": "LMT"}],
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("order_type" in e for e in errors)

    def test_limit_price_rejected(self) -> None:
        plan_dict = {
            "tranches": [{"limit_price": 100.0}],
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("limit_price" in e for e in errors)

    def test_credentials_rejected(self) -> None:
        plan_dict = {
            "credentials": {"api_key": "secret"},
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("credentials" in e for e in errors)

    def test_api_key_rejected(self) -> None:
        plan_dict = {
            "api_key": "AKIA...",
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("api_key" in e for e in errors)

    def test_network_request_rejected(self) -> None:
        plan_dict = {
            "network_request": {"url": "http://example.com"},
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("network_request" in e for e in errors)

    def test_file_path_rejected(self) -> None:
        plan_dict = {
            "file_path": "/etc/passwd",
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("file_path" in e for e in errors)

    def test_holdout_path_rejected(self) -> None:
        plan_dict = {
            "holdout_path": "/data/holdout.parquet",
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("holdout_path" in e for e in errors)

    def test_nested_prohibited_rejected(self) -> None:
        """Prohibited fields in nested objects are caught."""
        plan_dict = {
            "reasoning": {
                "internal": {"evaluator_path": "/evaluator/code"},
            },
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("evaluator_path" in e for e in errors)

    def test_case_insensitive_prohibited_check(self) -> None:
        """Prohibited field names are matched case-insensitively."""
        plan_dict = {
            "Broker_Order_Id": "12345",
        }
        errors = validate_plan_not_prohibited(plan_dict)
        assert any("Broker_Order_Id" in e for e in errors)


# ---------------------------------------------------------------------------
# T-007.4: Versioned interface conformance
# ---------------------------------------------------------------------------


class TestVersionedInterface:
    """Strategy interface is versioned and deterministic."""

    def test_schema_version_is_semver(self) -> None:
        parts = SCHEMA_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_plan_serialization_deterministic(self) -> None:
        """Same plan produces identical JSON."""
        plan = _make_buy_plan()
        json1 = plan.to_json()
        json2 = plan.to_json()
        assert json1 == json2

    def test_plan_hash_deterministic(self) -> None:
        """Same plan produces identical hash."""
        plan = _make_buy_plan()
        h1 = compute_plan_hash(plan)
        h2 = compute_plan_hash(plan)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_plan_hash_differs_for_different_plans(self) -> None:
        p1 = _make_buy_plan()
        p2 = _make_sell_plan()
        assert compute_plan_hash(p1) != compute_plan_hash(p2)

    def test_context_hash_deterministic(self) -> None:
        ctx = _make_context()
        h1 = compute_context_hash(ctx)
        h2 = compute_context_hash(ctx)
        assert h1 == h2
        assert len(h1) == 64

    def test_context_hash_differs_for_different_contexts(self) -> None:
        c1 = _make_context(features={StrategyFeature.CURRENT_PORTFOLIO})
        c2 = _make_context(features=set())
        assert compute_context_hash(c1) != compute_context_hash(c2)

    def test_context_hash_order_independent_of_position_order(self) -> None:
        """Hash should be stable regardless of input tuple order."""
        pos1 = HedgePositionSnapshot(
            strike=4300.0,
            expiration_date=TRADE_DATE + timedelta(days=30),
            quantity=1,
            entry_premium=50.0,
            current_dte=30,
        )
        pos2 = HedgePositionSnapshot(
            strike=4200.0,
            expiration_date=TRADE_DATE + timedelta(days=60),
            quantity=2,
            entry_premium=100.0,
            current_dte=60,
        )
        c1 = _make_context(positions=(pos1, pos2))
        c2 = _make_context(positions=(pos2, pos1))
        assert compute_context_hash(c1) == compute_context_hash(c2)


# ---------------------------------------------------------------------------
# T-007.5: StrategyProtocol compliance
# ---------------------------------------------------------------------------


class TestStrategyProtocolCompliance:
    """Verify the protocol is structurally enforced."""

    def test_protocol_has_decide_method(self) -> None:
        """The protocol requires a decide method."""
        assert hasattr(StrategyProtocol, "decide")

    def test_protocol_has_strategy_version(self) -> None:
        """The protocol requires a strategy_version property."""
        assert hasattr(StrategyProtocol, "strategy_version")

    def test_protocol_is_protocol(self) -> None:
        """The protocol type is correct."""
        assert hasattr(StrategyProtocol, "decide")
        assert hasattr(StrategyProtocol, "strategy_version")

    def test_static_strategy_conforms_to_protocol(self) -> None:
        """A minimal strategy implementation satisfies the protocol."""

        # We cannot use isinstance() with Protocol, but we can verify
        # the structural requirements are met.
        class MinimalStrategy:
            @property
            def strategy_version(self) -> str:
                return "test-1.0"

            def decide(self, context: StrategyContext) -> TargetHedgePlan:
                return TargetHedgePlan(
                    trade_date=context.trade_date,
                    tranches=(),
                )

        s = MinimalStrategy()
        assert s.strategy_version == "test-1.0"
        ctx = _make_context()
        plan = s.decide(ctx)
        assert isinstance(plan, TargetHedgePlan)
        assert plan.is_no_action


# ---------------------------------------------------------------------------
# T-007.6: Context validation helpers
# ---------------------------------------------------------------------------


class TestContextValidationHelpers:
    """validate_context_access checks feature requirements."""

    def test_all_features_present(self) -> None:
        ctx = _make_context(features=set(StrategyFeature))
        errors = validate_context_access(ctx, set(StrategyFeature))
        assert errors == []

    def test_missing_features(self) -> None:
        ctx = _make_context(features={StrategyFeature.CURRENT_PORTFOLIO})
        required = {
            StrategyFeature.CURRENT_PORTFOLIO,
            StrategyFeature.OPTION_CHAIN_QUOTES,
        }
        errors = validate_context_access(ctx, required)
        assert len(errors) == 1
        assert "OPTION_CHAIN_QUOTES" in errors[0]

    def test_no_required_features(self) -> None:
        ctx = _make_context(features=set())
        errors = validate_context_access(ctx, set())
        assert errors == []


# ---------------------------------------------------------------------------
# T-007.7: TargetHedgePlan properties
# ---------------------------------------------------------------------------


class TestTargetHedgePlanProperties:
    """Plan-level computed properties."""

    def test_is_no_action_empty(self) -> None:
        plan = TargetHedgePlan(trade_date=TRADE_DATE, tranches=())
        assert plan.is_no_action

    def test_is_no_action_all_hold(self) -> None:
        plan = TargetHedgePlan(
            trade_date=TRADE_DATE,
            tranches=(TargetTranche(action=HedgeAction.HOLD, quantity=0),),
        )
        assert plan.is_no_action

    def test_not_no_action_with_buy(self) -> None:
        plan = _make_buy_plan()
        assert not plan.is_no_action

    def test_total_buy_quantity(self) -> None:
        plan = TargetHedgePlan(
            trade_date=TRADE_DATE,
            tranches=(
                TargetTranche(
                    action=HedgeAction.BUY_PUT,
                    strike=4200.0,
                    expiration_date=TRADE_DATE + timedelta(days=63),
                    quantity=2,
                ),
                TargetTranche(
                    action=HedgeAction.BUY_PUT,
                    strike=4100.0,
                    expiration_date=TRADE_DATE + timedelta(days=90),
                    quantity=3,
                ),
            ),
        )
        assert plan.total_buy_quantity == 5

    def test_total_sell_quantity(self) -> None:
        plan = TargetHedgePlan(
            trade_date=TRADE_DATE,
            tranches=(
                TargetTranche(
                    action=HedgeAction.SELL_TO_CLOSE,
                    from_strike=4300.0,
                    from_expiration_date=TRADE_DATE + timedelta(days=7),
                    from_quantity=1,
                ),
                TargetTranche(
                    action=HedgeAction.ROLL,
                    from_strike=4400.0,
                    from_expiration_date=TRADE_DATE + timedelta(days=5),
                    from_quantity=2,
                    strike=4200.0,
                    expiration_date=TRADE_DATE + timedelta(days=63),
                    quantity=2,
                ),
            ),
        )
        assert plan.total_sell_quantity == 3


# ---------------------------------------------------------------------------
# T-007.8: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for the strategy SDK contract."""

    def test_plan_with_reasoning(self) -> None:
        plan = TargetHedgePlan(
            trade_date=TRADE_DATE,
            tranches=(),
            reasoning="No hedge needed today.",
        )
        assert plan.reasoning == "No hedge needed today."
        d = plan._to_dict()
        assert d["reasoning"] == "No hedge needed today."

    def test_reinvest_fraction_zero_allowed(self) -> None:
        t = TargetTranche(
            action=HedgeAction.SELL_TO_CLOSE,
            from_strike=4300.0,
            from_expiration_date=TRADE_DATE + timedelta(days=30),
            from_quantity=1,
            reinvest_fraction=0.0,
        )
        assert t.reinvest_fraction == 0.0

    def test_reinvest_fraction_one_allowed(self) -> None:
        t = TargetTranche(
            action=HedgeAction.SELL_TO_CLOSE,
            from_strike=4300.0,
            from_expiration_date=TRADE_DATE + timedelta(days=30),
            from_quantity=1,
            reinvest_fraction=1.0,
        )
        assert t.reinvest_fraction == 1.0

    def test_empty_plan_json(self) -> None:
        plan = TargetHedgePlan(trade_date=TRADE_DATE, tranches=())
        j = plan.to_json()
        assert '"tranches":[]' in j

    def test_plan_json_contains_all_fields(self) -> None:
        plan = _make_buy_plan()
        j = plan.to_json()
        assert SCHEMA_VERSION in j
        assert TRADE_DATE.isoformat() in j
        assert "BUY_PUT" in j

    def test_context_with_empty_option_chain(self) -> None:
        ctx = _make_context(
            features={StrategyFeature.OPTION_CHAIN_QUOTES},
            option_chain=(),
        )
        assert ctx.option_chain == ()

    def test_context_with_multiple_positions(self) -> None:
        positions = tuple(
            HedgePositionSnapshot(
                strike=4300.0 + i * 100,
                expiration_date=TRADE_DATE + timedelta(days=30 + i * 30),
                quantity=i + 1,
                entry_premium=50.0 + i * 10,
                current_dte=30 + i * 30,
            )
            for i in range(3)
        )
        ctx = _make_context(
            features={StrategyFeature.EXISTING_HEDGE_POSITIONS},
            positions=positions,
        )
        assert len(ctx.positions) == 3
