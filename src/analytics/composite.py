"""Composite Quality Score — Sprint 3 Day 17.

Computes a 0-100 composite score per company (latest year) using the spec
§25.1 weights:

    35%  Profitability  (ROE 15% + ROCE 10% + NPM 10%)
    30%  Cash Quality   (FCF CAGR 5y 15% + CFO/PAT ratio 10% + FCF>0 flag 5%)
    20%  Growth         (Revenue CAGR 5y 10% + PAT CAGR 5y 10%)
    15%  Leverage       (D/E score 10% + ICR score 5%)

Each metric is winsorised at the 10th / 90th percentile of the cross-section
to neutralise outliers, then min-max scaled to 0-100 before being weighted
and summed. Leverage metrics (D/E, ICR) use piecewise scoring per spec §25.1.

Two scores are produced:
    * ``composite_score_100``        — overall winsorised score 0-100.
    * ``sector_relative_score``      — re-normalised within ``broad_sector`` so
                                      scores rank companies against their
                                      sector peers.
    * ``composite_rank``             — universe rank (1 = best) on overall score.
    * ``sector_rank``                — rank within sector.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants (spec §25.1)
# ---------------------------------------------------------------------------
WINSOR_LOWER = 0.10
WINSOR_UPPER = 0.90

# Weight decomposition (must sum to 1.00)
W_ROE = 0.15
W_ROCE = 0.10
W_NPM = 0.10
W_FCF_CAGR = 0.15
W_CFO_PAT = 0.10
W_FCF_POS = 0.05
W_REV_CAGR = 0.10
W_PAT_CAGR = 0.10
W_DE = 0.10
W_ICR = 0.05

# Piecewise scoring anchors (spec §25.1)
DE_SCORES = [(0.0, 100), (0.5, 85), (1.0, 70), (2.0, 50), (5.0, 0)]  # (d/e, score)
ICR_SCORES = [(10.0, 100), (5.0, 75), (3.0, 50), (1.5, 0)]

FCF_POSITIVE_SCORE = 100
FCF_NEGATIVE_SCORE = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _winsorise(s: pd.Series, lower: float = WINSOR_LOWER, upper: float = WINSOR_UPPER) -> pd.Series:
    """Cap values at the lower / upper quantiles. NaNs are preserved."""
    q_low = s.quantile(lower)
    q_high = s.quantile(upper)
    return s.clip(lower=q_low, upper=q_high)


def _minmax_scale(s: pd.Series, reverse: bool = False) -> pd.Series:
    """Scale to 0-100 using min/max of (already winsorised) series.

    reverse=True means *lower* original value is better (e.g. D/E).
    NaNs are set to the mean (50) — neutral score for missing metric.
    """
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return pd.Series(np.where(s.notna(), 50.0, np.nan), index=s.index)
    scaled = (s - lo) / (hi - lo) * 100.0
    if reverse:
        scaled = 100.0 - scaled
    return scaled.fillna(50.0)


def _piecewise_linear(x: float, anchors: list[tuple[float, float]], reverse: bool = False) -> float:
    """Linearly interpolate score between (anchor_value, anchor_score) pairs.

    Anchors must be sorted ascending by anchor_value. Out-of-range values are
    clipped to the nearest endpoint. NaN returns 0.
    """
    if x is None or pd.isna(x):
        return 0.0
    pts = sorted(anchors, key=lambda p: p[0])
    if reverse:
        # reverse means lower x is better, but our anchors are already written
        # in that direction for D/E/ICR; we use ascending anchors as-is.
        pass
    if x <= pts[0][0]:
        return float(pts[0][1])
    if x >= pts[-1][0]:
        return float(pts[-1][1])
    for i in range(len(pts) - 1):
        x0, s0 = pts[i]
        x1, s1 = pts[i + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
            return float(s0 + t * (s1 - s0))
    return float(pts[-1][1])


def _piecewise_series(
    s: pd.Series, anchors: list[tuple[float, float]], reverse: bool = False
) -> pd.Series:
    return s.apply(lambda v: _piecewise_linear(v, anchors, reverse=reverse))


# ---------------------------------------------------------------------------
# FCF CAGR computation (5y) from cashflow table
# ---------------------------------------------------------------------------
def compute_fcf_cagr_5yr(
    db_path: str | None = None,
    latest_year: str | None = None,
) -> pd.DataFrame:
    """Compute FCF CAGR 5yr for every company.

    Returns DataFrame indexed by company_id with column ``fcf_cagr_5yr`` (float,
    may be NaN for insufficient history or turnaround cases).
    """
    from src.etl.database import get_connection

    sql = """
        SELECT company_id, year,
               operating_activity + investing_activity AS fcf_cr
        FROM cashflow
        ORDER BY company_id, year
    """
    with get_connection(db_path) as conn:
        cf = pd.read_sql_query(sql, conn)

    if latest_year is None:
        latest_year = cf["year"].max()

    # Build per-company FCF CAGR 5y: (fcf_t / fcf_{t-5})^(1/5) - 1, only
    # if both endpoints exist and base > 0.
    rows = []
    for cid, grp in cf.groupby("company_id"):
        grp = grp.sort_values("year").set_index("year")
        if latest_year not in grp.index:
            rows.append((cid, np.nan))
            continue
        cur = grp.loc[latest_year, "fcf_cr"]
        # find the year 5 years back (same fiscal month)
        years_sorted = sorted(grp.index)
        base_year = None
        for y in years_sorted:
            if y < latest_year:
                # prefer exact 5-year offset; else most recent prior up to 5
                try:
                    cur_yr_int = int(str(latest_year)[:4])
                    y_int = int(str(y)[:4])
                    if cur_yr_int - y_int == 5:
                        base_year = y
                        break
                except (ValueError, TypeError):
                    continue
        if base_year is None:
            rows.append((cid, np.nan))
            continue
        base = grp.loc[base_year, "fcf_cr"]
        if pd.isna(base) or pd.isna(cur):
            rows.append((cid, np.nan))
            continue
        # If base FCF was zero or negative, 5y CAGR is undefined (turnaround /
        # insufficient-history semantics consistent with cagr.py).
        if base <= 0:
            rows.append((cid, np.nan))
            continue
        ratio = cur / base
        if ratio <= 0:
            rows.append((cid, np.nan))
            continue
        cagr = ratio ** (1 / 5) - 1
        rows.append((cid, cagr * 100.0))

    return pd.DataFrame(rows, columns=["company_id", "fcf_cagr_5yr"])


# ---------------------------------------------------------------------------
# Composite score computation
# ---------------------------------------------------------------------------
@dataclass
class CompositeResult:
    """Output of ``compute_composite_scores`` with both score variants and ranks."""

    df: pd.DataFrame  # the screener dataset augmented with scores + ranks

    # Column names added
    OVERALL = "composite_score_100"
    SECTOR_REL = "sector_relative_score"
    UNIV_RANK = "composite_rank"
    SECTOR_RANK = "sector_rank"


def compute_component_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the winsorised + scaled 0-100 component scores.

    Expects ``df`` to be the latest-year screener dataset. Augments it with
    per-metric component columns (``_score`` suffix) plus the weighted totals.
    """
    out = df.copy()

    # --- Profitability components (higher = better) ---
    out["roe_score"] = _minmax_scale(_winsorise(out["roe_pct"]))
    out["roce_score"] = _minmax_scale(_winsorise(out["roce_pct"]))
    out["npm_score"] = _minmax_scale(_winsorise(out["net_profit_margin_pct"]))

    # --- Cash quality ---
    # FCF CAGR 5y may have NaNs; we winsorise the non-NaN portion then scale.
    fcf_cagr = out["fcf_cagr_5yr"].astype(float)
    if fcf_cagr.notna().any():
        out["fcf_cagr_score"] = _minmax_scale(_winsorise(fcf_cagr))
    else:
        out["fcf_cagr_score"] = 50.0
    out["cfo_pat_score"] = _minmax_scale(_winsorise(out["cfo_pat_ratio"]))
    out["fcf_pos_score"] = np.where(out["fcf_cr"] > 0, FCF_POSITIVE_SCORE, FCF_NEGATIVE_SCORE)

    # --- Growth (higher = better) ---
    out["rev_cagr_score"] = _minmax_scale(_winsorise(out["revenue_cagr_5yr"]))
    out["pat_cagr_score"] = _minmax_scale(_winsorise(out["pat_cagr_5yr"]))

    # --- Leverage (piecewise, higher = better) ---
    out["de_score"] = _piecewise_series(out["debt_to_equity"], DE_SCORES, reverse=True)
    out["icr_score"] = _piecewise_series(out["icr"], ICR_SCORES, reverse=True)
    # Debt-free companies get a perfect ICR score
    out.loc[out["icr_label"] == "Debt Free", "icr_score"] = 100.0

    # --- Weighted composite (0-100) ---
    out[CompositeResult.OVERALL] = (
        W_ROE * out["roe_score"]
        + W_ROCE * out["roce_score"]
        + W_NPM * out["npm_score"]
        + W_FCF_CAGR * out["fcf_cagr_score"]
        + W_CFO_PAT * out["cfo_pat_score"]
        + W_FCF_POS * out["fcf_pos_score"]
        + W_REV_CAGR * out["rev_cagr_score"]
        + W_PAT_CAGR * out["pat_cagr_score"]
        + W_DE * out["de_score"]
        + W_ICR * out["icr_score"]
    )
    out[CompositeResult.OVERALL] = out[CompositeResult.OVERALL].clip(0, 100)

    # --- Sector-relative score: rank-normalise within broad_sector (0-100) ---
    sector_scores = []
    for _sector, idx in out.groupby("broad_sector").groups.items():
        sub = out.loc[idx, CompositeResult.OVERALL]
        if len(sub) <= 1:
            sector_scores.append(pd.Series(50.0, index=sub.index))
        else:
            lo, hi = sub.min(), sub.max()
            scaled = (sub - lo) / (hi - lo) * 100.0 if hi > lo else pd.Series(50.0, index=sub.index)
            sector_scores.append(scaled)
    if sector_scores:
        out[CompositeResult.SECTOR_REL] = pd.concat(sector_scores).reindex(out.index)
    else:
        out[CompositeResult.SECTOR_REL] = 50.0

    # --- Ranks (1 = best) ---
    # Use nullable Int64 to tolerate NaN scores safely (defensive: production
    # latest-year dataset has no NaNs, but in-memory test DBs may).
    out[CompositeResult.UNIV_RANK] = (
        out[CompositeResult.OVERALL].rank(ascending=False, method="min").astype("Int64")
    )
    out[CompositeResult.SECTOR_RANK] = (
        out.groupby("broad_sector")[CompositeResult.OVERALL]
        .rank(ascending=False, method="min")
        .astype("Int64")
    )

    return out


