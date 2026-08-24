"""
Unit tests for the Sprint 2 Day 11 Cash-Flow KPI engine.

Covers the spec-required KPIs:
    1. Free Cash Flow (CFO+CFI; negative allowed)
    2. CFO/PAT ratio & 5-yr CFO Quality Score + tier labels
    3. CapEx Intensity with tier labels (Asset Light / Moderate / Capital Intensive)
    4. FCF Conversion Rate (FCF / EBITDA x 100)
    5. 8-class Capital Allocation pattern classifier from (CFO, CFI, CFF) signs
    6. CSV output for capital_allocation.csv
"""

from __future__ import annotations

import csv
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.analytics.cashflow_kpis import (
    CAPEX_LIGHT_MAX,
    CAPEX_MODERATE_MAX,
    CAPITAL_ALLOCATION_CSV_COLUMNS,
    CFO_QUALITY_HIGH,
    CFO_QUALITY_MODERATE_LOW,
    PATTERN_CASH_ACCUMULATOR,
    PATTERN_DISTRESS_SIGNAL,
    PATTERN_GROWTH_FUNDED_BY_DEBT,
    PATTERN_LIQUIDATING_ASSETS,
    PATTERN_MIXED,
    PATTERN_PRE_REVENUE,
    PATTERN_REINVESTOR,
    PATTERN_SHAREHOLDER_RETURNS,
    CapitalAllocationRow,
    CashFlowKPIs,
    build_capital_allocation_rows,
    capex_intensity,
    capex_tier,
    cfo_pat_ratio,
    cfo_quality_tier,
    classify_capital_allocation,
    compute_cashflow_kpis_for_company,
    fcf_conversion,
    free_cash_flow,
    write_capital_allocation_csv,
)


# ---------------------------------------------------------------------------
# 1. Free Cash Flow
# ---------------------------------------------------------------------------
class TestFreeCashFlow:
    def test_fcf_positive(self) -> None:
        # CFO 1000, CFI -400 → FCF 600
        assert free_cash_flow(1000.0, -400.0) == pytest.approx(600.0)

    def test_fcf_negative_allowed(self) -> None:
        """Negative FCF (cash burn) is allowed per spec."""
        assert free_cash_flow(200.0, -500.0) == pytest.approx(-300.0)

    def test_fcf_zero_cfi(self) -> None:
        assert free_cash_flow(500.0, 0.0) == pytest.approx(500.0)

    def test_fcf_all_negative(self) -> None:
        assert free_cash_flow(-100.0, -200.0) == pytest.approx(-300.0)


# ---------------------------------------------------------------------------
# 2. CFO / PAT ratio + CFO Quality tier
# ---------------------------------------------------------------------------
class TestCFOPAT:
    def test_normal_ratio(self) -> None:
        # CFO 120, PAT 100 → 1.2
        assert cfo_pat_ratio(120.0, 100.0) == pytest.approx(1.2)

    def test_pat_zero_returns_none(self) -> None:
        assert cfo_pat_ratio(50.0, 0.0) is None

    def test_negative_pat(self) -> None:
        # Loss-making; ratio is negative
        assert cfo_pat_ratio(50.0, -100.0) == pytest.approx(-0.5)

    def test_high_quality_tier(self) -> None:
        assert cfo_quality_tier(1.2) == "High Quality"
        assert cfo_quality_tier(CFO_QUALITY_HIGH + 0.01) == "High Quality"

    def test_moderate_tier(self) -> None:
        assert cfo_quality_tier(0.75) == "Moderate"
        assert cfo_quality_tier(CFO_QUALITY_MODERATE_LOW) == "Moderate"
        assert cfo_quality_tier(1.0) == "Moderate"

    def test_accrual_risk_tier(self) -> None:
        assert cfo_quality_tier(0.3) == "Accrual Risk"
        assert cfo_quality_tier(-0.2) == "Accrual Risk"

    def test_tier_none(self) -> None:
        assert cfo_quality_tier(None) is None

    def test_tier_threshold_constants(self) -> None:
        assert CFO_QUALITY_HIGH == 1.0
        assert CFO_QUALITY_MODERATE_LOW == 0.5


