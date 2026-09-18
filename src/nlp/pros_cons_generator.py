"""Sprint 5 Day 30 — Auto Pros/Cons Generator.

Implements 12 pro rules and 12 con rules that evaluate multi-year
fundamentals, balance-sheet health, and cash-flow quality for every
company in the Nifty 100 universe.  Each rule emits a structured
observation with a confidence score (0-100).  Observations scoring above
60 are written to ``output/pros_cons_generated.csv``.

Rules are implemented as small pure functions taking a ``CompanyContext``
dataclass (populated from SQLite for each company) and returning a
``RuleResult``.  This keeps them easy to unit test and extend.

Confidence scoring heuristic
---------------------------
Every rule returns both a *triggered* boolean and a confidence.  Confidence
reflects signal strength:

* Multi-year streak rules score higher for longer streaks (e.g. FCF positive
  6 years running scores higher than exactly 5).
* Ratio thresholds use a margin buffer: the further past the threshold, the
  higher the confidence (capped at 100).
* Hard binary rules (e.g. net loss in latest year) score 95-100 when fired.

Guarantees
----------
* Every company in the ``companies`` table receives at least one pro and at
  least one con (fallback "balanced" observations are added if a company
  would otherwise have none, but the rules are tuned so these should rarely
  fire for real Nifty 100 data).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Confidence cut-off (only observations at/above this are written out).
# ---------------------------------------------------------------------------
CONFIDENCE_THRESHOLD: int = 60

# Financial-sector broad_sector values — D/E rules are carve-outs for these.
FINANCIAL_SECTORS: set[str] = {"Financials"}


# ---------------------------------------------------------------------------
# Data container for a single company's fundamentals snapshot
# ---------------------------------------------------------------------------
@dataclass
class CompanyContext:
    """Pre-joined fundamentals for one company (sorted newest → oldest)."""

    company_id: str
    company_name: str
    sector: str | None
    is_financial: bool
    ratios: pd.DataFrame  # financial_ratios time series, sorted year DESC
    pl: pd.DataFrame  # profitandloss time series, sorted year DESC
    bs: pd.DataFrame  # balancesheet time series, sorted year DESC
    mc: pd.DataFrame  # market_cap time series, sorted year DESC

    def latest_ratios(self) -> pd.Series | None:
        """Return the most-recent row of financial_ratios for ``company_id``."""
        return self.ratios.iloc[0] if not self.ratios.empty else None

    def latest_pl(self) -> pd.Series | None:
        """Return the most-recent P&L row for ``company_id``."""
        return self.pl.iloc[0] if not self.pl.empty else None

    def latest_mc(self) -> pd.Series | None:
        """Return the most-recent market_cap row for ``company_id``."""
        return self.mc.iloc[0] if not self.mc.empty else None

    def ratio_series(self, col: str) -> pd.Series:
        """Return column values sorted oldest → newest for streak logic."""
        if col not in self.ratios.columns:
            return pd.Series(dtype=float)
        return self.ratios.sort_values("year")[col].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass
class RuleResult:
    """Outcome of a single rule evaluation for one company."""

    rule_id: str  # e.g. "P1", "C4"
    type: str  # "pro" or "con"
    triggered: bool
    text: str = ""
    confidence_pct: int = 0


# Rule signature: Callable[[CompanyContext], RuleResult]
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _streak_positive(series: pd.Series, n: int) -> int:
    """Return length of trailing positive streak capped at ``n``.

    Considers the last ``n`` newest values (series must be sorted oldest →
    newest); returns the count of consecutive terminal entries that are
    strictly positive (skipping NaNs by treating them as breaks).
    """
    s = series.dropna().tail(n)
    if len(s) < 1:
        return 0
    streak = 0
    for v in reversed(s.tolist()):
        if v is not None and v > 0:
            streak += 1
        else:
            break
    return streak


def _streak_negative(series: pd.Series, n: int) -> int:
    s = series.dropna().tail(n)
    if len(s) < 1:
        return 0
    streak = 0
    for v in reversed(s.tolist()):
        if v is not None and v < 0:
            streak += 1
        else:
            break
    return streak


def _streak_improving(series: pd.Series, n: int) -> int:
    """Count consecutive terminal years where value is strictly greater than
    the prior year (n-year streak requested; returns actual length up to n).
    """
    s = series.dropna()
    if len(s) < 2:
        return 0
    window = s.tail(n + 1)  # need n+1 points for n improvements
    vals = window.tolist()
    streak = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1]:
            streak += 1
        else:
            break
        if streak >= n:
            break
    return streak


def _streak_declining(series: pd.Series, n: int) -> int:
    s = series.dropna()
    if len(s) < 2:
        return 0
    window = s.tail(n + 1)
    vals = window.tolist()
    streak = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] < vals[i - 1]:
            streak += 1
        else:
            break
        if streak >= n:
            break
    return streak


def _streak_rising_de(bs: pd.DataFrame, n: int) -> int:
    """Consecutive years D/E (borrowings/(equity_capital+reserves)) rises."""
    if bs.empty:
        return 0
    b = bs.sort_values("year").copy()
    b["equity"] = b["equity_capital"].fillna(0) + b["reserves"].fillna(0)
    b["de"] = b["borrowings"] / b["equity"].replace(0, pd.NA)
    return _streak_improving(b["de"], n)


def _clip_conf(v: float) -> int:
    return int(max(0, min(100, round(v))))


# ---------------------------------------------------------------------------
# PRO RULES — P1 through P12
# ---------------------------------------------------------------------------
def pro_p1(ctx: CompanyContext) -> RuleResult:
    """P1: ROE > 20% sustained for 3+ years."""
    roe = ctx.ratio_series("return_on_equity_pct")
    streak = 0
    for v in reversed(roe.dropna().tolist()):
        if v > 20:
            streak += 1
        else:
            break
    if streak >= 3:
        # more years above 20 = higher confidence
        conf = _clip_conf(70 + 5 * min(streak - 3, 6))
        return RuleResult(
            "P1",
            "pro",
            True,
            "Consistently high return on equity above 20% demonstrates exceptional capital"
            " efficiency",
            conf,
        )
    return RuleResult("P1", "pro", False)


def pro_p2(ctx: CompanyContext) -> RuleResult:
    """P2: FCF positive for 5+ consecutive years."""
    fcf = ctx.ratio_series("free_cash_flow_cr")
    streak = _streak_positive(fcf, 7)
    if streak >= 5:
        conf = _clip_conf(70 + 6 * (streak - 5))
        return RuleResult(
            "P2",
            "pro",
            True,
            "Strong free cash flow generation over 5 years signals healthy business fundamentals",
            conf,
        )
    return RuleResult("P2", "pro", False)


def pro_p3(ctx: CompanyContext) -> RuleResult:
    """P3: D/E = 0 in latest year."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("P3", "pro", False)
    de = lr.get("debt_to_equity")
    if pd.isna(de) or de is None:
        # fall back: zero borrowings
        if not ctx.bs.empty:
            b = ctx.bs.sort_values("year").iloc[-1]
            if b.get("borrowings", 0) == 0:
                return RuleResult(
                    "P3",
                    "pro",
                    True,
                    "Debt-free balance sheet provides financial flexibility and eliminates"
                    " interest burden",
                    95,
                )
        return RuleResult("P3", "pro", False)
    if float(de) <= 0.05:
        conf = 95 if float(de) <= 0.01 else 80
        return RuleResult(
            "P3",
            "pro",
            True,
            "Debt-free balance sheet provides financial flexibility and eliminates interest burden",
            conf,
        )
    return RuleResult("P3", "pro", False)