def compute_composite_scores(
    df: pd.DataFrame,
    *,
    db_path: str | None = None,
) -> CompositeResult:
    """Attach FCF CAGR 5y (from cashflow table), compute winsorised component
    scores, overall composite, sector-relative composite, and ranks.

    Args:
        df: Latest-year screener dataset from ``load_screener_dataset``.
        db_path: Override DB path for FCF CAGR computation.
    """
    fcf_cagr_df = compute_fcf_cagr_5yr(
        db_path=db_path, latest_year=df["year"].iloc[0] if len(df) else None
    )
    merged = df.merge(fcf_cagr_df, on="company_id", how="left")
    scored = compute_component_scores(merged)

    # Re-sort by composite_score_100 descending
    scored = scored.sort_values(
        CompositeResult.OVERALL, ascending=False, na_position="last"
    ).reset_index(drop=True)
    # Refresh ranks after sort: composite_rank = 1..N (contiguous), sector_rank
    # recomputed via groupby rank. Use nullable Int64 to tolerate NaN scores.
    scored[CompositeResult.UNIV_RANK] = list(range(1, len(scored) + 1))
    scored[CompositeResult.SECTOR_RANK] = (
        scored.groupby("broad_sector")[CompositeResult.OVERALL]
        .rank(ascending=False, method="min")
        .astype("Int64")
    )

    return CompositeResult(df=scored)
