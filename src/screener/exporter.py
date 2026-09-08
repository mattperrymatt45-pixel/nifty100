"""Screener Excel exporter — Sprint 3 Day 16.

Writes the screener results to a formatted ``screener_output.xlsx`` workbook
with one sheet per preset, a "Custom" sheet when custom filters are supplied,
a "Summary" sheet listing hit counts / filter criteria, and colour-coded cells
to flag thresholds (green = passes comfortably, red = near/failing).

Column ordering groups the output into logical blocks for analyst readability:
    1. Rank & Identity      — rank, company_id, company_name, sector, sub-sector
    2. Profitability        — ROE, ROCE, NPM, OPM, ROA
    3. Growth               — Revenue/PAT/EPS CAGR (5yr), 3yr variants
    4. Leverage & Quality   — D/E, ICR, asset turnover, FCF, CFO/PAT
    5. Valuation            — P/E, P/B, EV/EBITDA, dividend yield, market cap
    6. Composite Score      — composite_quality_score, capital allocation pattern

Usage::

    from src.screener import load_config, run_screener
    from src.screener.exporter import export_screener_to_excel

    cfg = load_config()
    results = {name: run_screener(cfg.preset(name)) for name in cfg.presets}
    export_screener_to_excel(results, "output/screener_output.xlsx")
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.screener.engine import ScreenerResult

logger = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# Display column ordering (spec §3.5: 20+ KPIs displayed)
# ---------------------------------------------------------------------------
DISPLAY_COLUMNS: list[str] = [
    # Identity
    "rank",
    "company_id",
    "company_name",
    "broad_sector",
    "sub_sector",
    "market_cap_category",
    "year",
    # Profitability
    "roe_pct",
    "roce_pct",
    "net_profit_margin_pct",
    "operating_profit_margin_pct",
    "return_on_assets_pct",
    # Growth
    "revenue_cagr_5yr",
    "pat_cagr_5yr",
    "eps_cagr_5yr",
    "revenue_cagr_3yr",
    # Leverage & cash quality
    "debt_to_equity",
    "icr",
    "icr_label",
    "net_debt_cr",
    "asset_turnover",
    "fcf_cr",
    "fcf_conversion_pct",
    "cfo_pat_ratio",
    "capital_allocation_pattern",
    # Valuation
    "pe_ratio",
    "pb_ratio",
    "ev_ebitda",
    "dividend_yield_pct",
    "fcf_yield_pct",
    "valuation_bucket",
    "market_cap_cr",
    "sales",
    "net_profit",
    # Composite
    "composite_quality_score",
]

# Number format per column (for Excel number_format)
COLUMN_FORMATS: dict[str, str] = {
    "rank": "0",
    "roe_pct": "0.00",
    "roce_pct": "0.00",
    "net_profit_margin_pct": "0.00",
    "operating_profit_margin_pct": "0.00",
    "return_on_assets_pct": "0.00",
    "revenue_cagr_5yr": "0.00",
    "pat_cagr_5yr": "0.00",
    "eps_cagr_5yr": "0.00",
    "revenue_cagr_3yr": "0.00",
    "debt_to_equity": "0.00",
    "icr": "0.00",
    "net_debt_cr": "#,##0",
    "asset_turnover": "0.00",
    "fcf_cr": "#,##0",
    "fcf_conversion_pct": "0.0",
    "cfo_pat_ratio": "0.00",
    "pe_ratio": "0.00",
    "pb_ratio": "0.00",
    "ev_ebitda": "0.00",
    "dividend_yield_pct": "0.00",
    "fcf_yield_pct": "0.00",
    "market_cap_cr": "#,##0",
    "sales": "#,##0",
    "net_profit": "#,##0",
    "composite_quality_score": "0.0",
    "eps": "0.00",
    "book_value_per_share": "0.00",
    "dividend_payout_ratio_pct": "0.0",
    "cash_from_operations_cr": "#,##0",
}

# Friendly header labels (replace underscores, title case)
HEADER_RENAMES: dict[str, str] = {
    "rank": "Rank",
    "company_id": "Ticker",
    "company_name": "Company",
    "broad_sector": "Sector",
    "sub_sector": "Sub-Sector",
    "market_cap_category": "Mkt Cap Cat.",
    "year": "FY",
    "roe_pct": "ROE (%)",
    "roce_pct": "ROCE (%)",
    "net_profit_margin_pct": "NPM (%)",
    "operating_profit_margin_pct": "OPM (%)",
    "return_on_assets_pct": "ROA (%)",
    "revenue_cagr_5yr": "Rev CAGR 5y (%)",
    "pat_cagr_5yr": "PAT CAGR 5y (%)",
    "eps_cagr_5yr": "EPS CAGR 5y (%)",
    "revenue_cagr_3yr": "Rev CAGR 3y (%)",
    "debt_to_equity": "D/E",
    "icr": "ICR",
    "icr_label": "ICR Label",
    "net_debt_cr": "Net Debt (₹Cr)",
    "asset_turnover": "Asset Turnover",
    "fcf_cr": "FCF (₹Cr)",
    "fcf_conversion_pct": "FCF Conv (%)",
    "cfo_pat_ratio": "CFO/PAT",
    "capital_allocation_pattern": "Cap. Alloc.",
    "pe_ratio": "P/E",
    "pb_ratio": "P/B",
    "ev_ebitda": "EV/EBITDA",
    "dividend_yield_pct": "Div Yield (%)",
    "fcf_yield_pct": "FCF Yield (%)",
    "valuation_bucket": "Valuation",
    "market_cap_cr": "Mkt Cap (₹Cr)",
    "sales": "Sales (₹Cr)",
    "net_profit": "Net Profit (₹Cr)",
    "composite_quality_score": "Quality Score",
    "eps": "EPS (₹)",
    "book_value_per_share": "BVPS (₹)",
    "dividend_payout_ratio_pct": "Payout (%)",
    "cash_from_operations_cr": "CFO (₹Cr)",
}

# Columns where higher = better (colour scale green→red for descending)
HIGHER_IS_BETTER: frozenset[str] = frozenset(
    {
        "roe_pct",
        "roce_pct",
        "net_profit_margin_pct",
        "operating_profit_margin_pct",
        "return_on_assets_pct",
        "revenue_cagr_5yr",
        "pat_cagr_5yr",
        "eps_cagr_5yr",
        "revenue_cagr_3yr",
        "icr",
        "asset_turnover",
        "fcf_cr",
        "fcf_conversion_pct",
        "cfo_pat_ratio",
        "dividend_yield_pct",
        "fcf_yield_pct",
        "composite_quality_score",
        "net_profit",
        "sales",
        "market_cap_cr",
    }
)
# Columns where lower = better
LOWER_IS_BETTER: frozenset[str] = frozenset(
    {"debt_to_equity", "pe_ratio", "pb_ratio", "ev_ebitda", "net_debt_cr"}
)

MAX_SHEET_NAME_LEN = 31
SHEET_NAME_ILLEGAL = set(r"[]:*?/\\")


# ---------------------------------------------------------------------------
# Styling helpers
# ---------------------------------------------------------------------------
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
THIN_BORDER = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)
BENCHMARK_FILL = PatternFill("solid", fgColor="FFF2CC")  # light yellow for benchmark row
ALT_ROW_FILL = PatternFill("solid", fgColor="F7F9FC")


def _safe_sheet_name(name: str) -> str:
    """Sanitise a string for use as an Excel sheet name."""
    cleaned = "".join("_" if ch in SHEET_NAME_ILLEGAL else ch for ch in name)
    return cleaned[:MAX_SHEET_NAME_LEN]


def _select_columns(df: pd.DataFrame) -> list[str]:
    """Return the DISPLAY_COLUMNS subset that actually exists in df, preserving order."""
    return [c for c in DISPLAY_COLUMNS if c in df.columns]


def _rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with renamed headers, keeping unknown columns verbatim."""
    out = df.copy()
    rename_map = {c: HEADER_RENAMES[c] for c in out.columns if c in HEADER_RENAMES}
    return out.rename(columns=rename_map)


