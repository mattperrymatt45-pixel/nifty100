"""Tests for Sprint 6 Day 37 - Cluster Profiling & Portfolio Statistics."""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.analytics.cluster_profiling import (
    FEATURES,
    KPI_DISPLAY_NAMES,
    OUTLIER_Z_THRESHOLD,
    PORTFOLIO_KPIS,
    REFINED_CLUSTER_NAMES,
    compute_correlation_matrix,
    compute_portfolio_stats,
    detect_sector_outliers,
    load_latest_kpis,
    profile_clusters,
    relabel_clusters,
    run_day37_profiling,
    write_cluster_profile,
    write_correlation_heatmap,
    write_outlier_report,
    write_portfolio_stats,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def db_conn():
    from src.utils.config import settings

    conn = sqlite3.connect(str(settings.PROJECT_ROOT / "db" / "nifty100.db"))
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def labels_df():
    from src.utils.config import settings

    return pd.read_csv(settings.PROJECT_ROOT / "output" / "cluster_labels.csv")


@pytest.fixture(scope="module")
def panel_imputed(db_conn):
    from src.analytics.clustering import build_feature_panel, impute_by_sector_median

    panel = build_feature_panel(db_conn)
    return impute_by_sector_median(panel)


@pytest.fixture(scope="module")
def kpi_df(db_conn):
    return load_latest_kpis(db_conn)


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------
class TestConstants:
    def test_five_clusters_named(self):
        assert set(REFINED_CLUSTER_NAMES.keys()) == {0, 1, 2, 3, 4}

    def test_refined_names_are_descriptive(self):
        for name in REFINED_CLUSTER_NAMES.values():
            assert len(name) >= 5
            assert "Cluster" not in name

    def test_refined_names_match_spec_examples(self):
        names = set(REFINED_CLUSTER_NAMES.values())
        # Spec mentions these archetype examples; verify they appear
        assert any("Quality" in n for n in names)
        assert any("Dividend" in n for n in names)
        assert any("Value" in n for n in names)
        assert any("Turnaround" in n or "Distress" in n for n in names)
        assert any("Growth" in n for n in names)

    def test_portfolio_kpis_count(self):
        assert len(PORTFOLIO_KPIS) == 10

    def test_outlier_threshold(self):
        assert OUTLIER_Z_THRESHOLD == 3.0


# ---------------------------------------------------------------------------
# KPI loading
# ---------------------------------------------------------------------------
class TestLoadLatestKPIs:
    def test_one_row_per_company(self, kpi_df):
        assert len(kpi_df) == 92
        assert kpi_df["company_id"].nunique() == 92

    def test_has_all_ten_kpis(self, kpi_df):
        for kpi in PORTFOLIO_KPIS:
            assert kpi in kpi_df.columns, f"Missing column {kpi}"

    def test_kpis_numeric(self, kpi_df):
        for kpi in PORTFOLIO_KPIS:
            assert pd.api.types.is_numeric_dtype(kpi_df[kpi])

    def test_no_duplicate_companies(self, kpi_df):
        assert not kpi_df["company_id"].duplicated().any()


# ---------------------------------------------------------------------------
# Cluster profiling
# ---------------------------------------------------------------------------
class TestClusterProfiling:
    def test_returns_mean_and_median(self, panel_imputed, labels_df):
        means, medians = profile_clusters(panel_imputed, labels_df)
        assert len(means) == 5
        assert len(medians) == 5

    def test_profile_counts_add_up(self, panel_imputed, labels_df):
        means, _ = profile_clusters(panel_imputed, labels_df)
        assert means["count"].sum() == 92

    def test_profile_has_all_features(self, panel_imputed, labels_df):
        means, _ = profile_clusters(panel_imputed, labels_df)
        for feat in FEATURES:
            assert feat in means.columns

    def test_compounder_has_highest_quality(self, panel_imputed, labels_df):
        """High-Quality Compounders should rank high on ROE and OPM with low D/E."""
        means, _ = profile_clusters(panel_imputed, labels_df)
        qc = means[means["cluster_id"] == 3].iloc[0]
        distressed = means[means["cluster_id"] == 1].iloc[0]
        assert qc["return_on_equity_pct"] > distressed["return_on_equity_pct"]
        assert qc["operating_profit_margin_pct"] > distressed["operating_profit_margin_pct"]

    def test_distressed_lowest_roe(self, panel_imputed, labels_df):
        means, _ = profile_clusters(panel_imputed, labels_df)
        distressed_roe = means.loc[means["cluster_id"] == 1, "return_on_equity_pct"].iloc[0]
        others = means[means["cluster_id"] != 1]["return_on_equity_pct"]
        assert distressed_roe < others.min()

    def test_write_cluster_profile(self, tmp_path, panel_imputed, labels_df):
        means, medians = profile_clusters(panel_imputed, labels_df)
        path = write_cluster_profile(means, medians, tmp_path / "profile.csv")
        assert path.exists()
        df = pd.read_csv(path)
        assert set(df["statistic"]) == {"mean", "median"}
        assert len(df) == 10  # 5 clusters * 2 stats


# ---------------------------------------------------------------------------
# Re-labelling
# ---------------------------------------------------------------------------
class TestRelabel:
    def test_relabel_preserves_ids(self, labels_df):
        out = relabel_clusters(labels_df)
        assert list(out["cluster_id"]) == list(labels_df["cluster_id"])
        assert len(out) == 92

    def test_relabel_uses_new_names(self, labels_df):
        out = relabel_clusters(labels_df)
        assert "High-Quality Compounders" in out["cluster_name"].values
        assert "Distressed / Turnaround" in out["cluster_name"].values


# ---------------------------------------------------------------------------
# Correlation matrix & heatmap
# ---------------------------------------------------------------------------
class TestCorrelation:
    def test_shape_diagonal(self, kpi_df):
        corr = compute_correlation_matrix(kpi_df)
        assert corr.shape == (10, 10)
        # Diagonal should be 1
        for col in corr.columns:
            assert corr.loc[col, col] == pytest.approx(1.0, abs=1e-9)

    def test_symmetric(self, kpi_df):
        corr = compute_correlation_matrix(kpi_df)
        assert np.allclose(corr.values, corr.values.T)

    def test_opm_npm_strong_correlation(self, kpi_df):
        corr = compute_correlation_matrix(kpi_df)
        opm_label = KPI_DISPLAY_NAMES["operating_profit_margin_pct"]
        npm_label = KPI_DISPLAY_NAMES["net_profit_margin_pct"]
        assert corr.loc[opm_label, npm_label] > 0.7

    def test_write_heatmap(self, tmp_path, kpi_df):
        corr = compute_correlation_matrix(kpi_df)
        path = write_correlation_heatmap(corr, tmp_path / "heat.png")
        assert path.exists()
        assert path.stat().st_size > 10_000  # Real PNG


# ---------------------------------------------------------------------------
# Outlier detection
# ---------------------------------------------------------------------------
class TestOutliers:
    def test_returns_dataframe(self, kpi_df):
        out = detect_sector_outliers(kpi_df)
        assert isinstance(out, pd.DataFrame)

    def test_outlier_columns(self, kpi_df):
        out = detect_sector_outliers(kpi_df)
        expected = {
            "company_id",
            "company_name",
            "sector",
            "metric",
            "metric_label",
            "value",
            "sector_mean",
            "z_score",
        }
        if len(out) > 0:
            assert expected.issubset(set(out.columns))

    def test_outliers_exceed_threshold(self, kpi_df):
        out = detect_sector_outliers(kpi_df)
        if len(out) > 0:
            assert out["z_score"].abs().min() > OUTLIER_Z_THRESHOLD

    def test_bajfinance_is_pat_outlier(self, kpi_df):
        out = detect_sector_outliers(kpi_df)
        baj = out[out["company_id"] == "BAJFINANCE"]
        assert (baj["metric"] == "pat_cagr_5yr").any()

    def test_write_outlier_report(self, tmp_path, kpi_df):
        out = detect_sector_outliers(kpi_df)
        path = write_outlier_report(out, tmp_path / "out.csv")
        assert path.exists()
        df = pd.read_csv(path)
        assert len(df) >= 1


# ---------------------------------------------------------------------------
# Portfolio stats
# ---------------------------------------------------------------------------
class TestPortfolioStats:
    def test_shape(self, kpi_df):
        stats = compute_portfolio_stats(kpi_df)
        assert len(stats) == len(PORTFOLIO_KPIS)

    def test_percentile_order(self, kpi_df):
        stats = compute_portfolio_stats(kpi_df)
        for _, r in stats.iterrows():
            assert r["p10"] <= r["p25"] <= r["p50"] <= r["p75"] <= r["p90"]

    def test_mean_between_p10_p90(self, kpi_df):
        stats = compute_portfolio_stats(kpi_df)
        for _, r in stats.iterrows():
            assert r["p10"] <= r["mean"] <= r["p90"]

    def test_all_counts_correct(self, kpi_df):
        stats = compute_portfolio_stats(kpi_df)
        for _, r in stats.iterrows():
            assert r["count"] >= 90  # at least 90 of 92 have data
            assert r["count"] <= 92

    def test_write_stats(self, tmp_path, kpi_df):
        stats = compute_portfolio_stats(kpi_df)
        path = write_portfolio_stats(stats, tmp_path / "stats.csv")
        assert path.exists()
        back = pd.read_csv(path)
        assert len(back) == 10
        assert "p50" in back.columns


# ---------------------------------------------------------------------------
# End-to-end entry point
# ---------------------------------------------------------------------------
class TestRunDay37:
    def test_end_to_end_produces_files(self, tmp_path):
        out_dir = tmp_path / "output"
        rep_dir = tmp_path / "reports"
        result = run_day37_profiling(output_dir=out_dir, reports_dir=rep_dir)
        assert (out_dir / "cluster_profile.csv").exists()
        assert (out_dir / "outlier_report.csv").exists()
        assert (out_dir / "portfolio_stats.csv").exists()
        assert (rep_dir / "correlation_heatmap.png").exists()
        # Labels should be re-written (even in tmp mode we write to real output
        # because labels_path uses output_dir argument)
        assert (out_dir / "cluster_labels.csv").exists() or result["paths"]["labels"].exists()

    def test_return_keys(self, tmp_path):
        result = run_day37_profiling(output_dir=tmp_path / "o", reports_dir=tmp_path / "r")
        for key in [
            "cluster_means",
            "cluster_medians",
            "correlation_matrix",
            "outliers",
            "portfolio_stats",
            "labels_relabelled",
            "paths",
        ]:
            assert key in result
