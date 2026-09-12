"""Golden synthetic research fixtures for deterministic backtest/security tests.

This module provides non-licensed, hand-crafted fixtures GF-001 through GF-007
that enable deterministic validation of the backtest engine, portfolio mapping,
execution cost model, split/leakage logic, and FX conversion.

Each fixture is documented with hand-calculated expected outputs to verify
correct behaviour.

Design principles:
- All values are hand-calculated and verified against expected outcomes.
- Fixtures use simple, round numbers to make manual verification tractable.
- No licensed vendor data is used; all data is synthetic.
- Fixtures are deterministic and reproducible.
- Expected ledgers use the default fill profile (``GF_FILL_CONFIG``): buys at
  ``mid + 25% of the full spread``, sells at ``mid - 25% of the full spread``,
  and a flat USD 0.65 commission per contract — the same fill model the
  engine applies to every strategy and baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from tailhedge.backtest.fill_model import FillConfig, Quote
from tailhedge.data.canonical_schema import OptionType

# ---------------------------------------------------------------------------
# Shared fill profile used by all fixture expected-value calculations
# ---------------------------------------------------------------------------

GF_FILL_CONFIG = FillConfig()  # base 25% of full spread, 0.65/contract
GF_COMMISSION_PER_CONTRACT = GF_FILL_CONFIG.commission_per_contract
GF_XSP_MULTIPLIER = 100.0

# ---------------------------------------------------------------------------
# Fixture data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionSnapshot:
    """Simplified option snapshot for fixture definition."""

    trade_date: date
    expiration_date: date
    strike: float
    option_type: OptionType
    bid: float
    ask: float
    underlying_price: float
    snapshot_ts_utc: datetime | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    volume: int | None = None
    open_interest: int | None = None


@dataclass(frozen=True)
class UnderlyingSnapshot:
    """Simplified underlying snapshot for fixture definition.

    ``leak_feature`` exists only for the GF-007 leakage trap: it carries a
    future-predictive value that must never be exposed to a strategy via a
    look-ahead-safe slice.
    """

    trade_date: date
    symbol: str
    close: float
    currency: str = "USD"
    leak_feature: float | None = None


@dataclass(frozen=True)
class CashLedgerEntry:
    """Expected cash ledger entry for fixture validation."""

    trade_date: date
    event_type: str  # "PREMIUM", "SETTLEMENT", "MONETISATION", "REINVESTMENT", "TRANSACTION_COST", "INITIAL"
    amount: float
    running_cash: float
    description: str


@dataclass(frozen=True)
class PositionEntry:
    """Expected position entry for fixture validation."""

    trade_date: date
    action: str  # "BUY", "SELL_TO_CLOSE", "EXPIRED", "NONE"
    quantity: int
    strike: float
    expiration_date: date
    running_positions: int
    description: str


@dataclass(frozen=True)
class PortfolioExposure:
    """Expected portfolio exposure for fixture validation."""

    holding_name: str
    beta: float
    market_value: float
    benchmark_equivalent: float
    description: str


# ---------------------------------------------------------------------------
# Look-ahead-safe access helpers (GF-007 data-access boundary)
# ---------------------------------------------------------------------------


def underlying_on_or_before(
    snapshots: list[UnderlyingSnapshot],
    as_of_date: date,
) -> list[UnderlyingSnapshot]:
    """Return underlying rows strictly dated on or before ``as_of_date``.

    This is the fixture-level stand-in for the data-access boundary: any
    consumer (strategy context builder, evaluator) must obtain data through
    an equivalent date-bounded slice so future rows are structurally
    unreachable.
    """
    return [s for s in snapshots if s.trade_date <= as_of_date]


def options_on_or_before(
    snapshots: list[OptionSnapshot],
    as_of_date: date,
) -> list[OptionSnapshot]:
    """Return option rows strictly dated on or before ``as_of_date``."""
    return [s for s in snapshots if s.trade_date <= as_of_date]


# ---------------------------------------------------------------------------
# Conversion helpers for engine runs
# ---------------------------------------------------------------------------


def _default_snapshot_ts(trade_date: date) -> datetime:
    """Default snapshot timestamp: 21:00 UTC (4:00 pm America/New_York)."""
    return datetime(
        trade_date.year, trade_date.month, trade_date.day, 21, 0, tzinfo=UTC
    )


def option_snapshots_to_quotes(
    snapshots: list[OptionSnapshot],
) -> list[Quote]:
    """Convert fixture option snapshots to fill-model quotes."""
    return [
        Quote(
            trade_date=s.trade_date,
            snapshot_ts_utc=s.snapshot_ts_utc or _default_snapshot_ts(s.trade_date),
            strike=s.strike,
            expiration_date=s.expiration_date,
            bid=s.bid,
            ask=s.ask,
            underlying_price=s.underlying_price,
        )
        for s in snapshots
    ]


def underlying_prices_map(snapshots: list[UnderlyingSnapshot]) -> dict[date, float]:
    """Map trade date -> underlying close for engine runs."""
    return {s.trade_date: s.close for s in snapshots}


def quotes_by_day(quotes: list[Quote]) -> dict[date, list[Quote]]:
    """Group quotes by trade date for engine runs."""
    grouped: dict[date, list[Quote]] = {}
    for quote in quotes:
        grouped.setdefault(quote.trade_date, []).append(quote)
    return grouped


# ---------------------------------------------------------------------------
# GF-001 — Simple option payoff
# ---------------------------------------------------------------------------
# Five daily underlying snapshots, one put, known expiration and premium.
# Expected cash ledger hand-calculated with the default fill profile.
#
# Scenario:
# - XSP put, strike 4900, expiring 2025-01-21
# - Underlying closes: 5000, 4980, 4950, 4920, 4800 (Jan 15, 16, 17, 20, 21)
# - Option snapshots on Jan 15-20 (unique trade dates), expiry ITM
#
# Hand calculation (base fill = mid + 25% of full spread; commission 0.65):
# - Jan 15: Buy 1 put. Quote bid=100 ask=105 -> mid=102.50, spread=5.
#   Fill = 102.50 + 0.25*5 = 103.75. Cost = 103.75*100 = 10,375.
#   Commission = 0.65.
# - Jan 16-20: hold.
# - Jan 21 (expiry): payoff = max(0, 4900 - 4800) = 100 -> +10,000.
# - Final cash = 100,000 - 10,375 - 0.65 + 10,000 = 99,624.35.

GF001_NAME = "GF-001: Simple option payoff"
GF001_DESCRIPTION = (
    "Five daily underlying snapshots, one put, known expiration and premium. "
    "Option expires ITM with known payoff."
)

GF001_INITIAL_CASH = 100_000.0
GF001_PUT_STRIKE = 4900.0
GF001_PUT_EXPIRY = date(2025, 1, 21)
GF001_PREMIUM_BID = 100.0
GF001_PREMIUM_ASK = 105.0
GF001_PREMIUM_MIDPOINT = 102.50  # (100 + 105) / 2
GF001_PREMIUM_FILL_BUY = 103.75  # mid + 25% of full spread: 102.50 + 1.25
GF001_CONTRACTS = 1
GF001_XSP_MULTIPLIER = 100.0
GF001_COMMISSION = 0.65
GF001_EXPIRY_SETTLEMENT_PRICE = 4800.0

GF001_UNDERLYING_PRICES = [
    UnderlyingSnapshot(trade_date=date(2025, 1, 15), symbol="XSP", close=5000.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 16), symbol="XSP", close=4980.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 17), symbol="XSP", close=4950.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 20), symbol="XSP", close=4920.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 21), symbol="XSP", close=4800.0),
]

GF001_OPTION_SNAPSHOTS = [
    OptionSnapshot(
        trade_date=date(2025, 1, 15),
        expiration_date=GF001_PUT_EXPIRY,
        strike=GF001_PUT_STRIKE,
        option_type=OptionType.PUT,
        bid=GF001_PREMIUM_BID,
        ask=GF001_PREMIUM_ASK,
        underlying_price=5000.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 16),
        expiration_date=GF001_PUT_EXPIRY,
        strike=GF001_PUT_STRIKE,
        option_type=OptionType.PUT,
        bid=105.0,
        ask=110.0,
        underlying_price=4980.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 17),
        expiration_date=GF001_PUT_EXPIRY,
        strike=GF001_PUT_STRIKE,
        option_type=OptionType.PUT,
        bid=115.0,
        ask=120.0,
        underlying_price=4950.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 20),
        expiration_date=GF001_PUT_EXPIRY,
        strike=GF001_PUT_STRIKE,
        option_type=OptionType.PUT,
        bid=130.0,
        ask=135.0,
        underlying_price=4920.0,
    ),
]

GF001_EXPECTED_CASH_LEDGER = [
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="INITIAL",
        amount=GF001_INITIAL_CASH,
        running_cash=GF001_INITIAL_CASH,
        description="Initial portfolio cash",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="PREMIUM",
        amount=-GF001_PREMIUM_FILL_BUY * GF001_XSP_MULTIPLIER,
        running_cash=GF001_INITIAL_CASH - GF001_PREMIUM_FILL_BUY * GF001_XSP_MULTIPLIER,
        description="Buy 1 XSP put at fill premium",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="TRANSACTION_COST",
        amount=-GF001_COMMISSION,
        running_cash=GF001_INITIAL_CASH
        - GF001_PREMIUM_FILL_BUY * GF001_XSP_MULTIPLIER
        - GF001_COMMISSION,
        description="Commission on buy (1 contract(s))",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 21),
        event_type="SETTLEMENT",
        amount=(GF001_PUT_STRIKE - GF001_EXPIRY_SETTLEMENT_PRICE)
        * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF001_INITIAL_CASH
            - GF001_PREMIUM_FILL_BUY * GF001_XSP_MULTIPLIER
            - GF001_COMMISSION
            + (GF001_PUT_STRIKE - GF001_EXPIRY_SETTLEMENT_PRICE) * GF001_XSP_MULTIPLIER
        ),
        description="Put expires ITM, cash settlement",
    ),
]

GF001_EXPECTED_FINAL_CASH = (
    GF001_INITIAL_CASH
    - GF001_PREMIUM_FILL_BUY * GF001_XSP_MULTIPLIER
    - GF001_COMMISSION
    + (GF001_PUT_STRIKE - GF001_EXPIRY_SETTLEMENT_PRICE) * GF001_XSP_MULTIPLIER
)  # 99,624.35

GF001_EXPECTED_POSITIONS = [
    PositionEntry(
        trade_date=date(2025, 1, 15),
        action="BUY",
        quantity=1,
        strike=GF001_PUT_STRIKE,
        expiration_date=GF001_PUT_EXPIRY,
        running_positions=1,
        description="Buy 1 put contract",
    ),
    PositionEntry(
        trade_date=GF001_PUT_EXPIRY,
        action="EXPIRED",
        quantity=1,
        strike=GF001_PUT_STRIKE,
        expiration_date=GF001_PUT_EXPIRY,
        running_positions=0,
        description="Put expires ITM, settled",
    ),
]


# ---------------------------------------------------------------------------
# GF-002 — Roll case
# ---------------------------------------------------------------------------
# Two expiries; target policy rolls at a known DTE threshold.
#
# Scenario:
# - Policy: roll when DTE <= 4 calendar days
# - Expiry 1: Jan 21, 2025, strike 4900 (bought Jan 15, DTE=6 > 4: not yet
#   roll-eligible; Jan 16 DTE=5 > 4: still not eligible; Jan 17 DTE=4 <= 4:
#   roll trigger)
# - Expiry 2: Feb 21, 2025, strike 4850
#
# Hand calculation (base fill = mid - 25% spread for sells, mid + 25% spread
# for buys; commission 0.65 per leg):
# - Jan 15: Buy 1 put (strike 4900). Quote 100/105 -> fill 103.75.
#   Cost -10,375; commission -0.65.
# - Jan 17: Sell Jan-21 put. Quote 115/120 -> mid 117.50, spread 5,
#   fill = 117.50 - 1.25 = 116.25 -> +11,625; commission -0.65.
# - Jan 17: Buy Feb-21 put. Quote 145/155 -> mid 150, spread 10,
#   fill = 150 + 2.50 = 152.50 -> -15,250; commission -0.65.
# - Final cash = 100,000 - 10,375 - 0.65 + 11,625 - 0.65 - 15,250 - 0.65
#             = 85,998.05.
# - Roll cost (premiums only) = (152.50 - 116.25) * 100 = 3,625.

GF002_NAME = "GF-002: Roll case"
GF002_DESCRIPTION = (
    "Two expiries; target policy rolls at known DTE. "
    "Expected close/buy and spend accounting."
)

GF002_INITIAL_CASH = 100_000.0
GF002_ROLL_DTE_THRESHOLD = 4

GF002_EXPIRY_1 = date(2025, 1, 21)
GF002_EXPIRY_2 = date(2025, 2, 21)
GF002_STRIKE_1 = 4900.0
GF002_STRIKE_2 = 4850.0

GF002_PREMIUM_1_BID = 100.0
GF002_PREMIUM_1_ASK = 105.0
GF002_PREMIUM_1_BUY = 103.75  # mid 102.50 + 25% of spread 5
GF002_PREMIUM_1_SELL_BID = 115.0
GF002_PREMIUM_1_SELL_ASK = 120.0
GF002_PREMIUM_1_SELL = 116.25  # mid 117.50 - 25% of spread
GF002_PREMIUM_2_BID = 145.0
GF002_PREMIUM_2_ASK = 155.0
GF002_PREMIUM_2_BUY = 152.50  # mid 150 + 25% of spread
GF002_COMMISSION = 0.65

GF002_UNDERLYING_PRICES = [
    UnderlyingSnapshot(trade_date=date(2025, 1, 15), symbol="XSP", close=5000.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 16), symbol="XSP", close=4980.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 17), symbol="XSP", close=4950.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 20), symbol="XSP", close=4920.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 21), symbol="XSP", close=4900.0),
]

GF002_OPTION_SNAPSHOTS_EXPIRY_1 = [
    OptionSnapshot(
        trade_date=date(2025, 1, 15),
        expiration_date=GF002_EXPIRY_1,
        strike=GF002_STRIKE_1,
        option_type=OptionType.PUT,
        bid=GF002_PREMIUM_1_BID,
        ask=GF002_PREMIUM_1_ASK,
        underlying_price=5000.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 16),
        expiration_date=GF002_EXPIRY_1,
        strike=GF002_STRIKE_1,
        option_type=OptionType.PUT,
        bid=105.0,
        ask=110.0,
        underlying_price=4980.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 17),
        expiration_date=GF002_EXPIRY_1,
        strike=GF002_STRIKE_1,
        option_type=OptionType.PUT,
        bid=GF002_PREMIUM_1_SELL_BID,
        ask=GF002_PREMIUM_1_SELL_ASK,
        underlying_price=4950.0,
    ),
]

GF002_OPTION_SNAPSHOTS_EXPIRY_2 = [
    OptionSnapshot(
        trade_date=date(2025, 1, 17),
        expiration_date=GF002_EXPIRY_2,
        strike=GF002_STRIKE_2,
        option_type=OptionType.PUT,
        bid=GF002_PREMIUM_2_BID,
        ask=GF002_PREMIUM_2_ASK,
        underlying_price=4950.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 20),
        expiration_date=GF002_EXPIRY_2,
        strike=GF002_STRIKE_2,
        option_type=OptionType.PUT,
        bid=155.0,
        ask=165.0,
        underlying_price=4920.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 21),
        expiration_date=GF002_EXPIRY_2,
        strike=GF002_STRIKE_2,
        option_type=OptionType.PUT,
        bid=160.0,
        ask=170.0,
        underlying_price=4900.0,
    ),
]

GF002_EXPECTED_CASH_LEDGER = [
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="INITIAL",
        amount=GF002_INITIAL_CASH,
        running_cash=GF002_INITIAL_CASH,
        description="Initial portfolio cash",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="PREMIUM",
        amount=-GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER,
        running_cash=GF002_INITIAL_CASH - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER,
        description="Buy Jan 21 put at fill premium",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="TRANSACTION_COST",
        amount=-GF002_COMMISSION,
        running_cash=GF002_INITIAL_CASH
        - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
        - GF002_COMMISSION,
        description="Commission on buy (1 contract(s))",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="MONETISATION",
        amount=GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF002_INITIAL_CASH
            - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
            - GF002_COMMISSION
            + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
        ),
        description="Sell Jan 21 put at fill price (roll close leg)",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="TRANSACTION_COST",
        amount=-GF002_COMMISSION,
        running_cash=(
            GF002_INITIAL_CASH
            - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
            - GF002_COMMISSION
            + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
            - GF002_COMMISSION
        ),
        description="Commission on sell leg of roll (1 contract(s))",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="PREMIUM",
        amount=-GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF002_INITIAL_CASH
            - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
            - 2 * GF002_COMMISSION
            + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
            - GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER
        ),
        description="Buy Feb 21 put at fill premium (roll open leg)",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="TRANSACTION_COST",
        amount=-GF002_COMMISSION,
        running_cash=(
            GF002_INITIAL_CASH
            - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
            - 2 * GF002_COMMISSION
            + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
            - GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER
            - GF002_COMMISSION
        ),
        description="Commission on buy leg of roll (1 contract(s))",
    ),
]

GF002_EXPECTED_ROLL_COST = (
    GF002_PREMIUM_2_BUY - GF002_PREMIUM_1_SELL
) * GF001_XSP_MULTIPLIER  # 3,625 (premiums only)

GF002_EXPECTED_FINAL_CASH = (
    GF002_INITIAL_CASH
    - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
    - 3 * GF002_COMMISSION
    + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
    - GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER
)  # 85,998.05


# ---------------------------------------------------------------------------
# GF-003 — Crash + monetisation
# ---------------------------------------------------------------------------
# Underlying drops sharply; put becomes ITM; policy sells the configured
# fraction and reinvests released cash into core units.
#
# Scenario:
# - Initial portfolio: 200 core units at $500 = $100,000 equity; $100,000
#   cash; total $200,000
# - Hedge: 2 puts at strike 4900, expiry Feb 21 (bought Jan 15)
# - Crash: underlying 5000 -> 4500 by Jan 17
# - Monetisation: sell 50% of the puts (1 contract), reinvest 100% of
#   proceeds into core units at the Jan-17 close of 4500
#
# Hand calculation (base fill = mid +/- 25% of full spread; commission 0.65):
# - Jan 15: Buy 2 puts. Quote 100/105 -> fill 103.75. Cost = 2*10,375 = 20,750;
#   commission = 2*0.65 = 1.30.
# - Jan 17: Sell 1 put. Quote 395/405 -> mid 400, spread 10,
#   fill = 400 - 2.50 = 397.50 -> proceeds = 39,750; commission 0.65.
# - Reinvest 100% of proceeds: 39,750 / 4,500 = 8.833333... units bought.
# - Units after: 200 + 8.833333... = 208.833333...
# - Final cash = 100,000 - 20,750 - 1.30 + 39,750 - 0.65 - 39,750 = 79,248.05.
# - Combined value at Jan-17 close = cash + units*4500
#   = 79,248.05 + (200 + 39,750/4500) * 4500
#   = 79,248.05 + 939,750.00 = 1,018,998.05.

GF003_NAME = "GF-003: Crash + monetisation"
GF003_DESCRIPTION = (
    "Underlying drops sharply; put becomes ITM; policy sells the configured "
    "fraction and reinvests cash. Expected combined-portfolio units/value known."
)

GF003_INITIAL_CASH = 100_000.0
GF003_INITIAL_UNITS = 200.0
GF003_INITIAL_PRICE = 500.0  # Core instrument price on day 1
GF003_TOTAL_PORTFOLIO = GF003_INITIAL_CASH + GF003_INITIAL_UNITS * GF003_INITIAL_PRICE

GF003_PUT_STRIKE = 4900.0
GF003_PUT_EXPIRY = date(2025, 2, 21)
GF003_PUT_QUANTITY = 2
GF003_PREMIUM_BID = 100.0
GF003_PREMIUM_ASK = 105.0
GF003_PREMIUM_BUY = 103.75  # mid 102.50 + 25% of spread
GF003_MONETISE_FRACTION = 0.5  # Sell 50% of profitable puts
GF003_MONETISE_BID = 395.0
GF003_MONETISE_ASK = 405.0
GF003_MONETISE_MIDPOINT = 400.0  # (395 + 405) / 2
GF003_MONETISE_FILL_SELL = 397.50  # mid 400 - 25% of spread 10
GF003_REINVEST_FRACTION = 1.0
GF003_REINVEST_PRICE = 4500.0  # Underlying close on monetisation day
GF003_COMMISSION = 0.65

GF003_UNDERLYING_PRICES = [
    UnderlyingSnapshot(trade_date=date(2025, 1, 15), symbol="XSP", close=5000.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 16), symbol="XSP", close=4800.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 17), symbol="XSP", close=4500.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 20), symbol="XSP", close=4600.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 21), symbol="XSP", close=4700.0),
]

GF003_OPTION_SNAPSHOTS = [
    OptionSnapshot(
        trade_date=date(2025, 1, 15),
        expiration_date=GF003_PUT_EXPIRY,
        strike=GF003_PUT_STRIKE,
        option_type=OptionType.PUT,
        bid=GF003_PREMIUM_BID,
        ask=GF003_PREMIUM_ASK,
        underlying_price=5000.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 17),
        expiration_date=GF003_PUT_EXPIRY,
        strike=GF003_PUT_STRIKE,
        option_type=OptionType.PUT,
        bid=GF003_MONETISE_BID,
        ask=GF003_MONETISE_ASK,
        underlying_price=4500.0,
    ),
]

GF003_EXPECTED_CASH_LEDGER = [
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="INITIAL",
        amount=GF003_INITIAL_CASH,
        running_cash=GF003_INITIAL_CASH,
        description="Initial portfolio cash",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="PREMIUM",
        amount=-GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER,
        running_cash=GF003_INITIAL_CASH
        - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER,
        description="Buy 2 puts at fill premium",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 15),
        event_type="TRANSACTION_COST",
        amount=-GF003_COMMISSION * GF003_PUT_QUANTITY,
        running_cash=GF003_INITIAL_CASH
        - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
        - GF003_COMMISSION * GF003_PUT_QUANTITY,
        description="Commission on buy (2 contract(s))",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="MONETISATION",
        amount=GF003_MONETISE_FILL_SELL * 1 * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
            - GF003_COMMISSION * GF003_PUT_QUANTITY
            + GF003_MONETISE_FILL_SELL * 1 * GF001_XSP_MULTIPLIER
        ),
        description="Sell 1 put at fill price (50% monetisation)",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="TRANSACTION_COST",
        amount=-GF003_COMMISSION,
        running_cash=(
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
            - GF003_COMMISSION * GF003_PUT_QUANTITY
            + GF003_MONETISE_FILL_SELL * 1 * GF001_XSP_MULTIPLIER
            - GF003_COMMISSION
        ),
        description="Commission on monetisation sell (1 contract(s))",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="REINVESTMENT",
        amount=-GF003_MONETISE_FILL_SELL * 1 * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
            - GF003_COMMISSION * GF003_PUT_QUANTITY
            - GF003_COMMISSION
        ),
        description="Reinvest monetised proceeds into core units at 4500",
    ),
]

GF003_EXPECTED_MONETISATION_PROCEEDS = (
    GF003_MONETISE_FILL_SELL * 1 * GF001_XSP_MULTIPLIER
)  # 39,750

# Cash after: -20,750 premium - 1.30 buy commission + 39,750 proceeds
#             - 0.65 sell commission - 39,750 reinvestment = 79,248.05
GF003_EXPECTED_FINAL_CASH = (
    GF003_INITIAL_CASH
    - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
    - GF003_COMMISSION * GF003_PUT_QUANTITY
    - GF003_COMMISSION
)  # 79,248.05

GF003_EXPECTED_UNITS_BOUGHT = (
    GF003_EXPECTED_MONETISATION_PROCEEDS / GF003_REINVEST_PRICE
)  # 8.833333...
GF003_EXPECTED_FINAL_UNITS = (
    GF003_INITIAL_UNITS + GF003_EXPECTED_UNITS_BOUGHT
)  # 208.833333...
GF003_EXPECTED_FINAL_COMBINED_VALUE = (
    GF003_EXPECTED_FINAL_CASH + GF003_EXPECTED_FINAL_UNITS * GF003_REINVEST_PRICE
)  # 1,018,998.05


# ---------------------------------------------------------------------------
# GF-004 — Wide/stale quote
# ---------------------------------------------------------------------------
# Candidate contract otherwise ideal but quote violates spread/freshness.
# Expected no tradable fill.
#
# Scenario:
# - Wide spread: bid 10 / ask 15 -> relative spread 0.40 > 0.10 threshold
# - Stale quote: snapshot at 20:00 UTC checked at 20:10 UTC (600s > 300s)
# - Expected: no tradable fill for either snapshot

GF004_NAME = "GF-004: Wide/stale quote"
GF004_DESCRIPTION = (
    "Candidate contract otherwise ideal but quote violates spread/freshness. "
    "Expected no tradable fill."
)

GF004_MAX_SPREAD_THRESHOLD = 0.10  # 10% of mid price
GF004_MAX_STALENESS_SECONDS = 300  # 5 minutes

GF004_WIDE_SPREAD_SNAPSHOT = OptionSnapshot(
    trade_date=date(2025, 1, 15),
    expiration_date=date(2025, 2, 21),
    strike=4900.0,
    option_type=OptionType.PUT,
    bid=10.0,
    ask=15.0,  # 50% spread, way above threshold
    underlying_price=5000.0,
    snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
)

GF004_STALE_SNAPSHOT = OptionSnapshot(
    trade_date=date(2025, 1, 15),
    expiration_date=date(2025, 2, 21),
    strike=4900.0,
    option_type=OptionType.PUT,
    bid=10.5,
    ask=11.0,  # Tight spread
    underlying_price=5000.0,
    snapshot_ts_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
)

GF004_CHECK_TIME = datetime(
    2025, 1, 15, 20, 10, tzinfo=UTC
)  # 600s after stale snapshot

GF004_EXPECTED_SPREAD_FRACTION = (15.0 - 10.0) / ((15.0 + 10.0) / 2)  # 0.40


# ---------------------------------------------------------------------------
# GF-005 — Basis-risk portfolio
# ---------------------------------------------------------------------------
# Two holdings with different SPX beta.
#
# Scenario:
# - Holding A: 100 units of SPY-like ETF, beta = 1.0, price = $500
# - Holding B: 50 units of tech ETF, beta = 1.2, price = $300
# - Total portfolio value: 100*500 + 50*300 = $65,000
# - Benchmark-equivalent exposure: 100*500*1.0 + 50*300*1.2 = $68,000
# - Weighted average beta: 68,000 / 65,000 = 1.046153...

GF005_NAME = "GF-005: Basis-risk portfolio"
GF005_DESCRIPTION = (
    "Two holdings with different SPX beta. "
    "Expected benchmark-equivalent exposure exact."
)

GF005_HOLDINGS = [
    PortfolioExposure(
        holding_name="SPY-ETF",
        beta=1.0,
        market_value=100 * 500,  # $50,000
        benchmark_equivalent=100 * 500 * 1.0,  # $50,000
        description="Broad market ETF with beta 1.0",
    ),
    PortfolioExposure(
        holding_name="TECH-ETF",
        beta=1.2,
        market_value=50 * 300,  # $15,000
        benchmark_equivalent=50 * 300 * 1.2,  # $18,000
        description="Tech ETF with beta 1.2",
    ),
]

GF005_TOTAL_PORTFOLIO_VALUE = 50_000 + 15_000  # $65,000
GF005_TOTAL_BENCHMARK_EQUIVALENT = 50_000 + 18_000  # $68,000
GF005_WEIGHTED_AVERAGE_BETA = 68_000 / 65_000  # 1.046153...

GF005_EXPECTED_UNMAPPED_WARNING = None  # All holdings mapped


# ---------------------------------------------------------------------------
# GF-006 — GBP/USD FX conversion
# ---------------------------------------------------------------------------
# Known FX path to verify premium/payout conversion.
#
# Scenario:
# - Portfolio in GBP, options in USD
# - FX rate: 1.27 USD/GBP
# - Premium in USD: $10,250
# - Payout in USD: $10,000
# - Expected GBP values:
#   - Premium: 10,250 / 1.27 = £8,070.87
#   - Payout: 10,000 / 1.27 = £7,874.02

GF006_NAME = "GF-006: GBP/USD FX conversion"
GF006_DESCRIPTION = "Known FX path to verify premium/payout conversion."

GF006_FX_RATE = 1.27  # USD per GBP
GF006_PREMIUM_USD = 10_250.0
GF006_PAYOUT_USD = 10_000.0

GF006_EXPECTED_PREMIUM_GBP = GF006_PREMIUM_USD / GF006_FX_RATE
GF006_EXPECTED_PAYOUT_GBP = GF006_PAYOUT_USD / GF006_FX_RATE

GF006_FX_PATH = [
    UnderlyingSnapshot(
        trade_date=date(2025, 1, 15), symbol="GBPUSD", close=1.27, currency="GBP"
    ),
    UnderlyingSnapshot(
        trade_date=date(2025, 1, 16), symbol="GBPUSD", close=1.265, currency="GBP"
    ),
    UnderlyingSnapshot(
        trade_date=date(2025, 1, 17), symbol="GBPUSD", close=1.275, currency="GBP"
    ),
]


# ---------------------------------------------------------------------------
# GF-007 — Split leakage trap
# ---------------------------------------------------------------------------
# Construct data where a future feature would make performance unrealistically
# perfect. The date-bounded access helpers above must prevent strategy access
# to future rows.
#
# Scenario:
# - Jan 15-17: normal data, option is OTM
# - Jan 20: a row carries leak_feature=1.0 ("crash coming" signal) — visible
#   only in rows dated Jan 20 or later
# - Jan 21: underlying drops 500 -> 4500 points
# - A strategy that could see the Jan-20 feature on Jan 15-17 would perfectly
#   predict the crash; the data-access boundary must make that impossible.

GF007_NAME = "GF-007: Split leakage trap"
GF007_DESCRIPTION = (
    "Construct data where a future feature would make performance unrealistically "
    "perfect. The date-bounded access helpers must prevent strategy access to "
    "future rows."
)

GF007_UNDERLYING_PRICES = [
    UnderlyingSnapshot(trade_date=date(2025, 1, 15), symbol="XSP", close=5000.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 16), symbol="XSP", close=5005.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 17), symbol="XSP", close=5010.0),
    UnderlyingSnapshot(
        trade_date=date(2025, 1, 20),
        symbol="XSP",
        close=5015.0,
        leak_feature=1.0,  # Binary "crash coming" signal, future-only
    ),
    UnderlyingSnapshot(
        trade_date=date(2025, 1, 21), symbol="XSP", close=4500.0
    ),  # Crash
]

GF007_LEAK_FEATURE_VALUE = 1.0  # Binary "crash coming" signal
GF007_LAST_SAFE_DATE = date(2025, 1, 17)  # Latest date a Jan-17 context may see
GF007_CRASH_DAY = date(2025, 1, 21)
GF007_CRASH_MAGNITUDE = 500  # 500 points drop

GF007_EXPECTED_WITH_LEAK = 100.0  # Perfect prediction if leak used
GF007_EXPECTED_WITHOUT_LEAK = 0.0  # No prediction possible without leak

GF007_OPTION_SNAPSHOTS = [
    OptionSnapshot(
        trade_date=date(2025, 1, 15),
        expiration_date=date(2025, 2, 21),
        strike=4900.0,
        option_type=OptionType.PUT,
        bid=10.0,
        ask=11.0,
        underlying_price=5000.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 21),
        expiration_date=date(2025, 2, 21),
        strike=4900.0,
        option_type=OptionType.PUT,
        bid=400.0,
        ask=410.0,
        underlying_price=4500.0,
    ),
]


# ---------------------------------------------------------------------------
# Fixture registry
# ---------------------------------------------------------------------------

ALL_FIXTURES: dict[str, dict[str, Any]] = {
    "GF-001": {
        "name": GF001_NAME,
        "description": GF001_DESCRIPTION,
        "fixture": {
            "underlying": GF001_UNDERLYING_PRICES,
            "options": GF001_OPTION_SNAPSHOTS,
        },
        "expected_cash_ledger": GF001_EXPECTED_CASH_LEDGER,
        "expected_final_cash": GF001_EXPECTED_FINAL_CASH,
        "expected_positions": GF001_EXPECTED_POSITIONS,
    },
    "GF-002": {
        "name": GF002_NAME,
        "description": GF002_DESCRIPTION,
        "fixture": {
            "underlying": GF002_UNDERLYING_PRICES,
            "expiry_1": GF002_OPTION_SNAPSHOTS_EXPIRY_1,
            "expiry_2": GF002_OPTION_SNAPSHOTS_EXPIRY_2,
        },
        "expected_cash_ledger": GF002_EXPECTED_CASH_LEDGER,
        "expected_roll_cost": GF002_EXPECTED_ROLL_COST,
        "expected_final_cash": GF002_EXPECTED_FINAL_CASH,
    },
    "GF-003": {
        "name": GF003_NAME,
        "description": GF003_DESCRIPTION,
        "fixture": {
            "underlying": GF003_UNDERLYING_PRICES,
            "options": GF003_OPTION_SNAPSHOTS,
        },
        "expected_cash_ledger": GF003_EXPECTED_CASH_LEDGER,
        "expected_monetisation_proceeds": GF003_EXPECTED_MONETISATION_PROCEEDS,
        "expected_final_cash": GF003_EXPECTED_FINAL_CASH,
        "expected_final_units": GF003_EXPECTED_FINAL_UNITS,
        "expected_final_combined_value": GF003_EXPECTED_FINAL_COMBINED_VALUE,
    },
    "GF-004": {
        "name": GF004_NAME,
        "description": GF004_DESCRIPTION,
        "fixture": {
            "wide_spread": GF004_WIDE_SPREAD_SNAPSHOT,
            "stale": GF004_STALE_SNAPSHOT,
            "check_time": GF004_CHECK_TIME,
        },
        "expected_spread_fraction": GF004_EXPECTED_SPREAD_FRACTION,
    },
    "GF-005": {
        "name": GF005_NAME,
        "description": GF005_DESCRIPTION,
        "fixture": GF005_HOLDINGS,
        "expected_total_portfolio_value": GF005_TOTAL_PORTFOLIO_VALUE,
        "expected_total_benchmark_equivalent": GF005_TOTAL_BENCHMARK_EQUIVALENT,
        "expected_weighted_average_beta": GF005_WEIGHTED_AVERAGE_BETA,
    },
    "GF-006": {
        "name": GF006_NAME,
        "description": GF006_DESCRIPTION,
        "fixture": GF006_FX_PATH,
        "expected_premium_gbp": GF006_EXPECTED_PREMIUM_GBP,
        "expected_payout_gbp": GF006_EXPECTED_PAYOUT_GBP,
    },
    "GF-007": {
        "name": GF007_NAME,
        "description": GF007_DESCRIPTION,
        "fixture": {
            "underlying": GF007_UNDERLYING_PRICES,
            "options": GF007_OPTION_SNAPSHOTS,
        },
        "expected_with_leak": GF007_EXPECTED_WITH_LEAK,
        "expected_without_leak": GF007_EXPECTED_WITHOUT_LEAK,
        "last_safe_date": GF007_LAST_SAFE_DATE,
    },
}
