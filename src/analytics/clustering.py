"""Sprint 6 Day 36 - KMeans Clustering for company archetypes.

Groups Nifty-100 companies into 5 labelled archetypes using KMeans on five
fundamental features:

    * return_on_equity_pct
    * debt_to_equity
    * revenue_cagr_5yr
    * fcf_cagr_5yr       (computed from trailing 5-year FCF history)
    * operating_profit_margin_pct

Pipeline per spec:
    1. Impute any missing values with the sector median for that metric.
    2. Apply StandardScaler (zero mean, unit variance).
    3. Run KMeans(n_clusters=5, random_state=42) for reproducibility.
    4. Generate an elbow plot (inertia vs k for k=2..10) to reports/elbow_plot.png.
    5. Write output/cluster_labels.csv with columns
       company_id, cluster_id (0-4), cluster_name, distance_from_centroid.

Cluster names are assigned after fitting by inspecting each centroid in
original-feature space and mapping to intuitive investor archetypes
(Quality Compounder, Growth Star, Value Play, Dividend / Cash Cow, Turnaround).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

FEATURES: tuple[str, ...] = (
    "return_on_equity_pct",
    "debt_to_equity",
    "revenue_cagr_5yr",
    "fcf_cagr_5yr",
    "operating_profit_margin_pct",
)

N_CLUSTERS = 5
RANDOM_STATE = 42
K_RANGE_ELBOW = range(2, 11)

# Archetype labels assigned after inspecting centroids - see _assign_cluster_names()
CLUSTER_NAMES: dict[int, str] = {}


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------
_QUERY = """
    SELECT
        c.id            AS company_id,
        c.company_name  AS company_name,
        s.broad_sector  AS sector,
        cf.year,
        cf.operating_activity  AS cfo,
        cf.investing_activity  AS cfi,
        fr.return_on_equity_pct,
        fr.debt_to_equity,
        fr.revenue_cagr_5yr,
        fr.operating_profit_margin_pct,
        pl.sales
    FROM companies c
    JOIN cashflow cf ON cf.company_id = c.id
    LEFT JOIN financial_ratios fr
        ON fr.company_id = c.id AND fr.year = cf.year
    LEFT JOIN profitandloss pl
        ON pl.company_id = c.id AND pl.year = cf.year
    LEFT JOIN sectors s ON s.company_id = c.id
    ORDER BY c.id, cf.year
"""


def _fcf_cagr_from_series(fcf_series: list[float | None], window: int = 5) -> float | None:
    """5-year FCF CAGR — mirrors src.analytics.cashflow_intelligence.fcf_cagr."""
    from src.analytics.cashflow_kpis import free_cash_flow

    vals: list[float] = []
    for cfo, cfi in fcf_series[-(window + 1) :]:
        if cfo is None or cfi is None:
            continue
        try:
            fcf = free_cash_flow(float(cfo), float(cfi))
        except (TypeError, ValueError):
            continue
        if pd.isna(fcf):
            continue
        vals.append(float(fcf))
    if len(vals) < 2:
        return None
    begin, end = vals[0], vals[-1]
    n = len(vals) - 1
    if begin <= 0 or end <= 0 or n <= 0:
        return None
    try:
        return ((end / begin) ** (1.0 / n) - 1.0) * 100.0
    except (ValueError, ZeroDivisionError):
        return None


def build_feature_panel(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return one row per company with all five clustering features.

    Sector-median imputation happens inside :func:`run_clustering`; this
    function returns raw (possibly NaN) values for traceability.
    """
    df = pd.read_sql(_QUERY, conn)
    # Compute 5yr FCF CAGR per company from cash-flow history
    records: list[dict[str, Any]] = []
    for cid, g in df.groupby("company_id", sort=False):
        g = g.sort_values("year").reset_index(drop=True)
        latest = g.iloc[-1]
        cf_pairs: list[tuple[float | None, float | None]] = []
        for _, r in g.iterrows():
            cfo = r["cfo"]
            cfi = r["cfi"]
            cf_pairs.append(
                (
                    None if pd.isna(cfo) else float(cfo),
                    None if pd.isna(cfi) else float(cfi),
                )
            )
        fcf_cagr_5 = _fcf_cagr_from_series(cf_pairs, window=5)
        records.append(
            {
                "company_id": cid,
                "company_name": latest["company_name"],
                "sector": latest["sector"],
                "return_on_equity_pct": _sfloat(latest["return_on_equity_pct"]),
                "debt_to_equity": _sfloat(latest["debt_to_equity"]),
                "revenue_cagr_5yr": _sfloat(latest["revenue_cagr_5yr"]),
                "fcf_cagr_5yr": fcf_cagr_5,
                "operating_profit_margin_pct": _sfloat(latest["operating_profit_margin_pct"]),
            }
        )
    return pd.DataFrame(records)