# ---------------------------------------------------------------------------
# 3. CapEx Intensity + tiers
# ---------------------------------------------------------------------------
class TestCapexIntensity:
    def test_asset_light(self) -> None:
        # |CFI|=20, sales=1000 → 2% → Asset Light
        pct = capex_intensity(-20.0, 1000.0)
        assert pct == pytest.approx(2.0)
        assert capex_tier(pct) == "Asset Light"

    def test_moderate(self) -> None:
        # |CFI|=50, sales=1000 → 5% → Moderate
        pct = capex_intensity(-50.0, 1000.0)
        assert pct == pytest.approx(5.0)
        assert capex_tier(pct) == "Moderate"

    def test_capital_intensive(self) -> None:
        # |CFI|=150, sales=1000 → 15% → Capital Intensive
        pct = capex_intensity(-150.0, 1000.0)
        assert pct == pytest.approx(15.0)
        assert capex_tier(pct) == "Capital Intensive"

    def test_zero_sales_returns_none(self) -> None:
        assert capex_intensity(-100.0, 0.0) is None
        assert capex_tier(None) is None

    def test_positive_cfi_uses_abs(self) -> None:
        # Divestment year — positive CFI should still compute positive intensity
        pct = capex_intensity(50.0, 1000.0)
        assert pct == pytest.approx(5.0)

    def test_threshold_constants(self) -> None:
        assert CAPEX_LIGHT_MAX == 3.0
        assert CAPEX_MODERATE_MAX == 8.0


# ---------------------------------------------------------------------------
# 4. FCF Conversion Rate
# ---------------------------------------------------------------------------
class TestFCFConversion:
    def test_healthy_conversion(self) -> None:
        # FCF 600, EBITDA 1000 → 60%
        assert fcf_conversion(600.0, 1000.0) == pytest.approx(60.0)

    def test_op_profit_zero_none(self) -> None:
        assert fcf_conversion(100.0, 0.0) is None

    def test_negative_fcf(self) -> None:
        # Negative FCF → negative conversion %
        assert fcf_conversion(-200.0, 1000.0) == pytest.approx(-20.0)


# ---------------------------------------------------------------------------
# 5. Capital Allocation 8-Pattern Classifier
# ---------------------------------------------------------------------------
class TestCapitalAllocation:
    def test_reinvestor(self) -> None:
        s_cfo, s_cfi, s_cff, label = classify_capital_allocation(
            1000, -400, -300, cfo_pat=0.8  # (+, -, -) with moderate CFO/PAT
        )
        assert (s_cfo, s_cfi, s_cff) == ("+", "-", "-")
        assert label == PATTERN_REINVESTOR

    def test_shareholder_returns_subclass(self) -> None:
        """(+, -, -) with high CFO/PAT ratio → Shareholder Returns."""
        _, _, _, label = classify_capital_allocation(1500, -400, -800, cfo_pat=1.2)
        assert label == PATTERN_SHAREHOLDER_RETURNS

    def test_liquidating_assets(self) -> None:
        """(+, +, -): selling assets, paying down debt/returning capital."""
        _, _, _, label = classify_capital_allocation(500, 300, -200, cfo_pat=0.6)
        assert label == PATTERN_LIQUIDATING_ASSETS

    def test_distress_signal(self) -> None:
        """(-, +, +): operations bleeding, raising cash via asset sales + financing."""
        _, _, _, label = classify_capital_allocation(-200, 150, 300, cfo_pat=-0.3)
        assert label == PATTERN_DISTRESS_SIGNAL

    def test_growth_funded_by_debt(self) -> None:
        """(-, -, +): investing heavily while ops are weak, funded by fresh financing."""
        _, _, _, label = classify_capital_allocation(-100, -500, 800, cfo_pat=-0.2)
        assert label == PATTERN_GROWTH_FUNDED_BY_DEBT

    def test_cash_accumulator(self) -> None:
        """(+, +, +): cash piling up from ops, asset sales, AND financing."""
        _, _, _, label = classify_capital_allocation(500, 200, 300, cfo_pat=1.1)
        assert label == PATTERN_CASH_ACCUMULATOR

    def test_pre_revenue(self) -> None:
        """(-, -, -): no cash from ops, heavy investing/financing outflows (very rare)."""
        _, _, _, label = classify_capital_allocation(-50, -200, -100, cfo_pat=None)
        assert label == PATTERN_PRE_REVENUE

    def test_mixed(self) -> None:
        """(+, -, +): ops positive, investing, financing inflow — 'Mixed' catch-all."""
        _, _, _, label = classify_capital_allocation(500, -300, 200, cfo_pat=0.9)
        assert label == PATTERN_MIXED

    def test_zero_treated_as_positive_sign(self) -> None:
        """Zero flows should map to '+' (neutral), so (0,-500,-200) is Reinvestor."""
        _, _, _, label = classify_capital_allocation(0, -500, -200, cfo_pat=0.0)
        assert label == PATTERN_REINVESTOR

    def test_cfo_pat_none_keeps_base_pattern(self) -> None:
        """If cfo_pat is None (PAT=0), don't promote to Shareholder Returns."""
        _, _, _, label = classify_capital_allocation(1000, -500, -400, cfo_pat=None)
        assert label == PATTERN_REINVESTOR


