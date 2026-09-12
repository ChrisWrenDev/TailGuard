"""Unit tests for metrics (T-006) and baseline configuration specs.

Covers CAGR, max drawdown, premium spend, drawdown reduction, tail
efficiency, fold utility, and complete-metrics calculation, including the
fail-closed behaviour on invalid inputs.
"""

from __future__ import annotations

import pytest

from tailhedge.backtest.baselines import (
    FIXED_PUT_SPEC,
    BaselineSpec,
    BaselineType,
    get_all_baseline_configs,
    get_baseline_config,
)
from tailhedge.backtest.metrics import (
    BacktestMetrics,
    calculate_annualised_premium_spend,
    calculate_cagr,
    calculate_drawdown_reduction,
    calculate_fold_utility,
    calculate_max_drawdown,
    calculate_metrics,
    calculate_premium_spend,
    calculate_premium_spend_ratio,
    calculate_tail_efficiency,
    compare_to_baseline,
)

# ---------------------------------------------------------------------------
# CAGR calculation
# ---------------------------------------------------------------------------


class TestCAGR:
    """Test Compound Annual Growth Rate calculation."""

    def test_simple_cagr(self) -> None:
        """Simple CAGR: double in 1 year = 100%."""
        cagr = calculate_cagr(100_000.0, 200_000.0, 1.0)
        assert cagr == pytest.approx(1.0)

    def test_10_year_cagr(self) -> None:
        """10-year CAGR: $100k to $200k."""
        cagr = calculate_cagr(100_000.0, 200_000.0, 10.0)
        # (2)^0.1 - 1 = 0.07177...
        assert cagr == pytest.approx(0.07177, rel=1e-3)

    def test_negative_return(self) -> None:
        """Negative return should give negative CAGR."""
        cagr = calculate_cagr(100_000.0, 50_000.0, 1.0)
        assert cagr == pytest.approx(-0.5)

    def test_zero_years_raises(self) -> None:
        """Non-positive years must fail closed, not return 0."""
        with pytest.raises(ValueError, match="years"):
            calculate_cagr(100_000.0, 200_000.0, 0.0)

    def test_zero_initial_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            calculate_cagr(0.0, 200_000.0, 1.0)

    def test_ruined_final_value_raises(self) -> None:
        """A ruined portfolio (final <= 0) must fail closed, not score 0%."""
        with pytest.raises(ValueError, match="ruined"):
            calculate_cagr(100_000.0, -10_000.0, 2.0)


# ---------------------------------------------------------------------------
# Max drawdown calculation
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    """Test maximum drawdown calculation."""

    def test_no_drawdown(self) -> None:
        """Monotonically increasing should have 0 drawdown."""
        equity = [100, 110, 120, 130]
        drawdown, duration = calculate_max_drawdown(equity)
        assert drawdown == 0.0
        assert duration == 0

    def test_simple_drawdown(self) -> None:
        """Simple 50% drawdown; duration = periods from peak to trough."""
        equity = [100, 100, 50, 50]
        drawdown, duration = calculate_max_drawdown(equity)
        assert drawdown == pytest.approx(-0.5)
        assert duration == 1  # Peak at index 1, trough at index 2

    def test_multiple_drawdowns(self) -> None:
        """Should find largest drawdown."""
        equity = [100, 90, 100, 80, 100]
        drawdown, _duration = calculate_max_drawdown(equity)
        assert drawdown == pytest.approx(-0.2)

    def test_empty_curve(self) -> None:
        drawdown, duration = calculate_max_drawdown([])
        assert drawdown == 0.0
        assert duration == 0

    def test_single_value(self) -> None:
        drawdown, duration = calculate_max_drawdown([100])
        assert drawdown == 0.0
        assert duration == 0

    def test_negative_equity_raises(self) -> None:
        """A zero/negative equity value means ruin and must fail closed."""
        with pytest.raises(ValueError, match="ruin"):
            calculate_max_drawdown([100_000, 50_000, -10_000])

    def test_zero_equity_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            calculate_max_drawdown([100_000, 0, 50_000])


# ---------------------------------------------------------------------------
# Premium spend calculation
# ---------------------------------------------------------------------------


