"""Sprint 5 Day 34 - Tests for batch tearsheet + sector report generation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.reports import batch as bm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


class TestHelpers:
    def test_sector_slug_simple(self) -> None:
        assert bm._sector_slug("Financials") == "financials"

    def test_sector_slug_special_chars(self) -> None:
        assert bm._sector_slug("Conglomerates / Other") == "conglomerates_other"

    def test_sector_slug_empty(self) -> None:
        assert bm._sector_slug("") == "unknown"

    def test_median_ignores_nan(self) -> None:
        s = pd.Series([1.0, 2.0, None, 4.0])
        assert bm._median(s) == pytest.approx(2.0)

    def test_median_empty(self) -> None:
        assert bm._median(pd.Series([], dtype=float)) is None
        assert bm._median(pd.Series([None, None])) is None


class TestSharedYearCounts:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH))
        yield conn
        conn.close()

    def test_all_companies_covered(self, conn: sqlite3.Connection) -> None:
        cov = bm.get_shared_year_counts(conn)
        n_companies = pd.read_sql("SELECT COUNT(*) FROM companies", conn).iloc[0, 0]
        assert len(cov) == n_companies
        assert (
            cov["n_years"] >= bm.MIN_YEARS_REQUIRED
        ).all(), "Some companies have fewer than 3 shared years"


class TestBatchTearsheets:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH))
        yield conn
        conn.close()

    def test_batch_generates_all_tearsheets(self, tmp_path: Path, conn: sqlite3.Connection) -> None:
        out_dir = tmp_path / "ts"
        result = bm.batch_generate_tearsheets(conn, out_dir, min_years=3)
        assert result.failures == []
        assert len(result.generated) == 92
        assert len(result.skipped) == 0
        # All files exist
        assert len(list(out_dir.glob("*_tearsheet.pdf"))) == 92

    def test_batch_respects_min_years(self, tmp_path: Path, conn: sqlite3.Connection) -> None:
        # Setting a very high threshold should skip everything
        out_dir = tmp_path / "ts2"
        result = bm.batch_generate_tearsheets(conn, out_dir, min_years=50)
        assert len(result.generated) == 0
        assert len(result.skipped) == 92

    def test_write_skipped_csv(self, tmp_path: Path) -> None:
        p = tmp_path / "skipped.csv"
        n = bm.write_skipped_csv([("FAKE1", "only 1yr"), ("FAKE2", "missing data")], p)
        assert n == 2
        df = pd.read_csv(p)
        assert list(df.columns) == ["company_id", "reason"]
        assert len(df) == 2
        assert df.iloc[0]["company_id"] == "FAKE1"

    def test_batch_result_dataclass(self) -> None:
        r = bm.BatchResult([], [], [], 0.0)
        assert r.generated == []
        assert r.failures == []


class TestSectorReports:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH))
        yield conn
        conn.close()

    def test_sector_panel_loads(self, conn: sqlite3.Connection) -> None:
        panel = bm._load_sector_panel(conn)
        assert len(panel) == 92
        assert "broad_sector" in panel.columns
        assert "market_cap_crore" in panel.columns

    def test_batch_generates_11_sector_pdfs(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
    ) -> None:
        out_dir = tmp_path / "sec"
        results = bm.batch_generate_sector_reports(conn, out_dir)
        assert len(results) == 11
        for _name, path in results:
            assert path.exists()
            assert path.stat().st_size > 5000
        # Spot check sector slug doesn't contain spaces/slashes
        for _name, path in results:
            assert " " not in path.name
            assert "/" not in path.name

    def test_sector_report_has_required_sections(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
    ) -> None:
        import pymupdf

        out_dir = tmp_path / "sec2"
        results = bm.batch_generate_sector_reports(conn, out_dir)
        # Check IT sector specifically
        it_path = next(p for n, p in results if "Information Technology" in n)
        doc = pymupdf.open(str(it_path))
        text = doc[0].get_text()
        for kw in ("Median ROE", "Sector Composition", "Companies in Sector", "TCS"):
            assert kw in text, f"Missing '{kw}' in IT sector report"
        doc.close()


class TestRunDay34:
    def test_full_run_produces_expected_outputs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Run end-to-end into a temp dir by monkeypatching PROJECT_ROOT."""
        # Set up a minimal project tree
        (tmp_path / "db").mkdir()
        (tmp_path / "output").mkdir()
        (tmp_path / "reports" / "tearsheets").mkdir(parents=True)
        (tmp_path / "reports" / "sector").mkdir(parents=True)
        # Copy DB
        import shutil

        shutil.copy(DB_PATH, tmp_path / "db" / "nifty100.db")
        # Need output dir with pros_cons_generated.csv
        shutil.copy(
            PROJECT_ROOT / "output" / "pros_cons_generated.csv",
            tmp_path / "output" / "pros_cons_generated.csv",
        )

        summary = bm.run_day34_batch(tmp_path)
        assert summary["tearsheets_generated"] == 92
        assert summary["tearsheets_failed"] == 0
        assert summary["sector_reports"] == 11
        assert summary["skipped_csv"].exists()
        pdfs = list((tmp_path / "reports" / "tearsheets").glob("*_tearsheet.pdf"))
        assert len(pdfs) == 92
        sec_pdfs = list((tmp_path / "reports" / "sector").glob("*_report.pdf"))
        assert len(sec_pdfs) == 11
