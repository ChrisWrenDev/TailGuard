"""Unit tests for canonical option and underlying schemas."""

from __future__ import annotations

from datetime import UTC, date, datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from tailhedge.data.canonical_schema import (
    SCHEMA_VERSION,
    CanonicalOptionRow,
    CanonicalUnderlyingRow,
    OptionType,
)

# ---------------------------------------------------------------------------
# CanonicalOptionRow
# ---------------------------------------------------------------------------


class TestCanonicalOptionRow:
    """Validation tests for the option-chain canonical row."""

    def test_valid_put_row(self) -> None:
        row = CanonicalOptionRow(
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
            trade_date=date(2025, 1, 15),
            source="CBOE",
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=500.0,
            option_type=OptionType.PUT,
            bid=10.5,
            ask=11.0,
            underlying_price=5000.0,
        )
        assert row.option_type == OptionType.PUT
        assert row.bid == 10.5
        assert row.ask == 11.0

    def test_valid_call_row(self) -> None:
        row = CanonicalOptionRow(
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
            trade_date=date(2025, 1, 15),
            source="ORATS",
            underlying_symbol="SPX",
            root_symbol="SPX",
            expiration_date=date(2025, 3, 21),
            strike=5200.0,
            option_type=OptionType.CALL,
            bid=5.0,
            ask=5.5,
            underlying_price=5100.0,
            bid_size=10,
            ask_size=20,
            volume=100,
            open_interest=500,
            implied_volatility=0.20,
            delta=0.45,
            gamma=0.01,
            theta=-0.05,
            vega=0.15,
            source_contract_id="V123",
        )
        assert row.option_type == OptionType.CALL
        assert row.source_contract_id == "V123"

    def test_bid_equals_ask(self) -> None:
        row = CanonicalOptionRow(
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
            trade_date=date(2025, 1, 15),
            source="CBOE",
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=500.0,
            option_type=OptionType.PUT,
            bid=10.0,
            ask=10.0,
            underlying_price=5000.0,
        )
        assert row.bid == row.ask

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 2, 21),
                strike=500.0,
                option_type=OptionType.PUT,
                # bid missing
                ask=11.0,  # type: ignore[call-arg]
                underlying_price=5000.0,
            )

    def test_negative_bid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 2, 21),
                strike=500.0,
                option_type=OptionType.PUT,
                bid=-1.0,
                ask=11.0,
                underlying_price=5000.0,
            )

    def test_ask_less_than_bid_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"ask.*must be >= bid"):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 2, 21),
                strike=500.0,
                option_type=OptionType.PUT,
                bid=12.0,
                ask=11.0,
                underlying_price=5000.0,
            )

    def test_expiration_before_trade_date_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"expiration_date.*must be after"):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 1, 10),
                strike=500.0,
                option_type=OptionType.PUT,
                bid=10.0,
                ask=11.0,
                underlying_price=5000.0,
            )

    def test_invalid_option_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 2, 21),
                strike=500.0,
                option_type="STRADDLE",  # type: ignore[arg-type]
                bid=10.0,
                ask=11.0,
                underlying_price=5000.0,
            )

    def test_zero_strike_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 2, 21),
                strike=0.0,
                option_type=OptionType.PUT,
                bid=10.0,
                ask=11.0,
                underlying_price=5000.0,
            )

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 2, 21),
                strike=500.0,
                option_type=OptionType.PUT,
                bid=10.0,
                ask=11.0,
                underlying_price=5000.0,
                surprise_field="oops",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# CanonicalUnderlyingRow
# ---------------------------------------------------------------------------


class TestCanonicalUnderlyingRow:
    """Validation tests for the underlying series canonical row."""

    def test_valid_row(self) -> None:
        row = CanonicalUnderlyingRow(
            timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
            trade_date=date(2025, 1, 15),
            symbol="SPX",
            currency="USD",
            close=5000.0,
            source="CBOE",
        )
        assert row.close == 5000.0

    def test_valid_with_optional_fields(self) -> None:
        row = CanonicalUnderlyingRow(
            timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
            trade_date=date(2025, 1, 15),
            symbol="SPX",
            currency="USD",
            open=4990.0,
            high=5010.0,
            low=4980.0,
            close=5000.0,
            adjusted_close=5000.0,
            total_return_index=10000.0,
            source="CBOE",
        )
        assert row.high == 5010.0
        assert row.low == 4980.0

    def test_high_less_than_low_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"high.*must be >= low"):
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                currency="USD",
                high=4980.0,
                low=5010.0,
                close=5000.0,
                source="CBOE",
            )

    def test_missing_close_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                currency="USD",
                source="CBOE",
            )  # type: ignore[call-arg]

    def test_invalid_currency_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                currency="US",  # too short
                close=5000.0,
                source="CBOE",
            )


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


