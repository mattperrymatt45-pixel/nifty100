"""Day 40 - Export OpenAPI spec and Postman collection to docs/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.api.main import app  # noqa: E402


def main() -> None:
    docs_dir = PROJECT_ROOT / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    openapi_path = docs_dir / "openapi.json"
    schema = app.openapi()
    openapi_path.write_text(json.dumps(schema, indent=2))
    print(f"OpenAPI spec written to {openapi_path} ({len(json.dumps(schema))} bytes)")

    # Build Postman collection from the same schema
    base = "http://localhost:8000"
    items = []
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
    postman = {
        "info": {
            "name": "Nifty 100 Financial Intelligence Platform API",
            "_postman_id": "a1b2c3d4-0000-0000-0000-nifty100api00",
            "description": schema.get("info", {}).get("description", ""),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
    }
    postman_path = docs_dir / "postman_collection.json"
    postman_path.write_text(json.dumps(postman, indent=2))
    print(f"Postman collection written to {postman_path} ({len(items)} requests)")


if __name__ == "__main__":
    main()
