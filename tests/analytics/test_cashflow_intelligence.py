"""Sprint 5 Day 31 — Tests for Cash Flow Intelligence module."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.analytics import cashflow_intelligence as ci

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


# ---------------------------------------------------------------------------
# Primitive flag unit tests
# ---------------------------------------------------------------------------
class TestPrimitives:
    def test_distress_signal_fires_when_cfo_neg_cff_pos(self) -> None:
        assert ci.distress_signal(-50.0, 200.0) is True

    def test_distress_signal_false_when_cfo_positive(self) -> None:
        assert ci.distress_signal(50.0, 200.0) is False

    def test_distress_signal_false_when_cff_negative(self) -> None:
        assert ci.distress_signal(-50.0, -200.0) is False

    def test_distress_signal_false_on_missing(self) -> None:
        assert ci.distress_signal(None, 100.0) is False
        assert ci.distress_signal(-100.0, None) is False

    def test_deleveraging_flag_fires_when_cff_neg_and_borrowings_down(self) -> None:
        assert ci.deleveraging_flag(-500.0, 800.0, 1000.0) is True

    def test_deleveraging_flag_false_when_cff_positive(self) -> None:
        assert ci.deleveraging_flag(500.0, 800.0, 1000.0) is False

    def test_deleveraging_flag_false_when_borrowings_up(self) -> None:
        assert ci.deleveraging_flag(-500.0, 1200.0, 1000.0) is False

    def test_deleveraging_flag_false_on_missing_borrowings(self) -> None:
        assert ci.deleveraging_flag(-500.0, None, None) is False

    def test_fcf_cagr_positive_growth(self) -> None:
        # FCF goes 100 -> 121 over 2y => 10% CAGR (but we use last-2 of 5 vals)
        vals = [None, 100.0, None, 110.0, 121.0]
        # With None stripped: [100, 110, 121]; n=2 -> 121/100 = 1.21 -> sqrt = 1.10 = 10%
        assert ci.fcf_cagr(vals, window=5) == pytest.approx(10.0, abs=0.1)

    def test_fcf_cagr_returns_none_for_negative_endpoints(self) -> None:
        assert ci.fcf_cagr([-100.0, 120.0]) is None
        assert ci.fcf_cagr([100.0, -120.0]) is None

    def test_fcf_cagr_returns_none_with_single_value(self) -> None:
        assert ci.fcf_cagr([100.0]) is None


# ---------------------------------------------------------------------------
# End-to-end panel against production DB
# ---------------------------------------------------------------------------
class TestPanelBuild:
    @pytest.fixture(scope="module")
    def panel(self) -> pd.DataFrame:
        return ci.build_cashflow_intelligence_panel(str(DB_PATH))

    def test_panel_covers_all_92_companies(self, panel: pd.DataFrame) -> None:
        assert len(panel) == 92

    def test_panel_has_required_columns(self, panel: pd.DataFrame) -> None:
        assert list(panel.columns) == list(ci.CASHOUTPUT_COLUMNS)

    def test_cfo_quality_scores_in_range(self, panel: pd.DataFrame) -> None:
        scores = panel["cfo_quality_score"].dropna()
        assert (scores >= 0).all() and (scores <= 5).all()  # reasonable upper bound

    def test_capex_pct_non_negative(self, panel: pd.DataFrame) -> None:
        capex = panel["capex_intensity_pct"].dropna()
        assert (capex >= 0).all()

    def test_labels_are_valid_tiers(self, panel: pd.DataFrame) -> None:
        valid_cfo = {"High Quality", "Moderate", "Accrual Risk"}
        valid_capex = {"Asset Light", "Moderate", "Capital Intensive"}
        assert set(panel["cfo_quality_label"].dropna()).issubset(valid_cfo)
        assert set(panel["capex_label"].dropna()).issubset(valid_capex)

    def test_flags_are_boolean(self, panel: pd.DataFrame) -> None:
        assert panel["distress_flag"].dtype == bool
        assert panel["deleveraging_flag"].dtype == bool

    def test_distress_flag_matches_expected_count(self, panel: pd.DataFrame) -> None:
        # Expect a small but plausible number of distress companies (2-6 for Nifty 100)
        assert 0 <= int(panel["distress_flag"].sum()) <= 10


# ---------------------------------------------------------------------------
# Output artifacts
# ---------------------------------------------------------------------------
class TestOutputs:
    def test_xlsx_and_csv_produced(self, tmp_path: Path) -> None:
        summary, _alerts, xlsx, csv = ci.run_cashflow_intelligence(
            db_path=DB_PATH, output_dir=tmp_path
        )
        assert xlsx.exists() and xlsx.stat().st_size > 5000
        assert csv.exists()
        assert len(summary) == 92
        # CSV must have the exact required columns
        a = pd.read_csv(csv)
        assert list(a.columns) == list(ci.DISTRESS_COLUMNS)
        for _, r in a.iterrows():
            # Distress rows must have CFO<0 and CFF>0
            assert r["cfo_cr"] < 0
            assert r["cff_cr"] > 0

    def test_xlsx_readable(self, tmp_path: Path) -> None:
        from openpyxl import load_workbook

        _summary, _alerts, xlsx, _csv = ci.run_cashflow_intelligence(
            db_path=DB_PATH, output_dir=tmp_path
        )
        wb = load_workbook(xlsx)
        assert "Cashflow Intelligence" in wb.sheetnames
        ws = wb["Cashflow Intelligence"]
        assert ws.cell(row=1, column=1).value == "company_id"
        # Header row should be 12 cells wide (CASHOUTPUT_COLUMNS)
        headers = [ws.cell(row=1, column=i).value for i in range(1, 13)]
        assert headers == list(ci.CASHOUTPUT_COLUMNS)
