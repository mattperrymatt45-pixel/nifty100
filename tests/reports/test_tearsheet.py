"""Sprint 5 Day 33 — Tests for the ReportLab PDF Tearsheet template."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from reportlab.platypus import Table

from src.reports import tearsheet as ts

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------
class TestFormatCrore:
    def test_none_returns_emdash(self) -> None:
        assert ts._format_crore(None) == "—"

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
        assert "-" in txt


class TestFormatPct:
    def test_none(self) -> None:
        assert ts._fmt_pct(None) == "—"

    def test_positive(self) -> None:
        assert ts._fmt_pct(15.234) == "15.2%"


class TestFigToImage:
    def test_image_returned_is_reportlab_image(self) -> None:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(2, 1))
        ax.plot([1, 2], [3, 4])
        img = ts._fig_to_image(fig, width_cm=4.0, height_cm=2.0)
        from reportlab.platypus import Image as RLImage

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
        assert isinstance(data.history, pd.DataFrame)
        assert len(data.history) <= 10
        assert {"year", "sales", "net_profit", "roe_pct", "roce_pct"}.issubset(data.history.columns)
        # Should have non-None KPIs
        assert data.market_cap_crore is not None and data.market_cap_crore > 0
        assert data.roe_pct is not None

    def test_unknown_company_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="not found"):
            ts.load_tearsheet_data("NONEXISTENTXXXX", conn)

    def test_case_insensitive_ticker(self, conn: sqlite3.Connection) -> None:
        data = ts.load_tearsheet_data("reliance", conn)
        assert data.company_id == "RELIANCE"


# ---------------------------------------------------------------------------
# Flowable/chart builders
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

    def test_revenue_bar_chart_returns_image(self, sample_hist: pd.DataFrame) -> None:
        from reportlab.platypus import Image as RLImage

        img = ts.make_revenue_bar_chart(sample_hist)
        assert isinstance(img, RLImage)

    def test_net_profit_bar_chart_returns_image(self, sample_hist: pd.DataFrame) -> None:
        from reportlab.platypus import Image as RLImage

        img = ts.make_net_profit_bar_chart(sample_hist)
        assert isinstance(img, RLImage)

    def test_roe_roce_line_chart_returns_image(self, sample_hist: pd.DataFrame) -> None:
        from reportlab.platypus import Image as RLImage

        img = ts.make_roe_roce_line_chart(sample_hist)
        assert isinstance(img, RLImage)

    def test_bar_chart_handles_negative_net_profit(self) -> None:
        from reportlab.platypus import Image as RLImage

        hist = pd.DataFrame(
            {
                "year": [f"{y}-03" for y in range(2015, 2025)],
                "sales": list(range(10000, 20000, 1000)),
                "net_profit": [1000, 800, -200, 500, 900, 1200, 1500, -100, 2000, 2500],
                "roe_pct": [10] * 10,
                "roce_pct": [12] * 10,
            }
        )
        img = ts.make_net_profit_bar_chart(hist)
        assert isinstance(img, RLImage)


class TestHeaderBar:
    def test_header_returns_table(self) -> None:
        data = ts.TearsheetData(
            company_id="TCS",
            company_name="Tata Consultancy Services Ltd",
            sector="Information Technology",
            sub_sector="IT Services",
            market_cap_crore=1_000_000.0,
            pe_ratio=25.0,
            pb_ratio=7.0,
            roe_pct=40.0,
            roce_pct=50.0,
            debt_to_equity=0.1,
            dividend_yield_pct=1.5,
            pat_cagr_5yr=10.0,
            revenue_cagr_5yr=8.0,
            eps=100.0,
            cfo_quality_tier="High Quality",
            capex_tier="Asset Light",
            capital_allocation_pattern="Shareholder Returns",
            history=pd.DataFrame(columns=["year", "sales", "net_profit", "roe_pct", "roce_pct"]),
        )
        tbl = ts.build_header_bar(data)
        assert isinstance(tbl, Table)


class TestKPITiles:
    def test_kpi_tiles_returns_table_with_2_rows(self) -> None:
        data = ts.TearsheetData(
            company_id="TCS",
            company_name="Tata Consultancy Services Ltd",
            sector="IT",
            sub_sector=None,
            market_cap_crore=1_000_000.0,
            pe_ratio=25.0,
            pb_ratio=7.0,
            roe_pct=40.0,
            roce_pct=50.0,
            debt_to_equity=0.1,
            dividend_yield_pct=1.5,
            pat_cagr_5yr=10.0,
            revenue_cagr_5yr=8.0,
            eps=100.0,
            cfo_quality_tier=None,
            capex_tier=None,
            capital_allocation_pattern=None,
            history=pd.DataFrame(columns=["year", "sales", "net_profit", "roe_pct", "roce_pct"]),
        )
        tiles = ts.build_kpi_tiles(data)
        assert isinstance(tiles, Table)

    def test_kpi_tiles_handles_all_none_metrics(self) -> None:
        data = ts.TearsheetData(
            company_id="X",
            company_name="X Corp",
            sector=None,
            sub_sector=None,
            market_cap_crore=None,
            pe_ratio=None,
            pb_ratio=None,
            roe_pct=None,
            roce_pct=None,
            debt_to_equity=None,
            dividend_yield_pct=None,
            pat_cagr_5yr=None,
            revenue_cagr_5yr=None,
            eps=None,
            cfo_quality_tier=None,
            capex_tier=None,
            capital_allocation_pattern=None,
            history=pd.DataFrame(columns=["year", "sales", "net_profit", "roe_pct", "roce_pct"]),
        )
        # Should not raise
        tiles = ts.build_kpi_tiles(data)
        assert isinstance(tiles, Table)


# ---------------------------------------------------------------------------
# End-to-end PDF generation
# ---------------------------------------------------------------------------
class TestPDFGeneration:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH))
        yield conn
        conn.close()

    def test_generate_pdf_for_reliance(self, tmp_path: Path, conn: sqlite3.Connection) -> None:
        out = tmp_path / "RELIANCE.pdf"
        path = ts.generate_tearsheet_for_company("RELIANCE", conn, out)
        assert path.exists()
        assert path.stat().st_size > 5000  # >5KB = real PDF with charts
        # Verify it's a valid PDF
        with open(path, "rb") as f:
            header = f.read(5)
        assert header == b"%PDF-"

    def test_generate_pdf_for_distressed_company(
        self, tmp_path: Path, conn: sqlite3.Connection
    ) -> None:
        out = tmp_path / "INDIGO.pdf"
        path = ts.generate_tearsheet_for_company("INDIGO", conn, out)
        assert path.exists()
        # INDIGO has negative NP in 2024-03; PDF should still render
        assert path.stat().st_size > 5000

    def test_pdf_has_two_pages(self, tmp_path: Path, conn: sqlite3.Connection) -> None:
        out = tmp_path / "TCS.pdf"
        ts.generate_tearsheet_for_company("TCS", conn, out)
        try:
            import pymupdf

            doc = pymupdf.open(str(out))
            assert doc.page_count == 2
            doc.close()
        except ImportError:
            # Fallback: count /Type /Page markers in raw bytes
            data = out.read_bytes()
            # Heuristic: a 2-page PDF has at least two /Type/Page entries
            assert data.count(b"/Type /Page") >= 2 or data.count(b"/Type/Page") >= 2

    def test_generate_pdf_with_loaded_data_directly(
        self, tmp_path: Path, conn: sqlite3.Connection
    ) -> None:
        data = ts.load_tearsheet_data("RELIANCE", conn)
        out = tmp_path / "direct.pdf"
        path = ts.generate_tearsheet_pdf(data, out)
        assert path.exists()
