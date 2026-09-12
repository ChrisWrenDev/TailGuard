"""Unit tests for golden synthetic research fixtures GF-001 through GF-007.

These tests validate fixture *structure and internal consistency*. Expected
values here are hardcoded literals (hand-calculated), so a scenario change
in fixtures.py fails these tests rather than silently passing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from tailhedge.backtest.fill_model import (
    FillSide,
    Quote,
    QuoteTradability,
    calculate_fill,
)
from tailhedge.data.canonical_schema import CanonicalOptionRow, OptionType
from tailhedge.data.fixtures import (
    ALL_FIXTURES,
    GF001_EXPECTED_CASH_LEDGER,
    GF001_EXPECTED_FINAL_CASH,
    GF001_EXPECTED_POSITIONS,
    GF001_OPTION_SNAPSHOTS,
    GF001_PUT_EXPIRY,
    GF001_UNDERLYING_PRICES,
    GF002_EXPECTED_CASH_LEDGER,
    GF002_EXPECTED_FINAL_CASH,
    GF002_EXPECTED_ROLL_COST,
    GF002_OPTION_SNAPSHOTS_EXPIRY_1,
    GF002_OPTION_SNAPSHOTS_EXPIRY_2,
    GF002_ROLL_DTE_THRESHOLD,
    GF003_EXPECTED_CASH_LEDGER,
    GF003_EXPECTED_FINAL_CASH,
    GF003_EXPECTED_FINAL_COMBINED_VALUE,
    GF003_EXPECTED_FINAL_UNITS,
    GF003_MONETISE_FRACTION,
    GF004_CHECK_TIME,
    GF004_EXPECTED_SPREAD_FRACTION,
    GF004_MAX_SPREAD_THRESHOLD,
    GF004_STALE_SNAPSHOT,
    GF004_WIDE_SPREAD_SNAPSHOT,
    GF005_HOLDINGS,
    GF005_TOTAL_BENCHMARK_EQUIVALENT,
    GF005_TOTAL_PORTFOLIO_VALUE,
    GF005_WEIGHTED_AVERAGE_BETA,
    GF006_FX_RATE,
    GF007_LAST_SAFE_DATE,
    GF007_LEAK_FEATURE_VALUE,
    GF007_UNDERLYING_PRICES,
    options_on_or_before,
    underlying_on_or_before,
)


def _canonical_option_row(snap: object) -> CanonicalOptionRow:
    """Build a CanonicalOptionRow from a fixture snapshot."""
    assert isinstance(snap.trade_date, date)
    return CanonicalOptionRow(
        snapshot_ts_utc=datetime(
            snap.trade_date.year,
            snap.trade_date.month,
            snap.trade_date.day,
            20,
            45,
            tzinfo=UTC,
        ),
        trade_date=snap.trade_date,
        source="GF_SYNTHETIC",
        underlying_symbol="XSP",
        root_symbol="XSP",
        expiration_date=snap.expiration_date,
        strike=snap.strike,
        option_type=snap.option_type,
        bid=snap.bid,
        ask=snap.ask,
        bid_size=snap.bid_size,
        ask_size=snap.ask_size,
        volume=snap.volume,
        open_interest=snap.open_interest,
        underlying_price=snap.underlying_price,
        implied_volatility=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
        source_contract_id=None,
    )


# ---------------------------------------------------------------------------
# GF-001: Simple option payoff — hand-calculated literals
# ---------------------------------------------------------------------------


class TestGF001SimpleOptionPayoff:
    """GF-001: five underlying days, one put, ITM expiry, exact ledger."""

    def test_five_unique_underlying_days_ending_on_expiry(self) -> None:
        """Underlying must have 5 rows on 5 distinct dates, last on expiry."""
        dates = [s.trade_date for s in GF001_UNDERLYING_PRICES]
        assert len(GF001_UNDERLYING_PRICES) == 5
        assert len(set(dates)) == 5
        assert dates[-1] == GF001_PUT_EXPIRY

    def test_option_snapshot_trade_dates_unique(self) -> None:
        """No two option snapshots may share a trade date (uniqueness key)."""
        dates = [s.trade_date for s in GF001_OPTION_SNAPSHOTS]
        assert len(dates) == len(set(dates))

    def test_all_snapshots_are_puts(self) -> None:
        """All snapshots should be PUT options."""
        for snap in GF001_OPTION_SNAPSHOTS:
            assert snap.option_type == OptionType.PUT

    def test_hand_calculated_expected_final_cash(self) -> None:
        """Expected final cash must equal the hardcoded hand calculation.

        100,000 - 103.75*100 (fill premium) - 0.65 (commission)
        + (4900 - 4800)*100 (settlement) = 99,624.35
        """
        assert pytest.approx(99_624.35) == GF001_EXPECTED_FINAL_CASH

    def test_expected_ledger_literal_amounts(self) -> None:
        """Event amounts must equal hardcoded literals."""
        amounts = [(e.event_type, e.amount) for e in GF001_EXPECTED_CASH_LEDGER]
        assert amounts == [
            ("INITIAL", 100_000.0),
            ("PREMIUM", -10_375.0),
            ("TRANSACTION_COST", -0.65),
            ("SETTLEMENT", 10_000.0),
        ]

    def test_expected_ledger_dates_literal(self) -> None:
        """Event dates must match the documented timeline."""
        dates = [str(e.trade_date) for e in GF001_EXPECTED_CASH_LEDGER]
        assert dates == ["2025-01-15", "2025-01-15", "2025-01-15", "2025-01-21"]

    def test_expected_ledger_running_totals(self) -> None:
        """Running cash must chain exactly."""
        running = [e.running_cash for e in GF001_EXPECTED_CASH_LEDGER]
        assert running == pytest.approx([100_000.0, 89_625.0, 89_624.35, 99_624.35])
        assert running[-1] == pytest.approx(GF001_EXPECTED_FINAL_CASH)

    def test_expected_positions_literal(self) -> None:
        """Position events must match the hand-calculated entries."""
        assert [
            (p.action, p.quantity, p.running_positions)
            for p in GF001_EXPECTED_POSITIONS
        ] == [
            ("BUY", 1, 1),
            ("EXPIRED", 1, 0),
        ]

    def test_fixture_validates_against_schema(self) -> None:
        """All option snapshots must be valid CanonicalOptionRow instances."""
        for snap in GF001_OPTION_SNAPSHOTS:
            row = _canonical_option_row(snap)
            assert row.strike == snap.strike

    def test_expiry_underlying_price_present(self) -> None:
        """The expiry-day settlement price must exist in the underlying series."""
        expiry_close = GF001_UNDERLYING_PRICES[-1].close
        assert expiry_close == 4800.0


# ---------------------------------------------------------------------------
# GF-002: Roll case — hand-calculated literals
# ---------------------------------------------------------------------------


class TestGF002RollCase:
    """GF-002: two expiries; roll fires at DTE <= 4, not at purchase."""

    def test_roll_threshold_literal(self) -> None:
        assert GF002_ROLL_DTE_THRESHOLD == 4

    def test_not_roll_eligible_at_purchase(self) -> None:
        """Position bought Jan 15 (DTE 6) must NOT be roll-eligible at once."""
        dte_at_purchase = (
            GF002_OPTION_SNAPSHOTS_EXPIRY_1[0].expiration_date
            - GF002_OPTION_SNAPSHOTS_EXPIRY_1[0].trade_date
        ).days
        assert dte_at_purchase == 6
        assert dte_at_purchase > GF002_ROLL_DTE_THRESHOLD

    def test_roll_eligible_on_rollback_day(self) -> None:
        """On Jan 17 (DTE 4) the position becomes roll-eligible."""
        dte = (GF002_EXPIRY_1_LITERAL - GF002_ROLL_DATE_LITERAL).days
        assert dte == GF002_ROLL_DTE_THRESHOLD


GF002_EXPIRY_1_LITERAL = date(2025, 1, 21)
GF002_ROLL_DATE_LITERAL = date(2025, 1, 17)


class TestGF002ExpectedLedgerLiterals:
    """GF-002 expected cash ledger must equal hardcoded hand calculations."""

    def test_hand_calculated_expected_final_cash(self) -> None:
        """100,000 - 10,375 - 0.65 + 11,625 - 0.65 - 15,250 - 0.65 = 85,998.05."""
        assert pytest.approx(85_998.05) == GF002_EXPECTED_FINAL_CASH

    def test_hand_calculated_roll_cost(self) -> None:
        """Premium roll cost: (152.50 - 116.25) * 100 = 3,625."""
        assert pytest.approx(3_625.0) == GF002_EXPECTED_ROLL_COST

    def test_event_types_literal(self) -> None:
        """Roll sale is a MONETISATION event (not SETTLEMENT)."""
        types = [e.event_type for e in GF002_EXPECTED_CASH_LEDGER]
        assert types == [
            "INITIAL",
            "PREMIUM",
            "TRANSACTION_COST",
            "MONETISATION",
            "TRANSACTION_COST",
            "PREMIUM",
            "TRANSACTION_COST",
        ]

    def test_amounts_literal(self) -> None:
        amounts = [e.amount for e in GF002_EXPECTED_CASH_LEDGER]
        assert amounts == pytest.approx(
            [100_000.0, -10_375.0, -0.65, 11_625.0, -0.65, -15_250.0, -0.65]
        )

    def test_running_totals_literal(self) -> None:
        running = [e.running_cash for e in GF002_EXPECTED_CASH_LEDGER]
        assert running == pytest.approx(
            [
                100_000.0,
                89_625.0,
                89_624.35,
                101_249.35,
                101_248.70,
                85_998.70,
                85_998.05,
            ]
        )
        assert running[-1] == pytest.approx(GF002_EXPECTED_FINAL_CASH)

    def test_two_expiry_sets(self) -> None:
        """Should have snapshots for two different expiries."""
        assert len(GF002_OPTION_SNAPSHOTS_EXPIRY_1) > 0
        assert len(GF002_OPTION_SNAPSHOTS_EXPIRY_2) > 0
        expiries_1 = {s.expiration_date for s in GF002_OPTION_SNAPSHOTS_EXPIRY_1}
        expiries_2 = {s.expiration_date for s in GF002_OPTION_SNAPSHOTS_EXPIRY_2}
        assert expiries_1 != expiries_2


# ---------------------------------------------------------------------------
# GF-003: Crash + monetisation — hand-calculated literals
# ---------------------------------------------------------------------------


class TestGF003CrashMonetisation:
    """GF-003: monetise 50%, reinvest 100%; units and value known."""

    def test_monetisation_fraction(self) -> None:
        assert GF003_MONETISE_FRACTION == 0.5

    def test_hand_calculated_monetisation_proceeds(self) -> None:
        """Sell fill = 400 - 0.25*10 = 397.50; proceeds = 39,750."""
        from tailhedge.data.fixtures import GF003_EXPECTED_MONETISATION_PROCEEDS

        assert pytest.approx(39_750.0) == GF003_EXPECTED_MONETISATION_PROCEEDS

    def test_hand_calculated_final_cash(self) -> None:
        """100,000 - 20,750 - 1.30 + 39,750 - 0.65 - 39,750 = 79,248.05."""
        assert pytest.approx(79_248.05) == GF003_EXPECTED_FINAL_CASH

    def test_hand_calculated_units(self) -> None:
        """Units: 200 + 39,750/4500 = 208.833333..."""
        assert pytest.approx(200 + 39_750 / 4500) == GF003_EXPECTED_FINAL_UNITS

    def test_hand_calculated_combined_value(self) -> None:
        """79,248.05 + 208.8333... * 4500 = 1,018,998.05."""
        assert pytest.approx(1_018_998.05) == GF003_EXPECTED_FINAL_COMBINED_VALUE

    def test_event_types_literal(self) -> None:
        types = [e.event_type for e in GF003_EXPECTED_CASH_LEDGER]
        assert types == [
            "INITIAL",
            "PREMIUM",
            "TRANSACTION_COST",
            "MONETISATION",
            "TRANSACTION_COST",
            "REINVESTMENT",
        ]

    def test_amounts_literal(self) -> None:
        amounts = [e.amount for e in GF003_EXPECTED_CASH_LEDGER]
        assert amounts == pytest.approx(
            [100_000.0, -20_750.0, -1.30, 39_750.0, -0.65, -39_750.0]
        )

    def test_running_totals_literal(self) -> None:
        running = [e.running_cash for e in GF003_EXPECTED_CASH_LEDGER]
        assert running == pytest.approx(
            [100_000.0, 79_250.0, 79_248.70, 118_998.70, 118_998.05, 79_248.05]
        )
        assert running[-1] == pytest.approx(GF003_EXPECTED_FINAL_CASH)


# ---------------------------------------------------------------------------
# GF-004: Wide/stale quote
# ---------------------------------------------------------------------------


class TestGF004WideStaleQuote:
    """GF-004: wide spread and staleness must both be detectable."""

    def test_wide_spread_fraction(self) -> None:
        assert GF004_EXPECTED_SPREAD_FRACTION > GF004_MAX_SPREAD_THRESHOLD

    def test_wide_spread_snapshot_has_timestamp(self) -> None:
        """Staleness must be representable: snapshots carry timestamps."""
        assert GF004_WIDE_SPREAD_SNAPSHOT.snapshot_ts_utc is not None

    def test_stale_quote_is_stale_at_check_time(self) -> None:
        """The fixture's stale snapshot is >300s old at the check time."""
        from tailhedge.backtest.fill_model import FillConfig

        snap = GF004_STALE_SNAPSHOT
        assert snap.snapshot_ts_utc is not None
        quote = Quote(
            trade_date=snap.trade_date,
            snapshot_ts_utc=snap.snapshot_ts_utc,
            strike=snap.strike,
            expiration_date=snap.expiration_date,
            bid=snap.bid,
            ask=snap.ask,
            underlying_price=snap.underlying_price,
        )
        age = (GF004_CHECK_TIME - snap.snapshot_ts_utc).total_seconds()
        assert age == 600  # 20:00 snapshot checked at 20:10

        result = calculate_fill(
            quote,
            FillSide.BUY,
            1,
            GF004_CHECK_TIME,
            FillConfig(max_quote_age_seconds=300),
        )
        assert result.tradability == QuoteTradability.STALE
        assert result.is_tradable is False

    def test_fixture_exists(self) -> None:
        assert "GF-004" in ALL_FIXTURES


