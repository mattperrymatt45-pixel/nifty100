"""Radar (Polar) Charts — Sprint 3 Day 19.

Generates per-company radar charts visualising eight KPIs against their
peer group. For companies with no peer-group assignment a standalone bar
chart is produced comparing the company against the Nifty-100 average.

Radar axes (spec §27 Day 19):
    1. ROE              (percentile within peer group)
    2. ROCE             (percentile within peer group)
    3. NPM              (percentile within peer group)
    4. D/E              (inverted percentile — lower leverage = higher score)
    5. FCF score        (CFO/PAT ratio percentile, used as FCF quality proxy)
    6. PAT CAGR 5y      (percentile within peer group)
    7. Revenue CAGR 5y  (percentile within peer group)
    8. Composite Score  (percentile within peer group)

All values are percentile ranks (0-1) within the company's peer group
(reusing the Day-18 ``peer_percentiles`` table for ROE/ROCE/NPM/D/E/PAT
CAGR 5y/Rev CAGR 5y and recomputing CFO/PAT and composite_score
percentiles in the same SQL-PERCENT_RANK style so every axis is on the
same 0-1 scale).

The company's polygon is filled; the peer-group average is overlaid as a
dashed outline for benchmarking. Files are written to
``reports/radar_charts/<company_id>_radar.png``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend; must be set before pyplot import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.projections.polar import PolarAxes

from src.analytics.peer import (
    NO_PEER_GROUP_MSG,
    companies_without_peer_group,
)
from src.analytics.peer import (
    ensure_schema as ensure_peer_schema,
)
from src.etl.database import get_connection
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPORTS_DIR = settings.PROJECT_ROOT / "reports" / "radar_charts"

# 8 radar axes (spec §27). Axis labels are human-friendly; axis keys map to
# either the Day-18 peer_percentiles metric or to extra percentiles
# computed in this module (cfo_pat, composite).
RADAR_AXES: tuple[tuple[str, str], ...] = (
    ("roe", "ROE"),
    ("roce", "ROCE"),
    ("npm", "NPM"),
    ("de", "D/E (low=good)"),
    ("cfo_pat", "FCF Quality"),
    ("pat_cagr_5yr", "PAT CAGR 5y"),
    ("rev_cagr_5yr", "Rev CAGR 5y"),
    ("composite", "Composite"),
)
AXIS_KEYS: tuple[str, ...] = tuple(k for k, _ in RADAR_AXES)
AXIS_LABELS: tuple[str, ...] = tuple(lbl for _, lbl in RADAR_AXES)
N_AXES = len(AXIS_KEYS)
ANGLES = np.linspace(0, 2 * np.pi, N_AXES, endpoint=False).tolist()
ANGLES_CLOSED = ANGLES + ANGLES[:1]  # close polygon

# Visual constants
FIG_SIZE = (9.5, 8.0)
DPI = 140
COMPANY_COLOR = "#1F77B4"
PEER_AVG_COLOR = "#FF4B4B"
NIFTY_AVG_COLOR = "#7F7F7F"
GRID_COLOR = "#CCCCCC"
BG_COLOR = "#FAFCFF"
FILL_ALPHA = 0.20

FONT_TITLE = {"size": 15, "weight": "bold"}
FONT_SUBTITLE = {"size": 10.5, "color": "#555555"}
FONT_LABEL = {"size": 10}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@dataclass
class RadarData:
    """Holds normalised 0-1 axis values for one radar chart."""

    company_id: str
    company_name: str
    peer_group_name: str
    year: str
    company_values: list[float]
    benchmark_values: list[float]
    benchmark_label: str


def _percent_rank(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """SQL-style PERCENT_RANK (same formula as Day 18 peer module)."""
    valid = series.notna()
    n = int(valid.sum())
    if n <= 1:
        out = pd.Series(np.nan, index=series.index, dtype=float)
        out.loc[valid] = 0.5
        return out
    r = series.rank(method="min", ascending=True)
    pr = (r - 1.0) / (n - 1.0)
    if not higher_is_better:
        pr = 1.0 - pr
    return pr


def _load_radar_dataset(
    db_path: Path | str | None = None,
    year: str | None = None,
) -> pd.DataFrame:
    """Load latest-year dataset enriched with peer percentiles + extra
    percentiles for CFO/PAT ratio and Composite Score (which are not in
    Day-18's peer_percentiles).
    """
    ensure_peer_schema(db_path=db_path)
    year_sql = "(SELECT MAX(year) FROM financial_ratios)" if year is None else f"'{year}'"

    # Pull peer-group membership + metrics from financial_ratios + composite.
    # Use the existing peer_percentiles table for the six Day-18 metrics
    # we need and compute the other two (cfo_pat, composite) on the fly.
    sql = f"""
        SELECT
            fr.company_id,
            co.company_name,
            pg.peer_group_name,
            fr.year,
            fr.return_on_equity_pct  AS roe,
            fr.roce_pct              AS roce,
            fr.net_profit_margin_pct AS npm,
            fr.debt_to_equity        AS de,
            fr.cfo_pat_ratio         AS cfo_pat,
            fr.pat_cagr_5yr          AS pat_cagr_5yr,
            fr.revenue_cagr_5yr      AS rev_cagr_5yr,
            fr.composite_quality_score AS composite_raw
        FROM financial_ratios fr
        JOIN companies co ON co.id = fr.company_id
        JOIN peer_groups pg ON pg.company_id = fr.company_id
        WHERE fr.year = {year_sql}
        ORDER BY pg.peer_group_name, fr.company_id
    """
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn)

    if df.empty:
        return df

    # Compute percentile ranks within each peer group for all 8 axes.
    axis_spec = {
        "roe": True,
        "roce": True,
        "npm": True,
        "de": False,  # inverted
        "cfo_pat": True,
        "pat_cagr_5yr": True,
        "rev_cagr_5yr": True,
        "composite": True,
    }
    for key, higher_better in axis_spec.items():
        col_raw = key if key != "composite" else "composite_raw"
        df[f"{key}_pctile"] = df.groupby("peer_group_name")[col_raw].transform(
            lambda s, h=higher_better: _percent_rank(s, higher_is_better=h)
        )
    return df


def _load_nifty_averages(
    db_path: Path | str | None = None,
    year: str | None = None,
) -> pd.Series:
    """Return Nifty-100 average values for the standalone chart (unranked;
    raw metrics normalised against company values for a bar chart).
    """
    year_sql = "(SELECT MAX(year) FROM financial_ratios)" if year is None else f"'{year}'"
    sql = f"""
        SELECT
            AVG(return_on_equity_pct)  AS roe,
            AVG(roce_pct)              AS roce,
            AVG(net_profit_margin_pct) AS npm,
            AVG(debt_to_equity)        AS de,
            AVG(cfo_pat_ratio)         AS cfo_pat,
            AVG(pat_cagr_5yr)          AS pat_cagr_5yr,
            AVG(revenue_cagr_5yr)      AS rev_cagr_5yr,
            AVG(composite_quality_score) AS composite_raw
        FROM financial_ratios
        WHERE year = {year_sql}
    """
    with get_connection(db_path) as conn:
        row = pd.read_sql_query(sql, conn).iloc[0]
    return row


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------
def _draw_radar_polygon(
    ax: PolarAxes,
    values_closed: list[float],
    *,
    color: str,
    label: str,
    linestyle: str = "-",
    linewidth: float = 2.0,
    fill: bool = False,
    fill_alpha: float = 0.0,
) -> None:
    ax.plot(
        ANGLES_CLOSED,
        values_closed,
        color=color,
        linewidth=linewidth,
        linestyle=linestyle,
        label=label,
    )
    if fill:
        ax.fill(ANGLES_CLOSED, values_closed, color=color, alpha=fill_alpha)


def plot_company_radar(
    data: RadarData,
    output_path: Path | str,
) -> Path:
    """Render one radar chart for a peer-group member and save it."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=FIG_SIZE, dpi=DPI, facecolor="white")
    ax = fig.add_subplot(111, polar=True, facecolor=BG_COLOR)

    # Close polygons
    company_closed = [*data.company_values, data.company_values[0]]
    bench_closed = [*data.benchmark_values, data.benchmark_values[0]]

    # Grid (concentric circles at 0.25/0.5/0.75/1.0 and spoke lines)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.50, 0.75, 1.00])
    ax.set_yticklabels(["25%", "50%", "75%", "100%"], fontsize=8, color="#888")
    ax.set_xticks(ANGLES)
    ax.set_xticklabels(AXIS_LABELS, fontdict=FONT_LABEL)
    ax.grid(color=GRID_COLOR, linewidth=0.7)
    ax.set_facecolor(BG_COLOR)

    # Company polygon (filled, solid)
    _draw_radar_polygon(
        ax,
        company_closed,
        color=COMPANY_COLOR,
        label=f"{data.company_id} ({data.company_name[:22]})",
        linestyle="-",
        linewidth=2.2,
        fill=True,
        fill_alpha=FILL_ALPHA,
    )
    # Peer average (dashed overlay, no fill)
    _draw_radar_polygon(
        ax,
        bench_closed,
        color=PEER_AVG_COLOR,
        label=f"{data.peer_group_name} avg",
        linestyle="--",
        linewidth=1.8,
    )

    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.10), fontsize=9, frameon=True)

    title = f"{data.company_name} ({data.company_id}) — {data.peer_group_name}"
    subtitle = (
        f"FY {data.year}  |  Filled = company (percentile in peer group), "
        f"dashed = {data.peer_group_name} average"
    )
    ax.set_title(title, fontdict=FONT_TITLE, pad=28)
    fig.text(0.5, 0.905, subtitle, ha="center", fontdict=FONT_SUBTITLE)

    plt.tight_layout()
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def plot_standalone_chart(
    company_id: str,
    company_name: str,
    year: str,
    company_values: dict[str, float],
    benchmark_values: dict[str, float],
    output_path: Path | str,
) -> Path:
    """For companies with NO peer group, emit a single horizontal bar chart
    comparing the company's raw metric values against the Nifty-100 average.

    Because the metrics are on very different scales (ROE % vs. D/E vs.
    CAGR % vs. composite 0-100), we normalise each axis to
    company_value / max(abs(company), abs(nifty_avg)) so both bars fit in
    [-1.5, 1.5] with a light reference line at 1.0 — giving an "index vs
    Nifty" visual that's readable regardless of scale.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    labels = []
    co_vals = []
    nifty_vals = []
    for key, lab in RADAR_AXES:
        cv = company_values.get(key)
        nv = benchmark_values.get(key)
        if cv is None or nv is None or (pd.isna(cv) or pd.isna(nv)):
            continue
        labels.append(lab)
        # Normalise: ratio of company to the larger of |company| and |nifty avg|.
        # For D/E, lower is better — invert so a bar above 1.0 means "better than
        # average".
        if key == "de":
            # ratio <1 means lower (better); convert so >1 = better than avg
            co_norm = nv / cv if cv > 0 else np.nan
            nifty_norm = 1.0
        else:
            scale = max(abs(cv), abs(nv)) if max(abs(cv), abs(nv)) > 0 else 1.0
            co_norm = cv / scale
            nifty_norm = nv / scale
        co_vals.append(co_norm)
        nifty_vals.append(nifty_norm)

    fig, ax = plt.subplots(figsize=(9.5, 5.5), dpi=DPI, facecolor="white")
    y = np.arange(len(labels))
    bar_h = 0.38
    ax.barh(y - bar_h / 2, co_vals, bar_h, color=COMPANY_COLOR, label=f"{company_id}")
    ax.barh(
        y + bar_h / 2, nifty_vals, bar_h, color=NIFTY_AVG_COLOR, label="Nifty 100 avg", alpha=0.65
    )
    ax.axvline(1.0, color="#999", linewidth=0.8, linestyle=":")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("Relative value (normalised; 1.0 = reference)", fontsize=9, color="#555")
    ax.set_title(
        f"{company_name} ({company_id}) — Standalone comparison vs Nifty 100 average",
        fontdict=FONT_TITLE,
        pad=14,
    )
    ax.text(
        0.0,
        -0.18,
        f"FY {year}  |  No peer group assigned — bars show raw metrics normalised "
        f"to max(company, Nifty avg); D/E inverted so longer = better",
        transform=ax.transAxes,
        ha="left",
        fontdict=FONT_SUBTITLE,
    )
    ax.legend(loc="lower right", fontsize=9)
    ax.set_facecolor(BG_COLOR)
    ax.grid(axis="x", color=GRID_COLOR, linewidth=0.6)
    plt.tight_layout()
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------
def _radar_pctile_columns() -> list[str]:
    return [f"{k}_pctile" for k in AXIS_KEYS]


def generate_radar_charts(
    db_path: Path | str | None = None,
    year: str | None = None,
    output_dir: Path | str | None = None,
) -> dict[str, object]:
    """Generate radar charts for every peer-grouped company plus standalone
    comparison charts for companies without a peer group.

    Returns dict with summary stats.
    """
    out_dir = Path(output_dir) if output_dir else REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    df = _load_radar_dataset(db_path=db_path, year=year)
    target_year = df["year"].iloc[0] if len(df) else year

    # Compute peer-group averages for each axis (percentile means)
    pct_cols = _radar_pctile_columns()
    peer_avg = df.groupby("peer_group_name")[pct_cols].mean()

    radar_count = 0
    generated: list[str] = []
    for _, row in df.iterrows():
        company_values = [
            float(row[f"{k}_pctile"]) if not pd.isna(row[f"{k}_pctile"]) else 0.0 for k in AXIS_KEYS
        ]
        grp_avg_row = peer_avg.loc[row["peer_group_name"]]
        bench_values = [float(grp_avg_row[f"{k}_pctile"]) for k in AXIS_KEYS]
        data = RadarData(
            company_id=row["company_id"],
            company_name=row["company_name"],
            peer_group_name=row["peer_group_name"],
            year=row["year"],
            company_values=company_values,
            benchmark_values=bench_values,
            benchmark_label=f"{row['peer_group_name']} avg",
        )
        out_path = out_dir / f"{row['company_id']}_radar.png"
        plot_company_radar(data, out_path)
        radar_count += 1
        generated.append(str(out_path))

    # Standalone charts for companies without a peer group
    no_peer = companies_without_peer_group(db_path=db_path, year=target_year)
    nifty_avg = _load_nifty_averages(db_path=db_path, year=target_year)

    # Pull raw metrics for each no-peer company
    standalone_count = 0
    if no_peer:
        placeholders = ",".join("?" * len(no_peer))
        year_sql = (
            target_year if target_year is not None else "(SELECT MAX(year) FROM financial_ratios)"
        )
        sql = f"""
            SELECT id AS company_id, company_name,
                   return_on_equity_pct AS roe,
                   roce_pct AS roce,
                   net_profit_margin_pct AS npm,
                   debt_to_equity AS de,
                   cfo_pat_ratio AS cfo_pat,
                   pat_cagr_5yr AS pat_cagr_5yr,
                   revenue_cagr_5yr AS rev_cagr_5yr,
                   composite_quality_score AS composite_raw
            FROM financial_ratios fr
            JOIN companies co ON co.id = fr.company_id
            WHERE fr.year = {year_sql if year_sql.startswith('(') else '?'}
              AND fr.company_id IN ({placeholders})
        """
        params: list[object] = list(no_peer)
        if not year_sql.startswith("("):
            params = [target_year, *no_peer]
        with get_connection(db_path) as conn:
            co_df = pd.read_sql_query(sql, conn, params=params)
        for _, crow in co_df.iterrows():
            company_vals = {
                k: crow[k] if k != "composite" else crow["composite_raw"] for k, _ in RADAR_AXES
            }
            nifty_vals = {
                k: nifty_avg[k if k != "composite" else "composite_raw"] for k, _ in RADAR_AXES
            }
            out_path = out_dir / f"{crow['company_id']}_radar.png"
            plot_standalone_chart(
                company_id=crow["company_id"],
                company_name=crow["company_name"],
                year=target_year or "",
                company_values=company_vals,
                benchmark_values=nifty_vals,
                output_path=out_path,
            )
            standalone_count += 1
            generated.append(str(out_path))

    stats = {
        "year": target_year,
        "radar_charts": radar_count,
        "standalone_charts": standalone_count,
        "total": radar_count + standalone_count,
        "output_dir": str(out_dir),
        "no_peer_group": no_peer,
    }
    logger.info(
        f"Generated {stats['total']} radar/standalone charts "
        f"({radar_count} peer-radar, {standalone_count} standalone) "
        f"-> {out_dir}"
    )
    return stats


__all__ = [
    "AXIS_KEYS",
    "AXIS_LABELS",
    "NO_PEER_GROUP_MSG",
    "REPORTS_DIR",
    "RadarData",
    "generate_radar_charts",
    "plot_company_radar",
    "plot_standalone_chart",
]
