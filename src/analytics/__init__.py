"""Nifty 100 Financial Intelligence Platform — Analytics Package.

Modules:
    ratios         — Profitability ratio primitives (Sprint 2, Day 08).
    leverage       — Leverage & efficiency ratios (Sprint 2, Day 09).
    cagr           — CAGR engine (Sprint 2, Day 10).
    cashflow_kpis  — Cash-flow quality KPIs (Sprint 2, Day 11).
"""

from src.analytics.leverage import (
    HIGH_LEVERAGE_DE_THRESHOLD,
    ICR_DEBT_FREE_LABEL,
    ICR_WARNING_THRESHOLD,
    LeverageRatios,
    asset_turnover,
    compute_leverage_ratios,
    debt_to_equity,
    high_leverage_flag,
    icr_display_label,
    icr_warning_flag,
    interest_coverage_ratio,
    net_debt,
)
from src.analytics.ratios import (
    FINANCIAL_SECTOR_KEYWORDS,
    OPM_CROSSCHECK_TOLERANCE,
    ProfitabilityRatios,
    compute_profitability_ratios,
    ebit,
    ebit_margin,
    is_financial_sector,
    net_profit_margin,
    operating_profit_margin,
    return_on_assets,
    return_on_capital_employed,
    return_on_equity,
)

__all__ = [
    "FINANCIAL_SECTOR_KEYWORDS",
    "HIGH_LEVERAGE_DE_THRESHOLD",
    "ICR_DEBT_FREE_LABEL",
    "ICR_WARNING_THRESHOLD",
    "OPM_CROSSCHECK_TOLERANCE",
    "LeverageRatios",
    "ProfitabilityRatios",
    "asset_turnover",
    "compute_leverage_ratios",
    "compute_profitability_ratios",
    "debt_to_equity",
    "ebit",
    "ebit_margin",
    "high_leverage_flag",
    "icr_display_label",
    "icr_warning_flag",
    "interest_coverage_ratio",
    "is_financial_sector",
    "net_debt",
    "net_profit_margin",
    "operating_profit_margin",
    "return_on_assets",
    "return_on_capital_employed",
    "return_on_equity",
]
