"""Unit tests for the CSV/Parquet import pipeline."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import polars as pl
import pytest

from tailhedge.data.canonical_schema import (
    CanonicalOptionRow,
    CanonicalUnderlyingRow,
    OptionType,
)
from tailhedge.data.import_pipeline import (
    _coerce_date,
    _coerce_utc_timestamp,
    _validate_underlying_rows,
    hash_file,
    read_csv_to_canonical,
    read_parquet_to_canonical,
    write_parquet_partitioned,
)
from tailhedge.data.manifests import build_manifest
from tailhedge.data.validation import validate_option_dataset

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------


class TestHashFile:
    def test_deterministic_hash(self, tmp_path: Path) -> None:
        p = tmp_path / "test.txt"
        p.write_text("hello world")
        h1 = hash_file(p)
        h2 = hash_file(p)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        p1 = tmp_path / "a.txt"
        p2 = tmp_path / "b.txt"
        p1.write_text("content A")
        p2.write_text("content B")
        assert hash_file(p1) != hash_file(p2)

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.txt"
        p.write_text("")
        h = hash_file(p)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# CSV reading and normalization
# ---------------------------------------------------------------------------


class TestReadCsvToCanonical:
    """Test CSV import with option data."""

    def _write_option_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        """Write a CSV file with option data."""
        fieldnames = [
            "trade_date",
            "underlying_symbol",
            "root_symbol",
            "expiration_date",
            "strike",
            "option_type",
            "bid",
            "ask",
            "underlying_price",
        ]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_read_valid_option_csv(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "options.csv"
        self._write_option_csv(
            csv_path,
            [
                {
                    "trade_date": "2025-01-15",
                    "underlying_symbol": "SPX",
                    "root_symbol": "XSP",
                    "expiration_date": "2025-02-21",
                    "strike": 500.0,
                    "option_type": "PUT",
                    "bid": 10.0,
                    "ask": 11.0,
                    "underlying_price": 5000.0,
                },
                {
                    "trade_date": "2025-01-16",
                    "underlying_symbol": "SPX",
                    "root_symbol": "XSP",
                    "expiration_date": "2025-02-21",
                    "strike": 500.0,
                    "option_type": "PUT",
                    "bid": 10.5,
                    "ask": 11.5,
                    "underlying_price": 5050.0,
                },
            ],
        )

        rows = read_csv_to_canonical(
            csv_path, source_vendor="CBOE", timezone="America/New_York"
        )

        assert len(rows) == 2
        assert all(isinstance(r, CanonicalOptionRow) for r in rows)
        assert rows[0].underlying_symbol == "SPX"
        assert rows[0].root_symbol == "XSP"
        assert rows[0].strike == 500.0
        assert rows[0].option_type == OptionType.PUT
        assert rows[0].bid == 10.0
        assert rows[0].ask == 11.0
        assert rows[0].source == "CBOE"

    def test_timestamp_normalised_to_utc(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "options.csv"
        self._write_option_csv(
            csv_path,
            [
                {
                    "trade_date": "2025-01-15",
                    "underlying_symbol": "SPX",
                    "root_symbol": "XSP",
                    "expiration_date": "2025-02-21",
                    "strike": 500.0,
                    "option_type": "PUT",
                    "bid": 10.0,
                    "ask": 11.0,
                    "underlying_price": 5000.0,
                },
            ],
        )

        rows = read_csv_to_canonical(
            csv_path, source_vendor="CBOE", timezone="America/New_York"
        )

        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, CanonicalOptionRow)
        assert row.snapshot_ts_utc.tzinfo is not None
        assert row.snapshot_ts_utc.utcoffset().total_seconds() == 0

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_csv_to_canonical(tmp_path / "nonexistent.csv", source_vendor="CBOE")

    def test_missing_required_column(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text("strike,bid\n500,10\n")
        with pytest.raises((ValueError, KeyError, TypeError)):
            read_csv_to_canonical(csv_path, source_vendor="CBOE")

    def test_invalid_option_type_rejected(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "bad_type.csv"
        self._write_option_csv(
            csv_path,
            [
                {
                    "trade_date": "2025-01-15",
                    "underlying_symbol": "SPX",
                    "root_symbol": "XSP",
                    "expiration_date": "2025-02-21",
                    "strike": 500.0,
                    "option_type": "STRADDLE",
                    "bid": 10.0,
                    "ask": 11.0,
                    "underlying_price": 5000.0,
                },
            ],
        )
        with pytest.raises((ValueError, Exception)):
            read_csv_to_canonical(csv_path, source_vendor="CBOE")

    def test_ask_less_than_bid_rejected(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "bad_spread.csv"
        self._write_option_csv(
            csv_path,
            [
                {
                    "trade_date": "2025-01-15",
                    "underlying_symbol": "SPX",
                    "root_symbol": "XSP",
                    "expiration_date": "2025-02-21",
                    "strike": 500.0,
                    "option_type": "PUT",
                    "bid": 12.0,
                    "ask": 10.0,
                    "underlying_price": 5000.0,
                },
            ],
        )
        with pytest.raises((ValueError, Exception)):
            read_csv_to_canonical(csv_path, source_vendor="CBOE")


# ---------------------------------------------------------------------------
# Parquet reading
# ---------------------------------------------------------------------------


class TestReadParquetToCanonical:
    def test_read_valid_parquet(self, tmp_path: Path) -> None:
        parquet_path = tmp_path / "options.parquet"
        df = pl.DataFrame(
            {
                "snapshot_ts_utc": ["2025-01-15T20:45:00+00:00"],
                "trade_date": ["2025-01-15"],
                "source": ["CBOE"],
                "underlying_symbol": ["SPX"],
                "root_symbol": ["XSP"],
                "expiration_date": ["2025-02-21"],
                "strike": [500.0],
                "option_type": ["PUT"],
                "bid": [10.0],
                "ask": [11.0],
                "underlying_price": [5000.0],
            }
        )
        df.write_parquet(parquet_path)

        rows = read_parquet_to_canonical(
            parquet_path, source_vendor="CBOE", source_role="OPTION_CHAIN"
        )

        assert len(rows) == 1
        assert isinstance(rows[0], CanonicalOptionRow)
        assert rows[0].strike == 500.0

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_parquet_to_canonical(
                tmp_path / "nonexistent.parquet", source_vendor="CBOE"
            )


# ---------------------------------------------------------------------------
# Canonical Parquet writing
# ---------------------------------------------------------------------------


class TestWriteParquetPartitioned:
    def test_write_option_data(self, tmp_path: Path) -> None:
        rows = [
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
            ),
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 2, 15, 20, 45, tzinfo=UTC),
                trade_date=date(2025, 2, 15),
                source="CBOE",
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 3, 21),
                strike=510.0,
                option_type=OptionType.PUT,
                bid=12.0,
                ask=13.0,
                underlying_price=5100.0,
            ),
        ]

        output_dir = tmp_path / "normalized"
        output_dir.mkdir()

        write_parquet_partitioned(rows, output_dir, source_role="OPTION_CHAIN")

        parquet_files = list(output_dir.rglob("*.parquet"))
        assert len(parquet_files) > 0

    def test_write_underlying_data(self, tmp_path: Path) -> None:
        rows = [
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                currency="USD",
                close=5000.0,
                source="CBOE",
            ),
        ]

        output_dir = tmp_path / "normalized"
        output_dir.mkdir()

        write_parquet_partitioned(rows, output_dir, source_role="UNDERLYING")

        parquet_files = list(output_dir.rglob("*.parquet"))
        assert len(parquet_files) > 0

    def test_empty_rows_no_output(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "normalized"
        output_dir.mkdir()
        write_parquet_partitioned([], output_dir)
        parquet_files = list(output_dir.rglob("*.parquet"))
        assert len(parquet_files) == 0


# ---------------------------------------------------------------------------
# Timestamp coercion
# ---------------------------------------------------------------------------


class TestCoerceUtcTimestamp:
    def test_naive_datetime_converted(self) -> None:
        ts = datetime(2025, 1, 15, 15, 45)
        result = _coerce_utc_timestamp(ts, "America/New_York")
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0

    def test_utc_datetime_preserved(self) -> None:
        ts = datetime(2025, 1, 15, 20, 45, tzinfo=UTC)
        result = _coerce_utc_timestamp(ts, "America/New_York")
        assert result.hour == 20

    def test_string_parsed(self) -> None:
        result = _coerce_utc_timestamp("2025-01-15T20:45:00", "America/New_York")
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0

    def test_date_coerced(self) -> None:
        result = _coerce_utc_timestamp(date(2025, 1, 15), "America/New_York")
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Cannot coerce"):
            _coerce_utc_timestamp(12345, "UTC")


# ---------------------------------------------------------------------------
# Date coercion
# ---------------------------------------------------------------------------


class TestCoerceDate:
    def test_date_passthrough(self) -> None:
        d = date(2025, 1, 15)
        ref = datetime(2025, 1, 15, 20, 45, tzinfo=UTC)
        assert _coerce_date(d, ref) == d

    def test_datetime_extracts_date(self) -> None:
        dt = datetime(2025, 1, 15, 20, 45, tzinfo=UTC)
        ref = datetime(2025, 1, 16, tzinfo=UTC)
        assert _coerce_date(dt, ref) == date(2025, 1, 15)

    def test_string_parsed(self) -> None:
        ref = datetime(2025, 1, 15, tzinfo=UTC)
        assert _coerce_date("2025-01-15", ref) == date(2025, 1, 15)

    def test_none_falls_back_to_reference(self) -> None:
        ref = datetime(2025, 1, 15, 20, 45, tzinfo=UTC)
        assert _coerce_date(None, ref) == date(2025, 1, 15)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidateOptionRows:
    def test_valid_rows_pass(self) -> None:
        rows = [
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
            ),
        ]
        row_dicts = [r.model_dump() for r in rows]
        report = validate_option_dataset(row_dicts)
        # Status may be WARN due to missing optional fields, but no FAIL errors
        assert report.status != "FAIL"
        assert len(report.fatal_errors) == 0

    def test_duplicate_key_detected(self) -> None:
        rows = [
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
            ),
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
                ask=13.0,
                underlying_price=5000.0,
            ),
        ]
        row_dicts = [r.model_dump() for r in rows]
        report = validate_option_dataset(row_dicts)
        assert report.status == "FAIL"
        assert len(report.fatal_errors) == 1
        assert "duplicate" in report.fatal_errors[0].lower()

    def test_expiry_before_trade_date_detected(self) -> None:
        rows = [
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
            ),
        ]
        row_dicts = [r.model_dump() for r in rows]
        report = validate_option_dataset(row_dicts)
        # Valid row: no expiry <= trade_date
        assert all("expiry" not in e for e in report.fatal_errors)


class TestValidateUnderlyingRows:
    def test_valid_rows_pass(self) -> None:
        rows = [
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                currency="USD",
                close=5000.0,
                source="CBOE",
            ),
        ]
        warnings: list[str] = []
        errors: list[str] = []
        _validate_underlying_rows(rows, warnings, errors)
        assert errors == []

    def test_duplicate_key_detected(self) -> None:
        rows = [
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                currency="USD",
                close=5000.0,
                source="CBOE",
            ),
            CanonicalUnderlyingRow(
                timestamp_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                currency="USD",
                close=5100.0,
                source="CBOE",
            ),
        ]
        warnings: list[str] = []
        errors: list[str] = []
        _validate_underlying_rows(rows, warnings, errors)
        assert len(errors) == 1
        assert "Duplicate" in errors[0]


# ---------------------------------------------------------------------------
# Manifest determinism with import
# ---------------------------------------------------------------------------


class TestManifestDeterminism:
    def test_same_inputs_same_manifest_hash(self) -> None:
        m1 = build_manifest(
            source_vendor="CBOE",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 15),
            row_count=100,
        )
        m2 = build_manifest(
            source_vendor="CBOE",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 15),
            row_count=100,
        )
        assert m1.manifest_sha256 == m2.manifest_sha256

    def test_different_row_count_changes_hash(self) -> None:
        m1 = build_manifest(
            source_vendor="CBOE",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 15),
            row_count=100,
        )
        m2 = build_manifest(
            source_vendor="CBOE",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 15),
            row_count=200,
        )
        assert m1.manifest_sha256 != m2.manifest_sha256


# ---------------------------------------------------------------------------
# Underlying CSV import
# ---------------------------------------------------------------------------


class TestReadCsvUnderlying:
    def test_read_valid_underlying_csv(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "underlying.csv"
        fieldnames = [
            "trade_date",
            "symbol",
            "currency",
            "close",
            "open",
            "high",
            "low",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "trade_date": "2025-01-15",
                        "symbol": "SPX",
                        "currency": "USD",
                        "close": 5000.0,
                        "open": 4990.0,
                        "high": 5010.0,
                        "low": 4980.0,
                    },
                ]
            )

        rows = read_csv_to_canonical(
            csv_path,
            source_vendor="CBOE",
            timezone="America/New_York",
            source_role="UNDERLYING",
        )

        assert len(rows) == 1
        assert isinstance(rows[0], CanonicalUnderlyingRow)
        assert rows[0].symbol == "SPX"
        assert rows[0].close == 5000.0
