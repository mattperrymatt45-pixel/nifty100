"""Peer group endpoints - group membership, percentiles, and radar comparison."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.db import get_db_connection

router = APIRouter(prefix="/peers", tags=["Peers"])

_PEER_METRICS: tuple[str, ...] = (
    "roe",
    "roce",
    "npm",
    "de",
    "fcf",
    "pat_cagr_5yr",
    "rev_cagr_5yr",
    "asset_turnover",
    "interest_coverage",
    "eps_cagr_5yr",
)

_GROUP_QUERY = """
    SELECT
        pg.company_id         AS company_id,
        c.company_name        AS company_name,
        pg.is_benchmark       AS is_benchmark
    FROM peer_groups pg
    JOIN companies c ON c.id = pg.company_id
    WHERE pg.peer_group_name = ?
    ORDER BY pg.is_benchmark DESC, c.id
"""

_PERCENTILES_QUERY = """
    SELECT company_id, metric, value, percentile_rank
    FROM peer_percentiles
    WHERE peer_group_name = ?
      AND year = (
        SELECT MAX(year) FROM peer_percentiles WHERE peer_group_name = ?
      )
"""

_COMPANY_GROUP_QUERY = """
    SELECT peer_group_name, is_benchmark FROM peer_groups WHERE company_id = ?
"""

# Radar: 8 axis values needed for compare endpoint.
# peer_percentiles table stores roe/roce/npm/de/pat_cagr_5yr/rev_cagr_5yr
# but NOT cfo_pat or composite — compute those separately from ratios table.
_LATEST_RATIOS_QUERY = """
    SELECT return_on_equity_pct, roce_pct, net_profit_margin_pct, debt_to_equity,
           cfo_pat_ratio, pat_cagr_5yr, revenue_cagr_5yr, composite_quality_score,
           free_cash_flow_cr
    FROM financial_ratios
    WHERE company_id = ? AND year = (SELECT MAX(year) FROM financial_ratios WHERE company_id = ?)
"""


@router.get("/{group_name}", summary="Get peer group members with percentiles")
def get_peer_group(group_name: str) -> dict:
    """Return all companies in a peer group with percentile ranks for each
    of the 10 standard metrics. Returns 404 for an unknown group.
    """
    with get_db_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM peer_groups WHERE peer_group_name = ? LIMIT 1", [group_name]
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"Peer group '{group_name}' not found")
        members = conn.execute(_GROUP_QUERY, [group_name]).fetchall()
        perc_rows = conn.execute(_PERCENTILES_QUERY, [group_name, group_name]).fetchall()

    # Build nested dict: company_id -> {metric: {value, percentile_rank}}
    by_co: dict[str, dict[str, dict[str, Any]]] = {
        m["company_id"]: {
            "company_id": m["company_id"],
            "company_name": m["company_name"],
            "is_benchmark": bool(m["is_benchmark"]),
            "metrics": {},
        }
        for m in (dict(r) for r in members)
    }
    for row in perc_rows:
        d = dict(row)
        cid = d["company_id"]
        if cid in by_co:
            by_co[cid]["metrics"][d["metric"]] = {
                "value": d["value"],
                "percentile_rank": (
                    round(float(d["percentile_rank"]), 4)
                    if d["percentile_rank"] is not None
                    else None
                ),
            }

    return {
        "peer_group": group_name,
        "count": len(by_co),
        "metrics": list(_PEER_METRICS),
        "companies": list(by_co.values()),
    }


def _percentile_rank(values: list[float], v: float) -> float:
    """Percent rank using (rank-1)/(n-1) — same formula as Day 18."""
    s = sorted(x for x in values if x is not None)
    n = len(s)
    if n <= 1:
        return 0.5
    below = sum(1 for x in s if x < v)
    return round(below / (n - 1), 4)


def _radar_for_company(conn: sqlite3.Connection, cid: str) -> dict[str, float | None] | None:
    r = conn.execute(_LATEST_RATIOS_QUERY, [cid, cid]).fetchone()
    if r is None:
        return None
    d = dict(r)
    return {
        "roe": d["return_on_equity_pct"],
        "roce": d["roce_pct"],
        "npm": d["net_profit_margin_pct"],
        "de": d["debt_to_equity"],  # will invert in caller
        "cfo_pat": d["cfo_pat_ratio"],
        "pat_cagr_5yr": d["pat_cagr_5yr"],
        "rev_cagr_5yr": d["revenue_cagr_5yr"],
        "composite": d["composite_quality_score"],
    }


@router.get("/../companies/{ticker}/peers/compare", include_in_schema=False)
def _placeholder() -> dict:  # pragma: no cover - fallback so FastAPI resolves
    return {}


# Register compare at /api/v1/companies/{ticker}/peers/compare by mounting
# a sub-router at the companies prefix in main.py is awkward; instead we
# expose it here and also register explicitly in main.py. For cleanliness
# we define the real handler here and add the route on the companies router
# via a helper.
def radar_compare(ticker: str) -> dict:
    """Return radar data for company vs peer-group average + benchmark."""
    tid = ticker.upper()
    radar_axes = (
        "roe",
        "roce",
        "npm",
        "de",
        "cfo_pat",
        "pat_cagr_5yr",
        "rev_cagr_5yr",
        "composite",
    )
    with get_db_connection() as conn:
        # Find which peer group this company belongs to
        gr = conn.execute(_COMPANY_GROUP_QUERY, [tid]).fetchone()
        if gr is None:
            raise HTTPException(
                status_code=404,
                detail=f"Company '{tid}' has no peer group assigned",
            )
        group_name = gr["peer_group_name"]
        # Get all members
        members = conn.execute(_GROUP_QUERY, [group_name]).fetchall()
        member_ids = [m["company_id"] for m in members]
        if tid not in member_ids:
            raise HTTPException(status_code=404, detail=f"Company '{tid}' not in group")
        # Build radar vectors for all members
        all_vecs: dict[str, dict[str, float | None]] = {}
        for mid in member_ids:
            v = _radar_for_company(conn, mid)
            if v is not None:
                all_vecs[mid] = v
        # Benchmark id
        bench_row = conn.execute(
            "SELECT company_id FROM peer_groups WHERE peer_group_name = ? AND is_benchmark = 1",
            [group_name],
        ).fetchone()
        bench_id = bench_row["company_id"] if bench_row else None

    # Compute peer-group average per axis (mean of raw values — for chart)
    avg_vec: dict[str, float | None] = {}
    for axis in radar_axes:
        vals = [v[axis] for v in all_vecs.values() if v.get(axis) is not None]
        avg_vec[axis] = round(sum(vals) / len(vals), 4) if vals else None

    # D/E inverted for "higher is better" radar representation
    company_vec = all_vecs.get(tid, {})
    benchmark_vec = all_vecs.get(bench_id) if bench_id else None

    return {
        "ticker": tid,
        "peer_group": group_name,
        "benchmark_ticker": bench_id,
        "axes": list(radar_axes),
        "company": company_vec,
        "peer_avg": avg_vec,
        "benchmark": benchmark_vec,
    }


__all__ = ["radar_compare", "router"]
