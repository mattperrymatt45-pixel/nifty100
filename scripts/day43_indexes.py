"""Day 43 — Ensure SQLite indexes are present for performance.

Checks and creates indexes on company_id/year columns for all large tables
if they are missing. Existing indexes are left untouched (IF NOT EXISTS).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "db" / "nifty100.db"


INDEXES = [
    # time-series: (company_id, year) composite lookups
    ("idx_pl_company_id", "profitandloss", "company_id"),
    ("idx_pl_year", "profitandloss", "year"),
    ("idx_bs_company_id", "balancesheet", "company_id"),
    ("idx_bs_year", "balancesheet", "year"),
    ("idx_cf_company_id", "cashflow", "company_id"),
    ("idx_cf_year", "cashflow", "year"),
    ("idx_ratios_company_id", "financial_ratios", "company_id"),
    ("idx_doc_company_id", "documents", "company_id"),
    ("idx_mcap_company_id", "market_cap", "company_id"),
    ("idx_prices_company_id", "stock_prices", "company_id"),
    ("idx_sectors_company_id", "sectors", "company_id"),
    ("idx_peers_company_id", "peer_groups", "company_id"),
]


def main() -> int:
    conn = sqlite3.connect(str(DB))
    try:
        existing = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        created = 0
        for name, table, col in INDEXES:
            if name in existing:
                continue
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ("{col}")')
            created += 1
            print(f"  created index {name} on {table}({col})")
        conn.commit()

        # ANALYZE so query planner has up-to-date stats
        conn.execute("ANALYZE")
        conn.commit()
        print(f"Done. Created {created} new index(es).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
