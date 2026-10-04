"""Screen 03 - Stock Screener.

10 metric sliders, 6 preset buttons, live-updating results table and
CSV download button.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard.utils.db import get_screener_dataset
from src.dashboard.utils.theme import (
    COLORS,
    app_stamp,
    fmt_cr,
    number_col,
    page_header,
    percent_col,
    ratio_col,
    section_label,
    style_dataframe,
    text_col,
)

# ---------------------------------------------------------------------------
# Preset thresholds.
# ---------------------------------------------------------------------------
PRESETS: dict[str, dict[str, float]] = {
    "Quality": dict(
        roe_min=15.0,
        de_max=1.0,
        fcf_min=0.0,
        rev_cagr_min=10.0,
        pat_cagr_min=0.0,
        opm_min=0.0,
        pe_max=100.0,
        pb_max=20.0,
        div_yield_min=0.0,
        icr_min=0.0,
    ),
    "Value": dict(
        roe_min=0.0,
        de_max=2.0,
        fcf_min=-1e9,
        rev_cagr_min=0.0,
        pat_cagr_min=0.0,
        opm_min=0.0,
        pe_max=20.0,
        pb_max=3.0,
        div_yield_min=1.0,
        icr_min=0.0,
    ),
    "Growth": dict(
        roe_min=0.0,
        de_max=2.0,
        fcf_min=-1e9,
        rev_cagr_min=15.0,
        pat_cagr_min=20.0,
        opm_min=0.0,
        pe_max=100.0,
        pb_max=20.0,
        div_yield_min=0.0,
        icr_min=0.0,
    ),
    "Dividend": dict(
        roe_min=0.0,
        de_max=3.0,
        fcf_min=0.0,
        rev_cagr_min=0.0,
        pat_cagr_min=0.0,
        opm_min=0.0,
        pe_max=100.0,
        pb_max=20.0,
        div_yield_min=2.0,
        icr_min=0.0,
    ),
    "Debt-Free": dict(
        roe_min=12.0,
        de_max=0.2,
        fcf_min=-1e9,
        rev_cagr_min=0.0,
        pat_cagr_min=0.0,
        opm_min=0.0,
        pe_max=100.0,
        pb_max=20.0,
        div_yield_min=0.0,
        icr_min=3.0,
    ),
    "Turnaround": dict(
        roe_min=0.0,
        de_max=5.0,
        fcf_min=0.0,
        rev_cagr_min=10.0,
        pat_cagr_min=0.0,
        opm_min=0.0,
        pe_max=100.0,
        pb_max=20.0,
        div_yield_min=0.0,
        icr_min=0.0,
    ),
}

DEFAULT_FILTERS: dict[str, float] = PRESETS["Quality"]

PRESET_ORDER = ["Quality", "Value", "Growth", "Dividend", "Debt-Free", "Turnaround"]


def _init_state() -> None:
    """Seed session state with default slider values once per run."""
    for k, v in DEFAULT_FILTERS.items():
        st.session_state.setdefault(k, v)


def _preset_buttons() -> None:
    """Render the 6 preset buttons; clicking one resets slider state."""
    section_label("Strategy Presets")
    cols = st.columns(3)
    for i, name in enumerate(PRESET_ORDER):
        with cols[i % 3]:
            if st.button(name, use_container_width=True, key=f"preset_{name}"):
                for k, v in PRESETS[name].items():
                    st.session_state[k] = v
                st.rerun()


def _sliders() -> dict[str, float]:
    """Render the 10 metric sliders in the sidebar."""
    with st.sidebar:
        st.divider()
        st.markdown("<div class='section-label'>Screener Filters</div>", unsafe_allow_html=True)

        roe_min = st.slider(
            "ROE min (%)", 0.0, 40.0, st.session_state.get("roe_min", 15.0), 0.5, key="roe_min"
        )
        de_max = st.slider(
            "D/E max", 0.0, 5.0, st.session_state.get("de_max", 1.0), 0.05, key="de_max"
        )
        fcf_min = st.slider(
            "FCF min (Rs Cr)",
            -20000.0,
            50000.0,
            st.session_state.get("fcf_min", 0.0),
            500.0,
            key="fcf_min",
        )
        rev_cagr_min = st.slider(
            "Revenue CAGR 5Y min (%)",
            -10.0,
            40.0,
            st.session_state.get("rev_cagr_min", 10.0),
            0.5,
            key="rev_cagr_min",
        )
        pat_cagr_min = st.slider(
            "PAT CAGR 5Y min (%)",
            -20.0,
            50.0,
            st.session_state.get("pat_cagr_min", 0.0),
            0.5,
            key="pat_cagr_min",
        )
        opm_min = st.slider(
            "OPM min (%)", 0.0, 50.0, st.session_state.get("opm_min", 0.0), 0.5, key="opm_min"
        )
        pe_max = st.slider(
            "P/E max", 0.0, 100.0, st.session_state.get("pe_max", 100.0), 1.0, key="pe_max"
        )
        pb_max = st.slider(
            "P/B max", 0.0, 20.0, st.session_state.get("pb_max", 20.0), 0.5, key="pb_max"
        )
        div_yield_min = st.slider(
            "Dividend Yield min (%)",
            0.0,
            10.0,
            st.session_state.get("div_yield_min", 0.0),
            0.1,
            key="div_yield_min",
        )
        icr_min = st.slider(
            "ICR min", 0.0, 20.0, st.session_state.get("icr_min", 0.0), 0.5, key="icr_min"
        )

    return dict(
        roe_min=roe_min,
        de_max=de_max,
        fcf_min=fcf_min,
        rev_cagr_min=rev_cagr_min,
        pat_cagr_min=pat_cagr_min,
        opm_min=opm_min,
        pe_max=pe_max,
        pb_max=pb_max,
        div_yield_min=div_yield_min,
        icr_min=icr_min,
    )


def _apply_filters(df: pd.DataFrame, f: dict[str, float]) -> pd.DataFrame:
    """Apply slider filters and sort by composite descending."""
    mask = (
        (df["roe_pct"].fillna(-1e9) >= f["roe_min"])
        & (df["de"].fillna(1e9) <= f["de_max"])
        & (df["fcf_cr"].fillna(-1e9) >= f["fcf_min"])
        & (df["rev_cagr_5yr"].fillna(-1e9) >= f["rev_cagr_min"])
        & (df["pat_cagr_5yr"].fillna(-1e9) >= f["pat_cagr_min"])
        & (df["opm_pct"].fillna(-1e9) >= f["opm_min"])
        & (df["pe_ratio"].fillna(1e9) <= f["pe_max"])
        & (df["pb_ratio"].fillna(1e9) <= f["pb_max"])
        & (df["div_yield_pct"].fillna(-1e9) >= f["div_yield_min"])
        & (df["icr"].fillna(-1e9) >= f["icr_min"])
    )
    out = df[mask].copy()
    return out.sort_values("composite", ascending=False, na_position="last")


def _csv(df: pd.DataFrame) -> bytes:
    """Convert result DataFrame to UTF-8 CSV bytes."""
    return df.to_csv(index=False).encode("utf-8")


def render() -> None:
    """Render the Screener page."""
    page_header("Stock Screener", "Multi-factor screening across Nifty 100 constituents.")

    _init_state()
    filters = _sliders()
    _preset_buttons()

    df = get_screener_dataset()
    results = _apply_filters(df, filters)

    st.markdown(
        f"<div style='margin:0.5rem 0 1rem;color:{COLORS['text_mute']};font-size:0.85rem'>"
        f"<b style='color:{COLORS['text']}'>{len(results)}</b> constituents match filters</div>",
        unsafe_allow_html=True,
    )

    if results.empty:
        st.warning("No constituents match - widen the filters or select a preset.")
        app_stamp()
        return

    show = results[
        [
            "ticker",
            "company_name",
            "broad_sector",
            "composite",
            "roe_pct",
            "de",
            "fcf_cr",
            "rev_cagr_5yr",
            "pat_cagr_5yr",
            "opm_pct",
            "pe_ratio",
            "pb_ratio",
            "div_yield_pct",
            "icr",
        ]
    ].copy()
    show.columns = [
        "Ticker",
        "Company",
        "Sector",
        "Composite",
        "ROE",
        "D/E",
        "FCF",
        "Rev CAGR 5Y",
        "PAT CAGR 5Y",
        "OPM",
        "P/E",
        "P/B",
        "Div Yield",
        "ICR",
    ]
    # Pre-format currency column
    show["FCF"] = show["FCF"].map(lambda v: fmt_cr(v, plain=False))

    st.dataframe(
        style_dataframe(
            show,
            green_cols={"ROE", "Rev CAGR 5Y", "PAT CAGR 5Y", "OPM", "Composite", "Div Yield"},
            red_cols={"D/E"},
        ),
        hide_index=True,
        use_container_width=True,
        height=540,
        column_config={
            "Ticker": text_col("Ticker"),
            "Company": text_col("Company"),
            "Sector": text_col("Sector"),
            "Composite": number_col("Composite", digits=1),
            "ROE": percent_col("ROE"),
            "D/E": number_col("D/E", digits=2),
            "FCF": text_col("FCF"),
            "Rev CAGR 5Y": percent_col("Rev CAGR 5Y"),
            "PAT CAGR 5Y": percent_col("PAT CAGR 5Y"),
            "OPM": percent_col("OPM"),
            "P/E": ratio_col("P/E"),
            "P/B": ratio_col("P/B", digits=1),
            "Div Yield": percent_col("Div Yield"),
            "ICR": number_col("ICR", digits=2),
        },
    )

    st.download_button(
        label="Export Results (CSV)",
        data=_csv(show),
        file_name="screener_results.csv",
        mime="text/csv",
        use_container_width=True,
    )

    app_stamp()
