"""Nifty 100 Financial Intelligence Platform — Cash Flow KPI Engine.

Implements Sprint 2 Day 11 KPIs per spec section 13 (KPI Reference):

    * Free Cash Flow (FCF)              = operating_activity + investing_activity
    * CFO / PAT Ratio (annual)          = operating_activity / net_profit
    * CFO Quality Score (5-yr rolling)  = mean(CFO/PAT) over trailing 5yr, with tier labels
    * CapEx Intensity                   = abs(investing_activity) / sales x 100, with tier labels
    * FCF Conversion Rate               = FCF / operating_profit x 100
    * Capital Allocation Pattern        = 8-class classifier from sign of (CFO, CFI, CFF)

Edge cases handled:
    * PAT = 0             -> CFO/PAT = None (undefined)
    * operating_profit=0  -> FCF Conversion = None
    * sales = 0           -> CapEx Intensity = None
    * Missing years       -> rolling window uses as many years as available; INSUFFICIENT if <3
    * Zero-flows are classified with their sign (0 maps to "+" per _sign() helper)

All ratios are pure functions of their inputs. Monetary inputs are in INR Crore.
"""

from __future__ import annotations

import csv
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier thresholds
# ---------------------------------------------------------------------------
CFO_QUALITY_HIGH = 1.0  # >1.0 -> High Quality
CFO_QUALITY_MODERATE_LOW = 0.5  # 0.5-1.0 -> Moderate; <0.5 -> Accrual Risk

CAPEX_LIGHT_MAX = 3.0  # <3%  -> Asset Light
CAPEX_MODERATE_MAX = 8.0  # 3-8% -> Moderate; >8% -> Capital Intensive

FCF_CONCERN_CONSEC_YEARS = 3  # 3yr consecutive negative FCF -> FCF Concern flag (for later)

# ---------------------------------------------------------------------------
# Capital Allocation pattern taxonomy (spec section 13 Day 11 brief)
# ---------------------------------------------------------------------------
# Each key is a sign triple (s_cfo, s_cfi, s_cff) where s in {"+", "-"}
PATTERN_REINVESTOR = "Reinvestor"
PATTERN_SHAREHOLDER_RETURNS = "Shareholder Returns"
PATTERN_LIQUIDATING_ASSETS = "Liquidating Assets"
PATTERN_DISTRESS_SIGNAL = "Distress Signal"
PATTERN_GROWTH_FUNDED_BY_DEBT = "Growth Funded by Debt"
PATTERN_CASH_ACCUMULATOR = "Cash Accumulator"
PATTERN_PRE_REVENUE = "Pre-Revenue"
PATTERN_MIXED = "Mixed"


def _sign(x: float) -> str:
    """Return '-' for negative values, '+' for non-negative (zero -> '+')."""
    return "-" if x < 0 else "+"


# Canonical pattern table per Day 11 brief.
_BASE_PATTERN_MAP: dict[tuple[str, str, str], str] = {
    ("+", "-", "-"): PATTERN_REINVESTOR,
    ("+", "+", "-"): PATTERN_LIQUIDATING_ASSETS,
    ("-", "+", "+"): PATTERN_DISTRESS_SIGNAL,
    ("-", "-", "+"): PATTERN_GROWTH_FUNDED_BY_DEBT,
    ("+", "+", "+"): PATTERN_CASH_ACCUMULATOR,
    ("-", "-", "-"): PATTERN_PRE_REVENUE,
}


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CashFlowKPIs:
    """Immutable cash-flow KPI bundle for a single company-year.

    Attributes
    ----------
    fcf_cr : float | None
        Free Cash Flow (INR Cr) = CFO + CFI. Negative = cash burn.
    cfo_pat_ratio : float | None
        Annual CFO/PAT ratio; None if PAT = 0.
    cfo_quality_score_5yr : float | None
        5-year rolling mean of CFO/PAT; None if insufficient data (<3 valid years).
    cfo_quality_tier : str | None
        'High Quality' / 'Moderate' / 'Accrual Risk' / None.
    capex_intensity_pct : float | None
        |CFI| / sales x 100; None if sales = 0.
    capex_tier : str | None
        'Asset Light' / 'Moderate' / 'Capital Intensive' / None.
    fcf_conversion_pct : float | None
        FCF / operating_profit x 100; None if operating_profit = 0.
    cfo_sign, cfi_sign, cff_sign : str
        '+' or '-' per _sign() helper (0 maps to '+').
    capital_allocation_pattern : str
        One of the 8 PATTERN_* labels.
    fcf_concern_flag : bool
        True if current + prior 2 years all show negative FCF.
    """

    fcf_cr: float | None
    cfo_pat_ratio: float | None
    cfo_quality_score_5yr: float | None
    cfo_quality_tier: str | None
    capex_intensity_pct: float | None
    capex_tier: str | None
    fcf_conversion_pct: float | None
    cfo_sign: str
    cfi_sign: str
    cff_sign: str
    capital_allocation_pattern: str
    fcf_concern_flag: bool


