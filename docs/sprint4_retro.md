# Sprint 4 Retrospective — Dashboard & Valuation (Days 22–28)

**Project:** Nifty 100 Financial Intelligence Platform
**Sprint:** 4 of 4 shipped (Dashboard & Valuation)
**Dates:** 2026-09-12 → 2026-09-14 (Days 22–28, accelerated)
**Status:** ✅ COMPLETE — all exit criteria met; 752/752 tests passing

---

## 1. What We Shipped

| Day | Deliverable | Status |
|-----|-------------|--------|
| D22 | Streamlit scaffold — `app.py`, 8 page stubs, `utils/db.py` with `@st.cache_data(ttl=600)`, wide layout, expanded sidebar | ✅ |
| D23 | Home screen (6 KPIs, sector donut, top-5, FY selector) + Company Profile (search, card, 6 metric tiles, Revenue/PAT bar, ROE/ROCE line, pros/cons, not-found message) | ✅ |
| D24 | Screener (10 sliders, 6 preset buttons, live table, CSV download, result count) + Peers (11 peer groups, 8-axis Scatterpolar radar vs peer avg, KPI table with gold benchmark) | ✅ |
| D25 | Trends (multi-metric dual-Y line, YoY annotations), Sectors (bubble chart, median KPI bars), Capital (Plotly treemap by capital-allocation pattern, drilldown), Reports (BSE PDF link checker, artefact downloads) | ✅ |
| D26 | Sector-relative valuation engine — FCF yield, sector-median P/E, 5yr median P/E, Caution/Discount/Fair flags; `output/valuation_summary.xlsx` (colour-coded); `output/valuation_flags.csv` (37 flagged initially) | ✅ |
| D27 | Integration QA — 8-screen smoke test across 10 cross-sector tickers, extreme-screener slider test, NaN-safe charts, partial-data note, Reports 2 s HEAD timeout, `st.columns` list fix | ✅ |
| D28 | Retro & documentation — README run instructions + 8-screen descriptions, Sprint 4 retro, task board update, valuation panel expanded to 92 companies (late-filer FY fallback) | ✅ |

### Final Test & Quality Numbers (end of Day 28)
- **Tests:** 752 passing (668 at start of Sprint 4, +84 across the sprint)
- **Formatting/Lint:** Black (line-length 100) clean; Ruff zero warnings
- **Profile render time:** 0.03–0.08 s per ticker (3 s budget met)
- **Valuation panel:** 92 companies (all latest-year market-cap names), 11 columns, colour-coded flags
- **Server health:** `/_stcore/health` returns `ok`; zero tracebacks after full page sweep

---

## 2. UX Decisions

1. **Wide layout + expanded sidebar by default.** Analysts need room for Plotly
   charts and navigating between 8 screens; collapsing the sidebar adds friction.
2. **Six-tile KPI pattern repeated** on Home and Profile so users build muscle
   memory for where to find headline numbers.
3. **Gold benchmark highlight** on the Peers KPI table and green/red status
   badges on the Reports page — scannable at a glance, never colour-only (text
   label always present).
4. **Consistent valuation flag colours** (red Caution, green Discount, yellow
   Fair) shared between `valuation_summary.xlsx` and any dashboard surface so
   users don't re-learn.
5. **NaN → N/A, never zero or blank.** Missing metrics render as "N/A" labels;
   partial-history charts (<10 years) get an explicit "partial data available"
   caption rather than silently truncating.
6. **Preset buttons in the original §25 order** (quality_compounder, value_pick,
   growth_accelerator, dividend_champion, debt_free_blue_chip,
   turnaround_watch) so screeners map 1:1 to the spec document.

---

## 3. Data Edge Cases Discovered

