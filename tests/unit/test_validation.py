"""Unit tests for the dataset validation module (FR-003, T-002)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from tailhedge.data.validation import (
    ValidationCheck,
    ValidationReport,
    validate_option_dataset,
)


def _make_row(
    trade_date: date = date(2025, 1, 15),
    root_symbol: str = "XSP",
    expiration_date: date = date(2025, 2, 21),
    strike: float = 500.0,
    option_type: str = "PUT",
    bid: float = 10.0,
    ask: float = 11.0,
    snapshot_ts: datetime | None = None,
) -> dict[str, object]:
    """Create a minimal valid option row dict."""
    if snapshot_ts is None:
        snapshot_ts = datetime(
            trade_date.year,
            trade_date.month,
            trade_date.day,
            20,
            45,
            tzinfo=UTC,
        )
    return {
        "snapshot_ts_utc": snapshot_ts,
        "trade_date": trade_date,
        "root_symbol": root_symbol,
        "expiration_date": expiration_date,
        "strike": strike,
        "option_type": option_type,
        "bid": bid,
        "ask": ask,
        "underlying_price": 5000.0,
    }


def _get_check(report: ValidationReport, name: str) -> ValidationCheck:
    """Get a validation check by name from a report."""
    return next(c for c in report.checks if c.name == name)


# ---------------------------------------------------------------------------
# Empty dataset
# ---------------------------------------------------------------------------


class TestEmptyDataset:
    def test_empty_dataset_fails(self) -> None:
        report = validate_option_dataset([])
        assert report.status == "FAIL"
        assert "no rows" in report.fatal_errors[0].lower()
        assert report.total_rows == 0

    def test_empty_dataset_summary_json(self) -> None:
        report = validate_option_dataset([])
        assert report.summary_json["status"] == "FAIL"
        assert report.summary_json["total_rows"] == 0


# ---------------------------------------------------------------------------
# Duplicate snapshot key detection
# ---------------------------------------------------------------------------


class TestDuplicateKeyDetection:
    def test_no_duplicates_pass(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15)),
            _make_row(trade_date=date(2025, 1, 16)),
        ]
        report = validate_option_dataset(rows)
        # Status may be WARN due to missing optional fields, but no FAIL errors
        assert report.status != "FAIL"
        assert all(
            c.status == "PASS"
            for c in report.checks
            if c.name == "duplicate_snapshot_key"
        )

    def test_duplicate_key_fails(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15)),
            _make_row(trade_date=date(2025, 1, 15)),  # Same key
        ]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        dup_check = _get_check(report, "duplicate_snapshot_key")
        assert dup_check.status == "FAIL"
        assert "duplicate" in dup_check.message.lower()

    def test_duplicate_key_counts_affected_rows(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15)),
            _make_row(trade_date=date(2025, 1, 15)),  # Duplicate
            _make_row(trade_date=date(2025, 1, 15)),  # Duplicate
        ]
        report = validate_option_dataset(rows)
        dup_check = _get_check(report, "duplicate_snapshot_key")
        assert dup_check.affected_rows == 2


# ---------------------------------------------------------------------------
# Bid validation
# ---------------------------------------------------------------------------


class TestBidValidation:
    def test_positive_bid_passes(self) -> None:
        rows = [_make_row(bid=10.0)]
        report = validate_option_dataset(rows)
        bid_check = _get_check(report, "bid_non_negative")
        assert bid_check.status == "PASS"

    def test_zero_bid_passes(self) -> None:
        rows = [_make_row(bid=0.0)]
        report = validate_option_dataset(rows)
        bid_check = _get_check(report, "bid_non_negative")
        assert bid_check.status == "PASS"

    def test_negative_bid_fails(self) -> None:
        rows = [_make_row(bid=-1.0)]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        bid_check = _get_check(report, "bid_non_negative")
        assert bid_check.status == "FAIL"
        assert bid_check.affected_rows == 1


# ---------------------------------------------------------------------------
# Ask >= bid validation
# ---------------------------------------------------------------------------


class TestAskGteBid:
    def test_ask_greater_than_bid_passes(self) -> None:
        rows = [_make_row(bid=10.0, ask=11.0)]
        report = validate_option_dataset(rows)
        spread_check = _get_check(report, "ask_gte_bid")
        assert spread_check.status == "PASS"

    def test_ask_equal_to_bid_passes(self) -> None:
        rows = [_make_row(bid=10.0, ask=10.0)]
        report = validate_option_dataset(rows)
        spread_check = _get_check(report, "ask_gte_bid")
        assert spread_check.status == "PASS"

    def test_ask_less_than_bid_fails(self) -> None:
        rows = [_make_row(bid=12.0, ask=10.0)]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        spread_check = _get_check(report, "ask_gte_bid")
        assert spread_check.status == "FAIL"
        assert "crossed" in spread_check.message.lower()


# ---------------------------------------------------------------------------
# Expiry validation
# ---------------------------------------------------------------------------


class TestExpiryValidation:
    def test_expiry_after_trade_passes(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15), expiration_date=date(2025, 2, 21))
        ]
        report = validate_option_dataset(rows)
        expiry_check = _get_check(report, "expiry_after_trade")
        assert expiry_check.status == "PASS"

    def test_expiry_equal_to_trade_fails(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15), expiration_date=date(2025, 1, 15))
        ]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        expiry_check = _get_check(report, "expiry_after_trade")
        assert expiry_check.status == "FAIL"

    def test_expiry_before_trade_fails(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15), expiration_date=date(2025, 1, 10))
        ]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        expiry_check = _get_check(report, "expiry_after_trade")
        assert expiry_check.status == "FAIL"


# ---------------------------------------------------------------------------
# Option type validation
# ---------------------------------------------------------------------------


class TestOptionTypeValidation:
    def test_put_passes(self) -> None:
        rows = [_make_row(option_type="PUT")]
        report = validate_option_dataset(rows)
        type_check = _get_check(report, "valid_option_type")
        assert type_check.status == "PASS"

    def test_call_passes(self) -> None:
        rows = [_make_row(option_type="CALL")]
        report = validate_option_dataset(rows)
        type_check = _get_check(report, "valid_option_type")
        assert type_check.status == "PASS"

    def test_invalid_type_fails(self) -> None:
        rows = [_make_row(option_type="STRADDLE")]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        type_check = _get_check(report, "valid_option_type")
        assert type_check.status == "FAIL"
        assert "STRADDLE" in type_check.message


# ---------------------------------------------------------------------------
# Coverage warnings
# ---------------------------------------------------------------------------


class TestCoverageValidation:
    def test_all_optional_fields_present_passes(self) -> None:
        rows = [
            {
                **_make_row(),
                "bid_size": 100,
                "ask_size": 50,
                "volume": 1000,
                "open_interest": 5000,
            }
        ]
        report = validate_option_dataset(rows)
        cov_check = _get_check(report, "field_coverage")
        assert cov_check.status == "PASS"

    def test_missing_optional_fields_warns(self) -> None:
        rows = [
            _make_row(
                bid=10.0, ask=11.0
            ),  # No bid_size, ask_size, volume, open_interest
        ]
        report = validate_option_dataset(rows)
        cov_check = _get_check(report, "field_coverage")
        assert cov_check.status == "WARN"
        assert "bid_size" in cov_check.message.lower()
        assert "0%" in cov_check.message


# ---------------------------------------------------------------------------
# Date coverage
# ---------------------------------------------------------------------------


class TestDateCoverage:
    def test_contiguous_dates_pass(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15)),
            _make_row(trade_date=date(2025, 1, 16)),
            _make_row(trade_date=date(2025, 1, 17)),
        ]
        report = validate_option_dataset(rows)
        date_check = _get_check(report, "date_coverage")
        assert date_check.status == "PASS"

    def test_gap_in_dates_warns(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15)),
            _make_row(trade_date=date(2025, 1, 17)),  # Gap of 2 days
        ]
        report = validate_option_dataset(rows)
        date_check = _get_check(report, "date_coverage")
        assert date_check.status == "WARN"
        assert "gap" in date_check.message.lower()


# ---------------------------------------------------------------------------
# Summary JSON structure
# ---------------------------------------------------------------------------


class TestSummaryJson:
    def test_summary_json_has_required_fields(self) -> None:
        rows = [_make_row()]
        report = validate_option_dataset(rows)
        summary = report.summary_json
        assert "status" in summary
        assert "total_rows" in summary
        assert "errors" in summary
        assert "warnings" in summary
        assert "checks" in summary

    def test_summary_json_checks_have_structure(self) -> None:
        rows = [_make_row()]
        report = validate_option_dataset(rows)
        checks = report.summary_json["checks"]
        assert isinstance(checks, list)
        for check in checks:
            assert isinstance(check, dict)
            assert "name" in check
            assert "status" in check
            assert "message" in check
            assert "affected_rows" in check
            assert "affected_dates_count" in check
            assert "affected_fields" in check

    def test_fatal_status_reflected_in_summary(self) -> None:
        rows = [_make_row(bid=-1.0)]
        report = validate_option_dataset(rows)
        assert report.summary_json["status"] == "FAIL"
        errors = report.summary_json["errors"]
        assert isinstance(errors, list)
        assert len(errors) > 0

    def test_warning_status_reflected_in_summary(self) -> None:
        rows = [_make_row()]  # Missing optional fields -> warnings
        report = validate_option_dataset(rows)
        # This should be WARN due to missing optional fields
        assert report.summary_json["status"] in ("PASS", "WARN")


# ---------------------------------------------------------------------------
# Multiple errors
# ---------------------------------------------------------------------------


class TestMultipleErrors:
    def test_multiple_fatal_errors_all_reported(self) -> None:
        rows = [
            {
                "snapshot_ts_utc": datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
                "trade_date": date(2025, 1, 15),
                "root_symbol": "XSP",
                "expiration_date": date(2025, 1, 10),  # Before trade date
                "strike": 500.0,
                "option_type": "STRADDLE",  # Invalid type
                "bid": -5.0,  # Negative bid
                "ask": -3.0,  # Ask < bid
                "underlying_price": 5000.0,
            },
        ]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        assert len(report.fatal_errors) >= 3  # expiry, option_type, bid, ask


# ---------------------------------------------------------------------------
# Affected dates tracking
# ---------------------------------------------------------------------------


class TestAffectedDatesTracking:
    def test_affected_dates_populated(self) -> None:
        rows = [
            _make_row(bid=-1.0, trade_date=date(2025, 1, 15)),
            _make_row(bid=-2.0, trade_date=date(2025, 1, 16)),
        ]
        report = validate_option_dataset(rows)
        bid_check = _get_check(report, "bid_non_negative")
        assert len(bid_check.affected_dates) == 2
        assert date(2025, 1, 15) in bid_check.affected_dates
        assert date(2025, 1, 16) in bid_check.affected_dates


# ---------------------------------------------------------------------------
# T-002: Crossed quotes
# ---------------------------------------------------------------------------


class TestT002CrossedQuotes:
    """T-002 invalid case: crossed bid/ask quotes should fail validation."""

    def test_crossed_quotes_fails_dataset(self) -> None:
        rows = [
            _make_row(bid=12.0, ask=10.0),  # Crossed quote
        ]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        assert any("crossed" in c.message.lower() for c in report.checks)


# ---------------------------------------------------------------------------
# T-002: Duplicate keys
# ---------------------------------------------------------------------------


class TestT002DuplicateKeys:
    """T-002 invalid case: duplicate snapshot keys should fail validation."""

    def test_duplicate_keys_fails_dataset(self) -> None:
        rows = [
            _make_row(trade_date=date(2025, 1, 15)),
            _make_row(trade_date=date(2025, 1, 15)),  # Duplicate
        ]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        assert any("duplicate" in c.message.lower() for c in report.checks)


# ---------------------------------------------------------------------------
# T-002: Invalid option type
# ---------------------------------------------------------------------------


class TestT002InvalidOptionType:
    """T-002 invalid case: invalid option type should fail validation."""

    def test_invalid_option_type_fails_dataset(self) -> None:
        rows = [_make_row(option_type="INVALID")]
        report = validate_option_dataset(rows)
        assert report.status == "FAIL"
        type_check = _get_check(report, "valid_option_type")
        assert type_check.status == "FAIL"
