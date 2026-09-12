"""Backtest metrics calculation.

Implements FR-005, FR-020: CAGR, max drawdown, premium spend, drawdown
reduction, tail-efficiency primitives.

Metric conventions (documented per TASK-013):

- All rates are decimals (e.g. 0.08 = 8%).
- CAGR: geometric annualisation ``(final/initial)^(1/years) - 1``. Invalid
  inputs (non-positive values/years) raise — a ruined backtest must never
  silently score as "0% growth" (fail closed).
- Max drawdown: peak-to-trough decline on the equity curve, returned as a
  negative decimal. ``max_drawdown_periods`` is the number of *observations*
  between the peak and the trough of the max drawdown; it is in days only
  when the equity curve is daily.
- Premium spend: **gross** sum of ``abs()`` of each premium/commission event;
  refunds never offset spend.
- Drawdown reduction: ``abs(baseline_dd) - abs(hedged_dd)`` (positive is
  better).
- Tail efficiency: drawdown reduction per **dollar of total premium spend**
  (see TECHNICAL_ARCHITECTURE.md §10). Units: drawdown fraction per
  currency unit spent.
- Fold utility: versioned-profile formula in TECHNICAL_ARCHITECTURE.md §10
  (``ΔCAGR + 0.25 * drawdown improvement``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class BacktestMetrics:
    """Complete set of backtest metrics."""

    cagr: float
    max_drawdown: float
    max_drawdown_periods: int
    total_premium_spent: float
    annualised_premium_spent: float
    premium_spend_ratio: float
    final_value: float
    initial_value: float
    total_return: float


@dataclass(frozen=True)
class BaselineComparison:
    """Comparison between hedged and baseline metrics."""

    hedged_metrics: BacktestMetrics
    baseline_metrics: BacktestMetrics
    cagr_delta: float
    drawdown_improvement: float
    premium_spend_delta: float
    tail_efficiency: float
    fold_utility: float


def compare_to_baseline(
    hedged_metrics: BacktestMetrics,
    baseline_metrics: BacktestMetrics,
) -> BaselineComparison:
    """Build a full comparison of hedged metrics against a baseline."""
    cagr_delta = hedged_metrics.cagr - baseline_metrics.cagr
    drawdown_improvement = calculate_drawdown_reduction(
        hedged_metrics.max_drawdown, baseline_metrics.max_drawdown
    )
    premium_spend_delta = (
        hedged_metrics.total_premium_spent - baseline_metrics.total_premium_spent
    )
    tail_efficiency = calculate_tail_efficiency(hedged_metrics, baseline_metrics)
    fold_utility = cagr_delta + 0.25 * drawdown_improvement

    return BaselineComparison(
        hedged_metrics=hedged_metrics,
        baseline_metrics=baseline_metrics,
        cagr_delta=cagr_delta,
        drawdown_improvement=drawdown_improvement,
        premium_spend_delta=premium_spend_delta,
        tail_efficiency=tail_efficiency,
        fold_utility=fold_utility,
    )


def calculate_cagr(
    initial_value: float,
    final_value: float,
    years: float,
) -> float:
    """Calculate Compound Annual Growth Rate.

    Parameters
    ----------
    initial_value : float
        Starting portfolio value (must be positive).
    final_value : float
        Ending portfolio value (must be positive).
    years : float
        Time period in years (must be positive).

    Returns
    -------
    float
        CAGR as decimal (e.g. 0.08 = 8%).

    Raises
    ------
    ValueError
        If any input is non-positive or non-finite. A ruined portfolio
        (non-positive final value) is an invalid input for CAGR, not a
        zero-growth result.
    """
    if initial_value <= 0 or final_value <= 0 or years <= 0:
        msg = (
            f"CAGR requires positive initial ({initial_value}), final "
            f"({final_value}) and years ({years}); a non-positive value is "
            f"an invalid/ruined backtest, not a zero-growth result"
        )
        raise ValueError(msg)
    if not (
        math.isfinite(initial_value)
        and math.isfinite(final_value)
        and math.isfinite(years)
    ):
        msg = "CAGR inputs must be finite"
        raise ValueError(msg)

    result = (final_value / initial_value) ** (1 / years) - 1
    return float(result)


def calculate_max_drawdown(
    equity_curve: Sequence[float],
) -> tuple[float, int]:
    """Calculate maximum drawdown and its duration in periods.

    Parameters
    ----------
    equity_curve : Sequence[float]
        Sequence of portfolio values over time. All values must be
        positive and finite.

    Returns
    -------
    tuple[float, int]
        (max_drawdown as negative decimal, duration as number of periods
        between the peak and the trough of the max drawdown).

    Raises
    ------
    ValueError
        If the curve contains a non-positive or non-finite value (a
        zero/negative equity value means ruin, which must fail closed).
    """
    if len(equity_curve) < 2:
        return 0.0, 0

    for value in equity_curve:
        if not math.isfinite(value) or value <= 0:
            msg = (
                f"equity_curve must contain only positive finite values "
                f"(ruin must fail closed), got {value}"
            )
            raise ValueError(msg)

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
    """Calculate total gross premium spend.

    The spend is the sum of the absolute value of each event: refunds or
    credits never offset gross premium spend.

    Parameters
    ----------
    premium_events : Sequence[float]
        Sequence of premium payments (negative values).

    Returns
    -------
    float
        Total gross premium spent (positive value).
    """
    return sum(abs(p) for p in premium_events)


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
        msg = f"years must be positive, got {years}"
        raise ValueError(msg)
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
        msg = (
            f"initial_value ({initial_value}) and years ({years}) must be "
            f"positive to compute the premium spend ratio"
        )
        raise ValueError(msg)
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

    Default scoring formula (TECHNICAL_ARCHITECTURE.md §10):
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

    Tail efficiency measures how much drawdown reduction is achieved per
    dollar of total (gross) premium spent. Defined here and in
    TECHNICAL_ARCHITECTURE.md §10; units are drawdown fraction per currency
    unit of premium spend.

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
        Sequence of portfolio values over time (non-empty; all values
        positive — see ``calculate_max_drawdown``).
    premium_events : Sequence[float]
        Sequence of premium/commission payments (negative values).
    years : float
        Time period in years (positive).
    initial_value : float | None
        Starting portfolio value (defaults to first equity curve value).

    Returns
    -------
    BacktestMetrics
        Complete set of metrics.

    Raises
    ------
    ValueError
        If the equity curve is empty or contains non-positive values, or
        ``years`` is non-positive.
    """
    if not equity_curve:
        msg = "equity_curve must not be empty (an empty backtest must fail closed)"
        raise ValueError(msg)
    if years <= 0:
        msg = f"years must be positive, got {years}"
        raise ValueError(msg)

    if initial_value is None:
        initial_value = equity_curve[0]

    final_value = equity_curve[-1]
    total_return = (final_value - initial_value) / initial_value

    cagr = calculate_cagr(initial_value, final_value, years)
    max_drawdown, max_duration = calculate_max_drawdown(equity_curve)
    total_premium = calculate_premium_spend(premium_events)
    annualised_premium = calculate_annualised_premium_spend(total_premium, years)
    premium_ratio = calculate_premium_spend_ratio(total_premium, initial_value, years)

    return BacktestMetrics(
        cagr=cagr,
        max_drawdown=max_drawdown,
        max_drawdown_periods=max_duration,
        total_premium_spent=total_premium,
        annualised_premium_spent=annualised_premium,
        premium_spend_ratio=premium_ratio,
        final_value=final_value,
        initial_value=initial_value,
        total_return=total_return,
    )
