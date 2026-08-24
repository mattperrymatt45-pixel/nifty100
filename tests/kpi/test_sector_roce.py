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


# ---------------------------------------------------------------------------
# Integration guard: run_bank_carveout must UPDATE only the Day-13 columns and
# never clobber pre-existing ratio columns (regression for Day-14 bug where
# load_dataframe(merge=True) DELETE+INSERT-ed rows with a 7-column DataFrame,
# wiping ROE/ROCE/CAGR/composite to NULL).
# ---------------------------------------------------------------------------
class TestRunBankCarveoutNoClobber:
    def test_existing_ratio_columns_preserved(self, tmp_path, monkeypatch):
        import sqlite3

        from scripts.day13_bank_roce import run_bank_carveout

        from src.etl.database import init_schema

        db_path = tmp_path / "test.db"
        log_path = tmp_path / "ratio_edge_cases.log"
        monkeypatch.setenv("NIFTY100_DB_PATH", str(db_path))

        # Build a minimal schema with the columns we need.
        init_schema(str(db_path))
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO companies (id, company_name, roce_percentage, roe_percentage) "
                "VALUES (?, ?, ?, ?)",
                ("TCS", "Tata Consultancy Services", 59.30, 30.47),
            )
            conn.execute(
                "INSERT INTO sectors (company_id, broad_sector) VALUES (?, ?)",
                ("TCS", "Information Technology"),
            )
            conn.execute(
                "INSERT INTO profitandloss (company_id, year, sales, expenses, "
                "operating_profit, opm_percentage, other_income, interest, depreciation, "
                "profit_before_tax, tax_percentage, net_profit, eps, dividend_payout) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "TCS",
                    "2024-03",
                    1000.0,
                    750.0,
                    250.0,
                    25.0,
                    10.0,
                    5.0,
                    20.0,
                    235.0,
                    25.0,
                    176.25,
                    50.0,
                    30.0,
                ),
            )
            conn.execute(
                "INSERT INTO balancesheet (company_id, year, equity_capital, reserves, "
                "borrowings, other_liabilities, total_liabilities, fixed_assets, "
                "investments, total_assets) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("TCS", "2024-03", 100.0, 400.0, 0.0, 100.0, 200.0, 200.0, 100.0, 600.0),
            )
            conn.execute(
                "INSERT INTO cashflow (company_id, year, operating_activity, "
                "investing_activity, financing_activity, net_cash_flow) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TCS", "2024-03", 200.0, -50.0, -100.0, 50.0),
            )
            # Pre-populate financial_ratios with non-trivial KPI values
            conn.execute(
                "INSERT INTO financial_ratios (company_id, year, net_profit_margin_pct, "
                "operating_profit_margin_pct, return_on_equity_pct, roce_pct, "
                "return_on_assets_pct, debt_to_equity, high_leverage_flag, "
                "interest_coverage, asset_turnover, free_cash_flow_cr, capex_cr, "
                "earnings_per_share, book_value_per_share, dividend_payout_ratio_pct, "
                "total_debt_cr, cash_from_operations_cr, composite_quality_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "TCS",
                    "2024-03",
                    17.625,
                    25.0,
                    35.25,
                    50.0,
                    29.375,
                    0.0,
                    52.0,
                    1.67,
                    150.0,
                    50.0,
                    50.0,
                    5.0,
                    30.0,
                    0.0,
                    200.0,
                    85.0,
                ),
            )
            conn.commit()

        # Run the Day-13 carve-out.
        n_anomalies, _ = run_bank_carveout(db_path=str(db_path), log_path=str(log_path))
        assert n_anomalies >= 1
        # The log should have been written to our tmp path, NOT to settings.OUTPUT_DIR.
        assert log_path.exists()
        assert "TCS" in log_path.read_text()

        # Verify Day-13 columns populated AND existing columns were NOT wiped.
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM financial_ratios WHERE company_id='TCS' AND year='2024-03'"
            ).fetchone()
        assert row is not None
        assert row["roce_source_value"] == pytest.approx(59.30)
        assert row["roe_source_value"] == pytest.approx(30.47)
        assert row["roce_anomaly_category"] is not None
        # Existing KPI values must survive (regression guard)
        assert row["return_on_equity_pct"] == pytest.approx(35.25)
        assert row["roce_pct"] == pytest.approx(50.0)
        assert row["composite_quality_score"] == pytest.approx(85.0)
        assert row["net_profit_margin_pct"] == pytest.approx(17.625)
