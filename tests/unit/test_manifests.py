"""Unit tests for dataset manifest and deterministic hashing."""

from __future__ import annotations

from datetime import date

import pytest

from tailhedge.data.manifests import (
    DatasetManifest,
    FileHash,
    build_manifest,
    compute_manifest_hash,
)


class TestDatasetManifest:
    """Validation tests for the manifest model."""

    def test_valid_manifest(self) -> None:
        manifest = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2020, 1, 2),
            end_date=date(2024, 12, 31),
            row_count=1000,
        )
        assert manifest.source_vendor == "CBOE"
        assert manifest.row_count == 1000

    def test_end_date_before_start_date_rejected(self) -> None:
        with pytest.raises(ValueError, match="end_date.*must be >= start_date"):
            DatasetManifest(
                source_vendor="CBOE",
                schema_version="1.0",
                timezone="America/New_York",
                start_date=date(2024, 12, 31),
                end_date=date(2020, 1, 2),
                row_count=1000,
            )

    def test_equal_start_end_date_allowed(self) -> None:
        manifest = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 15),
            row_count=1,
        )
        assert manifest.start_date == manifest.end_date

    def test_file_hashes_optional(self) -> None:
        manifest = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 1, 15),
            row_count=1,
        )
        assert manifest.file_hashes == []


class TestFileHash:
    """Validation for per-file hash entries."""

    def test_valid_file_hash(self) -> None:
        fh = FileHash(
            relative_path="options/data.parquet",
            sha256="a" * 64,
            byte_size=1024,
            row_count=100,
        )
        assert fh.relative_path == "options/data.parquet"

    def test_short_sha256_rejected(self) -> None:
        with pytest.raises(ValueError):
            FileHash(
                relative_path="options/data.parquet",
                sha256="abc",
                byte_size=1024,
            )


class TestComputeManifestHash:
    """Deterministic hash computation."""

    def test_same_content_same_hash(self) -> None:
        m1 = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=1000,
        )
        m2 = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=1000,
        )
        assert compute_manifest_hash(m1) == compute_manifest_hash(m2)

    def test_different_content_different_hash(self) -> None:
        m1 = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=1000,
        )
        m2 = DatasetManifest(
            source_vendor="ORATS",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=1000,
        )
        assert compute_manifest_hash(m1) != compute_manifest_hash(m2)

    def test_hash_independent_of_file_order(self) -> None:
        files_a = [
            FileHash(relative_path="a.parquet", sha256="a" * 64, byte_size=100),
            FileHash(relative_path="b.parquet", sha256="b" * 64, byte_size=200),
        ]
        files_b = [
            FileHash(relative_path="b.parquet", sha256="b" * 64, byte_size=200),
            FileHash(relative_path="a.parquet", sha256="a" * 64, byte_size=100),
        ]
        m1 = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=1000,
            file_hashes=files_a,
        )
        m2 = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=1000,
            file_hashes=files_b,
        )
        assert compute_manifest_hash(m1) == compute_manifest_hash(m2)

    def test_hash_is_64_char_hex(self) -> None:
        manifest = DatasetManifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=0,
        )
        h = compute_manifest_hash(manifest)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestBuildManifest:
    """Convenience builder that pre-computes the hash."""

    def test_build_populates_hash(self) -> None:
        manifest = build_manifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=500,
        )
        assert manifest.manifest_sha256 != ""
        assert len(manifest.manifest_sha256) == 64

    def test_build_hash_matches_compute(self) -> None:
        manifest = build_manifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=500,
        )
        assert manifest.manifest_sha256 == compute_manifest_hash(manifest)

    def test_build_deterministic(self) -> None:
        m1 = build_manifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=500,
        )
        m2 = build_manifest(
            source_vendor="CBOE",
            schema_version="1.0",
            timezone="America/New_York",
            start_date=date(2025, 1, 15),
            end_date=date(2025, 12, 31),
            row_count=500,
        )
        assert m1.manifest_sha256 == m2.manifest_sha256
