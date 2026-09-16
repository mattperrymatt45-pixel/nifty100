"""Peers router - Peer group composition and peer percentiles (stub).

Stub scaffold (Day 38). Endpoints will be added in subsequent days.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/peers", tags=["Peers"])


@router.get("/", summary="Peers endpoint root (stub)")
def peers_root_stub() -> dict:
    """Placeholder root for the Peers router (implemented in later days)."""
    return {
        "module": "peers",
        "status": "scaffold",
        "message": "Peers endpoints will be populated in upcoming sprint days.",
    }


__all__ = ["router"]