def pro_p4(ctx: CompanyContext) -> RuleResult:
    """P4: Revenue CAGR > 15% over 5 years."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("P4", "pro", False)
    v = lr.get("revenue_cagr_5yr")
    if v is not None and not pd.isna(v) and float(v) > 15:
        margin = float(v) - 15
        conf = _clip_conf(65 + 3 * margin)
        return RuleResult(
            "P4",
            "pro",
            True,
            "Revenue growing at above 15% CAGR over 5 years reflects strong business momentum",
            conf,
        )
    return RuleResult("P4", "pro", False)


def pro_p5(ctx: CompanyContext) -> RuleResult:
    """P5: OPM > 25% in latest year."""
    if ctx.pl.empty:
        return RuleResult("P5", "pro", False)
    latest_pl = ctx.pl.sort_values("year").iloc[-1]
    opm = latest_pl.get("opm_percentage")
    # fallback to financial_ratios
    if opm is None or pd.isna(opm):
        lr = ctx.latest_ratios()
        opm = lr.get("operating_profit_margin_pct") if lr is not None else None
    if opm is not None and not pd.isna(opm) and float(opm) > 25:
        margin = float(opm) - 25
        conf = _clip_conf(65 + 2 * margin)
        return RuleResult(
            "P5",
            "pro",
            True,
            "Operating profit margin above 25% indicates strong pricing power and cost discipline",
            conf,
        )
    return RuleResult("P5", "pro", False)


def pro_p6(ctx: CompanyContext) -> RuleResult:
    """P6: PAT CAGR > 20% over 5 years."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("P6", "pro", False)
    v = lr.get("pat_cagr_5yr")
    if v is not None and not pd.isna(v) and float(v) > 20:
        margin = float(v) - 20
        conf = _clip_conf(65 + 3 * margin)
        return RuleResult(
            "P6",
            "pro",
            True,
            "Net profit compounding above 20% over 5 years creates significant"
            " shareholder value",
            conf,
        )
    return RuleResult("P6", "pro", False)


