# Nifty 100 Platform — Standup Updates (5-Day Sample)

Daily standup format: **Yesterday → Today → Blockers**. Each day is picked from a
different sprint to show the range of work across the project.

---

## Day 5 — Sprint 1 (Data Ingestion)
**Theme: First successful end-to-end load into the warehouse**

- **Yesterday:**
  - Locked down the SQLAlchemy schema for 10 core tables (companies, profitandloss, balancesheet, cashflow, documents, prosandcons, sectors, stock_prices, market_cap, load_audit).
  - Fixed a `header=1` bug: Screener.in Excel files have a merged title row at row 0; passing `header=0` produced 400+ misnamed columns. Switching to `pd.read_excel(path, header=1)` resolved it.
  - Wrote the first 6 data-quality rules in `validation.py` (negative revenue, PAT type coercion, ticker whitespace).

- **Today:**
  - Completed the first full idempotent ETL run against all 7 Excel files.
  - Database now contains **92 companies** with P&L (1,282 rows), balance sheet (1,284), cash flow (1,182), documents (1,585).
  - Added a `load_audit` row per file (rowcount, status, timestamp) and a `validation_failures` table.
  - Delivered `output/load_audit.csv` and `output/validation_failures.csv` as required deliverables D-02/D-03.
  - Wrote `scripts/demo_db.py` to print table counts and spot-checked top companies.

- **Blockers:** None. Cash-flow file is missing FY 2019-20 for ~12 companies (incl. TCS); flagged to analytics layer rather than blocking load.

---

## Day 12 — Sprint 2 (KPI Engine)
**Theme: financial_ratios table goes live; CAGR bug caught and fixed**

- **Yesterday:**
  - Implemented ROCE, ROE, net/operating margin, and debt-to-equity in `src/analytics/ratios.py`.
  - Added "Debt Free" sentinel for companies with zero interest expense to avoid divide-by-zero.
  - Started on 1/3/5/10-year CAGR for revenue, PAT, and EPS.

- **Today:**
  - **Caught and fixed a material CAGR bug.** Initial LEFT JOIN of P&L + BS + CF pulled in years where cash flow was missing (12 cos), producing a TCS 5-yr revenue CAGR of ~7.8% instead of the manual 10.05%. Switching to INNER JOIN in the KPI gate resolved it (TCS now 10.047%). Logged as a lesson learned.
  - Implemented special-case rule: **negative base-year PAT returns `"TURNAROUND"`** instead of a mathematically nonsensical CAGR.
  - Populated the `financial_ratios` table end-to-end via `scripts/populate_ratios.py --reset --spot-check` → **1,184 rows** (one per company-year where P&L+BS+CF all present).
  - Excluded the Financials sector from D/E filters per spec (banks have structurally different leverage).
  - DuPont decomposition (margin × turnover × leverage) verified against TCS annual report values.

- **Blockers:** None. Bank/NBFC ROCE needs a special carve-out (their capital structure differs) — planning for Day 13.

---

## Day 25 — Sprint 4 (Dashboard & Valuation)
**Theme: Streamlit dashboard crosses 5 pages; valuation flags live**

- **Yesterday:**
  - Built Streamlit pages 01 (Home KPIs), 02 (Company Explorer), 03 (Screener), and the Plotly helper utilities in `src/dashboard/utils/db.py`.
  - Added a persistent "SIMULATED" banner for stock_prices / market_cap visuals.

- **Today:**
  - Shipped pages 04 (Sector Analysis) and 05 (Peer Comparison with radar charts), bringing the dashboard to **5 of 8 screens**.
  - Implemented valuation flags (`src/analytics/valuation.py`): PE vs peer median, Graham-number deviation, EV/EBITDA outliers; flagged BAJFINANCE as a high-PE outlier (confirmed by hand).
  - Wired the Screener page to all **6 presets** (quality_compounder, value_pick, growth_accelerator, dividend_champion, debt_free_blue_chip, turnaround_watch) — preset parameters exactly match spec §25.
  - Exported `output/valuation_summary.xlsx` with 92-company valuations and `output/valuation_flags.csv` (D-12 done).
  - Dashboard → database round-trips averaging ~200 ms per view; planning index work later in Sprint 6.

