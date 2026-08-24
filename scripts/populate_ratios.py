"""Populate the financial_ratios table for all 92 Nifty 100 companies.

Joins profitandloss, balancesheet, cashflow, companies, and sectors; runs all
ratio engines built in Days 8-11; computes 5-yr CAGRs (Day 10) and the
Composite Quality Score (0-100, P10/P90 winsorised) per spec section 13; writes
the result to the financial_ratios table via the idempotent merge upsert.

Usage:
    python -m scripts.populate_ratios            # populate using default DB
    python -m scripts.populate_ratios --reset    # truncate first, then reload
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning, module="pandas")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.analytics.cagr import (  # noqa: E402
    cagr,
)
from src.analytics.cashflow_kpis import (  # noqa: E402
    capex_intensity,
    capex_tier,
    cfo_pat_ratio,
    classify_capital_allocation,
    fcf_conversion,
    free_cash_flow,
)
from src.analytics.leverage import (  # noqa: E402
    asset_turnover,
    debt_to_equity,
    high_leverage_flag,
    icr_display_label,
    icr_warning_flag,
    interest_coverage_ratio,
    net_debt,
)
from src.analytics.ratios import (  # noqa: E402
    compute_profitability_ratios,
    is_financial_sector,
)
from src.etl.database import (  # noqa: E402
    get_connection,
    init_schema,
    load_dataframe,
    reset_tables,
    write_load_audit,
)
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Composite Quality Score weights (spec section 13):
#   0.30 * ROE + 0.25 * FCF + 0.25 * ROCE + 0.20 * DE
# For sub-scores we winsorise at P10/P90 and linearly scale to 0-100.
# The DE sub-score is inverted (lower D/E -> higher score).
# ---------------------------------------------------------------------------
COMPOSITE_WEIGHTS = {
    "roe": 0.30,
    "fcf": 0.25,
    "roce": 0.25,
    "de": 0.20,
}
WINSOR_LOW_PCT = 10
WINSOR_HIGH_PCT = 90


def _winsor_score(
    values: pd.Series,
    higher_is_better: bool = True,
) -> pd.Series:
    """Map raw metric values to a 0-100 sub-score using P10/P90 winsorisation.

    * Values at or beyond P10 map to 0 (if higher_is_better) or 100.
    * Values at or beyond P90 map to 100 (if higher_is_better) or 0.
    * Linear interpolation between P10 and P90.
    * NaN values propagate as NaN (they become 0 weight in composite).
    """
    s = pd.to_numeric(values, errors="coerce").astype(float)
    p_low = np.nanpercentile(s, WINSOR_LOW_PCT)
    p_high = np.nanpercentile(s, WINSOR_HIGH_PCT)
    if p_high == p_low:
        # Degenerate — all identical in the winsor band → midpoint score.
        return pd.Series(np.where(s.isna(), np.nan, 50.0), index=s.index)
    if higher_is_better:
        clipped = s.clip(lower=p_low, upper=p_high)
        scaled = (clipped - p_low) / (p_high - p_low) * 100.0
    else:
        # Lower is better: invert so that low values → high score.
        clipped = s.clip(lower=p_low, upper=p_high)
        scaled = (p_high - clipped) / (p_high - p_low) * 100.0
    return scaled


def _fetch_source_data(conn) -> pd.DataFrame:
    """Join PL, BS, CF, company face_value, and sector for every company-year."""
    sql = """
        SELECT
            p.company_id,
            p.year,
            p.sales,
            p.operating_profit,
            p.opm_percentage,
            p.other_income,
            p.interest,
            p.depreciation,
            p.net_profit,
            p.eps,
            p.dividend_payout,
            b.equity_capital,
            COALESCE(b.reserves, 0)          AS reserves,
            COALESCE(b.borrowings, 0)        AS borrowings,
            COALESCE(b.other_liabilities, 0) AS other_liabilities,
            b.total_assets,
            b.fixed_assets,
            COALESCE(b.investments, 0)       AS investments,
            COALESCE(c.operating_activity, 0) AS cfo,
            COALESCE(c.investing_activity, 0) AS cfi,
            COALESCE(c.financing_activity, 0) AS cff,
            COALESCE(c.net_cash_flow, 0)     AS net_cash_flow,
            co.face_value,
            COALESCE(s.broad_sector, '')     AS broad_sector
        FROM profitandloss p
        JOIN balancesheet b USING (company_id, year)
        JOIN cashflow    c USING (company_id, year)
        JOIN companies   co ON co.id = p.company_id
        LEFT JOIN sectors s ON s.company_id = p.company_id
        ORDER BY p.company_id, p.year
    """
    return pd.read_sql_query(sql, conn)


def _book_value_per_share(
    equity_capital: float,
    reserves: float,
    face_value: float,
) -> float | None:
    """BPS = (equity + reserves) / shares_outstanding, where shares = equity_cap / face_value."""
    if face_value is None or face_value <= 0:
        return None
    if equity_capital is None or equity_capital <= 0:
        return None
    shares = equity_capital / face_value
    if shares <= 0:
        return None
    equity = equity_capital + (reserves or 0.0)
    return equity / shares


def _compute_group(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all per-row KPIs + CAGRs for one company's time-series DataFrame."""
    df = df.sort_values("year").reset_index(drop=True).copy()

    # ---- Profitability (Day 8) ----
    npm_list, opm_list, em_list, roe_list, roce_list, roa_list = [], [], [], [], [], []
    opm_delta_list, opm_flag_list = [], []
    for _, r in df.iterrows():
        pr = compute_profitability_ratios(
            sales=float(r["sales"]),
            operating_profit=float(r["operating_profit"]),
            opm_percentage=float(r["opm_percentage"]) if pd.notna(r["opm_percentage"]) else None,
            depreciation=float(r["depreciation"]) if pd.notna(r["depreciation"]) else 0.0,
            other_income=float(r["other_income"]) if pd.notna(r["other_income"]) else 0.0,
            net_profit=float(r["net_profit"]),
            equity_capital=float(r["equity_capital"]),
            reserves=float(r["reserves"]) if pd.notna(r["reserves"]) else None,
            borrowings=float(r["borrowings"]) if pd.notna(r["borrowings"]) else None,
            total_assets=float(r["total_assets"]),
            broad_sector=r.get("broad_sector", ""),
        )
        npm_list.append(pr.net_profit_margin_pct)
        opm_list.append(pr.operating_profit_margin_pct)
        em_list.append(pr.ebit_margin_pct)
        roe_list.append(pr.return_on_equity_pct)
        roce_list.append(pr.roce_pct)
        roa_list.append(pr.return_on_assets_pct)
        opm_delta_list.append(pr.opm_crosscheck_delta)
        opm_flag_list.append(int(pr.opm_crosscheck_flag))

    df["net_profit_margin_pct"] = npm_list
    df["operating_profit_margin_pct"] = opm_list
    df["ebit_margin_pct"] = em_list
    df["return_on_equity_pct"] = roe_list
    df["roce_pct"] = roce_list
    df["return_on_assets_pct"] = roa_list

    # ---- Leverage & efficiency (Day 9) ----
    de_list, hlev_list, icr_list, icr_label_list, icr_warn_list = [], [], [], [], []
    nd_list, at_list = [], []
    for _, r in df.iterrows():
        de = debt_to_equity(
            float(r["borrowings"]),
            float(r["equity_capital"]),
            float(r["reserves"]) if pd.notna(r["reserves"]) else None,
        )
        fin = is_financial_sector(r.get("broad_sector", ""))
        hlev = int(high_leverage_flag(de, fin))
        icr = interest_coverage_ratio(
            float(r["operating_profit"]),
            float(r["other_income"]) if pd.notna(r["other_income"]) else 0.0,
            float(r["interest"]) if pd.notna(r["interest"]) else 0.0,
        )
        label = icr_display_label(icr)
        iwarn = int(icr_warning_flag(icr))
        nd = net_debt(
            float(r["borrowings"]), float(r["investments"]) if pd.notna(r["investments"]) else None
        )
        at = asset_turnover(float(r["sales"]), float(r["total_assets"]))
        de_list.append(de)
        hlev_list.append(hlev)
        icr_list.append(icr)
        icr_label_list.append(label)
        icr_warn_list.append(iwarn)
        nd_list.append(nd)
        at_list.append(at)
    df["debt_to_equity"] = de_list
    df["high_leverage_flag"] = hlev_list
    df["interest_coverage"] = icr_list
    df["icr_label"] = icr_label_list
    df["icr_warning_flag"] = icr_warn_list
    df["net_debt_cr"] = nd_list
    df["asset_turnover"] = at_list

    # ---- Cash-flow KPIs (Day 11) ----
    fcf_list, cfo_pat_list = [], []
    capex_pct_list, capex_tier_list = [], []
    fcf_conv_list = []
    cfo_sign_list, cfi_sign_list, cff_sign_list, pattern_list = [], [], [], []
    fcf_concern_list = []
    fcf_history: list[float] = []
    for _, r in df.iterrows():
        cfo = float(r["cfo"])
        cfi = float(r["cfi"])
        cff = float(r["cff"])
        fcf = free_cash_flow(cfo, cfi)
        cp = cfo_pat_ratio(cfo, float(r["net_profit"]))
        capex_p = capex_intensity(cfi, float(r["sales"]))
        ctier = capex_tier(capex_p)
        fconv = fcf_conversion(fcf, float(r["operating_profit"]))
        s_cfo, s_cfi, s_cff, pattern = classify_capital_allocation(cfo, cfi, cff, cp)
        fcf_history.append(fcf)
        # FCF concern: last 3 non-None (all numeric here) are negative
        concern = 0
        if len(fcf_history) >= 3 and all(x < 0 for x in fcf_history[-3:]):
            concern = 1
        fcf_list.append(fcf)
        cfo_pat_list.append(cp)
        capex_pct_list.append(capex_p)
        capex_tier_list.append(ctier)
        fcf_conv_list.append(fconv)
        cfo_sign_list.append(s_cfo)
        cfi_sign_list.append(s_cfi)
        cff_sign_list.append(s_cff)
        pattern_list.append(pattern)
        fcf_concern_list.append(concern)
    df["fcf_cr"] = fcf_list  # free_cash_flow_cr name
    df["free_cash_flow_cr"] = fcf_list
    df["cash_from_operations_cr"] = df["cfo"].astype(float)
    df["capex_cr"] = df["cfi"].abs().astype(float)  # abs(CFI) proxy
    df["cfo_pat_ratio"] = cfo_pat_list
    df["capex_intensity_pct"] = capex_pct_list
    df["capex_tier"] = capex_tier_list
    df["fcf_conversion_pct"] = fcf_conv_list
    df["cfo_sign"] = cfo_sign_list
    df["cfi_sign"] = cfi_sign_list
    df["cff_sign"] = cff_sign_list
    df["capital_allocation_pattern"] = pattern_list
    df["fcf_concern_flag"] = fcf_concern_list

    # ---- Simple columns direct from source ----
    df["earnings_per_share"] = df["eps"].astype(float)
    df["total_debt_cr"] = df["borrowings"].astype(float)
    df["dividend_payout_ratio_pct"] = df["dividend_payout"].astype(float)
    df["book_value_per_share"] = [
        _book_value_per_share(
            float(r["equity_capital"]),
            float(r["reserves"]) if pd.notna(r["reserves"]) else 0.0,
            float(r["face_value"]) if pd.notna(r["face_value"]) else None,
        )
        for _, r in df.iterrows()
    ]

    # ---- CAGRs (Day 10) — 3yr, 5yr, 10yr for revenue (sales), PAT (net_profit), EPS ----
    for metric, col in [("revenue", "sales"), ("pat", "net_profit"), ("eps", "eps")]:
        for n in (3, 5, 10):
            vals: list[float | None] = []
            flags: list[str] = []
            for i in range(len(df)):
                if i < n:
                    vals.append(None)
                    flags.append("INSUFFICIENT")
                    continue
                start = float(df.iloc[i - n][col])
                end = float(df.iloc[i][col])
                res = cagr(start, end, n)
                vals.append(res.value)
                flags.append(res.flag)
            df[f"{metric}_cagr_{n}yr"] = vals
            df[f"{metric}_cagr_{n}yr_flag"] = flags

    return df


