"""Canonical market-data schemas for option and underlying series.

Defines Pydantic models that validate required fields and enforce type constraints.
Schema versioning is managed via a constant that must be bumped when the canonical
schema changes in a backwards-incompatible way.
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class OptionType(StrEnum):
    """Option type enumeration."""

    PUT = "PUT"
    CALL = "CALL"


# Current canonical schema version.  Bump on breaking change.
SCHEMA_VERSION = "1.0"


class CanonicalOptionRow(BaseModel):
    """A single option-chain snapshot row in canonical form.

    Required fields are non-nullable; optional fields accept None.
    The model validates that bid <= ask when both are present and
    that option_type is one of the allowed enum values.
    """

    model_config = {"extra": "forbid", "strict": True}

    snapshot_ts_utc: datetime = Field(
        ..., description="Snapshot timestamp in UTC (microsecond precision)."
    )
    trade_date: date = Field(..., description="Trade date of the snapshot.")
    source: str = Field(..., min_length=1, description="Data vendor/source identifier.")
    underlying_symbol: str = Field(
        ..., min_length=1, description="Underlying instrument symbol."
    )
    root_symbol: str = Field(
        ..., min_length=1, description="Option root symbol (e.g. XSP)."
    )
    expiration_date: date = Field(..., description="Option expiration date.")
    strike: float = Field(..., gt=0, description="Option strike price.")
    option_type: OptionType = Field(..., description="PUT or CALL.")
    bid: float = Field(..., ge=0, description="Best bid price.")
    ask: float = Field(..., ge=0, description="Best ask price.")
    bid_size: int | None = Field(None, ge=0, description="Bid size when available.")
    ask_size: int | None = Field(None, ge=0, description="Ask size when available.")
    volume: int | None = Field(None, ge=0, description="Trading volume when available.")
    open_interest: int | None = Field(
        None, ge=0, description="Open interest when available."
    )
    underlying_price: float = Field(
        ..., gt=0, description="Underlying price/reference at snapshot time."
    )
    implied_volatility: float | None = Field(
        None, ge=0, description="Implied volatility (optional)."
    )
    delta: float | None = Field(None, description="Delta (optional).")
    gamma: float | None = Field(None, ge=0, description="Gamma (optional).")
    theta: float | None = Field(None, description="Theta (optional).")
    vega: float | None = Field(None, ge=0, description="Vega (optional).")
    source_contract_id: str | None = Field(
        None, description="Vendor-specific contract identifier (optional)."
    )

    @model_validator(mode="after")
    def _bid_ask_order(self) -> CanonicalOptionRow:
        if self.ask < self.bid:
            msg = f"ask ({self.ask}) must be >= bid ({self.bid})"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _expiry_after_observation(self) -> CanonicalOptionRow:
        if self.expiration_date <= self.trade_date:
            msg = (
                f"expiration_date ({self.expiration_date}) must be after "
                f"trade_date ({self.trade_date})"
            )
            raise ValueError(msg)
        return self


class CanonicalUnderlyingRow(BaseModel):
    """A single underlying/portfolio series snapshot row in canonical form."""

    model_config = {"extra": "forbid", "strict": True}

    timestamp_utc: datetime = Field(
        ..., description="Timestamp in UTC (microsecond precision)."
    )
    trade_date: date = Field(..., description="Trade date.")
    symbol: str = Field(..., min_length=1, description="Instrument symbol.")
    currency: str = Field(
        ..., min_length=3, max_length=3, description="ISO 4217 currency code."
    )
    open: float | None = Field(None, description="Open price (optional).")
    high: float | None = Field(None, description="High price (optional).")
    low: float | None = Field(None, description="Low price (optional).")
    close: float = Field(..., description="Close price (required).")
    adjusted_close: float | None = Field(None, description="Adjusted close (optional).")
    total_return_index: float | None = Field(
        None, ge=0, description="Total return index (optional)."
    )
    source: str = Field(..., min_length=1, description="Data vendor/source identifier.")

    @model_validator(mode="after")
    def _high_low_order(self) -> CanonicalUnderlyingRow:
        if self.high is not None and self.low is not None and self.high < self.low:
            msg = f"high ({self.high}) must be >= low ({self.low})"
            raise ValueError(msg)
        return self