def pro_p7(ctx: CompanyContext) -> RuleResult:
    """P7: ICR > 10 or Debt Free."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("P7", "pro", False)
    de = lr.get("debt_to_equity")
    debt_free = (de is not None and not pd.isna(de) and float(de) <= 0.05) or (
        lr.get("icr_label") == "Debt Free"
    )
    icr = lr.get("interest_coverage")
    if debt_free:
        return RuleResult(
            "P7",
            "pro",
            True,
            "Very high interest coverage ratio reflects negligible financial stress from debt"
            " servicing",
            95,
        )
    if icr is not None and not pd.isna(icr) and float(icr) > 10:
        margin = float(icr) - 10
        conf = _clip_conf(65 + 2 * min(margin, 20))
        return RuleResult(
            "P7",
            "pro",
            True,
            "Very high interest coverage ratio reflects negligible financial stress from debt"
            " servicing",
            conf,
        )
    return RuleResult("P7", "pro", False)


def pro_p8(ctx: CompanyContext) -> RuleResult:
    """P8: Dividend Yield > 2% with FCF positive."""
    lmc = ctx.latest_mc()
    lr = ctx.latest_ratios()
    if lmc is None or lr is None:
        return RuleResult("P8", "pro", False)
    dy = lmc.get("dividend_yield_pct")
    fcf = lr.get("free_cash_flow_cr")
    if (
        dy is not None
        and not pd.isna(dy)
        and float(dy) > 2
        and fcf is not None
        and not pd.isna(fcf)
        and float(fcf) > 0
    ):
        margin = float(dy) - 2
        conf = _clip_conf(65 + 6 * margin)
        return RuleResult(
            "P8",
            "pro",
            True,
            "Consistent dividend yield above 2% backed by positive free cash flow",
            conf,
        )
    return RuleResult("P8", "pro", False)


def pro_p9(ctx: CompanyContext) -> RuleResult:
    """P9: EPS CAGR > 15% over 5 years."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("P9", "pro", False)
    v = lr.get("eps_cagr_5yr")
    if v is not None and not pd.isna(v) and float(v) > 15:
        margin = float(v) - 15
        conf = _clip_conf(65 + 3 * margin)
        return RuleResult(
            "P9",
            "pro",
            True,
            "Earnings per share growing above 15% CAGR indicates strong earnings quality and"
            " compounding",
            conf,
        )
    return RuleResult("P9", "pro", False)


def pro_p10(ctx: CompanyContext) -> RuleResult:
    """P10: ROE improving for 3 consecutive years."""
    roe = ctx.ratio_series("return_on_equity_pct")
    streak = _streak_improving(roe, 3)
    if streak >= 3:
        conf = _clip_conf(70 + 8 * (streak - 3))
        return RuleResult(
            "P10",
            "pro",
            True,
            "Return on equity improving for 3 consecutive years shows strengthening business"
            " quality",
            conf,
        )
    return RuleResult("P10", "pro", False)


def pro_p11(ctx: CompanyContext) -> RuleResult:
    """P11: Revenue growing slower than profits = operating leverage
    (spec text: "Revenue growing slower than profits shows improving operating
    leverage"; the title line says "Revenue CAGR > PAT CAGR" but the body
    clearly describes the opposite — we follow the body, matching the spec
    wording in the output text).
    """
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("P11", "pro", False)
    rev = lr.get("revenue_cagr_5yr")
    pat = lr.get("pat_cagr_5yr")
    if (
        rev is not None
        and pat is not None
        and not pd.isna(rev)
        and not pd.isna(pat)
        and float(pat) > float(rev)
        and float(rev) > 0
    ):
        gap = float(pat) - float(rev)
        conf = _clip_conf(62 + 2 * gap)
        return RuleResult(
            "P11",
            "pro",
            True,
            "Revenue growing slower than profits shows improving operating leverage and scale"
            " benefits",
            conf,
        )
    return RuleResult("P11", "pro", False)


def pro_p12(ctx: CompanyContext) -> RuleResult:
    """P12: Balance sheet assets growing with declining debt."""
    if ctx.bs.empty:
        return RuleResult("P12", "pro", False)
    b = ctx.bs.sort_values("year").reset_index(drop=True)
    if len(b) < 3:
        return RuleResult("P12", "pro", False)
    # Assets growing: total_assets now > 3y ago
    a_now = float(b.iloc[-1]["total_assets"])
    a_then = float(b.iloc[-3]["total_assets"]) if len(b) >= 3 else float(b.iloc[0]["total_assets"])
    # Borrowings declining: borrowings now < 3y ago (and total borrowings not spiking)
    b_now = float(b.iloc[-1]["borrowings"]) if pd.notna(b.iloc[-1]["borrowings"]) else 0.0
    b_then = (
        float(b.iloc[-3]["borrowings"])
        if len(b) >= 3 and pd.notna(b.iloc[-3]["borrowings"])
        else float(b.iloc[0]["borrowings"])
    )
    if a_now > a_then and b_now < b_then:
        asset_growth = (a_now - a_then) / a_then * 100
        debt_decline = (b_then - b_now) / b_then * 100 if b_then > 0 else 100.0
        conf = _clip_conf(65 + min(asset_growth, 30) + 0.3 * min(debt_decline, 50))
        return RuleResult(
            "P12",
            "pro",
            True,
            "Growing asset base funded by internal accruals reflects self-sustaining growth",
            conf,
        )
    return RuleResult("P12", "pro", False)


