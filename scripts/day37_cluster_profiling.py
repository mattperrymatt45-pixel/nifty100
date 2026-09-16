"""Day 37 runner - Cluster Profiling & Statistics."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root on sys.path when run directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analytics.cluster_profiling import run_day37_profiling  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def main() -> None:
    result = run_day37_profiling()
    paths = result["paths"]
    print("=== Day 37 - Cluster Profiling & Statistics ===")
    print(f"Cluster profile       -> {paths['cluster_profile']}")
    print(f"Refined labels        -> {paths['labels']}")
    print(f"Correlation heatmap   -> {paths['heatmap']}")
    out_n = len(result["outliers"])
    print(f"Outlier report        -> {paths['outliers']} ({out_n} flags)")
    print(f"Portfolio stats       -> {paths['portfolio_stats']}")
    print()
    print("Cluster means (5 features):")
    print(result["cluster_means"].to_string(index=False))
    print()
    print("Outliers (top 10):")
    out = result["outliers"]
    if len(out) == 0:
        print("  None detected.")
    else:
        print(out.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