# ---------------------------------------------------------------------------
# Primitive single-row calculators
# ---------------------------------------------------------------------------
def free_cash_flow(cfo: float, cfi: float) -> float:
    """Return Free Cash Flow = CFO + CFI (INR Cr).

    Negative FCF is allowed - indicates cash burn after CapEx/investing.
    """
    return cfo + cfi


def cfo_pat_ratio(cfo: float, pat: float) -> float | None:
    """Return CFO / PAT ratio (not multiplied by 100 - it is a ratio, not a percent).

    Returns None when PAT = 0 (undefined). Negative PAT produces a negative
    ratio, which the quality-tier logic treats as accrual-risk / unreliable.
    """
    if pat == 0:
        return None
    return cfo / pat


def capex_intensity(cfi: float, sales: float) -> float | None:
    """Return CapEx Intensity as % = |CFI| / sales x 100.

    Per spec section 13, CFI (usually negative) is used as a CapEx proxy.
    Returns None when sales = 0.
    """
    if sales == 0:
        return None
    return abs(cfi) / sales * 100.0


def fcf_conversion(fcf: float, ebitda: float) -> float | None:
    """Return FCF Conversion Rate as % = FCF / operating_profit x 100.

    Returns None when operating_profit = 0.
    """
    if ebitda == 0:
        return None
    return fcf / ebitda * 100.0


def capex_tier(capex_pct: float | None) -> str | None:
    """Map CapEx Intensity % to a tier label."""
    if capex_pct is None:
        return None
    if capex_pct < CAPEX_LIGHT_MAX:
        return "Asset Light"
    if capex_pct <= CAPEX_MODERATE_MAX:
        return "Moderate"
    return "Capital Intensive"


def cfo_quality_tier(score: float | None) -> str | None:
    """Map a 5-yr CFO/PAT score to a quality tier."""
    if score is None:
        return None
    if math.isnan(score):
        return None
    if score > CFO_QUALITY_HIGH:
        return "High Quality"
    if score >= CFO_QUALITY_MODERATE_LOW:
        return "Moderate"
    return "Accrual Risk"


def classify_capital_allocation(
    cfo: float, cfi: float, cff: float, cfo_pat: float | None
) -> tuple[str, str, str, str]:
    """Return (s_cfo, s_cfi, s_cff, pattern_label) for one company-year.

    The Reinvestor/Shareholder-Returns split: (+,-,-) is normally "Reinvestor",
    but when CFO/PAT ratio is >= 1.0 (high quality) we label it "Shareholder Returns"
    because strong cash conversion with negative CFF typically reflects buybacks,
    dividends, or debt repayment - capital returned to shareholders.
    """
    s_cfo, s_cfi, s_cff = _sign(cfo), _sign(cfi), _sign(cff)
    key = (s_cfo, s_cfi, s_cff)
    base = _BASE_PATTERN_MAP.get(key, PATTERN_MIXED)

    # Sub-class: (+,-,-) + strong CFO/PAT -> Shareholder Returns
    if base == PATTERN_REINVESTOR and cfo_pat is not None and cfo_pat >= CFO_QUALITY_HIGH:
        label = PATTERN_SHAREHOLDER_RETURNS
    else:
        label = base
    return s_cfo, s_cfi, s_cff, label


# ---------------------------------------------------------------------------
# Rolling helpers
# ---------------------------------------------------------------------------
def _rolling_mean(values: Sequence[float | None], window: int, min_periods: int) -> float | None:
    """Return trailing-window mean of non-None values; None if insufficient."""
    window_vals = [v for v in values[-window:] if v is not None]
    if len(window_vals) < min_periods:
        return None
    return sum(window_vals) / len(window_vals)


def _consecutive_negatives_at_tail(values: Sequence[float | None], streak: int) -> bool:
    """True if the last `streak` non-None entries are all negative."""
    tail: list[float] = []
    for v in reversed(values):
        if v is None:
            continue
        tail.append(v)
        if len(tail) == streak:
            break
    if len(tail) < streak:
        return False
    return all(x < 0 for x in tail)


