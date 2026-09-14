"""Sprint 5 Day 29 — CLI runner for the analysis.xlsx parser.

Usage:
    python scripts/day29_nlp_parser.py
    python scripts/day29_nlp_parser.py --analysis-path data/raw/analysis.xlsx
    python scripts/day29_nlp_parser.py --threshold 5.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nlp.parser import run_parser  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parse analysis.xlsx and cross-validate against the Ratio Engine."
    )
    ap.add_argument("--analysis-path", type=Path, default=None, help="Path to analysis.xlsx")
    ap.add_argument("--db-path", type=Path, default=None, help="Path to nifty100.db")
    ap.add_argument("--output-dir", type=Path, default=None, help="Directory for CSV outputs")
    ap.add_argument(
        "--threshold",
        type=float,
        default=5.0,
        help="Divergence threshold in percentage points (default: 5.0)",
    )
    args = ap.parse_args()

    result = run_parser(
        analysis_path=args.analysis_path,
        db_path=args.db_path,
        output_dir=args.output_dir,
        threshold_pct=args.threshold,
    )

    print("=== Day 29 — Analysis Text Parser ===")
    print(f"Parsed rows:     {result.matched_rows}")
    print(f"Failed rows:     {result.failed_rows}")
    print(f"Total cells:     {result.total_rows}")
    print(f"Match rate:      {result.match_rate_pct}%")
    print(f"Divergences:     {len(result.divergences)} (threshold = {args.threshold} pp)")
    print()
    print(f"Wrote: {result.parsed_csv}")
    print(f"Wrote: {result.failures_csv}")
    print(f"Wrote: {result.divergences_csv}")

    if not result.failures.empty:
        print("\nParse failures:")
        print(result.failures.to_string(index=False))
    if not result.divergences.empty:
        print("\nDivergences (>5 pp):")
        print(result.divergences.to_string(index=False))


if __name__ == "__main__":
    main()
