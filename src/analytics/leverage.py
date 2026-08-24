"""Nifty 100 Financial Intelligence Platform — Leverage & Efficiency Ratio Engine.

Implements Sprint 2 Day 09 KPIs per spec §13 (KPI Reference):

    * Debt-to-Equity (D/E)           — borrowings / (equity_capital + reserves)
    * Interest Coverage Ratio (ICR) — (operating_profit + other_income) / interest
    * Net Debt                       — borrowings - investments
    * Asset Turnover                 — sales / total_assets

Edge cases implemented per the spec edge-case column and the Day 09 brief:

    * D/E returns ``0`` (not None) for debt-free companies (borrowings = 0)
    * ``high_leverage_flag`` is True when D/E > 5 and the company is NOT in
      Financials (banks/NBFCs structurally run high D/E — see §28 benchmarks)
    * ICR returns ``None`` when interest = 0; ``icr_label`` is set to
      ``"Debt Free"`` in that case (per spec §13: "display 'Debt Free'")
    * ``icr_warning_flag`` is True when 0 < ICR < 1.5 (difficulty servicing debt)
    * Asset Turnover returns ``None`` when total_assets = 0

All ratios are pure functions of their inputs so they are trivially unit-testable.
Monetary inputs are assumed to be in ₹ Crore.

Usage::

    from src.analytics.leverage import compute_leverage_ratios
    result = compute_leverage_ratios(
        sales=1000.0, operating_profit=250.0, other_income=10.0,
        interest=40.0, equity_capital=100.0, reserves=500.0,
        borrowings=200.0, investments=80.0, total_assets=1500.0,
        broad_sector="Information Technology",
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.analytics.ratios import is_financial_sector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (centralised for easy tuning; mirrored in tests)
# ---------------------------------------------------------------------------
HIGH_LEVERAGE_DE_THRESHOLD: float = 5.0  # D/E > 5 → flag (non-financials only)
ICR_WARNING_THRESHOLD: float = 1.5  # ICR < 1.5 → warning flag
ICR_DEBT_FREE_LABEL: str = "Debt Free"  # Display label when interest = 0


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LeverageRatios:
    """Immutable result of :func:`compute_leverage_ratios`.

    Attributes:
        debt_to_equity:          D/E ratio (0 for debt-free companies).
        high_leverage_flag:      True when D/E > HIGH_LEVERAGE_DE_THRESHOLD
                                 for non-financial companies.
        interest_coverage:       ICR; None when interest = 0 (debt-free).
        icr_label:               Human-readable label — "Debt Free" when
                                 interest = 0, otherwise a formatted number
                                 (set by caller; engine only sets the
                                 debt-free sentinel).
        icr_warning_flag:        True when 0 < ICR < ICR_WARNING_THRESHOLD.
        net_debt_cr:             Net debt (₹ Crore) = borrowings - investments.
                                 Negative value implies net cash.
        asset_turnover:          Sales / total_assets; None if total_assets = 0.
        is_financial_sector:     True for banks/NBFCs/NFCs — relaxes D/E flag.
        warnings:                Tuple of human-readable warning messages.
    """

    debt_to_equity: float | None
    high_leverage_flag: bool
    interest_coverage: float | None
    icr_label: str | None
    icr_warning_flag: bool
    net_debt_cr: float | None
    asset_turnover: float | None
    is_financial_sector: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Individual ratio primitives
# ---------------------------------------------------------------------------
def debt_to_equity(
    borrowings: float,
    equity_capital: float,
    reserves: float | None,
) -> float | None:
    """Compute Debt-to-Equity ratio.

    Formula:
        D/E = borrowings / (equity_capital + reserves)

    Edge cases (per spec §13 and Day 09 brief):
        * Returns ``0.0`` when ``borrowings == 0`` (debt-free), regardless
          of equity.  This is an explicit choice per the Day 09 brief
          ("return 0 (not None) if borrowings = 0").
        * Returns ``None`` when equity + reserves <= 0 (negative book value
          makes the ratio meaningless; will be logged as a warning upstream).
        * Treats ``reserves`` of None as 0.
    """
    if borrowings == 0:
        return 0.0
    _reserves = reserves if reserves is not None else 0.0
    equity = equity_capital + _reserves
    if equity <= 0:
        return None
    return borrowings / equity


def interest_coverage_ratio(
    operating_profit: float,
    other_income: float,
    interest: float,
) -> float | None:
    """Compute Interest Coverage Ratio (ICR).

    Formula:
        ICR = (operating_profit + other_income) / interest

    Edge cases (per spec §13):
        * Returns ``None`` when ``interest == 0`` (debt-free or missing
          interest expense).  Callers should render this as
          ``"Debt Free"`` via :data:`ICR_DEBT_FREE_LABEL`.
        * Negative ICR is allowed (EBIT losses while still paying interest).
    """
    if interest == 0:
        return None
    ebit_plus_other = operating_profit + other_income
    return ebit_plus_other / interest


def net_debt(
    borrowings: float,
    investments: float | None,
) -> float:
    """Compute Net Debt in ₹ Crore.

    Formula (per Day 09 brief — investments used as liquid-asset proxy):
        Net Debt = borrowings - investments

    Notes:
        * The spec §13 form is ``borrowings - investments - cash`` but the
          ``balancesheet`` table in this schema does not expose a standalone
          ``cash`` column; the Day 09 brief explicitly simplifies to
          ``borrowings - investments``.
        * A negative result implies a **net cash** position (investments
          exceed debt).
        * ``investments`` of None is treated as 0.
    """
    _inv = investments if investments is not None else 0.0
    return borrowings - _inv


def asset_turnover(
    sales: float,
    total_assets: float,
) -> float | None:
    """Compute Asset Turnover ratio (revenue per rupee of assets).

    Formula:
        Asset Turnover = sales / total_assets

    Edge cases (per spec §13):
        * Returns ``None`` when ``total_assets == 0`` (should never occur
          due to the schema CHECK constraint, but guarded for tests).
    """
    if total_assets == 0:
        return None
    return sales / total_assets


# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------
def high_leverage_flag(de_ratio: float | None, is_financial: bool) -> bool:
    """Return True when D/E exceeds the threshold AND company is non-financial.

    Per §28 sector benchmarks:
        * IT/FMCG D/E 0-0.5; >5 is a red flag.
        * Banks/NBFCs D/E >5 is **normal** (deposits are borrowings) — carve-out.
    """
    if de_ratio is None:
        return False
    if is_financial:
        return False
    return de_ratio > HIGH_LEVERAGE_DE_THRESHOLD


def icr_warning_flag(icr: float | None) -> bool:
    """Return True when ICR is positive but below the warning threshold.

    Per spec §13: "flag if <1" — we use 1.5 per the Day 09 brief to catch
    companies heading toward distress (1.0 is already in default zone).
    Debt-free companies (ICR None) do NOT trigger this flag.
    Negative ICR (operating losses with interest) also flags as a warning.
    """
    if icr is None:
        return False
    return icr < ICR_WARNING_THRESHOLD


def icr_display_label(icr: float | None) -> str | None:
    """Return the human-readable label for ICR.

    * ``"Debt Free"`` when ICR is None (interest = 0).
    * ``None`` otherwise — the caller can format the numeric value.
    """
    if icr is None:
        return ICR_DEBT_FREE_LABEL
    return None


# ---------------------------------------------------------------------------
# High-level convenience
# ---------------------------------------------------------------------------
def compute_leverage_ratios(
    *,
    sales: float,
    operating_profit: float,
    other_income: float = 0.0,
    interest: float,
    equity_capital: float,
    reserves: float | None = None,
    borrowings: float,
    investments: float | None = None,
    total_assets: float,
    broad_sector: str | None = None,
    company_id: str | None = None,
    year: str | None = None,
) -> LeverageRatios:
    """Compute all Day-09 leverage and efficiency ratios for one company-year.

    All keyword arguments are positional-only-by-convention (enforced via
    ``*``) to reduce the risk of silent argument mis-ordering.

    Args:
        sales:             Revenue from P&L (₹ Crore).
        operating_profit:  EBITDA from P&L (₹ Crore).
        other_income:      Non-operating income from P&L (₹ Crore).
        interest:          Interest expense from P&L (₹ Crore).
        equity_capital:    Equity share capital from B/S (₹ Crore).
        reserves:          Reserves & surplus from B/S (₹ Crore); None → 0.
        borrowings:        Total borrowings (debt) from B/S (₹ Crore).
        investments:       Investments from B/S (liquid-asset proxy); None → 0.
        total_assets:      Total assets from B/S (₹ Crore).
        broad_sector:      ``sectors.broad_sector`` label (used for financial-
                           sector carve-out on D/E flag).
        company_id:        Optional ticker for log context only.
        year:              Optional year label for log context only.

    Returns:
        A :class:`LeverageRatios` frozen dataclass with every ratio and flag
        populated.
    """
    warnings: list[str] = []
    ctx = f"{company_id or '?'} {year or '?'}"

    fin = is_financial_sector(broad_sector)

    de = debt_to_equity(borrowings, equity_capital, reserves)
    if de is None and borrowings != 0:
        msg = (
            f"D/E incalculable for {ctx}: borrowings={borrowings}, "
            f"equity+reserves<=0 (negative book value)"
        )
        warnings.append(msg)
        logger.warning(msg)

    hlev = high_leverage_flag(de, fin)
    if hlev:
        msg = (
            f"HIGH LEVERAGE flag for {ctx}: D/E={de:.2f} exceeds "
            f"threshold {HIGH_LEVERAGE_DE_THRESHOLD} (non-financial)"
        )
        warnings.append(msg)
        logger.warning(msg)

    icr = interest_coverage_ratio(operating_profit, other_income, interest)
    label = icr_display_label(icr)
    iwarn = icr_warning_flag(icr)
    if iwarn:
        msg = (
            f"ICR warning for {ctx}: ICR={icr:.2f} below "
            f"threshold {ICR_WARNING_THRESHOLD} (risk of debt-service stress)"
        )
        warnings.append(msg)
        logger.warning(msg)

    nd = net_debt(borrowings, investments)
    at = asset_turnover(sales, total_assets)

    return LeverageRatios(
        debt_to_equity=de,
        high_leverage_flag=hlev,
        interest_coverage=icr,
        icr_label=label,
        icr_warning_flag=iwarn,
        net_debt_cr=nd,
        asset_turnover=at,
        is_financial_sector=fin,
        warnings=tuple(warnings),
    )


__all__ = [
    "HIGH_LEVERAGE_DE_THRESHOLD",
    "ICR_DEBT_FREE_LABEL",
    "ICR_WARNING_THRESHOLD",
    "LeverageRatios",
    "asset_turnover",
    "compute_leverage_ratios",
    "debt_to_equity",
    "high_leverage_flag",
    "icr_display_label",
    "icr_warning_flag",
    "interest_coverage_ratio",
    "net_debt",
]
