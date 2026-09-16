"""Companies router - directory, profile, financial history, and tearsheet.

Endpoints (Day 39):
    * GET  /api/v1/companies                       - list all 92 companies with
        identity + sector + headline ROE/ROCE; supports sector,
        market_cap_category, and search (partial ticker/name) filters.
    * GET  /api/v1/companies/{ticker}              - full company profile.
    * GET  /api/v1/companies/{ticker}/pl           - P&L time series.
    * GET  /api/v1/companies/{ticker}/bs           - balance-sheet time series.
    * GET  /api/v1/companies/{ticker}/cashflow     - cash-flow time series.
    * GET  /api/v1/companies/{ticker}/ratios       - computed KPI history
        (optional ?year=YYYY-MM for a single year).
    * GET  /api/v1/companies/{ticker}/tearsheet    - binary PDF download
        of the pre-generated tearsheet.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from src.api.db import get_db_connection, get_db_path

router = APIRouter(prefix="/companies", tags=["Companies"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_YEAR_RE: Any | None = None  # lazy compile - used only for validation msg


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Convert a sqlite3.Row to a plain dict, recursing into nested rows."""
    if row is None:
        return None
    # Iterating sqlite3.Row yields column *values*, not keys — use keys().
    return {k: row[k] for k in row.keys()}  # noqa: SIM118


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_row_to_dict(r) for r in rows]


def _validate_year(value: str | None, param: str) -> str | None:
    """Validate a YYYY-MM year query parameter; raise 422 on bad input."""
    if value is None:
        return None
    parts = value.split("-")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise HTTPException(
            status_code=422,
            detail=f"Query param '{param}' must be in YYYY-MM format (got '{value}')",
        )
    if len(parts[0]) != 4 or len(parts[1]) != 2:
        raise HTTPException(
            status_code=422,
            detail=f"Query param '{param}' must be in YYYY-MM format (got '{value}')",
        )
    return value


def _company_exists(conn: sqlite3.Connection, ticker: str) -> bool:
    cur = conn.execute("SELECT 1 FROM companies WHERE id = ?", [ticker.upper()])
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# 1. GET /companies/  - list companies with optional filters
# ---------------------------------------------------------------------------
_LIST_QUERY = """
    SELECT
        c.id            AS id,
        c.company_name  AS company_name,
        s.broad_sector  AS broad_sector,
        s.sub_sector    AS sub_sector,
        s.market_cap_category AS market_cap_category,
        COALESCE(fr.return_on_equity_pct, c.roe_percentage)  AS roe_pct,
        COALESCE(fr.roce_pct, c.roce_percentage)            AS roce_pct
    FROM companies c
    LEFT JOIN sectors s ON s.company_id = c.id
    LEFT JOIN financial_ratios fr
        ON fr.company_id = c.id
       AND fr.year = (SELECT MAX(fr2.year) FROM financial_ratios fr2 WHERE fr2.company_id = c.id)
"""


@router.get("/", summary="List all companies")
def list_companies(
    sector: str | None = Query(None, description="Filter by broad_sector (e.g. 'Financials')."),
    market_cap_category: str | None = Query(
        None, alias="market-cap", description="Filter by market cap category (Large Cap / Mid Cap)."
    ),
    search: str | None = Query(
        None, description="Case-insensitive partial match on ticker or company name."
    ),
) -> dict:
    """Return list of all companies (default) filtered by any of the
    query parameters. Each item includes id, name, sector, sub_sector,
    market_cap_category, and latest-year ROE / ROCE percentages.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if sector:
        clauses.append("s.broad_sector = ?")
        params.append(sector)
    if market_cap_category:
        clauses.append("s.market_cap_category = ?")
        params.append(market_cap_category)
    if search:
        clauses.append("(c.id LIKE ? OR c.company_name LIKE ?)")
        like = f"%{search.upper()}%"
        like2 = f"%{search}%"
        params.extend([like, like2])
    sql = _LIST_QUERY
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY c.id"
    with get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = _rows_to_list(rows)
    return {"count": len(items), "companies": items}


# ---------------------------------------------------------------------------
# 2. GET /companies/{ticker}  - full company profile
# ---------------------------------------------------------------------------
_PROFILE_QUERY = """
    SELECT c.*,
           s.broad_sector, s.sub_sector, s.index_weight_pct, s.market_cap_category
    FROM companies c
    LEFT JOIN sectors s ON s.company_id = c.id
    WHERE c.id = ?
"""

_LATEST_KPI_QUERY = """
    SELECT *
    FROM financial_ratios
    WHERE company_id = ?
    ORDER BY year DESC
    LIMIT 1
"""

_LATEST_MC_QUERY = """
    SELECT *
    FROM market_cap
    WHERE company_id = ?
    ORDER BY year DESC
    LIMIT 1
