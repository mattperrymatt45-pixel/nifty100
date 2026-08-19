"""Data-quality (DQ) validation engine for the ETL pipeline.

Implements the 16 validation rules defined in the project spec (§14,
page 28). Each rule is a standalone function that takes a dictionary of
DataFrames keyed by dataset name and returns a list of
:class:`DQFailure` records. The top-level :func:`validate_all` function
runs every registered rule, collects all failures, writes them to
``validation_failures.csv``, and returns a summary.

Severity model
--------------
* **CRITICAL** -- indicates the load cannot proceed for that row/table
  (duplicate PKs, FK orphans, unparseable years/tickers). CRITICAL rows
  are rejected from the final DB load.
* **WARNING** -- data quality issue that should be flagged for analyst
  review but does not block load (OPM mismatch, BS imbalance, etc.).
* **INFO** -- informational metrics surfaced in the load audit.

The module is intentionally side-effect free except for the final CSV
write in :func:`validate_all` -- all individual rules are pure functions
so they are easy to unit test.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.etl.normalizers import YEAR_PARSE_ERROR
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Failure record
# ---------------------------------------------------------------------------
VALID_FIELDS: tuple[str, ...] = (
    "rule_id",
    "table",
    "company_id",
    "year",
    "column",
    "severity",
    "message",
    "expected",
    "actual",
    "row_index",
    "timestamp",
)


@dataclass
class DQFailure:
    """One data-quality violation.

    Attributes mirror the columns written to ``validation_failures.csv``.
    """

    rule_id: str
    table: str
    severity: str  # CRITICAL | WARNING | INFO
    message: str
    company_id: str | None = None
    year: str | None = None
    column: str | None = None
    expected: Any = None
    actual: Any = None
    row_index: int | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds") + "Z"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Type alias for the table bundle passed to rules.
TableBundle = dict[str, pd.DataFrame]

# Type for a rule function: (bundle) -> list[DQFailure]
RuleFunc = Callable[[TableBundle], list[DQFailure]]

# Registry populated by @register_rule
_RULE_REGISTRY: list[tuple[str, RuleFunc]] = []


def register_rule(rule_id: str) -> Callable[[RuleFunc], RuleFunc]:
    """Decorator that registers a function as a DQ rule.

    Usage::

        @register_rule("DQ-01")
        def dq01_company_pk_unique(tables): ...
    """

    def _wrap(fn: RuleFunc) -> RuleFunc:
        _RULE_REGISTRY.append((rule_id, fn))
        fn.rule_id = rule_id  # type: ignore[attr-defined]
        return fn

    return _wrap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce_numeric(series: pd.Series) -> pd.Series:
    """Convert a Series to numeric, coercing strings (e.g. "1,234.5") to NaN-safe."""
    if series.dtype.kind in "biufc":
        return series.astype(float)
    # Strings like "1,234" or "25.0%" need gentle coaxing.
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _has(df: pd.DataFrame, col: str) -> bool:
    return isinstance(df, pd.DataFrame) and col in df.columns


def _year_matches(s: pd.Series) -> pd.Series:
    """Boolean mask: True for rows whose year matches the YYYY-MM pattern."""
    pat = re.compile(r"^\d{4}-\d{2}$")
    return s.astype(str).map(lambda v: bool(pat.match(v)))


# ---------------------------------------------------------------------------
# DQ-01: Company PK uniqueness (CRITICAL)
# ---------------------------------------------------------------------------
@register_rule("DQ-01")
def dq01_company_pk_unique(tables: TableBundle) -> list[DQFailure]:
    """len(companies) == companies.id.nunique() → CRITICAL on duplicate."""
    failures: list[DQFailure] = []
    df = tables.get("companies")
    if df is None or not _has(df, "id"):
        return failures
    dup_mask = df["id"].duplicated(keep=False)
    for idx in df.index[dup_mask]:
        failures.append(
            DQFailure(
                rule_id="DQ-01",
                table="companies",
                severity="CRITICAL",
                message="Duplicate company primary key (id)",
                company_id=str(df.at[idx, "id"]),
                column="id",
                expected="unique ticker",
                actual="duplicate",
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-02: Annual (company_id, year) PK uniqueness across P&L/BS/CF (CRITICAL)
# ---------------------------------------------------------------------------
@register_rule("DQ-02")
def dq02_annual_pk_unique(tables: TableBundle) -> list[DQFailure]:
    """Duplicate (company_id, year) in time-series tables → CRITICAL.

    The spec says: "Deduplicate: keep last occurrence. Log all duplicates."
    This rule only *reports* the duplicates; the actual dedup happens in
    the de-duplication engine (Day 4). For DQ reporting we log every
    duplicate occurrence after the first.
    """
    failures: list[DQFailure] = []
    for table in ("profitandloss", "balancesheet", "cashflow"):
        df = tables.get(table)
        if df is None or not _has(df, "company_id") or not _has(df, "year"):
            continue
        dup_mask = df.duplicated(subset=["company_id", "year"], keep=False)
        for idx in df.index[dup_mask]:
            cid = df.at[idx, "company_id"]
            yr = df.at[idx, "year"]
            failures.append(
                DQFailure(
                    rule_id="DQ-02",
                    table=table,
                    severity="CRITICAL",
                    message="Duplicate (company_id, year) primary key",
                    company_id=None if pd.isna(cid) else str(cid),
                    year=None if pd.isna(yr) else str(yr),
                    column="company_id,year",
                    expected="unique composite key",
                    actual=f"duplicate pair ({cid},{yr})",
                    row_index=int(idx),
                )
            )
    return failures


# ---------------------------------------------------------------------------
# DQ-03: FK integrity - all company_ids in child tables exist in companies.id
# ---------------------------------------------------------------------------
@register_rule("DQ-03")
def dq03_fk_integrity(tables: TableBundle) -> list[DQFailure]:
    """Any company_id not present in companies.id → CRITICAL (orphan row)."""
    failures: list[DQFailure] = []
    companies = tables.get("companies")
    if companies is None or not _has(companies, "id"):
        return failures
    valid_ids: set[str] = set(companies["id"].dropna().astype(str).unique())

    child_tables = [
        "profitandloss",
        "balancesheet",
        "cashflow",
        "analysis",
        "documents",
        "prosandcons",
        "sectors",
        "stock_prices",
        "market_cap",
        "financial_ratios",
        "peer_groups",
    ]
    for table in child_tables:
        df = tables.get(table)
        if df is None or not _has(df, "company_id"):
            continue
        col = df["company_id"]
        orphan_mask = col.notna() & ~col.astype(str).isin(valid_ids)
        for idx in df.index[orphan_mask]:
            cid = df.at[idx, "company_id"]
            yr = df.at[idx, "year"] if _has(df, "year") else None
            failures.append(
                DQFailure(
                    rule_id="DQ-03",
                    table=table,
                    severity="CRITICAL",
                    message="Foreign key violation: company_id not in companies.id",
                    company_id=str(cid),
                    year=None if yr is None or pd.isna(yr) else str(yr),
                    column="company_id",
                    expected=f"one of {len(valid_ids)} known tickers",
                    actual=str(cid),
                    row_index=int(idx),
                )
            )
    return failures


# ---------------------------------------------------------------------------
# DQ-04: Balance sheet balance (WARNING)
# |total_assets - total_liabilities| / total_assets < 0.01
# ---------------------------------------------------------------------------
@register_rule("DQ-04")
def dq04_balance_sheet_balance(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("balancesheet")
    if df is None or not _has(df, "total_assets") or not _has(df, "total_liabilities"):
        return failures
    ta = _coerce_numeric(df["total_assets"])
    tl = _coerce_numeric(df["total_liabilities"])
    diff = (ta - tl).abs()
    ratio = diff / ta.replace(0, pd.NA)
    bad = ratio >= 0.01
    for idx in df.index[bad.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-04",
                table="balancesheet",
                severity="WARNING",
                message="Balance sheet imbalance > 1%",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="total_assets,total_liabilities",
                expected="|assets - liabilities| / assets < 0.01",
                actual=round(float(ratio.at[idx]), 4),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-05: OPM cross-check (WARNING)
# |opm_percentage - (operating_profit/sales*100)| < 1.0
# ---------------------------------------------------------------------------
@register_rule("DQ-05")
def dq05_opm_crosscheck(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("profitandloss")
    if (
        df is None
        or not _has(df, "operating_profit")
        or not _has(df, "sales")
        or not _has(df, "opm_percentage")
    ):
        return failures
    op = _coerce_numeric(df["operating_profit"])
    sales = _coerce_numeric(df["sales"])
    opm_reported = _coerce_numeric(df["opm_percentage"])
    computed = (op / sales.replace(0, pd.NA)) * 100.0
    diff = (opm_reported - computed).abs()
    bad = diff >= 1.0
    for idx in df.index[bad.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-05",
                table="profitandloss",
                severity="WARNING",
                message="OPM percentage mismatch vs (op_profit/sales)*100",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="opm_percentage",
                expected="|reported - computed| < 1.0 pp",
                actual=round(float(diff.at[idx]), 2),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-06: Positive sales (WARNING) -- sales > 0 for non-bank companies.
# We don't have sector map yet (Day 2 scope), so flag *all* sales ≤ 0 as
# warnings; the sector carve-out can be tightened in a later iteration.
# ---------------------------------------------------------------------------
@register_rule("DQ-06")
def dq06_positive_sales(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("profitandloss")
    if df is None or not _has(df, "sales"):
        return failures
    sales = _coerce_numeric(df["sales"])
    bad = sales <= 0
    for idx in df.index[bad.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-06",
                table="profitandloss",
                severity="WARNING",
                message="Sales non-positive",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="sales",
                expected="sales > 0",
                actual=float(sales.at[idx]),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-07: Year format (CRITICAL)
# After normalize_year(), all values must match ^\d{4}-\d{2}$ (not PARSE_ERROR).
# ---------------------------------------------------------------------------
@register_rule("DQ-07")
def dq07_year_format(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    for table in (
        "profitandloss",
        "balancesheet",
        "cashflow",
        "documents",
        "market_cap",
        "financial_ratios",
    ):
        df = tables.get(table)
        if df is None or not _has(df, "year"):
            # documents uses 'Year'; check for that too
            if table == "documents" and df is not None and _has(df, "Year"):
                year_col = "Year"
            else:
                continue
        else:
            year_col = "year"
        yr_series = df[year_col].astype(str)
        bad = ~_year_matches(yr_series) | (yr_series == YEAR_PARSE_ERROR)
        for idx in df.index[bad]:
            cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
            raw = df.at[idx, year_col]
            failures.append(
                DQFailure(
                    rule_id="DQ-07",
                    table=table,
                    severity="CRITICAL",
                    message="Year value unparseable / does not match YYYY-MM",
                    company_id=None if pd.isna(cid) else str(cid),
                    column=year_col,
                    expected="YYYY-MM format",
                    actual=str(raw),
                    row_index=int(idx),
                )
            )
    return failures


# ---------------------------------------------------------------------------
# DQ-08: Ticker format (CRITICAL)
# company_id = stripped uppercase, length 2-12 chars; matches [A-Z0-9&.-]+.
# ---------------------------------------------------------------------------
_TICKER_PAT = re.compile(r"^[A-Z0-9&.\-]{2,12}$")


@register_rule("DQ-08")
def dq08_ticker_format(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    companies = tables.get("companies")
    if companies is None or not _has(companies, "id"):
        return failures
    ids = companies["id"].astype(str)
    bad = ~ids.map(lambda v: bool(_TICKER_PAT.match(v)))
    for idx in companies.index[bad]:
        raw = companies.at[idx, "id"]
        failures.append(
            DQFailure(
                rule_id="DQ-08",
                table="companies",
                severity="CRITICAL",
                message="Ticker fails format check (length 2-12, uppercase, [A-Z0-9&.-])",
                company_id=str(raw),
                column="id",
                expected="2-12 chars; uppercase letters/digits/&/./-",
                actual=str(raw),
                row_index=int(idx),
            )
        )
    # Also check ticker format in child tables in case normalisation missed one
    for table in (
        "profitandloss",
        "balancesheet",
        "cashflow",
        "sectors",
        "stock_prices",
        "market_cap",
        "financial_ratios",
        "peer_groups",
    ):
        df = tables.get(table)
        if df is None or not _has(df, "company_id"):
            continue
        cids = df["company_id"].astype(str)
        bad = ~cids.map(lambda v: bool(_TICKER_PAT.match(v)))
        for idx in df.index[bad]:
            raw = df.at[idx, "company_id"]
            failures.append(
                DQFailure(
                    rule_id="DQ-08",
                    table=table,
                    severity="CRITICAL",
                    message="company_id fails ticker format check",
                    company_id=str(raw),
                    column="company_id",
                    expected="2-12 chars; uppercase letters/digits/&/./-",
                    actual=str(raw),
                    row_index=int(idx),
                )
            )
    return failures


# ---------------------------------------------------------------------------
# DQ-09: Net cash flow cross-check (WARNING)
# |net_cash_flow - (CFO+CFI+CFF)| <= 10 Cr tolerance.
# NOTE: The spec lists a cashflow schema of 7 columns (§5.4) but only
# enumerates operating_activity and investing_activity; the third flow
# (financing_activity) is implied by CFO+CFI+CFF identity and may not
# exist in the raw file. We validate only when all required columns
# (including net_cash_flow OR a derivable equivalent) are present.
# ---------------------------------------------------------------------------
@register_rule("DQ-09")
def dq09_net_cash_check(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("cashflow")
    if df is None:
        return failures
    # We need: operating_activity + investing_activity + [financing_activity]
    # and a net_cash_flow column to compare against.
    need = {"operating_activity", "investing_activity", "net_cash_flow"}
    if not need.issubset(set(df.columns)):
        return failures  # silently skip if raw file lacks a net_cash_flow col
    cfo = _coerce_numeric(df["operating_activity"])
    cfi = _coerce_numeric(df["investing_activity"])
    if "financing_activity" in df.columns:
        cff = _coerce_numeric(df["financing_activity"]).fillna(0)
    else:
        cff = pd.Series(0, index=df.index, dtype=float)
    reported_net = _coerce_numeric(df["net_cash_flow"])
    computed = cfo + cfi + cff
    diff = (reported_net - computed).abs()
    bad = diff > 10.0
    for idx in df.index[bad.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-09",
                table="cashflow",
                severity="WARNING",
                message="Net cash flow does not reconcile to CFO+CFI+CFF within ₹10 Cr",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="net_cash_flow",
                expected="|net - (CFO+CFI+CFF)| ≤ 10 Cr",
                actual=round(float(diff.at[idx]), 2),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-10: Non-negative fixed assets (WARNING) → coerce to 0 and log.
# ---------------------------------------------------------------------------
@register_rule("DQ-10")
def dq10_non_negative_fixed_assets(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("balancesheet")
    if df is None or not _has(df, "fixed_assets"):
        return failures
    fa = _coerce_numeric(df["fixed_assets"])
    bad = fa < 0
    for idx in df.index[bad.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-10",
                table="balancesheet",
                severity="WARNING",
                message="Negative fixed_assets (should be ≥ 0; coerce to 0)",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="fixed_assets",
                expected="≥ 0",
                actual=float(fa.at[idx]),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-11: Tax rate in [0, 60] (WARNING)
# ---------------------------------------------------------------------------
@register_rule("DQ-11")
def dq11_tax_rate_range(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("profitandloss")
    if df is None or not _has(df, "tax_percentage"):
        return failures
    tax = _coerce_numeric(df["tax_percentage"])
    bad = (tax < 0) | (tax > 60)
    for idx in df.index[bad.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-11",
                table="profitandloss",
                severity="WARNING",
                message="Tax rate outside plausible [0, 60]% range",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="tax_percentage",
                expected="0 ≤ tax% ≤ 60",
                actual=float(tax.at[idx]),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-12: Dividend payout ≤ 200% (WARNING)
# ---------------------------------------------------------------------------
@register_rule("DQ-12")
def dq12_dividend_payout_cap(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("profitandloss")
    if df is None or not _has(df, "dividend_payout"):
        return failures
    dp = _coerce_numeric(df["dividend_payout"])
    bad = dp > 200
    for idx in df.index[bad.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-12",
                table="profitandloss",
                severity="WARNING",
                message="Dividend payout > 200% (likely data entry error)",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="dividend_payout",
                expected="≤ 200%",
                actual=float(dp.at[idx]),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-13: URL validity for documents (WARNING)
# NOTE: Full HTTP head checks require network access; we implement the
# syntactic portion here (must be a http(s) URL). The live HEAD check
# is performed separately by a networked utility when desired (so unit
# tests can run offline).
# ---------------------------------------------------------------------------
_URL_PAT = re.compile(r"^https?://", re.IGNORECASE)


@register_rule("DQ-13")
def dq13_url_validity(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("documents")
    if df is None or not _has(df, "Annual_Report"):
        return failures
    url_col = df["Annual_Report"].astype(str)
    bad = ~url_col.map(lambda v: v in ("", "nan", "None") or bool(_URL_PAT.match(v)))
    for idx in df.index[bad]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "Year"] if _has(df, "Year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-13",
                table="documents",
                severity="WARNING",
                message="Annual_Report URL is not a valid http(s) URL",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="Annual_Report",
                expected="http(s):// URL or empty",
                actual=str(df.at[idx, "Annual_Report"]),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-14: EPS sign consistency (WARNING)
# eps > 0 whenever net_profit > 0.
# ---------------------------------------------------------------------------
@register_rule("DQ-14")
def dq14_eps_sign_consistency(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("profitandloss")
    if df is None or not _has(df, "eps") or not _has(df, "net_profit"):
        return failures
    eps = _coerce_numeric(df["eps"])
    np = _coerce_numeric(df["net_profit"])
    # If net_profit > 0 and eps <= 0 → flag (may indicate share-count issue)
    bad = (np > 0) & (eps <= 0)
    for idx in df.index[bad.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-14",
                table="profitandloss",
                severity="WARNING",
                message="EPS sign inconsistent with net_profit (PAT > 0 but EPS ≤ 0)",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="eps,net_profit",
                expected="eps > 0 when net_profit > 0",
                actual=f"eps={float(eps.at[idx])}, net_profit={float(np.at[idx])}",
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-15: BSE/ASE strict balance (INFO)
# Informational count of rows where total_liabilities == total_assets exactly.
# Surfaces "perfect" balances for QA reference (DQ-04 is the warning gate).
# ---------------------------------------------------------------------------
@register_rule("DQ-15")
def dq15_strict_balance_info(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    df = tables.get("balancesheet")
    if df is None or not _has(df, "total_assets") or not _has(df, "total_liabilities"):
        return failures
    ta = _coerce_numeric(df["total_assets"])
    tl = _coerce_numeric(df["total_liabilities"])
    exact = ta == tl
    for idx in df.index[exact.fillna(False)]:
        cid = df.at[idx, "company_id"] if _has(df, "company_id") else None
        yr = df.at[idx, "year"] if _has(df, "year") else None
        failures.append(
            DQFailure(
                rule_id="DQ-15",
                table="balancesheet",
                severity="INFO",
                message="Balance sheet matches exactly (assets = liabilities)",
                company_id=None if pd.isna(cid) else str(cid),
                year=None if pd.isna(yr) else str(yr),
                column="total_assets,total_liabilities",
                expected="informational",
                actual=float(ta.at[idx]),
                row_index=int(idx),
            )
        )
    return failures


# ---------------------------------------------------------------------------
# DQ-16: Coverage check (WARNING)
# Each company should have ≥ 5 years of P&L, BS, CF history.
# ---------------------------------------------------------------------------
@register_rule("DQ-16")
def dq16_coverage_check(tables: TableBundle) -> list[DQFailure]:
    failures: list[DQFailure] = []
    companies = tables.get("companies")
    if companies is None or not _has(companies, "id"):
        return failures
    all_ids = set(companies["id"].dropna().astype(str))

    for table in ("profitandloss", "balancesheet", "cashflow"):
        df = tables.get(table)
        if df is None or not _has(df, "company_id") or not _has(df, "year"):
            continue
        # Count valid years per company (exclude PARSE_ERROR years)
        valid = df[
            _year_matches(df["year"].astype(str)) & (df["year"].astype(str) != YEAR_PARSE_ERROR)
        ]
        counts = valid.groupby("company_id").size()
        # Companies with < 5 valid years in this table
        for cid in all_ids:
            n = int(counts.get(cid, 0))
            if n < 5:
                failures.append(
                    DQFailure(
                        rule_id="DQ-16",
                        table=table,
                        severity="WARNING",
                        message=f"Company has only {n} valid year(s) of {table} data (≥5 expected)",
                        company_id=cid,
                        column="year",
                        expected="≥ 5 years per company",
                        actual=n,
                    )
                )
    return failures


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------
def validate_all(
    tables: TableBundle,
    *,
    output_path: Path | str | None = None,
    rules: list[str] | None = None,
) -> dict[str, Any]:
    """Run every registered DQ rule (or the selected subset) and write CSV.

    Args:
        tables:      Mapping of dataset name → loaded (normalised) DataFrame.
        output_path: Destination for ``validation_failures.csv``. If None,
                     defaults to ``<PROCESSED_DATA_DIR>/validation_failures.csv``.
        rules:       Optional allow-list of rule IDs (e.g. ``["DQ-01","DQ-02"]``)
                     to run. Runs all 16 when omitted.

    Returns:
        Summary dict with counts, critical/warning/info breakdowns, output path,
        and the list of failures (as dicts).
    """
    all_failures: list[DQFailure] = []
    selected = set(rules) if rules else None

    for rule_id, fn in _RULE_REGISTRY:
        if selected is not None and rule_id not in selected:
            continue
        try:
            results = fn(tables)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"DQ rule {rule_id} raised an exception: {exc}")
            results = [
                DQFailure(
                    rule_id=rule_id,
                    table="(internal)",
                    severity="CRITICAL",
                    message=f"Rule execution error: {exc}",
                )
            ]
        all_failures.extend(results)
        logger.debug(f"DQ {rule_id}: {len(results)} violation(s)")

    # Summary
    crit = sum(1 for f in all_failures if f.severity == "CRITICAL")
    warn = sum(1 for f in all_failures if f.severity == "WARNING")
    info = sum(1 for f in all_failures if f.severity == "INFO")

    logger.info(
        f"DQ validation complete: {len(all_failures)} total "
        f"({crit} CRITICAL, {warn} WARNING, {info} INFO)"
    )

    # Write CSV
    if output_path is None:
        from src.utils.config import settings

        output_path = settings.PROCESSED_DATA_DIR / "validation_failures.csv"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if all_failures:
        df = pd.DataFrame([f.to_dict() for f in all_failures], columns=list(VALID_FIELDS))
        df.to_csv(output_path, index=False)
        logger.info(f"Wrote {len(df)} validation failure(s) to {output_path}")
    else:
        # Write an empty CSV with headers so downstream tools see the artifact
        pd.DataFrame(columns=list(VALID_FIELDS)).to_csv(output_path, index=False)
        logger.info(f"No DQ violations. Empty report written to {output_path}")

    return {
        "total_failures": len(all_failures),
        "critical": crit,
        "warning": warn,
        "info": info,
        "output_path": str(output_path),
        "failures": [f.to_dict() for f in all_failures],
        "rules_run": [rid for rid, _ in _RULE_REGISTRY if selected is None or rid in selected],
    }


def registered_rules() -> list[str]:
    """Return sorted list of registered DQ rule IDs (useful for introspection)."""
    return sorted(rid for rid, _ in _RULE_REGISTRY)