# ---------------------------------------------------------------------------
# 6. Series-level compute for one company (rolling window + flags)
# ---------------------------------------------------------------------------
class TestComputeForCompany:
    @pytest.fixture()
    def sample_data(self) -> tuple[list[dict], list[dict]]:
        """6 years of data for a fictional growing company."""
        years = [f"{y}-03" for y in range(2019, 2025)]
        pl_rows = []
        cf_rows = []
        for i, yr in enumerate(years):
            sales = 1000.0 * (1.10**i)
            op_profit = 200.0 * (1.10**i)
            pat = 150.0 * (1.10**i)
            cfo = 160.0 * (1.10**i)  # CFO ~ PAT*1.07 (high quality)
            cfi = -80.0 * (1.10**i)  # CapEx ≈ 8% of sales
            cff = -50.0 if i >= 2 else -30.0  # Negative CFF → Reinvestor/Returns
            pl_rows.append(
                {"year": yr, "sales": sales, "operating_profit": op_profit, "net_profit": pat}
            )
            cf_rows.append(
                {
                    "year": yr,
                    "operating_activity": cfo,
                    "investing_activity": cfi,
                    "financing_activity": cff,
                    "net_cash_flow": cfo + cfi + cff,
                }
            )
        return pl_rows, cf_rows

    def test_returns_one_row_per_matching_year(self, sample_data) -> None:
        pl, cf = sample_data
        out = compute_cashflow_kpis_for_company("TESTCO", pl, cf)
        assert len(out) == len(pl)
        assert all(isinstance(k, CashFlowKPIs) for k in out)

    def test_fcf_values(self, sample_data) -> None:
        pl, cf = sample_data
        out = compute_cashflow_kpis_for_company("TESTCO", pl, cf)
        # First year: CFO=160, CFI=-80 → FCF=80
        assert out[0].fcf_cr == pytest.approx(80.0)
        assert out[0].fcf_cr > 0

    def test_cfo_pat_ratio_positive(self, sample_data) -> None:
        pl, cf = sample_data
        out = compute_cashflow_kpis_for_company("TESTCO", pl, cf)
        # CFO ~ PAT*1.07 → ratio ≈ 1.07
        assert out[-1].cfo_pat_ratio == pytest.approx(160.0 / 150.0, rel=1e-6)

    def test_cfo_quality_needs_3yr_min(self, sample_data) -> None:
        """First 2 years have < 3yr history → quality score None."""
        pl, cf = sample_data
        out = compute_cashflow_kpis_for_company("TESTCO", pl, cf)
        assert out[0].cfo_quality_score_5yr is None
        assert out[1].cfo_quality_score_5yr is None
        assert out[2].cfo_quality_score_5yr is not None
        assert out[2].cfo_quality_tier is not None

    def test_capex_tier_assigned(self, sample_data) -> None:
        pl, cf = sample_data
        out = compute_cashflow_kpis_for_company("TESTCO", pl, cf)
        # CapEx ≈ 8% of sales → tier is "Moderate" (at boundary, < is Light, ≤ is Moderate)
        assert out[-1].capex_tier in ("Asset Light", "Moderate", "Capital Intensive")
        assert out[-1].capex_intensity_pct is not None

    def test_pattern_reinvestor_or_returns(self, sample_data) -> None:
        pl, cf = sample_data
        out = compute_cashflow_kpis_for_company("TESTCO", pl, cf)
        # (+, -, -) with CFO/PAT ~1.07 → should be Shareholder Returns once quality available
        assert out[-1].capital_allocation_pattern in (
            PATTERN_REINVESTOR,
            PATTERN_SHAREHOLDER_RETURNS,
        )
        assert out[-1].cfo_sign == "+"
        assert out[-1].cfi_sign == "-"
        assert out[-1].cff_sign == "-"

    def test_fcf_concern_3yr_consecutive_negative(self) -> None:
        """3 consecutive negative FCF years → fcf_concern_flag True on the 3rd."""
        pl = [
            {"year": "2022-03", "sales": 1000, "operating_profit": 200, "net_profit": 150},
            {"year": "2023-03", "sales": 1000, "operating_profit": 200, "net_profit": 150},
            {"year": "2024-03", "sales": 1000, "operating_profit": 200, "net_profit": 150},
        ]
        cf = [
            # CFO positive but swamped by heavy CFI → negative FCF
            {
                "year": "2022-03",
                "operating_activity": 100,
                "investing_activity": -300,
                "financing_activity": 250,
                "net_cash_flow": 50,
            },
            {
                "year": "2023-03",
                "operating_activity": 110,
                "investing_activity": -400,
                "financing_activity": 320,
                "net_cash_flow": 30,
            },
            {
                "year": "2024-03",
                "operating_activity": 90,
                "investing_activity": -500,
                "financing_activity": 450,
                "net_cash_flow": 40,
            },
        ]
        out = compute_cashflow_kpis_for_company("BURNC", pl, cf)
        assert out[0].fcf_concern_flag is False
        assert out[1].fcf_concern_flag is False
        assert out[2].fcf_concern_flag is True

    def test_empty_inputs(self) -> None:
        assert compute_cashflow_kpis_for_company("EMPTY", [], []) == []

    def test_mismatched_years_inner_join(self) -> None:
        pl = [{"year": "2023-03", "sales": 1000, "operating_profit": 200, "net_profit": 150}]
        cf = [
            {
                "year": "2022-03",
                "operating_activity": 100,
                "investing_activity": -50,
                "financing_activity": -30,
                "net_cash_flow": 20,
            },
            {
                "year": "2023-03",
                "operating_activity": 120,
                "investing_activity": -60,
                "financing_activity": -40,
                "net_cash_flow": 20,
            },
        ]
        out = compute_cashflow_kpis_for_company("GAP", pl, cf)
        # Only 2023 overlaps
        assert len(out) == 1

    def test_pat_zero_year_handled(self) -> None:
        pl = [{"year": "2023-03", "sales": 1000, "operating_profit": 100, "net_profit": 0}]
        cf = [
            {
                "year": "2023-03",
                "operating_activity": 80,
                "investing_activity": -40,
                "financing_activity": -30,
                "net_cash_flow": 10,
            }
        ]
        out = compute_cashflow_kpis_for_company("ZEROPAT", pl, cf)
        assert len(out) == 1
        assert out[0].cfo_pat_ratio is None
        # Without CFO/PAT, (+,-,-) stays Reinvestor (not promoted)
        assert out[0].capital_allocation_pattern == PATTERN_REINVESTOR


