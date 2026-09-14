"""Sprint 5 Day 34 — Batch Report Generation.

Generates tearsheet PDFs for all Nifty-100 companies (with a minimum-data
skip-list for companies under 3 years) and sector-level summary PDFs.

Output layout (per Day 34 spec):
    reports/tearsheets/<TICKER>_tearsheet.pdf   — one per company
    reports/sector/<SECTOR>_report.pdf          — one per broad sector
    output/skipped_tearsheets.csv               — tickers skipped for <3yr data
"""

from __future__ import annotations

import csv
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.reports.tearsheet import (
    NAVY,
    NAVY_HEX,
    _fig_to_image,
    _fmt_pct,
    _fmt_ratio,
    _format_crore,
    _safe_float,
    generate_tearsheet_pdf,
    load_tearsheet_data,
)

logger = logging.getLogger(__name__)

MIN_YEARS_REQUIRED = 3
TEARSHEET_DIRNAME = "tearsheets"
SECTOR_DIRNAME = "sector"
SKIPPED_CSV_NAME = "skipped_tearsheets.csv"


# ---------------------------------------------------------------------------
# Sector slug helper — safe filename
# ---------------------------------------------------------------------------
def _sector_slug(name: str) -> str:
    """Convert a sector name like 'Conglomerates / Other' to a safe slug."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower()
    return slug or "unknown"


# ---------------------------------------------------------------------------
# Data coverage check
# ---------------------------------------------------------------------------
def get_shared_year_counts(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return DataFrame[company_id, n_years] counting years present in
    cashflow + profitandloss + balancesheet together (inner-join).
    """
    df = pd.read_sql(
        """
        SELECT cf.company_id, COUNT(DISTINCT cf.year) AS n_years
        FROM cashflow cf
        INNER JOIN profitandloss pl
            ON pl.company_id = cf.company_id AND pl.year = cf.year
        INNER JOIN balancesheet bs
            ON bs.company_id = cf.company_id AND bs.year = cf.year
        GROUP BY cf.company_id
        """,
        conn,
    )
    return df


# ---------------------------------------------------------------------------
# Batch tearsheet generation
# ---------------------------------------------------------------------------
@dataclass
class BatchResult:
    """Summary of a batch tearsheet generation run."""

    generated: list[tuple[str, Path]]
    skipped: list[tuple[str, str]]  # (ticker, reason)
    failures: list[tuple[str, str]]  # (ticker, error message)
    elapsed_sec: float


def batch_generate_tearsheets(
    conn: sqlite3.Connection,
    output_dir: Path,
    min_years: int = MIN_YEARS_REQUIRED,
) -> BatchResult:
    """Generate tearsheet PDFs for every qualifying company.

    Companies with fewer than ``min_years`` of shared CF+P&L+BS years are
    skipped (logged to the returned list).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    companies = pd.read_sql("SELECT c.id FROM companies c ORDER BY c.company_name", conn)
    coverage = get_shared_year_counts(conn)
    cov_lookup = dict(zip(coverage["company_id"], coverage["n_years"], strict=True))

    generated: list[tuple[str, Path]] = []
    skipped: list[tuple[str, str]] = []
    failures: list[tuple[str, str]] = []

    t0 = time.perf_counter()
    for _, row in companies.iterrows():
        cid = row["id"]
        n_yr = int(cov_lookup.get(cid, 0))
        if n_yr < min_years:
            reason = f"only {n_yr} year(s) of shared CF+P&L+BS data (<{min_years})"
            skipped.append((cid, reason))
            logger.warning("Skipping %s: %s", cid, reason)
            continue
        out_path = output_dir / f"{cid}_tearsheet.pdf"
        try:
            data = load_tearsheet_data(cid, conn)
            generate_tearsheet_pdf(data, out_path)
            generated.append((cid, out_path))
        except Exception as exc:
            failures.append((cid, str(exc)))
            logger.exception("Failed to generate tearsheet for %s", cid)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Batch tearsheets: %d generated, %d skipped, %d failed in %.1fs",
        len(generated),
        len(skipped),
        len(failures),
        elapsed,
    )
    return BatchResult(generated, skipped, failures, elapsed)


def write_skipped_csv(skipped: list[tuple[str, str]], path: Path) -> int:
    """Write skipped tickers to CSV with columns: company_id, reason."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["company_id", "reason"])
        for cid, reason in skipped:
            w.writerow([cid, reason])
    return len(skipped)