def _compute_composite_scores(df: pd.DataFrame) -> pd.Series:
    """Compute composite quality score 0-100 using P10/P90 winsorised sub-scores."""
    # Sub-scores (each 0-100)
    roe_score = _winsor_score(df["return_on_equity_pct"], higher_is_better=True)
    # FCF sub-score uses FCF conversion % (how much of operating profit became free cash)
    fcf_score = _winsor_score(df["fcf_conversion_pct"], higher_is_better=True)
    roce_score = _winsor_score(df["roce_pct"], higher_is_better=True)
    # DE sub-score: lower D/E is better
    de_for_score = df["debt_to_equity"].replace(0, np.nan)  # debt-free: NaN → perfect score
    de_score = _winsor_score(de_for_score, higher_is_better=False)
    # Debt-free companies → DE score = 100 (best)
    de_score = de_score.where(df["debt_to_equity"] > 0, 100.0)
    # Financial sector companies: force a neutral DE score (their D/E is structurally high)
    fin_mask = (
        df["broad_sector"]
        .fillna("")
        .str.lower()
        .apply(lambda s: any(kw in s for kw in ("bank", "nbfc", "finance", "financial")))
    )
    de_score = de_score.where(~fin_mask, 50.0)

    composite = (
        COMPOSITE_WEIGHTS["roe"] * roe_score.fillna(0)
        + COMPOSITE_WEIGHTS["fcf"] * fcf_score.fillna(0)
        + COMPOSITE_WEIGHTS["roce"] * roce_score.fillna(0)
        + COMPOSITE_WEIGHTS["de"] * de_score.fillna(0)
    )
    # Where all four sub-scores are NaN, mark composite as NULL (shouldn't happen)
    any_valid = roe_score.notna() | fcf_score.notna() | roce_score.notna() | de_score.notna()
    composite = composite.where(any_valid, np.nan)
    return composite.round(2)


