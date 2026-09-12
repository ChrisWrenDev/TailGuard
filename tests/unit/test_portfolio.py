"""Unit tests for portfolio exposure calculations (T-001, GF-005).

Tests portfolio value, hedge-eligible value, benchmark-equivalent exposure,
mapping coverage, and unmapped holding warnings.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from tailhedge.data.fixtures import (
    GF005_TOTAL_BENCHMARK_EQUIVALENT,
    GF005_TOTAL_PORTFOLIO_VALUE,
    GF005_WEIGHTED_AVERAGE_BETA,
)
from tailhedge.domain.portfolio import (
    calculate_holding_exposure,
    calculate_portfolio_exposure,
)


def _make_portfolio(
    name: str = "Test Portfolio",
    base_currency: str = "USD",
) -> MagicMock:
    """Create a mock portfolio object."""
    portfolio = MagicMock()
    portfolio.id = uuid.uuid4()
    portfolio.name = name
    portfolio.base_currency = base_currency
    portfolio.status = "ACTIVE"
    return portfolio


def _make_holding(
    instrument_key: str = "SPY",
    display_name: str = "SPY ETF",
    asset_class: str = "ETF",
    currency: str = "USD",
    hedge_eligible: bool = True,
    hedge_benchmark: str | None = "SPX",
    hedge_beta: float | None = 1.0,
) -> MagicMock:
    """Create a mock holding definition object."""
    holding = MagicMock()
    holding.id = uuid.uuid4()
    holding.instrument_key = instrument_key
    holding.display_name = display_name
    holding.asset_class = asset_class
    holding.currency = currency
    holding.hedge_eligible = hedge_eligible
    holding.hedge_benchmark = hedge_benchmark
    holding.hedge_beta = hedge_beta
    return holding


# ---------------------------------------------------------------------------
# T-001: Portfolio exposure and unmapped-holding warnings
# ---------------------------------------------------------------------------


class TestHoldingExposure:
    """Test individual holding exposure calculation."""

    def test_mapped_holding_exposure(self) -> None:
        """A fully mapped hedge-eligible holding should have benchmark equivalent."""
        holding = _make_holding(
            hedge_eligible=True,
            hedge_benchmark="SPX",
            hedge_beta=1.0,
        )
        exposure = calculate_holding_exposure(holding, market_value=50_000.0)

        assert exposure.hedge_eligible is True
        assert exposure.is_mapped is True
        assert exposure.benchmark_equivalent == 50_000.0
        assert exposure.warning is None

    def test_unmapped_holding_eligible_no_benchmark(self) -> None:
        """Holding marked eligible but missing benchmark should warn."""
        holding = _make_holding(
            hedge_eligible=True,
            hedge_benchmark=None,
            hedge_beta=None,
        )
        exposure = calculate_holding_exposure(holding, market_value=10_000.0)

        assert exposure.hedge_eligible is True
        assert exposure.is_mapped is False
        assert exposure.benchmark_equivalent is None
        assert exposure.warning is not None
        assert "no benchmark mapping" in exposure.warning

    def test_unmapped_holding_eligible_no_beta(self) -> None:
        """Holding marked eligible with benchmark but missing beta should warn."""
        holding = _make_holding(
            hedge_eligible=True,
            hedge_benchmark="SPX",
            hedge_beta=None,
        )
        exposure = calculate_holding_exposure(holding, market_value=10_000.0)

        assert exposure.hedge_eligible is True
        assert exposure.is_mapped is False
        assert exposure.benchmark_equivalent is None
        assert exposure.warning is not None
        assert "no beta value" in exposure.warning

    def test_non_eligible_holding_warning(self) -> None:
        """Non-cash, non-eligible holding should warn about exclusion."""
        holding = _make_holding(
            asset_class="EQUITY",
            hedge_eligible=False,
        )
        exposure = calculate_holding_exposure(holding, market_value=5_000.0)

        assert exposure.hedge_eligible is False
        assert exposure.is_mapped is False
        assert exposure.benchmark_equivalent is None
        assert exposure.warning is not None
        assert "not hedge-eligible" in exposure.warning

    def test_cash_holding_no_warning(self) -> None:
        """Cash holding should not generate a warning."""
        holding = _make_holding(
            asset_class="CASH",
            hedge_eligible=False,
        )
        exposure = calculate_holding_exposure(holding, market_value=10_000.0)

        assert exposure.hedge_eligible is False
        assert exposure.is_mapped is False
        assert exposure.warning is None

    def test_zero_value_non_eligible_no_warning(self) -> None:
        """Zero-value non-eligible holding should not warn."""
        holding = _make_holding(
            asset_class="EQUITY",
            hedge_eligible=False,
        )
        exposure = calculate_holding_exposure(holding, market_value=0.0)

        assert exposure.warning is None


class TestPortfolioExposure:
    """Test complete portfolio exposure calculation."""

    def test_total_value_calculation(self) -> None:
        """Total value should be sum of all holding market values."""
        portfolio = _make_portfolio()
        holdings = [
            (_make_holding(instrument_key="A"), 50_000.0),
            (_make_holding(instrument_key="B"), 30_000.0),
            (_make_holding(instrument_key="C"), 20_000.0),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        assert result.total_value == pytest.approx(100_000.0)

    def test_hedge_eligible_value(self) -> None:
        """Hedge-eligible value should sum only eligible holdings."""
        portfolio = _make_portfolio()
        holdings = [
            (_make_holding(instrument_key="A", hedge_eligible=True), 50_000.0),
            (_make_holding(instrument_key="B", hedge_eligible=True), 30_000.0),
            (_make_holding(instrument_key="C", hedge_eligible=False), 20_000.0),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        assert result.hedge_eligible_value == pytest.approx(80_000.0)

    def test_benchmark_equivalent_calculation(self) -> None:
        """Benchmark equivalent should be sum of (value * beta) for eligible holdings."""
        portfolio = _make_portfolio()
        holdings = [
            (_make_holding(instrument_key="A", hedge_beta=1.0), 50_000.0),
            (_make_holding(instrument_key="B", hedge_beta=1.2), 25_000.0),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        # 50000 * 1.0 + 25000 * 1.2 = 50000 + 30000 = 80000
        assert result.total_benchmark_equivalent == pytest.approx(80_000.0)

    def test_weighted_average_beta(self) -> None:
        """Weighted average beta should be total_benchmark / eligible_value."""
        portfolio = _make_portfolio()
        holdings = [
            (_make_holding(instrument_key="A", hedge_beta=1.0), 50_000.0),
            (_make_holding(instrument_key="B", hedge_beta=1.2), 25_000.0),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        # 80000 / 75000 = 1.0666...
        assert result.weighted_average_beta == pytest.approx(80_000.0 / 75_000.0)

    def test_mapping_coverage(self) -> None:
        """Mapping coverage should be mapped/total eligible holdings."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="A", hedge_benchmark="SPX", hedge_beta=1.0
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="B", hedge_benchmark="SPX", hedge_beta=1.0
                ),
                30_000.0,
            ),
            (
                _make_holding(
                    instrument_key="C", hedge_benchmark=None, hedge_beta=None
                ),
                20_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        # 2 mapped out of 3 eligible = 0.666...
        assert result.mapping_coverage == pytest.approx(2 / 3)

    def test_warnings_for_unmapped_holdings(self) -> None:
        """Unmapped non-cash holdings should generate warnings."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="A",
                    hedge_eligible=True,
                    hedge_benchmark="SPX",
                    hedge_beta=1.0,
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="B", hedge_eligible=False, asset_class="EQUITY"
                ),
                30_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        assert len(result.warnings) == 1
        assert "not hedge-eligible" in result.warnings[0]

    def test_no_warnings_when_all_mapped(self) -> None:
        """No warnings when all holdings are properly mapped."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="A", hedge_benchmark="SPX", hedge_beta=1.0
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="B", hedge_benchmark="SPX", hedge_beta=1.0
                ),
                30_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        assert result.warnings == []

    def test_empty_portfolio(self) -> None:
        """Empty portfolio should have zero values."""
        portfolio = _make_portfolio()

        result = calculate_portfolio_exposure(portfolio, [])

        assert result.total_value == 0.0
        assert result.hedge_eligible_value == 0.0
        assert result.total_benchmark_equivalent == 0.0
        assert result.weighted_average_beta == 0.0
        assert result.mapping_coverage == 0.0
        assert result.holdings == []
        assert result.warnings == []


