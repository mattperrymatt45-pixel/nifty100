"""Sprint 5 Day 33 — PDF Tearsheet Template (ReportLab).

Generates a 2-page company tearsheet PDF for any Nifty-100 company.

**Page 1 layout:**
    1. Navy header bar — company name (white text) + ticker code (bottom-right)
    2. Six KPI tiles arranged 2 rows x 3 columns:
         Market Cap | P/E Ratio | ROE %
         ROCE %     | D/E Ratio | 5yr PAT CAGR
    3. 10-year Revenue bar chart  |  10-year Net Profit bar chart  (side-by-side)
    4. ROE & ROCE dual-axis line chart (overlaid)

**Page 2 (extended in later days) — reserved with section headers:**
    1. Cash Flow Quality summary (CFO/PAT, CapEx tier, capital-allocation pattern)
    2. Pros & Cons auto-generated bullets
    3. Valuation snapshot

Charts are rendered with matplotlib and embedded as PNG images into the
ReportLab Platypus flowable pipeline.  The navy brand colour is ``#1F4E78``
matching the Excel header styling used elsewhere in the project.
"""

from __future__ import annotations

import io
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Brand palette
# ---------------------------------------------------------------------------
NAVY = colors.HexColor("#1F4E78")
NAVY_HEX = "#1F4E78"
LIGHT_NAVY = colors.HexColor("#D9E2F3")
GREY = colors.HexColor("#595959")
LIGHT_GREY = colors.HexColor("#F2F2F2")
ACCENT_GREEN = colors.HexColor("#548235")
ACCENT_RED = colors.HexColor("#C00000")
WHITE = colors.white

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = RIGHT_MARGIN = 1.5 * cm
TOP_MARGIN = BOTTOM_MARGIN = 1.5 * cm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TearsheetData:
    """All data needed to render one company tearsheet."""

    company_id: str
    company_name: str
    sector: str | None
    sub_sector: str | None

    # Latest-FY KPI values (floats; None = missing)
    market_cap_crore: float | None
    pe_ratio: float | None
    pb_ratio: float | None
    roe_pct: float | None
    roce_pct: float | None
    debt_to_equity: float | None
    dividend_yield_pct: float | None
    pat_cagr_5yr: float | None
    revenue_cagr_5yr: float | None
    eps: float | None
    cfo_quality_tier: str | None
    capex_tier: str | None
    capital_allocation_pattern: str | None

    # 10-year history (sorted ascending by year)
    history: pd.DataFrame  # columns: year, sales, net_profit, roe_pct, roce_pct


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------
def load_tearsheet_data(company_id: str, conn: sqlite3.Connection) -> TearsheetData:
    """Fetch all data required to render a company tearsheet.

    Latest-FY values are taken from the company's most recent year that appears
    in ``financial_ratios`` (handles late filers without 2024-03).
    """
    company_id = company_id.upper()

    # Company meta
    meta = pd.read_sql(
        """
        SELECT c.id, c.company_name, s.broad_sector, s.sub_sector
        FROM companies c
        LEFT JOIN sectors s ON s.company_id = c.id
        WHERE c.id = ?
        """,
        conn,
        params=(company_id,),
    )
    if len(meta) == 0:
        raise ValueError(f"Company '{company_id}' not found in companies table")
    row0 = meta.iloc[0]

    # Determine latest year for this company
    latest_year_row = pd.read_sql(
        "SELECT MAX(year) AS y FROM financial_ratios WHERE company_id = ?",
        conn,
        params=(company_id,),
    )
    latest_year = latest_year_row["y"].iloc[0]
    if latest_year is None:
        # fall back to market_cap
        latest_year_row = pd.read_sql(
            "SELECT MAX(year) AS y FROM market_cap WHERE company_id = ?",
            conn,
            params=(company_id,),
        )
        latest_year = str(latest_year_row["y"].iloc[0])

    # Latest ratios
    fr = pd.read_sql(
        """
        SELECT * FROM financial_ratios
        WHERE company_id = ? AND year = ?
        """,
        conn,
        params=(company_id, latest_year),
    )
    fr_dict: dict[str, Any] = {}
    if len(fr) > 0:
        fr_dict = fr.iloc[0].to_dict()

    # Market cap / valuation (year stored as INTEGER in market_cap table)
    try:
        mc_year = int(str(latest_year).split("-")[0])
    except (ValueError, IndexError):
        mc_year = None
    mc_dict: dict[str, Any] = {}
    if mc_year is not None:
        mc = pd.read_sql(
            "SELECT * FROM market_cap WHERE company_id = ? AND year = ?",
            conn,
            params=(company_id, mc_year),
        )
        if len(mc) > 0:
            mc_dict = mc.iloc[0].to_dict()
    if not mc_dict:
        # fallback: latest available market_cap row
        mc = pd.read_sql(
            "SELECT * FROM market_cap WHERE company_id = ? ORDER BY year DESC LIMIT 1",
            conn,
            params=(company_id,),
        )
        if len(mc) > 0:
            mc_dict = mc.iloc[0].to_dict()

    # 10-year history (Revenue, Net Profit, ROE, ROCE)
    hist = pd.read_sql(
        """
        SELECT pl.year, pl.sales, pl.net_profit,
               fr.return_on_equity_pct AS roe_pct, fr.roce_pct AS roce_pct
        FROM profitandloss pl
        LEFT JOIN financial_ratios fr ON fr.company_id = pl.company_id AND fr.year = pl.year
        WHERE pl.company_id = ?
        ORDER BY pl.year DESC
        LIMIT 10
        """,
        conn,
        params=(company_id,),
    )
    hist = hist.sort_values("year").reset_index(drop=True)

    def _f(d: dict, key: str) -> float | None:
        v = d.get(key)
        if v is None:
            return None
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        return None if pd.isna(fv) else fv

    def _s(d: dict, key: str) -> str | None:
        v = d.get(key)
        if v is None:
            return None
        return str(v) if not pd.isna(v) else None

    return TearsheetData(
        company_id=company_id,
        company_name=str(row0["company_name"]),
        sector=_s(row0.to_dict(), "broad_sector"),
        sub_sector=_s(row0.to_dict(), "sub_sector"),
        market_cap_crore=_f(mc_dict, "market_cap_crore"),
        pe_ratio=_f(mc_dict, "pe_ratio"),
        pb_ratio=_f(mc_dict, "pb_ratio"),
        roe_pct=_f(fr_dict, "return_on_equity_pct"),
        roce_pct=_f(fr_dict, "roce_pct"),
        debt_to_equity=_f(fr_dict, "debt_to_equity"),
        dividend_yield_pct=_f(mc_dict, "dividend_yield_pct"),
        pat_cagr_5yr=_f(fr_dict, "pat_cagr_5yr"),
        revenue_cagr_5yr=_f(fr_dict, "revenue_cagr_5yr"),
        eps=_f(fr_dict, "earnings_per_share"),
        cfo_quality_tier=_s(fr_dict, "cfo_quality_tier"),
        capex_tier=_s(fr_dict, "capex_tier"),
        capital_allocation_pattern=_s(fr_dict, "capital_allocation_pattern"),
        history=hist,
    )


