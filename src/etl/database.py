"""SQLite database management for the ETL pipeline.

Provides:
* :func:`get_connection` -- open a connection with ``PRAGMA foreign_keys=ON``
  and Row factory enabled.
* :func:`init_schema` -- execute ``db/schema.sql`` to (re)create tables and
  indexes. Idempotent.
* :func:`load_dataframe` -- bulk-insert a DataFrame into a table via
  ``to_sql(..., if_exists='append')``, returning row counts.
* :func:`reset_tables` / :func:`table_rowcount` -- helpers for re-runnable
  loads and QA.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

import pandas as pd

from src.etl.exceptions import LoaderError
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Tables that contain a time-series year/Year column (used for dedup ordering)
_TIMESERIES_TABLES: frozenset[str] = frozenset(
    {
        "profitandloss",
        "balancesheet",
        "cashflow",
        "documents",
        "stock_prices",
        "market_cap",
        "financial_ratios",
    }
)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
MEMORY_SENTINEL = ":memory:"


def _resolve_db_path(db_path: Path | str | None = None) -> Path | str:
    """Return the absolute DB path, or ':memory:' for in-memory connections.

    Resolution order:
      1. Explicit ``db_path`` argument (always honoured as-is).
      2. ``NIFTY100_DB_PATH`` environment variable (for tests / overrides).
      3. ``settings.DB_PATH`` from the .env configuration.
    """
    raw: Path | str | None = db_path
    if raw is None:
        import os

        raw = os.environ.get("NIFTY100_DB_PATH", settings.DB_PATH)
    if isinstance(raw, str) and raw == MEMORY_SENTINEL:
        return MEMORY_SENTINEL
    p = Path(raw)
    if not p.is_absolute():
        p = (settings.PROJECT_ROOT / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def get_connection(
    db_path: Path | str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a SQLite connection with FKs enabled.

    Pass ``db_path=':memory:'`` for an ephemeral in-memory database (tests).

    Usage::

        with get_connection() as conn:
            conn.execute("INSERT INTO companies (id) VALUES (?)", ("TCS",))
    """
    path = _resolve_db_path(db_path)
    target = str(path) if isinstance(path, Path) else path
    logger.debug(f"Opening SQLite connection to {target}")
    conn = sqlite3.connect(target)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------
_SCHEMA_PATH: Path | None = None


