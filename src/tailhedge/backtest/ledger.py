"""Backtest accounting ledger.

Implements FR-004: deterministic backtest engine accounting.
Tracks core portfolio units/cash, long-put positions, expiry settlement,
premium/cost flows, and explicit currencies.

Safety invariants enforced here:
- Only long puts can be held: quantity must be positive, so a "buy" can
  never act as a sell-to-open (AGENT_INSTRUCTIONS §3.4).
- Cash can never go negative: purchases and reinvestments must be covered
  by available cash (no borrowing/margin, AGENT_INSTRUCTIONS §3.5).
- Expiry settlement happens exactly on the expiry date; missed settlements
  fail closed instead of being priced with a later underlying price.
- Cash changes only via explicit recorded events; ``validate_cash_conservation``
  checks the full running-cash chain, and property-based tests verify final
  cash against independently computed expected values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class EventType(StrEnum):
    """Types of ledger events."""

    INITIAL = "INITIAL"
    PREMIUM = "PREMIUM"
    SETTLEMENT = "SETTLEMENT"
    MONETISATION = "MONETISATION"
    REINVESTMENT = "REINVESTMENT"
    TRANSACTION_COST = "TRANSACTION_COST"


class PositionAction(StrEnum):
    """Types of position actions."""

    BUY = "BUY"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"
    EXPIRED = "EXPIRED"
    NONE = "NONE"


@dataclass(frozen=True)
class LedgerEvent:
    """A single event in the cash ledger.

    ``strike``/``expiration_date`` link cash events to the specific option
    contract involved (None for portfolio-level events such as INITIAL).
    """

    trade_date: date
    event_type: EventType
    amount: float
    running_cash: float
    description: str
    strike: float | None = None
    expiration_date: date | None = None


@dataclass(frozen=True)
class PositionEvent:
    """A single position change event."""

    trade_date: date
    action: PositionAction
    quantity: int
    strike: float
    expiration_date: date
    running_positions: int
    description: str


@dataclass
class PutPosition:
    """A long put position held in the portfolio."""

    strike: float
    expiration_date: date
    quantity: int
    entry_premium: float  # Per unit premium paid


def _validate_positive(name: str, value: float) -> None:
    """Raise ValueError unless value is a finite positive number."""
    if not math.isfinite(value) or value <= 0:
        msg = f"{name} must be a finite positive number, got {value}"
        raise ValueError(msg)


def _validate_non_negative(name: str, value: float) -> None:
    """Raise ValueError unless value is a finite non-negative number."""
    if not math.isfinite(value) or value < 0:
        msg = f"{name} must be a finite non-negative number, got {value}"
        raise ValueError(msg)


@dataclass
class BacktestLedger:
    """Accounting ledger for backtest simulation.

    Tracks cash balance, core portfolio units, long-put positions, and all
    events for reconciliation. Ensures no unexplained cash creation or loss.
    All amounts are in ``currency`` (mixing currencies is not permitted here;
    conversion must happen explicitly at the caller, e.g. via GF-006 FX input).
    """

    initial_cash: float
    initial_units: float = 0.0
    currency: str = "USD"
    multiplier: float = 100.0  # XSP/SPX options multiplier
    initial_date: date = field(default_factory=lambda: date(1970, 1, 1))

    # State
    cash: float = field(init=False)
    units: float = field(init=False)
    _reinvested_units: float = field(init=False, default=0.0, repr=False)
    positions: list[PutPosition] = field(default_factory=list)
    cash_events: list[LedgerEvent] = field(default_factory=list)
    position_events: list[PositionEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize cash/units with starting balances."""
        _validate_non_negative("initial_cash", self.initial_cash)
        _validate_non_negative("initial_units", self.initial_units)
        _validate_positive("multiplier", self.multiplier)
        if len(self.currency) != 3 or not self.currency.isupper():
            msg = f"currency must be a 3-letter ISO code, got {self.currency!r}"
            raise ValueError(msg)
        self.cash = 0.0
        self.units = 0.0
        self._reinvested_units = 0.0
        self._record_event(
            trade_date=self.initial_date,
            event_type=EventType.INITIAL,
            amount=self.initial_cash,
            description="Initial portfolio cash",
        )
        if self.initial_units > 0:
            self.units = self.initial_units

    def _record_event(
        self,
        trade_date: date,
        event_type: EventType,
        amount: float,
        description: str,
        strike: float | None = None,
        expiration_date: date | None = None,
    ) -> None:
        """Record a cash event and update running balance."""
        self.cash += amount
        event = LedgerEvent(
            trade_date=trade_date,
            event_type=event_type,
            amount=amount,
            running_cash=self.cash,
            description=description,
            strike=strike,
            expiration_date=expiration_date,
        )
        self.cash_events.append(event)

    def buy_put(
        self,
        trade_date: date,
        strike: float,
        expiration_date: date,
        quantity: int,
        premium: float,
    ) -> None:
        """Buy a long put position with cash on hand.

        Parameters
        ----------
        trade_date : date
            Date of the trade.
        strike : float
            Strike price of the put.
        expiration_date : date
            Expiration date of the put.
        quantity : int
            Number of contracts to buy (must be positive).
        premium : float
            Premium per unit (not multiplied by multiplier).

        Raises
        ------
        ValueError
            If quantity <= 0, premium < 0, expiration <= trade_date, or
            the cost exceeds available cash (no borrowing/margin).
        """
        if quantity <= 0:
            msg = (
                f"quantity must be a positive number of contracts, got {quantity}; "
                f"negative quantity would open a short (sell-to-open) position"
            )
            raise ValueError(msg)
        _validate_non_negative("premium", premium)
        if expiration_date <= trade_date:
            msg = (
                f"expiration_date ({expiration_date}) must be after "
                f"trade_date ({trade_date})"
            )
            raise ValueError(msg)

        cost = premium * quantity * self.multiplier
        if cost > self.cash + 1e-9:
            msg = (
                f"Insufficient cash: cost {cost} exceeds available cash "
                f"{self.cash}; borrowing/margin is not permitted"
            )
            raise ValueError(msg)

        position = PutPosition(
            strike=strike,
            expiration_date=expiration_date,
            quantity=quantity,
            entry_premium=premium,
        )
        self.positions.append(position)

        # Record cash event
        self._record_event(
            trade_date=trade_date,
            event_type=EventType.PREMIUM,
            amount=-cost,
            description=f"Buy {quantity} put(s) at premium {premium}",
            strike=strike,
            expiration_date=expiration_date,
        )

        # Record position event
        total_positions = sum(p.quantity for p in self.positions)
        self.position_events.append(
            PositionEvent(
                trade_date=trade_date,
                action=PositionAction.BUY,
                quantity=quantity,
                strike=strike,
                expiration_date=expiration_date,
                running_positions=total_positions,
                description=f"Buy {quantity} put contract(s)",
            )
        )

    def sell_to_close(
        self,
        trade_date: date,
        strike: float,
        expiration_date: date,
        quantity: int,
        price: float,
    ) -> None:
        """Sell to close part or all of an owned long put position.

        Parameters
        ----------
        trade_date : date
            Date of the trade.
        strike : float
            Strike price of the put.
        expiration_date : date
            Expiration date of the put.
        quantity : int
            Number of contracts to sell (must be positive).
        price : float
            Sell price per unit (not multiplied by multiplier).

        Raises
        ------
        ValueError
            If quantity <= 0, price < 0, or no matching owned long position
            with sufficient quantity exists (no sell-to-open).
        """
        if quantity <= 0:
            msg = (
                f"quantity must be a positive number of contracts, got {quantity}; "
                f"selling requires closing an owned long position"
            )
            raise ValueError(msg)
        _validate_non_negative("price", price)

        # Find matching position
        position = self._find_position(strike, expiration_date, quantity)
        if position is None:
            msg = (
                f"No matching position for {quantity} put(s) "
                f"with strike {strike} expiring {expiration_date}"
            )
            raise ValueError(msg)

        proceeds = price * quantity * self.multiplier

        # Update or remove position
        if position.quantity == quantity:
            self.positions.remove(position)
        else:
            position.quantity -= quantity

        # Record cash event
        self._record_event(
            trade_date=trade_date,
            event_type=EventType.MONETISATION,
            amount=proceeds,
            description=f"Sell {quantity} put(s) at price {price}",
            strike=strike,
            expiration_date=expiration_date,
        )

        # Record position event
        total_positions = sum(p.quantity for p in self.positions)
        self.position_events.append(
            PositionEvent(
                trade_date=trade_date,
                action=PositionAction.SELL_TO_CLOSE,
                quantity=quantity,
                strike=strike,
                expiration_date=expiration_date,
                running_positions=total_positions,
                description=f"Sell {quantity} put contract(s) to close",
            )
        )

    def settle_expiry(
        self,
        trade_date: date,
        underlying_price: float,
    ) -> None:
        """Settle all put positions expiring exactly on ``trade_date``.

        The settlement price is the underlying price *on the expiry date*;
        calling this method with positions whose expiry was missed (i.e.
        ``expiration_date < trade_date``) raises instead of pricing them at
        the current price, so stale positions can never be mis-settled.

        Parameters
        ----------
        trade_date : date
            Date of settlement (must equal each position's expiry date).
        underlying_price : float
            Price of the underlying at expiry.

        Raises
        ------
        ValueError
            If a position expired strictly before ``trade_date`` (missed
            settlement) — the caller must fail closed and reconcile.
        """
        _validate_non_negative("underlying_price", underlying_price)

        missed = [p for p in self.positions if p.expiration_date < trade_date]
        if missed:
            details = ", ".join(f"{p.strike}/{p.expiration_date}" for p in missed)
            msg = (
                f"Position(s) expired before trade_date {trade_date} and were "
                f"never settled: {details}; refusing to price at the current "
                f"underlying ({underlying_price})"
            )
            raise ValueError(msg)

        expired = [p for p in self.positions if p.expiration_date == trade_date]

        for position in expired:
            # Calculate payoff: max(0, strike - underlying)
            payoff_per_unit = max(0.0, position.strike - underlying_price)
            total_payoff = payoff_per_unit * position.quantity * self.multiplier

            if payoff_per_unit > 0:
                settlement_description = (
                    f"Put expires ITM, cash settlement: "
                    f"strike={position.strike}, underlying={underlying_price}"
                )
            else:
                settlement_description = (
                    f"Put expires OTM/ATM, expires worthless: "
                    f"strike={position.strike}, underlying={underlying_price}"
                )

            # Record cash event
            self._record_event(
                trade_date=trade_date,
                event_type=EventType.SETTLEMENT,
                amount=total_payoff,
                description=settlement_description,
                strike=position.strike,
                expiration_date=position.expiration_date,
            )

            # Record position event
            self.positions.remove(position)
            total_positions = sum(p.quantity for p in self.positions)
            self.position_events.append(
                PositionEvent(
                    trade_date=trade_date,
                    action=PositionAction.EXPIRED,
                    quantity=position.quantity,
                    strike=position.strike,
                    expiration_date=position.expiration_date,
                    running_positions=total_positions,
                    description="Put expires, settled",
                )
            )

    def reinvest(
        self,
        trade_date: date,
        amount: float,
        price: float,
        description: str = "Reinvest cash into core portfolio",
    ) -> float:
        """Reinvest cash into the core portfolio, buying units at ``price``.

        Parameters
        ----------
        trade_date : date
            Date of reinvestment.
        amount : float
            Amount of cash to reinvest (positive; subtracted from cash).
        price : float
            Price per unit of the core portfolio instrument (positive).
        description : str
            Description of the reinvestment.

        Returns
        -------
        float
            Number of units bought.

        Raises
        ------
        ValueError
            If amount <= 0, price <= 0, or amount exceeds available cash.
        """
        _validate_positive("reinvestment amount", amount)
        _validate_positive("reinvestment price", price)
        if amount > self.cash + 1e-9:
            msg = (
                f"Insufficient cash: reinvestment {amount} exceeds available "
                f"cash {self.cash}"
            )
            raise ValueError(msg)

        units_bought = amount / price
        self.units += units_bought
        self._reinvested_units += units_bought
        self._record_event(
            trade_date=trade_date,
            event_type=EventType.REINVESTMENT,
            amount=-amount,
            description=f"{description} ({units_bought:.6f} units at {price})",
        )
        return units_bought

    def record_transaction_cost(
        self,
        trade_date: date,
        cost: float,
        description: str = "Transaction cost",
    ) -> None:
        """Record a transaction cost.

        Parameters
        ----------
        trade_date : date
            Date of the cost.
        cost : float
            Cost amount (positive value, will be subtracted from cash).
        description : str
            Description of the cost.

        Raises
        ------
        ValueError
            If cost < 0 or the cost exceeds available cash.
        """
        _validate_non_negative("cost", cost)
        if cost > self.cash + 1e-9:
            msg = f"Insufficient cash: cost {cost} exceeds available cash {self.cash}"
            raise ValueError(msg)
        self._record_event(
            trade_date=trade_date,
            event_type=EventType.TRANSACTION_COST,
            amount=-cost,
            description=description,
        )

    def _find_position(
        self,
        strike: float,
        expiration_date: date,
        quantity: int,
    ) -> PutPosition | None:
        """Find a matching position with sufficient quantity."""
        for position in self.positions:
            if (
                position.strike == strike
                and position.expiration_date == expiration_date
                and position.quantity >= quantity
            ):
                return position
        return None

    def get_cash_balance(self) -> float:
        """Get current cash balance."""
        return self.cash

    def get_units(self) -> float:
        """Get current core portfolio unit count."""
        return self.units

    def get_position_count(self) -> int:
        """Get total number of put contracts held."""
        return sum(p.quantity for p in self.positions)

    def validate_cash_conservation(self) -> bool:
        """Validate the full running-cash chain and final balance.

        Cash is only ever mutated inside ``_record_event``, so this checks
        that (a) every event's ``running_cash`` equals the cumulative sum of
        amounts from the initial event, and (b) the final balance matches.
        Independent final-cash equivalence is additionally covered by
        property-based tests in the test suite.

        Returns
        -------
        bool
            True if cash is conserved (no unexplained creation/loss).
        """
        expected_cash = 0.0
        for event in self.cash_events:
            expected_cash += event.amount
            if abs(event.running_cash - expected_cash) > 1e-9:
                return False

        return abs(self.cash - expected_cash) < 1e-9

    def validate_unit_conservation(self) -> bool:
        """Validate that units only change through explicit reinvestments.

        Checks that the current unit count equals initial units plus the
        accumulated reinvestment purchases (tracked independently of the
        unit balance in ``_reinvested_units``).

        Returns
        -------
        bool
            True if units are conserved (no unexplained unit creation/loss).
        """
        expected_units = self.initial_units + self._reinvested_units
        return (
            math.isfinite(self.units)
            and abs(self.units - expected_units) < 1e-9
            and self.units >= 0.0
        )

    def portfolio_value(self, underlying_price: float) -> float:
        """Mark-to-market combined portfolio value.

        Parameters
        ----------
        underlying_price : float
            Current price of the core portfolio instrument.

        Returns
        -------
        float
            Cash + units * underlying_price. Option positions are excluded;
            they settle or are sold at recorded cash flows.
        """
        _validate_non_negative("underlying_price", underlying_price)
        return self.cash + self.units * underlying_price

    def get_final_cash(self) -> float:
        """Get final cash balance after all events."""
        return self.cash
