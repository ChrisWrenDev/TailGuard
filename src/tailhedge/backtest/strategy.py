"""Hedge roll, monetisation, and reinvestment mechanics.

Implements FR-004, FR-019: support daily strategy-directed sell-to-close,
roll, cash release, and core reinvestment without intraday inference.

All simulated trades go through the bid/ask fill model: a roll or
monetisation leg is only executed when its quote is tradable; otherwise a
no-action decision is returned with the rejection reason (missing
executable quote means no simulated trade). Commissions are charged via
the ledger's transaction-cost events.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tailhedge.backtest.fill_model import (
    FillConfig,
    FillResult,
    FillSide,
    calculate_fill,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from tailhedge.backtest.fill_model import Quote
    from tailhedge.backtest.ledger import BacktestLedger


@dataclass(frozen=True)
class RollConfig:
    """Configuration for roll mechanics.

    ``roll_dte_threshold`` is in calendar days: a position is roll-eligible
    when ``(expiry_date - trade_date).days <= threshold``.
    """

    roll_dte_threshold: int = 7  # Calendar days to expiry threshold


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
    reinvest_units: float = 0.0
    description: str = ""


def calculate_dte(trade_date: date, expiry_date: date) -> int:
    """Calculate calendar days to expiry.

    Parameters
    ----------
    trade_date : date
        Current trade date.
    expiry_date : date
        Option expiry date.

    Returns
    -------
    int
        Number of calendar days to expiry (0 on the expiry date).
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
        Roll configuration (calendar-day threshold).

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
    current_time: datetime,
    fill_config: FillConfig,
    from_strike: float,
    from_expiry: date,
    to_strike: float,
    to_expiry: date,
    quantity: int,
    sell_quote: Quote,
    buy_quote: Quote,
) -> StrategyDecision:
    """Execute a roll from one expiry to another using the fill model.

    Both legs must be tradable at their quotes; otherwise nothing is
    executed and a no-action decision with the rejection reason is
    returned. Sell/buy fill prices and commissions come from the fill
    model (no midpoint fills).

    Parameters
    ----------
    ledger : BacktestLedger
        The accounting ledger.
    trade_date : date
        Date of the roll.
    current_time : datetime
        Timestamp used for quote freshness checks.
    fill_config : FillConfig
        Fill model configuration (spread fractions, commissions).
    from_strike : float
        Strike of the position being closed.
    from_expiry : date
        Expiry of the position being closed.
    to_strike : float
        Strike of the new position.
    to_expiry : date
        Expiry of the new position (must be after ``from_expiry``).
    quantity : int
        Number of contracts to roll.
    sell_quote : Quote
        Quote for the position being closed.
    buy_quote : Quote
        Quote for the new position.

    Returns
    -------
    StrategyDecision
        Decision record for the roll (action "ROLL" or "NONE").
    """
    description = (
        f"Roll {quantity} put(s) from {from_strike}/{from_expiry} "
        f"to {to_strike}/{to_expiry}"
    )

    sell_fill = calculate_fill(
        sell_quote, FillSide.SELL, quantity, current_time, fill_config
    )
    if not sell_fill.is_tradable:
        return _fill_or_skip(sell_fill, "SELL", trade_date, description)

    buy_fill = calculate_fill(
        buy_quote, FillSide.BUY, quantity, current_time, fill_config
    )
    if not buy_fill.is_tradable:
        return _fill_or_skip(buy_fill, "BUY", trade_date, description)

    if to_expiry <= from_expiry:
        msg = (
            f"Roll target expiry ({to_expiry}) must be after the position "
            f"being closed ({from_expiry})"
        )
        raise ValueError(msg)

    ledger.sell_to_close(
        trade_date=trade_date,
        strike=from_strike,
        expiration_date=from_expiry,
        quantity=quantity,
        price=sell_fill.fill_price,
    )
    ledger.record_transaction_cost(
        trade_date=trade_date,
        cost=sell_fill.commission,
        description=f"Commission on sell leg of roll ({quantity} contract(s))",
    )

    ledger.buy_put(
        trade_date=trade_date,
        strike=to_strike,
        expiration_date=to_expiry,
        quantity=quantity,
        premium=buy_fill.fill_price,
    )
    ledger.record_transaction_cost(
        trade_date=trade_date,
        cost=buy_fill.commission,
        description=f"Commission on buy leg of roll ({quantity} contract(s))",
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
            f"{description}: sold at {sell_fill.fill_price}, "
            f"bought at {buy_fill.fill_price}"
        ),
    )


