"""Sprint 5 Day 34 - Batch Report Generation.

Generates:
  * reports/tearsheets/<TICKER>_tearsheet.pdf for all qualifying companies
  * reports/sector/<SECTOR>_report.pdf for each of 11 broad sectors
  * output/skipped_tearsheets.csv for any companies with <3 years data
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reports.batch import run_day34_batch  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    print("=" * 60)
    print("  Day 34 - Batch Report Generation")
    print("=" * 60)

    summary = run_day34_batch(PROJECT_ROOT)

    print(f"\n  Tearsheets generated : {summary['tearsheets_generated']}")
    print(f"  Tearsheets skipped   : {summary['tearsheets_skipped']}")
    print("                         (see output/skipped_tearsheets.csv)")
    print(f"  Tearsheets failed    : {summary['tearsheets_failed']}")
    print(f"  Sector reports       : {summary['sector_reports']}")
    print(f"  Elapsed              : {summary['elapsed_sec']:.1f}s")
    print("\n  Output dirs:")
    print(f"    {summary['tearsheet_dir'].relative_to(PROJECT_ROOT)}/")
    print(f"    {summary['sector_dir'].relative_to(PROJECT_ROOT)}/")

    if summary["failures"]:
        print("\n  FAILURES:")
        for cid, err in summary["failures"]:
            print(f"    - {cid}: {err[:120]}")
        return 1

    # Verification: count tearsheet files
    pdfs = [f for f in os.listdir(summary["tearsheet_dir"]) if f.endswith("_tearsheet.pdf")]
    expected = summary["tearsheets_generated"]
    print(
        f"\n  File-count check: {len(pdfs)} tearsheet PDFs in reports/tearsheets/ "
        f"(expected {expected})"
    )
    assert len(pdfs) == expected, f"File count mismatch: {len(pdfs)} != {expected}"
    print("  OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
