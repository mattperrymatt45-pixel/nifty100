r"""Sprint 5 Day 29 — Analysis text parser.

Parses free-text growth fields in ``data/raw/analysis.xlsx`` (as exported from
Screener.in's "Analysis" tab) using a strict regex, writes a tidy long-form
CSV of metric observations, logs any entries the regex cannot match, and
cross-validates the parsed values against the Ratio Engine's computed CAGRs.
Flagged divergences (>5 percentage points by default) are written for manual
review.

Target fields (from analysis.xlsx, header row = spreadsheet row 2):
    - ``compounded_sales_growth``
    - ``compounded_profit_growth``
    - ``stock_price_cagr``
    - ``roe``

Regex contract (spec Day 29)::

    (\d+)\s*Years?:?\s*([\d.]+)%

Accepts both ``"10 Years: 21%"`` and ``"5 Years: 7.5%"`` (optional colon,
flexible whitespace, decimal percentages).

Outputs (default location ``output/``):
    - ``analysis_parsed.csv``   — tidy long-form: company_id, metric_type,
                                  period_years, value_pct, source_value
    - ``parse_failures.csv``    — rows whose text did not match the regex
                                  (company_id, metric_type, raw_text, reason)
    - ``analysis_divergences.csv`` — cross-validation flags where parsed value
                                     differs from Ratio Engine by more than
                                     ``CAGR_DIVERGENCE_THRESHOLD_PCT`` points.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Regex / schema constants
# ---------------------------------------------------------------------------
PARSE_REGEX: re.Pattern[str] = re.compile(
    r"(?P<years>\d+)\s*Years?\s*:?\s*(?P<value>[\d.]+)\s*%",
    flags=re.IGNORECASE,
)

# Analysis workbook columns we attempt to parse.
METRIC_COLUMNS: tuple[str, ...] = (
    "compounded_sales_growth",
    "compounded_profit_growth",
    "stock_price_cagr",
    "roe",
)


# How a parsed (metric_type, period_years) maps to a Ratio Engine column.
# A value of ``None`` means no computed equivalent exists in the DB (e.g.
# stock price CAGR is market-derived, not in financial_ratios), so those rows
# are emitted but skipped during cross-validation.
@dataclass(frozen=True)
class MetricMapping:
    """Bind a parsed metric to a financial_ratios CAGR column (if available)."""

    metric_type: str
    ratio_col_template: str | None  # e.g. "revenue_cagr_{period}yr" or None
    average_col: str | None = None  # e.g. "return_on_equity_pct" used for ROE


RATIO_MAPPINGS: dict[str, MetricMapping] = {
    "compounded_sales_growth": MetricMapping(
        metric_type="sales_cagr",
        ratio_col_template="revenue_cagr_{period}yr",
    ),
    "compounded_profit_growth": MetricMapping(
        metric_type="profit_cagr",
        ratio_col_template="pat_cagr_{period}yr",
    ),
    "stock_price_cagr": MetricMapping(
        metric_type="stock_cagr",
        ratio_col_template=None,  # market-derived, not held in financial_ratios
    ),
    "roe": MetricMapping(
        metric_type="roe_avg",
        ratio_col_template=None,
        average_col="return_on_equity_pct",
    ),
}

# Threshold for divergence flagging (percentage-points of difference between
# parsed value and Ratio Engine value).
CAGR_DIVERGENCE_THRESHOLD_PCT: float = 5.0


# ---------------------------------------------------------------------------
# Dataclass results
# ---------------------------------------------------------------------------
@dataclass
class AnalysisParseResult:
    """Container for parser outputs."""

    parsed: pd.DataFrame
    failures: pd.DataFrame
    divergences: pd.DataFrame
    parsed_csv: Path
    failures_csv: Path
    divergences_csv: Path
    total_rows: int = 0
    matched_rows: int = 0
    failed_rows: int = 0

    @property
    def match_rate_pct(self) -> float:
        """Return the fuzzy-match percentage for Strengths/Weaknesses sentences."""
        if self.total_rows == 0:
            return 0.0
        return round(self.matched_rows / self.total_rows * 100.0, 2)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_analysis_workbook(path: Path | str) -> pd.DataFrame:
    """Load ``analysis.xlsx`` into a tidy DataFrame with proper headers.

    The Screener.in export places the real header on row 2 of the "Analysis"
    sheet, so we pass ``header=1`` to pandas.
    """
    path = Path(path)
    df = pd.read_excel(path, sheet_name="Analysis", header=1)
    # Coerce expected columns to string to protect regex from numeric NaN.
    for col in METRIC_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df


# ---------------------------------------------------------------------------
# Core parse primitive
# ---------------------------------------------------------------------------
def parse_analysis_text(text: str) -> list[tuple[int, float]]:
    """Parse one text cell and return all ``(period_years, value_pct)`` tuples.

    Returns an empty list if no matches are found.  Multiple matches in a
    single cell are supported (e.g. a future format with both 5Y and 10Y in
    one cell will yield both tuples).
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    s = str(text).strip()
    if not s:
        return []
    out: list[tuple[int, float]] = []
    for m in PARSE_REGEX.finditer(s):
        try:
            years = int(m.group("years"))
            value = float(m.group("value"))
        except (TypeError, ValueError):
            continue
        out.append((years, value))
    return out


