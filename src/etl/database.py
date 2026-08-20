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


def init_schema(db_path: Path | str | None = None) -> None:
    """Execute db/schema.sql to create all tables, indexes, and triggers.

    Safe to call multiple times (uses ``IF NOT EXISTS``).  Pass
    ``db_path=':memory:'`` for an ephemeral test database.
    """
    schema_file = _schema_path()
    sql = schema_file.read_text(encoding="utf-8")
    resolved = _resolve_db_path(db_path)
    with get_connection(resolved) as conn:
        conn.executescript(sql)
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


def load_dataframe(
    df: pd.DataFrame,
    table: str,
    *,
    db_path: Path | str | None = None,
    if_exists: str = "append",
    deduplicate: bool = True,
) -> dict[str, int]:
    """Load ``df`` into ``table`` and return row-count statistics.

    Args:
        df:          Pre-normalised pandas DataFrame.
        table:       Target table name.
        db_path:     Override DB path (defaults to ``settings.DB_PATH``).
        if_exists:   pandas ``to_sql`` policy: ``'append'`` (default),
                     ``'replace'``, or ``'fail'``.
        deduplicate: If True (default), drop PK duplicates keeping last.

    Returns:
        Dict with keys: ``table``, ``rows_in``, ``rows_loaded``, ``rows_dropped``.
    """
    if df is None or df.empty:
        logger.warning(f"load_dataframe({table}): empty DataFrame — nothing written")
        return {"table": table, "rows_in": 0, "rows_loaded": 0, "rows_dropped": 0}

    rows_in = len(df)

    if deduplicate:
        df = _dedupe_by_pk(df, table)
    cleaned = _clean_for_sqlite(df, table, db_path=db_path)
    rows_dropped = rows_in - len(cleaned)

    with get_connection(db_path) as conn:
        cleaned.to_sql(
            table,
            conn,
            if_exists=if_exists,
            index=False,
            chunksize=1000,
        )
        conn.commit()

    logger.info(f"Loaded {table}: {len(cleaned)} rows written ({rows_dropped} dropped)")
    return {
        "table": table,
        "rows_in": rows_in,
        "rows_loaded": len(cleaned),
        "rows_dropped": rows_dropped,
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
