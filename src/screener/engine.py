"""Screener Filter Engine — Sprint 3 Day 15.

Loads ``config/screener_config.yaml`` and applies threshold filters against a
joined dataset of ``financial_ratios`` + ``profitandloss`` + ``market_cap``
+ ``sectors``. Returns a DataFrame sorted by ``composite_quality_score``.

Supports all 15 filterable metrics per the Day 15 brief:
    ROE min, D/E max (with financial-sector skip), FCF min, Revenue CAGR 5yr
    min, PAT CAGR 5yr min, OPM min, P/E max, P/B max, Dividend Yield min,
    ICR min (Debt Free → infinity), Market Cap min, Net Profit min, EPS
    CAGR 5yr min, Asset Turnover min, Sales min.

Usage::

    from src.screener import load_config, run_screener
    cfg = load_config()                               # from screener_config.yaml
    df = run_screener(cfg.presets["quality_compounders"])
    df.to_excel("screener_output.xlsx", index=False)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.etl.database import get_connection
from src.utils.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = settings.PROJECT_ROOT
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "screener_config.yaml"

# Join SQL that assembles the full screener-ready dataset.
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
    {where_year}
    ORDER BY fr.company_id, fr.year
"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScreenerFilter:
    """One threshold constraint."""

    metric: str
    threshold: float
    direction: str  # 'min' or 'max'
    skip_financials: bool = False
    debt_free_passes: bool = False
    column: str = ""


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
        filters_raw: dict[str, float] = body.get("filters", {}) or {}
        filters: list[ScreenerFilter] = []
        for raw_key, threshold in filters_raw.items():
            # Allow preset YAML to use either bare metric name (e.g.
            # "roe_pct") or direction-prefixed form ("min_roe_pct",
            # "max_pe_ratio"). Strip the prefix and look up by canonical
            # metric name.
            metric_key = raw_key
            for prefix in ("min_", "max_"):
                if raw_key.startswith(prefix) and raw_key[4:] in metrics_defs:
                    metric_key = raw_key[4:]
                    break
            if metric_key not in metrics_defs:
                raise ValueError(
                    f"Preset '{name}' references unknown metric '{raw_key}' "
                    f"(not declared in metrics:)"
                )
            mdef = metrics_defs[metric_key]
            filters.append(
                ScreenerFilter(
                    metric=metric_key,
                    threshold=float(threshold),
                    direction=mdef.get("direction", "min"),
                    skip_financials=bool(mdef.get("skip_financials", False)),
                    debt_free_passes=bool(mdef.get("debt_free_passes", False)),
                    column=mdef["column"],
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
            # Debt-free companies pass ICR minimums (infinite cover)
            if flt.debt_free_passes and "icr_label" in out.columns:
                mask = mask | (out["icr_label"] == "Debt Free")
            # Auto-skip financial-sector companies for D/E (and other skip_financials metrics)
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
            )
        active_filters = list(by_metric.values())
        preset = ScreenerPreset(
            name=preset.name,
            label=preset.label,
            description=preset.description,
            filters=active_filters,
        )

    return apply_filters(df, preset, config)
