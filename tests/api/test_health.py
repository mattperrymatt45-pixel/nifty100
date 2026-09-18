"""Day 42 — Health endpoint integration tests.

Verify GET /api/v1/health returns HTTP 200 with status=ok and db_row_counts
containing all 10 business tables.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.db import BUSINESS_TABLES
from src.api.main import API_PREFIX, API_VERSION, app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_200(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200

    def test_health_status_ok(self, client: TestClient) -> None:
        data = client.get(f"{API_PREFIX}/health").json()
        assert data["status"] == "ok"

    def test_health_version_matches(self, client: TestClient) -> None:
        data = client.get(f"{API_PREFIX}/health").json()
        assert data["version"] == API_VERSION

    def test_health_db_row_counts_has_all_10_tables(self, client: TestClient) -> None:
        data = client.get(f"{API_PREFIX}/health").json()
        counts = data["db_row_counts"]
        assert set(counts.keys()) == set(BUSINESS_TABLES)
        assert len(counts) == 10

    def test_health_db_counts_are_non_negative_integers(self, client: TestClient) -> None:
        counts = client.get(f"{API_PREFIX}/health").json()["db_row_counts"]
        for table, n in counts.items():
            assert isinstance(n, int), f"{table} count {n!r} is not int"
            assert n >= 0, f"{table} count is negative: {n}"

    def test_health_companies_count_is_92(self, client: TestClient) -> None:
        counts = client.get(f"{API_PREFIX}/health").json()["db_row_counts"]
        assert counts["companies"] == 92

    def test_health_sectors_count_is_92(self, client: TestClient) -> None:
        counts = client.get(f"{API_PREFIX}/health").json()["db_row_counts"]
        assert counts["sectors"] == 92

    def test_health_has_uptime(self, client: TestClient) -> None:
        data = client.get(f"{API_PREFIX}/health").json()
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0

    def test_health_response_is_json(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/health")
        assert r.headers["content-type"].startswith("application/json")

    def test_health_x_response_time_header(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/health")
        assert "x-response-time-ms" in r.headers
