"""Unit tests for Sprint 3 Days 15-16 — Screener Filter Engine.

Covers:
    * YAML config loading with all 6 spec presets
    * Filter metrics: ROE min, D/E max (financials skipped), FCF min/flag,
      revenue/PAT/EPS CAGR 5yr min, OPM min, P/E max, P/B max, Div Yield min,
      Div Payout max, ICR min (Debt Free passes), Market Cap min, Net Profit
      min, Asset Turnover min, Sales min, CFO/PAT min, D/E eq-0 (with
      epsilon tolerance, debt-free passes), YoY D/E decline flag
    * Sorted by composite_quality_score desc with rank column
    * Custom threshold overrides
    * Error handling for unknown preset / metric names
    * Day 16 spec §25 acceptance: every preset returns 5-50 companies
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
SPEC_PRESET_NAMES = (
    "quality_compounder",
    "value_pick",
    "growth_accelerator",
    "dividend_champion",
    "debt_free_blue_chip",
    "turnaround_watch",
)


class TestConfigLoad:
    def test_default_config_loads_all_six_spec_presets(self):
        cfg = load_config()
        for name in SPEC_PRESET_NAMES:
            assert name in cfg.presets, f"missing spec preset {name}"
        assert len(cfg.presets) == 6

    def test_core_metrics_declared(self):
        cfg = load_config()
        required = {
            "roe_pct",
            "debt_to_equity",
            "debt_to_equity_zero",  # D/E=0 (eq)
            "fcf_cr",
            "fcf_positive",  # boolean flag
            "revenue_cagr_5yr_pct",
            "revenue_cagr_3yr_pct",
            "pat_cagr_5yr_pct",
            "eps_cagr_5yr_pct",
            "opm_pct",
            "pe_ratio",
            "pb_ratio",
            "dividend_yield_pct",
            "dividend_payout_ratio_pct",
            "icr",
            "market_cap_cr",
            "net_profit_cr",
            "asset_turnover",
            "sales_cr",
            "cfo_pat_ratio",
            "de_yoy_declining",  # boolean flag
        }
        assert required.issubset(set(cfg.metrics.keys()))

    def test_preset_filters_are_screener_filter_objects(self):
        cfg = load_config()
        for preset in cfg.presets.values():
            assert preset.label
            for f in preset.filters:
                assert isinstance(f, ScreenerFilter)
                assert f.direction in ("min", "max", "eq", "flag")
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

    def test_dataset_has_all_metric_columns(self, populated_screener_db):
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        cfg = load_config()
        for metric, mdef in cfg.metrics.items():
            assert mdef["column"] in df.columns, f"missing column for {metric}: {mdef['column']}"

    def test_derived_yoy_columns_present(self, populated_screener_db):
        """Day 16: prior-year D/E and YoY decline flag must exist."""
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        assert "prev_debt_to_equity" in df.columns
        assert "de_yoy_change" in df.columns
        assert "de_yoy_declining" in df.columns
        assert "fcf_positive" in df.columns
        assert "fcf_yield_pct" in df.columns
        assert "valuation_bucket" in df.columns

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
        from src.screener.engine import ScreenerPreset

        only_roe = ScreenerPreset(
            name="roe_test",
            label="ROE test",
            description="",
            filters=[
                ScreenerFilter(metric="roe_pct", threshold=15.0, direction="min", column="roe_pct")
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
        is_fin = (
            res.df["broad_sector"]
            .fillna("")
            .apply(lambda s: any(kw in s.lower() for kw in cfg.financial_keywords))
        )
        assert is_fin.any(), "Expected financial-sector companies to pass D/E filter via skip"

    def test_debt_free_passes_icr_min(self, populated_screener_db):
        """Any company whose icr_label == 'Debt Free' must pass even an
        absurdly high ICR minimum (their cover is effectively infinite)."""
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
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
                    threshold=999.0,
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
                    metric="pe_ratio", threshold=20.0, direction="max", column="pe_ratio"
                )
            ],
        )
        res = apply_filters(df, pe_cap, cfg)
        pe_vals = res.df["pe_ratio"].dropna()
        assert (pe_vals <= 20.0 + 1e-9).all()

    def test_eq_de_zero_uses_epsilon_tolerance(self, populated_screener_db):
        """Day 16: D/E=0 filter uses eq_epsilon tolerance. Near-zero firms pass."""
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        from src.screener.engine import ScreenerPreset

        strict_de_zero = ScreenerPreset(
            name="de0",
            label="D/E zero",
            description="",
            filters=[
                ScreenerFilter(
                    metric="debt_to_equity_zero",
                    threshold=0.0,
                    direction="eq",
                    column="debt_to_equity",
                    eq_epsilon=0.01,  # extremely tight
                )
            ],
        )
        res_tight = apply_filters(df, strict_de_zero, cfg)
        # Synthetic data might have 0 or 1 firms at D/E <= 0.01
        for _, row in res_tight.df.iterrows():
            assert row["debt_to_equity"] <= 0.01 + 1e-9

        loose_de_zero = ScreenerPreset(
            name="de0_loose",
            label="D/E zero loose",
            description="",
            filters=[
                ScreenerFilter(
                    metric="debt_to_equity_zero",
                    threshold=0.0,
                    direction="eq",
                    column="debt_to_equity",
                    eq_epsilon=0.5,
                )
            ],
        )
        res_loose = apply_filters(df, loose_de_zero, cfg)
        assert len(res_loose.df) >= len(res_tight.df)
        for _, row in res_loose.df.iterrows():
            assert row["debt_to_equity"] <= 0.5 + 1e-9

    def test_flag_fcf_positive_passes_only_positive_fcf(self, populated_screener_db):
        """Day 16: flag direction keeps only rows where col > 0."""
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        from src.screener.engine import ScreenerPreset

        fcf_pos = ScreenerPreset(
            name="fcf_flag",
            label="FCF positive",
            description="",
            filters=[
                ScreenerFilter(
                    metric="fcf_positive",
                    threshold=0.0,
                    direction="flag",
                    column="fcf_positive",
                )
            ],
        )
        res = apply_filters(df, fcf_pos, cfg)
        # All surviving rows must have FCF > 0
        assert (res.df["fcf_cr"] > 0).all()

    def test_flag_de_yoy_declining(self, populated_screener_db):
        """Day 16: de_yoy_declining flag keeps only firms where D/E decreased YoY."""
        cfg = load_config()
        df = load_screener_dataset(db_path=populated_screener_db, latest_year_only=True)
        from src.screener.engine import ScreenerPreset

        de_decl = ScreenerPreset(
            name="de_decl",
            label="D/E declining",
            description="",
            filters=[
                ScreenerFilter(
                    metric="de_yoy_declining",
                    threshold=0.0,
                    direction="flag",
                    column="de_yoy_declining",
                )
            ],
        )
        res = apply_filters(df, de_decl, cfg)
        # Every survivor must have negative de_yoy_change (declining)
        assert (res.df["de_yoy_change"] < 0).all()


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
                assert res.df["composite_quality_score"].fillna(-1).is_monotonic_decreasing

    @pytest.mark.parametrize("preset_name", list(SPEC_PRESET_NAMES))
    def test_each_preset_returns_5_to_50_companies(self, populated_screener_db, preset_name):
        """Day 16 spec: verify every preset returns between 5 and 50 companies."""
        cfg = load_config()
        res = run_screener(cfg.preset(preset_name), db_path=populated_screener_db)
        assert 5 <= res.rows_out <= 50, (
            f"Preset '{preset_name}' returned {res.rows_out} companies " f"(expected 5-50)"
        )

    def test_quality_compounder_criteria_enforced(self, populated_screener_db):
        """Quality Compounder: ROE>15, D/E<1, FCF>0, Rev CAGR 5y>10 — every survivor must pass."""
        cfg = load_config()
        res = run_screener(cfg.preset("quality_compounder"), db_path=populated_screener_db)
        assert len(res.df) >= 5
        assert (res.df["roe_pct"] >= 15 - 1e-9).all()
        # Non-financials must satisfy D/E <= 1 (financials are auto-passed)
        non_fin = (
            ~res.df["broad_sector"]
            .fillna("")
            .str.lower()
            .apply(lambda s: any(k in s for k in cfg.financial_keywords))
        )
        assert (res.df.loc[non_fin, "debt_to_equity"] <= 1.0 + 1e-9).all()
        assert (res.df["fcf_cr"] > 0).all()
        assert (res.df["revenue_cagr_5yr"] >= 10 - 1e-9).all()

    def test_value_pick_criteria_enforced(self, populated_screener_db):
        """Value Pick: P/E<20, P/B<3, D/E<2, Div Yield>1%."""
        cfg = load_config()
        res = run_screener(cfg.preset("value_pick"), db_path=populated_screener_db)
        assert (res.df["pe_ratio"].dropna() <= 20 + 1e-9).all()
        assert (res.df["pb_ratio"].dropna() <= 3 + 1e-9).all()
        non_fin = (
            ~res.df["broad_sector"]
            .fillna("")
            .str.lower()
            .apply(lambda s: any(k in s for k in cfg.financial_keywords))
        )
        assert (res.df.loc[non_fin, "debt_to_equity"] <= 2.0 + 1e-9).all()
        assert (res.df["dividend_yield_pct"].dropna() >= 1 - 1e-9).all()

    def test_growth_accelerator_criteria_enforced(self, populated_screener_db):
        """Growth Accelerator: PAT CAGR 5y>20, Rev CAGR 5y>15, D/E<2."""
        cfg = load_config()
        res = run_screener(cfg.preset("growth_accelerator"), db_path=populated_screener_db)
        assert (res.df["pat_cagr_5yr"] >= 20 - 1e-9).all()
        assert (res.df["revenue_cagr_5yr"] >= 15 - 1e-9).all()
        non_fin = (
            ~res.df["broad_sector"]
            .fillna("")
            .str.lower()
            .apply(lambda s: any(k in s for k in cfg.financial_keywords))
        )
        assert (res.df.loc[non_fin, "debt_to_equity"] <= 2.0 + 1e-9).all()

    def test_dividend_champion_criteria_enforced(self, populated_screener_db):
        """Dividend Champion: Yield>2%, Payout<80%, FCF>0."""
        cfg = load_config()
        res = run_screener(cfg.preset("dividend_champion"), db_path=populated_screener_db)
        assert (res.df["dividend_yield_pct"] >= 2 - 1e-9).all()
        assert (res.df["dividend_payout_ratio_pct"] <= 80 + 1e-9).all()
        assert (res.df["fcf_cr"] > 0).all()

    def test_debt_free_blue_chip_criteria_enforced(self, populated_screener_db):
        """Debt-Free Blue Chip: D/E<=epsilon (~0), ROE>12, Sales>5000Cr.

        Insurers can legitimately have very low D/E (policyholder reserves
        aren't deposit leverage); but deposit-taking banks/NBFCs must be
        excluded since their leverage is structural.
        """
        cfg = load_config()
        res = run_screener(cfg.preset("debt_free_blue_chip"), db_path=populated_screener_db)
        epsilon = 0.20  # must match metric eq_epsilon in config
        for _, row in res.df.iterrows():
            sub = str(row.get("sub_sector", "")).lower()
            broad = str(row["broad_sector"]).lower()
            is_bank_nbfc = (
                "bank" in sub or "nbfc" in sub or "consumer finance" in sub or "finance" in broad
            ) and "insurance" not in sub
            assert not is_bank_nbfc, (
                f"Bank/NBFC '{row['company_id']}' (sector={row['broad_sector']}/"
                f"{row.get('sub_sector','')}) in debt-free preset with D/E={row['debt_to_equity']}"
            )
            assert row["debt_to_equity"] <= epsilon + 1e-9
            assert row["roe_pct"] >= 12 - 1e-9
            assert row["sales"] >= 5000 - 1e-9

    def test_turnaround_watch_criteria_enforced(self, populated_screener_db):
        """Turnaround Watch: Rev CAGR 3y>10, FCF positive, D/E declining YoY."""
        cfg = load_config()
        res = run_screener(cfg.preset("turnaround_watch"), db_path=populated_screener_db)
        assert (res.df["revenue_cagr_3yr"] >= 10 - 1e-9).all()
        assert (res.df["fcf_cr"] > 0).all()
        assert (res.df["de_yoy_change"] < 0).all()

    def test_result_summary_string(self, populated_screener_db):
        cfg = load_config()
        res = run_screener(cfg.preset("quality_compounder"), db_path=populated_screener_db)
        s = res.summary()
        assert "Quality Compounder" in s
        assert "filters applied" in s


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------
class TestCustomFilters:
    def test_custom_filter_overrides_preset(self, populated_screener_db):
        cfg = load_config()
        res = run_screener(
            cfg.preset("quality_compounder"),
            db_path=populated_screener_db,
            custom_filters={"roe_pct": 100.0},
        )
        assert res.rows_out == 0

    def test_custom_filter_unknown_metric_raises(self, populated_screener_db):
        cfg = load_config()
        with pytest.raises(ValueError):
            run_screener(
                cfg.preset("quality_compounder"),
                db_path=populated_screener_db,
                custom_filters={"nonexistent_metric": 1.0},
            )


# ---------------------------------------------------------------------------
# Fixture: builds a fresh DB (reuses logic from populate_ratios tests)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def populated_screener_db(tmp_path_factory):
    """Build a fresh DB with synthetic data + populated ratios."""
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
