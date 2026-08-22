# Sprint 1 Retrospective — Data Foundation (Days 1–7)

**Project:** Nifty 100 Financial Intelligence Platform
**Sprint:** 1 of 6 (Data Foundation, Module 1 — ETL)
**Dates:** 2026-08-22 (Days 1–7, single-session accelerated execution)
**Status:** ✅ COMPLETE — all exit criteria met

---

## 1. What We Shipped

| Day | Deliverable | Status |
|-----|-------------|--------|
| D01 | Project scaffolding, venv, Makefile, Black/Ruff/Pytest, logger, config | ✅ |
| D02 | Excel loader with `header=1` core / `header=0` supp; `normalize_year()` (10 formats); `normalize_ticker()`; 87 unit tests | ✅ |
| D03 | Schema validator with all 16 DQ rules (DQ-01…DQ-16); `validation_failures.csv`; 58 rule tests | ✅ |
| D04 | SQLite schema (12 business tables + 2 audit tables, FKs ON DELETE CASCADE, 10 indexes, CHECK constraint); bulk loader + dedup engine; 25 DB tests | ✅ |
| D05 | Full 12-file load, TEMP TABLE merge upsert (idempotent), `load_audit.csv`, synthetic data generator (SEED=42, deterministic); 19 integration tests | ✅ |
| D06 | Data Quality Manual Review — 5 random companies (KOTAKBANK, ADANIGREEN, HEROMOTOCO, IOC, COLPAL); fixed DQ-06 bank carve-out; added CRITICAL-row rejection before insert; new `parse_failures.csv`; 8 new tests | ✅ |
| D07 | 17 exploratory SQL queries (row counts, FKs, coverage, nulls, leaders, sector mix, peer benchmarks, stock performance, audit); demo DB; this retrospective | ✅ |

### Final Test & Coverage Numbers
- **Tests:** 254 passing (up from 53 on D01, +201 across the sprint)
- **Coverage:** 89% line coverage on src/etl/ and src/utils/
- **Formatting/Lint:** Black (line-length 100) clean, Ruff zero warnings
- **DB Row Counts:** 12,845 business rows across 12 tables; 0 FK orphans; 0 CRITICAL DQ failures; 0 WARNING DQ failures; 1 INFO (DQ-15 strict-balance counter)

### Tables Populated
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
| financial_ratios | 1,184 |
| stock_prices | 5,520 |
| **Total** | **12,845** |

---

## 2. Exit-Criteria Check (Sprint 1 Gate)

From spec §12 / §29 Week 1 Go/No-Go:

| Criterion | Result |
|-----------|--------|
| `nifty100.db` built; **all 12 tables** loaded | ✅ (schema lists 12 business + 2 audit tables; spec says "all 10 tables" but §9 lists 12 — we loaded all 12) |
| `load_audit.csv` shows **zero CRITICAL** DQ failures | ✅ (0 CRITICAL / 0 WARNING / 1 INFO) |
| Coverage: companies with ≥5yr P&L/BS/CF | ✅ all 92 (min=10yr for P&L, min=10yr for CF — exceeds ≥5 gate) |
| FK integrity (`PRAGMA foreign_key_check`) | ✅ 0 orphan rows across 11 child tables |
| 60+ tests collected and passing | ✅ 254 tests, 0 failures |
| Year format normalised (`YYYY-MM`) | ✅ 0 PARSE_ERROR rows in DB |
| Tickers uppercase, stripped, length 2-12 | ✅ all 92 pass `^[A-Z0-9&.-]{2,12}$` |
| `validation_failures.csv` present | ✅ (1 INFO row — DQ-15 counter) |
| `parse_failures.csv` present | ✅ (empty with headers — clean load) |
| 10+ exploratory SQL queries | ✅ 17 queries in `db/exploratory_queries.sql` |

---

## 3. Bugs Found & Fixed This Sprint

