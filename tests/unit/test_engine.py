"""Tests for the daily backtest engine, shared-engine baselines, and synthetic data.

Covers:
- GF-001/002/003 run through the engine reconcile with hand-calculated values.
- All baselines execute through the SAME engine + fill/cost model (T-006).
- The engine fails closed (unknown action, no-quote actions, missed settlement).
- The synthetic dataset generator is deterministic.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from tailhedge.backtest.baselines import (
    FIXED_PUT_SPEC,
    LOWER_EQUITY_SPEC,
    NO_HEDGE_SPEC,
    BaselineType,
    RollingHedgePolicy,
    get_all_baseline_configs,
    get_baseline_config,
    run_baseline,
)
from tailhedge.backtest.engine import (
    BacktestConfig,
    EngineAction,
    EngineActionKind,
    ReinvestDirective,
    run_daily_backtest,
)
from tailhedge.backtest.fill_model import Quote
from tailhedge.backtest.ledger import BacktestLedger, EventType
from tailhedge.backtest.metrics import calculate_metrics, compare_to_baseline
from tailhedge.backtest.strategy import RollConfig
from tailhedge.backtest.synthetic import generate_synthetic_dataset
from tailhedge.data.fixtures import (
    GF001_EXPECTED_FINAL_CASH,
    GF001_OPTION_SNAPSHOTS,
    GF001_UNDERLYING_PRICES,
    GF002_EXPECTED_FINAL_CASH,
    GF002_OPTION_SNAPSHOTS_EXPIRY_1,
    GF002_OPTION_SNAPSHOTS_EXPIRY_2,
    GF002_ROLL_DTE_THRESHOLD,
    GF003_EXPECTED_FINAL_CASH,
    GF003_EXPECTED_FINAL_UNITS,
    GF003_INITIAL_UNITS,
    GF003_MONETISE_FRACTION,
    GF003_REINVEST_FRACTION,
    option_snapshots_to_quotes,
    quotes_by_day,
    underlying_prices_map,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

GF001_EX1 = date(2025, 1, 21)
GF002_EX2 = date(2025, 2, 21)


# ---------------------------------------------------------------------------
# Golden fixtures through the engine
# ---------------------------------------------------------------------------


class _ScriptedPolicy:
    """Policy executing a fixed script of actions on given dates."""

    def __init__(
        self, script: dict[date, list[tuple[EngineAction, ReinvestDirective | None]]]
    ):
        self.script = script
        self.done: set[date] = set()

    def decide(
        self,
        trade_date: date,
        _ledger: BacktestLedger,
        _quotes_by_day_map: Mapping[date, Sequence[Quote]],
        _close: float,
    ) -> list[tuple[EngineAction, ReinvestDirective | None]]:
        if trade_date in self.script and trade_date not in self.done:
            self.done.add(trade_date)
            return self.script[trade_date]
        return []


class TestEngineGoldenFixtures:
    """The engine reconciles each golden fixture exactly."""

    def test_gf001_through_engine(self) -> None:
        prices = underlying_prices_map(GF001_UNDERLYING_PRICES)
        qbd = quotes_by_day(option_snapshots_to_quotes(GF001_OPTION_SNAPSHOTS))
        policy = _ScriptedPolicy(
            {
                date(2025, 1, 15): [
                    (
                        EngineAction(
                            kind=EngineActionKind.BUY_PUT,
                            strike=4900.0,
                            expiration_date=GF001_EX1,
                            quantity=1,
                        ),
                        None,
                    )
                ]
            }
        )
        result = run_daily_backtest(
            config=BacktestConfig(initial_cash=100_000.0),
            policy=policy,
            underlying_prices=prices,
            quotes_by_day=qbd,
        )
        assert result.ledger.get_final_cash() == pytest.approx(
            GF001_EXPECTED_FINAL_CASH
        )
        assert result.ledger.validate_cash_conservation()

        # Events match the documented GF-001 timeline exactly
        events = [(e.trade_date, e.event_type) for e in result.ledger.cash_events]
        assert events == [
            (date(2025, 1, 15), EventType.INITIAL),
            (date(2025, 1, 15), EventType.PREMIUM),
            (date(2025, 1, 15), EventType.TRANSACTION_COST),
            (date(2025, 1, 21), EventType.SETTLEMENT),
        ]

    def test_gf002_roll_through_engine(self) -> None:
        prices = underlying_prices_map(GF001_UNDERLYING_PRICES)
        qbd = quotes_by_day(
            option_snapshots_to_quotes(
                GF002_OPTION_SNAPSHOTS_EXPIRY_1 + GF002_OPTION_SNAPSHOTS_EXPIRY_2
            )
        )
        policy = _ScriptedPolicy(
            {
                date(2025, 1, 15): [
                    (
                        EngineAction(
                            kind=EngineActionKind.BUY_PUT,
                            strike=4900.0,
                            expiration_date=GF001_EX1,
                            quantity=1,
                        ),
                        None,
                    )
                ],
                date(2025, 1, 17): [
                    (
                        EngineAction(
                            kind=EngineActionKind.ROLL,
                            strike=4900.0,
                            expiration_date=GF001_EX1,
                            quantity=1,
                            to_strike=4850.0,
                            to_expiry=GF002_EX2,
                        ),
                        None,
                    )
                ],
            }
        )
        result = run_daily_backtest(
            config=BacktestConfig(
                initial_cash=100_000.0,
                roll_config=RollConfig(roll_dte_threshold=GF002_ROLL_DTE_THRESHOLD),
            ),
            policy=policy,
            underlying_prices=prices,
            quotes_by_day=qbd,
        )
        assert result.ledger.get_final_cash() == pytest.approx(
            GF002_EXPECTED_FINAL_CASH
        )
        assert result.ledger.validate_cash_conservation()

    def test_gf003_monetise_reinvest_through_engine(self) -> None:
        from tailhedge.data.fixtures import (
            GF003_OPTION_SNAPSHOTS,
            GF003_UNDERLYING_PRICES,
        )

        prices = underlying_prices_map(GF003_UNDERLYING_PRICES)
        qbd = quotes_by_day(option_snapshots_to_quotes(GF003_OPTION_SNAPSHOTS))
        policy = _ScriptedPolicy(
            {
                date(2025, 1, 15): [
                    (
                        EngineAction(
                            kind=EngineActionKind.BUY_PUT,
                            strike=4900.0,
                            expiration_date=GF002_EX2,
                            quantity=2,
                        ),
                        None,
                    )
                ],
                date(2025, 1, 17): [
                    (
                        EngineAction(
                            kind=EngineActionKind.SELL_TO_CLOSE,
                            strike=4900.0,
                            expiration_date=GF002_EX2,
                            quantity=int(2 * GF003_MONETISE_FRACTION),
                        ),
                        ReinvestDirective(
                            price=4500.0, fraction=GF003_REINVEST_FRACTION
                        ),
                    )
                ],
            }
        )
        result = run_daily_backtest(
            config=BacktestConfig(
                initial_cash=100_000.0, initial_units=GF003_INITIAL_UNITS
            ),
            policy=policy,
            underlying_prices=prices,
            quotes_by_day=qbd,
        )
        assert result.ledger.get_final_cash() == pytest.approx(
            GF003_EXPECTED_FINAL_CASH
        )
        assert result.ledger.get_units() == pytest.approx(GF003_EXPECTED_FINAL_UNITS)
        assert result.ledger.validate_cash_conservation()
        assert result.ledger.validate_unit_conservation()

        # T-004: units conserved and combined value known on the monetisation
        # day close (Jan 17, underlying 4500); the curve marks to market daily.
        monetise_idx = result.trade_dates.index(date(2025, 1, 17))
        assert result.equity_curve[monetise_idx] == pytest.approx(
            GF003_EXPECTED_FINAL_UNITS * 4500 + GF003_EXPECTED_FINAL_CASH
        )
        # Combined value at the Jan-17 close = 1,018,998.05
        assert result.equity_curve[monetise_idx] == pytest.approx(1_018_998.05)


# ---------------------------------------------------------------------------
# Engine fail-closed behaviour
# ---------------------------------------------------------------------------


class TestEngineFailClosed:
    def test_unknown_action_kind_rejected(self) -> None:
        prices = {date(2025, 1, 15): 5000.0}

        class BadPolicy:
            def decide(
                self,
                _trade_date: date,
                _ledger: BacktestLedger,
                _quotes: Mapping[date, Sequence[Quote]],
                _close: float,
            ) -> list[tuple[EngineAction, ReinvestDirective | None]]:
                return [
                    (
                        EngineAction(
                            kind="SELL_TO_OPEN",
                            strike=4900.0,
                            expiration_date=GF001_EX1,
                            quantity=1,
                        ),
                        None,
                    )
                ]

        with pytest.raises(ValueError, match="Unknown engine action"):
            run_daily_backtest(
                config=BacktestConfig(initial_cash=100_000.0),
                policy=BadPolicy(),
                underlying_prices=prices,
                quotes_by_day={},
            )

    def test_action_without_quote_is_skipped_not_crashed(self) -> None:
        prices = {date(2025, 1, 15): 5000.0, date(2025, 1, 16): 4980.0}

        class NoQuotePolicy:
            def decide(
                self,
                _trade_date: date,
                _ledger: BacktestLedger,
                _quotes: Mapping[date, Sequence[Quote]],
                _close: float,
            ) -> list[tuple[EngineAction, ReinvestDirective | None]]:
                return [
                    (
                        EngineAction(
                            kind=EngineActionKind.BUY_PUT,
                            strike=4900.0,
                            expiration_date=GF001_EX1,
                            quantity=1,
                        ),
                        None,
                    )
                ]

        result = run_daily_backtest(
            config=BacktestConfig(initial_cash=100_000.0),
            policy=NoQuotePolicy(),
            underlying_prices=prices,
            quotes_by_day={},  # no quotes at all
        )
        assert all(d.action == "NONE" for d in result.decisions)
        assert result.ledger.get_position_count() == 0
        assert result.ledger.get_cash_balance() == 100_000.0

    def test_empty_underlying_prices_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one trade date"):
            run_daily_backtest(
                config=BacktestConfig(initial_cash=100.0),
                policy=_ScriptedPolicy({}),
                underlying_prices={},
                quotes_by_day={},
            )

    def test_missed_expiry_settlement_fails_closed(self) -> None:
        """A position expiring on a date with no data must fail, not misprice."""
        from datetime import UTC, datetime

        prices = {
            date(2025, 1, 15): 5000.0,
            date(2025, 1, 22): 4800.0,  # expiry Jan 21 is missing!
        }
        quote = Quote(
            trade_date=date(2025, 1, 15),
            snapshot_ts_utc=datetime(2025, 1, 15, 21, 0, tzinfo=UTC),
            strike=4900.0,
            expiration_date=date(2025, 1, 21),  # not in prices
            bid=100.0,
            ask=105.0,
            underlying_price=5000.0,
        )

        class BuyThenHoldPolicy:
            def __init__(self) -> None:
                self.bought = False

            def decide(
                self,
                _trade_date: date,
                _ledger: BacktestLedger,
                _quotes: Mapping[date, Sequence[Quote]],
                _close: float,
            ) -> list[tuple[EngineAction, ReinvestDirective | None]]:
                if self.bought:
                    return []
                self.bought = True
                return [
                    (
                        EngineAction(
                            kind=EngineActionKind.BUY_PUT,
                            strike=4900.0,
                            expiration_date=date(2025, 1, 21),  # not in prices
                            quantity=1,
                        ),
                        None,
                    )
                ]

        with pytest.raises(ValueError, match="never settled"):
            run_daily_backtest(
                config=BacktestConfig(initial_cash=100_000.0),
                policy=BuyThenHoldPolicy(),
                underlying_prices=prices,
                quotes_by_day={date(2025, 1, 15): [quote]},
            )


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


class TestBaselineConfigurations:
    def test_all_baselines_defined(self) -> None:
        baselines = get_all_baseline_configs()
        assert len(baselines) == 3
        types = {b.baseline_type for b in baselines}
        assert types == {
            BaselineType.NO_HEDGE,
            BaselineType.LOWER_EQUITY,
            BaselineType.FIXED_PUT,
        }

    def test_get_baseline_config(self) -> None:
        spec = get_baseline_config(BaselineType.FIXED_PUT)
        assert spec.target_dte == 90
        assert spec.moneyness == pytest.approx(0.95)
        assert spec.budget_pct == pytest.approx(0.01)

    def test_unknown_baseline_raises(self) -> None:
        """get_baseline_config's guard fires when a type lacks a default spec."""
        import tailhedge.backtest.baselines as baselines_module

        original = baselines_module.DEFAULT_BASELINES
        baselines_module.DEFAULT_BASELINES = [NO_HEDGE_SPEC]
        try:
            with pytest.raises(ValueError, match="Unknown baseline type"):
                baselines_module.get_baseline_config(BaselineType.FIXED_PUT)
        finally:
            baselines_module.DEFAULT_BASELINES = original

    def test_fixed_put_is_pput_like(self) -> None:
        """FR-005: the fixed-put baseline is the Cboe-PPUT-like policy."""
        assert FIXED_PUT_SPEC.name == "Fixed Put Hedge (PPUT-like)"
        assert "PPUT" in FIXED_PUT_SPEC.description


