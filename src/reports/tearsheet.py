"""Sprint 5 Day 33 - PDF Tearsheet Template (ReportLab).

Generates a 2-page company tearsheet PDF for any Nifty-100 company.

**Page 1 layout:**
    1. Navy header bar - company name (white text) + ticker code (bottom-right)
    2. Six KPI tiles arranged 2 rows x 3 columns:
         Market Cap | P/E Ratio | ROE %
         ROCE %     | D/E Ratio | 5yr PAT CAGR
    3. 10-year Revenue bar chart  |  10-year Net Profit bar chart  (side-by-side)
    4. ROE & ROCE dual-axis line chart (overlaid)

**Page 2 layout:**
    1. Balance Sheet composition stacked bar chart (equity, borrowings,
       other liabilities) across available years.
    2. Cash Flow waterfall for the latest year (CFO, CFI, CFF, Net Cash Flow).
    3. Pros section - green bullet points (auto-generated, from Day 30).
    4. Cons section - red bullet points (auto-generated, from Day 30).
    5. Capital Allocation badge (coloured by pattern).

All text in tables uses ``Paragraph`` flowables with WORDWRAP enabled to
prevent overflow on long pros/cons text.  Charts are rendered with matplotlib
and embedded as PNG via ReportLab Platypus.  The navy brand colour is
``#1F4E78`` matching the Excel header styling used elsewhere in the project.
"""

from __future__ import annotations

import io
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
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
ACCENT_GREEN_HEX = "#548235"
ACCENT_RED = colors.HexColor("#C00000")
ACCENT_RED_HEX = "#C00000"
ACCENT_AMBER = colors.HexColor("#BF8F00")
ACCENT_AMBER_HEX = "#BF8F00"
WHITE = colors.white

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = RIGHT_MARGIN = 1.5 * cm
TOP_MARGIN = BOTTOM_MARGIN = 1.5 * cm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

