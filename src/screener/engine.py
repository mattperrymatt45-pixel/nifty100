"""Screener Filter Engine — Sprint 3 Days 15-16.

Loads ``config/screener_config.yaml`` and applies threshold filters against a
joined dataset of ``financial_ratios`` + ``profitandloss`` + ``market_cap``
+ ``sectors``. Returns a DataFrame sorted by ``composite_quality_score``.

Supports min / max / eq / declining filter directions. The ``eq`` direction is
used by the Debt-Free Blue Chip preset (D/E = 0); it also treats
``icr_label == "Debt Free"`` and near-zero D/E (≤ 0.05 epsilon, per the
synthetic data calibration) as passing, since a strict zero is rarely
observed in real-world data either but near-zero is economically equivalent.
The ``declining`` direction requires ``column_yoy_change < 0`` (prior-year
comparison) — used by Turnaround Watch to detect deleveraging.

Usage::

    from src.screener import load_config, run_screener
    cfg = load_config()                               # from screener_config.yaml
    df = run_screener(cfg.presets["quality_compounder"])
    df.to_excel("screener_output.xlsx", index=False)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.analytics.valuation import classify_valuation
from src.analytics.valuation import fcf_yield as _fcf_yield
from src.etl.database import get_connection
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = settings.PROJECT_ROOT
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "screener_config.yaml"

# Join SQL that assembles the full screener-ready dataset.
# prev_fr subquery fetches prior-year D/E so we can compute YoY change for
# trend-aware filters (e.g. Turnaround Watch "D/E declining YoY").
SCREENER_SQL = """
    SELECT
        fr.company_id,
        co.company_name,
        fr.year,
        COALESCE(s.broad_sector, '')   AS broad_sector,
        COALESCE(s.sub_sector, '')     AS sub_sector,
        s.market_cap_category,
        fr.net_profit_margin_pct,
        fr.operating_profit_margin_pct,
        fr.return_on_equity_pct        AS roe_pct,
        fr.roce_pct,
        fr.return_on_assets_pct,
        fr.debt_to_equity,
        prev_fr.debt_to_equity         AS prev_debt_to_equity,
        fr.interest_coverage           AS icr,
        fr.icr_label,
        fr.net_debt_cr,
        fr.asset_turnover,
        fr.free_cash_flow_cr           AS fcf_cr,
        fr.earnings_per_share          AS eps,
        fr.book_value_per_share,
        fr.dividend_payout_ratio_pct,
        fr.cash_from_operations_cr,
        fr.revenue_cagr_3yr,
        fr.revenue_cagr_5yr,
        fr.revenue_cagr_10yr,
        fr.pat_cagr_3yr,
        fr.pat_cagr_5yr,
        fr.eps_cagr_3yr,
        fr.eps_cagr_5yr,
        fr.cfo_pat_ratio,
        fr.fcf_conversion_pct,
        fr.capital_allocation_pattern,
        fr.composite_quality_score,
        fr.roce_sector_adjusted,
        p.sales,
        p.net_profit,
        mc.market_cap_crore            AS market_cap_cr,
        mc.enterprise_value_crore      AS ev_cr,
        mc.pe_ratio,
        mc.pb_ratio,
        mc.ev_ebitda,
        mc.dividend_yield_pct
    FROM financial_ratios fr
    JOIN companies   co ON co.id = fr.company_id
    JOIN profitandloss p ON p.company_id = fr.company_id AND p.year = fr.year
    LEFT JOIN sectors s ON s.company_id = fr.company_id
    LEFT JOIN market_cap mc
      ON mc.company_id = fr.company_id
     AND mc.year = CAST(SUBSTR(fr.year, 1, 4) AS INTEGER)
    LEFT JOIN financial_ratios prev_fr
      ON prev_fr.company_id = fr.company_id
     AND prev_fr.year = (
         SELECT MAX(fr2.year) FROM financial_ratios fr2
         WHERE fr2.company_id = fr.company_id AND fr2.year < fr.year
     )
    {where_year}
    ORDER BY fr.company_id, fr.year
