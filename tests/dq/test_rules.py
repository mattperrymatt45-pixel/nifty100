"""Spec-mandated DQ rule unit tests (tests/dq/test_rules.py per spec §27).

Covers DQ-01 through DQ-14 (14 rules) — the unit-testable subset of the
16-rule validation engine. DQ-15 (strict-balance INFO counter) and
DQ-16 (coverage check) are integration-level rules exercised via the
full-ETL test suite rather than synthetic one-row fixtures here.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.etl.validation import (
    dq01_company_pk_unique,
    dq02_annual_pk_unique,
    dq03_fk_integrity,
    dq04_balance_sheet_balance,
    dq05_opm_crosscheck,
    dq06_positive_sales,
    dq07_year_format,
    dq08_ticker_format,
    dq09_net_cash_check,
    dq10_non_negative_fixed_assets,
    dq11_tax_rate_range,
    dq12_dividend_payout_cap,
    dq13_url_validity,
    dq14_eps_sign_consistency,
)


# ---------------------------------------------------------------------------
# DQ-01: Company PK uniqueness
# ---------------------------------------------------------------------------
class TestDQ01CompanyPKUnique:
    def test_no_duplicates_returns_empty(self) -> None:
        df = pd.DataFrame({"id": ["TCS", "INFY", "RELIANCE"]})
        assert dq01_company_pk_unique({"companies": df}) == []

    def test_duplicate_pk_flags_critical(self) -> None:
        df = pd.DataFrame({"id": ["TCS", "TCS"]})
        failures = dq01_company_pk_unique({"companies": df})
        assert len(failures) == 2
        assert all(f.rule_id == "DQ-01" and f.severity == "CRITICAL" for f in failures)


# ---------------------------------------------------------------------------
# DQ-02: Annual PK uniqueness
# ---------------------------------------------------------------------------
class TestDQ02AnnualPKUnique:
    def test_unique_pairs_pass(self) -> None:
        pl = pd.DataFrame({"company_id": ["TCS", "TCS"], "year": ["2022-03", "2023-03"]})
        assert dq02_annual_pk_unique({"profitandloss": pl}) == []

    def test_duplicate_pair_flags_critical(self) -> None:
        pl = pd.DataFrame({"company_id": ["TCS", "TCS"], "year": ["2023-03", "2023-03"]})
        failures = dq02_annual_pk_unique({"profitandloss": pl})
        assert len(failures) == 2
        assert all(f.rule_id == "DQ-02" and f.severity == "CRITICAL" for f in failures)


# ---------------------------------------------------------------------------
# DQ-03: FK integrity
# ---------------------------------------------------------------------------
class TestDQ03FKIntegrity:
    def test_valid_refs_pass(self) -> None:
        comp = pd.DataFrame({"id": ["TCS", "INFY"]})
        pl = pd.DataFrame({"company_id": ["TCS", "INFY"], "year": ["2023-03"] * 2})
        assert dq03_fk_integrity({"companies": comp, "profitandloss": pl}) == []

    def test_orphan_row_flags_critical(self) -> None:
        comp = pd.DataFrame({"id": ["TCS"]})
        pl = pd.DataFrame({"company_id": ["TCS", "GHOST"], "year": ["2023-03"] * 2})
        failures = dq03_fk_integrity({"companies": comp, "profitandloss": pl})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-03"
        assert failures[0].severity == "CRITICAL"
        assert failures[0].company_id == "GHOST"


# ---------------------------------------------------------------------------
# DQ-04: Balance sheet balance
# ---------------------------------------------------------------------------
class TestDQ04BalanceSheetBalance:
    def test_bs_balanced_passes(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "total_assets": [1000.0],
                "total_liabilities": [1005.0],
            }
        )
        assert dq04_balance_sheet_balance({"balancesheet": df}) == []

    def test_bs_imbalanced_warns(self) -> None:
        """Spec example: assets=1000, liab=1020 → DQ-04 WARNING triggered."""
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "total_assets": [1000.0],
                "total_liabilities": [1020.0],
            }
        )
        failures = dq04_balance_sheet_balance({"balancesheet": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-04"
        assert failures[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# DQ-05: OPM cross-check
# ---------------------------------------------------------------------------
class TestDQ05OPMCrosscheck:
    def test_opm_matches_passes(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "sales": [1000.0],
                "operating_profit": [200.0],
                "opm_percentage": [20.0],
            }
        )
        assert dq05_opm_crosscheck({"profitandloss": df}) == []

    def test_opm_mismatch_warns(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "sales": [1000.0],
                "operating_profit": [200.0],
                "opm_percentage": [25.0],  # reported 25 vs computed 20 → diff=5
            }
        )
        failures = dq05_opm_crosscheck({"profitandloss": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-05"
        assert failures[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# DQ-06: Positive sales
# ---------------------------------------------------------------------------
class TestDQ06PositiveSales:
    def test_positive_sales_passes(self) -> None:
        df = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "sales": [500.0]})
        assert dq06_positive_sales({"profitandloss": df}) == []

    def test_zero_sales_warns_non_bank(self) -> None:
        """Spec example: sales=0 → DQ-06 WARNING triggered."""
        df = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "sales": [0.0]})
        failures = dq06_positive_sales({"profitandloss": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-06"
        assert failures[0].severity == "WARNING"

    def test_bank_zero_sales_excluded(self) -> None:
        """Banks (financial sector) are NOT flagged for zero sales."""
        pl = pd.DataFrame({"company_id": ["HDFCBANK"], "year": ["2023-03"], "sales": [0.0]})
        sectors = pd.DataFrame({"company_id": ["HDFCBANK"], "broad_sector": ["Private Banks"]})
        assert dq06_positive_sales({"profitandloss": pl, "sectors": sectors}) == []

    def test_nbfc_zero_sales_excluded(self) -> None:
        """NBFCs (Finance sector) are NOT flagged for zero sales."""
        pl = pd.DataFrame({"company_id": ["BAJFINANCE"], "year": ["2023-03"], "sales": [0.0]})
        sectors = pd.DataFrame({"company_id": ["BAJFINANCE"], "broad_sector": ["Consumer Finance"]})
        assert dq06_positive_sales({"profitandloss": pl, "sectors": sectors}) == []

    def test_non_bank_zero_sales_flagged_with_sectors(self) -> None:
        pl = pd.DataFrame({"company_id": ["TCS"], "year": ["2023-03"], "sales": [0.0]})
        sectors = pd.DataFrame({"company_id": ["TCS"], "broad_sector": ["Information Technology"]})
        failures = dq06_positive_sales({"profitandloss": pl, "sectors": sectors})
        assert len(failures) == 1
        assert failures[0].company_id == "TCS"


# ---------------------------------------------------------------------------
# DQ-07: Year format
# ---------------------------------------------------------------------------
class TestDQ07YearFormat:
    def test_valid_year_passes(self) -> None:
        df = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"]})
        assert dq07_year_format({"profitandloss": df}) == []

    def test_bad_year_flags_critical(self) -> None:
        df = pd.DataFrame({"company_id": ["X"], "year": ["2023"]})
        failures = dq07_year_format({"profitandloss": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-07"
        assert failures[0].severity == "CRITICAL"


# ---------------------------------------------------------------------------
# DQ-08: Ticker format
# ---------------------------------------------------------------------------
class TestDQ08TickerFormat:
    @pytest.mark.parametrize("ticker", ["TCS", "INFY", "RELIANCE", "M&M", "BRITANNIA"])
    def test_valid_ticker_passes(self, ticker: str) -> None:
        df = pd.DataFrame({"id": [ticker]})
        assert dq08_ticker_format({"companies": df}) == []

    @pytest.mark.parametrize("ticker", ["lowercase", "bad ticker", "", "a"])
    def test_bad_ticker_flags_critical(self, ticker: str) -> None:
        df = pd.DataFrame({"id": [ticker]})
        failures = dq08_ticker_format({"companies": df})
        assert len(failures) >= 1
        assert all(f.severity == "CRITICAL" for f in failures)


# ---------------------------------------------------------------------------
# DQ-09: Net cash flow cross-check
# ---------------------------------------------------------------------------
class TestDQ09NetCashCheck:
    def test_cashflow_reconciles_passes(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "operating_activity": [100.0],
                "investing_activity": [-50.0],
                "financing_activity": [-20.0],
                "net_cash_flow": [30.0],
            }
        )
        assert dq09_net_cash_check({"cashflow": df}) == []

    def test_cashflow_mismatch_warns(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "operating_activity": [100.0],
                "investing_activity": [-50.0],
                "financing_activity": [-20.0],
                "net_cash_flow": [100.0],  # diff = 70 > 10
            }
        )
        failures = dq09_net_cash_check({"cashflow": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-09"
        assert failures[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# DQ-10: Non-negative fixed assets
# ---------------------------------------------------------------------------
class TestDQ10NonNegativeFixedAssets:
    def test_non_negative_passes(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "fixed_assets": [500.0],
            }
        )
        assert dq10_non_negative_fixed_assets({"balancesheet": df}) == []

    def test_negative_fa_warns(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "fixed_assets": [-50.0],
            }
        )
        failures = dq10_non_negative_fixed_assets({"balancesheet": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-10"
        assert failures[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# DQ-11: Tax rate range
# ---------------------------------------------------------------------------
class TestDQ11TaxRateRange:
    @pytest.mark.parametrize("rate", [0.0, 25.0, 30.0, 60.0])
    def test_valid_tax_passes(self, rate: float) -> None:
        df = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "tax_percentage": [rate]})
        assert dq11_tax_rate_range({"profitandloss": df}) == []

    @pytest.mark.parametrize("rate", [-5.0, 75.0])
    def test_invalid_tax_warns(self, rate: float) -> None:
        df = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "tax_percentage": [rate]})
        failures = dq11_tax_rate_range({"profitandloss": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-11"
        assert failures[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# DQ-12: Dividend payout cap
# ---------------------------------------------------------------------------
class TestDQ12DividendPayoutCap:
    @pytest.mark.parametrize("dp", [0.0, 50.0, 200.0])
    def test_reasonable_payout_passes(self, dp: float) -> None:
        df = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "dividend_payout": [dp]})
        assert dq12_dividend_payout_cap({"profitandloss": df}) == []

    def test_excessive_payout_warns(self) -> None:
        df = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "dividend_payout": [250.0]})
        failures = dq12_dividend_payout_cap({"profitandloss": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-12"
        assert failures[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# DQ-13: URL validity
# ---------------------------------------------------------------------------
class TestDQ13URLValidity:
    @pytest.mark.parametrize("url", ["https://example.com/ar.pdf", "http://x.y/z", "", None])
    def test_valid_url_passes(self, url: str | None) -> None:
        df = pd.DataFrame({"company_id": ["X"], "Year": ["2023"], "Annual_Report": [url]})
        assert dq13_url_validity({"documents": df}) == []

    def test_bad_url_warns(self) -> None:
        df = pd.DataFrame({"company_id": ["X"], "Year": ["2023"], "Annual_Report": ["not-a-url"]})
        failures = dq13_url_validity({"documents": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-13"
        assert failures[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# DQ-14: EPS sign consistency
# ---------------------------------------------------------------------------
class TestDQ14EPSSignConsistency:
    def test_consistent_sign_passes(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "net_profit": [100.0],
                "eps": [10.0],
            }
        )
        assert dq14_eps_sign_consistency({"profitandloss": df}) == []

    def test_loss_negative_eps_passes(self) -> None:
        """Loss with negative EPS is consistent."""
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "net_profit": [-50.0],
                "eps": [-5.0],
            }
        )
        assert dq14_eps_sign_consistency({"profitandloss": df}) == []

    def test_profit_negative_eps_warns(self) -> None:
        """PAT > 0 but EPS ≤ 0 → flag."""
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "net_profit": [100.0],
                "eps": [-1.0],
            }
        )
        failures = dq14_eps_sign_consistency({"profitandloss": df})
        assert len(failures) == 1
        assert failures[0].rule_id == "DQ-14"
        assert failures[0].severity == "WARNING"
