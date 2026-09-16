"""Tests for Sprint 6 Day 40 - Screener, Sectors, Peers, Valuation, Portfolio,
Documents, and Export endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import API_PREFIX, app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------
class TestScreener:
    PATH = f"{API_PREFIX}/screener/"

    def test_unfiltered_returns_92(self, client: TestClient):
        r = client.get(self.PATH)
        assert r.status_code == 200
        assert r.json()["count"] == 92

    def test_filter_min_roe(self, client: TestClient):
        r = client.get(self.PATH, params={"min_roe": "20"})
        assert r.status_code == 200
        data = r.json()
        for c in data["companies"]:
            assert c["roe_pct"] is None or c["roe_pct"] >= 20
        assert data["count"] <= 92
        assert data["count"] >= 10

    def test_filter_sector(self, client: TestClient):
        r = client.get(self.PATH, params={"sector": "Financials"})
        assert r.status_code == 200
        for c in r.json()["companies"]:
            assert c["sector"] == "Financials"

    def test_combined_filters(self, client: TestClient):
        r = client.get(
            self.PATH,
            params={"min_roe": "15", "max_de": "1", "max_pe": "30"},
        )
        assert r.status_code == 200
        for c in r.json()["companies"]:
            assert c["roe_pct"] is None or c["roe_pct"] >= 15
            assert c["debt_to_equity"] is None or c["debt_to_equity"] <= 1

    def test_invalid_param_returns_400(self, client: TestClient):
        r = client.get(self.PATH, params={"min_roe": "abc"})
        assert r.status_code == 400
        assert "Invalid value" in r.json()["detail"]

    def test_response_has_filter_metrics(self, client: TestClient):
        r = client.get(self.PATH, params={"min_roe": "20"})
        required = {
            "id",
            "company_name",
            "sector",
            "roe_pct",
            "debt_to_equity",
            "pe_ratio",
            "revenue_cagr_5yr",
            "pat_cagr_5yr",
            "composite_score",
        }
        for c in r.json()["companies"]:
            assert required.issubset(c.keys())

    def test_ranked_by_composite(self, client: TestClient):
        r = client.get(self.PATH)
        scores = [c["composite_score"] or 0 for c in r.json()["companies"]]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Sectors
# ---------------------------------------------------------------------------
class TestSectors:
    LIST = f"{API_PREFIX}/sectors/"

    def test_list_11_sectors(self, client: TestClient):
        r = client.get(self.LIST)
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 11
        names = [s["sector"] for s in data["sectors"]]
        assert "Financials" in names
        assert "Energy" in names

    def test_median_columns(self, client: TestClient):
        s = client.get(self.LIST).json()["sectors"][0]
        for k in ("sector", "company_count", "median_roe", "median_pe", "median_de"):
            assert k in s

    def test_sector_companies(self, client: TestClient):
        r = client.get(f"{self.LIST}Financials/companies")
        assert r.status_code == 200
        data = r.json()
        assert data["sector"] == "Financials"
        assert data["count"] == 19
        for c in data["companies"]:
            assert "id" in c and "company_name" in c

    def test_sector_companies_has_kpis(self, client: TestClient):
        co = client.get(f"{self.LIST}Information Technology/companies").json()["companies"][0]
        for k in ("roe_pct", "roce_pct", "pe_ratio", "composite_score", "market_cap_crore"):
            assert k in co

    def test_unknown_sector_404(self, client: TestClient):
        r = client.get(f"{self.LIST}Nonexistent/companies")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------
class TestPeers:
    def test_peer_group(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/peers/IT Services")
        assert r.status_code == 200
        data = r.json()
        assert data["peer_group"] == "IT Services"
        assert data["count"] >= 4  # TCS, INFY, HCLTECH, WIPRO, TECHM...
        assert len(data["metrics"]) == 10
        ids = {c["company_id"] for c in data["companies"]}
        assert "TCS" in ids

    def test_metrics_include_percentiles(self, client: TestClient):
        c0 = client.get(f"{API_PREFIX}/peers/IT Services").json()["companies"][0]
        assert "metrics" in c0
        sample_metric = next(iter(c0["metrics"].values()))
        assert "percentile_rank" in sample_metric
        assert "value" in sample_metric

    def test_benchmark_flag(self, client: TestClient):
        cos = client.get(f"{API_PREFIX}/peers/IT Services").json()["companies"]
        bench = [c for c in cos if c["is_benchmark"]]
        assert len(bench) == 1
        assert bench[0]["company_id"] == "TCS"

    def test_unknown_group_404(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/peers/FAKEGROUP")
        assert r.status_code == 404

    def test_radar_compare(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/TCS/peers/compare")
        assert r.status_code == 200
        data = r.json()
        assert data["peer_group"] == "IT Services"
        assert data["benchmark_ticker"] == "TCS"
        assert len(data["axes"]) == 8
        assert set(data["company"].keys()) >= set(data["axes"])
        assert set(data["peer_avg"].keys()) >= set(data["axes"])

    def test_radar_compare_unknown_ticker_404(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/FAKE/peers/compare")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Market-cap history
# ---------------------------------------------------------------------------
class TestMarketCap:
    def test_tcs_history(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/market-cap/TCS")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "TCS"
        assert data["count"] == 6
        years = [h["year"] for h in data["history"]]
        assert years == [2019, 2020, 2021, 2022, 2023, 2024]
        assert "pe_ratio" in data["history"][0]
        assert "dividend_yield_pct" in data["history"][0]

    def test_unknown_ticker_404(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/market-cap/FAKE")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------
class TestPortfolio:
    def test_stats(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/portfolio/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["kpi_count"] == 10
        for k in data["stats"]:
            assert k["p10"] <= k["p50"] <= k["p90"]
            assert k["count"] >= 89
        labels = {k["metric_label"] for k in data["stats"]}
        assert "ROE (%)" in labels
        assert "P/E Ratio" in labels

    def test_clusters(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/portfolio/clusters")
        assert r.status_code == 200
        assert r.json()["count"] == 92


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class TestDocuments:
    def test_documents_list(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/TCS/documents")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "TCS"
        assert data["count"] >= 10
        first = data["documents"][0]
        assert "year" in first
        assert "url" in first
        assert "is_url_valid" in first
        assert isinstance(first["is_url_valid"], bool)

    def test_documents_404(self, client: TestClient):
        r = client.get(f"{API_PREFIX}/companies/FAKE/documents")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------
class TestExport:
    def test_openapi_json_root(self, client: TestClient):
        r = client.get("/export/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        assert "openapi" in schema or "swagger" in schema
        assert "paths" in schema
        assert f"{API_PREFIX}/health" in schema["paths"]
        assert f"{API_PREFIX}/companies/{'{ticker}'}/pl" in schema["paths"]

    def test_postman_export(self, client: TestClient):
        r = client.get("/export/postman.json")
        assert r.status_code == 200
        pm = r.json()
        assert pm["info"]["schema"].startswith("https://schema.getpostman.com")
        names = [it["name"] for it in pm["item"]]
        assert any("health" in n.lower() for n in names)
        assert any("screener" in n.lower() for n in names)
        assert len(pm["item"]) >= 15


# ---------------------------------------------------------------------------
# Exported docs/openapi.json on disk
# ---------------------------------------------------------------------------
def test_docs_openapi_file_exists():
    p = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert "paths" in data


def test_docs_postman_file_exists():
    p = Path(__file__).resolve().parents[2] / "docs" / "postman_collection.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert "item" in data
    assert len(data["item"]) >= 15
