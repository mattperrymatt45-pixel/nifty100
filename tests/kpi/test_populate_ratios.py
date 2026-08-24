"""Tests for the Day 12 financial_ratios population script.

Validates:
    * Row count >= 1100 after population
    * All required KPI columns populated
    * 3-company manual spot-check passes with <0.1% delta
    * Composite quality score is bounded 0-100
    * Book value per share computed correctly
    * Idempotent (running twice yields same row count)
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.generate_data import generate_all  # noqa: E402
from scripts.populate_ratios import (  # noqa: E402
    _book_value_per_share,
    _spot_check,
    _winsor_score,
    populate,
)

from src.etl import load_dataset  # noqa: E402
from src.etl.database import (  # noqa: E402
    get_connection,
    init_schema,
    load_dataframe,
    reset_tables,
)
from src.etl.normalizers import normalize_ticker, normalize_year_safe  # noqa: E402

LOAD_ORDER = (
    "companies",
    "sectors",
    "analysis",
    "peer_groups",
    "prosandcons",
    "documents",
    "market_cap",
    "profitandloss",
    "balancesheet",
    "cashflow",
    "stock_prices",
)


def _post_process(df: pd.DataFrame, name: str) -> pd.DataFrame:
    if name == "documents" and "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    elif name == "market_cap" and "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    elif name == "analysis" and "id" in df.columns and "company_id" in df.columns:
        df = df.drop(columns=["id"])
    return df


@pytest.fixture(scope="module")
def populated_db(tmp_path_factory):
    """Build a fresh DB with synthetic data, run full ETL, then populate ratios."""
    tmp = tmp_path_factory.mktemp("pop_db")
    db_path = tmp / "test.db"
    raw_dir = tmp / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    generate_all(raw_dir)

    import os

    old = os.environ.get("NIFTY100_DB_PATH")
    os.environ["NIFTY100_DB_PATH"] = str(db_path)
    try:
        init_schema(str(db_path))
        reset_tables(db_path=str(db_path))
        for name in LOAD_ORDER:
            df = load_dataset(name, data_dir=str(raw_dir))
            if "company_id" in df.columns:
                df["company_id"] = df["company_id"].map(
                    lambda x: normalize_ticker(str(x)) if pd.notna(x) else x
                )
            if name in ("profitandloss", "balancesheet", "cashflow"):
                df["year"] = df["year"].map(lambda x: normalize_year_safe(x) if pd.notna(x) else x)
                df = df[df["year"].notna()]
            df = _post_process(df, name)
            load_dataframe(df, name, db_path=str(db_path))
        result = populate(reset=True)
        yield str(db_path), result
    finally:
        if old is None:
            os.environ.pop("NIFTY100_DB_PATH", None)
        else:
            os.environ["NIFTY100_DB_PATH"] = old


class TestRowCount:
    def test_row_count_exceeds_1100(self, populated_db):
        db_path, result = populated_db
        assert result["rows"] >= 1100
        with get_connection(db_path) as conn:
            c = conn.execute("SELECT COUNT(*) FROM financial_ratios").fetchone()[0]
        assert c >= 1100

    def test_ninety_two_companies(self, populated_db):
        db_path, _ = populated_db
        with get_connection(db_path) as conn:
            c = conn.execute("SELECT COUNT(DISTINCT company_id) FROM financial_ratios").fetchone()[
                0
            ]
        assert c == 92


class TestRequiredColumnsPopulated:
    REQUIRED = (
        "net_profit_margin_pct",
        "operating_profit_margin_pct",
        "return_on_equity_pct",
        "debt_to_equity",
        "interest_coverage",
        "asset_turnover",
        "free_cash_flow_cr",
        "capex_cr",
        "earnings_per_share",
        "book_value_per_share",
        "dividend_payout_ratio_pct",
        "total_debt_cr",
        "cash_from_operations_cr",
        "revenue_cagr_5yr",
        "pat_cagr_5yr",
        "eps_cagr_5yr",
        "composite_quality_score",
    )

    @pytest.mark.parametrize("col", REQUIRED)
    def test_column_has_data(self, populated_db, col):
        db_path, _ = populated_db
        with get_connection(db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM financial_ratios").fetchone()[0]
            non_null = conn.execute(
                f"SELECT COUNT(*) FROM financial_ratios WHERE {col} IS NOT NULL"
            ).fetchone()[0]
        if "cagr_5yr" in col:
            assert non_null > total * 0.5, f"{col}: {non_null}/{total}"
        else:
            assert non_null == total, f"{col} has NULLs: {non_null}/{total}"


class TestCompositeScore:
    def test_composite_bounded(self, populated_db):
        db_path, _ = populated_db
        df = pd.read_sql(
            "SELECT composite_quality_score FROM financial_ratios", f"sqlite:///{db_path}"
        )
        assert df["composite_quality_score"].min() >= 0
        assert df["composite_quality_score"].max() <= 100
        assert df["composite_quality_score"].between(0, 100).all()

    def test_winsor_score_higher_is_better(self):
        s = pd.Series([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
        scored = _winsor_score(s, higher_is_better=True)
        # P10=10 → 0; P90=90 → 100; 0 clipped to P10 → 0; 100 clipped to P90 → 100
        assert scored.iloc[0] == pytest.approx(0.0)
        assert scored.iloc[-1] == pytest.approx(100.0)
        assert scored.iloc[5] == pytest.approx(50.0, rel=0.05)

    def test_winsor_lower_is_better(self):
        s = pd.Series([0.1, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0])
        scored = _winsor_score(s, higher_is_better=False)
        assert scored.iloc[0] > scored.iloc[-1]
        assert scored.min() >= 0
        assert scored.max() <= 100


class TestBookValuePerShare:
    def test_basic(self):
        # equity=100, reserves=400, face=10 → 10 shares, book=50
        assert _book_value_per_share(100.0, 400.0, 10.0) == pytest.approx(50.0)

    def test_face_value_one(self):
        assert _book_value_per_share(100.0, 500.0, 1.0) == pytest.approx(6.0)

    def test_zero_face_value_none(self):
        assert _book_value_per_share(100.0, 400.0, 0.0) is None

    def test_none_face_value_none(self):
        assert _book_value_per_share(100.0, 400.0, None) is None


class TestSpotCheck:
    def test_spot_check_passes(self, populated_db):
        db_path, _ = populated_db
        random.seed(2024)
        with get_connection(db_path) as conn:
            checks = _spot_check(conn)
        assert len(checks) == 3
        for c in checks:
            assert c["roe_delta"] < 0.1, f"ROE delta too high for {c['company_id']}"
            assert c["cagr5_delta"] < 0.1, f"CAGR delta too high for {c['company_id']}"


class TestIdempotent:
    def test_double_populate_same_count(self, populated_db):
        db_path, first = populated_db
        import os

        old = os.environ.get("NIFTY100_DB_PATH")
        os.environ["NIFTY100_DB_PATH"] = db_path
        try:
            second = populate(reset=False)
            assert first["rows"] == second["rows"]
        finally:
            if old is None:
                os.environ.pop("NIFTY100_DB_PATH", None)
            else:
                os.environ["NIFTY100_DB_PATH"] = old
