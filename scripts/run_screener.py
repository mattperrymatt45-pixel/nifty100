"""Sprint 3 Day 15 — CLI entry point for the screener filter engine.

Runs a preset (or custom thresholds) against financial_ratios and prints
a summary. Optionally writes the result to CSV or Excel.

Usage:
    python -m scripts.run_screener --preset quality_compounders
    python -m scripts.run_screener --preset dividend_aristocrats
        --export output/screener_dividends.csv
    python -m scripts.run_screener --custom min_roe_pct=20 max_pe_ratio=25
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screener import load_config, run_screener  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def _parse_custom(kv_list: list[str]) -> dict[str, float]:
    """Parse ['min_roe_pct=20', 'max_pe=25'] -> {metric: threshold}."""
    out: dict[str, float] = {}
    for kv in kv_list:
        if "=" not in kv:
            raise argparse.ArgumentTypeError(f"Custom filter must be key=value, got '{kv}'")
        key, val = kv.split("=", 1)
        out[key] = float(val)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Nifty 100 Screener")
    parser.add_argument(
        "--preset",
        type=str,
        default=None,
        help="Named preset from config/screener_config.yaml "
        "(quality_compounders, dividend_aristocrats, growth_at_reasonable_price, "
        "deep_value, debt_free, small_cap_momentum)",
    )
    parser.add_argument(
        "--custom",
        nargs="*",
        default=[],
        metavar="KEY=VALUE",
        help="Custom threshold overrides e.g. min_roe_pct=20 max_pe_ratio=25",
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="List available presets and exit",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Export filtered DataFrame to CSV or XLSX (inferred from extension)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Override DB path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Print only the top N rows (default: top 20)",
    )
    parser.add_argument(
        "--all-years",
        action="store_true",
        help="Include all company-years (not just latest FY per company)",
    )
    args = parser.parse_args()

    cfg = load_config()

    if args.list_presets:
        print("Available screener presets:\n")
        for name, preset in cfg.presets.items():
            print(f"  {name:30s} — {preset.label}")
            if preset.description:
                first_line = preset.description.strip().split("\n")[0]
                print(f"    {'':30s}   {first_line[:90]}")
            print()
        return 0

    if args.preset is None and not args.custom:
        parser.error("Specify --preset NAME, --custom KEY=VALUE ..., or --list-presets")

    # Build a base preset: either a named one or an empty preset for custom-only
    if args.preset:
        base = cfg.preset(args.preset)
    else:
        from src.screener.engine import ScreenerPreset

        base = ScreenerPreset(name="custom", label="Custom Screen", description="", filters=[])

    custom = _parse_custom(args.custom)

    result = run_screener(
        base,
        config=cfg,
        db_path=args.db_path,
        latest_year_only=not args.all_years,
        custom_filters=custom or None,
    )

    print()
    print("=" * 100)
    print(f"  {result.preset_label}")
    print("=" * 100)
    print(f"  Rows passing: {result.rows_out} / {result.rows_in}")
    print(f"  Filters applied: {len(result.filters_applied)}")
    for f in result.filters_applied:
        print(f"    * {f.metric:25s} {f.direction:>3s}  {f.threshold}")
    print()

    # Display columns
    display_cols = [
        "rank",
        "company_id",
        "company_name",
        "broad_sector",
        "roe_pct",
        "debt_to_equity",
        "roce_pct",
        "revenue_cagr_5yr",
        "operating_profit_margin_pct",
        "pe_ratio",
        "dividend_yield_pct",
        "icr",
        "composite_quality_score",
    ]
    avail = [c for c in display_cols if c in result.df.columns]
    limit = args.limit if args.limit is not None else 20
    show = result.df[avail].head(limit)
    if len(show) > 0:
        # Round floats for readability
        with pd.option_context(
            "display.max_columns", None, "display.width", 200, "display.max_colwidth", 28
        ):
            print(show.to_string(index=False))
    print()

    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        suffix = args.export.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            result.df.to_excel(args.export, index=False)
        else:
            result.df.to_csv(args.export, index=False)
        print(f"  Exported {len(result.df)} rows to {args.export}")

    print(f"\n{result.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
