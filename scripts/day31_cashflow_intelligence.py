"""Sprint 5 Day 31 — CLI runner for Cash Flow Intelligence.

Usage:
    python scripts/day31_cashflow_intelligence.py
    python scripts/day31_cashflow_intelligence.py --db-path db/nifty100.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics.cashflow_intelligence import run_cashflow_intelligence  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Cash Flow Intelligence deliverables.")
    ap.add_argument("--db-path", type=Path, default=None)
    ap.add_argument("--output-dir", type=Path, default=None)
    args = ap.parse_args()

    summary, alerts, xlsx, csv = run_cashflow_intelligence(
        db_path=args.db_path, output_dir=args.output_dir
    )

    print("=== Day 31 — Cash Flow Intelligence ===")
    print(f"Companies processed:        {len(summary)}")
    print(f"Distress alerts:            {len(alerts)}")
    print(f"cashflow_intelligence.xlsx: {xlsx}")
    print(f"distress_alerts.csv:        {csv}")
    print()
    print("CFO Quality label distribution:")
    print(summary["cfo_quality_label"].value_counts(dropna=False).to_string())
    print()
    print("CapEx tier distribution:")
    print(summary["capex_label"].value_counts(dropna=False).to_string())
    print()
    print("Capital-allocation distribution:")
    print(summary["capital_allocation_label"].value_counts(dropna=False).to_string())
    print()
    print("Distress alerts:")
    if len(alerts):
        print(alerts.to_string(index=False))
    else:
        print("  (none)")
    print()
    print(f"Deleveraging names: {int(summary['deleveraging_flag'].sum())}")


if __name__ == "__main__":
    main()