def _sfloat(v: Any) -> float | None:
    if v is None or pd.isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Clustering engine
# ---------------------------------------------------------------------------
def impute_by_sector_median(panel: pd.DataFrame) -> pd.DataFrame:
    """Fill missing feature values with sector median; fall back to global median."""
    out = panel.copy()
    for feat in FEATURES:
        # Sector medians (skipna by default in pandas .median())
        sector_medians = out.groupby("sector")[feat].transform("median")
        out[feat] = out[feat].fillna(sector_medians)
        # Global median computed on non-null values
        valid = out[feat].dropna()
        global_median = float(valid.median()) if len(valid) > 0 else 0.0
        out[feat] = out[feat].fillna(global_median)
    return out


def _assign_cluster_names(centroids_orig: pd.DataFrame) -> dict[int, str]:
    """Map each cluster id to a human-readable archetype name.

    Uses percentile ranks across the five centroids so that labels are
    assigned based on the most dominant feature rather than a brittle
    composite score.

    Archetypes assigned (in priority order):
        * Turnaround / Risk  - lowest ROE (profitability stress)
        * Quality Compounder - highest combined rank of ROE + Op Margin + low D/E
        * Growth Star        - highest 5yr Revenue CAGR
        * Cash Cow / Yield   - highest 5yr FCF CAGR
        * Value Play         - the remaining cluster (typically high D/E,
                              moderate margins)
    """
    cdf = centroids_orig.copy()
    # 1..5 ranks (higher = "better" for that attribute)
    for col in [
        "return_on_equity_pct",
        "operating_profit_margin_pct",
        "revenue_cagr_5yr",
        "fcf_cagr_5yr",
    ]:
        cdf[f"{col}_rank"] = cdf[col].rank(ascending=True)
    # Low debt -> higher rank
    cdf["debt_rank_inv"] = cdf["debt_to_equity"].rank(ascending=False)

    names: dict[int, str] = {}
    available: set[int] = set(cdf.index.tolist())

    # Turnaround: lowest ROE rank
    tid = int(cdf.loc[list(available), "return_on_equity_pct_rank"].idxmin())
    names[tid] = "Turnaround / Risk"
    available.remove(tid)

    # Quality Compounder: highest composite quality = ROE + OpMargin + lowD/E
    cdf["quality"] = (
        cdf["return_on_equity_pct_rank"]
        + cdf["operating_profit_margin_pct_rank"]
        + cdf["debt_rank_inv"]
    )
    qid = int(cdf.loc[list(available), "quality"].idxmax())
    names[qid] = "Quality Compounder"
    available.remove(qid)

    # Growth Star: highest Revenue CAGR
    gid = int(cdf.loc[list(available), "revenue_cagr_5yr_rank"].idxmax())
    names[gid] = "Growth Star"
    available.remove(gid)

    # Cash Cow / Yield: highest FCF CAGR
    cid = int(cdf.loc[list(available), "fcf_cagr_5yr_rank"].idxmax())
    names[cid] = "Cash Cow / Yield"
    available.remove(cid)

    # Remaining -> Value Play
    for leftover in available:
        names[int(leftover)] = "Value Play"
    return names


