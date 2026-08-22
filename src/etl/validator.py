"""Compatibility shim — validator.py re-exports everything from validation.py.

The Sprint 1 deliverable list names the file ``validator.py``, while the
codebase uses ``validation.py`` (matching the module layout established on
Day 3). This shim keeps both import paths working so neither tests nor
downstream code break.
"""

from src.etl.validation import (
    VALID_FIELDS,
    DQFailure,
    registered_rules,
    validate_all,
)

__all__ = [
    "VALID_FIELDS",
    "DQFailure",
    "registered_rules",
    "validate_all",
]
