"""Unit tests for Sprint 2 Day 13 — Bank/NBFC ROCE carve-out and cross-check.

Covers:
    * Financial-sector detection (banks/NBFCs/insurance)
    * Bank ROCE uses ROA-proxy (EBIT/total_assets) instead of standard ROCE
    * Non-financial companies continue to use standard ROCE
    * Cross-check anomalies flagged only when |computed-source| > threshold
    * Bank ROCE discrepancies always categorised as bank_carveout
    * Anomaly categorisation by magnitude (formula / version / data_source)
    * Log formatter produces a non-empty report with categories
"""

from __future__ import annotations

import pytest

from src.analytics.sector_roce import (
    ROCEAnomaly,
    categorize_anomaly,
    compute_bank_roce,
    cross_check_vs_source,
    format_anomaly_log,
    is_bank_nfc_insurance,
    roce_for_company,
)


# ---------------------------------------------------------------------------
# Sector detection
# ---------------------------------------------------------------------------
class TestSectorDetection:
    @pytest.mark.parametrize(
        "sector,expected",
        [
            ("Financials (Banks)", True),
            ("Financials (NBFC)", True),
            ("Financials", True),
            ("Banks", True),
            ("NBFC", True),
            ("Consumer Finance", True),
            ("Financial Services", True),
            ("Life Insurance", True),
            ("Insurance", True),
            ("Information Technology", False),
            ("Consumer Staples", False),
            ("Energy (Oil & Gas)", False),
            ("", False),
            (None, False),
        ],
    )
    def test_sector_classification(self, sector, expected):
        assert is_bank_nfc_insurance(sector) is expected


# ---------------------------------------------------------------------------
# Bank ROCE (ROA-proxy)
# ---------------------------------------------------------------------------
class TestBankROCE:
    def test_bank_roce_uses_total_assets(self):
        # EBIT = 1000 - 200 = 800; total_assets=20000 → ROA=4%
        val = compute_bank_roce(operating_profit=1000, depreciation=200, total_assets=20000)
        assert val == pytest.approx(4.0)

    def test_bank_roce_zero_assets_returns_none(self):
        assert compute_bank_roce(100, 20, 0) is None

    def test_standard_roce_for_nonfinancial(self):
        # EBIT=800, CE=2000+6000+2000=10000 → ROCE=8%
        val = roce_for_company(
            operating_profit=1000,
            depreciation=200,
            equity_capital=2000,
            reserves=6000,
            borrowings=2000,
            total_assets=20000,
            broad_sector="Information Technology",
        )
        assert val == pytest.approx(8.0)

    def test_bank_dispatches_to_bank_formula(self):
        val = roce_for_company(
            operating_profit=1000,
            depreciation=200,
            equity_capital=2000,
            reserves=6000,
            borrowings=12000,  # huge deposits → standard ROCE would be tiny
            total_assets=20000,
            broad_sector="Financials (Banks)",
        )
        # Should use EBIT/total_assets = 4%
        assert val == pytest.approx(4.0)

    def test_negative_capital_employed_none(self):
        val = roce_for_company(
            operating_profit=100,
            depreciation=10,
            equity_capital=100,
            reserves=-500,
            borrowings=0,
            total_assets=1000,
            broad_sector="Industrials",
        )
        assert val is None