# ---------------------------------------------------------------------------
# 7. CSV output
# ---------------------------------------------------------------------------
class TestCapitalAllocationCSV:
    def test_csv_columns_and_content(self, tmp_path: Path) -> None:
        pl_rows = [
            {"year": "2022-03", "sales": 1000, "operating_profit": 200, "net_profit": 150},
            {"year": "2023-03", "sales": 1100, "operating_profit": 220, "net_profit": 165},
            {"year": "2024-03", "sales": 1210, "operating_profit": 242, "net_profit": 180},
        ]
        cf_rows = [
            {
                "year": "2022-03",
                "operating_activity": 200,
                "investing_activity": -80,
                "financing_activity": -90,
                "net_cash_flow": 30,
            },
            {
                "year": "2023-03",
                "operating_activity": -50,
                "investing_activity": 30,
                "financing_activity": 40,
                "net_cash_flow": 20,
            },
            {
                "year": "2024-03",
                "operating_activity": 250,
                "investing_activity": -100,
                "financing_activity": -100,
                "net_cash_flow": 50,
            },
        ]
        kpis = compute_cashflow_kpis_for_company("TST", pl_rows, cf_rows)
        years = [r["year"] for r in pl_rows]
        rows = build_capital_allocation_rows("TST", years, kpis)
        assert len(rows) == 3
        assert all(isinstance(r, CapitalAllocationRow) for r in rows)

        out = tmp_path / "capital_allocation.csv"
        n = write_capital_allocation_csv(rows, out)
        assert n == 3
        assert out.exists()

        # Read back and verify columns
        with out.open() as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == CAPITAL_ALLOCATION_CSV_COLUMNS
            data = list(reader)
        assert len(data) == 3
        assert data[0]["company_id"] == "TST"
        assert data[0]["year"] == "2022-03"
        assert data[0]["cfo_sign"] == "+"
        assert data[0]["pattern_label"] in (PATTERN_REINVESTOR, PATTERN_SHAREHOLDER_RETURNS)
        # 2023 was (- , + , +) → Distress Signal
        assert data[1]["cfo_sign"] == "-"
        assert data[1]["cfi_sign"] == "+"
        assert data[1]["cff_sign"] == "+"
        assert data[1]["pattern_label"] == PATTERN_DISTRESS_SIGNAL

    def test_csv_empty_writes_header_only(self, tmp_path: Path) -> None:
        out = tmp_path / "empty.csv"
        n = write_capital_allocation_csv([], out)
        assert n == 0
        text = out.read_text()
        assert ",".join(CAPITAL_ALLOCATION_CSV_COLUMNS) in text

    def test_csv_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "dir" / "capital_allocation.csv"
        write_capital_allocation_csv([], out)
        assert out.exists()