def _fill_or_skip(
    fill: FillResult,
    leg: str,
    trade_date: date,
    description: str,
) -> StrategyDecision:
    """Convert an untradable fill into a no-action decision."""
    return StrategyDecision(
        trade_date=trade_date,
        action="NONE",
        description=(
            f"{description} skipped: {fill.rejection_reason} ({leg} leg not tradable)"
        ),
    )


def execute_monetise(
    ledger: BacktestLedger,
    trade_date: date,
    current_time: datetime,
    fill_config: FillConfig,
    strike: float,
    expiry: date,
    quantity: int,
    sell_quote: Quote,
    reinvest: bool = False,
    reinvest_price: float = 0.0,
    reinvest_fraction: float = 1.0,
) -> StrategyDecision:
    """Execute monetisation of profitable puts using the fill model.

    The sell leg must be tradable at its quote; otherwise nothing is
    executed and a no-action decision with the rejection reason is
    returned. Proceeds are credited at the model fill price (never the
    midpoint) and commissions are charged. When ``reinvest`` is set, a
    ``reinvest_fraction`` of the net proceeds is invested back into the
    core portfolio at ``reinvest_price``, buying recorded units.

    Parameters
    ----------
    ledger : BacktestLedger
        The accounting ledger.
    trade_date : date
        Date of monetisation.
    current_time : datetime
        Timestamp used for quote freshness checks.
    fill_config : FillConfig
        Fill model configuration (spread fractions, commissions).
    strike : float
        Strike of the position being monetised.
    expiry : date
        Expiry of the position being monetised.
    quantity : int
        Number of contracts to sell.
    sell_quote : Quote
        Quote for the position being sold.
    reinvest : bool
        Whether to reinvest proceeds.
    reinvest_price : float
        Price of the core portfolio instrument for reinvestment.
    reinvest_fraction : float
        Fraction of proceeds to reinvest.

    Returns
    -------
    StrategyDecision
        Decision record for the monetisation (action "MONETISE" or "NONE").
    """
    description = f"Monetise {quantity} put(s) strike {strike}/{expiry}"

    sell_fill = calculate_fill(
        sell_quote, FillSide.SELL, quantity, current_time, fill_config
    )
    if not sell_fill.is_tradable:
        return _fill_or_skip(sell_fill, "SELL", trade_date, description)

    ledger.sell_to_close(
        trade_date=trade_date,
        strike=strike,
        expiration_date=expiry,
        quantity=quantity,
        price=sell_fill.fill_price,
    )
    ledger.record_transaction_cost(
        trade_date=trade_date,
        cost=sell_fill.commission,
        description=f"Commission on monetisation sell ({quantity} contract(s))",
    )

    proceeds = sell_fill.fill_price * quantity * ledger.multiplier
    reinvest_amount = 0.0
    reinvest_units = 0.0

    # Reinvest if configured: a fraction of proceeds buys core units at price
    if reinvest and reinvest_price > 0:
        reinvest_amount = proceeds * reinvest_fraction
        if reinvest_amount > 0:
            reinvest_units = ledger.reinvest(
                trade_date=trade_date,
                amount=reinvest_amount,
                price=reinvest_price,
                description=f"Reinvest monetised proceeds at price {reinvest_price}",
            )

    return StrategyDecision(
        trade_date=trade_date,
        action="MONETISE",
        monetise_quantity=quantity,
        monetise_price=sell_fill.fill_price,
        reinvest_amount=reinvest_amount,
        reinvest_units=reinvest_units,
        description=(
            f"Sold {quantity} put(s) at {sell_fill.fill_price}"
            + (
                f", reinvested {reinvest_amount} into {reinvest_units:.6f} units"
                if reinvest_units > 0
                else ""
            )
        ),
    )


