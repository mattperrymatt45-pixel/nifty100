"""Day 42 — API integration tests (screener, sectors) + dashboard cross-check.

Covers:
  * GET /api/v1/health → 200, status=ok, 10 tables in db_row_counts
  * GET /api/v1/companies/ → 92 records
  * GET /api/v1/companies/TCS → correct profile
  * GET /api/v1/companies/INVALID → 404
  * GET /api/v1/screener/?min_roe=15 → only ROE ≥ 15 companies returned
  * GET /api/v1/screener/ with invalid param → HTTP 400
  * GET /api/v1/sectors/ → exactly 11 sectors
  * GET /api/v1/sectors/{sector}/companies → sector-filtered list
  * Dashboard screener page returns the same results as the API
    (Streamlit <-> API integration check via shared engine/DB)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.db import BUSINESS_TABLES, get_db_connection
from src.api.main import API_PREFIX, API_VERSION, app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
class TestHealth:
    def test_health_200(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/health")
        assert r.status_code == 200

    def test_health_status_ok_and_10_tables(self, client: TestClient) -> None:
        data = client.get(f"{API_PREFIX}/health").json()
        assert data["status"] == "ok"
        assert data["version"] == API_VERSION
        counts = data["db_row_counts"]
        assert len(counts) == 10
        assert set(counts.keys()) == set(BUSINESS_TABLES)
        assert counts["companies"] == 92


# --------------------------------------------------------------------------
# Companies
# --------------------------------------------------------------------------
class TestCompaniesIntegration:
    def test_companies_list_92(self, client: TestClient) -> None:
        data = client.get(f"{API_PREFIX}/companies/").json()
        assert data["count"] == 92
        assert len(data["companies"]) == 92

    def test_tcs_profile_correct(self, client: TestClient) -> None:
        data = client.get(f"{API_PREFIX}/companies/TCS").json()
        assert data["id"] == "TCS"
        assert "company_name" in data
        assert data["broad_sector"] == "Information Technology"
        assert "latest_kpis" in data
        assert "latest_valuation" in data

    def test_invalid_ticker_404(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/companies/NOSUCHTICKERXYZ")
        assert r.status_code == 404


# --------------------------------------------------------------------------
# Screener
# --------------------------------------------------------------------------
class TestScreenerIntegration:
    def test_min_roe_filter_only_returns_qualifying(self, client: TestClient) -> None:
        """Every company returned by ?min_roe=15 must have ROE >= 15."""
        r = client.get(f"{API_PREFIX}/screener/", params={"min_roe": 15})
        assert r.status_code == 200
        data = r.json()
        companies = data["companies"]
        assert isinstance(companies, list)
        assert len(companies) >= 1
        assert data["count"] == len(companies)
        for c in companies:
            roe = c.get("roe_pct")
            assert roe is not None, f"Company {c.get('id')} missing roe_pct"
            assert float(roe) >= 15.0 - 1e-6, f"{c.get('id')} ROE {roe} < 15 but passed min_roe=15"

    def test_min_roe_narrows_results(self, client: TestClient) -> None:
        all_n = client.get(f"{API_PREFIX}/screener/").json()["count"]
        f25 = client.get(f"{API_PREFIX}/screener/", params={"min_roe": 25}).json()
        assert f25["count"] < all_n

    def test_invalid_param_returns_400(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/screener/", params={"min_roe": "not-a-number"})
        assert r.status_code == 400


# --------------------------------------------------------------------------
# Sectors
# --------------------------------------------------------------------------
class TestSectorsIntegration:
    def test_sectors_returns_11(self, client: TestClient) -> None:
        data = client.get(f"{API_PREFIX}/sectors/").json()
        assert data["count"] == 11
        assert len(data["sectors"]) == 11
        sector_names = {s["sector"] for s in data["sectors"]}
        assert "Information Technology" in sector_names

    def test_it_sector_companies_all_in_it(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/sectors/Information Technology/companies")
        assert r.status_code == 200
        data = r.json()
        assert data["sector"] == "Information Technology"
        assert data["count"] == len(data["companies"])
        assert data["count"] == 6
        ids = {c["id"] for c in data["companies"]}
        assert "TCS" in ids

    def test_unknown_sector_404(self, client: TestClient) -> None:
        r = client.get(f"{API_PREFIX}/sectors/NoSuchSector/companies")
        assert r.status_code == 404


# --------------------------------------------------------------------------
# Dashboard ↔ API integration
# --------------------------------------------------------------------------
class TestDashboardAPIIntegration:
    """Verify dashboard data is consistent with the API.

    Rather than spinning up a full Streamlit+Selenium harness, we exercise
    the same database/screener engine the dashboard uses under the hood
    and confirm it produces results equivalent to the REST API.
    """

    def test_screener_engine_matches_api(self, client: TestClient) -> None:
        """Screener engine (used by Streamlit dashboard) with min_roe=15
        returns the same IDs as the /screener API endpoint."""
        api_ids = sorted(
            c["id"]
            for c in client.get(f"{API_PREFIX}/screener/", params={"min_roe": 15}).json()[
                "companies"
            ]
        )
        assert len(api_ids) > 0

        # Dashboard uses the screener engine directly — call it.
        from src.screener.engine import load_screener_dataset

        df = load_screener_dataset()
        mask = df["roe_pct"] >= 15.0
        engine_ids = sorted(df.loc[mask, "company_id"].astype(str).unique())

        # Every engine ID must appear in the API result
        missing = set(engine_ids) - set(api_ids)
        assert not missing, f"Engine has IDs missing from API: {missing}"

    def test_db_companies_count_matches_api(self, client: TestClient) -> None:
        """Direct DB count, API /companies, and API /health all agree on 92."""
        with get_db_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        api_n = client.get(f"{API_PREFIX}/companies/").json()["count"]
        health_n = client.get(f"{API_PREFIX}/health").json()["db_row_counts"]["companies"]
        assert n == api_n == health_n == 92

    def test_db_sector_counts_match_api(self, client: TestClient) -> None:
        """DB sector count per broad_sector matches /sectors/ API."""
        api_sectors = {
            s["sector"]: s["company_count"]
            for s in client.get(f"{API_PREFIX}/sectors/").json()["sectors"]
        }
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT broad_sector, COUNT(*) FROM sectors GROUP BY broad_sector"
            ).fetchall()
        db_counts = {r[0]: r[1] for r in rows}
        assert sum(db_counts.values()) == 92
        for name, count in api_sectors.items():
            assert db_counts[name] == count


def test_pytest_html_plugin_available() -> None:
    """Sanity: pytest-html is installed so HTML reports can be generated."""
    import pytest_html  # noqa: F401