def test_schema_version_is_string() -> None:
    assert isinstance(SCHEMA_VERSION, str)
    assert "." in SCHEMA_VERSION


def test_option_type_enum_members() -> None:
    assert OptionType.PUT == "PUT"
    assert OptionType.CALL == "CALL"


# ---------------------------------------------------------------------------
# UTC enforcement (FR-003)
# ---------------------------------------------------------------------------


class TestTimestampUTCEnforcement:
    """Timestamps must be tz-aware and UTC (offset zero)."""

    def _option_kwargs(self, ts: datetime) -> dict[str, Any]:
        return {
            "snapshot_ts_utc": ts,
            "trade_date": date(2025, 1, 15),
            "source": "CBOE",
            "underlying_symbol": "SPX",
            "root_symbol": "XSP",
            "expiration_date": date(2025, 2, 21),
            "strike": 500.0,
            "option_type": OptionType.PUT,
            "bid": 10.0,
            "ask": 11.0,
            "underlying_price": 5000.0,
        }

    def _underlying_kwargs(self, ts: datetime) -> dict[str, Any]:
        return {
            "timestamp_utc": ts,
            "trade_date": date(2025, 1, 15),
            "symbol": "SPX",
            "currency": "USD",
            "close": 5000.0,
            "source": "CBOE",
        }

    def test_naive_option_timestamp_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"timezone-aware"):
            CanonicalOptionRow(**self._option_kwargs(datetime(2025, 1, 15, 20, 45)))

    def test_non_utc_option_timestamp_rejected(self) -> None:
        from datetime import timedelta

        est = datetime(2025, 1, 15, 15, 45, tzinfo=timezone(timedelta(hours=-5)))
        with pytest.raises(ValidationError, match="UTC"):
            CanonicalOptionRow(**self._option_kwargs(est))

    def test_utc_option_timestamp_accepted(self) -> None:
        row = CanonicalOptionRow(
            **self._option_kwargs(datetime(2025, 1, 15, 20, 45, tzinfo=UTC))
        )
        offset = row.snapshot_ts_utc.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0

    def test_naive_underlying_timestamp_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"timezone-aware"):
            CanonicalUnderlyingRow(
                **self._underlying_kwargs(datetime(2025, 1, 15, 20, 0))
            )

    def test_non_utc_underlying_timestamp_rejected(self) -> None:
        from datetime import timedelta

        jst = datetime(2025, 1, 16, 5, 0, tzinfo=timezone(timedelta(hours=9)))
        with pytest.raises(ValidationError, match="UTC"):
            CanonicalUnderlyingRow(**self._underlying_kwargs(jst))


# ---------------------------------------------------------------------------
# Underlying-row strength (FR-003)
# ---------------------------------------------------------------------------


class TestUnderlyingRowStrength:
    def _kwargs(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "timestamp_utc": datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
            "trade_date": date(2025, 1, 15),
            "symbol": "SPX",
            "currency": "USD",
            "close": 5000.0,
            "source": "CBOE",
        }
        base.update(overrides)
        return base

    def test_negative_close_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalUnderlyingRow(**self._kwargs(close=-1.0))

    def test_zero_close_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalUnderlyingRow(**self._kwargs(close=0.0))

    def test_close_above_high_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"close.*must be <= high"):
            CanonicalUnderlyingRow(**self._kwargs(high=4990.0))

    def test_close_below_low_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"close.*must be >= low"):
            CanonicalUnderlyingRow(**self._kwargs(low=5010.0))

    def test_open_outside_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"open.*must be <= high"):
            CanonicalUnderlyingRow(**self._kwargs(open=6000.0, high=5010.0, low=4980.0))

    def test_lowercase_currency_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalUnderlyingRow(**self._kwargs(currency="usd"))

    def test_fake_currency_code_still_shape_validated(self) -> None:
        """Shape is validated (3 uppercase letters); ISO registry is TASK-016."""
        row = CanonicalUnderlyingRow(**self._kwargs(currency="XXX"))
        assert row.currency == "XXX"


# ---------------------------------------------------------------------------
# Schema version linkage
# ---------------------------------------------------------------------------


def test_schema_version_semver_shape() -> None:
    assert SCHEMA_VERSION == "1.0"
    import re

    assert re.fullmatch(r"\d+\.\d+", SCHEMA_VERSION)


def test_strict_mode_rejects_string_option_type() -> None:
    """strict=True: even a valid-typed string is rejected for the enum field."""
    with pytest.raises(ValidationError):
        CanonicalOptionRow(
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
            trade_date=date(2025, 1, 15),
            source="CBOE",
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=500.0,
            option_type="PUT",  # type: ignore[arg-type]
            bid=10.0,
            ask=11.0,
            underlying_price=5000.0,
        )
