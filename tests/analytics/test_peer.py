"""Unit tests for Sprint 3 Day 18 — Peer Percentile Rankings."""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from src.analytics.peer import (
    NO_PEER_GROUP_MSG,
    PEER_METRICS,
    PeerMetric,
    companies_without_peer_group,
    compute_peer_percentiles,
    ensure_schema,
    peer_percentile_for_company,
    populate_peer_percentiles,
)


class TestRegistry:
    def test_ten_metrics_registered(self):
        assert len(PEER_METRICS) == 10

    def test_metric_keys(self):
        keys = {m.key for m in PEER_METRICS}
        expected = {
            "roe",
            "roce",
            "npm",
            "de",
            "fcf",
            "pat_cagr_5yr",
            "rev_cagr_5yr",
            "eps_cagr_5yr",
            "icr",
            "asset_turnover",
        }
        assert keys == expected

    def test_de_is_lower_is_better(self):
        de = next(m for m in PEER_METRICS if m.key == "de")
        assert de.higher_is_better is False

    def test_all_other_metrics_higher_is_better(self):
        for m in PEER_METRICS:
            if m.key == "de":
                continue
            assert m.higher_is_better is True, f"{m.key} should be higher=better"


class TestRank:
    def test_percent_rank_strict_order(self):
        """For 5 distinct sorted values, ranks should be 0, .25, .5, .75, 1."""
        m = PeerMetric("x", "X", "x", higher_is_better=True)
        s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        pr = m.rank(s)
        assert list(pr) == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])

    def test_percent_rank_ties(self):
        """Ties share the same rank (method='min' semantics, same as SQL)."""
        m = PeerMetric("x", "X", "x", higher_is_better=True)
        s = pd.Series([10.0, 20.0, 20.0, 50.0])
        pr = m.rank(s)
        # rank of 10=1→0, 20=2 (tied)→1/3, 50=4→1
        assert list(pr) == pytest.approx([0.0, 1 / 3, 1 / 3, 1.0])

    def test_percent_rank_inverted(self):
        """For D/E, lowest value should get rank 1.0, highest 0.0."""
        m = PeerMetric("de", "D/E", "de", higher_is_better=False)
        s = pd.Series([0.1, 0.5, 1.0, 2.0])
        pr = m.rank(s)
        assert pr.iloc[0] == pytest.approx(1.0)  # lowest D/E = best
        assert pr.iloc[-1] == pytest.approx(0.0)  # highest D/E = worst

    def test_solo_peer_gets_half(self):
        m = PeerMetric("x", "X", "x")
        s = pd.Series([42.0])
        pr = m.rank(s)
        assert pr.iloc[0] == pytest.approx(0.5)

    def test_nan_propagates(self):
        m = PeerMetric("x", "X", "x")
        s = pd.Series([10.0, float("nan"), 30.0])
        pr = m.rank(s)
        assert pd.isna(pr.iloc[1])
        # Non-NaN values ranked against each other: 10→0, 30→1
        assert pr.iloc[0] == pytest.approx(0.0)
        assert pr.iloc[2] == pytest.approx(1.0)


class TestComputeAgainstLiveDb:
    @pytest.fixture(scope="module")
    def scored(self, prod_db):
        return compute_peer_percentiles(db_path=prod_db)

    def test_returns_long_form(self, scored):
        assert isinstance(scored, pd.DataFrame)
        required = {
            "company_id",
            "company_name",
            "peer_group_name",
            "is_benchmark",
            "year",
            "metric",
            "value",
            "percentile_rank",
        }
        assert required.issubset(scored.columns)

    def test_eleven_peer_groups_present(self, scored):
        assert scored["peer_group_name"].nunique() == 11

    def test_row_count_equals_companies_x_metrics(self, scored):
        n_companies = scored["company_id"].nunique()
        assert len(scored) == n_companies * 10
        assert n_companies == 54  # 56 memberships but 2 companies in multiple groups?
        # Actually 56 rows in peer_groups (some companies in multiple groups),
        # so 56 memberships x 10 metrics = 560 rows
        assert len(scored) >= 540

    def test_percentile_in_zero_one(self, scored):
        s = scored["percentile_rank"].dropna()
        assert s.min() >= 0 - 1e-9
        assert s.max() <= 1 + 1e-9

    def test_best_in_group_scores_one(self, scored):
        """Within every (peer_group, metric) the best value scores 1.0."""
        for (grp, metric_key), sub in scored.groupby(["peer_group_name", "metric"]):
            m = next((mm for mm in PEER_METRICS if mm.key == metric_key), None)
            assert m is not None
            s = sub.dropna(subset=["percentile_rank"])
            if s.empty:
                continue
            if m.higher_is_better:
                best_idx = s["value"].idxmax()
                worst_idx = s["value"].idxmin()
            else:
                best_idx = s["value"].idxmin()
                worst_idx = s["value"].idxmax()
            assert s.loc[best_idx, "percentile_rank"] == pytest.approx(
                1.0
            ), f"{grp}/{metric_key} best did not score 1.0"
            assert s.loc[worst_idx, "percentile_rank"] == pytest.approx(
                0.0
            ), f"{grp}/{metric_key} worst did not score 0.0"


