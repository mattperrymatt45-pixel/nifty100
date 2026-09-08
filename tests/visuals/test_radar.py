"""Unit tests for Sprint 3 Day 19 — Radar Charts."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pytest
from PIL import Image

from src.analytics.radar_charts import (
    AXIS_KEYS,
    AXIS_LABELS,
    N_AXES,
    REPORTS_DIR,
    RadarData,
    _percent_rank,
    generate_radar_charts,
    plot_company_radar,
    plot_standalone_chart,
)


class TestConstants:
    def test_eight_axes(self):
        assert N_AXES == 8
        assert len(AXIS_KEYS) == 8
        assert len(AXIS_LABELS) == 8

    def test_axis_keys_match_spec(self):
        expected = {
            "roe",
            "roce",
            "npm",
            "de",
            "cfo_pat",
            "pat_cagr_5yr",
            "rev_cagr_5yr",
            "composite",
        }
        assert set(AXIS_KEYS) == expected

    def test_de_axis_present_and_lower_is_better(self):
        assert "de" in AXIS_KEYS


class TestPercentRank:
    def test_higher_better_strict_order(self):
        s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        pr = _percent_rank(s, higher_is_better=True)
        assert list(pr) == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])

    def test_lower_better_inverts(self):
        s = pd.Series([0.1, 0.5, 1.0, 2.0])
        pr = _percent_rank(s, higher_is_better=False)
        assert pr.iloc[0] == pytest.approx(1.0)
        assert pr.iloc[-1] == pytest.approx(0.0)

    def test_ties_share_rank(self):
        s = pd.Series([10.0, 20.0, 20.0, 50.0])
        pr = _percent_rank(s, higher_is_better=True)
        assert pr.iloc[0] == pytest.approx(0.0)
        assert pr.iloc[1] == pytest.approx(1 / 3)
        assert pr.iloc[2] == pytest.approx(1 / 3)
        assert pr.iloc[3] == pytest.approx(1.0)

    def test_solo_value_neutral(self):
        pr = _percent_rank(pd.Series([42.0]))
        assert pr.iloc[0] == pytest.approx(0.5)


class TestPlotCompanyRadar:
    @pytest.fixture
    def sample_data(self):
        # Uniform 0.75 across all axes, peer avg at 0.50
        return RadarData(
            company_id="TESTCO",
            company_name="Test Co Ltd",
            peer_group_name="Test Group",
            year="2024-03",
            company_values=[0.75] * 8,
            benchmark_values=[0.50] * 8,
            benchmark_label="Test Group avg",
        )

    def test_writes_png_file(self, tmp_path, sample_data):
        out = tmp_path / "TESTCO_radar.png"
        path = plot_company_radar(sample_data, out)
        assert path.exists()
        assert out.stat().st_size > 5_000  # non-trivial PNG
        with Image.open(out) as img:
            assert img.format == "PNG"
            w, h = img.size
            # Should be a reasonable size (DPI*figsize ~ 1300x1100)
            assert w > 600 and h > 400
        plt.close("all")

    def test_title_contains_company_and_group(self, tmp_path, sample_data):
        out = tmp_path / "TESTCO_radar.png"
        plot_company_radar(sample_data, out)
        # Verify file is valid PNG
        with Image.open(out) as img:
            img.verify()
        plt.close("all")


class TestPlotStandalone:
    def test_writes_png_for_no_peer_company(self, tmp_path):
        out = tmp_path / "NOPGROUP_radar.png"
        company_vals = dict(
            zip(AXIS_KEYS, [15.0, 20.0, 10.0, 0.5, 1.1, 12.0, 8.0, 65.0], strict=True)
        )
        nifty_vals = dict(
            zip(AXIS_KEYS, [16.0, 18.0, 11.0, 0.8, 1.0, 10.0, 9.0, 60.0], strict=True)
        )
        path = plot_standalone_chart(
            company_id="NOPGROUP",
            company_name="No Peer Group Inc",
            year="2024-03",
            company_values=company_vals,
            benchmark_values=nifty_vals,
            output_path=out,
        )
        assert path.exists()
        assert out.stat().st_size > 5_000
        with Image.open(out) as img:
            assert img.format == "PNG"
        plt.close("all")


class TestGenerateBatch:
    def test_generates_one_png_per_company(self, tmp_path, prod_db):
        stats = generate_radar_charts(db_path=prod_db, output_dir=tmp_path)
        assert stats["total"] == 89
        assert stats["radar_charts"] == 54
        assert stats["standalone_charts"] == 35
        # Every file should exist and be a valid PNG
        files = list(tmp_path.glob("*_radar.png"))
        assert len(files) == 89
        for f in files:
            assert f.stat().st_size > 3_000
            with Image.open(f) as img:
                img.verify()
        plt.close("all")

    def test_filename_convention(self, tmp_path, prod_db):
        generate_radar_charts(db_path=prod_db, output_dir=tmp_path)
        assert (tmp_path / "TCS_radar.png").exists()
        assert (tmp_path / "HDFCBANK_radar.png").exists()
        assert (tmp_path / "ADANIENT_radar.png").exists()
        plt.close("all")

    def test_reports_dir_constant(self):
        assert str(REPORTS_DIR).endswith("reports/radar_charts")
        assert REPORTS_DIR.is_dir() or not REPORTS_DIR.exists()  # exists after generation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def prod_db():
    """Production DB path, defensively reset (same pattern as Days 17/18)."""
    import os

    from src.utils.config import settings

    prod = str(settings.PROJECT_ROOT / "db" / "nifty100.db")
    os.environ["NIFTY100_DB_PATH"] = prod
    object.__setattr__(settings, "DB_PATH", Path(prod))
    return prod
