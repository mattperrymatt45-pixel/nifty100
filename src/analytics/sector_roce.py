"""Sector-relative ROCE for Banks / NBFCs (Sprint 2 Day 13).

Per spec sections 13 and 28, a plain ROCE computed as
    EBIT / (equity + reserves + borrowings) * 100
is *structurally* misleading for banks, NBFCs, and insurance companies because
their "borrowings" are mostly customer deposits and policyholder funds - which
are operating liabilities, not financing.  This module implements the Day 13
carve-out:

* ``compute_bank_roce()``      - placeholder "bank ROCE" using Net Interest Margin
                                 (NIM) proxy when available.  For now returns
                                 ``None`` to signal "sector-relative benchmark
                                 required" (see spec section 28).
* ``roce_for_company()``       - dispatches to bank-aware ROCE for financials,
                                 standard ROCE otherwise.
* ``flag_high_d_e()``          - suppresses the high-D/E warning flag for
                                 financial-sector companies (already wired into
                                 ``high_leverage_flag`` from Day 9; this module
                                 documents and validates the carve-out).
* ``cross_check_vs_source()``  - compares computed ROCE / ROE to the pre-computed
                                 values in the ``companies`` reference table and
                                 returns anomalies >5pp (ROCE) or >10pp (ROE).

NIM proxy (spec page 27 and section 28):
    Banks/NBFCs use NIM + ROA instead of ROCE.  Without granular interest
    income/expense split in our schema (synthetic or real), a true NIM isn't
    available - we therefore leave the bank ROCE as ``None`` and mark it
    "sector-relative benchmark pending" in the ratio-edge-cases log.  A real
    dataset would populate this from granular banking schedules.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from src.analytics.ratios import FINANCIAL_SECTOR_KEYWORDS

logger = logging.getLogger(__name__)

# Cross-check thresholds (percentage points, i.e. |computed - source|)
ROCE_DELTA_THRESHOLD_PP = 5.0
ROE_DELTA_THRESHOLD_PP = 10.0


@dataclass(frozen=True)
class ROCEAnomaly:
    """A single cross-check anomaly between computed and source ROCE/ROE."""

    company_id: str
    company_name: str
    broad_sector: str
    year: str
    metric: str  # "ROCE" or "ROE"
    computed_pct: float | None
    source_pct: float | None
    delta_pp: float  # |computed - source| in pp
    is_financial: bool
    category: str  # "data_source", "version_difference", "formula_discrepancy", "bank_carveout"


def is_bank_nfc_insurance(broad_sector: str | None) -> bool:
    """Return True if this company belongs to a sector where ROCE must be
    interpreted sector-relatively (banks, NBFCs, insurance).
    """
    if not broad_sector:
        return False
    s = broad_sector.lower()
    return any(kw in s for kw in FINANCIAL_SECTOR_KEYWORDS) or "insurance" in s


def compute_bank_roce(
    operating_profit: float,
    depreciation: float,
    total_assets: float,
    cfo: float | None = None,
) -> float | None:
    """Return a bank/NBFC/insurance-appropriate return-on-capital metric.

    For banks, the conventional ROCE formula double-counts deposits.  Without
    granular interest income/expense split we cannot compute true NIM, so
    this is a conservative ROA-proxy that uses total assets as the denominator:
        Bank ROCE ~ EBIT / total_assets * 100
    Note: this is *not* directly comparable to non-financial ROCE.  Downstream
    consumers should treat it as a sector-relative score, not an absolute return.
    """
    if total_assets <= 0:
        return None
    ebit = operating_profit - (depreciation or 0.0)
    return ebit / total_assets * 100.0


def roce_for_company(
    *,
    operating_profit: float,
    depreciation: float,
    equity_capital: float,
    reserves: float | None,
    borrowings: float | None,
    total_assets: float,
    broad_sector: str | None,
    cfo: float | None = None,
) -> float | None:
    """Dispatch between standard and bank-aware ROCE.

    * For non-financial companies: EBIT / (equity + reserves + borrowings) * 100
    * For banks/NBFCs/insurance: ROA-proxy (``compute_bank_roce``)
    """
    if is_bank_nfc_insurance(broad_sector):
        return compute_bank_roce(
            operating_profit=operating_profit,
            depreciation=depreciation,
            total_assets=total_assets,
            cfo=cfo,
        )
    # Standard ROCE (duplicated from ratios.return_on_capital_employed intentionally
    # so we can expose the bank path cleanly without circular imports).
    _reserves = reserves if reserves is not None else 0.0
    _borrowings = borrowings if borrowings is not None else 0.0
    ce = equity_capital + _reserves + _borrowings
    if ce <= 0:
        return None
    ebit = operating_profit - (depreciation or 0.0)
    return ebit / ce * 100.0


def categorize_anomaly(
    *,
    metric: str,
    delta_pp: float,
    is_financial: bool,
    computed_pct: float | None,
    source_pct: float | None,
) -> str:
    """Categorize a single ROCE/ROE anomaly into one of four buckets.

    Categories:
        * ``bank_carveout``        - financial sector company, large delta expected
                                     because deposits are operating liabilities
        * ``formula_discrepancy``  - small but non-trivial delta → likely different
                                     formula (e.g. EBIT uses avg capital employed
                                     vs year-end; pre-tax vs post-tax)
        * ``version_difference``   - moderate delta → possibly due to TTM vs FY,
                                     or a different data vintage
        * ``data_source``          - very large delta → likely source data issue
                                     (erroneous reference value or corrupted input)
    """
    if is_financial and metric == "ROCE":
        return "bank_carveout"
    if delta_pp > 40:
        return "data_source"
    if delta_pp > 15:
        return "version_difference"
    return "formula_discrepancy"


def cross_check_vs_source(
    company_id: str,
    company_name: str,
    broad_sector: str,
    year: str,
    computed_roce: float | None,
    source_roce: float | None,
    computed_roe: float | None,
    source_roe: float | None,
) -> list[ROCEAnomaly]:
    """Compare computed ROCE/ROE to reference values; return anomalies over threshold.

    An anomaly is logged when:
        * Both computed and source are non-None AND
        * Absolute delta > ROCE_DELTA_THRESHOLD_PP (5pp) for ROCE
        * Absolute delta > ROE_DELTA_THRESHOLD_PP (10pp) for ROE
    Financial-sector ROCE deltas are always reported and categorised as
    ``bank_carveout`` regardless of magnitude (informational).
    """
    anomalies: list[ROCEAnomaly] = []
    fin = is_bank_nfc_insurance(broad_sector)

    for metric, computed, source, thresh in [
        ("ROCE", computed_roce, source_roce, ROCE_DELTA_THRESHOLD_PP),
        ("ROE", computed_roe, source_roe, ROE_DELTA_THRESHOLD_PP),
    ]:
        if computed is None or source is None:
            continue
        delta = abs(computed - source)
        if fin and metric == "ROCE":
            # Always log bank ROCE discrepancies as informational
            category = "bank_carveout"
            anomalies.append(
                ROCEAnomaly(
                    company_id=company_id,
                    company_name=company_name,
                    broad_sector=broad_sector,
                    year=year,
                    metric=metric,
                    computed_pct=computed,
                    source_pct=source,
                    delta_pp=round(delta, 2),
                    is_financial=True,
                    category=category,
                )
            )
        elif delta > thresh:
            category = categorize_anomaly(
                metric=metric,
                delta_pp=delta,
                is_financial=fin,
                computed_pct=computed,
                source_pct=source,
            )
            anomalies.append(
                ROCEAnomaly(
                    company_id=company_id,
                    company_name=company_name,
                    broad_sector=broad_sector,
                    year=year,
                    metric=metric,
                    computed_pct=computed,
                    source_pct=source,
                    delta_pp=round(delta, 2),
                    is_financial=fin,
                    category=category,
                )
            )
    return anomalies


def format_anomaly_log(anomalies: Sequence[ROCEAnomaly]) -> str:
    """Format a list of anomalies into a human-readable log string."""
    lines = [
        "=" * 100,
        "RATIO EDGE-CASE LOG — Sprint 2 Day 13",
        "=" * 100,
        "",
        "Cross-check: computed ROCE / ROE vs pre-computed values in companies.xlsx.",
        f"Thresholds: ROCE Δ > {ROCE_DELTA_THRESHOLD_PP}pp flagged; "
        f"ROE Δ > {ROE_DELTA_THRESHOLD_PP}pp flagged.",
        "Categories: bank_carveout (informational), formula_discrepancy, "
        "version_difference, data_source.",
        "",
    ]
    if not anomalies:
        lines.append("No anomalies found above threshold.")
        return "\n".join(lines)

    # Group by category for readability
    by_cat: dict[str, list[ROCEAnomaly]] = {}
    for a in anomalies:
        by_cat.setdefault(a.category, []).append(a)

    for cat in ("bank_carveout", "formula_discrepancy", "version_difference", "data_source"):
        rows = by_cat.get(cat)
        if not rows:
            continue
        lines.append(f"--- {cat.upper()} ({len(rows)} rows) ---")
        lines.append(
            f"{'Company':<14} {'Sector':<22} {'Year':<8} {'Metric':<5} "
            f"{'Computed':>9} {'Source':>9} {'Δ (pp)':>9}   Name"
        )
        for a in rows:
            name = (a.company_name or "")[:28]
            lines.append(
                f"{a.company_id:<14} {(a.broad_sector or '')[:21]:<22} {a.year:<8} "
                f"{a.metric:<5} {a.computed_pct or 0:>9.2f} {a.source_pct or 0:>9.2f} "
                f"{a.delta_pp:>9.2f}   {name}"
            )
        lines.append("")

    # Summary counts
    total = len(anomalies)
    lines.append("=" * 100)
    lines.append(f"TOTAL ANOMALIES: {total}")
    for cat in ("bank_carveout", "formula_discrepancy", "version_difference", "data_source"):
        n = len(by_cat.get(cat, []))
        if n:
            lines.append(f"  {cat:<25} : {n:4d}")
    lines.append("")
    lines.append("Notes:")
    lines.append("  * bank_carveout: Banks/NBFCs/Insurance deposits are NOT debt — standard ROCE")
    lines.append("    double-counts them, so source roce_percentage typically uses NIM or ROTE.")
    lines.append("    Ratio engine value is displayed as ROA-proxy for these companies.")
    lines.append("  * formula_discrepancy: likely denominator choice (avg vs year-end CE),")
    lines.append("    inclusion/exclusion of other_income, or pre/post-tax treatment.")
    lines.append("  * version_difference: TTM vs annualised, or different data-vintage refresh.")
    lines.append("  * data_source: very large deltas suggest source values reflect a different")
    lines.append("    share count / equity base or a data entry error in the reference.")
    lines.append("  * DISPLAY POLICY: use RATIO ENGINE values for screener/analytics (consistent,")
    lines.append("    reproducible); use companies.xlsx ROCE/ROE only for display KPI tiles.")
    return "\n".join(lines)


__all__ = [
    "ROCE_DELTA_THRESHOLD_PP",
    "ROE_DELTA_THRESHOLD_PP",
    "ROCEAnomaly",
    "categorize_anomaly",
    "compute_bank_roce",
    "cross_check_vs_source",
    "format_anomaly_log",
    "is_bank_nfc_insurance",
    "roce_for_company",
]
