# Sprint 2 Retrospective — Ratio Engine (Days 8–14)

**Project:** Nifty 100 Financial Intelligence Platform
**Sprint:** 2 of 6 (Ratio Engine, Module 2 — KPI Computation)
**Dates:** 2026-08-23 → 2026-08-24 (single-session accelerated execution)
**Status:** ✅ COMPLETE — all exit criteria met

---

## 1. What We Shipped

| Day | Deliverable | Status |
|-----|-------------|--------|
| D08 | Profitability ratios module (`src/analytics/ratios.py`): NPM, OPM, EBIT Margin, ROE, ROCE, ROA; cross-check delta vs `opm_percentage`; financial-sector detection helper; 46 unit tests | ✅ |
| D09 | Leverage & efficiency module (`src/analytics/leverage.py`): D/E (0 for debt-free; negative-equity → None), ICR (None when interest=0; warning <1.5), Net Debt, Asset Turnover, `high_leverage_flag` (>5x for non-financials suppressed for banks/NBFCs); 40 unit tests | ✅ |
| D10 | CAGR engine (`src/analytics/cagr.py`): Revenue/PAT/EPS CAGR over 3/5/10yr windows with 6 edge-case flags (OK, TURNAROUND, DECLINE_TO_LOSS, BOTH_NEGATIVE, ZERO_BASE, INSUFFICIENT); `compute_all_cagrs()` batch API; 30 unit tests. Schema migration adds 18 CAGR columns to `financial_ratios` | ✅ |
| D11 | Cash-flow KPIs module (`src/analytics/cashflow_kpis.py`): FCF, CFO/PAT, 5-yr rolling CFO quality score/tier (High Quality / Moderate / Accrual Risk), CapEx Intensity + tier, FCF Conversion %, 8-class capital allocation classifier (Reinvestor, Shareholder Returns, Liquidating Assets, Distress Signal, Growth Funded by Debt, Cash Accumulator, Pre-Revenue, Mixed), FCF Concern flag (3yr consecutive negative FCF); `scripts/generate_capital_allocation_csv.py` → `output/capital_allocation.csv`; 46 unit tests | ✅ |
| D12 | `scripts/populate_ratios.py`: full PL+BS+CF+companies+sectors inner-join; computes all 50+ KPIs per company via `_compute_group()`; P10/P90 winsorised composite quality score (0.30 ROE + 0.25 FCF Conv + 0.25 ROCE + 0.20 D/E, debt-free=100, banks neutralised to 50); idempotent merge load; `--spot-check` recomputes ROE/5yr Rev-CAGR for 3 seeded companies and asserts deltas <0.1pp; 28 integration tests | ✅ |
| D13 | Bank/NBFC/Insurance ROCE carve-out (`src/analytics/sector_roce.py`): `is_bank_nfc_insurance()` includes insurance substring; `compute_bank_roce()` uses EBIT/Total-Assets ROA proxy; `categorize_anomaly()` into 4 buckets (bank_carveout, formula_discrepancy, version_difference, data_source); cross-check vs `companies.roce_percentage` / `roe_percentage`; writes `roce_sector_adjusted`, `roce_source_value`, `roe_source_value`, `roce_anomaly_category`, `roe_anomaly_category` back to DB; `output/ratio_edge_cases.log`; 30 unit tests | ✅ |
| D14 | All 479 tests green; renamed `test_spec_example` → `test_cagr_normal` per spec §27; fixed non-determinism in `generate_all()` (RNG seed now reset on every call, not just at import); 3-company spot-check deltas all 0.000000; this retrospective | ✅ |

### Final Test & Coverage Numbers (end of D14)
- **Tests:** **479 passing** across 14 test files (up from 258 at end of Sprint 1, +221 across Sprint 2)
  - 53 smoke/env tests (`tests/test_environment.py`)
  - 5 DQ rule tests (`tests/dq/test_rules.py`)
  - 200 ETL tests (database, day6, exploratory, full_load, loader, normalize, validation)
  - 221 KPI tests (ratios=46, leverage=40, cagr=30, cashflow=46, populate_ratios=29, sector_roce=30)