"""


@router.get("/{ticker}", summary="Get company profile")
def get_company(ticker: str) -> dict:
    """Return the full company profile: companies.* fields, sector data,
    and latest-year KPIs (financial_ratios + market_cap). Returns 404 if
    the ticker is not found.
    """
    tid = ticker.upper()
    with get_db_connection() as conn:
        core = conn.execute(_PROFILE_QUERY, [tid]).fetchone()
        if core is None:
            raise HTTPException(status_code=404, detail=f"Company '{tid}' not found")
        kpi = conn.execute(_LATEST_KPI_QUERY, [tid]).fetchone()
        mc = conn.execute(_LATEST_MC_QUERY, [tid]).fetchone()
    profile = _row_to_dict(core)
    profile["latest_kpis"] = _row_to_dict(kpi)
    profile["latest_valuation"] = _row_to_dict(mc)
    return profile


# ---------------------------------------------------------------------------
# 3-5. Time-series helpers for pl / bs / cashflow
# ---------------------------------------------------------------------------
def _fetch_history(
    table: str, ticker: str, from_year: str | None, to_year: str | None
) -> list[dict[str, Any]]:
    clauses = ["company_id = ?"]
    params: list[Any] = [ticker.upper()]
    if from_year:
        clauses.append("year >= ?")
        params.append(from_year)
    if to_year:
        clauses.append("year <= ?")
        params.append(to_year)
    sql = f'SELECT * FROM "{table}" WHERE {" AND ".join(clauses)} ORDER BY year'
    with get_db_connection() as conn:
        if not _company_exists(conn, ticker.upper()):
            return None  # signal to caller
        rows = conn.execute(sql, params).fetchall()
    return _rows_to_list(rows)


@router.get("/{ticker}/pl", summary="Profit & Loss history")
def get_pl(
    ticker: str,
    from_year: str | None = Query(None, alias="from", description="Start year (YYYY-MM)."),
    to_year: str | None = Query(None, alias="to", description="End year (YYYY-MM)."),
) -> dict:
    """Return P&L history (one row per fiscal year) for a company."""
    fy = _validate_year(from_year, "from")
    ty = _validate_year(to_year, "to")
    history = _fetch_history("profitandloss", ticker, fy, ty)
    if history is None:
        raise HTTPException(status_code=404, detail=f"Company '{ticker.upper()}' not found")
    return {
        "ticker": ticker.upper(),
        "statement": "profit_and_loss",
        "count": len(history),
        "history": history,
    }


@router.get("/{ticker}/bs", summary="Balance Sheet history")
def get_bs(
    ticker: str,
    from_year: str | None = Query(None, alias="from", description="Start year (YYYY-MM)."),
    to_year: str | None = Query(None, alias="to", description="End year (YYYY-MM)."),
) -> dict:
    """Return balance-sheet history for a company."""
    fy = _validate_year(from_year, "from")
    ty = _validate_year(to_year, "to")
    history = _fetch_history("balancesheet", ticker, fy, ty)
    if history is None:
        raise HTTPException(status_code=404, detail=f"Company '{ticker.upper()}' not found")
    return {
        "ticker": ticker.upper(),
        "statement": "balance_sheet",
        "count": len(history),
        "history": history,
    }


@router.get("/{ticker}/cashflow", summary="Cash Flow history")
def get_cashflow(
    ticker: str,
    from_year: str | None = Query(None, alias="from", description="Start year (YYYY-MM)."),
    to_year: str | None = Query(None, alias="to", description="End year (YYYY-MM)."),
) -> dict:
    """Return cash-flow history for a company."""
    fy = _validate_year(from_year, "from")
    ty = _validate_year(to_year, "to")
    history = _fetch_history("cashflow", ticker, fy, ty)
    if history is None:
        raise HTTPException(status_code=404, detail=f"Company '{ticker.upper()}' not found")
    return {
        "ticker": ticker.upper(),
        "statement": "cash_flow",
        "count": len(history),
        "history": history,
    }


# ---------------------------------------------------------------------------
# 6. GET /companies/{ticker}/ratios   - computed KPI history
# ---------------------------------------------------------------------------
@router.get("/{ticker}/ratios", summary="Computed KPI history")
def get_ratios(
    ticker: str,
    year: str | None = Query(None, description="Return a single fiscal year (YYYY-MM)."),
) -> dict:
    """Return all computed financial ratios per year for a company, or a
    single year when ``year`` is supplied.
    """
    tid = ticker.upper()
    yr = _validate_year(year, "year")
    with get_db_connection() as conn:
        if not _company_exists(conn, tid):
            raise HTTPException(status_code=404, detail=f"Company '{tid}' not found")
        if yr:
            rows = conn.execute(
                "SELECT * FROM financial_ratios WHERE company_id = ? AND year = ? ORDER BY year",
                [tid, yr],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM financial_ratios WHERE company_id = ? ORDER BY year",
                [tid],
            ).fetchall()
    history = _rows_to_list(rows)
    return {"ticker": tid, "count": len(history), "ratios": history}


# ---------------------------------------------------------------------------
# 7. GET /companies/{ticker}/tearsheet - PDF download
# ---------------------------------------------------------------------------
def _tearsheet_dir() -> Path:
    return Path(get_db_path()).parent.parent / "reports" / "tearsheets"


@router.get("/{ticker}/tearsheet", summary="Download tearsheet PDF")
def get_tearsheet(ticker: str) -> FileResponse:
    """Return the pre-generated tearsheet PDF as ``application/pdf``."""
    tid = ticker.upper()
    pdf_path = _tearsheet_dir() / f"{tid}_tearsheet.pdf"
    # Check company exists for proper 404 message
    with get_db_connection() as conn:
        if not _company_exists(conn, tid):
            raise HTTPException(status_code=404, detail=f"Company '{tid}' not found")
    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Tearsheet PDF for '{tid}' has not been generated. Expected: {pdf_path.name}",
        )
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"{tid}_tearsheet.pdf",
        headers={"Content-Disposition": f'attachment; filename="{tid}_tearsheet.pdf"'},
    )


__all__ = ["router"]