# ---------------------------------------------------------------------------
# Workbook builder
# ---------------------------------------------------------------------------
@dataclass
class ExportResult:
    """Summary of what was written."""

    output_path: Path
    sheets_written: list[str] = field(default_factory=list)
    total_rows: int = 0


# Fallback short labels for presets whose pretty label contains illegal chars
# or exceeds the Excel 31-char sheet-name limit.
_FALLBACK_SHEET_LABELS: dict[str, str] = {
    "quality_compounder": "Quality Compounder",
    "value_pick": "Value Pick",
    "growth_accelerator": "Growth Accelerator",
    "dividend_champion": "Dividend Champion",
    "debt_free_blue_chip": "Debt-Free Blue Chip",
    "turnaround_watch": "Turnaround Watch",
}


def _write_result_sheet(
    wb: Workbook,
    result: ScreenerResult,
    sheet_name: str | None = None,
) -> str:
    """Write a single ScreenerResult to a new sheet and return the sheet name used."""
    requested = sheet_name or result.preset_label
    # If the pretty label is too long or contains illegal sheet-name chars, fall back
    if (len(requested) > MAX_SHEET_NAME_LEN) or any(c in requested for c in SHEET_NAME_ILLEGAL):
        requested = _FALLBACK_SHEET_LABELS.get(result.preset_name, result.preset_name)
    name = _safe_sheet_name(requested)
    ws = wb.create_sheet(title=name)

    # Build output df with selected, renamed columns
    cols = _select_columns(result.df)
    df = result.df[cols].copy()
    df = _rename_columns(df)

    # ---- Header ----
    header_font = HEADER_FONT
    header_fill = HEADER_FILL
    for col_idx, col_name in enumerate(df.columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER

    # ---- Data rows ----
    for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
        alt_fill = ALT_ROW_FILL if (row_idx % 2 == 0) else None
        for col_idx, col_name in enumerate(df.columns, start=1):
            value = row[col_name]
            if pd.isna(value):
                value = None
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = THIN_BORDER
            # Reverse-map original column key for number formatting
            orig_col = None
            for k, v in HEADER_RENAMES.items():
                if v == col_name:
                    orig_col = k
                    break
            if orig_col and orig_col in COLUMN_FORMATS:
                cell.number_format = COLUMN_FORMATS[orig_col]
            if alt_fill is not None:
                cell.fill = alt_fill

    # ---- Column widths ----
    for col_idx, col_name in enumerate(df.columns, start=1):
        letter = get_column_letter(col_idx)
        # Auto-size based on header + sample values (cap to reasonable range)
        max_len = len(str(col_name))
        sample_vals = df[col_name].dropna().astype(str).head(20).tolist()
        for v in sample_vals:
            if len(v) > max_len:
                max_len = len(v)
        ws.column_dimensions[letter].width = min(max(max_len + 2, 9), 28)

    ws.freeze_panes = "D2"  # freeze rank/ticker/company + header
    ws.auto_filter.ref = ws.dimensions

    # ---- Conditional formatting ----
    # Reverse map header -> original key so we know which metric each column is
    header_to_orig = {v: k for k, v in HEADER_RENAMES.items()}
    n_rows = len(df)
    if n_rows > 0:
        for col_idx, col_name in enumerate(df.columns, start=1):
            letter = get_column_letter(col_idx)
            orig = header_to_orig.get(col_name)
            rng = f"{letter}2:{letter}{n_rows + 1}"
            if orig in HIGHER_IS_BETTER:
                rule = ColorScaleRule(
                    start_type="min",
                    start_color="F8696B",
                    mid_type="percentile",
                    mid_value=50,
                    mid_color="FFEB84",
                    end_type="max",
                    end_color="63BE7B",
                )
                ws.conditional_formatting.add(rng, rule)
            elif orig in LOWER_IS_BETTER:
                rule = ColorScaleRule(
                    start_type="min",
                    start_color="63BE7B",
                    mid_type="percentile",
                    mid_value=50,
                    mid_color="FFEB84",
                    end_type="max",
                    end_color="F8696B",
                )
                ws.conditional_formatting.add(rng, rule)
            elif orig == "composite_quality_score":
                # Green >= 70, red < 40
                ws.conditional_formatting.add(
                    rng,
                    CellIsRule(
                        operator="greaterThanOrEqual",
                        formula=["70"],
                        fill=PatternFill("solid", fgColor="C6EFCE"),
                    ),
                )
                ws.conditional_formatting.add(
                    rng,
                    CellIsRule(
                        operator="lessThan",
                        formula=["40"],
                        fill=PatternFill("solid", fgColor="FFC7CE"),
                    ),
                )

    # ---- Title row (insert at top) ----
    ws.insert_rows(1)
    ws.cell(
        row=1,
        column=1,
        value=f"{result.preset_label} — {result.rows_out} of {result.rows_in} companies",
    ).font = Font(bold=True, size=13, color="1F4E78")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=min(len(df.columns), 10))
    ws.row_dimensions[1].height = 22

    return name