# ---------------------------------------------------------------------------
# Series-level calculator (handles rolling windows for one company)
# ---------------------------------------------------------------------------
def compute_cashflow_kpis_for_company(
    company_id: str,
    pl_rows: Sequence[dict],
    cf_rows: Sequence[dict],
) -> list[CashFlowKPIs]:
    """Compute cash-flow KPIs for every year of a single company.

    Parameters
    ----------
    company_id : str
        NSE ticker (used for logging context).
    pl_rows : Sequence[dict]
        Each dict has keys: year, sales, operating_profit, net_profit.
    cf_rows : Sequence[dict]
        Each dict has keys: year, operating_activity (CFO), investing_activity (CFI),
        financing_activity (CFF), net_cash_flow (optional, not used).

    Returns
    -------
    list[CashFlowKPIs]
        One record per year in the inner-join of cf_rows and pl_rows (sorted by year ascending).
    """
    pl_by_year = {r["year"]: r for r in pl_rows}
    # Inner-join on year
    paired: list[tuple[str, dict, dict]] = []
    for cr in sorted(cf_rows, key=lambda r: r["year"]):
        yr = cr["year"]
        if yr in pl_by_year:
            paired.append((yr, pl_by_year[yr], cr))

    if not paired:
        logger.warning(f"No overlapping P&L/cashflow years for {company_id}")
        return []

    # Trailing arrays (for rolling mean / consecutive-negative checks)
    cfo_pat_history: list[float | None] = []
    fcf_history: list[float | None] = []

    out: list[CashFlowKPIs] = []
    for _yr, pl, cf in paired:
        sales = float(pl["sales"])
        op_profit = float(pl["operating_profit"])
        pat = float(pl["net_profit"])
        cfo = float(cf["operating_activity"])
        cfi = float(cf["investing_activity"])
        cff = float(cf["financing_activity"])

        fcf = free_cash_flow(cfo, cfi)
        cfo_pat = cfo_pat_ratio(cfo, pat)
        capex_pct = capex_intensity(cfi, sales)
        fcf_conv = fcf_conversion(fcf, op_profit)

        cfo_pat_history.append(cfo_pat)
        fcf_history.append(fcf)

        quality_5yr = _rolling_mean(cfo_pat_history, window=5, min_periods=3)
        quality_tier = cfo_quality_tier(quality_5yr)
        c_tier = capex_tier(capex_pct)

        s_cfo, s_cfi, s_cff, pattern = classify_capital_allocation(cfo, cfi, cff, cfo_pat)
        fcf_concern = _consecutive_negatives_at_tail(fcf_history, FCF_CONCERN_CONSEC_YEARS)

        out.append(
            CashFlowKPIs(
                fcf_cr=fcf,
                cfo_pat_ratio=cfo_pat,
                cfo_quality_score_5yr=quality_5yr,
                cfo_quality_tier=quality_tier,
                capex_intensity_pct=capex_pct,
                capex_tier=c_tier,
                fcf_conversion_pct=fcf_conv,
                cfo_sign=s_cfo,
                cfi_sign=s_cfi,
                cff_sign=s_cff,
                capital_allocation_pattern=pattern,
                fcf_concern_flag=fcf_concern,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Capital Allocation CSV writer
# ---------------------------------------------------------------------------
CAPITAL_ALLOCATION_CSV_COLUMNS = [
    "company_id",
    "year",
    "cfo_sign",
    "cfi_sign",
    "cff_sign",
    "pattern_label",
]


@dataclass(frozen=True)
class CapitalAllocationRow:
    """Flat row for capital_allocation.csv export."""

    company_id: str
    year: str
    cfo_sign: str
    cfi_sign: str
    cff_sign: str
    pattern_label: str

    def as_dict(self) -> dict[str, str]:
        return {
            "company_id": self.company_id,
            "year": self.year,
            "cfo_sign": self.cfo_sign,
            "cfi_sign": self.cfi_sign,
            "cff_sign": self.cff_sign,
            "pattern_label": self.pattern_label,
        }


def write_capital_allocation_csv(
    rows: Iterable[CapitalAllocationRow],
    output_path: Path,
) -> int:
    """Write capital-allocation rows to CSV. Returns number of rows written.

    Overwrites any existing file (ETL style). Creates parent dirs as needed.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CAPITAL_ALLOCATION_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
            count += 1
    logger.info(f"Wrote {count} rows to {output_path}")
    return count


def build_capital_allocation_rows(
    company_id: str,
    years: Sequence[str],
    kpis: Sequence[CashFlowKPIs],
) -> list[CapitalAllocationRow]:
    """Zip company_id/year with KPI sign triples and pattern labels."""
    rows: list[CapitalAllocationRow] = []
    for yr, kpi in zip(years, kpis, strict=True):
        rows.append(
            CapitalAllocationRow(
                company_id=company_id,
                year=yr,
                cfo_sign=kpi.cfo_sign,
                cfi_sign=kpi.cfi_sign,
                cff_sign=kpi.cff_sign,
                pattern_label=kpi.capital_allocation_pattern,
            )
        )
    return rows


__all__ = [
    "CAPEX_LIGHT_MAX",
    "CAPEX_MODERATE_MAX",
    "CAPITAL_ALLOCATION_CSV_COLUMNS",
    "CFO_QUALITY_HIGH",
    "CFO_QUALITY_MODERATE_LOW",
    "FCF_CONCERN_CONSEC_YEARS",
    "PATTERN_CASH_ACCUMULATOR",
    "PATTERN_DISTRESS_SIGNAL",
    "PATTERN_GROWTH_FUNDED_BY_DEBT",
    "PATTERN_LIQUIDATING_ASSETS",
    "PATTERN_MIXED",
    "PATTERN_PRE_REVENUE",
    "PATTERN_REINVESTOR",
    "PATTERN_SHAREHOLDER_RETURNS",
    "CapitalAllocationRow",
    "CashFlowKPIs",
    "build_capital_allocation_rows",
    "capex_intensity",
    "capex_tier",
    "cfo_pat_ratio",
    "cfo_quality_tier",
    "classify_capital_allocation",
    "compute_cashflow_kpis_for_company",
    "fcf_conversion",
    "free_cash_flow",
    "write_capital_allocation_csv",
]