# Capital Allocation pattern -> badge colour mapping
PATTERN_BADGE_COLORS: dict[str, colors.Color] = {
    "Shareholder Returns": ACCENT_GREEN,
    "Reinvestor": NAVY,
    "Mixed": ACCENT_AMBER,
    "Growth Funded by Debt": ACCENT_RED,
    "Distress Signal": ACCENT_RED,
    "Liquidating Assets": ACCENT_AMBER,
    "Cash Accumulator": ACCENT_GREEN,
    "Pre-Revenue": GREY,
}


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
    latest_year: str

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

    # 10-year P&L history (sorted ascending)
    history: pd.DataFrame  # columns: year, sales, net_profit, roe_pct, roce_pct

    # Balance sheet history for stacked bar
    bs_history: pd.DataFrame  # columns: year, equity, borrowings, other_liabilities

    # Latest-year cash flow (waterfall)
    cfo_latest: float | None
    cfi_latest: float | None
    cff_latest: float | None
    net_cf_latest: float | None

    # Auto-generated pros/cons text (already sorted by confidence desc)
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------
def load_tearsheet_data(company_id: str, conn: sqlite3.Connection) -> TearsheetData:
    """Fetch all data required to render a company tearsheet.

    Latest-FY values come from the company's most recent year present in
    ``financial_ratios`` (handles late filers that have not yet filed 2024-03).
    """
    company_id = company_id.upper()

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

    # Latest year
    ly_row = pd.read_sql(
        "SELECT MAX(year) AS y FROM financial_ratios WHERE company_id = ?",
        conn,
        params=(company_id,),
    )
    latest_year = ly_row["y"].iloc[0]
    if latest_year is None:
        ly_row = pd.read_sql(
            "SELECT MAX(year) AS y FROM cashflow WHERE company_id = ?",
            conn,
            params=(company_id,),
        )
        latest_year = str(ly_row["y"].iloc[0])

    fr = pd.read_sql(
        "SELECT * FROM financial_ratios WHERE company_id = ? AND year = ?",
        conn,
        params=(company_id, latest_year),
    )
    fr_dict: dict[str, Any] = fr.iloc[0].to_dict() if len(fr) > 0 else {}

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
        mc = pd.read_sql(
            "SELECT * FROM market_cap WHERE company_id = ? ORDER BY year DESC LIMIT 1",
            conn,
            params=(company_id,),
        )
        if len(mc) > 0:
            mc_dict = mc.iloc[0].to_dict()

    # 10-year P&L history
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

    # Balance sheet history (up to 10 most recent years)
    bs = pd.read_sql(
        """
        SELECT year, equity_capital, reserves, borrowings, other_liabilities
        FROM balancesheet
        WHERE company_id = ?
        ORDER BY year DESC
        LIMIT 10
        """,
        conn,
        params=(company_id,),
    )
    bs = bs.sort_values("year").reset_index(drop=True)
    bs["equity"] = bs["equity_capital"].fillna(0) + bs["reserves"].fillna(0)
    bs_history = bs[["year", "equity", "borrowings", "other_liabilities"]].copy()

    # Cash flow latest year
    cf = pd.read_sql(
        """
        SELECT operating_activity, investing_activity, financing_activity, net_cash_flow
        FROM cashflow WHERE company_id = ? AND year = ?
        """,
        conn,
        params=(company_id, latest_year),
    )
    cfo = cfi = cff = ncf = None
    if len(cf) > 0:
        cfo = _safe_float(cf.iloc[0]["operating_activity"])
        cfi = _safe_float(cf.iloc[0]["investing_activity"])
        cff = _safe_float(cf.iloc[0]["financing_activity"])
        ncf = _safe_float(cf.iloc[0]["net_cash_flow"])

    # Pros/cons - try CSV first, fall back to prosandcons table
    pros: list[str] = []
    cons: list[str] = []
    try:
        pc_csv = pd.read_csv(
            Path(__file__).resolve().parents[2] / "output" / "pros_cons_generated.csv"
        )
        co = pc_csv[pc_csv["company_id"] == company_id].sort_values(
            "confidence_pct", ascending=False
        )
        pros = co[co["type"] == "pro"]["text"].astype(str).tolist()
        cons = co[co["type"] == "con"]["text"].astype(str).tolist()
    except (FileNotFoundError, pd.errors.EmptyDataError, KeyError):
        pass
    if not pros or not cons:
        pcdb = pd.read_sql(
            "SELECT pros, cons FROM prosandcons WHERE company_id = ?",
            conn,
            params=(company_id,),
        )
        if len(pcdb) > 0:
            p_text = str(pcdb.iloc[0]["pros"] or "")
            c_text = str(pcdb.iloc[0]["cons"] or "")
            if not pros and p_text and p_text.lower() != "nan":
                pros = [line.strip(" •-") for line in p_text.split("\n") if line.strip()]
            if not cons and c_text and c_text.lower() != "nan":
                cons = [line.strip(" •-") for line in c_text.split("\n") if line.strip()]

    def _f(d: dict, key: str) -> float | None:
        return _safe_float(d.get(key))

    def _s(d: dict, key: str) -> str | None:
        v = d.get(key)
        if v is None or pd.isna(v):
            return None
        return str(v)

    return TearsheetData(
        company_id=company_id,
        company_name=str(row0["company_name"]),
        sector=_s(row0.to_dict(), "broad_sector"),
        sub_sector=_s(row0.to_dict(), "sub_sector"),
        latest_year=str(latest_year),
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
        bs_history=bs_history,
        cfo_latest=cfo,
        cfi_latest=cfi,
        cff_latest=cff,
        net_cf_latest=ncf,
        pros=pros,
        cons=cons,
    )


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(fv) else fv


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


def _format_crore(val: float | None) -> str:
    """Format INR Crore values with human-friendly suffixes.

    Uses ASCII "Rs" because built-in Helvetica lacks the Rupee-sign glyph.
    """
    if val is None or pd.isna(val):
        return "-"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 100000:
        return f"{sign}Rs {abs_val/100000:.2f} L Cr"
    if abs_val >= 1000:
        return f"{sign}Rs {abs_val/1000:.1f}k Cr"
    return f"{sign}Rs {abs_val:,.0f} Cr"


