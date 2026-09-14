"""Sprint 5 Day 30 — CLI runner for the auto pros/cons generator.

Usage:
    python scripts/day30_pros_cons.py
    python scripts/day30_pros_cons.py --threshold 60
    python scripts/day30_pros_cons.py --output output/pros_cons_generated.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nlp.pros_cons_generator import generate_pros_cons  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Auto-generate pros/cons observations for all 92 Nifty 100 companies."
    )
    ap.add_argument("--db-path", type=Path, default=None)
    ap.add_argument(
        "--output", type=Path, default=None, help="Path to write pros_cons_generated.csv"
    )
    ap.add_argument(
        "--threshold",
        type=int,
        default=60,
        help="Minimum confidence to emit an observation (default: 60)",
    )
    args = ap.parse_args()

    res = generate_pros_cons(
        db_path=args.db_path,
        output_path=args.output,
        confidence_threshold=args.threshold,
    )

    print("=== Day 30 — Auto Pros/Cons Generator ===")
    print(f"Companies processed:       {res.total_companies}")
    print(
        f"Companies with >=1 pro:    {res.companies_with_pros} "
        f"(fallback pro used: {res.companies_needing_fallback_pro})"
    )
    print(
        f"Companies with >=1 con:    {res.companies_with_cons} "
        f"(fallback con used: {res.companies_needing_fallback_con})"
    )
    print(f"Total observations:        {len(res.df)}")
    print(f"Written to:                {res.csv_path}")
    print()
    print("Rule hit counts (12 pro + 12 hard con rules + watch-list cons):")
    for rid, n in sorted(res.rule_hit_counts.items()):
        print(f"  {rid}: {n:3d}")


if __name__ == "__main__":
    main()