# ---------------------------------------------------------------------------
# Tidy long-form parse over the workbook
# ---------------------------------------------------------------------------
def _parse_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (parsed_long, failures) DataFrames."""
    parsed_rows: list[dict] = []
    failure_rows: list[dict] = []

    for _, row in df.iterrows():
        company_id = row.get("company_id")
        if pd.isna(company_id):
            continue
        company_id = str(company_id).strip()
        for col in METRIC_COLUMNS:
            if col not in df.columns:
                failure_rows.append(
                    {
                        "company_id": company_id,
                        "metric_type": col,
                        "raw_text": None,
                        "reason": "column_missing_from_workbook",
                    }
                )
                continue
            raw = row[col]
            if raw is None or (isinstance(raw, float) and pd.isna(raw)) or pd.isna(raw):
                raw_text = None
            else:
                raw_text = str(raw)
            if raw_text is None or raw_text.strip() == "":
                failure_rows.append(
                    {
                        "company_id": company_id,
                        "metric_type": col,
                        "raw_text": "",
                        "reason": "empty_cell",
                    }
                )
                continue
            matches = parse_analysis_text(raw_text)
            if not matches:
                failure_rows.append(
                    {
                        "company_id": company_id,
                        "metric_type": col,
                        "raw_text": raw_text,
                        "reason": "no_regex_match",
                    }
                )
                continue
            for years, value in matches:
                metric_type = RATIO_MAPPINGS[col].metric_type
                parsed_rows.append(
                    {
                        "company_id": company_id,
                        "metric_type": metric_type,
                        "source_column": col,
                        "period_years": years,
                        "value_pct": round(value, 2),
                        "source_value": raw_text,
                    }
                )

    parsed = pd.DataFrame(
        parsed_rows,
        columns=[
            "company_id",
            "metric_type",
            "source_column",
            "period_years",
            "value_pct",
            "source_value",
        ],
    )
    failures = pd.DataFrame(
        failure_rows,
        columns=["company_id", "metric_type", "raw_text", "reason"],
    )
    return parsed, failures


# ---------------------------------------------------------------------------
# Cross-validation against Ratio Engine
# ---------------------------------------------------------------------------
def _load_latest_ratios(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return the latest FY of financial_ratios per company."""
    query = """
        SELECT fr.*
        FROM financial_ratios fr
        JOIN (
            SELECT company_id, MAX(year) AS latest_year
            FROM financial_ratios
            GROUP BY company_id
        ) lat ON lat.company_id = fr.company_id AND lat.latest_year = fr.year
    """
    return pd.read_sql(query, conn)


