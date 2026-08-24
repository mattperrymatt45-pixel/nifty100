"""
Unit tests for the Sprint 2 Day 08 profitability ratio engine.

Covers the spec-required edge cases:
    * Normal (healthy) case
    * Zero denominator → None
    * Negative equity → None
    * OPM source cross-check mismatch flag
    * Negative NPM (loss-making company) allowed
    * Financial-sector detection
    * ROCE computation includes borrowings
    * EBIT = operating_profit - depreciation
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.analytics.ratios import (
    OPM_CROSSCHECK_TOLERANCE,
    ProfitabilityRatios,
    compute_profitability_ratios,
    ebit,
    ebit_margin,
    is_financial_sector,
    net_profit_margin,
    operating_profit_margin,
    return_on_assets,
    return_on_capital_employed,
    return_on_equity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _approx(a: float | None, b: float, rel: float = 1e-6) -> bool:
    """Pytest approx wrapper that also accepts None (always fails)."""
    if a is None:
        return False
    return a == pytest.approx(b, rel=rel)


# ---------------------------------------------------------------------------
# 1. Normal case — all ratios return expected percentages
# ---------------------------------------------------------------------------
class TestNormalCase:
    """Standard profitable non-financial company (e.g. a typical FMCG/IT firm)."""

    @pytest.fixture()
    def result(self) -> ProfitabilityRatios:
        return compute_profitability_ratios(
            sales=1000.0,
            operating_profit=250.0,  # 25% OPM
            opm_percentage=25.0,
            depreciation=50.0,  # → EBIT = 200
            other_income=10.0,
            net_profit=150.0,  # 15% NPM
            equity_capital=100.0,
            reserves=500.0,  # equity = 600
            borrowings=200.0,  # CE = 800
            total_assets=1500.0,  # ROA = 10%
            broad_sector="Consumer Staples",
            company_id="HINDUNILVR",
            year="2023-03",
        )

    def test_npm(self, result: ProfitabilityRatios) -> None:
        """NPM = 150/1000*100 = 15%."""
        assert _approx(result.net_profit_margin_pct, 15.0)

    def test_opm(self, result: ProfitabilityRatios) -> None:
        """OPM = 250/1000*100 = 25%."""
        assert _approx(result.operating_profit_margin_pct, 25.0)

    def test_ebit_margin(self, result: ProfitabilityRatios) -> None:
        """EBIT margin = (250-50)/1000*100 = 20%."""
        assert _approx(result.ebit_margin_pct, 20.0)

    def test_roe(self, result: ProfitabilityRatios) -> None:
        """ROE = 150/(100+500)*100 = 25%."""
        assert _approx(result.return_on_equity_pct, 25.0)

    def test_roce(self, result: ProfitabilityRatios) -> None:
        """ROCE = 200/(100+500+200)*100 = 25%."""
        assert _approx(result.roce_pct, 25.0)

    def test_roa(self, result: ProfitabilityRatios) -> None:
        """ROA = 150/1500*100 = 10%."""
        assert _approx(result.return_on_assets_pct, 10.0)

    def test_no_opm_flag(self, result: ProfitabilityRatios) -> None:
        """OPM cross-check is within tolerance → flag False."""
        assert result.opm_crosscheck_flag is False
        assert result.opm_crosscheck_delta == pytest.approx(0.0)

    def test_not_financial(self, result: ProfitabilityRatios) -> None:
        assert result.is_financial_sector is False

    def test_warnings_empty(self, result: ProfitabilityRatios) -> None:
        assert len(result.warnings) == 0


# ---------------------------------------------------------------------------
# 2. Zero denominator → None (sales=0, total_assets=0)
# ---------------------------------------------------------------------------
class TestZeroDenominator:
    """Per spec §13: NPM/OPM/EBIT margin return None when sales=0; ROA None when assets=0."""

    def test_npm_zero_sales(self) -> None:
        assert net_profit_margin(net_profit=10.0, sales=0.0) is None

    def test_opm_zero_sales(self) -> None:
        assert operating_profit_margin(operating_profit=5.0, sales=0.0) is None

    def test_ebit_margin_zero_sales(self) -> None:
        assert ebit_margin(operating_profit=5.0, depreciation=1.0, sales=0.0) is None

    def test_roa_zero_assets(self) -> None:
        assert return_on_assets(net_profit=10.0, total_assets=0.0) is None

    def test_bundle_zero_sales(self) -> None:
        """compute_profitability_ratios returns None for sales-driven ratios."""
        res = compute_profitability_ratios(
            sales=0.0,
            operating_profit=0.0,
            opm_percentage=0.0,
            depreciation=0.0,
            net_profit=-5.0,
            equity_capital=100.0,
            reserves=400.0,
            borrowings=0.0,
            total_assets=800.0,
        )
        assert res.net_profit_margin_pct is None
        assert res.operating_profit_margin_pct is None
        assert res.ebit_margin_pct is None
        # ROE/ROCE/ROA should still compute
        assert res.return_on_equity_pct is not None
        assert res.roce_pct is not None
        assert res.return_on_assets_pct is not None


# ---------------------------------------------------------------------------
# 3. Negative equity → ROE and ROCE return None
# ---------------------------------------------------------------------------
class TestNegativeEquity:
    """Per spec §13: ROE = None when equity + reserves ≤ 0."""

    def test_roe_negative_equity(self) -> None:
        # equity_capital=10, reserves=-200 → equity=-190 (accumulated losses > capital)
        assert return_on_equity(net_profit=10.0, equity_capital=10.0, reserves=-200.0) is None

    def test_roe_zero_equity(self) -> None:
        assert return_on_equity(net_profit=10.0, equity_capital=0.0, reserves=0.0) is None

    def test_roce_negative_capital_employed(self) -> None:
        # CE = 10 + (-200) + 0 = -190 → None
        assert (
            return_on_capital_employed(
                operating_profit=50.0,
                depreciation=10.0,
                equity_capital=10.0,
                reserves=-200.0,
                borrowings=0.0,
            )
            is None
        )

    def test_bundle_negative_equity(self) -> None:
        res = compute_profitability_ratios(
            sales=500.0,
            operating_profit=50.0,
            opm_percentage=10.0,
            depreciation=10.0,
            net_profit=-30.0,
            equity_capital=10.0,
            reserves=-200.0,
            borrowings=50.0,
            total_assets=600.0,
        )
        assert res.return_on_equity_pct is None
        # CE = 10 + (-200) + 50 = -140 → ROCE None
        assert res.roce_pct is None
        # NPM/OPM/EBIT/ROA still compute
        assert res.net_profit_margin_pct is not None
        assert res.operating_profit_margin_pct is not None
        assert res.return_on_assets_pct is not None


# ---------------------------------------------------------------------------
# 4. OPM cross-check mismatch → flag True, warning emitted
# ---------------------------------------------------------------------------
class TestOPMCrossCheck:
    """If recomputed OPM differs from source by >1pp, opm_crosscheck_flag is True."""

    def test_flag_triggered_on_large_mismatch(self) -> None:
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=300.0,  # → 30%
            opm_percentage=20.0,  # source says 20%  (delta = 10pp)
            depreciation=50.0,
            net_profit=180.0,
            equity_capital=100.0,
            reserves=500.0,
            borrowings=200.0,
            total_assets=1500.0,
            company_id="TESTCO",
            year="2023-03",
        )
        assert res.opm_crosscheck_flag is True
        assert res.opm_crosscheck_delta is not None
        assert res.opm_crosscheck_delta == pytest.approx(10.0)
        assert len(res.warnings) == 1
        assert "OPM cross-check" in res.warnings[0]

    def test_flag_not_triggered_at_exact_tolerance(self) -> None:
        """Exactly at tolerance boundary should NOT flag (strict >)."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=260.0,  # → 26%
            opm_percentage=25.0,  # delta exactly 1pp
            depreciation=0.0,
            net_profit=150.0,
            equity_capital=100.0,
            reserves=500.0,
            borrowings=0.0,
            total_assets=1000.0,
        )
        assert res.opm_crosscheck_flag is False
        assert res.opm_crosscheck_delta == pytest.approx(OPM_CROSSCHECK_TOLERANCE)

    def test_flag_triggered_just_above_tolerance(self) -> None:
        """1.0001 pp mismatch → flag True."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=260.0 + 0.001,  # 26.0001%
            opm_percentage=25.0,
            depreciation=0.0,
            net_profit=150.0,
            equity_capital=100.0,
            reserves=500.0,
            borrowings=0.0,
            total_assets=1000.0,
        )
        assert res.opm_crosscheck_flag is True

    def test_no_source_opm_no_delta(self) -> None:
        """If opm_percentage is None, no cross-check is performed."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=250.0,
            opm_percentage=None,
            depreciation=0.0,
            net_profit=150.0,
            equity_capital=100.0,
            reserves=500.0,
            borrowings=0.0,
            total_assets=1000.0,
        )
        assert res.opm_crosscheck_delta is None
        assert res.opm_crosscheck_flag is False


