"""Sprint 6 Day 36 - KMeans Clustering runner.

Groups all 92 Nifty-100 companies into 5 archetype clusters using
KMeans on five fundamental features. Produces output/cluster_labels.csv
and reports/elbow_plot.png.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.analytics.clustering import run_day36_clustering  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    print("=" * 60)
    print("  Day 36 - KMeans Clustering (5 archetypes)")
    print("=" * 60)

    result = run_day36_clustering()
    labels = result["labels"]
    centroids = result["centroids"]

    print(f"\n  Companies clustered : {len(labels)}")
    print("  Features            : ROE, D/E, 5yr Rev CAGR, 5yr FCF CAGR, Op Margin")
    print("\n  Cluster distribution:")
    counts = labels["cluster_name"].value_counts()
    for name, cnt in counts.items():
        cid = int(labels[labels["cluster_name"] == name]["cluster_id"].iloc[0])
        print(f"    [{cid}] {name:<25s}  {cnt:2d} companies")

    print("\n  Centroids (feature-space averages):")
    show_cols = [
        "cluster_id",
        "cluster_name",
        "return_on_equity_pct",
        "debt_to_equity",
        "revenue_cagr_5yr",
        "fcf_cagr_5yr",
        "operating_profit_margin_pct",
    ]
    print(centroids[show_cols].to_string(index=False, float_format=lambda x: f"{x:7.2f}"))

    print("\n  Outputs:")
    print(f"    {result['csv_path'].relative_to(PROJECT_ROOT)}")
    print(f"    {result['elbow_path'].relative_to(PROJECT_ROOT)}")
    print(f"    {result['centroids_path'].relative_to(PROJECT_ROOT)}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
