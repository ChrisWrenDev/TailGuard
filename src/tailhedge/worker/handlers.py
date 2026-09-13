"""Job handlers for background tasks."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tailhedge.data.import_pipeline import run_import
from tailhedge.persistence.engine import get_session

logger = logging.getLogger(__name__)


def dataset_import_handler(payload: dict[str, Any]) -> None:
    """Handle a ``dataset_import`` job.

    Expected payload keys:
        - ``name``: User-facing dataset name.
        - ``source_vendor``: Vendor identifier.
        - ``source_paths``: List of file path strings.
        - ``source_role``: ``"OPTION_CHAIN"`` or ``"UNDERLYING"``.
        - ``timezone``: IANA timezone string.
        - ``dataset_root``: Root directory for dataset storage.
    """
    name = payload["name"]
    source_vendor = payload["source_vendor"]
    source_paths = [Path(p) for p in payload["source_paths"]]
    source_role = payload.get("source_role", "OPTION_CHAIN")
    timezone = payload.get("timezone", "America/New_York")
    dataset_root = payload.get("dataset_root", "data")

    logger.info(
        "Starting dataset import: name=%s vendor=%s files=%d",
        name,
        source_vendor,
        len(source_paths),
    )

    # get_session is a generator dependency (FastAPI), not a context
    # manager; wrap it for commit-on-success/rollback semantics.
    with contextmanager(get_session)() as session:
        result = run_import(
            session,
            name=name,
            source_vendor=source_vendor,
            source_paths=source_paths,
            source_role=source_role,
            timezone=timezone,
            dataset_root=dataset_root,
        )

    logger.info(
        "Dataset import complete: id=%s rows=%d status=%s duplicate=%s",
        result.dataset_id,
        result.row_count,
        result.status,
        result.is_duplicate,
    )
