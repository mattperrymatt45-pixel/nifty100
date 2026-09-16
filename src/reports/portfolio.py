"""Sprint 5 Day 35 - Portfolio Summary PDF builder.

Generates ``reports/portfolio/portfolio_summary.pdf`` containing one page per
Nifty-100 company in alphabetical order by ticker. Each page shows the
company name, sector, six top KPIs, and trend arrows comparing the latest
fiscal year to the prior year:

    UP arrow     metric improved in the latest year by more than 2%
    DOWN arrow   metric declined in the latest year by more than 2%
    RIGHT arrow  metric flat within +/- 2% (or NaN / insufficient data)

A relative 2% threshold is used for level metrics (crore values); percentage
metrics use a 2 percentage-point absolute threshold. "Higher is better" is
contextual (e.g., a declining D/E is treated as improvement).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from src.reports.tearsheet import NAVY, _make_para

logger = logging.getLogger(__name__)

ARROW_UP = "\u25b2"
ARROW_DOWN = "\u25bc"
ARROW_FLAT = "\u25b6"
TREND_THRESHOLD_PCT = 2.0  # +/- 2% relative change triggers arrow


@dataclass(frozen=True)
class KPI:
    """Definition of one KPI shown on the portfolio card."""

    label: str
    col_latest: str
    col_prev: str
    fmt: str  # 'pct' | 'ratio' | 'crore'
    higher_is_better: bool = True


PORTFOLIO_KPIS: tuple[KPI, ...] = (
    KPI("Revenue", "sales_latest", "sales_prev", "crore", True),
    KPI("Net Profit", "np_latest", "np_prev", "crore", True),
    KPI("ROE", "roe_latest", "roe_prev", "pct", True),
    KPI("ROCE", "roce_latest", "roce_prev", "pct", True),
    KPI("D/E Ratio", "de_latest", "de_prev", "ratio", False),
    KPI("Net Margin", "npm_latest", "npm_prev", "pct", True),
)


# ---------------------------------------------------------------------------
# Trend calculation
# ---------------------------------------------------------------------------
def _safe(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _fmt(val: float | None, kind: str) -> str:
    if val is None:
        return "-"
    if kind == "pct":
        return f"{val:.1f}%"
    if kind == "ratio":
        return f"{val:.2f}"
    if kind == "crore":
        if abs(val) >= 100000:
            return f"Rs {val/100000:.2f} L Cr"
        if abs(val) >= 1000:
            return f"Rs {val/1000:.1f}k Cr"
        return f"Rs {val:,.0f} Cr"
    return str(val)


def trend_arrow(
    latest: float | None,
    prev: float | None,
    higher_better: bool,
) -> tuple[str, colors.Color]:
    """Return (arrow_char, colour) for the direction of change between years."""
    if latest is None or prev is None:
        return ARROW_FLAT, colors.grey
    delta = latest - prev
    rel = delta * 100 if abs(prev) < 1e-9 else delta / abs(prev) * 100
    if abs(rel) < TREND_THRESHOLD_PCT:
        return ARROW_FLAT, colors.grey
    improving = (delta > 0) if higher_better else (delta < 0)
    return (
        (ARROW_UP, colors.HexColor("#548235"))
        if improving
        else (ARROW_DOWN, colors.HexColor("#C00000"))
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_portfolio_panel(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return one row per company with latest and previous year KPI values."""
    # Financial ratios (rn=1 latest, rn=2 previous)
    fr_wide = pd.read_sql(
        """
        WITH ranked AS (
            SELECT company_id, year,
                   return_on_equity_pct, roce_pct, debt_to_equity, net_profit_margin_pct,
                   ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY year DESC) rn
            FROM financial_ratios
        )
        SELECT company_id,
               MAX(CASE WHEN rn=1 THEN year END) latest_year,
               MAX(CASE WHEN rn=2 THEN year END) prev_year,
               MAX(CASE WHEN rn=1 THEN return_on_equity_pct END) roe_latest,
               MAX(CASE WHEN rn=2 THEN return_on_equity_pct END) roe_prev,
               MAX(CASE WHEN rn=1 THEN roce_pct END) roce_latest,
               MAX(CASE WHEN rn=2 THEN roce_pct END) roce_prev,
               MAX(CASE WHEN rn=1 THEN debt_to_equity END) de_latest,
               MAX(CASE WHEN rn=2 THEN debt_to_equity END) de_prev,
               MAX(CASE WHEN rn=1 THEN net_profit_margin_pct END) npm_latest,
               MAX(CASE WHEN rn=2 THEN net_profit_margin_pct END) npm_prev
        FROM ranked WHERE rn <= 2 GROUP BY company_id
        """,
        conn,
    )
    # P&L sales / net profit
    pl = pd.read_sql(
        """
        SELECT company_id, year, sales, net_profit
        FROM profitandloss
        ORDER BY company_id, year DESC
        """,
        conn,
    )

    def _pl_pick(df: pd.DataFrame, col: str, idx: int) -> float | None:
        df = df.sort_values("year", ascending=False).reset_index(drop=True)
        if len(df) <= idx:
            return None
        return _safe(df.iloc[idx][col])

    rows = []
    for cid, g in pl.groupby("company_id"):
        rows.append(
            {
                "company_id": cid,
                "sales_latest": _pl_pick(g, "sales", 0),
                "sales_prev": _pl_pick(g, "sales", 1),
                "np_latest": _pl_pick(g, "net_profit", 0),
                "np_prev": _pl_pick(g, "net_profit", 1),
            }
        )
    pl_wide = pd.DataFrame(rows)

    meta = pd.read_sql(
        """
        SELECT c.id company_id, c.company_name, s.broad_sector sector
        FROM companies c LEFT JOIN sectors s ON s.company_id = c.id
        """,
        conn,
    )
    out = meta.merge(fr_wide, on="company_id", how="left").merge(
        pl_wide, on="company_id", how="left"
    )
    return out


