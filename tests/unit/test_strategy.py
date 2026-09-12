"""Unit tests for hedge roll, monetisation, and reinvestment mechanics (T-004).

Tests GF-002 (roll case) and GF-003 (crash + monetisation) reconciliation.
"""

from __future__ import annotations

from datetime import date

import pytest

from tailhedge.backtest.ledger import BacktestLedger
from tailhedge.backtest.strategy import (
    RollConfig,
    calculate_dte,
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
    GF002_PREMIUM_1_BUY,
    GF002_PREMIUM_1_SELL,
    GF002_PREMIUM_2_BUY,
    GF002_STRIKE_1,
    GF002_STRIKE_2,
    GF003_EXPECTED_FINAL_CASH,
    GF003_INITIAL_CASH,
    GF003_MONETISE_PRICE,
    GF003_PREMIUM_BUY,
    GF003_PUT_EXPIRY,
    GF003_PUT_QUANTITY,
    GF003_PUT_STRIKE,
)

# ---------------------------------------------------------------------------
# DTE calculation
# ---------------------------------------------------------------------------


class TestDTESCalculation:
    """Test days to expiry calculation."""

    def test_dte_same_day(self) -> None:
        """DTE on expiry date should be 0."""
        dte = calculate_dte(date(2025, 1, 21), date(2025, 1, 21))
        assert dte == 0

    def test_dte_one_day(self) -> None:
        """DTE one day before expiry should be 1."""
        dte = calculate_dte(date(2025, 1, 20), date(2025, 1, 21))
        assert dte == 1

    def test_dte_seven_days(self) -> None:
        """DTE seven days before expiry should be 7."""
        dte = calculate_dte(date(2025, 1, 14), date(2025, 1, 21))
        assert dte == 7


# ---------------------------------------------------------------------------
# Roll condition evaluation
# ---------------------------------------------------------------------------


class TestRollCondition:
    """Test roll condition evaluation."""

    def test_roll_when_dte_below_threshold(self) -> None:
        """Should roll when DTE <= threshold."""
        config = RollConfig(roll_dte_threshold=7)
        assert evaluate_roll_condition(date(2025, 1, 14), date(2025, 1, 21), config)

    def test_no_roll_when_dte_above_threshold(self) -> None:
        """Should not roll when DTE > threshold."""
        config = RollConfig(roll_dte_threshold=7)
        assert not evaluate_roll_condition(date(2025, 1, 13), date(2025, 1, 21), config)

    def test_roll_at_exact_threshold(self) -> None:
        """Should roll when DTE == threshold."""
        config = RollConfig(roll_dte_threshold=7)
        assert evaluate_roll_condition(date(2025, 1, 14), date(2025, 1, 21), config)


# ---------------------------------------------------------------------------
# Monetise condition evaluation
# ---------------------------------------------------------------------------


class TestMonetiseCondition:
    """Test monetise condition evaluation."""

    def test_monetise_when_profitable(self) -> None:
        """Should monetise when current price > entry price."""
        assert evaluate_monetise_condition(150.0, 100.0)

    def test_no_monetise_when_not_profitable(self) -> None:
        """Should not monetise when current price <= entry price."""
        assert not evaluate_monetise_condition(100.0, 100.0)
        assert not evaluate_monetise_condition(90.0, 100.0)


# ---------------------------------------------------------------------------
# GF-002: Roll case
# ---------------------------------------------------------------------------


