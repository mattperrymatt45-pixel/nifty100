"""Unit tests for the Sprint 3 Day 16 valuation ratios module.

Covers:
    * P/E normal, loss-making (None), zero earnings (None), None inputs
    * P/B normal, negative/zero book (None)
    * EV/EBITDA normal, negative EBIT (None)
    * FCF yield positive/negative, zero market cap (None)
    * Earnings yield inverse of P/E
    * compare_multiples tolerance logic
    * classify_valuation buckets (Cheap / Fair / Expensive)
    * Aggregator compute_valuation_ratios
"""

from __future__ import annotations

import pytest

from src.analytics.valuation import (
    DEFAULT_TOLERANCE_PCT,
    ValuationRatios,
    classify_valuation,
    compare_multiples,
    compute_valuation_ratios,
    earnings_yield,
    ev_to_ebitda,
    fcf_yield,
    price_to_book,
    price_to_earnings,
)


# ---------------------------------------------------------------------------
# P/E
# ---------------------------------------------------------------------------
class TestPriceToEarnings:
    def test_normal(self) -> None:
        assert price_to_earnings(100000.0, 5000.0) == pytest.approx(20.0)

    def test_loss_making_returns_none(self) -> None:
        assert price_to_earnings(100000.0, -500.0) is None

    def test_zero_profit_returns_none(self) -> None:
        assert price_to_earnings(100000.0, 0.0) is None

    def test_zero_mcap_returns_none(self) -> None:
        assert price_to_earnings(0.0, 5000.0) is None

    def test_none_inputs_return_none(self) -> None:
        assert price_to_earnings(None, 5000.0) is None
        assert price_to_earnings(100000.0, None) is None

    def test_tcs_like_pe(self) -> None:
        # Large-cap IT: ~₹13L Cr mcap, ~₹50K Cr net profit → P/E ~26
        assert price_to_earnings(1_300_000.0, 50_000.0) == pytest.approx(26.0)


# ---------------------------------------------------------------------------
# P/B
# ---------------------------------------------------------------------------
class TestPriceToBook:
    def test_normal(self) -> None:
        # MCap 100000, book 25000 → P/B 4.0
        assert price_to_book(100000.0, 25000.0) == pytest.approx(4.0)

    def test_negative_book_returns_none(self) -> None:
        assert price_to_book(100000.0, -1000.0) is None

    def test_zero_book_returns_none(self) -> None:
        assert price_to_book(100000.0, 0.0) is None

    def test_none_inputs(self) -> None:
        assert price_to_book(None, 25000.0) is None
        assert price_to_book(100000.0, None) is None


# ---------------------------------------------------------------------------
# EV/EBITDA
# ---------------------------------------------------------------------------
class TestEvToEbitda:
    def test_normal(self) -> None:
        # EV 120000, EBIT 10000 → 12*
        assert ev_to_ebitda(120000.0, 10000.0) == pytest.approx(12.0)

    def test_negative_ebit_returns_none(self) -> None:
        assert ev_to_ebitda(120000.0, -500.0) is None

    def test_zero_ebit_returns_none(self) -> None:
        assert ev_to_ebitda(120000.0, 0.0) is None

    def test_none_inputs(self) -> None:
        assert ev_to_ebitda(None, 10000.0) is None
        assert ev_to_ebitda(120000.0, None) is None


# ---------------------------------------------------------------------------
# FCF Yield
# ---------------------------------------------------------------------------
class TestFcfYield:
    def test_positive_fcf(self) -> None:
        # FCF 5000, MCap 100000 → 5% yield
        assert fcf_yield(5000.0, 100000.0) == pytest.approx(5.0)

    def test_negative_fcf_gives_negative_yield(self) -> None:
        assert fcf_yield(-2000.0, 100000.0) == pytest.approx(-2.0)

    def test_zero_mcap_returns_none(self) -> None:
        assert fcf_yield(5000.0, 0.0) is None

    def test_none_inputs(self) -> None:
        assert fcf_yield(None, 100000.0) is None
        assert fcf_yield(5000.0, None) is None