# ---------------------------------------------------------------------------
# Page builder
# ---------------------------------------------------------------------------
def build_company_page(row: pd.Series, styles: dict[str, ParagraphStyle]) -> list:
    """Return flowables for one company's summary page."""
    flowables: list = []

    name = str(row["company_name"])
    ticker = str(row["company_id"])
    sector = str(row["sector"]) if pd.notna(row["sector"]) else ""
    latest_year = str(row["latest_year"]) if pd.notna(row["latest_year"]) else ""

    header_tbl = Table(
        [
            [
                _make_para(name, styles["title"]),
                _make_para(ticker, styles["ticker_right"]),
            ]
        ],
        colWidths=[13.5 * cm, 4 * cm],
    )
    header_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
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
    flowables.append(header_tbl)
    flowables.append(Spacer(1, 0.2 * cm))
    flowables.append(Paragraph(f"{sector}  |  FY {latest_year}", styles["subtitle"]))
    flowables.append(Spacer(1, 0.4 * cm))

    # KPI grid 3 rows x 2 columns
    col_w = (A4[0] - 3 * cm - 0.3 * cm) / 2
    cells: list[list] = []
    for i in range(0, len(PORTFOLIO_KPIS), 2):
        row_cells: list = []
        for kpi in (PORTFOLIO_KPIS[i], PORTFOLIO_KPIS[i + 1]):
            lv = _safe(row.get(kpi.col_latest))
            pv = _safe(row.get(kpi.col_prev))
            arrow, arrow_col = trend_arrow(lv, pv, kpi.higher_is_better)
            val_style = ParagraphStyle(
                f"V_{kpi.label}",
                fontName="Helvetica-Bold",
                fontSize=14,
                textColor=NAVY,
                alignment=1,
                leading=17,
            )
            name_style = ParagraphStyle(
                f"N_{kpi.label}",
                fontName="Helvetica",
                fontSize=8,
                textColor=colors.HexColor("#595959"),
                alignment=1,
                leading=10,
            )
            arrow_st = ParagraphStyle(
                f"A_{kpi.label}",
                fontName="Helvetica-Bold",
                fontSize=16,
                textColor=arrow_col,
                alignment=1,
                leading=18,
            )
            cell_tbl = Table(
                [
                    [_make_para(kpi.label, name_style)],
                    [_make_para(_fmt(lv, kpi.fmt), val_style)],
                    [_make_para(arrow, arrow_st)],
                ],
                colWidths=[col_w],
            )
            cell_tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F2F2")),
                        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )
            row_cells.append(cell_tbl)
        cells.append([row_cells[0], "", row_cells[1]])

    grid = Table(cells, colWidths=[col_w, 0.3 * cm, col_w])
    grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (1, 0), (1, -1), 0),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
            ]
        )
    )
    flowables.append(grid)
    flowables.append(Spacer(1, 0.3 * cm))

    legend_style = ParagraphStyle(
        "Legend",
        fontName="Helvetica-Oblique",
        fontSize=7,
        textColor=colors.HexColor("#595959"),
        leading=9,
    )
    flowables.append(
        Paragraph(
            f"Trend: <font color='#548235'><b>{ARROW_UP} up</b></font> "
            f"<font color='#C00000'><b>{ARROW_DOWN} down</b></font> "
            f"<font color='grey'><b>{ARROW_FLAT} flat</b></font> "
            f"(within +/- {TREND_THRESHOLD_PCT:.0f}% vs prior year). "
            "D/E considered improved when declining.",
            legend_style,
        )
    )
    return flowables