def _schema_path() -> Path:
    """Locate db/schema.sql relative to the project root."""
    global _SCHEMA_PATH
    if _SCHEMA_PATH is not None and _SCHEMA_PATH.exists():
        return _SCHEMA_PATH
    candidate = settings.PROJECT_ROOT / "db" / "schema.sql"
    if not candidate.exists():
        raise LoaderError(f"Schema file not found: {candidate}")
    _SCHEMA_PATH = candidate
    return candidate


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Idempotently add any columns introduced after initial launch.

    SQLite does not support ``ALTER TABLE ADD COLUMN IF NOT EXISTS`` in older
    versions; we introspect ``PRAGMA table_info`` and only ADD what is missing.
    Add new columns here as the schema evolves during Sprint 2+.
    """
    migrations: dict[str, list[tuple[str, str]]] = {
        "financial_ratios": [
            ("ebit_margin_pct", "REAL"),
            ("return_on_assets_pct", "REAL"),
            ("high_leverage_flag", "INTEGER NOT NULL DEFAULT 0"),
            ("icr_label", "TEXT"),
            ("icr_warning_flag", "INTEGER NOT NULL DEFAULT 0"),
            ("net_debt_cr", "REAL"),
            # Day 10: CAGR columns (revenue/PAT/EPS x 3/5/10yr + flags)
            ("revenue_cagr_3yr", "REAL"),
            ("revenue_cagr_3yr_flag", "TEXT"),
            ("revenue_cagr_5yr", "REAL"),
            ("revenue_cagr_5yr_flag", "TEXT"),
            ("revenue_cagr_10yr", "REAL"),
            ("revenue_cagr_10yr_flag", "TEXT"),
            ("pat_cagr_3yr", "REAL"),
            ("pat_cagr_3yr_flag", "TEXT"),
            ("pat_cagr_5yr", "REAL"),
            ("pat_cagr_5yr_flag", "TEXT"),
            ("pat_cagr_10yr", "REAL"),
            ("pat_cagr_10yr_flag", "TEXT"),
            ("eps_cagr_3yr", "REAL"),
            ("eps_cagr_3yr_flag", "TEXT"),
            ("eps_cagr_5yr", "REAL"),
            ("eps_cagr_5yr_flag", "TEXT"),
            ("eps_cagr_10yr", "REAL"),
            ("eps_cagr_10yr_flag", "TEXT"),
            # Day 11: Cash-flow KPIs + capital allocation
            ("fcf_cr", "REAL"),
            ("cfo_pat_ratio", "REAL"),
            ("cfo_quality_score_5yr", "REAL"),
            ("cfo_quality_tier", "TEXT"),
            ("capex_intensity_pct", "REAL"),
            ("capex_tier", "TEXT"),
            ("fcf_conversion_pct", "REAL"),
            ("capital_allocation_pattern", "TEXT"),
            ("cfo_sign", "TEXT"),
            ("cfi_sign", "TEXT"),
            ("cff_sign", "TEXT"),
            ("fcf_concern_flag", "INTEGER NOT NULL DEFAULT 0"),
        ],
    }
    for table, cols in migrations.items():
        cur = conn.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        for col_name, col_def in cols:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                logger.info(f"Migration: added column {table}.{col_name}")


def init_schema(db_path: Path | str | None = None) -> None:
    """Execute db/schema.sql to create all tables, indexes, and triggers.

    Safe to call multiple times (uses ``IF NOT EXISTS``).  Pass
    ``db_path=':memory:'`` for an ephemeral test database.  Runs lightweight
    idempotent migrations after the schema script to backfill new columns
    added to existing databases.
    """
    schema_file = _schema_path()
    sql = schema_file.read_text(encoding="utf-8")
    resolved = _resolve_db_path(db_path)
    with get_connection(resolved) as conn:
        conn.executescript(sql)
        _migrate_schema(conn)
    logger.info(f"Schema initialized from {schema_file}")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def reset_tables(
    tables: list[str] | None = None,
    *,
    db_path: Path | str | None = None,
) -> None:
    """Truncate the given tables (or ALL known tables if ``None``).

    Intended for idempotent re-runs of the ETL pipeline. Respects FK order
    (children before parents) automatically by deactivating FKs during
    the truncation.
    """
    all_tables = [
        "validation_failures",
        "load_audit",
        "prosandcons",
        "peer_groups",
        "financial_ratios",
        "market_cap",
        "stock_prices",
        "documents",
        "analysis",
        "cashflow",
        "balancesheet",
        "profitandloss",
        "sectors",
        "companies",
    ]
    targets = tables if tables is not None else all_tables
    with get_connection(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in targets:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("PRAGMA foreign_keys = ON")
    logger.info(f"Reset tables: {targets}")


def table_rowcount(table: str, *, db_path: Path | str | None = None) -> int:
    """Return the current row count of ``table`` (0 if empty/missing)."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if cur.fetchone()[0] == 0:
            return 0
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])


