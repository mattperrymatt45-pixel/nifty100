"""Sprint 5 Day 29 — Tests for the Analysis text parser."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.nlp import parser as p
from src.nlp.parser import (
    PARSE_REGEX,
    AnalysisParseResult,
    cross_validate_parsed,
    load_analysis_workbook,
    parse_analysis_text,
    run_parser,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_PATH = PROJECT_ROOT / "data" / "raw" / "analysis.xlsx"
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


# ---------------------------------------------------------------------------
# Regex primitives
# ---------------------------------------------------------------------------
class TestRegexPrimitive:
    def test_standard_format_with_colon(self) -> None:
        assert parse_analysis_text("10 Years: 21%") == [(10, 21.0)]

    def test_standard_format_five_year(self) -> None:
        assert parse_analysis_text("5 Years: 16.3%") == [(5, 16.3)]

    def test_decimal_value(self) -> None:
        assert parse_analysis_text("10 Years: 5.3%") == [(10, 5.3)]

    def test_no_colon(self) -> None:
        """Regex must accept optional colon: ``10 Years 21%``."""
        assert parse_analysis_text("10 Years 21%") == [(10, 21.0)]

    def test_year_singular(self) -> None:
        assert parse_analysis_text("1 Year: 7%") == [(1, 7.0)]

    def test_case_insensitive(self) -> None:
        assert parse_analysis_text("10 years: 21%") == [(10, 21.0)]

    def test_extra_whitespace(self) -> None:
        assert parse_analysis_text("  10  Years  :   21.0%  ") == [(10, 21.0)]

    def test_empty_string_returns_empty(self) -> None:
        assert parse_analysis_text("") == []
        assert parse_analysis_text(None) == []

    def test_no_match_returns_empty(self) -> None:
        assert parse_analysis_text("not a valid metric") == []

    def test_multiple_matches_in_one_cell(self) -> None:
        txt = "5 Years: 12% 10 Years: 18%"
        out = parse_analysis_text(txt)
        assert (5, 12.0) in out
        assert (10, 18.0) in out
        assert len(out) == 2

    def test_regex_attribute_exists(self) -> None:
        """PARSE_REGEX must be a compiled pattern with groups 'years' and 'value'."""
        m = PARSE_REGEX.search("10 Years: 21%")
        assert m is not None
        assert m.group("years") == "10"
        assert m.group("value") == "21"


# ---------------------------------------------------------------------------
# Workbook loading
# ---------------------------------------------------------------------------
class TestWorkbookLoad:
    def test_load_returns_expected_columns(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        for col in ("id", "company_id", *p.METRIC_COLUMNS):
            assert col in df.columns

    def test_workbook_has_rows(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        assert len(df) >= 20  # shipped sample has 20 rows
        assert df["company_id"].notna().sum() >= 20

    def test_metric_columns_are_string_type(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        for col in p.METRIC_COLUMNS:
            # After astype('string') cells should be str or <NA>, not float.
            assert df[col].dtype == "string" or df[col].dtype == object


# ---------------------------------------------------------------------------
# Full parse result
# ---------------------------------------------------------------------------
class TestFullParse:
    def test_full_parse_on_shipped_workbook(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        parsed, failures = p._parse_frame(df)
        # Shipped file is cleanly formatted — 20 rows x 4 metric cols = 80 matches expected.
        assert len(parsed) == 80
        assert len(failures) == 0

    def test_parsed_columns(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        parsed, _ = p._parse_frame(df)
        expected_cols = {
            "company_id",
            "metric_type",
            "source_column",
            "period_years",
            "value_pct",
            "source_value",
        }
        assert expected_cols.issubset(parsed.columns)

    def test_parsed_metric_types_match_mapping(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        parsed, _ = p._parse_frame(df)
        allowed = {m.metric_type for m in p.RATIO_MAPPINGS.values()}
        assert set(parsed["metric_type"]).issubset(allowed)

    def test_period_years_are_integers(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        parsed, _ = p._parse_frame(df)
        for v in parsed["period_years"]:
            assert isinstance(v, int)

    def test_unparseable_text_logged_as_failure(self) -> None:
        df = pd.DataFrame(
            {
                "id": [1],
                "company_id": ["FAKETICKER"],
                "compounded_sales_growth": pd.array(["garbage no number"], dtype="string"),
                "compounded_profit_growth": pd.array(["5 Years: 10.0%"], dtype="string"),
                "stock_price_cagr": pd.array([pd.NA], dtype="string"),
                "roe": pd.array(["10 Years: 15%"], dtype="string"),
            }
        )
        parsed, failures = p._parse_frame(df)
        # Should have 2 successes (profit_cagr, roe) and 2 failures (bad text + NA)
        assert len(parsed) == 2
        assert len(failures) == 2
        reasons = set(failures["reason"])
        assert "no_regex_match" in reasons
        assert "empty_cell" in reasons


# ---------------------------------------------------------------------------
# Cross-validation
# ---------------------------------------------------------------------------
class TestCrossValidation:
    def test_cross_validate_returns_divergences_only(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        parsed, _ = p._parse_frame(df)
        div = cross_validate_parsed(parsed, DB_PATH, threshold_pct=5.0)
        # Every divergence must have |delta| > 5 pp OR be a null/column-missing reason
        for _, r in div.iterrows():
            if r["reason"] == "divergence_gt_threshold":
                assert abs(r["delta_pct"]) > 5.0

    def test_cross_validate_columns(self) -> None:
        df = load_analysis_workbook(ANALYSIS_PATH)
        parsed, _ = p._parse_frame(df)
        div = cross_validate_parsed(parsed, DB_PATH, threshold_pct=5.0)
        required = {
            "company_id",
            "metric_type",
            "period_years",
            "parsed_value_pct",
            "ratio_value_pct",
            "delta_pct",
            "ratio_column",
            "reason",
        }
        assert required.issubset(div.columns)

    def test_stock_cagr_not_included_in_divergences(self) -> None:
        """Stock-price CAGR has no DB column — must be skipped (not in divergences)."""
        df = load_analysis_workbook(ANALYSIS_PATH)
        parsed, _ = p._parse_frame(df)
        div = cross_validate_parsed(parsed, DB_PATH, threshold_pct=5.0)
        assert (div["metric_type"] == "stock_cagr").sum() == 0

    def test_synthetic_perfect_match_no_divergence(self, tmp_path: Path) -> None:
        # Build a tiny SQLite DB with a known value, confirm no divergence when match is exact
        db = tmp_path / "tiny.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE financial_ratios (company_id TEXT, year TEXT, "
            "revenue_cagr_10yr REAL, pat_cagr_5yr REAL, return_on_equity_pct REAL)"
        )
        conn.execute("INSERT INTO financial_ratios VALUES ('TESTCO','2024-03',21.0,15.0,18.0)")
        conn.commit()
        conn.close()

        parsed = pd.DataFrame(
            [
                {
                    "company_id": "TESTCO",
                    "metric_type": "sales_cagr",
                    "period_years": 10,
                    "value_pct": 21.0,
                },
                {
                    "company_id": "TESTCO",
                    "metric_type": "profit_cagr",
                    "period_years": 5,
                    "value_pct": 15.0,
                },
                {
                    "company_id": "TESTCO",
                    "metric_type": "roe_avg",
                    "period_years": 10,
                    "value_pct": 18.0,
                },
            ]
        )
        div = cross_validate_parsed(parsed, db, threshold_pct=5.0)
        assert len(div) == 0

    def test_synthetic_divergence_flagged(self, tmp_path: Path) -> None:
        db = tmp_path / "tiny.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE financial_ratios (company_id TEXT, year TEXT, revenue_cagr_10yr REAL)"
        )
        conn.execute("INSERT INTO financial_ratios VALUES ('TESTCO','2024-03',10.0)")
        conn.commit()
        conn.close()

        parsed = pd.DataFrame(
            [
                {
                    "company_id": "TESTCO",
                    "metric_type": "sales_cagr",
                    "period_years": 10,
                    "value_pct": 20.0,
                }
            ]
        )
        div = cross_validate_parsed(parsed, db, threshold_pct=5.0)
        assert len(div) == 1
        assert div.iloc[0]["delta_pct"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# End-to-end run
# ---------------------------------------------------------------------------
class TestEndToEndRun:
    def test_run_parser_produces_csvs(self, tmp_path: Path) -> None:
        result = run_parser(
            analysis_path=ANALYSIS_PATH,
            db_path=DB_PATH,
            output_dir=tmp_path,
        )
        assert isinstance(result, AnalysisParseResult)
        assert result.parsed_csv.exists()
        assert result.failures_csv.exists()
        assert result.divergences_csv.exists()
        # Shipped file is clean
        assert result.failed_rows == 0
        assert result.match_rate_pct == 100.0
        assert result.matched_rows == 80
        assert result.total_rows == 80

    def test_output_csvs_readable(self, tmp_path: Path) -> None:
        result = run_parser(
            analysis_path=ANALYSIS_PATH,
            db_path=DB_PATH,
            output_dir=tmp_path,
        )
        p_csv = pd.read_csv(result.parsed_csv)
        f_csv = pd.read_csv(result.failures_csv)
        pd.read_csv(result.divergences_csv)  # divergences file must be readable
        assert len(p_csv) == result.matched_rows
        assert set(p_csv.columns) >= {
            "company_id",
            "metric_type",
            "period_years",
            "value_pct",
        }
        assert len(f_csv) == result.failed_rows
