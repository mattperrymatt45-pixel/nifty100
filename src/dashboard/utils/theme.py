"""Design system for the Nifty 100 institutional dashboard.

This module is the single source of truth for:

* Global CSS injected into every page (``apply_theme``) that hides Streamlit
  chrome, sets institutional typography, and restyles metric tiles to look
  like Bloomberg-style terminal tiles.
* A unified Plotly template (``PLOTLY_TEMPLATE``) that renders charts on a
  transparent background with the corporate color palette, muted gridlines,
  and no garish default colours.
* Column-config factories (``currency_col``, ``percent_col``, ``number_col``)
  that produce correctly formatted right-aligned ``st.column_config``
  instances -- currency abbreviated to "Cr" suffix, percentages with two
  decimals, integers with thousand separators.
* Number-formatting helpers (``fmt_cr``, ``fmt_pct``, ``fmt_num``) for ad-hoc
  string rendering outside dataframes.

All pages must call ``apply_theme()`` as their first Streamlit command after
``st.set_page_config`` (which lives in ``app.py``).

Usage (top of any page module)::

    import streamlit as st
    from src.dashboard.utils.theme import apply_theme
    apply_theme()
"""

from __future__ import annotations

import re

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
COLORS = {
    "bg": "#0B0F17",  # canvas
    "panel": "#131822",  # surface / card
    "card": "#1A2030",  # elevated card
    "border": "#252C3D",  # hairline borders
    "border_hi": "#2F3B55",  # focus borders
    "text": "#E8ECEF",  # primary text
    "text_mute": "#8A94A6",  # secondary / captions
    "text_dim": "#5E6878",  # tertiary / disabled
    "gold": "#C9A227",  # primary accent
    "gold_dim": "#8C7120",  # muted gold
    "green": "#2EB886",  # positive (muted forest)
    "red": "#D94F5C",  # negative (muted brick)
    "blue": "#4C8BF5",  # info / links
    "slate": "#5B6B86",  # neutral accent
    "amber": "#E0A43C",  # warning
}

# Corporate chart sequence -- muted, high-contrast, no neon.
CHART_PALETTE: list[str] = [
    "#C9A227",  # gold
    "#4C8BF5",  # slate blue
    "#2EB886",  # forest
    "#D94F5C",  # brick
    "#B07AE0",  # muted violet
    "#E0A43C",  # amber
    "#48B8D0",  # teal
    "#D17B55",  # terracotta
]

CHART_RED = COLORS["red"]
CHART_GREEN = COLORS["green"]
CHART_GOLD = COLORS["gold"]

FONT_FAMILY = (
    '"Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, ' '"Helvetica Neue", Arial, sans-serif'
)

# ---------------------------------------------------------------------------
# Plotly template
# ---------------------------------------------------------------------------
_PLOTLY_LAYOUT = dict(
    font=dict(family=FONT_FAMILY, size=12, color=COLORS["text"]),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    title_font=dict(size=15, color=COLORS["text"], family=FONT_FAMILY),
    title_x=0.0,
    title_xanchor="left",
    margin=dict(l=10, r=10, t=40, b=10),
    xaxis=dict(
        gridcolor=COLORS["border"],
        zerolinecolor=COLORS["border_hi"],
        linecolor=COLORS["border"],
        tickcolor=COLORS["border"],
        showgrid=False,
        gridwidth=1,
        tickfont=dict(size=11, color=COLORS["text_mute"]),
        title_font=dict(size=12, color=COLORS["text_mute"]),
    ),
    yaxis=dict(
        gridcolor=COLORS["border"],
        zerolinecolor=COLORS["border_hi"],
        linecolor=COLORS["border"],
        tickcolor=COLORS["border"],
        showgrid=True,
        gridwidth=1,
        griddash="dot",
        tickfont=dict(size=11, color=COLORS["text_mute"]),
        title_font=dict(size=12, color=COLORS["text_mute"]),
    ),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        bgcolor="rgba(0,0,0,0)",
        bordercolor="rgba(0,0,0,0)",
        font=dict(size=11, color=COLORS["text"]),
    ),
    hoverlabel=dict(
        bgcolor=COLORS["card"],
        bordercolor=COLORS["border_hi"],
        font=dict(family=FONT_FAMILY, size=11, color=COLORS["text"]),
    ),
    colorway=CHART_PALETTE,
    height=420,
)