| Finding | Resolution |
|---|---|
| `financial_ratios` rows missing for FY 2024-03 for NHPC, TORNTPHARM, BANDHANBNK (late filers) — valuation panel returned only 89/92 companies | Changed `load_valuation_panel()` to LEFT JOIN financial_ratios and fall back to each company's latest available FY fundamentals; panel now returns all 92 |
| `get_full_ratios_with_pl()` returns `company_id`, not `ticker` — AttributeError on Sectors/Capital pages | Patched pages 06 & 07 to use `company_id` and alias to `ticker` for display |
| SQLite has no `MEDIAN()` aggregate | Computed sector- and 5yr-medians in pandas; merged back into panel |
| `icr_label` all NULL in current DB build | Debt-free filter uses `icr_label == "Debt Free" OR D/E ≤ 0.05` |
| `prosandcons` populated for only 16 companies | Profile renders "No data" caption when no rows (e.g. TCS) |
| Latest-FY `capital_allocation_pattern` only covers 4 of the 8 buckets | Treemap renders only populated buckets; full 8-colour palette retained for forward-compatibility |
| BSE `urlopen` HEAD stalls 4+ seconds | Tightened to 2 s timeout; unknown tickers skip the probe |
| ROE/ROCE series all-NaN for some partial-history tickers crashed Plotly | Charts `dropna(how="all")` and plot only non-null traces |
| Revenue/PAT chart crashed when recent years had NaN net profit | dropna on the value subset before plotting + partial-data caption |
| `st.columns()` originally shimmed for integers only; ratio lists like `[1,1,1,1,1,1]` broke | Shim now accepts ints and iterables (matches real Streamlit) |

---

## 4. Performance Findings

- `@st.cache_data(ttl=600)` makes intra-session navigation effectively free
  after first load.
- **Profile screen 0.03–0.08 s** per ticker across the 5 spot-checked names
  (TCS, HDFCBANK, HINDUNILVR, RELIANCE, SUNPHARMA) — ~40× under the 3 s budget.
- Heavy Plotly charts (treemap, bubble, radar) render <200 ms on production
  data; the 5yr-P/E median aggregation runs once per panel load, not per
  company.
- The full pytest suite runs in ~2.5 minutes end-to-end; Day-27 integration
  tests (in-process Streamlit shim) account for ~60 seconds of that.
- BSE HEAD timeout reduction from 4 s → 2 s cut Reports-page worst-case
  render from >8 s to <3 s even when BSE is slow.

---

## 5. What Went Well

- The shim-based integration approach let us exercise every page against real
  production data without spinning up a browser, catching real column-name and
  NaN bugs (ticker/company_id, BSE timeouts) that unit tests wouldn't see.
- Valuation flag thresholds (1.5× / 0.7×) produced a believable distribution
  out of the gate (14 Caution / 25 Discount / 53 Fair) — no re-tuning needed.
- The preset → screener → CSV-download flow works end-to-end with correct
  column headers.
- Consistent commit-message discipline (`[SprintN-DayM] feat: …`) made history
  bisect-able.

## 6. What We'd Improve Next Sprint

- Adopt `streamlit.testing.v1.AppTest` (once stable on Python 3.13) for true
  headless E2E; the shim catches Python exceptions but not CSS / layout
  regressions.
- Pre-compute and persist the valuation panel alongside the DB so Home,
  Screener, and future valuation screens don't re-join market_cap/financial_
  ratios/balancesheet/PL independently.
- Back-fill `prosandcons` for the remaining 76 companies (16/92 is thin for
  the Profile screen).
- Add proper typing / `py.typed` marker and tighten a handful of loose
  `sqlite3.Connection | str | Path` signatures.
- Wire the FastAPI surface (scaffolded but not yet exposed) so the dashboard
  can optionally query through a thin data layer instead of hitting SQLite
  directly.

---

## 7. Demo Sign-off Checklist

- [x] Streamlit running on `0.0.0.0:8501`; `/_stcore/health` returns `ok`
- [x] Home — KPI tiles, sector donut, top-5, FY selector render
- [x] Profile — TCS (IT), HDFCBANK (Financials), HINDUNILVR (FMCG),
      RELIANCE (Energy), SUNPHARMA (Healthcare) all render <3 s with charts
- [x] Screener — sliders respond, 6 preset buttons load, CSV download produces
      a correctly-headed file, extreme slider values don't crash
- [x] Peers — all 11 peer groups load, radar renders, gold benchmark highlights
- [x] Trends — multi-metric select, dual-Y axis, YoY annotations
- [x] Sectors — bubble chart renders, bubbles sized by market cap, median bars
- [x] Capital — treemap renders with 4 populated pattern groups, drill-down
- [x] Reports — BSE links show status badges, artefact downloads present,
      ghost ticker handled gracefully
- [x] `output/valuation_summary.xlsx` — 92 rows, 11 columns, colour-coded flags
- [x] `output/valuation_flags.csv` — 39 Caution/Discount rows
- [x] 752/752 tests passing; Black & Ruff clean