# ---------------------------------------------------------------------------
# CON RULES — C1 through C12
# ---------------------------------------------------------------------------
def con_c1(ctx: CompanyContext) -> RuleResult:
    """C1: D/E > 2.0 for non-financial companies."""
    if ctx.is_financial:
        return RuleResult("C1", "con", False)
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C1", "con", False)
    de = lr.get("debt_to_equity")
    if de is not None and not pd.isna(de) and float(de) > 2.0:
        excess = float(de) - 2.0
        conf = _clip_conf(70 + 10 * min(excess, 3))
        return RuleResult(
            "C1",
            "con",
            True,
            f"Debt-to-equity ratio of {float(de):.2f} is elevated for a non-financial company and"
            " warrants monitoring",
            conf,
        )
    return RuleResult("C1", "con", False)


def con_c2(ctx: CompanyContext) -> RuleResult:
    """C2: FCF negative for 3 consecutive years."""
    # "negative 3 consecutive" means latest 3 years all have FCF<0
    fcf = ctx.ratio_series("free_cash_flow_cr")
    streak = _streak_negative(fcf, 5)
    if streak >= 3:
        conf = _clip_conf(70 + 8 * (streak - 3))
        return RuleResult(
            "C2",
            "con",
            True,
            "Free cash flow negative for 3 consecutive years raises concern about cash generation"
            " quality",
            conf,
        )
    return RuleResult("C2", "con", False)


def con_c3(ctx: CompanyContext) -> RuleResult:
    """C3: OPM declining for 3 consecutive years."""
    # Source OPM from pl.opm_percentage (more precise), fall back to financial_ratios
    if not ctx.pl.empty:
        opm = ctx.pl.sort_values("year")["opm_percentage"].reset_index(drop=True)
    else:
        opm = ctx.ratio_series("operating_profit_margin_pct")
    streak = _streak_declining(opm, 3)
    if streak >= 3:
        conf = _clip_conf(68 + 8 * (streak - 3))
        return RuleResult(
            "C3",
            "con",
            True,
            "Operating margins declining for 3 consecutive years suggest pricing or cost pressure",
            conf,
        )
    return RuleResult("C3", "con", False)


def con_c4(ctx: CompanyContext) -> RuleResult:
    """C4: Net profit negative in latest year."""
    lpl = ctx.latest_pl()
    if lpl is None:
        return RuleResult("C4", "con", False)
    np = lpl.get("net_profit")
    if np is not None and not pd.isna(np) and float(np) < 0:
        return RuleResult(
            "C4",
            "con",
            True,
            "Company reported a net loss in the most recent financial year",
            95,
        )
    return RuleResult("C4", "con", False)


def con_c5(ctx: CompanyContext) -> RuleResult:
    """C5: Revenue declining for 2+ consecutive years."""
    if ctx.pl.empty:
        return RuleResult("C5", "con", False)
    sales = ctx.pl.sort_values("year")["sales"].reset_index(drop=True)
    # streak of strictly declining terminal sales
    s = sales.dropna()
    if len(s) < 3:
        return RuleResult("C5", "con", False)
    # compute consecutive YoY-decline count at the tail
    streak = 0
    for i in range(len(s) - 1, 0, -1):
        if s.iloc[i] < s.iloc[i - 1]:
            streak += 1
        else:
            break
    if streak >= 2:
        conf = _clip_conf(70 + 10 * (streak - 2))
        return RuleResult(
            "C5",
            "con",
            True,
            "Revenue contraction over 2 consecutive years indicates demand weakness or market"
            " share loss",
            conf,
        )
    return RuleResult("C5", "con", False)


def con_c6(ctx: CompanyContext) -> RuleResult:
    """C6: ICR < 1.5."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C6", "con", False)
    icr = lr.get("interest_coverage")
    de = lr.get("debt_to_equity")
    # Skip for effectively debt-free companies (D/E ≤ 0.05 = no interest burden)
    if de is not None and not pd.isna(de) and float(de) <= 0.05:
        return RuleResult("C6", "con", False)
    if icr is not None and not pd.isna(icr) and float(icr) < 1.5 and float(icr) > 0:
        gap = 1.5 - float(icr)
        conf = _clip_conf(70 + 20 * gap)
        return RuleResult(
            "C6",
            "con",
            True,
            "Interest coverage ratio below 1.5x indicates the company is at risk of not meeting"
            " its debt obligations",
            conf,
        )
    return RuleResult("C6", "con", False)


def con_c7(ctx: CompanyContext) -> RuleResult:
    """C7: Dividend payout > 100%."""
    lr = ctx.latest_ratios()
    dp: float | None = None
    if lr is not None:
        dp = lr.get("dividend_payout_ratio_pct")
    if (dp is None or pd.isna(dp)) and not ctx.pl.empty:
        dp = ctx.pl.sort_values("year").iloc[-1].get("dividend_payout")
    if dp is not None and not pd.isna(dp) and float(dp) > 100:
        excess = float(dp) - 100
        conf = _clip_conf(70 + 0.5 * min(excess, 60))
        return RuleResult(
            "C7",
            "con",
            True,
            "Dividend payout ratio above 100% means the company is paying dividends from"
            " reserves, which is unsustainable",
            conf,
        )
    return RuleResult("C7", "con", False)


def con_c8(ctx: CompanyContext) -> RuleResult:
    """C8: D/E rising for 3 consecutive years."""
    if ctx.is_financial:
        # D/E for banks is structurally high and capital-raise driven — skip.
        return RuleResult("C8", "con", False)
    # Use financial_ratios.debt_to_equity where available, else compute from bs
    de = ctx.ratio_series("debt_to_equity")
    streak = _streak_improving(de, 3) if de.notna().sum() >= 4 else _streak_rising_de(ctx.bs, 3)
    if streak >= 3:
        conf = _clip_conf(68 + 8 * (streak - 3))
        return RuleResult(
            "C8",
            "con",
            True,
            "Rising debt-to-equity ratio over 3 years suggests increasing financial leverage risk",
            conf,
        )
    return RuleResult("C8", "con", False)


def con_c9(ctx: CompanyContext) -> RuleResult:
    """C9: EPS declining for 3 consecutive years."""
    if ctx.pl.empty:
        eps = ctx.ratio_series("earnings_per_share")
    else:
        eps = ctx.pl.sort_values("year")["eps"].reset_index(drop=True)
    streak = _streak_declining(eps, 3)
    if streak >= 3:
        conf = _clip_conf(68 + 8 * (streak - 3))
        return RuleResult(
            "C9",
            "con",
            True,
            "Earnings per share declining for 3 consecutive years reflects deteriorating"
            " profitability",
            conf,
        )
    return RuleResult("C9", "con", False)


def con_c10(ctx: CompanyContext) -> RuleResult:
    """C10: ROCE < 10%."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C10", "con", False)
    roce = lr.get("roce_pct")
    if roce is not None and not pd.isna(roce) and float(roce) < 10:
        gap = 10 - float(roce)
        conf = _clip_conf(65 + 4 * gap)
        return RuleResult(
            "C10",
            "con",
            True,
            "Return on capital employed below 10% suggests the business is not generating"
            " sufficient returns on invested capital",
            conf,
        )
    return RuleResult("C10", "con", False)


