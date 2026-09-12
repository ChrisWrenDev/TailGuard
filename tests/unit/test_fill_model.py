"""Unit tests for historical execution-cost/fill model (GF-004).

Tests quote tradability validation, fill price calculation, stress fills,
and ensures invalid quotes are never silently midpoint-filled.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from tailhedge.backtest.fill_model import (
    FillConfig,
    FillSide,
    Quote,
    QuoteTradability,
    StressFillResult,
    calculate_commission,
    calculate_fill,
    calculate_fill_price,
    calculate_stress_fills,
    validate_quote_tradability,
)
from tailhedge.data.fixtures import (
    GF004_EXPECTED_SPREAD_FRACTION,
    GF004_MAX_SPREAD_THRESHOLD,
    GF004_MAX_STALENESS_SECONDS,
    GF004_STALE_SNAPSHOT,
    GF004_WIDE_SPREAD_SNAPSHOT,
)


def _make_quote(
    bid: float = 10.0,
    ask: float = 11.0,
    trade_date: date = date(2025, 1, 15),
    snapshot_ts_utc: datetime | None = None,
) -> Quote:
    """Create a quote with default values."""
    if snapshot_ts_utc is None:
        snapshot_ts_utc = datetime(2025, 1, 15, 20, 45, tzinfo=UTC)
    return Quote(
        trade_date=trade_date,
        snapshot_ts_utc=snapshot_ts_utc,
        strike=4900.0,
        bid=bid,
        ask=ask,
        underlying_price=5000.0,
    )


def _make_config(
    max_relative_spread: float = 0.20,
    max_quote_age_seconds: int = 300,
) -> FillConfig:
    """Create a fill config with default values."""
    return FillConfig(
        max_relative_spread=max_relative_spread,
        max_quote_age_seconds=max_quote_age_seconds,
    )


# ---------------------------------------------------------------------------
# Quote tradability validation
# ---------------------------------------------------------------------------


class TestQuoteTradability:
    """Test quote tradability validation."""

    def test_tradable_quote(self) -> None:
        """Valid quote should be tradable."""
        quote = _make_quote(bid=10.0, ask=11.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = validate_quote_tradability(quote, current_time, config)

        assert result == QuoteTradability.TRADABLE

    def test_wide_spread_rejected(self) -> None:
        """Quote with spread exceeding threshold should be rejected."""
        quote = _make_quote(bid=10.0, ask=15.0)  # 50% spread
        config = _make_config(max_relative_spread=0.20)
        current_time = quote.snapshot_ts_utc

        result = validate_quote_tradability(quote, current_time, config)

        assert result == QuoteTradability.WIDE_SPREAD

    def test_stale_quote_rejected(self) -> None:
        """Quote older than threshold should be rejected."""
        quote = _make_quote(snapshot_ts_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC))
        config = _make_config(max_quote_age_seconds=300)
        current_time = datetime(2025, 1, 15, 20, 10, tzinfo=UTC)  # 10 minutes later

        result = validate_quote_tradability(quote, current_time, config)

        assert result == QuoteTradability.STALE

    def test_zero_bid_rejected(self) -> None:
        """Quote with zero bid should be rejected."""
        quote = _make_quote(bid=0.0, ask=0.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = validate_quote_tradability(quote, current_time, config)

        assert result == QuoteTradability.ZERO_BID

    def test_crossed_quote_rejected(self) -> None:
        """Quote with bid > ask should be rejected."""
        quote = _make_quote(bid=15.0, ask=10.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = validate_quote_tradability(quote, current_time, config)

        assert result == QuoteTradability.CROSSED

    def test_negative_bid_rejected(self) -> None:
        """Quote with negative bid should be rejected."""
        quote = _make_quote(bid=-1.0, ask=10.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = validate_quote_tradability(quote, current_time, config)

        assert result == QuoteTradability.NEGATIVE

    def test_negative_ask_rejected(self) -> None:
        """Quote with negative ask should be rejected."""
        quote = _make_quote(bid=10.0, ask=-1.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = validate_quote_tradability(quote, current_time, config)

        assert result == QuoteTradability.NEGATIVE


# ---------------------------------------------------------------------------
# GF-004: Wide/stale quote
# ---------------------------------------------------------------------------


class TestGF004WideStaleQuote:
    """GF-004: Candidate contract violates spread/freshness rules."""

    def test_wide_spread_detected(self) -> None:
        """Wide spread quote should be detected."""
        quote = Quote(
            trade_date=GF004_WIDE_SPREAD_SNAPSHOT.trade_date,
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
            strike=GF004_WIDE_SPREAD_SNAPSHOT.strike,
            bid=GF004_WIDE_SPREAD_SNAPSHOT.bid,
            ask=GF004_WIDE_SPREAD_SNAPSHOT.ask,
            underlying_price=GF004_WIDE_SPREAD_SNAPSHOT.underlying_price,
        )
        config = _make_config(max_relative_spread=GF004_MAX_SPREAD_THRESHOLD)
        current_time = quote.snapshot_ts_utc

        result = validate_quote_tradability(quote, current_time, config)

        assert result == QuoteTradability.WIDE_SPREAD

    def test_spread_fraction_calculation(self) -> None:
        """Spread fraction should match GF-004 expected."""
        quote = Quote(
            trade_date=GF004_WIDE_SPREAD_SNAPSHOT.trade_date,
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
            strike=GF004_WIDE_SPREAD_SNAPSHOT.strike,
            bid=GF004_WIDE_SPREAD_SNAPSHOT.bid,
            ask=GF004_WIDE_SPREAD_SNAPSHOT.ask,
            underlying_price=GF004_WIDE_SPREAD_SNAPSHOT.underlying_price,
        )

        mid = (quote.bid + quote.ask) / 2
        spread = quote.ask - quote.bid
        relative_spread = spread / mid

        assert relative_spread == pytest.approx(GF004_EXPECTED_SPREAD_FRACTION)

    def test_wide_spread_no_order(self) -> None:
        """Wide spread should result in no tradable order."""
        quote = Quote(
            trade_date=GF004_WIDE_SPREAD_SNAPSHOT.trade_date,
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 45, tzinfo=UTC),
            strike=GF004_WIDE_SPREAD_SNAPSHOT.strike,
            bid=GF004_WIDE_SPREAD_SNAPSHOT.bid,
            ask=GF004_WIDE_SPREAD_SNAPSHOT.ask,
            underlying_price=GF004_WIDE_SPREAD_SNAPSHOT.underlying_price,
        )
        config = _make_config(max_relative_spread=GF004_MAX_SPREAD_THRESHOLD)
        current_time = quote.snapshot_ts_utc

        result = calculate_fill(quote, FillSide.BUY, 1, current_time, config)

        assert result.is_tradable is False
        assert result.tradability == QuoteTradability.WIDE_SPREAD

    def test_stale_quote_no_order(self) -> None:
        """Stale quote should result in no tradable order."""
        quote = Quote(
            trade_date=GF004_STALE_SNAPSHOT.trade_date,
            snapshot_ts_utc=datetime(2025, 1, 15, 20, 0, tzinfo=UTC),
            strike=GF004_STALE_SNAPSHOT.strike,
            bid=GF004_STALE_SNAPSHOT.bid,
            ask=GF004_STALE_SNAPSHOT.ask,
            underlying_price=GF004_STALE_SNAPSHOT.underlying_price,
        )
        config = _make_config(max_quote_age_seconds=GF004_MAX_STALENESS_SECONDS)
        current_time = datetime(2025, 1, 15, 20, 10, tzinfo=UTC)

        result = calculate_fill(quote, FillSide.BUY, 1, current_time, config)

        assert result.is_tradable is False
        assert result.tradability == QuoteTradability.STALE


# ---------------------------------------------------------------------------
# Fill price calculation
# ---------------------------------------------------------------------------


class TestFillPriceCalculation:
    """Test fill price calculation logic."""

    def test_buy_fill_at_midpoint(self) -> None:
        """BUY at 0% spread should be at midpoint."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()

        price = calculate_fill_price(quote, FillSide.BUY, 0.0, config)

        assert price == pytest.approx(11.0)  # Midpoint

    def test_buy_fill_at_25pct(self) -> None:
        """BUY at 25% spread should be at mid + 25% of half-spread."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()

        price = calculate_fill_price(quote, FillSide.BUY, 0.25, config)

        # Mid = 11.0, spread = 2.0, half-spread = 1.0, 25% = 0.25, price = 11.25
        assert price == pytest.approx(11.25)

    def test_buy_fill_at_full_spread(self) -> None:
        """BUY at 100% spread should be at ask."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()

        price = calculate_fill_price(quote, FillSide.BUY, 1.0, config)

        assert price == pytest.approx(12.0)  # Ask

    def test_sell_fill_at_midpoint(self) -> None:
        """SELL at 0% spread should be at midpoint."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()

        price = calculate_fill_price(quote, FillSide.SELL, 0.0, config)

        assert price == pytest.approx(11.0)  # Midpoint

    def test_sell_fill_at_25pct(self) -> None:
        """SELL at 25% spread should be at mid - 25% of half-spread."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()

        price = calculate_fill_price(quote, FillSide.SELL, 0.25, config)

        # Mid = 11.0, spread = 2.0, half-spread = 1.0, 25% = 0.25, price = 10.75
        assert price == pytest.approx(10.75)

    def test_sell_fill_at_full_spread(self) -> None:
        """SELL at 100% spread should be at bid."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()

        price = calculate_fill_price(quote, FillSide.SELL, 1.0, config)

        assert price == pytest.approx(10.0)  # Bid

    def test_tick_rounding(self) -> None:
        """Fill price should be rounded to tick size."""
        quote = _make_quote(bid=10.02, ask=10.08)
        config = FillConfig(tick_size=0.05)

        price = calculate_fill_price(quote, FillSide.BUY, 0.25, config)

        # Mid = 10.05, spread = 0.06, half-spread = 0.03, 25% = 0.0075, price = 10.0575 -> 10.05
        assert price % 0.05 == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Fill calculation
# ---------------------------------------------------------------------------


class TestFillCalculation:
    """Test complete fill calculation with tradability validation."""

    def test_tradable_quote_returns_fill(self) -> None:
        """Tradable quote should return valid fill."""
        quote = _make_quote(bid=10.0, ask=11.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = calculate_fill(quote, FillSide.BUY, 1, current_time, config)

        assert result.is_tradable is True
        assert result.fill_price > 0
        assert result.commission >= 0

    def test_untradable_quote_returns_no_fill(self) -> None:
        """Untradable quote should return no fill."""
        quote = _make_quote(bid=10.0, ask=15.0)  # Wide spread
        config = _make_config(max_relative_spread=0.20)
        current_time = quote.snapshot_ts_utc

        result = calculate_fill(quote, FillSide.BUY, 1, current_time, config)

        assert result.is_tradable is False
        assert result.fill_price == 0.0
        assert result.commission == 0.0

    def test_never_midpoint_fill_invalid_quote(self) -> None:
        """Invalid quotes should never be silently midpoint-filled."""
        invalid_quotes = [
            _make_quote(bid=0.0, ask=0.0),  # Zero bid
            _make_quote(bid=15.0, ask=10.0),  # Crossed
            _make_quote(bid=-1.0, ask=10.0),  # Negative bid
        ]
        config = _make_config()
        current_time = datetime(2025, 1, 15, 20, 45, tzinfo=UTC)

        for quote in invalid_quotes:
            result = calculate_fill(quote, FillSide.BUY, 1, current_time, config)
            assert result.is_tradable is False
            assert result.fill_price == 0.0


# ---------------------------------------------------------------------------
# Commission calculation
# ---------------------------------------------------------------------------


class TestCommissionCalculation:
    """Test commission calculation."""

    def test_flat_commission(self) -> None:
        """Flat commission should be per contract."""
        config = FillConfig(commission_per_contract=0.65, commission_rate=0.0)

        commission = calculate_commission(quantity=10, fill_price=100.0, config=config)

        assert commission == pytest.approx(6.5)  # 10 * 0.65

    def test_percentage_commission(self) -> None:
        """Percentage commission should be based on trade value."""
        config = FillConfig(commission_per_contract=0.0, commission_rate=0.001)

        commission = calculate_commission(quantity=10, fill_price=100.0, config=config)

        assert commission == pytest.approx(1.0)  # 10 * 100 * 0.001

    def test_combined_commission(self) -> None:
        """Combined commission should sum flat and percentage."""
        config = FillConfig(commission_per_contract=0.65, commission_rate=0.001)

        commission = calculate_commission(quantity=10, fill_price=100.0, config=config)

        # 6.5 + 1.0 = 7.5
        assert commission == pytest.approx(7.5)


# ---------------------------------------------------------------------------
# Stress fills
# ---------------------------------------------------------------------------


class TestStressFills:
    """Test stress fill calculations."""

    def test_stress_fills_all_scenarios(self) -> None:
        """Stress fills should include all mandatory scenarios."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = calculate_stress_fills(quote, FillSide.BUY, 1, current_time, config)

        assert isinstance(result, StressFillResult)
        assert result.base_fill.is_tradable
        assert result.midpoint_fill.is_tradable
        assert result.stress_50pct_fill.is_tradable
        assert result.full_spread_fill.is_tradable

    def test_midpoint_fill_is_diagnostic(self) -> None:
        """Midpoint fill should be at exact midpoint."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = calculate_stress_fills(quote, FillSide.BUY, 1, current_time, config)

        assert result.midpoint_fill.fill_price == pytest.approx(11.0)

    def test_full_spread_fill_is_worst_case(self) -> None:
        """Full spread fill should be at ask (worst case for BUY)."""
        quote = _make_quote(bid=10.0, ask=12.0)
        config = _make_config()
        current_time = quote.snapshot_ts_utc

        result = calculate_stress_fills(quote, FillSide.BUY, 1, current_time, config)

        assert result.full_spread_fill.fill_price == pytest.approx(12.0)

    def test_stress_fills_untradable_quote(self) -> None:
        """Stress fills for untradable quote should all be untradable."""
        quote = _make_quote(bid=10.0, ask=15.0)  # Wide spread
        config = _make_config(max_relative_spread=0.20)
        current_time = quote.snapshot_ts_utc

        result = calculate_stress_fills(quote, FillSide.BUY, 1, current_time, config)

        assert result.base_fill.is_tradable is False
        assert result.midpoint_fill.is_tradable is False
        assert result.stress_50pct_fill.is_tradable is False
        assert result.full_spread_fill.is_tradable is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestFillModelEdgeCases:
    """Edge cases for fill model."""

    def test_zero_spread_quote(self) -> None:
        """Quote with zero spread should be at midpoint."""
        quote = _make_quote(bid=10.0, ask=10.0)
        config = _make_config()

        price = calculate_fill_price(quote, FillSide.BUY, 0.25, config)

        assert price == pytest.approx(10.0)

    def test_very_small_spread(self) -> None:
        """Very small spread should not cause issues."""
        quote = _make_quote(bid=10.00, ask=10.01)
        config = _make_config(max_relative_spread=0.20)

        price = calculate_fill_price(quote, FillSide.BUY, 0.25, config)

        assert price >= 10.00
        assert price <= 10.01

    def test_very_large_spread(self) -> None:
        """Very large spread should be rejected."""
        quote = _make_quote(bid=10.0, ask=100.0)
        config = _make_config(max_relative_spread=0.20)

        result = validate_quote_tradability(quote, quote.snapshot_ts_utc, config)

        assert result == QuoteTradability.WIDE_SPREAD
