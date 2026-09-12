"""Unit tests for backtest accounting ledger (T-003).

Tests golden payoff ledger matches hand-calculated result and
property-based cash invariants.
"""

from __future__ import annotations

from datetime import date

import pytest

from tailhedge.backtest.ledger import (
    BacktestLedger,
    EventType,
    PositionAction,
)
from tailhedge.data.fixtures import (
    GF001_EXPECTED_FINAL_CASH,
    GF001_INITIAL_CASH,
    GF001_PREMIUM_MIDPOINT,
    GF001_PUT_EXPIRY,
    GF001_PUT_STRIKE,
    GF001_XSP_MULTIPLIER,
)

# ---------------------------------------------------------------------------
# T-003: Golden payoff ledger matches hand-calculated result
# ---------------------------------------------------------------------------


class TestGF001SimpleOptionPayoff:
    """GF-001: Simple option payoff ledger reconciliation."""

    def test_initial_cash(self) -> None:
        """Ledger should start with initial cash."""
        ledger = BacktestLedger(initial_cash=GF001_INITIAL_CASH)
        assert ledger.get_cash_balance() == GF001_INITIAL_CASH

    def test_buy_put_records_premium(self) -> None:
        """Buying a put should deduct premium from cash."""
        ledger = BacktestLedger(initial_cash=GF001_INITIAL_CASH)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF001_PUT_STRIKE,
            expiration_date=GF001_PUT_EXPIRY,
            quantity=1,
            premium=GF001_PREMIUM_MIDPOINT,
        )

        expected_cash = (
            GF001_INITIAL_CASH - GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER
        )
        assert ledger.get_cash_balance() == pytest.approx(expected_cash)

    def test_settlement_itm_payoff(self) -> None:
        """ITM put settlement should add payoff to cash."""
        ledger = BacktestLedger(initial_cash=GF001_INITIAL_CASH)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF001_PUT_STRIKE,
            expiration_date=GF001_PUT_EXPIRY,
            quantity=1,
            premium=GF001_PREMIUM_MIDPOINT,
        )

        # Underlying at 4800, strike at 4900 -> payoff = 100
        # Settlement happens on expiry date
        ledger.settle_expiry(
            trade_date=GF001_PUT_EXPIRY,
            underlying_price=4800.0,
        )

        expected_payoff = (GF001_PUT_STRIKE - 4800.0) * GF001_XSP_MULTIPLIER
        expected_cash = (
            GF001_INITIAL_CASH
            - GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER
            + expected_payoff
        )
        assert ledger.get_cash_balance() == pytest.approx(expected_cash)

    def test_final_cash_matches_fixture(self) -> None:
        """Final cash should match GF-001 expected."""
        ledger = BacktestLedger(initial_cash=GF001_INITIAL_CASH)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF001_PUT_STRIKE,
            expiration_date=GF001_PUT_EXPIRY,
            quantity=1,
            premium=GF001_PREMIUM_MIDPOINT,
        )

        ledger.settle_expiry(
            trade_date=GF001_PUT_EXPIRY,
            underlying_price=4800.0,
        )

        assert ledger.get_final_cash() == pytest.approx(GF001_EXPECTED_FINAL_CASH)

    def test_cash_ledger_events_match_fixture(self) -> None:
        """Cash ledger events should match GF-001 expected."""
        ledger = BacktestLedger(initial_cash=GF001_INITIAL_CASH)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF001_PUT_STRIKE,
            expiration_date=GF001_PUT_EXPIRY,
            quantity=1,
            premium=GF001_PREMIUM_MIDPOINT,
        )

        ledger.settle_expiry(
            trade_date=GF001_PUT_EXPIRY,
            underlying_price=4800.0,
        )

        # Filter out the initial event (date is placeholder)
        actual_events = [
            e for e in ledger.cash_events if e.event_type != EventType.INITIAL
        ]

        assert len(actual_events) == 2

        # Premium event
        premium_event = actual_events[0]
        assert premium_event.event_type == EventType.PREMIUM
        assert premium_event.amount == pytest.approx(
            -GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER
        )

        # Settlement event
        settlement_event = actual_events[1]
        assert settlement_event.event_type == EventType.SETTLEMENT
        assert settlement_event.amount == pytest.approx(
            (GF001_PUT_STRIKE - 4800.0) * GF001_XSP_MULTIPLIER
        )

    def test_position_events_match_fixture(self) -> None:
        """Position events should match GF-001 expected."""
        ledger = BacktestLedger(initial_cash=GF001_INITIAL_CASH)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF001_PUT_STRIKE,
            expiration_date=GF001_PUT_EXPIRY,
            quantity=1,
            premium=GF001_PREMIUM_MIDPOINT,
        )

        ledger.settle_expiry(
            trade_date=GF001_PUT_EXPIRY,
            underlying_price=4800.0,
        )

        assert len(ledger.position_events) == 2

        buy_event = ledger.position_events[0]
        assert buy_event.action == PositionAction.BUY
        assert buy_event.quantity == 1
        assert buy_event.running_positions == 1

        expire_event = ledger.position_events[1]
        assert expire_event.action == PositionAction.EXPIRED
        assert expire_event.quantity == 1
        assert expire_event.running_positions == 0


# ---------------------------------------------------------------------------
# Property-based cash invariants
# ---------------------------------------------------------------------------