class TestGF002RollCase:
    """GF-002: Two expiries; target policy rolls at known DTE."""

    def test_roll_execution(self) -> None:
        """Roll should close old position and open new one."""
        ledger = BacktestLedger(initial_cash=GF002_INITIAL_CASH)

        # Buy first expiry
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF002_STRIKE_1,
            expiration_date=GF002_EXPIRY_1,
            quantity=1,
            premium=GF002_PREMIUM_1_BUY,
        )

        # Roll on Jan 17 (DTE = 4 days, below threshold)
        decision = execute_roll(
            ledger=ledger,
            trade_date=date(2025, 1, 17),
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_price=GF002_PREMIUM_1_SELL,
            buy_price=GF002_PREMIUM_2_BUY,
        )

        assert decision.action == "ROLL"
        assert decision.roll_quantity == 1

    def test_roll_cash_accounting(self) -> None:
        """Roll should produce correct cash flows."""
        ledger = BacktestLedger(initial_cash=GF002_INITIAL_CASH)

        # Buy first expiry
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF002_STRIKE_1,
            expiration_date=GF002_EXPIRY_1,
            quantity=1,
            premium=GF002_PREMIUM_1_BUY,
        )

        # Roll on Jan 17
        execute_roll(
            ledger=ledger,
            trade_date=date(2025, 1, 17),
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_price=GF002_PREMIUM_1_SELL,
            buy_price=GF002_PREMIUM_2_BUY,
        )

        # Expected: initial - buy1 + sell1 - buy2
        expected = (
            GF002_INITIAL_CASH
            - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
            + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
            - GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER
        )
        assert ledger.get_cash_balance() == pytest.approx(expected)

    def test_roll_cost_matches_fixture(self) -> None:
        """Roll cost should match GF-002 expected."""
        roll_cost = (GF002_PREMIUM_2_BUY - GF002_PREMIUM_1_SELL) * GF001_XSP_MULTIPLIER
        assert roll_cost == pytest.approx(GF002_EXPECTED_ROLL_COST)

    def test_final_cash_matches_fixture(self) -> None:
        """Final cash should match GF-002 expected."""
        ledger = BacktestLedger(initial_cash=GF002_INITIAL_CASH)

        # Buy first expiry
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF002_STRIKE_1,
            expiration_date=GF002_EXPIRY_1,
            quantity=1,
            premium=GF002_PREMIUM_1_BUY,
        )

        # Roll on Jan 17
        execute_roll(
            ledger=ledger,
            trade_date=date(2025, 1, 17),
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_price=GF002_PREMIUM_1_SELL,
            buy_price=GF002_PREMIUM_2_BUY,
        )

        assert ledger.get_final_cash() == pytest.approx(GF002_EXPECTED_FINAL_CASH)

    def test_cash_conservation(self) -> None:
        """Cash should be conserved through roll."""
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
            trade_date=date(2025, 1, 17),
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_price=GF002_PREMIUM_1_SELL,
            buy_price=GF002_PREMIUM_2_BUY,
        )

        assert ledger.validate_cash_conservation()


# ---------------------------------------------------------------------------
# GF-003: Crash + monetisation
# ---------------------------------------------------------------------------


