"""Nifty 100 Financial Intelligence Platform - NLP Package.

Modules (Sprint 5):
    parser              - Analysis text parser (Day 29) — regex extraction of
                          compounded growth / CAGR / ROE values from analysis.xlsx
                          with cross-validation against the Ratio Engine.
    pros_cons_generator - Auto pros/cons generator (Day 30) — 12 pro rules +
                          12 con rules (plus watch-list rules) evaluating
                          multi-year fundamentals, with confidence scores.
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
from src.nlp.pros_cons_generator import (
    CON_RULES,
    CONFIDENCE_THRESHOLD,
    FINANCIAL_SECTORS,
    PRO_RULES,
    CompanyContext,
    ProsConsResult,
    RuleResult,
    generate_pros_cons,
)

__all__ = [
    "CAGR_DIVERGENCE_THRESHOLD_PCT",
    "CONFIDENCE_THRESHOLD",
    "CON_RULES",
    "FINANCIAL_SECTORS",
    "METRIC_COLUMNS",
    "PARSE_REGEX",
    "PRO_RULES",
    "AnalysisParseResult",
    "CompanyContext",
    "MetricMapping",
    "ProsConsResult",
    "RuleResult",
    "cross_validate_parsed",
    "generate_pros_cons",
    "load_analysis_workbook",
    "parse_analysis_text",
    "run_parser",
]
