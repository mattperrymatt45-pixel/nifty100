"""KPI unit tests — Day 41 (20 tests).

Covers ROE, D/E, ICR, CAGR, OPM cross-check, and CFO quality score per
the Day 41 brief.
"""

from __future__ import annotations

import pytest

from src.analytics.cagr import (
    CAGR_DECLINE_TO_LOSS,
    CAGR_OK,
    CAGR_TURNAROUND,
    CAGR_ZERO_BASE,
    cagr,
)
from src.analytics.cashflow_kpis import (
    CFO_QUALITY_HIGH,
    CFO_QUALITY_MODERATE_LOW,
    cfo_pat_ratio,
    cfo_quality_tier,
)
from src.analytics.leverage import (
    HIGH_LEVERAGE_DE_THRESHOLD,
    debt_to_equity,
    high_leverage_flag,
    interest_coverage_ratio,
)
from src.analytics.ratios import (
    OPM_CROSSCHECK_TOLERANCE,
    compute_profitability_ratios,
    return_on_equity,
)


# --------------------------------------------------------------------------
# ROE — return_on_equity (4 tests)
# --------------------------------------------------------------------------
class TestROE:
    def test_roe_positive_equity_returns_pct(self) -> None:
        """Normal case: net_profit 150 on equity 700 → ~21.4%."""
        roe = return_on_equity(net_profit=150.0, equity_capital=100.0, reserves=600.0)
        assert roe is not None
        assert roe == pytest.approx(150.0 / 700.0 * 100.0)

    def test_roe_negative_equity_returns_none(self) -> None:
        """Negative book value (accumulated losses) → ROE meaningless → None."""
        roe = return_on_equity(net_profit=100.0, equity_capital=100.0, reserves=-500.0)
        assert roe is None

    def test_roe_zero_equity_returns_none(self) -> None:
        """Equity exactly zero → None (divide by zero guard)."""
        roe = return_on_equity(net_profit=50.0, equity_capital=0.0, reserves=0.0)
        assert roe is None

    def test_roe_reserves_none_treated_as_zero(self) -> None:
        """Missing reserves treated as zero."""
        roe = return_on_equity(net_profit=20.0, equity_capital=100.0, reserves=None)
        assert roe == pytest.approx(20.0)


# --------------------------------------------------------------------------
# D/E — debt_to_equity + high_leverage_flag (4 tests)
# --------------------------------------------------------------------------
class TestDebtToEquity:
    def test_de_zero_borrowings_returns_zero(self) -> None:
        """Debt-free company (borrowings=0) returns 0.0 explicitly."""
        de = debt_to_equity(borrowings=0.0, equity_capital=100.0, reserves=400.0)
        assert de == 0.0

    def test_de_normal_value(self) -> None:
        """Borrowings 200, equity 500 → D/E = 0.4."""
        de = debt_to_equity(borrowings=200.0, equity_capital=100.0, reserves=400.0)
        assert de is not None
        assert de == pytest.approx(0.4)

    def test_de_negative_equity_returns_none(self) -> None:
        de = debt_to_equity(borrowings=100.0, equity_capital=100.0, reserves=-500.0)
        assert de is None

    def test_high_leverage_flag_triggers_for_non_financial_above_5(self) -> None:
        """D/E > 5 AND not financial → True flag."""
        de = 5.5  # above threshold
        assert high_leverage_flag(de, is_financial=False) is True
        # financials are carve-out
        assert high_leverage_flag(de, is_financial=True) is False
        # at/under threshold → False
        assert high_leverage_flag(HIGH_LEVERAGE_DE_THRESHOLD, is_financial=False) is False


# --------------------------------------------------------------------------
# ICR — interest coverage ratio (2 tests)
# --------------------------------------------------------------------------
class TestInterestCoverage:
    def test_icr_zero_interest_returns_none(self) -> None:
        """Debt-free (interest=0) → None (display: Debt Free)."""
        icr = interest_coverage_ratio(operating_profit=250.0, other_income=10.0, interest=0.0)
        assert icr is None

    def test_icr_normal_calculation(self) -> None:
        """ICR = (250+10)/40 = 6.5."""
        icr = interest_coverage_ratio(operating_profit=250.0, other_income=10.0, interest=40.0)
        assert icr is not None
        assert icr == pytest.approx(6.5)


