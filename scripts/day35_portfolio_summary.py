"""Sprint 5 Day 35 - Portfolio Summary PDF generation."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reports.portfolio import run_portfolio_summary  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    print("=" * 60)
    print("  Day 35 - Portfolio Summary PDF")
    print("=" * 60)
    panel, path = run_portfolio_summary()
    # Verify page count
    try:
        import pymupdf

        doc = pymupdf.open(str(path))
        n_pages = doc.page_count
        doc.close()
    except ImportError:
        n_pages = -1
    print(f"\n  Companies in panel : {len(panel)}")
    print(f"  Output PDF         : {path.relative_to(PROJECT_ROOT)}")
    print(f"  Pages              : {n_pages}")
    print(f"  Expected pages     : {len(panel)}")
    assert n_pages == len(panel), f"Page mismatch: {n_pages} != {len(panel)}"
    print("\n  OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