# ---------------------------------------------------------------------------
# Earnings Yield (inverse of P/E)
# ---------------------------------------------------------------------------
class TestEarningsYield:
    def test_normal(self) -> None:
        # P/E=20 → earnings yield 5%
        assert earnings_yield(5000.0, 100000.0) == pytest.approx(5.0)

    def test_loss_making_none(self) -> None:
        assert earnings_yield(-100.0, 100000.0) is None

    def test_pe_of_25_gives_4pct(self) -> None:
        assert earnings_yield(4000.0, 100000.0) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------
class TestComputeValuationRatios:
    def test_all_normal(self) -> None:
        vr = compute_valuation_ratios(
            market_cap_crore=100000.0,
            enterprise_value_crore=120000.0,
            net_profit_crore=5000.0,
            book_value_crore=25000.0,
            ebit_crore=10000.0,
            free_cash_flow_cr=4000.0,
            dividend_yield_pct=2.5,
        )
        assert isinstance(vr, ValuationRatios)
        assert vr.pe_ratio == pytest.approx(20.0)
        assert vr.pb_ratio == pytest.approx(4.0)
        assert vr.ev_ebitda == pytest.approx(12.0)
        assert vr.dividend_yield_pct == pytest.approx(2.5)
        assert vr.fcf_yield_pct == pytest.approx(4.0)
        assert vr.earnings_yield_pct == pytest.approx(5.0)

    def test_loss_making_masks_pe_and_earnings_yield(self) -> None:
        vr = compute_valuation_ratios(
            market_cap_crore=100000.0,
            enterprise_value_crore=120000.0,
            net_profit_crore=-500.0,
            book_value_crore=25000.0,
            ebit_crore=8000.0,
            free_cash_flow_cr=-2000.0,
        )
        assert vr.pe_ratio is None
        assert vr.earnings_yield_pct is None
        assert vr.fcf_yield_pct == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# compare_multiples
# ---------------------------------------------------------------------------
class TestCompareMultiples:
    def test_within_tolerance(self) -> None:
        chk = compare_multiples("pe", 20.0, 21.0, tolerance_pct=10.0)
        assert chk.within_tolerance is True
        assert chk.delta_pct == pytest.approx(4.76190476, rel=1e-4)

    def test_outside_tolerance(self) -> None:
        chk = compare_multiples("pe", 30.0, 20.0, tolerance_pct=25.0)
        assert chk.within_tolerance is False
        assert chk.delta_pct == pytest.approx(50.0)

    def test_both_none_is_ok(self) -> None:
        chk = compare_multiples("pe", None, None)
        assert chk.within_tolerance is True

    def test_one_none_fails(self) -> None:
        chk = compare_multiples("pe", 20.0, None)
        assert chk.within_tolerance is False

    def test_default_tolerance_is_25pct(self) -> None:
        assert DEFAULT_TOLERANCE_PCT == 25.0


# ---------------------------------------------------------------------------
# classify_valuation
# ---------------------------------------------------------------------------
class TestClassifyValuation:
    def test_cheap_low_pe_only(self) -> None:
        # P/E < 10 → immediately Cheap
        assert classify_valuation(8.0, 1.0, 5.0) == "Cheap"

    def test_expensive_high_pe_only(self) -> None:
        # P/E > 50 → immediately Expensive
        assert classify_valuation(55.0, 5.0, 25.0) == "Expensive"

    def test_cheap_two_votes(self) -> None:
        # P/E=12 (1 vote), P/B=1.5 (1 vote), EV/EBITDA=8 (1 vote) → Cheap
        assert classify_valuation(12.0, 1.5, 8.0) == "Cheap"

    def test_expensive_two_votes(self) -> None:
        # P/E=38 (1 vote), P/B=9 (1 vote), EV/EBITDA=25 (1 vote) → Expensive
        assert classify_valuation(38.0, 9.0, 25.0) == "Expensive"

    def test_fair_midrange(self) -> None:
        assert classify_valuation(20.0, 3.5, 15.0) == "Fair"

    def test_none_pe_uses_other_metrics(self) -> None:
        # Loss-making, but P/B=1.2 (<2) and EV/EBITDA=7 (<10) → 2 cheap votes
        assert classify_valuation(None, 1.2, 7.0) == "Cheap"
