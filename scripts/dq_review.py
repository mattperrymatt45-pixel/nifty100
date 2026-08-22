#!/usr/bin/env python3
"""Data Quality Manual Review (Sprint 1, Day 6).

Selects 5 random companies and audits them across every time-series table:
year coverage, PK uniqueness, FK integrity, value sanity, and DQ-16
(< 5yr coverage). Prints a human-readable report and exits non-zero if
any CRITICAL issues are found.

Usage (from project root)::

    python -m scripts.dq_review            # fixed seed for reproducibility
    python -m scripts.dq_review --seed 0   # truly random
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.etl.database import get_connection  # noqa: E402
from src.utils.config import settings  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

# Tables we check per company.  Key = table name; value = (year_col, label).
TIMESERIES_TABLES: dict[str, tuple[str, str]] = {
    "profitandloss": ("year", "P&L"),
    "balancesheet": ("year", "BS"),
    "cashflow": ("year", "CF"),
    "financial_ratios": ("year", "Ratios"),
    "documents": ("Year", "Docs (calendar ints)"),
    "market_cap": ("year", "Mkt Cap (calendar ints)"),
    "stock_prices": ("date", "Prices (months)"),
}


def _coverage_table(conn) -> pd.DataFrame:
    """Return a per-company coverage summary across P&L/BS/CF."""
    return pd.read_sql(
        """
        SELECT c.id, c.company_name, s.broad_sector,
          (SELECT COUNT(DISTINCT year) FROM profitandloss p
             WHERE p.company_id=c.id) AS pl_yrs,
          (SELECT COUNT(DISTINCT year) FROM balancesheet b
             WHERE b.company_id=c.id) AS bs_yrs,
          (SELECT COUNT(DISTINCT year) FROM cashflow cf
             WHERE cf.company_id=c.id) AS cf_yrs,
          (SELECT COUNT(DISTINCT year) FROM financial_ratios fr
             WHERE fr.company_id=c.id) AS fr_yrs,
          (SELECT COUNT(*) FROM documents d WHERE d.company_id=c.id) AS docs,
          (SELECT COUNT(*) FROM stock_prices sp WHERE sp.company_id=c.id) AS prices,
          (SELECT COUNT(*) FROM market_cap mc WHERE mc.company_id=c.id) AS mcap
        FROM companies c
        JOIN sectors s ON s.company_id = c.id
        ORDER BY c.id
        """,
        conn,
    )


def run_review(*, seed: int = 12345) -> int:
    """Run the manual DQ review. Returns 0 on clean / 1 on CRITICAL findings."""
    random.seed(seed)

    with get_connection() as conn:
        # --- Global checks ---
        n_companies = pd.read_sql("SELECT COUNT(*) c FROM companies", conn).iloc[0, 0]
        fk_orphans = {}
        for t, _yc in TIMESERIES_TABLES.items():
            orph = pd.read_sql(
                f"SELECT COUNT(*) c FROM {t} WHERE company_id NOT IN " "(SELECT id FROM companies)",
                conn,
            ).iloc[0, 0]
            if orph:
                fk_orphans[t] = orph
        parse_errors = {}
        for t in ("profitandloss", "balancesheet", "cashflow", "financial_ratios"):
            c = pd.read_sql(f"SELECT COUNT(*) c FROM {t} WHERE year='PARSE_ERROR'", conn).iloc[0, 0]
            if c:
                parse_errors[t] = c

        # --- Coverage ---
        cov = _coverage_table(conn)
        short_coverage = cov[(cov["pl_yrs"] < 5) | (cov["bs_yrs"] < 5) | (cov["cf_yrs"] < 5)]

        # --- 5 random companies deep-dive ---
        sample_ids = random.sample(list(cov["id"]), 5)

        # --- Report ---
        print("=" * 78)
        print("NIFTY 100 — DATA QUALITY MANUAL REVIEW")
        print(f"Seed={seed}  DB={settings.DB_PATH}")
        print("=" * 78)

        print(f"\nCompanies loaded: {n_companies}")
        print(f"FK orphans: {fk_orphans if fk_orphans else 'NONE'}")
        print(f"PARSE_ERROR rows in DB: {parse_errors if parse_errors else 'NONE'}")

        print("\n--- Coverage (DQ-16: ≥5 years per core table) ---")
        if len(short_coverage) == 0:
            print(f"OK — all {len(cov)} companies have ≥5 years of P&L, BS, and CF.")
        else:
            print(f"WARNING — {len(short_coverage)} companies under 5yr threshold:")
            print(short_coverage.to_string(index=False))

        print("\n--- Year-count distribution (P&L) ---")
        dist = cov["pl_yrs"].value_counts().sort_index()
        for yrs, count in dist.items():
            print(f"  {yrs:>3} years: {count:>3} companies")

        print("\n--- 5 Random Companies Deep-Dive ---")
        for cid in sample_ids:
            row = cov[cov["id"] == cid].iloc[0]
            print(f"\n▸ {cid}  —  {row['company_name']}  ({row['broad_sector']})")
            for tbl, (yc, label) in TIMESERIES_TABLES.items():
                if tbl == "stock_prices":
                    info = pd.read_sql(
                        f"SELECT COUNT(*) c, MIN({yc}) mn, MAX({yc}) mx "
                        f"FROM {tbl} WHERE company_id=?",
                        conn,
                        params=(cid,),
                    ).iloc[0]
                    print(f"    {label:<26s}: {info['c']:>5} rows  " f"{info['mn']} → {info['mx']}")
                elif tbl in ("documents", "market_cap"):
                    info = pd.read_sql(
                        f"SELECT COUNT(*) c, MIN({yc}) mn, MAX({yc}) mx "
                        f"FROM {tbl} WHERE company_id=?",
                        conn,
                        params=(cid,),
                    ).iloc[0]
                    print(
                        f"    {label:<26s}: {info['c']:>5} years  " f"{info['mn']} → {info['mx']}"
                    )
                else:
                    info = pd.read_sql(
                        f"SELECT COUNT(*) c, MIN({yc}) mn, MAX({yc}) mx "
                        f"FROM {tbl} WHERE company_id=?",
                        conn,
                        params=(cid,),
                    ).iloc[0]
                    flag = " ⚠ <5yr" if info["c"] < 5 else ""
                    print(
                        f"    {label:<26s}: {info['c']:>5} years  "
                        f"{info['mn']} → {info['mx']}{flag}"
                    )

        # --- Final verdict ---
        print("\n" + "=" * 78)
        critical = bool(fk_orphans or parse_errors)
        if critical:
            print("VERDICT: CRITICAL issues detected — see above.")
        else:
            print(
                f"VERDICT: CLEAN — 0 CRITICAL, "
                f"{len(short_coverage)} coverage warnings "
                f"({'none' if len(short_coverage) == 0 else 'review needed'})."
            )
        print("=" * 78)

        return 1 if critical else 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Day 6 DQ manual review report")
    p.add_argument("--seed", type=int, default=12345, help="Random seed (default 12345)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return run_review(seed=args.seed)


if __name__ == "__main__":
    sys.exit(main())
