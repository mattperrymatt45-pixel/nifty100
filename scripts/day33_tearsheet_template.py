"""Sprint 5 Day 33 — PDF Tearsheet Template generator.

Generates sample tearsheet PDFs to validate the ReportLab template:
    * output/tearsheets/sample_RELIANCE.pdf
    * output/tearsheets/sample_TCS.pdf
    * output/tearsheets/sample_INDIGO.pdf   (distressed, should show red NP)
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reports.tearsheet import generate_tearsheet_for_company  # noqa: E402
from src.utils.config import settings  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    db_path = settings.PROJECT_ROOT / "db" / "nifty100.db"
    out_dir = settings.PROJECT_ROOT / "output" / "tearsheets"
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_tickers = ["RELIANCE", "TCS", "INDIGO", "NAUKRI"]

    conn = sqlite3.connect(str(db_path))
    try:
        for ticker in sample_tickers:
            out_path = out_dir / f"sample_{ticker}.pdf"
            try:
                generate_tearsheet_for_company(ticker, conn, out_path)
                print(f"  ✓ {ticker:12s} -> {out_path.relative_to(PROJECT_ROOT)}")
            except Exception as exc:
                print(f"  ✗ {ticker:12s} -> ERROR: {exc}")
                raise
    finally:
        conn.close()

    print(f"\n✓ Sample tearsheets generated in {out_dir.relative_to(PROJECT_ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
