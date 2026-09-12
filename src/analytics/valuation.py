"""Valuation ratio primitives and sector-relative valuation engine.

Sprint 3 Day 16: primitive multiples (P/E, P/B, EV/EBITDA, Dividend Yield,
FCF Yield, Earnings Yield) computed from fundamentals.

Sprint 4 Day 26: sector-relative valuation engine — joins the latest-year
financial_ratios / market_cap / sectors tables, computes FCF yield,
sector-median P/E and 5-year median P/E, applies overvaluation flags
(Caution / Discount / Fair) and emits ``valuation_summary.xlsx`` plus
``valuation_flags.csv``.

All monetary inputs are expected in ₹ Crore.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

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

# Day 26 sector-relative thresholds
SECTOR_PREMIUM_MULTIPLIER = 1.5  # P/E > sector_median * 1.5 → Caution
SECTOR_DISCOUNT_MULTIPLIER = 0.7  # P/E < sector_median * 0.7 → Discount


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


# ---------------------------------------------------------------------------
# Day 26 — Sector-relative valuation engine
# ---------------------------------------------------------------------------
VALUATION_SUMMARY_COLUMNS: tuple[str, ...] = (
    "company_id",
    "company_name",
    "sector",
    "pe_ratio",
    "pb_ratio",
    "ev_ebitda",
    "fcf_yield_pct",
    "5yr_median_PE",
    "sector_median_PE",
    "PE_vs_sector_median_pct",
    "flag",
)


def load_valuation_panel(
    conn: sqlite3.Connection | str | Path,  # type: ignore[name-defined]
    year: int | None = None,
) -> pd.DataFrame:
    """Load a joined valuation panel for the latest (or specified) calendar year.

    Returns one row per latest-FY company with columns required for the
    valuation summary. ``year`` is a calendar year (e.g. 2024) which maps
    to FY ``{year}-03`` in financial_ratios. When ``year`` is None the
    most recent year from market_cap is used.
    """
    import sqlite3

    if isinstance(conn, (str, Path)):
        conn = sqlite3.connect(str(conn))

    if year is None:
        year = int(pd.read_sql("SELECT MAX(year) AS y FROM market_cap", conn).iloc[0]["y"])

    fy = f"{year}-03"

    query = """
        SELECT
            fr.company_id,
            c.company_name,
            s.broad_sector                                 AS sector,
            mc.pe_ratio,
            mc.pb_ratio,
            mc.ev_ebitda,
            mc.market_cap_crore,
            mc.dividend_yield_pct,
            fr.free_cash_flow_cr,
            pl.net_profit,
            pl.operating_profit                            AS ebit,
            (fr.equity_cr)                                AS book_value_cr
        FROM market_cap mc
        JOIN financial_ratios fr
            ON fr.company_id = mc.company_id
           AND fr.year = :fy
        JOIN companies c ON c.id = mc.company_id
        LEFT JOIN sectors s ON s.company_id = mc.company_id
        LEFT JOIN profitandloss pl ON pl.company_id = mc.company_id AND pl.year = :fy
        WHERE mc.year = :year
    """
    # equity_cr is not a native column — compute it from balancesheet to stay safe.
    query = """
        SELECT
            fr.company_id,
            c.company_name,
            s.broad_sector                                 AS sector,
            mc.pe_ratio,
            mc.pb_ratio,
            mc.ev_ebitda,
            mc.market_cap_crore,
            mc.dividend_yield_pct,
            fr.free_cash_flow_cr,
            pl.net_profit,
            pl.operating_profit                            AS ebit,
            (bs.equity_capital + bs.reserves)              AS book_value_cr
        FROM market_cap mc
        JOIN financial_ratios fr
            ON fr.company_id = mc.company_id
           AND fr.year = :fy
        JOIN companies c ON c.id = mc.company_id
        LEFT JOIN sectors s ON s.company_id = mc.company_id
        LEFT JOIN profitandloss pl ON pl.company_id = mc.company_id AND pl.year = :fy
        LEFT JOIN balancesheet bs ON bs.company_id = mc.company_id AND bs.year = :fy
        WHERE mc.year = :year
    """
    df = pd.read_sql(query, conn, params={"year": year, "fy": fy})

    # 5-year median P/E for each company across the market_cap window ending in ``year``.
    pe5_query = """
        SELECT company_id, year, pe_ratio
        FROM market_cap
        WHERE year BETWEEN :start AND :year
          AND pe_ratio IS NOT NULL
          AND pe_ratio > 0
        ORDER BY company_id, year
    """
    pe5_raw = pd.read_sql(pe5_query, conn, params={"year": year, "start": year - 4})
    pe5 = (
        pe5_raw.groupby("company_id")["pe_ratio"]
        .median()
        .reset_index()
        .rename(columns={"pe_ratio": "pe_5yr_median"})
    )
    df = df.merge(pe5, left_on="company_id", right_on="company_id", how="left")

    return df


def compute_valuation_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Compute FCF yield, sector-median P/E, vs-sector % and Caution/Discount/Fair flag.

    Input: the DataFrame returned by :func:`load_valuation_panel`.
    Returns a DataFrame with exactly the columns in
    :data:`VALUATION_SUMMARY_COLUMNS`, sorted by company_name.
    """
    out = df.copy()

    # FCF Yield = FCF / market_cap * 100
    out["fcf_yield_pct"] = (out["free_cash_flow_cr"] / out["market_cap_crore"]) * 100.0
    out.loc[out["market_cap_crore"] <= 0, "fcf_yield_pct"] = pd.NA

    # Sector median P/E (positive P/E rows only; loss-makers excluded so they
    # don't distort the median downwards).
    out["sector_median_PE"] = out.groupby("sector")["pe_ratio"].transform(
        lambda s: s[s > 0].median()
    )

    # 5-yr median PE rename
    out["5yr_median_PE"] = out["pe_5yr_median"]

    # P/E vs sector-median as a percentage (100% = at median; 200% = double)
    out["PE_vs_sector_median_pct"] = (out["pe_ratio"] / out["sector_median_PE"]) * 100.0

    def _flag(row: pd.Series) -> str:
        pe = row["pe_ratio"]
        med = row["sector_median_PE"]
        if pd.isna(pe) or pe <= 0 or pd.isna(med) or med <= 0:
            return "Fair"  # insufficient data to flag
        if pe > med * SECTOR_PREMIUM_MULTIPLIER:
            return "Caution"
        if pe < med * SECTOR_DISCOUNT_MULTIPLIER:
            return "Discount"
        return "Fair"

    out["flag"] = out.apply(_flag, axis=1)

    out = out.rename(columns={"free_cash_flow_cr": "_fcf"})
    summary = out[
        [
            "company_id",
            "company_name",
            "sector",
            "pe_ratio",
            "pb_ratio",
            "ev_ebitda",
            "fcf_yield_pct",
            "5yr_median_PE",
            "sector_median_PE",
            "PE_vs_sector_median_pct",
            "flag",
        ]
    ].copy()
    summary = summary.sort_values("company_name").reset_index(drop=True)

    # Round numeric columns for readability
    for c in [
        "pe_ratio",
        "pb_ratio",
        "ev_ebitda",
        "fcf_yield_pct",
        "5yr_median_PE",
        "sector_median_PE",
        "PE_vs_sector_median_pct",
    ]:
        summary[c] = summary[c].astype(float).round(2)
    return summary