def populate(*, reset: bool = False) -> dict:
    """Main entry point: build and load the financial_ratios table."""
    init_schema()
    if reset:
        logger.info("Resetting financial_ratios table...")
        reset_tables(tables=["financial_ratios"])

    with get_connection() as conn:
        src = _fetch_source_data(conn)
    logger.info(f"Fetched {len(src)} joined company-year rows for ratio computation")

    # Compute per-company ratios
    pieces: list[pd.DataFrame] = []
    for _cid, grp in src.groupby("company_id", sort=False):
        pieces.append(_compute_group(grp))
    out = pd.concat(pieces, ignore_index=True, sort=False)
    logger.info(f"Computed ratios for {out['company_id'].nunique()} companies, {len(out)} rows")

    # ---- Composite Quality Score (cross-sectional, after computing all rows) ----
    out["composite_quality_score"] = _compute_composite_scores(out)

    # Ensure required columns exist with the right names for the target table
    keep_cols = [
        "company_id",
        "year",
        "net_profit_margin_pct",
        "operating_profit_margin_pct",
        "ebit_margin_pct",
        "return_on_equity_pct",
        "roce_pct",
        "return_on_assets_pct",
        "debt_to_equity",
        "high_leverage_flag",
        "interest_coverage",
        "icr_label",
        "icr_warning_flag",
        "net_debt_cr",
        "asset_turnover",
        "free_cash_flow_cr",
        "capex_cr",
        "earnings_per_share",
        "book_value_per_share",
        "dividend_payout_ratio_pct",
        "total_debt_cr",
        "cash_from_operations_cr",
        "revenue_cagr_3yr",
        "revenue_cagr_3yr_flag",
        "revenue_cagr_5yr",
        "revenue_cagr_5yr_flag",
        "revenue_cagr_10yr",
        "revenue_cagr_10yr_flag",
        "pat_cagr_3yr",
        "pat_cagr_3yr_flag",
        "pat_cagr_5yr",
        "pat_cagr_5yr_flag",
        "pat_cagr_10yr",
        "pat_cagr_10yr_flag",
        "eps_cagr_3yr",
        "eps_cagr_3yr_flag",
        "eps_cagr_5yr",
        "eps_cagr_5yr_flag",
        "eps_cagr_10yr",
        "eps_cagr_10yr_flag",
        "cfo_pat_ratio",
        "cfo_quality_score_5yr",
        "cfo_quality_tier",
        "capex_intensity_pct",
        "capex_tier",
        "fcf_conversion_pct",
        "cfo_sign",
        "cfi_sign",
        "cff_sign",
        "capital_allocation_pattern",
        "fcf_concern_flag",
        "composite_quality_score",
    ]
    # Add the 5-yr rolling CFO quality score (mean of cfo_pat_ratio over trailing 5y, min 3y)
    out["cfo_quality_score_5yr"] = out.groupby("company_id")["cfo_pat_ratio"].transform(
        lambda s: s.rolling(window=5, min_periods=3).mean()
    )
    out["cfo_quality_tier"] = out["cfo_quality_score_5yr"].apply(
        lambda v: (
            None
            if pd.isna(v)
            else "High Quality" if v > 1.0 else "Moderate" if v >= 0.5 else "Accrual Risk"
        )
    )

    final = out[keep_cols].copy()
    # Coerce flags to int where appropriate
    for col in ["high_leverage_flag", "icr_warning_flag", "fcf_concern_flag"]:
        final[col] = final[col].fillna(0).astype(int)

    # Load into DB
    import time

    t0 = time.time()
    stats = load_dataframe(final, "financial_ratios", merge=True)
    runtime = time.time() - t0

    write_load_audit(
        [
            {
                "table": "financial_ratios",
                "rows_in": stats["rows_in"],
                "rows_out": stats["rows_loaded"],
                "rows_rejected": stats["rows_dropped"],
                "runtime_s": round(runtime, 3),
                "status": "OK",
            }
        ]
    )

    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM financial_ratios").fetchone()[0]
        null_cagr5 = conn.execute(
            "SELECT COUNT(*) FROM financial_ratios WHERE revenue_cagr_5yr_flag='OK'"
        ).fetchone()[0]
        comp_nulls = conn.execute(
            "SELECT COUNT(*) FROM financial_ratios WHERE composite_quality_score IS NULL"
        ).fetchone()[0]
    logger.info(
        f"financial_ratios now has {count} rows; "
        f"{null_cagr5} rows have 5yr Revenue CAGR; "
        f"{count - comp_nulls} rows have composite score."
    )
    return {
        "rows": count,
        "stats": stats,
        "runtime_s": round(runtime, 3),
    }


