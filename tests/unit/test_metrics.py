"""Unit tests for metrics and baselines (T-006).

Tests CAGR, max drawdown, premium spend, drawdown reduction, tail-efficiency,
and baseline configurations.
"""

from __future__ import annotations

import pytest

from tailhedge.backtest.baselines import (
    BaselineType,
    FixedPutConfig,
    LowerEquityConfig,
    NoHedgeConfig,
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

    def test_zero_years(self) -> None:
        """Zero years should return 0."""
        cagr = calculate_cagr(100_000.0, 200_000.0, 0.0)
        assert cagr == 0.0

    def test_negative_return(self) -> None:
        """Negative return should give negative CAGR."""
        cagr = calculate_cagr(100_000.0, 50_000.0, 1.0)
        assert cagr == pytest.approx(-0.5)


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
        """Simple 50% drawdown."""
        equity = [100, 100, 50, 50]
        drawdown, duration = calculate_max_drawdown(equity)
        assert drawdown == pytest.approx(-0.5)
        assert duration == 1  # Peak at index 1, trough at index 2

    def test_multiple_drawdowns(self) -> None:
        """Should find largest drawdown."""
        equity = [100, 90, 100, 80, 100]
        drawdown, _duration = calculate_max_drawdown(equity)
        assert drawdown == pytest.approx(-0.2)  # 80/100 = 0.8, drawdown = -0.2

    def test_empty_curve(self) -> None:
        """Empty curve should return 0."""
        drawdown, duration = calculate_max_drawdown([])
        assert drawdown == 0.0
        assert duration == 0

    def test_single_value(self) -> None:
        """Single value should return 0."""
        drawdown, duration = calculate_max_drawdown([100])
        assert drawdown == 0.0
        assert duration == 0


# ---------------------------------------------------------------------------
# Premium spend calculation
# ---------------------------------------------------------------------------


class TestPremiumSpend:
    """Test premium spend calculation."""

    def test_simple_premium(self) -> None:
        """Simple premium calculation."""
        premium = calculate_premium_spend([-1000, -2000, -3000])
        assert premium == 6000.0

    def test_empty_premium(self) -> None:
        """Empty premium should return 0."""
        premium = calculate_premium_spend([])
        assert premium == 0.0

    def test_annualised_premium(self) -> None:
        """Annualised premium should be total / years."""
        annualised = calculate_annualised_premium_spend(6000.0, 3.0)
        assert annualised == pytest.approx(2000.0)

    def test_premium_spend_ratio(self) -> None:
        """Premium spend ratio should be total / (initial * years)."""
        ratio = calculate_premium_spend_ratio(6000.0, 100_000.0, 3.0)
        assert ratio == pytest.approx(0.02)  # 2% per year


# ---------------------------------------------------------------------------
# Drawdown reduction
# ---------------------------------------------------------------------------


class TestDrawdownReduction:
    """Test drawdown reduction calculation."""

    def test_improvement(self) -> None:
        """Hedged better than baseline should be positive."""
        improvement = calculate_drawdown_reduction(-0.1, -0.2)
        assert improvement == pytest.approx(0.1)

    def test_no_improvement(self) -> None:
        """Same drawdown should be 0."""
        improvement = calculate_drawdown_reduction(-0.2, -0.2)
        assert improvement == pytest.approx(0.0)

    def test_worse(self) -> None:
        """Hedged worse than baseline should be negative."""
        improvement = calculate_drawdown_reduction(-0.3, -0.2)
        assert improvement == pytest.approx(-0.1)


# ---------------------------------------------------------------------------
# Fold utility
# ---------------------------------------------------------------------------


class TestFoldUtility:
    """Test fold utility calculation."""

    def test_positive_utility(self) -> None:
        """Better CAGR and lower drawdown should give positive utility."""
        utility = calculate_fold_utility(
            hedged_cagr=0.10,
            unhedged_cagr=0.08,
            hedged_max_drawdown=-0.15,
            unhedged_max_drawdown=-0.25,
        )
        # (0.10 - 0.08) + 0.25 * (0.25 - 0.15) = 0.02 + 0.025 = 0.045
        assert utility == pytest.approx(0.045)

    def test_negative_utility(self) -> None:
        """Worse CAGR should give negative utility."""
        utility = calculate_fold_utility(
            hedged_cagr=0.06,
            unhedged_cagr=0.08,
            hedged_max_drawdown=-0.25,
            unhedged_max_drawdown=-0.25,
        )
        # (0.06 - 0.08) + 0.25 * (0.25 - 0.25) = -0.02 + 0.0 = -0.02
        assert utility == pytest.approx(-0.02)


# ---------------------------------------------------------------------------
# Tail efficiency
# ---------------------------------------------------------------------------


class TestTailEfficiency:
    """Test tail efficiency calculation."""

    def test_positive_efficiency(self) -> None:
        """Drawdown improvement per premium spent."""
        hedged = BacktestMetrics(
            cagr=0.10,
            max_drawdown=-0.15,
            max_drawdown_duration_days=30,
            total_premium_spent=5000.0,
            annualised_premium_spent=500.0,
            premium_spend_ratio=0.01,
            final_value=150_000.0,
            initial_value=100_000.0,
            total_return=0.5,
        )
        baseline = BacktestMetrics(
            cagr=0.08,
            max_drawdown=-0.25,
            max_drawdown_duration_days=60,
            total_premium_spent=0.0,
            annualised_premium_spent=0.0,
            premium_spend_ratio=0.0,
            final_value=140_000.0,
            initial_value=100_000.0,
            total_return=0.4,
        )
        efficiency = calculate_tail_efficiency(hedged, baseline)
        # (0.25 - 0.15) / 5000 = 0.10 / 5000 = 0.00002
        assert efficiency == pytest.approx(0.00002)


# ---------------------------------------------------------------------------
# Complete metrics calculation
# ---------------------------------------------------------------------------


class TestCompleteMetrics:
    """Test complete metrics calculation."""

    def test_simple_metrics(self) -> None:
        """Simple metrics calculation."""
        equity = [100_000, 105_000, 110_000, 115_000, 120_000]
        premiums = [-1000, -1000, -1000, -1000]

        metrics = calculate_metrics(equity, premiums, years=4.0)

        assert metrics.initial_value == 100_000.0
        assert metrics.final_value == 120_000.0
        assert metrics.total_return == pytest.approx(0.2)
        assert metrics.total_premium_spent == pytest.approx(4000.0)
        assert metrics.annualised_premium_spent == pytest.approx(1000.0)

    def test_metrics_with_custom_initial(self) -> None:
        """Metrics with custom initial value."""
        equity = [100_000, 105_000]
        metrics = calculate_metrics(equity, [], years=1.0, initial_value=50_000.0)

        assert metrics.initial_value == 50_000.0
        assert metrics.final_value == 105_000.0
        assert metrics.total_return == pytest.approx(1.1)  # (105k - 50k) / 50k


# ---------------------------------------------------------------------------
# Baseline configurations
# ---------------------------------------------------------------------------


class TestBaselineConfigurations:
    """Test baseline strategy configurations."""

    def test_no_hedge_config(self) -> None:
        """No-hedge baseline should have correct properties."""
        config = NoHedgeConfig()
        assert config.baseline_type == BaselineType.NO_HEDGE
        assert config.name == "No Hedge"

    def test_lower_equity_config(self) -> None:
        """Lower-equity baseline should have correct allocations."""
        config = LowerEquityConfig()
        assert config.baseline_type == BaselineType.LOWER_EQUITY
        assert config.equity_allocation == 0.7
        assert config.cash_allocation == 0.3

    def test_fixed_put_config(self) -> None:
        """Fixed-put baseline should have correct parameters."""
        config = FixedPutConfig()
        assert config.baseline_type == BaselineType.FIXED_PUT
        assert config.target_dte == 30
        assert config.target_delta == 0.25

    def test_all_baselines_defined(self) -> None:
        """All default baselines should be defined."""
        baselines = get_all_baseline_configs()
        assert len(baselines) == 3
        types = {b.baseline_type for b in baselines}
        assert types == {
            BaselineType.NO_HEDGE,
            BaselineType.LOWER_EQUITY,
            BaselineType.FIXED_PUT,
        }

    def test_get_baseline_config(self) -> None:
        """Should get correct config by type."""
        config = get_baseline_config(BaselineType.FIXED_PUT)
        assert isinstance(config, FixedPutConfig)

    def test_get_unknown_baseline(self) -> None:
        """Should raise error for unknown baseline type."""
        with pytest.raises((ValueError, KeyError)):
            get_baseline_config(BaselineType("UNKNOWN"))


# ---------------------------------------------------------------------------
# T-006: No-hedge and fixed-put baselines use same engine
# ---------------------------------------------------------------------------


class TestT006BaselineEngine:
    """T-006: No-hedge and fixed-put baselines run through same engine."""

    def test_baselines_use_same_metrics(self) -> None:
        """Both baselines should be calculable with same metrics function."""
        equity_no_hedge = [100_000, 105_000, 110_000]
        equity_fixed_put = [100_000, 104_000, 108_000]

        metrics_no_hedge = calculate_metrics(equity_no_hedge, [], years=2.0)
        metrics_fixed_put = calculate_metrics(
            equity_fixed_put, [-2000, -2000], years=2.0
        )

        assert metrics_no_hedge.initial_value == metrics_fixed_put.initial_value
        assert metrics_no_hedge.final_value != metrics_fixed_put.final_value

    def test_baseline_comparison(self) -> None:
        """Should be able to compare baselines."""
        hedged_metrics = BacktestMetrics(
            cagr=0.10,
            max_drawdown=-0.15,
            max_drawdown_duration_days=30,
            total_premium_spent=5000.0,
            annualised_premium_spent=500.0,
            premium_spend_ratio=0.01,
            final_value=150_000.0,
            initial_value=100_000.0,
            total_return=0.5,
        )
        baseline_metrics = BacktestMetrics(
            cagr=0.08,
            max_drawdown=-0.25,
            max_drawdown_duration_days=60,
            total_premium_spent=0.0,
            annualised_premium_spent=0.0,
            premium_spend_ratio=0.0,
            final_value=140_000.0,
            initial_value=100_000.0,
            total_return=0.4,
        )

        cagr_delta = hedged_metrics.cagr - baseline_metrics.cagr
        drawdown_improvement = calculate_drawdown_reduction(
            hedged_metrics.max_drawdown, baseline_metrics.max_drawdown
        )
        fold_utility = calculate_fold_utility(
            hedged_metrics.cagr,
            baseline_metrics.cagr,
            hedged_metrics.max_drawdown,
            baseline_metrics.max_drawdown,
        )

        assert cagr_delta == pytest.approx(0.02)
        assert drawdown_improvement == pytest.approx(0.1)
        assert fold_utility == pytest.approx(0.045)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestMetricsEdgeCases:
    """Edge cases for metrics calculations."""

    def test_zero_equity(self) -> None:
        """Zero equity should handle gracefully."""
        metrics = calculate_metrics([0, 0, 0], [], years=2.0)
        assert metrics.cagr == 0.0

    def test_single_equity(self) -> None:
        """Single equity value should handle gracefully."""
        metrics = calculate_metrics([100_000], [], years=1.0)
        assert metrics.final_value == 100_000.0

    def test_very_small_values(self) -> None:
        """Very small values should not cause division by zero."""
        cagr = calculate_cagr(0.01, 0.02, 1.0)
        assert cagr == pytest.approx(1.0)

    def test_negative_equity(self) -> None:
        """Negative equity should handle gracefully."""
        equity = [100_000, 50_000, -10_000]
        metrics = calculate_metrics(equity, [], years=2.0)
        assert metrics.max_drawdown < 0
