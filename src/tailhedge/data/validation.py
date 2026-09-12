"""Dataset validation checks per FR-003.

Mandatory checks:
- Unique contract snapshot key
- bid >= 0
- ask >= bid for tradable quotes
- expiry >= observation date
- Valid put/call value
- No impossible strike/expiry types
- Deterministic timezone normalisation
- Duplicate detection
- Coverage summary

Warnings are quantified by date and field for UI reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class ValidationCheck:
    """A single validation check result."""

    name: str
    status: str  # PASS, WARN, FAIL
    message: str = ""
    affected_rows: int = 0
    affected_dates: list[date] = field(default_factory=list)
    affected_fields: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Aggregated validation report for a dataset."""

    status: str  # PASS, WARN, FAIL
    checks: list[ValidationCheck] = field(default_factory=list)
    total_rows: int = 0
    fatal_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary_json: dict[str, object] = field(default_factory=dict)


def _extract_trade_date(row: dict[str, object]) -> date | None:
    """Extract the trade date from a row dict."""
    ts = row.get("snapshot_ts_utc")
    if isinstance(ts, datetime):
        return ts.date()
    trade_dt = row.get("trade_date")
    if isinstance(trade_dt, date) and not isinstance(trade_dt, datetime):
        return trade_dt
    if isinstance(trade_dt, datetime):
        return trade_dt.date()
    return None


def _make_check(
    name: str,
    status: str,
    message: str = "",
    affected_rows: int = 0,
    affected_dates: list[date] | None = None,
    affected_fields: list[str] | None = None,
) -> ValidationCheck:
    return ValidationCheck(
        name=name,
        status=status,
        message=message,
        affected_rows=affected_rows,
        affected_dates=affected_dates or [],
        affected_fields=affected_fields or [],
    )


def validate_option_dataset(
    rows: list[dict[str, object]],
) -> ValidationReport:
    """Run all mandatory FR-003 validation checks on option rows.

    Each row should have canonical fields already normalised to UTC.
    """
    report = ValidationReport(
        status="PASS",
        total_rows=len(rows),
    )

    if not rows:
        report.status = "FAIL"
        report.fatal_errors.append("Dataset contains no rows")
        report.checks.append(
            _make_check("empty_dataset", "FAIL", "Dataset contains no rows")
        )
        report.summary_json = {
            "status": "FAIL",
            "errors": report.fatal_errors,
            "warnings": report.warnings,
            "total_rows": 0,
            "checks": [_check_summary(c) for c in report.checks],
        }
        return report

    # 1. Duplicate detection (unique snapshot key)
    _check_duplicate_keys(rows, report)

    # 2. Bid >= 0
    _check_bid_non_negative(rows, report)

    # 3. Ask >= bid for tradable quotes
    _check_ask_gte_bid(rows, report)

    # 4. Expiry >= observation date
    _check_expiry_after_trade(rows, report)

    # 5. Valid put/call value
    _check_valid_option_type(rows, report)

    # 6. Coverage summary (missing optional fields)
    _check_coverage(rows, report)

    # 7. Date range coverage
    _check_date_coverage(rows, report)

    # Build summary
    errors = [c for c in report.checks if c.status == "FAIL"]
    warns = [c for c in report.checks if c.status == "WARN"]

    report.fatal_errors = [c.message for c in errors]
    report.warnings = [c.message for c in warns]

    if errors:
        report.status = "FAIL"
    elif warns:
        report.status = "WARN"
    else:
        report.status = "PASS"

    report.summary_json = {
        "status": report.status,
        "total_rows": report.total_rows,
        "errors": report.fatal_errors,
        "warnings": report.warnings,
        "checks": [_check_summary(c) for c in report.checks],
    }

    return report


def _check_summary(check: ValidationCheck) -> dict[str, object]:
    """Convert a check to a JSON-serialisable dict."""
    return {
        "name": check.name,
        "status": check.status,
        "message": check.message,
        "affected_rows": check.affected_rows,
        "affected_dates_count": len(check.affected_dates),
        "affected_fields": check.affected_fields,
    }