# ---------------------------------------------------------------------------
# 8. Result contract / immutability
# ---------------------------------------------------------------------------
class TestCashflowKPIResultContract:
    def test_frozen_dataclass(self) -> None:
        kpi = CashFlowKPIs(
            fcf_cr=100.0,
            cfo_pat_ratio=1.1,
            cfo_quality_score_5yr=1.05,
            cfo_quality_tier="High Quality",
            capex_intensity_pct=5.0,
            capex_tier="Moderate",
            fcf_conversion_pct=60.0,
            cfo_sign="+",
            cfi_sign="-",
            cff_sign="-",
            capital_allocation_pattern=PATTERN_REINVESTOR,
            fcf_concern_flag=False,
        )
        with pytest.raises(FrozenInstanceError):
            kpi.fcf_cr = 999.0  # type: ignore[misc]

    def test_capital_allocation_row_as_dict(self) -> None:
        r = CapitalAllocationRow(
            company_id="TCS",
            year="2024-03",
            cfo_sign="+",
            cfi_sign="-",
            cff_sign="-",
            pattern_label=PATTERN_SHAREHOLDER_RETURNS,
        )
        d = r.as_dict()
        assert set(d.keys()) == set(CAPITAL_ALLOCATION_CSV_COLUMNS)
        assert d["pattern_label"] == PATTERN_SHAREHOLDER_RETURNS
