"""Sectors router - Sector breakdown and sector-level KPIs (stub).

Stub scaffold (Day 38). Endpoints will be added in subsequent days.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/sectors", tags=["Sectors"])


@router.get("/", summary="Sectors endpoint root (stub)")
def sectors_root_stub() -> dict:
    """Placeholder root for the Sectors router (implemented in later days)."""
    return {
        "module": "sectors",
        "status": "scaffold",
        "message": "Sectors endpoints will be populated in upcoming sprint days.",
    }


__all__ = ["router"]