def _short_crore_axis(v: float, _pos: Any = None) -> str:
    """Matplotlib tick formatter for large crore values."""
    if abs(v) >= 100000:
        return f"{v/100000:.1f}L"
    if abs(v) >= 1000:
        return f"{v/1000:.0f}k"
    return f"{v:.0f}"


def make_revenue_bar_chart(hist: pd.DataFrame, width_cm: float, height_cm: float) -> Image:
    """10-year Revenue bar chart."""
    fig, ax = plt.subplots(figsize=(max(width_cm / 2.54, 3), max(height_cm / 2.54, 2)))
    years = hist["year"].apply(lambda y: str(y)[:4]).tolist()
    vals = hist["sales"].fillna(0).tolist()
    bars = ax.bar(years, vals, color=NAVY_HEX, edgecolor="white", linewidth=0.5)
    ax.set_title("Revenue (Rs Cr)", fontsize=8, fontweight="bold", color=NAVY_HEX, pad=4)
    ax.tick_params(axis="both", labelsize=6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_short_crore_axis))
    for bar in bars:
        h = bar.get_height()
        if h > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                h,
                _short_crore_axis(h),
                ha="center",
                va="bottom",
                fontsize=5,
                color=NAVY_HEX,
            )
    fig.tight_layout(pad=0.4)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


def make_net_profit_bar_chart(hist: pd.DataFrame, width_cm: float, height_cm: float) -> Image:
    """10-year Net Profit bar chart (green/red for positive/negative)."""
    fig, ax = plt.subplots(figsize=(max(width_cm / 2.54, 3), max(height_cm / 2.54, 2)))
    years = hist["year"].apply(lambda y: str(y)[:4]).tolist()
    vals = hist["net_profit"].fillna(0).tolist()
    colors_list = [ACCENT_GREEN_HEX if v >= 0 else ACCENT_RED_HEX for v in vals]
    ax.bar(years, vals, color=colors_list, edgecolor="white", linewidth=0.5)
    ax.set_title("Net Profit (Rs Cr)", fontsize=8, fontweight="bold", color=NAVY_HEX, pad=4)
    ax.tick_params(axis="both", labelsize=6)
    ax.axhline(0, color="grey", linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_short_crore_axis))
    fig.tight_layout(pad=0.4)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


def make_roe_roce_line_chart(hist: pd.DataFrame, width_cm: float, height_cm: float) -> Image:
    """ROE & ROCE dual-axis line chart."""
    fig, ax1 = plt.subplots(figsize=(max(width_cm / 2.54, 5), max(height_cm / 2.54, 2.5)))
    years = hist["year"].apply(lambda y: str(y)[:4]).tolist()
    roe = hist["roe_pct"].tolist()
    roce = hist["roce_pct"].tolist()
    ax1.plot(years, roe, marker="o", color=NAVY_HEX, linewidth=1.8, label="ROE %", markersize=3.5)
    ax1.set_ylabel("ROE %", color=NAVY_HEX, fontsize=7)
    ax1.tick_params(axis="y", labelsize=6, labelcolor=NAVY_HEX)
    ax1.tick_params(axis="x", labelsize=6)
    ax1.spines["top"].set_visible(False)
    ax2 = ax1.twinx()
    ax2.plot(
        years,
        roce,
        marker="s",
        color=ACCENT_RED_HEX,
        linewidth=1.8,
        label="ROCE %",
        markersize=3.5,
        linestyle="--",
    )
    ax2.set_ylabel("ROCE %", color=ACCENT_RED_HEX, fontsize=7)
    ax2.tick_params(axis="y", labelsize=6, labelcolor=ACCENT_RED_HEX)
    ax2.spines["top"].set_visible(False)
    ax1.set_title("ROE vs ROCE (%)", fontsize=8, fontweight="bold", color=NAVY_HEX, pad=4)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=6, frameon=False)
    ax1.grid(axis="y", alpha=0.3)
    fig.tight_layout(pad=0.4)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


