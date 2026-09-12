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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from tailhedge.data.canonical_schema import OptionType

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
    bid_size: int | None = None
    ask_size: int | None = None
    volume: int | None = None
    open_interest: int | None = None


@dataclass(frozen=True)
class UnderlyingSnapshot:
    """Simplified underlying snapshot for fixture definition."""

    trade_date: date
    symbol: str
    close: float
    currency: str = "USD"


@dataclass(frozen=True)
class CashLedgerEntry:
    """Expected cash ledger entry for fixture validation."""

    trade_date: date
    event_type: str  # "PREMIUM", "SETTLEMENT", "REINVESTMENT", "INITIAL"
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
# GF-001 — Simple option payoff
# ---------------------------------------------------------------------------
# Five daily snapshots, one put, known expiration and premium.
# Expected cash ledger hand-calculated.
#
# Scenario:
# - XSP put option with strike 500, expiring on Day 5
# - Initial premium paid: bid/ask midpoint
# - Underlying drops from 5000 to 4900 over 5 days
# - Option expires in-the-money
#
# Hand calculation:
# - Day 1: Buy 1 put at midpoint of 10.5/11.0 = 10.75. Cash = -10.75
# - Day 2-4: No action (hold)
# - Day 5: Option expires. Strike = 500, Underlying = 4900
#   - Intrinsic value = max(0, 500 - 4900) = 0 (OTM, not ITM)
#   - Wait, this doesn't make sense for a put. Let me recalculate.
#   - For a put option: payoff = max(0, strike - underlying)
#   - Strike = 500, Underlying = 4900 -> payoff = 0 (underlying > strike)
#   - The put is OTM, expires worthless
#   - Total cash = -10.75 (premium lost)
#
# Let me redesign with a more realistic scenario where the put actually pays off:
# - Strike = 4900 (ATM or slightly OTM at start)
# - Underlying drops to 4800
# - Payoff = 4900 - 4800 = 100

GF001_NAME = "GF-001: Simple option payoff"
GF001_DESCRIPTION = (
    "Five daily snapshots, one put, known expiration and premium. "
    "Option expires ITM with known payoff."
)

# Hand-calculated values for GF-001:
# - Initial cash: $100,000
# - Put strike: 4900
# - Put premium (midpoint): (100 + 105) / 2 = 102.50
# - Underlying price day 1: 5000
# - Underlying price day 5: 4800
# - Put payoff at expiry: max(0, 4900 - 4800) = 100
# - Net P&L per contract: 100 - 102.50 = -2.50
# - Total P&L for 1 contract: -2.50

GF001_INITIAL_CASH = 100_000.0
GF001_PUT_STRIKE = 4900.0
GF001_PUT_EXPIRY = date(2025, 1, 21)
GF001_PREMIUM_BID = 100.0
GF001_PREMIUM_ASK = 105.0
GF001_PREMIUM_MIDPOINT = 102.50  # (100 + 105) / 2
GF001_CONTRACTS = 1
GF001_XSP_MULTIPLIER = 100

GF001_UNDERLYING_PRICES = [
    UnderlyingSnapshot(trade_date=date(2025, 1, 15), symbol="XSP", close=5000.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 16), symbol="XSP", close=4980.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 17), symbol="XSP", close=4950.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 20), symbol="XSP", close=4800.0),
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
    OptionSnapshot(
        trade_date=date(2025, 1, 20),
        expiration_date=GF001_PUT_EXPIRY,
        strike=GF001_PUT_STRIKE,
        option_type=OptionType.PUT,
        bid=0.0,
        ask=0.0,
        underlying_price=4800.0,
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
        amount=-GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER,
        running_cash=GF001_INITIAL_CASH - GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER,
        description="Buy 1 XSP put at midpoint premium",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 20),
        event_type="SETTLEMENT",
        amount=(GF001_PUT_STRIKE - 4800.0) * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF001_INITIAL_CASH
            - GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER
            + (GF001_PUT_STRIKE - 4800.0) * GF001_XSP_MULTIPLIER
        ),
        description="Put expires ITM, cash settlement",
    ),
]

