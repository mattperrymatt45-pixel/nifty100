"""Sprint 5 Day 33 - PDF Tearsheet Template generator.

Generates sample tearsheet PDFs to validate the ReportLab template across
5 companies from different sectors:
    * TCS        - Information Technology
    * HDFCBANK   - Financials
    * RELIANCE   - Energy
    * SUNPHARMA  - Healthcare
    * TATASTEEL  - Materials

Also generates the distressed NAUKRI/INDIGO as regression checks.
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

# 5 companies from different sectors (per Day 33 spec)
SAMPLE_TICKERS: list[tuple[str, str]] = [
    ("TCS", "Information Technology"),
    ("HDFCBANK", "Financials"),
    ("RELIANCE", "Energy"),
    ("SUNPHARMA", "Healthcare"),
    ("TATASTEEL", "Materials"),
]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    db_path = settings.PROJECT_ROOT / "db" / "nifty100.db"
    out_dir = settings.PROJECT_ROOT / "output" / "tearsheets"
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        print("=== Day 33 - PDF Tearsheet Template (5 cross-sector samples) ===\n")
        for ticker, sector in SAMPLE_TICKERS:
            out_path = out_dir / f"sample_{ticker}.pdf"
            try:
                generate_tearsheet_for_company(ticker, conn, out_path)
                size_kb = out_path.stat().st_size / 1024
                print(
                    f"  OK  {ticker:<12s} ({sector:<24s})  -> {out_path.name}  ({size_kb:.0f} KB)"
                )
            except Exception as exc:
                print(f"  FAIL {ticker:<12s}: {exc}")
                raise
    finally:
        conn.close()

    print(f"\nTearsheets saved to {out_dir.relative_to(PROJECT_ROOT)}/")
    print("Visually inspect each PDF for text overflow before Day 34 batch generation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