class TestBaselinesThroughSharedEngine:
    """T-006: all baselines run through the same engine + fill/cost model."""

    def test_gf003_dataset_baselines(self) -> None:
        from tailhedge.data.fixtures import (
            GF003_OPTION_SNAPSHOTS,
            GF003_UNDERLYING_PRICES,
        )

        prices = underlying_prices_map(GF003_UNDERLYING_PRICES)
        qbd = quotes_by_day(option_snapshots_to_quotes(GF003_OPTION_SNAPSHOTS))
        engine_config = BacktestConfig(
            initial_cash=100_000.0, initial_units=GF003_INITIAL_UNITS
        )
        initial_price = 500.0

        results = {
            spec.baseline_type: run_baseline(
                spec=spec,
                engine_config=engine_config,
                underlying_prices=prices,
                quotes_by_day=qbd,
                initial_price=initial_price,
            )
            for spec in (NO_HEDGE_SPEC, LOWER_EQUITY_SPEC, FIXED_PUT_SPEC)
        }

        # Same engine: every ledger conserves cash and units
        for result in results.values():
            assert result.ledger.validate_cash_conservation()

        # No-hedge never trades
        no_hedge = results[BaselineType.NO_HEDGE]
        assert no_hedge.ledger.get_position_count() == 0
        assert all(
            e.event_type == EventType.INITIAL for e in no_hedge.ledger.cash_events
        )

        # Lower-equity splits value 70/30 at the initial price
        lower = results[BaselineType.LOWER_EQUITY]
        assert lower.ledger.get_units() == pytest.approx(200_000.0 * 0.7 / 500.0)
        assert lower.ledger.get_cash_balance() == pytest.approx(200_000.0 * 0.3)

        # Fixed put has no matching strike in GF-003's tiny quote set, so it
        # fails closed with zero spend rather than trading something else.
        fixed = results[BaselineType.FIXED_PUT]
        fixed_premium = sum(
            -e.amount
            for e in fixed.ledger.cash_events
            if e.event_type == EventType.PREMIUM
        )
        assert fixed_premium == 0.0

    def test_fixed_put_budget_honoured_on_generated_dataset(self) -> None:
        """PPUT-like baseline buys within its rolling annual budget."""
        dataset = generate_synthetic_dataset(
            start_date=date(2025, 1, 15),
            trading_days=126,
            seed=20260101,
            expiry_interval_days=21,
            option_moneyness=0.95,
        )
        engine_config = BacktestConfig(initial_cash=100_000.0, initial_units=200.0)
        result = run_baseline(
            spec=FIXED_PUT_SPEC,
            engine_config=engine_config,
            underlying_prices=dataset.underlying_prices,
            quotes_by_day=dataset.quotes_by_day,
            initial_price=dataset.initial_price,
        )

        premium_spend = sum(
            -e.amount
            for e in result.ledger.cash_events
            if e.event_type == EventType.PREMIUM
        )
        # Net option outlay (buys minus sale/settlement proceeds) must stay
        # within the accruing annual budget (budget_pct of portfolio value).
        net_outlay = -sum(
            e.amount
            for e in result.ledger.cash_events
            if e.event_type
            in (EventType.PREMIUM, EventType.MONETISATION, EventType.SETTLEMENT)
        )
        run_days = (result.trade_dates[-1] - result.trade_dates[0]).days
        max_allowance = 0.01 * 200_000.0 * (run_days / 365.25 + 1e-9)
        assert premium_spend > 0
        assert net_outlay <= max_allowance
        assert result.ledger.validate_cash_conservation()

        metrics = calculate_metrics(
            result.equity_curve, result.premium_events(), years=result.years
        )
        assert metrics.initial_value > 0

    def test_baseline_comparison_math(self) -> None:
        """compare_to_baseline produces the documented deltas."""
        prices = underlying_prices_map(GF001_UNDERLYING_PRICES)
        qbd = quotes_by_day(option_snapshots_to_quotes(GF001_OPTION_SNAPSHOTS))
        engine_config = BacktestConfig(initial_cash=100_000.0, initial_units=20.0)

        hedged = run_daily_backtest(
            config=engine_config,
            policy=RollingHedgePolicy(roll_config=RollConfig(roll_dte_threshold=4)),
            underlying_prices=prices,
            quotes_by_day=qbd,
        )
        no_hedge = run_baseline(
            spec=NO_HEDGE_SPEC,
            engine_config=engine_config,
            underlying_prices=prices,
            quotes_by_day=qbd,
            initial_price=5000.0,
        )
        hedged_metrics = calculate_metrics(
            hedged.equity_curve, hedged.premium_events(), years=hedged.years
        )
        baseline_metrics = calculate_metrics(
            no_hedge.equity_curve, no_hedge.premium_events(), years=no_hedge.years
        )
        comparison = compare_to_baseline(hedged_metrics, baseline_metrics)

        assert comparison.cagr_delta == pytest.approx(
            hedged_metrics.cagr - baseline_metrics.cagr
        )
        expected_dd = abs(baseline_metrics.max_drawdown) - abs(
            hedged_metrics.max_drawdown
        )
        assert comparison.drawdown_improvement == pytest.approx(expected_dd)
        assert comparison.fold_utility == pytest.approx(
            comparison.cagr_delta + 0.25 * comparison.drawdown_improvement
        )


