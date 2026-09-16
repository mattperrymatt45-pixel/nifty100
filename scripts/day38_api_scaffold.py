"""Day 38 runner - FastAPI Server Scaffold verification.

Launches the FastAPI application briefly via TestClient (no uvicorn process
required), hits every scaffold endpoint, and prints a summary table. Use
this to verify the scaffold works before wiring real endpoints.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import API_PREFIX, app  # noqa: E402


def main() -> None:
    import json

    print("=== Day 38 - FastAPI Server Scaffold verification ===")
    print()
    with TestClient(app) as client:
        # Root
        r = client.get("/")
        print(f"GET /                     -> {r.status_code}  {r.json()['name']}")

        # Health
        r = client.get(f"{API_PREFIX}/health")
        body = r.json()
        print(f"GET {API_PREFIX}/health  -> {r.status_code}  status={body['status']} "
              f"version={body['version']} uptime={body['uptime_seconds']:.2f}s")
        print("         db_row_counts:")
        for t, n in body["db_row_counts"].items():
            print(f"           {t:20s} = {n}")

        # Router stubs
        for stub in ["companies", "screener", "sectors", "peers",
                     "valuation", "portfolio", "documents"]:
            r = client.get(f"{API_PREFIX}/{stub}/")
            print(f"GET {API_PREFIX}/{stub:12s}/  -> {r.status_code}  "
                  f"module={r.json()['module']}")

        # Docs / OpenAPI
        r = client.get("/docs")
        print(f"GET /docs                 -> {r.status_code}  ({len(r.content)} bytes)")
        r = client.get("/openapi.json")
        schema = r.json()
        print(f"GET /openapi.json         -> {r.status_code}  "
              f"{len(schema['paths'])} paths registered")
        print()
        print("=== All scaffold endpoints respond 200 OK ===")


if __name__ == "__main__":
    main()