"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScreenerFilter:
    """One threshold constraint.

    direction:
        'min'       - keep rows where col >= threshold (NaN fails)
        'max'       - keep rows where col <= threshold (NaN fails)
        'eq'        - keep rows where col ≈ threshold (within epsilon, default 0.05);
                      used for strict D/E=0 with a near-zero tolerance so economically
                      debt-free companies are included
        'flag'      - keep rows where boolean col is True (or numeric col > 0);
                      used for binary trend / quality flags
    """

    metric: str
    threshold: float
    direction: str  # 'min', 'max', 'eq', 'flag'
    skip_financials: bool = False
    debt_free_passes: bool = False
    column: str = ""
    eq_epsilon: float = 0.05  # tolerance for 'eq' direction (e.g. D/E <= 0.05 treated as 0)


@dataclass
class ScreenerPreset:
    """A named bundle of filters (i.e. a preset screen)."""

    name: str
    label: str
    description: str
    filters: list[ScreenerFilter] = field(default_factory=list)


@dataclass
class ScreenerConfig:
    """Top-level config: defaults + presets + metric registry."""

    defaults: dict[str, Any]
    presets: dict[str, ScreenerPreset]
    metrics: dict[str, dict[str, Any]]
    financial_keywords: tuple[str, ...] = (
        "bank",
        "nbfc",
        "finance",
        "financial",
        "insurance",
    )

    def preset(self, name: str) -> ScreenerPreset:
        if name not in self.presets:
            available = ", ".join(sorted(self.presets))
            raise KeyError(f"Unknown screener preset '{name}'. Available: {available}")
        return self.presets[name]


