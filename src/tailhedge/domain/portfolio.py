"""Portfolio exposure calculation service.

Implements FR-001: portfolio definition and hedge mapping.
Calculates portfolio value, hedge-eligible value, benchmark-equivalent exposure,
and mapping coverage. Surfaces warnings for unmapped non-cash holdings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tailhedge.persistence.models import HoldingDefinition, Portfolio


@dataclass(frozen=True)
class HoldingExposure:
    """Exposure calculation result for a single holding."""

    holding_id: str
    instrument_key: str
    display_name: str
    asset_class: str
    currency: str
    market_value: float
    hedge_eligible: bool
    hedge_benchmark: str | None
    hedge_beta: float | None
    benchmark_equivalent: float | None
    is_mapped: bool
    warning: str | None


@dataclass(frozen=True)
class PortfolioExposureSummary:
    """Complete portfolio exposure calculation result."""

    portfolio_id: str
    portfolio_name: str
    base_currency: str
    total_value: float
    hedge_eligible_value: float
    total_benchmark_equivalent: float
    weighted_average_beta: float
    mapping_coverage: float
    holdings: list[HoldingExposure]
    warnings: list[str]


def calculate_holding_exposure(
    holding: HoldingDefinition,
    market_value: float,
) -> HoldingExposure:
    """Calculate exposure for a single holding.

    Parameters
    ----------
    holding : HoldingDefinition
        The holding definition from the database.
    market_value : float
        Current market value of the holding in its local currency.

    Returns
    -------
    HoldingExposure
        Calculated exposure with benchmark equivalent and warnings.
    """
    is_mapped = (
        holding.hedge_eligible
        and holding.hedge_benchmark is not None
        and holding.hedge_beta is not None
    )
    benchmark_equivalent: float | None = None
    warning: str | None = None

    if holding.hedge_eligible:
        if holding.hedge_benchmark is None:
            warning = (
                f"Holding '{holding.display_name}' ({holding.instrument_key}) "
                f"is marked hedge-eligible but has no benchmark mapping"
            )
        elif holding.hedge_beta is None:
            warning = (
                f"Holding '{holding.display_name}' ({holding.instrument_key}) "
                f"is marked hedge-eligible but has no beta value"
            )
        else:
            benchmark_equivalent = market_value * holding.hedge_beta
    elif holding.asset_class != "CASH" and market_value > 0:
        warning = (
            f"Holding '{holding.display_name}' ({holding.instrument_key}) "
            f"is not hedge-eligible and will be excluded from hedge sizing"
        )

    return HoldingExposure(
        holding_id=str(holding.id),
        instrument_key=holding.instrument_key,
        display_name=holding.display_name,
        asset_class=holding.asset_class,
        currency=holding.currency,
        market_value=market_value,
        hedge_eligible=holding.hedge_eligible,
        hedge_benchmark=holding.hedge_benchmark,
        hedge_beta=holding.hedge_beta,
        benchmark_equivalent=benchmark_equivalent,
        is_mapped=is_mapped,
        warning=warning,
    )


def calculate_portfolio_exposure(
    portfolio: Portfolio,
    holdings_with_values: Sequence[tuple[HoldingDefinition, float]],
) -> PortfolioExposureSummary:
    """Calculate complete portfolio exposure summary.

    Parameters
    ----------
    portfolio : Portfolio
        The portfolio definition from the database.
    holdings_with_values : list[tuple[HoldingDefinition, float]]
        List of (holding_definition, market_value) tuples.

    Returns
    -------
    PortfolioExposureSummary
        Complete exposure calculation with all metrics and warnings.
    """
    holdings: list[HoldingExposure] = []
    total_value = 0.0
    hedge_eligible_value = 0.0
    total_benchmark_equivalent = 0.0
    warnings: list[str] = []

    for holding, market_value in holdings_with_values:
        exposure = calculate_holding_exposure(holding, market_value)
        holdings.append(exposure)

        total_value += market_value

        if exposure.hedge_eligible:
            hedge_eligible_value += market_value
            if exposure.benchmark_equivalent is not None:
                total_benchmark_equivalent += exposure.benchmark_equivalent

        if exposure.warning is not None:
            warnings.append(exposure.warning)

    # Calculate weighted average beta
    weighted_average_beta = 0.0
    if hedge_eligible_value > 0:
        weighted_average_beta = total_benchmark_equivalent / hedge_eligible_value

    # Calculate mapping coverage
    eligible_holdings = [h for h in holdings if h.hedge_eligible]
    mapped_holdings = [h for h in eligible_holdings if h.is_mapped]
    mapping_coverage = 0.0
    if eligible_holdings:
        mapping_coverage = len(mapped_holdings) / len(eligible_holdings)

    return PortfolioExposureSummary(
        portfolio_id=str(portfolio.id),
        portfolio_name=portfolio.name,
        base_currency=portfolio.base_currency,
        total_value=total_value,
        hedge_eligible_value=hedge_eligible_value,
        total_benchmark_equivalent=total_benchmark_equivalent,
        weighted_average_beta=weighted_average_beta,
        mapping_coverage=mapping_coverage,
        holdings=holdings,
        warnings=warnings,
    )