# ---------------------------------------------------------------------------
# GF-005: Basis-risk portfolio
# ---------------------------------------------------------------------------


class TestGF005BasisRiskPortfolio:
    """GF-005: two holdings with different beta; totals hand-calculated."""

    def test_two_holdings(self) -> None:
        assert len(GF005_HOLDINGS) == 2

    def test_total_portfolio_value_literal(self) -> None:
        assert sum(h.market_value for h in GF005_HOLDINGS) == 65_000.0
        assert GF005_TOTAL_PORTFOLIO_VALUE == 65_000.0

    def test_total_benchmark_equivalent_literal(self) -> None:
        assert sum(h.benchmark_equivalent for h in GF005_HOLDINGS) == 68_000.0
        assert GF005_TOTAL_BENCHMARK_EQUIVALENT == 68_000.0

    def test_weighted_average_beta_literal(self) -> None:
        assert pytest.approx(68_000 / 65_000) == GF005_WEIGHTED_AVERAGE_BETA
        assert pytest.approx(1.0461538461538462) == GF005_WEIGHTED_AVERAGE_BETA

    def test_individual_benchmark_calculation(self) -> None:
        for holding in GF005_HOLDINGS:
            assert holding.benchmark_equivalent == pytest.approx(
                holding.market_value * holding.beta
            )


