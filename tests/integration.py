"""Helpers for PostgreSQL-backed integration tests.

Integration tests run when ``TAILHEDGE_TEST_DATABASE_URL`` points at a
PostgreSQL database (CI provisions one as a service; locally use
``docker compose up -d`` and export the variable).
"""

from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.environ.get("TAILHEDGE_TEST_DATABASE_URL")

requires_postgres = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason=(
        "Integration tests require PostgreSQL; set TAILHEDGE_TEST_DATABASE_URL "
        "(e.g. postgresql+psycopg://tailhedge:tailhedge@localhost:5432/tailhedge_test)"
    ),
)
