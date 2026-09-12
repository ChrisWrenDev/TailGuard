"""Baseline strategies for comparison.

Implements FR-005: immutable comparison baselines. All baselines run through
the SAME deterministic engine (``tailhedge.backtest.engine``), the same
accounting ledger, and the same bid/ask fill/cost model as candidate
strategies — no baseline has a bespoke accounting path.

Baselines:
1. No hedge — core portfolio only (never trades).
2. Lower-equity/cash allocation — static split, never trades.
3. Fixed put hedge — Cboe-PPUT-like mechanical policy: a long ~5% OTM
   put at a target DTE, rolled before expiry, funded within a fixed
   percentage-of-portfolio budget. This is PPUT-inspired, not an exact
   index replication (FR-005).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from tailhedge.backtest.engine import (
    BacktestConfig,
    EngineAction,
    EngineActionKind,
    ReinvestDirective,
    run_daily_backtest,
)
from tailhedge.backtest.fill_model import (
    FillConfig,
    QuoteTradability,
    validate_quote_tradability,
)
from tailhedge.backtest.strategy import RollConfig

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from tailhedge.backtest.engine import BacktestRunResult
    from tailhedge.backtest.fill_model import Quote
    from tailhedge.backtest.ledger import BacktestLedger, PutPosition


class BaselineType(StrEnum):
    """Types of baseline strategies."""

    NO_HEDGE = "NO_HEDGE"
    LOWER_EQUITY = "LOWER_EQUITY"
    FIXED_PUT = "FIXED_PUT"


@dataclass(frozen=True)
class BaselineSpec:
    """Immutable configuration for a baseline strategy.

    One frozen spec carries both the descriptive identity and the policy
    parameters; defaults for unused parameters are harmless.
    """

    baseline_type: BaselineType
    name: str
    description: str
    # Fixed-put (PPUT-like) parameters
    target_dte: int = 90
    moneyness: float = 0.95
    roll_dte_threshold: int = 21
    budget_pct: float = 0.01
    # Lower-equity parameters
    equity_allocation: float = 0.7
    cash_allocation: float = 0.3


NO_HEDGE_SPEC = BaselineSpec(
    baseline_type=BaselineType.NO_HEDGE,
    name="No Hedge",
    description="Core portfolio only, no put overlay",
)
LOWER_EQUITY_SPEC = BaselineSpec(
    baseline_type=BaselineType.LOWER_EQUITY,
    name="Lower Equity/Cash",
    description="70% equity, 30% cash, never hedged",
)
FIXED_PUT_SPEC = BaselineSpec(
    baseline_type=BaselineType.FIXED_PUT,
    name="Fixed Put Hedge (PPUT-like)",
    description=(
        "Cboe-PPUT-like mechanical policy: long 5% OTM put at target DTE, "
        "rolled before expiry, funded within a fixed % of portfolio budget"
    ),
)

DEFAULT_BASELINES: list[BaselineSpec] = [
    NO_HEDGE_SPEC,
    LOWER_EQUITY_SPEC,
    FIXED_PUT_SPEC,
]


def get_baseline_config(baseline_type: BaselineType) -> BaselineSpec:
    """Get default configuration for a baseline type."""
    for config in DEFAULT_BASELINES:
        if config.baseline_type == baseline_type:
            return config
    msg = f"Unknown baseline type: {baseline_type}"
    raise ValueError(msg)


def get_all_baseline_configs() -> list[BaselineSpec]:
    """Get all default baseline configurations."""
    return list(DEFAULT_BASELINES)


# ---------------------------------------------------------------------------
# Baseline policies (all executed by the shared engine)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoHedgePolicy:
    """Never trades; the core portfolio is left untouched."""

    def decide(
        self,
        _trade_date: date,
        _ledger: BacktestLedger,
        _quotes_by_day: Mapping[date, Sequence[Quote]],
        _underlying_close: float,
    ) -> list[tuple[EngineAction, ReinvestDirective | None]]:
        return []


@dataclass(frozen=True)
class FixedPutPolicy:
    """Cboe-PPUT-like mechanical put-buying policy.

    When no put is held, buys one contract at ``moneyness`` * spot strike
    and an expiry near ``target_dte``, if the rolling annual budget allows.
    When held, rolls to the next eligible contract once DTE drops to
    ``roll_dte_threshold``; otherwise holds to expiry.
    """

    spec: BaselineSpec

    def decide(
        self,
        trade_date: date,
        ledger: BacktestLedger,
        quotes_by_day: Mapping[date, Sequence[Quote]],
        underlying_close: float,
    ) -> list[tuple[EngineAction, ReinvestDirective | None]]:
        day_quotes = list(quotes_by_day.get(trade_date, []))
        if not day_quotes:
            return []

        held = list(ledger.positions)

        if held:
            # Roll the most-expiring-soon position if within threshold,
            # provided the roll keeps net outlay within the annual budget.
            soonest = min(held, key=lambda p: p.expiration_date)
            dte = (soonest.expiration_date - trade_date).days
            if dte <= self.spec.roll_dte_threshold:
                target = _pick_roll_target(day_quotes, soonest)
                sell_quote = _find_day_quote(day_quotes, soonest)
                if (
                    target is not None
                    and sell_quote is not None
                    and _roll_within_budget(
                        self.spec,
                        ledger,
                        trade_date,
                        soonest,
                        sell_quote,
                        target,
                        underlying_close,
                    )
                ):
                    return [
                        (
                            EngineAction(
                                kind=EngineActionKind.ROLL,
                                strike=soonest.strike,
                                expiration_date=soonest.expiration_date,
                                quantity=soonest.quantity,
                                to_strike=target.strike,
                                to_expiry=target.expiration_date,
                            ),
                            None,
                        )
                    ]
                # Over budget or missing quote: skip the roll and let the
                # position ride to expiry (it settles there); the policy
                # re-enters once flat and the budget allows.
            return []

        return _maybe_buy_new_put(
            self.spec, ledger, trade_date, day_quotes, underlying_close
        )


def _find_day_quote(
    day_quotes: Sequence[Quote],
    position: PutPosition,
) -> Quote | None:
    """Find the day's quote for a held position's contract."""
    return next(
        (
            q
            for q in day_quotes
            if q.strike == position.strike
            and q.expiration_date == position.expiration_date
        ),
        None,
    )


def _net_option_outlay(ledger: BacktestLedger) -> float:
    """Net premium outlay to date (buys minus sale/settlement proceeds)."""
    from tailhedge.backtest.ledger import EventType

    return -sum(
        e.amount
        for e in ledger.cash_events
        if e.event_type
        in (EventType.PREMIUM, EventType.MONETISATION, EventType.SETTLEMENT)
        and e.trade_date > ledger.cash_events[0].trade_date
    )


def _annual_allowance(
    spec: BaselineSpec,
    ledger: BacktestLedger,
    trade_date: date,
    underlying_close: float,
) -> float:
    """Budget allowance accrued to date (budget_pct of value per elapsed year)."""
    run_start = ledger.cash_events[0].trade_date
    years_elapsed = max((trade_date - run_start).days / 365.25, 0.0)
    budget = spec.budget_pct * ledger.portfolio_value(underlying_close)
    return budget * years_elapsed


def _roll_within_budget(
    spec: BaselineSpec,
    ledger: BacktestLedger,
    trade_date: date,
    position: PutPosition,
    sell_quote: Quote,
    target: Quote,
    underlying_close: float,
) -> bool:
    """Check whether rolling keeps net option outlay within the budget.

    Uses a conservative estimate (sell at bid, buy at ask) so the actual
    fill-model roll never increases net outlay more than the estimate.
    """
    allowance = _annual_allowance(spec, ledger, trade_date, underlying_close)
    net_now = _net_option_outlay(ledger)
    increase_estimate = (
        (target.ask - sell_quote.bid) * position.quantity * ledger.multiplier
    )
    return net_now + max(increase_estimate, 0.0) <= allowance


def _pick_roll_target(
    day_quotes: Sequence[Quote],
    position: PutPosition,
) -> Quote | None:
    """Pick the nearest-expiry tradable quote beyond the current position."""

    candidates = [
        q
        for q in day_quotes
        if q.expiration_date > position.expiration_date
        and validate_quote_tradability(q, q.snapshot_ts_utc, FillConfig())
        == QuoteTradability.TRADABLE
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda q: q.expiration_date)


def _maybe_buy_new_put(
    spec: BaselineSpec,
    ledger: BacktestLedger,
    trade_date: date,
    day_quotes: Sequence[Quote],
    underlying_close: float,
) -> list[tuple[EngineAction, ReinvestDirective | None]]:
    """Budget-constrained purchase of a new target-DTE put.

    The budget is the *net* premium outlay per rolling year (premium buys
    minus option proceeds from sales/settlements), consistent with the
    project's annual budget-cap framing (ADR-024).
    """

    remaining = _annual_allowance(
        spec, ledger, trade_date, underlying_close
    ) - _net_option_outlay(ledger)
    if remaining <= 0:
        return []

    target_strike = _round_strike(spec.moneyness * underlying_close)
    candidates = [
        q
        for q in day_quotes
        if q.strike == target_strike
        and validate_quote_tradability(q, q.snapshot_ts_utc, FillConfig())
        == QuoteTradability.TRADABLE
    ]
    if not candidates:
        return []
    # Closest DTE to the target
    target = min(
        candidates,
        key=lambda q: abs((q.expiration_date - trade_date).days - spec.target_dte),
    )

    premium_estimate = target.ask
    quantity = int(remaining // (premium_estimate * ledger.multiplier))
    if quantity <= 0:
        return []

    return [
        (
            EngineAction(
                kind=EngineActionKind.BUY_PUT,
                strike=target.strike,
                expiration_date=target.expiration_date,
                quantity=quantity,
            ),
            None,
        )
    ]


def _round_strike(value: float) -> float:
    """Round a strike to the nearest 5-point increment (XSP convention)."""
    return round(value / 5.0) * 5.0


@dataclass(frozen=True)
class RollingHedgePolicy:
    """Daily strategy-directed hedge policy for candidate runs.

    Entry: when no put is held, buys one contract at ``entry_moneyness`` *
    spot with an expiry near ``entry_target_dte``, within an annual budget
    of ``budget_pct`` of portfolio value (same mechanical budget rule as
    the fixed-put baseline).

    Roll: positions at or below the DTE threshold roll to the nearest
    further expiry. Monetise: profitable positions sell
    ``monetise_fraction`` of their quantity when ``monetise_fraction > 0``,
    reinvesting ``reinvest_fraction`` of proceeds into core units at the
    current underlying close.
    """

    roll_config: RollConfig = field(default_factory=RollConfig)
    entry_moneyness: float = 0.95
    entry_target_dte: int = 63
    budget_pct: float = 0.01
    monetise_fraction: float = 0.0
    reinvest_fraction: float = 0.0

    def decide(
        self,
        trade_date: date,
        ledger: BacktestLedger,
        quotes_by_day: Mapping[date, Sequence[Quote]],
        underlying_close: float,
    ) -> list[tuple[EngineAction, ReinvestDirective | None]]:
        day_quotes = list(quotes_by_day.get(trade_date, []))
        if not day_quotes:
            return []

        if not ledger.positions:
            return _maybe_buy_new_put(
                BaselineSpec(
                    baseline_type=BaselineType.FIXED_PUT,
                    name="entry",
                    description="",
                    target_dte=self.entry_target_dte,
                    moneyness=self.entry_moneyness,
                    roll_dte_threshold=self.roll_config.roll_dte_threshold,
                    budget_pct=self.budget_pct,
                ),
                ledger,
                trade_date,
                day_quotes,
                underlying_close,
            )

        actions: list[tuple[EngineAction, ReinvestDirective | None]] = []

        for position in list(ledger.positions):
            quote = next(
                (
                    q
                    for q in day_quotes
                    if q.strike == position.strike
                    and q.expiration_date == position.expiration_date
                ),
                None,
            )
            if quote is None:
                continue  # No executable quote -> no simulated trade

            dte = (position.expiration_date - trade_date).days
            if dte <= self.roll_config.roll_dte_threshold:
                target = _pick_roll_target(day_quotes, position)
                if target is not None:
                    actions.append(
                        (
                            EngineAction(
                                kind=EngineActionKind.ROLL,
                                strike=position.strike,
                                expiration_date=position.expiration_date,
                                quantity=position.quantity,
                                to_strike=target.strike,
                                to_expiry=target.expiration_date,
                            ),
                            None,
                        )
                    )
            elif self.monetise_fraction > 0:
                sell_qty = math.floor(position.quantity * self.monetise_fraction + 1e-9)
                if sell_qty > 0:
                    directive: ReinvestDirective | None = None
                    if self.reinvest_fraction > 0:
                        directive = ReinvestDirective(
                            price=underlying_close,
                            fraction=self.reinvest_fraction,
                        )
                    actions.append(
                        (
                            EngineAction(
                                kind=EngineActionKind.SELL_TO_CLOSE,
                                strike=position.strike,
                                expiration_date=position.expiration_date,
                                quantity=sell_qty,
                            ),
                            directive,
                        )
                    )

        return actions


# ---------------------------------------------------------------------------
# Baseline runners (shared engine)
# ---------------------------------------------------------------------------


def run_baseline(
    spec: BaselineSpec,
    engine_config: BacktestConfig,
    underlying_prices: Mapping[date, float],
    quotes_by_day: Mapping[date, Sequence[Quote]],
    initial_price: float,
) -> BacktestRunResult:
    """Run a baseline through the shared engine.

    Parameters
    ----------
    spec : BaselineSpec
        Immutable baseline configuration.
    engine_config : BacktestConfig
        Shared engine configuration (initial cash/units are overridden for
        the lower-equity baseline).
    underlying_prices, quotes_by_day :
        Shared market data — identical to what candidate strategies see.
    initial_price : float
        Underlying price on the first trade date (for allocation split).

    Returns
    -------
    BacktestRunResult
        Result of the baseline run through the shared engine.
    """
    if spec.baseline_type == BaselineType.NO_HEDGE:
        policy: NoHedgePolicy | FixedPutPolicy | RollingHedgePolicy = NoHedgePolicy()
        run_config = engine_config
    elif spec.baseline_type == BaselineType.LOWER_EQUITY:
        policy = NoHedgePolicy()
        total_value = (
            engine_config.initial_cash + engine_config.initial_units * initial_price
        )
        run_config = BacktestConfig(
            initial_cash=total_value * spec.cash_allocation,
            initial_units=total_value * spec.equity_allocation / initial_price,
            currency=engine_config.currency,
            fill_config=engine_config.fill_config,
            roll_config=engine_config.roll_config,
            monetise_config=engine_config.monetise_config,
            reinvest_config=engine_config.reinvest_config,
        )
    elif spec.baseline_type == BaselineType.FIXED_PUT:
        policy = FixedPutPolicy(spec=spec)
        run_config = engine_config
    else:
        msg = f"Unknown baseline type: {spec.baseline_type}"
        raise ValueError(msg)

    return run_daily_backtest(
        config=run_config,
        policy=policy,
        underlying_prices=underlying_prices,
        quotes_by_day=quotes_by_day,
    )