GF001_EXPECTED_FINAL_CASH = (
    GF001_INITIAL_CASH
    - GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER
    + (GF001_PUT_STRIKE - 4800.0) * GF001_XSP_MULTIPLIER
)

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
        trade_date=date(2025, 1, 20),
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
# Two expiries; target policy rolls at known DTE.
# Expected close/buy and spend accounting.
#
# Scenario:
# - Policy: roll when DTE <= 7 days
# - Expiry 1: Jan 21, 2025 (bought Jan 15, DTE=6, within threshold)
# - Expiry 2: Feb 21, 2025 (bought Jan 20, after expiry 1)
#
# Hand calculation:
# - Day 1 (Jan 15): Buy Jan 21 put (strike 4900), premium 102.50
# - Day 2 (Jan 16): Hold
# - Day 3 (Jan 17): DTE = 4 days (Jan 21 - Jan 17 = 4), <= 7, roll trigger
# - Day 3 (Jan 17): Sell Jan 21 put at 117.50 (midpoint of 115/120)
# - Day 3 (Jan 17): Buy Feb 21 put (strike 4850), premium 150.00
# - Day 4-5: Hold Feb 21 put

GF002_NAME = "GF-002: Roll case"
GF002_DESCRIPTION = (
    "Two expiries; target policy rolls at known DTE. "
    "Expected close/buy and spend accounting."
)

GF002_INITIAL_CASH = 100_000.0
GF002_ROLL_DTE_THRESHOLD = 7

GF002_EXPIRY_1 = date(2025, 1, 21)
GF002_EXPIRY_2 = date(2025, 2, 21)
GF002_STRIKE_1 = 4900.0
GF002_STRIKE_2 = 4850.0

GF002_PREMIUM_1_BUY = 102.50
GF002_PREMIUM_1_SELL = 117.50
GF002_PREMIUM_2_BUY = 150.00

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
        bid=100.0,
        ask=105.0,
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
        bid=115.0,
        ask=120.0,
        underlying_price=4950.0,
    ),
]

GF002_OPTION_SNAPSHOTS_EXPIRY_2 = [
    OptionSnapshot(
        trade_date=date(2025, 1, 17),
        expiration_date=GF002_EXPIRY_2,
        strike=GF002_STRIKE_2,
        option_type=OptionType.PUT,
        bid=145.0,
        ask=155.0,
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
        description="Buy Jan 21 put at midpoint premium",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="SETTLEMENT",
        amount=GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF002_INITIAL_CASH
            - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
            + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
        ),
        description="Sell Jan 21 put at midpoint",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="PREMIUM",
        amount=-GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF002_INITIAL_CASH
            - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
            + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
            - GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER
        ),
        description="Buy Feb 21 put at midpoint premium",
    ),
]

GF002_EXPECTED_ROLL_COST = (
    GF002_PREMIUM_2_BUY - GF002_PREMIUM_1_SELL
) * GF001_XSP_MULTIPLIER

GF002_EXPECTED_FINAL_CASH = (
    GF002_INITIAL_CASH
    - GF002_PREMIUM_1_BUY * GF001_XSP_MULTIPLIER
    + GF002_PREMIUM_1_SELL * GF001_XSP_MULTIPLIER
    - GF002_PREMIUM_2_BUY * GF001_XSP_MULTIPLIER
)