def write_valuation_outputs(
    summary: pd.DataFrame,
    output_dir: Path | str,
) -> tuple[Path, Path]:
    """Write ``valuation_summary.xlsx`` and ``valuation_flags.csv`` to ``output_dir``.

    Returns the two output paths as a tuple ``(xlsx_path, csv_path)``.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils.dataframe import dataframe_to_rows

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = output_dir / "valuation_summary.xlsx"
    csv_path = output_dir / "valuation_flags.csv"

    # ---- XLSX with colour-coded flag column ----
    wb = Workbook()
    ws = wb.active
    ws.title = "Valuation Summary"

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")
    caution_fill = PatternFill("solid", fgColor="FFC7CE")
    discount_fill = PatternFill("solid", fgColor="C6EFCE")
    fair_fill = PatternFill("solid", fgColor="FFEB9C")

    for r_idx, row in enumerate(dataframe_to_rows(summary, index=False, header=True), 1):
        for c_idx, value in enumerate(row, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=value)
            if r_idx == 1:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center")
            else:
                flag_val = summary.iloc[r_idx - 2]["flag"]
                if c_idx == len(summary.columns):  # flag column
                    if flag_val == "Caution":
                        cell.fill = caution_fill
                    elif flag_val == "Discount":
                        cell.fill = discount_fill
                    else:
                        cell.fill = fair_fill
                    cell.font = Font(bold=True)

    # Auto-size columns
    for col_cells in ws.columns:
        max_len = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 3, 28)

    ws.freeze_panes = "A2"
    wb.save(xlsx_path)

    # ---- CSV: only Caution / Discount rows ----
    flagged = summary[summary["flag"].isin(["Caution", "Discount"])].copy()
    flagged.to_csv(csv_path, index=False)

    return xlsx_path, csv_path


def run_valuation_module(
    db_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    year: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, Path, Path]:
    """High-level entry point used by the Day-26 script.

    Returns ``(summary_df, flagged_df, xlsx_path, csv_path)``.
    """
    import sqlite3

    from src.utils.config import settings

    if db_path is None:
        db_path = settings.PROJECT_ROOT / "db" / "nifty100.db"
    if output_dir is None:
        output_dir = settings.PROJECT_ROOT / "output"

    conn = sqlite3.connect(str(db_path))
    try:
        panel = load_valuation_panel(conn, year=year)
        summary = compute_valuation_summary(panel)
        xlsx, csv = write_valuation_outputs(summary, Path(output_dir))
        flagged = summary[summary["flag"].isin(["Caution", "Discount"])].copy()
        return summary, flagged, xlsx, csv
    finally:
        conn.close()
