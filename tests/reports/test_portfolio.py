"""Sprint 5 Day 35 - Tests for portfolio summary PDF."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from reportlab.lib import colors

from src.reports import portfolio as pf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


class TestTrendArrow:
    def test_improving_up_green(self) -> None:
        a, c = pf.trend_arrow(120.0, 100.0, higher_better=True)
        assert a == pf.ARROW_UP
        assert c == colors.HexColor("#548235")

    def test_declining_down_red(self) -> None:
        a, c = pf.trend_arrow(80.0, 100.0, higher_better=True)
        assert a == pf.ARROW_DOWN
        assert c == colors.HexColor("#C00000")

    def test_flat_within_threshold(self) -> None:
        a, _c = pf.trend_arrow(101.0, 100.0, higher_better=True)  # +1%
        assert a == pf.ARROW_FLAT

    def test_lower_is_better(self) -> None:
        # D/E declining -> improvement
        a, _ = pf.trend_arrow(0.3, 0.5, higher_better=False)
        assert a == pf.ARROW_UP
        # D/E rising -> decline
        a, _ = pf.trend_arrow(0.8, 0.5, higher_better=False)
        assert a == pf.ARROW_DOWN

    def test_none_returns_flat(self) -> None:
        a, _ = pf.trend_arrow(None, 100.0, higher_better=True)
        assert a == pf.ARROW_FLAT
        a, _ = pf.trend_arrow(100.0, None, higher_better=True)
        assert a == pf.ARROW_FLAT


class TestFormatters:
    def test_fmt_none(self) -> None:
        assert pf._fmt(None, "pct") == "-"

    def test_fmt_pct(self) -> None:
        assert pf._fmt(15.234, "pct") == "15.2%"

    def test_fmt_ratio(self) -> None:
        assert pf._fmt(2.345, "ratio") == "2.35"

    def test_fmt_crore_thousands(self) -> None:
        assert "k Cr" in pf._fmt(25000.0, "crore")

    def test_fmt_crore_lakh(self) -> None:
        assert "L Cr" in pf._fmt(1_500_000.0, "crore")


class TestLoadPanel:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(DB_PATH))
        yield c
        c.close()

    def test_panel_has_92_rows(self, conn: sqlite3.Connection) -> None:
        panel = pf.load_portfolio_panel(conn)
        assert len(panel) == 92
        assert "sales_latest" in panel.columns
        assert "np_latest" in panel.columns

    def test_panel_sorted_by_ticker(self, conn: sqlite3.Connection) -> None:
        panel = pf.load_portfolio_panel(conn)
        sorted_ids = sorted(panel["company_id"].tolist())
        assert panel.sort_values("company_id")["company_id"].tolist() == sorted_ids


class TestPDFBuild:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(DB_PATH))
        yield c
        c.close()

    def test_build_portfolio_pdf(self, tmp_path: Path, conn: sqlite3.Connection) -> None:
        panel = pf.load_portfolio_panel(conn)
        out = tmp_path / "portfolio.pdf"
        path = pf.build_portfolio_summary(panel, out)
        assert path.exists()
        assert path.stat().st_size > 100_000
        import pymupdf

        doc = pymupdf.open(str(path))
        assert doc.page_count == 92
        # Every page has company name and 6 KPIs
        for i in range(0, 92, 10):  # spot-check every 10th page
            text = doc[i].get_text()
            assert "FY" in text
            assert "ROE" in text or "Return on Equity" in text
        doc.close()

    def test_run_portfolio_entry(self, tmp_path: Path) -> None:
        out = tmp_path / "p.pdf"
        panel, path = pf.run_portfolio_summary(
            db_path=DB_PATH,
            output_path=out,
        )
        assert len(panel) == 92
        assert path.exists()

    def test_portfolio_pdf_footer_has_page_number(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
    ) -> None:
        panel = pf.load_portfolio_panel(conn)
        out = tmp_path / "p.pdf"
        pf.build_portfolio_summary(panel, out)
        import pymupdf

        doc = pymupdf.open(str(out))
        text_last = doc[-1].get_text()
        assert "Page 92" in text_last
        doc.close()