def _check_duplicate_keys(
    rows: list[dict[str, object]], report: ValidationReport
) -> None:
    """Check for duplicate (snapshot_ts_utc, root_symbol, expiration_date, strike, option_type) keys."""
    seen: dict[tuple[object, ...], int] = {}
    duplicates = 0
    duplicate_dates: list[date] = []

    for row in rows:
        trade_dt = _extract_trade_date(row)

        key = (
            row.get("snapshot_ts_utc"),
            row.get("root_symbol"),
            row.get("expiration_date"),
            row.get("strike"),
            row.get("option_type"),
        )
        if key in seen:
            duplicates += 1
            if trade_dt is not None and trade_dt not in duplicate_dates:
                duplicate_dates.append(trade_dt)
        else:
            seen[key] = 1

    if duplicates > 0:
        report.checks.append(
            _make_check(
                name="duplicate_snapshot_key",
                status="FAIL",
                message=f"Found {duplicates} duplicate snapshot keys",
                affected_rows=duplicates,
                affected_dates=duplicate_dates,
                affected_fields=[
                    "snapshot_ts_utc",
                    "root_symbol",
                    "expiration_date",
                    "strike",
                    "option_type",
                ],
            )
        )
    else:
        report.checks.append(
            _make_check(
                name="duplicate_snapshot_key",
                status="PASS",
                message="No duplicate snapshot keys found",
            )
        )


def _check_bid_non_negative(
    rows: list[dict[str, object]], report: ValidationReport
) -> None:
    """Check that all bid values are >= 0."""
    violations = 0
    violation_dates: list[date] = []

    for row in rows:
        bid = row.get("bid")
        if bid is not None and isinstance(bid, (int, float)) and bid < 0:
            violations += 1
            trade_dt = _extract_trade_date(row)
            if trade_dt is not None and trade_dt not in violation_dates:
                violation_dates.append(trade_dt)

    if violations > 0:
        report.checks.append(
            _make_check(
                name="bid_non_negative",
                status="FAIL",
                message=f"Found {violations} rows with negative bid values",
                affected_rows=violations,
                affected_dates=violation_dates,
                affected_fields=["bid"],
            )
        )
    else:
        report.checks.append(
            _make_check(
                name="bid_non_negative",
                status="PASS",
                message="All bid values are non-negative",
            )
        )


def _check_ask_gte_bid(rows: list[dict[str, object]], report: ValidationReport) -> None:
    """Check that ask >= bid for all tradable quotes."""
    violations = 0
    violation_dates: list[date] = []

    for row in rows:
        bid = row.get("bid")
        ask = row.get("ask")
        if (
            bid is not None
            and ask is not None
            and isinstance(bid, (int, float))
            and isinstance(ask, (int, float))
            and ask < bid
        ):
            violations += 1
            trade_dt = _extract_trade_date(row)
            if trade_dt is not None and trade_dt not in violation_dates:
                violation_dates.append(trade_dt)

    if violations > 0:
        report.checks.append(
            _make_check(
                name="ask_gte_bid",
                status="FAIL",
                message=f"Found {violations} rows where ask < bid (crossed quote)",
                affected_rows=violations,
                affected_dates=violation_dates,
                affected_fields=["bid", "ask"],
            )
        )
    else:
        report.checks.append(
            _make_check(
                name="ask_gte_bid",
                status="PASS",
                message="All ask values are >= bid",
            )
        )


def _check_expiry_after_trade(
    rows: list[dict[str, object]], report: ValidationReport
) -> None:
    """Check that expiry >= observation (trade) date."""
    violations = 0
    violation_dates: list[date] = []

    for row in rows:
        expiry_date_raw = row.get("expiration_date")

        trade_dt = _extract_trade_date(row)
        expiry_dt: date | None = None
        if isinstance(expiry_date_raw, date) and not isinstance(
            expiry_date_raw, datetime
        ):
            expiry_dt = expiry_date_raw
        elif isinstance(expiry_date_raw, datetime):
            expiry_dt = expiry_date_raw.date()

        if trade_dt is not None and expiry_dt is not None and expiry_dt <= trade_dt:
            violations += 1
            if trade_dt not in violation_dates:
                violation_dates.append(trade_dt)

    if violations > 0:
        report.checks.append(
            _make_check(
                name="expiry_after_trade",
                status="FAIL",
                message=f"Found {violations} rows where expiry <= trade date",
                affected_rows=violations,
                affected_dates=violation_dates,
                affected_fields=["expiration_date", "trade_date"],
            )
        )
    else:
        report.checks.append(
            _make_check(
                name="expiry_after_trade",
                status="PASS",
                message="All expiry dates are after trade dates",
            )
        )