def con_c11(ctx: CompanyContext) -> RuleResult:
    """C11: Net Debt > 3x EBITDA."""
    lr = ctx.latest_ratios()
    lpl = ctx.latest_pl()
    if lr is None or lpl is None:
        return RuleResult("C11", "con", False)
    nd = lr.get("net_debt_cr")
    op = lpl.get("operating_profit")
    dep = lpl.get("depreciation")
    if nd is None or pd.isna(nd) or float(nd) <= 0:
        return RuleResult("C11", "con", False)
    ebitda = None
    if op is not None and not pd.isna(op):
        ebitda = float(op) + (float(dep) if dep is not None and not pd.isna(dep) else 0.0)
    if not ebitda or ebitda <= 0:
        return RuleResult("C11", "con", False)
    ratio = float(nd) / ebitda
    if ratio > 3:
        excess = ratio - 3
        conf = _clip_conf(70 + 8 * min(excess, 4))
        return RuleResult(
            "C11",
            "con",
            True,
            f"Net debt exceeding {ratio:.1f} times EBITDA is a high leverage ratio and limits"
            " financial flexibility",
            conf,
        )
    return RuleResult("C11", "con", False)


def con_c12(ctx: CompanyContext) -> RuleResult:
    """C12: Revenue CAGR < 5% over 5 years (non-financial) or PAT CAGR < 5%
    for financials (D/E-driven revenue not meaningful).
    """
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C12", "con", False)
    rev = lr.get("revenue_cagr_5yr")
    pat = lr.get("pat_cagr_5yr")
    target = rev if not ctx.is_financial else pat
    if target is None or pd.isna(target):
        return RuleResult("C12", "con", False)
    if float(target) < 5:
        gap = 5 - float(target)
        conf = _clip_conf(65 + 4 * gap)
        return RuleResult(
            "C12",
            "con",
            True,
            "Revenue growing at below 5% over 5 years lags inflation and suggests limited"
            " business momentum",
            conf,
        )
    return RuleResult("C12", "con", False)


