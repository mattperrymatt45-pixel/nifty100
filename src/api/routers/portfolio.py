"""Portfolio router - Portfolio statistics, clusters, and analytics (stub).

Stub scaffold (Day 38). Endpoints will be added in subsequent days.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


@router.get("/", summary="Portfolio endpoint root (stub)")
def portfolio_root_stub() -> dict:
    """Placeholder root for the Portfolio router (implemented in later days)."""
    return {
        "module": "portfolio",
        "status": "scaffold",
        "message": "Portfolio endpoints will be populated in upcoming sprint days.",
    }


__all__ = ["router"]
