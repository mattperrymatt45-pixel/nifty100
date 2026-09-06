"""Sprint 3 Day 16 — Generate output/screener_output.xlsx.

Runs all six preset screeners and writes formatted sheets to a single Excel
workbook. Also writes a "Summary" sheet listing hit counts and the filters
applied for each preset.

Usage:
    python -m scripts.export_screener                 # default output/screener_output.xlsx
    python -m scripts.export_screener --output reports/screener_q2.xlsx
    python -m scripts.export_screener --db-path db/nifty100.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screener import export_screener_to_excel, load_config, run_screener  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

DEFAULT_OUTPUT = _PROJECT_ROOT / "output" / "screener_output.xlsx"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export all screener presets to Excel")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output XLSX path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Override DB path",
    )
    parser.add_argument(
        "--all-years",
        action="store_true",
        help="Export all company-year rows (not just latest FY)",
    )
    args = parser.parse_args()

    cfg = load_config()

    results = {}
    for name, preset in cfg.presets.items():
        logger.info(f"Running preset: {preset.label} ({name})")
        result = run_screener(
            preset,
            config=cfg,
            db_path=args.db_path,
            latest_year_only=not args.all_years,
        )
        results[name] = result
        print(f"  {preset.label:35s}  {result.rows_out:3d} / {result.rows_in} companies")

    export_result = export_screener_to_excel(results, args.output)

    print()
    print(f"Wrote {len(export_result.sheets_written)} sheets to {args.output}")
    for s in export_result.sheets_written:
        print(f"  - {s}")
    print(f"Total rows across presets: {export_result.total_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
