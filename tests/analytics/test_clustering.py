"""Sprint 6 Day 36 - Tests for KMeans clustering module."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from src.analytics import clustering as cl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


class TestConstants:
    def test_features_tuple_has_five(self) -> None:
        assert len(cl.FEATURES) == 5
        assert "return_on_equity_pct" in cl.FEATURES
        assert "fcf_cagr_5yr" in cl.FEATURES

    def test_n_clusters_is_5(self) -> None:
        assert cl.N_CLUSTERS == 5

    def test_random_state_is_42(self) -> None:
        assert cl.RANDOM_STATE == 42


class TestHelpers:
    def test_sfloat_none(self) -> None:
        assert cl._sfloat(None) is None

    def test_sfloat_valid(self) -> None:
        assert cl._sfloat("12.5") == 12.5

    def test_sfloat_invalid(self) -> None:
        assert cl._sfloat("abc") is None


class TestFeaturePanel:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(DB_PATH))
        yield c
        c.close()

    def test_panel_has_92_rows(self, conn: sqlite3.Connection) -> None:
        panel = cl.build_feature_panel(conn)
        assert len(panel) == 92
        expected_cols = {"company_id", "company_name", "sector", *cl.FEATURES}
        for col in expected_cols:
            assert col in panel.columns


class TestImputation:
    def test_impute_fills_missing_with_sector_median(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["A", "B", "C", "D"],
                "company_name": ["A Co", "B Co", "C Co", "D Co"],
                "sector": ["Fin", "Fin", "Fin", "IT"],
                "return_on_equity_pct": [10.0, 20.0, None, 15.0],
                "debt_to_equity": [1.0, 1.0, 1.0, 0.5],
                "revenue_cagr_5yr": [5.0, 5.0, 5.0, 10.0],
                "fcf_cagr_5yr": [3.0, 3.0, 3.0, 8.0],
                "operating_profit_margin_pct": [15.0, 15.0, 15.0, 20.0],
            }
        )
        out = cl.impute_by_sector_median(df)
        assert out.loc[2, "return_on_equity_pct"] == pytest.approx(15.0)
        assert out[list(cl.FEATURES)].isna().sum().sum() == 0

    def test_impute_fallback_global_when_whole_sector_missing(self) -> None:
        df = pd.DataFrame(
            {
                "company_id": ["A", "B"],
                "company_name": ["A", "B"],
                "sector": ["Fin", "Fin"],
                "return_on_equity_pct": [None, None],
                "debt_to_equity": [1.0, 1.0],
                "revenue_cagr_5yr": [5.0, 5.0],
                "fcf_cagr_5yr": [3.0, 3.0],
                "operating_profit_margin_pct": [15.0, 15.0],
            }
        )
        out = cl.impute_by_sector_median(df)
        assert out["return_on_equity_pct"].isna().sum() == 0


class TestClustering:
    @pytest.fixture()
    def panel(self) -> pd.DataFrame:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            return cl.build_feature_panel(conn)
        finally:
            conn.close()

    def test_run_clustering_produces_5_clusters(self, panel: pd.DataFrame) -> None:
        labels, centroids, inertias = cl.run_clustering(panel)
        assert len(labels) == 92
        assert set(labels["cluster_id"].unique()) == {0, 1, 2, 3, 4}
        assert labels["cluster_name"].nunique() == 5
        assert len(centroids) == 5
        assert len(inertias) == len(cl.K_RANGE_ELBOW)
        assert all(inertias[i] >= inertias[i + 1] - 1e-6 for i in range(len(inertias) - 1))

    def test_cluster_labels_columns(self, panel: pd.DataFrame) -> None:
        labels, _c, _i = cl.run_clustering(panel)
        required = {"company_id", "cluster_id", "cluster_name", "distance_from_centroid"}
        assert required.issubset(labels.columns)
        assert labels["distance_from_centroid"].min() >= 0

    def test_reproducibility(self, panel: pd.DataFrame) -> None:
        """Same random_state -> same labels."""
        imputed = cl.impute_by_sector_median(panel)
        feat = StandardScaler().fit_transform(imputed[list(cl.FEATURES)].values)
        labels1 = KMeans(n_clusters=5, random_state=42, n_init=10).fit_predict(feat)
        labels2 = KMeans(n_clusters=5, random_state=42, n_init=10).fit_predict(feat)
        assert (labels1 == labels2).all()

    def test_assign_cluster_names_uses_all_five(self, panel: pd.DataFrame) -> None:
        _lbl, centroids, _i = cl.run_clustering(panel)
        assert set(centroids["cluster_name"]) == {
            "Quality Compounder",
            "Growth Star",
            "Value Play",
            "Cash Cow / Yield",
            "Turnaround / Risk",
        }

    def test_elbow_plot_and_csv_written(self, panel: pd.DataFrame, tmp_path: Path) -> None:
        _lbl, _c, inertias = cl.run_clustering(panel)
        csv_p = tmp_path / "labels.csv"
        elb_p = tmp_path / "elbow.png"
        lab_df, _c, _i = cl.run_clustering(panel)
        cl.write_cluster_labels(lab_df, csv_p)
        cl.write_elbow_plot(inertias, elb_p)
        assert csv_p.exists() and csv_p.stat().st_size > 500
        assert elb_p.exists() and elb_p.stat().st_size > 5000
        with open(elb_p, "rb") as f:
            assert f.read(8)[:4] == b"\x89PNG"


class TestRunDay36:
    def test_run_end_to_end(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        rep = tmp_path / "rep"
        out.mkdir()
        rep.mkdir()
        shutil.copy(DB_PATH, tmp_path / "nifty100.db")
        cl.run_day36_clustering(
            db_path=tmp_path / "nifty100.db",
            output_dir=out,
            reports_dir=rep,
        )
        assert (out / "cluster_labels.csv").exists()
        assert (out / "cluster_centroids.csv").exists()
        assert (rep / "elbow_plot.png").exists()
        df = pd.read_csv(out / "cluster_labels.csv")
        assert len(df) == 92
        assert df["cluster_id"].nunique() == 5
        assert (df["distance_from_centroid"] >= 0).all()