# ---------------------------------------------------------------------------
# 5. Negative NPM allowed (loss-making company)
# ---------------------------------------------------------------------------
class TestNegativeMargins:
    def test_negative_npm(self) -> None:
        assert net_profit_margin(net_profit=-50.0, sales=1000.0) == pytest.approx(-5.0)

    def test_negative_opm(self) -> None:
        assert operating_profit_margin(operating_profit=-30.0, sales=1000.0) == pytest.approx(-3.0)

    def test_negative_roe(self) -> None:
        """Negative PAT with positive equity → negative ROE (loss year)."""
        assert return_on_equity(net_profit=-50.0, equity_capital=100.0, reserves=400.0) == (
            pytest.approx(-10.0)
        )


# ---------------------------------------------------------------------------
# 6. Financial-sector detection
# ---------------------------------------------------------------------------
class TestFinancialSectorDetection:
    @pytest.mark.parametrize(
        "sector,expected",
        [
            ("Financials (Banks)", True),
            ("Financials (NBFC)", True),
            ("Banks", True),
            ("NBFC", True),
            ("Consumer Finance", True),
            ("Financial Services", True),
            ("Information Technology", False),
            ("Consumer Staples", False),
            ("Energy (Oil & Gas)", False),
            ("", False),
            (None, False),
        ],
    )
    def test_is_financial_sector(self, sector: str | None, expected: bool) -> None:
        assert is_financial_sector(sector) is expected

    def test_bundle_flags_bank(self) -> None:
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=300.0,
            opm_percentage=30.0,
            depreciation=20.0,
            net_profit=180.0,
            equity_capital=100.0,
            reserves=500.0,
            borrowings=4000.0,  # banks have very high borrowings (deposits)
            total_assets=8000.0,
            broad_sector="Financials (Banks)",
        )
        assert res.is_financial_sector is True
        # ROCE still computed but will be structurally low
        assert res.roce_pct is not None
        assert res.roce_pct < 10.0  # 280/4600 ≈ 6%