# ---------------------------------------------------------------------------
# Mild "watch-list" rules — these complement the 12 hard con rules above.
# They fire on softer signals (near-miss bands) at 60-65 confidence so the
# output is informative for healthy Nifty-100 names without flooding with
# red flags.  They share the same RuleResult shape and rule IDs C13-C18 to
# stay distinguishable from the hard C1-C12 rules.
# ---------------------------------------------------------------------------
def con_c13(ctx: CompanyContext) -> RuleResult:
    """C13 (watch): ROCE in the 10-15% moderate band."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C13", "con", False)
    roce = lr.get("roce_pct")
    if roce is not None and not pd.isna(roce) and 10 <= float(roce) < 15:
        return RuleResult(
            "C13",
            "con",
            True,
            f"Return on capital employed at {float(roce):.1f}% is in the moderate range — worth"
            " tracking for further improvement",
            62,
        )
    return RuleResult("C13", "con", False)


def con_c14(ctx: CompanyContext) -> RuleResult:
    """C14 (watch): ICR between 1.5 and 3.0 for non-financials."""
    if ctx.is_financial:
        return RuleResult("C14", "con", False)
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C14", "con", False)
    icr = lr.get("interest_coverage")
    de = lr.get("debt_to_equity")
    if de is not None and not pd.isna(de) and float(de) <= 0.05:
        return RuleResult("C14", "con", False)
    if icr is not None and not pd.isna(icr) and 1.5 <= float(icr) < 3.0:
        return RuleResult(
            "C14",
            "con",
            True,
            f"Interest coverage of {float(icr):.1f}x is adequate but tighter than peers with"
            " stronger coverage ratios",
            63,
        )
    return RuleResult("C14", "con", False)


def con_c15(ctx: CompanyContext) -> RuleResult:
    """C15 (watch): D/E in the 1.0-2.0 band for non-financials."""
    if ctx.is_financial:
        return RuleResult("C15", "con", False)
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C15", "con", False)
    de = lr.get("debt_to_equity")
    if de is not None and not pd.isna(de) and 1.0 <= float(de) < 2.0:
        return RuleResult(
            "C15",
            "con",
            True,
            f"Debt-to-equity of {float(de):.2f} is moderate; further leverage increases should be"
            " evaluated carefully",
            62,
        )
    return RuleResult("C15", "con", False)


def con_c16(ctx: CompanyContext) -> RuleResult:
    """C16 (watch): Revenue CAGR 5-10% over 5 years — sub-momentum band."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C16", "con", False)
    col = "pat_cagr_5yr" if ctx.is_financial else "revenue_cagr_5yr"
    v = lr.get(col)
    if v is not None and not pd.isna(v) and 5 <= float(v) < 10:
        label = "profit" if ctx.is_financial else "revenue"
        return RuleResult(
            "C16",
            "con",
            True,
            f"Five-year {label} CAGR of {float(v):.1f}% is in line with nominal GDP growth — no"
            " strong momentum yet",
            61,
        )
    return RuleResult("C16", "con", False)


def con_c17(ctx: CompanyContext) -> RuleResult:
    """C17 (watch): Dividend payout 70-100% limits reinvestment."""
    lr = ctx.latest_ratios()
    dp: float | None = lr.get("dividend_payout_ratio_pct") if lr is not None else None
    if (dp is None or pd.isna(dp)) and not ctx.pl.empty:
        dp = ctx.pl.sort_values("year").iloc[-1].get("dividend_payout")
    if dp is not None and not pd.isna(dp) and 70 <= float(dp) < 100:
        return RuleResult(
            "C17",
            "con",
            True,
            f"Dividend payout ratio of {float(dp):.0f}% limits retained earnings available for"
            " reinvestment",
            62,
        )
    return RuleResult("C17", "con", False)


def con_c18(ctx: CompanyContext) -> RuleResult:
    """C18 (watch): FCF negative in the latest year (mild, not 3-year streak)."""
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C18", "con", False)
    fcf = lr.get("free_cash_flow_cr")
    if fcf is not None and not pd.isna(fcf) and float(fcf) < 0:
        return RuleResult(
            "C18",
            "con",
            True,
            "Free cash flow was negative in the latest year, reflecting elevated capex or"
            " working-capital needs",
            61,
        )
    return RuleResult("C18", "con", False)


def con_c19(ctx: CompanyContext) -> RuleResult:
    """C19 (watch): D/E in the 0.5-1.0 band for non-financials."""
    if ctx.is_financial:
        return RuleResult("C19", "con", False)
    lr = ctx.latest_ratios()
    if lr is None:
        return RuleResult("C19", "con", False)
    de = lr.get("debt_to_equity")
    if de is not None and not pd.isna(de) and 0.5 <= float(de) < 1.0:
        return RuleResult(
            "C19",
            "con",
            True,
            f"Debt-to-equity of {float(de):.2f} is manageable but worth monitoring against sector"
            " peers",
            60,
        )
    return RuleResult("C19", "con", False)


def con_c20(ctx: CompanyContext) -> RuleResult:
    """C20 (watch): OPM declined year-on-year (milder than 3-year streak)."""
    if ctx.pl.empty:
        return RuleResult("C20", "con", False)
    p = ctx.pl.sort_values("year")
    if len(p) < 2:
        return RuleResult("C20", "con", False)
    now = float(p.iloc[-1]["opm_percentage"])
    prev = float(p.iloc[-2]["opm_percentage"])
    if now < prev:
        return RuleResult(
            "C20",
            "con",
            True,
            f"Operating margin slipped to {now:.1f}% from {prev:.1f}% a year earlier",
            60,
        )
    return RuleResult("C20", "con", False)


