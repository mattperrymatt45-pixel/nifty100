"""Screener endpoint - filterable ranked company list.

``GET /api/v1/screener`` accepts numeric filter parameters (min_roe, max_de,
min_fcf, sector, min_rev_cagr_5yr, min_pat_cagr_5yr, max_pe) and returns
companies ranked by composite quality score. Invalid parameter values
(non-numeric) return HTTP 400.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.api.db import get_db_connection

router = APIRouter(prefix="/screener", tags=["Screener"])

# Base query: latest-year panel with the columns we can filter/rank on.
_BASE_QUERY = """
    SELECT
        c.id AS id,
        c.company_name AS company_name,
        s.broad_sector AS sector,
        s.sub_sector AS sub_sector,
        fr.year AS fy,
        fr.return_on_equity_pct AS roe_pct,
        fr.roce_pct AS roce_pct,
        fr.debt_to_equity AS debt_to_equity,
        fr.operating_profit_margin_pct AS opm_pct,
        fr.net_profit_margin_pct AS npm_pct,
        fr.revenue_cagr_5yr AS revenue_cagr_5yr,
        fr.pat_cagr_5yr AS pat_cagr_5yr,
        fr.free_cash_flow_cr AS free_cash_flow_cr,
        fr.composite_quality_score AS composite_score,
        mc.pe_ratio AS pe_ratio,
        mc.pb_ratio AS pb_ratio,
        mc.dividend_yield_pct AS dividend_yield_pct,
        mc.market_cap_crore AS market_cap_crore
    FROM companies c
    LEFT JOIN sectors s ON s.company_id = c.id
    LEFT JOIN financial_ratios fr
        ON fr.company_id = c.id
       AND fr.year = (SELECT MAX(fr2.year) FROM financial_ratios fr2 WHERE fr2.company_id = c.id)
    LEFT JOIN market_cap mc
        ON mc.company_id = c.id
       AND mc.year = (SELECT MAX(mc2.year) FROM market_cap mc2 WHERE mc2.company_id = c.id)
"""


def _parse_float(name: str, raw: str | None) -> float | None:
    """Parse an optional float query param; raise 400 on bad input."""
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid value for query parameter '{name}': expected a number, got '{raw}'",
        ) from exc


@router.get("/", summary="Screen companies by fundamental filters")
def screen_companies(
    min_roe: str | None = Query(None, description="Minimum ROE %."),
    max_de: str | None = Query(None, description="Maximum debt-to-equity."),
    min_fcf: str | None = Query(None, description="Minimum free cash flow (Rs crore)."),
    sector: str | None = Query(None, description="Exact broad_sector name."),
    min_rev_cagr_5yr: str | None = Query(None, description="Minimum 5-year revenue CAGR %."),
    min_pat_cagr_5yr: str | None = Query(None, description="Minimum 5-year PAT CAGR %."),
    max_pe: str | None = Query(None, description="Maximum P/E ratio."),
) -> dict:
    # Parse numeric params (400 on invalid)
    """Return a filtered, ranked list of companies matching the supplied query parameters."""
    f_min_roe = _parse_float("min_roe", min_roe)
    f_max_de = _parse_float("max_de", max_de)
    f_min_fcf = _parse_float("min_fcf", min_fcf)
    f_min_rev = _parse_float("min_rev_cagr_5yr", min_rev_cagr_5yr)
    f_min_pat = _parse_float("min_pat_cagr_5yr", min_pat_cagr_5yr)
    f_max_pe = _parse_float("max_pe", max_pe)

    clauses: list[str] = []
    params: list[Any] = []
    if f_min_roe is not None:
        clauses.append("fr.return_on_equity_pct >= ?")
        params.append(f_min_roe)
    if f_max_de is not None:
        clauses.append("(fr.debt_to_equity <= ? OR fr.debt_to_equity IS NULL)")
        params.append(f_max_de)
    if f_min_fcf is not None:
        clauses.append("fr.free_cash_flow_cr >= ?")
        params.append(f_min_fcf)
    if sector:
        clauses.append("s.broad_sector = ?")
        params.append(sector)
    if f_min_rev is not None:
        clauses.append("fr.revenue_cagr_5yr >= ?")
        params.append(f_min_rev)
    if f_min_pat is not None:
        clauses.append("fr.pat_cagr_5yr >= ?")
        params.append(f_min_pat)
    if f_max_pe is not None:
        clauses.append("(mc.pe_ratio <= ? OR mc.pe_ratio IS NULL)")
        params.append(f_max_pe)

    sql = _BASE_QUERY
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY COALESCE(fr.composite_quality_score, 0) DESC, c.id"

    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = [dict(r) for r in rows]

    return {
        "count": len(items),
        "filters_applied": {
            "min_roe": f_min_roe,
            "max_de": f_max_de,
            "min_fcf": f_min_fcf,
            "sector": sector,
            "min_rev_cagr_5yr": f_min_rev,
            "min_pat_cagr_5yr": f_min_pat,
            "max_pe": f_max_pe,
        },
        "companies": items,
    }


__all__ = ["router"]