# ---------------------------------------------------------------------------
# Cross-check and categorisation
# ---------------------------------------------------------------------------
class TestCrossCheck:
    def test_no_anomaly_when_within_threshold(self):
        res = cross_check_vs_source(
            company_id="GOODCO",
            company_name="Good Co",
            broad_sector="Consumer Staples",
            year="2024-03",
            computed_roce=20.0,
            source_roce=21.5,  # Δ=1.5 < 5
            computed_roe=15.0,
            source_roe=16.0,  # Δ=1.0 < 10
        )
        assert res == []

    def test_roce_anomaly_flagged(self):
        res = cross_check_vs_source(
            company_id="BADCO",
            company_name="Bad Co",
            broad_sector="Industrials",
            year="2024-03",
            computed_roce=10.0,
            source_roce=20.0,  # Δ=10 > 5
            computed_roe=12.0,
            source_roe=13.0,
        )
        assert len(res) == 1
        assert res[0].metric == "ROCE"
        assert res[0].delta_pp == pytest.approx(10.0)
        assert res[0].category in ("formula_discrepancy", "version_difference", "data_source")

    def test_roe_anomaly_flagged(self):
        res = cross_check_vs_source(
            company_id="BADCO",
            company_name="Bad Co",
            broad_sector="Industrials",
            year="2024-03",
            computed_roce=20.0,
            source_roce=21.0,
            computed_roe=5.0,
            source_roe=20.0,  # Δ=15 > 10
        )
        assert any(a.metric == "ROE" for a in res)

    def test_bank_roce_always_flagged_informational(self):
        res = cross_check_vs_source(
            company_id="HDFCBANK",
            company_name="HDFC Bank",
            broad_sector="Financials (Banks)",
            year="2024-03",
            computed_roce=2.0,
            source_roce=21.41,  # huge delta — banks always flagged as carve-out
            computed_roe=1.3,
            source_roe=29.84,
        )
        # ROCE must be flagged as bank_carveout
        assert any(a.metric == "ROCE" and a.category == "bank_carveout" for a in res)

    def test_none_values_skipped(self):
        res = cross_check_vs_source(
            company_id="X",
            company_name="X",
            broad_sector="Industrials",
            year="2024-03",
            computed_roce=None,
            source_roce=20.0,
            computed_roe=15.0,
            source_roe=None,
        )
        assert res == []


# ---------------------------------------------------------------------------
# Categorisation thresholds
# ---------------------------------------------------------------------------
class TestCategorisation:
    def test_formula_discrepancy_small_delta(self):
        assert (
            categorize_anomaly(
                metric="ROCE",
                delta_pp=7,
                is_financial=False,
                computed_pct=20,
                source_pct=27,
            )
            == "formula_discrepancy"
        )

    def test_version_difference_medium_delta(self):
        assert (
            categorize_anomaly(
                metric="ROCE",
                delta_pp=20,
                is_financial=False,
                computed_pct=20,
                source_pct=40,
            )
            == "version_difference"
        )

    def test_data_source_large_delta(self):
        assert (
            categorize_anomaly(
                metric="ROCE",
                delta_pp=50,
                is_financial=False,
                computed_pct=2,
                source_pct=52,
            )
            == "data_source"
        )

    def test_bank_carveout_regardless_of_delta(self):
        assert (
            categorize_anomaly(
                metric="ROCE",
                delta_pp=5,
                is_financial=True,
                computed_pct=2,
                source_pct=25,
            )
            == "bank_carveout"
        )


# ---------------------------------------------------------------------------
# Log formatter
# ---------------------------------------------------------------------------
class TestLogFormatter:
    def test_empty_log_mentions_no_anomalies(self):
        txt = format_anomaly_log([])
        assert "No anomalies found" in txt

    def test_log_contains_categories_and_summary(self):
        anomalies = [
            ROCEAnomaly(
                company_id="HDFCBANK",
                company_name="HDFC Bank",
                broad_sector="Financials (Banks)",
                year="2024-03",
                metric="ROCE",
                computed_pct=2.0,
                source_pct=21.41,
                delta_pp=19.41,
                is_financial=True,
                category="bank_carveout",
            ),
            ROCEAnomaly(
                company_id="TCS",
                company_name="Tata Consultancy Services",
                broad_sector="Information Technology",
                year="2024-03",
                metric="ROCE",
                computed_pct=1.12,
                source_pct=59.3,
                delta_pp=58.18,
                is_financial=False,
                category="data_source",
            ),
        ]
        txt = format_anomaly_log(anomalies)
        assert "BANK_CARVEOUT" in txt
        assert "DATA_SOURCE" in txt
        assert "HDFCBANK" in txt
        assert "TCS" in txt
        assert "TOTAL ANOMALIES: 2" in txt
        # Display-policy note should be present
        assert "DISPLAY POLICY" in txt