# ---------------------------------------------------------------------------
# Synthetic dataset generator
# ---------------------------------------------------------------------------


class TestSyntheticDataset:
    def test_deterministic_same_seed(self) -> None:
        d1 = generate_synthetic_dataset(
            start_date=date(2025, 1, 15), trading_days=40, seed=7
        )
        d2 = generate_synthetic_dataset(
            start_date=date(2025, 1, 15), trading_days=40, seed=7
        )
        assert d1.underlying_prices == d2.underlying_prices
        assert {
            k: [(q.bid, q.ask) for q in v] for k, v in d1.quotes_by_day.items()
        } == {k: [(q.bid, q.ask) for q in v] for k, v in d2.quotes_by_day.items()}

    def test_different_seed_different_path(self) -> None:
        d1 = generate_synthetic_dataset(
            start_date=date(2025, 1, 15), trading_days=40, seed=7
        )
        d2 = generate_synthetic_dataset(
            start_date=date(2025, 1, 15), trading_days=40, seed=8
        )
        assert d1.underlying_prices != d2.underlying_prices

    def test_crash_episode_present(self) -> None:
        d = generate_synthetic_dataset(
            start_date=date(2025, 1, 15), trading_days=40, seed=7, crash_start_index=20
        )
        prices = [d.underlying_prices[dt] for dt in sorted(d.underlying_prices)]
        worst = min(
            (prices[i + 1] / prices[i] - 1 for i in range(len(prices) - 1)),
        )
        assert worst == pytest.approx(-0.035)

    def test_quotes_exist_for_trading_days(self) -> None:
        d = generate_synthetic_dataset(
            start_date=date(2025, 1, 15), trading_days=60, seed=7
        )
        assert sum(1 for qs in d.quotes_by_day.values() if qs) > 0


