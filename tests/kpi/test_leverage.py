"""
Unit tests for the Sprint 2 Day 09 leverage & efficiency ratio engine.

Covers the spec-required edge cases:
    1. Normal healthy company — D/E, ICR, net debt, asset turnover compute
    2. Debt-free company (borrowings=0) — D/E returns 0 (not None)
    3. ICR with interest=0 returns None (debt-free)
    4. icr_label == "Debt Free" when interest=0
    5. High D/E flag triggers for non-financial companies (D/E > 5)
    6. High D/E flag does NOT trigger for banks/NBFCs (carve-out)
    7. ICR warning flag when ICR < 1.5; no flag for debt-free
    8. Net debt = borrowings - investments; negative = net cash
    9. Asset turnover returns None when total_assets = 0
    10. Negative equity with debt → D/E None (meaningless ratio)
"""

from __future__ import annotations

import pytest

from src.analytics.leverage import (
    HIGH_LEVERAGE_DE_THRESHOLD,
    ICR_DEBT_FREE_LABEL,
    ICR_WARNING_THRESHOLD,
    LeverageRatios,
    asset_turnover,
    compute_leverage_ratios,
    debt_to_equity,
    high_leverage_flag,
    icr_display_label,
    icr_warning_flag,
    interest_coverage_ratio,
    net_debt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normal_company(**overrides) -> LeverageRatios:
    """Return ratios for a baseline healthy non-financial company.

    Defaults: sales=1000, EBITDA=250, other_income=10, interest=40 (ICR=6.5),
    equity=100, reserves=500 (equity=600), borrowings=200 (D/E=0.33),
    investments=80 (net_debt=120), total_assets=1500 (AT=0.67).
    """
    base = dict(
        sales=1000.0,
        operating_profit=250.0,
        other_income=10.0,
        interest=40.0,
        equity_capital=100.0,
        reserves=500.0,
        borrowings=200.0,
        investments=80.0,
        total_assets=1500.0,
        broad_sector="Consumer Staples",
        company_id="HINDUNILVR",
        year="2023-03",
    )
    base.update(overrides)
    return compute_leverage_ratios(**base)


# ---------------------------------------------------------------------------
# 1. Normal case
# ---------------------------------------------------------------------------
class TestNormalCase:
    def test_debt_to_equity(self) -> None:
        r = _normal_company()
        # borrowings=200, equity=600 → 0.333...
        assert r.debt_to_equity == pytest.approx(200.0 / 600.0)

    def test_interest_coverage(self) -> None:
        r = _normal_company()
        # (250+10)/40 = 6.5
        assert r.interest_coverage == pytest.approx(6.5)

    def test_net_debt(self) -> None:
        r = _normal_company()
        # 200 - 80 = 120
        assert r.net_debt_cr == pytest.approx(120.0)

    def test_asset_turnover(self) -> None:
        r = _normal_company()
        # 1000 / 1500 = 0.6667
        assert r.asset_turnover == pytest.approx(2.0 / 3.0)

    def test_no_flags(self) -> None:
        r = _normal_company()
        assert r.high_leverage_flag is False
        assert r.icr_warning_flag is False
        assert r.is_financial_sector is False
        assert r.warnings == ()


# ---------------------------------------------------------------------------
# 2. D/E returns 0 (not None) for debt-free companies
# ---------------------------------------------------------------------------
class TestDebtFreeDE:
    def test_debt_to_equity_zero_borrowings(self) -> None:
        """Per Day 09 brief: return 0, not None, if borrowings=0."""
        assert debt_to_equity(borrowings=0.0, equity_capital=100.0, reserves=500.0) == 0.0

    def test_debt_free_bundle_de_zero(self) -> None:
        r = _normal_company(borrowings=0.0)
        assert r.debt_to_equity == 0.0
        assert r.high_leverage_flag is False

    def test_debt_free_zero_borrowings_despite_negative_equity(self) -> None:
        """Zero borrowings should still return 0 even with negative equity."""
        assert debt_to_equity(borrowings=0.0, equity_capital=10.0, reserves=-200.0) == 0.0


# ---------------------------------------------------------------------------
# 3. ICR returns None when interest=0
# ---------------------------------------------------------------------------
class TestICRZeroInterest:
    def test_icr_none_when_interest_zero(self) -> None:
        """Per spec §13: None if interest=0."""
        assert interest_coverage_ratio(250.0, 10.0, 0.0) is None

    def test_bundle_icr_none_debt_free(self) -> None:
        r = _normal_company(interest=0.0, borrowings=0.0)
        assert r.interest_coverage is None


# ---------------------------------------------------------------------------
# 4. icr_label == "Debt Free" when interest=0
# ---------------------------------------------------------------------------
class TestICRLabelDebtFree:
    def test_icr_display_label_debt_free(self) -> None:
        assert icr_display_label(None) == ICR_DEBT_FREE_LABEL
        assert icr_display_label(None) == "Debt Free"

    def test_icr_display_label_numeric_is_none(self) -> None:
        """Numeric ICR → no preset label; caller formats."""
        assert icr_display_label(5.0) is None
        assert icr_display_label(0.5) is None

    def test_bundle_icr_label(self) -> None:
        r = _normal_company(interest=0.0, borrowings=0.0)
        assert r.icr_label == "Debt Free"

    def test_bundle_icr_label_not_set_when_interest_present(self) -> None:
        r = _normal_company(interest=40.0)
        assert r.icr_label is None


# ---------------------------------------------------------------------------
# 5. High D/E flag triggers for non-financial companies when D/E > 5
# ---------------------------------------------------------------------------
class TestHighDEFlag:
    def test_flag_triggered_above_threshold(self) -> None:
        # equity=100+0=100, borrowings=600 → D/E=6 > 5
        r = _normal_company(
            borrowings=600.0,
            investments=0.0,
            reserves=0.0,
            broad_sector="Industrials",
        )
        assert r.debt_to_equity == pytest.approx(6.0)
        assert r.high_leverage_flag is True
        assert any("HIGH LEVERAGE" in w for w in r.warnings)

    def test_flag_not_triggered_at_threshold(self) -> None:
        """Exactly 5 should NOT flag (strict >)."""
        # equity=600, borrowings=3000 → D/E=5 exactly
        r = _normal_company(
            borrowings=3000.0,
            reserves=0.0,
            equity_capital=600.0,
            broad_sector="IT",
        )
        assert r.debt_to_equity == pytest.approx(5.0)
        assert r.high_leverage_flag is False

    def test_flag_helper_directly(self) -> None:
        assert high_leverage_flag(6.0, is_financial=False) is True
        assert high_leverage_flag(5.0, is_financial=False) is False
        assert high_leverage_flag(None, is_financial=False) is False

    def test_flag_threshold_constant(self) -> None:
        """Sanity check: threshold constant matches spec."""
        assert HIGH_LEVERAGE_DE_THRESHOLD == 5.0


# ---------------------------------------------------------------------------
# 6. High D/E flag does NOT trigger for banks/NBFCs (carve-out)
# ---------------------------------------------------------------------------
class TestFinancialCarveOut:
    @pytest.mark.parametrize(
        "sector",
        ["Financials (Banks)", "Financials (NBFC)", "Banks", "Consumer Finance"],
    )
    def test_bank_high_de_not_flagged(self, sector: str) -> None:
        # Very high borrowings (deposits make D/E look huge)
        r = _normal_company(borrowings=5000.0, investments=1000.0, broad_sector=sector)
        assert r.debt_to_equity is not None
        assert r.debt_to_equity > HIGH_LEVERAGE_DE_THRESHOLD
        assert r.high_leverage_flag is False
        assert r.is_financial_sector is True

    def test_non_financial_high_de_flagged(self) -> None:
        r = _normal_company(borrowings=4000.0, investments=0.0, broad_sector="Steel & Metals")
        assert r.high_leverage_flag is True
        assert r.is_financial_sector is False


# ---------------------------------------------------------------------------
# 7. ICR warning flag when ICR < 1.5
# ---------------------------------------------------------------------------
class TestICRWarning:
    def test_icr_below_1_5_warns(self) -> None:
        # (EBITDA+OI)/interest = 50/40 = 1.25 (below threshold)
        r = _normal_company(operating_profit=40.0, other_income=10.0, interest=40.0)
        assert r.interest_coverage == pytest.approx(1.25)
        assert r.icr_warning_flag is True
        assert any("ICR warning" in w for w in r.warnings)

    def test_icr_at_threshold_no_warn(self) -> None:
        # (EBITDA+OI) = 1.5 * interest → exactly at threshold
        r = _normal_company(operating_profit=50.0, other_income=10.0, interest=40.0)
        # (50+10)/40 = 1.5 exactly
        assert r.interest_coverage == pytest.approx(1.5)
        assert r.icr_warning_flag is False

    def test_debt_free_no_icr_warning(self) -> None:
        """Debt-free companies (ICR None) must NOT trigger the warning."""
        r = _normal_company(interest=0.0, borrowings=0.0)
        assert r.interest_coverage is None
        assert r.icr_warning_flag is False

    def test_negative_icr_warns(self) -> None:
        """Operating losses + interest payments → strongly negative ICR → flag."""
        r = _normal_company(operating_profit=-50.0, other_income=5.0, interest=40.0)
        assert r.icr_warning_flag is True

    def test_icr_warning_helper(self) -> None:
        assert icr_warning_flag(1.0) is True
        assert icr_warning_flag(0.0) is True
        assert icr_warning_flag(-2.0) is True
        assert icr_warning_flag(1.5) is False
        assert icr_warning_flag(5.0) is False
        assert icr_warning_flag(None) is False

    def test_icr_threshold_constant(self) -> None:
        assert ICR_WARNING_THRESHOLD == 1.5


# ---------------------------------------------------------------------------
# 8. Net debt = borrowings - investments; negative = net cash
# ---------------------------------------------------------------------------
class TestNetDebt:
    def test_net_debt_positive(self) -> None:
        assert net_debt(borrowings=200.0, investments=80.0) == pytest.approx(120.0)

    def test_net_debt_negative_is_net_cash(self) -> None:
        """Investments exceed debt → net cash (negative net debt)."""
        nd = net_debt(borrowings=100.0, investments=300.0)
        assert nd == pytest.approx(-200.0)
        assert nd < 0  # net cash position

    def test_net_debt_zero_investments(self) -> None:
        assert net_debt(borrowings=500.0, investments=None) == pytest.approx(500.0)

    def test_net_debt_bundle(self) -> None:
        r = _normal_company(borrowings=100.0, investments=400.0)
        assert r.net_debt_cr == pytest.approx(-300.0)


# ---------------------------------------------------------------------------
# 9. Asset turnover returns None when total_assets = 0
# ---------------------------------------------------------------------------
class TestAssetTurnover:
    def test_zero_assets_returns_none(self) -> None:
        assert asset_turnover(sales=1000.0, total_assets=0.0) is None

    def test_normal_turnover(self) -> None:
        assert asset_turnover(sales=1000.0, total_assets=500.0) == pytest.approx(2.0)

    def test_bundle_zero_assets(self) -> None:
        r = _normal_company(total_assets=0.0)
        assert r.asset_turnover is None


# ---------------------------------------------------------------------------
# 10. Negative equity with debt → D/E None (meaningless ratio)
# ---------------------------------------------------------------------------
class TestNegativeEquityDE:
    def test_de_negative_equity_is_none(self) -> None:
        # equity=10+(-200) = -190, borrowings=50
        assert debt_to_equity(50.0, 10.0, -200.0) is None

    def test_bundle_negative_equity_warning(self) -> None:
        r = _normal_company(equity_capital=10.0, reserves=-200.0, borrowings=50.0)
        assert r.debt_to_equity is None
        assert any("D/E incalculable" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# 11. Result immutability & tuple warnings
# ---------------------------------------------------------------------------
class TestResultContract:
    def test_result_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        r = _normal_company()
        with pytest.raises(FrozenInstanceError):
            r.debt_to_equity = 999.0  # type: ignore[misc]

    def test_warnings_is_tuple(self) -> None:
        r = _normal_company()
        assert isinstance(r.warnings, tuple)