PLOTLY_TEMPLATE = go.layout.Template(layout=go.Layout(**_PLOTLY_LAYOUT))
pio.templates["nifty_terminal"] = PLOTLY_TEMPLATE

# Plotly config -- hide the floating modebar.
PLOTLY_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
}


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------
_CSS = f"""
<style>
/* ---------- Reset Streamlit chrome ---------- */
    header, .stAppHeader {{ visibility: hidden; height: 0px !important; }}
    #MainMenu {{ visibility: hidden !important; }}
    footer {{ visibility: hidden !important; }}
    [data-testid="stDeployButton"] {{ display: none !important; }}
    [data-testid="stHeader"] {{ height: 0px !important; display: none !important; }}
    .stAppDeployButton {{ display: none !important; }}
    .stDecoration {{ display: none !important; }}

/* ---------- Global canvas ---------- */
    .stApp, .stAppViewContainer {{
        background-color: {COLORS["bg"]} !important;
        color: {COLORS["text"]};
        font-family: {FONT_FAMILY};
    }}
    .main .block-container {{
        padding-top: 1.4rem !important;
        padding-bottom: 2rem !important;
        max-width: 1500px !important;
    }}
    body, .stMarkdown, .stText, p, label, span {{
        color: {COLORS["text"]};
        font-family: {FONT_FAMILY};
        -webkit-font-smoothing: antialiased;
    }}

/* ---------- Typography ---------- */
    h1, h2, h3, h4, h5, h6 {{
        color: {COLORS["text"]} !important;
        font-family: {FONT_FAMILY};
        font-weight: 600;
        letter-spacing: -0.01em;
    }}
    h1 {{
        font-size: 1.75rem; font-weight: 700; margin-bottom: 0.25rem;
        border-bottom: 1px solid {COLORS["border"]}; padding-bottom: 0.6rem;
    }}
    h2 {{ font-size: 1.25rem; font-weight: 600; margin-top: 1.2rem; }}
    h3 {{
        font-size: 0.78rem; font-weight: 600; color: {COLORS["text"]};
        letter-spacing: 0.04em; text-transform: uppercase;
    }}
    .stCaption, small, [data-testid="stCaptionContainer"] {{
        color: {COLORS["text_mute"]} !important;
        font-size: 0.78rem;
        letter-spacing: 0.02em;
    }}
    a, a:visited {{ color: {COLORS["blue"]}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

/* ---------- Dividers ---------- */
    hr, [data-testid="stHorizontalBlock"] + hr, .stHr {{
        border-color: {COLORS["border"]} !important;
        margin: 1.25rem 0 !important;
    }}
    [data-testid="stDivider"] {{
        border-top-color: {COLORS["border"]} !important;
    }}

/* ---------- Sidebar ---------- */
    section[data-testid="stSidebar"] {{
        background-color: {COLORS["panel"]} !important;
        border-right: 1px solid {COLORS["border"]};
        width: 260px !important;
    }}
    section[data-testid="stSidebar"] .block-container {{
        padding-top: 1.6rem !important;
    }}
    section[data-testid="stSidebar"] * {{
        color: {COLORS["text"]};
    }}
    .sidebar-brand {{
        padding: 0.3rem 0.5rem 0.9rem;
        border-bottom: 1px solid {COLORS["border"]};
        margin-bottom: 0.7rem;
    }}
    .sidebar-brand .brand-name {{
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: {COLORS["gold"]};
    }}
    .sidebar-brand .brand-sub {{
        font-size: 0.72rem;
        color: {COLORS["text_mute"]};
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-top: 0.15rem;
    }}

/* ---------- Radio (sidebar nav) ---------- */
    .stRadio label, .stRadio div[data-baseweb="radio"] label {{
        color: {COLORS["text"]} !important;
    }}
    div[data-baseweb="radio"] > div {{
        padding: 0.3rem 0.5rem !important;
        border-radius: 4px;
    }}
    div[data-baseweb="radio"] > div:hover {{
        background-color: {COLORS["card"]};
    }}
    div[data-baseweb="radio"] [aria-checked="true"] {{
        background-color: {COLORS["card"]} !important;
        border-left: 3px solid {COLORS["gold"]} !important;
    }}
    div[data-baseweb="radio"] [aria-checked="true"] + div p {{
        color: {COLORS["gold"]} !important;
        font-weight: 600;
    }}

/* ---------- KPI metric cards ---------- */
    [data-testid="stMetric"] {{
        background-color: {COLORS["card"]};
        border: 1px solid {COLORS["border"]};
        border-top: 2px solid {COLORS["gold"]};
        border-radius: 4px;
        padding: 0.9rem 1rem 0.85rem !important;
        margin-bottom: 0.4rem;
        transition: border-color 0.15s ease;
    }}
    [data-testid="stMetric"]:hover {{
        border-color: {COLORS["border_hi"]};
    }}
    [data-testid="stMetricLabel"] p {{
        font-size: 0.68rem !important;
        font-weight: 600;
        letter-spacing: 0.10em;
        text-transform: uppercase;
        color: {COLORS["text_mute"]} !important;
    }}
    [data-testid="stMetricValue"] > div {{
        font-size: 1.55rem !important;
        font-weight: 700;
        color: {COLORS["text"]} !important;
        font-variant-numeric: tabular-nums;
        padding-top: 0.2rem;
    }}
    [data-testid="stMetricDelta"] {{
        font-size: 0.75rem;
    }}

/* ---------- KPI cards: green/red border accents based on direction class.
   Pages add these classes via st.metric(..., delta_color="normal") combined
   with the data-testid attribute. We keep the default gold top and rely on
   the built-in delta colours (we restyle them just below). */
    [data-testid="stMetric"] [data-testid="stMetricDelta"] > div > div > span {{
        font-variant-numeric: tabular-nums;
        font-weight: 600;
    }}
    [data-testid="stMetric"] [data-testid="stMetricDelta"] svg {{
        display: none;
    }}

/* ---------- Select boxes / inputs ---------- */
    .stSelectbox label, .stTextInput label, .stMultiSelect label,
    .stSlider label, .stNumberInput label, .stDateInput label {{
        font-size: 0.70rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: {COLORS["text_mute"]} !important;
    }}
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div {{
        background-color: {COLORS["card"]} !important;
        border-color: {COLORS["border"]} !important;
        color: {COLORS["text"]} !important;
        border-radius: 3px !important;
    }}
    div[data-baseweb="select"]:hover > div,
    div[data-baseweb="input"]:hover > div {{
        border-color: {COLORS["border_hi"]} !important;
    }}
    .stSlider {{ padding-top: 0.5rem; }}

/* ---------- Dataframes ---------- */
    [data-testid="stDataFrame"] {{
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        background-color: {COLORS["card"]};
        overflow: hidden;
    }}
    [data-testid="stDataFrame"] table {{
        font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace;
        font-size: 0.82rem;
    }}
    [data-testid="stDataFrame"] th {{
        background-color: {COLORS["panel"]} !important;
        color: {COLORS["text_mute"]} !important;
        font-weight: 600 !important;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        font-size: 0.68rem !important;
        border-bottom: 1px solid {COLORS["border"]} !important;
    }}
    [data-testid="stDataFrame"] td {{
        color: {COLORS["text"]} !important;
        border-bottom: 1px solid {COLORS["border"]} !important;
    }}
    [data-testid="stDataFrame"] tr:hover td {{
        background-color: rgba(201, 162, 39, 0.06) !important;
    }}

/* ---------- Buttons ---------- */
    .stButton > button {{
        background-color: {COLORS["card"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 3px;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.45rem 0.8rem;
        transition: all 0.15s ease;
    }}
    .stButton > button:hover {{
        background-color: {COLORS["panel"]};
        border-color: {COLORS["gold"]};
        color: {COLORS["gold"]};
    }}
    .stButton > button:focus:not(:active) {{
        border-color: {COLORS["gold"]};
        color: {COLORS["gold"]};
        box-shadow: 0 0 0 1px {COLORS["gold_dim"]};
    }}
    .stDownloadButton > button {{
        background-color: {COLORS["card"]} !important;
        color: {COLORS["text"]} !important;
        border: 1px solid {COLORS["border"]} !important;
        border-radius: 3px !important;
        font-weight: 600 !important;
        letter-spacing: 0.05em;
    }}
    .stDownloadButton > button:hover {{
        border-color: {COLORS["gold"]} !important;
        color: {COLORS["gold"]} !important;
    }}

/* ---------- Alerts ---------- */
    [data-testid="stInfo"],    [data-testid="stSuccess"],
    [data-testid="stWarning"], [data-testid="stError"] {{
        border-radius: 3px;
        border-left-width: 3px;
    }}

/* ---------- Tabs ---------- */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 0;
        border-bottom: 1px solid {COLORS["border"]};
    }}
    .stTabs [data-baseweb="tab"] {{
        color: {COLORS["text_mute"]};
        border-radius: 0;
        padding: 0.5rem 1rem;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }}
    .stTabs [aria-selected="true"] {{
        color: {COLORS["gold"]} !important;
        border-bottom: 2px solid {COLORS["gold"]} !important;
    }}

/* ---------- Expander ---------- */
    [data-testid="stExpander"] {{
        border: 1px solid {COLORS["border"]};
        border-radius: 3px;
        background-color: {COLORS["card"]};
    }}
    [data-testid="stExpander"] summary {{
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: {COLORS["text_mute"]};
    }}

/* ---------- Scrollbar ---------- */
    ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
    ::-webkit-scrollbar-track {{ background: {COLORS["bg"]}; }}
    ::-webkit-scrollbar-thumb {{ background: {COLORS["border_hi"]}; border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: {COLORS["slate"]}; }}

/* ---------- Utility: section header (used by pages for mini-section labels) */
    .section-label {{
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: {COLORS["gold"]};
        margin: 1.4rem 0 0.5rem;
        padding-bottom: 0.3rem;
        border-bottom: 1px solid {COLORS["border"]};
    }}

/* ---------- Utility: page footer stamp ---------- */
    .app-stamp {{
        font-size: 0.66rem;
        color: {COLORS["text_dim"]};
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-top: 2rem;
        padding-top: 0.8rem;
        border-top: 1px solid {COLORS["border"]};
    }}
</style>
"""


