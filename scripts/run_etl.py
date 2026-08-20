#!/usr/bin/env python3
"""End-to-end ETL entry point (Sprint 1, Days 2-4).

Loads all 12 datasets from ``data/raw/``, normalises tickers/years,
initialises the SQLite database schema, bulk-loads all tables,
runs DQ validation, and writes an audit trail.

Usage (from project root)::

    python -m scripts.run_etl            # full run
    python -m scripts.run_etl --reset    # wipe all tables first
    make load                            # via Makefile
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is importable when invoked as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from src.etl import (  # noqa: E402
    DATASET_SPECS,
    available_datasets,
    load_dataset,
)
from src.etl.database import (  # noqa: E402
    init_schema,
    load_dataframe,
    reset_tables,
    table_rowcount,
    write_load_audit,
)
from src.etl.exceptions import ETLError, LoaderError  # noqa: E402
from src.etl.validation import validate_all  # noqa: E402
from src.utils.config import settings  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def _normalize_documents_year(df: pd.DataFrame) -> pd.DataFrame:
    """Documents.xlsx has a capitalised ``Year`` column (calendar-year int)."""
    if "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    return df


def _normalize_market_cap_year(df: pd.DataFrame) -> pd.DataFrame:
    """market_cap.xlsx uses integer calendar years."""
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    return df


def _normalize_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Analysis.xlsx has an ``id`` column that's a row-id, not a ticker — drop it."""
    if "id" in df.columns and "company_id" in df.columns:
        df = df.drop(columns=["id"])
    return df


# Per-dataset post-processing hooks. Keyed by logical dataset name.
_POST_PROCESS: dict[str, callable] = {
    "documents": _normalize_documents_year,
    "market_cap": _normalize_market_cap_year,
    "analysis": _normalize_analysis,
}


def run(
    *,
    reset: bool = False,
    datasets: list[str] | None = None,
) -> dict:
    """Execute the ETL pipeline.

    Args:
        reset:    If True, truncate all tables before loading.
        datasets: Optional list of dataset names to load (default: all 12).
    """
    start = time.perf_counter()
    logger.info("=== Nifty 100 ETL run starting ===")

    # 1. Initialise schema (idempotent — creates missing tables/indexes)
    init_schema()

    if reset:
        reset_tables()

    targets = datasets or available_datasets()
    unknown = [n for n in targets if n not in DATASET_SPECS]
    if unknown:
        raise LoaderError(f"Unknown dataset(s): {unknown}")

    tables: dict[str, pd.DataFrame] = {}
    audit_entries: list[dict] = []

    # 2. Companies must be loaded first (FK parent for all others)
    ordered = ["companies"] + [n for n in targets if n != "companies"]

    for name in ordered:
        t0 = time.perf_counter()
        try:
            df = load_dataset(name)

            # Apply per-dataset post-processing
            hook = _POST_PROCESS.get(name)
            if hook is not None:
                df = hook(df)

            tables[name] = df
            stats = load_dataframe(df, name, deduplicate=True)
            stats["runtime_s"] = round(time.perf_counter() - t0, 3)
            stats["status"] = "OK"
            audit_entries.append(stats)
        except ETLError as exc:
            logger.error(f"Failed to load {name}: {exc}")
            audit_entries.append(
                {
                    "table": name,
                    "rows_in": 0,
                    "rows_loaded": 0,
                    "rows_dropped": 0,
                    "runtime_s": round(time.perf_counter() - t0, 3),
                    "status": f"FAILED: {exc}",
                }
            )

    # 3. Run DQ validation across all loaded tables
    vf_path = settings.PROCESSED_DATA_DIR / "validation_failures.csv"
    summary = validate_all(tables, output_path=vf_path)
    logger.info(
        f"DQ summary: {summary['critical']} CRITICAL / "
        f"{summary['warning']} WARNING / {summary['info']} INFO — "
        f"failures written to {vf_path}"
    )

    # Also persist DQ failures to DB (validation_failures table)
    if summary["failures"]:
        # Translate dict keys to the SQL schema (column vs column_name)
        col_map = {
            "rule_id": "rule_id",
            "table": "table_name",
            "company_id": "company_id",
            "year": "year",
            "column": "column_name",
            "severity": "severity",
            "message": "message",
            "expected": "expected",
            "actual": "actual",
            "row_index": "row_index",
        }
        vf_db = pd.DataFrame(
            [{sql_k: f.get(k) for k, sql_k in col_map.items()} for f in summary["failures"]]
        )
        # Append (don't dedupe — history is preserved)
        load_dataframe(vf_db, "validation_failures", deduplicate=False)

    # 4. Record per-table rowcounts for the audit log
    for entry in audit_entries:
        entry["rows_out"] = table_rowcount(entry["table"])
    write_load_audit(audit_entries)

    total_runtime = round(time.perf_counter() - start, 3)
    logger.info(
        f"=== ETL run complete in {total_runtime}s — "
        f"{sum(e.get('rows_loaded', 0) for e in audit_entries)} rows across "
        f"{len(audit_entries)} tables ==="
    )

    # Print a friendly summary to stdout (for `make load` visibility)
    print("\n=== ETL Summary ===")
    for e in audit_entries:
        print(
            f"  {e['table']:<18} in={e.get('rows_in',0):>6}  "
            f"loaded={e.get('rows_loaded',0):>6}  "
            f"dropped={e.get('rows_dropped',0):>4}  "
            f"[{e['status']}] ({e.get('runtime_s',0):.2f}s)"
        )
    print(
        f"\nDQ: {summary['critical']} CRITICAL / {summary['warning']} WARNING / "
        f"{summary['info']} INFO"
    )
    print(f"DB: {settings.DB_PATH}")
    print(f"Validation CSV: {vf_path}")

    return {
        "audit": audit_entries,
        "dq": summary,
        "runtime_s": total_runtime,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the Nifty 100 ETL pipeline")
    p.add_argument(
        "--reset",
        action="store_true",
        help="Truncate all tables before loading (fresh run)",
    )
    p.add_argument(
        "--datasets",
        nargs="*",
        help="Only load the named datasets (default: all)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        run(reset=args.reset, datasets=args.datasets)
        return 0
    except Exception as exc:  # pragma: no cover - top-level guard
        logger.exception(f"ETL run failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
