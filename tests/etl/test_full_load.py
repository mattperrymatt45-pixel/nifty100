"""Integration tests for Day 5: Full end-to-end data load into SQLite.

Verifies the deliverables from Sprint 1 Day 5:
- All 12 datasets load successfully
- companies = 92 rows
- P&L ~1276 rows, BS ~1312 rows, CF ~1187 rows (+/-15% tolerance on synthetic data)
- stock_prices = 5520 (92 x 60 months)
- market_cap = 552 (92 x 6 years)
- Zero FK orphans (FK check = 0)
- load_audit table populated
- Idempotent reloads don't duplicate rows
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.etl import available_datasets, load_dataset
from src.etl.database import (
    get_connection,
    init_schema,
    load_dataframe,
    reset_tables,
    table_rowcount,
    write_load_audit,
)
from src.etl.validation import validate_all

# Parent/snapshot tables load first; time-series children after.
LOAD_ORDER = [
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

# Expected minimum row counts (spec §5-§6; synthetic data targets within tolerance)
EXPECTED_COUNTS = {
    "companies": 92,
    "sectors": 92,
    "stock_prices": 5520,
    "market_cap": 552,
    "peer_groups": (50, 70),
    "analysis": (15, 92),
    "prosandcons": (10, 30),
    "documents": (1500, 1700),
    "profitandloss": (1100, 1400),
    "balancesheet": (1100, 1400),
    "cashflow": (1000, 1300),
    "financial_ratios": (1000, 1300),
}


def _post_process(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Mimic scripts/run_etl.py post-processing hooks."""
    if name == "documents" and "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    elif name == "market_cap" and "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    elif name == "analysis" and "id" in df.columns and "company_id" in df.columns:
        df = df.drop(columns=["id"])
    return df


@pytest.fixture()
def loaded_db(tmp_path, monkeypatch):
    """Run a full ETL load against a fresh temp DB and return the path."""
    db_file = tmp_path / "nifty100.db"
    monkeypatch.setenv("NIFTY100_DB_PATH", str(db_file))
    init_schema(db_file)
    reset_tables(db_path=db_file)

    tables: dict[str, pd.DataFrame] = {}
    audit_entries: list[dict] = []
    for name in LOAD_ORDER:
        df = load_dataset(name)
        df = _post_process(df, name)
        tables[name] = df
        stats = load_dataframe(df, name, db_path=db_file, deduplicate=True)
        stats["runtime_s"] = 0.001
        stats["status"] = "OK"
        audit_entries.append(stats)
    for entry in audit_entries:
        entry["rows_out"] = table_rowcount(entry["table"], db_path=db_file)
    write_load_audit(audit_entries, db_path=db_file)

    summary = validate_all(tables)
    return db_file, tables, summary


def test_all_twelve_datasets_available():
    names = available_datasets()
    for expected in LOAD_ORDER:
        assert expected in names, f"Missing dataset: {expected}"


def test_companies_count_is_92(loaded_db):
    db_file, _, _ = loaded_db
    assert table_rowcount("companies", db_path=db_file) == 92


@pytest.mark.parametrize(
    "table,expected",
    [(t, e) for t, e in EXPECTED_COUNTS.items()],
)
def test_table_row_counts(loaded_db, table, expected):
    db_file, _, _ = loaded_db
    count = table_rowcount(table, db_path=db_file)
    if isinstance(expected, tuple):
        lo, hi = expected
        assert lo <= count <= hi, f"{table}: {count} not in [{lo}, {hi}]"
    else:
        assert count == expected, f"{table}: expected {expected}, got {count}"


def test_zero_fk_orphans(loaded_db):
    """All company_id references in child tables must resolve to companies.id."""
    db_file, _, _ = loaded_db
    child_tables = [
        "profitandloss",
        "balancesheet",
        "cashflow",
        "analysis",
        "documents",
        "prosandcons",
        "sectors",
        "stock_prices",
        "market_cap",
        "financial_ratios",
        "peer_groups",
    ]
    with get_connection(db_file) as conn:
        for t in child_tables:
            # Determine the company column name (documents uses company_id too)
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
            cid_col = "company_id" if "company_id" in cols else None
            if cid_col is None:
                continue
            cur = conn.execute(
                f'SELECT COUNT(*) FROM {t} WHERE "{cid_col}" NOT IN (SELECT id FROM companies)'
            )
            orphans = cur.fetchone()[0]
            assert orphans == 0, f"{t} has {orphans} orphan company_id rows"


def test_no_critical_dq_failures(loaded_db):
    _, _, summary = loaded_db
    assert summary["critical"] == 0, f"Critical DQ failures: {summary['critical']}"


def test_load_audit_populated(loaded_db):
    db_file, _, _ = loaded_db
    assert table_rowcount("load_audit", db_path=db_file) >= 12  # one row per table


def test_idempotent_reload_does_not_duplicate(loaded_db):
    db_file, tables, _ = loaded_db
    before = {t: table_rowcount(t, db_path=db_file) for t in EXPECTED_COUNTS}
    for name in LOAD_ORDER:
        df = _post_process(tables[name], name)
        load_dataframe(df, name, db_path=db_file, deduplicate=True)
    after = {t: table_rowcount(t, db_path=db_file) for t in EXPECTED_COUNTS}
    for t in EXPECTED_COUNTS:
        assert after[t] == before[t], f"{t} grew from {before[t]} to {after[t]} on reload"


def test_stock_prices_92x60_rows(loaded_db):
    """92 companies x 60 months (Jan 2020 - Dec 2024) = 5520 rows exactly."""
    db_file, _, _ = loaded_db
    with get_connection(db_file) as conn:
        (n,) = conn.execute("SELECT COUNT(*) FROM stock_prices").fetchone()
        (n_companies,) = conn.execute(
            "SELECT COUNT(DISTINCT company_id) FROM stock_prices"
        ).fetchone()
        (n_dates,) = conn.execute("SELECT COUNT(DISTINCT date) FROM stock_prices").fetchone()
    assert n == 5520
    assert n_companies == 92
    assert n_dates == 60