def run_clustering(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Impute, scale, cluster; return (labels_df, centroids_orig_df, inertias)."""
    imputed = impute_by_sector_median(panel)
    features_matrix = imputed[list(FEATURES)].values

    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features_matrix)

    kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=RANDOM_STATE, n_init=10)
    cluster_labels = kmeans.fit_predict(features_scaled)

    # Inertias over k for elbow plot
    inertias: list[float] = []
    for k in K_RANGE_ELBOW:
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
        km.fit(features_scaled)
        inertias.append(km.inertia_)
    inertias_arr = np.array(inertias)

    # Distance to assigned centroid in scaled space
    distances = np.linalg.norm(features_scaled - kmeans.cluster_centers_[cluster_labels], axis=1)

    # Centroids in original feature space
    centroids_scaled = kmeans.cluster_centers_
    centroids_orig = scaler.inverse_transform(centroids_scaled)
    centroids_df = pd.DataFrame(centroids_orig, columns=list(FEATURES))

    cluster_names = _assign_cluster_names(centroids_df)

    out = panel[["company_id", "company_name", "sector"]].copy()
    out["cluster_id"] = cluster_labels.astype(int)
    out["cluster_name"] = [cluster_names[int(lbl)] for lbl in cluster_labels]
    out["distance_from_centroid"] = np.round(distances, 4)

    centroids_df.index.name = "cluster_id"
    centroids_df["cluster_name"] = [cluster_names.get(int(i), "") for i in centroids_df.index]
    return out, centroids_df.reset_index(), inertias_arr


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------
def write_elbow_plot(inertias: np.ndarray, path: Path) -> Path:
    """Save elbow plot (inertia vs k) as PNG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(list(K_RANGE_ELBOW), inertias, "o-", color="#1F4E78", linewidth=2, markersize=7)
    ax.axvline(
        N_CLUSTERS, color="#C00000", linestyle="--", linewidth=1, label=f"k = {N_CLUSTERS} (chosen)"
    )
    ax.set_xlabel("Number of clusters (k)")
    ax.set_ylabel("Inertia (sum of squared distances)")
    ax.set_title(
        "KMeans Elbow Plot - Nifty 100 Archetypes", fontsize=11, fontweight="bold", color="#1F4E78"
    )
    ax.set_xticks(list(K_RANGE_ELBOW))
    ax.grid(alpha=0.3)
    ax.legend()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def write_cluster_labels(df: pd.DataFrame, path: Path) -> Path:
    """Write cluster labels CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------
def run_day36_clustering(
    db_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    reports_dir: Path | str | None = None,
) -> dict:
    """Run the Day-36 clustering pipeline end to end."""
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

    conn = sqlite3.connect(str(db_path))
    try:
        panel = build_feature_panel(conn)
    finally:
        conn.close()

    labels_df, centroids_df, inertias = run_clustering(panel)

    csv_path = write_cluster_labels(labels_df, output_dir / "cluster_labels.csv")
    elbow_path = write_elbow_plot(inertias, reports_dir / "elbow_plot.png")

    # Persist centroids too for downstream use / debugging
    centroids_path = output_dir / "cluster_centroids.csv"
    centroids_df.to_csv(centroids_path, index=False)

    return {
        "labels": labels_df,
        "centroids": centroids_df,
        "inertias": inertias,
        "csv_path": csv_path,
        "elbow_path": elbow_path,
        "centroids_path": centroids_path,
    }


__all__ = [
    "FEATURES",
    "N_CLUSTERS",
    "RANDOM_STATE",
    "build_feature_panel",
    "impute_by_sector_median",
    "run_clustering",
    "run_day36_clustering",
    "write_cluster_labels",
    "write_elbow_plot",
]
