"""Spec-mandated DQ rule smoke tests (tests/dq/test_rules.py per spec p.41).

These are the two examples cited directly in §27 (Test Framework):
    test_dq04_bs_balance  — assets=1000, liab=1020 → DQ-04 WARNING
    test_dq06_zero_sales  — sales=0                 → DQ-06 WARNING

The full 16-rule suite lives in tests/etl/test_validation.py.
"""

from __future__ import annotations

import pandas as pd

from src.etl.validation import dq04_balance_sheet_balance, dq06_positive_sales


def test_dq04_bs_balance() -> None:
    """Spec example: assets=1000, liab=1020 → DQ-04 WARNING triggered."""
    df = pd.DataFrame(
        {
            "company_id": ["X"],
            "year": ["2023-03"],
            "total_assets": [1000.0],
            "total_liabilities": [1020.0],
        }
    )
    failures = dq04_balance_sheet_balance({"balancesheet": df})
    assert len(failures) == 1
    assert failures[0].rule_id == "DQ-04"
    assert failures[0].severity == "WARNING"


def test_dq06_zero_sales() -> None:
    """Spec example: sales=0 → DQ-06 WARNING triggered."""
    df = pd.DataFrame({"company_id": ["X"], "year": ["2023-03"], "sales": [0.0]})
    failures = dq06_positive_sales({"profitandloss": df})
    assert len(failures) == 1
    assert failures[0].rule_id == "DQ-06"
    assert failures[0].severity == "WARNING"
