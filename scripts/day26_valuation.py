"""Day 26 - Valuation Summary generator.

Computes FCF yield, sector-median P/E, 5-yr median P/E and sector-relative
overvaluation flags (Caution / Discount / Fair) for the latest FY, then
writes output/valuation_summary.xlsx and output/valuation_flags.csv.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger  # noqa: E402

from src.analytics.valuation import run_valuation_module  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 26 - Valuation summary generator")
    parser.add_argument("--db-path", type=Path, default=None, help="Override DB path")
    parser.add_argument("--output-dir", type=Path, default=None, help="Override output dir")
    parser.add_argument("--year", type=int, default=None, help="Calendar year (default latest)")
    args = parser.parse_args()

    summary, flagged, xlsx, csv = run_valuation_module(
        db_path=args.db_path,
        output_dir=args.output_dir,
        year=args.year,
    )

    logger.info(f"Valuation summary: {len(summary)} companies for latest FY")
    counts = summary["flag"].value_counts().to_dict()
    logger.info(
        "Flag distribution: "
        f"Caution={counts.get('Caution', 0)}  "
        f"Discount={counts.get('Discount', 0)}  "
        f"Fair={counts.get('Fair', 0)}"
    )
    logger.info(f"Wrote {xlsx}")
    logger.info(f"Wrote {csv} ({len(flagged)} flagged rows)")

    print()
    print("Valuation Summary")
    print("=" * 60)
    print(summary.head(10).to_string(index=False))
    print()
    print(f"Flagged (Caution/Discount): {len(flagged)} companies")
    print(f"Output XLSX : {xlsx}")
    print(f"Output CSV  : {csv}")


if __name__ == "__main__":
    main()
