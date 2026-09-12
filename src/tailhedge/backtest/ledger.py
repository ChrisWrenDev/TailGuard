"""Backtest accounting ledger.

Implements FR-004: deterministic backtest engine accounting.
Tracks core portfolio units/cash, long-put positions, expiry settlement,
premium/cost flows, and explicit currencies.

The ledger ensures cash reconciliation at every simulated step and prevents
unexplained cash creation or loss.
"""

from __future__ import annotations

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
    """A single event in the cash ledger."""

    trade_date: date
    event_type: EventType
    amount: float
    running_cash: float
    description: str


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


@dataclass
class BacktestLedger:
    """Accounting ledger for backtest simulation.

    Tracks cash balance, positions, and all events for reconciliation.
    Ensures no unexplained cash creation or loss.
    """

    initial_cash: float
    currency: str = "USD"
    multiplier: float = 100.0  # XSP/SPX options multiplier

    # State
    cash: float = field(init=False)
    positions: list[PutPosition] = field(default_factory=list)
    cash_events: list[LedgerEvent] = field(default_factory=list)
    position_events: list[PositionEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize cash with initial balance."""
        self.cash = 0.0
        self._record_event(
            trade_date=date(1970, 1, 1),  # Placeholder for initial
            event_type=EventType.INITIAL,
            amount=self.initial_cash,
            description="Initial portfolio cash",
        )

    def _record_event(
        self,
        trade_date: date,
        event_type: EventType,
        amount: float,
        description: str,
    ) -> None:
        """Record a cash event and update running balance."""
        self.cash += amount
        event = LedgerEvent(
            trade_date=trade_date,
            event_type=event_type,
            amount=amount,
            running_cash=self.cash,
            description=description,
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
        """Buy a long put position.

        Parameters
        ----------
        trade_date : date
            Date of the trade.
        strike : float
            Strike price of the put.
        expiration_date : date
            Expiration date of the put.
        quantity : int
            Number of contracts to buy.
        premium : float
            Premium per unit (not multiplied by multiplier).
        """
        cost = premium * quantity * self.multiplier

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
        """Sell to close a long put position.

        Parameters
        ----------
        trade_date : date
            Date of the trade.
        strike : float
            Strike price of the put.
        expiration_date : date
            Expiration date of the put.
        quantity : int
            Number of contracts to sell.
        price : float
            Sell price per unit (not multiplied by multiplier).
        """
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
        """Settle all expired put positions.

        Parameters
        ----------
        trade_date : date
            Date of settlement.
        underlying_price : float
            Price of the underlying at expiry.
        """
        expired = [p for p in self.positions if p.expiration_date <= trade_date]

        for position in expired:
            # Calculate payoff: max(0, strike - underlying)
            payoff_per_unit = max(0.0, position.strike - underlying_price)
            total_payoff = payoff_per_unit * position.quantity * self.multiplier

            # Record cash event
            self._record_event(
                trade_date=trade_date,
                event_type=EventType.SETTLEMENT,
                amount=total_payoff,
                description=(
                    f"Put expires ITM, cash settlement: "
                    f"strike={position.strike}, underlying={underlying_price}"
                ),
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
        description: str = "Reinvest cash into core portfolio",
    ) -> None:
        """Reinvest cash into the core portfolio.

        Parameters
        ----------
        trade_date : date
            Date of reinvestment.
        amount : float
            Amount to reinvest (positive value, will be subtracted from cash).
        description : str
            Description of the reinvestment.
        """
        self._record_event(
            trade_date=trade_date,
            event_type=EventType.REINVESTMENT,
            amount=-amount,
            description=description,
        )

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
        """
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

    def get_position_count(self) -> int:
        """Get total number of put contracts held."""
        return sum(p.quantity for p in self.positions)

    def validate_cash_conservation(self) -> bool:
        """Validate that cash changes are only from explicit events.

        Returns
        -------
        bool
            True if cash is conserved (no unexplained creation/loss).
        """
        expected_cash = self.initial_cash
        for event in self.cash_events[1:]:  # Skip initial event
            expected_cash += event.amount

        return abs(self.cash - expected_cash) < 1e-10

    def get_final_cash(self) -> float:
        """Get final cash balance after all events."""
        return self.cash
