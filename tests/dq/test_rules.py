"""Data-quality rule unit tests — Day 41 (14 tests).

Each test crafts a minimal DataFrame that violates exactly one DQ rule
(DQ-01 through DQ-14), runs that rule in isolation, and asserts the
correct ``rule_id`` and ``severity`` are returned.
"""

from __future__ import annotations

import pandas as pd

from src.etl.normalizers import YEAR_PARSE_ERROR
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


# --------------------------------------------------------------------------
# DQ-01: Company PK uniqueness (CRITICAL)
# --------------------------------------------------------------------------
class TestDQ01:
    def test_duplicate_company_id_flags_critical(self) -> None:
        companies = pd.DataFrame({"id": ["TCS", "TCS", "INFY"], "company_name": ["A", "A", "B"]})
        tables = {"companies": companies}
        failures = dq01_company_pk_unique(tables)
        assert len(failures) == 2  # both duplicate rows flagged
        for f in failures:
            assert f.rule_id == "DQ-01"
            assert f.severity == "CRITICAL"
            assert f.table == "companies"


# --------------------------------------------------------------------------
# DQ-02: Annual (company_id, year) PK uniqueness (CRITICAL)
# --------------------------------------------------------------------------
class TestDQ02:
    def test_duplicate_company_year_flags_critical(self) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["TCS", "TCS", "INFY"],
                "year": ["2023-03", "2023-03", "2023-03"],
                "sales": [100, 100, 200],
            }
        )
        tables = {"profitandloss": pl}
        failures = dq02_annual_pk_unique(tables)
        assert len(failures) == 2  # both TCS rows flagged
        for f in failures:
            assert f.rule_id == "DQ-02"
            assert f.severity == "CRITICAL"