def _write_summary_sheet(wb: Workbook, results: Mapping[str, ScreenerResult]) -> str:
    """Write a summary sheet listing every preset's hit count and filters applied."""
    ws = wb.create_sheet(title="Summary", index=0)
    ws.cell(row=1, column=1, value="Nifty 100 Screener — Summary").font = Font(
        bold=True, size=14, color="1F4E78"
    )
    ws.merge_cells("A1:E1")
    ws.row_dimensions[1].height = 22

    headers = ["Preset", "Label", "Companies Passing", "Universe Size", "Filters Applied"]
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=col_idx, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER

    row = 4
    for name, result in results.items():
        ws.cell(row=row, column=1, value=name).border = THIN_BORDER
        ws.cell(row=row, column=2, value=result.preset_label).border = THIN_BORDER
        ws.cell(row=row, column=3, value=result.rows_out).border = THIN_BORDER
        ws.cell(row=row, column=4, value=result.rows_in).border = THIN_BORDER
        filter_str = "; ".join(
            f"{f.metric} {f.direction} {f.threshold:g}" for f in result.filters_applied
        )
        cell = ws.cell(row=row, column=5, value=filter_str)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.border = THIN_BORDER
        row += 1

    for col_idx, width in enumerate([28, 32, 18, 16, 80], start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.freeze_panes = "A4"

    return "Summary"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def export_screener_to_excel(
    results: Mapping[str, ScreenerResult],
    output_path: Path | str,
    *,
    include_summary: bool = True,
) -> ExportResult:
    """Write multiple ScreenerResult objects to a single XLSX workbook.

    Args:
        results: Mapping of sheet_key -> ScreenerResult (typically preset name -> result).
        output_path: Destination .xlsx path.
        include_summary: If True, prepend a "Summary" sheet.

    Returns:
        ExportResult with sheet list and total row count.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    # Remove default sheet
    default_sheet = wb.active
    wb.remove(default_sheet)

    sheets: list[str] = []
    total_rows = 0

    if include_summary and results:
        sheets.append(_write_summary_sheet(wb, results))

    for key, result in results.items():
        sheet_label = result.preset_label if result.preset_label else key
        used_name = _write_result_sheet(wb, result, sheet_name=sheet_label)
        sheets.append(used_name)
        total_rows += result.rows_out

    wb.save(output_path)
    logger.info(
        f"Wrote screener export with {len(sheets)} sheets / {total_rows} rows -> {output_path}"
    )
    return ExportResult(output_path=output_path, sheets_written=sheets, total_rows=total_rows)


def export_single_result(
    result: ScreenerResult,
    output_path: Path | str,
    sheet_name: str | None = None,
) -> ExportResult:
    """Convenience: write a single ScreenerResult to an XLSX file (one sheet)."""
    return export_screener_to_excel(
        {result.preset_name: result}, output_path, include_summary=False
    )
