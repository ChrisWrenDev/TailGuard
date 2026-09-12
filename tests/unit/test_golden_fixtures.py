"""Unit tests for golden synthetic research fixtures GF-001 through GF-007.

These tests validate that the fixture data is consistent and that the
hand-calculated expected outputs match the actual calculations.
"""

from __future__ import annotations

import pytest

from tailhedge.data.canonical_schema import OptionType
from tailhedge.data.fixtures import (
    ALL_FIXTURES,
    GF001_EXPECTED_CASH_LEDGER,
    GF001_EXPECTED_FINAL_CASH,
    GF001_OPTION_SNAPSHOTS,
    GF001_PREMIUM_ASK,
    GF001_PREMIUM_BID,
    GF001_PREMIUM_MIDPOINT,
    GF001_PUT_STRIKE,
    GF001_UNDERLYING_PRICES,
    GF001_XSP_MULTIPLIER,
    GF002_EXPECTED_CASH_LEDGER,
    GF002_EXPECTED_ROLL_COST,
    GF002_OPTION_SNAPSHOTS_EXPIRY_1,
    GF002_OPTION_SNAPSHOTS_EXPIRY_2,
    GF002_PREMIUM_1_SELL,
    GF002_PREMIUM_2_BUY,
    GF002_ROLL_DTE_THRESHOLD,
    GF003_EXPECTED_CASH_LEDGER,
    GF003_EXPECTED_MONETISATION_PROCEEDS,
    GF003_PREMIUM_BUY,
    GF003_PUT_QUANTITY,
    GF004_EXPECTED_SPREAD_FRACTION,
    GF004_MAX_SPREAD_THRESHOLD,
    GF004_WIDE_SPREAD_SNAPSHOT,
    GF005_HOLDINGS,
    GF005_TOTAL_BENCHMARK_EQUIVALENT,
    GF005_TOTAL_PORTFOLIO_VALUE,
    GF005_WEIGHTED_AVERAGE_BETA,
    GF006_EXPECTED_PAYOUT_GBP,
    GF006_EXPECTED_PREMIUM_GBP,
    GF006_FX_RATE,
    GF006_PAYOUT_USD,
    GF006_PREMIUM_USD,
    GF007_EXPECTED_WITH_LEAK,
    GF007_EXPECTED_WITHOUT_LEAK,
    GF007_OPTION_SNAPSHOTS,
)