# ---------------------------------------------------------------------------
# GF-006: FX conversion
# ---------------------------------------------------------------------------


class TestGF006FXConversion:
    """GF-006: known FX path; conversions hand-calculated."""

    def test_fx_rate_literal(self) -> None:
        assert GF006_FX_RATE == 1.27

    def test_premium_gbp_conversion_literal(self) -> None:
        from tailhedge.data.fixtures import GF006_EXPECTED_PREMIUM_GBP

        assert pytest.approx(10_250.0 / 1.27) == GF006_EXPECTED_PREMIUM_GBP

    def test_payout_gbp_conversion_literal(self) -> None:
        from tailhedge.data.fixtures import GF006_EXPECTED_PAYOUT_GBP

        assert pytest.approx(10_000.0 / 1.27) == GF006_EXPECTED_PAYOUT_GBP

    def test_fx_path_exists(self) -> None:
        from tailhedge.data.fixtures import GF006_FX_PATH

        assert len(GF006_FX_PATH) >= 2


# ---------------------------------------------------------------------------
# GF-007: Split leakage trap
# ---------------------------------------------------------------------------


class TestGF007SplitLeakageTrap:
    """GF-007: leak feature must be structurally present and sliceable."""

    def test_leak_feature_literal(self) -> None:
        assert GF007_LEAK_FEATURE_VALUE == 1.0

    def test_leak_feature_structurally_present(self) -> None:
        """A row dated after the last-safe date carries the leak feature."""
        leak_rows = [s for s in GF007_UNDERLYING_PRICES if s.leak_feature is not None]
        assert len(leak_rows) == 1
        assert leak_rows[0].trade_date > GF007_LAST_SAFE_DATE

    def test_safe_slice_cannot_see_leak(self) -> None:
        """A Jan-17 context slice must not contain any leak feature value."""
        safe_rows = underlying_on_or_before(
            GF007_UNDERLYING_PRICES, GF007_LAST_SAFE_DATE
        )
        assert all(s.leak_feature is None for s in safe_rows)
        assert len(safe_rows) == 3
        assert safe_rows[-1].trade_date == GF007_LAST_SAFE_DATE

    def test_option_safe_slice_excludes_crash_day(self) -> None:
        from tailhedge.data.fixtures import GF007_OPTION_SNAPSHOTS

        safe = options_on_or_before(GF007_OPTION_SNAPSHOTS, GF007_LAST_SAFE_DATE)
        assert [s.trade_date for s in safe] == [date(2025, 1, 15)]
        assert len(safe) < len(GF007_OPTION_SNAPSHOTS)

    def test_expected_outcomes_literals(self) -> None:
        from tailhedge.data.fixtures import (
            GF007_EXPECTED_WITH_LEAK,
            GF007_EXPECTED_WITHOUT_LEAK,
        )

        assert GF007_EXPECTED_WITH_LEAK == 100.0
        assert GF007_EXPECTED_WITHOUT_LEAK == 0.0


