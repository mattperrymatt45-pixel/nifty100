"""Companies router - company directory, identity, and profile data.

Stub scaffold (Day 38). Endpoints will be added in subsequent days.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.get("/", summary="List companies (stub)")
def list_companies_stub() -> dict:
    """Placeholder for company listing endpoint (implemented in later days)."""
    return {
        "module": "companies",
        "status": "scaffold",
        "message": "Companies endpoints will be populated in upcoming sprint days.",
    }


__all__ = ["router"]
