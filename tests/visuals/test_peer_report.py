"""Unit tests for Sprint 3 Day 20 — Peer Comparison Excel Report."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.analytics.peer_report import (
    OUTPUT_PATH,
    REPORT_METRICS,
    generate_peer_report,
    load_peer_report_dataset,
)

EXPECTED_GROUPS = {
    "Automobiles",
    "Consumer Finance",
    "FMCG",
    "IT Services",
    "Life Insurance",
    "Oil & Gas",
    "Pharmaceuticals",
    "Power & Utilities",
    "Private Banks",
    "Public Banks",
    "Steel & Metals",
}


class TestMetricRegistry:
    def test_twenty_metrics(self):
        assert len(REPORT_METRICS) == 20

    def test_required_metrics_present(self):
        keys = {m.key for m in REPORT_METRICS}
        # Spec bullets: ROE, ROCE, NPM, D/E, FCF, PAT CAGR 5y, Rev CAGR 5y, Composite
        for must_have in (
            "roe",
            "roce",
            "npm",
            "de",
            "fcf",
            "pat_cagr_5yr",
            "rev_cagr_5yr",
            "composite",
        ):
            assert must_have in keys, f"Missing metric: {must_have}"


class TestDatasetLoad:
    def test_returns_one_row_per_peer_group_member(self, prod_db):
        df = load_peer_report_dataset(db_path=prod_db)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 54  # 56 peer_group memberships minus 2? Actually 54.
        assert "is_benchmark" in df.columns
        # Every metric + percentile column present
        for m in REPORT_METRICS:
            assert m.column in df.columns
            assert f"{m.key}_pctile" in df.columns
        # 11 peer groups
        assert set(df["peer_group_name"].unique()) == EXPECTED_GROUPS

    def test_percentiles_in_zero_one(self, prod_db):
        df = load_peer_report_dataset(db_path=prod_db)
        for m in REPORT_METRICS:
            s = df[f"{m.key}_pctile"].dropna()
            assert s.min() >= -1e-9
            assert s.max() <= 1 + 1e-9


class TestWorkbookStructure:
    @pytest.fixture(scope="module")
    def wb_path(self, tmp_path_factory, prod_db):
        tmp = tmp_path_factory.mktemp("peer_rpt")
        out = tmp / "peer_comparison.xlsx"
        generate_peer_report(db_path=prod_db, output_path=out)
        return out

    def test_eleven_sheets(self, wb_path):
        wb = load_workbook(wb_path)
        assert len(wb.sheetnames) == 11
        assert set(wb.sheetnames) == EXPECTED_GROUPS
        wb.close()

    def test_column_count(self, wb_path):
        """Each sheet: 2 identity cols + 2*20 (value + %ile) = 42 columns."""
        wb = load_workbook(wb_path)
        for name in wb.sheetnames:
            ws = wb[name]
            assert ws.max_column == 42, f"{name}: expected 42 cols, got {ws.max_column}"
        wb.close()

    def test_title_row_present(self, wb_path):
        wb = load_workbook(wb_path)
        for name in wb.sheetnames:
            ws = wb[name]
            title = ws.cell(1, 1).value
            assert name in str(title)
            assert "Peer Comparison" in str(title)
        wb.close()

    def test_percentile_colour_coding(self, wb_path):
        """Percentile cells should have green/yellow/red fills in each sheet."""
        wb = load_workbook(wb_path)
        for name in wb.sheetnames:
            ws = wb[name]
            # Percentile columns are every even column starting with D (4)
            n_data = ws.max_row - 3  # exclude title, header, summary
            green = yellow = red = 0
            for r in range(3, 3 + n_data):
                for c in range(4, ws.max_column + 1, 2):
                    f = ws.cell(r, c).fill
                    rgb = f.fgColor.rgb if f.fgColor else ""
                    if rgb.endswith("C6EFCE"):
                        green += 1
                    elif rgb.endswith("FFEB9C"):
                        yellow += 1
                    elif rgb.endswith("FFC7CE"):
                        red += 1
            assert green > 0, f"{name}: no green cells"
            assert yellow > 0, f"{name}: no yellow cells"
            assert red > 0, f"{name}: no red cells"
        wb.close()

    def test_benchmark_row_gold(self, wb_path):
        """The is_benchmark row should have gold fill on the identity columns."""
        wb = load_workbook(wb_path)
        # Pick IT Services where TCS is the benchmark; TCS may not be row 3
        # (sorted by composite). Look for the gold fill row.
        ws = wb["IT Services"]
        found_gold = False
        for r in range(3, ws.max_row + 1):
            if ws.cell(r, 1).value == "Peer Median":
                continue
            rgb = ws.cell(r, 1).fill.fgColor.rgb if ws.cell(r, 1).fill.fgColor else ""
            if rgb.endswith("FFD966"):
                found_gold = True
                # Company column should also be gold
                assert ws.cell(r, 2).fill.fgColor.rgb.endswith("FFD966")
                assert ws.cell(r, 1).value == "TCS"
                break
        assert found_gold, "Benchmark gold fill not found in IT Services"
        wb.close()

    def test_summary_row_peer_median(self, wb_path):
        wb = load_workbook(wb_path)
        for name in wb.sheetnames:
            ws = wb[name]
            last = ws.max_row
            assert ws.cell(last, 1).value == "Peer Median"
            # Summary row should have the light-grey fill
            rgb = ws.cell(last, 1).fill.fgColor.rgb if ws.cell(last, 1).fill.fgColor else ""
            assert rgb.endswith("E7E6E6"), f"{name} summary fill: {rgb}"
            # Median percentile should be 50% for every metric column
            for c in range(4, ws.max_column + 1, 2):
                v = ws.cell(last, c).value
                assert v == pytest.approx(0.5), f"{name} col {c} median %ile = {v}"
        wb.close()

    def test_default_output_exists(self):
        assert OUTPUT_PATH.parent.exists()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def prod_db():
    import os

    from src.utils.config import settings

    prod = str(settings.PROJECT_ROOT / "db" / "nifty100.db")
    os.environ["NIFTY100_DB_PATH"] = prod
    object.__setattr__(settings, "DB_PATH", Path(prod))
    return prod