def _dedupe_by_pk(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Drop exact duplicate PK rows, keeping the last occurrence per spec DQ-02."""
    before = len(df)

    if table == "companies":
        pk = ["id"]
    elif table in (
        "profitandloss",
        "balancesheet",
        "cashflow",
        "market_cap",
        "financial_ratios",
    ):
        pk = ["company_id", "year"]
    elif table == "stock_prices":
        pk = ["company_id", "date"]
    elif table == "documents":
        pk = ["company_id", "Year"]
    elif table == "peer_groups":
        pk = ["company_id", "peer_group_name"]
    elif table == "sectors" or table == "analysis":
        pk = ["company_id"]
    elif table == "prosandcons":
        pk = ["id"] if "id" in df.columns else None
    else:
        pk = None  # audit / vf tables — append-only

    if pk and all(c in df.columns for c in pk):
        out = df.drop_duplicates(subset=pk, keep="last").reset_index(drop=True)
        dropped = before - len(out)
        if dropped:
            logger.warning(f"{table}: dropped {dropped} duplicate PK rows (kept last)")
        return out
    return df


def _clean_for_sqlite(
    df: pd.DataFrame, table: str, db_path: Path | str | None = None
) -> pd.DataFrame:
    """Return a copy of ``df`` trimmed to columns that actually exist in
    the target table, with NaN replaced by None (NULL in SQLite).
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1] for row in cur.fetchall()}

    if not existing_cols:
        raise LoaderError(f"Table '{table}' does not exist. Run init_schema() first.")

    # Keep only DataFrame columns present in the table schema (case-insensitive)
    df_cols_lower = {c.lower(): c for c in df.columns}
    keep: list[str] = []
    for col in existing_cols:
        if col in df.columns:
            keep.append(col)
        elif col.lower() in df_cols_lower:
            keep.append(df_cols_lower[col.lower()])
    out = df[keep].copy() if keep else pd.DataFrame()
    # Replace NaN with None for SQLite NULL semantics
    out = out.where(pd.notna(out), None)
    return out


def _pk_for_table(table: str, df_cols: list[str]) -> list[str] | None:
    """Return the primary-key columns for ``table`` (case-insensitive lookup).

    Matches column names from ``df_cols`` (which may differ in case from our
    canonical names). Returns ``None`` for append-only audit tables.
    """
    cols_lower = {c.lower(): c for c in df_cols}

    def _resolve(*names_lower: str) -> list[str] | None:
        resolved = [cols_lower[n] for n in names_lower if n in cols_lower]
        return resolved if len(resolved) == len(names_lower) else None

    if table == "companies":
        return _resolve("id")
    if table in (
        "profitandloss",
        "balancesheet",
        "cashflow",
        "market_cap",
        "financial_ratios",
    ):
        return _resolve("company_id", "year")
    if table == "stock_prices":
        return _resolve("company_id", "date")
    if table == "documents":
        return _resolve("company_id", "year")  # matches capital-Y "Year" case-insensitively
    if table == "peer_groups":
        return _resolve("company_id", "peer_group_name")
    if table in ("sectors", "analysis"):
        return _resolve("company_id")
    if table == "prosandcons":
        return _resolve("id") if "id" in cols_lower else None
    return None  # append-only audit / validation tables


def _delete_existing_pks(
    conn: sqlite3.Connection, table: str, pk_cols: list[str], cleaned: pd.DataFrame
) -> int:
    """Delete existing rows whose PKs appear in ``cleaned``; return # deleted.

    Uses a temporary table + correlated DELETE to avoid SQLite's
    SQLITE_MAX_EXPR_DEPTH limit (which we hit on large tables like
    stock_prices / documents when using OR'd tuples).
    """
    if cleaned.empty or not pk_cols:
        return 0

    pk_df = cleaned[pk_cols].drop_duplicates().dropna(how="any")
    if pk_df.empty:
        return 0

    # Quote columns to handle e.g. capital-"Y" ``Year``.
    quoted_cols = [f'"{c}"' for c in pk_cols]
    tmp = f"_tmp_pks_{table}"
    col_defs = ", ".join(f"{qc} TEXT" for qc in quoted_cols)
    conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    conn.execute(f"CREATE TEMP TABLE {tmp} ({col_defs})")

    placeholders = ",".join("?" for _ in pk_cols)
    insert_sql = f"INSERT INTO {tmp} VALUES ({placeholders})"
    batch_size = 900
    batch: list[tuple] = []
    for _, row in pk_df.iterrows():
        tup = tuple(_coerce_for_sqlite(v) for v in row.tolist())
        batch.append(tup)
        if len(batch) >= batch_size:
            conn.executemany(insert_sql, batch)
            batch = []
    if batch:
        conn.executemany(insert_sql, batch)

    join_cond = " AND ".join(f"{table}.{qc} = {tmp}.{qc}" for qc in quoted_cols)
    cur = conn.execute(
        f"DELETE FROM {table} WHERE EXISTS (" f"SELECT 1 FROM {tmp} WHERE {join_cond})"
    )
    deleted = cur.rowcount
    conn.execute(f"DROP TABLE {tmp}")
    return deleted


