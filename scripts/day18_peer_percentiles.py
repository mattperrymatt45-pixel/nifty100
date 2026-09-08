"""Populate the ``peer_percentiles`` table — Sprint 3 Day 18.

Computes PERCENT_RANK for the 10 spec metrics (ROE, ROCE, NPM, D/E inverted,
FCF, PAT CAGR 5y, Revenue CAGR 5y, EPS CAGR 5y, ICR, Asset Turnover) within
each of the 11 defined peer groups for the latest fiscal year and writes
one row per (company, peer_group, metric, year) to the ``peer_percentiles``
SQLite table.

Usage:
    python -m scripts.day18_peer_percentiles [--year YEAR] [--reset]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.analytics.peer import (  # noqa: E402
    PEER_METRICS,
    ensure_schema,
    populate_peer_percentiles,
)
from src.etl.database import get_connection  # noqa: E402
from src.utils.logger import logger  # noqa: E402


def _fetch_latest_year() -> str:
    with get_connection() as conn:
        year = conn.execute("SELECT MAX(year) FROM financial_ratios").fetchone()[0]
    return year


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate peer_percentiles")
    parser.add_argument("--year", default=None, help="Fiscal year (default: latest)")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="DELETE existing rows for the target year before inserting",
    )
    args = parser.parse_args()

    ensure_schema()
    year = args.year or _fetch_latest_year()
    logger.info(
        f"Computing peer percentiles for year={year} "
        f"({len(PEER_METRICS)} metrics across all peer groups)"
    )
    stats = populate_peer_percentiles(year=year, reset=args.reset)

    print(
        f"peer_percentiles: {stats['rows']} rows written "
        f"(year={stats['year']}, companies={stats['companies']}, "
        f"groups={stats['groups']}, metrics={stats['metrics']})"
    )
    n_no_peer = len(stats["no_peer_group"])
    if n_no_peer:
        print(
            f"  {n_no_peer} companies without peer group (no error, skipped): "
            f"{', '.join(stats['no_peer_group'][:8])}" + (" ..." if n_no_peer > 8 else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
