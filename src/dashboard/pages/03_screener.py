"""Screen 03 - Screener (Day 24).

10 metric sliders, 6 preset buttons, live-updating results table and
CSV download button.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from src.dashboard.utils.db import get_screener_dataset

# ---------------------------------------------------------------------------
# Preset thresholds (mirrors config/screener_config.yaml for dashboard use;
# kept local so the dashboard doesn't depend on the YAML loader at runtime).
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


def _init_state() -> None:
    """Seed session state with default slider values once per run."""
    for k, v in DEFAULT_FILTERS.items():
        st.session_state.setdefault(k, v)


def _preset_buttons() -> None:
    """Render the 6 preset buttons; clicking one resets slider state."""
    st.subheader("Presets")
    cols = st.columns(3)
    for i, name in enumerate(["Quality", "Value", "Growth", "Dividend", "Debt-Free", "Turnaround"]):
        with cols[i % 3]:
            if st.button(name, use_container_width=True, key=f"preset_{name}"):
                for k, v in PRESETS[name].items():
                    st.session_state[k] = v
                st.rerun()


def _sliders() -> dict[str, float]:
    """Render the 10 metric sliders in the sidebar, return current values."""
    with st.sidebar:
        st.divider()
        st.subheader("Screener Filters")

        roe_min = st.slider(
            "ROE min (%)", 0.0, 40.0, st.session_state.get("roe_min", 15.0), 0.5, key="roe_min"
        )
        de_max = st.slider(
            "D/E max", 0.0, 5.0, st.session_state.get("de_max", 1.0), 0.05, key="de_max"
        )
        fcf_min = st.slider(
            "FCF min (Cr)",
            -20000.0,
            50000.0,
            st.session_state.get("fcf_min", 0.0),
            500.0,
            key="fcf_min",
        )
        rev_cagr_min = st.slider(
            "Revenue CAGR 5y min (%)",
            -10.0,
            40.0,
            st.session_state.get("rev_cagr_min", 10.0),
            0.5,
            key="rev_cagr_min",
        )
        pat_cagr_min = st.slider(
            "PAT CAGR 5y min (%)",
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
    """Apply the slider filters to the screener dataset."""
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


def _csv(df: pd.DataFrame) -> str:
    """Convert result DataFrame to well-formed CSV (UTF-8, no index)."""
    return df.to_csv(index=False).encode("utf-8")


def render() -> None:
    """Render the Screener page."""
    st.title("Stock Screener")
    st.caption("Adjust sliders in the sidebar, or click a preset to auto-fill filters.")

    _init_state()
    filters = _sliders()
    _preset_buttons()

    df = get_screener_dataset()
    results = _apply_filters(df, filters)

    st.subheader(f"{len(results)} companies match your filters")

    if results.empty:
        st.warning("No companies match - widen the filters or try a preset.")
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
        "ROE %",
        "D/E",
        "FCF (Cr)",
        "Rev CAGR 5y %",
        "PAT CAGR 5y %",
        "OPM %",
        "P/E",
        "P/B",
        "Div Yield %",
        "ICR",
    ]
    for col in [
        "Composite",
        "ROE %",
        "D/E",
        "FCF (Cr)",
        "Rev CAGR 5y %",
        "PAT CAGR 5y %",
        "OPM %",
        "P/E",
        "P/B",
        "Div Yield %",
        "ICR",
    ]:
        show[col] = show[col].map(lambda v: round(float(v), 1) if pd.notna(v) else np.nan)

    st.dataframe(show, hide_index=True, use_container_width=True, height=520)

    st.download_button(
        label="Download results as CSV",
        data=_csv(show),
        file_name="screener_results.csv",
        mime="text/csv",
        use_container_width=True,
    )
