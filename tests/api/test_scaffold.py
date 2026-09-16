"""Tests for Sprint 6 Day 38 - FastAPI Server Scaffold."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.api.db import BUSINESS_TABLES, get_db_path, table_row_counts
from src.api.main import API_PREFIX, API_VERSION, app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client() -> TestClient:
    """Yield a TestClient bound to the FastAPI application."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
class TestDBHelpers:
    def test_db_path_exists(self):
        p = get_db_path()
        assert p.exists()
        assert p.suffix == ".db"

    def test_business_tables_is_10(self):
        assert len(BUSINESS_TABLES) == 10

    def test_business_tables_unique(self):
        assert len(set(BUSINESS_TABLES)) == 10

    def test_row_counts_has_10_keys(self):
        counts = table_row_counts()
        assert len(counts) == 10
        assert set(counts.keys()) == set(BUSINESS_TABLES)

    def test_row_counts_companies_92(self):
        counts = table_row_counts()
        assert counts["companies"] == 92
        assert counts["sectors"] == 92
        assert counts["stock_prices"] > 0
        assert counts["profitandloss"] > 0


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------
class TestRoot:
    def test_root_200(self, client: TestClient):
        r = client.get("/")
        assert r.status_code == 200

    def test_root_payload(self, client: TestClient):
        data = client.get("/").json()
        assert data["name"]
        assert data["version"] == API_VERSION
        assert data["status"] == "ok"
        assert data["docs"] == "/docs"
        assert data["openapi"] == "/openapi.json"
        assert data["health"] == f"{API_PREFIX}/health"


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
class TestCORS:
    def test_cors_preflight_allows_all_origins(self, client: TestClient):
        r = client.options(
            "/api/v1/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "*"
        assert "GET" in r.headers.get("access-control-allow-methods", "")

    def test_cors_header_on_response(self, client: TestClient):
        r = client.get("/api/v1/health", headers={"Origin": "https://example.com"})
        assert r.headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------
class TestLoggingMiddleware:
    def test_x_response_time_header_present(self, client: TestClient):
        r = client.get("/api/v1/health")
        assert "x-response-time-ms" in r.headers
        ms = float(r.headers["x-response-time-ms"])
        assert ms >= 0.0

    def test_x_response_time_is_numeric(self, client: TestClient):
        r = client.get("/")
        ms = float(r.headers["x-response-time-ms"])
        assert ms < 1000.0  # sanity - nothing in scaffold takes over a second


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
class TestHealthEndpoint:
    def test_health_200(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200

    def test_health_keys(self, client: TestClient):
        data = client.get(f"{API_PREFIX}/health").json()
        assert data["status"] == "ok"
        assert "db_row_counts" in data
        assert "uptime_seconds" in data
        assert data["version"] == API_VERSION

    def test_health_db_counts_10_tables(self, client: TestClient):
        data = client.get(f"{API_PREFIX}/health").json()
        assert len(data["db_row_counts"]) == 10

    def test_health_db_counts_sane_values(self, client: TestClient):
        data = client.get(f"{API_PREFIX}/health").json()
        counts = data["db_row_counts"]
        assert counts["companies"] == 92
        assert counts["sectors"] == 92
        for _table, n in counts.items():
            assert isinstance(n, int)
            assert n >= 0

    def test_uptime_increases(self, client: TestClient):
        r1 = client.get(f"{API_PREFIX}/health").json()
        time.sleep(0.1)
        r2 = client.get(f"{API_PREFIX}/health").json()
        assert r2["uptime_seconds"] >= r1["uptime_seconds"]


# ---------------------------------------------------------------------------
# All 8 routers registered under /api/v1
# ---------------------------------------------------------------------------
EXPECTED_ROUTER_STUBS = [
    ("screener", "screener"),
    ("sectors", "sectors"),
    ("peers", "peers"),
    ("valuation", "valuation"),
    ("portfolio", "portfolio"),
    ("documents", "documents"),
]


class TestRouterRegistration:
    @pytest.mark.parametrize("name,_tag", EXPECTED_ROUTER_STUBS)
    def test_stub_returns_200(self, client: TestClient, name: str, _tag: str):
        r = client.get(f"{API_PREFIX}/{name}/")
        assert r.status_code == 200, f"Router {name} did not return 200"
        body = r.json()
        assert body["module"] == name
        assert body["status"] == "scaffold"

    def test_companies_root_returns_list(self, client: TestClient):
        # /companies/ is now a real endpoint (Day 39) returning the full list.
        r = client.get(f"{API_PREFIX}/companies/")
        assert r.status_code == 200
        body = r.json()
        assert "companies" in body
        assert body["count"] == 92

    def test_health_router_without_trailing_slash(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200

    def test_openapi_has_all_eight_router_tags(self, client: TestClient):
        schema = client.get("/openapi.json").json()
        # Collect tags from every operation (FastAPI does not always emit
        # a top-level 'tags' list when tags are only declared per-route).
        tags: set[str] = set()
        for methods in schema["paths"].values():
            for op in methods.values():
                tags.update(op.get("tags", []))
        expected_tags = {
            "Companies",
            "Screener",
            "Sectors",
            "Peers",
            "Valuation",
            "Portfolio",
            "Documents",
            "Health",
            "Root",
        }
        assert expected_tags.issubset(tags), f"Missing tags: {expected_tags - tags}"

    def test_all_paths_prefixed_with_api_v1(self, client: TestClient):
        schema = client.get("/openapi.json").json()
        api_paths = [p for p in schema["paths"] if p != "/"]
        for p in api_paths:
            assert p.startswith(API_PREFIX), f"Path {p} is not under {API_PREFIX}"


# ---------------------------------------------------------------------------
# OpenAPI / docs
# ---------------------------------------------------------------------------
class TestDocsEndpoints:
    def test_docs_200(self, client: TestClient):
        r = client.get("/docs")
        assert r.status_code == 200
        assert "swagger" in r.text.lower() or "openapi" in r.text.lower()

    def test_redoc_200(self, client: TestClient):
        r = client.get("/redoc")
        assert r.status_code == 200

    def test_openapi_json_has_correct_title_version(self, client: TestClient):
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "Nifty 100 Financial Intelligence Platform API"
        assert schema["info"]["version"] == API_VERSION

    def test_404_for_unknown_route(self, client: TestClient):
        r = client.get("/api/v1/nonexistent/path")
        assert r.status_code == 404
