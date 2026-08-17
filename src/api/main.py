"""
Nifty 100 Financial Intelligence Platform - FastAPI Application.

NOTE: This is a scaffold file for Sprint 4 (API).
The full REST API will be implemented in a later sprint.
Running `make run-api` will launch this placeholder server.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI

# Ensure project root is importable when launched via `uvicorn`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

app = FastAPI(
    title="Nifty 100 Financial Intelligence Platform API",
    description="REST API for querying Nifty 100 financial data, analytics, and metrics.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/", tags=["Root"])
async def root() -> dict:
    """Root endpoint - returns basic API metadata."""
    logger.info("Root endpoint called")
    return {
        "name": "Nifty 100 Financial Intelligence Platform API",
        "version": "0.1.0",
        "status": "placeholder - Sprint 4 implementation pending",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """Simple health-check endpoint for load balancers / monitoring."""
    return {"status": "ok"}


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("FastAPI application starting up (placeholder)")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("FastAPI application shutting down")