def apply_theme() -> None:
    """Inject the global CSS and apply the Plotly template.

    Must be called once per page (Streamlit re-runs the script on every
    interaction, and CSS doesn't persist across pages). Safe to call
    multiple times -- the CSS is idempotent.
    """
    st.markdown(_CSS, unsafe_allow_html=True)
    pio.templates.default = "nifty_terminal"


def plotly_chart(fig: go.Figure, height: int | None = None) -> None:
    """Render a Plotly figure with the institutional template and no modebar.

    Convenience wrapper around ``st.plotly_chart`` so pages do not have to
    remember to pass ``config`` and ``use_container_width``.
    """
    if height is not None:
        fig.update_layout(height=height)
    # Enforce the template regardless of what the figure set.
    fig.update_layout(template="nifty_terminal")
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------
def _abbreviate_crore(value: float) -> str:
    """Format a value (in INR Crore) with an appropriate suffix.

    Returns values >= 100,000 Cr as lakh-Cr (LCr), values >= 1,000 Cr as
    thousand-Cr, otherwise adds thousand separators. Produces output like
    "Rs 12,400 Cr", "Rs 12.4K Cr", "Rs 1.24 LCr".
    """
    v = float(value)
    if abs(v) >= 100_000:
        return f"Rs {v/100_000:,.2f} LCr"
    if abs(v) >= 1_000:
        return f"Rs {v/1_000:,.1f}K Cr"
    return f"Rs {v:,.0f} Cr"


