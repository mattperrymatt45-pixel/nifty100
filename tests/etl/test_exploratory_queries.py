"""Day 7 integration tests — exploratory SQL queries + demo script.

Validates:
- db/exploratory_queries.sql exists and contains ≥10 queries
- Every statement in the file is syntactically valid SQLite
- Every SELECT returns at least one row (i.e. is meaningful against a loaded DB)
- scripts/demo_db.py exits 0 against a fresh loaded DB
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUERIES_FILE = PROJECT_ROOT / "db" / "exploratory_queries.sql"
DEMO_SCRIPT = PROJECT_ROOT / "scripts" / "demo_db.py"


def _load_db_with_synthetic_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Generate synthetic data, run ETL into a temp DB, return DB path."""
    monkeypatch.setenv("NIFTY100_DB_PATH", str(tmp_path / "nifty100.db"))
    # Import settings after env is set so _resolve_db_path picks it up
    from src.utils import config as cfg_mod

    db_path = tmp_path / "nifty100.db"
    raw_dir = tmp_path / "raw"
    sup_dir = raw_dir / "supporting datasets"
    processed = tmp_path / "processed"
    raw_dir.mkdir(parents=True)
    sup_dir.mkdir(parents=True)
    processed.mkdir(parents=True)

    # Thaw the frozen settings so we can repoint dirs
    object.__setattr__(cfg_mod.settings, "RAW_DATA_DIR", raw_dir)
    object.__setattr__(cfg_mod.settings, "PROCESSED_DATA_DIR", processed)
    object.__setattr__(cfg_mod.settings, "DB_PATH", db_path)

    from scripts.generate_data import generate_all
    from scripts.run_etl import run as run_etl

    from src.etl.database import get_connection, init_schema, reset_tables

    generate_all(raw_dir)
    init_schema(str(db_path))
    reset_tables(db_path=str(db_path))
    run_etl()

    # Sanity: companies = 92
    with get_connection(str(db_path)) as conn:
        (n,) = conn.execute("SELECT COUNT(*) FROM companies").fetchone()
        assert n == 92, f"Expected 92 companies, got {n}"
    return db_path


def _parse_queries(sql_text: str) -> list[tuple[int, str]]:
    """Extract (query_number, sql_statement) pairs from the annotated file."""
    # Strip sqlite3 dot-pragmas
    sql_text = "\n".join(ln for ln in sql_text.split("\n") if not ln.strip().startswith("."))
    # Split on the long "=====" comment separators
    chunks = re.split(r"\n-- ={20,}\n", sql_text)
    queries: list[tuple[int, str]] = []
    i = 0
    while i < len(chunks):
        m = re.match(r"--\s*QUERY\s+(\d+)\s*:", chunks[i].strip())
        if m and i + 1 < len(chunks):
            qnum = int(m.group(1))
            rest = chunks[i + 1]
            clean_lines: list[str] = []
            for ln in rest.split("\n"):
                if ln.strip().startswith("--"):
                    continue
                # Stop at next separator marker (will be handled by next iteration)
                if ln.strip().startswith("-- ===="):
                    break
                if "--" in ln:
                    ln = ln.split("--", 1)[0]
                clean_lines.append(ln)
            stmt = "\n".join(clean_lines).strip().rstrip(";").strip()
            if stmt:
                queries.append((qnum, stmt))
            i += 2
        else:
            i += 1
    return queries


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_exploratory_queries_file_exists():
    assert QUERIES_FILE.exists(), f"Missing {QUERIES_FILE}"


def test_at_least_10_queries_present():
    sql_text = QUERIES_FILE.read_text(encoding="utf-8")
    queries = _parse_queries(sql_text)
    assert (
        len(queries) >= 10
    ), f"Expected ≥10 QUERY blocks in exploratory_queries.sql, found {len(queries)}"


def test_each_query_runs_and_returns_rows(tmp_path, monkeypatch):
    db_path = _load_db_with_synthetic_data(tmp_path, monkeypatch)
    sql_text = QUERIES_FILE.read_text(encoding="utf-8")
    queries = _parse_queries(sql_text)
    assert len(queries) >= 10

    # Queries that *search for violations* legitimately return 0 rows on clean data.
    # All other queries (summaries, top-N, distributions) must return ≥1 row.
    zero_row_ok = {4, 11, 12, 13}

    with sqlite3.connect(str(db_path)) as conn:
        for qnum, stmt in queries:
            try:
                cur = conn.execute(stmt)
                rows = cur.fetchall()
            except Exception as exc:  # pragma: no cover
                pytest.fail(f"Query {qnum} failed: {exc}\nSQL:\n{stmt}")
            if qnum in zero_row_ok:
                # These are violation-finding queries; 0 rows = clean = expected.
                assert isinstance(rows, list)
            else:
                assert len(rows) >= 1, f"Query {qnum} returned 0 rows (expected >=1)"


def test_demo_script_exits_zero(tmp_path, monkeypatch):
    """scripts/demo_db.py should exit 0 against a healthy DB."""
    db_path = _load_db_with_synthetic_data(tmp_path, monkeypatch)
    result = subprocess.run(
        [sys.executable, str(DEMO_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        env={**__import__("os").environ, "NIFTY100_DB_PATH": str(db_path)},
    )
    assert result.returncode == 0, (
        f"demo_db.py exited {result.returncode}\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "DEMO OK" in result.stdout
    assert "0 critical issues" in result.stdout
