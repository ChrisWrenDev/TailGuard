"""Canonical market-data schemas for option and underlying series.

Defines Pydantic models that validate required fields and enforce type constraints.
Schema versioning is managed via a constant that must be bumped when the canonical
schema changes in a backwards-incompatible way.

All timestamps are enforced tz-aware and UTC (offset zero), matching the
``timestamp[us, UTC]`` physical type in DATA_MODEL.md; vendor local times must
be normalised to UTC before a row can enter the canonical layer (FR-003).
"""

from __future__ import annotations

import re
from datetime import date, datetime  # noqa: TC003
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class OptionType(StrEnum):
    """Option type enumeration."""

    PUT = "PUT"
    CALL = "CALL"


# Current canonical schema version.  Bump on breaking change.
SCHEMA_VERSION = "1.0"

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _validate_utc(name: str, value: datetime) -> datetime:
    """Require a timezone-aware datetime at offset zero (UTC)."""
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{name} must be timezone-aware (UTC); got a naive datetime"
        raise ValueError(msg)
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        msg = f"{name} must be expressed in UTC (offset zero); got offset {offset}"
        raise ValueError(msg)
    return value


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

    @field_validator("snapshot_ts_utc", mode="after")
    @classmethod
    def _snapshot_ts_is_utc(cls, value: datetime) -> datetime:
        return _validate_utc("snapshot_ts_utc", value)

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
        ...,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 currency code (three uppercase letters).",
    )
    open: float | None = Field(None, gt=0, description="Open price (optional).")
    high: float | None = Field(None, gt=0, description="High price (optional).")
    low: float | None = Field(None, gt=0, description="Low price (optional).")
    close: float = Field(..., gt=0, description="Close price (required, positive).")
    adjusted_close: float | None = Field(
        None, gt=0, description="Adjusted close (optional)."
    )
    total_return_index: float | None = Field(
        None, ge=0, description="Total return index (optional)."
    )
    source: str = Field(..., min_length=1, description="Data vendor/source identifier.")

    @field_validator("timestamp_utc", mode="after")
    @classmethod
    def _timestamp_is_utc(cls, value: datetime) -> datetime:
        return _validate_utc("timestamp_utc", value)

    @model_validator(mode="after")
    def _ohlc_consistency(self) -> CanonicalUnderlyingRow:
        if self.high is not None and self.low is not None and self.high < self.low:
            msg = f"high ({self.high}) must be >= low ({self.low})"
            raise ValueError(msg)
        if self.high is not None and self.close > self.high:
            msg = f"close ({self.close}) must be <= high ({self.high})"
            raise ValueError(msg)
        if self.low is not None and self.close < self.low:
            msg = f"close ({self.close}) must be >= low ({self.low})"
            raise ValueError(msg)
        if self.open is not None and self.high is not None and self.open > self.high:
            msg = f"open ({self.open}) must be <= high ({self.high})"
            raise ValueError(msg)
        if self.open is not None and self.low is not None and self.open < self.low:
            msg = f"open ({self.open}) must be >= low ({self.low})"
            raise ValueError(msg)
        return self
