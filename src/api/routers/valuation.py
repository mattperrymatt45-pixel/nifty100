"""Valuation router - Valuation multiples and sector-relative flags (stub).

Stub scaffold (Day 38). Endpoints will be added in subsequent days.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/valuation", tags=["Valuation"])


@router.get("/", summary="Valuation endpoint root (stub)")
def valuation_root_stub() -> dict:
    """Placeholder root for the Valuation router (implemented in later days)."""
    return {
        "module": "valuation",
        "status": "scaffold",
        "message": "Valuation endpoints will be populated in upcoming sprint days.",
    }


__all__ = ["router"]