# ---------------------------------------------------------------------------
# Canonical-schema validation of every fixture's option snapshots
# ---------------------------------------------------------------------------


class TestAllFixturesValidateAgainstCanonicalSchema:
    """Every fixture option snapshot must import cleanly (except trap rows)."""

    @pytest.mark.parametrize(
        "snapshots",
        [
            GF001_OPTION_SNAPSHOTS,
            GF002_OPTION_SNAPSHOTS_EXPIRY_1,
            GF002_OPTION_SNAPSHOTS_EXPIRY_2,
        ],
    )
    def test_fixture_rows_validate(self, snapshots: list[object]) -> None:
        for snap in snapshots:
            row = _canonical_option_row(snap)
            assert row.bid <= row.ask

    def test_underlying_fixtures_are_canonicalisable(self) -> None:
        from tailhedge.data.canonical_schema import CanonicalUnderlyingRow
        from tailhedge.data.fixtures import (
            GF001_UNDERLYING_PRICES,
            GF002_UNDERLYING_PRICES,
            GF003_UNDERLYING_PRICES,
        )

        for series in (
            GF001_UNDERLYING_PRICES,
            GF002_UNDERLYING_PRICES,
            GF003_UNDERLYING_PRICES,
        ):
            for snap in series:
                row = CanonicalUnderlyingRow(
                    timestamp_utc=datetime(
                        snap.trade_date.year,
                        snap.trade_date.month,
                        snap.trade_date.day,
                        21,
                        0,
                        tzinfo=UTC,
                    ),
                    trade_date=snap.trade_date,
                    symbol=snap.symbol,
                    currency=snap.currency,
                    close=snap.close,
                    source="GF_SYNTHETIC",
                )
                assert row.close == snap.close


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestAllFixturesRegistry:
    """Test that all fixtures are registered and have required fields."""

    def test_all_seven_fixtures_registered(self) -> None:
        expected_ids = {
            "GF-001",
            "GF-002",
            "GF-003",
            "GF-004",
            "GF-005",
            "GF-006",
            "GF-007",
        }
        assert set(ALL_FIXTURES.keys()) == expected_ids

    def test_all_fixtures_have_name_and_description(self) -> None:
        for fixture_data in ALL_FIXTURES.values():
            assert isinstance(fixture_data["name"], str)
            assert bool(fixture_data["name"])
            assert isinstance(fixture_data["description"], str)
            assert bool(fixture_data["description"])
            assert "fixture" in fixture_data


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class TestFixtureDataStructures:
    """Fixture data structures are properly typed and immutable."""

    def test_option_snapshot_fields(self) -> None:
        snap = GF001_OPTION_SNAPSHOTS[0]
        for field_name in (
            "trade_date",
            "expiration_date",
            "strike",
            "option_type",
            "bid",
            "ask",
            "underlying_price",
            "snapshot_ts_utc",
        ):
            assert hasattr(snap, field_name)

    def test_cash_ledger_entry_fields(self) -> None:
        entry = GF001_EXPECTED_CASH_LEDGER[0]
        for field_name in (
            "trade_date",
            "event_type",
            "amount",
            "running_cash",
            "description",
        ):
            assert hasattr(entry, field_name)

    def test_immutable_dataclasses(self) -> None:
        snap = GF001_OPTION_SNAPSHOTS[0]
        with pytest.raises(AttributeError):
            snap.strike = 999  # type: ignore[misc]

    def test_naive_timestamp_rejected_by_canonical_schema(self) -> None:
        """A naive snapshot timestamp must fail canonical import (FR-003)."""
        snap = GF001_OPTION_SNAPSHOTS[0]
        with pytest.raises(ValidationError):
            CanonicalOptionRow(
                snapshot_ts_utc=datetime(2025, 1, 15, 20, 45),  # naive!
                trade_date=snap.trade_date,
                source="GF_SYNTHETIC",
                underlying_symbol="XSP",
                root_symbol="XSP",
                expiration_date=snap.expiration_date,
                strike=snap.strike,
                option_type=snap.option_type,
                bid=snap.bid,
                ask=snap.ask,
                underlying_price=snap.underlying_price,
            )
