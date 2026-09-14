"""Sprint 5 Day 32 — Capital Allocation Report runner.

Verifies capital_allocation.csv completeness, generates a pattern-distribution
summary for the latest FY, detects YoY pattern changes (output/pattern_changes.csv),
and refreshes cashflow_intelligence.xlsx with the capital_allocation_label column.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.analytics.capital_allocation_report import run_capital_allocation_report  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    completeness, distribution, changes_df, _xlsx = run_capital_allocation_report()

    pass_fail = "PASS" if completeness["is_complete"] else "FAIL"
    print("\n" + "=" * 60)
    print("  Day 32 - Capital Allocation Report")
    print("=" * 60)
    print(f"\n  capital_allocation.csv completeness: {pass_fail}")
    print(f"    {completeness['total_rows_csv']} / {completeness['total_rows_expected']} rows")
    n_csv = completeness["total_companies_csv"]
    n_db = completeness["total_companies_db"]
    print(f"    {n_csv} / {n_db} companies")

    print("\n  Latest-FY Pattern Distribution (all 8 canonical classes):")
    for _, row in distribution.iterrows():
        print(f"    {row['pattern_label']:<25s}  {int(row['company_count']):3d} companies")

    print(f"\n  YoY Pattern Changes: {len(changes_df)} companies changed pattern")
    if len(changes_df) > 0:
        for _, r in changes_df.iterrows():
            print(
                f"    {r['company_id']:<15s}  {r['prev_pattern']}  ->  {r['latest_pattern']}  "
                f"({r['prev_year']} -> {r['latest_year']})"
            )

    print("\n  Output written to:")
    print("    output/pattern_changes.csv")
    print("    output/capital_allocation_report.xlsx")
    print("    output/cashflow_intelligence.xlsx (refreshed)")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