class TestCashInvariants:
    """Property-based tests for cash invariants."""

    def test_cash_conservation_no_events(self) -> None:
        """Cash should be conserved with no events after initial."""
        ledger = BacktestLedger(initial_cash=100_000.0)
        assert ledger.validate_cash_conservation()

    def test_cash_conservation_after_buy(self) -> None:
        """Cash should be conserved after buying a put."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            premium=102.50,
        )

        assert ledger.validate_cash_conservation()

    def test_cash_conservation_after_settlement(self) -> None:
        """Cash should be conserved after settlement."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )

        ledger.settle_expiry(
            trade_date=date(2025, 1, 20),
            underlying_price=4800.0,
        )

        assert ledger.validate_cash_conservation()

    def test_cash_conservation_multiple_positions(self) -> None:
        """Cash should be conserved with multiple positions."""
        ledger = BacktestLedger(initial_cash=200_000.0)

        # Buy two different puts
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            premium=102.50,
        )

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4800.0,
            expiration_date=date(2025, 3, 21),
            quantity=2,
            premium=80.00,
        )

        # Settle first position
        ledger.settle_expiry(
            trade_date=date(2025, 2, 21),
            underlying_price=4800.0,
        )

        assert ledger.validate_cash_conservation()

    def test_no_cash_creation(self) -> None:
        """Ledger should not create cash from nothing."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        # Buy OTM put (expires worthless)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )

        # Settle with underlying above strike (OTM)
        ledger.settle_expiry(
            trade_date=date(2025, 1, 20),
            underlying_price=5000.0,
        )

        # Cash should be less than initial (premium lost)
        assert ledger.get_cash_balance() < 100_000.0
        assert ledger.validate_cash_conservation()

    def test_no_cash_destruction(self) -> None:
        """Ledger should not destroy cash without explicit events."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        # Buy ITM put
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )

        # Settle with underlying below strike (ITM)
        ledger.settle_expiry(
            trade_date=date(2025, 1, 20),
            underlying_price=4800.0,
        )

        # Cash should be initial minus premium plus payoff
        expected = 100_000.0 - 102.50 * 100 + (4900.0 - 4800.0) * 100
        assert ledger.get_cash_balance() == pytest.approx(expected)
        assert ledger.validate_cash_conservation()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestLedgerEdgeCases:
    """Edge cases for backtest ledger."""

    def test_otm_settlement_zero_payoff(self) -> None:
        """OTM put settlement should result in zero payoff."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )

        # Underlying above strike -> OTM
        ledger.settle_expiry(
            trade_date=date(2025, 1, 20),
            underlying_price=5000.0,
        )

        # Only premium lost
        expected = 100_000.0 - 102.50 * 100
        assert ledger.get_cash_balance() == pytest.approx(expected)

    def test_atm_settlement_zero_payoff(self) -> None:
        """ATM put settlement should result in zero payoff."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )

        # Underlying at strike -> ATM
        ledger.settle_expiry(
            trade_date=date(2025, 1, 20),
            underlying_price=4900.0,
        )

        # Only premium lost
        expected = 100_000.0 - 102.50 * 100
        assert ledger.get_cash_balance() == pytest.approx(expected)

    def test_sell_to_close(self) -> None:
        """Sell to close should add proceeds to cash."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            premium=102.50,
        )

        # Sell before expiry at higher price
        ledger.sell_to_close(
            trade_date=date(2025, 1, 20),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            price=150.0,
        )

        expected = 100_000.0 - 102.50 * 100 + 150.0 * 100
        assert ledger.get_cash_balance() == pytest.approx(expected)

    def test_sell_to_close_partial(self) -> None:
        """Partial sell to close should reduce position."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=2,
            premium=102.50,
        )

        assert ledger.get_position_count() == 2

        # Sell 1 contract
        ledger.sell_to_close(
            trade_date=date(2025, 1, 20),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            price=150.0,
        )

        assert ledger.get_position_count() == 1
        assert ledger.validate_cash_conservation()

    def test_sell_to_close_nonexistent_position(self) -> None:
        """Selling non-existent position should raise error."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        with pytest.raises(ValueError, match="No matching position"):
            ledger.sell_to_close(
                trade_date=date(2025, 1, 20),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=1,
                price=150.0,
            )

    def test_reinvestment(self) -> None:
        """Reinvestment should deduct cash."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        ledger.reinvest(
            trade_date=date(2025, 1, 20),
            amount=50_000.0,
        )

        assert ledger.get_cash_balance() == pytest.approx(50_000.0)
        assert ledger.validate_cash_conservation()

    def test_transaction_cost(self) -> None:
        """Transaction cost should deduct cash."""
        ledger = BacktestLedger(initial_cash=100_000.0)

        ledger.record_transaction_cost(
            trade_date=date(2025, 1, 20),
            cost=10.0,
        )

        assert ledger.get_cash_balance() == pytest.approx(99_990.0)
        assert ledger.validate_cash_conservation()

    def test_empty_ledger(self) -> None:
        """Empty ledger should have correct initial state."""
        ledger = BacktestLedger(initial_cash=0.0)

        assert ledger.get_cash_balance() == 0.0
        assert ledger.get_position_count() == 0
        assert len(ledger.cash_events) == 1  # Initial event
        assert len(ledger.position_events) == 0
