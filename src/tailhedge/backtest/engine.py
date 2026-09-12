"""Deterministic daily backtest engine.

Runs a portfolio + long-put overlay through the accounting ledger using the
bid/ask fill model, one decision per trade date, with no intraday inference
(FR-004, FR-019).

All strategies and baselines execute through this same engine and the same
fill/cost model; nothing may bypass the ledger or midpoint-fill quotes.

Daily loop per trade date (TECHNICAL_ARCHITECTURE.md §9):
1. settle options expiring today at the expiry-day underlying close;
2. ask the strategy policy for actions (buy/sell targets);
3. execute each action through the fill model (untradable quote -> no trade);
4. record mark-to-market portfolio value (cash + units * close).

Options are not marked to market in the daily equity value; hedge P&L enters
through realised cash flows (premiums, sale proceeds, settlements) exactly as
the ledger records them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from tailhedge.backtest.fill_model import (
    FillConfig,
    FillSide,
    calculate_fill,
)
from tailhedge.backtest.ledger import BacktestLedger
from tailhedge.backtest.strategy import (
    MonetiseConfig,
    ReinvestConfig,
    RollConfig,
    StrategyDecision,
    execute_monetise,
    execute_roll,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime

    from tailhedge.backtest.fill_model import Quote


class EngineActionKind:
    """Action kinds a strategy policy may request."""

    BUY_PUT = "BUY_PUT"
    SELL_TO_CLOSE = "SELL_TO_CLOSE"
    ROLL = "ROLL"


@dataclass(frozen=True)
class EngineAction:
    """A strategy-requested action for one day.

    For ``ROLL`` actions, ``strike``/``expiration_date`` identify the leg
    being closed and ``to_strike``/``to_expiry`` the new contract; the roll
    is executed atomically (both legs must be tradable or nothing happens).
    """

    kind: str  # EngineActionKind value
    strike: float
    expiration_date: date
    quantity: int
    to_strike: float | None = None
    to_expiry: date | None = None


@dataclass(frozen=True)
class ReinvestDirective:
    """Reinvestment directive attached to a sell action."""

    price: float
    fraction: float


class StrategyPolicy(Protocol):
    """Protocol for daily strategy policies used by the engine.

    A policy sees only current-day market data and the ledger's own state;
    it never touches the fill model internals or future data.
    """

    def decide(
        self,
        trade_date: date,
        ledger: BacktestLedger,
        quotes_by_day: Mapping[date, Sequence[Quote]],
        underlying_close: float,
    ) -> list[tuple[EngineAction, ReinvestDirective | None]]:
        """Return the actions to execute on ``trade_date``."""
        ...


@dataclass(frozen=True)
class BacktestConfig:
    """Configuration for a single deterministic backtest run."""

    initial_cash: float
    initial_units: float = 0.0
    currency: str = "USD"
    fill_config: FillConfig = field(default_factory=FillConfig)
    roll_config: RollConfig = field(default_factory=RollConfig)
    monetise_config: MonetiseConfig = field(default_factory=MonetiseConfig)
    reinvest_config: ReinvestConfig = field(default_factory=ReinvestConfig)


@dataclass(frozen=True)
class BacktestRunResult:
    """Result of one deterministic backtest run."""

    ledger: BacktestLedger
    trade_dates: list[date]
    equity_curve: list[float]
    decisions: list[StrategyDecision]
    years: float

    def premium_events(self) -> list[float]:
        """Negative cash events for premium and commission spend."""
        from tailhedge.backtest.ledger import EventType

        return [
            e.amount
            for e in self.ledger.cash_events
            if e.event_type in (EventType.PREMIUM, EventType.TRANSACTION_COST)
        ]


def run_daily_backtest(
    config: BacktestConfig,
    policy: StrategyPolicy,
    underlying_prices: Mapping[date, float],
    quotes_by_day: Mapping[date, Sequence[Quote]],
    initial_date: date | None = None,
) -> BacktestRunResult:
    """Run a deterministic daily backtest.

    Parameters
    ----------
    config : BacktestConfig
        Initial balances and frozen fill/strategy configuration.
    policy : StrategyPolicy
        Daily strategy policy.
    underlying_prices : Mapping[date, float]
        Underlying close price per trade date. Must cover the expiry date
        of every position the policy can hold, otherwise settlement fails
        closed.
    quotes_by_day : Mapping[date, Sequence[Quote]]
        Option quotes available on each trade date.
    initial_date : date | None
        Date recorded on the ledger's initial event (defaults to the first
        trade date).

    Returns
    -------
    BacktestRunResult
        Ledger, daily equity curve, decisions, and elapsed years.

    Raises
    ------
    ValueError
        If settlement is missed or no trade dates are supplied.
    """
    trade_dates = sorted(underlying_prices)
    if not trade_dates:
        msg = "underlying_prices must contain at least one trade date"
        raise ValueError(msg)

    ledger = BacktestLedger(
        initial_cash=config.initial_cash,
        initial_units=config.initial_units,
        currency=config.currency,
        initial_date=initial_date or trade_dates[0],
    )

    decisions: list[StrategyDecision] = []
    equity_curve: list[float] = []

    for trade_date in trade_dates:
        close = underlying_prices[trade_date]

        # 1. Settle options expiring today at the expiry-day close.
        ledger.settle_expiry(trade_date, close)

        # 2. Strategy decisions from current-day data only.
        day_actions = policy.decide(trade_date, ledger, quotes_by_day, close)

        # 3. Execute actions through the fill model (never midpoint).
        day_quotes = list(quotes_by_day.get(trade_date, []))
        for action, reinvest_directive in day_actions:
            if action.kind not in (
                EngineActionKind.BUY_PUT,
                EngineActionKind.SELL_TO_CLOSE,
                EngineActionKind.ROLL,
            ):
                msg = f"Unknown engine action kind: {action.kind}"
                raise ValueError(msg)

            quote = _find_quote(day_quotes, action)
            if quote is None:
                decisions.append(
                    StrategyDecision(
                        trade_date=trade_date,
                        action="NONE",
                        description=(
                            f"{action.kind} skipped: no executable quote for "
                            f"{action.strike}/{action.expiration_date}"
                        ),
                    )
                )
                continue

            current_time = quote.snapshot_ts_utc

            if action.kind == EngineActionKind.SELL_TO_CLOSE:
                decision = execute_monetise(
                    ledger=ledger,
                    trade_date=trade_date,
                    current_time=current_time,
                    fill_config=config.fill_config,
                    strike=action.strike,
                    expiry=action.expiration_date,
                    quantity=action.quantity,
                    sell_quote=quote,
                    reinvest=reinvest_directive is not None,
                    reinvest_price=(
                        reinvest_directive.price if reinvest_directive else 0.0
                    ),
                    reinvest_fraction=(
                        reinvest_directive.fraction if reinvest_directive else 0.0
                    ),
                )
            elif action.kind == EngineActionKind.BUY_PUT:
                decision = _execute_buy(
                    ledger, trade_date, current_time, config, action, quote
                )
            elif action.kind == EngineActionKind.ROLL:
                decision = _execute_roll(
                    ledger, trade_date, current_time, config, action, quote, day_quotes
                )
            else:
                msg = f"Unknown engine action kind: {action.kind}"
                raise ValueError(msg)

            decisions.append(decision)

        # 4. Mark-to-market combined portfolio value at the close.
        equity_curve.append(ledger.portfolio_value(close))

    years = (trade_dates[-1] - trade_dates[0]).days / 365.25
    if years <= 0:
        years = 1.0 / 365.25

    return BacktestRunResult(
        ledger=ledger,
        trade_dates=trade_dates,
        equity_curve=equity_curve,
        decisions=decisions,
        years=years,
    )


def _execute_roll(
    ledger: BacktestLedger,
    trade_date: date,
    current_time: datetime,
    config: BacktestConfig,
    action: EngineAction,
    sell_quote: Quote,
    day_quotes: Sequence[Quote],
) -> StrategyDecision:
    """Execute a ROLL action atomically through the fill model.

    Both legs must have tradable quotes from the same day; otherwise
    nothing is executed and a no-action decision is recorded.
    """
    if action.to_strike is None or action.to_expiry is None:
        msg = "ROLL action requires to_strike and to_expiry"
        raise ValueError(msg)

    buy_quote = next(
        (
            q
            for q in day_quotes
            if q.strike == action.to_strike and q.expiration_date == action.to_expiry
        ),
        None,
    )
    if buy_quote is None:
        return StrategyDecision(
            trade_date=trade_date,
            action="NONE",
            description=(
                f"Roll skipped: no executable quote for target contract "
                f"{action.to_strike}/{action.to_expiry}"
            ),
        )

    return execute_roll(
        ledger=ledger,
        trade_date=trade_date,
        current_time=current_time,
        fill_config=config.fill_config,
        from_strike=action.strike,
        from_expiry=action.expiration_date,
        to_strike=action.to_strike,
        to_expiry=action.to_expiry,
        quantity=action.quantity,
        sell_quote=sell_quote,
        buy_quote=buy_quote,
    )


def _execute_buy(
    ledger: BacktestLedger,
    trade_date: date,
    current_time: datetime,
    config: BacktestConfig,
    action: EngineAction,
    quote: Quote,
) -> StrategyDecision:
    """Execute a BUY_PUT action through the fill model."""
    description = (
        f"Buy {action.quantity} put(s) {action.strike}/{action.expiration_date}"
    )

    buy_fill = calculate_fill(
        quote, FillSide.BUY, action.quantity, current_time, config.fill_config
    )
    if not buy_fill.is_tradable:
        return StrategyDecision(
            trade_date=trade_date,
            action="NONE",
            description=f"{description} skipped: {buy_fill.rejection_reason}",
        )

    ledger.buy_put(
        trade_date=trade_date,
        strike=action.strike,
        expiration_date=action.expiration_date,
        quantity=action.quantity,
        premium=buy_fill.fill_price,
    )
    ledger.record_transaction_cost(
        trade_date=trade_date,
        cost=buy_fill.commission,
        description=f"Commission on buy ({action.quantity} contract(s))",
    )

    return StrategyDecision(
        trade_date=trade_date,
        action="BUY",
        roll_to_strike=action.strike,
        roll_to_expiry=action.expiration_date,
        roll_quantity=action.quantity,
        description=f"{description} at {buy_fill.fill_price}",
    )


def _find_quote(
    day_quotes: Sequence[Quote],
    action: EngineAction,
) -> Quote | None:
    """Find the quote matching an action's contract (strike + expiry)."""
    for quote in day_quotes:
        if (
            quote.strike == action.strike
            and quote.expiration_date == action.expiration_date
        ):
            return quote
    return None
