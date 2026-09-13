"""Unit tests for backtest accounting ledger (T-003).

Tests the GF-001 golden ledger against hand-calculated literals, input
validation (no short puts, no unbacked cash use, no mis-settlement), unit
tracking, and property-based cash/unit invariants.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TypedDict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tailhedge.backtest.ledger import (
    BacktestLedger,
)
from tailhedge.data.fixtures import (
    GF001_EXPECTED_CASH_LEDGER,
    GF001_EXPECTED_FINAL_CASH,
    GF001_EXPECTED_POSITIONS,
    GF001_INITIAL_CASH,
    GF001_PREMIUM_FILL_BUY,
    GF001_PUT_EXPIRY,
    GF001_PUT_STRIKE,
)

# ---------------------------------------------------------------------------
# T-003: GF-001 golden ledger — full-ledger reconciliation
# ---------------------------------------------------------------------------


class TestGF001SimpleOptionPayoff:
    """GF-001: ledger output must reconcile with the full expected ledger."""

    def test_initial_cash(self) -> None:
        """Ledger should start with initial cash on the initial date."""
        ledger = BacktestLedger(
            initial_cash=GF001_INITIAL_CASH, initial_date=date(2025, 1, 15)
        )
        assert ledger.get_cash_balance() == GF001_INITIAL_CASH
        assert ledger.cash_events[0].trade_date == date(2025, 1, 15)

    def test_full_ledger_matches_fixture(self) -> None:
        """Every event (date, type, amount, running cash) must match GF-001."""
        ledger = BacktestLedger(
            initial_cash=GF001_INITIAL_CASH, initial_date=date(2025, 1, 15)
        )
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF001_PUT_STRIKE,
            expiration_date=GF001_PUT_EXPIRY,
            quantity=1,
            premium=GF001_PREMIUM_FILL_BUY,
        )
        ledger.record_transaction_cost(
            trade_date=date(2025, 1, 15),
            cost=0.65,
            description="Commission on buy (1 contract(s))",
        )
        ledger.settle_expiry(trade_date=GF001_PUT_EXPIRY, underlying_price=4800.0)

        actual = [
            (e.trade_date, e.event_type.value, e.amount, e.running_cash)
            for e in ledger.cash_events
        ]
        expected = [
            (e.trade_date, e.event_type, e.amount, e.running_cash)
            for e in GF001_EXPECTED_CASH_LEDGER
        ]
        assert len(actual) == len(expected)
        for (a_date, a_type, a_amount, a_running), (
            e_date,
            e_type,
            e_amount,
            e_running,
        ) in zip(actual, expected, strict=True):
            assert a_date == e_date
            assert a_type == e_type
            assert a_amount == pytest.approx(e_amount)
            assert a_running == pytest.approx(e_running)

    def test_final_cash_matches_fixture(self) -> None:
        ledger = BacktestLedger(
            initial_cash=GF001_INITIAL_CASH, initial_date=date(2025, 1, 15)
        )
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF001_PUT_STRIKE,
            expiration_date=GF001_PUT_EXPIRY,
            quantity=1,
            premium=GF001_PREMIUM_FILL_BUY,
        )
        ledger.record_transaction_cost(trade_date=date(2025, 1, 15), cost=0.65)
        ledger.settle_expiry(trade_date=GF001_PUT_EXPIRY, underlying_price=4800.0)

        assert ledger.get_final_cash() == pytest.approx(GF001_EXPECTED_FINAL_CASH)

    def test_position_events_match_fixture(self) -> None:
        ledger = BacktestLedger(
            initial_cash=GF001_INITIAL_CASH, initial_date=date(2025, 1, 15)
        )
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=GF001_PUT_STRIKE,
            expiration_date=GF001_PUT_EXPIRY,
            quantity=1,
            premium=GF001_PREMIUM_FILL_BUY,
        )
        ledger.settle_expiry(trade_date=GF001_PUT_EXPIRY, underlying_price=4800.0)

        actual = [
            (p.trade_date, p.action.value, p.quantity, p.running_positions)
            for p in ledger.position_events
        ]
        expected = [
            (p.trade_date, p.action, p.quantity, p.running_positions)
            for p in GF001_EXPECTED_POSITIONS
        ]
        assert actual == expected


# ---------------------------------------------------------------------------
# Input validation (fail closed)
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Malformed inputs must fail closed — no short puts, no cash creation."""

    def test_negative_quantity_buy_rejected(self) -> None:
        """A negative-quantity buy is a sell-to-open and must be rejected."""
        ledger = BacktestLedger(initial_cash=100_000.0)
        with pytest.raises(ValueError, match="sell-to-open"):
            ledger.buy_put(
                trade_date=date(2025, 1, 15),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=-1,
                premium=102.50,
            )
        assert ledger.get_position_count() == 0
        assert ledger.get_cash_balance() == 100_000.0

    def test_zero_quantity_buy_rejected(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        with pytest.raises(ValueError, match="quantity"):
            ledger.buy_put(
                trade_date=date(2025, 1, 15),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=0,
                premium=102.50,
            )

    def test_negative_premium_buy_rejected(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        with pytest.raises(ValueError, match="premium"):
            ledger.buy_put(
                trade_date=date(2025, 1, 15),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=1,
                premium=-102.50,
            )
        assert ledger.get_cash_balance() == 100_000.0

    def test_buy_after_expiry_rejected(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        with pytest.raises(ValueError, match="expiration_date"):
            ledger.buy_put(
                trade_date=date(2025, 2, 21),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=1,
                premium=102.50,
            )

    def test_insufficient_cash_buy_rejected(self) -> None:
        """Buying beyond available cash must fail (no borrowing/margin)."""
        ledger = BacktestLedger(initial_cash=100.0)
        with pytest.raises(ValueError, match="Insufficient cash"):
            ledger.buy_put(
                trade_date=date(2025, 1, 15),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=100,
                premium=102.50,
            )
        assert ledger.get_cash_balance() == 100.0
        assert ledger.get_position_count() == 0

    def test_negative_quantity_sell_rejected(self) -> None:
        """A negative-quantity sell must not create phantom positions/cash loss."""
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            premium=102.50,
        )
        with pytest.raises(ValueError, match="quantity"):
            ledger.sell_to_close(
                trade_date=date(2025, 1, 20),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=-1,
                price=150.0,
            )
        assert ledger.get_position_count() == 1

    def test_negative_price_sell_rejected(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            premium=102.50,
        )
        with pytest.raises(ValueError, match="price"):
            ledger.sell_to_close(
                trade_date=date(2025, 1, 20),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=1,
                price=-150.0,
            )
        assert ledger.get_position_count() == 1

    def test_sell_to_close_unowned_position_rejected(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        with pytest.raises(ValueError, match="No matching position"):
            ledger.sell_to_close(
                trade_date=date(2025, 1, 20),
                strike=4900.0,
                expiration_date=date(2025, 2, 21),
                quantity=1,
                price=150.0,
            )

    def test_reinvestment_requires_positive_amount_and_price(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        with pytest.raises(ValueError, match="amount"):
            ledger.reinvest(trade_date=date(2025, 1, 20), amount=0.0, price=4500.0)
        with pytest.raises(ValueError, match="price"):
            ledger.reinvest(trade_date=date(2025, 1, 20), amount=1000.0, price=0.0)

    def test_reinvestment_beyond_cash_rejected(self) -> None:
        ledger = BacktestLedger(initial_cash=100.0)
        with pytest.raises(ValueError, match="Insufficient cash"):
            ledger.reinvest(trade_date=date(2025, 1, 20), amount=1_000.0, price=10.0)

    def test_negative_transaction_cost_rejected(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        with pytest.raises(ValueError, match="cost"):
            ledger.record_transaction_cost(trade_date=date(2025, 1, 20), cost=-1.0)

    def test_invalid_currency_rejected(self) -> None:
        with pytest.raises(ValueError, match="currency"):
            BacktestLedger(initial_cash=100.0, currency="usd")

    def test_cash_events_carry_contract_identifiers(self) -> None:
        """Cash events must link to the option contract for audit."""
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            premium=102.50,
        )
        premium_event = ledger.cash_events[-1]
        assert premium_event.strike == 4900.0
        assert premium_event.expiration_date == date(2025, 2, 21)


# ---------------------------------------------------------------------------
# Settlement correctness
# ---------------------------------------------------------------------------


class TestSettlement:
    """Expiry settlement must happen on the expiry day, priced at expiry."""

    def test_settlement_on_expiry_date(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )
        ledger.settle_expiry(trade_date=date(2025, 1, 20), underlying_price=4800.0)
        expected = 100_000.0 - 102.50 * 100 + (4900.0 - 4800.0) * 100
        assert ledger.get_cash_balance() == pytest.approx(expected)

    def test_settlement_not_before_expiry(self) -> None:
        """Calling settle before expiry must not settle anything."""
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )
        ledger.settle_expiry(trade_date=date(2025, 1, 18), underlying_price=4000.0)
        assert ledger.get_position_count() == 1

    def test_missed_settlement_fails_closed(self) -> None:
        """Settling after the expiry date must raise, not misprice."""
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )
        # Jan-21 call would previously misprice a Jan-20 expiry at 4000:
        # true payoff (100*100) vs wrong payoff (90*100).
        with pytest.raises(ValueError, match="never settled"):
            ledger.settle_expiry(trade_date=date(2025, 1, 21), underlying_price=4000.0)

    def test_otm_settlement_description_is_accurate(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )
        ledger.settle_expiry(trade_date=date(2025, 1, 20), underlying_price=5000.0)
        assert "OTM" in ledger.cash_events[-1].description
        assert "ITM" not in ledger.cash_events[-1].description

    def test_itm_settlement_description(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 1, 20),
            quantity=1,
            premium=102.50,
        )
        ledger.settle_expiry(trade_date=date(2025, 1, 20), underlying_price=4800.0)
        assert "ITM" in ledger.cash_events[-1].description


# ---------------------------------------------------------------------------
# Cash conservation
# ---------------------------------------------------------------------------


class TestCashInvariants:
    """Cash conservation across representative flows."""

    def test_cash_conservation_no_events(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0)
        assert ledger.validate_cash_conservation()

    def test_cash_conservation_after_flows(self) -> None:
        ledger = BacktestLedger(initial_cash=200_000.0)
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
        ledger.sell_to_close(
            trade_date=date(2025, 2, 10),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            price=150.0,
        )
        ledger.record_transaction_cost(trade_date=date(2025, 2, 10), cost=1.95)
        ledger.settle_expiry(trade_date=date(2025, 3, 21), underlying_price=4700.0)
        ledger.reinvest(trade_date=date(2025, 3, 24), amount=10_000.0, price=4700.0)

        assert ledger.validate_cash_conservation()
        expected = (
            200_000.0
            - 102.50 * 100
            - 2 * 80 * 100
            + 150 * 100
            - 1.95
            + 100 * 100
            + 10_000.0
            - 10_000.0
        )
        assert ledger.get_cash_balance() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Unit tracking (core portfolio)
# ---------------------------------------------------------------------------


class TestUnitTracking:
    """Core portfolio units are tracked and conserved."""

    def test_initial_units(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0, initial_units=200.0)
        assert ledger.get_units() == 200.0

    def test_reinvestment_buys_units(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0, initial_units=200.0)
        units_bought = ledger.reinvest(
            trade_date=date(2025, 1, 20), amount=39_750.0, price=4500.0
        )
        assert units_bought == pytest.approx(8.8333333333)
        assert ledger.get_units() == pytest.approx(208.8333333333)
        assert ledger.get_cash_balance() == pytest.approx(60_250.0)
        assert ledger.validate_unit_conservation()

    def test_portfolio_value(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0, initial_units=200.0)
        assert ledger.portfolio_value(500.0) == pytest.approx(200_000.0)
        ledger.reinvest(trade_date=date(2025, 1, 20), amount=39_750.0, price=4500.0)
        # Reinvesting at the current price keeps combined value unchanged:
        # 60,250 cash + 208.8333... * 4500 = 1,000,000
        assert ledger.portfolio_value(4500.0) == pytest.approx(1_000_000.0)

    def test_unit_conservation_detects_tampering(self) -> None:
        ledger = BacktestLedger(initial_cash=100_000.0, initial_units=200.0)
        ledger.units += 1.0  # simulate internal state corruption
        assert not ledger.validate_unit_conservation()


# ---------------------------------------------------------------------------
# Property-based invariants (Hypothesis)
# ---------------------------------------------------------------------------

_STRIKE = 4900.0
_EXPIRY = date(2026, 6, 30)


class _LifecycleScenario(TypedDict):
    """Typed shape of a generated lifecycle scenario."""

    quantity: int
    premium: float
    initial_cash: float
    sells: list[dict[str, float]]
    remaining: int
    settle: bool
    underlying_at_expiry: float


@st.composite
def _lifecycle_scenarios(draw: st.DrawFn) -> _LifecycleScenario:
    """Generate a feasible buy -> partial sells -> settlement lifecycle."""
    quantity = draw(st.integers(min_value=1, max_value=10))
    premium = draw(st.floats(min_value=0.0, max_value=200.0))
    cost = premium * quantity * 100
    initial_cash = cost * draw(st.floats(min_value=1.1, max_value=3.0))

    sells: list[dict[str, float]] = []
    remaining = quantity
    n_sells = draw(st.integers(min_value=0, max_value=quantity))
    for _ in range(n_sells):
        if remaining == 0:
            break
        sell_qty = draw(st.integers(min_value=1, max_value=remaining))
        remaining -= sell_qty
        sells.append(
            {
                "quantity": sell_qty,
                "price": draw(st.floats(min_value=0.0, max_value=500.0)),
            }
        )

    settle = draw(st.booleans())
    underlying_at_expiry = draw(st.floats(min_value=0.0, max_value=6000.0))

    return {
        "quantity": quantity,
        "premium": premium,
        "initial_cash": initial_cash,
        "sells": sells,
        "remaining": remaining,
        "settle": settle,
        "underlying_at_expiry": underlying_at_expiry,
    }


class TestPropertyBasedInvariants:
    """Property-based cash/unit invariants with independent expected values.

    Expected cash is recomputed in the test from the scenario parameters
    (independent of the ledger's event accounting), so any unexplained
    cash creation or loss in the ledger fails the test.
    """

    @settings(max_examples=100)
    @given(scenario=_lifecycle_scenarios())
    def test_cash_matches_independent_expected_value(
        self, scenario: _LifecycleScenario
    ) -> None:
        quantity = scenario["quantity"]
        premium = scenario["premium"]
        initial_cash = scenario["initial_cash"]
        sells = scenario["sells"]
        remaining = scenario["remaining"]
        settle = scenario["settle"]
        underlying = scenario["underlying_at_expiry"]

        ledger = BacktestLedger(
            initial_cash=initial_cash, initial_date=date(2025, 1, 15)
        )
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=_STRIKE,
            expiration_date=_EXPIRY,
            quantity=quantity,
            premium=premium,
        )

        # Independently computed expected cash
        expected = initial_cash - premium * quantity * 100
        for sell in sells:
            sell_quantity = int(sell["quantity"])
            sell_price = sell["price"]
            ledger.sell_to_close(
                trade_date=date(2025, 3, 2),
                strike=_STRIKE,
                expiration_date=_EXPIRY,
                quantity=sell_quantity,
                price=sell_price,
            )
            expected += sell_price * sell_quantity * 100

        if settle:
            ledger.settle_expiry(trade_date=_EXPIRY, underlying_price=underlying)
            expected += max(0.0, _STRIKE - underlying) * remaining * 100

        assert ledger.validate_cash_conservation()
        assert ledger.get_cash_balance() == pytest.approx(expected, abs=1e-6)
        assert math.isfinite(ledger.get_cash_balance())

    @settings(max_examples=50)
    @given(
        amount=st.floats(min_value=1.0, max_value=50_000.0),
        price=st.floats(min_value=1.0, max_value=6000.0),
    )
    def test_reinvestment_units_match_independent_value(
        self, amount: float, price: float
    ) -> None:
        ledger = BacktestLedger(
            initial_cash=max(amount * 2.0, 1.0), initial_units=200.0
        )
        units_bought = ledger.reinvest(
            trade_date=date(2025, 1, 20), amount=amount, price=price
        )
        assert units_bought == pytest.approx(amount / price, abs=1e-9)
        assert ledger.get_units() == pytest.approx(200.0 + amount / price, abs=1e-9)
        assert ledger.validate_unit_conservation()
        assert ledger.validate_cash_conservation()

    def test_buy_sell_roundtrip_never_creates_cash(self) -> None:
        """Buy-then-sell returns exactly (price - premium) * multiplier."""
        ledger = BacktestLedger(initial_cash=100_000.0)
        ledger.buy_put(
            trade_date=date(2025, 1, 15),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            premium=102.50,
        )
        ledger.sell_to_close(
            trade_date=date(2025, 1, 20),
            strike=4900.0,
            expiration_date=date(2025, 2, 21),
            quantity=1,
            price=137.25,
        )
        expected = 100_000.0 + (137.25 - 102.50) * 100
        assert ledger.get_cash_balance() == pytest.approx(expected)