def _coerce_for_sqlite(v: Any) -> Any:
    """Coerce numpy/pandas scalars to plain Python types for sqlite3."""
    if v is None:
        return None
    if isinstance(v, (int, float, str, bytes)):
        return v
    # numpy/pandas types
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, TypeError):
            pass
    if pd.isna(v):
        return None
    return str(v)


def load_dataframe(
    df: pd.DataFrame,
    table: str,
    *,
    db_path: Path | str | None = None,
    if_exists: str = "append",
    deduplicate: bool = True,
    merge: bool = True,
) -> dict[str, int]:
    """Load ``df`` into ``table`` and return row-count statistics.

    Args:
        df:          Pre-normalised pandas DataFrame.
        table:       Target table name.
        db_path:     Override DB path (defaults to ``settings.DB_PATH``).
        if_exists:   pandas ``to_sql`` policy: ``'append'`` (default),
                     ``'replace'``, or ``'fail'``. Only used when ``merge=False``.
        deduplicate: If True (default), drop PK duplicates keeping last within
                     the incoming DataFrame (DQ-02 behaviour).
        merge:       If True (default), delete existing rows whose PKs appear
                     in ``df`` before inserting. This makes repeated loads
                     idempotent ("upsert" via delete+insert). Audit tables
                     (load_audit, validation_failures) ignore this and always
                     append.

    Returns:
        Dict with keys: ``table``, ``rows_in``, ``rows_loaded``, ``rows_dropped``,
        ``rows_deleted``.
    """
    if df is None or df.empty:
        logger.warning(f"load_dataframe({table}): empty DataFrame — nothing written")
        return {
            "table": table,
            "rows_in": 0,
            "rows_loaded": 0,
            "rows_dropped": 0,
            "rows_deleted": 0,
        }

    rows_in = len(df)

    if deduplicate:
        df = _dedupe_by_pk(df, table)
    cleaned = _clean_for_sqlite(df, table, db_path=db_path)
    rows_dropped = rows_in - len(cleaned)

    # Resolve PK for merge strategy.
    pk_cols = _pk_for_table(table, list(cleaned.columns)) if merge else None

    rows_deleted = 0
    with get_connection(db_path) as conn:
        if pk_cols:
            rows_deleted = _delete_existing_pks(conn, table, pk_cols, cleaned)
            if rows_deleted:
                logger.debug(f"{table}: deleted {rows_deleted} existing rows for merge")
        cleaned.to_sql(
            table,
            conn,
            if_exists="append",
            index=False,
            chunksize=1000,
        )
        conn.commit()

    logger.info(
        f"Loaded {table}: {len(cleaned)} rows written "
        f"({rows_dropped} dropped, {rows_deleted} replaced)"
    )
    return {
        "table": table,
        "rows_in": rows_in,
        "rows_loaded": len(cleaned),
        "rows_dropped": rows_dropped,
        "rows_deleted": rows_deleted,
    }


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------
def write_load_audit(
    entries: list[dict],
    *,
    db_path: Path | str | None = None,
) -> None:
    """Append rows to the load_audit table.

    Accepts dicts keyed by either ``table`` (loader convention) or
    ``table_name`` (SQL column name); normalises to ``table_name`` before
    insert and stamps ``loaded_at`` (UTC ISO) client-side so the column
    is never NULL even when a column list is explicitly passed to pandas.
    """
    if not entries:
        return
    from datetime import datetime

    now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
    df = pd.DataFrame([dict(e) for e in entries])
    if "table" in df.columns and "table_name" not in df.columns:
        df = df.rename(columns={"table": "table_name"})
    if "loaded_at" not in df.columns:
        df["loaded_at"] = now
    else:
        df["loaded_at"] = df["loaded_at"].fillna(now)
    if "status" not in df.columns:
        df["status"] = "OK"
    # Don't dedupe the audit table — it's append-only history.
    load_dataframe(df, "load_audit", db_path=db_path, if_exists="append", deduplicate=False)


__all__ = [
    "get_connection",
    "init_schema",
    "load_dataframe",
    "reset_tables",
    "table_rowcount",
    "write_load_audit",
]
