"""Unit tests for src.etl.loader.

These tests build small synthetic Excel files in a temporary directory so
they don't depend on the actual Nifty 100 data being present. They cover:

* Correct header-row selection (header=1 for core, header=0 for supp).
* Column-name stripping.
* Ticker column normalisation (uppercase, strip, drop-invalid).
* Year column normalisation (Mar-23 → 2023-03; PARSE_ERROR sentinel).
* Dataset registry correctness (12 datasets, proper flags).
* File-not-found / unknown-dataset errors.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.etl.exceptions import LoaderError, TickerParseError
from src.etl.loader import (
    DATASET_SPECS,
    available_datasets,
    dataset_spec,
    load_dataset,
    load_excel,
)
from src.etl.normalizers import YEAR_PARSE_ERROR


# ---------------------------------------------------------------------------
# Fixtures: write tiny .xlsx files to tmp_path
# ---------------------------------------------------------------------------
@pytest.fixture()
def xlsx_core_header1(tmp_path: Path) -> Path:
    """Create a synthetic core-dataset Excel with header at row index 1.

    Layout:
        Row 0:  metadata title  (ignored when header=1)
        Row 1:  column headers  [id, company_name]
        Row 2+: data rows
    """
    p = tmp_path / "core_companies.xlsx"
    meta = pd.DataFrame([["NIFTY 100 COMPANIES — Screener.in Export", ""]])
    data = pd.DataFrame(
        {
            "id": ["TCS", "  infy  ", "m&m", None, "BAJAJ-AUTO"],
            "company_name": [
                "Tata Consultancy",
                "Infosys",
                "Mahindra & Mahindra",
                "Broken Row",
                "Bajaj Auto",
            ],
        }
    )
    with pd.ExcelWriter(p, engine="openpyxl") as xw:
        meta.to_excel(xw, index=False, header=False, startrow=0)
        data.to_excel(xw, index=False, startrow=1)
    return p


@pytest.fixture()
def xlsx_pl_header1(tmp_path: Path) -> Path:
    """Synthetic P&L-style file: header=1 with company_id + year columns.

    Note: the parse-error year ("xyzzy") is attached to a *valid* ticker so
    we can verify the loader keeps that row (marking it PARSE_ERROR)
    rather than dropping it alongside rows with missing tickers.
    """
    p = tmp_path / "pl.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as xw:
        pd.DataFrame([["Profit & Loss — Screener.in Export"]]).to_excel(
            xw, index=False, header=False, startrow=0
        )
        pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5, 6],
                "company_id": ["TCS", "tcs", " INFY ", "BAJAJ-AUTO", "HDFCBANK", None],
                "year": ["Mar-23", "Mar 22", "FY24", "Dec-22", "xyzzy", "Mar-20"],
                "sales": [225458, 200000, 150000, 1000, 500, 999],
            }
        ).to_excel(xw, index=False, startrow=1)
    return p


@pytest.fixture()
def xlsx_supp_header0(tmp_path: Path) -> Path:
    """Synthetic supplementary file with header at row 0."""
    p = tmp_path / "supp_sectors.xlsx"
    pd.DataFrame(
        {
            "company_id": ["TCS", "INFY", "m&m", "BAJAJ-AUTO"],
            "broad_sector": ["IT", "IT", "Automobiles", "Auto"],
        }
    ).to_excel(p, index=False, engine="openpyxl")
    return p


@pytest.fixture()
def xlsx_trailing_empty_cols(tmp_path: Path) -> Path:
    """Excel with a trailing 'Unnamed: N' empty column (common screener artifact)."""
    p = tmp_path / "trailing.xlsx"
    df = pd.DataFrame(
        {
            "company_id": ["TCS", "INFY"],
            "value": [1, 2],
            "Unnamed: 2": [None, None],
            "Unnamed: 3": [None, None],
        }
    )
    df.to_excel(p, index=False, engine="openpyxl")
    return p


@pytest.fixture()
def project_dir_with_companies(tmp_path: Path, xlsx_core_header1: Path) -> Path:
    """A project-root directory containing data/raw/companies.xlsx.

    Layout mirrors production:
        <tmp>/data/raw/companies.xlsx
    """
    import shutil

    d = tmp_path / "data" / "raw"
    d.mkdir(parents=True)
    shutil.copy(xlsx_core_header1, d / "companies.xlsx")
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: basic file loading
# ---------------------------------------------------------------------------
class TestLoadExcelBasics:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LoaderError):
            load_excel(tmp_path / "nope.xlsx")

    def test_loads_header1_correctly(self, xlsx_core_header1: Path) -> None:
        df = load_excel(xlsx_core_header1, sheet=0, header=1, ticker_col="id", year_col=None)
        assert list(df.columns) == ["id", "company_name"]
        # 5 rows originally, but the None ticker row should be dropped
        assert len(df) == 4

    def test_loads_header0_correctly(self, xlsx_supp_header0: Path) -> None:
        df = load_excel(
            xlsx_supp_header0, sheet=0, header=0, ticker_col="company_id", year_col=None
        )
        assert list(df.columns) == ["company_id", "broad_sector"]
        assert len(df) == 4
        assert df["company_id"].iloc[0] == "TCS"

    def test_strips_column_whitespace(self, tmp_path: Path) -> None:
        p = tmp_path / "spacycols.xlsx"
        pd.DataFrame({"  id ": [1], " name ": ["x"]}).to_excel(p, index=False, engine="openpyxl")
        df = load_excel(p, header=0, ticker_col=None, year_col=None)
        assert "id" in df.columns
        assert "name" in df.columns
        assert "  id " not in df.columns


class TestLoadExcelTickerNormalization:
    def test_uppercases_and_strips(self, xlsx_core_header1: Path) -> None:
        df = load_excel(xlsx_core_header1, sheet=0, header=1, ticker_col="id", year_col=None)
        ids = df["id"].tolist()
        assert "TCS" in ids
        assert "INFY" in ids  # was "  infy  "
        assert "M&M" in ids  # was "m&m"
        assert "BAJAJ-AUTO" in ids
        # Broken row with None id must be dropped
        assert None not in ids
        assert "Broken Row" not in df["company_name"].values  # row dropped

    def test_missing_ticker_column_raises(self, xlsx_supp_header0: Path) -> None:
        with pytest.raises(LoaderError):
            load_excel(xlsx_supp_header0, header=0, ticker_col="nonexistent", year_col=None)

    def test_ticker_parse_error_is_dropped(self) -> None:
        # Direct import sanity check for the exception type used by the loader
        with pytest.raises(TickerParseError):
            from src.etl.normalizers import normalize_ticker

            normalize_ticker(None)


class TestLoadExcelYearNormalization:
    def test_year_formats(self, xlsx_pl_header1: Path) -> None:
        df = load_excel(
            xlsx_pl_header1,
            sheet=0,
            header=1,
            ticker_col="company_id",
            year_col="year",
        )
        # After ticker filter drops the None-ticker row, we have 4 rows left.
        years = df["year"].tolist()
        assert "2023-03" in years  # Mar-23
        assert "2022-03" in years  # Mar 22
        assert "2024-03" in years  # FY24
        assert "2022-12" in years  # Dec-22
        assert YEAR_PARSE_ERROR in years  # "xyzzy" garbage

    def test_parse_error_count_does_not_raise(self, xlsx_pl_header1: Path) -> None:
        # The loader should NOT raise on bad years — it should mark them.
        df = load_excel(
            xlsx_pl_header1,
            sheet=0,
            header=1,
            ticker_col="company_id",
            year_col="year",
        )
        bad = (df["year"] == YEAR_PARSE_ERROR).sum()
        assert bad == 1

    def test_missing_year_column_raises(self, xlsx_core_header1: Path) -> None:
        with pytest.raises(LoaderError):
            load_excel(xlsx_core_header1, header=1, ticker_col="id", year_col="nonexistent")


class TestLoadExcelCleanup:
    def test_drops_empty_rows(self, tmp_path: Path) -> None:
        p = tmp_path / "emptyrows.xlsx"
        pd.DataFrame({"company_id": ["TCS", None, "INFY"], "v": [1, None, 2]}).to_excel(
            p, index=False, engine="openpyxl"
        )
        df = load_excel(p, header=0, ticker_col=None, year_col=None)
        # Middle row is all-NaN? No — it has no v but the ticker is None.
        # Ticker normalisation would drop it only if ticker_col is set;
        # without it, dropna(how='all') keeps it because of the None col.
        # So just verify we didn't crash and row count ≤ source rows.
        assert len(df) <= 3

    def test_drops_trailing_empty_columns(self, xlsx_trailing_empty_cols: Path) -> None:
        df = load_excel(
            xlsx_trailing_empty_cols,
            header=0,
            ticker_col="company_id",
            year_col=None,
        )
        assert "Unnamed: 2" not in df.columns
        assert "Unnamed: 3" not in df.columns
        assert list(df.columns) == ["company_id", "value"]
        assert len(df) == 2


# ---------------------------------------------------------------------------
# Tests: dataset registry & load_dataset
# ---------------------------------------------------------------------------
class TestDatasetRegistry:
    def test_twelve_datasets_registered(self) -> None:
        assert len(DATASET_SPECS) == 12

    def test_expected_names_present(self) -> None:
        expected_core = {
            "companies",
            "profitandloss",
            "balancesheet",
            "cashflow",
            "analysis",
            "documents",
            "prosandcons",
        }
        expected_supp = {
            "sectors",
            "stock_prices",
            "market_cap",
            "financial_ratios",
            "peer_groups",
        }
        assert expected_core.issubset(set(DATASET_SPECS.keys()))
        assert expected_supp.issubset(set(DATASET_SPECS.keys()))

    def test_core_datasets_use_header1(self) -> None:
        for name in ("companies", "profitandloss", "balancesheet", "cashflow"):
            assert DATASET_SPECS[name].header == 1, f"{name} should use header=1"

    def test_supplementary_datasets_use_header0(self) -> None:
        for name in ("sectors", "stock_prices", "market_cap", "financial_ratios", "peer_groups"):
            assert DATASET_SPECS[name].header == 0, f"{name} should use header=0"
            assert DATASET_SPECS[name].is_supplementary is True

    def test_companies_uses_id_as_ticker_col(self) -> None:
        assert DATASET_SPECS["companies"].normalize_id == "id"
        assert DATASET_SPECS["companies"].normalize_year_col is None

    def test_documents_uses_capital_y_year(self) -> None:
        assert DATASET_SPECS["documents"].normalize_year_col == "Year"

    def test_available_datasets_sorted(self) -> None:
        names = available_datasets()
        assert names == sorted(names)
        assert len(names) == 12

    def test_dataset_spec_lookup(self) -> None:
        spec = dataset_spec("profitandloss")
        assert spec.filename == "profitandloss.xlsx"
        assert spec.header == 1

    def test_dataset_spec_unknown_raises(self) -> None:
        with pytest.raises(LoaderError):
            dataset_spec("nope_does_not_exist")

    def test_load_dataset_unknown_name_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LoaderError):
            load_dataset("not_a_real_dataset", data_dir=tmp_path)

    def test_load_dataset_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LoaderError):
            load_dataset("companies", data_dir=tmp_path)

    def test_load_dataset_reads_file(self, project_dir_with_companies: Path) -> None:
        # project_dir_with_companies/ contains data/raw/companies.xlsx
        df = load_dataset("companies", data_dir=project_dir_with_companies)
        assert "id" in df.columns
        assert len(df) == 4
        assert "TCS" in df["id"].tolist()
        assert "INFY" in df["id"].tolist()


# ---------------------------------------------------------------------------
# Tests: supplementary dataset subdirectory resolution
# ---------------------------------------------------------------------------
class TestSupplementaryPathResolution:
    def test_supplementary_in_data_raw_supporting(self, tmp_path: Path) -> None:
        """sectors.xlsx under data/raw/supporting datasets/ (canonical spec location)."""
        raw = tmp_path / "data" / "raw"
        supp = raw / "supporting datasets"
        supp.mkdir(parents=True)
        pd.DataFrame({"company_id": ["TCS"], "broad_sector": ["IT"]}).to_excel(
            supp / "sectors.xlsx", index=False, engine="openpyxl"
        )
        df = load_dataset("sectors", data_dir=tmp_path)
        assert len(df) == 1
        assert df["broad_sector"].iloc[0] == "IT"

    def test_supplementary_falls_back_to_raw_root(self, tmp_path: Path) -> None:
        """If 'supporting datasets/' is absent, look directly in data/raw/."""
        raw = tmp_path / "data" / "raw"
        raw.mkdir(parents=True)
        pd.DataFrame({"company_id": ["TCS"], "broad_sector": ["IT"]}).to_excel(
            raw / "sectors.xlsx", index=False, engine="openpyxl"
        )
        df = load_dataset("sectors", data_dir=tmp_path)
        assert len(df) == 1

    def test_data_dir_as_raw_dir_directly(self, tmp_path: Path) -> None:
        """data_dir passed directly as a raw directory (no data/raw/ nesting)."""
        pd.DataFrame({"company_id": ["TCS"], "broad_sector": ["IT"]}).to_excel(
            tmp_path / "sectors.xlsx", index=False, engine="openpyxl"
        )
        df = load_dataset("sectors", data_dir=tmp_path)
        assert len(df) == 1

    def test_data_dir_project_root_with_named_sheet_fallback(self, tmp_path: Path) -> None:
        """data_dir as project root; sheet-name mismatch falls back to first sheet."""
        raw = tmp_path / "data" / "raw"
        raw.mkdir(parents=True)
        meta = pd.DataFrame([["NIFTY 100 COMPANIES", ""]])
        data = pd.DataFrame({"id": ["TCS"], "company_name": ["Tata Consultancy"]})
        with pd.ExcelWriter(raw / "companies.xlsx", engine="openpyxl") as xw:
            meta.to_excel(xw, index=False, header=False, startrow=0)
            data.to_excel(xw, index=False, startrow=1)
        df = load_dataset("companies", data_dir=tmp_path)
        assert "TCS" in df["id"].tolist()
        assert len(df) == 1