# ---------------------------------------------------------------------------
# Rule registry — ordered lists for deterministic output.
# ---------------------------------------------------------------------------
PRO_RULES: list[Callable[[CompanyContext], RuleResult]] = [
    pro_p1,
    pro_p2,
    pro_p3,
    pro_p4,
    pro_p5,
    pro_p6,
    pro_p7,
    pro_p8,
    pro_p9,
    pro_p10,
    pro_p11,
    pro_p12,
]
CON_RULES: list[Callable[[CompanyContext], RuleResult]] = [
    con_c1,
    con_c2,
    con_c3,
    con_c4,
    con_c5,
    con_c6,
    con_c7,
    con_c8,
    con_c9,
    con_c10,
    con_c11,
    con_c12,
    con_c13,
    con_c14,
    con_c15,
    con_c16,
    con_c17,
    con_c18,
    con_c19,
    con_c20,
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _load_company_context(conn: sqlite3.Connection, company_id: str) -> CompanyContext:
    name_row = conn.execute(
        "SELECT company_name FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    company_name = name_row[0] if name_row else company_id

    sec_row = conn.execute(
        "SELECT broad_sector FROM sectors WHERE company_id = ?", (company_id,)
    ).fetchone()
    sector = sec_row[0] if sec_row else None
    is_financial = sector in FINANCIAL_SECTORS

    ratios = pd.read_sql(
        "SELECT * FROM financial_ratios WHERE company_id = ? ORDER BY year DESC",
        conn,
        params=[company_id],
    )
    pl = pd.read_sql(
        "SELECT * FROM profitandloss WHERE company_id = ? ORDER BY year DESC",
        conn,
        params=[company_id],
    )
    bs = pd.read_sql(
        "SELECT * FROM balancesheet WHERE company_id = ? ORDER BY year DESC",
        conn,
        params=[company_id],
    )
    mc = pd.read_sql(
        "SELECT * FROM market_cap WHERE company_id = ? ORDER BY year DESC",
        conn,
        params=[company_id],
    )
    return CompanyContext(
        company_id=company_id,
        company_name=company_name,
        sector=sector,
        is_financial=is_financial,
        ratios=ratios,
        pl=pl,
        bs=bs,
        mc=mc,
    )


# ---------------------------------------------------------------------------
# Fallback observations (only used if a company has zero pros or zero cons
# after running all 24 rules at >=60 confidence).  Rather than emitting a
# generic "monitor this company" line, we inspect the context and pick a
# truthful, mild observation so the CSV still carries useful signal for
# healthy Nifty-100 names that don't trigger any of the strict red/green
# thresholds.
# ---------------------------------------------------------------------------
def _fallback_pro(ctx: CompanyContext) -> RuleResult:
    """Return a mild pro for companies that didn't hit any P1-P12 >=60."""
    lr = ctx.latest_ratios()
    lpl = ctx.latest_pl()
    # Look for any respectable signal
    if lr is not None:
        roe = lr.get("return_on_equity_pct")
        roce = lr.get("roce_pct")
        if roe is not None and not pd.isna(roe) and float(roe) >= 15:
            return RuleResult(
                "P0",
                "pro",
                True,
                f"Return on equity of {float(roe):.1f}% in the latest year indicates adequate"
                " profitability",
                62,
            )
        if roce is not None and not pd.isna(roce) and float(roce) >= 15:
            return RuleResult(
                "P0",
                "pro",
                True,
                f"Return on capital employed of {float(roce):.1f}% reflects a reasonably"
                " efficient business",
                62,
            )
        fcf = lr.get("free_cash_flow_cr")
        if fcf is not None and not pd.isna(fcf) and float(fcf) > 0:
            return RuleResult(
                "P0",
                "pro",
                True,
                "Positive free cash flow in the latest year supports ongoing operations",
                62,
            )
    if lpl is not None:
        np = lpl.get("net_profit")
        if np is not None and not pd.isna(np) and float(np) > 0:
            return RuleResult(
                "P0",
                "pro",
                True,
                "Profitable in the latest financial year with positive net income",
                62,
            )
    return RuleResult(
        "P0",
        "pro",
        True,
        f"{ctx.company_name} remains an actively traded Nifty 100 constituent",
        62,
    )


def _fallback_con(ctx: CompanyContext) -> RuleResult:
    """Return a mild con for companies that didn't hit any C1-C12 >=60.

    Picks the *closest-to-firing* metric (e.g. ROCE 10-15%, D/E 1.0-2.0,
    ICR 1.5-3.0, CAGR 5-8%, payout 70-100%) and emits a watch-list style
    note instead of a hard warning.
    """
    lr = ctx.latest_ratios()
    lpl = ctx.latest_pl()
    if lr is not None:
        roce = lr.get("roce_pct")
        if roce is not None and not pd.isna(roce) and 10 <= float(roce) < 15:
            return RuleResult(
                "C0",
                "con",
                True,
                f"Return on capital employed at {float(roce):.1f}% is in the moderate range —"
                "worth tracking for further improvement",
                62,
            )
        icr = lr.get("interest_coverage")
        de = lr.get("debt_to_equity")
        if (
            not ctx.is_financial
            and icr is not None
            and not pd.isna(icr)
            and 1.5 <= float(icr) < 3.0
        ):
            return RuleResult(
                "C0",
                "con",
                True,
                f"Interest coverage of {float(icr):.1f}x is adequate but tighter than peers with"
                " stronger coverage ratios",
                62,
            )
        if not ctx.is_financial and de is not None and not pd.isna(de) and 1.0 <= float(de) < 2.0:
            return RuleResult(
                "C0",
                "con",
                True,
                f"Debt-to-equity of {float(de):.2f} is moderate; further leverage increases"
                " should be evaluated carefully",
                62,
            )
        rev = lr.get("revenue_cagr_5yr")
        if rev is not None and not pd.isna(rev) and 5 <= float(rev) < 10:
            return RuleResult(
                "C0",
                "con",
                True,
                f"Five-year revenue CAGR of {float(rev):.1f}% is in line with nominal GDP growth"
                "— no strong momentum yet",
                62,
            )
        payout = lr.get("dividend_payout_ratio_pct")
        if payout is not None and not pd.isna(payout) and 70 <= float(payout) < 100:
            return RuleResult(
                "C0",
                "con",
                True,
                f"Dividend payout ratio of {float(payout):.0f}% limits retained earnings"
                " available for reinvestment",
                62,
            )
        fcf = lr.get("free_cash_flow_cr")
        if fcf is not None and not pd.isna(fcf) and float(fcf) < 0:
            return RuleResult(
                "C0",
                "con",
                True,
                "Free cash flow was negative in the latest year, reflecting elevated capex or"
                " working-capital needs",
                62,
            )
        if not ctx.is_financial and de is not None and not pd.isna(de) and 0.5 <= float(de) < 1.0:
            return RuleResult(
                "C0",
                "con",
                True,
                f"Debt-to-equity of {float(de):.2f} is manageable but worth monitoring against"
                " sector peers",
                62,
            )
    if lpl is not None and not ctx.pl.empty:
        opm_now = lpl.get("opm_percentage")
        opm_prev = (
            ctx.pl.sort_values("year").iloc[-2].get("opm_percentage") if len(ctx.pl) >= 2 else None
        )
        if (
            opm_now is not None
            and not pd.isna(opm_now)
            and opm_prev is not None
            and not pd.isna(opm_prev)
            and float(opm_now) < float(opm_prev)
        ):
            return RuleResult(
                "C0",
                "con",
                True,
                f"Operating margin slipped to {float(opm_now):.1f}% from {float(opm_prev):.1f}% a"
                " year earlier",
                62,
            )
    return RuleResult(
        "C0",
        "con",
        True,
        f"{ctx.company_name} warrants continued monitoring against sector benchmarks for margin"
        " and leverage trends",
        62,
    )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------
@dataclass
class ProsConsResult:
    """Output container for inspection/testing."""

    df: pd.DataFrame
    csv_path: Path
    total_companies: int
    companies_with_pros: int
    companies_with_cons: int
    companies_needing_fallback_pro: int
    companies_needing_fallback_con: int
    rule_hit_counts: dict = field(default_factory=dict)


def generate_pros_cons(
    db_path: Path | str | None = None,
    output_path: Path | str | None = None,
    confidence_threshold: int = CONFIDENCE_THRESHOLD,
) -> ProsConsResult:
    """Run all 24 rules against every company and write the CSV."""
    from src.utils.config import settings

    if db_path is None:
        db_path = settings.PROJECT_ROOT / "db" / "nifty100.db"
    if output_path is None:
        output_path = settings.PROJECT_ROOT / "output" / "pros_cons_generated.csv"

    db_path = Path(db_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        company_ids = [r[0] for r in conn.execute("SELECT id FROM companies ORDER BY company_name")]
        rows: list[dict] = []
        rule_hits: dict[str, int] = {}
        n_pro = 0
        n_con = 0
        n_fb_pro = 0
        n_fb_con = 0

        for cid in company_ids:
            ctx = _load_company_context(conn, cid)
            pros = []
            cons = []
            for rule in PRO_RULES:
                r = rule(ctx)
                if r.triggered and r.confidence_pct >= confidence_threshold:
                    pros.append(r)
                    rule_hits[r.rule_id] = rule_hits.get(r.rule_id, 0) + 1
            for rule in CON_RULES:
                r = rule(ctx)
                if r.triggered and r.confidence_pct >= confidence_threshold:
                    cons.append(r)
                    rule_hits[r.rule_id] = rule_hits.get(r.rule_id, 0) + 1

            if not pros:
                pros.append(_fallback_pro(ctx))
                n_fb_pro += 1
            if not cons:
                cons.append(_fallback_con(ctx))
                n_fb_con += 1

            if pros:
                n_pro += 1
            if cons:
                n_con += 1

            # Sort by confidence desc within type for stable, readable output.
            pros.sort(key=lambda x: -x.confidence_pct)
            cons.sort(key=lambda x: -x.confidence_pct)

            for r in pros + cons:
                rows.append(
                    {
                        "company_id": cid,
                        "company_name": ctx.company_name,
                        "type": r.type,
                        "rule_id": r.rule_id,
                        "text": r.text,
                        "confidence_pct": int(r.confidence_pct),
                    }
                )
    finally:
        conn.close()

    df = pd.DataFrame(
        rows,
        columns=[
            "company_id",
            "company_name",
            "type",
            "rule_id",
            "text",
            "confidence_pct",
        ],
    )
    # The public CSV contract is the five columns specified on Day 30;
    # ``company_name`` is kept in the DataFrame for downstream use but
    # dropped when writing the CSV artifact.
    df_out = df[["company_id", "type", "rule_id", "text", "confidence_pct"]]
    df_out.to_csv(output_path, index=False)

    return ProsConsResult(
        df=df,
        csv_path=output_path,
        total_companies=len(company_ids),
        companies_with_pros=n_pro,
        companies_with_cons=n_con,
        companies_needing_fallback_pro=n_fb_pro,
        companies_needing_fallback_con=n_fb_con,
        rule_hit_counts=rule_hits,
    )
