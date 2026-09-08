"""Unit tests for the Sprint 3 Day 17 Composite Quality Score module.

Covers:
    * Weights sum to 1.00
    * winsorise caps at P10/P90
    * minmax_scale maps to 0-100
    * piecewise_linear interpolation for D/E and ICR anchors
    * compute_fcf_cagr_5yr returns a DataFrame with fcf_cagr_5yr column
    * compute_composite_scores returns scores in 0-100 range with ranks
    * sector_relative_score is 0-100 within each sector
    * composite_rank and sector_rank start at 1 and are unique within partition
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.analytics.composite import (
    W_CFO_PAT,
    W_DE,
    W_FCF_CAGR,
    W_FCF_POS,
    W_ICR,
    W_NPM,
    W_PAT_CAGR,
    W_REV_CAGR,
    W_ROCE,
    W_ROE,
    CompositeResult,
    _minmax_scale,
    _piecewise_linear,
    _winsorise,
    compute_composite_scores,
    compute_fcf_cagr_5yr,
)


class TestWeightsSumToOne:
    def test_weights_sum_to_one(self):
        total = (
            W_ROE
            + W_ROCE
            + W_NPM
            + W_FCF_CAGR
            + W_CFO_PAT
            + W_FCF_POS
            + W_REV_CAGR
            + W_PAT_CAGR
            + W_DE
            + W_ICR
        )
        assert total == pytest.approx(1.00)

    def test_profitability_is_35_pct(self):
        assert pytest.approx(0.35) == W_ROE + W_ROCE + W_NPM

    def test_cash_quality_is_30_pct(self):
        assert pytest.approx(0.30) == W_FCF_CAGR + W_CFO_PAT + W_FCF_POS

    def test_growth_is_20_pct(self):
        assert pytest.approx(0.20) == W_REV_CAGR + W_PAT_CAGR

    def test_leverage_is_15_pct(self):
        assert pytest.approx(0.15) == W_DE + W_ICR


class TestWinsorise:
    def test_caps_extremes(self):
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 100])
        w = _winsorise(s, lower=0.10, upper=0.90)
        assert w.min() >= s.quantile(0.10) - 1e-9
        assert w.max() <= s.quantile(0.90) + 1e-9
        # After winsorisation, the largest value should be the P90 cap, not 100
        assert w.max() < 100


class TestMinMaxScale:
    def test_maps_to_zero_to_100(self):
        s = pd.Series([10.0, 20.0, 30.0])
        out = _minmax_scale(s)
        assert out.min() == pytest.approx(0.0)
        assert out.max() == pytest.approx(100.0)
        assert out.iloc[1] == pytest.approx(50.0)

    def test_reverse_inverts(self):
        s = pd.Series([1.0, 2.0, 3.0])
        out = _minmax_scale(s, reverse=True)
        assert out.iloc[0] == pytest.approx(100.0)
        assert out.iloc[2] == pytest.approx(0.0)

    def test_constant_series_returns_50(self):
        s = pd.Series([5.0, 5.0, 5.0])
        out = _minmax_scale(s)
        assert (out == 50.0).all()


class TestPiecewiseLinear:
    def test_exact_anchors(self):
        anchors = [(0, 100), (1, 70), (2, 50), (5, 0)]
        assert _piecewise_linear(0.0, anchors) == 100.0
        assert _piecewise_linear(1.0, anchors) == 70.0
        assert _piecewise_linear(2.0, anchors) == 50.0
        assert _piecewise_linear(5.0, anchors) == 0.0

    def test_interpolation(self):
        anchors = [(0, 100), (1, 70)]
        # Midpoint between 0 and 1 → score 85
        assert _piecewise_linear(0.5, anchors) == pytest.approx(85.0)

    def test_clips_out_of_range(self):
        anchors = [(0, 100), (2, 50)]
        assert _piecewise_linear(-1.0, anchors) == 100.0
        assert _piecewise_linear(10.0, anchors) == 50.0

    def test_nan_returns_zero(self):
        assert _piecewise_linear(None, [(0, 100), (1, 70)]) == 0.0


class TestFcfCagr5yr:
    def test_returns_dataframe_for_live_db(self):
        df = compute_fcf_cagr_5yr()
        assert isinstance(df, pd.DataFrame)
        assert "company_id" in df.columns
        assert "fcf_cagr_5yr" in df.columns
        # Must have at least some non-NaN values
        assert df["fcf_cagr_5yr"].notna().sum() >= 10


class TestCompositeScores:
    @pytest.fixture(scope="module")
    def scored(self):
        # Use the production DB for these tests — it has complete latest-year
        # rows for all 92 companies (minus the 3 that lack CF data). We pass
        # ``db_path`` explicitly to defend against sibling module-scoped
        # fixtures that mutate os.environ or the frozen settings singleton
        # (e.g. test_exploratory_queries repoints DB_PATH via object.__setattr__
        # without always restoring it cleanly).
        import os

        from src.screener import load_screener_dataset
        from src.utils.config import settings

        prod_db = str(settings.PROJECT_ROOT / "db" / "nifty100.db")
        # Force the env var too so any downstream code that ignores the
        # explicit kwarg still sees the production DB.
        os.environ["NIFTY100_DB_PATH"] = prod_db
        object.__setattr__(settings, "DB_PATH", __import__("pathlib").Path(prod_db))
        df = load_screener_dataset(
            db_path=prod_db, latest_year_only=True, include_composite_scores=False
        )
        return compute_composite_scores(df, db_path=prod_db)

    def test_returns_composite_result(self, scored):
        assert isinstance(scored, CompositeResult)
        assert isinstance(scored.df, pd.DataFrame)

    def test_scores_in_0_to_100(self, scored):
        s = scored.df[CompositeResult.OVERALL]
        assert s.min() >= 0 - 1e-9
        assert s.max() <= 100 + 1e-9

    def test_sector_relative_in_0_to_100(self, scored):
        s = scored.df[CompositeResult.SECTOR_REL]
        assert s.min() >= 0 - 1e-9
        assert s.max() <= 100 + 1e-9

    def test_universe_rank_starts_at_1_and_is_unique(self, scored):
        r = scored.df[CompositeResult.UNIV_RANK]
        assert r.min() == 1
        assert r.max() == len(scored.df)
        assert r.is_unique

    def test_sector_rank_starts_at_1_within_each_sector(self, scored):
        for sector, grp in scored.df.groupby("broad_sector"):
            assert (
                grp[CompositeResult.SECTOR_RANK].min() == 1
            ), f"{sector} sector_rank doesn't start at 1"

    def test_sorted_descending_by_composite(self, scored):
        scores = scored.df[CompositeResult.OVERALL].tolist()
        assert scores == sorted(scores, reverse=True)

    def test_component_columns_present(self, scored):
        for col in (
            "roe_score",
            "roce_score",
            "npm_score",
            "fcf_cagr_score",
            "cfo_pat_score",
            "fcf_pos_score",
            "rev_cagr_score",
            "pat_cagr_score",
            "de_score",
            "icr_score",
            "fcf_cagr_5yr",
        ):
            assert col in scored.df.columns, f"missing {col}"
