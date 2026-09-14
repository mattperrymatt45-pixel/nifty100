"""Sprint 5 Day 33 - Tests for the ReportLab PDF Tearsheet template."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Table

from src.reports import tearsheet as ts

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


def _make_dummy_data(**overrides) -> ts.TearsheetData:
    """Build a TearsheetData with sensible defaults, overridden by kwargs."""
    base = {
        "company_id": "TEST",
        "company_name": "Test Corp",
        "sector": "IT",
        "sub_sector": None,
        "latest_year": "2024-03",
        "market_cap_crore": 100000.0,
        "pe_ratio": 20.0,
        "pb_ratio": 5.0,
        "roe_pct": 20.0,
        "roce_pct": 25.0,
        "debt_to_equity": 0.3,
        "dividend_yield_pct": 1.5,
        "pat_cagr_5yr": 12.0,
        "revenue_cagr_5yr": 10.0,
        "eps": 50.0,
        "cfo_quality_tier": "High Quality",
        "capex_tier": "Moderate",
        "capital_allocation_pattern": "Shareholder Returns",
        "history": pd.DataFrame(columns=["year", "sales", "net_profit", "roe_pct", "roce_pct"]),
        "bs_history": pd.DataFrame(columns=["year", "equity", "borrowings", "other_liabilities"]),
        "cfo_latest": 5000.0,
        "cfi_latest": -3000.0,
        "cff_latest": -1500.0,
        "net_cf_latest": 500.0,
        "pros": ["Strong ROCE above 20%", "Consistent free cash flow generation"],
        "cons": ["Elevated D/E ratio"],
    }
    base.update(overrides)
    return ts.TearsheetData(**base)


# ---------------------------------------------------------------------------
# Unit tests - helpers
# ---------------------------------------------------------------------------
class TestFormatCrore:
    def test_none_returns_dash(self) -> None:
        assert ts._format_crore(None) == "-"

    def test_small_value(self) -> None:
        assert "Cr" in ts._format_crore(450.0)
        assert "Rs" in ts._format_crore(450.0)
        assert "450" in ts._format_crore(450.0)

    def test_large_value_in_thousands(self) -> None:
        txt = ts._format_crore(25000.0)
        assert "k Cr" in txt
        assert "25.0" in txt

    def test_very_large_value_in_lakh_crore(self) -> None:
        txt = ts._format_crore(1_500_000.0)
        assert "L Cr" in txt

    def test_handles_negative(self) -> None:
        txt = ts._format_crore(-500.0)
        assert txt.startswith("-")


class TestFormatPct:
    def test_none(self) -> None:
        assert ts._fmt_pct(None) == "-"

    def test_positive(self) -> None:
        assert ts._fmt_pct(15.234) == "15.2%"


class TestFigToImage:
    def test_image_returned_is_reportlab_image(self) -> None:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(2, 1))
        ax.plot([1, 2], [3, 4])
        img = ts._fig_to_image(fig, width_cm=4.0, height_cm=2.0)
        assert isinstance(img, RLImage)
        assert img.drawWidth == pytest.approx(4.0 * ts.cm, abs=0.1)


# ---------------------------------------------------------------------------
# TearsheetData loader
# ---------------------------------------------------------------------------
class TestLoadTearsheetData:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH))
        yield conn
        conn.close()

    def test_load_reliance(self, conn: sqlite3.Connection) -> None:
        data = ts.load_tearsheet_data("RELIANCE", conn)
        assert data.company_id == "RELIANCE"
        assert "Reliance" in data.company_name
        assert data.latest_year is not None
        assert isinstance(data.history, pd.DataFrame)
        assert isinstance(data.bs_history, pd.DataFrame)
        assert len(data.history) <= 10
        assert {"year", "sales", "net_profit", "roe_pct", "roce_pct"}.issubset(data.history.columns)
        assert {"year", "equity", "borrowings", "other_liabilities"}.issubset(
            data.bs_history.columns
        )
        assert data.market_cap_crore is not None and data.market_cap_crore > 0
        assert data.roe_pct is not None
        assert data.cfo_latest is not None
        # pros/cons lists are present
        assert isinstance(data.pros, list)
        assert isinstance(data.cons, list)

    def test_unknown_company_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="not found"):
            ts.load_tearsheet_data("NONEXISTENTXXXX", conn)

    def test_case_insensitive_ticker(self, conn: sqlite3.Connection) -> None:
        data = ts.load_tearsheet_data("reliance", conn)
        assert data.company_id == "RELIANCE"


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
class TestCharts:
    @pytest.fixture()
    def sample_hist(self) -> pd.DataFrame:
        years = [f"{y}-03" for y in range(2015, 2025)]
        return pd.DataFrame(
            {
                "year": years,
                "sales": [10000 * (1.1**i) for i in range(10)],
                "net_profit": [1000 * (1.12**i) for i in range(10)],
                "roe_pct": [15 + i * 0.3 for i in range(10)],
                "roce_pct": [18 + i * 0.2 for i in range(10)],
            }
        )

    @pytest.fixture()
    def sample_bs(self) -> pd.DataFrame:
        years = [f"{y}-03" for y in range(2020, 2025)]
        return pd.DataFrame(
            {
                "year": years,
                "equity": [50000 + i * 5000 for i in range(5)],
                "borrowings": [20000 - i * 1000 for i in range(5)],
                "other_liabilities": [30000 + i * 2000 for i in range(5)],
            }
        )

    def test_revenue_bar_chart(self, sample_hist: pd.DataFrame) -> None:
        img = ts.make_revenue_bar_chart(sample_hist, width_cm=8.0, height_cm=4.0)
        assert isinstance(img, RLImage)

    def test_net_profit_bar_chart(self, sample_hist: pd.DataFrame) -> None:
        img = ts.make_net_profit_bar_chart(sample_hist, width_cm=8.0, height_cm=4.0)
        assert isinstance(img, RLImage)

    def test_roe_roce_line_chart(self, sample_hist: pd.DataFrame) -> None:
        img = ts.make_roe_roce_line_chart(sample_hist, width_cm=16.0, height_cm=5.0)
        assert isinstance(img, RLImage)

    def test_bs_stacked_chart(self, sample_bs: pd.DataFrame) -> None:
        img = ts.make_balance_sheet_stacked_chart(sample_bs, width_cm=10.0, height_cm=4.5)
        assert isinstance(img, RLImage)

    def test_cashflow_waterfall(self) -> None:
        img = ts.make_cashflow_waterfall(
            10000.0,
            -6000.0,
            -3000.0,
            1000.0,
            width_cm=6.0,
            height_cm=4.0,
        )
        assert isinstance(img, RLImage)

    def test_cashflow_waterfall_handles_none(self) -> None:
        # Should not crash even if CFI is None
        img = ts.make_cashflow_waterfall(
            None,
            -500.0,
            None,
            None,
            width_cm=6.0,
            height_cm=4.0,
        )
        assert isinstance(img, RLImage)

    def test_bar_chart_handles_negative_net_profit(self) -> None:
        hist = pd.DataFrame(
            {
                "year": [f"{y}-03" for y in range(2015, 2025)],
                "sales": list(range(10000, 20000, 1000)),
                "net_profit": [1000, 800, -200, 500, 900, 1200, 1500, -100, 2000, 2500],
                "roe_pct": [10] * 10,
                "roce_pct": [12] * 10,
            }
        )
        img = ts.make_net_profit_bar_chart(hist, width_cm=8.0, height_cm=4.0)
        assert isinstance(img, RLImage)


# ---------------------------------------------------------------------------
# Flowable builders
# ---------------------------------------------------------------------------
class TestFlowableBuilders:
    def test_header_returns_table(self) -> None:
        data = _make_dummy_data()
        styles = ts._get_styles()
        tbl = ts.build_header_bar(data, styles)
        assert isinstance(tbl, Table)

    def test_kpi_tiles_returns_table(self) -> None:
        data = _make_dummy_data()
        styles = ts._get_styles()
        tiles = ts.build_kpi_tiles(data, styles)
        assert isinstance(tiles, Table)

    def test_kpi_tiles_handles_all_none(self) -> None:
        data = _make_dummy_data(
            market_cap_crore=None,
            pe_ratio=None,
            roe_pct=None,
            roce_pct=None,
            debt_to_equity=None,
            pat_cagr_5yr=None,
        )
        styles = ts._get_styles()
        tiles = ts.build_kpi_tiles(data, styles)
        assert isinstance(tiles, Table)

    def test_capital_allocation_badge(self) -> None:
        data = _make_dummy_data()
        styles = ts._get_styles()
        badge = ts.build_capital_allocation_badge(data, styles)
        assert isinstance(badge, Table)

    def test_pros_cons_table(self) -> None:
        data = _make_dummy_data()
        styles = ts._get_styles()
        tbl = ts.build_pros_cons_table(data, styles)
        assert isinstance(tbl, Table)
        # Long text should be wrapped in Paragraph (wordwrap enabled)
        data2 = _make_dummy_data(
            pros=["This is a very long pro text " * 10],
            cons=["This is a very long con text " * 10],
        )
        tbl2 = ts.build_pros_cons_table(data2, styles)
        assert isinstance(tbl2, Table)

    def test_page1_flowables(self) -> None:
        data = _make_dummy_data()
        flow = ts.build_page1_flowables(data)
        assert len(flow) > 5
        # Should contain Paragraph, Table, Image, Spacer

    def test_page2_flowables(self) -> None:
        data = _make_dummy_data()
        flow = ts.build_page2_flowables(data)
        assert len(flow) >= 4

    def test_tables_use_paragraphs_for_wordwrap(self) -> None:
        """KPI tiles & pros/cons should use Paragraphs for wrapping."""
        data = _make_dummy_data()
        styles = ts._get_styles()
        pc_tbl = ts.build_pros_cons_table(data, styles)
        assert pc_tbl is not None


# ---------------------------------------------------------------------------
# End-to-end PDF generation (5 cross-sector companies per spec)
# ---------------------------------------------------------------------------
CROSS_SECTOR_TICKERS = [
    "TCS",  # Information Technology
    "HDFCBANK",  # Financials
    "RELIANCE",  # Energy
    "SUNPHARMA",  # Healthcare
    "TATASTEEL",  # Materials
]


class TestPDFGeneration:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH))
        yield conn
        conn.close()

    @pytest.mark.parametrize("ticker", CROSS_SECTOR_TICKERS)
    def test_generate_pdf_cross_sector(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        ticker: str,
    ) -> None:
        out = tmp_path / f"{ticker}.pdf"
        path = ts.generate_tearsheet_for_company(ticker, conn, out)
        assert path.exists()
        assert path.stat().st_size > 5000
        with open(path, "rb") as f:
            assert f.read(5) == b"%PDF-"

    @pytest.mark.parametrize("ticker", CROSS_SECTOR_TICKERS)
    def test_pdf_has_exactly_two_pages(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        ticker: str,
    ) -> None:
        out = tmp_path / f"{ticker}.pdf"
        ts.generate_tearsheet_for_company(ticker, conn, out)
        import pymupdf

        doc = pymupdf.open(str(out))
        assert doc.page_count == 2
        doc.close()

    @pytest.mark.parametrize("ticker", CROSS_SECTOR_TICKERS)
    def test_pdf_no_overflow(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        ticker: str,
    ) -> None:
        """All text blocks must fit within the A4 page (bottom ~800pt)."""
        out = tmp_path / f"{ticker}.pdf"
        ts.generate_tearsheet_for_company(ticker, conn, out)
        import pymupdf

        doc = pymupdf.open(str(out))
        for page in doc:
            blocks = page.get_text("blocks")
            max_y = max((b[3] for b in blocks if b[6] == 0), default=0)
            assert max_y < 810, f"{ticker} page bottom at y={max_y:.1f} > 810"
        doc.close()

    @pytest.mark.parametrize("ticker", CROSS_SECTOR_TICKERS)
    def test_pdf_page2_contains_required_sections(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        ticker: str,
    ) -> None:
        out = tmp_path / f"{ticker}.pdf"
        ts.generate_tearsheet_for_company(ticker, conn, out)
        import pymupdf

        doc = pymupdf.open(str(out))
        p2_text = doc[1].get_text()
        for kw in ("Balance Sheet", "Cash Flow", "Strengths", "Risks", "Capital Allocation"):
            assert kw in p2_text, f"{ticker} page 2 missing '{kw}'"
        doc.close()

    @pytest.mark.parametrize("ticker", CROSS_SECTOR_TICKERS)
    def test_pdf_contains_charts(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
        ticker: str,
    ) -> None:
        """Page 1 should have 3 images (2 bars + 1 line); Page 2 has 2 (BS + CF)."""
        out = tmp_path / f"{ticker}.pdf"
        ts.generate_tearsheet_for_company(ticker, conn, out)
        import pymupdf

        doc = pymupdf.open(str(out))
        assert len(doc[0].get_images()) >= 3, f"{ticker} page 1 missing charts"
        assert len(doc[1].get_images()) >= 2, f"{ticker} page 2 missing charts"
        doc.close()

    def test_generate_pdf_with_loaded_data_directly(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
    ) -> None:
        data = ts.load_tearsheet_data("RELIANCE", conn)
        out = tmp_path / "direct.pdf"
        path = ts.generate_tearsheet_pdf(data, out)
        assert path.exists()

    def test_generate_pdf_for_pros_rich_company(
        self,
        tmp_path: Path,
        conn: sqlite3.Connection,
    ) -> None:
        """ASIANPAINT has 9 pros (truncated to 6) - should not overflow."""
        out = tmp_path / "ASIANPAINT.pdf"
        ts.generate_tearsheet_for_company("ASIANPAINT", conn, out)
        import pymupdf

        doc = pymupdf.open(str(out))
        assert doc.page_count == 2
        for page in doc:
            blocks = page.get_text("blocks")
            max_y = max((b[3] for b in blocks if b[6] == 0), default=0)
            assert max_y < 810, f"ASIANPAINT overflow: y={max_y:.1f}"
        doc.close()