def _floor_contracts(quantity: int, fraction: float) -> int:
    """Return the whole-contract count equal to ``quantity * fraction``."""
    if fraction <= 0:
        return 0
    return math.floor(quantity * fraction + 1e-9)


def evaluate_daily_strategy(
    trade_date: date,
    ledger: BacktestLedger,
    roll_config: RollConfig,
    monetise_config: MonetiseConfig,
    current_time: datetime,
    fill_config: FillConfig,
    quotes_by_position: dict[tuple[float, date], Quote],
) -> list[StrategyDecision]:
    """Evaluate daily strategy decisions: roll eligibility and monetisation.

    A position is roll-eligible when its DTE is at or below the configured
    threshold. A position is a monetisation candidate when a tradable quote
    exists whose price exceeds the entry premium; the candidate quantity is
    the whole-contract portion of ``monetise_fraction * quantity``.

    Decisions are markers only; the caller executes via ``execute_roll`` /
    ``execute_monetise`` (which re-validate tradability). Positions with no
    quote in ``quotes_by_position`` produce no decision (fail closed: no
    executable quote means no simulated trade).

    Parameters
    ----------
    trade_date : date
        Current trade date.
    ledger : BacktestLedger
        The accounting ledger with current positions.
    roll_config : RollConfig
        Roll configuration.
    monetise_config : MonetiseConfig
        Monetisation configuration.
    current_time : datetime
        Timestamp used for quote freshness checks.
    fill_config : FillConfig
        Fill model configuration.
    quotes_by_position : dict[tuple[float, date], Quote]
        Current quotes keyed by (strike, expiration_date).

    Returns
    -------
    list[StrategyDecision]
        List of decisions for the day.
    """
    decisions: list[StrategyDecision] = []

    for position in list(ledger.positions):
        quote = quotes_by_position.get((position.strike, position.expiration_date))
        if quote is None:
            continue  # No executable quote -> no simulated trade

        roll_eligible = evaluate_roll_condition(
            trade_date, position.expiration_date, roll_config
        )

        # Monetisation candidate check uses a tradable-quote price probe:
        # the midpoint of a tradable quote is the neutral reference.
        monetise_quantity = _floor_contracts(
            position.quantity, monetise_config.monetise_fraction
        )
        monetise_candidate = False
        if monetise_quantity > 0:
            probe = calculate_fill(quote, FillSide.BUY, 1, current_time, fill_config)
            if probe.is_tradable:
                mid_probe_price = (quote.bid + quote.ask) / 2
                monetise_candidate = evaluate_monetise_condition(
                    mid_probe_price, position.entry_premium
                )

        if roll_eligible or monetise_candidate:
            description = (
                f"Position {position.strike}/{position.expiration_date} "
                f"roll-eligible (DTE={calculate_dte(trade_date, position.expiration_date)})"
                if roll_eligible
                else (
                    f"Position {position.strike}/{position.expiration_date} "
                    f"monetisation candidate (qty={monetise_quantity}, "
                    f"fraction={monetise_config.monetise_fraction})"
                )
            )
            decisions.append(
                StrategyDecision(
                    trade_date=trade_date,
                    action="ROLL" if roll_eligible else "MONETISE",
                    roll_from_strike=position.strike if roll_eligible else None,
                    roll_from_expiry=position.expiration_date
                    if roll_eligible
                    else None,
                    roll_quantity=position.quantity if roll_eligible else 0,
                    monetise_quantity=monetise_quantity if monetise_candidate else 0,
                    description=description,
                )
            )

    return decisions
