"""Historical execution-cost/fill model.

Implements FR-004, FR-011: bid/ask-based base and stress fill models,
quote tradability rules, and commissions hook.

The fill model validates quotes before calculating fill prices and never
silently midpoint-fills invalid/untradable quotes.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class Quote:
    """A market quote for an option."""

    trade_date: date
    snapshot_ts_utc: datetime
    strike: float
    bid: float
    ask: float
    underlying_price: float


@dataclass(frozen=True)
class FillConfig:
    """Configuration for the fill model."""

    max_relative_spread: float = 0.20  # 20% of mid price
    max_quote_age_seconds: int = 300  # 5 minutes
    base_fill_spread_fraction: float = 0.25  # 25% of spread for base case
    stress_fill_spread_fraction: float = 0.50  # 50% of spread for stress case
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
    """Result of stress fill calculations."""

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

    # Check staleness
    age_seconds = (current_time - quote.snapshot_ts_utc).total_seconds()
    if age_seconds > config.max_quote_age_seconds:
        return QuoteTradability.STALE

    return QuoteTradability.TRADABLE


def calculate_fill_price(
    quote: Quote,
    side: FillSide,
    spread_fraction: float,
    config: FillConfig,
) -> float:
    """Calculate fill price based on bid/ask and spread fraction.

    For BUY: fill = mid + spread_fraction * spread
    For SELL: fill = mid - spread_fraction * spread

    Parameters
    ----------
    quote : Quote
        The quote to use for calculation.
    side : FillSide
        BUY or SELL.
    spread_fraction : float
        Fraction of spread to use (0.0 = midpoint, 1.0 = full ask/bid).
    config : FillConfig
        Fill model configuration for tick rounding.

    Returns
    -------
    float
        Calculated fill price rounded to tick size.
    """
    mid = (quote.bid + quote.ask) / 2
    spread = quote.ask - quote.bid

    if side == FillSide.BUY:
        raw_price = mid + spread_fraction * (spread / 2)
    else:
        raw_price = mid - spread_fraction * (spread / 2)

    # Round to tick size
    return round(raw_price / config.tick_size) * config.tick_size


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
    flat_commission = quantity * config.commission_per_contract
    percentage_commission = quantity * fill_price * config.commission_rate
    return flat_commission + percentage_commission


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
    tradability = validate_quote_tradability(quote, current_time, config)

    if tradability != QuoteTradability.TRADABLE:
        return FillResult(
            fill_price=0.0,
            fill_side=side,
            spread_fraction=0.0,
            commission=0.0,
            is_tradable=False,
            tradability=tradability,
            rejection_reason=f"Quote not tradable: {tradability.value}",
        )

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

    Mandatory robustness cases:
    - Base case: mid + 25% spread
    - Midpoint: diagnostic/optimistic
    - 50% spread: stress case
    - Full spread: worst case

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
    """Calculate a fill with a specific spread fraction.

    Parameters
    ----------
    quote : Quote
        The quote to use for calculation.
    side : FillSide
        BUY or SELL.
    spread_fraction : float
        Fraction of spread to use.
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
    tradability = validate_quote_tradability(quote, current_time, config)

    if tradability != QuoteTradability.TRADABLE:
        return FillResult(
            fill_price=0.0,
            fill_side=side,
            spread_fraction=spread_fraction,
            commission=0.0,
            is_tradable=False,
            tradability=tradability,
            rejection_reason=f"Quote not tradable: {tradability.value}",
        )

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