class TestPremiumSpend:
    """Test premium spend calculation (gross: sum of absolute values)."""

    def test_simple_premium(self) -> None:
        premium = calculate_premium_spend([-1000, -2000, -3000])
        assert premium == 6000.0

    def test_refunds_do_not_offset_gross_spend(self) -> None:
        """Gross spend: a credit never reduces reported premium spend."""
        premium = calculate_premium_spend([-1000, 200, -3000])
        assert premium == 4200.0

    def test_empty_premium(self) -> None:
        premium = calculate_premium_spend([])
        assert premium == 0.0

    def test_annualised_premium(self) -> None:
        annualised = calculate_annualised_premium_spend(6000.0, 3.0)
        assert annualised == pytest.approx(2000.0)

    def test_annualised_premium_zero_years_raises(self) -> None:
        with pytest.raises(ValueError, match="years"):
            calculate_annualised_premium_spend(6000.0, 0.0)

    def test_premium_spend_ratio(self) -> None:
        ratio = calculate_premium_spend_ratio(6000.0, 100_000.0, 3.0)
        assert ratio == pytest.approx(0.02)  # 2% per year

    def test_premium_spend_ratio_invalid_inputs_raise(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            calculate_premium_spend_ratio(6000.0, 0.0, 3.0)


# ---------------------------------------------------------------------------
# Drawdown reduction
# ---------------------------------------------------------------------------


class TestDrawdownReduction:
    def test_improvement(self) -> None:
        improvement = calculate_drawdown_reduction(-0.1, -0.2)
        assert improvement == pytest.approx(0.1)

    def test_no_improvement(self) -> None:
        improvement = calculate_drawdown_reduction(-0.2, -0.2)
        assert improvement == pytest.approx(0.0)

    def test_worse(self) -> None:
        improvement = calculate_drawdown_reduction(-0.3, -0.2)
        assert improvement == pytest.approx(-0.1)


# ---------------------------------------------------------------------------
# Fold utility
# ---------------------------------------------------------------------------


class TestFoldUtility:
    def test_positive_utility(self) -> None:
        utility = calculate_fold_utility(
            hedged_cagr=0.10,
            unhedged_cagr=0.08,
            hedged_max_drawdown=-0.15,
            unhedged_max_drawdown=-0.25,
        )
        # (0.10 - 0.08) + 0.25 * (0.25 - 0.15) = 0.02 + 0.025 = 0.045
        assert utility == pytest.approx(0.045)

    def test_negative_utility(self) -> None:
        utility = calculate_fold_utility(
            hedged_cagr=0.06,
            unhedged_cagr=0.08,
            hedged_max_drawdown=-0.25,
            unhedged_max_drawdown=-0.25,
        )
        assert utility == pytest.approx(-0.02)


# ---------------------------------------------------------------------------
# Tail efficiency
# ---------------------------------------------------------------------------


def _metrics(
    *,
    cagr: float,
    max_drawdown: float,
    total_premium: float,
) -> BacktestMetrics:
    return BacktestMetrics(
        cagr=cagr,
        max_drawdown=max_drawdown,
        max_drawdown_periods=30,
        total_premium_spent=total_premium,
        annualised_premium_spent=total_premium / 10,
        premium_spend_ratio=total_premium / 1_000_000,
        final_value=150_000.0,
        initial_value=100_000.0,
        total_return=0.5,
    )


class TestTailEfficiency:
    def test_positive_efficiency(self) -> None:
        """Drawdown improvement per dollar of gross premium spent."""
        hedged = _metrics(cagr=0.10, max_drawdown=-0.15, total_premium=5000.0)
        baseline = _metrics(cagr=0.08, max_drawdown=-0.25, total_premium=0.0)
        efficiency = calculate_tail_efficiency(hedged, baseline)
        # (0.25 - 0.15) / 5000 = 0.10 / 5000 = 0.00002
        assert efficiency == pytest.approx(0.00002)

    def test_zero_premium_spend(self) -> None:
        """No premium spent -> efficiency 0 (no division by zero)."""
        hedged = _metrics(cagr=0.10, max_drawdown=-0.15, total_premium=0.0)
        baseline = _metrics(cagr=0.08, max_drawdown=-0.25, total_premium=0.0)
        assert calculate_tail_efficiency(hedged, baseline) == 0.0


# ---------------------------------------------------------------------------
# Complete metrics calculation
# ---------------------------------------------------------------------------


class TestCompleteMetrics:
    def test_simple_metrics(self) -> None:
        equity = [100_000, 105_000, 110_000, 115_000, 120_000]
        premiums = [-1000, -1000, -1000, -1000]

        metrics = calculate_metrics(equity, premiums, years=4.0)

        assert metrics.initial_value == 100_000.0
        assert metrics.final_value == 120_000.0
        assert metrics.total_return == pytest.approx(0.2)
        assert metrics.total_premium_spent == pytest.approx(4000.0)
        assert metrics.annualised_premium_spent == pytest.approx(1000.0)
        assert metrics.cagr == pytest.approx((1.2) ** 0.25 - 1)

    def test_metrics_with_custom_initial(self) -> None:
        equity = [100_000, 105_000]
        metrics = calculate_metrics(equity, [], years=1.0, initial_value=50_000.0)

        assert metrics.initial_value == 50_000.0
        assert metrics.final_value == 105_000.0
        assert metrics.total_return == pytest.approx(1.1)  # (105k - 50k) / 50k

    def test_empty_curve_raises(self) -> None:
        """Empty equity curve must fail closed."""
        with pytest.raises(ValueError, match="empty"):
            calculate_metrics([], [], years=1.0)

    def test_zero_years_raises(self) -> None:
        with pytest.raises(ValueError, match="years"):
            calculate_metrics([100_000, 110_000], [], years=0.0)

    def test_drawdown_periods_counted(self) -> None:
        equity = [100, 110, 90, 85, 95]
        metrics = calculate_metrics(equity, [], years=1.0)
        # Peak at index 1 (110), trough at index 3 (85): duration = 2 periods
        assert metrics.max_drawdown_periods == 2
        assert metrics.max_drawdown == pytest.approx(85 / 110 - 1)


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------


class TestBaselineComparison:
    def test_compare_to_baseline(self) -> None:
        hedged = _metrics(cagr=0.10, max_drawdown=-0.15, total_premium=5000.0)
        baseline = _metrics(cagr=0.08, max_drawdown=-0.25, total_premium=0.0)

        comparison = compare_to_baseline(hedged, baseline)

        assert comparison.cagr_delta == pytest.approx(0.02)
        assert comparison.drawdown_improvement == pytest.approx(0.1)
        assert comparison.premium_spend_delta == pytest.approx(5000.0)
        assert comparison.fold_utility == pytest.approx(0.045)
        assert comparison.tail_efficiency == pytest.approx(0.00002)


# ---------------------------------------------------------------------------
# Baseline specs
# ---------------------------------------------------------------------------


class TestBaselineSpecs:
    def test_no_hedge_spec(self) -> None:
        spec = get_baseline_config(BaselineType.NO_HEDGE)
        assert spec.baseline_type == BaselineType.NO_HEDGE
        assert spec.name == "No Hedge"

    def test_lower_equity_spec(self) -> None:
        spec = get_baseline_config(BaselineType.LOWER_EQUITY)
        assert spec.equity_allocation == pytest.approx(0.7)
        assert spec.cash_allocation == pytest.approx(0.3)

    def test_fixed_put_spec_is_pput_like(self) -> None:
        spec = get_baseline_config(BaselineType.FIXED_PUT)
        assert spec.target_dte == 90
        assert spec.moneyness == pytest.approx(0.95)
        assert spec.budget_pct == pytest.approx(0.01)
        assert "PPUT" in spec.description

    def test_specs_frozen(self) -> None:
        spec = get_baseline_config(BaselineType.FIXED_PUT)
        with pytest.raises(AttributeError):
            spec.budget_pct = 0.5  # type: ignore[misc]

    def test_all_baselines_defined(self) -> None:
        baselines = get_all_baseline_configs()
        assert len(baselines) == 3
        types = {b.baseline_type for b in baselines}
        assert types == {
            BaselineType.NO_HEDGE,
            BaselineType.LOWER_EQUITY,
            BaselineType.FIXED_PUT,
        }

    def test_default_specs_match_getter(self) -> None:
        assert get_baseline_config(BaselineType.FIXED_PUT) == FIXED_PUT_SPEC
        assert isinstance(BaselineSpec, type)  # sanity: frozen spec type
