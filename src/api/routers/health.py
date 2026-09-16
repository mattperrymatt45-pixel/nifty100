"""Health router - liveness / readiness / diagnostics.

Exposes ``GET /api/v1/health`` which returns service status, DB row counts,
uptime, and API version.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from src.api.db import table_row_counts

router = APIRouter(tags=["Health"])

# Server start time (set from main.py at startup for accurate uptime).
_START_TIME: float = time.time()
API_VERSION: str = "1.0.0-sprint6"


def set_start_time(start_time: float) -> None:
    """Allow main.py to inject an explicit process start time."""
    global _START_TIME
    _START_TIME = start_time


@router.get("/health", summary="Service health check")
def health() -> dict:
    """Return service status, table row counts, uptime, and version.

    Returns 200 OK when the server can connect to the SQLite database and
    run a count query. Returns 503 if the database is unreachable.
    """
    try:
        counts = table_row_counts()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    return {
        "status": "ok",
        "db_row_counts": counts,
        "uptime_seconds": round(time.time() - _START_TIME, 3),
        "version": API_VERSION,
    }


__all__ = ["API_VERSION", "router", "set_start_time"]
