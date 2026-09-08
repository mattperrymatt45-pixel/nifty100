"""Generate peer-group radar charts for all Nifty-100 companies — Sprint 3 Day 19.

Writes one PNG per company to ``reports/radar_charts/``:
    * Peer-grouped companies: 8-axis polar/radar chart (company filled polygon +
      peer-group-mean dashed outline).
    * Companies with no peer group: horizontal bar chart comparing each metric
      against the Nifty-100 average.

Usage:
    python -m scripts.day19_radar_charts [--year YEAR] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.analytics.radar_charts import REPORTS_DIR, generate_radar_charts  # noqa: E402
from src.utils.logger import logger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate radar charts")
    parser.add_argument("--year", default=None, help="Fiscal year (default: latest)")
    parser.add_argument(
        "--output-dir",
        default=str(REPORTS_DIR),
        help=f"Output directory (default: {REPORTS_DIR})",
    )
    args = parser.parse_args()

    stats = generate_radar_charts(year=args.year, output_dir=args.output_dir)
    print(
        f"radar_charts: {stats['total']} PNGs written to {stats['output_dir']}\n"
        f"  peer-group radar:    {stats['radar_charts']}\n"
        f"  standalone (no peer): {stats['standalone_charts']}\n"
        f"  year: {stats['year']}"
    )
    if stats["no_peer_group"]:
        logger.info(
            f"{len(stats['no_peer_group'])} companies without peer group "
            f"received standalone charts: {stats['no_peer_group'][:5]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
