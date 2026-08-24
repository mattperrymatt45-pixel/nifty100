"""
Nifty 100 Financial Intelligence Platform — Analytics Package.

Modules:
    ratios    — Profitability ratio primitives (Sprint 2, Day 08).
    cagr      — CAGR engine (Sprint 2, Day 10).
    cashflow_kpis — Cash-flow quality KPIs (Sprint 2, Day 11).
"""

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
    "OPM_CROSSCHECK_TOLERANCE",
    "ProfitabilityRatios",
    "compute_profitability_ratios",
    "ebit",
    "ebit_margin",
    "is_financial_sector",
    "net_profit_margin",
    "operating_profit_margin",
    "return_on_assets",
    "return_on_capital_employed",
    "return_on_equity",
]
