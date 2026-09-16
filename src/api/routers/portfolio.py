"""Portfolio router - portfolio-level analytics (stats, clusters etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter

from src.api.db import get_db_connection
from src.utils.config import settings

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])

_KPI_COLUMNS: tuple[tuple[str, str], ...] = (
    ("return_on_equity_pct", "ROE (%)"),
    ("roce_pct", "ROCE (%)"),
    ("debt_to_equity", "Debt/Equity"),
    ("revenue_cagr_5yr", "Revenue CAGR 5y (%)"),
    ("pat_cagr_5yr", "PAT CAGR 5y (%)"),
    ("operating_profit_margin_pct", "OPM (%)"),
    ("net_profit_margin_pct", "NPM (%)"),
    ("dividend_payout_ratio_pct", "Div Payout (%)"),
    ("pe_ratio", "P/E Ratio"),
    ("pb_ratio", "P/B Ratio"),
)

_LATEST_KPI_QUERY = """
    SELECT fr.return_on_equity_pct, fr.roce_pct, fr.debt_to_equity,
           fr.revenue_cagr_5yr, fr.pat_cagr_5yr, fr.operating_profit_margin_pct,
           fr.net_profit_margin_pct, fr.dividend_payout_ratio_pct,
           mc.pe_ratio, mc.pb_ratio
    FROM financial_ratios fr
    LEFT JOIN market_cap mc ON mc.company_id = fr.company_id
        AND mc.year = CAST(SUBSTR(fr.year, 1, 4) AS INTEGER)
    WHERE fr.year = (
        SELECT MAX(year) FROM financial_ratios fr2 WHERE fr2.company_id = fr.company_id
    )
"""


@router.get("/stats", summary="Portfolio percentile statistics across all 92 companies")
def portfolio_stats() -> dict:
    """Return P10/P25/P50/P75/P90/Mean/Std for the 10 core KPIs across all
    companies. Serves directly from the production DB (regenerates the
    stats on demand so they reflect the latest data); matches
    ``output/portfolio_stats.csv`` schema from Day 37.
    """
    with get_db_connection() as conn:
        df = pd.read_sql(_LATEST_KPI_QUERY, conn)
    records: list[dict[str, Any]] = []
    for col, label in _KPI_COLUMNS:
        s = df[col].dropna()
        records.append(
            {
                "metric": col,
                "metric_label": label,
                "count": int(s.count()),
                "p10": round(float(s.quantile(0.10)), 4),
                "p25": round(float(s.quantile(0.25)), 4),
                "p50": round(float(s.quantile(0.50)), 4),
                "p75": round(float(s.quantile(0.75)), 4),
                "p90": round(float(s.quantile(0.90)), 4),
                "mean": round(float(s.mean()), 4),
                "std": round(float(s.std(ddof=1)), 4) if s.count() > 1 else 0.0,
            }
        )
    return {"kpi_count": len(records), "stats": records}


@router.get("/clusters", summary="Cluster archetype assignments (Day 36)")
def clusters() -> dict:
    """Return the Day-36/37 cluster assignments from output/cluster_labels.csv."""
    csv_path = Path(settings.PROJECT_ROOT) / "output" / "cluster_labels.csv"
    if not csv_path.exists():
        return {"count": 0, "clusters": [], "note": "cluster_labels.csv not found"}
    df = pd.read_csv(csv_path)
    return {"count": len(df), "clusters": df.to_dict(orient="records")}


__all__ = ["router"]