- **Formatting/Lint:** Black (line-length 100) clean, Ruff zero warnings
- **DB Row Counts:** 12,845 business rows across 12 tables (stable vs Sprint 1); **1,182 rows in `financial_ratios`** (exceeds spec's ≥1,100-row gate)
- **Composite quality score populated:** 1,182/1,182 rows (100%)
- **5-yr Revenue CAGR populated:** 722/1,182 rows (61% — remainder correctly flagged INSUFFICIENT due to <5yr history)

### Tables Populated (post D14 regeneration)
| Table | Rows |
|-------|------|
| companies | 92 |
| sectors | 92 |
| analysis | 20 |
| peer_groups | 56 |
| prosandcons | 16 |
| documents | 1,585 |
| market_cap | 552 |
| profitandloss | 1,262 |
| balancesheet | 1,284 |
| cashflow | 1,182 |
| **financial_ratios** | **1,182** |
| stock_prices | 5,520 |
| **Total** | **12,845** |

### `financial_ratios` Column Inventory (58 columns)
Primary key (2): `company_id`, `year`
Profitability (6): `net_profit_margin_pct`, `operating_profit_margin_pct`, `ebit_margin_pct`, `return_on_equity_pct`, `roce_pct`, `return_on_assets_pct`
Leverage/Efficiency (7): `debt_to_equity`, `high_leverage_flag`, `interest_coverage`, `icr_label`, `icr_warning_flag`, `net_debt_cr`, `asset_turnover`
Per-share / payout (3): `earnings_per_share`, `book_value_per_share`, `dividend_payout_ratio_pct`
Cashflow absolute (5): `total_debt_cr`, `cash_from_operations_cr`, `free_cash_flow_cr`, `capex_cr`, `fcf_cr`
CAGR metrics + flags (18): `{revenue,pat,eps}_cagr_{3,5,10}yr` and matching `_flag` columns
Cashflow quality / allocation (10): `cfo_pat_ratio`, `cfo_quality_score_5yr`, `cfo_quality_tier`, `capex_intensity_pct`, `capex_tier`, `fcf_conversion_pct`, `cfo_sign`, `cfi_sign`, `cff_sign`, `capital_allocation_pattern`, `fcf_concern_flag`
Composite score (1): `composite_quality_score`
Day-13 carve-out / cross-check (5): `roce_sector_adjusted`, `roce_source_value`, `roe_source_value`, `roce_anomaly_category`, `roe_anomaly_category`
Audit (1): `loaded_at`

---

## 2. Exit-Criteria Check (Sprint 2 Gate)

From spec §29 Week 2 Go/No-Go:

| Criterion | Result |
|-----------|--------|
| `financial_ratios` table populated with **1,100+ rows** | ✅ 1,182 rows (all 92 companies × all PL+BS+CF inner-join years) |
| **All KPI formula tests green** (spec §27 names `test_cagr_normal` with base=100, end=161, n=5 → ~10.0%) | ✅ 479/479 passing, including renamed `test_cagr_normal` |
| Formula spot-checks match hand-computed values (3 companies × ROE + 5yr CAGR) | ✅ NAUKRI / COALINDIA / SIEMENS all deltas = 0.000000 pp |
| Bank / NBFC D/E high-leverage flag **suppressed** (structural leverage) | ✅ 18 financial-sector companies correctly skip `high_leverage_flag` |
| Bank/NBFC/Insurance ROCE uses ROA-proxy (EBIT/Total Assets) | ✅ `is_bank_nfc_insurance()` matches 18 tickers across banks, NBFCs, insurance |
| Cross-check vs `companies.roce_percentage` / `roe_percentage` logged | ✅ `output/ratio_edge_cases.log` with 2,009 anomalies across 4 categories |
| Capital-allocation classification CSV produced | ✅ `output/capital_allocation.csv` (1,182 rows, 8 patterns) |
| Composite quality score 0–100 populated for all rows | ✅ Winsorised (P10/P90), 4-component weighted, 1,182/1,182 rows |
| `make load` + `make populate-ratios` + `make bank-roce` idempotent | ✅ Re-runs produce identical row counts and spot-check deltas |
| Spec §27 named tests (`test_dq04_bs_balance`, `test_dq06_zero_sales`, `test_cagr_normal`) all green | ✅ All 3 pass |

---

## 3. Bugs Found & Fixed This Sprint

| # | Day | Bug | Fix |
|---|-----|-----|-----|
| 1 | D09 | Negative equity (e.g. accumulated losses > paid-in capital) produced nonsensical negative D/E ratios that tripped the high-leverage flag | `debt_to_equity()` returns `None` when equity ≤ 0; callers treat None as "not meaningful" and skip flagging |
| 2 | D09 | Interest expense = 0 (debt-free companies) caused divide-by-zero in ICR | `interest_coverage_ratio()` returns `None` when interest ≤ 0; `icr_display_label()` returns "Debt Free"; warning flag suppressed |
| 3 | D10 | Companies with base-year loss and current-year profit were getting nonsense negative CAGRs | Introduced 6-state flag enum (TURNAROUND, DECLINE_TO_LOSS, BOTH_NEGATIVE, ZERO_BASE, INSUFFICIENT, OK) and return `None` value for any non-OK flag |
| 4 | D11 | FCF concern flag fired on a single negative year, giving false distress signals | Changed rule to **3 consecutive trailing years** of negative FCF before setting `fcf_concern_flag=1` |
| 5 | D12 | Composite score gave 0 to companies with missing ROCE (e.g. banks on the standard formula), dragging sector averages | Day 13 added ROA-proxy for banks so ROCE is always populated; winsorisation is per-sub-score so NaNs don't poison other components |
| 6 | D12 | Pandas FutureWarning on `pd.concat(pieces, …)` when some pieces have all-NA columns (from early-year CAGR Nones) | Documented as pandas 2.x forward-compat notice; not a bug (concat still produces correct columns), will silence in post-Sprint-6 cleanup when pandas 3.0 ships |
| 7 | D13 | Insurance companies were NOT excluded from D/E flagging or given the ROA-proxy ROCE — `is_financial_sector()` only matched bank/nbfc/finance keywords | Added `is_bank_nfc_insurance()` that also matches "insurance" substring; wired into both high-leverage flag suppression and ROCE dispatch |
| 8 | **D14** | `generate_all()` seeded `random` / `np.random` only at **module import time**, so any test that consumed RNG state before calling `generate_all()` got a different data distribution — this broke the 3-company spot-check when tests ran in a different order (COALINDIA delta went from 0.0 → 6.82) | Moved `random.seed(SEED)` / `np.random.seed(SEED)` inside `generate_all()` so every invocation is deterministic regardless of prior RNG consumption |
| 9 | **D14** | Day-13 `run_bank_carveout()` used `load_dataframe(upd_df, "financial_ratios", merge=True)` to write back 5 columns. The merge strategy is DELETE+INSERT on PK, so every column not present in `upd_df` (ROE, ROCE, all CAGRs, composite, etc.) was set to NULL — running `make bank-roce` silently clobbered 50+ KPI columns across 1,182 rows | Replaced with a targeted `executemany` UPDATE that only touches the 5 Day-13 carve-out columns; added a regression test (`test_existing_ratio_columns_preserved`) that seeds a row with non-trivial KPI values, runs `run_bank_carveout()`, and asserts no existing column is nullified |
| 9 | D14 | Spec §27 explicitly names the CAGR test `test_cagr_normal`, but we had it named `test_spec_example`; mismatch would cause spec audit-trail to fail | Renamed test to `test_cagr_normal` with docstring referencing spec §27 / page 41 |

---

## 4. Ratio Edge-Case Log Summary (D13)

`output/ratio_edge_cases.log` — 2047 lines, 2,009 anomalies cross-checked against `companies.xlsx` snapshot:

| Category | Count | Explanation |
|----------|-------|-------------|
| `bank_carveout` | 243 | Informational — every bank/NBFC/insurance ROCE uses the EBIT/TA ROA-proxy because deposits and borrowings aren't comparable to non-financial capital employed |
| `formula_discrepancy` | 378 | Δ ≤ 15pp — most likely denominator choice (average vs year-end capital employed), inclusion/exclusion of other income, or pre/post-tax treatment |
| `version_difference` | 1,092 | 15pp < Δ ≤ 40pp — consistent with TTM vs FY annualisation or a data-vintage refresh between sources |
| `data_source` | 296 | Δ > 40pp — likely a different share count / equity base in the reference snapshot, or a data entry error |

### Interpretation

With **synthetic** data, the `roce_percentage` / `roe_percentage` columns in `companies.xlsx` were generated as independent random values (5–60% for ROCE, 3–45% for ROE) and were **not** calibrated to reproduce the computed ratios from the generated balance sheets. This is why virtually every company-year shows a delta — it is **expected** given the data generator, and not a bug in the ratio engine. When real Screener.in data is loaded, the `formula_discrepancy` and `version_difference` buckets should shrink dramatically; `data_source` will then highlight genuine data-quality issues.

**Display policy (documented in log):** Use Ratio-Engine values for screener filtering, peer comparison, and composite scoring (reproducible, formulaically consistent); use `companies.xlsx` snapshot values only for display KPI tiles on the dashboard where users expect to see the published headline number.

---

## 5. What Went Well

- **Day-by-day modular decomposition** paid off: each KPI family (profitability, leverage, CAGR, cashflow, carve-outs) lives in its own module under `src/analytics/` with a frozen-dataclass return contract, making unit tests easy to write and edge cases obvious.
- **The CAGR 6-flag state machine** turned out to be cleaner than a wall of `if/else` — every edge case (negative base, zero base, turnaround, decline-to-loss) is an explicit flag rather than a sentinel float.
- **Winsorised composite score** (P10/P90 per sub-component, then 0–100 scale) is robust to outliers even on synthetic data — no score hits exactly 0 or 100 except the intentional debt-free=100 and bank-neutral=50 cases.
- **The `make bank-roce` target is fully idempotent** — re-running on an already-populated DB produces the same 2,009 anomalies and identical category counts.
- **Spot-check with 3 seeded companies (NAUKRI, COALINDIA, SIEMENS)** gave us a deterministic regression guard: after the D14 RNG-seed fix all three deltas are 0.000000 pp.
- **Schema migrations are additive** (new columns added via `ALTER TABLE ADD COLUMN` in `_migrate_schema()`) — no DROP TABLEs needed between days, so existing data survived every sprint-day change.
- **British-spelling shims** (`normaliser.py` re-exporting `normalizers`, `validator.py` re-exporting `validation`) prevented an import-error class of bug for developers using UK spelling.

---

## 6. What to Watch / Improvements for Sprint 3+

1. **Synthetic-data generator does not tie `companies.roce_percentage` to actual balance sheets.** As noted in §4, this inflates the anomaly log. When real data lands, re-run `make bank-roce` and expect a much smaller `data_source` bucket. We should **not** over-calibrate thresholds to the synthetic distribution.
2. **FutureWarning from `pd.concat`** (scripts/populate_ratios.py:364) will become an error in pandas 3.0. Fix is to drop all-NA columns from each piece before concat, or build the DataFrame from dicts. Deferred to post-Sprint-6 maintenance.
3. **`fcf_cr` and `free_cash_flow_cr` are duplicated** — both set to the same value. Kept for backward compatibility with early Sprint-2 queries that referenced the shorter name; plan a dedup in a future schema cleanup.
4. **`fcf_concern_flag` uses 3 consecutive negative FCF years.** This is a reasonable heuristic but may mis-classify very capital-intensive growth stories (e.g. Reliance Jio capex cycle). When sector benchmarks from Sprint 3 land, we should layer in sector-relative thresholds.
5. **Insurance ROA-proxy treats them like banks** (EBIT/TA). Insurers have a different capital structure (policyholder liabilities vs deposits); if a specialist insurance KPI set is needed later (combined ratio, solvency ratio), extend `sector_roce.py` with a separate insurer dispatcher.
6. **API tests (`test_health_200`, `test_companies_count`, `test_invalid_ticker`, `test_screener_filter`)** are listed in spec §27 for Sprints 3–4 (FastAPI layer) — not yet written because the API module is still a scaffold (`src/api/main.py` placeholder).
7. **The composite score weights (0.30/0.25/0.25/0.20)** are a sensible default but should be exposed in a config file so analysts can tune them without code changes.
8. **`generate_data.py` RNG-seed fix on D14** means any CI run, regardless of test order, will produce identical data. Add a CI pipeline (GitHub Actions) in a later sprint to enforce this.

---

## 7. Artifacts Inventory (Sprint 2 deliverables)

| File | Purpose |
|------|---------|
| `src/analytics/ratios.py` | Day 8 — NPM, OPM, EBIT Margin, ROE, ROCE, ROA + cross-check |
| `src/analytics/leverage.py` | Day 9 — D/E, ICR, Net Debt, Asset Turnover + flags/labels |
| `src/analytics/cagr.py` | Day 10 — 3/5/10yr CAGR engine with 6 edge-case flags |
| `src/analytics/cashflow_kpis.py` | Day 11 — FCF, CFO/PAT, quality score, CapEx intensity, capital-allocation classifier |
| `src/analytics/sector_roce.py` | Day 13 — Bank/NBFC/Insurance ROCE carve-out + anomaly categorisation |
| `scripts/populate_ratios.py` | Day 12 — `make populate-ratios`; joins PL/BS/CF/companies/sectors, computes all KPIs, loads to DB, runs 3-company spot-check |
| `scripts/day13_bank_roce.py` | Day 13 — `make bank-roce`; applies ROA-proxy for financials, cross-checks vs snapshot, writes log |
| `scripts/generate_capital_allocation_csv.py` | Day 11 — `make capital-alloc`; exports capital_allocation.csv |
| `output/capital_allocation.csv` | 1,182 rows × company/year/pattern/signs/CFO-PAT/FCF-concern |
| `output/ratio_edge_cases.log` | 2,009 anomalies in 4 categories with display-policy notes |
| `db/nifty100.db` | 12,845 rows across 12 tables; financial_ratios has 1,182 fully-computed KPI rows |
| `db/schema.sql` | DDL (after Day 13 migration: financial_ratios has 58 columns) |
| `tests/kpi/test_ratios.py` | 46 profitability tests |
| `tests/kpi/test_leverage.py` | 40 leverage/efficiency tests |
| `tests/kpi/test_cagr.py` | 30 CAGR tests (includes spec-named `test_cagr_normal`) |
| `tests/kpi/test_cashflow_kpis.py` | 46 cashflow / capital-allocation tests |
| `tests/kpi/test_populate_ratios.py` | 29 integration tests (row count, column coverage, composite bounds, BPS, spot-check, idempotent) |
| `tests/kpi/test_sector_roce.py` | 31 sector-carve-out / anomaly tests incl. `test_existing_ratio_columns_preserved` regression guard against partial-column UPDATE clobbering |
| `docs/sprint2_retro.md` | This document |

---

## 8. Sprint 3 Preview (Days 15–21: Screener & Peer Comparison)

Per spec §14 / §30:
- **D15** Sector benchmarks loaded from spec page 42 (ROE / D/E / OPM / P/E ranges per sector) — relativistic scoring
- **D16** Peer-group engine: for each company, identify 5–8 closest peers by sector + market-cap bucket
- **D17** Screener filter API: `GET /api/v1/screener?min_roe=15&max_de=1&sector=IT` → ranked list with composite score
- **D18** Valuation ratios (from market_cap + financials): P/E, P/B, EV/EBITDA, dividend yield
- **D19** Relative scoring: each KPI scored vs sector P25/P50/P75
- **D20** `GET /api/v1/companies/{ticker}/peers` peer-comparison JSON endpoint
- **D21** Sprint 3 review, API integration tests (`test_companies_count`, `test_invalid_ticker`, `test_screener_filter` all green per spec §27), `sprint3_retro.md`

Target gate: API returns 92 companies on `/companies`, 404 on invalid ticker, screener filter enforces ROE/D/E/OPM thresholds, peer groups drawn from the same broad_sector.

---

*Retrospective written 2026-08-24 by the Ratio-Engine pod. All 479 tests green; 1,182 KPI rows loaded; 2,009 edge cases logged. Ready for Sprint 3 kickoff.*
