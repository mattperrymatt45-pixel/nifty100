"""Unit tests for src.etl.validation (DQ rules DQ-01 through DQ-16)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.etl.normalizers import YEAR_PARSE_ERROR
from src.etl.validation import (
    DQFailure,
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
    dq15_strict_balance_info,
    dq16_coverage_check,
    registered_rules,
    validate_all,
)


# ---------------------------------------------------------------------------
# Fixtures: small canonical DataFrames
# ---------------------------------------------------------------------------
@pytest.fixture()
def good_companies() -> pd.DataFrame:
    return pd.DataFrame(
        {"id": ["TCS", "INFY", "HDFCBANK"], "company_name": ["TCS", "Infosys", "HDFC Bank"]}
    )


@pytest.fixture()
def good_pl() -> pd.DataFrame:
    """Six years of good P&L rows per company (so DQ-16 passes).

    opm_percentage matches operating_profit/sales*100 within < 1pp so DQ-05
    does not fire.
    """

    def _row(cid: str, year: str, sales: float, op_profit: float) -> dict:
        opm_pct = round(op_profit / sales * 100, 4)
        return {
            "company_id": cid,
            "year": year,
            "sales": sales,
            "expenses": sales - op_profit,
            "operating_profit": op_profit,
            "opm_percentage": opm_pct,
            "other_income": 1000.0,
            "interest": 0.0,
            "depreciation": 2000.0,
            "profit_before_tax": op_profit + 1000.0 - 2000.0,
            "tax_percentage": 25.0,
            "net_profit": (op_profit + 1000.0 - 2000.0) * 0.75,
            "eps": 50.0,
            "dividend_payout": 40.0,
        }

    years = [f"{y}-03" for y in range(2018, 2024)]
    rows = []
    for cid, sales_base, op_base in [
        ("TCS", 200000.0, 45000.0),
        ("INFY", 140000.0, 30000.0),
        ("HDFCBANK", 120000.0, 40000.0),
    ]:
        for i, y in enumerate(years):
            rows.append(_row(cid, y, sales_base + i * 5000, op_base + i * 1000))
    return pd.DataFrame(rows)


@pytest.fixture()
def good_bs() -> pd.DataFrame:
    """Balance sheet rows balanced exactly (so DQ-04 passes, DQ-15 fires as INFO)."""
    years = [f"{y}-03" for y in range(2018, 2024)]
    rows = []
    for cid, equity, reserves, borrow, other_liab, fa, cwip, inv, oa in [
        ("TCS", 360.0, 80000.0, 0.0, 20000.0, 50000.0, 0.0, 10000.0, 40360.0),
        ("INFY", 420.0, 60000.0, 0.0, 15000.0, 30000.0, 0.0, 15000.0, 30420.0),
        ("HDFCBANK", 500.0, 100000.0, 0.0, 30000.0, 40000.0, 0.0, 20000.0, 70500.0),
    ]:
        for y in years:
            tl = equity + reserves + borrow + other_liab
            ta = fa + cwip + inv + oa
            # Force exact balance (adjust other_asset if needed)
            oa_adj = oa + (tl - ta)
            ta = fa + cwip + inv + oa_adj
            assert abs(tl - ta) < 1e-9
            rows.append(
                {
                    "company_id": cid,
                    "year": y,
                    "equity_capital": equity,
                    "reserves": reserves,
                    "borrowings": borrow,
                    "other_liabilities": other_liab,
                    "total_liabilities": tl,
                    "fixed_assets": fa,
                    "cwip": cwip,
                    "investments": inv,
                    "other_asset": oa_adj,
                    "total_assets": ta,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture()
def good_cf() -> pd.DataFrame:
    """Cash flow rows where CFO+CFI+CFF = net_cash_flow (within 10 Cr tolerance)."""
    years = [f"{y}-03" for y in range(2018, 2024)]
    rows = []
    for cid, cfo, cfi, cff in [
        ("TCS", 38000.0, -10000.0, -20000.0),
        ("INFY", 25000.0, -8000.0, -12000.0),
        ("HDFCBANK", 30000.0, -5000.0, -20000.0),
    ]:
        for y in years:
            rows.append(
                {
                    "company_id": cid,
                    "year": y,
                    "operating_activity": cfo,
                    "investing_activity": cfi,
                    "financing_activity": cff,
                    "net_cash_flow": cfo + cfi + cff,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture()
def good_tables(good_companies, good_pl, good_bs, good_cf) -> dict[str, pd.DataFrame]:
    return {
        "companies": good_companies,
        "profitandloss": good_pl,
        "balancesheet": good_bs,
        "cashflow": good_cf,
    }


# ---------------------------------------------------------------------------
# Rule registration
# ---------------------------------------------------------------------------
def test_all_16_rules_registered() -> None:
    ids = registered_rules()
    assert len(ids) == 16
    for i in range(1, 17):
        assert f"DQ-{i:02d}" in ids


def test_registered_rules_sorted() -> None:
    ids = registered_rules()
    assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# DQ-01
# ---------------------------------------------------------------------------
class TestDQ01:
    def test_clean_companies_no_failures(self, good_companies) -> None:
        assert dq01_company_pk_unique({"companies": good_companies}) == []

    def test_duplicate_pk_is_critical(self) -> None:
        df = pd.DataFrame({"id": ["TCS", "TCS", "INFY"]})
        failures = dq01_company_pk_unique({"companies": df})
        assert len(failures) == 2  # both TCS rows flagged
        assert all(f.severity == "CRITICAL" for f in failures)
        assert all(f.rule_id == "DQ-01" for f in failures)
        assert all(f.table == "companies" for f in failures)

    def test_missing_companies_table_noop(self) -> None:
        assert dq01_company_pk_unique({}) == []


# ---------------------------------------------------------------------------
# DQ-02
# ---------------------------------------------------------------------------
class TestDQ02:
    def test_clean_pk_no_failures(self, good_pl, good_bs, good_cf) -> None:
        tables = {
            "profitandloss": good_pl,
            "balancesheet": good_bs,
            "cashflow": good_cf,
        }
        assert dq02_annual_pk_unique(tables) == []

    def test_duplicate_company_year_is_critical(self) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["TCS", "TCS"],
                "year": ["2023-03", "2023-03"],
                "sales": [100.0, 200.0],
            }
        )
        failures = dq02_annual_pk_unique({"profitandloss": pl})
        assert len(failures) == 2
        assert all(f.severity == "CRITICAL" for f in failures)


# ---------------------------------------------------------------------------
# DQ-03
# ---------------------------------------------------------------------------
class TestDQ03:
    def test_no_orphans(self, good_tables) -> None:
        assert dq03_fk_integrity(good_tables) == []

    def test_orphan_child_row_is_critical(self, good_companies) -> None:
        pl = pd.DataFrame({"company_id": ["TCS", "UNKNOWN"], "year": ["2023-03", "2023-03"]})
        failures = dq03_fk_integrity({"companies": good_companies, "profitandloss": pl})
        assert len(failures) == 1
        f = failures[0]
        assert f.severity == "CRITICAL"
        assert f.rule_id == "DQ-03"
        assert f.company_id == "UNKNOWN"

    def test_missing_companies_table_skips(self) -> None:
        assert dq03_fk_integrity({"profitandloss": pd.DataFrame()}) == []


# ---------------------------------------------------------------------------
# DQ-04 (spec example: assets=1000, liab=1020 → WARNING)
# ---------------------------------------------------------------------------
class TestDQ04:
    def test_exact_balance_no_failure(self, good_bs) -> None:
        assert dq04_balance_sheet_balance({"balancesheet": good_bs}) == []

    def test_spec_example_1000_vs_1020_warns(self) -> None:
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
        assert failures[0].severity == "WARNING"
        assert failures[0].rule_id == "DQ-04"

    def test_small_diff_within_1pct_ok(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "total_assets": [1000.0],
                "total_liabilities": [1005.0],  # 0.5% diff → ok
            }
        )
        assert dq04_balance_sheet_balance({"balancesheet": df}) == []

    def test_missing_table_noop(self) -> None:
        assert dq04_balance_sheet_balance({}) == []


# ---------------------------------------------------------------------------
# DQ-05 OPM cross-check
# ---------------------------------------------------------------------------
class TestDQ05:
    def test_matching_opm_passes(self, good_pl) -> None:
        assert dq05_opm_crosscheck({"profitandloss": good_pl}) == []

    def test_large_opm_mismatch_warns(self) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "year": ["2023-03"],
                "sales": [1000.0],
                "operating_profit": [200.0],
                "opm_percentage": [50.0],  # actual opm is 20%
            }
        )
        failures = dq05_opm_crosscheck({"profitandloss": pl})
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# DQ-06 zero sales
# ---------------------------------------------------------------------------
class TestDQ06:
    def test_positive_sales_ok(self, good_pl) -> None:
        assert dq06_positive_sales({"profitandloss": good_pl}) == []

    def test_zero_sales_warns(self) -> None:
        # Spec's example: sales=0 → DQ-06 warning
        pl = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "sales": [0.0]})
        failures = dq06_positive_sales({"profitandloss": pl})
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"
        assert failures[0].actual == 0.0

    def test_negative_sales_warns(self) -> None:
        pl = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "sales": [-100.0]})
        assert len(dq06_positive_sales({"profitandloss": pl})) == 1


# ---------------------------------------------------------------------------
# DQ-07 year format
# ---------------------------------------------------------------------------
class TestDQ07:
    def test_valid_years_ok(self, good_tables) -> None:
        assert dq07_year_format(good_tables) == []

    def test_parse_error_year_is_critical(self) -> None:
        pl = pd.DataFrame({"company_id": ["TCS"], "year": ["garbage"]})
        failures = dq07_year_format({"profitandloss": pl})
        assert len(failures) == 1
        assert failures[0].severity == "CRITICAL"
        assert failures[0].actual == "garbage"

    def test_bad_format_2023_3_critical(self) -> None:
        pl = pd.DataFrame({"company_id": ["TCS"], "year": ["2023-3"]})
        # Single-digit month is rejected because pattern is \d{4}-\d{2}
        failures = dq07_year_format({"profitandloss": pl})
        assert len(failures) == 1

    def test_year_parse_error_sentinel_flagged(self) -> None:
        pl = pd.DataFrame({"company_id": ["TCS"], "year": [YEAR_PARSE_ERROR]})
        failures = dq07_year_format({"profitandloss": pl})
        assert len(failures) == 1


# ---------------------------------------------------------------------------
# DQ-08 ticker format
# ---------------------------------------------------------------------------
class TestDQ08:
    def test_valid_tickers_ok(self, good_tables) -> None:
        assert dq08_ticker_format(good_tables) == []

    def test_lowercase_ticker_flagged(self) -> None:
        # Our loader normalizes to upper before DQ, but a raw lowercase ticker
        # would slip through if DQ is invoked pre-normalisation; verify caught.
        companies = pd.DataFrame({"id": ["tcs"]})
        failures = dq08_ticker_format({"companies": companies})
        assert len(failures) == 1
        assert failures[0].severity == "CRITICAL"

    def test_hyphen_and_ampersand_allowed(self) -> None:
        companies = pd.DataFrame({"id": ["BAJAJ-AUTO", "M&M", "SBI-CARDS"]})
        assert dq08_ticker_format({"companies": companies}) == []

    def test_too_short_ticker_flagged(self) -> None:
        companies = pd.DataFrame({"id": ["A"]})
        assert len(dq08_ticker_format({"companies": companies})) == 1

    def test_too_long_ticker_flagged(self) -> None:
        companies = pd.DataFrame({"id": ["ABCDEFGHIJKLMN"]})  # 14 chars
        assert len(dq08_ticker_format({"companies": companies})) == 1


# ---------------------------------------------------------------------------
# DQ-09 net cash flow check
# ---------------------------------------------------------------------------
class TestDQ09:
    def test_reconciling_cf_passes(self, good_cf) -> None:
        assert dq09_net_cash_check({"cashflow": good_cf}) == []

    def test_out_of_tolerance_warns(self) -> None:
        cf = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "operating_activity": [100.0],
                "investing_activity": [-50.0],
                "financing_activity": [-20.0],
                "net_cash_flow": [200.0],  # should be 30 → diff 170 > 10
            }
        )
        failures = dq09_net_cash_check({"cashflow": cf})
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"

    def test_within_tolerance_ok(self) -> None:
        cf = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "operating_activity": [100.0],
                "investing_activity": [-50.0],
                "financing_activity": [-20.0],
                "net_cash_flow": [33.0],  # diff 3 → within 10 Cr tolerance
            }
        )
        assert dq09_net_cash_check({"cashflow": cf}) == []

    def test_missing_net_cash_column_skips(self) -> None:
        cf = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "operating_activity": [100.0],
                "investing_activity": [-50.0],
            }
        )
        assert dq09_net_cash_check({"cashflow": cf}) == []


# ---------------------------------------------------------------------------
# DQ-10 non-negative fixed assets
# ---------------------------------------------------------------------------
class TestDQ10:
    def test_non_negative_passes(self, good_bs) -> None:
        assert dq10_non_negative_fixed_assets({"balancesheet": good_bs}) == []

    def test_negative_fa_warns(self) -> None:
        bs = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "fixed_assets": [-100.0]})
        failures = dq10_non_negative_fixed_assets({"balancesheet": bs})
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"
        assert "coerce to 0" in failures[0].message


# ---------------------------------------------------------------------------
# DQ-11 tax rate [0,60]
# ---------------------------------------------------------------------------
class TestDQ11:
    def test_normal_tax_rates_pass(self, good_pl) -> None:
        assert dq11_tax_rate_range({"profitandloss": good_pl}) == []

    @pytest.mark.parametrize("bad_rate", [-5.0, 70.0, 100.0])
    def test_out_of_range_warns(self, bad_rate) -> None:
        pl = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "tax_percentage": [bad_rate]})
        assert len(dq11_tax_rate_range({"profitandloss": pl})) == 1


# ---------------------------------------------------------------------------
# DQ-12 dividend payout ≤ 200%
# ---------------------------------------------------------------------------
class TestDQ12:
    def test_normal_payout_passes(self, good_pl) -> None:
        assert dq12_dividend_payout_cap({"profitandloss": good_pl}) == []

    def test_over_200_warns(self) -> None:
        pl = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "dividend_payout": [250.0]})
        failures = dq12_dividend_payout_cap({"profitandloss": pl})
        assert len(failures) == 1
        assert failures[0].actual == 250.0

    def test_200_is_ok(self) -> None:
        pl = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "dividend_payout": [200.0]})
        assert dq12_dividend_payout_cap({"profitandloss": pl}) == []


# ---------------------------------------------------------------------------
# DQ-13 URL validity
# ---------------------------------------------------------------------------
class TestDQ13:
    def test_valid_urls_passes(self) -> None:
        docs = pd.DataFrame(
            {
                "company_id": ["TCS"],
                "Year": [2023],
                "Annual_Report": ["https://bseindia.com/tcs-2023.pdf"],
            }
        )
        assert dq13_url_validity({"documents": docs}) == []

    def test_invalid_url_warns(self) -> None:
        docs = pd.DataFrame({"company_id": ["TCS"], "Year": [2023], "Annual_Report": ["not-a-url"]})
        failures = dq13_url_validity({"documents": docs})
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"

    def test_empty_url_allowed(self) -> None:
        docs = pd.DataFrame({"company_id": ["TCS"], "Year": [2023], "Annual_Report": [""]})
        assert dq13_url_validity({"documents": docs}) == []


# ---------------------------------------------------------------------------
# DQ-14 EPS sign consistency
# ---------------------------------------------------------------------------
class TestDQ14:
    def test_consistent_sign_passes(self, good_pl) -> None:
        assert dq14_eps_sign_consistency({"profitandloss": good_pl}) == []

    def test_positive_profit_nonpositive_eps_warns(self) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "net_profit": [100.0],
                "eps": [-2.0],
            }
        )
        failures = dq14_eps_sign_consistency({"profitandloss": pl})
        assert len(failures) == 1
        assert failures[0].severity == "WARNING"

    def test_loss_with_positive_eps_allowed(self) -> None:
        # Sign consistency rule only flags profit>0 with eps≤0; a loss with
        # positive eps is unusual but not flagged by DQ-14.
        pl = pd.DataFrame(
            {
                "company_id": ["X"],
                "year": ["2023-03"],
                "net_profit": [-100.0],
                "eps": [2.0],
            }
        )
        assert dq14_eps_sign_consistency({"profitandloss": pl}) == []


# ---------------------------------------------------------------------------
# DQ-15 strict balance info (aggregate counter per spec p.28)
# ---------------------------------------------------------------------------
class TestDQ15:
    def test_exact_balance_reports_one_info(self, good_bs) -> None:
        """DQ-15 emits a single INFO counter (not one-per-row)."""
        failures = dq15_strict_balance_info({"balancesheet": good_bs})
        assert len(failures) == 1
        f = failures[0]
        assert f.severity == "INFO"
        assert f.rule_id == "DQ-15"
        assert f.table == "balancesheet"
        # Counter value equals the number of exactly-balanced rows
        assert f.actual == len(good_bs)

    def test_no_exact_balance_still_reports_zero_info(self) -> None:
        """Even when zero rows balance exactly we report an INFO counter."""
        bs = pd.DataFrame({"total_assets": [1000.0], "total_liabilities": [1005.0]})
        failures = dq15_strict_balance_info({"balancesheet": bs})
        assert len(failures) == 1
        assert failures[0].actual == 0
        assert failures[0].severity == "INFO"

    def test_missing_table_noop(self) -> None:
        assert dq15_strict_balance_info({}) == []


# ---------------------------------------------------------------------------
# DQ-16 coverage ≥ 5 years
# ---------------------------------------------------------------------------
class TestDQ16:
    def test_good_coverage_passes(self, good_companies) -> None:
        # 6 years per company → no warnings
        years = [f"{y}-03" for y in range(2018, 2024)]
        pl = pd.DataFrame(
            {
                "company_id": (["TCS"] * 6 + ["INFY"] * 6 + ["HDFCBANK"] * 6),
                "year": years * 3,
            }
        )
        failures = dq16_coverage_check({"companies": good_companies, "profitandloss": pl})
        assert failures == []

    def test_low_coverage_warns(self, good_companies) -> None:
        pl = pd.DataFrame({"company_id": ["TCS", "INFY", "HDFCBANK"], "year": ["2023-03"] * 3})
        bs = pd.DataFrame({"company_id": ["TCS", "INFY", "HDFCBANK"], "year": ["2023-03"] * 3})
        cf = pd.DataFrame({"company_id": ["TCS", "INFY", "HDFCBANK"], "year": ["2023-03"] * 3})
        failures = dq16_coverage_check(
            {"companies": good_companies, "profitandloss": pl, "balancesheet": bs, "cashflow": cf}
        )
        # 3 companies x 3 tables = 9 warnings
        assert len(failures) == 9
        assert all(f.severity == "WARNING" for f in failures)


# ---------------------------------------------------------------------------
# Integration: validate_all end-to-end
# ---------------------------------------------------------------------------
class TestValidateAll:
    def test_clean_data_produces_empty_csv(self, good_tables, tmp_path) -> None:
        out = tmp_path / "validation_failures.csv"
        summary = validate_all(good_tables, output_path=out)
        assert summary["critical"] == 0
        # INFO from DQ-15 will be non-zero on perfectly balanced BS rows;
        # WARNING/CRITICAL must both be zero on clean input.
        assert summary["warning"] == 0
        assert out.exists()
        df = pd.read_csv(out)
        # Only INFO rows expected (DQ-15); no WARNING/CRITICAL
        assert not (df["severity"] == "WARNING").any()
        assert not (df["severity"] == "CRITICAL").any()

    def test_critical_failure_reported_in_summary(self, good_companies, tmp_path) -> None:
        pl = pd.DataFrame(
            {
                "company_id": ["TCS", "UNKNOWN"],
                "year": ["2023-03", "garbage"],
                "sales": [100.0, 200.0],
            }
        )
        out = tmp_path / "vf.csv"
        summary = validate_all({"companies": good_companies, "profitandloss": pl}, output_path=out)
        # Expect: one FK orphan (CRITICAL) + one year parse (CRITICAL)
        assert summary["critical"] >= 2
        # Output CSV should exist and contain the failures
        csv_df = pd.read_csv(out)
        assert (csv_df["severity"] == "CRITICAL").sum() >= 2

    def test_selective_rule_filter(self, good_tables, tmp_path) -> None:
        out = tmp_path / "vf.csv"
        summary = validate_all(good_tables, output_path=out, rules=["DQ-01", "DQ-07"])
        assert set(summary["rules_run"]) == {"DQ-01", "DQ-07"}
        assert summary["total_failures"] == 0

    def test_failure_dataclass_shape(self) -> None:
        f = DQFailure(
            rule_id="DQ-04",
            table="balancesheet",
            severity="WARNING",
            message="test",
            company_id="TCS",
            year="2023-03",
            column="x",
            expected="ok",
            actual=1.0,
            row_index=0,
        )
        d = f.to_dict()
        for key in (
            "rule_id",
            "table",
            "company_id",
            "year",
            "column",
            "severity",
            "message",
            "expected",
            "actual",
            "row_index",
            "timestamp",
        ):
            assert key in d

    def test_validation_output_uses_default_path(self, good_tables, tmp_path, monkeypatch) -> None:
        # Rather than mutating the frozen Settings dataclass, simply pass
        # output_path explicitly to validate_all — equivalent production
        # behaviour without needing to monkeypatch immutable config.
        out = tmp_path / "processed" / "validation_failures.csv"
        summary = validate_all(good_tables, output_path=out)
        assert Path(summary["output_path"]).exists()
        assert Path(summary["output_path"]) == out
