"""Nifty 100 API - Shared database helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from src.utils.config import settings

# 10 core business tables exposed via the /api/v1/health endpoint
# (per Day-38 spec - the original set before later analytics tables).
BUSINESS_TABLES: tuple[str, ...] = (
    "companies",
    "profitandloss",
    "balancesheet",
    "cashflow",
    "analysis",
    "documents",
    "prosandcons",
    "sectors",
    "stock_prices",
    "market_cap",
)


def get_db_path() -> Path:
    """Return the absolute path to the production SQLite database."""
    return Path(settings.PROJECT_ROOT) / "db" / "nifty100.db"


@contextmanager
def get_db_connection() -> Iterator[sqlite3.Connection]:
    """Context manager yielding a sqlite3 connection with row_factory = Row.

    Usage::

        with get_db_connection() as conn:
            cur = conn.execute(...)
    """
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def table_row_counts() -> dict[str, int]:
    """Return {table_name: row_count} for every tracked business table."""
    counts: dict[str, int] = {}
    with get_db_connection() as conn:
        for table in BUSINESS_TABLES:
            try:
                cur = conn.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[table] = int(cur.fetchone()[0])
            except sqlite3.OperationalError:
                # Missing table surfaces as 0 rather than 500 during scaffold.
                counts[table] = 0
    return counts


__all__ = [
    "BUSINESS_TABLES",
    "get_db_connection",
    "get_db_path",
    "table_row_counts",
]
