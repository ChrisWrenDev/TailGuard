"""Historical execution-cost/fill model.

Implements FR-004, FR-011: bid/ask-based base and stress fill models,
quote tradability rules, and commissions hook.

The fill model validates quotes before calculating fill prices and never
silently midpoint-fills invalid/untradable quotes.

Spread-fraction convention (matches TECHNICAL_ARCHITECTURE.md §9 and FR-017):
the fraction applies to the *full* quoted spread, so a base fill of 25%
means ``mid + 0.25 * (ask - bid)`` for buys and ``mid - 0.25 * (ask - bid)``
for sells.  A fraction of 1.0 fills at the ask (buy) or bid (sell) and a
fraction of 0.0 fills at the midpoint (diagnostic only).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime


class FillSide(StrEnum):
    """Side of the fill."""

    BUY = "BUY"
    SELL = "SELL"


class QuoteTradability(StrEnum):
    """Quote tradability status."""

    TRADABLE = "TRADABLE"
    WIDE_SPREAD = "WIDE_SPREAD"
    STALE = "STALE"
    ZERO_BID = "ZERO_BID"
    CROSSED = "CROSSED"
    NEGATIVE = "NEGATIVE"
    MISSING = "MISSING"
    TIMESTAMP_IN_FUTURE = "TIMESTAMP_IN_FUTURE"


@dataclass(frozen=True)
class Quote:
    """A market quote for an option."""

    trade_date: date
    snapshot_ts_utc: datetime
    strike: float
    expiration_date: date
    bid: float
    ask: float
    underlying_price: float


@dataclass(frozen=True)
class FillConfig:
    """Configuration for the fill model.

    ``base_fill_spread_fraction`` and ``stress_fill_spread_fraction`` are
    fractions of the full quoted spread (0.25 = 25% of ask-bid), matching the
    documented execution-cost convention.
    """

    max_relative_spread: float = 0.20  # 20% of mid price
    max_quote_age_seconds: int = 300  # 5 minutes
    base_fill_spread_fraction: float = 0.25  # 25% of the full spread
    stress_fill_spread_fraction: float = 0.50  # 50% of the full spread
    commission_per_contract: float = 0.65  # USD per contract
    commission_rate: float = 0.0  # Percentage of trade value (0 = flat rate)
    tick_size: float = 0.05  # Minimum price increment


@dataclass(frozen=True)
class FillResult:
    """Result of a fill calculation."""

    fill_price: float
    fill_side: FillSide
    spread_fraction: float
    commission: float
    is_tradable: bool
    tradability: QuoteTradability
    rejection_reason: str | None = None


@dataclass(frozen=True)
class StressFillResult:
    """Result of stress fill calculations.

    Cases are ordered from most to least conservative:
    full spread (worst) >= 50% spread (stress) >= base (25%) >= midpoint
    (diagnostic/optimistic only, never used for accounting).
    """

    base_fill: FillResult
    midpoint_fill: FillResult
    stress_50pct_fill: FillResult
    full_spread_fill: FillResult


def validate_quote_tradability(
    quote: Quote,
    current_time: datetime,
    config: FillConfig,
) -> QuoteTradability:
    """Validate whether a quote is tradable.

    Parameters
    ----------
    quote : Quote
        The quote to validate.
    current_time : datetime
        Current timestamp for staleness check.
    config : FillConfig
        Fill model configuration.

    Returns
    -------
    QuoteTradability
        Tradability status of the quote.
    """
    # Check for negative prices
    if quote.bid < 0 or quote.ask < 0:
        return QuoteTradability.NEGATIVE

    # Check for crossed quotes (bid > ask)
    if quote.bid > quote.ask:
        return QuoteTradability.CROSSED

    # Check for zero bid (untradeable)
    if quote.bid == 0 and quote.ask == 0:
        return QuoteTradability.ZERO_BID

    # Check spread
    mid = (quote.bid + quote.ask) / 2
    if mid > 0:
        spread = quote.ask - quote.bid
        relative_spread = spread / mid
        if relative_spread > config.max_relative_spread:
            return QuoteTradability.WIDE_SPREAD

    # Check staleness (reject future timestamps too: a quote dated after
    # "now" is suspect data, not a fresh quote)
    age_seconds = (current_time - quote.snapshot_ts_utc).total_seconds()
    if age_seconds < 0:
        return QuoteTradability.TIMESTAMP_IN_FUTURE
    if age_seconds > config.max_quote_age_seconds:
        return QuoteTradability.STALE

    return QuoteTradability.TRADABLE


def _validate_quantity(quantity: int) -> None:
    """Raise ValueError if quantity is not a positive contract count."""
    if quantity <= 0:
        msg = f"quantity must be a positive number of contracts, got {quantity}"
        raise ValueError(msg)


def _round_to_tick(
    price: float, side: FillSide, bid: float, ask: float, tick: float
) -> float:
    """Round a fill price to the tick grid and clamp inside the quoted band.

    The clamp guarantees the fill never exceeds the ask on a BUY or falls
    below the bid on a SELL (consistent with the FR-017 limit-price cap).
    """
    rounded = round(price / tick) * tick
    if side == FillSide.BUY:
        return min(rounded, ask)
    return max(rounded, bid)


def calculate_fill_price(
    quote: Quote,
    side: FillSide,
    spread_fraction: float,
    config: FillConfig,
) -> float:
    """Calculate fill price based on bid/ask and spread fraction.

    The fraction applies to the full quoted spread:
    ``BUY: mid + spread_fraction * (ask - bid)`` and
    ``SELL: mid - spread_fraction * (ask - bid)``.

    Parameters
    ----------
    quote : Quote
        The quote to use for calculation.
    side : FillSide
        BUY or SELL.
    spread_fraction : float
        Fraction of the full spread (0.0 = midpoint, 1.0 = full ask/bid).
    config : FillConfig
        Fill model configuration for tick rounding.

    Returns
    -------
    float
        Calculated fill price rounded to tick size and clamped inside
        the quoted band.
    """
    mid = (quote.bid + quote.ask) / 2
    spread = quote.ask - quote.bid

    if side == FillSide.BUY:
        raw_price = mid + spread_fraction * spread
    else:
        raw_price = mid - spread_fraction * spread

    return _round_to_tick(raw_price, side, quote.bid, quote.ask, config.tick_size)


def calculate_commission(
    quantity: int,
    fill_price: float,
    config: FillConfig,
) -> float:
    """Calculate commission for a trade.

    Parameters
    ----------
    quantity : int
        Number of contracts.
    fill_price : float
        Fill price per contract.
    config : FillConfig
        Commission configuration.

    Returns
    -------
    float
        Total commission.
    """
    _validate_quantity(quantity)
    if fill_price < 0 or not math.isfinite(fill_price):
        msg = f"fill_price must be a finite non-negative number, got {fill_price}"
        raise ValueError(msg)
    flat_commission = quantity * config.commission_per_contract
    percentage_commission = quantity * fill_price * config.commission_rate
    return flat_commission + percentage_commission


def _untradable_result(
    side: FillSide,
    spread_fraction: float,
    tradability: QuoteTradability,
) -> FillResult:
    """Build the no-fill result for an untradable quote."""
    return FillResult(
        fill_price=0.0,
        fill_side=side,
        spread_fraction=spread_fraction,
        commission=0.0,
        is_tradable=False,
        tradability=tradability,
        rejection_reason=f"Quote not tradable: {tradability.value}",
    )


def calculate_fill(
    quote: Quote,
    side: FillSide,
    quantity: int,
    current_time: datetime,
    config: FillConfig,
) -> FillResult:
    """Calculate a fill with tradability validation.

    Parameters
    ----------
    quote : Quote
        The quote to use for calculation.
    side : FillSide
        BUY or SELL.
    quantity : int
        Number of contracts.
    current_time : datetime
        Current timestamp for staleness check.
    config : FillConfig
        Fill model configuration.

    Returns
    -------
    FillResult
        Fill result with price, commission, and tradability status.
    """
    _validate_quantity(quantity)
    tradability = validate_quote_tradability(quote, current_time, config)

    if tradability != QuoteTradability.TRADABLE:
        return _untradable_result(side, config.base_fill_spread_fraction, tradability)

    fill_price = calculate_fill_price(
        quote, side, config.base_fill_spread_fraction, config
    )
    commission = calculate_commission(quantity, fill_price, config)

    return FillResult(
        fill_price=fill_price,
        fill_side=side,
        spread_fraction=config.base_fill_spread_fraction,
        commission=commission,
        is_tradable=True,
        tradability=tradability,
    )


def calculate_stress_fills(
    quote: Quote,
    side: FillSide,
    quantity: int,
    current_time: datetime,
    config: FillConfig,
) -> StressFillResult:
    """Calculate stress fill scenarios.

    Mandatory robustness cases (fractions of the full spread):
    - Base case: mid + 25% of spread
    - Midpoint: diagnostic/optimistic (never used for accounting)
    - 50% of spread: stress case
    - Full ask/bid: worst case

    Parameters
    ----------
    quote : Quote
        The quote to use for calculation.
    side : FillSide
        BUY or SELL.
    quantity : int
        Number of contracts.
    current_time : datetime
        Current timestamp for staleness check.
    config : FillConfig
        Fill model configuration.

    Returns
    -------
    StressFillResult
        All stress fill scenarios.
    """
    base_fill = calculate_fill(quote, side, quantity, current_time, config)

    midpoint_fill = calculate_fill_with_fraction(
        quote, side, 0.0, quantity, current_time, config
    )
    stress_50pct_fill = calculate_fill_with_fraction(
        quote, side, config.stress_fill_spread_fraction, quantity, current_time, config
    )
    full_spread_fill = calculate_fill_with_fraction(
        quote, side, 1.0, quantity, current_time, config
    )

    return StressFillResult(
        base_fill=base_fill,
        midpoint_fill=midpoint_fill,
        stress_50pct_fill=stress_50pct_fill,
        full_spread_fill=full_spread_fill,
    )


def calculate_fill_with_fraction(
    quote: Quote,
    side: FillSide,
    spread_fraction: float,
    quantity: int,
    current_time: datetime,
    config: FillConfig,
) -> FillResult:
    """Calculate a fill with a specific spread fraction (of the full spread).

    Parameters
    ----------
    quote : Quote
        The quote to use for calculation.
    side : FillSide
        BUY or SELL.
    spread_fraction : float
        Fraction of the full spread (0.0 = midpoint, 1.0 = full ask/bid).
    quantity : int
        Number of contracts.
    current_time : datetime
        Current timestamp for staleness check.
    config : FillConfig
        Fill model configuration.

    Returns
    -------
    FillResult
        Fill result with price, commission, and tradability status.
    """
    _validate_quantity(quantity)
    tradability = validate_quote_tradability(quote, current_time, config)

    if tradability != QuoteTradability.TRADABLE:
        return _untradable_result(side, spread_fraction, tradability)

    fill_price = calculate_fill_price(quote, side, spread_fraction, config)
    commission = calculate_commission(quantity, fill_price, config)

    return FillResult(
        fill_price=fill_price,
        fill_side=side,
        spread_fraction=spread_fraction,
        commission=commission,
        is_tradable=True,
        tradability=tradability,
    )
