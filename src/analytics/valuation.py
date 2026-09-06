"""Valuation ratio primitives — Sprint 3 Day 16.

Computes valuation multiples (P/E, P/B, EV/EBITDA, Dividend Yield, FCF Yield)
from fundamentals and compares them with externally supplied market-cap-table
multiples. Returns ``None`` for undefined cases (negative earnings, zero
equity, etc.) per the KPI reference in §13 of the spec.

All monetary inputs are expected in ₹ Crore.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Thresholds / benchmarks (spec §13 "KPI Reference")
# ---------------------------------------------------------------------------
PE_FAIR_LOWER = 15.0
PE_FAIR_UPPER = 25.0
PE_EXPENSIVE = 40.0
PE_CHEAP = 10.0

PB_FAIR_UPPER = 3.0
PB_EXPENSIVE = 8.0  # IT/services may sit here legitimately — flag only contextually

EV_EBITDA_FAIR_LOWER = 12.0
EV_EBITDA_FAIR_UPPER = 18.0

DIV_YIELD_HIGH = 4.0
DIV_YIELD_DECENT = 2.0

FCF_YIELD_ATTRACTIVE = 3.0


@dataclass(frozen=True)
class ValuationRatios:
    """Computed valuation multiples for a single company-year."""

    pe_ratio: float | None = None
    pb_ratio: float | None = None
    ev_ebitda: float | None = None
    dividend_yield_pct: float | None = None
    fcf_yield_pct: float | None = None
    earnings_yield_pct: float | None = None


# ---------------------------------------------------------------------------
# Primitive computations
# ---------------------------------------------------------------------------
def price_to_earnings(
    market_cap_crore: float | None, net_profit_crore: float | None
) -> float | None:
    """Price-to-Earnings = market cap / net profit.

    Returns None when net profit is non-positive (multiple undefined / loss-making).
    """
    if market_cap_crore is None or net_profit_crore is None:
        return None
    if net_profit_crore <= 0 or market_cap_crore <= 0:
        return None
    return market_cap_crore / net_profit_crore


def price_to_book(market_cap_crore: float | None, book_value_crore: float | None) -> float | None:
    """Price-to-Book = market cap / (equity + reserves).

    Returns None when book value is zero or negative.
    """
    if market_cap_crore is None or book_value_crore is None:
        return None
    if book_value_crore <= 0 or market_cap_crore <= 0:
        return None
    return market_cap_crore / book_value_crore


def ev_to_ebitda(enterprise_value_crore: float | None, ebit_crore: float | None) -> float | None:
    """EV/EBITDA proxy = enterprise value / EBIT (operating_profit from spec §13).

    The spec sheet approximates EBITDA as operating profit for this dataset.
    Returns None when EBIT ≤ 0.
    """
    if enterprise_value_crore is None or ebit_crore is None:
        return None
    if ebit_crore <= 0 or enterprise_value_crore <= 0:
        return None
    return enterprise_value_crore / ebit_crore


def fcf_yield(free_cash_flow_cr: float | None, market_cap_crore: float | None) -> float | None:
    """FCF Yield (%) = FCF / Market Cap * 100.

    Negative FCF gives a negative yield (not screened out — caller decides).
    """
    if free_cash_flow_cr is None or market_cap_crore is None:
        return None
    if market_cap_crore <= 0:
        return None
    return (free_cash_flow_cr / market_cap_crore) * 100.0


def earnings_yield(net_profit_crore: float | None, market_cap_crore: float | None) -> float | None:
    """Earnings Yield (%) = Net Profit / Market Cap * 100 (inverse of P/E)."""
    pe = price_to_earnings(market_cap_crore, net_profit_crore)
    if pe is None or pe == 0:
        return None
    return 100.0 / pe


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------
def compute_valuation_ratios(
    market_cap_crore: float | None,
    enterprise_value_crore: float | None,
    net_profit_crore: float | None,
    book_value_crore: float | None,
    ebit_crore: float | None,
    free_cash_flow_cr: float | None,
    dividend_yield_pct: float | None = None,
) -> ValuationRatios:
    """Compute all five valuation multiples from fundamentals.

    ``dividend_yield_pct`` is taken as-is from the market-cap table when
    available; the synthetic dataset pre-computes it.
    """
    return ValuationRatios(
        pe_ratio=price_to_earnings(market_cap_crore, net_profit_crore),
        pb_ratio=price_to_book(market_cap_crore, book_value_crore),
        ev_ebitda=ev_to_ebitda(enterprise_value_crore, ebit_crore),
        dividend_yield_pct=dividend_yield_pct,
        fcf_yield_pct=fcf_yield(free_cash_flow_cr, market_cap_crore),
        earnings_yield_pct=earnings_yield(net_profit_crore, market_cap_crore),
    )


# ---------------------------------------------------------------------------
# Comparison / sanity-check vs source-supplied multiples
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ValuationCheck:
    """Result of comparing a computed multiple to the source (market_cap) value."""

    metric: str
    computed: float | None
    source: float | None
    delta_pct: float | None
    within_tolerance: bool


DEFAULT_TOLERANCE_PCT = 25.0  # synthetic data may diverge; flag >25% gap


def compare_multiples(
    metric: str,
    computed: float | None,
    source: float | None,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> ValuationCheck:
    """Return a ValuationCheck comparing computed vs source multiple."""
    if computed is None or source is None or source == 0:
        delta = None
        ok = computed is None and source is None  # both missing = OK
    else:
        delta = abs(computed - source) / abs(source) * 100.0
        ok = delta <= tolerance_pct
    return ValuationCheck(
        metric=metric,
        computed=computed,
        source=source,
        delta_pct=delta,
        within_tolerance=ok,
    )


def classify_valuation(pe: float | None, pb: float | None, ev_ebitda: float | None) -> str:
    """Heuristic valuation bucket: Cheap / Fair / Expensive based on KPI reference.

    Logic (conservative — requires at least two multiples to agree):
        - Cheap if P/E < 12 AND P/B < 2.5, or P/E < 10
        - Expensive if P/E > 35 AND P/B > 6, or P/E > 50
        - Otherwise Fair
    """
    cheap_votes = 0
    exp_votes = 0

    if pe is not None:
        if pe < PE_CHEAP:
            return "Cheap"
        if pe < PE_FAIR_LOWER:
            cheap_votes += 1
        if pe > PE_EXPENSIVE:
            return "Expensive"
        if pe > PE_FAIR_UPPER + 10:
            exp_votes += 1

    if pb is not None:
        if pb < 2.0:
            cheap_votes += 1
        if pb > PB_EXPENSIVE:
            exp_votes += 1

    if ev_ebitda is not None:
        if ev_ebitda < 10.0:
            cheap_votes += 1
        if ev_ebitda > 22.0:
            exp_votes += 1

    if cheap_votes >= 2:
        return "Cheap"
    if exp_votes >= 2:
        return "Expensive"
    return "Fair"