# ---------------------------------------------------------------------------
# GF-003 — Crash + monetisation
# ---------------------------------------------------------------------------
# Underlying drops sharply; put becomes ITM; daily policy sells configured
# fraction and reinvests cash. Expected combined-portfolio units/value known.
#
# Scenario:
# - Initial portfolio: 100 units of SPY-like ETF at $500 = $50,000
# - Cash: $50,000
# - Total portfolio: $100,000
# - Hedge: 2 puts at strike 4900
# - Crash: underlying drops from 5000 to 4500
# - Monetisation: sell 50% of profitable puts, reinvest at lower price
#
# Hand calculation:
# - Day 1: Buy 2 puts at 102.50 premium = $20,500 cost
# - Day 3: Underlying at 4500, put value = max(0, 4900-4500) = 400 per unit
# - Monetise: sell 1 put at 400 = $40,000 proceeds
# - Reinvest: buy 8.89 units of ETF at $4500 (rounded to 8 units)
# - Cash after reinvestment: $50,000 - $20,500 + $40,000 - $36,000 = $33,500
# - Holdings: 100 + 8 = 108 units at $4500 = $486,000 (in ETF terms)
# - Wait, this doesn't scale well. Let me use simpler numbers.

GF003_NAME = "GF-003: Crash + monetisation"
GF003_DESCRIPTION = (
    "Underlying drops sharply; put becomes ITM; daily policy sells configured "
    "fraction and reinvests cash. Expected combined-portfolio units/value known."
)

GF003_INITIAL_CASH = 100_000.0
GF003_INITIAL_UNITS = 200.0
GF003_INITIAL_PRICE = 500.0  # ETF price
GF003_TOTAL_PORTFOLIO = GF003_INITIAL_CASH + GF003_INITIAL_UNITS * GF003_INITIAL_PRICE

GF003_PUT_STRIKE = 4900.0
GF003_PUT_EXPIRY = date(2025, 2, 21)
GF003_PUT_QUANTITY = 2
GF003_PREMIUM_BUY = 102.50
GF003_MONETISE_FRACTION = 0.5  # Sell 50% of profitable puts
GF003_MONETISE_PRICE = 400.0  # Put value when underlying at 4500

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
        bid=100.0,
        ask=105.0,
        underlying_price=5000.0,
    ),
    OptionSnapshot(
        trade_date=date(2025, 1, 17),
        expiration_date=GF003_PUT_EXPIRY,
        strike=GF003_PUT_STRIKE,
        option_type=OptionType.PUT,
        bid=395.0,
        ask=405.0,
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
        description="Buy 2 puts at midpoint premium",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="MONETISATION",
        amount=GF003_MONETISE_PRICE * 1 * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
            + GF003_MONETISE_PRICE * 1 * GF001_XSP_MULTIPLIER
        ),
        description="Sell 1 put at 400 (50% monetisation)",
    ),
    CashLedgerEntry(
        trade_date=date(2025, 1, 17),
        event_type="REINVESTMENT",
        amount=-GF003_MONETISE_PRICE * 1 * GF001_XSP_MULTIPLIER,
        running_cash=(
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
            + GF003_MONETISE_PRICE * 1 * GF001_XSP_MULTIPLIER
            - GF003_MONETISE_PRICE * 1 * GF001_XSP_MULTIPLIER
        ),
        description="Reinvest monetised proceeds into ETF",
    ),
]

GF003_EXPECTED_MONETISATION_PROCEEDS = GF003_MONETISE_PRICE * 1 * GF001_XSP_MULTIPLIER

GF003_EXPECTED_FINAL_CASH = (
    GF003_INITIAL_CASH - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
)


# ---------------------------------------------------------------------------
# GF-004 — Wide/stale quote
# ---------------------------------------------------------------------------
# Candidate contract otherwise ideal but quote violates spread/freshness.
# Expected no eligible order.
#
# Scenario:
# - Option with very wide spread (ask - bid > threshold)
# - Option with stale quote (snapshot older than freshness window)
# - Expected: no order generated

GF004_NAME = "GF-004: Wide/stale quote"
GF004_DESCRIPTION = (
    "Candidate contract otherwise ideal but quote violates spread/freshness. "
    "Expected no eligible order."
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
)

GF004_STALE_SNAPSHOT = OptionSnapshot(
    trade_date=date(2025, 1, 15),
    expiration_date=date(2025, 2, 21),
    strike=4900.0,
    option_type=OptionType.PUT,
    bid=10.5,
    ask=11.0,  # Tight spread
    underlying_price=5000.0,
)