def make_balance_sheet_stacked_chart(
    bs_hist: pd.DataFrame, width_cm: float, height_cm: float
) -> Image:
    """Balance Sheet composition stacked bar chart (equity, borrowings, other liab)."""
    fig, ax = plt.subplots(figsize=(max(width_cm / 2.54, 5), max(height_cm / 2.54, 2.5)))
    years = bs_hist["year"].apply(lambda y: str(y)[:4]).tolist()
    eq = bs_hist["equity"].fillna(0).tolist()
    bo = bs_hist["borrowings"].fillna(0).tolist()
    ol = bs_hist["other_liabilities"].fillna(0).tolist()
    x = np.arange(len(years))
    ax.bar(x, eq, label="Equity (Cap + Reserves)", color=NAVY_HEX, edgecolor="white", linewidth=0.4)
    ax.bar(
        x,
        bo,
        bottom=eq,
        label="Borrowings",
        color=ACCENT_AMBER_HEX,
        edgecolor="white",
        linewidth=0.4,
    )
    ax.bar(
        x,
        ol,
        bottom=[a + b for a, b in zip(eq, bo, strict=True)],
        label="Other Liabilities",
        color="#A6A6A6",
        edgecolor="white",
        linewidth=0.4,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(years, fontsize=6)
    ax.tick_params(axis="y", labelsize=6)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_short_crore_axis))
    ax.set_title(
        "Balance Sheet Composition (Rs Cr)", fontsize=8, fontweight="bold", color=NAVY_HEX, pad=4
    )
    ax.legend(loc="upper left", fontsize=6, frameon=False, ncol=3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout(pad=0.4)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


def make_cashflow_waterfall(
    cfo: float | None,
    cfi: float | None,
    cff: float | None,
    ncf: float | None,
    width_cm: float,
    height_cm: float,
) -> Image:
    """Cash flow waterfall: CFO, CFI, CFF, Net Cash Flow for the latest FY."""
    fig, ax = plt.subplots(figsize=(max(width_cm / 2.54, 4), max(height_cm / 2.54, 2.3)))
    labels = ["CFO", "CFI", "CFF", "Net CF"]
    values = [v if v is not None else 0.0 for v in (cfo, cfi, cff)]
    if ncf is None:
        ncf = sum(values)
    values.append(ncf)
    colours = []
    for i, v in enumerate(values):
        if i == 3:  # Net
            colours.append(NAVY_HEX if v >= 0 else ACCENT_RED_HEX)
        else:
            colours.append(ACCENT_GREEN_HEX if v >= 0 else ACCENT_RED_HEX)
    # Cumulative positions for waterfall
    cum = 0.0
    bottoms: list[float] = []
    heights: list[float] = []
    for i, v in enumerate(values):
        if i < 3:
            bottoms.append(cum if v >= 0 else cum + v)
            heights.append(abs(v))
            cum += v
        else:
            # Net CF as standalone bar starting at 0
            bottoms.append(0 if v >= 0 else v)
            heights.append(abs(v))
    x = np.arange(len(labels))
    ax.bar(x, heights, bottom=bottoms, color=colours, edgecolor="white", linewidth=0.5, width=0.6)
    # Value labels on top
    for i, v in enumerate(values):
        top = bottoms[i] + heights[i]
        ax.text(
            x[i],
            top,
            _short_crore_axis(v),
            ha="center",
            va="bottom" if v >= 0 else "top",
            fontsize=6,
            color="black",
        )
    ax.axhline(0, color="grey", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7)
    ax.tick_params(axis="y", labelsize=6)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_short_crore_axis))
    ax.set_title(
        "Cash Flow Waterfall - Latest FY (Rs Cr)",
        fontsize=8,
        fontweight="bold",
        color=NAVY_HEX,
        pad=4,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout(pad=0.4)
    return _fig_to_image(fig, width_cm=width_cm, height_cm=height_cm)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------
def _fmt_pct(val: float | None, suffix: str = "%") -> str:
    if val is None or pd.isna(val):
        return "-"
    return f"{val:.1f}{suffix}"


def _fmt_num(val: float | None, decimals: int = 1) -> str:
    if val is None or pd.isna(val):
        return "-"
    return f"{val:,.{decimals}f}"


def _fmt_ratio(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "-"
    return f"{val:.2f}"


# ---------------------------------------------------------------------------
# Paragraph styles (wordwrap via Paragraph)
# ---------------------------------------------------------------------------
def _get_styles() -> dict[str, ParagraphStyle]:
    """Return a dict of reusable paragraph styles with word wrap."""
    base = getSampleStyleSheet()
    return {
        "cell": ParagraphStyle(
            "WrapCell",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.black,
        ),
        "cell_bold": ParagraphStyle(
            "WrapCellBold",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=NAVY,
        ),
        "bullet_pro": ParagraphStyle(
            "BulletPro",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=ACCENT_GREEN,
            leftIndent=10,
            bulletIndent=0,
            spaceAfter=2,
        ),
        "bullet_con": ParagraphStyle(
            "BulletCon",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=ACCENT_RED,
            leftIndent=10,
            bulletIndent=0,
            spaceAfter=2,
        ),
        "section": ParagraphStyle(
            "SectionTitle",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=4,
            leading=12,
        ),
        "badge": ParagraphStyle(
            "BadgeText",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=WHITE,
            alignment=1,
            leading=11,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=GREY,
            alignment=2,
            leading=10,
        ),
        "header_name": ParagraphStyle(
            "HeaderName",
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=WHITE,
            leading=20,
            spaceAfter=2,
        ),
        "header_sector": ParagraphStyle(
            "HeaderSector",
            fontName="Helvetica",
            fontSize=9,
            textColor=colors.HexColor("#D9E2F3"),
            leading=12,
        ),
        "header_ticker": ParagraphStyle(
            "HeaderTicker",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=WHITE,
            alignment=2,
            leading=18,
        ),
    }


def _make_para(text: str, style: ParagraphStyle) -> Paragraph:
    """Wrap text in a Paragraph (which supports WORDWRAP)."""
    return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


# ---------------------------------------------------------------------------
# KPI tiles
# ---------------------------------------------------------------------------
def build_kpi_tiles(data: TearsheetData, styles: dict[str, ParagraphStyle]) -> Table:
    """Return a 2x3 Table of KPI tiles using Paragraphs (word-wrap safe)."""
    tiles = [
        ("Market Cap", _format_crore(data.market_cap_crore)),
        ("P/E Ratio", _fmt_ratio(data.pe_ratio)),
        ("ROE", _fmt_pct(data.roe_pct)),
        ("ROCE", _fmt_pct(data.roce_pct)),
        ("D/E Ratio", _fmt_ratio(data.debt_to_equity)),
        ("5yr PAT CAGR", _fmt_pct(data.pat_cagr_5yr)),
    ]
    cell_bold = styles["cell_bold"]
    tile_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 1), (-1, 1), LIGHT_GREY),
            ("TEXTCOLOR", (0, 1), (-1, 1), NAVY),
            ("TOPPADDING", (0, 0), (-1, 0), 3),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
            ("TOPPADDING", (0, 1), (-1, 1), 5),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 5),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFBFBF")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#BFBFBF")),
        ]
    )
    gap = 0.2 * cm
    tile_width = (CONTENT_WIDTH - 2 * gap) / 3.0
    tile_objs: list[Table] = []
    for label, value in tiles:
        t = Table(
            [[_make_para(label, cell_bold)], [_make_para(value, cell_bold)]],
            colWidths=[tile_width],
        )
        t.setStyle(tile_style)
        tile_objs.append(t)
    grid = Table(
        [
            [tile_objs[0], "", tile_objs[1], "", tile_objs[2]],
            [""],
            [tile_objs[3], "", tile_objs[4], "", tile_objs[5]],
        ],
        colWidths=[tile_width, gap, tile_width, gap, tile_width],
        rowHeights=[None, 0.2 * cm, None],
    )
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return grid