class TestCompaniesWithoutPeerGroup:
    def test_returns_list_for_live_db(self, prod_db):
        no_peer = companies_without_peer_group(db_path=prod_db)
        assert isinstance(no_peer, list)
        # Latest year has 89 companies; 56 in peer_groups → 33 or 35 without
        assert 30 <= len(no_peer) <= 40
        # These must NOT be in peer_groups
        import sqlite3

        conn = sqlite3.connect(prod_db)
        for cid in no_peer:
            n = conn.execute(
                "SELECT COUNT(*) FROM peer_groups WHERE company_id=?", (cid,)
            ).fetchone()[0]
            assert n == 0, f"{cid} should not be in peer_groups"
        conn.close()


class TestPeerPercentileForCompany:
    def test_company_with_peer_returns_dataframe(self, prod_db):
        df = peer_percentile_for_company("TCS", db_path=prod_db)
        assert isinstance(df, pd.DataFrame)
        assert set(df["metric"]) == {m.key for m in PEER_METRICS}
        assert (df["peer_group_name"] == "IT Services").all()

    def test_company_without_peer_returns_message(self, prod_db):
        msg = peer_percentile_for_company("ADANIENT", db_path=prod_db)
        assert msg == NO_PEER_GROUP_MSG


class TestPopulateTable:
    def test_ensure_schema_creates_table(self, tmp_path):
        db = tmp_path / "t.db"
        # Bootstrap minimal schema by init_schema from production copy? Use
        # ensure_schema which runs CREATE IF NOT EXISTS directly on an empty
        # DB — will create the table but no peers, so populate returns 0 rows
        # without error.
        ensure_schema(db_path=str(db))
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='peer_percentiles'"
            ).fetchall()
        assert len(rows) == 1

    def test_populate_against_synthetic_db(self, populated_screener_db_for_peer):
        db_path = populated_screener_db_for_peer
        stats = populate_peer_percentiles(db_path=db_path, reset=True)
        assert stats["rows"] == stats["companies"] * stats["metrics"]
        assert stats["metrics"] == 10
        assert stats["groups"] == 11
        # Verify table has right structure
        with sqlite3.connect(db_path) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(peer_percentiles)").fetchall()}
            assert {
                "company_id",
                "peer_group_name",
                "metric",
                "value",
                "percentile_rank",
                "year",
                "computed_at",
            }.issubset(cols)
            n = conn.execute("SELECT COUNT(*) FROM peer_percentiles").fetchone()[0]
            assert n == stats["rows"]

    def test_populate_idempotent(self, populated_screener_db_for_peer):
        db_path = populated_screener_db_for_peer
        s1 = populate_peer_percentiles(db_path=db_path, reset=False)
        s2 = populate_peer_percentiles(db_path=db_path, reset=False)
        assert s1["rows"] == s2["rows"]
        with sqlite3.connect(db_path) as conn:
            n = conn.execute("SELECT COUNT(*) FROM peer_percentiles").fetchone()[0]
        assert n == s2["rows"]  # not doubled


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def prod_db():
    """Absolute path to the production DB (defensive reset like Day-17)."""
    import os
    from pathlib import Path

    from src.utils.config import settings

    prod = str(settings.PROJECT_ROOT / "db" / "nifty100.db")
    os.environ["NIFTY100_DB_PATH"] = prod
    object.__setattr__(settings, "DB_PATH", Path(prod))
    return prod


@pytest.fixture(scope="module")
def populated_screener_db_for_peer(tmp_path_factory, prod_db):
    """Copy the production peer_groups/financial_ratios schema into a fresh
    temp DB for population testing (so we don't clobber production)."""
    import os
    import shutil

    tmp = tmp_path_factory.mktemp("peer_db")
    db_path = str(tmp / "test.db")

    # Copy production DB file (already has companies, peer_groups, financial_ratios).
    shutil.copyfile(prod_db, db_path)
    # Drop peer_percentiles if already present from a prior run.
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS peer_percentiles")
    # Reset env to point at our copy.
    old = os.environ.get("NIFTY100_DB_PATH")
    os.environ["NIFTY100_DB_PATH"] = db_path
    try:
        ensure_schema(db_path=db_path)
        yield db_path
    finally:
        if old is None:
            os.environ.pop("NIFTY100_DB_PATH", None)
        else:
            os.environ["NIFTY100_DB_PATH"] = old
