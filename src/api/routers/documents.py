"""Documents router - annual report link metadata."""

from __future__ import annotations

import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Query

from src.api.db import get_db_connection

router = APIRouter(tags=["Documents"])

_DOCS_QUERY = """
    SELECT Year AS year, Annual_Report AS url
    FROM documents
    WHERE company_id = ?
    ORDER BY Year DESC
"""

_MISSING_TOKEN = "/missing/"


def _is_url_valid(url: str, timeout: float = 2.0) -> bool:
    """Lightweight HEAD (GET fallback) check, same semantics as the dashboard.

    Returns False immediately for empty/missing-token URLs. Network errors
    return False rather than raising.
    """
    if not url:
        return False
    if _MISSING_TOKEN in url:
        return False
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Nifty100-API/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, ValueError, TimeoutError):
        return False


@router.get("/companies/{ticker}/documents", summary="List annual reports for a company")
def get_company_documents(
    ticker: str,
    check_urls: bool | None = Query(
        False,
        alias="check-urls",
        description="If true, perform a live URL HEAD check (slower).",
    ),
) -> dict:
    """Return annual report links per fiscal year for the given company.

    Each entry contains ``year``, ``url`` and ``is_url_valid``. When
    ``?check-urls=true`` is supplied, URLs are probed with a lightweight
    HEAD request (2-second timeout); otherwise validity is inferred from
    the presence of a ``/missing/`` path token in the source URL (fast).
    """
    tid = ticker.upper()
    with get_db_connection() as conn:
        exists = conn.execute("SELECT 1 FROM companies WHERE id = ?", [tid]).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail=f"Company '{tid}' not found")
        rows = conn.execute(_DOCS_QUERY, [tid]).fetchall()
    items = []
    for r in rows:
        url = r["url"]
        valid = _is_url_valid(url) if check_urls else bool(url) and _MISSING_TOKEN not in url
        items.append({"year": r["year"], "url": url, "is_url_valid": valid})
    return {"ticker": tid, "count": len(items), "live_check": bool(check_urls), "documents": items}


__all__ = ["router"]