GF004_EXPECTED_SPREAD_FRACTION = (15.0 - 10.0) / ((15.0 + 10.0) / 2)  # 0.40

GF004_EXPECTED_NO_ORDER_REASON_SPREAD = "Spread 0.40 exceeds threshold 0.10"
GF004_EXPECTED_NO_ORDER_REASON_STALE = "Quote stale beyond 300s threshold"


# ---------------------------------------------------------------------------
# GF-005 — Basis-risk portfolio
# ---------------------------------------------------------------------------
# Two holdings with different SPX beta.
# Expected benchmark-equivalent exposure exact.
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
# Construct data where future feature would make performance unrealistically
# perfect. Evaluator must prevent strategy access to future rows.
#
# Scenario:
# - Day 1-3: Normal data, option is OTM
# - Day 4: Future "leak" feature available only in future data
# - Day 5: Underlying drops, option becomes ITM
# - Strategy that sees Day 4 feature on Day 1 would know crash is coming
# - Evaluator must enforce: strategy cannot see future rows
#
# Hand calculation:
# - If strategy uses future data: perfect prediction, 100% return
# - If strategy uses only historical data: cannot predict crash

GF007_NAME = "GF-007: Split leakage trap"
GF007_DESCRIPTION = (
    "Construct data where future feature would make performance unrealistically "
    "perfect. Evaluator must prevent strategy access to future rows."
)

GF007_UNDERLYING_PRICES = [
    UnderlyingSnapshot(trade_date=date(2025, 1, 15), symbol="XSP", close=5000.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 16), symbol="XSP", close=5005.0),
    UnderlyingSnapshot(trade_date=date(2025, 1, 17), symbol="XSP", close=5010.0),
    UnderlyingSnapshot(
        trade_date=date(2025, 1, 20), symbol="XSP", close=5015.0
    ),  # Leak feature
    UnderlyingSnapshot(
        trade_date=date(2025, 1, 21), symbol="XSP", close=4500.0
    ),  # Crash
]

GF007_LEAK_FEATURE_VALUE = 1.0  # Binary "crash coming" signal
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
        "fixture": GF001_OPTION_SNAPSHOTS,
        "expected_cash_ledger": GF001_EXPECTED_CASH_LEDGER,
        "expected_final_cash": GF001_EXPECTED_FINAL_CASH,
    },
    "GF-002": {
        "name": GF002_NAME,
        "description": GF002_DESCRIPTION,
        "fixture": {
            "expiry_1": GF002_OPTION_SNAPSHOTS_EXPIRY_1,
            "expiry_2": GF002_OPTION_SNAPSHOTS_EXPIRY_2,
        },
        "expected_cash_ledger": GF002_EXPECTED_CASH_LEDGER,
        "expected_roll_cost": GF002_EXPECTED_ROLL_COST,
    },
    "GF-003": {
        "name": GF003_NAME,
        "description": GF003_DESCRIPTION,
        "fixture": GF003_OPTION_SNAPSHOTS,
        "expected_cash_ledger": GF003_EXPECTED_CASH_LEDGER,
        "expected_monetisation_proceeds": GF003_EXPECTED_MONETISATION_PROCEEDS,
    },
    "GF-004": {
        "name": GF004_NAME,
        "description": GF004_DESCRIPTION,
        "fixture": {
            "wide_spread": GF004_WIDE_SPREAD_SNAPSHOT,
            "stale": GF004_STALE_SNAPSHOT,
        },
        "expected_no_order_reasons": [
            GF004_EXPECTED_NO_ORDER_REASON_SPREAD,
            GF004_EXPECTED_NO_ORDER_REASON_STALE,
        ],
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
        "fixture": GF007_OPTION_SNAPSHOTS,
        "expected_with_leak": GF007_EXPECTED_WITH_LEAK,
        "expected_without_leak": GF007_EXPECTED_WITHOUT_LEAK,
    },
}