| # | Day | Bug | Fix |
|---|-----|-----|-----|
| 1 | D04 | SQLite `SQLITE_MAX_EXPR_DEPTH` (1000) exceeded by OR-tuple deletes on large tables (documents=1585, stock_prices=5520) | Replaced with TEMP TABLE + correlated `EXISTS` DELETE, batched in chunks of 900 PKs |
| 2 | D04 | Pandas `to_sql` with explicit columns bypasses SQLite `DEFAULT` expressions — `loaded_at`, `status` were NULL | Stamped both client-side in `write_load_audit()` using UTC ISO with `Z` suffix |
| 3 | D04 | `_clean_for_sqlite()` used default `settings.DB_PATH` and couldn't see temp-test DB | Added `db_path` parameter, threaded through all callers |
| 4 | D05 | Settings dataclass is `frozen=True` — tests couldn't monkeypath DB path | Introduced `NIFTY100_DB_PATH` env var (with `:memory:` sentinel support) |
| 5 | D05 | `documents.Year` (capital-Y) not matched by case-insensitive PK resolution for merge | Added `_pk_for_table()` helper with case-insensitive column lookup |
| 6 | D05 | DQ-15 emitted 1,200+ INFO messages (one per balanced row) flooding audit | Refactored to one aggregate INFO counter |
| 7 | D06 | **DQ-06 flagged banks** for sales=0 even though banks report interest income not sales; comment said "to be tightened later" | Added sector-carve-out using `sectors.broad_sector` keywords (bank/nbfc/finance/financial) |
| 8 | D06 | PARSE_ERROR sentinel rows were only flagged by DQ-07 validator but could still reach SQLite if validation ran *after* load | Added `_reject_critical_rows()` pipeline step that runs BEFORE DB insert and logs rejects to `parse_failures.csv` |
| 9 | D06 | `load_audit.rows_rejected` was always 0 (default) even when rows dropped | Set to `rows_dropped + critical_rejected` before writing audit |
| 10 | D07 | `.git/config` lost across sandbox snapshots (not persisted) | Documented recovery command; re-added remote in workspace when needed |

---

## 4. Data-Quality Findings from the Manual Review (D06)

Using `scripts/dq_review.py` (seed=12345, reproducible):

- **5 random companies audited** across all 7 time-series tables (P&L, BS, CF, financial_ratios, documents, market_cap, stock_prices) — all years properly formatted, FKs intact, values sensible.
- **All 92 companies have ≥10yr P&L history** (well above the DQ-16 ≥5yr threshold). Distribution: 12yr=15 cos, 13yr=14 cos, 14yr=45 cos, 15yr=18 cos.
- **0 PARSE_ERROR rows** in any FY-normalised table.
- **0 FK orphans** across 11 child tables (verified both pre- and post-load).
- **0 BS imbalances** (|assets-liab|/assets < 1%) — synthetic generator plugs `other_asset`/`other_liabilities` to balance exactly.
- **0 OPM cross-check failures** — opm_percentage matches (op_profit/sales×100) exactly.
- **0 net-cash reconciliation outliers** — CFO+CFI+CFF rounds to net_cash_flow within ₹10 Cr.
- **22 companies have fewer than 6 annual reports in the 2019-2024 window** (Query 16); this is an artifact of our synthetic generator (random 15-19yr span across 2008-2025) and NOT a loader bug. When real Screener.in data is loaded, this query will identify genuinely missing filings.
- **Peer group benchmarks all present** — 11/11 expected benchmarks (HDFCBANK, TCS, SUNPHARMA, MARUTI, LICI, RELIANCE, NTPC, TATASTEEL, HINDUNILVR, BAJFINANCE, SBIN) with `is_benchmark=1`.

---

## 5. What Went Well

- **Deterministic synthetic data** (SEED=42) made every bug reproducible and every test stable.
- **Temp-table merge upsert** proved itself — `make load` is fully idempotent and completes in ~2s.
- **Type hints + frozen dataclass Settings** caught a class of config bugs early.
- **The 16-rule validator** fired exactly zero false positives on clean synthetic data.
- **Pytest fixtures with in-memory / temp DB** via `NIFTY100_DB_PATH` kept the 254-test suite under 2 minutes.
- **Day-by-day commit history** on `main` (one commit per day with `[Sprint1-DayN]` prefix) provides clean bisect points.

---

