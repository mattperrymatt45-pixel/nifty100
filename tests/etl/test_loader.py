"""Unit tests for src.etl.loader (Day 41 — 10 tests).

Verify the loader reads each of the Screener.in Excel datasets without
error and exposes the expected columns / normalised id fields.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.etl.loader import DATASET_SPECS, available_datasets, load_dataset
from src.utils.config import settings


def _load(name: str) -> pd.DataFrame:
    return load_dataset(name, data_dir=settings.PROJECT_ROOT)


# -- 1. Twelve datasets registered in the spec registry -------------------
def test_twelve_datasets_registered() -> None:
    """DATASET_SPECS enumerates the 12 spec datasets (7 core + 5 supp)."""
    assert len(DATASET_SPECS) == 12
    expected = {
        "companies",
        "profitandloss",
        "balancesheet",
        "cashflow",
        "analysis",
        "documents",
        "prosandcons",
        "sectors",
        "stock_prices",
        "market_cap",
        "financial_ratios",
        "peer_groups",
    }
    assert set(DATASET_SPECS.keys()) == expected
    assert available_datasets() == sorted(expected)


# -- 2. Core datasets load with the expected header row -------------------
@pytest.mark.parametrize(
    "name,expected_cols_subset",
    [
        ("companies", {"id", "company_name", "about_company", "face_value"}),
        ("profitandloss", {"company_id", "year", "sales", "operating_profit", "net_profit", "eps"}),
        (
            "balancesheet",
            {
                "company_id",
                "year",
                "equity_capital",
                "borrowings",
                "total_assets",
                "total_liabilities",
            },
        ),
        (
            "cashflow",
            {
                "company_id",
                "year",
                "operating_activity",
                "investing_activity",
                "financing_activity",
                "net_cash_flow",
            },
        ),
    ],
)
def test_core_datasets_columns(name: str, expected_cols_subset: set[str]) -> None:
    """Core (header=1) files expose the expected columns and normalised ids."""
    df = _load(name)
    missing = expected_cols_subset - set(df.columns)
    assert not missing, f"{name}: missing columns {missing}"
    assert len(df) > 0


# -- 3. Supplementary datasets load with header=0 -------------------------
@pytest.mark.parametrize(
    "name,expected_cols_subset",
    [
        ("sectors", {"company_id", "broad_sector", "sub_sector"}),
        ("stock_prices", {"company_id", "date", "close_price"}),
        ("market_cap", {"company_id", "market_cap_crore", "pe_ratio", "pb_ratio"}),
        ("financial_ratios", {"company_id", "return_on_equity_pct", "debt_to_equity"}),
        ("peer_groups", {"company_id", "peer_group_name", "is_benchmark"}),
    ],
)
def test_supplementary_datasets_columns(name: str, expected_cols_subset: set[str]) -> None:
    """Supplementary (header=0) files expose the expected columns."""
    df = _load(name)
    missing = expected_cols_subset - set(df.columns)
    assert not missing, f"{name}: missing columns {missing}"
    assert len(df) > 0


# -- 4. Ticker column is uppercased after normalisation -------------------
def test_tickers_are_uppercased() -> None:
    """All normalised ticker columns should be uppercase."""
    for name, spec in DATASET_SPECS.items():
        if spec.normalize_id is None:
            continue
        df = _load(name)
        col = spec.normalize_id
        if col not in df.columns:
            continue
        for v in df[col].dropna().head(10):
            assert (
                str(v) == str(v).upper()
            ), f"{name}.{col}: ticker {v!r} not normalised to uppercase"


# -- 5. Year columns in time-series tables are YYYY-MM --------------------
def test_time_series_years_normalised() -> None:
    """Time-series datasets have years in YYYY-MM canonical form."""
    import re

    yr_pat = re.compile(r"^\d{4}-\d{2}$")
    for name in ("profitandloss", "balancesheet", "cashflow", "financial_ratios"):
        df = _load(name)
        bad = [y for y in df["year"].dropna().unique() if not yr_pat.match(str(y))]
        assert not bad, f"{name}: un-normalised years: {bad[:5]}"


# -- 6. Companies uses 'id' as the ticker column --------------------------
def test_companies_uses_id_column() -> None:
    spec = DATASET_SPECS["companies"]
    assert spec.normalize_id == "id"
    df = _load("companies")
    assert "id" in df.columns
    # 92 companies loaded
    assert len(df) == 92


# -- 7. Documents has Year (calendar int) not YYYY-MM ---------------------
def test_documents_year_is_calendar_int() -> None:
    """documents.Year is a calendar-year INT (2019-2024), NOT normalised."""
    spec = DATASET_SPECS["documents"]
    # normalise_year_col is None per spec
    assert spec.normalize_year_col is None
    df = _load("documents")
    assert "Year" in df.columns
    assert "Annual_Report" in df.columns
    assert len(df) > 100


# -- 8. Companies dataframe has all 92 tickers ----------------------------
def test_companies_has_ninety_two_tickers() -> None:
    df = _load("companies")
    assert df["id"].nunique() == 92


# -- 9. Sectors maps every company ---------------------------------------
def test_sectors_covers_all_companies() -> None:
    companies = _load("companies")
    sectors = _load("sectors")
    comp_ids = set(companies["id"].astype(str))
    sec_ids = set(sectors["company_id"].astype(str))
    assert comp_ids == sec_ids, (
        f"Sectors missing companies: {comp_ids - sec_ids}; " f"extra: {sec_ids - comp_ids}"
    )


# -- 10. Empty rows/cols are dropped, column headers stripped -------------
def test_columns_have_no_leading_trailing_whitespace() -> None:
    """Column headers are stripped of whitespace by load_excel."""
    for name in DATASET_SPECS:
        df = _load(name)
        for c in df.columns:
            assert c == c.strip(), f"{name}: column {c!r} has surrounding whitespace"
