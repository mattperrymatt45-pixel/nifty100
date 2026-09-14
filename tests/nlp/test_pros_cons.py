"""Sprint 5 Day 30 — Tests for the auto pros/cons generator."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.nlp import pros_cons_generator as pcg
from src.nlp.pros_cons_generator import (
    CONFIDENCE_THRESHOLD,
    CompanyContext,
    generate_pros_cons,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


# ---------------------------------------------------------------------------
# Helpers to build synthetic contexts
# ---------------------------------------------------------------------------
def _ctx(**overrides) -> CompanyContext:
    defaults = dict(
        company_id="TEST",
        company_name="Test Co",
        sector="Industrials",
        is_financial=False,
        ratios=pd.DataFrame(),
        pl=pd.DataFrame(),
        bs=pd.DataFrame(),
        mc=pd.DataFrame(),
    )
    defaults.update(overrides)
    return CompanyContext(**defaults)


# ---------------------------------------------------------------------------
# Pro-rule unit tests
# ---------------------------------------------------------------------------
class TestProRules:
    def test_p1_fires_on_3yr_high_roe(self) -> None:
        ratios = pd.DataFrame(
            {
                "year": ["2022-03", "2023-03", "2024-03"],
                "return_on_equity_pct": [22.0, 23.0, 24.0],
            }
        )
        ctx = _ctx(ratios=ratios.iloc[::-1])  # DESC
        r = pcg.pro_p1(ctx)
        assert r.triggered
        assert r.type == "pro"
        assert r.rule_id == "P1"
        assert r.confidence_pct >= CONFIDENCE_THRESHOLD

    def test_p2_fires_on_5yr_positive_fcf(self) -> None:
        ratios = pd.DataFrame(
            {
                "year": [f"{y}-03" for y in range(2020, 2025)],
                "free_cash_flow_cr": [100, 200, 300, 400, 500],
            }
        )
        ctx = _ctx(ratios=ratios.iloc[::-1])
        r = pcg.pro_p2(ctx)
        assert r.triggered and r.rule_id == "P2"

    def test_p3_debt_free(self) -> None:
        ratios = pd.DataFrame(
            {"year": ["2024-03"], "debt_to_equity": [0.0], "icr_label": ["Debt Free"]}
        )
        ctx = _ctx(ratios=ratios)
        r = pcg.pro_p3(ctx)
        assert r.triggered and r.rule_id == "P3"

    def test_p4_high_rev_cagr(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "revenue_cagr_5yr": [18.0]})
        ctx = _ctx(ratios=ratios)
        r = pcg.pro_p4(ctx)
        assert r.triggered and r.rule_id == "P4"
        assert "15%" in r.text

    def test_p5_high_opm(self) -> None:
        pl = pd.DataFrame({"year": ["2024-03"], "opm_percentage": [28.0]})
        ctx = _ctx(pl=pl)
        r = pcg.pro_p5(ctx)
        assert r.triggered and r.rule_id == "P5"

    def test_p6_high_pat_cagr(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "pat_cagr_5yr": [25.0]})
        ctx = _ctx(ratios=ratios)
        r = pcg.pro_p6(ctx)
        assert r.triggered and r.rule_id == "P6"

    def test_p7_icr_high(self) -> None:
        ratios = pd.DataFrame(
            {
                "year": ["2024-03"],
                "debt_to_equity": [0.5],
                "interest_coverage": [15.0],
                "icr_label": [None],
            }
        )
        ctx = _ctx(ratios=ratios)
        r = pcg.pro_p7(ctx)
        assert r.triggered and r.rule_id == "P7"

    def test_p8_dividend_fcf(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "free_cash_flow_cr": [100.0]})
        mc = pd.DataFrame({"year": [2024], "dividend_yield_pct": [3.0]})
        ctx = _ctx(ratios=ratios, mc=mc)
        r = pcg.pro_p8(ctx)
        assert r.triggered and r.rule_id == "P8"

    def test_p9_high_eps_cagr(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "eps_cagr_5yr": [17.0]})
        ctx = _ctx(ratios=ratios)
        r = pcg.pro_p9(ctx)
        assert r.triggered and r.rule_id == "P9"

    def test_p10_roe_improving_3yr(self) -> None:
        ratios = pd.DataFrame(
            {
                "year": ["2022-03", "2023-03", "2024-03", "2025-03"],
                "return_on_equity_pct": [12.0, 14.0, 16.0, 18.0],
            }
        )
        ctx = _ctx(ratios=ratios.iloc[::-1])
        r = pcg.pro_p10(ctx)
        assert r.triggered and r.rule_id == "P10"

    def test_p11_pat_cagr_exceeds_rev_cagr(self) -> None:
        ratios = pd.DataFrame(
            {"year": ["2024-03"], "revenue_cagr_5yr": [12.0], "pat_cagr_5yr": [20.0]}
        )
        ctx = _ctx(ratios=ratios)
        r = pcg.pro_p11(ctx)
        assert r.triggered and r.rule_id == "P11"
        assert "operating leverage" in r.text

    def test_p12_assets_up_debt_down(self) -> None:
        bs = pd.DataFrame(
            {
                "year": ["2022-03", "2023-03", "2024-03"],
                "total_assets": [1000.0, 1100.0, 1300.0],
                "borrowings": [300.0, 280.0, 200.0],
                "equity_capital": [100.0, 100.0, 100.0],
                "reserves": [600.0, 720.0, 1000.0],
            }
        )
        ctx = _ctx(bs=bs.iloc[::-1])
        r = pcg.pro_p12(ctx)
        assert r.triggered and r.rule_id == "P12"


# ---------------------------------------------------------------------------
# Con-rule unit tests
# ---------------------------------------------------------------------------
class TestConRules:
    def test_c1_high_de_nonfinancial(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "debt_to_equity": [2.5]})
        ctx = _ctx(ratios=ratios, is_financial=False)
        r = pcg.con_c1(ctx)
        assert r.triggered and r.rule_id == "C1"
        assert "2.50" in r.text

    def test_c1_skipped_for_financials(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "debt_to_equity": [5.0]})
        ctx = _ctx(ratios=ratios, sector="Financials", is_financial=True)
        r = pcg.con_c1(ctx)
        assert not r.triggered

    def test_c2_fcf_negative_3yr(self) -> None:
        ratios = pd.DataFrame(
            {
                "year": [f"{y}-03" for y in range(2022, 2025)],
                "free_cash_flow_cr": [-100.0, -200.0, -300.0],
            }
        )
        ctx = _ctx(ratios=ratios.iloc[::-1])
        r = pcg.con_c2(ctx)
        assert r.triggered and r.rule_id == "C2"

    def test_c3_opm_declining_3yr(self) -> None:
        pl = pd.DataFrame(
            {
                "year": ["2022-03", "2023-03", "2024-03", "2025-03"],
                "opm_percentage": [25.0, 22.0, 18.0, 15.0],
            }
        )
        ctx = _ctx(pl=pl.iloc[::-1])
        r = pcg.con_c3(ctx)
        assert r.triggered and r.rule_id == "C3"

    def test_c4_net_loss_latest_year(self) -> None:
        pl = pd.DataFrame({"year": ["2024-03"], "net_profit": [-50.0]})
        ctx = _ctx(pl=pl)
        r = pcg.con_c4(ctx)
        assert r.triggered and r.rule_id == "C4"
        assert r.confidence_pct >= 90

    def test_c5_revenue_declining_2yr(self) -> None:
        pl = pd.DataFrame(
            {
                "year": ["2022-03", "2023-03", "2024-03"],
                "sales": [1000.0, 900.0, 800.0],
            }
        )
        ctx = _ctx(pl=pl.iloc[::-1])
        r = pcg.con_c5(ctx)
        assert r.triggered and r.rule_id == "C5"

    def test_c6_low_icr(self) -> None:
        ratios = pd.DataFrame(
            {"year": ["2024-03"], "interest_coverage": [1.2], "debt_to_equity": [0.8]}
        )
        ctx = _ctx(ratios=ratios)
        r = pcg.con_c6(ctx)
        assert r.triggered and r.rule_id == "C6"

    def test_c6_skipped_debt_free(self) -> None:
        ratios = pd.DataFrame(
            {"year": ["2024-03"], "interest_coverage": [0.5], "debt_to_equity": [0.0]}
        )
        ctx = _ctx(ratios=ratios)
        r = pcg.con_c6(ctx)
        assert not r.triggered

    def test_c7_payout_above_100(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "dividend_payout_ratio_pct": [120.0]})
        ctx = _ctx(ratios=ratios)
        r = pcg.con_c7(ctx)
        assert r.triggered and r.rule_id == "C7"

    def test_c8_de_rising_3yr(self) -> None:
        ratios = pd.DataFrame(
            {
                "year": ["2022-03", "2023-03", "2024-03", "2025-03"],
                "debt_to_equity": [0.3, 0.5, 0.8, 1.2],
            }
        )
        ctx = _ctx(ratios=ratios.iloc[::-1])
        r = pcg.con_c8(ctx)
        assert r.triggered and r.rule_id == "C8"

    def test_c9_eps_declining_3yr(self) -> None:
        pl = pd.DataFrame(
            {
                "year": ["2022-03", "2023-03", "2024-03", "2025-03"],
                "eps": [20.0, 18.0, 15.0, 10.0],
            }
        )
        ctx = _ctx(pl=pl.iloc[::-1])
        r = pcg.con_c9(ctx)
        assert r.triggered and r.rule_id == "C9"

    def test_c10_low_roce(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "roce_pct": [6.0]})
        ctx = _ctx(ratios=ratios)
        r = pcg.con_c10(ctx)
        assert r.triggered and r.rule_id == "C10"

    def test_c11_high_net_debt_to_ebitda(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "net_debt_cr": [5000.0]})
        pl = pd.DataFrame(
            {"year": ["2024-03"], "operating_profit": [1000.0], "depreciation": [200.0]}
        )
        ctx = _ctx(ratios=ratios, pl=pl)
        r = pcg.con_c11(ctx)
        assert r.triggered and r.rule_id == "C11"
        assert "4.2" in r.text  # 5000/1200 ≈ 4.2

    def test_c12_low_rev_cagr_nonfinancial(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "revenue_cagr_5yr": [3.0]})
        ctx = _ctx(ratios=ratios, is_financial=False)
        r = pcg.con_c12(ctx)
        assert r.triggered and r.rule_id == "C12"


# ---------------------------------------------------------------------------
# Confidence bounds
# ---------------------------------------------------------------------------
class TestConfidence:
    def test_confidence_always_in_0_100(self) -> None:
        ratios = pd.DataFrame({"year": ["2024-03"], "debt_to_equity": [0.0]})
        ctx = _ctx(ratios=ratios)
        for rule in pcg.PRO_RULES + pcg.CON_RULES:
            r = rule(ctx)
            assert 0 <= r.confidence_pct <= 100

    def test_not_triggered_has_zero_confidence(self) -> None:
        ctx = _ctx()
        for rule in pcg.PRO_RULES + pcg.CON_RULES:
            r = rule(ctx)
            if not r.triggered:
                assert r.confidence_pct == 0


# ---------------------------------------------------------------------------
# End-to-end against production DB
# ---------------------------------------------------------------------------
class TestEndToEnd:
    def test_all_92_companies_have_pro_and_con(self, tmp_path: Path) -> None:
        out = tmp_path / "pros_cons_generated.csv"
        res = generate_pros_cons(db_path=DB_PATH, output_path=out)
        assert res.total_companies == 92
        assert res.companies_with_pros == 92
        assert res.companies_with_cons == 92
        assert out.exists()
        csv = pd.read_csv(out)
        # CSV must have exactly the 5 specified columns
        assert list(csv.columns) == ["company_id", "type", "rule_id", "text", "confidence_pct"]
        # Every company appears at least once per type
        for t in ("pro", "con"):
            assert set(csv[csv["type"] == t]["company_id"].unique()) == set(self._all_company_ids())
        # All emitted rows pass the threshold
        assert (csv["confidence_pct"] >= CONFIDENCE_THRESHOLD).all()
        # Rule IDs present
        pros_in_csv = set(csv[csv["type"] == "pro"]["rule_id"])
        cons_in_csv = set(csv[csv["type"] == "con"]["rule_id"])
        # At least one hard (P1-P12) pro and one hard/wildcard con fires overall
        assert pros_in_csv  # non-empty
        assert cons_in_csv

    def test_output_csv_sorted_readable(self, tmp_path: Path) -> None:
        out = tmp_path / "pros_cons_generated.csv"
        generate_pros_cons(db_path=DB_PATH, output_path=out)
        csv = pd.read_csv(out)
        assert len(csv) >= 92 * 2  # at least 1 pro + 1 con per company
        assert (csv["text"].str.len() > 20).all()

    @staticmethod
    def _all_company_ids() -> set[str]:
        import sqlite3

        conn = sqlite3.connect(str(DB_PATH))
        try:
            return {r[0] for r in conn.execute("SELECT id FROM companies")}
        finally:
            conn.close()