# --------------------------------------------------------------------------
# DQ-03: FK integrity (CRITICAL)
# --------------------------------------------------------------------------
class TestDQ03:
    def test_orphan_company_id_flags_critical(self) -> None:
        companies = pd.DataFrame({"id": ["TCS", "INFY"]})
        pl = pd.DataFrame(
            {
                "company_id": ["TCS", "UNKNOWN"],
                "year": ["2023-03", "2023-03"],
                "sales": [100, 200],
            }
        )
        tables = {"companies": companies, "profitandloss": pl}
        failures = dq03_fk_integrity(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-03"
        assert f.severity == "CRITICAL"
        assert f.company_id == "UNKNOWN"


# --------------------------------------------------------------------------
# DQ-04: Balance sheet imbalance (WARNING)
# --------------------------------------------------------------------------
class TestDQ04:
    def test_imbalanced_bs_warns(self) -> None:
        bs = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "total_assets": [1000.0],
                "total_liabilities": [800.0],  # 20% off
            }
        )
        tables = {"balancesheet": bs}
        failures = dq04_balance_sheet_balance(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-04"
        assert f.severity == "WARNING"


# --------------------------------------------------------------------------
# DQ-05: OPM cross-check (WARNING)
# --------------------------------------------------------------------------
class TestDQ05:
    def test_opm_mismatch_warns(self) -> None:
        # reported OPM = 30%, but computed = 250/1000 = 25% → 5pp delta
        pl = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "sales": [1000.0],
                "operating_profit": [250.0],
                "opm_percentage": [30.0],
            }
        )
        tables = {"profitandloss": pl}
        failures = dq05_opm_crosscheck(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-05"
        assert f.severity == "WARNING"


# --------------------------------------------------------------------------
# DQ-06: Positive sales for non-banks (WARNING)
# --------------------------------------------------------------------------
class TestDQ06:
    def test_zero_sales_non_bank_warns(self) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "sales": [0.0],
            }
        )
        # No sectors table → financial_ids empty → zero sales flagged
        tables = {"profitandloss": pl}
        failures = dq06_positive_sales(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-06"
        assert f.severity == "WARNING"
        assert f.company_id == "TCS"


# --------------------------------------------------------------------------
# DQ-07: Year format (CRITICAL)
# --------------------------------------------------------------------------
class TestDQ07:
    def test_bad_year_flags_critical(self) -> None:
        """Both raw garbage and the YEAR_PARSE_ERROR sentinel must be flagged."""
        pl = pd.DataFrame(
            {
                "company_id": ["TCS", "INFY", "WIPRO"],
                "year": ["garbage", "2023-03", YEAR_PARSE_ERROR],
                "sales": [100, 200, 300],
            }
        )
        tables = {"profitandloss": pl}
        failures = dq07_year_format(tables)
        assert len(failures) == 2  # TCS + WIPRO
        for f in failures:
            assert f.rule_id == "DQ-07"
            assert f.severity == "CRITICAL"


# --------------------------------------------------------------------------
# DQ-08: Ticker format (CRITICAL)
# --------------------------------------------------------------------------
class TestDQ08:
    def test_bad_ticker_flags_critical(self) -> None:
        # Lowercase / invalid chars
        companies = pd.DataFrame({"id": ["bad ticker!!", "TCS"]})
        tables = {"companies": companies}
        failures = dq08_ticker_format(tables)
        assert any(f.rule_id == "DQ-08" for f in failures)
        crit = [f for f in failures if f.severity == "CRITICAL" and f.rule_id == "DQ-08"]
        assert len(crit) >= 1


# --------------------------------------------------------------------------
# DQ-09: Net cash flow cross-check (WARNING)
# --------------------------------------------------------------------------
class TestDQ09:
    def test_net_cash_mismatch_warns(self) -> None:
        cf = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "operating_activity": [100.0],
                "investing_activity": [-50.0],
                "financing_activity": [-20.0],
                "net_cash_flow": [100.0],  # should be 30 → mismatch
            }
        )
        tables = {"cashflow": cf}
        failures = dq09_net_cash_check(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-09"
        assert f.severity == "WARNING"


# --------------------------------------------------------------------------
# DQ-10: Non-negative fixed assets (WARNING)
# --------------------------------------------------------------------------
class TestDQ10:
    def test_negative_fixed_assets_warns(self) -> None:
        bs = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "fixed_assets": [-100.0],
            }
        )
        tables = {"balancesheet": bs}
        failures = dq10_non_negative_fixed_assets(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-10"
        assert f.severity == "WARNING"


# --------------------------------------------------------------------------
# DQ-11: Tax rate in [0, 60] (WARNING)
# --------------------------------------------------------------------------
class TestDQ11:
    def test_tax_rate_out_of_range_warns(self) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "sales": [1000.0],
                "tax_percentage": [75.0],  # > 60
            }
        )
        tables = {"profitandloss": pl}
        failures = dq11_tax_rate_range(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-11"
        assert f.severity == "WARNING"


# --------------------------------------------------------------------------
# DQ-12: Dividend payout ≤ 200% (WARNING)
# --------------------------------------------------------------------------
class TestDQ12:
    def test_excessive_dividend_payout_warns(self) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "sales": [1000.0],
                "dividend_payout": [250.0],  # > 200
            }
        )
        tables = {"profitandloss": pl}
        failures = dq12_dividend_payout_cap(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-12"
        assert f.severity == "WARNING"


# --------------------------------------------------------------------------
# DQ-13: URL validity for documents (WARNING)
# --------------------------------------------------------------------------
class TestDQ13:
    def test_invalid_url_warns(self) -> None:
        docs = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "Year": [2023],
                "Annual_Report": ["not-a-url"],
            }
        )
        tables = {"documents": docs}
        failures = dq13_url_validity(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-13"
        assert f.severity == "WARNING"


# --------------------------------------------------------------------------
# DQ-14: EPS sign consistency (WARNING)
# --------------------------------------------------------------------------
class TestDQ14:
    def test_profit_with_negative_eps_warns(self) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "sales": [1000.0],
                "net_profit": [150.0],  # profit
                "eps": [-5.0],  # but negative EPS
            }
        )
        tables = {"profitandloss": pl}
        failures = dq14_eps_sign_consistency(tables)
        assert len(failures) == 1
        f = failures[0]
        assert f.rule_id == "DQ-14"
        assert f.severity == "WARNING"