def _portfolio_page(canvas: Any, doc: Any) -> None:
    """Draw footer with page number."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawString(1.5 * cm, 1 * cm, "Nifty 100 - Portfolio Summary")
    canvas.drawRightString(A4[0] - 1.5 * cm, 1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build_portfolio_summary(panel: pd.DataFrame, output_path: Path) -> Path:
    """Render portfolio summary PDF (one page per company, alphabetical)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = {
        "title": ParagraphStyle(
            "PT",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=colors.white,
            leading=17,
        ),
        "subtitle": ParagraphStyle(
            "PS",
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=colors.HexColor("#595959"),
            leading=10,
        ),
        "ticker_right": ParagraphStyle(
            "PTR",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=colors.white,
            alignment=2,
            leading=17,
        ),
    }

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.5 * cm,
        title="Nifty 100 - Portfolio Summary",
        author="Nifty 100 Financial Intelligence Platform",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal", showBoundary=0
    )
    doc.addPageTemplates([PageTemplate(id="port", frames=[frame], onPage=_portfolio_page)])

    panel_sorted = panel.sort_values("company_id").reset_index(drop=True)
    story: list = []
    for i, row in panel_sorted.iterrows():
        if i > 0:
            story.append(PageBreak())
        story.extend(build_company_page(row, styles))

    doc.build(story)
    logger.info(
        "Portfolio summary written to %s (%d companies)",
        output_path,
        len(panel_sorted),
    )
    return output_path


def run_portfolio_summary(
    db_path: Path | None = None,
    output_path: Path | None = None,
) -> tuple[pd.DataFrame, Path]:
    """High-level entry point for Day 35."""
    from src.utils.config import settings

    if db_path is None:
        db_path = settings.PROJECT_ROOT / "db" / "nifty100.db"
    if output_path is None:
        output_path = settings.PROJECT_ROOT / "reports" / "portfolio" / "portfolio_summary.pdf"
    conn = sqlite3.connect(str(db_path))
    try:
        panel = load_portfolio_panel(conn)
        path = build_portfolio_summary(panel, output_path)
    finally:
        conn.close()
    return panel, path


__all__ = [
    "ARROW_DOWN",
    "ARROW_FLAT",
    "ARROW_UP",
    "KPI",
    "PORTFOLIO_KPIS",
    "TREND_THRESHOLD_PCT",
    "build_company_page",
    "build_portfolio_summary",
    "load_portfolio_panel",
    "run_portfolio_summary",
    "trend_arrow",
]
