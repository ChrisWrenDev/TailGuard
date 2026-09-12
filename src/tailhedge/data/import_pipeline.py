"""CSV/Parquet import pipeline.

Handles immutable raw file hashing, canonical normalization, Parquet
partitioning, manifest generation, duplicate detection, and dataset DB
metadata persistence.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from tailhedge.data.canonical_schema import (
    SCHEMA_VERSION,
    CanonicalOptionRow,
    CanonicalUnderlyingRow,
    OptionType,
)
from tailhedge.data.manifests import FileHash, build_manifest

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_TIMEZONE = "America/New_York"


@dataclass(frozen=True)
class ImportResult:
    """Result of a successful dataset import."""

    dataset_id: uuid.UUID
    manifest_sha256: str
    row_count: int
    status: str
    is_duplicate: bool = False


@dataclass
class _RawFile:
    """Intermediate representation of a raw file's metadata."""

    path: Path
    relative_path: str
    sha256: str
    byte_size: int
    row_count: int | None
    source_role: str


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------


def hash_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# CSV reading and normalization
# ---------------------------------------------------------------------------

_DEFAULT_CSV_OPTION_MAP: dict[str, str] = {
    "trade_date": "trade_date",
    "snapshot_ts_utc": "snapshot_ts_utc",
    "underlying_symbol": "underlying_symbol",
    "root_symbol": "root_symbol",
    "expiration_date": "expiration_date",
    "strike": "strike",
    "option_type": "option_type",
    "bid": "bid",
    "ask": "ask",
    "bid_size": "bid_size",
    "ask_size": "ask_size",
    "volume": "volume",
    "open_interest": "open_interest",
    "underlying_price": "underlying_price",
    "implied_volatility": "implied_volatility",
    "delta": "delta",
    "gamma": "gamma",
    "theta": "theta",
    "vega": "vega",
    "source_contract_id": "source_contract_id",
    "source": "source",
}


def read_csv_to_canonical(
    path: Path,
    *,
    source_vendor: str,
    column_map: dict[str, str] | None = None,
    timezone: str = DEFAULT_SOURCE_TIMEZONE,
    source_role: str = "OPTION_CHAIN",
) -> list[CanonicalOptionRow] | list[CanonicalUnderlyingRow]:
    """Read a CSV file and normalize rows to canonical form.

    Args:
        path: Path to the CSV file.
        source_vendor: Vendor identifier for the ``source`` field.
        column_map: Optional mapping from CSV column names to canonical
            field names.  When ``None`` the default identity map is used.
        timezone: IANA timezone of the source data.
        source_role: ``"OPTION_CHAIN"`` or ``"UNDERLYING"``.

    Returns:
        List of validated canonical rows.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ValueError: If required columns are missing or data is invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    effective_map = column_map or _DEFAULT_CSV_OPTION_MAP

    df = pl.read_csv(path, try_parse_dates=True).rename(effective_map)
    records = df.to_dicts()

    if source_role == "OPTION_CHAIN":
        return _normalize_option_rows(records, source_vendor, timezone)
    return _normalize_underlying_rows(records, source_vendor, timezone)


def _normalize_option_rows(
    records: list[dict[str, object]],
    source_vendor: str,
    timezone: str,
) -> list[CanonicalOptionRow]:
    """Validate and convert raw dicts to CanonicalOptionRow."""
    rows: list[CanonicalOptionRow] = []
    for rec in records:
        raw_ts = rec.get("snapshot_ts_utc") or rec.get("trade_date")
        ts_utc = _coerce_utc_timestamp(raw_ts, timezone)
        trade_dt = _coerce_date(rec.get("trade_date"), ts_utc)

        raw_expiry = rec.get("expiration_date")
        expiry_dt = _coerce_date(raw_expiry, ts_utc)

        rec["snapshot_ts_utc"] = ts_utc
        rec["trade_date"] = trade_dt
        rec["expiration_date"] = expiry_dt
        rec["source"] = source_vendor

        # Convert option_type string to enum for strict mode
        raw_type = rec.get("option_type")
        if isinstance(raw_type, str):
            rec["option_type"] = OptionType(raw_type)

        row = CanonicalOptionRow.model_validate(rec)
        rows.append(row)
    return rows


def _normalize_underlying_rows(
    records: list[dict[str, object]],
    source_vendor: str,
    timezone: str,
) -> list[CanonicalUnderlyingRow]:
    """Validate and convert raw dicts to CanonicalUnderlyingRow."""
    rows: list[CanonicalUnderlyingRow] = []
    for rec in records:
        raw_ts = rec.get("timestamp_utc") or rec.get("trade_date")
        ts_utc = _coerce_utc_timestamp(raw_ts, timezone)
        trade_dt = _coerce_date(rec.get("trade_date"), ts_utc)

        rec["timestamp_utc"] = ts_utc
        rec["trade_date"] = trade_dt
        rec["source"] = source_vendor

        row = CanonicalUnderlyingRow.model_validate(rec)
        rows.append(row)
    return rows


def _coerce_utc_timestamp(value: object, source_tz: str) -> datetime:
    """Coerce a value to a UTC-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            from zoneinfo import ZoneInfo

            local = value.replace(tzinfo=ZoneInfo(source_tz))
            return local.astimezone(UTC)
        return value.astimezone(UTC)
    if isinstance(value, date):
        from zoneinfo import ZoneInfo

        dt = datetime.combine(value, datetime.min.time())
        return dt.replace(tzinfo=ZoneInfo(source_tz)).astimezone(UTC)
    if isinstance(value, str):
        from zoneinfo import ZoneInfo

        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(source_tz))
        return dt.astimezone(UTC)
    msg = f"Cannot coerce {type(value).__name__!r} to UTC datetime"
    raise TypeError(msg)