# --------------------------------------------------------------------------
# CAGR (5 tests)
# --------------------------------------------------------------------------
class TestCAGR:
    def test_cagr_turnaround_flag(self) -> None:
        """start<0 (loss), end>0 (profit) → TURNAROUND, value None."""
        r = cagr(start=-50.0, end=200.0, n=5)
        assert r.flag == CAGR_TURNAROUND
        assert r.value is None

    def test_cagr_decline_to_loss_flag(self) -> None:
        """start>0, end<0 → DECLINE_TO_LOSS, value None."""
        r = cagr(start=200.0, end=-50.0, n=5)
        assert r.flag == CAGR_DECLINE_TO_LOSS
        assert r.value is None

    def test_cagr_normal_calculation(self) -> None:
        """200 → 400 over 5 years = ~14.87% (doubles in 5y)."""
        r = cagr(start=200.0, end=400.0, n=5)
        assert r.flag == CAGR_OK
        assert r.value is not None
        assert r.value == pytest.approx((2 ** (1 / 5) - 1) * 100.0)

    def test_cagr_zero_base(self) -> None:
        r = cagr(start=0.0, end=100.0, n=5)
        assert r.flag == CAGR_ZERO_BASE
        assert r.value is None

    def test_cagr_negative_growth(self) -> None:
        """400 → 200 over 5 years = ~-12.94% CAGR."""
        r = cagr(start=400.0, end=200.0, n=5)
        assert r.flag == CAGR_OK
        assert r.value is not None
        assert r.value < 0


# --------------------------------------------------------------------------
# OPM cross-check divergence flag (3 tests)
# --------------------------------------------------------------------------
class TestOPMCrossCheck:
    def test_opm_crosscheck_no_divergence(self) -> None:
        """Source OPM matches computed → flag False."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=250.0,
            opm_percentage=25.0,
            net_profit=150.0,
            equity_capital=100.0,
            reserves=600.0,
            total_assets=1500.0,
        )
        assert res.opm_crosscheck_flag is False
        assert res.opm_crosscheck_delta == 0.0

    def test_opm_crosscheck_divergence_flag_true(self) -> None:
        """Source OPM diverges by >1pp → flag True."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=250.0,
            opm_percentage=30.0,  # 5pp divergence
            net_profit=150.0,
            equity_capital=100.0,
            reserves=600.0,
            total_assets=1500.0,
        )
        assert res.opm_crosscheck_flag is True
        assert res.opm_crosscheck_delta is not None
        assert res.opm_crosscheck_delta > OPM_CROSSCHECK_TOLERANCE

    def test_opm_crosscheck_at_tolerance_no_flag(self) -> None:
        """At exactly 1pp divergence → no flag (strictly greater)."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=250.0,
            opm_percentage=26.0,  # exactly 1pp delta
            net_profit=150.0,
            equity_capital=100.0,
            reserves=600.0,
            total_assets=1500.0,
        )
        assert res.opm_crosscheck_flag is False


# --------------------------------------------------------------------------
# CFO quality score & tier (2 tests)
# --------------------------------------------------------------------------
class TestCFOQuality:
    def test_cfo_pat_ratio_basic(self) -> None:
        """CFO 120, PAT 100 → ratio 1.2."""
        r = cfo_pat_ratio(cfo=120.0, pat=100.0)
        assert r == pytest.approx(1.2)

    def test_cfo_quality_tiers(self) -> None:
        """Tier thresholds per cashflow_kpis.py: >1.0 High, 0.5-1.0 Moderate, <0.5 Accrual Risk."""
        # Strictly greater than HIGH → High Quality
        assert cfo_quality_tier(1.2) == "High Quality"
        # At exactly the HIGH boundary (1.0), the rule is score > 1.0 → Moderate
        assert cfo_quality_tier(CFO_QUALITY_HIGH) == "Moderate"
        assert cfo_quality_tier(0.75) == "Moderate"
        # At exactly MODERATE_LOW (0.5) → Moderate (≥ bound)
        assert cfo_quality_tier(CFO_QUALITY_MODERATE_LOW) == "Moderate"
        assert cfo_quality_tier(0.3) == "Accrual Risk"
        assert cfo_quality_tier(None) is None
        assert cfo_quality_tier(float("nan")) is None
