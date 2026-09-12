"""Integration tests for the DuckDB research repository.

These tests create small partitioned Parquet datasets and verify that
date/instrument queries are deterministic and partition-pruned where
practical (TASK-017 acceptance criteria).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import duckdb
import pytest

from tailhedge.data.canonical_schema import (
    CanonicalOptionRow,
    CanonicalUnderlyingRow,
    OptionType,
)
from tailhedge.data.duckdb_repository import DuckDBRepository
from tailhedge.data.import_pipeline import write_parquet_partitioned

if TYPE_CHECKING:
    from pathlib import Path


def _option_row(
    trade_date: date,
    underlying_symbol: str,
    root_symbol: str,
    expiration_date: date,
    strike: float,
    option_type: OptionType,
    bid: float,
    ask: float,
    underlying_price: float,
) -> CanonicalOptionRow:
    """Create a CanonicalOptionRow with optional fields set to None."""
    return CanonicalOptionRow(
        snapshot_ts_utc=datetime(
            trade_date.year, trade_date.month, trade_date.day, 20, 45, tzinfo=UTC
        ),
        trade_date=trade_date,
        source="TEST",
        underlying_symbol=underlying_symbol,
        root_symbol=root_symbol,
        expiration_date=expiration_date,
        strike=strike,
        option_type=option_type,
        bid=bid,
        ask=ask,
        bid_size=None,
        ask_size=None,
        volume=None,
        open_interest=None,
        underlying_price=underlying_price,
        implied_volatility=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
        source_contract_id=None,
    )


def _underlying_row(
    trade_date: date,
    symbol: str,
    close: float,
    currency: str = "USD",
) -> CanonicalUnderlyingRow:
    """Create a CanonicalUnderlyingRow with optional fields set to None."""
    return CanonicalUnderlyingRow(
        timestamp_utc=datetime(
            trade_date.year, trade_date.month, trade_date.day, 20, 0, tzinfo=UTC
        ),
        trade_date=trade_date,
        symbol=symbol,
        currency=currency,
        open=None,
        high=None,
        low=None,
        close=close,
        adjusted_close=None,
        total_return_index=None,
        source="TEST",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def option_dataset(tmp_path: Path) -> Path:
    """Create a small option dataset with multiple partitions.

    Layout:
      options/
        underlying_symbol=SPX/year=2025/month=01/*.parquet  (3 rows)
        underlying_symbol=SPX/year=2025/month=02/*.parquet  (2 rows)
        underlying_symbol=XSP/year=2025/month=01/*.parquet  (1 row)
    """
    rows = [
        # SPX Jan 2025
        _option_row(
            trade_date=date(2025, 1, 15),
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=5000.0,
            option_type=OptionType.PUT,
            bid=100.0,
            ask=105.0,
            underlying_price=5000.0,
        ),
        _option_row(
            trade_date=date(2025, 1, 16),
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=5000.0,
            option_type=OptionType.PUT,
            bid=105.0,
            ask=110.0,
            underlying_price=4980.0,
        ),
        _option_row(
            trade_date=date(2025, 1, 17),
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=4900.0,
            option_type=OptionType.PUT,
            bid=110.0,
            ask=115.0,
            underlying_price=4950.0,
        ),
        # SPX Feb 2025
        _option_row(
            trade_date=date(2025, 2, 15),
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 3, 21),
            strike=5100.0,
            option_type=OptionType.CALL,
            bid=50.0,
            ask=55.0,
            underlying_price=5100.0,
        ),
        _option_row(
            trade_date=date(2025, 2, 16),
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 3, 21),
            strike=5100.0,
            option_type=OptionType.CALL,
            bid=55.0,
            ask=60.0,
            underlying_price=5150.0,
        ),
        # XSP Jan 2025
        _option_row(
            trade_date=date(2025, 1, 15),
            underlying_symbol="XSP",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=500.0,
            option_type=OptionType.PUT,
            bid=10.0,
            ask=11.0,
            underlying_price=5000.0,
        ),
    ]

    output_dir = tmp_path / "normalized" / "dataset1" / "options"
    output_dir.mkdir(parents=True)
    write_parquet_partitioned(rows, output_dir, source_role="OPTION_CHAIN")  # type: ignore[arg-type]
    return tmp_path / "normalized" / "dataset1"


@pytest.fixture
def underlying_dataset(tmp_path: Path) -> Path:
    """Create a small underlying dataset with multiple partitions.

    Layout:
      underlying/
        year=2025/*.parquet  (3 rows)
    """
    rows = [
        _underlying_row(
            trade_date=date(2025, 1, 15),
            symbol="SPX",
            close=5000.0,
        ),
        _underlying_row(
            trade_date=date(2025, 1, 16),
            symbol="SPX",
            close=4980.0,
        ),
        _underlying_row(
            trade_date=date(2025, 1, 17),
            symbol="SPX",
            close=4950.0,
        ),
    ]

    output_dir = tmp_path / "normalized" / "dataset2" / "underlying"
    output_dir.mkdir(parents=True)
    write_parquet_partitioned(rows, output_dir, source_role="UNDERLYING")  # type: ignore[arg-type]
    return tmp_path / "normalized" / "dataset2"


@pytest.fixture
def combined_dataset(tmp_path: Path) -> Path:
    """Create a dataset with both options and underlying data."""
    option_rows = [
        _option_row(
            trade_date=date(2025, 1, 15),
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=5000.0,
            option_type=OptionType.PUT,
            bid=100.0,
            ask=105.0,
            underlying_price=5000.0,
        ),
        _option_row(
            trade_date=date(2025, 1, 16),
            underlying_symbol="SPX",
            root_symbol="XSP",
            expiration_date=date(2025, 2, 21),
            strike=5000.0,
            option_type=OptionType.PUT,
            bid=105.0,
            ask=110.0,
            underlying_price=4980.0,
        ),
    ]

    underlying_rows = [
        _underlying_row(
            trade_date=date(2025, 1, 15),
            symbol="SPX",
            close=5000.0,
        ),
        _underlying_row(
            trade_date=date(2025, 1, 16),
            symbol="SPX",
            close=4980.0,
        ),
    ]

    root = tmp_path / "normalized" / "combined"
    options_dir = root / "options"
    options_dir.mkdir(parents=True)
    write_parquet_partitioned(option_rows, options_dir, source_role="OPTION_CHAIN")  # type: ignore[arg-type]

    underlying_dir = root / "underlying"
    underlying_dir.mkdir(parents=True)
    write_parquet_partitioned(underlying_rows, underlying_dir, source_role="UNDERLYING")  # type: ignore[arg-type]

    return root


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


class TestDuckDBRepositoryConnection:
    """Test connection management."""

    def test_connect_creates_connection(self, option_dataset: Path) -> None:
        repo = DuckDBRepository(option_dataset)
        con = repo.connect()
        assert con is not None
        repo.close()

    def test_context_manager(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            count = repo.count_option_rows()
            assert count == 6

    def test_close_idempotent(self, option_dataset: Path) -> None:
        repo = DuckDBRepository(option_dataset)
        repo.connect()
        repo.close()
        repo.close()  # should not raise

    def test_query_before_connect_raises(self, option_dataset: Path) -> None:
        repo = DuckDBRepository(option_dataset)
        with pytest.raises(RuntimeError, match="not connected"):
            repo.count_option_rows()


# ---------------------------------------------------------------------------
# Option chain query tests
# ---------------------------------------------------------------------------


class TestOptionChainQueries:
    """Test option chain query methods."""

    def test_query_all(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain()
            assert len(results) == 6

    def test_query_by_date_range(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain(
                start_date=date(2025, 1, 15),
                end_date=date(2025, 1, 16),
            )
            assert len(results) == 3  # 2 SPX + 1 XSP on Jan 15, 1 SPX on Jan 16
            assert all(r.trade_date in ("2025-01-15", "2025-01-16") for r in results)

    def test_query_single_date(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain_for_date(date(2025, 1, 15))
            assert len(results) == 2  # SPX + XSP

    def test_query_by_underlying_symbol(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain(underlying_symbol="XSP")
            assert len(results) == 1
            assert results[0].underlying_symbol == "XSP"
            assert results[0].strike == 500.0

    def test_query_by_root_symbol(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain(root_symbol="XSP")
            assert len(results) == 6

    def test_query_by_expiration_date(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain(
                expiration_date=date(2025, 3, 21),
            )
            assert len(results) == 2
            assert all(r.expiration_date == "2025-03-21" for r in results)

    def test_query_by_strike(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain(strike=4900.0)
            assert len(results) == 1
            assert results[0].strike == 4900.0

    def test_query_by_option_type(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            calls = repo.query_option_chain(option_type="CALL")
            puts = repo.query_option_chain(option_type="PUT")
            assert len(calls) == 2
            assert len(puts) == 4

    def test_combined_filters(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain(
                start_date=date(2025, 1, 15),
                end_date=date(2025, 1, 17),
                underlying_symbol="SPX",
                option_type="PUT",
            )
            assert len(results) == 3
            assert all(r.underlying_symbol == "SPX" for r in results)
            assert all(r.option_type == "PUT" for r in results)

    def test_no_results_for_empty_filter(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain(underlying_symbol="NONEXISTENT")
            assert len(results) == 0

    def test_result_fields_populated(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain_for_date(date(2025, 1, 15))
            assert len(results) == 2
            for r in results:
                assert "2025-01-15" in r.snapshot_ts_utc
                assert r.source == "TEST"
                assert r.root_symbol == "XSP"
                assert r.bid > 0
                assert r.ask > 0
                assert r.underlying_price > 0


# ---------------------------------------------------------------------------
# Underlying query tests
# ---------------------------------------------------------------------------


class TestUnderlyingQueries:
    """Test underlying series query methods."""

    def test_query_all(self, underlying_dataset: Path) -> None:
        with DuckDBRepository(underlying_dataset) as repo:
            results = repo.query_underlying()
            assert len(results) == 3

    def test_query_by_date_range(self, underlying_dataset: Path) -> None:
        with DuckDBRepository(underlying_dataset) as repo:
            results = repo.query_underlying(
                start_date=date(2025, 1, 15),
                end_date=date(2025, 1, 16),
            )
            assert len(results) == 2

    def test_query_single_date(self, underlying_dataset: Path) -> None:
        with DuckDBRepository(underlying_dataset) as repo:
            results = repo.query_underlying_for_date(date(2025, 1, 15))
            assert len(results) == 1
            assert results[0].symbol == "SPX"
            assert results[0].close == 5000.0

    def test_query_by_symbol(self, underlying_dataset: Path) -> None:
        with DuckDBRepository(underlying_dataset) as repo:
            results = repo.query_underlying(symbol="SPX")
            assert len(results) == 3

    def test_result_fields(self, underlying_dataset: Path) -> None:
        with DuckDBRepository(underlying_dataset) as repo:
            results = repo.query_underlying_for_date(date(2025, 1, 15))
            r = results[0]
            assert r.trade_date == "2025-01-15"
            assert r.currency == "USD"
            assert r.close == 5000.0
            assert r.source == "TEST"


# ---------------------------------------------------------------------------
# Combined dataset tests
# ---------------------------------------------------------------------------


class TestCombinedDataset:
    """Test querying a dataset with both options and underlying."""

    def test_option_and_underlying_queries(self, combined_dataset: Path) -> None:
        with DuckDBRepository(combined_dataset) as repo:
            options = repo.query_option_chain()
            underlying = repo.query_underlying()
            assert len(options) == 2
            assert len(underlying) == 2

    def test_correlated_queries(self, combined_dataset: Path) -> None:
        with DuckDBRepository(combined_dataset) as repo:
            for d in [date(2025, 1, 15), date(2025, 1, 16)]:
                opts = repo.query_option_chain_for_date(d)
                under = repo.query_underlying_for_date(d)
                assert len(opts) == 1
                assert len(under) == 1
                # Underlying price matches option's underlying_price
                assert opts[0].underlying_price == under[0].close


# ---------------------------------------------------------------------------
# Aggregate query tests
# ---------------------------------------------------------------------------


class TestAggregateQueries:
    """Test count and distinct queries."""

    def test_count_option_rows(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            total = repo.count_option_rows()
            assert total == 6
            spx_count = repo.count_option_rows(underlying_symbol="SPX")
            assert spx_count == 5
            xsp_count = repo.count_option_rows(underlying_symbol="XSP")
            assert xsp_count == 1

    def test_count_by_date_range(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            jan_count = repo.count_option_rows(
                start_date=date(2025, 1, 15),
                end_date=date(2025, 1, 31),
            )
            assert (
                jan_count == 4
            )  # 2 SPX (Jan 15) + 1 XSP (Jan 15) + 1 SPX (Jan 16) + 1 SPX (Jan 17) = 4

    def test_count_underlying_rows(self, underlying_dataset: Path) -> None:
        with DuckDBRepository(underlying_dataset) as repo:
            total = repo.count_underlying_rows()
            assert total == 3

    def test_distinct_trade_dates(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            dates = repo.distinct_trade_dates(table="option_chain")
            assert len(dates) == 5  # 3 Jan + 2 Feb
            assert dates[0] == date(2025, 1, 15)
            assert dates[-1] == date(2025, 2, 16)

    def test_distinct_underlying_symbols(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            symbols = repo.distinct_underlying_symbols()
            assert symbols == ["SPX", "XSP"]

    def test_distinct_dates_invalid_table(self, option_dataset: Path) -> None:
        with (
            DuckDBRepository(option_dataset) as repo,
            pytest.raises(ValueError, match="Unknown table"),
        ):
            repo.distinct_trade_dates(table="nonexistent")


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Verify queries are deterministic across multiple executions."""

    def test_same_query_same_results(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            r1 = repo.query_option_chain(
                start_date=date(2025, 1, 15),
                underlying_symbol="SPX",
            )
            r2 = repo.query_option_chain(
                start_date=date(2025, 1, 15),
                underlying_symbol="SPX",
            )
            assert len(r1) == len(r2)
            for a, b in zip(r1, r2, strict=True):
                assert a.strike == b.strike
                assert a.bid == b.bid
                assert a.ask == b.ask
                assert a.trade_date == b.trade_date

    def test_count_deterministic(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            c1 = repo.count_option_rows()
            c2 = repo.count_option_rows()
            assert c1 == c2

    def test_polars_deterministic(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            df1 = repo.query_option_chain_polars(underlying_symbol="SPX")
            df2 = repo.query_option_chain_polars(underlying_symbol="SPX")
            assert df1.shape == df2.shape
            assert df1.columns == df2.columns


# ---------------------------------------------------------------------------
# Polars integration tests
# ---------------------------------------------------------------------------


class TestPolarsIntegration:
    """Test Polars DataFrame return path."""

    def test_polars_query(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            df = repo.query_option_chain_polars()
            assert df.shape[0] == 6
            assert "strike" in df.columns
            assert "bid" in df.columns
            assert "underlying_symbol" in df.columns

    def test_polars_with_filters(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            df = repo.query_option_chain_polars(
                start_date=date(2025, 1, 15),
                end_date=date(2025, 1, 15),
                underlying_symbol="SPX",
            )
            assert df.shape[0] == 1
            assert df["underlying_symbol"][0] == "SPX"

    def test_polars_empty_result(self, option_dataset: Path) -> None:
        with DuckDBRepository(option_dataset) as repo:
            df = repo.query_option_chain_polars(underlying_symbol="NONEXISTENT")
            assert df.shape[0] == 0


# ---------------------------------------------------------------------------
# Partition pruning verification
# ---------------------------------------------------------------------------


class TestPartitionPruning:
    """Verify that partition pruning works correctly.

    DuckDB automatically prunes partitions when filtering on partition
    columns.  These tests verify that filtered queries return only the
    expected rows from the correct partitions.
    """

    def test_date_filter_prunes_months(self, option_dataset: Path) -> None:
        """Filtering by Jan only returns Jan partitions."""
        with DuckDBRepository(option_dataset) as repo:
            jan = repo.query_option_chain(
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
            )
            feb = repo.query_option_chain(
                start_date=date(2025, 2, 1),
                end_date=date(2025, 2, 28),
            )
            assert len(jan) == 4  # 1 SPX+1 XSP Jan 15 + 1 SPX Jan 16 + 1 SPX Jan 17
            assert len(feb) == 2  # 2 SPX Feb rows
            # No overlap
            jan_dates = {r.trade_date for r in jan}
            feb_dates = {r.trade_date for r in feb}
            assert jan_dates.isdisjoint(feb_dates)

    def test_underlying_filter_prunes_symbols(self, option_dataset: Path) -> None:
        """Filtering by underlying_symbol prunes to correct partitions."""
        with DuckDBRepository(option_dataset) as repo:
            spx = repo.query_option_chain(underlying_symbol="SPX")
            xsp = repo.query_option_chain(underlying_symbol="XSP")
            assert len(spx) == 5
            assert len(xsp) == 1
            assert all(r.underlying_symbol == "SPX" for r in spx)
            assert all(r.underlying_symbol == "XSP" for r in xsp)

    def test_combined_partition_pruning(self, option_dataset: Path) -> None:
        """Filtering by both date and underlying prunes both levels."""
        with DuckDBRepository(option_dataset) as repo:
            results = repo.query_option_chain(
                start_date=date(2025, 2, 1),
                end_date=date(2025, 2, 28),
                underlying_symbol="SPX",
            )
            assert len(results) == 2
            assert all(r.underlying_symbol == "SPX" for r in results)
            assert all(r.trade_date.startswith("2025-02") for r in results)


# ---------------------------------------------------------------------------
# Missing dataset handling
# ---------------------------------------------------------------------------


class TestMissingDataset:
    """Test behaviour when dataset directories are missing."""

    def test_missing_options_dir(self, tmp_path: Path) -> None:
        """Repository works with only underlying data."""
        rows = [
            _underlying_row(
                trade_date=date(2025, 1, 15),
                symbol="SPX",
                close=5000.0,
            ),
        ]
        output_dir = tmp_path / "underlying"
        output_dir.mkdir()
        write_parquet_partitioned(rows, output_dir, source_role="UNDERLYING")  # type: ignore[arg-type]

        repo = DuckDBRepository(tmp_path)
        repo.connect()
        results = repo.query_underlying()
        assert len(results) == 1
        repo.close()

    def test_missing_underlying_dir(self, tmp_path: Path) -> None:
        """Repository works with only option data."""
        rows = [
            _option_row(
                trade_date=date(2025, 1, 15),
                underlying_symbol="SPX",
                root_symbol="XSP",
                expiration_date=date(2025, 2, 21),
                strike=5000.0,
                option_type=OptionType.PUT,
                bid=100.0,
                ask=105.0,
                underlying_price=5000.0,
            ),
        ]
        output_dir = tmp_path / "options"
        output_dir.mkdir()
        write_parquet_partitioned(rows, output_dir, source_role="OPTION_CHAIN")  # type: ignore[arg-type]

        repo = DuckDBRepository(tmp_path)
        repo.connect()
        results = repo.query_option_chain()
        assert len(results) == 1
        repo.close()

    def test_empty_dataset_root(self, tmp_path: Path) -> None:
        """Repository handles empty dataset root gracefully."""
        repo = DuckDBRepository(tmp_path)
        repo.connect()
        # Tables won't be registered; queries will fail with a CatalogException
        with pytest.raises(duckdb.CatalogException, match="does not exist"):
            repo.query_option_chain()
        repo.close()