# ---------------------------------------------------------------------------
# 7. ROCE uses borrowings correctly
# ---------------------------------------------------------------------------
class TestROCEComposition:
    def test_ebit_formula(self) -> None:
        assert ebit(operating_profit=250.0, depreciation=50.0) == pytest.approx(200.0)

    def test_ebit_with_none_depreciation(self) -> None:
        """Missing depreciation treated as 0."""
        assert ebit(operating_profit=250.0, depreciation=None) == pytest.approx(250.0)  # type: ignore[arg-type]

    def test_roce_includes_borrowings(self) -> None:
        # CE = 100 + 400 + 500 = 1000; EBIT = 200-40 = 160 → ROCE = 16%
        roce = return_on_capital_employed(
            operating_profit=200.0,
            depreciation=40.0,
            equity_capital=100.0,
            reserves=400.0,
            borrowings=500.0,
        )
        assert roce == pytest.approx(16.0)

    def test_roce_zero_borrowings_debt_free(self) -> None:
        """Debt-free company: CE = equity only."""
        roce = return_on_capital_employed(
            operating_profit=200.0,
            depreciation=0.0,
            equity_capital=100.0,
            reserves=400.0,
            borrowings=0.0,
        )
        # EBIT=200, CE=500 → 40%
        assert roce == pytest.approx(40.0)

    def test_roce_none_borrowings_treated_as_zero(self) -> None:
        roce = return_on_capital_employed(
            operating_profit=200.0,
            depreciation=0.0,
            equity_capital=100.0,
            reserves=400.0,
            borrowings=None,
        )
        assert roce == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# 8. Missing optional inputs (reserves=None) handled gracefully
# ---------------------------------------------------------------------------
class TestOptionalInputs:
    def test_reserves_none_treated_as_zero(self) -> None:
        # equity_capital=600, reserves=None → equity=600; PAT=90 → ROE=15%
        assert return_on_equity(net_profit=90.0, equity_capital=600.0, reserves=None) == (
            pytest.approx(15.0)
        )

    def test_depreciation_default_zero(self) -> None:
        """EBIT margin with default depreciation=0 = OPM."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=250.0,
            opm_percentage=25.0,
            net_profit=150.0,
            equity_capital=100.0,
            reserves=500.0,
            borrowings=200.0,
            total_assets=1500.0,
        )
        # No depreciation passed → defaults to 0 → EBIT margin = OPM = 25%
        assert res.ebit_margin_pct == pytest.approx(25.0)

    def test_result_is_frozen(self) -> None:
        """ProfitabilityRatios is a frozen dataclass (immutability guarantee)."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=200.0,
            net_profit=100.0,
            equity_capital=100.0,
            reserves=400.0,
            total_assets=1000.0,
        )
        with pytest.raises(FrozenInstanceError):
            res.net_profit_margin_pct = 999.0  # type: ignore[misc]

    def test_warnings_is_tuple(self) -> None:
        """Warnings should be exposed as a tuple (immutable)."""
        res = compute_profitability_ratios(
            sales=1000.0,
            operating_profit=200.0,
            opm_percentage=20.0,
            net_profit=100.0,
            equity_capital=100.0,
            reserves=400.0,
            total_assets=1000.0,
        )
        assert isinstance(res.warnings, tuple)