# ---------------------------------------------------------------------------
# Full vertical slice: synthetic backtest result
# ---------------------------------------------------------------------------


class TestSyntheticBacktestResult:
    def test_deterministic_results(self) -> None:
        from tailhedge.research.synthetic_backtest import run_synthetic_backtest

        r1 = run_synthetic_backtest()
        r2 = run_synthetic_backtest()
        assert r1.hedged.metrics == r2.hedged.metrics
        assert [(e.name, e.metrics) for e, _ in r1.baselines] == [
            (e.name, e.metrics) for e, _ in r2.baselines
        ]

    def test_all_runs_share_engine_and_dataset(self) -> None:
        from tailhedge.research.synthetic_backtest import run_synthetic_backtest

        r = run_synthetic_backtest()
        names = [e.name for e, _ in r.baselines]
        assert len(names) == 3
        # All comparisons computed against the hedged run
        for _, comparison in r.baselines:
            assert comparison.hedged_metrics == r.hedged.metrics

    def test_api_shape(self) -> None:
        from tailhedge.research.synthetic_backtest import run_synthetic_backtest

        payload = run_synthetic_backtest().to_api_dict()
        assert payload["status"] == "success"
        hedged = payload["hedged"]
        assert isinstance(hedged, dict)
        assert {"cagr", "max_drawdown", "total_premium_spent"} <= set(hedged)
        baselines = payload["baselines"]
        assert isinstance(baselines, list)
        assert len(baselines) == 3