# ---------------------------------------------------------------------------
# Chart helpers (matplotlib)
# ---------------------------------------------------------------------------
def _fig_to_image(fig: plt.Figure, width_cm: float, height_cm: float) -> Image:
    """Convert a matplotlib figure to a ReportLab Image flowable."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf, width=width_cm * cm, height=height_cm * cm)
    img.hAlign = "CENTER"
    return img


def _format_crore(val: float) -> str:
    """Format INR Crore values with human-friendly suffixes (Cr / L Cr).

    Uses "Rs." prefix because built-in Helvetica lacks the U+20B9 Rupee glyph.
    """
    if val is None or pd.isna(val):
        return "—"
    abs_val = abs(val)
    if abs_val >= 100000:  # >= 10 Lakh Cr -> L Cr
        return f"Rs {val/100000:.2f} L Cr"
    if abs_val >= 1000:  # >= 1,000 Cr -> thousand Cr
        return f"Rs {val/1000:.1f}k Cr"
    return f"Rs {val:,.0f} Cr"


def make_revenue_bar_chart(
    hist: pd.DataFrame, width_cm: float = 8.0, height_cm: float = 4.5
) -> Image:
    """10-year Revenue bar chart."""
    fig_w = max(width_cm / 2.54, 3.0)
    fig_h = max(height_cm / 2.54, 2.0)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    years = hist["year"].apply(lambda y: str(y)[:4]).tolist()
    vals = hist["sales"].fillna(0).tolist()
    bars = ax.bar(years, vals, color=NAVY_HEX, edgecolor="white", linewidth=0.5)
    ax.set_title("Revenue (Rs Cr)", fontsize=9, fontweight="bold", color=NAVY_HEX, pad=6)
    ax.tick_params(axis="both", labelsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"{x/1000:.0f}k" if x >= 1000 else f"{x:.0f}")
    )
    for bar in bars:
        h = bar.get_height()
        if h > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                h,
                f"{h/1000:.0f}k" if h >= 1000 else f"{h:.0f}",
                ha="center",
                va="bottom",
                fontsize=5.5,
                color=NAVY_HEX,
            )
    fig.tight_layout(pad=0.5)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


def make_net_profit_bar_chart(
    hist: pd.DataFrame, width_cm: float = 8.0, height_cm: float = 4.5
) -> Image:
    """10-year Net Profit bar chart."""
    fig_w = max(width_cm / 2.54, 3.0)
    fig_h = max(height_cm / 2.54, 2.0)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    years = hist["year"].apply(lambda y: str(y)[:4]).tolist()
    vals = hist["net_profit"].fillna(0).tolist()
    colors_list = ["#548235" if v >= 0 else "#C00000" for v in vals]
    ax.bar(years, vals, color=colors_list, edgecolor="white", linewidth=0.5)
    ax.set_title("Net Profit (Rs Cr)", fontsize=9, fontweight="bold", color=NAVY_HEX, pad=6)
    ax.tick_params(axis="both", labelsize=7)
    ax.axhline(0, color="grey", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"{x/1000:.0f}k" if abs(x) >= 1000 else f"{x:.0f}")
    )
    fig.tight_layout(pad=0.5)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


def make_roe_roce_line_chart(
    hist: pd.DataFrame, width_cm: float = 17.0, height_cm: float = 5.5
) -> Image:
    """ROE & ROCE dual-axis line chart."""
    fig_w = max(width_cm / 2.54, 5.0)
    fig_h = max(height_cm / 2.54, 2.5)
    fig, ax1 = plt.subplots(figsize=(fig_w, fig_h))
    years = hist["year"].apply(lambda y: str(y)[:4]).tolist()
    roe = hist["roe_pct"].tolist()
    roce = hist["roce_pct"].tolist()

    ax1.plot(years, roe, marker="o", color="#1F4E78", linewidth=2, label="ROE %", markersize=4)
    ax1.set_ylabel("ROE %", color=NAVY_HEX, fontsize=8)
    ax1.tick_params(axis="y", labelsize=7, labelcolor=NAVY_HEX)
    ax1.tick_params(axis="x", labelsize=7)
    ax1.spines["top"].set_visible(False)

    ax2 = ax1.twinx()
    ax2.plot(
        years,
        roce,
        marker="s",
        color="#C00000",
        linewidth=2,
        label="ROCE %",
        markersize=4,
        linestyle="--",
    )
    ax2.set_ylabel("ROCE %", color="#C00000", fontsize=8)
    ax2.tick_params(axis="y", labelsize=7, labelcolor="#C00000")
    ax2.spines["top"].set_visible(False)

    ax1.set_title("ROE vs ROCE (%)", fontsize=9, fontweight="bold", color=NAVY_HEX, pad=6)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=7, frameon=False)
    ax1.grid(axis="y", alpha=0.3)
    fig.tight_layout(pad=0.5)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


# ---------------------------------------------------------------------------
# KPI tile builder
# ---------------------------------------------------------------------------
def _fmt_pct(val: float | None, suffix: str = "%") -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{val:.1f}{suffix}"


def _fmt_num(val: float | None, decimals: int = 1) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{val:,.{decimals}f}"


def _fmt_ratio(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{val:.2f}"


def build_kpi_tiles(data: TearsheetData) -> Table:
    """Return a 2x3 Table of KPI tiles."""
    tiles = [
        ("Market Cap", _format_crore(data.market_cap_crore)),
        ("P/E Ratio", _fmt_ratio(data.pe_ratio)),
        ("ROE", _fmt_pct(data.roe_pct)),
        ("ROCE", _fmt_pct(data.roce_pct)),
        ("D/E Ratio", _fmt_ratio(data.debt_to_equity)),
        ("5yr PAT CAGR", _fmt_pct(data.pat_cagr_5yr)),
    ]

    # Build a Table of Table (each tile is its own 2-row table)
    tile_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 1), (-1, 1), LIGHT_GREY),
            ("TEXTCOLOR", (0, 1), (-1, 1), NAVY),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 1), (-1, 1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("TOPPADDING", (0, 0), (-1, 0), 4),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
            ("TOPPADDING", (0, 1), (-1, 1), 6),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFBFBF")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#BFBFBF")),
        ]
    )

    gap = 0.25 * cm
    tile_width = (CONTENT_WIDTH - 2 * gap) / 3.0
    tile_objs: list[Table] = []
    for label, value in tiles:
        t = Table([[label], [value]], colWidths=[tile_width])
        t.setStyle(tile_style)
        tile_objs.append(t)

    grid = Table(
        [
            [tile_objs[0], "", tile_objs[1], "", tile_objs[2]],
            [""],
            [tile_objs[3], "", tile_objs[4], "", tile_objs[5]],
        ],
        colWidths=[tile_width, gap, tile_width, gap, tile_width],
        rowHeights=[None, 0.25 * cm, None],
    )
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return grid


# ---------------------------------------------------------------------------
# Header bar
# ---------------------------------------------------------------------------
def build_header_bar(data: TearsheetData) -> Table:
    """Navy header bar with company name + ticker."""
    name_style = ParagraphStyle(
        "HeaderName",
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=WHITE,
        leading=20,
        spaceAfter=2,
    )
    sector_style = ParagraphStyle(
        "HeaderSector",
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#D9E2F3"),
        leading=12,
    )
    ticker_style = ParagraphStyle(
        "HeaderTicker",
        fontName="Helvetica-Bold",
        fontSize=14,
        textColor=WHITE,
        alignment=2,  # right
    )

    sector_line = ""
    if data.sector:
        sector_line = data.sector
        if data.sub_sector:
            sector_line += f"  •  {data.sub_sector}"

    left_cell = [
        Paragraph(data.company_name, name_style),
        Paragraph(sector_line, sector_style),
    ]
    right_cell = Paragraph(data.company_id, ticker_style)

    ticker_w = 3.5 * cm
    header_tbl = Table(
        [[left_cell, right_cell]],
        colWidths=[CONTENT_WIDTH - ticker_w, ticker_w],
    )
    header_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 12),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("RIGHTPADDING", (1, 0), (-1, -1), 12),
            ]
        )
    )
    return header_tbl


# ---------------------------------------------------------------------------
# Page 1 assembly
# ---------------------------------------------------------------------------
def _section_title(text: str) -> Paragraph:
    style = ParagraphStyle(
        "SectionTitle",
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=NAVY,
        spaceBefore=10,
        spaceAfter=6,
        leading=13,
    )
    return Paragraph(text, style)


def build_page1_flowables(data: TearsheetData) -> list:
    """Return the list of Platypus flowables making up Page 1."""
    flowables: list = []

    flowables.append(build_header_bar(data))
    flowables.append(Spacer(1, 0.4 * cm))

    # Subtitle line
    subtitle_style = ParagraphStyle(
        "Subtitle",
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=GREY,
        alignment=2,
    )
    latest_yr = data.history["year"].iloc[-1] if len(data.history) > 0 else ""
    flowables.append(Paragraph(f"Tearsheet as of FY {latest_yr}", subtitle_style))
    flowables.append(Spacer(1, 0.3 * cm))

    # 6 KPI tiles
    flowables.append(_section_title("Key Performance Indicators"))
    flowables.append(build_kpi_tiles(data))
    flowables.append(Spacer(1, 0.5 * cm))

    # Side-by-side Revenue & Net Profit bars
    flowables.append(_section_title("10-Year Revenue & Net Profit Trend"))
    chart_gap = 0.3 * cm
    chart_width = (CONTENT_WIDTH - chart_gap) / 2.0
    rev_chart = make_revenue_bar_chart(data.history, width_cm=chart_width / cm)
    np_chart = make_net_profit_bar_chart(data.history, width_cm=chart_width / cm)
    chart_row = Table(
        [[rev_chart, "", np_chart]],
        colWidths=[chart_width, chart_gap, chart_width],
    )
    chart_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flowables.append(chart_row)
    flowables.append(Spacer(1, 0.3 * cm))

    # ROE/ROCE dual axis line chart
    flowables.append(_section_title("Return Ratios — ROE vs ROCE"))
    flowables.append(
        make_roe_roce_line_chart(
            data.history,
            width_cm=CONTENT_WIDTH / cm,
            height_cm=5.5,
        )
    )

    return flowables


def build_page2_flowables(data: TearsheetData) -> list:
    """Return Page-2 placeholder flowables (to be extended in later days).

    Currently renders:
        * Cash Flow Quality summary (CFO quality tier, CapEx tier, pattern)
        * Valuation snapshot (P/B, Div Yield, 5yr Revenue CAGR, EPS)
    """
    flowables: list = []

    flowables.append(_section_title("Cash Flow Quality & Capital Allocation"))
    cf_rows = [
        ["Metric", "Value"],
        ["CFO Quality Tier", data.cfo_quality_tier or "—"],
        ["CapEx Tier", data.capex_tier or "—"],
        ["Capital Allocation Pattern", data.capital_allocation_pattern or "—"],
        ["5yr Revenue CAGR", _fmt_pct(data.revenue_cagr_5yr)],
        ["Dividend Yield", _fmt_pct(data.dividend_yield_pct)],
        ["P/B Ratio", _fmt_ratio(data.pb_ratio)],
        ["EPS (Rs)", _fmt_num(data.eps, decimals=2)],
    ]
    cf_tbl = Table(cf_rows, colWidths=[7 * cm, 7 * cm])
    cf_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    flowables.append(cf_tbl)
    flowables.append(Spacer(1, 0.5 * cm))

    note_style = ParagraphStyle(
        "FootNote",
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=GREY,
        leading=11,
    )
    flowables.append(
        Paragraph(
            "Note: Pros/cons bullets, peer comparison, and valuation commentary "
            "will be added in subsequent days (Sprint 5 Days 34-35).",
            note_style,
        )
    )
    return flowables


# ---------------------------------------------------------------------------
# PDF generator
# ---------------------------------------------------------------------------
def generate_tearsheet_pdf(
    data: TearsheetData,
    output_path: Path,
) -> Path:
    """Render a 2-page tearsheet PDF for one company. Returns the written path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=f"{data.company_name} ({data.company_id}) — Nifty 100 Tearsheet",
        author="Nifty 100 Financial Intelligence Platform",
    )

    story = []
    story.extend(build_page1_flowables(data))
    story.append(PageBreak())
    story.extend(build_page2_flowables(data))

    doc.build(story)
    logger.info("Tearsheet written to %s", output_path)
    return output_path


