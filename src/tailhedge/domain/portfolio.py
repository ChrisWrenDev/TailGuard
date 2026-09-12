"""Portfolio exposure calculation service.

Implements FR-001: portfolio definition and hedge mapping.
Calculates portfolio value, hedge-eligible value, benchmark-equivalent exposure,
and mapping coverage. Surfaces warnings for unmapped non-cash holdings.

Currency rule (INV-010): values in different currencies are never summed.
When holdings span multiple currencies, an explicit ``fx_to_base`` mapping
(currency -> rate: one unit of that currency expressed in the portfolio's
base currency) must be provided; otherwise the calculation fails closed
with a ValueError rather than silently mixing currencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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
    elif holding.asset_class != "CASH":
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
    fx_to_base: Mapping[str, float] | None = None,
) -> PortfolioExposureSummary:
    """Calculate complete portfolio exposure summary.

    Parameters
    ----------
    portfolio : Portfolio
        The portfolio definition from the database.
    holdings_with_values : list[tuple[HoldingDefinition, float]]
        List of (holding_definition, market_value) tuples, with values in
        each holding's own currency.
    fx_to_base : Mapping[str, float] | None
        Explicit FX rates: for each currency, how many units of the
        portfolio base currency one unit of that currency is worth.
        Required when holdings span more than one currency (INV-010);
        absent rates for a present currency fail closed.

    Returns
    -------
    PortfolioExposureSummary
        Complete exposure calculation with all metrics and warnings. All
        values are expressed in the portfolio base currency.

    Raises
    ------
    ValueError
        If holdings mix currencies without a complete ``fx_to_base`` mapping.
    """
    currencies = {holding.currency for holding, _ in holdings_with_values}
    non_base_currencies = currencies - {portfolio.base_currency}
    needs_fx = bool(non_base_currencies)
    if needs_fx:
        if fx_to_base is None:
            msg = (
                f"Holdings mix currencies {sorted(currencies)} but no fx_to_base "
                f"rates were provided; refusing to combine values without "
                f"explicit FX input (INV-010)"
            )
            raise ValueError(msg)
        missing = non_base_currencies - set(fx_to_base)
        if missing:
            msg = f"Missing fx_to_base rates for currencies: {sorted(missing)}"
            raise ValueError(msg)

    def _to_base(market_value: float, currency: str) -> float:
        if currency == portfolio.base_currency:
            return market_value
        rate = (fx_to_base or {}).get(currency)
        if rate is None:
            msg = f"Missing fx_to_base rate for currency {currency}"
            raise ValueError(msg)
        return market_value * rate

    holdings: list[HoldingExposure] = []
    total_value = 0.0
    hedge_eligible_value = 0.0
    mapped_eligible_value = 0.0
    total_benchmark_equivalent = 0.0
    warnings: list[str] = []

    for holding, market_value in holdings_with_values:
        exposure = calculate_holding_exposure(holding, market_value)
        holdings.append(exposure)

        total_value += _to_base(market_value, holding.currency)

        if exposure.hedge_eligible:
            hedge_eligible_value += _to_base(market_value, holding.currency)
            if exposure.benchmark_equivalent is not None:
                mapped_eligible_value += _to_base(market_value, holding.currency)
                total_benchmark_equivalent += _to_base(
                    exposure.benchmark_equivalent, holding.currency
                )

        if exposure.warning is not None:
            warnings.append(exposure.warning)

    # Weighted average beta is weighted over *mapped* eligible value only,
    # so eligible-but-unmapped holdings do not dilute the beta of the
    # portion that is actually hedgeable.
    weighted_average_beta = 0.0
    if mapped_eligible_value > 0:
        weighted_average_beta = total_benchmark_equivalent / mapped_eligible_value

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
