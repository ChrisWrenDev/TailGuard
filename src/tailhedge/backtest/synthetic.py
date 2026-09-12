"""Deterministic synthetic market dataset for engine demonstration runs.

Generates a reproducible multi-month synthetic series (seeded random walk
with a fixed crash episode) plus option quotes — no licensed data, no
pretence of being observed historical quotes. Used by the research UI's
synthetic backtest and the T-006 shared-engine baseline tests.

Quote model (simple, monotone, deterministic):
- put premium = intrinsic (max(0, strike - spot)) + time value
  (spot * 0.4% * sqrt(max(dte, 1) / 30))
- spread = max(0.05, 2% of premium); bid/ask straddle the premium
- snapshot timestamp: 21:00 UTC (4:00 pm America/New_York) per trade date
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from tailhedge.backtest.fill_model import Quote


@dataclass(frozen=True)
class SyntheticDataset:
    """A generated synthetic market dataset."""

    underlying_prices: dict[date, float]
    quotes_by_day: dict[date, list[Quote]]
    first_date: date
    last_date: date
    initial_price: float
    crash_date: date | None
    metadata: dict[str, object] = field(default_factory=dict)


def _next_trading_day(d: date) -> date:
    """Advance to the next weekday (Mon-Fri)."""
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _snapshot_ts(trade_date: date) -> datetime:
    """Snapshot timestamp: 21:00 UTC per trade date."""
    return datetime(
        trade_date.year, trade_date.month, trade_date.day, 21, 0, tzinfo=UTC
    )


def generate_synthetic_dataset(
    *,
    start_date: date,
    trading_days: int,
    seed: int = 20260101,
    initial_price: float = 500.0,
    daily_drift: float = 0.0002,
    daily_vol: float = 0.008,
    crash_start_index: int | None = None,
    crash_daily_return: float = -0.035,
    crash_days: int = 4,
    expiry_interval_days: int = 63,
    option_moneyness: float = 0.95,
    quote_moneyness: float | None = None,
) -> SyntheticDataset:
    """Generate a deterministic synthetic underlying + option quote series.

    Parameters
    ----------
    start_date : date
        First trading date.
    trading_days : int
        Number of trading days to generate.
    seed : int
        RNG seed (determinism contract).
    initial_price, daily_drift, daily_vol :
        Random-walk parameters for underlying closes.
    crash_start_index, crash_daily_return, crash_days :
        Fixed crash episode parameters (independent of the RNG draws).
    expiry_interval_days :
        New contract listed every N trading days, expiring N trading days
        later (approximately quarterly for 63).
    option_moneyness :
        Strike moneyness of the listed put contract (0.95 = 5% OTM).
    quote_moneyness :
        Deprecated alias for ``option_moneyness``.

    Returns
    -------
    SyntheticDataset
        Deterministic synthetic dataset with per-day underlying closes and
        one quoted contract per day.
    """
    if quote_moneyness is not None:
        option_moneyness = quote_moneyness

    rng = random.Random(seed)

    dates: list[date] = []
    d = start_date
    for _ in range(trading_days):
        dates.append(d)
        d = _next_trading_day(d)

    # Underlying path: random walk + fixed crash episode.
    closes: list[float] = []
    price = initial_price
    crash_end = (
        (crash_start_index + crash_days) if crash_start_index is not None else -1
    )
    for i in range(trading_days):
        if crash_start_index is not None and crash_start_index <= i < crash_end:
            price *= 1 + crash_daily_return
        else:
            ret = daily_drift + daily_vol * rng.gauss(0.0, 1.0)
            price *= 1 + ret
        closes.append(price)

    underlying_prices = {dates[i]: closes[i] for i in range(trading_days)}

    # Contracts: one listed at a time, rolling every expiry_interval_days.
    # Expiries land on trading-day indexes so settlement data always exists.
    quotes_by_day: dict[date, list[Quote]] = {dt: [] for dt in dates}

    for start_idx in range(0, trading_days, expiry_interval_days):
        expiry_idx = min(start_idx + expiry_interval_days - 1, trading_days - 1)
        listing_idx = max(start_idx - 5, 0)  # listed a few days before period starts
        strike = _round_strike(option_moneyness * closes[listing_idx])

        for i in range(listing_idx, min(expiry_idx + 1, trading_days)):
            if dates[i] >= dates[expiry_idx]:
                break  # no quotes on/after expiry day
            trade_date = dates[i]
            spot = closes[i]
            dte = (dates[expiry_idx] - trade_date).days
            bid, ask = _option_quote(strike, spot, dte)
            quotes_by_day[trade_date].append(
                Quote(
                    trade_date=trade_date,
                    snapshot_ts_utc=_snapshot_ts(trade_date),
                    strike=strike,
                    expiration_date=dates[expiry_idx],
                    bid=bid,
                    ask=ask,
                    underlying_price=spot,
                )
            )

    crash_date = dates[crash_start_index] if crash_start_index is not None else None

    return SyntheticDataset(
        underlying_prices=underlying_prices,
        quotes_by_day=quotes_by_day,
        first_date=dates[0],
        last_date=dates[-1],
        initial_price=initial_price,
        crash_date=crash_date,
        metadata={
            "seed": seed,
            "trading_days": trading_days,
            "daily_drift": daily_drift,
            "daily_vol": daily_vol,
            "crash_start_index": crash_start_index,
            "crash_daily_return": crash_daily_return,
            "expiry_interval_days": expiry_interval_days,
            "option_moneyness": option_moneyness,
            "generator": "tailhedge.backtest.synthetic.generate_synthetic_dataset",
        },
    )


def _round_strike(value: float) -> float:
    """Round a strike to the nearest 5-point increment (XSP convention)."""
    return round(value / 5.0) * 5.0


def _option_quote(strike: float, spot: float, dte: int) -> tuple[float, float]:
    """Simple deterministic put quote: intrinsic + time value, 2% spread."""
    intrinsic = max(0.0, strike - spot)
    time_value = spot * 0.004 * math.sqrt(max(dte, 1) / 30.0)
    premium = intrinsic + time_value
    spread = max(0.05, 0.02 * premium)
    bid = max(0.0, premium - spread / 2)
    ask = premium + spread / 2
    return bid, ask
