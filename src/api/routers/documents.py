"""Documents router - Company documents / annual report metadata (stub).

Stub scaffold (Day 38). Endpoints will be added in subsequent days.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("/", summary="Documents endpoint root (stub)")
def documents_root_stub() -> dict:
    """Placeholder root for the Documents router (implemented in later days)."""
    return {
        "module": "documents",
        "status": "scaffold",
        "message": "Documents endpoints will be populated in upcoming sprint days.",
    }


__all__ = ["router"]