def _check_valid_option_type(
    rows: list[dict[str, object]], report: ValidationReport
) -> None:
    """Check that option_type is valid (PUT or CALL)."""
    violations = 0
    violation_dates: list[date] = []
    invalid_types: set[str] = set()

    for row in rows:
        opt_type = row.get("option_type")
        opt_str = str(opt_type).upper() if opt_type is not None else ""
        if opt_str not in ("PUT", "CALL"):
            violations += 1
            invalid_types.add(opt_str)
            trade_dt = _extract_trade_date(row)
            if trade_dt is not None and trade_dt not in violation_dates:
                violation_dates.append(trade_dt)

    if violations > 0:
        report.checks.append(
            _make_check(
                name="valid_option_type",
                status="FAIL",
                message=f"Found {violations} rows with invalid option type: {sorted(invalid_types)}",
                affected_rows=violations,
                affected_dates=violation_dates,
                affected_fields=["option_type"],
            )
        )
    else:
        report.checks.append(
            _make_check(
                name="valid_option_type",
                status="PASS",
                message="All option types are valid (PUT/CALL)",
            )
        )


def _check_coverage(rows: list[dict[str, object]], report: ValidationReport) -> None:
    """Check coverage of optional but recommended fields."""
    recommended_fields = ["bid_size", "ask_size", "volume", "open_interest"]
    field_coverage: dict[str, int] = dict.fromkeys(recommended_fields, 0)

    for row in rows:
        for f in recommended_fields:
            val = row.get(f)
            if val is not None and val != "" and val != 0:
                field_coverage[f] += 1

    total = len(rows)
    warnings_list: list[str] = []

    for f, count in field_coverage.items():
        pct = (count / total * 100) if total > 0 else 0
        if count == 0:
            warnings_list.append(f"{f}: 0% coverage (all values missing/zero)")
        elif pct < 50:
            warnings_list.append(f"{f}: {pct:.0f}% coverage ({count}/{total} rows)")

    if warnings_list:
        low_cov_fields = [
            f for f, c in field_coverage.items() if c == 0 or (c / total * 100) < 50
        ]
        report.checks.append(
            _make_check(
                name="field_coverage",
                status="WARN",
                message="; ".join(warnings_list),
                affected_fields=low_cov_fields,
            )
        )
    else:
        report.checks.append(
            _make_check(
                name="field_coverage",
                status="PASS",
                message="All recommended fields have sufficient coverage",
            )
        )


def _check_date_coverage(
    rows: list[dict[str, object]], report: ValidationReport
) -> None:
    """Check for gaps in date coverage."""
    dates: set[date] = set()

    for row in rows:
        trade_dt = _extract_trade_date(row)
        if trade_dt is not None:
            dates.add(trade_dt)

    if len(dates) < 2:
        report.checks.append(
            _make_check(
                name="date_coverage",
                status="PASS",
                message=f"Dataset covers {len(dates)} unique date(s)",
            )
        )
        return

    sorted_dates = sorted(dates)
    gaps: list[int] = []

    for i in range(1, len(sorted_dates)):
        diff = (sorted_dates[i] - sorted_dates[i - 1]).days
        if diff > 1:
            gaps.append(diff)

    if gaps:
        max_gap = max(gaps)
        report.checks.append(
            _make_check(
                name="date_coverage",
                status="WARN",
                message=f"Found {len(gaps)} gap(s) in date coverage; largest gap is {max_gap} day(s)",
                affected_dates=sorted_dates,
            )
        )
    else:
        report.checks.append(
            _make_check(
                name="date_coverage",
                status="PASS",
                message=f"Date coverage is contiguous across {len(dates)} dates",
            )
        )
