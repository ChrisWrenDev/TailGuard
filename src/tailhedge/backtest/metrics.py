"""Backtest metrics calculation.

Implements FR-005, FR-020: CAGR, max drawdown, premium spend, drawdown
reduction, tail-efficiency primitives.

All rates are decimals (e.g. 0.08 = 8%). Premium cost is already reflected
in hedged CAGR and is also bounded by a hard cap, avoiding double counting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class BacktestMetrics:
    """Complete set of backtest metrics."""

    cagr: float
    max_drawdown: float
    max_drawdown_duration_days: int
    total_premium_spent: float
    annualised_premium_spent: float
    premium_spend_ratio: float
    final_value: float
    initial_value: float
    total_return: float
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None


@dataclass(frozen=True)
class BaselineComparison:
    """Comparison between hedged and baseline metrics."""

    hedged_metrics: BacktestMetrics
    baseline_metrics: BacktestMetrics
    cagr_delta: float
    drawdown_improvement: float
    premium_spend_delta: float
    fold_utility: float


def calculate_cagr(
    initial_value: float,
    final_value: float,
    years: float,
) -> float:
    """Calculate Compound Annual Growth Rate.

    Parameters
    ----------
    initial_value : float
        Starting portfolio value.
    final_value : float
        Ending portfolio value.
    years : float
        Time period in years.

    Returns
    -------
    float
        CAGR as decimal (e.g. 0.08 = 8%).
    """
    if initial_value <= 0 or final_value <= 0 or years <= 0:
        return 0.0

    result = (final_value / initial_value) ** (1 / years) - 1
    return float(result)


def calculate_max_drawdown(
    equity_curve: Sequence[float],
) -> tuple[float, int]:
    """Calculate maximum drawdown and its duration.

    Parameters
    ----------
    equity_curve : Sequence[float]
        Sequence of portfolio values over time.

    Returns
    -------
    tuple[float, int]
        (max_drawdown as negative decimal, duration in periods).
    """
    if len(equity_curve) < 2:
        return 0.0, 0

    max_drawdown = 0.0
    peak = equity_curve[0]
    peak_idx = 0
    max_duration = 0
    current_duration = 0

    for i, value in enumerate(equity_curve):
        if value >= peak:
            peak = value
            peak_idx = i
            current_duration = 0
        else:
            current_duration = i - peak_idx
            drawdown = (value - peak) / peak
            if drawdown < max_drawdown:
                max_drawdown = drawdown
                max_duration = current_duration

    return max_drawdown, max_duration


def calculate_premium_spend(
    premium_events: Sequence[float],
) -> float:
    """Calculate total premium spent.

    Parameters
    ----------
    premium_events : Sequence[float]
        Sequence of premium payments (negative values).

    Returns
    -------
    float
        Total premium spent (positive value).
    """
    return abs(sum(premium_events))


def calculate_annualised_premium_spend(
    total_premium: float,
    years: float,
) -> float:
    """Calculate annualised premium spend.

    Parameters
    ----------
    total_premium : float
        Total premium spent.
    years : float
        Time period in years.

    Returns
    -------
    float
        Annualised premium spend.
    """
    if years <= 0:
        return 0.0
    return total_premium / years


def calculate_premium_spend_ratio(
    total_premium: float,
    initial_value: float,
    years: float,
) -> float:
    """Calculate premium spend as percentage of initial value per year.

    Parameters
    ----------
    total_premium : float
        Total premium spent.
    initial_value : float
        Starting portfolio value.
    years : float
        Time period in years.

    Returns
    -------
    float
        Premium spend ratio as decimal.
    """
    if initial_value <= 0 or years <= 0:
        return 0.0
    return total_premium / (initial_value * years)


def calculate_drawdown_reduction(
    hedged_drawdown: float,
    baseline_drawdown: float,
) -> float:
    """Calculate drawdown improvement (positive = better).

    Parameters
    ----------
    hedged_drawdown : float
        Hedged strategy max drawdown (negative).
    baseline_drawdown : float
        Baseline strategy max drawdown (negative).

    Returns
    -------
    float
        Drawdown improvement (positive if hedged is better).
    """
    return abs(baseline_drawdown) - abs(hedged_drawdown)


def calculate_fold_utility(
    hedged_cagr: float,
    unhedged_cagr: float,
    hedged_max_drawdown: float,
    unhedged_max_drawdown: float,
) -> float:
    """Calculate fold utility score.

    Default scoring formula:
    fold_utility = (hedged_CAGR - unhedged_CAGR)
                 + 0.25 * (abs(unhedged_max_drawdown) - abs(hedged_max_drawdown))

    Parameters
    ----------
    hedged_cagr : float
        Hedged strategy CAGR.
    unhedged_cagr : float
        Unhedged strategy CAGR.
    hedged_max_drawdown : float
        Hedged strategy max drawdown (negative).
    unhedged_max_drawdown : float
        Unhedged strategy max drawdown (negative).

    Returns
    -------
    float
        Fold utility score.
    """
    cagr_delta = hedged_cagr - unhedged_cagr
    drawdown_improvement = abs(unhedged_max_drawdown) - abs(hedged_max_drawdown)
    return cagr_delta + 0.25 * drawdown_improvement


def calculate_tail_efficiency(
    hedged_metrics: BacktestMetrics,
    baseline_metrics: BacktestMetrics,
) -> float:
    """Calculate tail efficiency ratio.

    Tail efficiency measures how much drawdown reduction is achieved
    per unit of premium spent.

    Parameters
    ----------
    hedged_metrics : BacktestMetrics
        Hedged strategy metrics.
    baseline_metrics : BacktestMetrics
        Baseline strategy metrics.

    Returns
    -------
    float
        Tail efficiency ratio (drawdown reduction per unit premium).
    """
    if hedged_metrics.total_premium_spent <= 0:
        return 0.0

    drawdown_improvement = calculate_drawdown_reduction(
        hedged_metrics.max_drawdown, baseline_metrics.max_drawdown
    )

    return drawdown_improvement / hedged_metrics.total_premium_spent


def calculate_metrics(
    equity_curve: Sequence[float],
    premium_events: Sequence[float],
    years: float,
    initial_value: float | None = None,
) -> BacktestMetrics:
    """Calculate complete backtest metrics.

    Parameters
    ----------
    equity_curve : Sequence[float]
        Sequence of portfolio values over time.
    premium_events : Sequence[float]
        Sequence of premium payments (negative values).
    years : float
        Time period in years.
    initial_value : float | None
        Starting portfolio value (defaults to first equity curve value).

    Returns
    -------
    BacktestMetrics
        Complete set of metrics.
    """
    if not equity_curve:
        return BacktestMetrics(
            cagr=0.0,
            max_drawdown=0.0,
            max_drawdown_duration_days=0,
            total_premium_spent=0.0,
            annualised_premium_spent=0.0,
            premium_spend_ratio=0.0,
            final_value=0.0,
            initial_value=0.0,
            total_return=0.0,
        )

    if initial_value is None:
        initial_value = equity_curve[0]

    final_value = equity_curve[-1]
    total_return = (
        (final_value - initial_value) / initial_value if initial_value > 0 else 0.0
    )

    cagr = calculate_cagr(initial_value, final_value, years)
    max_drawdown, max_duration = calculate_max_drawdown(equity_curve)
    total_premium = calculate_premium_spend(premium_events)
    annualised_premium = calculate_annualised_premium_spend(total_premium, years)
    premium_ratio = calculate_premium_spend_ratio(total_premium, initial_value, years)

    return BacktestMetrics(
        cagr=cagr,
        max_drawdown=max_drawdown,
        max_drawdown_duration_days=max_duration,
        total_premium_spent=total_premium,
        annualised_premium_spent=annualised_premium,
        premium_spend_ratio=premium_ratio,
        final_value=final_value,
        initial_value=initial_value,
        total_return=total_return,
    )