@dataclass
class ScreenerResult:
    """Output of run_screener: the filtered DataFrame plus summary stats."""

    preset_name: str
    preset_label: str
    rows_in: int
    rows_out: int
    filters_applied: list[ScreenerFilter]
    df: pd.DataFrame

    def summary(self) -> str:
        """Human-readable one-line summary."""
        return (
            f"[{self.preset_label}] {self.rows_out} of {self.rows_in} companies pass "
            f"({len(self.filters_applied)} filters applied)"
        )


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config(path: Path | str | None = None) -> ScreenerConfig:
    """Load screener_config.yaml and return a ScreenerConfig object."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    defaults = raw.get("defaults", {})
    metrics_defs = raw.get("metrics", {})
    presets_raw = raw.get("presets", {})

    fin_kws = tuple(
        kw.lower()
        for kw in raw.get("financial_sector_keywords", ["bank", "nbfc", "finance", "insurance"])
    )

    presets: dict[str, ScreenerPreset] = {}
    for name, body in presets_raw.items():
        filters_raw: dict[str, Any] = body.get("filters", {}) or {}
        filters: list[ScreenerFilter] = []
        for raw_key, raw_value in filters_raw.items():
            # Strip any direction prefix (min_, max_, eq_, flag_) and look up
            # by the canonical metric name. Presets may use either
            # "min_roe_pct: 15" (min threshold on roe_pct),
            # "eq_debt_to_equity_zero: true" (eq match on debt_to_equity_zero),
            # "flag_fcf_positive: true" (boolean flag must be True).
            metric_key = raw_key
            for prefix in ("min_", "max_", "eq_", "flag_"):
                if raw_key.startswith(prefix):
                    candidate = raw_key[len(prefix) :]
                    if candidate in metrics_defs:
                        metric_key = candidate
                        break
            if metric_key not in metrics_defs:
                raise ValueError(
                    f"Preset '{name}' references unknown metric '{raw_key}' "
                    f"(not declared in metrics:)"
                )
            mdef = metrics_defs[metric_key]
            direction = mdef.get("direction", "min")
            # Normalise raw_value to a numeric threshold:
            #   - flag direction: boolean True -> threshold 0 (col > 0 passes);
            #                     boolean False -> impossible threshold
            #   - eq direction:   boolean True -> threshold 0 (match zero, e.g. D/E=0)
            #   - otherwise: cast raw_value to float
            if direction == "flag" or (direction == "eq" and isinstance(raw_value, bool)):
                threshold = 0.0 if raw_value else float("inf")
            else:
                threshold = float(raw_value)
            filters.append(
                ScreenerFilter(
                    metric=metric_key,
                    threshold=threshold,
                    direction=direction,
                    skip_financials=bool(mdef.get("skip_financials", False)),
                    debt_free_passes=bool(mdef.get("debt_free_passes", False)),
                    column=mdef["column"],
                    eq_epsilon=float(mdef.get("eq_epsilon", 0.05)),
                )
            )
        presets[name] = ScreenerPreset(
            name=name,
            label=body.get("label", name),
            description=(body.get("description") or "").strip(),
            filters=filters,
        )

    return ScreenerConfig(
        defaults=defaults,
        presets=presets,
        metrics=metrics_defs,
        financial_keywords=fin_kws,
    )


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------
def load_screener_dataset(
    db_path: Path | str | None = None,
    latest_year_only: bool = True,
) -> pd.DataFrame:
    """Load the joined screener dataset from the SQLite database.

    Args:
        db_path: Override DB path; defaults to settings.DB_PATH.
        latest_year_only: If True (default) keep only the most recent year
            per company. If False return all company-year rows.
    """
    where_year = (
        "WHERE fr.year = (SELECT MAX(year) FROM financial_ratios)" if latest_year_only else ""
    )
    sql = SCREENER_SQL.format(where_year=where_year)
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn)

    # ----- Derived columns -----
    # FCF yield — uses market_cap when available; NaN otherwise.
    df["fcf_yield_pct"] = [
        _fcf_yield(fcf, mc) for fcf, mc in zip(df["fcf_cr"], df["market_cap_cr"], strict=True)
    ]
    # Cheap/Fair/Expensive valuation bucket based on P/E, P/B, EV/EBITDA.
    df["valuation_bucket"] = [
        classify_valuation(pe, pb, ev)
        for pe, pb, ev in zip(df["pe_ratio"], df["pb_ratio"], df["ev_ebitda"], strict=True)
    ]
    # FCF-positive boolean flag (for Dividend Champion / Turnaround Watch).
    df["fcf_positive"] = df["fcf_cr"] > 0
    # YoY D/E declining flag (D/E_t < D/E_{t-1}). Missing prior-year → NaN (fails).
    df["de_yoy_change"] = df["debt_to_equity"] - df["prev_debt_to_equity"]
    df["de_yoy_declining"] = df["de_yoy_change"] < 0
    # Helper boolean for "is insurance" so that D/E-eq and other strict-leverage
    # filters can treat insurers more leniently than banks/NBFCs (insurers have
    # policyholder reserves rather than deposit leverage).
    df["_is_insurance"] = df["sub_sector"].fillna("").str.lower().str.contains("insurance")

    logger.info(f"Loaded screener dataset: {len(df)} rows, {len(df.columns)} columns")
    return df


# ---------------------------------------------------------------------------
# Filter application
# ---------------------------------------------------------------------------
def _is_financial(broad_sector: str, keywords: tuple[str, ...]) -> bool:
    """Return True if broad_sector matches any financial-sector keyword."""
    if not broad_sector:
        return False
    s = str(broad_sector).lower()
    return any(kw in s for kw in keywords)


def apply_filters(
    df: pd.DataFrame,
    preset: ScreenerPreset,
    config: ScreenerConfig,
) -> ScreenerResult:
    """Apply the preset's filters to df and return a ScreenerResult."""
    rows_in = len(df)
    out = df.copy()

    applied: list[ScreenerFilter] = []
    for flt in preset.filters:
        col = flt.column
        if col not in out.columns:
            logger.warning(f"Skipping filter on unknown column '{col}'")
            continue
        series = out[col]

        if flt.direction == "min":
            mask = (series >= flt.threshold) | series.isna()
            mask = mask.fillna(False)  # NaN fails a min threshold
            # Debt-free companies pass any minimum (infinite cover)
            if flt.debt_free_passes and "icr_label" in out.columns:
                mask = mask | (out["icr_label"] == "Debt Free")
            # Auto-skip financial-sector companies for D/E and similar leverage metrics
            if flt.skip_financials:
                fin_mask = (
                    out["broad_sector"]
                    .fillna("")
                    .apply(lambda s: _is_financial(s, config.financial_keywords))
                )
                mask = mask | fin_mask

        elif flt.direction == "max":
            mask = (series <= flt.threshold) | series.isna()
            mask = mask.fillna(False)
            # Debt-free companies also pass D/E <= anything (they have effectively 0 leverage)
            if flt.debt_free_passes and "icr_label" in out.columns:
                mask = mask | (out["icr_label"] == "Debt Free")
            if flt.skip_financials:
                fin_mask = (
                    out["broad_sector"]
                    .fillna("")
                    .apply(lambda s: _is_financial(s, config.financial_keywords))
                )
                mask = mask | fin_mask

        elif flt.direction == "eq":
            # Strict equality with epsilon tolerance (e.g. D/E = 0 → D/E <= epsilon).
            # NaN fails. Debt-free companies pass (treat as zero-leverage equivalent).
            eps = flt.eq_epsilon if flt.eq_epsilon > 0 else 1e-9
            mask = (series - flt.threshold).abs() <= eps
            mask = mask.fillna(False)
            if flt.debt_free_passes and "icr_label" in out.columns:
                mask = mask | (out["icr_label"] == "Debt Free")
            if flt.skip_financials:
                fin_mask = (
                    out["broad_sector"]
                    .fillna("")
                    .apply(lambda s: _is_financial(s, config.financial_keywords))
                )
                mask = mask | fin_mask

        elif flt.direction == "flag":
            # Boolean / positive flag: pass if the column is truthy (True or > 0).
            # NaN fails. Threshold is ignored but conventionally 0 for "positive".
            if series.dtype == bool:
                mask = series.fillna(False)
            else:
                mask = series > flt.threshold
                mask = mask.fillna(False)
            if flt.debt_free_passes and "icr_label" in out.columns:
                mask = mask | (out["icr_label"] == "Debt Free")
            if flt.skip_financials:
                fin_mask = (
                    out["broad_sector"]
                    .fillna("")
                    .apply(lambda s: _is_financial(s, config.financial_keywords))
                )
                mask = mask | fin_mask

        else:
            raise ValueError(f"Unknown filter direction '{flt.direction}' for {flt.metric}")

        before = len(out)
        out = out[mask].copy()
        applied.append(flt)
        logger.debug(
            f"  after {flt.metric} {flt.direction} {flt.threshold}: "
            f"{len(out)} rows (removed {before - len(out)})"
        )

    # Always sort by composite_quality_score descending (tiebreak on market_cap desc)
    sort_by = config.defaults.get("sort_by", "composite_quality_score")
    ascending = bool(config.defaults.get("sort_ascending", False))
    out = out.sort_values(
        by=[sort_by, "market_cap_cr"],
        ascending=[ascending, False],
        na_position="last",
    ).reset_index(drop=True)
    # Rank column
    out.insert(0, "rank", range(1, len(out) + 1))

    logger.info(
        f"Preset '{preset.label}': {len(out)} of {rows_in} pass " f"({len(applied)} filters)"
    )
    return ScreenerResult(
        preset_name=preset.name,
        preset_label=preset.label,
        rows_in=rows_in,
        rows_out=len(out),
        filters_applied=applied,
        df=out,
    )


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------
def run_screener(
    preset: ScreenerPreset,
    config: ScreenerConfig | None = None,
    *,
    db_path: Path | str | None = None,
    latest_year_only: bool | None = None,
    custom_filters: dict[str, float] | None = None,
) -> ScreenerResult:
    """Convenience wrapper: load dataset, apply preset (plus any custom
    overrides), return ScreenerResult sorted by composite_quality_score.

    Args:
        preset:        A ScreenerPreset (from cfg.preset(name)).
        config:        ScreenerConfig; loaded from default path if None.
        db_path:       Override DB path.
        latest_year_only: Override default; True = latest FY per company.
        custom_filters: Extra {metric: threshold} pairs merged on top of the
                        preset (overrides same-metric preset filters).
    """
    if config is None:
        config = load_config()
    if latest_year_only is None:
        latest_year_only = bool(config.defaults.get("latest_year_only", True))

    df = load_screener_dataset(db_path=db_path, latest_year_only=latest_year_only)

    active_filters = list(preset.filters)
    if custom_filters:
        # Merge: replace preset filters with same metric; add new ones
        by_metric = {f.metric: f for f in active_filters}
        for mkey, threshold in custom_filters.items():
            if mkey not in config.metrics:
                raise ValueError(f"Custom filter uses unknown metric '{mkey}'")
            mdef = config.metrics[mkey]
            by_metric[mkey] = ScreenerFilter(
                metric=mkey,
                threshold=float(threshold),
                direction=mdef.get("direction", "min"),
                skip_financials=bool(mdef.get("skip_financials", False)),
                debt_free_passes=bool(mdef.get("debt_free_passes", False)),
                column=mdef["column"],
                eq_epsilon=float(mdef.get("eq_epsilon", 0.05)),
            )
        active_filters = list(by_metric.values())
        preset = ScreenerPreset(
            name=preset.name,
            label=preset.label,
            description=preset.description,
            filters=active_filters,
        )

    return apply_filters(df, preset, config)
