"""Day 27 integration QA: render each page module against real DB data using
a Streamlit shim. Confirms no unhandled exceptions and covers 10 tickers
across sectors plus extreme-screener slider values."""

from __future__ import annotations

import os
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ["NIFTY100_DB_PATH"] = str(ROOT / "db" / "nifty100.db")
from src.utils.config import settings  # noqa: E402

object.__setattr__(settings, "DB_PATH", ROOT / "db" / "nifty100.db")


# ---------------------------------------------------------------------------
# Streamlit shim
# ---------------------------------------------------------------------------
class _Empty:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, n):
        def _noop(*a, **kw):
            return _Empty()

        return _noop

    def __call__(self, *a, **kw):
        return _Empty()

    def __iter__(self):
        return iter([])

    def __bool__(self):
        return False


class _Shim:
    def __init__(self):
        self.session_state: dict = {}

    def set_page_config(self, **kw):
        pass

    def title(self, *a, **kw):
        pass

    def caption(self, *a, **kw):
        pass

    def header(self, *a, **kw):
        pass

    def subheader(self, *a, **kw):
        pass

    def markdown(self, *a, **kw):
        pass

    def write(self, *a, **kw):
        pass

    def metric(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def success(self, *a, **kw):
        pass

    def divider(self, *a, **kw):
        pass

    def spinner(self, *a, **kw):
        @contextmanager
        def _ctx():
            yield

        return _ctx()

    def empty(self, *a, **kw):
        return _Empty()

    def container(self, *a, **kw):
        return _Empty()

    def columns(self, n, *a, **kw):
        if isinstance(n, (list, tuple)):
            return [_Empty() for _ in n]
        return [_Empty() for _ in range(n)]

    def tabs(self, names):
        return [_Empty() for _ in names]

    def expander(self, *a, **kw):
        @contextmanager
        def _ctx():
            yield _Empty()

        return _ctx()

    def form(self, *a, **kw):
        @contextmanager
        def _ctx():
            yield _Empty()

        return _ctx()

    def radio(self, *a, **kw):
        opts = kw.get("options", []) if not a else (a[1] if len(a) > 1 else [])
        return opts[0] if opts else None

    def selectbox(self, label, options, index=0, **kw):
        return options[index] if options and 0 <= index < len(options) else None

    def multiselect(self, label, options, default=None, max_selections=None, **kw):
        return default if default is not None else options[: min(2, len(options))]

    def slider(self, label, mn, mx, value=None, step=None, **kw):
        return value if value is not None else mn

    def text_input(self, *a, **kw):
        return kw.get("value", "")

    def number_input(self, *a, **kw):
        return kw.get("value", 0)

    def checkbox(self, *a, **kw):
        return False

    def button(self, *a, **kw):
        return False

    def download_button(self, *a, **kw):
        pass

    def dataframe(self, *a, **kw):
        pass

    def table(self, *a, **kw):
        pass

    def plotly_chart(self, fig, *a, **kw):
        pass

    def json(self, *a, **kw):
        pass

    def latex(self, *a, **kw):
        pass

    def code(self, *a, **kw):
        pass

    def rerun(self, *a, **kw):
        raise _Rerun()

    def stop(self, *a, **kw):
        pass

    class cache_data:
        def __init__(self, *a, **kw):
            pass

        def __call__(self, fn):
            return fn

    def connection(self, *a, **kw):
        return _SQLConn()

    @property
    def sidebar(self):
        return _SidebarShim()


class _SidebarShim(_Shim):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Rerun(Exception):
    pass


class _SQLConn:
    def __init__(self):
        from sqlalchemy import create_engine

        self._eng = create_engine(f"sqlite:///{ROOT / 'db' / 'nifty100.db'}")

    def query(self, query, params=None, ttl=None):
        with self._eng.connect() as c:
            return pd.read_sql(query, c, params=params or {})


def _install_shim() -> _Shim:
    shim = _Shim()
    sys.modules["streamlit"] = shim
    for m in list(sys.modules):
        if m.startswith("src.dashboard"):
            del sys.modules[m]
    import importlib

    import src.dashboard.app  # noqa: F401

    for mod in ("home", "profile", "screener", "peers", "trends", "sectors", "capital", "reports"):
        importlib.import_module(f"src.dashboard.pages.{mod}")
    importlib.import_module("src.dashboard.utils.db")
    return shim


def _render(page) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    try:
        page.render()
        return True, time.perf_counter() - t0, ""
    except Exception:
        return False, time.perf_counter() - t0, traceback.format_exc()


@pytest.fixture(scope="module")
def shim_and_pages():
    shim = _install_shim()
    from src.dashboard.pages import (
        capital,
        home,
        peers,
        profile,
        reports,
        screener,
        sectors,
        trends,
    )
    from src.dashboard.utils import db

    return (
        shim,
        dict(
            home=home,
            profile=profile,
            screener=screener,
            peers=peers,
            trends=trends,
            sectors=sectors,
            capital=capital,
            reports=reports,
        ),
        db,
    )


TEST_TICKERS = [
    "TCS",
    "HDFCBANK",
    "HINDUNILVR",
    "RELIANCE",
    "SUNPHARMA",
    "TATAMOTORS",
    "TATASTEEL",
    "JSWSTEEL",
    "HDFCLIFE",
    "ADANIGREEN",
]


def _pick_company(shim, target_label, pages):
    orig = shim.selectbox

    def _sb(label, options, index=0, **kw):
        if options and target_label in options:
            return target_label
        return orig(label, options, index=index, **kw)

    shim.selectbox = _sb
    try:
        ok, t, err = _render(pages["profile"])
        assert ok, f"Profile render failed: {err[:400]}"
        assert t < 3.0, f"Profile render took {t:.2f}s (budget <3s)"
    finally:
        shim.selectbox = orig


def test_all_screens_render_across_tickers(shim_and_pages):
    shim, pages, db = shim_and_pages
    failures = []

    ok, _, err = _render(pages["home"])
    if not ok:
        failures.append(f"home: {err[:300]}")

    companies = db.get_companies()
    labels = [f"{r['ticker']} - {r['company_name']}" for _, r in companies.iterrows()]

    for ticker in TEST_TICKERS:
        target = next((l for l in labels if l.startswith(f"{ticker} - ")), None)
        assert target, f"Ticker {ticker} missing from companies table"

        # Profile
        orig = shim.selectbox

        def _psb(label, options, index=0, **kw):
            return (
                target
                if (target and options and target in options)
                else orig(label, options, index=index, **kw)
            )

        shim.selectbox = _psb
        ok, t, err = _render(pages["profile"])
        shim.selectbox = orig
        if not ok:
            failures.append(f"profile/{ticker}: {err[:300]}")
        if t >= 3.0:
            failures.append(f"profile/{ticker}: slow {t:.2f}s")

        # Trends (override multiselect to fixed metric triple)
        om = shim.multiselect
        shim.multiselect = lambda *a, **k: ["Revenue (Cr)", "Net Profit (Cr)", "ROE %"]
        orig2 = shim.selectbox
        shim.selectbox = _psb
        ok, _, err = _render(pages["trends"])
        shim.selectbox = orig2
        shim.multiselect = om
        if not ok:
            failures.append(f"trends/{ticker}: {err[:300]}")

        # Reports
        orig2 = shim.selectbox
        shim.selectbox = _psb
        ok, _, err = _render(pages["reports"])
        shim.selectbox = orig2
        if not ok:
            failures.append(f"reports/{ticker}: {err[:300]}")

    # Screener with three slider settings
    for preset_name, preset in [
        ("default", None),
        (
            "loose",
            dict(
                roe_min=0.0,
                de_max=5.0,
                fcf_min=-20000.0,
                rev_cagr_min=-10.0,
                pat_cagr_min=-20.0,
                opm_min=0.0,
                pe_max=100.0,
                pb_max=20.0,
                div_yield_min=0.0,
                icr_min=0.0,
            ),
        ),
        (
            "tight",
            dict(
                roe_min=40.0,
                de_max=0.1,
                fcf_min=50000.0,
                rev_cagr_min=40.0,
                pat_cagr_min=50.0,
                opm_min=50.0,
                pe_max=5.0,
                pb_max=1.0,
                div_yield_min=10.0,
                icr_min=20.0,
            ),
        ),
    ]:
        shim.session_state.clear()
        if preset:
            shim.session_state.update(preset)
        ok, _, err = _render(pages["screener"])
        if not ok:
            failures.append(f"screener/{preset_name}: {err[:300]}")
    shim.session_state.clear()

    # Peers across all 11 groups
    groups = db.get_peer_groups()["peer_group_name"].tolist()
    for g in groups:
        orig = shim.selectbox
        state = {"n": 0}

        def _sb(label, options, index=0, **kw):
            if options and g in options:
                return g
            return options[0] if options else None

        shim.selectbox = _sb
        ok, _, err = _render(pages["peers"])
        shim.selectbox = orig
        if not ok:
            failures.append(f"peers/{g}: {err[:300]}")

    # Sectors
    ok, _, err = _render(pages["sectors"])
    if not ok:
        failures.append(f"sectors: {err[:300]}")

    # Capital
    ok, _, err = _render(pages["capital"])
    if not ok:
        failures.append(f"capital: {err[:300]}")

    assert not failures, "Render failures:\n" + "\n".join(failures)