# ---------------------------------------------------------------------------
# GF-005: Basis-risk portfolio
# ---------------------------------------------------------------------------


class TestGF005BasisRiskPortfolio:
    """GF-005: Two holdings with different SPX beta."""

    def test_total_portfolio_value_matches_fixture(self) -> None:
        """Total portfolio value should match GF-005 expected."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="SPY-ETF",
                    display_name="SPY-ETF",
                    hedge_beta=1.0,
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="TECH-ETF",
                    display_name="TECH-ETF",
                    hedge_beta=1.2,
                ),
                15_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        assert result.total_value == pytest.approx(GF005_TOTAL_PORTFOLIO_VALUE)

    def test_total_benchmark_equivalent_matches_fixture(self) -> None:
        """Total benchmark equivalent should match GF-005 expected."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="SPY-ETF",
                    display_name="SPY-ETF",
                    hedge_beta=1.0,
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="TECH-ETF",
                    display_name="TECH-ETF",
                    hedge_beta=1.2,
                ),
                15_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        # 50000 * 1.0 + 15000 * 1.2 = 50000 + 18000 = 68000
        assert result.total_benchmark_equivalent == pytest.approx(
            GF005_TOTAL_BENCHMARK_EQUIVALENT
        )

    def test_weighted_average_beta_matches_fixture(self) -> None:
        """Weighted average beta should match GF-005 expected."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="SPY-ETF",
                    display_name="SPY-ETF",
                    hedge_beta=1.0,
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="TECH-ETF",
                    display_name="TECH-ETF",
                    hedge_beta=1.2,
                ),
                15_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        # 68000 / 65000 = 1.046153...
        assert result.weighted_average_beta == pytest.approx(
            GF005_WEIGHTED_AVERAGE_BETA
        )

    def test_individual_benchmark_equivalents(self) -> None:
        """Each holding should have correct benchmark equivalent."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="SPY-ETF",
                    display_name="SPY-ETF",
                    hedge_beta=1.0,
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="TECH-ETF",
                    display_name="TECH-ETF",
                    hedge_beta=1.2,
                ),
                15_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        spy_exposure = next(h for h in result.holdings if h.instrument_key == "SPY-ETF")
        tech_exposure = next(
            h for h in result.holdings if h.instrument_key == "TECH-ETF"
        )

        assert spy_exposure.benchmark_equivalent == pytest.approx(50_000.0)
        assert tech_exposure.benchmark_equivalent == pytest.approx(18_000.0)

    def test_all_holdings_mapped(self) -> None:
        """All holdings should be mapped in GF-005 scenario."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="SPY-ETF",
                    display_name="SPY-ETF",
                    hedge_benchmark="SPX",
                    hedge_beta=1.0,
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="TECH-ETF",
                    display_name="TECH-ETF",
                    hedge_benchmark="SPX",
                    hedge_beta=1.2,
                ),
                15_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        assert result.mapping_coverage == pytest.approx(1.0)
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestPortfolioExposureEdgeCases:
    """Edge cases for portfolio exposure calculations."""

    def test_all_holdings_non_eligible(self) -> None:
        """Portfolio with no hedge-eligible holdings."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="A", hedge_eligible=False, asset_class="EQUITY"
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="B", hedge_eligible=False, asset_class="FUND"
                ),
                30_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        assert result.total_value == 80_000.0
        assert result.hedge_eligible_value == 0.0
        assert result.total_benchmark_equivalent == 0.0
        assert result.weighted_average_beta == 0.0
        assert result.mapping_coverage == 0.0
        assert len(result.warnings) == 2

    def test_mixed_asset_classes(self) -> None:
        """Portfolio with mixed asset classes."""
        portfolio = _make_portfolio()
        holdings = [
            (
                _make_holding(
                    instrument_key="EQUITY",
                    asset_class="EQUITY",
                    hedge_eligible=True,
                    hedge_beta=1.0,
                ),
                50_000.0,
            ),
            (
                _make_holding(
                    instrument_key="FUND",
                    asset_class="FUND",
                    hedge_eligible=True,
                    hedge_beta=0.8,
                ),
                30_000.0,
            ),
            (
                _make_holding(
                    instrument_key="CASH", asset_class="CASH", hedge_eligible=False
                ),
                20_000.0,
            ),
        ]

        result = calculate_portfolio_exposure(portfolio, holdings)

        assert result.total_value == 100_000.0
        assert result.hedge_eligible_value == 80_000.0
        # 50000 * 1.0 + 30000 * 0.8 = 50000 + 24000 = 74000
        assert result.total_benchmark_equivalent == pytest.approx(74_000.0)

    def test_portfolio_metadata(self) -> None:
        """Portfolio metadata should be preserved in result."""
        portfolio = _make_portfolio(name="My Portfolio", base_currency="GBP")

        result = calculate_portfolio_exposure(portfolio, [])

        assert result.portfolio_name == "My Portfolio"
        assert result.base_currency == "GBP"