# ---------------------------------------------------------------------------
# Header bar
# ---------------------------------------------------------------------------
def build_header_bar(data: TearsheetData, styles: dict[str, ParagraphStyle]) -> Table:
    """Navy header bar with company name + ticker."""
    sector_line = ""
    if data.sector:
        sector_line = data.sector
        if data.sub_sector:
            sector_line += f"  -  {data.sub_sector}"

    left_cell = [
        _make_para(data.company_name, styles["header_name"]),
        _make_para(sector_line, styles["header_sector"]),
    ]
    right_cell = _make_para(data.company_id, styles["header_ticker"])

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
                ("LEFTPADDING", (0, 0), (0, 0), 10),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("RIGHTPADDING", (1, 0), (-1, -1), 10),
            ]
        )
    )
    return header_tbl


# ---------------------------------------------------------------------------
# Capital Allocation badge
# ---------------------------------------------------------------------------
def build_capital_allocation_badge(data: TearsheetData, styles: dict[str, ParagraphStyle]) -> Table:
    """Coloured pill badge showing the capital-allocation pattern."""
    pattern = data.capital_allocation_pattern or "N/A"
    bg = PATTERN_BADGE_COLORS.get(pattern, GREY)
    badge_text = _make_para(f"Capital Allocation: {pattern}", styles["badge"])
    tbl = Table([[badge_text]], colWidths=[7.5 * cm])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("ROUNDEDCORNERS", [4, 4, 4, 4]),
                ("BOX", (0, 0), (-1, -1), 0.5, bg),
            ]
        )
    )
    return tbl