def cross_validate_parsed(
    parsed: pd.DataFrame,
    db_path: Path | str,
    threshold_pct: float = CAGR_DIVERGENCE_THRESHOLD_PCT,
) -> pd.DataFrame:
    """Compare parsed CAGR / ROE values against the Ratio Engine.

    Returns a DataFrame of divergences (rows where the absolute gap exceeds
    ``threshold_pct``) with columns:
    company_id, metric_type, period_years, parsed_value_pct, ratio_value_pct,
    delta_pct, ratio_column, reason.

    Metrics without a Ratio Engine column mapping (e.g. ``stock_cagr``) are
    skipped.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        ratios = _load_latest_ratios(conn)
    finally:
        conn.close()

    ratio_map = ratios.set_index("company_id")
    div_rows: list[dict] = []

    for _, row in parsed.iterrows():
        cid = row["company_id"]
        metric_type = row["metric_type"]
        period = int(row["period_years"])
        parsed_val = float(row["value_pct"])

        # Find the mapping whose metric_type matches
        col_map: MetricMapping | None = None
        for _src_col, m in RATIO_MAPPINGS.items():
            if m.metric_type == metric_type:
                col_map = m
                break
        if col_map is None:
            continue

        ratio_col: str | None = None
        if col_map.ratio_col_template is not None:
            ratio_col = col_map.ratio_col_template.format(period=period)
        elif col_map.average_col is not None:
            ratio_col = col_map.average_col
        if ratio_col is None:
            continue  # e.g. stock_cagr — no DB equivalent

        if cid not in ratio_map.index:
            div_rows.append(
                {
                    "company_id": cid,
                    "metric_type": metric_type,
                    "period_years": period,
                    "parsed_value_pct": parsed_val,
                    "ratio_value_pct": None,
                    "delta_pct": None,
                    "ratio_column": ratio_col,
                    "reason": "company_not_in_financial_ratios",
                }
            )
            continue

        if ratio_col not in ratio_map.columns:
            div_rows.append(
                {
                    "company_id": cid,
                    "metric_type": metric_type,
                    "period_years": period,
                    "parsed_value_pct": parsed_val,
                    "ratio_value_pct": None,
                    "delta_pct": None,
                    "ratio_column": ratio_col,
                    "reason": "ratio_column_not_found",
                }
            )
            continue

        db_val = ratio_map.at[cid, ratio_col]
        if pd.isna(db_val):
            div_rows.append(
                {
                    "company_id": cid,
                    "metric_type": metric_type,
                    "period_years": period,
                    "parsed_value_pct": parsed_val,
                    "ratio_value_pct": None,
                    "delta_pct": None,
                    "ratio_column": ratio_col,
                    "reason": "ratio_value_null",
                }
            )
            continue

        db_val_f = float(db_val)
        delta = parsed_val - db_val_f
        if abs(delta) > threshold_pct:
            div_rows.append(
                {
                    "company_id": cid,
                    "metric_type": metric_type,
                    "period_years": period,
                    "parsed_value_pct": round(parsed_val, 2),
                    "ratio_value_pct": round(db_val_f, 2),
                    "delta_pct": round(delta, 2),
                    "ratio_column": ratio_col,
                    "reason": "divergence_gt_threshold",
                }
            )

    return pd.DataFrame(
        div_rows,
        columns=[
            "company_id",
            "metric_type",
            "period_years",
            "parsed_value_pct",
            "ratio_value_pct",
            "delta_pct",
            "ratio_column",
            "reason",
        ],
    )


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------
def run_parser(
    analysis_path: Path | str | None = None,
    db_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    threshold_pct: float = CAGR_DIVERGENCE_THRESHOLD_PCT,
) -> AnalysisParseResult:
    """End-to-end parse + cross-validate + write CSVs.

    Default paths resolve to project-relative locations using
    ``src.utils.config.settings``.
    """
    from src.utils.config import settings

    if analysis_path is None:
        analysis_path = settings.PROJECT_ROOT / "data" / "raw" / "analysis.xlsx"
    if db_path is None:
        db_path = settings.PROJECT_ROOT / "db" / "nifty100.db"
    if output_dir is None:
        output_dir = settings.PROJECT_ROOT / "output"

    analysis_path = Path(analysis_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_analysis_workbook(analysis_path)
    parsed, failures = _parse_frame(df)

    divergences = cross_validate_parsed(parsed, db_path, threshold_pct=threshold_pct)

    parsed_csv = output_dir / "analysis_parsed.csv"
    failures_csv = output_dir / "parse_failures.csv"
    divergences_csv = output_dir / "analysis_divergences.csv"

    parsed.to_csv(parsed_csv, index=False)
    failures.to_csv(failures_csv, index=False)
    divergences.to_csv(divergences_csv, index=False)

    total_cells = sum(df[col].notna().sum() for col in METRIC_COLUMNS if col in df.columns)
    matched = len(parsed)
    failed = len(failures)

    return AnalysisParseResult(
        parsed=parsed,
        failures=failures,
        divergences=divergences,
        parsed_csv=parsed_csv,
        failures_csv=failures_csv,
        divergences_csv=divergences_csv,
        total_rows=int(total_cells),
        matched_rows=int(matched),
        failed_rows=int(failed),
    )
