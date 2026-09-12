"""Unit tests for hedge roll, monetisation, and reinvestment mechanics (T-004).

Tests GF-002 (roll case) and GF-003 (crash + monetisation) reconciliation
through the fill model (no midpoint fills), quote tradability gates, and
cash+units conservation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from tailhedge.backtest.fill_model import FillConfig, Quote
from tailhedge.backtest.ledger import BacktestLedger, EventType
from tailhedge.backtest.strategy import (
    MonetiseConfig,
    RollConfig,
    calculate_dte,
    evaluate_daily_strategy,
    evaluate_monetise_condition,
    evaluate_roll_condition,
    execute_monetise,
    execute_roll,
)
from tailhedge.data.fixtures import (
    GF001_XSP_MULTIPLIER,
    GF002_EXPECTED_FINAL_CASH,
    GF002_EXPECTED_ROLL_COST,
    GF002_EXPIRY_1,
    GF002_EXPIRY_2,
    GF002_INITIAL_CASH,
    GF002_OPTION_SNAPSHOTS_EXPIRY_1,
    GF002_OPTION_SNAPSHOTS_EXPIRY_2,
    GF002_PREMIUM_1_BUY,
    GF002_PREMIUM_1_SELL,
    GF002_PREMIUM_2_BUY,
    GF002_STRIKE_1,
    GF002_STRIKE_2,
    GF003_EXPECTED_FINAL_CASH,
    GF003_EXPECTED_FINAL_UNITS,
    GF003_INITIAL_CASH,
    GF003_INITIAL_UNITS,
    GF003_MONETISE_FILL_SELL,
    GF003_PREMIUM_BUY,
    GF003_PUT_EXPIRY,
    GF003_PUT_QUANTITY,
    GF003_PUT_STRIKE,
    GF003_REINVEST_FRACTION,
    GF003_REINVEST_PRICE,
    option_snapshots_to_quotes,
)

CHECK_TS = datetime(2025, 1, 17, 21, 0, tzinfo=UTC)  # matches fixture snapshot ts
ROLL_DATE = date(2025, 1, 17)
MONETISE_DATE = date(2025, 1, 17)
DEFAULT_FILL = FillConfig()


def _make_quote(
    bid: float,
    ask: float,
    strike: float,
    expiry: date,
    trade_date: date | None = None,
) -> Quote:
    return Quote(
        trade_date=trade_date or date(2025, 1, 17),
        snapshot_ts_utc=CHECK_TS,
        strike=strike,
        expiration_date=expiry,
        bid=bid,
        ask=ask,
        underlying_price=4500.0,
    )


# ---------------------------------------------------------------------------
# DTE calculation
# ---------------------------------------------------------------------------


class TestDTECalculation:
    """Test calendar-day DTE calculation."""

    def test_dte_same_day(self) -> None:
        assert calculate_dte(date(2025, 1, 21), date(2025, 1, 21)) == 0

    def test_dte_one_day(self) -> None:
        assert calculate_dte(date(2025, 1, 20), date(2025, 1, 21)) == 1

    def test_dte_seven_days(self) -> None:
        assert calculate_dte(date(2025, 1, 14), date(2025, 1, 21)) == 7


# ---------------------------------------------------------------------------
# Roll condition evaluation
# ---------------------------------------------------------------------------


class TestRollCondition:
    """Test roll condition evaluation (calendar-day threshold)."""

    def test_roll_when_dte_below_threshold(self) -> None:
        config = RollConfig(roll_dte_threshold=7)
        assert evaluate_roll_condition(date(2025, 1, 14), date(2025, 1, 21), config)

    def test_no_roll_when_dte_above_threshold(self) -> None:
        config = RollConfig(roll_dte_threshold=7)
        assert not evaluate_roll_condition(date(2025, 1, 13), date(2025, 1, 21), config)

    def test_roll_at_exact_threshold(self) -> None:
        config = RollConfig(roll_dte_threshold=7)
        assert evaluate_roll_condition(date(2025, 1, 14), date(2025, 1, 21), config)


# ---------------------------------------------------------------------------
# Monetise condition evaluation
# ---------------------------------------------------------------------------


class TestMonetiseCondition:
    def test_monetise_when_profitable(self) -> None:
        assert evaluate_monetise_condition(150.0, 100.0)

    def test_no_monetise_when_not_profitable(self) -> None:
        assert not evaluate_monetise_condition(100.0, 100.0)
        assert not evaluate_monetise_condition(90.0, 100.0)


# ---------------------------------------------------------------------------
# GF-002: Roll case (through the fill model)
# ---------------------------------------------------------------------------


class TestGF002RollCase:
    """GF-002: two expiries; policy rolls at known DTE via fill-model prices."""

    def _ledger_with_position(self) -> BacktestLedger:
        ledger = BacktestLedger(initial_cash=GF002_INITIAL_CASH)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF002_STRIKE_1,
            expiration_date=GF002_EXPIRY_1,
            quantity=1,
            premium=GF002_PREMIUM_1_BUY,
        )
        ledger.record_transaction_cost(
            trade_date=date(2025, 1, 15),
            cost=DEFAULT_FILL.commission_per_contract,
            description="Commission on buy (1 contract(s))",
        )
        return ledger

    def _sell_quote(self) -> Quote:
        # GF-002 Jan-17 quote for expiry 1: bid 115 / ask 120
        return option_snapshots_to_quotes(GF002_OPTION_SNAPSHOTS_EXPIRY_1)[-1]

    def _buy_quote(self) -> Quote:
        # GF-002 Jan-17 quote for expiry 2: bid 145 / ask 155
        return option_snapshots_to_quotes(GF002_OPTION_SNAPSHOTS_EXPIRY_2)[0]

    def test_roll_execution(self) -> None:
        ledger = self._ledger_with_position()
        decision = execute_roll(
            ledger=ledger,
            trade_date=ROLL_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_quote=self._sell_quote(),
            buy_quote=self._buy_quote(),
        )
        assert decision.action == "ROLL"
        assert decision.roll_quantity == 1
        assert ledger.get_position_count() == 1  # new position replaces old

    def test_roll_uses_fill_model_prices_not_midpoints(self) -> None:
        """Sell at 116.25 (mid 117.50 - 25% of spread), buy at 152.50."""
        ledger = self._ledger_with_position()
        execute_roll(
            ledger=ledger,
            trade_date=ROLL_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_quote=self._sell_quote(),
            buy_quote=self._buy_quote(),
        )
        expected = (
            GF002_INITIAL_CASH
            - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
            - DEFAULT_FILL.commission_per_contract
            + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
            - GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER
            - 2 * DEFAULT_FILL.commission_per_contract
        )
        assert ledger.get_cash_balance() == pytest.approx(expected)
        assert ledger.get_final_cash() == pytest.approx(GF002_EXPECTED_FINAL_CASH)

    def test_roll_charges_commissions(self) -> None:
        ledger = self._ledger_with_position()
        execute_roll(
            ledger=ledger,
            trade_date=ROLL_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_quote=self._sell_quote(),
            buy_quote=self._buy_quote(),
        )
        cost_events = [
            e
            for e in ledger.cash_events
            if e.event_type == EventType.TRANSACTION_COST and e.trade_date == ROLL_DATE
        ]
        assert len(cost_events) == 2
        assert sum(-e.amount for e in cost_events) == pytest.approx(2 * 0.65)

    def test_untradable_sell_quote_blocks_whole_roll(self) -> None:
        """A wide sell quote must block the roll atomically (no new leg)."""
        ledger = self._ledger_with_position()
        wide_sell = Quote(
            trade_date=ROLL_DATE,
            snapshot_ts_utc=CHECK_TS,
            strike=GF002_STRIKE_1,
            expiration_date=GF002_EXPIRY_1,
            bid=10.0,
            ask=50.0,  # relative spread far above 20%
            underlying_price=4950.0,
        )
        decision = execute_roll(
            ledger=ledger,
            trade_date=ROLL_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_quote=wide_sell,
            buy_quote=self._buy_quote(),
        )
        assert decision.action == "NONE"
        assert "not tradable" in decision.description
        assert ledger.get_position_count() == 1  # old leg still held
        assert not any(p.expiration_date == GF002_EXPIRY_2 for p in ledger.positions)

    def test_untradable_buy_quote_blocks_whole_roll(self) -> None:
        ledger = self._ledger_with_position()
        wide_buy = Quote(
            trade_date=ROLL_DATE,
            snapshot_ts_utc=CHECK_TS,
            strike=GF002_STRIKE_2,
            expiration_date=GF002_EXPIRY_2,
            bid=10.0,
            ask=50.0,
            underlying_price=4950.0,
        )
        decision = execute_roll(
            ledger=ledger,
            trade_date=ROLL_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_quote=self._sell_quote(),
            buy_quote=wide_buy,
        )
        assert decision.action == "NONE"
        assert ledger.get_position_count() == 1
        assert ledger.get_position_count() == 1  # no churn

    def test_roll_to_earlier_expiry_rejected(self) -> None:
        ledger = self._ledger_with_position()
        with pytest.raises(ValueError, match="must be after"):
            execute_roll(
                ledger=ledger,
                trade_date=ROLL_DATE,
                current_time=CHECK_TS,
                fill_config=DEFAULT_FILL,
                from_strike=GF002_STRIKE_1,
                from_expiry=GF002_EXPIRY_1,
                to_strike=GF002_STRIKE_2,
                to_expiry=date(2025, 1, 14),  # earlier than from_expiry
                quantity=1,
                sell_quote=self._sell_quote(),
                buy_quote=self._buy_quote(),
            )

    def test_roll_cost_matches_fixture(self) -> None:
        assert (
            pytest.approx(GF002_EXPECTED_ROLL_COST)
            == (GF002_PREMIUM_2_BUY - GF002_PREMIUM_1_SELL) * GF001_XSP_MULTIPLIER
        )

    def test_cash_conservation(self) -> None:
        ledger = self._ledger_with_position()
        execute_roll(
            ledger=ledger,
            trade_date=ROLL_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_quote=self._sell_quote(),
            buy_quote=self._buy_quote(),
        )
        assert ledger.validate_cash_conservation()


# ---------------------------------------------------------------------------
# GF-003: Crash + monetisation
# ---------------------------------------------------------------------------


class TestGF003CrashMonetisation:
    """GF-003: monetise 50% of profitable puts; reinvest releases cash."""

    def _ledger_with_positions(self) -> BacktestLedger:
        ledger = BacktestLedger(
            initial_cash=GF003_INITIAL_CASH, initial_units=GF003_INITIAL_UNITS
        )
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF003_PUT_STRIKE,
            expiration_date=GF003_PUT_EXPIRY,
            quantity=GF003_PUT_QUANTITY,
            premium=GF003_PREMIUM_BUY,
        )
        ledger.record_transaction_cost(
            trade_date=date(2025, 1, 15),
            cost=DEFAULT_FILL.commission_per_contract * GF003_PUT_QUANTITY,
            description="Commission on buy (2 contract(s))",
        )
        return ledger

    def _sell_quote(self) -> Quote:
        return _make_quote(395.0, 405.0, GF003_PUT_STRIKE, GF003_PUT_EXPIRY)

    def test_monetise_execution(self) -> None:
        ledger = self._ledger_with_positions()
        decision = execute_monetise(
            ledger=ledger,
            trade_date=MONETISE_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            sell_quote=self._sell_quote(),
        )
        assert decision.action == "MONETISE"
        assert decision.monetise_quantity == 1

    def test_monetise_sells_at_fill_price_not_midpoint(self) -> None:
        """Sell fill = 400 - 25% of 10 = 397.50, never the 400 midpoint."""
        ledger = self._ledger_with_positions()
        decision = execute_monetise(
            ledger=ledger,
            trade_date=MONETISE_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            sell_quote=self._sell_quote(),
        )
        assert decision.monetise_price == pytest.approx(397.50)
        assert ledger.get_cash_balance() == pytest.approx(
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
            - DEFAULT_FILL.commission_per_contract * GF003_PUT_QUANTITY
            + GF003_MONETISE_FILL_SELL * GF001_XSP_MULTIPLIER
            - DEFAULT_FILL.commission_per_contract
        )

    def test_monetise_with_reinvestment_buys_units(self) -> None:
        """Reinvest 100% of proceeds: 39,750 / 4500 = 8.8333 units bought."""
        ledger = self._ledger_with_positions()
        decision = execute_monetise(
            ledger=ledger,
            trade_date=MONETISE_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            sell_quote=self._sell_quote(),
            reinvest=True,
            reinvest_price=GF003_REINVEST_PRICE,
            reinvest_fraction=GF003_REINVEST_FRACTION,
        )
        assert decision.reinvest_units == pytest.approx(
            GF003_EXPECTED_FINAL_UNITS - GF003_INITIAL_UNITS
        )
        assert ledger.get_units() == pytest.approx(GF003_EXPECTED_FINAL_UNITS)
        assert ledger.get_final_cash() == pytest.approx(GF003_EXPECTED_FINAL_CASH)
        assert ledger.validate_cash_conservation()
        assert ledger.validate_unit_conservation()

    def test_monetise_fraction_respected(self) -> None:
        """reinvest_fraction=0.5 reinvests half the proceeds."""
        ledger = self._ledger_with_positions()
        execute_monetise(
            ledger=ledger,
            trade_date=MONETISE_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            sell_quote=self._sell_quote(),
            reinvest=True,
            reinvest_price=GF003_REINVEST_PRICE,
            reinvest_fraction=0.5,
        )
        # Half the proceeds stayed in cash
        expected = (
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
            - DEFAULT_FILL.commission_per_contract * GF003_PUT_QUANTITY
            + GF003_MONETISE_FILL_SELL * GF001_XSP_MULTIPLIER
            - DEFAULT_FILL.commission_per_contract
            - GF003_MONETISE_FILL_SELL * GF001_XSP_MULTIPLIER * 0.5
        )
        assert ledger.get_cash_balance() == pytest.approx(expected)

    def test_untradable_sell_quote_blocks_monetisation(self) -> None:
        ledger = self._ledger_with_positions()
        wide = _make_quote(395.0, 500.0, GF003_PUT_STRIKE, GF003_PUT_EXPIRY)
        decision = execute_monetise(
            ledger=ledger,
            trade_date=MONETISE_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            sell_quote=wide,
            reinvest=True,
            reinvest_price=GF003_REINVEST_PRICE,
        )
        assert decision.action == "NONE"
        assert ledger.get_position_count() == GF003_PUT_QUANTITY
        assert ledger.get_units() == pytest.approx(GF003_INITIAL_UNITS)

    def test_cash_conservation(self) -> None:
        ledger = self._ledger_with_positions()
        execute_monetise(
            ledger=ledger,
            trade_date=MONETISE_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            sell_quote=self._sell_quote(),
        )
        assert ledger.validate_cash_conservation()


# ---------------------------------------------------------------------------
# Daily strategy decisions
# ---------------------------------------------------------------------------


class TestEvaluateDailyStrategy:
    """evaluate_daily_strategy produces roll/monetise decisions."""

    def _ledger(self) -> BacktestLedger:
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 21),
            quantity=2,
            premium=100.0,
        )
        return ledger

    def test_roll_eligible_position_reported(self) -> None:
        ledger = self._ledger()
        quote = _make_quote(115.0, 120.0, 4900.0, date(2025, 1, 21))
        decisions = evaluate_daily_strategy(
            trade_date=date(2025, 1, 17),
            ledger=ledger,
            roll_config=RollConfig(roll_dte_threshold=7),
            monetise_config=MonetiseConfig(monetise_fraction=0.5),
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            quotes_by_position={(4900.0, date(2025, 1, 21)): quote},
        )
        assert len(decisions) == 1
        assert decisions[0].action == "ROLL"
        assert decisions[0].roll_quantity == 2

    def test_profitable_position_monetise_candidate(self) -> None:
        """Non-roll-eligible but profitable -> MONETISE decision with fraction."""
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),  # DTE far above threshold
            quantity=2,
            premium=100.0,
        )
        quote = _make_quote(395.0, 405.0, 4900.0, date(2025, 2, 21))
        decisions = evaluate_daily_strategy(
            trade_date=date(2025, 1, 17),
            ledger=ledger,
            roll_config=RollConfig(roll_dte_threshold=7),
            monetise_config=MonetiseConfig(monetise_fraction=0.5),
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            quotes_by_position={(4900.0, date(2025, 2, 21)): quote},
        )
        assert len(decisions) == 1
        assert decisions[0].action == "MONETISE"
        assert decisions[0].monetise_quantity == 1  # floor(2 * 0.5)

    def test_no_quote_means_no_decision(self) -> None:
        """Fail closed: no executable quote -> no simulated trade."""
        ledger = self._ledger()
        decisions = evaluate_daily_strategy(
            trade_date=date(2025, 1, 17),
            ledger=ledger,
            roll_config=RollConfig(roll_dte_threshold=7),
            monetise_config=MonetiseConfig(monetise_fraction=0.5),
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            quotes_by_position={},
        )
        assert decisions == []

    def test_unprofitable_position_not_reported(self) -> None:
        ledger = self._ledger()
        quote = _make_quote(50.0, 60.0, 4900.0, date(2025, 2, 21))
        decisions = evaluate_daily_strategy(
            trade_date=date(2025, 1, 17),
            ledger=ledger,
            roll_config=RollConfig(roll_dte_threshold=7),
            monetise_config=MonetiseConfig(monetise_fraction=0.5),
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            quotes_by_position={(4900.0, date(2025, 2, 21)): quote},
        )
        assert decisions == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestStrategyEdgeCases:
    def test_roll_preserves_position_count(self) -> None:
        ledger = BacktestLedger(initial_cash=GF002_INITIAL_CASH)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF002_STRIKE_1,
            expiration_date=GF002_EXPIRY_1,
            quantity=1,
            premium=GF002_PREMIUM_1_BUY,
        )
        execute_roll(
            ledger=ledger,
            trade_date=ROLL_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_quote=option_snapshots_to_quotes(GF002_OPTION_SNAPSHOTS_EXPIRY_1)[-1],
            buy_quote=option_snapshots_to_quotes(GF002_OPTION_SNAPSHOTS_EXPIRY_2)[0],
        )
        assert ledger.get_position_count() == 1

    def test_monetise_reduces_position_count(self) -> None:
        ledger = BacktestLedger(initial_cash=GF003_INITIAL_CASH)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF003_PUT_STRIKE,
            expiration_date=GF003_PUT_EXPIRY,
            quantity=GF003_PUT_QUANTITY,
            premium=GF003_PREMIUM_BUY,
        )
        execute_monetise(
            ledger=ledger,
            trade_date=MONETISE_DATE,
            current_time=CHECK_TS,
            fill_config=DEFAULT_FILL,
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            sell_quote=_make_quote(395.0, 405.0, GF003_PUT_STRIKE, GF003_PUT_EXPIRY),
        )
        assert ledger.get_position_count() == GF003_PUT_QUANTITY - 1
