"""Generate output/capital_allocation.csv from the nifty100 SQLite database.

Joins cashflow and profitandloss tables for every company-year, runs the
Day-11 capital-allocation classifier, and writes the deliverable CSV.

Usage:
    python -m scripts.generate_capital_allocation_csv
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when invoked as a script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.analytics.cashflow_kpis import (  # noqa: E402
    CapitalAllocationRow,
    build_capital_allocation_rows,
    compute_cashflow_kpis_for_company,
    write_capital_allocation_csv,
)
from src.etl.database import get_connection  # noqa: E402
from src.utils.config import settings  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def _fetch_company_data(conn) -> list[tuple[str, list[dict], list[dict]]]:
    """Return [(company_id, pl_rows, cf_rows), ...] for every company."""
    pl_rows = conn.execute(
        "SELECT company_id, year, sales, operating_profit, net_profit "
        "FROM profitandloss ORDER BY company_id, year"
    ).fetchall()
    cf_rows = conn.execute(
        "SELECT company_id, year, operating_activity, investing_activity, financing_activity "
        "FROM cashflow ORDER BY company_id, year"
    ).fetchall()

    by_co_pl: dict[str, list[dict]] = {}
    by_co_cf: dict[str, list[dict]] = {}
    for r in pl_rows:
        by_co_pl.setdefault(r["company_id"], []).append(dict(r))
    for r in cf_rows:
        by_co_cf.setdefault(r["company_id"], []).append(dict(r))

    companies = sorted(set(by_co_pl.keys()) & set(by_co_cf.keys()))
    return [(c, by_co_pl[c], by_co_cf[c]) for c in companies]


def generate(output_path: Path | None = None) -> int:
    """Generate capital_allocation.csv. Returns the number of rows written."""
    target = output_path or (settings.OUTPUT_DIR / "capital_allocation.csv")
    all_rows: list[CapitalAllocationRow] = []

    with get_connection() as conn:
        companies = _fetch_company_data(conn)
        logger.info(f"Classifying capital allocation for {len(companies)} companies")
        for cid, pl, cf in companies:
            kpis = compute_cashflow_kpis_for_company(cid, pl, cf)
            years = sorted({r["year"] for r in pl} & {r["year"] for r in cf})
            all_rows.extend(build_capital_allocation_rows(cid, years, kpis))

    n = write_capital_allocation_csv(all_rows, target)
    logger.info(f"Wrote {n} rows to {target}")
    return n


if __name__ == "__main__":
    n = generate()
    print(f"capital_allocation.csv written: {n} rows")