def generate_tearsheet_for_company(
    company_id: str,
    conn: sqlite3.Connection,
    output_path: Path,
) -> Path:
    """High-level convenience: load data + render PDF."""
    data = load_tearsheet_data(company_id, conn)
    return generate_tearsheet_pdf(data, output_path)


# ---------------------------------------------------------------------------
# Batch helper (for Day 34/35 — generates all 92 tearsheets)
# ---------------------------------------------------------------------------
def generate_all_tearsheets(
    conn: sqlite3.Connection,
    output_dir: Path,
) -> list[Path]:
    """Generate tearsheet PDFs for every company in companies table.

    Returns a list of output paths. (Used by Day 34/35.)
    """
    companies = pd.read_sql("SELECT id FROM companies ORDER BY company_name", conn)
    paths: list[Path] = []
    for _, r in companies.iterrows():
        cid = r["id"]
        out_path = output_dir / f"tearsheet_{cid}.pdf"
        generate_tearsheet_for_company(cid, conn, out_path)
        paths.append(out_path)
    return paths


__all__ = [
    "NAVY",
    "NAVY_HEX",
    "TearsheetData",
    "build_header_bar",
    "build_kpi_tiles",
    "build_page1_flowables",
    "build_page2_flowables",
    "generate_all_tearsheets",
    "generate_tearsheet_for_company",
    "generate_tearsheet_pdf",
    "load_tearsheet_data",
    "make_net_profit_bar_chart",
    "make_revenue_bar_chart",
    "make_roe_roce_line_chart",
]
