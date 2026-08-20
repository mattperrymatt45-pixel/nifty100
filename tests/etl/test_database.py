"""Tests for src.etl.database — schema bootstrap, FK enforcement, and bulk loading."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.etl.database import (
    get_connection,
    init_schema,
    load_dataframe,
    reset_tables,
    table_rowcount,
    write_load_audit,
)
from src.etl.exceptions import LoaderError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_path(tmp_path, monkeypatch) -> Path:
    """A fresh temporary SQLite file per test."""
    p = tmp_path / "test_nifty100.db"
    # Route the default-db resolver to our temp file via env var
    monkeypatch.setenv("NIFTY100_DB_PATH", str(p))
    return p


@pytest.fixture()
def init_db(db_path):
    init_schema(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------
EXPECTED_TABLES = {
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
    "financial_ratios",
    "peer_groups",
    "load_audit",
    "validation_failures",
}


def test_init_schema_creates_all_tables(init_db):
    with get_connection(init_db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    tables = {r[0] for r in rows}
    assert EXPECTED_TABLES.issubset(tables), f"Missing: {EXPECTED_TABLES - tables}"


def test_init_schema_is_idempotent(init_db):
    """Running init_schema a second time must not error or duplicate objects."""
    init_schema(init_db)  # second call
    with get_connection(init_db) as conn:
        (n,) = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()
    # Should have exactly our tables (plus sqlite_sequence from AUTOINCREMENT)
    assert n >= len(EXPECTED_TABLES)


def test_init_schema_missing_sql_file_raises(tmp_path, monkeypatch):
    fake_root = tmp_path / "noproject"
    fake_root.mkdir()
    target = fake_root / "x.db"
    # The schema locator walks up from __file__ looking for a parent containing
    # db/schema.sql.  We bypass that by replacing _schema_path() directly.
    from src.etl import database as db_mod

    def _boom():
        raise LoaderError(f"Schema file not found: {fake_root / 'nope'}")

    monkeypatch.setattr(db_mod, "_schema_path", _boom)
    with pytest.raises(LoaderError, match="Schema file not found"):
        init_schema(target)


# ---------------------------------------------------------------------------
# Foreign-key enforcement
# ---------------------------------------------------------------------------
def test_foreign_keys_enabled(init_db):
    """PRAGMA foreign_keys must be ON inside every connection from get_connection."""
    with get_connection(init_db) as conn:
        (fk,) = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk == 1


def test_foreign_key_orphan_rejected(init_db):
    """Inserting a profitandloss row for a ticker absent in companies must fail."""
    with get_connection(init_db) as conn:
        conn.execute("INSERT INTO companies (id, company_name, face_value) VALUES ('TCS','TCS',1)")
        # Valid FK — should succeed
        conn.execute(
            "INSERT INTO profitandloss (company_id, year, sales, expenses, "
            "operating_profit, opm_percentage) VALUES ('TCS','2023-03',100,80,20,20.0)"
        )
        # Invalid FK — should raise
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO profitandloss (company_id, year, sales, expenses, "
                "operating_profit, opm_percentage) VALUES ('FAKECO','2023-03',1,1,0,0.0)"
            )


def test_check_constraint_total_assets_positive(init_db):
    """balancesheet has CHECK (total_assets > 0)."""
    with get_connection(init_db) as conn:
        conn.execute("INSERT INTO companies (id, company_name, face_value) VALUES ('X','X',1)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO balancesheet (company_id, year, equity_capital, "
                "total_liabilities, total_assets) VALUES ('X','2023-03',1,1,0)"
            )


# ---------------------------------------------------------------------------
# Primary key enforcement
# ---------------------------------------------------------------------------
def test_company_pk_unique(init_db):
    with get_connection(init_db) as conn:
        conn.execute("INSERT INTO companies (id, company_name, face_value) VALUES ('TCS','a',1)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO companies (id, company_name, face_value) VALUES ('TCS','b',1)"
            )


def test_pl_composite_pk_unique(init_db):
    with get_connection(init_db) as conn:
        conn.execute("INSERT INTO companies (id, company_name, face_value) VALUES ('TCS','TCS',1)")
        conn.execute(
            "INSERT INTO profitandloss (company_id, year, sales, expenses, "
            "operating_profit, opm_percentage) VALUES ('TCS','2023-03',100,80,20,20.0)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO profitandloss (company_id, year, sales, expenses, "
                "operating_profit, opm_percentage) VALUES ('TCS','2023-03',200,160,40,20.0)"
            )


# ---------------------------------------------------------------------------
# load_dataframe
# ---------------------------------------------------------------------------
def test_load_dataframe_basic(init_db):
    companies = pd.DataFrame(
        {"id": ["TCS", "INFY"], "company_name": ["Tata", "Infosys"], "face_value": [1, 5]}
    )
    stats = load_dataframe(companies, "companies", db_path=init_db)
    assert stats["rows_in"] == 2
    assert stats["rows_loaded"] == 2
    assert stats["rows_dropped"] == 0
    assert table_rowcount("companies", db_path=init_db) == 2


def test_load_dataframe_deduplicates_by_pk(init_db):
    """Last occurrence wins when duplicate PKs are present (DQ-02 behavior)."""
    pl = pd.DataFrame(
        {
            "company_id": ["TCS", "TCS", "INFY"],
            "year": ["2023-03", "2023-03", "2023-03"],
            "sales": [100.0, 999.0, 50.0],
            "expenses": [80.0, 888.0, 40.0],
            "operating_profit": [20.0, 111.0, 10.0],
            "opm_percentage": [20.0, 11.1, 20.0],
        }
    )
    # Need a parent company for FK
    load_dataframe(
        pd.DataFrame({"id": ["TCS", "INFY"], "company_name": ["a", "b"], "face_value": [1, 5]}),
        "companies",
        db_path=init_db,
    )
    stats = load_dataframe(pl, "profitandloss", db_path=init_db)
    # One of the two TCS duplicates should be dropped
    assert stats["rows_loaded"] == 2
    with get_connection(init_db) as conn:
        (sales,) = conn.execute(
            "SELECT sales FROM profitandloss WHERE company_id='TCS' AND year='2023-03'"
        ).fetchone()
    assert sales == 999.0  # last-write-wins


def test_load_dataframe_missing_table_raises(init_db):
    df = pd.DataFrame({"x": [1]})
    with pytest.raises(LoaderError, match="does not exist"):
        load_dataframe(df, "no_such_table", db_path=init_db)


def test_load_dataframe_ignores_unknown_columns(init_db):
    """Extra columns not in the schema should be silently ignored by _clean_for_sqlite."""
    df = pd.DataFrame(
        {
            "id": ["TCS"],
            "company_name": ["Tata"],
            "face_value": [1],
            "extra_col": ["will be dropped"],
        }
    )
    load_dataframe(df, "companies", db_path=init_db)
    with get_connection(init_db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
    assert "extra_col" not in cols
    assert table_rowcount("companies", db_path=init_db) == 1


def test_load_dataframe_empty_df(init_db):
    stats = load_dataframe(pd.DataFrame(), "companies", db_path=init_db)
    assert stats["rows_in"] == 0
    assert stats["rows_loaded"] == 0


# ---------------------------------------------------------------------------
# reset_tables & audit
# ---------------------------------------------------------------------------
def test_reset_tables(init_db):
    load_dataframe(
        pd.DataFrame({"id": ["TCS"], "company_name": ["Tata"], "face_value": [1]}),
        "companies",
        db_path=init_db,
    )
    assert table_rowcount("companies", db_path=init_db) == 1
    reset_tables(["companies"], db_path=init_db)
    assert table_rowcount("companies", db_path=init_db) == 0


def test_write_load_audit_appends(init_db):
    write_load_audit(
        [
            {
                "table": "companies",
                "rows_in": 2,
                "rows_out": 2,
                "rows_rejected": 0,
                "runtime_s": 0.1,
                "status": "OK",
            },
            {
                "table": "profitandloss",
                "rows_in": 10,
                "rows_out": 10,
                "rows_rejected": 0,
                "runtime_s": 0.2,
                "status": "OK",
            },
        ],
        db_path=init_db,
    )
    assert table_rowcount("load_audit", db_path=init_db) == 2
    with get_connection(init_db) as conn:
        names = {r[0] for r in conn.execute("SELECT table_name FROM load_audit")}
    assert names == {"companies", "profitandloss"}


# ---------------------------------------------------------------------------
# Indexes exist
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "index_name",
    [
        "idx_pl_company_year",
        "idx_bs_company_year",
        "idx_cf_company_year",
        "idx_sectors_broad",
        "idx_prices_date",
        "idx_mcap_year",
        "idx_ratios_year",
        "idx_peers_group",
        "idx_vf_severity",
    ],
)
def test_index_created(init_db, index_name):
    with get_connection(init_db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,)
        ).fetchone()
    assert row is not None, f"Missing index: {index_name}"


# ---------------------------------------------------------------------------
# In-memory database smoke test (single-connection, since :memory: is per-conn)
# ---------------------------------------------------------------------------
def test_in_memory_schema_creates_successfully():
    """init_schema must work against an ephemeral in-memory DB (no file IO)."""
    init_schema(":memory:")
    with get_connection(":memory:") as conn:
        # Note: :memory: is per-connection, so a fresh conn sees nothing; the
        # point of this test is to confirm _resolve_db_path accepts the sentinel
        # and that we can at least open it without error.
        conn.execute("CREATE TABLE IF NOT EXISTS _probe (x INTEGER)")
        conn.execute("INSERT INTO _probe VALUES (1)")
        (val,) = conn.execute("SELECT x FROM _probe").fetchone()
    assert val == 1
