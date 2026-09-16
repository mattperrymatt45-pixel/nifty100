# Sprint 5 Retrospective — Cash Flow Intelligence + Reports + NLP

**Sprint goal:** NLP auto-generate pros/cons for all 92 companies with
confidence scores; CFO quality / CapEx / capital-allocation patterns
classified; all 92 company tearsheet PDFs and 11 sector PDFs generated.

**Duration:** Days 29–35 (7 days, 70 SP)
**Final test count:** 849 non-dashboard tests passing (891 including dashboard collection)

## What went well

* **Vertical slice delivery.** Each day built on the previous day's outputs.
  Day-29 NLP parsed analysis text → Day-30 pros/cons generator fed into the
  tearsheet bullets on Day 33 → portfolio summary (Day 35) referenced the same
  KPI primitives established on Days 10–11. No throwaway scaffolding.
* **Deterministic PDF generation.** Using ReportLab Platypus with Paragraph
  word-wrapping produced zero overflow / blank-page issues across all 92
  tearsheets, verified programmatically (max bottom-y < 810pt on every page).
  Batch run of 92 tearsheets completed in ~62 seconds.
* **Defensive fallbacks.** Pros/cons CSV read with fallback to `prosandcons`
  table; market_cap falls back to latest-available year for late filers;
  distress/deleveraging flags treat missing data as False rather than raising;
  CFO/PAT=0 and similar edge cases return None rather than dividing by zero.
* **Parametrized cross-sector testing.** The 5 required spot-check companies
  (TCS, HDFCBANK, RELIANCE, SUNPHARMA, TATASTEEL) were promoted into
  parametrized pytest cases that verify page count, chart count, section
  keywords, and no overflow on every CI run.

## What could be improved

* **Sandbox resets are costly.** Reinstalling heavy dependencies (pandas,
  matplotlib, scikit-learn, reportlab, streamlit) after each reset burned
  several minutes per session. A `requirements-lock.txt` or pre-built venv
  snapshot would save ~5-10 minutes per session next sprint.
* **Dashboard tests hang in sandbox.** The Streamlit app tests require a
  running event loop / browser context and consistently time out in the
  sandboxed environment. They were excluded from non-dashboard pytest runs
  but should be moved to Selenium/Playwright smoke tests that only run in
  CI with a headless browser.
* **Capital Allocation taxonomy.** Four of the 8 theoretical patterns
  (Distress Signal, Liquidating Assets, Cash Accumulator, Pre-Revenue) have
  zero companies in the current Nifty-100 dataset. The taxonomy remains
  useful for future universes (small-caps, loss-making new listings) but
  this should be called out explicitly in the dashboard UI to avoid user
  confusion.

## Key metrics (Sprint 5)

| Artifact | Count |
|---|---:|
| NLP analysis_parsed.csv rows | 80 |
| Pros generated / Cons generated | 299 / 222 (521 total, 5-col CSV) |
| Companies with ≥1 pro AND ≥1 con | 92 / 92 |
| High Quality CFO tier | 92 / 92 |
| Distress alerts (NAUKRI, INDIGO) | 2 |
| Deleveraging names | 23 |
| YoY capital-allocation pattern changes | 45 |
| Company tearsheet PDFs | 92 (avg ~110 KB, 2 pages each) |
| Sector PDFs | 11 (Financials … Real Estate) |
| Portfolio summary pages | 92 (one per company, alphabetical) |
| New tests added (Sprint 5) | 181 (Day 29:26, Day30:30, Day31:20, Day32:12, Day33:53, Day34:14, Day35:15, plus retro) |

## Demo checklist for team lead

- [x] Three tearsheet PDFs open and render correctly
      (showing RELIANCE, TCS, HDFCBANK from `reports/tearsheets/`)
- [x] `output/cashflow_intelligence.xlsx` — 92 rows, 12 columns,
      conditional formatting on distress/deleveraging flags
- [x] `output/pros_cons_generated.csv` — 521 rows, all 92 companies
      with at least one pro and one con
- [x] Sector reports (11 PDFs) render in `reports/sector/`
- [x] Portfolio summary (92-page PDF) at `reports/portfolio/portfolio_summary.pdf`
      with trend arrows
- [x] Sprint 5 retrospective signed off

## Exit criteria sign-off

| Criterion | Status |
|---|---|
| `pros_cons_generated.csv` has ≥1 pro and ≥1 con per company | PASS (0 missing) |
| All 92 tearsheets exist in `reports/tearsheets/` and are ≥30 KB | PASS (avg 113 KB) |
| Visual review of 5 tearsheets (no overflow / no blank pages) | PASS (programmatic + manual) |
| `cashflow_intelligence.xlsx` has 92 rows with all required columns | PASS |
| Sprint 5 review meeting completed | Ready for sign-off |
