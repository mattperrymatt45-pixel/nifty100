#!/usr/bin/env python3
"""Sprint 1 Demo — print a human-readable snapshot of nifty100.db.

Run after a successful `make load`:

    python -m scripts.demo_db

Exit codes:
    0 — demo ran cleanly, all counts match expected ranges
    1 — any critical check failed (missing tables, zero rows, FK orphans, etc.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.etl.database import get_connection, table_rowcount  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

EXPECTED_COUNTS: dict[str, tuple[int, int]] = {
    # table              min,   max
    "companies": (92, 92),
    "sectors": (92, 92),
    "analysis": (15, 92),
    "peer_groups": (50, 70),
    "prosandcons": (10, 30),
    "documents": (1500, 1700),
    "market_cap": (552, 552),
    "profitandloss": (1100, 1400),
    "balancesheet": (1100, 1400),
    "cashflow": (1000, 1300),
    "financial_ratios": (1000, 1300),
    "stock_prices": (5520, 5520),
}


def _hr(width: int = 78, char: str = "=") -> str:
    return char * width


def run_demo() -> int:
    """Print a demo snapshot and return 0 on success, 1 on critical failure."""
    print(_hr())
    print("NIFTY 100 FINANCIAL INTELLIGENCE PLATFORM — Sprint 1 DB Demo")
    print(_hr())

    errors: list[str] = []
    with get_connection() as conn:
        # 1. Table row counts
        print("\n[1] Table row counts")
        print("-" * 78)
        for table, (lo, hi) in EXPECTED_COUNTS.items():
            n = table_rowcount(table)
            ok = lo <= n <= hi
            flag = "OK " if ok else "!! "
            print(f"  {flag}{table:<20s} {n:>6} rows   (expected {lo}-{hi})")
            if not ok:
                errors.append(f"{table} row count {n} outside [{lo},{hi}]")

        # 2. FK integrity
        print("\n[2] Foreign-key integrity (expect 0 orphans per child table)")
        print("-" * 78)
        child_tables = [
            "sectors",
            "profitandloss",
            "balancesheet",
            "cashflow",
            "financial_ratios",
            "stock_prices",
            "documents",
            "market_cap",
            "analysis",
            "prosandcons",
            "peer_groups",
        ]
        for t in child_tables:
            try:
                n = pd.read_sql(
                    f"SELECT COUNT(*) c FROM {t} WHERE company_id NOT IN "
                    "(SELECT id FROM companies)",
                    conn,
                ).iloc[0, 0]
            except Exception as exc:  # pragma: no cover
                errors.append(f"{t} FK check raised: {exc}")
                n = -1
            flag = "OK " if n == 0 else "!! "
            print(f"  {flag}{t:<20s} {n} orphan rows")
            if n != 0:
                errors.append(f"{t} has {n} FK orphans")

        # 3. Sector composition
        print("\n[3] Sector composition")
        print("-" * 78)
        sectors = pd.read_sql(
            "SELECT broad_sector, COUNT(*) c FROM sectors " "GROUP BY broad_sector ORDER BY c DESC",
            conn,
        )
        for _, r in sectors.iterrows():
            bar = "█" * int(r["c"] / 3)
            print(f"  {r['broad_sector']:<28s} {r['c']:>3}  {bar}")

        # 4. Year coverage summary
        print("\n[4] Time-series coverage (P&L / BS / CF years per company)")
        print("-" * 78)
        cov = pd.read_sql(
            "SELECT "
            " (SELECT COUNT(DISTINCT year) FROM profitandloss p WHERE p.company_id=c.id) pl, "
            " (SELECT COUNT(DISTINCT year) FROM balancesheet  b WHERE b.company_id=c.id) bs, "
            " (SELECT COUNT(DISTINCT year) FROM cashflow      cf WHERE cf.company_id=c.id) cf "
            "FROM companies c",
            conn,
        )
        print(
            f"  P&L years  — min={cov['pl'].min()}  median={cov['pl'].median():.0f}  "
            f"max={cov['pl'].max()}  companies<5yr={(cov['pl']<5).sum()}"
        )
        print(
            f"  BS  years  — min={cov['bs'].min()}  median={cov['bs'].median():.0f}  "
            f"max={cov['bs'].max()}  companies<5yr={(cov['bs']<5).sum()}"
        )
        print(
            f"  CF  years  — min={cov['cf'].min()}  median={cov['cf'].median():.0f}  "
            f"max={cov['cf'].max()}  companies<5yr={(cov['cf']<5).sum()}"
        )

        # 5. Sample top 5 companies by latest-year sales
        print("\n[5] Top 5 companies by latest-year sales (₹ Cr)")
        print("-" * 78)
        top = pd.read_sql(
            "SELECT p.company_id, c.company_name, s.broad_sector, "
            "ROUND(p.sales,0) AS sales_cr "
            "FROM profitandloss p JOIN companies c ON c.id=p.company_id "
            "JOIN sectors s ON s.company_id=c.id "
            "WHERE p.year = (SELECT MAX(year) FROM profitandloss) "
            "ORDER BY p.sales DESC LIMIT 5",
            conn,
        )
        for _, r in top.iterrows():
            print(
                f"  {r['company_id']:<12s} {r['company_name'][:30]:<32s} "
                f"{r['broad_sector']:<25s} {r['sales_cr']:>10,.0f} Cr"
            )

        # 6. Peer group benchmarks
        print("\n[6] Peer-group benchmark companies")
        print("-" * 78)
        peers = pd.read_sql(
            "SELECT pg.peer_group_name, pg.company_id, c.company_name "
            "FROM peer_groups pg JOIN companies c ON c.id=pg.company_id "
            "WHERE pg.is_benchmark=1 ORDER BY pg.peer_group_name",
            conn,
        )
        for _, r in peers.iterrows():
            print(
                f"  {r['peer_group_name']:<22s} → {r['company_id']:<12s} " f"({r['company_name']})"
            )

        # 7. Latest ETL audit
        print("\n[7] Latest ETL run (load_audit last 12 rows)")
        print("-" * 78)
        audit = pd.read_sql(
            "SELECT table_name, rows_in, rows_out, rows_rejected, status "
            "FROM load_audit ORDER BY id DESC LIMIT 12",
            conn,
        )
        for _, r in audit.iloc[::-1].iterrows():
            print(
                f"  {r['table_name']:<18s} in={r['rows_in']:>5}  "
                f"out={r['rows_out']:>5}  rej={r['rows_rejected']:>3}  [{r['status']}]"
            )

    print("\n" + _hr())
    if errors:
        print(f"DEMO FAILED — {len(errors)} issue(s):")
        for e in errors:
            print(f"  ✗ {e}")
        print(_hr())
        return 1

    print("DEMO OK — Sprint 1 database is healthy. 0 critical issues.")
    print(_hr())
    return 0


def main() -> int:
    try:
        return run_demo()
    except Exception as exc:  # pragma: no cover
        logger.exception(f"Demo crashed: {exc}")
        print(f"\nDEMO CRASHED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
