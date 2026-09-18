"""Generate docs/analyst_guide.pdf - an Analyst User Guide for the platform.

At least 10 pages covering:
  - Platform overview
  - Setup / launch
  - Streamlit dashboard screens (Home, Profile, Screener, Peers, Trends,
    Sectors, Capital Allocation, Reports)
  - Screener presets
  - PDF tearsheet generation
  - REST API with curl examples
  - Troubleshooting
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parents[1] / "docs" / "analyst_guide.pdf"

styles = getSampleStyleSheet()
H1 = ParagraphStyle(
    "H1",
    parent=styles["Heading1"],
    fontSize=20,
    spaceAfter=14,
    textColor=colors.HexColor("#0B3D91"),
)
H2 = ParagraphStyle(
    "H2", parent=styles["Heading2"], fontSize=14, spaceAfter=8, textColor=colors.HexColor("#0B3D91")
)
H3 = ParagraphStyle(
    "H3", parent=styles["Heading3"], fontSize=12, spaceAfter=6, textColor=colors.HexColor("#333333")
)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=6)
CODE = ParagraphStyle(
    "Code",
    parent=styles["BodyText"],
    fontName="Courier",
    fontSize=9,
    leading=12,
    leftIndent=12,
    backColor=colors.HexColor("#F4F4F4"),
    textColor=colors.HexColor("#1a1a1a"),
)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=18, bulletIndent=6)
TITLE = ParagraphStyle(
    "Title",
    parent=styles["Title"],
    fontSize=26,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#0B3D91"),
)
SUB = ParagraphStyle(
    "Sub", parent=BODY, alignment=TA_CENTER, fontSize=12, textColor=colors.HexColor("#555555")
)


def bullets(items: list[str]) -> list:
    return [Paragraph(f"• {i}", BULLET) for i in items]


def code(text: str) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>").replace(" ", "&nbsp;"), CODE)


def page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(2 * cm, 1.2 * cm, "Nifty 100 Financial Intelligence Platform - Analyst Guide")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build() -> None:
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Nifty 100 Analyst Guide",
        author="Nifty 100 Platform",
    )
    story: list = []

    # --------- Cover ----------
    story += [
        Spacer(1, 4 * cm),
        Paragraph("Nifty 100 Financial Intelligence Platform", TITLE),
        Spacer(1, 0.4 * cm),
        Paragraph("Analyst User Guide", SUB),
        Spacer(1, 0.2 * cm),
        Paragraph("Sprint 6 - API, Clustering &amp; Sign-off", SUB),
        Spacer(1, 4 * cm),
        Paragraph(
            "A practical handbook for equity-research analysts covering the "
            "Streamlit dashboard, PDF tearsheet generation, and the REST API.",
            BODY,
        ),
        PageBreak(),
    ]

    # --------- 1. Overview ----------
    story += [
        Paragraph("1. Platform Overview", H1),
        Paragraph(
            "The Nifty 100 Financial Intelligence Platform is a Python-based "
            "analytics workspace covering 92 large- and mid-cap Indian equities "
            "with up to 14 years of financial history. It combines four layers:",
            BODY,
        ),
        *bullets(
            [
                "<b>ETL pipeline</b> - ingests 12 Screener.in Excel files, normalises "
                "company identifiers and financial-year labels, runs 16 data-quality "
                "rules, and loads the data into a SQLite warehouse "
                "(<font face='Courier'>db/nifty100.db</font>).",
                "<b>KPI engine</b> - computes 60+ financial ratios including ROE, "
                "ROCE, D/E, ICR, free cash flow, CAGR, valuation multiples and a "
                "0-100 composite quality score.",
                "<b>Analytics</b> - peer-group percentiles, capital-allocation "
                "pattern detection, outlier detection, KMeans clustering into 5 "
                "archetypes (High-Quality Compounder, Value Cyclical, Defensive "
                "Dividend Payer, Emerging Growth, Distressed / Turnaround).",
                "<b>Surfaces</b> - an 8-screen Streamlit dashboard, a FastAPI REST "
                "API (/api/v1), and batch PDF tearsheet generation.",
            ]
        ),
        Spacer(1, 0.4 * cm),
        Paragraph(
            "The dashboard and API are read-only views over the warehouse. "
            "Refresh the data by re-running the ETL scripts from the "
            "<font face='Courier'>scripts/</font> directory.",
            BODY,
        ),
        PageBreak(),
    ]

    # --------- 2. Setup & Launch ----------
    story += [
        Paragraph("2. Setup &amp; Launch", H1),
        Paragraph("2.1 Pre-requisites", H2),
        *bullets(
            [
                "Python 3.11 or newer (tested on 3.13).",
                "The dependencies listed in <font face='Courier'>pyproject.toml</font> "
                "(FastAPI, Streamlit, Pandas, scikit-learn, ReportLab, Plotly, …).",
                "Raw data files in <font face='Courier'>data/raw/</font> (7 core "
                "Screener.in exports) and <font face='Courier'>data/raw/supporting "
                "datasets/</font> (5 supplementary files).",
            ]
        ),
        Paragraph("2.2 Install", H2),
        code("pip install -r requirements.txt    # or install via pip as needed"),
        Spacer(1, 0.3 * cm),
        Paragraph("2.3 Run the ETL (first time / refresh)", H2),
        code(
            "python scripts/day1_ingest.py         # import raw data\n"
            "python scripts/day2_normalise.py      # normalise ids/years\n"
            "python scripts/populate_ratios.py     # compute financial ratios\n"
            "python scripts/day36_clustering.py    # KMeans clustering\n"
            "python scripts/generate_tearsheets.py # 92 per-company PDFs"
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("2.4 Launch the dashboard and API", H2),
        code(
            "# FastAPI on http://127.0.0.1:8000\n"
            "uvicorn src.api.main:app --port 8000 --host 0.0.0.0\n"
            "\n"
            "# Streamlit dashboard on http://127.0.0.1:8501\n"
            "streamlit run src/dashboard/app.py"
        ),
        Spacer(1, 0.3 * cm),
        Paragraph(
            "Both servers can run simultaneously without port conflict (the API "
            "is on 8000, the dashboard on 8501). The dashboard reads data "
            "directly from the SQLite database, not from the API, but the API "
            "can be used to power custom scripts or external tools.",
            BODY,
        ),
        PageBreak(),
    ]

    # --------- 3. Dashboard Screens ----------
    story += [
        Paragraph("3. Dashboard Screens", H1),
        Paragraph(
            "The Streamlit dashboard has eight screens, selectable from the " "left-hand sidebar.",
            BODY,
        ),
        Paragraph("3.1 Home", H2),
        Paragraph(
            "Landing page with headline statistics (92 companies, 11 sectors, "
            "date range) and an overview of the five cluster archetypes with "
            "company counts.",
            BODY,
        ),
        Paragraph("3.2 Company Profile", H2),
        Paragraph(
            "Select a ticker from the drop-down (or type to search). The page " "renders:",
            BODY,
        ),
        *bullets(
            [
                "Company name, sector, market-cap category, website and NSE/BSE links.",
                "Key ratios: ROE, ROCE, D/E, ICR, PE, PB, dividend yield.",
                "10-year sales/PAT/EPS trend chart.",
                "Latest cluster label and capital-allocation pattern.",
                "A <b>Download Tearsheet PDF</b> button (see §5).",
            ]
        ),
        Paragraph("3.3 Screener", H2),
        Paragraph(
            "The interactive stock screener. Adjust sliders and drop-downs for "
            "min ROE, max D/E, min FCF, sector, min Revenue CAGR, min PAT CAGR, "
            "max PE. Results are sorted by composite quality score descending. "
            "Six preset buttons apply pre-built filters (see §4).",
            BODY,
        ),
        Paragraph("3.4 Peers", H2),
        Paragraph(
            "Pick a peer group (IT Services, Private Banks, FMCG, …) to see "
            "every member with percentile ranks across 10 metrics and a radar "
            "chart comparing the selected company with the peer-group average "
            "and the benchmark (e.g. TCS for IT Services).",
            BODY,
        ),
        PageBreak(),
        Paragraph("3.5 Trends", H2),
        Paragraph(
            "Multi-year line charts for a selected ticker across sales, "
            "operating profit, net profit, EPS, OPM, ROCE, and D/E.",
            BODY,
        ),
        Paragraph("3.6 Sectors", H2),
        Paragraph(
            "Median ROE / PE / D/E across all 11 broad sectors, plus a "
            "drill-down table listing every company in a chosen sector with "
            "their KPI values.",
            BODY,
        ),
        Paragraph("3.7 Capital Allocation", H2),
        Paragraph(
            "Donut chart showing the distribution of the 8-class capital-"
            "allocation taxonomy (Reinvestor, Shareholder Returns, Liquidating "
            "Assets, Distress Signal, Growth Funded by Debt, Cash Accumulator, "
            "Pre-Revenue, Mixed), plus a per-pattern company list.",
            BODY,
        ),
        Paragraph("3.8 Reports", H2),
        Paragraph(
            "Download centre for generated artifacts: per-company tearsheet "
            "PDFs, the 92-page portfolio summary PDF, sector reports, CSV "
            "exports (capital_allocation.csv, valuation_flags.csv, distress_"
            "alerts.csv) and the OpenAPI / Postman API specs.",
            BODY,
        ),
        PageBreak(),
    ]

    # --------- 4. Screener Presets ----------
    story += [
        Paragraph("4. Screener Presets", H2),
        Paragraph(
            "Six one-click preset buttons on the Screener screen apply "
            "curated filter combinations (defined in spec §25):",
            BODY,
        ),
        Spacer(1, 0.2 * cm),
    ]
    preset_data = [
        ["Preset", "Filter criteria"],
        ["Quality Compounder", "ROE ≥ 18%, D/E ≤ 0.5, 5yr PAT CAGR ≥ 10%, PE ≤ 40"],
        ["Value Pick", "ROE ≥ 12%, D/E ≤ 1.0, PE ≤ 15, PB ≤ 2"],
        ["Growth Accelerator", "5yr Revenue CAGR ≥ 15%, 5yr PAT CAGR ≥ 15%, ROE ≥ 12%"],
        ["Dividend Champion", "Dividend Yield ≥ 2.5%, D/E ≤ 0.5, ROE ≥ 12%"],
        ["Debt-Free Blue Chip", "D/E = 0, Market Cap = Large Cap, ROE ≥ 15%"],
        ["Turnaround Watch", "D/E ≤ 2.0, latest PAT &gt; 0, 3yr PAT CAGR flagged TURNAROUND"],
    ]
    t = Table(preset_data, colWidths=[4.5 * cm, 11.5 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(t)
    story += [
        Spacer(1, 0.5 * cm),
        Paragraph(
            "Presets are additive with the manual sliders; adjust any preset "
            "further to refine results.",
            BODY,
        ),
        PageBreak(),
    ]

    # --------- 5. PDF Tearsheets ----------
    story += [
        Paragraph("5. Generating PDF Tearsheets", H1),
        Paragraph("5.1 Single-company tearsheet", H2),
        Paragraph(
            "From the Company Profile page, click <b>Download Tearsheet PDF</b>. "
            "A 2-page PDF is generated on demand and served as a download. "
            "You can also fetch a tearsheet directly from the API:",
            BODY,
        ),
        code(
            "curl -o TCS_tearsheet.pdf \\\n  http://127.0.0.1:8000/api/v1/companies/TCS/tearsheet"
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("5.2 Batch generation", H2),
        Paragraph(
            "To regenerate all 92 tearsheets in one go (takes ~30 seconds), " "run:",
            BODY,
        ),
        code("python scripts/generate_tearsheets.py"),
        Spacer(1, 0.2 * cm),
        Paragraph(
            "Outputs are written to <font face='Courier'>reports/tearsheets/"
            "&lt;TICKER&gt;_tearsheet.pdf</font>. The 92-page portfolio "
            "summary is produced by:",
            BODY,
        ),
        code("python scripts/generate_portfolio_pdf.py"),
        Spacer(1, 0.3 * cm),
        Paragraph("5.3 Contents of each tearsheet", H2),
        *bullets(
            [
                "Page 1 - Header with company identity and sector, 10-year KPI table, "
                "cluster label, composite quality score, algorithmically generated "
                "strengths / weaknesses bullets.",
                "Page 2 - Sales/PAT trend chart, ROE/ROCE trend, balance-sheet "
                "summary, peer radar chart, and capital-allocation pattern "
                "callout.",
            ]
        ),
        Paragraph(
            "All tables use Paragraph flowables with word-wrap enabled so long "
            "text does not overflow cells; the rupee symbol is rendered as "
            '"Rs" for font-compatibility.',
            BODY,
        ),
        PageBreak(),
    ]

    # --------- 6. REST API ----------
    story += [
        Paragraph("6. Calling the REST API", H1),
        Paragraph(
            "The FastAPI server exposes versioned endpoints under "
            "<font face='Courier'>/api/v1/</font>. Interactive documentation "
            "is live at <font face='Courier'>http://127.0.0.1:8000/docs</font> "
            "(Swagger UI) and <font face='Courier'>/redoc</font>. An OpenAPI "
            "3 JSON schema is available at "
            "<font face='Courier'>/export/openapi.json</font> and a Postman "
            "v2.1 collection at <font face='Courier'>/export/postman.json</font>.",
            BODY,
        ),
        Paragraph("6.1 Health check", H2),
        code("curl http://127.0.0.1:8000/api/v1/health"),
        Spacer(1, 0.2 * cm),
        Paragraph("6.2 List all companies", H2),
        code("curl http://127.0.0.1:8000/api/v1/companies/"),
        Spacer(1, 0.2 * cm),
        Paragraph("6.3 Get a company profile (TCS)", H2),
        code("curl http://127.0.0.1:8000/api/v1/companies/TCS"),
        Spacer(1, 0.2 * cm),
        Paragraph("6.4 Run the screener (min ROE 18%, sector IT)", H2),
        code(
            'curl "http://127.0.0.1:8000/api/v1/screener/'
            '?min_roe=18&amp;sector=Information+Technology"'
        ),
        Spacer(1, 0.2 * cm),
        Paragraph("6.5 Fetch 11 sectors with medians", H2),
        code("curl http://127.0.0.1:8000/api/v1/sectors/"),
        Spacer(1, 0.2 * cm),
        Paragraph("6.6 IT-sector companies", H2),
        code("curl http://127.0.0.1:8000/api/v1/sectors/Information%20Technology/companies"),
        Spacer(1, 0.2 * cm),
        Paragraph("6.7 Peer group &amp; radar", H2),
        code(
            "curl http://127.0.0.1:8000/api/v1/peers/IT%20Services\n"
            "curl http://127.0.0.1:8000/api/v1/companies/TCS/peers/compare"
        ),
        Spacer(1, 0.2 * cm),
        Paragraph("6.8 Market-cap history", H2),
        code("curl http://127.0.0.1:8000/api/v1/market-cap/TCS"),
        Spacer(1, 0.2 * cm),
        Paragraph("6.9 Portfolio stats &amp; clusters", H2),
        code(
            "curl http://127.0.0.1:8000/api/v1/portfolio/stats\n"
            "curl http://127.0.0.1:8000/api/v1/portfolio/clusters"
        ),
        PageBreak(),
    ]

    # --------- 7. Troubleshooting ----------
    story += [
        Paragraph("7. Troubleshooting", H1),
        Spacer(1, 0.2 * cm),
    ]
    issues = [
        ["Symptom", "Likely cause / fix"],
        [
            "Dashboard shows 0 companies",
            "Run the ETL (scripts/day1_ingest.py → scripts/populate_ratios.py) "
            "to populate db/nifty100.db. Verify the DB file exists.",
        ],
        [
            "API returns 404 for a ticker",
            "Tickers are case-insensitive but must match an NSE symbol exactly "
            "(e.g. 'M&M', 'BAJAJ-AUTO'). Use /companies/ to list valid IDs.",
        ],
        [
            "Screener returns fewer than expected rows",
            "Filters are AND-ed together. Relax one slider or clear the sector " "filter.",
        ],
        [
            "Tearsheet download is slow",
            "Generating a tearsheet involves rendering two charts per company; "
            "expect ~200-500 ms. Batch generation is faster than one-by-one.",
        ],
        [
            "OPM cross-check warnings in load audit",
            "The source opm_percentage deviates from (operating_profit/sales)*100 "
            "by more than 1 pp; usually a rounding or typo in the raw file.",
        ],
        [
            "Port 8000 / 8501 already in use",
            "Stop any previous uvicorn/streamlit process or pass a different "
            "--port. 'fuser -k 8000/tcp' will free the port on Linux.",
        ],
        [
            "PDF shows boxes instead of Rs",
            "The platform uses the ASCII prefix 'Rs' instead of the rupee glyph "
            "because Helvetica does not include the U+20B9 character.",
        ],
        [
            "Cluster count doesn't match spec",
            "Clustering uses random_state=42; if you modified the input data, "
            "re-run scripts/day36_clustering.py and day37_cluster_profiling.py.",
        ],
    ]
    tt = Table(issues, colWidths=[5.0 * cm, 11.0 * cm])
    tt.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(tt)
    story += [
        PageBreak(),
        Paragraph("8. Test Suite &amp; Quality Gates", H1),
        Paragraph(
            "The project uses pytest with 600+ unit, integration and API tests. "
            "To run the suite:",
            BODY,
        ),
        code(
            "pytest tests/ -q                      # full suite\n"
            "pytest tests/api -q                  # API tests only\n"
            "pytest tests/perf -v                 # performance tests\n"
            "pytest tests/ --html=reports/pytest_report.html --self-contained-html"
        ),
        Spacer(1, 0.3 * cm),
        Paragraph(
            "Before commit, run Black (line length 100) and Ruff:",
            BODY,
        ),
        code("python -m black src/ tests/ scripts/\n" "python -m ruff check src/ tests/ scripts/"),
        Spacer(1, 0.5 * cm),
        Paragraph(
            "Happy analysing! For data issues or feature requests, check the "
            "load-audit table in the database and the log files under "
            "<font face='Courier'>logs/</font>.",
            BODY,
        ),
    ]

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(f"Analyst guide written to {OUT} ({OUT.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    build()
