"""Unit tests for src.etl.normalizers.

Test cases cover every example in the spec §23 ETL Edge Cases table
(pages 37-38) plus additional edge cases discovered during code review.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.etl.exceptions import TickerParseError, YearParseError
from src.etl.normalizers import (
    YEAR_PARSE_ERROR,
    normalize_ticker,
    normalize_ticker_safe,
    normalize_year,
    normalize_year_safe,
)


# =========================================================================
# normalize_ticker — spec §23 examples
# =========================================================================
class TestNormalizeTicker:
    def test_ticker_strip_whitespace(self) -> None:
        """'  TCS  ' → 'TCS'."""
        assert normalize_ticker("  TCS  ") == "TCS"

    def test_ticker_uppercase(self) -> None:
        """'tcs' → 'TCS'."""
        assert normalize_ticker("tcs") == "TCS"

    def test_ticker_already_canonical(self) -> None:
        """'TCS' passes through unchanged."""
        assert normalize_ticker("TCS") == "TCS"

    def test_ticker_hyphen_preserved(self) -> None:
        """'BAJAJ-AUTO' keeps its hyphen."""
        assert normalize_ticker("bajaj-auto") == "BAJAJ-AUTO"

    def test_ticker_ampersand_preserved(self) -> None:
        """'m&m' → 'M&M'."""
        assert normalize_ticker("m&m") == "M&M"

    def test_ticker_mixed_case(self) -> None:
        assert normalize_ticker("InFoSyS") == "INFOSYS"

    def test_ticker_collapses_internal_double_space(self) -> None:
        # Screener.in occasionally emits double-spaced names; we collapse.
        assert normalize_ticker("BAJAJ  AUTO") == "BAJAJ AUTO"

    def test_ticker_multi_symbol(self) -> None:
        """L&TFH is a real NSE ticker (L&T Finance Holdings)."""
        assert normalize_ticker("l&tfh") == "L&TFH"

    def test_ticker_none_raises(self) -> None:
        with pytest.raises(TickerParseError):
            normalize_ticker(None)

    def test_ticker_empty_string_raises(self) -> None:
        with pytest.raises(TickerParseError):
            normalize_ticker("")

    def test_ticker_whitespace_only_raises(self) -> None:
        with pytest.raises(TickerParseError):
            normalize_ticker("   \t  ")

    def test_ticker_integer_raises(self) -> None:
        # Numeric company_id doesn't make sense for NSE.
        with pytest.raises(TickerParseError):
            normalize_ticker(12345)  # type: ignore[arg-type]

    def test_ticker_float_raises(self) -> None:
        with pytest.raises(TickerParseError):
            normalize_ticker(3.14)  # type: ignore[arg-type]

    def test_ticker_single_character(self) -> None:
        # Edge case — no real NSE ticker is one letter, but the function
        # should not crash if it encounters one.
        assert normalize_ticker(" a ") == "A"

    # ---- safe wrapper ----
    def test_ticker_safe_returns_none_on_bad_input(self) -> None:
        assert normalize_ticker_safe(None) is None
        assert normalize_ticker_safe("") is None

    def test_ticker_safe_returns_value_on_good_input(self) -> None:
        assert normalize_ticker_safe("tcs") == "TCS"


# =========================================================================
# normalize_year — spec §23 examples
# =========================================================================
class TestNormalizeYearMarFormats:
    def test_mar23_short(self) -> None:
        """'Mar-23' → '2023-03' (spec canonical example)."""
        assert normalize_year("Mar-23") == "2023-03"

    def test_mar_23_space(self) -> None:
        """'Mar 23' (space separator)."""
        assert normalize_year("Mar 23") == "2023-03"

    def test_march_full_name_hyphen(self) -> None:
        """'March-2023' → '2023-03'."""
        assert normalize_year("March-2023") == "2023-03"

    def test_march_full_name_space(self) -> None:
        """'March 2023' → '2023-03'."""
        assert normalize_year("March 2023") == "2023-03"

    def test_mar23_with_surrounding_whitespace(self) -> None:
        assert normalize_year("  Mar-23  ") == "2023-03"

    def test_lowercase(self) -> None:
        assert normalize_year("mar-23") == "2023-03"

    def test_underscore_separator(self) -> None:
        assert normalize_year("Mar_23") == "2023-03"

    def test_slash_separator(self) -> None:
        assert normalize_year("Mar/23") == "2023-03"


class TestNormalizeYearBareYear:
    def test_bare_integer_2023(self) -> None:
        """2023 (int) → 2023-03."""
        assert normalize_year(2023) == "2023-03"

    def test_bare_string_2023(self) -> None:
        """'2023' → 2023-03."""
        assert normalize_year("2023") == "2023-03"

    def test_bare_string_two_digit(self) -> None:
        """'23' → 2023-03 (pivot rule: ≤50 → 20xx)."""
        assert normalize_year("23") == "2023-03"

    def test_bare_float_2023(self) -> None:
        """2023.0 → 2023-03 (Excel occasionally returns floats)."""
        assert normalize_year(2023.0) == "2023-03"

    def test_bare_integer_2024(self) -> None:
        assert normalize_year(2024) == "2024-03"

    def test_bare_integer_2010(self) -> None:
        assert normalize_year(2010) == "2010-03"


class TestNormalizeYearFYPrefix:
    def test_fy23(self) -> None:
        """'FY23' → '2023-03'."""
        assert normalize_year("FY23") == "2023-03"

    def test_fy_24(self) -> None:
        """'FY 24' → '2024-03'."""
        assert normalize_year("FY 24") == "2024-03"

    def test_fy_2024(self) -> None:
        """'FY-2024' → '2024-03'."""
        assert normalize_year("FY-2024") == "2024-03"

    def test_fy_dotted(self) -> None:
        """'F.Y. 2023' → '2023-03'."""
        assert normalize_year("F.Y. 2023") == "2023-03"

    def test_fyfy_double_prefix(self) -> None:
        """'FY FY 24' (shouldn't happen, but we tolerate)."""
        assert normalize_year("FYFY24") == "2024-03"


class TestNormalizeYearOtherCloseMonths:
    def test_dec22(self) -> None:
        """'Dec-22' → '2022-12' (NESTLEIND has December year-end)."""
        assert normalize_year("Dec-22") == "2022-12"

    def test_jun23(self) -> None:
        """'Jun-23' → '2023-06' (some banks)."""
        assert normalize_year("Jun-23") == "2023-06"

    def test_sep21(self) -> None:
        assert normalize_year("Sep-21") == "2021-09"

    def test_january_2020(self) -> None:
        assert normalize_year("January-2020") == "2020-01"


class TestNormalizeYearAlreadyNormalized:
    def test_already_yyyy_mm(self) -> None:
        """'2023-03' → '2023-03'."""
        assert normalize_year("2023-03") == "2023-03"

    def test_already_yyyy_mm_with_padding(self) -> None:
        assert normalize_year(" 2022-12 ") == "2022-12"

    def test_already_yyyy_single_digit_month(self) -> None:
        # '2023-3' is unusual but valid — we accept and repad.
        assert normalize_year("2023-3") == "2023-03"


class TestNormalizeYearDateTimeInput:
    def test_datetime_object(self) -> None:
        # If Excel parsed 'Mar-23' as a real date we should still accept it.
        assert normalize_year(datetime(2023, 3, 31)) == "2023-03"


class TestNormalizeYearTwoDigitPivot:
    def test_99_maps_to_1999(self) -> None:
        """Two-digit years > 50 → 19xx (pivot)."""
        assert normalize_year("99") == "1999-03"

    def test_50_maps_to_2050(self) -> None:
        assert normalize_year("50") == "2050-03"

    def test_51_maps_to_1951(self) -> None:
        # 51 is the pivot cutoff; >50 → 19xx
        assert normalize_year("51") == "1951-03"


class TestNormalizeYearErrors:
    def test_garbage_raises(self) -> None:
        """'garbage' → YearParseError (spec example)."""
        with pytest.raises(YearParseError):
            normalize_year("garbage")

    def test_none_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year(None)

    def test_empty_string_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year("")

    def test_bad_month_abbreviation_raises(self) -> None:
        """'XYZ-99' — 'XYZ' is not a valid month."""
        with pytest.raises(YearParseError):
            normalize_year("XYZ-99")

    def test_nan_float_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year(float("nan"))

    def test_boolean_raises(self) -> None:
        # bool is an int subclass — make sure we explicitly reject it.
        with pytest.raises(YearParseError):
            normalize_year(True)  # type: ignore[arg-type]
        with pytest.raises(YearParseError):
            normalize_year(False)  # type: ignore[arg-type]

    def test_zero_year_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year(0)

    def test_negative_year_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year(-23)

    def test_invalid_month_in_yyyy_mm_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year("2023-13")

    def test_yyyy_mm_too_old_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year("1800-03")

    def test_unknown_suffix_raises(self) -> None:
        with pytest.raises(YearParseError):
            normalize_year("Mar-23Q")  # trailing junk


class TestNormalizeYearSafe:
    def test_safe_returns_sentinel_on_error(self) -> None:
        assert normalize_year_safe("garbage") == YEAR_PARSE_ERROR
        assert normalize_year_safe(None) == YEAR_PARSE_ERROR

    def test_safe_returns_value_on_success(self) -> None:
        assert normalize_year_safe("Mar-23") == "2023-03"
        assert normalize_year_safe(2024) == "2024-03"
