"""Generate the peer-comparison Excel report — Sprint 3 Day 20.

Writes ``output/peer_comparison.xlsx`` with one sheet per peer group,
20 metric columns + percentile ranks, green/yellow/red percentile coloring,
gold benchmark-row highlighting, and a "Peer Median" summary row per sheet.

Usage:
    python -m scripts.day20_peer_report [--year YEAR] [--output PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.analytics.peer_report import OUTPUT_PATH, generate_peer_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate peer_comparison.xlsx")
    parser.add_argument("--year", default=None, help="Fiscal year (default: latest)")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output .xlsx path")
    args = parser.parse_args()

    stats = generate_peer_report(year=args.year, output_path=args.output)
    print(
        f"peer_comparison: {stats['n_sheets']} sheets x {stats['n_companies']} companies x "
        f"{stats['n_metrics']} metrics -> {stats['output_path']}"
    )
    for s in stats["sheets"]:
        print(f"  - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