def _fmt_plain(value: float, digits: int = 0) -> str:
    """Thousand-separated plain number with configurable decimal places."""
    return f"{float(value):,.{digits}f}"


def fmt_cr(value: object, plain: bool = False) -> str:
    """Format a value in INR Crore. Returns "-" for NaN/None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    v = float(value)
    if plain:
        return _fmt_plain(v)
    return _abbreviate_crore(v)


def fmt_pct(value: object, digits: int = 2) -> str:
    """Format as percentage with exactly ``digits`` decimals."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    return f"{float(value):.{digits}f}%"


def fmt_num(value: object, digits: int = 1) -> str:
    """Thousand-separated number with ``digits`` decimals."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    return _fmt_plain(float(value), digits)


def fmt_ratio(value: object, digits: int = 2) -> str:
    """Format a ratio/multiple with trailing 'x' (e.g. 18.42x)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    return f"{float(value):.{digits}f}x"


# ---------------------------------------------------------------------------
# st.column_config factories
# ---------------------------------------------------------------------------
def currency_col(label: str) -> st.column_config.TextColumn:
    """Right-aligned Crore column (pre-format values with ``fmt_cr``)."""
    return st.column_config.TextColumn(label, help="Amount in INR Crore")


def percent_col(label: str) -> st.column_config.NumberColumn:
    """Percentage column with two decimal places and percent sign.

    IMPORTANT: values in our DB are already in percentage units (e.g.,
    25.4 means 25.4%). d3 ``%`` multiplies by 100, so we rely on a plain
    fixed-decimal format and the column label carries the (%) suffix.
    """
    return st.column_config.NumberColumn(
        label,
        format=",.2f",
        step=0.01,
    )


