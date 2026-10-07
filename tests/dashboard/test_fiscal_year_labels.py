"""Tests for human-readable Indian fiscal-year labels in the dashboard."""

from src.dashboard.utils.theme import fy_label, fy_long, fy_short


def test_march_period_uses_year_ending_fy() -> None:
    """March 2024 is FY24 / FY 2023-24, not FY25."""
    assert fy_short("2024-03") == "FY24"
    assert fy_long("2024-03") == "FY 2023-24"
    assert fy_label("2024-03") == "FY 2023-24 (Mar 2024)"


def test_april_to_december_period_rolls_to_next_fy_end() -> None:
    """Periods after March belong to the next March-ending FY."""
    assert fy_short("2024-04") == "FY25"
    assert fy_long("2024-06") == "FY 2024-25"
    assert fy_label("2024-12") == "FY 2024-25 (Dec 2024)"


def test_january_to_march_period_stays_in_current_fy_end() -> None:
    """January 2024 is part of the Indian FY ending March 2024."""
    assert fy_short("2024-01") == "FY24"
    assert fy_long("2024-02") == "FY 2023-24"


def test_non_iso_year_labels_are_returned_unchanged() -> None:
    """Calendar years and invalid values remain safe pass-throughs."""
    assert fy_short("FY24") == "FY24"
    assert fy_long("2024") == "2024"
    assert fy_label("invalid") == "invalid"
    assert fy_short(None) == ""
