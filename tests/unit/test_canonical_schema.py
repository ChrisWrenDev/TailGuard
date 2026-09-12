"""Unit tests for canonical option and underlying schemas."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from tailhedge.data.canonical_schema import (
    CanonicalOptionRow,
    CanonicalUnderlyingRow,
    OptionType,
    SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# CanonicalOptionRow
# ---------------------------------------------------------------------------


class TestCanonicalOptionRow:
    """Validation tests for the option-chain canonical row."""

    def test_valid_put_row(self) -> None:
        row = CanonicalOptionRow(
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
                trade_date=date(2025, 1, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 2, 21),
                strike=500.0,
                option_type=OptionType.PUT,
                # bid missing
                ask=11.0,
                underlying_price=5000.0,
            )

    def test_negative_bid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
        with pytest.raises(ValidationError, match="ask.*must be >= bid"):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
        with pytest.raises(ValidationError, match="expiration_date.*must be after"):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=timezone.utc),
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
            timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=timezone.utc),
            trade_date=date(2025, 1, 15),
            symbol="SPX",
            currency="USD",
            close=5000.0,
            source="CBOE",
        )
        assert row.close == 5000.0

    def test_valid_with_optional_fields(self) -> None:
        row = CanonicalUnderlyingRow(
            timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=timezone.utc),
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
        with pytest.raises(ValidationError, match="high.*must be >= low"):
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=timezone.utc),
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
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=timezone.utc),
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                currency="USD",
                source="CBOE",
            )

    def test_invalid_currency_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=timezone.utc),
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
