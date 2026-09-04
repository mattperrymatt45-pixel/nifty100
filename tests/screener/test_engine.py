"""Unit tests for Sprint 3 Day 15 — Screener Filter Engine.

Covers:
    * YAML config loading with all 6 presets and 15 metrics
    * 15 filter metrics: ROE min, D/E max (financials skipped), FCF min,
      revenue/PAT/EPS CAGR 5yr min, OPM min, P/E max, P/B max, Div Yield min,
      ICR min (Debt Free passes), Market Cap min, Net Profit min, Asset
      Turnover min, Sales min, CFO/PAT min
    * Sorted by composite_quality_score desc with rank column
    * Custom threshold overrides
    * Error handling for unknown preset / metric names
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screener import (  # noqa: E402
    ScreenerFilter,
    apply_filters,
    load_config,
    load_screener_dataset,
    run_screener,
)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
class TestConfigLoad:
    def test_default_config_loads(self):
        cfg = load_config()
        assert "quality_compounders" in cfg.presets
        assert "dividend_aristocrats" in cfg.presets
        assert "growth_at_reasonable_price" in cfg.presets
        assert "deep_value" in cfg.presets
        assert "debt_free" in cfg.presets
        assert "small_cap_momentum" in cfg.presets
        assert len(cfg.presets) == 6

    def test_all_15_filterable_metrics_declared(self):
        cfg = load_config()
        required = {
            "roe_pct",
            "debt_to_equity",
            "fcf_cr",
            "revenue_cagr_5yr_pct",
            "pat_cagr_5yr_pct",
            "eps_cagr_5yr_pct",
            "opm_pct",
            "pe_ratio",
            "pb_ratio",
            "dividend_yield_pct",
            "icr",
            "market_cap_cr",
            "net_profit_cr",
            "asset_turnover",
            "sales_cr",
        }
        # Allow extras (e.g. cfo_pat_ratio which we use for compounders)
        assert required.issubset(set(cfg.metrics.keys()))

    def test_preset_filters_are_screener_filter_objects(self):
        cfg = load_config()
        for preset in cfg.presets.values():
            assert preset.label
            for f in preset.filters:
                assert isinstance(f, ScreenerFilter)
                assert f.direction in ("min", "max")
                assert f.column

    def test_unknown_preset_raises(self):
        cfg = load_config()
        with pytest.raises(KeyError):
            cfg.preset("nonexistent_screen")


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------
class TestDatasetLoad:
    def test_latest_year_returns_one_row_per_company(self, populated_screener_db):
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        assert len(df) > 0
        assert df["company_id"].is_unique
        # Every row should have the same latest year
        assert df["year"].nunique() == 1

    def test_dataset_has_all_15_filter_columns(self, populated_screener_db):
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        cfg = load_config()
        for metric, mdef in cfg.metrics.items():
            assert mdef["column"] in df.columns, f"missing column for {metric}: {mdef['column']}"

    def test_composite_score_column_present(self, populated_screener_db):
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        assert "composite_quality_score" in df.columns


# ---------------------------------------------------------------------------
# Individual filter semantics
# ---------------------------------------------------------------------------
class TestFilterSemantics:
    def test_min_roe_threshold_filters(self, populated_screener_db):
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        cfg.preset("dividend_aristocrats")  # smoke-check preset exists
        # Build a synthetic preset that only applies ROE ≥ 15
        from src.screener.engine import ScreenerPreset

        only_roe = ScreenerPreset(
            name="roe_test",
            label="ROE test",
            description="",
            filters=[
                ScreenerFilter(
                    metric="roe_pct",
                    threshold=15.0,
                    direction="min",
                    column="roe_pct",
                )
            ],
        )
        res = apply_filters(df, only_roe, cfg)
        assert (res.df["roe_pct"] >= 15.0).all() or len(res.df) == 0
        assert res.rows_out <= res.rows_in

    def test_max_de_filter_excludes_high_leverage_non_financials(self, populated_screener_db):
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        from src.screener.engine import ScreenerPreset

        de_only = ScreenerPreset(
            name="de_test",
            label="D/E test",
            description="",
            filters=[
                ScreenerFilter(
                    metric="debt_to_equity",
                    threshold=1.0,
                    direction="max",
                    skip_financials=True,
                    column="debt_to_equity",
                )
            ],
        )
        res = apply_filters(df, de_only, cfg)
        # Any non-financial company in the output must have D/E ≤ 1.
        non_fin_mask = (
            res.df["broad_sector"]
            .fillna("")
            .apply(lambda s: not any(kw in s.lower() for kw in cfg.financial_keywords))
        )
        assert (res.df.loc[non_fin_mask, "debt_to_equity"] <= 1.0 + 1e-9).all()

    def test_financials_skipped_for_de_filter(self, populated_screener_db):
        """Financials with high D/E MUST still appear when D/E max filter
        is set — their leverage is structural."""
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        from src.screener.engine import ScreenerPreset

        de_tight = ScreenerPreset(
            name="de_tight",
            label="D/E tight",
            description="",
            filters=[
                ScreenerFilter(
                    metric="debt_to_equity",
                    threshold=0.5,
                    direction="max",
                    skip_financials=True,
                    column="debt_to_equity",
                )
            ],
        )
        res = apply_filters(df, de_tight, cfg)
        # There should be at least one financial in the output even with tight D/E
        is_fin = (
            res.df["broad_sector"]
            .fillna("")
            .apply(lambda s: any(kw in s.lower() for kw in cfg.financial_keywords))
        )
        assert is_fin.any(), "Expected financial-sector companies to pass D/E filter via skip"

    def test_debt_free_passes_icr_min(self, populated_screener_db):
        """Any company whose icr_label == 'Debt Free' must pass even an
        absurdly high ICR minimum (their cover is effectively infinite).
        We construct a synthetic row in the DataFrame to guarantee the
        case exists regardless of synthetic-data calibration."""
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        # Inject one synthetic debt-free company
        synth = df.iloc[0].copy()
        synth["company_id"] = "DEBTFREE01"
        synth["company_name"] = "Debt Free Test Co"
        synth["icr"] = None
        synth["icr_label"] = "Debt Free"
        synth["composite_quality_score"] = 100.0
        df_aug = pd.concat([df, pd.DataFrame([synth])], ignore_index=True)

        from src.screener.engine import ScreenerPreset

        icr_strict = ScreenerPreset(
            name="icr_test",
            label="ICR strict",
            description="",
            filters=[
                ScreenerFilter(
                    metric="icr",
                    threshold=999.0,  # impossible unless debt-free
                    direction="min",
                    debt_free_passes=True,
                    column="icr",
                )
            ],
        )
        res = apply_filters(df_aug, icr_strict, cfg)
        assert len(res.df) >= 1
        assert (res.df["icr_label"] == "Debt Free").all()
        assert "DEBTFREE01" in set(res.df["company_id"])

    def test_pe_max_filter(self, populated_screener_db):
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        from src.screener.engine import ScreenerPreset

        pe_cap = ScreenerPreset(
            name="pe_test",
            label="P/E cap",
            description="",
            filters=[
                ScreenerFilter(
                    metric="pe_ratio",
                    threshold=20.0,
                    direction="max",
                    column="pe_ratio",
                )
            ],
        )
        res = apply_filters(df, pe_cap, cfg)
        pe_vals = res.df["pe_ratio"].dropna()
        assert (pe_vals <= 20.0 + 1e-9).all()


# ---------------------------------------------------------------------------
# Preset behaviour
# ---------------------------------------------------------------------------
class TestPresets:
    def test_all_presets_return_dataframe_with_rank(self, populated_screener_db):
        cfg = load_config()
        for name in cfg.presets:
            res = run_screener(cfg.preset(name), db_path=populated_screener_db)
            assert isinstance(res.df, pd.DataFrame)
            if len(res.df) > 0:
                assert "rank" in res.df.columns
                assert res.df["rank"].iloc[0] == 1
                # Sorted by composite descending
                assert res.df["composite_quality_score"].is_monotonic_decreasing or (
                    res.df["composite_quality_score"].fillna(-1).is_monotonic_decreasing
                )

    def test_quality_compounders_count_reasonable(self, populated_screener_db):
        cfg = load_config()
        res = run_screener(cfg.preset("quality_compounders"), db_path=populated_screener_db)
        # Expect 15-50 companies
        assert 5 <= res.rows_out <= 60, f"quality_compounders returned {res.rows_out}"

    def test_result_summary_string(self, populated_screener_db):
        cfg = load_config()
        res = run_screener(cfg.preset("quality_compounders"), db_path=populated_screener_db)
        s = res.summary()
        assert "Quality Compounders" in s
        assert "filters applied" in s


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------
class TestCustomFilters:
    def test_custom_filter_overrides_preset(self, populated_screener_db):
        cfg = load_config()
        # Run compounders but with an insanely high ROE threshold — few/no companies
        res = run_screener(
            cfg.preset("quality_compounders"),
            db_path=populated_screener_db,
            custom_filters={"roe_pct": 100.0},
        )
        assert res.rows_out == 0

    def test_custom_filter_unknown_metric_raises(self, populated_screener_db):
        cfg = load_config()
        with pytest.raises(ValueError):
            run_screener(
                cfg.preset("quality_compounders"),
                db_path=populated_screener_db,
                custom_filters={"nonexistent_metric": 1.0},
            )


# ---------------------------------------------------------------------------
# Fixture: builds a fresh DB (reuses logic from populate_ratios tests)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def populated_screener_db(tmp_path_factory):
    """Build a fresh DB with synthetic data + populated ratios (no bank carve-out needed)."""
    import os

    tmp = tmp_path_factory.mktemp("screener_db")
    db_path = tmp / "test.db"
    raw_dir = tmp / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    old_env = os.environ.get("NIFTY100_DB_PATH")
    os.environ["NIFTY100_DB_PATH"] = str(db_path)
    try:
        from scripts.generate_data import generate_all
        from scripts.populate_ratios import populate

        from src.etl.database import init_schema, load_dataframe, reset_tables
        from src.etl.loader import load_dataset
        from src.etl.normalizers import normalize_ticker, normalize_year_safe

        generate_all(raw_dir)

        # Load order from the kpi tests
        load_order = (
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
        import pandas as pd

        def _post_process(df: pd.DataFrame, name: str) -> pd.DataFrame:
            if name == "documents" and "Year" in df.columns:
                df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
            elif name == "market_cap" and "year" in df.columns:
                df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
            elif name == "analysis" and "id" in df.columns and "company_id" in df.columns:
                df = df.drop(columns=["id"])
            return df

        init_schema(str(db_path))
        reset_tables(db_path=str(db_path))
        for name in load_order:
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
        populate(reset=True)
        yield str(db_path)
    finally:
        if old_env is None:
            os.environ.pop("NIFTY100_DB_PATH", None)
        else:
            os.environ["NIFTY100_DB_PATH"] = old_env
