"""
Unit tests for the Sprint 2 Day 10 CAGR engine.

Covers the spec-required edge cases (§23.1 & Day 10 brief):
    1. Normal (positive→positive) CAGR — 5yr, 10yr math check
    2. TURNAROUND flag (base<0, end>0) → None
    3. DECLINE_TO_LOSS flag (base>0, end<0) → None
    4. BOTH_NEGATIVE flag → None
    5. ZERO_BASE flag (start=0) → None
    6. INSUFFICIENT flag (less than n years of data) → None
    7. End=0 (total wipeout, positive base) → -100% (not a flag)
    8. Series-level helper produces INSUFFICIENT for early rows
    9. compute_all_cagrs returns all 9 metrics for a multi-year company
    10. Invalid flags/windows raise appropriate errors
"""

from __future__ import annotations

import pytest

from src.analytics.cagr import (
    CAGR_BOTH_NEGATIVE,
    CAGR_DECLINE_TO_LOSS,
    CAGR_INSUFFICIENT,
    CAGR_OK,
    CAGR_TURNAROUND,
    CAGR_WINDOWS,
    CAGR_ZERO_BASE,
    CAGRResult,
    CompanyCAGRs,
    cagr,
    compute_all_cagrs,
    compute_cagrs_for_series,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _series(*pairs: tuple[str, float]) -> list[tuple[str, float]]:
    """Build a (year, value) series from positional pairs."""
    return list(pairs)


# ---------------------------------------------------------------------------
# 1. Normal positive CAGR
# ---------------------------------------------------------------------------
class TestNormalCAGR:
    def test_cagr_10pct_over_5yr(self) -> None:
        """100 → 161.05 over 5yr ≈ 10% CAGR."""
        r = cagr(100.0, 100.0 * (1.10**5), 5)
        assert r.flag == CAGR_OK
        assert r.value is not None
        assert r.value == pytest.approx(10.0, rel=1e-4)
        assert r.start == pytest.approx(100.0)
        assert r.n == 5

    def test_cagr_20pct_over_3yr(self) -> None:
        """100 → 172.8 over 3yr = 20% CAGR."""
        r = cagr(100.0, 172.8, 3)
        assert r.flag == CAGR_OK
        assert r.value == pytest.approx(20.0, rel=1e-4)

    def test_cagr_15pct_over_10yr(self) -> None:
        r = cagr(200.0, 200.0 * (1.15**10), 10)
        assert r.flag == CAGR_OK
        assert r.value == pytest.approx(15.0, rel=1e-4)

    def test_cagr_flat_growth_zero(self) -> None:
        """Start == end (both positive) → 0% CAGR."""
        r = cagr(100.0, 100.0, 5)
        assert r.flag == CAGR_OK
        assert r.value == pytest.approx(0.0)

    def test_cagr_decline_positive_end(self) -> None:
        """100 → 59.05 over 5yr ≈ -10% CAGR."""
        r = cagr(100.0, 100.0 * (0.9**5), 5)
        assert r.flag == CAGR_OK
        assert r.value is not None
        assert r.value == pytest.approx(-10.0, rel=1e-4)

    def test_cagr_normal(self) -> None:
        """Spec §27 (page 41): base=100, end=161, n=5 → CAGR ≈ 10.0%.

        (161/100)^(1/5) - 1 ≈ 9.99% — within 0.05pp of 10.0% since
        1.10**5 = 161.051 exactly.
        """
        r = cagr(100.0, 161.0, 5)
        assert r.flag == CAGR_OK
        assert r.value is not None
        assert abs(r.value - 10.0) < 0.05


# ---------------------------------------------------------------------------
# 2. TURNAROUND — base negative, end positive → None + TURNAROUND flag
# ---------------------------------------------------------------------------
class TestTurnaround:
    def test_turnaround_basic(self) -> None:
        r = cagr(-50.0, 150.0, 5)
        assert r.value is None
        assert r.flag == CAGR_TURNAROUND

    def test_turnaround_small_loss_to_profit(self) -> None:
        r = cagr(-1.0, 100.0, 3)
        assert r.value is None
        assert r.flag == CAGR_TURNAROUND

    def test_turnaround_at_zero_end(self) -> None:
        """Zero end with negative base → turnaround (loss → break-even)."""
        r = cagr(-10.0, 0.0, 3)
        assert r.flag == CAGR_TURNAROUND
        assert r.value is None


# ---------------------------------------------------------------------------
# 3. DECLINE_TO_LOSS — base positive, end negative → None
# ---------------------------------------------------------------------------
class TestDeclineToLoss:
    def test_decline_basic(self) -> None:
        r = cagr(200.0, -50.0, 5)
        assert r.value is None
        assert r.flag == CAGR_DECLINE_TO_LOSS

    def test_decline_tiny_profit_to_loss(self) -> None:
        r = cagr(1.0, -1.0, 3)
        assert r.value is None
        assert r.flag == CAGR_DECLINE_TO_LOSS


# ---------------------------------------------------------------------------
# 4. BOTH_NEGATIVE — both negative → None
# ---------------------------------------------------------------------------
class TestBothNegative:
    def test_both_negative(self) -> None:
        r = cagr(-100.0, -50.0, 5)
        assert r.value is None
        assert r.flag == CAGR_BOTH_NEGATIVE

    def test_both_negative_deepening_loss(self) -> None:
        r = cagr(-50.0, -200.0, 3)
        assert r.value is None
        assert r.flag == CAGR_BOTH_NEGATIVE


# ---------------------------------------------------------------------------
# 5. ZERO_BASE — start = 0 → None
# ---------------------------------------------------------------------------
class TestZeroBase:
    def test_zero_start_positive_end(self) -> None:
        r = cagr(0.0, 100.0, 5)
        assert r.value is None
        assert r.flag == CAGR_ZERO_BASE

    def test_zero_start_zero_end(self) -> None:
        r = cagr(0.0, 0.0, 5)
        assert r.value is None
        assert r.flag == CAGR_ZERO_BASE

    def test_zero_start_negative_end(self) -> None:
        r = cagr(0.0, -50.0, 3)
        assert r.value is None
        assert r.flag == CAGR_ZERO_BASE


# ---------------------------------------------------------------------------
# 6. INSUFFICIENT — series helper returns INSUFFICIENT for early rows
# ---------------------------------------------------------------------------
class TestInsufficientData:
    def test_series_early_rows_insufficient(self) -> None:
        s = _series(
            ("2019-03", 100.0),
            ("2020-03", 110.0),
            ("2021-03", 121.0),
            ("2022-03", 133.1),
            ("2023-03", 146.41),
            ("2024-03", 161.05),
        )
        results = compute_cagrs_for_series(s)
        # Rows 0-4 have INSUFFICIENT for 10yr window (need 10 prior rows)
        for i in range(10):
            if i >= len(results):
                break
            res10 = results[i].get(10)
            if i < 10:
                # With only 6 rows, 10yr is ALWAYS insufficient
                assert res10 is not None
                assert res10.flag == CAGR_INSUFFICIENT
                assert res10.value is None
        # 5yr window: row 5 (2024) has 5 predecessors (rows 0..4) → 5-year look-back OK
        assert results[5][5].flag == CAGR_OK
        # Row 4 (2023) only has 4 predecessors → 5yr INSUFFICIENT
        assert results[4][5].flag == CAGR_INSUFFICIENT
        # 3yr window: row 3 (2022) has 3 predecessors → OK
        assert results[3][3].flag == CAGR_OK
        # Rows 0-2 → 3yr INSUFFICIENT
        for i in range(3):
            assert results[i][3].flag == CAGR_INSUFFICIENT

    def test_empty_series(self) -> None:
        assert compute_cagrs_for_series([]) == []

    def test_single_row_all_insufficient(self) -> None:
        results = compute_cagrs_for_series([("2020-03", 100.0)])
        assert len(results) == 1
        for n in CAGR_WINDOWS:
            assert results[0][n].flag == CAGR_INSUFFICIENT
            assert results[0][n].value is None


# ---------------------------------------------------------------------------
# 7. End = 0 (total wipeout, positive base) → -100% CAGR (no flag)
# ---------------------------------------------------------------------------
class TestTotalWipeout:
    def test_end_zero_is_minus_100(self) -> None:
        r = cagr(100.0, 0.0, 5)
        assert r.flag == CAGR_OK
        assert r.value == pytest.approx(-100.0)


# ---------------------------------------------------------------------------
# 8. compute_all_cagrs produces 9 metrics per company-year
# ---------------------------------------------------------------------------
class TestComputeAllCAGRs:
    @pytest.fixture()
    def tcs_rows(self) -> list[dict]:
        """Build 11 years of synthetic P&L rows with 10% sales CAGR, 15% PAT CAGR."""
        rows = []
        base_year = 2014  # earliest year; 10th predecessor for 2024
        for i in range(11):
            yr = f"{base_year + i}-03"
            sales = 1000.0 * ((1.10) ** i)
            pat = 100.0 * ((1.15) ** i)
            eps = 10.0 * ((1.12) ** i)
            rows.append({"year": yr, "sales": sales, "net_profit": pat, "eps": eps})
        return rows

    def test_returns_one_row_per_input(self, tcs_rows: list[dict]) -> None:
        out = compute_all_cagrs("TCS", tcs_rows)
        assert len(out) == len(tcs_rows)
        assert all(isinstance(r, CompanyCAGRs) for r in out)
        assert all(r.company_id == "TCS" for r in out)

    def test_latest_year_cagrs_computed(self, tcs_rows: list[dict]) -> None:
        out = compute_all_cagrs("TCS", tcs_rows)
        last = out[-1]
        assert last.year == "2024-03"
        # Sales grew 10%/yr → 3yr, 5yr, 10yr ≈ 10%
        assert last.revenue_cagr_3yr == pytest.approx(10.0, rel=1e-3)
        assert last.revenue_cagr_5yr == pytest.approx(10.0, rel=1e-3)
        assert last.revenue_cagr_10yr == pytest.approx(10.0, rel=1e-3)
        assert last.revenue_cagr_3yr_flag == CAGR_OK
        assert last.revenue_cagr_5yr_flag == CAGR_OK
        assert last.revenue_cagr_10yr_flag == CAGR_OK
        # PAT 15%
        assert last.pat_cagr_10yr == pytest.approx(15.0, rel=1e-3)
        assert last.pat_cagr_10yr_flag == CAGR_OK
        # EPS 12%
        assert last.eps_cagr_10yr == pytest.approx(12.0, rel=1e-3)
        assert last.eps_cagr_10yr_flag == CAGR_OK

    def test_early_year_insufficient_flags(self, tcs_rows: list[dict]) -> None:
        out = compute_all_cagrs("TCS", tcs_rows)
        # First row: all windows INSUFFICIENT
        first = out[0]
        assert first.revenue_cagr_3yr_flag == CAGR_INSUFFICIENT
        assert first.revenue_cagr_5yr_flag == CAGR_INSUFFICIENT
        assert first.revenue_cagr_10yr_flag == CAGR_INSUFFICIENT
        assert first.revenue_cagr_3yr is None

    def test_empty_input(self) -> None:
        assert compute_all_cagrs("TCS", []) == []

    def test_turnaround_scenario_in_series(self) -> None:
        """Inject a loss year; verify TURNAROUND flag appears at the profit recovery."""
        rows = [
            {"year": "2018-03", "sales": 1000.0, "net_profit": -50.0, "eps": -5.0},
            {"year": "2019-03", "sales": 1050.0, "net_profit": 40.0, "eps": 4.0},
            {"year": "2020-03", "sales": 1100.0, "net_profit": 80.0, "eps": 8.0},
            {"year": "2021-03", "sales": 1200.0, "net_profit": 120.0, "eps": 12.0},
        ]
        out = compute_all_cagrs("TURNCO", rows)
        # 2021 is 3yr after 2018: PAT went -50 → 120 = TURNAROUND
        last = out[-1]
        assert last.pat_cagr_3yr_flag == CAGR_TURNAROUND
        assert last.pat_cagr_3yr is None
        assert last.eps_cagr_3yr_flag == CAGR_TURNAROUND
        assert last.eps_cagr_3yr is None
        # Revenue was always positive → OK
        assert last.revenue_cagr_3yr_flag == CAGR_OK
        assert last.revenue_cagr_3yr is not None


# ---------------------------------------------------------------------------
# 9. CAGRResult contract & validation
# ---------------------------------------------------------------------------
class TestCAGRResultContract:
    def test_invalid_flag_rejected(self) -> None:
        with pytest.raises(ValueError):
            CAGRResult(10.0, "BOGUS", 100.0, 161.0, 5)

    def test_invalid_window_rejected(self) -> None:
        with pytest.raises(ValueError):
            cagr(100.0, 200.0, 0)
        with pytest.raises(ValueError):
            cagr(100.0, 200.0, -1)

    def test_result_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        r = cagr(100.0, 161.05, 5)
        with pytest.raises(FrozenInstanceError):
            r.value = 999.0  # type: ignore[misc]

    def test_n1_window(self) -> None:
        """1-year CAGR is just simple YoY growth."""
        r = cagr(100.0, 115.0, 1)
        assert r.flag == CAGR_OK
        assert r.value == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# 10. Windows tuple is correct
# ---------------------------------------------------------------------------
class TestWindowsConstant:
    def test_cagr_windows_tuple(self) -> None:
        assert CAGR_WINDOWS == (3, 5, 10)
