"""Sprint 2 Day 13 — Bank ROCE Carve-Out & Ratio Edge-Case Log.

Cross-checks the computed ROCE and ROE values in financial_ratios against the
pre-computed reference values in companies.xlsx (roce_percentage, roe_percentage).
For banks / NBFCs / insurance companies the high-D/E flag is suppressed and
a ROA-proxy is stored in ``roce_sector_adjusted``.  All anomalies above 5pp (ROCE)
/ 10pp (ROE) are categorised and written to ``output/ratio_edge_cases.log``.

Usage:
    python -m scripts.day13_bank_roce
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.analytics.sector_roce import (  # noqa: E402
    compute_bank_roce,
    cross_check_vs_source,
    format_anomaly_log,
    is_bank_nfc_insurance,
)
from src.etl.database import get_connection, init_schema  # noqa: E402
from src.utils.config import settings  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def run_bank_carveout(
    db_path: Path | str | None = None,
    log_path: Path | str | None = None,
) -> tuple[int, str]:
    """Apply bank ROCE carve-out, run cross-check, write log. Return (n_anomalies, log_text).

    Args:
        db_path: Override DB path (defaults to settings.DB_PATH).
        log_path: Override log output path (defaults to output/ratio_edge_cases.log).
    """
    init_schema(db_path)
    all_anomalies = []
    updates: list[dict] = []

    with get_connection(db_path) as conn:
        # Pull latest-year financial_ratios joined to companies + sectors
        sql = """
            SELECT
                fr.company_id, fr.year,
                fr.roce_pct            AS computed_roce,
                fr.return_on_equity_pct AS computed_roe,
                fr.high_leverage_flag,
                co.company_name,
                co.roce_percentage     AS source_roce,
                co.roe_percentage      AS source_roe,
                COALESCE(s.broad_sector, '') AS broad_sector,
                p.operating_profit,
                p.depreciation,
                b.total_assets
            FROM financial_ratios fr
            JOIN companies co ON co.id = fr.company_id
            LEFT JOIN sectors s ON s.company_id = fr.company_id
            JOIN profitandloss p ON p.company_id = fr.company_id AND p.year = fr.year
            JOIN balancesheet b   ON b.company_id = fr.company_id AND b.year = fr.year
            ORDER BY fr.company_id, fr.year
        """
        df = pd.read_sql_query(sql, conn)

    logger.info(f"Cross-checking ROCE/ROE for {len(df)} company-year rows")

    for _, r in df.iterrows():
        is_fin = is_bank_nfc_insurance(r["broad_sector"])
        sector_roce = None
        if is_fin:
            sector_roce = compute_bank_roce(
                operating_profit=float(r["operating_profit"]),
                depreciation=float(r["depreciation"]) if pd.notna(r["depreciation"]) else 0.0,
                total_assets=float(r["total_assets"]),
            )

        anomalies = cross_check_vs_source(
            company_id=r["company_id"],
            company_name=r["company_name"] or r["company_id"],
            broad_sector=r["broad_sector"] or "",
            year=r["year"],
            computed_roce=float(r["computed_roce"]) if pd.notna(r["computed_roce"]) else None,
            source_roce=float(r["source_roce"]) if pd.notna(r["source_roce"]) else None,
            computed_roe=float(r["computed_roe"]) if pd.notna(r["computed_roe"]) else None,
            source_roe=float(r["source_roe"]) if pd.notna(r["source_roe"]) else None,
        )
        all_anomalies.extend(anomalies)

        roce_cat = next((a.category for a in anomalies if a.metric == "ROCE"), None)
        roe_cat = next((a.category for a in anomalies if a.metric == "ROE"), None)

        updates.append(
            {
                "company_id": r["company_id"],
                "year": r["year"],
                "roce_sector_adjusted": sector_roce,
                "roce_source_value": (
                    float(r["source_roce"]) if pd.notna(r["source_roce"]) else None
                ),
                "roe_source_value": float(r["source_roe"]) if pd.notna(r["source_roe"]) else None,
                "roce_anomaly_category": roce_cat,
                "roe_anomaly_category": roe_cat,
            }
        )

    # Write updates via in-place UPDATE (load_dataframe with merge=True does a
    # DELETE+INSERT which would null out every other column — unsafe for partial
    # column updates).
    with get_connection() as conn:
        conn.executemany(
            """
            UPDATE financial_ratios
               SET roce_sector_adjusted = ?,
                   roce_source_value    = ?,
                   roe_source_value     = ?,
                   roce_anomaly_category = ?,
                   roe_anomaly_category  = ?
             WHERE company_id = ? AND year = ?
            """,
            [
                (
                    u["roce_sector_adjusted"],
                    u["roce_source_value"],
                    u["roe_source_value"],
                    u["roce_anomaly_category"],
                    u["roe_anomaly_category"],
                    u["company_id"],
                    u["year"],
                )
                for u in updates
            ],
        )
        conn.commit()
    logger.info(f"Updated {len(updates)} rows with Day-13 carve-out metadata")

    log_text = format_anomaly_log(all_anomalies)

    # Write log to output/ (default) or a caller-supplied path (e.g. tests)
    target_log = Path(log_path) if log_path else (settings.OUTPUT_DIR / "ratio_edge_cases.log")
    target_log.parent.mkdir(parents=True, exist_ok=True)
    target_log.write_text(log_text + "\n", encoding="utf-8")
    logger.info(f"Wrote ratio edge-case log to {target_log} ({len(all_anomalies)} anomalies)")
    return len(all_anomalies), log_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 13 bank ROCE carve-out")
    parser.add_argument("--db-path", type=Path, default=None, help="Override DB path")
    parser.add_argument("--log-path", type=Path, default=None, help="Override log output path")
    args = parser.parse_args()
    n, _ = run_bank_carveout(db_path=args.db_path, log_path=args.log_path)
    print(
        f"Day 13 complete: {n} anomalies logged to {args.log_path or 'output/ratio_edge_cases.log'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
