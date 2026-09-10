"""Peer Comparison Excel Report — Sprint 3 Day 20.

Builds ``output/peer_comparison.xlsx`` with one sheet per peer group. Each
sheet contains:
    * company_id + company_name identity columns.
    * 20 metric columns (profitability, growth, leverage, cash quality,
      valuation, composite) with the metric's raw value.
    * A matching percentile-rank column for each metric (0-1 within the
      peer group, computed with SQL PERCENT_RANK semantics).
    * Colour-coded percentile cells: green for >= 0.75 (top quartile),
      yellow for 0.25-0.75, red for <= 0.25 (bottom quartile).
    * A gold/amber row background for the company flagged
      ``is_benchmark = 1`` in ``peer_groups``.
    * A "Peer Median" summary row at the bottom of each sheet showing
      the median raw value and median percentile (0.5 by definition) for
      each metric.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.etl.database import get_connection
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

OUTPUT_PATH = settings.PROJECT_ROOT / "output" / "peer_comparison.xlsx"


# ---------------------------------------------------------------------------
# Metric registry — 20 metrics for the report.
# Each metric has: key, label, SQL column, number format, higher_is_better.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReportMetric:
    """One metric displayed in the peer comparison report."""

    key: str
    label: str
    column: str
    fmt: str
    higher_is_better: bool = True


REPORT_METRICS: tuple[ReportMetric, ...] = (
    ReportMetric("roe", "ROE (%)", "return_on_equity_pct", "0.00"),
    ReportMetric("roce", "ROCE (%)", "roce_pct", "0.00"),
    ReportMetric("npm", "Net Profit Margin (%)", "net_profit_margin_pct", "0.00"),
    ReportMetric("opm", "Operating Profit Margin (%)", "operating_profit_margin_pct", "0.00"),
    ReportMetric("roa", "Return on Assets (%)", "return_on_assets_pct", "0.00"),
    ReportMetric("de", "Debt-to-Equity", "debt_to_equity", "0.00", higher_is_better=False),
    ReportMetric("icr", "Interest Coverage (x)", "interest_coverage", "0.00"),
    ReportMetric("fcf", "Free Cash Flow (Rs Cr)", "free_cash_flow_cr", "#,##0"),
    ReportMetric("fcf_yield", "FCF Yield (%)", "fcf_yield_pct", "0.00"),  # computed after join
    ReportMetric("cfo_pat", "CFO/PAT (x)", "cfo_pat_ratio", "0.00"),
    ReportMetric("rev_cagr_3yr", "Revenue CAGR 3y (%)", "revenue_cagr_3yr", "0.00"),
    ReportMetric("rev_cagr_5yr", "Revenue CAGR 5y (%)", "revenue_cagr_5yr", "0.00"),
    ReportMetric("pat_cagr_3yr", "PAT CAGR 3y (%)", "pat_cagr_3yr", "0.00"),
    ReportMetric("pat_cagr_5yr", "PAT CAGR 5y (%)", "pat_cagr_5yr", "0.00"),
    ReportMetric("eps_cagr_5yr", "EPS CAGR 5y (%)", "eps_cagr_5yr", "0.00"),
    ReportMetric("asset_turnover", "Asset Turnover (x)", "asset_turnover", "0.00"),
    ReportMetric("pe", "P/E", "pe_ratio", "0.00", higher_is_better=False),
    ReportMetric("pb", "P/B", "pb_ratio", "0.00", higher_is_better=False),
    ReportMetric("div_yield", "Dividend Yield (%)", "dividend_yield_pct", "0.00"),
    ReportMetric("composite", "Composite Score", "composite_quality_score", "0.0"),
)

# Columns that require the screener-style derived computation (FCF yield).
DERIVED_COLUMNS = ("fcf_yield_pct",)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
BENCHMARK_FILL = PatternFill("solid", fgColor="FFD966")  # gold/amber
SUMMARY_FILL = PatternFill("solid", fgColor="E7E6E6")  # light grey
SUMMARY_FONT = Font(bold=True, italic=True, size=10)
GREEN_FILL = PatternFill("solid", fgColor="C6EFCE")  # top quartile
YELLOW_FILL = PatternFill("solid", fgColor="FFEB9C")  # middle 50%
RED_FILL = PatternFill("solid", fgColor="FFC7CE")  # bottom quartile
THIN_BORDER = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)
TITLE_FONT = Font(bold=True, size=13, color="1F4E78")
BODY_FONT = Font(size=10)

PCT_HIGH = 0.75  # >= 75th percentile → green
PCT_LOW = 0.25  # <= 25th percentile → red


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _fcf_yield(fcf: float, mc: float) -> float | None:
    """Free Cash Flow yield = FCF / Market Cap * 100 (matches Day-16 valuation)."""
    if fcf is None or mc is None:
        return None
    try:
        if mc == 0:
            return None
        return float(fcf) / float(mc) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _percent_rank(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """SQL PERCENT_RANK (same as Day 18/19): (rank-1)/(n-1) with ties='min'."""
    valid = series.notna()
    n = int(valid.sum())
    if n <= 1:
        out = pd.Series(float("nan"), index=series.index, dtype=float)
        out.loc[valid] = 0.5
        return out
    r = series.rank(method="min", ascending=True)
    pr = (r - 1.0) / (n - 1.0)
    if not higher_is_better:
        pr = 1.0 - pr
    return pr


def load_peer_report_dataset(
    db_path: Path | str | None = None,
    year: str | None = None,
) -> pd.DataFrame:
    """Load wide dataset per peer-group with 20 metrics per company + percentile ranks."""
    # Pull raw metric columns joined with peer_groups, market_cap, sectors.
    # Note: pe_ratio, pb_ratio, ev_ebitda, dividend_yield_pct, market_cap_cr live
    # in the market_cap table, not financial_ratios.
    fr_metrics = []
    mc_metrics = ["mc.market_cap_crore AS market_cap_cr"]
    for m in REPORT_METRICS:
        if m.column in DERIVED_COLUMNS:
            continue
        if m.column in ("pe_ratio", "pb_ratio", "ev_ebitda", "dividend_yield_pct"):
            mc_metrics.append(f"mc.{m.column}")
        else:
            fr_metrics.append(f"fr.{m.column}")
    metric_cols = ", ".join(fr_metrics)
    if mc_metrics:
        metric_cols += ", " + ", ".join(dict.fromkeys(mc_metrics))  # de-dupe keeping order

    if year is None:
        where_year = "fr.year = (SELECT MAX(year) FROM financial_ratios)"
    else:
        where_year = f"fr.year = '{year}'"

    # For fcf_yield we need market_cap from market_cap table.
    year_num_expr = "CAST(SUBSTR(fr.year, 1, 4) AS INTEGER)"
    sql = f"""
        SELECT
            fr.company_id,
            co.company_name,
            pg.peer_group_name,
            pg.is_benchmark,
            fr.year,
            {metric_cols}
        FROM financial_ratios fr
        JOIN companies co ON co.id = fr.company_id
        JOIN peer_groups pg ON pg.company_id = fr.company_id
        LEFT JOIN market_cap mc
          ON mc.company_id = fr.company_id
         AND mc.year = {year_num_expr}
        WHERE {where_year}
        ORDER BY pg.peer_group_name, co.company_name
    """
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn)

    if df.empty:
        return df

    # Compute derived FCF yield.
    df["fcf_yield_pct"] = [
        _fcf_yield(fcf, mc)
        for fcf, mc in zip(df["free_cash_flow_cr"], df["market_cap_cr"], strict=True)
    ]
    df.drop(columns=["market_cap_cr"], inplace=True)

    # Compute percentile ranks within each peer_group.
    for m in REPORT_METRICS:
        df[f"{m.key}_pctile"] = df.groupby("peer_group_name")[m.column].transform(
            lambda s, h=m.higher_is_better: _percent_rank(s, higher_is_better=h)
        )
    return df


# ---------------------------------------------------------------------------
# Workbook builder
# ---------------------------------------------------------------------------
def _safe_sheet(name: str) -> str:
    return name[:31]


def _pctile_fill(pr: float | None) -> PatternFill | None:
    """Map a percentile rank (0-1) to the green/yellow/red fill."""
    if pr is None or pd.isna(pr):
        return None
    if pr >= PCT_HIGH - 1e-9:
        return GREEN_FILL
    if pr <= PCT_LOW + 1e-9:
        return RED_FILL
    return YELLOW_FILL


def _write_group_sheet(wb: Workbook, group_name: str, df: pd.DataFrame, year: str) -> str:
    name = _safe_sheet(group_name)
    ws = wb.create_sheet(title=name)

    # Build header row: company_id, company_name, then for each metric
    # a "Value" column and a "Percentile" column.
    headers: list[str] = ["Ticker", "Company"]
    for m in REPORT_METRICS:
        headers.append(m.label)
        headers.append(f"{m.label} %ile")

    # Title row
    n_companies = len(df)
    ws.cell(
        row=1,
        column=1,
        value=f"{group_name} — Peer Comparison (FY {year}, {n_companies} companies)",
    ).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=min(len(headers), 12))
    ws.row_dimensions[1].height = 22

    # Header row at row 2
    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=2, column=col_idx, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = THIN_BORDER
    ws.row_dimensions[2].height = 32

    # Sort by composite_pctile descending so best-in-group appears first
    sorted_df = df.sort_values("composite_pctile", ascending=False, na_position="last").reset_index(
        drop=True
    )

    # Data rows starting row 3
    data_start_row = 3
    for row_idx, (_, r) in enumerate(sorted_df.iterrows(), start=data_start_row):
        is_bench = bool(r.get("is_benchmark", 0))
        base_fill = BENCHMARK_FILL if is_bench else None

        # Ticker
        cell = ws.cell(row=row_idx, column=1, value=r["company_id"])
        cell.font = Font(bold=bool(is_bench), size=10)
        cell.border = THIN_BORDER
        if base_fill is not None:
            cell.fill = base_fill
        # Company
        cell = ws.cell(row=row_idx, column=2, value=r["company_name"])
        cell.font = Font(bold=bool(is_bench), size=10)
        cell.border = THIN_BORDER
        if base_fill is not None:
            cell.fill = base_fill

        col_idx = 3
        for m in REPORT_METRICS:
            val = r[m.column]
            pct = r[f"{m.key}_pctile"]

            # Value cell
            v_cell = ws.cell(
                row=row_idx, column=col_idx, value=None if pd.isna(val) else float(val)
            )
            v_cell.number_format = m.fmt
            v_cell.font = BODY_FONT
            v_cell.border = THIN_BORDER
            if base_fill is not None:
                v_cell.fill = base_fill
            col_idx += 1

            # Percentile cell — colour coded by quartile
            p_val = None if pd.isna(pct) else float(pct)
            p_cell = ws.cell(row=row_idx, column=col_idx, value=p_val)
            p_cell.number_format = "0%"
            p_cell.font = BODY_FONT
            p_cell.border = THIN_BORDER
            q_fill = _pctile_fill(p_val)
            if q_fill is not None:
                p_cell.fill = q_fill
            elif base_fill is not None:
                p_cell.fill = base_fill
            col_idx += 1

    # Peer-median summary row
    summary_row = data_start_row + len(sorted_df)
    ws.cell(row=summary_row, column=1, value="Peer Median").font = SUMMARY_FONT
    ws.cell(row=summary_row, column=2, value="").font = SUMMARY_FONT
    for c in (1, 2):
        ws.cell(row=summary_row, column=c).fill = SUMMARY_FILL
        ws.cell(row=summary_row, column=c).border = THIN_BORDER
    col_idx = 3
    for m in REPORT_METRICS:
        med_val = sorted_df[m.column].median()
        med_cell = ws.cell(
            row=summary_row, column=col_idx, value=None if pd.isna(med_val) else float(med_val)
        )
        med_cell.number_format = m.fmt
        med_cell.font = SUMMARY_FONT
        med_cell.fill = SUMMARY_FILL
        med_cell.border = THIN_BORDER
        col_idx += 1

        # Median percentile = 0.5 by definition.
        p_med = 0.5
        p_cell = ws.cell(row=summary_row, column=col_idx, value=p_med)
        p_cell.number_format = "0%"
        p_cell.font = SUMMARY_FONT
        p_cell.fill = SUMMARY_FILL
        p_cell.border = THIN_BORDER
        col_idx += 1

    # Column widths
    ws.column_dimensions["A"].width = 13
    ws.column_dimensions["B"].width = 28
    # Data columns: value columns narrower than percentile columns
    for i in range(len(REPORT_METRICS)):
        val_col = get_column_letter(3 + 2 * i)
        pct_col = get_column_letter(4 + 2 * i)
        ws.column_dimensions[val_col].width = 12
        ws.column_dimensions[pct_col].width = 8

    ws.freeze_panes = "C3"
    return name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_peer_report(
    db_path: Path | str | None = None,
    year: str | None = None,
    output_path: Path | str | None = None,
) -> dict[str, object]:
    """Generate the peer_comparison.xlsx report."""
    out = Path(output_path) if output_path else OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)

    df = load_peer_report_dataset(db_path=db_path, year=year)
    if df.empty:
        raise RuntimeError("No peer-group data returned; cannot build report.")
    target_year = df["year"].iloc[0]

    wb = Workbook()
    default_sheet = wb.active
    wb.remove(default_sheet)

    groups_written: list[str] = []
    for group_name, sub in df.groupby("peer_group_name", sort=True):
        written = _write_group_sheet(wb, group_name, sub, year=target_year)
        groups_written.append(written)
        logger.info(f"peer_report: wrote sheet '{written}' ({len(sub)} companies)")

    wb.save(out)

    stats = {
        "output_path": str(out),
        "year": target_year,
        "sheets": groups_written,
        "n_sheets": len(groups_written),
        "n_companies": int(df["company_id"].nunique()),
        "n_metrics": len(REPORT_METRICS),
    }
    logger.info(
        f"Wrote peer_comparison.xlsx: {stats['n_sheets']} sheets, "
        f"{stats['n_companies']} companies, {stats['n_metrics']} metrics -> {out}"
    )
    return stats


__all__ = [
    "OUTPUT_PATH",
    "REPORT_METRICS",
    "ReportMetric",
    "generate_peer_report",
    "load_peer_report_dataset",
]
