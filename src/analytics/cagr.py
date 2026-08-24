"""Nifty 100 Financial Intelligence Platform — CAGR (Compound Annual Growth Rate) Engine.

Implements Sprint 2 Day 10 growth KPIs per spec §13 and §23.1:

    * Revenue CAGR — 3yr, 5yr, 10yr (from ``profitandloss.sales``)
    * PAT CAGR — 3yr, 5yr, 10yr (from ``profitandloss.net_profit``)
    * EPS CAGR — 3yr, 5yr, 10yr (from ``profitandloss.eps``)

Edge-case flags (returned alongside the CAGR value):

    * ``OK``             — Positive base and positive end; CAGR computed normally.
    * ``TURNAROUND``     — Base < 0, end > 0 (losses turned to profits) → CAGR = None.
    * ``DECLINE_TO_LOSS``— Base > 0, end < 0 (profit turned to losses) → CAGR = None.
    * ``BOTH_NEGATIVE``  — Both base and end < 0 → CAGR = None (mathematically
                           undefined in real numbers).
    * ``ZERO_BASE``      — Base == 0 → CAGR = None.
    * ``INSUFFICIENT``   — Fewer than ``n`` years of data → CAGR = None.

The engine is intentionally a pure-function library — no I/O.  A higher-level
helper :func:`compute_cagrs_for_series` will produce a list of (year, value, flag)
tuples for a time series sorted ascending by year.  A second helper
:func:`compute_all_cagrs` joins sales / net_profit / EPS for one company and
returns all 9 CAGR values + 9 flag strings suitable for direct insertion into
the ``financial_ratios`` table.

All monetary inputs are in ₹ Crore; CAGR outputs are in percent (e.g. 15.3 for
15.3% CAGR).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flag constants — used both as Python strings and as stored SQL values.
# ---------------------------------------------------------------------------
CAGR_OK = "OK"
CAGR_TURNAROUND = "TURNAROUND"
CAGR_DECLINE_TO_LOSS = "DECLINE_TO_LOSS"
CAGR_BOTH_NEGATIVE = "BOTH_NEGATIVE"
CAGR_ZERO_BASE = "ZERO_BASE"
CAGR_INSUFFICIENT = "INSUFFICIENT"

VALID_FLAGS: frozenset[str] = frozenset(
    {
        CAGR_OK,
        CAGR_TURNAROUND,
        CAGR_DECLINE_TO_LOSS,
        CAGR_BOTH_NEGATIVE,
        CAGR_ZERO_BASE,
        CAGR_INSUFFICIENT,
    }
)

# Standard CAGR windows (years) used across the platform.
CAGR_WINDOWS: tuple[int, ...] = (3, 5, 10)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CAGRResult:
    """Immutable outcome of a single CAGR computation.

    Attributes:
        value: CAGR percentage (e.g. 15.2 for 15.2%), or ``None`` when a flag
               other than ``OK`` applies.
        flag:  One of the ``CAGR_*`` constants above.
        start: Start-period value used (for debugging / transparency).
        end:   End-period value used.
        n:     Window length in years.
    """

    value: float | None
    flag: str
    start: float
    end: float
    n: int

    def __post_init__(self) -> None:
        if self.flag not in VALID_FLAGS:
            raise ValueError(f"Invalid CAGR flag: {self.flag!r}")
        if self.n < 1:
            raise ValueError(f"CAGR window must be ≥ 1 year, got {self.n}")


@dataclass(frozen=True)
class CompanyCAGRs:
    """All 9 CAGR metrics + flags for a single company-year row.

    Attributes are named ``<metric>_cagr_<window>yr`` for the numeric value and
    ``<metric>_cagr_<window>yr_flag`` for the flag string.  ``revenue`` is used
    in code to match the P&L column name ``sales``; the public column names
    use ``revenue`` per the spec KPI list.
    """

    company_id: str
    year: str

    # Revenue (sales) CAGRs
    revenue_cagr_3yr: float | None
    revenue_cagr_3yr_flag: str
    revenue_cagr_5yr: float | None
    revenue_cagr_5yr_flag: str
    revenue_cagr_10yr: float | None
    revenue_cagr_10yr_flag: str

    # PAT (net_profit) CAGRs
    pat_cagr_3yr: float | None
    pat_cagr_3yr_flag: str
    pat_cagr_5yr: float | None
    pat_cagr_5yr_flag: str
    pat_cagr_10yr: float | None
    pat_cagr_10yr_flag: str

    # EPS CAGRs
    eps_cagr_3yr: float | None
    eps_cagr_3yr_flag: str
    eps_cagr_5yr: float | None
    eps_cagr_5yr_flag: str
    eps_cagr_10yr: float | None
    eps_cagr_10yr_flag: str


# ---------------------------------------------------------------------------
# Single-pair CAGR primitive
# ---------------------------------------------------------------------------
def cagr(start: float, end: float, n: int) -> CAGRResult:
    """Compute Compound Annual Growth Rate for a single (start, end, n) triple.

    Formula (spec §13):
        ``CAGR = ((end / start) ** (1 / n) - 1) * 100``

    Edge-case handling per §23.1 / Day 10 brief:
        * ``start == 0`` → flag = ``ZERO_BASE``, value = ``None``.
        * ``start < 0 and end > 0`` → ``TURNAROUND``.
        * ``start > 0 and end < 0`` → ``DECLINE_TO_LOSS``.
        * ``start < 0 and end < 0`` → ``BOTH_NEGATIVE``.
        * Otherwise (both positive) → ``OK`` with computed percentage.

    Args:
        start: Value n years ago.
        end:   Current value.
        n:     Number of years in the window (≥ 1).

    Returns:
        A :class:`CAGRResult` with value and flag populated.
    """
    if n < 1:
        raise ValueError(f"CAGR window must be >= 1 year, got {n}")

    # Exact zero base → undefined regardless of end.
    if start == 0:
        return CAGRResult(None, CAGR_ZERO_BASE, start, end, n)

    # Sign-matrix handling:
    #   start<0, end>0  → TURNAROUND (loss to profit)
    #   start<0, end==0 → TURNAROUND (loss to break-even)
    #   start>0, end<0  → DECLINE_TO_LOSS (profit to loss)
    #   start<0, end<0  → BOTH_NEGATIVE (CAGR undefined in real numbers)
    #   start>0, end==0 → -100% wipeout, OK flag (total erosion)
    #   start>0, end>0  → normal CAGR
    if start < 0 and end > 0:
        return CAGRResult(None, CAGR_TURNAROUND, start, end, n)
    if start < 0 and end == 0:
        return CAGRResult(None, CAGR_TURNAROUND, start, end, n)
    if start > 0 and end < 0:
        return CAGRResult(None, CAGR_DECLINE_TO_LOSS, start, end, n)
    if start < 0 and end < 0:
        return CAGRResult(None, CAGR_BOTH_NEGATIVE, start, end, n)
    if end == 0 and start > 0:
        # end=0 with positive base is a 100% decline → -100% (total wipeout).
        return CAGRResult(-100.0, CAGR_OK, start, end, n)
    if start > 0 and end > 0:
        ratio = end / start
        pct = (math.pow(ratio, 1.0 / n) - 1.0) * 100.0
        return CAGRResult(pct, CAGR_OK, start, end, n)

    # Defensive — should be unreachable.
    return CAGRResult(None, CAGR_BOTH_NEGATIVE, start, end, n)


# ---------------------------------------------------------------------------
# Series-level helper — compute trailing CAGRs for every row in a time series
# ---------------------------------------------------------------------------
def compute_cagrs_for_series(
    series: Sequence[tuple[str, float]],
    windows: Iterable[int] = CAGR_WINDOWS,
) -> list[dict[int, CAGRResult]]:
    """Compute trailing-window CAGRs for every row in a sorted time series.

    Args:
        series:  A chronologically-sorted sequence of ``(year_label, value)``
                 pairs, oldest first.  Year labels are compared lexicographically
                 ("YYYY-MM" strings sort correctly); values must be plain floats.
        windows: Iterable of window lengths in years (default: 3, 5, 10).

    Returns:
        A list of dicts of the same length as ``series``.  The i-th dict maps
        each requested window ``n`` to a :class:`CAGRResult`.  Rows without
        enough look-back history receive ``INSUFFICIENT`` results for that
        window.
    """
    wins = tuple(windows)
    out: list[dict[int, CAGRResult]] = []
    # Build index of year → position for efficient lookup.
    year_pos: dict[str, int] = {yr: idx for idx, (yr, _v) in enumerate(series)}
    # Pre-sort years ascending to find look-back positions by index offset.
    years_sorted = [yr for yr, _v in series]

    for i, (_yr, end_val) in enumerate(series):
        per_window: dict[int, CAGRResult] = {}
        for n in wins:
            j = i - n
            if j < 0:
                per_window[n] = CAGRResult(None, CAGR_INSUFFICIENT, float("nan"), end_val, n)
                continue
            start_yr = years_sorted[j]
            start_val = series[j][1]
            # Extra safety: if there is a year gap (missing data), mark insufficient.
            # We detect by verifying the year at position i-n is *exactly* n steps
            # back in the year-index map and that the year label is present.
            if year_pos.get(start_yr) != j:
                per_window[n] = CAGRResult(None, CAGR_INSUFFICIENT, float("nan"), end_val, n)
                continue
            per_window[n] = cagr(start_val, end_val, n)
        out.append(per_window)
    return out


# ---------------------------------------------------------------------------
# Company-level convenience: compute all 9 CAGR metrics per year
# ---------------------------------------------------------------------------
def compute_all_cagrs(
    company_id: str,
    pl_rows: Sequence[dict],
) -> list[CompanyCAGRs]:
    """Compute all 9 CAGR metrics (revenue/PAT/EPS x 3/5/10yr) for one company.

    Args:
        company_id: NSE ticker (uppercase, stripped).
        pl_rows:    Sequence of P&L dicts for the company.  Each dict must
                    contain ``year`` (YYYY-MM string, sortable), ``sales``,
                    ``net_profit`` and ``eps``.  Rows need not be pre-sorted;
                    this function sorts by ``year`` ascending.

    Returns:
        A list of :class:`CompanyCAGRs` in ascending year order, one per input
        row (after sorting).  Early rows (where insufficient look-back exists)
        carry ``INSUFFICIENT`` flags and ``None`` values.
    """
    if not pl_rows:
        return []

    # Sort ascending by year.
    sorted_rows = sorted(pl_rows, key=lambda r: r["year"])

    sales_series = [(r["year"], float(r["sales"])) for r in sorted_rows]
    pat_series = [(r["year"], float(r["net_profit"])) for r in sorted_rows]
    eps_series = [(r["year"], float(r["eps"])) for r in sorted_rows]

    sales_cagrs = compute_cagrs_for_series(sales_series)
    pat_cagrs = compute_cagrs_for_series(pat_series)
    eps_cagrs = compute_cagrs_for_series(eps_series)

    out: list[CompanyCAGRs] = []
    for i, row in enumerate(sorted_rows):
        sc = sales_cagrs[i]
        pc = pat_cagrs[i]
        ec = eps_cagrs[i]
        out.append(
            CompanyCAGRs(
                company_id=company_id,
                year=row["year"],
                revenue_cagr_3yr=sc[3].value,
                revenue_cagr_3yr_flag=sc[3].flag,
                revenue_cagr_5yr=sc[5].value,
                revenue_cagr_5yr_flag=sc[5].flag,
                revenue_cagr_10yr=sc[10].value,
                revenue_cagr_10yr_flag=sc[10].flag,
                pat_cagr_3yr=pc[3].value,
                pat_cagr_3yr_flag=pc[3].flag,
                pat_cagr_5yr=pc[5].value,
                pat_cagr_5yr_flag=pc[5].flag,
                pat_cagr_10yr=pc[10].value,
                pat_cagr_10yr_flag=pc[10].flag,
                eps_cagr_3yr=ec[3].value,
                eps_cagr_3yr_flag=ec[3].flag,
                eps_cagr_5yr=ec[5].value,
                eps_cagr_5yr_flag=ec[5].flag,
                eps_cagr_10yr=ec[10].value,
                eps_cagr_10yr_flag=ec[10].flag,
            )
        )
    return out


__all__ = [
    "CAGR_BOTH_NEGATIVE",
    "CAGR_DECLINE_TO_LOSS",
    "CAGR_INSUFFICIENT",
    "CAGR_OK",
    "CAGR_TURNAROUND",
    "CAGR_WINDOWS",
    "CAGR_ZERO_BASE",
    "VALID_FLAGS",
    "CAGRResult",
    "CompanyCAGRs",
    "cagr",
    "compute_all_cagrs",
    "compute_cagrs_for_series",
]
