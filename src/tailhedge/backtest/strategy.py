"""Hedge roll, monetisation, and reinvestment mechanics.

Implements FR-004, FR-019: support daily strategy-directed sell-to-close,
roll, cash release, and core reinvestment without intraday inference.

The strategy module evaluates roll conditions, executes monetisation of
profitable positions, and reinvests released cash into the core portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from tailhedge.backtest.ledger import BacktestLedger


@dataclass(frozen=True)
class RollConfig:
    """Configuration for roll mechanics."""

    roll_dte_threshold: int = 7  # Days to expiry threshold for rolling


@dataclass(frozen=True)
class MonetiseConfig:
    """Configuration for monetisation mechanics."""

    monetise_fraction: float = 0.5  # Fraction of profitable puts to sell


@dataclass(frozen=True)
class ReinvestConfig:
    """Configuration for reinvestment mechanics."""

    reinvest_fraction: float = 1.0  # Fraction of released cash to reinvest


@dataclass(frozen=True)
class StrategyDecision:
    """Decision from the strategy for a single day."""

    trade_date: date
    action: str  # "ROLL", "MONETISE", "NONE"
    roll_from_strike: float | None = None
    roll_from_expiry: date | None = None
    roll_to_strike: float | None = None
    roll_to_expiry: date | None = None
    roll_quantity: int = 0
    monetise_quantity: int = 0
    monetise_price: float = 0.0
    reinvest_amount: float = 0.0
    description: str = ""


def calculate_dte(trade_date: date, expiry_date: date) -> int:
    """Calculate days to expiry.

    Parameters
    ----------
    trade_date : date
        Current trade date.
    expiry_date : date
        Option expiry date.

    Returns
    -------
    int
        Number of days to expiry.
    """
    return (expiry_date - trade_date).days


def evaluate_roll_condition(
    trade_date: date,
    expiry_date: date,
    config: RollConfig,
) -> bool:
    """Evaluate whether a position should be rolled.

    Parameters
    ----------
    trade_date : date
        Current trade date.
    expiry_date : date
        Option expiry date.
    config : RollConfig
        Roll configuration.

    Returns
    -------
    bool
        True if position should be rolled.
    """
    dte = calculate_dte(trade_date, expiry_date)
    return dte <= config.roll_dte_threshold


def evaluate_monetise_condition(
    current_price: float,
    entry_price: float,
) -> bool:
    """Evaluate whether a position is profitable for monetisation.

    Parameters
    ----------
    current_price : float
        Current option price.
    entry_price : float
        Entry premium paid.

    Returns
    -------
    bool
        True if position is profitable (current > entry).
    """
    return current_price > entry_price


def execute_roll(
    ledger: BacktestLedger,
    trade_date: date,
    from_strike: float,
    from_expiry: date,
    to_strike: float,
    to_expiry: date,
    quantity: int,
    sell_price: float,
    buy_price: float,
) -> StrategyDecision:
    """Execute a roll from one expiry to another.

    Parameters
    ----------
    ledger : BacktestLedger
        The accounting ledger.
    trade_date : date
        Date of the roll.
    from_strike : float
        Strike of the position being closed.
    from_expiry : date
        Expiry of the position being closed.
    to_strike : float
        Strike of the new position.
    to_expiry : date
        Expiry of the new position.
    quantity : int
        Number of contracts to roll.
    sell_price : float
        Price to sell the old position.
    buy_price : float
        Price to buy the new position.

    Returns
    -------
    StrategyDecision
        Decision record for the roll.
    """
    # Sell to close old position
    ledger.sell_to_close(
        trade_date=trade_date,
        strike=from_strike,
        expiration_date=from_expiry,
        quantity=quantity,
        price=sell_price,
    )

    # Buy new position
    ledger.buy_put(
        trade_date=trade_date,
        strike=to_strike,
        expiration_date=to_expiry,
        quantity=quantity,
        premium=buy_price,
    )

    return StrategyDecision(
        trade_date=trade_date,
        action="ROLL",
        roll_from_strike=from_strike,
        roll_from_expiry=from_expiry,
        roll_to_strike=to_strike,
        roll_to_expiry=to_expiry,
        roll_quantity=quantity,
        description=(
            f"Roll {quantity} put(s) from {from_strike}/{from_expiry} "
            f"to {to_strike}/{to_expiry}"
        ),
    )


def execute_monetise(
    ledger: BacktestLedger,
    trade_date: date,
    strike: float,
    expiry: date,
    quantity: int,
    price: float,
    reinvest: bool = False,
    reinvest_price: float = 0.0,
) -> StrategyDecision:
    """Execute monetisation of profitable puts.

    Parameters
    ----------
    ledger : BacktestLedger
        The accounting ledger.
    trade_date : date
        Date of monetisation.
    strike : float
        Strike of the position being monetised.
    expiry : date
        Expiry of the position being monetised.
    quantity : int
        Number of contracts to sell.
    price : float
        Sell price per contract.
    reinvest : bool
        Whether to reinvest proceeds.
    reinvest_price : float
        Price of the core portfolio for reinvestment.

    Returns
    -------
    StrategyDecision
        Decision record for the monetisation.
    """
    # Sell to close position
    ledger.sell_to_close(
        trade_date=trade_date,
        strike=strike,
        expiration_date=expiry,
        quantity=quantity,
        price=price,
    )

    proceeds = price * quantity * ledger.multiplier
    reinvest_amount = 0.0

    # Reinvest if configured
    if reinvest and reinvest_price > 0:
        reinvest_amount = proceeds
        ledger.reinvest(
            trade_date=trade_date,
            amount=reinvest_amount,
            description=f"Reinvest monetised proceeds at price {reinvest_price}",
        )

    return StrategyDecision(
        trade_date=trade_date,
        action="MONETISE",
        monetise_quantity=quantity,
        monetise_price=price,
        reinvest_amount=reinvest_amount,
        description=(
            f"Sell {quantity} put(s) at {price}"
            + (f" and reinvest {reinvest_amount}" if reinvest else "")
        ),
    )


def evaluate_daily_strategy(
    trade_date: date,
    ledger: BacktestLedger,
    roll_config: RollConfig,
) -> list[StrategyDecision]:
    """Evaluate daily strategy decisions.

    Parameters
    ----------
    trade_date : date
        Current trade date.
    ledger : BacktestLedger
        The accounting ledger with current positions.
    roll_config : RollConfig
        Roll configuration.

    Returns
    -------
    list[StrategyDecision]
        List of decisions for the day.
    """
    decisions: list[StrategyDecision] = []

    # Check for roll conditions
    for position in list(ledger.positions):
        if evaluate_roll_condition(trade_date, position.expiration_date, roll_config):
            # Mark for roll (actual execution depends on strategy)
            decisions.append(
                StrategyDecision(
                    trade_date=trade_date,
                    action="ROLL",
                    roll_from_strike=position.strike,
                    roll_from_expiry=position.expiration_date,
                    roll_quantity=position.quantity,
                    description=(
                        f"Position {position.strike}/{position.expiration_date} "
                        f"eligible for roll (DTE={calculate_dte(trade_date, position.expiration_date)})"
                    ),
                )
            )

    return decisions
