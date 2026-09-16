"""Sector endpoints - sector directory and per-sector company lists."""

from __future__ import annotations

import statistics
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.db import get_db_connection

router = APIRouter(prefix="/sectors", tags=["Sectors"])

_SECTOR_RAW_QUERY = """
    SELECT
        s.broad_sector AS sector,
        c.id AS company_id,
        fr.return_on_equity_pct AS roe_pct,
        mc.pe_ratio AS pe_ratio,
        fr.debt_to_equity AS debt_to_equity
    FROM sectors s
    JOIN companies c ON c.id = s.company_id
    LEFT JOIN financial_ratios fr
        ON fr.company_id = c.id
       AND fr.year = (SELECT MAX(fr2.year) FROM financial_ratios fr2 WHERE fr2.company_id = c.id)
    LEFT JOIN market_cap mc
        ON mc.company_id = c.id
       AND mc.year = (SELECT MAX(mc2.year) FROM market_cap mc2 WHERE mc2.company_id = c.id)
    ORDER BY s.broad_sector, c.id
"""

_SECTOR_COMPANIES_QUERY = """
    SELECT
        c.id AS id,
        c.company_name AS company_name,
        s.sub_sector AS sub_sector,
        s.market_cap_category AS market_cap_category,
        fr.year AS fy,
        fr.return_on_equity_pct AS roe_pct,
        fr.roce_pct AS roce_pct,
        fr.debt_to_equity AS debt_to_equity,
        fr.operating_profit_margin_pct AS opm_pct,
        fr.net_profit_margin_pct AS npm_pct,
        fr.revenue_cagr_5yr AS revenue_cagr_5yr,
        fr.pat_cagr_5yr AS pat_cagr_5yr,
        fr.composite_quality_score AS composite_score,
        mc.pe_ratio AS pe_ratio,
        mc.pb_ratio AS pb_ratio,
        mc.dividend_yield_pct AS dividend_yield_pct,
        mc.market_cap_crore AS market_cap_crore
    FROM sectors s
    JOIN companies c ON c.id = s.company_id
    LEFT JOIN financial_ratios fr
        ON fr.company_id = c.id
       AND fr.year = (SELECT MAX(fr2.year) FROM financial_ratios fr2 WHERE fr2.company_id = c.id)
    LEFT JOIN market_cap mc
        ON mc.company_id = c.id
       AND mc.year = (SELECT MAX(mc2.year) FROM market_cap mc2 WHERE mc2.company_id = c.id)
    WHERE s.broad_sector = ?
    ORDER BY c.id
"""


def _median(vals: list[float]) -> float | None:
    clean = [v for v in vals if v is not None]
    if not clean:
        return None
    return round(float(statistics.median(clean)), 3)


@router.get("/", summary="List all sectors with summary KPIs")
def list_sectors() -> dict:
    """Return all broad sectors with company_count and median ROE / P/E / D/E
    (medians computed in-Python because SQLite has no MEDIAN()).
    """
    with get_db_connection() as conn:
        rows = conn.execute(_SECTOR_RAW_QUERY).fetchall()
    # Group by sector
    buckets: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        d = dict(r)
        sec = d["sector"]
        buckets.setdefault(sec, {"roe": [], "pe": [], "de": []})
        if d["roe_pct"] is not None:
            buckets[sec]["roe"].append(float(d["roe_pct"]))
        if d["pe_ratio"] is not None:
            buckets[sec]["pe"].append(float(d["pe_ratio"]))
        if d["debt_to_equity"] is not None:
            buckets[sec]["de"].append(float(d["debt_to_equity"]))
    items: list[dict[str, Any]] = []
    for sec, vals in buckets.items():
        items.append(
            {
                "sector": sec,
                "company_count": len(vals["roe"]) or len(vals["pe"]) or len(vals["de"]),
                "median_roe": _median(vals["roe"]),
                "median_pe": _median(vals["pe"]),
                "median_de": _median(vals["de"]),
            }
        )
    items.sort(key=lambda x: x["company_count"], reverse=True)
    return {"count": len(items), "sectors": items}


@router.get("/{sector}/companies", summary="List companies in a sector")
def get_sector_companies(sector: str) -> dict:
    """Return all companies in a broad sector with latest-year KPIs.
    Returns 404 for an unknown sector name.
    """
    with get_db_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sectors WHERE broad_sector = ? LIMIT 1", [sector]
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"Sector '{sector}' not found")
        rows = conn.execute(_SECTOR_COMPANIES_QUERY, [sector]).fetchall()
    items = [dict(r) for r in rows]
    return {"sector": sector, "count": len(items), "companies": items}


__all__ = ["router"]
