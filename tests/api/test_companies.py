"""Tests for Sprint 6 Day 39 - Companies API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import API_PREFIX, app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/v1/companies/
# ---------------------------------------------------------------------------
class TestListCompanies:
    PATH = f"{API_PREFIX}/companies/"

    def test_list_all_returns_92(self, client: TestClient):
        r = client.get(self.PATH)
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 92
        assert len(data["companies"]) == 92

    def test_list_schema(self, client: TestClient):
        data = client.get(self.PATH).json()
        required = {"id", "company_name", "broad_sector", "sub_sector", "roe_pct", "roce_pct"}
        for item in data["companies"]:
            assert required.issubset(set(item.keys())), f"Missing keys in {item}"

    def test_filter_by_sector(self, client: TestClient):
        r = client.get(self.PATH, params={"sector": "Financials"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 19
        for c in data["companies"]:
            assert c["broad_sector"] == "Financials"

    def test_filter_by_market_cap(self, client: TestClient):
        r = client.get(self.PATH, params={"market-cap": "Large Cap"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 50
        for c in data["companies"]:
            assert c["market_cap_category"] == "Large Cap"

    def test_filter_by_search_ticker(self, client: TestClient):
        r = client.get(self.PATH, params={"search": "RELIANCE"})
        data = r.json()
        assert any(c["id"] == "RELIANCE" for c in data["companies"])

    def test_filter_by_search_partial_name(self, client: TestClient):
        r = client.get(self.PATH, params={"search": "Tata"})
        data = r.json()
        assert data["count"] >= 3  # TCS, TATAMOTORS, TATASTEEL, etc.
        for c in data["companies"]:
            assert "tata" in c["id"].lower() or "tata" in c["company_name"].lower()

    def test_filter_combination(self, client: TestClient):
        r = client.get(self.PATH, params={"sector": "IT", "search": "TCS"})
        assert r.status_code == 200
        assert r.json()["count"] == 0 or all(
            c["broad_sector"] == "Information Technology" for c in r.json()["companies"]
        )

    def test_filter_empty_result_is_200(self, client: TestClient):
        r = client.get(self.PATH, params={"sector": "Nonexistent"})
        assert r.status_code == 200
        assert r.json()["count"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/companies/{ticker}
# ---------------------------------------------------------------------------
class TestGetCompany:
    def test_tcs_profile(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/TCS")
        assert r.status_code == 200
        p = r.json()
        assert p["id"] == "TCS"
        assert p["company_name"]
        assert p["broad_sector"] == "Information Technology"
        assert "latest_kpis" in p
        assert p["latest_kpis"]["company_id"] == "TCS"
        assert "latest_valuation" in p

    def test_hdfcbank_profile(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/HDFCBANK")
        assert r.status_code == 200
        assert r.json()["broad_sector"] == "Financials"

    def test_ticker_case_insensitive(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/tcs")
        assert r.status_code == 200
        assert r.json()["id"] == "TCS"

    def test_404_for_unknown(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/FAKETICKER")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Time-series endpoints: PL, BS, Cashflow
# ---------------------------------------------------------------------------
class TestTimeSeries:
    @pytest.mark.parametrize(
        "suffix,expected_col,min_rows",
        [("pl", "sales", 14), ("bs", "equity_capital", 14), ("cashflow", "operating_activity", 13)],
    )
    def test_full_history(self, client: TestClient, suffix: str, expected_col: str, min_rows: int):
        r = client.get(f"{API_PREFIX}/companies/TCS/{suffix}")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "TCS"
        assert data["count"] >= min_rows
        assert expected_col in data["history"][0]

    @pytest.mark.parametrize("suffix", ["pl", "bs", "cashflow"])
    def test_from_to_year_filter(self, client: TestClient, suffix: str):
        r = client.get(
            f"{API_PREFIX}/companies/TCS/{suffix}",
            params={"from": "2022-03", "to": "2024-03"},
        )
        assert r.status_code == 200
        data = r.json()
        years = [row["year"] for row in data["history"]]
        assert data["count"] == 3
        assert set(years) == {"2022-03", "2023-03", "2024-03"}

    @pytest.mark.parametrize("suffix", ["pl", "bs", "cashflow"])
    def test_invalid_year_returns_422(self, client: TestClient, suffix: str):
        r = client.get(f"{API_PREFIX}/companies/TCS/{suffix}", params={"from": "not-a-year"})
        assert r.status_code == 422

    @pytest.mark.parametrize("suffix", ["pl", "bs", "cashflow"])
    def test_404_for_unknown(self, client: TestClient, suffix: str):
        r = client.get(f"{API_PREFIX}/companies/FAKETICKER/{suffix}")
        assert r.status_code == 404

    def test_pl_sorted_ascending(self, client: TestClient):
        data = client.get(f"{API_PREFIX}/companies/TCS/pl").json()
        years = [row["year"] for row in data["history"]]
        assert years == sorted(years)


# ---------------------------------------------------------------------------
# GET /api/v1/companies/{ticker}/ratios
# ---------------------------------------------------------------------------
class TestRatios:
    def test_full_history(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/TCS/ratios")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "TCS"
        assert data["count"] >= 13
        assert "return_on_equity_pct" in data["ratios"][0]

    def test_single_year(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/TCS/ratios", params={"year": "2024-03"})
        assert r.status_code == 200
        data = r.json()
        # Note: 2024-03 may have ratios via fr row OR fall through to null
        assert data["count"] == 1
        assert data["ratios"][0]["year"] == "2024-03"

    def test_404(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/FAKE/ratios")
        assert r.status_code == 404

    def test_invalid_year_422(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/TCS/ratios", params={"year": "garbage"})
        assert r.status_code == 422

    def test_single_year_no_data(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/TCS/ratios", params={"year": "1900-01"})
        assert r.status_code == 200
        assert r.json()["count"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/companies/{ticker}/tearsheet
# ---------------------------------------------------------------------------
class TestTearsheet:
    def test_pdf_download(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/TCS/tearsheet")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"
        assert "TCS_tearsheet.pdf" in r.headers["content-disposition"]
        assert len(r.content) > 30_000  # real tearsheet is ~110 KB

    def test_pdf_for_cross_sector_companies(self, client: TestClient):
        for ticker in ["RELIANCE", "HDFCBANK", "TATASTEEL", "SUNPHARMA"]:
            r = client.get(f"{API_PREFIX}/companies/{ticker}/tearsheet")
            assert r.status_code == 200, f"{ticker} tearsheet failed"
            assert r.content[:5] == b"%PDF-"

    def test_404_for_unknown(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/FAKETICKER/tearsheet")
        assert r.status_code == 404
