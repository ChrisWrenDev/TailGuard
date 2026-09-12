"""DuckDB research repository for querying canonical Parquet data.

Provides read-only access to partitioned Parquet datasets without loading
data into PostgreSQL.  DuckDB queries Parquet in place (TECHNICAL_ARCHITECTURE
§7.3), enabling efficient date/instrument queries with automatic partition
pruning.

All queries are deterministic: identical inputs always produce identical
results.  The repository never mutates source data.

Partition layout (FR-002):
  options/:  underlying_symbol=SPX/year=2025/month=01/*.parquet
  underlying/:  year=2025/*.parquet

DuckDB automatically prunes partitions when filters reference partition
columns (underlying_symbol, year, month).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

import duckdb
import polars as pl

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionQuoteResult:
    """A single option quote row returned by repository queries."""

    snapshot_ts_utc: str
    trade_date: str
    source: str
    underlying_symbol: str
    root_symbol: str
    expiration_date: str
    strike: float
    option_type: str
    bid: float
    ask: float
    bid_size: int | None
    ask_size: int | None
    volume: int | None
    open_interest: int | None
    underlying_price: float
    implied_volatility: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    source_contract_id: str | None


@dataclass(frozen=True)
class UnderlyingQuoteResult:
    """A single underlying row returned by repository queries."""

    timestamp_utc: str
    trade_date: str
    symbol: str
    currency: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    adjusted_close: float | None
    total_return_index: float | None
    source: str


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class DuckDBRepository:
    """Read-only query layer over partitioned Parquet datasets.

    Create an instance pointing at a dataset root directory containing
    ``options/`` and/or ``underlying/`` sub-directories with partitioned
    Parquet files.

    Parameters
    ----------
    dataset_root : Path
        Root directory of the normalized dataset (the ``storage_uri`` from
        the ``research_dataset`` record).
    """

    def __init__(self, dataset_root: Path) -> None:
        self._dataset_root = dataset_root
        self._con: duckdb.DuckDBPyConnection | None = None

    # -- connection management -----------------------------------------------

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Open an in-memory DuckDB connection and register Parquet tables.

        The connection is read-only; no write operations are supported.
        """
        if self._con is not None:
            return self._con

        self._con = duckdb.connect(":memory:")
        self._register_tables()
        return self._con

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._con is not None:
            self._con.close()
            self._con = None

    def __enter__(self) -> DuckDBRepository:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- table registration --------------------------------------------------

    def _register_tables(self) -> None:
        """Register Parquet directories as DuckDB tables.

        DuckDB reads partitioned Parquet automatically.  Partition columns
        become regular columns in the virtual table, and DuckDB prunes
        non-matching partitions when filters reference them.
        """
        con = self._con
        assert con is not None

        options_dir = self._dataset_root / "options"
        if options_dir.is_dir():
            parquet_files = list(options_dir.rglob("*.parquet"))
            if parquet_files:
                # DuckDB read_parquet does not support prepared parameters for paths.
                # The path is a local filesystem path constructed from trusted input
                # (dataset_root from configuration), not user-supplied SQL.
                con.execute(
                    f"CREATE VIEW option_chain AS "
                    f"SELECT * FROM read_parquet('{options_dir}', hive_partitioning=true)"
                )
                logger.info(
                    "Registered option_chain view from %s",
                    options_dir,
                )

        underlying_dir = self._dataset_root / "underlying"
        if underlying_dir.is_dir():
            parquet_files = list(underlying_dir.rglob("*.parquet"))
            if parquet_files:
                con.execute(
                    f"CREATE VIEW underlying_series AS "
                    f"SELECT * FROM read_parquet('{underlying_dir}', hive_partitioning=true)"
                )
                logger.info(
                    "Registered underlying_series view from %s",
                    underlying_dir,
                )

    # -- option chain queries ------------------------------------------------

    def query_option_chain(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        underlying_symbol: str | None = None,
        root_symbol: str | None = None,
        expiration_date: date | None = None,
        strike: float | None = None,
        option_type: str | None = None,
    ) -> list[OptionQuoteResult]:
        """Query option chain snapshots with optional date/instrument filters.

        Filters are ANDed together.  Empty filters return all rows.
        Partition columns (underlying_symbol, year, month) are pruned
        automatically when the corresponding filters are provided.

        Parameters
        ----------
        start_date, end_date : date, optional
            Inclusive date range on ``trade_date``.
        underlying_symbol : str, optional
            Filter by underlying symbol (e.g. ``"SPX"``).
        root_symbol : str, optional
            Filter by root symbol (e.g. ``"XSP"``).
        expiration_date : date, optional
            Filter to a specific expiration date.
        strike : float, optional
            Filter to a specific strike price.
        option_type : str, optional
            Filter to ``"PUT"`` or ``"CALL"``.

        Returns
        -------
        list[OptionQuoteResult]
            Matching rows sorted by (trade_date, strike, expiration_date).
        """
        con = self._connect_or_raise()

        conditions: list[str] = []
        params: list[Any] = []

        if start_date is not None:
            conditions.append("trade_date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            conditions.append("trade_date <= ?")
            params.append(end_date.isoformat())
        if underlying_symbol is not None:
            conditions.append("underlying_symbol = ?")
            params.append(underlying_symbol)
        if root_symbol is not None:
            conditions.append("root_symbol = ?")
            params.append(root_symbol)
        if expiration_date is not None:
            conditions.append("expiration_date = ?")
            params.append(expiration_date.isoformat())
        if strike is not None:
            conditions.append("strike = ?")
            params.append(strike)
        if option_type is not None:
            conditions.append("option_type = ?")
            params.append(option_type)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM option_chain{where} ORDER BY trade_date, strike, expiration_date"

        rows = con.execute(sql, params).fetchall()
        columns = [desc[0] for desc in con.description]
        return [self._row_to_option_result(row, columns) for row in rows]

    def query_option_chain_for_date(
        self,
        trade_date: date,
        *,
        underlying_symbol: str | None = None,
        root_symbol: str | None = None,
    ) -> list[OptionQuoteResult]:
        """Convenience: all option quotes for a single trade date.

        Partition pruning is maximised because the date filter narrows
        to specific year/month partitions.
        """
        return self.query_option_chain(
            start_date=trade_date,
            end_date=trade_date,
            underlying_symbol=underlying_symbol,
            root_symbol=root_symbol,
        )

    def query_option_chain_for_instrument(
        self,
        *,
        underlying_symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        expiration_date: date | None = None,
        strike: float | None = None,
        option_type: str | None = None,
    ) -> list[OptionQuoteResult]:
        """Convenience: option quotes for a specific underlying instrument.

        The underlying_symbol filter enables full partition pruning on
        the first partition level.
        """
        return self.query_option_chain(
            start_date=start_date,
            end_date=end_date,
            underlying_symbol=underlying_symbol,
            expiration_date=expiration_date,
            strike=strike,
            option_type=option_type,
        )

    # -- underlying queries --------------------------------------------------

    def query_underlying(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        symbol: str | None = None,
    ) -> list[UnderlyingQuoteResult]:
        """Query underlying price series with optional date/symbol filters.

        Parameters
        ----------
        start_date, end_date : date, optional
            Inclusive date range on ``trade_date``.
        symbol : str, optional
            Filter by instrument symbol.

        Returns
        -------
        list[UnderlyingQuoteResult]
            Matching rows sorted by trade_date.
        """
        con = self._connect_or_raise()

        conditions: list[str] = []
        params: list[Any] = []

        if start_date is not None:
            conditions.append("trade_date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            conditions.append("trade_date <= ?")
            params.append(end_date.isoformat())
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM underlying_series{where} ORDER BY trade_date"

        rows = con.execute(sql, params).fetchall()
        columns = [desc[0] for desc in con.description]
        return [self._row_to_underlying_result(row, columns) for row in rows]

    def query_underlying_for_date(
        self,
        trade_date: date,
        *,
        symbol: str | None = None,
    ) -> list[UnderlyingQuoteResult]:
        """Convenience: all underlying rows for a single trade date."""
        return self.query_underlying(
            start_date=trade_date,
            end_date=trade_date,
            symbol=symbol,
        )

    # -- aggregate queries ---------------------------------------------------

    def count_option_rows(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        underlying_symbol: str | None = None,
    ) -> int:
        """Return the count of option rows matching the given filters."""
        con = self._connect_or_raise()

        conditions: list[str] = []
        params: list[Any] = []

        if start_date is not None:
            conditions.append("trade_date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            conditions.append("trade_date <= ?")
            params.append(end_date.isoformat())
        if underlying_symbol is not None:
            conditions.append("underlying_symbol = ?")
            params.append(underlying_symbol)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT COUNT(*) FROM option_chain{where}"

        result = con.execute(sql, params).fetchone()
        return result[0] if result is not None else 0

    def count_underlying_rows(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        symbol: str | None = None,
    ) -> int:
        """Return the count of underlying rows matching the given filters."""
        con = self._connect_or_raise()

        conditions: list[str] = []
        params: list[Any] = []

        if start_date is not None:
            conditions.append("trade_date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            conditions.append("trade_date <= ?")
            params.append(end_date.isoformat())
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT COUNT(*) FROM underlying_series{where}"

        result = con.execute(sql, params).fetchone()
        return result[0] if result is not None else 0

    def distinct_trade_dates(
        self,
        *,
        table: str = "option_chain",
    ) -> list[date]:
        """Return sorted distinct trade dates from a table.

        Parameters
        ----------
        table : str
            ``"option_chain"`` or ``"underlying_series"``.
        """
        con = self._connect_or_raise()

        if table not in ("option_chain", "underlying_series"):
            msg = f"Unknown table: {table!r}"
            raise ValueError(msg)

        date_col = "trade_date"
        sql = f"SELECT DISTINCT {date_col} FROM {table} ORDER BY {date_col}"
        rows = con.execute(sql).fetchall()
        return [date.fromisoformat(row[0]) for row in rows]

    def distinct_underlying_symbols(self) -> list[str]:
        """Return sorted distinct underlying symbols from the option chain."""
        con = self._connect_or_raise()
        sql = "SELECT DISTINCT underlying_symbol FROM option_chain ORDER BY underlying_symbol"
        rows = con.execute(sql).fetchall()
        return [row[0] for row in rows]

    # -- polars integration --------------------------------------------------

    def query_option_chain_polars(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        underlying_symbol: str | None = None,
        root_symbol: str | None = None,
        expiration_date: date | None = None,
        strike: float | None = None,
        option_type: str | None = None,
    ) -> pl.DataFrame:
        """Query option chain and return a Polars DataFrame.

        Useful for callers that need DataFrame operations rather than
        typed result objects.
        """
        con = self._connect_or_raise()

        conditions: list[str] = []
        params: list[Any] = []

        if start_date is not None:
            conditions.append("trade_date >= ?")
            params.append(start_date.isoformat())
        if end_date is not None:
            conditions.append("trade_date <= ?")
            params.append(end_date.isoformat())
        if underlying_symbol is not None:
            conditions.append("underlying_symbol = ?")
            params.append(underlying_symbol)
        if root_symbol is not None:
            conditions.append("root_symbol = ?")
            params.append(root_symbol)
        if expiration_date is not None:
            conditions.append("expiration_date = ?")
            params.append(expiration_date.isoformat())
        if strike is not None:
            conditions.append("strike = ?")
            params.append(strike)
        if option_type is not None:
            conditions.append("option_type = ?")
            params.append(option_type)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM option_chain{where} ORDER BY trade_date, strike, expiration_date"

        result = con.execute(sql, params)
        columns = [d[0] for d in result.description]
        return pl.DataFrame(result.fetchall(), schema=columns, orient="row")

    # -- internal helpers ----------------------------------------------------

    def _connect_or_raise(self) -> duckdb.DuckDBPyConnection:
        """Return the active connection or raise if not connected."""
        if self._con is None:
            msg = (
                "DuckDB repository not connected. "
                "Call connect() or use as a context manager."
            )
            raise RuntimeError(msg)
        return self._con

    @staticmethod
    def _row_to_option_result(
        row: tuple[Any, ...],
        columns: list[str],
    ) -> OptionQuoteResult:
        """Map a DuckDB result row to an OptionQuoteResult."""
        mapping = dict(zip(columns, row, strict=True))
        return OptionQuoteResult(
            snapshot_ts_utc=str(mapping.get("snapshot_ts_utc", "")),
            trade_date=str(mapping.get("trade_date", "")),
            source=str(mapping.get("source", "")),
            underlying_symbol=str(mapping.get("underlying_symbol", "")),
            root_symbol=str(mapping.get("root_symbol", "")),
            expiration_date=str(mapping.get("expiration_date", "")),
            strike=float(mapping.get("strike", 0.0)),
            option_type=str(mapping.get("option_type", "")),
            bid=float(mapping.get("bid", 0.0)),
            ask=float(mapping.get("ask", 0.0)),
            bid_size=int(mapping["bid_size"])
            if mapping.get("bid_size") is not None
            else None,
            ask_size=int(mapping["ask_size"])
            if mapping.get("ask_size") is not None
            else None,
            volume=int(mapping["volume"])
            if mapping.get("volume") is not None
            else None,
            open_interest=int(mapping["open_interest"])
            if mapping.get("open_interest") is not None
            else None,
            underlying_price=float(mapping.get("underlying_price", 0.0)),
            implied_volatility=(
                float(mapping["implied_volatility"])
                if mapping.get("implied_volatility") is not None
                else None
            ),
            delta=float(mapping["delta"]) if mapping.get("delta") is not None else None,
            gamma=float(mapping["gamma"]) if mapping.get("gamma") is not None else None,
            theta=float(mapping["theta"]) if mapping.get("theta") is not None else None,
            vega=float(mapping["vega"]) if mapping.get("vega") is not None else None,
            source_contract_id=(
                str(mapping["source_contract_id"])
                if mapping.get("source_contract_id") is not None
                else None
            ),
        )

    @staticmethod
    def _row_to_underlying_result(
        row: tuple[Any, ...],
        columns: list[str],
    ) -> UnderlyingQuoteResult:
        """Map a DuckDB result row to an UnderlyingQuoteResult."""
        mapping = dict(zip(columns, row, strict=True))
        return UnderlyingQuoteResult(
            timestamp_utc=str(mapping.get("timestamp_utc", "")),
            trade_date=str(mapping.get("trade_date", "")),
            symbol=str(mapping.get("symbol", "")),
            currency=str(mapping.get("currency", "")),
            open=float(mapping["open"]) if mapping.get("open") is not None else None,
            high=float(mapping["high"]) if mapping.get("high") is not None else None,
            low=float(mapping["low"]) if mapping.get("low") is not None else None,
            close=float(mapping.get("close", 0.0)),
            adjusted_close=(
                float(mapping["adjusted_close"])
                if mapping.get("adjusted_close") is not None
                else None
            ),
            total_return_index=(
                float(mapping["total_return_index"])
                if mapping.get("total_return_index") is not None
                else None
            ),
            source=str(mapping.get("source", "")),
        )