def _coerce_date(value: object, reference_ts: datetime) -> date:
    """Coerce a value to a date, falling back to the trade date from a timestamp."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    return reference_ts.date()


# ---------------------------------------------------------------------------
# Parquet reading
# ---------------------------------------------------------------------------


def read_parquet_to_canonical(
    path: Path,
    *,
    source_vendor: str,
    source_role: str = "OPTION_CHAIN",
) -> list[CanonicalOptionRow] | list[CanonicalUnderlyingRow]:
    """Read a Parquet file and validate rows against the canonical schema.

    Args:
        path: Path to the Parquet file.
        source_vendor: Vendor identifier for the ``source`` field.
        source_role: ``"OPTION_CHAIN"`` or ``"UNDERLYING"``.

    Returns:
        List of validated canonical rows.
    """
    if not path.exists():
        raise FileNotFoundError(f"Parquet file not found: {path}")

    df = pl.read_parquet(path)
    records = df.to_dicts()

    if source_role == "OPTION_CHAIN":
        return _normalize_option_rows(records, source_vendor, "UTC")
    return _normalize_underlying_rows(records, source_vendor, "UTC")


# ---------------------------------------------------------------------------
# Canonical Parquet writing
# ---------------------------------------------------------------------------


def write_parquet_partitioned(
    rows: list[CanonicalOptionRow | CanonicalUnderlyingRow],
    output_dir: Path,
    *,
    source_role: str = "OPTION_CHAIN",
) -> None:
    """Write canonical rows to a partitioned Parquet dataset.

    Option data is partitioned by ``underlying_symbol``, ``year``, ``month``.
    Underlying data is partitioned by ``year``.
    """
    if not rows:
        return

    if source_role == "OPTION_CHAIN":
        records = [r.model_dump(mode="json") for r in rows]
        df = pl.DataFrame(records)
        df = df.with_columns(
            pl.col("snapshot_ts_utc").str.slice(0, 4).alias("year"),
            pl.col("snapshot_ts_utc").str.slice(5, 2).alias("month"),
        )
        df.write_parquet(
            output_dir / "options.parquet",
            use_pyarrow=True,
            pyarrow_options={"partition_cols": ["underlying_symbol", "year", "month"]},
        )
    else:
        records = [r.model_dump(mode="json") for r in rows]
        df = pl.DataFrame(records)
        df = df.with_columns(
            pl.col("timestamp_utc").str.slice(0, 4).alias("year"),
        )
        df.write_parquet(
            output_dir / "underlying.parquet",
            use_pyarrow=True,
            pyarrow_options={"partition_cols": ["year"]},
        )


# ---------------------------------------------------------------------------
# Import pipeline
# ---------------------------------------------------------------------------


def run_import(
    session: Session,
    *,
    name: str,
    source_vendor: str,
    source_paths: list[Path],
    source_role: str = "OPTION_CHAIN",
    timezone: str = DEFAULT_SOURCE_TIMEZONE,
    dataset_root: str = "data",
) -> ImportResult:
    """Run the full dataset import pipeline.

    Steps:
    1. Hash raw files and create DB metadata.
    2. Read and normalize to canonical schema.
    3. Write partitioned Parquet.
    4. Build and persist manifest.
    5. Duplicate check via manifest hash.
    6. Validate and persist validation result.

    Args:
        session: Database session.
        name: User-facing dataset name.
        source_vendor: Data vendor identifier.
        source_paths: Paths to the source files.
        source_role: ``"OPTION_CHAIN"`` or ``"UNDERLYING"``.
        timezone: IANA timezone of the source data.
        dataset_root: Root directory for dataset storage.

    Returns:
        An ImportResult with dataset ID, manifest hash, row count, and status.
    """
    from tailhedge.persistence.models import (
        DatasetFile,
        DatasetValidationResult,
        ResearchDataset,
    )

    normalized_dir = Path(dataset_root) / "normalized"

    # Step 1: Hash raw files
    raw_files: list[_RawFile] = []
    for path in source_paths:
        sha = hash_file(path)
        raw_files.append(
            _RawFile(
                path=path,
                relative_path=path.name,
                sha256=sha,
                byte_size=path.stat().st_size,
                row_count=None,
                source_role=source_role,
            )
        )

    # Step 2: Read and normalize
    all_rows: list[CanonicalOptionRow | CanonicalUnderlyingRow] = []
    for rf in raw_files:
        if rf.path.suffix.lower() == ".csv":
            rows = read_csv_to_canonical(
                rf.path,
                source_vendor=source_vendor,
                timezone=timezone,
                source_role=source_role,
            )
        else:
            rows = read_parquet_to_canonical(
                rf.path,
                source_vendor=source_vendor,
                source_role=source_role,
            )
        all_rows.extend(rows)

    # Step 3: Build manifest
    file_hashes = [
        FileHash(
            relative_path=rf.relative_path,
            sha256=rf.sha256,
            byte_size=rf.byte_size,
            row_count=len(all_rows) if len(raw_files) == 1 else None,
        )
        for rf in raw_files
    ]

    manifest = build_manifest(
        source_vendor=source_vendor,
        schema_version=SCHEMA_VERSION,
        timezone=timezone,
        start_date=date.min,
        end_date=date.max,
        row_count=len(all_rows),
        file_hashes=file_hashes,
    )

    if all_rows:
        if source_role == "OPTION_CHAIN":
            first_row = all_rows[0]
            assert isinstance(first_row, CanonicalOptionRow)
            manifest = build_manifest(
                source_vendor=source_vendor,
                schema_version=SCHEMA_VERSION,
                timezone=timezone,
                start_date=first_row.trade_date,
                end_date=all_rows[-1].trade_date,
                row_count=len(all_rows),
                file_hashes=file_hashes,
            )
        else:
            first_row = all_rows[0]
            assert isinstance(first_row, CanonicalUnderlyingRow)
            manifest = build_manifest(
                source_vendor=source_vendor,
                schema_version=SCHEMA_VERSION,
                timezone=timezone,
                start_date=first_row.trade_date,
                end_date=all_rows[-1].trade_date,
                row_count=len(all_rows),
                file_hashes=file_hashes,
            )

    # Step 4: Duplicate check
    existing = session.execute(
        __import__("sqlalchemy")
        .select(ResearchDataset)
        .where(ResearchDataset.manifest_sha256 == manifest.manifest_sha256)
    ).scalar_one_or_none()

    if existing is not None:
        return ImportResult(
            dataset_id=existing.id,
            manifest_sha256=existing.manifest_sha256,
            row_count=existing.row_count,
            status=existing.status,
            is_duplicate=True,
        )

    # Step 5: Create dataset record
    dataset_id = uuid.uuid4()
    storage_uri = str(normalized_dir / str(dataset_id))
    now = datetime.now(UTC)

    dataset = ResearchDataset(
        id=dataset_id,
        name=name,
        source_vendor=source_vendor,
        schema_version=SCHEMA_VERSION,
        timezone=timezone,
        start_date=manifest.start_date,
        end_date=manifest.end_date,
        row_count=manifest.row_count,
        manifest_sha256=manifest.manifest_sha256,
        storage_uri=storage_uri,
        status="INGESTING",
        created_at=now,
    )
    session.add(dataset)
    session.flush()

    # Step 6: Create dataset file records
    for rf in raw_files:
        session.add(
            DatasetFile(
                dataset_id=dataset_id,
                relative_path=rf.relative_path,
                sha256=rf.sha256,
                byte_size=rf.byte_size,
                row_count=len(all_rows) if len(raw_files) == 1 else None,
                source_role=rf.source_role,
            )
        )
    session.flush()

    # Step 7: Write partitioned Parquet
    output_path = Path(storage_uri)
    output_path.mkdir(parents=True, exist_ok=True)
    write_parquet_partitioned(all_rows, output_path, source_role=source_role)

    # Step 8: Validate and persist result
    validation_status, summary = _validate_dataset(all_rows, source_role)
    session.add(
        DatasetValidationResult(
            dataset_id=dataset_id,
            validator_version="1.0",
            status=validation_status,
            summary_json=summary,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()

    # Step 9: Update dataset status
    dataset.status = "READY" if validation_status != "FAIL" else "BLOCKED"
    session.commit()

    return ImportResult(
        dataset_id=dataset_id,
        manifest_sha256=manifest.manifest_sha256,
        row_count=manifest.row_count,
        status=dataset.status,
    )


def _validate_dataset(
    rows: list[CanonicalOptionRow | CanonicalUnderlyingRow],
    source_role: str,
) -> tuple[str, dict[str, object]]:
    """Run validation checks on canonical rows.

    Returns (status, summary) where status is PASS/WARN/FAIL.
    """
    from tailhedge.data.validation import validate_option_dataset

    if not rows:
        return "FAIL", {
            "errors": ["Dataset contains no rows"],
            "warnings": [],
            "row_count": 0,
        }

    if source_role == "OPTION_CHAIN":
        row_dicts = [r.model_dump() for r in rows]
        report = validate_option_dataset(row_dicts)
        return report.status, report.summary_json

    # Underlying rows use simpler validation
    warnings: list[str] = []
    errors: list[str] = []
    _validate_underlying_rows(rows, warnings, errors)  # type: ignore[arg-type]

    if errors:
        return "FAIL", {"errors": errors, "warnings": warnings, "row_count": len(rows)}
    return (
        "WARN" if warnings else "PASS",
        {"warnings": warnings, "row_count": len(rows)},
    )


def _validate_underlying_rows(
    rows: list[CanonicalUnderlyingRow],
    warnings: list[str],  # noqa: ARG001 — used by callers for consistency
    errors: list[str],
) -> None:
    """Validate underlying rows for duplicates and basic invariants."""
    seen_keys: set[tuple[datetime, str]] = set()
    for row in rows:
        key = (row.timestamp_utc, row.symbol)
        if key in seen_keys:
            errors.append(f"Duplicate underlying snapshot key: {key}")
        seen_keys.add(key)

        if row.close <= 0:
            errors.append(f"Non-positive close price: {row.close}")
