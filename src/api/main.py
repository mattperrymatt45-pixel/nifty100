"""Nifty 100 Financial Intelligence Platform - FastAPI Application (Day 38).

Production-ready scaffold for Sprint 6 REST API:
    * CORS middleware allowing all origins (internal-use only).
    * Request-logging middleware: method, path, status, response time.
    * Eight routers mounted under ``/api/v1``:
        companies, screener, sectors, peers, valuation, portfolio,
        documents, health.
    * ``GET /api/v1/health`` returns status=ok, DB row counts, uptime_seconds,
      and the API version string.

Run locally:
    uvicorn src.api.main:app --port 8000 --host 0.0.0.0 --reload

Docs:
    * Swagger UI:  http://localhost:8000/docs
    * ReDoc:       http://localhost:8000/redoc
    * OpenAPI JSON: http://localhost:8000/openapi.json
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure project root is importable when launched via ``uvicorn``.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.routers import (  # noqa: E402
    companies,
    documents,
    health,
    peers,
    portfolio,
    screener,
    sectors,
    valuation,
)
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

API_TITLE = "Nifty 100 Financial Intelligence Platform API"
API_DESCRIPTION = (
    "REST API for querying Nifty 100 financial data, analytics, screener "
    "results, peer comparisons, valuation, and portfolio intelligence."
)
API_VERSION = health.API_VERSION

# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------------------------
# CORS middleware - allow all origins (internal deployment only).
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request logging middleware - method, path, status, response time.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log method, path, response status, and elapsed time for every request."""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.error(
            "request method={} path={} status=500 elapsed_ms={:.2f} error={}",
            request.method,
            request.url.path,
            elapsed_ms,
            exc,
        )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    logger.info(
        "request method={} path={} status={} elapsed_ms={:.2f}",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


# ---------------------------------------------------------------------------
# Routers mounted under /api/v1
# ---------------------------------------------------------------------------
API_PREFIX = "/api/v1"

app.include_router(health.router, prefix=API_PREFIX)
app.include_router(companies.router, prefix=API_PREFIX)
app.include_router(screener.router, prefix=API_PREFIX)
app.include_router(sectors.router, prefix=API_PREFIX)
app.include_router(peers.router, prefix=API_PREFIX)
app.include_router(valuation.router, prefix=API_PREFIX)
app.include_router(portfolio.router, prefix=API_PREFIX)
app.include_router(documents.router, prefix=API_PREFIX)


# ---------------------------------------------------------------------------
# Root + OpenAPI export
# ---------------------------------------------------------------------------
@app.get("/", tags=["Root"])
def root() -> dict:
    """Root endpoint - API metadata and link to documentation."""
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "status": "ok",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": f"{API_PREFIX}/health",
    }


def _openapi_schema() -> dict:
    """Return the resolved OpenAPI schema dict (works across FastAPI versions)."""
    return app.openapi()


@app.get("/export/openapi.json", tags=["Export"])
def export_openapi() -> JSONResponse:
    """Return the OpenAPI 3.x specification as JSON (also written to
    ``docs/openapi.json`` on demand by the CLI exporter).
    """
    schema = _openapi_schema()
    return JSONResponse(schema)


@app.get("/export/postman.json", tags=["Export"])
def export_postman() -> JSONResponse:
    """Generate a Postman Collection v2.1 JSON document with one request
    per documented GET endpoint. Intended for quick import into Postman
    without manual setup.
    """
    schema = _openapi_schema()
    base = "http://localhost:8000"
    items: list[dict] = []
    for path, ops in schema.get("paths", {}).items():
        for method, op in ops.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch"}:
                continue
            items.append(
                {
                    "name": f"{method.upper()} {path} — {op.get('summary', path)}",
                    "request": {
                        "method": method.upper(),
                        "header": [{"key": "Accept", "value": "application/json"}],
                        "url": {
                            "raw": base + path,
                            "host": ["localhost"],
                            "port": "8000",
                            "path": [p for p in path.strip("/").split("/") if p],
                        },
                        "description": op.get("description", op.get("summary", "")),
                    },
                }
            )
    collection = {
        "info": {
            "name": "Nifty 100 Financial Intelligence Platform API",
            "description": API_DESCRIPTION,
            "version": API_VERSION,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
    }
    return JSONResponse(collection)


# ---------------------------------------------------------------------------
# Startup / shutdown hooks
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup() -> None:
    # Seed the health router's uptime clock from this process's start.
    health.set_start_time(time.time())
    logger.info("FastAPI application starting up (version={})", API_VERSION)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("FastAPI application shutting down")


__all__ = ["API_PREFIX", "API_VERSION", "app"]
