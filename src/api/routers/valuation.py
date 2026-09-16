"""Valuation router - historical market-cap multiples for a company."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.db import get_db_connection

router = APIRouter(prefix="/market-cap", tags=["Valuation"])

_MCAP_QUERY = """
    SELECT year,
           market_cap_crore,
           enterprise_value_crore,
           pe_ratio,
           pb_ratio,
           ev_ebitda,
           dividend_yield_pct
    FROM market_cap
    WHERE company_id = ? AND year BETWEEN 2019 AND 2024
    ORDER BY year
"""


@router.get("/{ticker}", summary="Historical valuation multiples (2019-2024)")
def get_market_cap_history(ticker: str) -> dict:
    """Return annual market-cap, P/E, P/B, EV/EBITDA and dividend yield for
    the company from calendar year 2019 through 2024. Returns 404 for an
    unknown ticker or a company with no market-cap rows in that window.
    """
    tid = ticker.upper()
    with get_db_connection() as conn:
        exists = conn.execute("SELECT 1 FROM companies WHERE id = ?", [tid]).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"Company '{tid}' not found")
        rows = conn.execute(_MCAP_QUERY, [tid]).fetchall()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No market-cap history found for '{tid}' (2019-2024)",
        )
    return {
        "ticker": tid,
        "count": len(rows),
        "year_range": [rows[0]["year"], rows[-1]["year"]],
        "history": [dict(r) for r in rows],
    }


__all__ = ["router"]