# ---------------------------------------------------------------------------
# Pros/Cons bulleted lists (with word wrap)
# ---------------------------------------------------------------------------
def build_pros_cons_table(data: TearsheetData, styles: dict[str, ParagraphStyle]) -> Table:
    """Two-column table: Pros (green bullets) | Cons (red bullets)."""
    pro_style = styles["bullet_pro"]
    con_style = styles["bullet_con"]

    def _bullets(items: list[str], style: ParagraphStyle, max_items: int = 6) -> list:
        bullets = []
        for txt in items[:max_items]:
            txt = str(txt).strip()
            if txt:
                bullets.append(Paragraph(f"\u2022  {txt}", style))
        if not bullets:
            bullets.append(Paragraph("\u2022  (none identified)", con_style))
        return bullets

    pros_list = _bullets(data.pros, pro_style)
    cons_list = _bullets(data.cons, con_style)

    col_w = (CONTENT_WIDTH - 0.2 * cm) / 2.0
    # Header row
    header_style = ParagraphStyle(
        "ProConHeader",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=WHITE,
        alignment=1,
        leading=11,
    )
    pro_header = Paragraph("Strengths (Pros)", header_style)
    con_header = Paragraph("Risks / Watch Items (Cons)", header_style)

    # Build the table: header + max(len, len) rows
    n_rows = max(len(pros_list), len(cons_list))
    table_data: list[list] = [[pro_header, "", con_header]]
    for i in range(n_rows):
        p = pros_list[i] if i < len(pros_list) else ""
        c = cons_list[i] if i < len(cons_list) else ""
        table_data.append([p, "", c])

    col_widths = [col_w, 0.2 * cm, col_w]
    tbl = Table(table_data, colWidths=col_widths)
    style_cmds = [
        ("BACKGROUND", (0, 0), (0, 0), ACCENT_GREEN),
        ("BACKGROUND", (2, 0), (2, 0), ACCENT_RED),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
        ("BOX", (0, 0), (0, -1), 0.4, ACCENT_GREEN),
        ("BOX", (2, 0), (2, -1), 0.4, ACCENT_RED),
        ("ROWBACKGROUNDS", (0, 1), (0, -1), [WHITE, colors.HexColor("#F0F6E8")]),
        ("ROWBACKGROUNDS", (2, 1), (2, -1), [WHITE, colors.HexColor("#FBEFEF")]),
    ]
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ---------------------------------------------------------------------------
# Page 1
# ---------------------------------------------------------------------------
def build_page1_flowables(data: TearsheetData) -> list:
    """Return the list of Platypus flowables making up Page 1."""
    styles = _get_styles()
    flowables: list = []

    flowables.append(build_header_bar(data, styles))
    flowables.append(Spacer(1, 0.25 * cm))
    flowables.append(Paragraph(f"Tearsheet as of FY {data.latest_year}", styles["subtitle"]))
    flowables.append(Spacer(1, 0.2 * cm))

    flowables.append(Paragraph("Key Performance Indicators", styles["section"]))
    flowables.append(build_kpi_tiles(data, styles))
    flowables.append(Spacer(1, 0.3 * cm))

    flowables.append(Paragraph("10-Year Revenue &amp; Net Profit Trend", styles["section"]))
    gap = 0.3 * cm
    cw = (CONTENT_WIDTH - gap) / 2.0
    rev_chart = make_revenue_bar_chart(data.history, width_cm=cw / cm, height_cm=4.0)
    np_chart = make_net_profit_bar_chart(data.history, width_cm=cw / cm, height_cm=4.0)
    chart_row = Table([[rev_chart, "", np_chart]], colWidths=[cw, gap, cw])
    chart_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flowables.append(chart_row)
    flowables.append(Spacer(1, 0.2 * cm))

    flowables.append(Paragraph("Return Ratios - ROE vs ROCE", styles["section"]))
    flowables.append(
        make_roe_roce_line_chart(data.history, width_cm=CONTENT_WIDTH / cm, height_cm=4.8)
    )
    return flowables


