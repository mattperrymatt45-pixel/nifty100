"""Nifty 100 Financial Intelligence Platform - NLP Package.

Modules (Sprint 5):
    parser        - Analysis text parser (Day 29) — regex extraction of
                    compounded growth / CAGR / ROE values from analysis.xlsx
                    with cross-validation against the Ratio Engine.
"""

from src.nlp.parser import (
    CAGR_DIVERGENCE_THRESHOLD_PCT,
    METRIC_COLUMNS,
    PARSE_REGEX,
    AnalysisParseResult,
    MetricMapping,
    cross_validate_parsed,
    load_analysis_workbook,
    parse_analysis_text,
    run_parser,
)

__all__ = [
    "CAGR_DIVERGENCE_THRESHOLD_PCT",
    "METRIC_COLUMNS",
    "PARSE_REGEX",
    "AnalysisParseResult",
    "MetricMapping",
    "cross_validate_parsed",
    "load_analysis_workbook",
    "parse_analysis_text",
    "run_parser",
]