- **Blockers:** None. Minor: Streamlit multi-page numeric-prefix filenames (`01_home.py`) violate PEP8 module naming (`N999`); added a Ruff per-file-ignore instead of renaming.

---

## Day 33 — Sprint 5 (Reporting & NLP)
**Theme: Tearsheet PDF generation; word-wrap bug solved**

- **Yesterday:**
  - NLP pros/cons parser (`src/nlp/pros_cons_generator.py`) generated **299 pro / 222 con** rows across all 92 companies from the 1,585 management-analysis documents.
  - Built the first 5 tearsheet PDFs with ReportLab but found cells overflowing and the rupee glyph (ₐ) rendering as a box.

- **Today:**
  - **Fixed the PDF text-overflow bug.** Switched every table cell from raw strings to ReportLab `Paragraph` flowables, which honor word-wrap. All columns now wrap properly instead of clipping (this was the Day-33 explicit requirement).
  - Switched currency prefix from ₹ to **"Rs"** because the built-in Helvetica font lacks the rupee glyph; documented the trade-off in code comments.
  - Generated all **92 company tearsheets** at `reports/tearsheets/<TICKER>_tearsheet.pdf` — each is 2 pages, ≥30 KB, with KPI summary, 5-yr trend table, peer radar chart, pros/cons, and valuation flags.
  - Started on sector reports (3 of 11 done — IT, Pharma, Energy).

- **Blockers:** None. Arrows ▲▼▶ work correctly in Helvetica after confirming glyph coverage; no further font issues expected.

---

## Day 45 — Sprint 6 (Final Sign-Off)
**Theme: Acceptance gates pass, deliverables archived, project signed off**

- **Yesterday (Day 44):**
  - Generated `docs/analyst_guide.pdf` (10 pages) via `scripts/generate_analyst_guide.py`.
  - Verified all 267 public functions have docstrings; refreshed `README.md` with the API table and Sprint 6 commands.
  - Archived 23 deliverables to `output/final_deliverables/`. Black and Ruff both clean.

- **Today:**
  - Ran `scripts/day45_acceptance.py` — **20/20 acceptance gates PASS**:
    - DB contains 92 companies, financial_ratios = 1,184 rows
    - capital_allocation.csv = 1,182 rows (8 classes)
    - screener_output.xlsx has all 7 sheets (QC 32, VP 5, GA 14, DC 32, DFBC 8, TW 27)
    - 11 sector reports, 11 peer groups, 92 cluster labels
    - API health, companies, sectors, TCS detail, TCS ratios (14 rows), screener endpoint all return 200
    - Screener API vs Excel overlap = 53 matches
    - 92/92 tearsheet PDFs ≥30 KB, 0 small
    - **pytest: 695 passed, 0 failures**
    - validation_failures.csv has all 8 required columns
    - analyst_guide.pdf = 10 pages
  - Generated `docs/acceptance_checklist.pdf` (3 pages, signed Day 45 — 2026-09-18).
  - Wrote `output/acceptance_results.json`; archived **25 deliverables** to `output/final_deliverables/`.
  - Final commit: `[Sprint6-Day45] feat: final sign-off — 20/20 acceptance gates pass, checklist PDF, 25 archived deliverables` → `66b692a`, pushed to `main`.

- **Blockers:** **None. Project is signed off and ready for handover.** All 23 required deliverables (D-01 through D-23) marked Done.

---

## Quick Reference — Weekly Cadence

| Sprint | Days | Focus |
|--------|------|-------|
| 1 | Day 1–8 | Project scaffolding, ETL, data load, DQ basics |
| 2 | Day 9–15 | Financial ratios, CAGR, capital-allocation taxonomy |
| 3 | Day 16–22 | Screener engine, peer groups, radar charts |
| 4 | Day 23–29 | Streamlit dashboard (8 screens), valuation flags |
| 5 | Day 30–37 | Cashflow intelligence, NLP pros/cons, 104 PDF reports |
| 6 | Day 38–45 | FastAPI, tests (695), perf tuning, docs, acceptance |