class TestGF003CrashMonetisation:
    """GF-003: Underlying drops sharply; put becomes ITM; monetisation."""

    def test_monetise_execution(self) -> None:
        """Monetise should sell position and optionally reinvest."""
        ledger = BacktestLedger(initial_cash=GF003_INITIAL_CASH)

        # Buy puts
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF003_PUT_STRIKE,
            expiration_date=GF003_PUT_EXPIRY,
            quantity=GF003_PUT_QUANTITY,
            premium=GF003_PREMIUM_BUY,
        )

        # Monetise 50% (1 contract)
        decision = execute_monetise(
            ledger=ledger,
            trade_date=date(2025, 1, 17),
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            price=GF003_MONETISE_PRICE,
            reinvest=False,
        )

        assert decision.action == "MONETISE"
        assert decision.monetise_quantity == 1

    def test_monetise_proceeds_match_fixture(self) -> None:
        """Monetisation proceeds should match GF-003 expected."""
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
            trade_date=date(2025, 1, 17),
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            price=GF003_MONETISE_PRICE,
            reinvest=False,
        )

        # Check cash balance includes monetisation proceeds
        expected_proceeds = GF003_MONETISE_PRICE * 1 * GF001_XSP_MULTIPLIER
        expected_cash = (
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
            + expected_proceeds
        )
        assert ledger.get_cash_balance() == pytest.approx(expected_cash)

    def test_final_cash_matches_fixture(self) -> None:
        """Final cash should match GF-003 expected."""
        ledger = BacktestLedger(initial_cash=GF003_INITIAL_CASH)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF003_PUT_STRIKE,
            expiration_date=GF003_PUT_EXPIRY,
            quantity=GF003_PUT_QUANTITY,
            premium=GF003_PREMIUM_BUY,
        )

        # Monetise with reinvestment (proceeds cancel out)
        execute_monetise(
            ledger=ledger,
            trade_date=date(2025, 1, 17),
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            price=GF003_MONETISE_PRICE,
            reinvest=True,
            reinvest_price=4500.0,
        )

        assert ledger.get_final_cash() == pytest.approx(GF003_EXPECTED_FINAL_CASH)

    def test_cash_conservation(self) -> None:
        """Cash should be conserved through monetisation."""
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
            trade_date=date(2025, 1, 17),
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            price=GF003_MONETISE_PRICE,
            reinvest=False,
        )

        assert ledger.validate_cash_conservation()

    def test_monetise_with_reinvest(self) -> None:
        """Monetise with reinvestment should deduct proceeds from cash."""
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
            trade_date=date(2025, 1, 17),
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            price=GF003_MONETISE_PRICE,
            reinvest=True,
            reinvest_price=4500.0,
        )

        # Cash should be initial minus premium only (monetise + reinvest cancel out)
        expected = (
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
        )
        assert ledger.get_cash_balance() == pytest.approx(expected)
        assert ledger.validate_cash_conservation()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestStrategyEdgeCases:
    """Edge cases for strategy execution."""

    def test_roll_preserves_position_count(self) -> None:
        """Roll should preserve total position count."""
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
            trade_date=date(2025, 1, 17),
            from_strike=GF002_STRIKE_1,
            from_expiry=GF002_EXPIRY_1,
            to_strike=GF002_STRIKE_2,
            to_expiry=GF002_EXPIRY_2,
            quantity=1,
            sell_price=GF002_PREMIUM_1_SELL,
            buy_price=GF002_PREMIUM_2_BUY,
        )

        assert ledger.get_position_count() == 1

    def test_monetise_reduces_position_count(self) -> None:
        """Monetise should reduce position count."""
        ledger = BacktestLedger(initial_cash=GF003_INITIAL_CASH)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF003_PUT_STRIKE,
            expiration_date=GF003_PUT_EXPIRY,
            quantity=GF003_PUT_QUANTITY,
            premium=GF003_PREMIUM_BUY,
        )

        assert ledger.get_position_count() == GF003_PUT_QUANTITY

        execute_monetise(
            ledger=ledger,
            trade_date=date(2025, 1, 17),
            strike=GF003_PUT_STRIKE,
            expiry=GF003_PUT_EXPIRY,
            quantity=1,
            price=GF003_MONETISE_PRICE,
            reinvest=False,
        )

        assert ledger.get_position_count() == GF003_PUT_QUANTITY - 1

    def test_multiple_rolls(self) -> None:
        """Multiple rolls should work correctly."""
        ledger = BacktestLedger(initial_cash=200_000.0)

        # Buy first expiry
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 21),
            quantity=1,
            premium=100.0,
        )

        # Roll to second expiry
        execute_roll(
            ledger=ledger,
            trade_date=date(2025, 1, 17),
            from_strike=4900.0,
            from_expiry=date(2025, 1, 21),
            to_strike=4850.0,
            to_expiry=date(2025, 2, 21),
            quantity=1,
            sell_price=115.0,
            buy_price=150.0,
        )

        # Roll to third expiry
        execute_roll(
            ledger=ledger,
            trade_date=date(2025, 2, 14),
            from_strike=4850.0,
            from_expiry=date(2025, 2, 21),
            to_strike=4800.0,
            to_expiry=date(2025, 3, 21),
            quantity=1,
            sell_price=120.0,
            buy_price=160.0,
        )

        assert ledger.get_position_count() == 1
        assert ledger.validate_cash_conservation()
