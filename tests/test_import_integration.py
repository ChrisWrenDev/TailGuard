"""Integration tests for the CSV/Parquet import pipeline with PostgreSQL."""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect, select

from tailhedge.data.import_pipeline import (
    ImportResult,
    run_import,
)
from tailhedge.persistence.models import (
    DatasetFile,
    DatasetValidationResult,
    ResearchDataset,
)
from tests.integration import requires_postgres

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session


def _write_option_csv(path: Path, rows: list[dict[str, object]]) -> None:
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


@pytest.fixture
def option_csv(tmp_path: Path) -> Path:
    """Create a simple valid option CSV fixture."""
    csv_path = tmp_path / "options.csv"
    _write_option_csv(
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
            {
                "trade_date": "2025-01-17",
                "underlying_symbol": "SPX",
                "root_symbol": "XSP",
                "expiration_date": "2025-02-21",
                "strike": 510.0,
                "option_type": "CALL",
                "bid": 15.0,
                "ask": 16.0,
                "underlying_price": 5100.0,
            },
        ],
    )
    return csv_path


@pytest.fixture
def dataset_root(tmp_path: Path) -> str:
    """Create a temporary dataset root directory."""
    root = tmp_path / "data"
    root.mkdir()
    return str(root)


@requires_postgres
class TestImportPipelineIntegration:
    """Integration tests for the full import pipeline with PostgreSQL."""

    def test_import_creates_dataset_and_files(
        self,
        db_session: Session,
        option_csv: Path,
        dataset_root: str,
    ) -> None:
        result = run_import(
            db_session,
            name="Test Options",
            source_vendor="CBOE",
            source_paths=[option_csv],
            dataset_root=dataset_root,
        )

        assert isinstance(result, ImportResult)
        assert result.row_count == 3
        assert result.status == "READY"
        assert result.is_duplicate is False

        # Verify DB records
        dataset = db_session.execute(
            select(ResearchDataset).where(ResearchDataset.id == result.dataset_id)
        ).scalar_one()

        assert dataset.name == "Test Options"
        assert dataset.source_vendor == "CBOE"
        assert dataset.schema_version == "1.0"
        assert dataset.timezone == "America/New_York"
        assert dataset.row_count == 3
        assert dataset.status == "READY"
        assert len(dataset.manifest_sha256) == 64

        # Verify file records
        files = (
            db_session.execute(
                select(DatasetFile).where(DatasetFile.dataset_id == result.dataset_id)
            )
            .scalars()
            .all()
        )
        assert len(files) == 1
        assert files[0].relative_path == "options.csv"
        assert len(files[0].sha256) == 64
        assert files[0].source_role == "OPTION_CHAIN"

        # Verify validation result
        validations = (
            db_session.execute(
                select(DatasetValidationResult).where(
                    DatasetValidationResult.dataset_id == result.dataset_id
                )
            )
            .scalars()
            .all()
        )
        assert len(validations) == 1
        assert validations[0].status in ("PASS", "WARN")

    def test_duplicate_manifest_returns_existing(
        self,
        db_session: Session,
        option_csv: Path,
        dataset_root: str,
    ) -> None:
        # First import
        result1 = run_import(
            db_session,
            name="First Import",
            source_vendor="CBOE",
            source_paths=[option_csv],
            dataset_root=dataset_root,
        )
        assert result1.is_duplicate is False

        # Second import with same files
        result2 = run_import(
            db_session,
            name="Second Import",
            source_vendor="CBOE",
            source_paths=[option_csv],
            dataset_root=dataset_root,
        )
        assert result2.is_duplicate is True
        assert result2.dataset_id == result1.dataset_id
        assert result2.manifest_sha256 == result1.manifest_sha256

    def test_manifest_hash_is_deterministic(
        self,
        db_session: Session,
        option_csv: Path,
        dataset_root: str,
    ) -> None:
        result1 = run_import(
            db_session,
            name="Dataset A",
            source_vendor="CBOE",
            source_paths=[option_csv],
            dataset_root=dataset_root,
        )

        # Import again with same content but different name
        result2 = run_import(
            db_session,
            name="Dataset B",
            source_vendor="CBOE",
            source_paths=[option_csv],
            dataset_root=dataset_root,
        )

        # Same manifest hash because content is identical
        assert result1.manifest_sha256 == result2.manifest_sha256
        # Duplicate detected
        assert result2.is_duplicate is True

    def test_different_files_produce_different_manifests(
        self,
        db_session: Session,
        tmp_path: Path,
        dataset_root: str,
    ) -> None:
        csv1 = tmp_path / "options_a.csv"
        csv2 = tmp_path / "options_b.csv"

        _write_option_csv(
            csv1,
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

        _write_option_csv(
            csv2,
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

        result1 = run_import(
            db_session,
            name="Dataset 1",
            source_vendor="CBOE",
            source_paths=[csv1],
            dataset_root=dataset_root,
        )

        result2 = run_import(
            db_session,
            name="Dataset 2",
            source_vendor="CBOE",
            source_paths=[csv2],
            dataset_root=dataset_root,
        )

        assert result1.manifest_sha256 != result2.manifest_sha256
        assert result1.row_count == 1
        assert result2.row_count == 2

    def test_parquet_parquet_import(
        self,
        db_session: Session,
        tmp_path: Path,
        dataset_root: str,
    ) -> None:
        import polars as pl

        parquet_path = tmp_path / "options.parquet"
        df = pl.DataFrame(
            {
                "snapshot_ts_utc": [
                    "2025-01-15T20:45:00+00:00",
                    "2025-01-16T20:45:00+00:00",
                ],
                "trade_date": ["2025-01-15", "2025-01-16"],
                "source": ["CBOE", "CBOE"],
                "underlying_symbol": ["SPX", "SPX"],
                "root_symbol": ["XSP", "XSP"],
                "expiration_date": ["2025-02-21", "2025-02-21"],
                "strike": [500.0, 500.0],
                "option_type": ["PUT", "PUT"],
                "bid": [10.0, 10.5],
                "ask": [11.0, 11.5],
                "underlying_price": [5000.0, 5050.0],
            }
        )
        df.write_parquet(parquet_path)

        result = run_import(
            db_session,
            name="Parquet Dataset",
            source_vendor="CBOE",
            source_paths=[parquet_path],
            dataset_root=dataset_root,
        )

        assert result.row_count == 2
        assert result.status == "READY"

    def test_validation_blocks_invalid_data(
        self,
        db_session: Session,
        tmp_path: Path,
        dataset_root: str,
    ) -> None:
        csv_path = tmp_path / "invalid.csv"
        _write_option_csv(
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
                    "trade_date": "2025-01-15",
                    "underlying_symbol": "SPX",
                    "root_symbol": "XSP",
                    "expiration_date": "2025-02-21",
                    "strike": 500.0,
                    "option_type": "PUT",
                    "bid": 12.0,
                    "ask": 13.0,
                    "underlying_price": 5000.0,
                },
            ],
        )

        result = run_import(
            db_session,
            name="Invalid Dataset",
            source_vendor="CBOE",
            source_paths=[csv_path],
            dataset_root=dataset_root,
        )

        # Duplicate snapshot key causes BLOCKED status
        assert result.status == "BLOCKED"

        # Verify validation result is FAIL
        validations = (
            db_session.execute(
                select(DatasetValidationResult).where(
                    DatasetValidationResult.dataset_id == result.dataset_id
                )
            )
            .scalars()
            .all()
        )
        assert len(validations) == 1
        assert validations[0].status == "FAIL"
        assert "errors" in validations[0].summary_json


@requires_postgres
class TestImportPipelineSchemaCreation:
    """Verify that dataset tables exist and have correct structure."""

    def test_dataset_tables_exist(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        tables = sorted(inspector.get_table_names())
        assert "research_dataset" in tables
        assert "dataset_file" in tables
        assert "dataset_validation_result" in tables

    def test_research_dataset_columns(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        cols = {c["name"] for c in inspector.get_columns("research_dataset")}
        assert {
            "id",
            "name",
            "source_vendor",
            "schema_version",
            "timezone",
            "start_date",
            "end_date",
            "row_count",
            "manifest_sha256",
            "storage_uri",
            "status",
            "created_at",
        } <= cols

    def test_dataset_file_foreign_key(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        fks = inspector.get_foreign_keys("dataset_file")
        assert any(fk["referred_table"] == "research_dataset" for fk in fks)

    def test_manifest_sha256_unique(self, db_session: Session) -> None:
        inspector = inspect(db_session.get_bind())
        indexes = inspector.get_indexes("research_dataset")
        unique_indexes = [idx for idx in indexes if idx.get("unique")]
        assert any(
            "manifest_sha256" in idx.get("column_names", []) for idx in unique_indexes
        )