## 6. What to Watch / Improvements for Sprint 2+

1. **Real Excel data not yet available.** Pipeline tested on deterministic synthetic data; live Screener.in exports will surface real edge cases (non-March FY closes, NESTLEIND Dec, banks June, mixed year formats in the same column). Re-run `make load` + `make dq-review` as soon as real files land in `data/raw/`.
2. **DQ-13 URL validity** is currently syntactic only (`^https?://`). The spec asks for `requests.head().status_code == 200`; this requires network and is flagged for a later maintenance pass (we intentionally do NOT run live HTTP checks during load to keep `make load` hermetic).
3. **`financial_ratios` table is a stub** (loaded from the supplementary synthetic xlsx with placeholder values). Sprint 2 will **recompute** all 14 KPI columns from P&L+BS+CF primary data, at which point we should drop the pre-computed ratios from the source files.
4. **`analysis.xlsx` text-parsing** (e.g. `"10 Years: 21%"`) is loaded as raw text; parsing into numeric CAGR/ROE columns is scheduled for Sprint 5 (NLP module, D29-30).
5. **Stock prices use 1st-of-month dates** (e.g. 2020-01-01). Real NSE monthly data may use last-trading-day dates; the schema accepts any `YYYY-MM-DD` string, but queries that join ratios (year ending March) with prices (calendar months) will need an alignment helper.
6. **No CI pipeline yet.** All tests are local. Before Sprint 6 we should wire GitHub Actions so pushes run `make test` automatically.
7. **Loguru config could be refined** to separate INFO/WARNING into per-level files once the project grows.

---

## 7. Artifacts Inventory (Sprint 1 deliverables)

| File | Purpose |
|------|---------|
| `db/schema.sql` | SQLite DDL (12 business + 2 audit tables, FKs, CHECK, 10 indexes) |
| `db/nifty100.db` | Populated database (~13k rows) |
| `db/exploratory_queries.sql` | 17 ready-to-run analytical queries |
| `data/processed/load_audit.csv` | Per-table audit trail for the latest run |
| `data/processed/validation_failures.csv` | DQ violation log |
| `data/processed/parse_failures.csv` | Pre-insert rejects (unparseable years/tickers) |
| `src/etl/loader.py` | Excel reader with header/sheet registry |
| `src/etl/normalizers.py` | `normalize_ticker`, `normalize_year` (10 edge cases) |
| `src/etl/validation.py` | 16 DQ rules + `validate_all()` runner |
| `src/etl/database.py` | Connection, init_schema, load_dataframe (merge upsert), audit helpers |
| `src/etl/exceptions.py` | Exception hierarchy |
| `scripts/run_etl.py` | `make load` entry point |
| `scripts/generate_data.py` | Deterministic synthetic data generator (SEED=42) |
| `scripts/dq_review.py` | `make dq-review` — 5-company audit report |
| `tests/` | 254 tests across 7 files |
| `output/day6_dq_review.txt` | Saved DQ manual-review report |
| `output/sprint1_retro.md` | This document |

---

## 8. Sprint 2 Preview (Days 8–14: Ratio Engine)

Immediate next steps, per spec §13 / §25:
- **D08** Profitability ratios: NPM, OPM, ROE, ROCE (negative-equity, zero-sales edge cases)
- **D09** Leverage + efficiency: D/E (bank carve-out), ICR (debt-free → NULL), Asset Turnover
- **D10** CAGR engine: Revenue/PAT/EPS CAGR for 3/5/10yr windows with turnaround flag
- **D11** Cash-flow KPIs: FCF, CFO Quality Score, CapEx Intensity, FCF Conversion, 8 capital-allocation patterns
- **D12** Populate `financial_ratios` for 92 × all years (target 1,184+ rows)
- **D13** Bank/NBFC ROCE with sector-relative benchmarks
- **D14** All 20 KPI tests green, `ratio_edge_cases.log`

Target gate: ≥1,100 rows in `financial_ratios`, formula spot-checks match hand-computed Excel values.

---

*Retrospective written 2026-08-22 by the ETL/Data-Engineering pod. Ready for Sprint 2 kickoff.*