# ---------------------------------------------------------------------------
# Page 2
# ---------------------------------------------------------------------------
def build_page2_flowables(data: TearsheetData) -> list:
    """Return Page-2 flowables: BS stacked chart, CF waterfall, pros/cons, badge."""
    styles = _get_styles()
    flowables: list = []

    # Balance sheet stacked bar (wider) and CF waterfall (narrower), side-by-side
    flowables.append(Paragraph("Balance Sheet Composition & Cash Flow", styles["section"]))
    charts_gap = 0.2 * cm
    bs_w = 11.0 * cm
    cf_w_cm = (CONTENT_WIDTH - bs_w - charts_gap) / cm
    bs_chart = make_balance_sheet_stacked_chart(data.bs_history, width_cm=bs_w / cm, height_cm=4.5)
    cf_chart_resized = make_cashflow_waterfall(
        data.cfo_latest,
        data.cfi_latest,
        data.cff_latest,
        data.net_cf_latest,
        width_cm=cf_w_cm,
        height_cm=4.5,
    )
    two_chart_row = Table(
        [[bs_chart, "", cf_chart_resized]],
        colWidths=[bs_w, charts_gap, CONTENT_WIDTH - bs_w - charts_gap],
    )
    two_chart_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flowables.append(two_chart_row)
    flowables.append(Spacer(1, 0.25 * cm))

    # Pros/Cons table
    flowables.append(Paragraph("Automated Strengths & Risk Signals", styles["section"]))
    flowables.append(build_pros_cons_table(data, styles))
    flowables.append(Spacer(1, 0.3 * cm))

    # Capital Allocation badge (centred)
    badge = build_capital_allocation_badge(data, styles)
    badge_row = Table([[badge]], colWidths=[CONTENT_WIDTH])
    badge_row.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    flowables.append(badge_row)

    return flowables


# ---------------------------------------------------------------------------
# PDF generator
# ---------------------------------------------------------------------------
def generate_tearsheet_pdf(data: TearsheetData, output_path: Path) -> Path:
    """Render a 2-page tearsheet PDF for one company. Returns the written path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=f"{data.company_name} ({data.company_id}) - Nifty 100 Tearsheet",
        author="Nifty 100 Financial Intelligence Platform",
    )
    story: list = []
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


def generate_all_tearsheets(conn: sqlite3.Connection, output_dir: Path) -> list[Path]:
    """Generate tearsheet PDFs for every company in companies table (Day 34/35)."""
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
    "PATTERN_BADGE_COLORS",
    "TearsheetData",
    "build_capital_allocation_badge",
    "build_header_bar",
    "build_kpi_tiles",
    "build_page1_flowables",
    "build_page2_flowables",
    "build_pros_cons_table",
    "generate_all_tearsheets",
    "generate_tearsheet_for_company",
    "generate_tearsheet_pdf",
    "load_tearsheet_data",
    "make_balance_sheet_stacked_chart",
    "make_cashflow_waterfall",
    "make_net_profit_bar_chart",
    "make_revenue_bar_chart",
    "make_roe_roce_line_chart",
]
