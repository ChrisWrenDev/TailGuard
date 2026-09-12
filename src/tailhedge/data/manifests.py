"""Dataset manifest model and deterministic hashing.

A manifest captures the provenance and integrity of an imported dataset.
The manifest hash (SHA-256) is computed over a canonical JSON representation
of the manifest fields (excluding the hash itself) and provides a unique,
immutable identifier for the dataset content.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date  # noqa: TC003
from typing import Any

from pydantic import BaseModel, Field, model_validator

from tailhedge.data.canonical_schema import SCHEMA_VERSION

_SCHEMA_VERSION_RE = re.compile(r"^\d+\.\d+$")


class FileHash(BaseModel):
    """Hash and size metadata for a single file within a dataset."""

    relative_path: str = Field(..., min_length=1)
    sha256: str = Field(..., min_length=64, max_length=64)
    byte_size: int = Field(..., ge=0)
    row_count: int | None = Field(None, ge=0)


class DatasetManifest(BaseModel):
    """Immutable metadata describing an imported dataset.

    The ``manifest_sha256`` field is the deterministic hash of all other
    manifest fields and serves as the unique immutable identity of the
    dataset content.
    """

    source_vendor: str = Field(
        ..., min_length=1, description="Data vendor/source identifier."
    )
    schema_version: str = Field(
        ...,
        pattern=r"^\d+\.\d+$",
        description="Canonical schema version used (defaults to SCHEMA_VERSION).",
    )
    timezone: str = Field(
        ..., min_length=1, description="IANA timezone of the dataset."
    )
    start_date: date = Field(..., description="First trade date in the dataset.")
    end_date: date = Field(..., description="Last trade date in the dataset.")
    row_count: int = Field(..., ge=0, description="Total number of rows.")
    file_hashes: list[FileHash] = Field(
        default_factory=list,
        description="Per-file SHA-256 hashes and sizes.",
    )
    manifest_sha256: str = Field(
        default="",
        description="Deterministic SHA-256 of the manifest (filled by compute_hash).",
    )

    @model_validator(mode="after")
    def _date_order(self) -> DatasetManifest:
        if self.end_date < self.start_date:
            msg = (
                f"end_date ({self.end_date}) must be >= start_date ({self.start_date})"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _unique_relative_paths(self) -> DatasetManifest:
        paths = [f.relative_path for f in self.file_hashes]
        if len(paths) != len(set(paths)):
            duplicates = sorted({p for p in paths if paths.count(p) > 1})
            msg = f"duplicate relative_path entries in file_hashes: {duplicates}"
            raise ValueError(msg)
        return self


def _canonical_dict(manifest: DatasetManifest) -> dict[str, Any]:
    """Return a JSON-serialisable dict of the manifest, sorted deterministically.

    The ``manifest_sha256`` field is excluded from the hash input.
    File hashes are sorted by ``relative_path`` for order independence.
    """
    files = sorted(
        [f.model_dump() for f in manifest.file_hashes],
        key=lambda f: f["relative_path"],
    )
    return {
        "source_vendor": manifest.source_vendor,
        "schema_version": manifest.schema_version,
        "timezone": manifest.timezone,
        "start_date": manifest.start_date.isoformat(),
        "end_date": manifest.end_date.isoformat(),
        "row_count": manifest.row_count,
        "file_hashes": files,
    }


def compute_manifest_hash(manifest: DatasetManifest) -> str:
    """Compute a deterministic SHA-256 hash of the manifest content.

    The hash is over a canonical JSON representation (sorted keys, no
    extra whitespace) of all manifest fields except ``manifest_sha256``.
    The result is a 64-character lowercase hex string.
    """
    canonical = _canonical_dict(manifest)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_manifest_integrity(manifest: DatasetManifest) -> list[str]:
    """Verify a manifest's self-consistency.

    Checks that the stored ``manifest_sha256`` matches the recomputed hash,
    that the hash is well-formed 64-char lowercase hex, and that per-file
    ``row_count`` values sum to the total when all files report counts.

    Returns a list of problems found (empty list means the manifest is
    consistent). Callers must treat a non-empty result as a corrupted or
    tampered manifest and fail closed.
    """
    problems: list[str] = []

    if not re.fullmatch(r"[0-9a-f]{64}", manifest.manifest_sha256):
        problems.append(
            f"manifest_sha256 is not 64-char lowercase hex: {manifest.manifest_sha256!r}"
        )

    recomputed = compute_manifest_hash(manifest)
    if manifest.manifest_sha256 and recomputed != manifest.manifest_sha256:
        problems.append(
            f"manifest_sha256 mismatch: stored {manifest.manifest_sha256}, "
            f"recomputed {recomputed}"
        )

    counted = [f.row_count for f in manifest.file_hashes if f.row_count is not None]
    if (
        counted
        and len(counted) == len(manifest.file_hashes)
        and sum(counted) != manifest.row_count
    ):
        problems.append(
            f"row_count ({manifest.row_count}) does not equal the sum of "
            f"per-file row counts ({sum(counted)})"
        )

    return problems


def build_manifest(
    *,
    source_vendor: str,
    schema_version: str = SCHEMA_VERSION,
    timezone: str,
    start_date: date,
    end_date: date,
    row_count: int,
    file_hashes: list[FileHash] | None = None,
) -> DatasetManifest:
    """Construct a ``DatasetManifest`` with its ``manifest_sha256`` pre-computed.

    ``schema_version`` defaults to the current canonical ``SCHEMA_VERSION``.
    """
    manifest = DatasetManifest(
        source_vendor=source_vendor,
        schema_version=schema_version,
        timezone=timezone,
        start_date=start_date,
        end_date=end_date,
        row_count=row_count,
        file_hashes=file_hashes or [],
    )
    manifest.manifest_sha256 = compute_manifest_hash(manifest)
    return manifest