def number_col(label: str, digits: int = 1) -> st.column_config.NumberColumn:
    """Thousand-separated numeric column (d3-format)."""
    return st.column_config.NumberColumn(label, format=f",.{digits}f")


def ratio_col(label: str, digits: int = 2) -> st.column_config.NumberColumn:
    """Ratio/multiple column (e.g., 18.42); 'x' suffix carried in header."""
    return st.column_config.NumberColumn(label, format=f",.{digits}f", step=0.01)


def text_col(label: str, width: str | None = None) -> st.column_config.TextColumn:
    """Left-aligned text column (ticker/company name)."""
    return st.column_config.TextColumn(label)


# ---------------------------------------------------------------------------
# Conditional-format helpers
# ---------------------------------------------------------------------------
def style_dataframe(
    df: pd.DataFrame, green_cols: set[str] | None = None, red_cols: set[str] | None = None
) -> pd.DataFrame:
    """Return ``df`` with muted green/red text for positive/negative values.

    Operates on a copy and only stylses numeric columns that are listed in
    ``green_cols`` (positive = green, negative = red). Callers pass in the
    formatted-string or numeric version of the dataframe; if numeric values
    are passed we colour by sign, if strings we detect a leading "-".
    """
    green_cols = green_cols or set()
    red_cols = red_cols or set()

    def _color_cell(val: object, positive_is_good: bool) -> str:
        if val is None or pd.isna(val):
            return ""
        try:
            n = float(re.sub(r"[^\d.\-]", "", str(val)))
        except (ValueError, TypeError):
            return ""
        if n > 0:
            return f"color: {CHART_GREEN};" if positive_is_good else f"color: {CHART_RED};"
        if n < 0:
            return f"color: {CHART_RED};" if positive_is_good else f"color: {CHART_GREEN};"
        return f"color: {COLORS['text_mute']};"

    styler = df.style
    for col in green_cols:
        if col in df.columns:
            styler = styler.map(lambda v: _color_cell(v, True), subset=[col])
    for col in red_cols:
        if col in df.columns:
            styler = styler.map(lambda v: _color_cell(v, False), subset=[col])
    return styler


# ---------------------------------------------------------------------------
# Page header / section helpers
# ---------------------------------------------------------------------------
def page_header(title: str, subtitle: str | None = None) -> None:
    """Render a crisp institutional page header (no emojis, tight leading)."""
    st.markdown(f"# {title}")
    if subtitle:
        st.caption(subtitle)


def section_label(text: str) -> None:
    """Render a small uppercase section label in gold."""
    st.markdown(f"<div class='section-label'>{text}</div>", unsafe_allow_html=True)


def app_stamp() -> None:
    """Render a subtle footer stamp."""
    st.markdown(
        "<div class='app-stamp'>NIFTY 100 FINANCIAL INTELLIGENCE PLATFORM"
        "&nbsp;&nbsp;|&nbsp;&nbsp;INSTITUTIONAL TERMINAL"
        "&nbsp;&nbsp;|&nbsp;&nbsp;DATA AS OF LATEST FY</div>",
        unsafe_allow_html=True,
    )