# ---------------------------------------------------------------------------
# Sector PDF generation
# ---------------------------------------------------------------------------
SECTOR_METRIC_COLS: tuple[tuple[str, str, str], ...] = (
    # (label, column_source, formatter)
    ("Market Cap (Rs Cr)", "market_cap_crore", _format_crore),
    ("P/E", "pe_ratio", _fmt_ratio),
    ("P/B", "pb_ratio", _fmt_ratio),
    ("ROE %", "roe_pct", _fmt_pct),
    ("ROCE %", "roce_pct", _fmt_pct),
    ("D/E", "debt_to_equity", _fmt_ratio),
    ("5yr Rev CAGR", "revenue_cagr_5yr", _fmt_pct),
    ("5yr PAT CAGR", "pat_cagr_5yr", _fmt_pct),
)


def _median(series: pd.Series) -> float | None:
    """Return median ignoring NaN (SQLite has no MEDIAN())."""
    s = series.dropna()
    if len(s) == 0:
        return None
    return float(s.median())


def _load_sector_panel(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return a panel with one row per company (latest FY) with metrics needed
    for the sector summary table.
    """
    # For each company pick latest year available in financial_ratios
    panel = pd.read_sql(
        """
        SELECT c.id AS company_id, c.company_name, s.broad_sector, s.sub_sector,
               fr.year, fr.return_on_equity_pct AS roe_pct, fr.roce_pct AS roce_pct,
               fr.debt_to_equity, fr.revenue_cagr_5yr, fr.pat_cagr_5yr,
               fr.earnings_per_share, fr.dividend_payout_ratio_pct AS div_payout,
               mc.market_cap_crore, mc.pe_ratio, mc.pb_ratio, mc.dividend_yield_pct,
               fr.capital_allocation_pattern
        FROM companies c
        LEFT JOIN sectors s ON s.company_id = c.id
        LEFT JOIN financial_ratios fr ON fr.company_id = c.id
            AND fr.year = (SELECT MAX(year) FROM financial_ratios fr2
                          WHERE fr2.company_id = c.id)
        LEFT JOIN market_cap mc ON mc.company_id = c.id
            AND mc.year = (SELECT MAX(year) FROM market_cap mc2
                          WHERE mc2.company_id = c.id)
        ORDER BY s.broad_sector, c.company_name
        """,
        conn,
    )
    return panel


def _make_sector_kpi_summary_chart(
    panel: pd.DataFrame,
    width_cm: float,
    height_cm: float,
):
    """Bar chart of median ROE and ROCE per sector (used on individual sector PDF)."""
    import matplotlib.pyplot as plt
    import numpy as np

    grp = (
        panel.groupby("broad_sector", dropna=False)
        .agg(
            med_roe=("roe_pct", _median),
            med_roce=("roce_pct", _median),
        )
        .reset_index()
    )
    # For the single-sector PDF we just show a horizontal bar for THIS sector vs overall median
    fig, ax = plt.subplots(figsize=(max(width_cm / 2.54, 4), max(height_cm / 2.54, 2)))
    sectors = grp["broad_sector"].fillna("Other").tolist()
    roe = grp["med_roe"].fillna(0).tolist()
    roce = grp["med_roce"].fillna(0).tolist()
    y = np.arange(len(sectors))
    ax.barh(y - 0.15, roe, height=0.3, color=NAVY_HEX, label="Median ROE %")
    ax.barh(y + 0.15, roce, height=0.3, color="#C00000", label="Median ROCE %")
    ax.set_yticks(y)
    ax.set_yticklabels(sectors, fontsize=6)
    ax.tick_params(axis="x", labelsize=6)
    ax.set_xlabel("%", fontsize=7)
    ax.set_title(
        "Sector Return Comparison (Medians)", fontsize=8, fontweight="bold", color=NAVY_HEX, pad=4
    )
    ax.axvline(0, color="grey", linewidth=0.4)
    ax.legend(loc="lower right", fontsize=6, frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout(pad=0.4)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


def _make_sector_composition_chart(sector_df: pd.DataFrame, width_cm: float, height_cm: float):
    """Pie chart of market-cap share within the sector."""
    import matplotlib.pyplot as plt

    df = sector_df.dropna(subset=["market_cap_crore"]).copy()
    if len(df) == 0:
        # No market cap data — empty placeholder
        fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54))
        ax.text(0.5, 0.5, "Market cap data unavailable", ha="center", va="center", fontsize=8)
        ax.axis("off")
        return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)
    # Group small slices (<3%) into "Other"
    df = df.sort_values("market_cap_crore", ascending=False)
    total = df["market_cap_crore"].sum()
    labels: list[str] = []
    sizes: list[float] = []
    other = 0.0
    for _, r in df.iterrows():
        share = r["market_cap_crore"] / total * 100
        if share < 3.0:
            other += r["market_cap_crore"]
        else:
            labels.append(str(r["company_id"]))
            sizes.append(float(r["market_cap_crore"]))
    if other > 0:
        labels.append("Other")
        sizes.append(other)
    fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54))
    ax.pie(
        sizes,
        labels=labels,
        autopct="%1.0f%%",
        startangle=90,
        textprops={"fontsize": 6},
        colors=plt.cm.tab20.colors,
    )
    ax.set_title("Market Cap Composition", fontsize=8, fontweight="bold", color=NAVY_HEX, pad=4)
    fig.tight_layout(pad=0.4)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


def generate_sector_pdf(
    sector_name: str,
    sector_df: pd.DataFrame,
    panel: pd.DataFrame,
    output_path: Path,
) -> Path:
    """Generate a single sector summary PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- styles ----
    base = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "SH1",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=NAVY,
        spaceAfter=6,
        leading=20,
    )
    h2 = ParagraphStyle(
        "SH2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=NAVY,
        spaceBefore=10,
        spaceAfter=4,
        leading=14,
    )
    body = ParagraphStyle(
        "SBody", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=12
    )
    cell = ParagraphStyle(
        "SCell", parent=base["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9
    )
    cell_bold = ParagraphStyle(
        "SCellB",
        parent=base["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=NAVY,
    )

    # ---- median KPIs for the sector ----
    medians: dict[str, Any] = {
        "market_cap_crore": _median(sector_df["market_cap_crore"]),
        "pe_ratio": _median(sector_df["pe_ratio"]),
        "pb_ratio": _median(sector_df["pb_ratio"]),
        "roe_pct": _median(sector_df["roe_pct"]),
        "roce_pct": _median(sector_df["roce_pct"]),
        "debt_to_equity": _median(sector_df["debt_to_equity"]),
        "revenue_cagr_5yr": _median(sector_df["revenue_cagr_5yr"]),
        "pat_cagr_5yr": _median(sector_df["pat_cagr_5yr"]),
    }
    overall_roe = _median(panel["roe_pct"])
    overall_roce = _median(panel["roce_pct"])

    # ---- doc setup ----
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"{sector_name} — Sector Report",
        author="Nifty 100 Financial Intelligence Platform",
    )
    content_width = A4[0] - 3 * cm
    story: list = []

    # Title bar
    title_bar = Table([[Paragraph(sector_name, h1)]], colWidths=[content_width])
    title_bar.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(title_bar)
    story.append(Spacer(1, 0.2 * cm))
    story.append(
        Paragraph(
            f"Number of companies in sector: <b>{len(sector_df)}</b> &nbsp;|&nbsp; "
            f"Nifty 100 overall median ROE: <b>{overall_roe:.1f}%</b> &nbsp;|&nbsp; "
            f"Overall median ROCE: <b>{overall_roce:.1f}%</b>",
            body,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    # Median KPI tiles (4 x 2)
    story.append(Paragraph("Sector Median KPIs", h2))
    kpi_pairs = [
        ("Median Market Cap", _format_crore(medians["market_cap_crore"])),
        ("Median P/E", _fmt_ratio(medians["pe_ratio"])),
        ("Median P/B", _fmt_ratio(medians["pb_ratio"])),
        ("Median ROE", _fmt_pct(medians["roe_pct"])),
        ("Median ROCE", _fmt_pct(medians["roce_pct"])),
        ("Median D/E", _fmt_ratio(medians["debt_to_equity"])),
        ("Median 5yr Rev CAGR", _fmt_pct(medians["revenue_cagr_5yr"])),
        ("Median 5yr PAT CAGR", _fmt_pct(medians["pat_cagr_5yr"])),
    ]
    tile_gap = 0.2 * cm
    tile_w = (content_width - 3 * tile_gap) / 4.0
    tile_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F2F2F2")),
            ("TEXTCOLOR", (0, 1), (-1, 1), NAVY),
            ("TOPPADDING", (0, 0), (-1, 0), 3),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
            ("TOPPADDING", (0, 1), (-1, 1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
        ]
    )
    tiles = []
    for label, val in kpi_pairs:
        t = Table(
            [[Paragraph(label, cell_bold)], [Paragraph(val, cell_bold)]],
            colWidths=[tile_w],
        )
        t.setStyle(tile_style)
        tiles.append(t)
    grid = Table(
        [
            [tiles[0], "", tiles[1], "", tiles[2], "", tiles[3]],
            [""],
            [tiles[4], "", tiles[5], "", tiles[6], "", tiles[7]],
        ],
        colWidths=[tile_w, tile_gap, tile_w, tile_gap, tile_w, tile_gap, tile_w],
        rowHeights=[None, 0.15 * cm, None],
    )
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(grid)
    story.append(Spacer(1, 0.3 * cm))

    # Charts row: composition pie + sector comparison bar
    story.append(Paragraph("Sector Composition & Peer Comparison", h2))
    pie_w = 7.5 * cm
    bar_w = content_width - pie_w - 0.3 * cm
    pie = _make_sector_composition_chart(sector_df, width_cm=pie_w / cm, height_cm=5.0)
    bar = _make_sector_kpi_summary_chart(panel, width_cm=bar_w / cm, height_cm=5.0)
    chart_row = Table([[pie, "", bar]], colWidths=[pie_w, 0.3 * cm, bar_w])
    chart_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(chart_row)
    story.append(Spacer(1, 0.3 * cm))

    # Company table
    story.append(Paragraph("Companies in Sector", h2))
    header = ["Ticker", "Company"] + [lbl for lbl, _, _ in SECTOR_METRIC_COLS] + ["Pattern"]
    table_data: list[list] = [[Paragraph(h, cell_bold) for h in header]]
    sector_sorted = sector_df.sort_values("market_cap_crore", ascending=False, na_position="last")
    for _, r in sector_sorted.iterrows():
        row = [
            Paragraph(str(r["company_id"]), cell_bold),
            Paragraph(str(r["company_name"]), cell),
        ]
        for _lbl, col, fmt in SECTOR_METRIC_COLS:
            val = _safe_float(r[col])
            row.append(Paragraph(fmt(val), cell))
        pattern = (
            str(r["capital_allocation_pattern"])
            if pd.notna(r.get("capital_allocation_pattern"))
            else "-"
        )
        row.append(Paragraph(pattern, cell))
        table_data.append(row)

    col_widths = [1.8 * cm, 3.8 * cm] + [(content_width - 5.6 * cm - 1.8 * cm) / 9.0] * 9
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (1, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BFBFBF")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ]
        )
    )
    story.append(tbl)

    doc.build(story)
    logger.info("Sector report written to %s", output_path)
    return output_path


def batch_generate_sector_reports(
    conn: sqlite3.Connection,
    output_dir: Path,
) -> list[tuple[str, Path]]:
    """Generate one sector PDF per broad_sector. Returns (sector_name, path) list."""
    output_dir.mkdir(parents=True, exist_ok=True)
    panel = _load_sector_panel(conn)
    results: list[tuple[str, Path]] = []
    for sector_name, grp in panel.groupby("broad_sector", dropna=False, sort=True):
        name = sector_name if isinstance(sector_name, str) else "Unclassified"
        slug = _sector_slug(name)
        out_path = output_dir / f"{slug}_report.pdf"
        generate_sector_pdf(name, grp, panel, out_path)
        results.append((name, out_path))
    return results


# ---------------------------------------------------------------------------
# Full batch entry point
# ---------------------------------------------------------------------------
def run_day34_batch(
    project_root: Path | None = None,
) -> dict:
    """Run Day-34 batch: tearsheets + sector reports. Returns summary dict."""
    from src.utils.config import settings

    if project_root is None:
        project_root = settings.PROJECT_ROOT
    project_root = Path(project_root)

    db_path = project_root / "db" / "nifty100.db"
    tearsheets_dir = project_root / "reports" / TEARSHEET_DIRNAME
    sectors_dir = project_root / "reports" / SECTOR_DIRNAME
    skipped_csv = project_root / "output" / SKIPPED_CSV_NAME

    conn = sqlite3.connect(str(db_path))
    try:
        tb = batch_generate_tearsheets(conn, tearsheets_dir)
        write_skipped_csv(tb.skipped, skipped_csv)
        sector_results = batch_generate_sector_reports(conn, sectors_dir)
    finally:
        conn.close()

    return {
        "tearsheets_generated": len(tb.generated),
        "tearsheets_skipped": len(tb.skipped),
        "tearsheets_failed": len(tb.failures),
        "skipped_csv": skipped_csv,
        "sector_reports": len(sector_results),
        "elapsed_sec": tb.elapsed_sec,
        "failures": tb.failures,
        "tearsheet_dir": tearsheets_dir,
        "sector_dir": sectors_dir,
    }


__all__ = [
    "SECTOR_METRIC_COLS",
    "BatchResult",
    "batch_generate_sector_reports",
    "batch_generate_tearsheets",
    "generate_sector_pdf",
    "get_shared_year_counts",
    "run_day34_batch",
    "write_skipped_csv",
]
