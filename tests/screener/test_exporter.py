"""Unit tests for the Sprint 3 Day 16 screener Excel exporter.

Covers:
    * DISPLAY_COLUMNS includes expected KPIs (>=20)
    * export_screener_to_excel writes a valid .xlsx file with correct sheet count
    * Summary sheet contains all six spec preset names and hit counts
    * Preset sheets contain required columns (rank, Ticker, Company, Quality Score,
      P/E, FCF Yield, Valuation bucket)
    * Column count matches (formatted headers + no duplicate columns)
    * export_single_result creates a workbook with exactly one data sheet
    * Illegal sheet-name characters are sanitised / fall back to short labels
    * fcf_yield_pct, valuation_bucket, YoY columns present in dataset & output
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.screener import (
    DISPLAY_COLUMNS,
    ExportResult,
    export_screener_to_excel,
    export_single_result,
    load_config,
    load_screener_dataset,
    run_screener,
)
from src.screener.engine import ScreenerResult
from src.screener.exporter import _safe_sheet_name

pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")


# ---------------------------------------------------------------------------
# Constants / column config
# ---------------------------------------------------------------------------
class TestDisplayColumns:
    def test_at_least_20_kpis_displayed(self) -> None:
        # Spec §3.5 requires 20+ KPIs displayed
        assert len(DISPLAY_COLUMNS) >= 20

    def test_core_identity_columns_present(self) -> None:
        for c in ("composite_rank", "company_id", "company_name", "broad_sector", "year"):
            assert c in DISPLAY_COLUMNS

    def test_core_valuation_columns_present(self) -> None:
        for c in ("pe_ratio", "pb_ratio", "ev_ebitda", "dividend_yield_pct", "market_cap_cr"):
            assert c in DISPLAY_COLUMNS

    def test_fcf_yield_and_valuation_bucket_present(self) -> None:
        """Day 16 additions: derived FCF yield and Cheap/Fair/Expensive bucket."""
        assert "fcf_yield_pct" in DISPLAY_COLUMNS
        assert "valuation_bucket" in DISPLAY_COLUMNS

    def test_no_duplicate_display_columns(self) -> None:
        assert len(DISPLAY_COLUMNS) == len(set(DISPLAY_COLUMNS))


# ---------------------------------------------------------------------------
# Sheet-name safety
# ---------------------------------------------------------------------------
class TestSheetNameSafety:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Quality Compounders", "Quality Compounders"),
            ("Mid/Small-Cap Growth", "Mid_Small-Cap Growth"),  # / -> _
            ("Sheet[With]Brackets", "Sheet_With_Brackets"),
        ],
    )
    def test_safe_sheet_name_substitutes_illegal_chars(self, name: str, expected: str) -> None:
        assert _safe_sheet_name(name) == expected

    def test_safe_sheet_name_truncates_to_31(self) -> None:
        long = "X" * 50
        assert len(_safe_sheet_name(long)) == 31


# ---------------------------------------------------------------------------
# Full export integration test against real DB
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _prod_db() -> str:
    """Return the absolute path to the production DB and reset env/settings
    to point at it. This defends against sibling module-scoped fixtures that
    mutate ``os.environ`` or the frozen ``settings`` singleton without
    restoring it cleanly (notably test_exploratory_queries._load_db_with_
    synthetic_data, which uses ``object.__setattr__`` on settings.DB_PATH).
    """
    import os
    from pathlib import Path

    from src.utils.config import settings

    prod_db = str(settings.PROJECT_ROOT / "db" / "nifty100.db")
    os.environ["NIFTY100_DB_PATH"] = prod_db
    object.__setattr__(settings, "DB_PATH", Path(prod_db))
    return prod_db


@pytest.fixture(scope="module")
def preset_results(cfg):
    db_path = _prod_db()
    out = {}
    for name, preset in cfg.presets.items():
        out[name] = run_screener(preset, config=cfg, db_path=db_path)
    return out


def test_dataset_has_valuation_columns() -> None:
    db_path = _prod_db()
    df = load_screener_dataset(db_path=db_path)
    assert "fcf_yield_pct" in df.columns
    assert "valuation_bucket" in df.columns
    assert "ev_cr" in df.columns
    assert "fcf_cagr_5yr" in df.columns
    # valuation_bucket should only contain our three buckets
    assert set(df["valuation_bucket"].dropna().unique()).issubset({"Cheap", "Fair", "Expensive"})


def test_export_all_presets_writes_file(tmp_path: Path, preset_results) -> None:
    out = tmp_path / "screener.xlsx"
    result = export_screener_to_excel(preset_results, out)
    assert out.exists()
    assert isinstance(result, ExportResult)
    # 1 summary + 6 preset sheets = 7
    assert len(result.sheets_written) == len(preset_results) + 1
    assert "Summary" in result.sheets_written
    assert result.total_rows == sum(r.rows_out for r in preset_results.values())


def test_export_workbook_structure(tmp_path: Path, cfg, preset_results) -> None:
    out = tmp_path / "screener.xlsx"
    export_screener_to_excel(preset_results, out)

    wb = load_workbook(out, data_only=True)
    # First sheet must be Summary
    assert wb.sheetnames[0] == "Summary"
    # Six preset sheets after
    assert len(wb.sheetnames) == 7

    # Check that all six spec presets appear as sheets (including the
    # "Debt-Free Blue Chip" label which fits, and "Growth Accelerator" etc.)
    for expected in (
        "Quality Compounder",
        "Value Pick",
        "Growth Accelerator",
        "Dividend Champion",
        "Debt-Free Blue Chip",
        "Turnaround Watch",
    ):
        assert expected in wb.sheetnames, f"missing sheet '{expected}'"

    # Check preset sheet headers contain "Company" and "Quality Score"
    for sheet_name in wb.sheetnames[1:]:
        ws = wb[sheet_name]
        # Row 1 is the title (preset label), Row 2 is the header row (we inserted title at top)
        header_cells = [c.value for c in ws[2]]
        # Friendly headers from HEADER_RENAMES
        assert "Rank" in header_cells
        assert "Ticker" in header_cells
        assert "Company" in header_cells
        assert "Quality Score" in header_cells
        assert "P/E" in header_cells
        assert "Valuation" in header_cells
        assert "FCF Yield (%)" in header_cells

    wb.close()


def test_summary_sheet_contains_preset_rows(tmp_path: Path, cfg, preset_results) -> None:
    out = tmp_path / "screener.xlsx"
    export_screener_to_excel(preset_results, out)
    wb = load_workbook(out, data_only=True)
    ws = wb["Summary"]
    # Read preset-name column (A) starting from header row (row 4 is first data row)
    preset_names_in_sheet = set()
    for row in ws.iter_rows(min_row=4, max_col=1, values_only=True):
        if row[0]:
            preset_names_in_sheet.add(row[0])
    for name in cfg.presets:
        assert name in preset_names_in_sheet, f"{name} missing from Summary sheet"
    wb.close()


def test_export_single_result_one_sheet(tmp_path: Path) -> None:
    db_path = _prod_db()
    df = load_screener_dataset(db_path=db_path)
    # Fake ScreenerResult for smoke test
    res = ScreenerResult(
        preset_name="custom",
        preset_label="Custom Test",
        rows_in=len(df),
        rows_out=len(df),
        filters_applied=[],
        df=df.head(5),
    )
    out = tmp_path / "single.xlsx"
    export_single_result(res, out)
    wb = load_workbook(out)
    # No summary sheet when include_summary=False — just the data sheet
    assert len(wb.sheetnames) == 1
    assert "Custom Test" in wb.sheetnames[0]
    wb.close()


def test_xlsx_file_is_readable_by_pandas(tmp_path: Path, preset_results) -> None:
    """Ensure the workbook isn't corrupted and each preset sheet is tabular."""
    out = tmp_path / "screener.xlsx"
    export_screener_to_excel(preset_results, out)
    # Sheet names other than Summary should read into a DataFrame
    xls = pd.ExcelFile(out)
    for sheet in xls.sheet_names:
        if sheet == "Summary":
            continue
        # Row 0 is title, row 1 is headers (since we inserted title row at top in ws.insert_rows)
        df = pd.read_excel(out, sheet_name=sheet, header=1)
        assert "Rank" in df.columns
        assert "Ticker" in df.columns
        assert len(df) >= 1  # at least header row — but our presets all return >=3 companies
    xls.close()
