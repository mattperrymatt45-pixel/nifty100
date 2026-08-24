"""
Nifty 100 Financial Intelligence Platform — Profitability Ratio Engine.

Implements Day 08 profitability KPIs per spec §13 (KPI Reference):

    * Net Profit Margin (NPM)
    * Operating Profit Margin (OPM) — with source cross-check
    * EBIT Margin
    * Return on Equity (ROE)
    * Return on Capital Employed (ROCE) — with bank/NBFC carve-out flag
    * Return on Assets (ROA)

All ratios are pure functions of their inputs so they are trivially unit-testable.
Denominator-zero and negative-equity edge cases return ``None`` per the spec's
edge-case column; callers can render ``None`` as "NM" (not meaningful) in UIs.

All monetary inputs are assumed to be in ₹ Crore and outputs are percentages
unless otherwise noted.

Usage:
    from src.analytics.ratios import compute_profitability_ratios
    result = compute_profitability_ratios(
        sales=1000.0, operating_profit=250.0, opm_percentage=25.0,
        depreciation=40.0, net_profit=150.0,
        equity_capital=100.0, reserves=600.0, borrowings=200.0,
        total_assets=1500.0,
        broad_sector="Information Technology",
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Logging — cross-check mismatches are logged at WARNING level.
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OPM cross-check tolerance.  DQ-05 uses 1.0 percentage point; the ratio engine
# logs at WARNING when the recomputed OPM deviates from source by more than
# this value but still returns the computed value (per spec DQ-05 action).
# ---------------------------------------------------------------------------
OPM_CROSSCHECK_TOLERANCE: float = 1.0  # percentage points

# ---------------------------------------------------------------------------
# Broad-sector keywords that identify Financials companies (banks / NBFCs).
# These mirror the keywords used in src.etl.validation for DQ-06.
# ---------------------------------------------------------------------------
FINANCIAL_SECTOR_KEYWORDS: tuple[str, ...] = ("bank", "nbfc", "finance", "financial")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProfitabilityRatios:
    """
    Immutable result of :func:`compute_profitability_ratios`.

    Attributes:
        net_profit_margin_pct:        NPM  = net_profit / sales x 100
        operating_profit_margin_pct:  OPM  = operating_profit / sales x 100
        ebit_margin_pct:              (operating_profit - depreciation) / sales x 100
        return_on_equity_pct:         ROE  = net_profit / (equity + reserves) x 100
        roce_pct:                     ROCE = EBIT / capital employed x 100
        return_on_assets_pct:         ROA  = net_profit / total_assets x 100
        opm_crosscheck_delta:         Absolute delta between computed OPM and
                                      source ``opm_percentage`` (None if no
                                      source value supplied).
        opm_crosscheck_flag:          True when delta > ``OPM_CROSSCHECK_TOLERANCE``.
        is_financial_sector:          True when ``broad_sector`` matches a
                                      financial keyword (ROCE should be
                                      interpreted as sector-relative, not absolute).
    """

    net_profit_margin_pct: float | None
    operating_profit_margin_pct: float | None
    ebit_margin_pct: float | None
    return_on_equity_pct: float | None
    roce_pct: float | None
    return_on_assets_pct: float | None
    opm_crosscheck_delta: float | None = None
    opm_crosscheck_flag: bool = False
    is_financial_sector: bool = False
    warnings: list[str] = field(default_factory=tuple)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # dataclass frozen=True still allows object.__setattr__; coerce list->tuple
        if isinstance(self.warnings, list):
            object.__setattr__(self, "warnings", tuple(self.warnings))


# ---------------------------------------------------------------------------
# Sector helpers
# ---------------------------------------------------------------------------
def is_financial_sector(broad_sector: str | None) -> bool:
    """
    Return True if the ``broad_sector`` string indicates a bank / NBFC /
    financial-services company.  Matching is case-insensitive and substring-based.

    Args:
        broad_sector: Sector label from ``sectors.broad_sector``.

    Returns:
        True if any :data:`FINANCIAL_SECTOR_KEYWORDS` substring matches.
    """
    if not broad_sector:
        return False
    lowered = broad_sector.lower()
    return any(kw in lowered for kw in FINANCIAL_SECTOR_KEYWORDS)


# ---------------------------------------------------------------------------
# Individual ratio primitives
# ---------------------------------------------------------------------------
def net_profit_margin(net_profit: float, sales: float) -> float | None:
    """
    Compute Net Profit Margin (NPM) as a percentage.

    Formula:
        NPM = net_profit / sales x 100

    Edge cases:
        * Returns ``None`` if ``sales`` is zero (per spec §13).
        * Negative NPM is allowed (loss-making companies).
    """
    if sales == 0:
        return None
    return (net_profit / sales) * 100.0


def operating_profit_margin(operating_profit: float, sales: float) -> float | None:
    """
    Compute Operating Profit Margin (OPM) as a percentage.

    Formula:
        OPM = operating_profit / sales x 100

    Edge cases:
        * Returns ``None`` if ``sales`` is zero.
        * Negative OPM is allowed.
    """
    if sales == 0:
        return None
    return (operating_profit / sales) * 100.0


def ebit(operating_profit: float, depreciation: float) -> float:
    """
    Compute Earnings Before Interest and Tax (EBIT) from EBITDA and D&A.

    Per spec §13: EBIT Margin = (operating_profit - depreciation) / sales x 100
    "Excludes other_income to get core ops only", so we use core operating
    EBITDA and subtract depreciation.  This is the standard Screener.in-style
    calculation used across Indian financial datasets.

    Args:
        operating_profit: EBITDA from ``profitandloss.operating_profit``.
        depreciation:     D&A from ``profitandloss.depreciation`` (treated as 0
                          if None/NaN, since depreciation is sometimes missing
                          for financials).

    Returns:
        EBIT in ₹ Crore.
    """
    _dep = depreciation if depreciation is not None else 0.0
    return operating_profit - _dep


def ebit_margin(operating_profit: float, depreciation: float, sales: float) -> float | None:
    """
    Compute EBIT Margin as a percentage (core operations, excludes other income).

    Formula:
        EBIT Margin = (operating_profit - depreciation) / sales x 100

    Edge cases:
        * Returns ``None`` if ``sales`` is zero.
    """
    if sales == 0:
        return None
    return (ebit(operating_profit, depreciation) / sales) * 100.0


def return_on_equity(
    net_profit: float,
    equity_capital: float,
    reserves: float | None,
) -> float | None:
    """
    Compute Return on Equity (ROE) as a percentage.

    Formula:
        ROE = net_profit / (equity_capital + reserves) x 100

    Edge cases (per spec §13):
        * Returns ``None`` if equity + reserves ≤ 0 (negative book value).
        * Treats ``reserves`` of None as 0.
    """
    _reserves = reserves if reserves is not None else 0.0
    equity = equity_capital + _reserves
    if equity <= 0:
        return None
    return (net_profit / equity) * 100.0


def _capital_employed(
    equity_capital: float,
    reserves: float | None,
    borrowings: float | None,
) -> float:
    """
    Compute capital employed = equity + reserves + borrowings.
    Missing reserves/borrowings are treated as zero.
    """
    _reserves = reserves if reserves is not None else 0.0
    _borrowings = borrowings if borrowings is not None else 0.0
    return equity_capital + _reserves + _borrowings


def return_on_capital_employed(
    operating_profit: float,
    depreciation: float,
    equity_capital: float,
    reserves: float | None,
    borrowings: float | None,
) -> float | None:
    """
    Compute Return on Capital Employed (ROCE) as a percentage.

    Formula:
        ROCE = EBIT / (equity_capital + reserves + borrowings) x 100
        EBIT = operating_profit - depreciation

    Edge cases:
        * Returns ``None`` if capital employed ≤ 0.
        * Missing ``reserves`` or ``borrowings`` are treated as 0.
        * For banks / NBFCs the absolute value is structurally low; callers
          should check :func:`is_financial_sector` and use a sector-relative
          benchmark instead (Day 13 specialisation).
    """
    ce = _capital_employed(equity_capital, reserves, borrowings)
    if ce <= 0:
        return None
    e = ebit(operating_profit, depreciation)
    return (e / ce) * 100.0


def return_on_assets(net_profit: float, total_assets: float) -> float | None:
    """
    Compute Return on Assets (ROA) as a percentage.

    Formula:
        ROA = net_profit / total_assets x 100

    Edge cases (per spec §13):
        * Returns ``None`` if ``total_assets`` is zero (schema CHECK constraint
          makes this impossible in DB, but the guard exists for unit tests).
    """
    if total_assets == 0:
        return None
    return (net_profit / total_assets) * 100.0


# ---------------------------------------------------------------------------
# High-level convenience
# ---------------------------------------------------------------------------
def compute_profitability_ratios(
    *,
    sales: float,
    operating_profit: float,
    opm_percentage: float | None = None,
    depreciation: float = 0.0,
    other_income: float = 0.0,
    net_profit: float,
    equity_capital: float,
    reserves: float | None = None,
    borrowings: float | None = None,
    total_assets: float,
    broad_sector: str | None = None,
    company_id: str | None = None,
    year: str | None = None,
) -> ProfitabilityRatios:
    """
    Compute all six Day-08 profitability ratios for a single company-year,
    performing the OPM source cross-check and sector classification.

    All keyword arguments are positional-only-by-convention (enforced via ``*``)
    to reduce the risk of silent argument mis-ordering.

    Args:
        sales:              Revenue from P&L (₹ Crore).
        operating_profit:   EBITDA from P&L (₹ Crore).
        opm_percentage:     Source OPM % from P&L (for cross-check); may be None.
        depreciation:       D&A from P&L (₹ Crore); defaults to 0.
        other_income:       Other income (unused by core ratios today; reserved
                            for later ICR / adjusted ROCE work).
        net_profit:         PAT from P&L (₹ Crore).
        equity_capital:     Equity share capital from B/S (₹ Crore).
        reserves:           Reserves & surplus from B/S (₹ Crore); None treated as 0.
        borrowings:         Total borrowings from B/S (₹ Crore); None treated as 0.
        total_assets:       Total assets from B/S (₹ Crore).
        broad_sector:       ``sectors.broad_sector`` label used to detect
                            financial-sector companies.
        company_id:         Optional ticker — included only for log context.
        year:               Optional year label — included only for log context.

    Returns:
        A :class:`ProfitabilityRatios` frozen dataclass with every ratio and
        flag populated.
    """
    warnings: list[str] = []

    npm = net_profit_margin(net_profit, sales)
    opm = operating_profit_margin(operating_profit, sales)
    em = ebit_margin(operating_profit, depreciation, sales)
    roe = return_on_equity(net_profit, equity_capital, reserves)
    roce = return_on_capital_employed(
        operating_profit, depreciation, equity_capital, reserves, borrowings
    )
    roa = return_on_assets(net_profit, total_assets)

    # ---- OPM cross-check against source ------------------------------------
    opm_delta: float | None = None
    opm_flag = False
    if opm is not None and opm_percentage is not None:
        opm_delta = abs(opm - opm_percentage)
        if opm_delta > OPM_CROSSCHECK_TOLERANCE:
            opm_flag = True
            msg = (
                f"OPM cross-check mismatch for {company_id or '?'} {year or '?'}: "
                f"computed={opm:.2f}% source={opm_percentage:.2f}% "
                f"delta={opm_delta:.2f}pp (>{OPM_CROSSCHECK_TOLERANCE}pp)"
            )
            warnings.append(msg)
            logger.warning(msg)

    # ---- Sector classification ---------------------------------------------
    fin = is_financial_sector(broad_sector)
    if fin and roce is not None:
        # Banks/NBFCs have structurally low ROCE due to high borrowings (deposits).
        # We still compute the absolute value for completeness, but flag it so
        # downstream (Day 13) can substitute a NIM/ROA-based sector benchmark.
        logger.debug(
            "Financial sector detected for %s %s — "
            "absolute ROCE=%.2f%% will be sector-relative interpreted on Day 13.",
            company_id or "?",
            year or "?",
            roce,
        )

    return ProfitabilityRatios(
        net_profit_margin_pct=npm,
        operating_profit_margin_pct=opm,
        ebit_margin_pct=em,
        return_on_equity_pct=roe,
        roce_pct=roce,
        return_on_assets_pct=roa,
        opm_crosscheck_delta=opm_delta,
        opm_crosscheck_flag=opm_flag,
        is_financial_sector=fin,
        warnings=warnings,
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
