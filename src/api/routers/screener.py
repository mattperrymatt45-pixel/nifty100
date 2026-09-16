"""Screener router - Screener preset results and filter queries (stub).

Stub scaffold (Day 38). Endpoints will be added in subsequent days.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/screener", tags=["Screener"])


@router.get("/", summary="Screener endpoint root (stub)")
def screener_root_stub() -> dict:
    """Placeholder root for the Screener router (implemented in later days)."""
    return {
        "module": "screener",
        "status": "scaffold",
        "message": "Screener endpoints will be populated in upcoming sprint days.",
    }


__all__ = ["router"]