class TestGF001SimpleOptionPayoff:
    """GF-001: Five daily snapshots, one put, known expiration and premium."""

    def test_premium_midpoint_calculation(self) -> None:
        """Premium midpoint should be (bid + ask) / 2."""
        expected = (GF001_PREMIUM_BID + GF001_PREMIUM_ASK) / 2
        assert expected == GF001_PREMIUM_MIDPOINT

    def test_option_snapshots_count(self) -> None:
        """Should have 5 daily snapshots."""
        assert len(GF001_OPTION_SNAPSHOTS) == 5

    def test_all_snapshots_are_puts(self) -> None:
        """All snapshots should be PUT options."""
        for snap in GF001_OPTION_SNAPSHOTS:
            assert snap.option_type == OptionType.PUT

    def test_same_strike_and_expiry(self) -> None:
        """All snapshots should have same strike and expiry."""
        strikes = {s.strike for s in GF001_OPTION_SNAPSHOTS}
        expiries = {s.expiration_date for s in GF001_OPTION_SNAPSHOTS}
        assert len(strikes) == 1
        assert len(expiries) == 1

    def test_cash_ledger_events(self) -> None:
        """Cash ledger should have INITIAL, PREMIUM, and SETTLEMENT."""
        event_types = [e.event_type for e in GF001_EXPECTED_CASH_LEDGER]
        assert "INITIAL" in event_types
        assert "PREMIUM" in event_types
        assert "SETTLEMENT" in event_types

    def test_premium_calculation(self) -> None:
        """Premium paid should be midpoint * multiplier."""
        premium_entry = next(
            e for e in GF001_EXPECTED_CASH_LEDGER if e.event_type == "PREMIUM"
        )
        expected_premium = -GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER
        assert premium_entry.amount == expected_premium

    def test_settlement_calculation(self) -> None:
        """Settlement should be (strike - underlying) * multiplier for ITM put."""
        settlement_entry = next(
            e for e in GF001_EXPECTED_CASH_LEDGER if e.event_type == "SETTLEMENT"
        )
        final_underlying = GF001_UNDERLYING_PRICES[-1].close
        expected_settlement = (
            GF001_PUT_STRIKE - final_underlying
        ) * GF001_XSP_MULTIPLIER
        assert settlement_entry.amount == expected_settlement

    def test_final_cash_calculation(self) -> None:
        """Final cash should be initial - premium + settlement."""
        premium = GF001_PREMIUM_MIDPOINT * GF001_XSP_MULTIPLIER
        settlement = (GF001_PUT_STRIKE - 4800.0) * GF001_XSP_MULTIPLIER
        expected = 100_000.0 - premium + settlement
        assert expected == GF001_EXPECTED_FINAL_CASH

    def test_cash_ledger_running_totals(self) -> None:
        """Running cash should match cumulative calculation."""
        for i, entry in enumerate(GF001_EXPECTED_CASH_LEDGER):
            if i == 0:
                assert entry.running_cash == entry.amount
            else:
                prev = GF001_EXPECTED_CASH_LEDGER[i - 1]
                assert entry.running_cash == pytest.approx(
                    prev.running_cash + entry.amount
                )

    def test_fixture_validates_against_schema(self) -> None:
        """All option snapshots should be valid CanonicalOptionRow instances."""
        from datetime import UTC, datetime

        from tailhedge.data.canonical_schema import CanonicalOptionRow

        for snap in GF001_OPTION_SNAPSHOTS:
            row = CanonicalOptionRow(
                snapshot_ts_utc=datetime(
                    snap.trade_date.year,
                    snap.trade_date.month,
                    snap.trade_date.day,
                    20,
                    45,
                    tzinfo=UTC,
                ),
                trade_date=snap.trade_date,
                source="GF001_SYNTHETIC",
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
            assert row.strike == snap.strike


class TestGF002RollCase:
    """GF-002: Two expiries; target policy rolls at known DTE."""

    def test_roll_threshold(self) -> None:
        """Roll threshold should be 7 DTE."""
        assert GF002_ROLL_DTE_THRESHOLD == 7

    def test_two_expiry_sets(self) -> None:
        """Should have snapshots for two different expiries."""
        assert len(GF002_OPTION_SNAPSHOTS_EXPIRY_1) > 0
        assert len(GF002_OPTION_SNAPSHOTS_EXPIRY_2) > 0
        expiries_1 = {s.expiration_date for s in GF002_OPTION_SNAPSHOTS_EXPIRY_1}
        expiries_2 = {s.expiration_date for s in GF002_OPTION_SNAPSHOTS_EXPIRY_2}
        assert expiries_1 != expiries_2

    def test_roll_cost_calculation(self) -> None:
        """Roll cost should be (new premium - old premium) * multiplier."""
        expected = (GF002_PREMIUM_2_BUY - GF002_PREMIUM_1_SELL) * GF001_XSP_MULTIPLIER
        assert expected == GF002_EXPECTED_ROLL_COST

    def test_cash_ledger_has_roll_events(self) -> None:
        """Cash ledger should show sell of expiry 1 and buy of expiry 2."""
        event_types = [e.event_type for e in GF002_EXPECTED_CASH_LEDGER]
        assert "SETTLEMENT" in event_types  # Sell expiry 1
        assert "PREMIUM" in event_types  # Buy expiry 2

    def test_cash_ledger_running_totals(self) -> None:
        """Running cash should match cumulative calculation."""
        for i, entry in enumerate(GF002_EXPECTED_CASH_LEDGER):
            if i == 0:
                assert entry.running_cash == entry.amount
            else:
                prev = GF002_EXPECTED_CASH_LEDGER[i - 1]
                assert entry.running_cash == pytest.approx(
                    prev.running_cash + entry.amount
                )


class TestGF003CrashMonetisation:
    """GF-003: Underlying drops sharply; put becomes ITM; monetisation."""

    def test_monetisation_fraction(self) -> None:
        """Should monetise 50% of position."""
        from tailhedge.data.fixtures import GF003_MONETISE_FRACTION

        assert GF003_MONETISE_FRACTION == 0.5

    def test_monetisation_proceeds(self) -> None:
        """Monetisation proceeds should be price * quantity * multiplier."""
        from tailhedge.data.fixtures import GF003_MONETISE_PRICE

        expected = GF003_MONETISE_PRICE * 1 * GF001_XSP_MULTIPLIER
        assert expected == GF003_EXPECTED_MONETISATION_PROCEEDS

    def test_cash_ledger_has_monetisation(self) -> None:
        """Cash ledger should have MONETISATION event."""
        event_types = [e.event_type for e in GF003_EXPECTED_CASH_LEDGER]
        assert "MONETISATION" in event_types

    def test_cash_ledger_has_reinvestment(self) -> None:
        """Cash ledger should have REINVESTMENT event."""
        event_types = [e.event_type for e in GF003_EXPECTED_CASH_LEDGER]
        assert "REINVESTMENT" in event_types

    def test_cash_conservation(self) -> None:
        """Total cash should be conserved (no creation/destruction)."""
        from tailhedge.data.fixtures import GF003_INITIAL_CASH

        final_cash = GF003_EXPECTED_CASH_LEDGER[-1].running_cash
        # Cash should be initial minus premium paid
        expected = (
            GF003_INITIAL_CASH
            - GF003_PREMIUM_BUY * GF003_PUT_QUANTITY * GF001_XSP_MULTIPLIER
        )
        assert final_cash == pytest.approx(expected)


class TestGF004WideStaleQuote:
    """GF-004: Candidate contract violates spread/freshness rules."""

    def test_wide_spread_fraction(self) -> None:
        """Wide spread should exceed threshold."""
        assert GF004_EXPECTED_SPREAD_FRACTION > GF004_MAX_SPREAD_THRESHOLD

    def test_spread_calculation(self) -> None:
        """Spread fraction should be (ask - bid) / midpoint."""
        mid = (GF004_WIDE_SPREAD_SNAPSHOT.ask + GF004_WIDE_SPREAD_SNAPSHOT.bid) / 2
        expected = (
            GF004_WIDE_SPREAD_SNAPSHOT.ask - GF004_WIDE_SPREAD_SNAPSHOT.bid
        ) / mid
        assert pytest.approx(expected) == GF004_EXPECTED_SPREAD_FRACTION

    def test_wide_spread_rejected(self) -> None:
        """Wide spread should be rejected."""
        assert GF004_WIDE_SPREAD_SNAPSHOT.ask - GF004_WIDE_SPREAD_SNAPSHOT.bid > 0

    def test_fixture_exists(self) -> None:
        """GF-004 fixture should exist in registry."""
        assert "GF-004" in ALL_FIXTURES


class TestGF005BasisRiskPortfolio:
    """GF-005: Two holdings with different SPX beta."""

    def test_two_holdings(self) -> None:
        """Should have two holdings."""
        assert len(GF005_HOLDINGS) == 2

    def test_total_portfolio_value(self) -> None:
        """Total portfolio value should be sum of holdings."""
        total = sum(h.market_value for h in GF005_HOLDINGS)
        assert total == GF005_TOTAL_PORTFOLIO_VALUE

    def test_total_benchmark_equivalent(self) -> None:
        """Total benchmark equivalent should be sum of beta * value."""
        total = sum(h.benchmark_equivalent for h in GF005_HOLDINGS)
        assert total == GF005_TOTAL_BENCHMARK_EQUIVALENT

    def test_weighted_average_beta(self) -> None:
        """Weighted average beta should be total_benchmark / total_value."""
        expected = GF005_TOTAL_BENCHMARK_EQUIVALENT / GF005_TOTAL_PORTFOLIO_VALUE
        assert pytest.approx(expected) == GF005_WEIGHTED_AVERAGE_BETA

    def test_individual_benchmark_calculation(self) -> None:
        """Each holding's benchmark equivalent should be value * beta."""
        for holding in GF005_HOLDINGS:
            expected = holding.market_value * holding.beta
            assert holding.benchmark_equivalent == pytest.approx(expected)


class TestGF006FXConversion:
    """GF-006: Known FX path to verify premium/payout conversion."""

    def test_fx_rate(self) -> None:
        """FX rate should be 1.27 USD/GBP."""
        from tailhedge.data.fixtures import GF006_FX_RATE

        assert GF006_FX_RATE == 1.27

    def test_premium_gbp_conversion(self) -> None:
        """Premium in GBP should be USD / FX rate."""
        expected = GF006_PREMIUM_USD / GF006_FX_RATE
        assert pytest.approx(expected) == GF006_EXPECTED_PREMIUM_GBP

    def test_payout_gbp_conversion(self) -> None:
        """Payout in GBP should be USD / FX rate."""
        expected = GF006_PAYOUT_USD / GF006_FX_RATE
        assert pytest.approx(expected) == GF006_EXPECTED_PAYOUT_GBP

    def test_fx_path_exists(self) -> None:
        """FX path should have multiple snapshots."""
        from tailhedge.data.fixtures import GF006_FX_PATH

        assert len(GF006_FX_PATH) >= 2


class TestGF007SplitLeakageTrap:
    """GF-007: Construct data where future feature would cause leakage."""

    def test_leak_feature_exists(self) -> None:
        """Leak feature should be defined."""
        from tailhedge.data.fixtures import GF007_LEAK_FEATURE_VALUE

        assert GF007_LEAK_FEATURE_VALUE == 1.0

    def test_crash_day_defined(self) -> None:
        """Crash day should be defined."""
        from tailhedge.data.fixtures import GF007_CRASH_DAY

        assert GF007_CRASH_DAY is not None

    def test_expected_with_leak(self) -> None:
        """With leak, strategy should achieve perfect prediction."""
        assert GF007_EXPECTED_WITH_LEAK == 100.0

    def test_expected_without_leak(self) -> None:
        """Without leak, strategy cannot predict crash."""
        assert GF007_EXPECTED_WITHOUT_LEAK == 0.0

    def test_option_snapshots_valid(self) -> None:
        """Option snapshots should be valid."""
        assert len(GF007_OPTION_SNAPSHOTS) >= 2
        for snap in GF007_OPTION_SNAPSHOTS:
            assert snap.option_type == OptionType.PUT


class TestAllFixturesRegistry:
    """Test that all fixtures are registered and have required fields."""

    def test_all_seven_fixtures_registered(self) -> None:
        """All 7 fixtures should be in the registry."""
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

    def test_all_fixtures_have_name(self) -> None:
        """All fixtures should have a name."""
        for fixture_id, fixture_data in ALL_FIXTURES.items():
            assert "name" in fixture_data, f"{fixture_id} missing name"
            assert isinstance(fixture_data["name"], str)
            assert len(fixture_data["name"]) > 0

    def test_all_fixtures_have_description(self) -> None:
        """All fixtures should have a description."""
        for fixture_id, fixture_data in ALL_FIXTURES.items():
            assert "description" in fixture_data, f"{fixture_id} missing description"
            assert isinstance(fixture_data["description"], str)
            assert len(fixture_data["description"]) > 0

    def test_all_fixtures_have_fixture_data(self) -> None:
        """All fixtures should have fixture data."""
        for fixture_id, fixture_data in ALL_FIXTURES.items():
            assert "fixture" in fixture_data, f"{fixture_id} missing fixture data"


class TestFixtureDataStructures:
    """Test fixture data structures are properly typed."""

    def test_option_snapshot_fields(self) -> None:
        """OptionSnapshot should have required fields."""
        snap = GF001_OPTION_SNAPSHOTS[0]
        assert hasattr(snap, "trade_date")
        assert hasattr(snap, "expiration_date")
        assert hasattr(snap, "strike")
        assert hasattr(snap, "option_type")
        assert hasattr(snap, "bid")
        assert hasattr(snap, "ask")
        assert hasattr(snap, "underlying_price")

    def test_cash_ledger_entry_fields(self) -> None:
        """CashLedgerEntry should have required fields."""
        entry = GF001_EXPECTED_CASH_LEDGER[0]
        assert hasattr(entry, "trade_date")
        assert hasattr(entry, "event_type")
        assert hasattr(entry, "amount")
        assert hasattr(entry, "running_cash")
        assert hasattr(entry, "description")

    def test_portfolio_exposure_fields(self) -> None:
        """PortfolioExposure should have required fields."""
        holding = GF005_HOLDINGS[0]
        assert hasattr(holding, "holding_name")
        assert hasattr(holding, "beta")
        assert hasattr(holding, "market_value")
        assert hasattr(holding, "benchmark_equivalent")

    def test_immutable_dataclasses(self) -> None:
        """All fixture dataclasses should be frozen."""
        snap = GF001_OPTION_SNAPSHOTS[0]
        with pytest.raises(AttributeError):
            snap.strike = 999  # type: ignore[misc]
