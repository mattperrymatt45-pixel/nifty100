"""Sprint 6 Day 37 - Cluster Profiling & Portfolio Statistics.

Deliverables:
    1. Profile each cluster: mean & median of the 5 clustering features per
       cluster -> saved to ``output/cluster_profile.csv``.
    2. Review & rename clusters to descriptive investor-archetype names
       (overrides Day-36 labels after team-lead review of constituent
       companies and financial profiles).
    3. Pearson correlation heatmap (10 KPIs) -> ``reports/correlation_heatmap.png``.
    4. Per-sector Z-score outlier detection (|Z|>3) -> ``output/outlier_report.csv``.
    5. Portfolio percentile statistics (P10/P25/P50/P75/P90/Mean/Std) for 10
       KPIs across all 92 companies -> ``output/portfolio_stats.csv``.

Cluster names after Day-37 review
---------------------------------
After reviewing the actual constituent companies, valuation multiples, ROCE,
dividend yields and sector mix per cluster, the archetypes have been refined:

===========  ===========================  =====================================
Cluster ID   Day-36 label                 Day-37 refined label
===========  ===========================  =====================================
0            Growth Star                  Emerging Growth
1            Turnaround / Risk            Distressed / Turnaround
2            Value Play                   Value Cyclicals
3            Quality Compounder           High-Quality Compounders
4            Cash Cow / Yield             Defensive Dividend Payers
===========  ===========================  =====================================
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from src.analytics.clustering import (
    FEATURES,
    build_feature_panel,
    impute_by_sector_median,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Refined cluster names after team-lead review (Day 37)
# ---------------------------------------------------------------------------
REFINED_CLUSTER_NAMES: dict[int, str] = {
    0: "Emerging Growth",
    1: "Distressed / Turnaround",
    2: "Value Cyclicals",
    3: "High-Quality Compounders",
    4: "Defensive Dividend Payers",
}

# ---------------------------------------------------------------------------
# 10 KPIs used for correlation heatmap, outliers and portfolio stats
# ---------------------------------------------------------------------------
PORTFOLIO_KPIS: tuple[str, ...] = (
    "return_on_equity_pct",
    "roce_pct",
    "debt_to_equity",
    "revenue_cagr_5yr",
    "pat_cagr_5yr",
    "operating_profit_margin_pct",
    "net_profit_margin_pct",
    "dividend_payout_ratio_pct",
    "pe_ratio",
    "pb_ratio",
)

KPI_DISPLAY_NAMES: dict[str, str] = {
    "return_on_equity_pct": "ROE (%)",
    "roce_pct": "ROCE (%)",
    "debt_to_equity": "Debt / Equity",
    "revenue_cagr_5yr": "Revenue CAGR 5yr (%)",
    "pat_cagr_5yr": "PAT CAGR 5yr (%)",
    "operating_profit_margin_pct": "OPM (%)",
    "net_profit_margin_pct": "NPM (%)",
    "dividend_payout_ratio_pct": "Div Payout (%)",
    "pe_ratio": "P/E Ratio",
    "pb_ratio": "P/B Ratio",
}

OUTLIER_Z_THRESHOLD = 3.0


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------
_LATEST_KPI_QUERY = """
    SELECT
        c.id            AS company_id,
        c.company_name  AS company_name,
        s.broad_sector  AS sector,
        fr.year,
        fr.return_on_equity_pct,
        fr.roce_pct,
        fr.debt_to_equity,
        fr.revenue_cagr_5yr,
        fr.pat_cagr_5yr,
        fr.operating_profit_margin_pct,
        fr.net_profit_margin_pct,
        fr.dividend_payout_ratio_pct,
        mc.pe_ratio,
        mc.pb_ratio
    FROM companies c
    LEFT JOIN sectors s ON s.company_id = c.id
    LEFT JOIN financial_ratios fr
        ON fr.company_id = c.id
       AND fr.year = (SELECT MAX(fr2.year) FROM financial_ratios fr2 WHERE fr2.company_id = c.id)
    LEFT JOIN market_cap mc
        ON mc.company_id = c.id
       AND mc.year = CAST(SUBSTR(fr.year, 1, 4) AS INTEGER)
    ORDER BY c.id
"""


def load_latest_kpis(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return a DataFrame with one row per company for the latest FY."""
    df = pd.read_sql(_LATEST_KPI_QUERY, conn)
    # Ensure numeric
    for col in PORTFOLIO_KPIS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# 1. Cluster profiling (mean + median per cluster)