def _spot_check(conn) -> list[dict]:
    """Manual spot-check: recompute ROE and 5-yr Revenue CAGR for 3 companies.

    Selects 3 companies with ≥6 years of PL+BS history, uses the last year as
    end and the row 5 positions earlier as start (mirroring the same position-
    based look-back used inside _compute_group), then compares DB values.
    """
    import random

    random.seed(2024)
    eligible = [r[0] for r in conn.execute("""SELECT company_id FROM profitandloss
               GROUP BY company_id HAVING COUNT(*) >= 6""").fetchall()]
    picks = random.sample(eligible, 3)
    results = []
    for cid in picks:
        rows = conn.execute(
            """SELECT p.year, p.net_profit, p.sales,
                      b.equity_capital, b.reserves
               FROM profitandloss p JOIN balancesheet b
                 ON p.company_id = b.company_id AND p.year = b.year
               WHERE p.company_id = ? ORDER BY p.year""",
            (cid,),
        ).fetchall()
        if len(rows) < 6:
            continue
        end = rows[-1]
        start = rows[-6]
        yr = end["year"]
        db_row = conn.execute(
            """SELECT return_on_equity_pct, revenue_cagr_5yr
               FROM financial_ratios WHERE company_id=? AND year=?""",
            (cid, yr),
        ).fetchone()
        if db_row is None:
            continue
        eq = end["equity_capital"] + (end["reserves"] or 0.0)
        man_roe = end["net_profit"] / eq * 100 if eq > 0 else None
        if start["sales"] <= 0 or end["sales"] <= 0:
            continue
        man_cagr5 = ((end["sales"] / start["sales"]) ** (1 / 5) - 1) * 100
        results.append(
            {
                "company_id": cid,
                "year": yr,
                "db_roe": db_row["return_on_equity_pct"],
                "manual_roe": round(man_roe, 4) if man_roe is not None else None,
                "roe_delta": (
                    round(abs(db_row["return_on_equity_pct"] - man_roe), 6)
                    if man_roe is not None
                    else 0.0
                ),
                "db_cagr5": db_row["revenue_cagr_5yr"],
                "manual_cagr5": round(man_cagr5, 4),
                "cagr5_delta": round(abs(db_row["revenue_cagr_5yr"] - man_cagr5), 6),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate financial_ratios table")
    parser.add_argument("--reset", action="store_true", help="Truncate table first")
    parser.add_argument(
        "--spot-check", action="store_true", help="Run manual 3-company spot check after load"
    )
    args = parser.parse_args()

    result = populate(reset=args.reset)
    print(f"Populated financial_ratios: {result['rows']} rows in {result['runtime_s']}s")

    if args.spot_check:
        with get_connection() as conn:
            checks = _spot_check(conn)
        print("\n--- 3-Company Manual Spot-Check ---")
        hdr = (
            f"{'Company':<14} {'Year':<8} {'DB ROE':>8} {'Man ROE':>8}"
            f" {'ROE Δ':>10}   {'DB CAGR5':>10} {'Man CAGR5':>11} {'CAGR Δ':>10}"
        )
        print(hdr)
        for c in checks:
            line = (
                f"{c['company_id']:<14} {c['year']:<8} {c['db_roe']:>8.2f}"
                f" {c['manual_roe']:>8.2f} {c['roe_delta']:>10.6f}"
                f"   {c['db_cagr5']:>10.4f} {c['manual_cagr5']:>11.4f}"
                f" {c['cagr5_delta']:>10.6f}"
            )
            print(line)
        max_d = max(max(c["roe_delta"], c["cagr5_delta"]) for c in checks) if checks else 0
        assert max_d < 0.1, f"Spot-check delta {max_d} exceeds 0.1% tolerance"
        print(f"\n✓ All deltas < 0.1% (max delta: {max_d:.6f})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
