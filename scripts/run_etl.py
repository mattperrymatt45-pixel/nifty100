#!/usr/bin/env python3
"""End-to-end ETL entry point (Sprint 1, Days 2-6).

Loads all 12 datasets from ``data/raw/``, normalises tickers/years,
initialises the SQLite database schema, bulk-loads all tables,
rejects CRITICAL rows (unparseable years / invalid tickers) before
insertion, runs DQ validation, and writes a full audit trail
(load_audit.csv, validation_failures.csv, parse_failures.csv).

Usage (from project root)::

    python -m scripts.run_etl            # full run
    python -m scripts.run_etl --reset    # wipe all tables first
    make load                            # via Makefile
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

# Ensure project root is importable when invoked as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.etl import (  # noqa: E402
    DATASET_SPECS,
    available_datasets,
    load_dataset,
)
from src.etl.database import (  # noqa: E402
    get_connection,
    init_schema,
    load_dataframe,
    reset_tables,
    table_rowcount,
    write_load_audit,
)
from src.etl.exceptions import ETLError, LoaderError  # noqa: E402
from src.etl.normalizers import YEAR_PARSE_ERROR  # noqa: E402
from src.etl.validation import validate_all  # noqa: E402
from src.utils.config import settings  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

#: Tables whose ``year`` column is normalised to YYYY-MM and therefore
#: must never contain the ``PARSE_ERROR`` sentinel when persisted.
_YEAR_NORMALISED_TABLES: frozenset[str] = frozenset(
    {"profitandloss", "balancesheet", "cashflow", "financial_ratios"}
)

#: Tables whose ticker column is ``company_id`` (everybody except companies
#: itself, where the ticker lives in ``id``).
_TICKER_COL: dict[str, str] = {"companies": "id"}
_DEFAULT_TICKER_COL = "company_id"

# Load order: parent/snapshot tables first, then time-series children.
# companies is the only FK parent; dimensions are loaded before facts for
# readability and so any future intra-child FKs resolve cleanly.
LOAD_ORDER: list[str] = [
    "companies",
    "sectors",
    "analysis",
    "peer_groups",
    "prosandcons",
    "documents",
    "market_cap",
    "profitandloss",
    "balancesheet",
    "cashflow",
    "financial_ratios",
    "stock_prices",
]


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
    """Analysis.xlsx: coerce ``id`` to integer (source row id, not a PK)."""
    if "id" in df.columns:
        df["id"] = pd.to_numeric(df["id"], errors="coerce")
    return df


# Per-dataset post-processing hooks. Keyed by logical dataset name.
_POST_PROCESS: dict[str, callable] = {
    "documents": _normalize_documents_year,
    "market_cap": _normalize_market_cap_year,
    "analysis": _normalize_analysis,
}


def _reject_critical_rows(
    df: pd.DataFrame, table_name: str, parse_failures: list[dict]
) -> pd.DataFrame:
    """Remove CRITICAL-DQ rows (unparseable years / tickers) before DB insert.

    Rows whose year column equals the ``PARSE_ERROR`` sentinel are removed
    and appended to ``parse_failures`` so they can be logged to
    ``parse_failures.csv``. Rows whose ticker is empty/None after
    normalisation are also removed (the loader already drops these for
    ticker_col tables, but we re-check defensively).

    Returns the cleaned DataFrame.
    """
    before = len(df)

    # Reject PARSE_ERROR years in tables that receive normalised FY labels.
    if table_name in _YEAR_NORMALISED_TABLES and "year" in df.columns:
        bad_mask = df["year"].astype(str) == YEAR_PARSE_ERROR
        if bad_mask.any():
            for idx in df.index[bad_mask]:
                parse_failures.append(
                    {
                        "table": table_name,
                        "company_id": (
                            str(df.at[idx, "company_id"]) if "company_id" in df.columns else None
                        ),
                        "column": "year",
                        "raw_value": str(df.at[idx, "year"]),
                        "reason": "Unparseable financial-year label (DQ-07)",
                        "detected_at": datetime.now(UTC)
                        .replace(tzinfo=None)
                        .isoformat(timespec="seconds")
                        + "Z",
                    }
                )
            df = df.loc[~bad_mask].reset_index(drop=True)

    # Reject rows with missing/empty ticker in the appropriate column.
    tcol = _TICKER_COL.get(table_name, _DEFAULT_TICKER_COL)
    if tcol in df.columns:
        empty_mask = df[tcol].isna() | (df[tcol].astype(str).str.strip() == "")
        if empty_mask.any():
            for _idx in df.index[empty_mask]:
                parse_failures.append(
                    {
                        "table": table_name,
                        "company_id": None,
                        "column": tcol,
                        "raw_value": None,
                        "reason": "Missing/invalid ticker (DQ-08)",
                        "detected_at": datetime.now(UTC)
                        .replace(tzinfo=None)
                        .isoformat(timespec="seconds")
                        + "Z",
                    }
                )
            df = df.loc[~empty_mask].reset_index(drop=True)

    rejected = before - len(df)
    if rejected:
        logger.warning(f"{table_name}: rejected {rejected} row(s) with CRITICAL DQ failures")
    return df


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
    parse_failures: list[dict] = []

    # 2. Load order: parent/snapshot tables first, then time-series children.
    ordered = [n for n in LOAD_ORDER if n in targets]
    # Include any unexpected targets at the end (defensive)
    ordered += [n for n in targets if n not in ordered]

    for name in ordered:
        t0 = time.perf_counter()
        try:
            df = load_dataset(name)

            # Apply per-dataset post-processing (year type coercion etc.)
            hook = _POST_PROCESS.get(name)
            if hook is not None:
                df = hook(df)

            # Reject CRITICAL rows (PARSE_ERROR years, empty tickers) so
            # they never reach SQLite, and log them to parse_failures.
            rows_before_reject = len(df)
            df = _reject_critical_rows(df, name, parse_failures)
            critical_rejected = rows_before_reject - len(df)

            tables[name] = df
            stats = load_dataframe(df, name, deduplicate=True)
            stats["runtime_s"] = round(time.perf_counter() - t0, 3)
            stats["status"] = "OK"
            # Translate loader keys to the load_audit schema names so the
            # CSV/DB columns (rows_out, rows_rejected) are always populated.
            stats["rows_out"] = stats.get("rows_loaded", 0)
            stats["rows_rejected"] = stats.get("rows_dropped", 0) + critical_rejected
            audit_entries.append(stats)
        except ETLError as exc:
            logger.error(f"Failed to load {name}: {exc}")
            audit_entries.append(
                {
                    "table": name,
                    "rows_in": 0,
                    "rows_loaded": 0,
                    "rows_dropped": 0,
                    "rows_out": 0,
                    "rows_rejected": 0,
                    "rows_deleted": 0,
                    "runtime_s": round(time.perf_counter() - t0, 3),
                    "status": f"FAILED: {exc}",
                }
            )

    # 3. Run DQ validation across all loaded tables. The canonical CSV is
    #    written to OUTPUT_DIR (deliverable location) and a mirror copy is
    #    kept in PROCESSED_DATA_DIR so the working dataset directory is
    #    self-contained.
    output_dir = settings.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    vf_path = output_dir / "validation_failures.csv"
    vf_path_processed = settings.PROCESSED_DATA_DIR / "validation_failures.csv"
    summary = validate_all(tables, output_path=vf_path)
    # Mirror a copy into data/processed for working-directory convenience.
    with contextlib.suppress(OSError):
        shutil.copyfile(vf_path, vf_path_processed)
    logger.info(
        f"DQ summary: {summary['critical']} CRITICAL / "
        f"{summary['warning']} WARNING / {summary['info']} INFO — "
        f"failures written to {vf_path}"
    )

    # Also persist DQ failures to DB (validation_failures table)
    if summary["failures"]:
        # Translate dict keys to the SQL schema (validation_failures columns).
        # DQFailure uses `table`/`column`/`timestamp`; the DB schema uses
        # `table_name`/`column_name`/`reported_at`.
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
            "timestamp": "reported_at",
        }
        vf_db = pd.DataFrame(
            [{sql_k: f.get(k) for k, sql_k in col_map.items()} for f in summary["failures"]]
        )
        # Ensure reported_at is stamped (NOT NULL column)
        now_iso = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
        if "reported_at" not in vf_db.columns:
            vf_db["reported_at"] = now_iso
        else:
            vf_db["reported_at"] = vf_db["reported_at"].fillna(now_iso)
        # Append (don't dedupe — history is preserved)
        load_dataframe(vf_db, "validation_failures", deduplicate=False)

    # 4. Record per-table rowcounts for the audit log
    for entry in audit_entries:
        entry["rows_out"] = table_rowcount(entry["table"])
    write_load_audit(audit_entries)

    # 5. Export audit CSVs to OUTPUT_DIR (deliverable location) and mirror
    #    to PROCESSED_DATA_DIR for working-directory convenience.
    output_dir = settings.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    processed = settings.PROCESSED_DATA_DIR
    processed.mkdir(parents=True, exist_ok=True)

    def _mirror_csv(src_df: pd.DataFrame, name: str) -> Path:
        """Write ``df`` to both OUTPUT_DIR and PROCESSED_DATA_DIR; return output path."""
        out = output_dir / name
        prc = processed / name
        src_df.to_csv(out, index=False)
        with contextlib.suppress(OSError):
            src_df.to_csv(prc, index=False)
        return out

    # 5a. load_audit.csv (latest 1000 entries)
    with get_connection() as conn:
        audit_df = pd.read_sql_query("SELECT * FROM load_audit ORDER BY id DESC LIMIT 1000", conn)
    audit_csv = _mirror_csv(audit_df, "load_audit.csv")
    logger.info(f"Wrote load_audit CSV: {audit_csv} ({len(audit_df)} rows)")

    # 5b. parse_failures.csv — rows rejected before DB insert (DQ-07 / DQ-08)
    pf_cols = ["table", "company_id", "column", "raw_value", "reason", "detected_at"]
    if parse_failures:
        pf_df = pd.DataFrame(parse_failures)
        parse_csv = _mirror_csv(pf_df, "parse_failures.csv")
        logger.info(f"Wrote parse_failures CSV: {parse_csv} ({len(pf_df)} rejected rows)")
    else:
        empty_pf = pd.DataFrame(columns=pf_cols)
        parse_csv = _mirror_csv(empty_pf, "parse_failures.csv")
        logger.info(f"No parse failures. Empty report written to {parse_csv}")

    total_runtime = round(time.perf_counter() - start, 3)
    total_loaded = sum(e.get("rows_loaded", 0) for e in audit_entries)
    total_rejected = sum(e.get("rows_rejected", 0) for e in audit_entries)
    logger.info(
        f"=== ETL run complete in {total_runtime}s — "
        f"{total_loaded} rows loaded / {total_rejected} rejected across "
        f"{len(audit_entries)} tables ==="
    )

    # Print a friendly summary to stdout (for `make load` visibility)
    print("\n=== ETL Summary ===")
    for e in audit_entries:
        print(
            f"  {e['table']:<18} in={e.get('rows_in',0):>6}  "
            f"loaded={e.get('rows_loaded',0):>6}  "
            f"rejected={e.get('rows_rejected',0):>4}  "
            f"[{e['status']}] ({e.get('runtime_s',0):.2f}s)"
        )
    print(
        f"\nDQ: {summary['critical']} CRITICAL / {summary['warning']} WARNING / "
        f"{summary['info']} INFO"
    )
    print(f"DB: {settings.DB_PATH}")
    print(f"Validation CSV: {vf_path}")
    print(f"Load audit CSV: {audit_csv}")
    print(f"Parse failures CSV: {parse_csv}")
    return {
        "audit": audit_entries,
        "dq": summary,
        "parse_failures": parse_failures,
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