# ---------------------------------------------------------------------------
def profile_clusters(
    panel_imputed: pd.DataFrame, labels_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute cluster-level mean & median for the 5 clustering features.

    Returns (means_df, medians_df) with columns cluster_id, cluster_name,
    count, and the 5 feature columns.
    """
    merged = panel_imputed.merge(
        labels_df[["company_id", "cluster_id"]], on="company_id", how="inner"
    )
    merged["cluster_name"] = merged["cluster_id"].map(REFINED_CLUSTER_NAMES)

    group = merged.groupby(["cluster_id", "cluster_name"])
    means = group[list(FEATURES)].mean().round(3).reset_index()
    medians = group[list(FEATURES)].median().round(3).reset_index()
    counts = group.size().reset_index(name="count")
    means = counts.merge(means, on=["cluster_id", "cluster_name"])
    medians = counts.merge(medians, on=["cluster_id", "cluster_name"])
    return means, medians


def write_cluster_profile(means: pd.DataFrame, medians: pd.DataFrame, path: Path) -> Path:
    """Write a long-format CSV combining mean and median profiles."""
    path.parent.mkdir(parents=True, exist_ok=True)
    m = means.copy()
    m.insert(2, "statistic", "mean")
    md = medians.copy()
    md.insert(2, "statistic", "median")
    out = pd.concat([m, md], ignore_index=True)
    out.to_csv(path, index=False)
    return path


def relabel_clusters(labels_df: pd.DataFrame) -> pd.DataFrame:
    """Return an updated labels_df with refined Day-37 cluster names."""
    out = labels_df.copy()
    out["cluster_name"] = out["cluster_id"].map(REFINED_CLUSTER_NAMES)
    return out


# ---------------------------------------------------------------------------
# 3. Correlation heatmap
# ---------------------------------------------------------------------------
def compute_correlation_matrix(kpi_df: pd.DataFrame) -> pd.DataFrame:
    """Pearson correlation across the 10 portfolio KPIs (latest FY)."""
    sub = kpi_df[list(PORTFOLIO_KPIS)].copy()
    corr = sub.corr(method="pearson")
    corr.index = [KPI_DISPLAY_NAMES.get(c, c) for c in corr.index]
    corr.columns = [KPI_DISPLAY_NAMES.get(c, c) for c in corr.columns]
    return corr


def write_correlation_heatmap(corr: pd.DataFrame, path: Path) -> Path:
    """Save a seaborn-annotated correlation heatmap."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 8))
    cmap = sns.diverging_palette(220, 10, as_cmap=True)
    sns.heatmap(
        corr,
        annot=True,
        fmt=".2f",
        cmap=cmap,
        vmin=-1,
        vmax=1,
        center=0,
        square=True,
        linewidths=0.6,
        linecolor="white",
        cbar_kws={"shrink": 0.8, "label": "Pearson r"},
        annot_kws={"size": 8},
        ax=ax,
    )
    ax.set_title(
        "Nifty 100 - KPI Correlation Matrix (Latest FY, n=92)",
        fontsize=12,
        fontweight="bold",
        color="#1F4E78",
        pad=14,
    )
    ax.set_xticklabels(ax.get_xticklabels(), rotation=40, ha="right", fontsize=9)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# 4. Outlier detection (per-sector Z-scores)
# ---------------------------------------------------------------------------
def detect_sector_outliers(kpi_df: pd.DataFrame) -> pd.DataFrame:
    """Flag company/KPI pairs where absolute per-sector Z-score > 3.

    For each KPI, the Z-score is computed *within each broad sector* using
    that sector's mean and standard deviation. Companies where any KPI
    has |Z| > 3 are flagged; rows where the sector has fewer than 3 data
    points fall back to the global Z-score.
    """
    rows: list[dict[str, Any]] = []
    df = kpi_df[["company_id", "company_name", "sector", *PORTFOLIO_KPIS]].copy()
    for kpi in PORTFOLIO_KPIS:
        col = df[kpi].astype(float)
        # Sector Z
        sec_mean = df.groupby("sector")[kpi].transform("mean")
        sec_std = df.groupby("sector")[kpi].transform("std")
        # Global fallback
        global_mean = col.mean()
        global_std = col.std(ddof=0)
        # Use sector stats only when sector has >=3 valid points; else global
        sec_counts = df.groupby("sector")[kpi].transform("count")
        use_sector = (sec_counts >= 3) & sec_std.notna() & (sec_std > 0)
        z = np.where(
            use_sector,
            (col - sec_mean) / sec_std.replace(0, np.nan),
            (col - global_mean) / (global_std if global_std > 0 else np.nan),
        )
        z = pd.Series(z, index=df.index)
        flagged = z.abs() > OUTLIER_Z_THRESHOLD
        for idx, is_flag in flagged.items():
            if bool(is_flag):
                rows.append(
                    {
                        "company_id": df.at[idx, "company_id"],
                        "company_name": df.at[idx, "company_name"],
                        "sector": df.at[idx, "sector"],
                        "metric": kpi,
                        "metric_label": KPI_DISPLAY_NAMES.get(kpi, kpi),
                        "value": (
                            round(float(col.iloc[idx]), 4) if pd.notna(col.iloc[idx]) else None
                        ),
                        "sector_mean": (
                            round(float(sec_mean.iloc[idx]), 4)
                            if pd.notna(sec_mean.iloc[idx])
                            else None
                        ),
                        "z_score": round(float(z.iloc[idx]), 4),
                    }
                )
    out = pd.DataFrame(rows)
    if len(out) > 0:
        out = out.sort_values(["sector", "company_id", "metric"]).reset_index(drop=True)
    return out


def write_outlier_report(df: pd.DataFrame, path: Path) -> Path:
    """Save outlier report CSV; writes a single 'No outliers found' row if empty."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(df) == 0:
        pd.DataFrame([{"note": "No sector-level outliers (|Z|>3) detected."}]).to_csv(
            path, index=False
        )
    else:
        df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# 5. Portfolio percentiles
# ---------------------------------------------------------------------------
def compute_portfolio_stats(kpi_df: pd.DataFrame) -> pd.DataFrame:
    """Return P10, P25, P50, P75, P90, Mean, Std, Min, Max, Count per KPI."""
    records: list[dict[str, Any]] = []
    for kpi in PORTFOLIO_KPIS:
        s = pd.to_numeric(kpi_df[kpi], errors="coerce").dropna()
        records.append(
            {
                "metric": kpi,
                "metric_label": KPI_DISPLAY_NAMES.get(kpi, kpi),
                "count": int(s.count()),
                "p10": round(float(s.quantile(0.10)), 4),
                "p25": round(float(s.quantile(0.25)), 4),
                "p50": round(float(s.quantile(0.50)), 4),
                "p75": round(float(s.quantile(0.75)), 4),
                "p90": round(float(s.quantile(0.90)), 4),
                "mean": round(float(s.mean()), 4),
                "std": round(float(s.std(ddof=1)), 4),
                "min": round(float(s.min()), 4),
                "max": round(float(s.max()), 4),
            }
        )
    return pd.DataFrame(records)


def write_portfolio_stats(df: pd.DataFrame, path: Path) -> Path:
    """Write the portfolio-level percentile summary CSV to ``output/portfolio_stats.csv``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------
def run_day37_profiling(
    db_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    reports_dir: Path | str | None = None,
) -> dict:
    """Run the full Day-37 pipeline end-to-end."""
    from src.utils.config import settings

    if db_path is None:
        db_path = settings.PROJECT_ROOT / "db" / "nifty100.db"
    if output_dir is None:
        output_dir = settings.PROJECT_ROOT / "output"
    if reports_dir is None:
        reports_dir = settings.PROJECT_ROOT / "reports"
    db_path = Path(db_path)
    output_dir = Path(output_dir)
    reports_dir = Path(reports_dir)

    # --- Load clustering state from Day 36 (or recompute if labels missing)
    labels_path = output_dir / "cluster_labels.csv"
    if labels_path.exists():
        labels_df = pd.read_csv(labels_path)
    else:
        # Fallback: re-run Day-36 clustering so profiling is self-contained
        from src.analytics.clustering import run_day36_clustering

        cl_res = run_day36_clustering(
            db_path=db_path, output_dir=output_dir, reports_dir=reports_dir
        )
        labels_df = cl_res["labels"]

    conn = sqlite3.connect(str(db_path))
    try:
        panel = build_feature_panel(conn)
        kpi_df = load_latest_kpis(conn)
    finally:
        conn.close()

    panel_imp = impute_by_sector_median(panel)

    # 1. Cluster profiles + re-labelling
    means, medians = profile_clusters(panel_imp, labels_df)
    profile_path = write_cluster_profile(means, medians, output_dir / "cluster_profile.csv")
    labels_relabelled = relabel_clusters(labels_df)
    labels_relabelled.to_csv(labels_path, index=False)  # overwrite with refined names

    # 3. Correlation heatmap
    corr = compute_correlation_matrix(kpi_df)
    heatmap_path = write_correlation_heatmap(corr, reports_dir / "correlation_heatmap.png")

    # 4. Outlier detection
    outliers = detect_sector_outliers(kpi_df)
    outlier_path = write_outlier_report(outliers, output_dir / "outlier_report.csv")

    # 5. Portfolio stats
    stats = compute_portfolio_stats(kpi_df)
    stats_path = write_portfolio_stats(stats, output_dir / "portfolio_stats.csv")

    return {
        "cluster_means": means,
        "cluster_medians": medians,
        "correlation_matrix": corr,
        "outliers": outliers,
        "portfolio_stats": stats,
        "labels_relabelled": labels_relabelled,
        "paths": {
            "cluster_profile": profile_path,
            "labels": labels_path,
            "heatmap": heatmap_path,
            "outliers": outlier_path,
            "portfolio_stats": stats_path,
        },
    }


__all__ = [
    "FEATURES",
    "KPI_DISPLAY_NAMES",
    "OUTLIER_Z_THRESHOLD",
    "PORTFOLIO_KPIS",
    "REFINED_CLUSTER_NAMES",
    "compute_correlation_matrix",
    "compute_portfolio_stats",
    "detect_sector_outliers",
    "load_latest_kpis",
    "profile_clusters",
    "relabel_clusters",
    "run_day37_profiling",
    "write_cluster_profile",
    "write_correlation_heatmap",
    "write_outlier_report",
    "write_portfolio_stats",
]
