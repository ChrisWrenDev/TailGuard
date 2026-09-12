"""Baseline strategies for comparison.

Implements FR-005: immutable comparison baselines.
All baselines use the same accounting/cost model as candidate strategies.

Baselines:
1. No hedge - core portfolio only
2. Lower-equity/cash allocation - static allocation
3. Fixed mechanical put hedge - configurable DTE/moneyness, roll rule, budget
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BaselineType(StrEnum):
    """Types of baseline strategies."""

    NO_HEDGE = "NO_HEDGE"
    LOWER_EQUITY = "LOWER_EQUITY"
    FIXED_PUT = "FIXED_PUT"


@dataclass(frozen=True)
class BaselineConfig:
    """Configuration for baseline strategies."""

    baseline_type: BaselineType
    name: str
    description: str


@dataclass(frozen=True)
class NoHedgeConfig(BaselineConfig):
    """Configuration for no-hedge baseline."""

    def __init__(self) -> None:
        super().__init__(
            baseline_type=BaselineType.NO_HEDGE,
            name="No Hedge",
            description="Core portfolio only, no put overlay",
        )


@dataclass(frozen=True)
class LowerEquityConfig(BaselineConfig):
    """Configuration for lower-equity baseline."""

    equity_allocation: float = 0.7  # 70% equity
    cash_allocation: float = 0.3  # 30% cash

    def __init__(
        self, equity_allocation: float = 0.7, cash_allocation: float = 0.3
    ) -> None:
        object.__setattr__(self, "baseline_type", BaselineType.LOWER_EQUITY)
        object.__setattr__(self, "name", "Lower Equity/Cash")
        object.__setattr__(
            self,
            "description",
            f"{equity_allocation:.0%} equity, {cash_allocation:.0%} cash",
        )
        object.__setattr__(self, "equity_allocation", equity_allocation)
        object.__setattr__(self, "cash_allocation", cash_allocation)


@dataclass(frozen=True)
class FixedPutConfig(BaselineConfig):
    """Configuration for fixed put baseline."""

    target_dte: int = 30  # Days to expiry target
    target_delta: float = 0.25  # Target delta (put)
    roll_dte_threshold: int = 7  # Roll when DTE <= this
    budget_pct: float = 0.01  # 1% of portfolio value per year

    def __init__(
        self,
        target_dte: int = 30,
        target_delta: float = 0.25,
        roll_dte_threshold: int = 7,
        budget_pct: float = 0.01,
    ) -> None:
        object.__setattr__(self, "baseline_type", BaselineType.FIXED_PUT)
        object.__setattr__(self, "name", "Fixed Put Hedge")
        object.__setattr__(
            self,
            "description",
            f"DTE={target_dte}, delta={target_delta}, budget={budget_pct:.1%}",
        )
        object.__setattr__(self, "target_dte", target_dte)
        object.__setattr__(self, "target_delta", target_delta)
        object.__setattr__(self, "roll_dte_threshold", roll_dte_threshold)
        object.__setattr__(self, "budget_pct", budget_pct)


# Default baseline configurations
DEFAULT_BASELINES = [
    NoHedgeConfig(),
    LowerEquityConfig(),
    FixedPutConfig(),
]


def get_baseline_config(baseline_type: BaselineType) -> BaselineConfig:
    """Get default configuration for a baseline type.

    Parameters
    ----------
    baseline_type : BaselineType
        Type of baseline.

    Returns
    -------
    BaselineConfig
        Default configuration for the baseline.
    """
    for config in DEFAULT_BASELINES:
        if config.baseline_type == baseline_type:
            return config
    msg = f"Unknown baseline type: {baseline_type}"
    raise ValueError(msg)


def get_all_baseline_configs() -> list[BaselineConfig]:
    """Get all default baseline configurations.

    Returns
    -------
    list[BaselineConfig]
        List of all baseline configurations.
    """
    return list(DEFAULT_BASELINES)
