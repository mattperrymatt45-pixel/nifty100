"""Tests for the Day 22 Streamlit dashboard scaffold."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _install_noop_cache():
    """Replace st.cache_data with a no-op decorator for offline testing."""
    import streamlit as st

    def _no_cache(ttl=None, **_kw):
        def _wrap(fn):
            return fn

        return _wrap

    st.cache_data = _no_cache


class _DummyConn:
    """A stand-in for st.connection('sql') that reads from the real SQLite."""

    def __init__(self) -> None:
        from sqlalchemy import create_engine

        db_path = str(PROJECT_ROOT / "db" / "nifty100.db")
        self._eng = create_engine(f"sqlite:///{db_path}")

    def query(self, query: str, params: dict | None = None, ttl=None) -> pd.DataFrame:
        with self._eng.connect() as conn:
            return pd.read_sql(query, conn, params=params or {})


@pytest.fixture(scope="module", autouse=True)
def _prod_db_env():
    """Point settings at the production DB before any dashboard imports."""
    import os

    os.environ["NIFTY100_DB_PATH"] = str(PROJECT_ROOT / "db" / "nifty100.db")
    from src.utils.config import settings

    object.__setattr__(settings, "DB_PATH", PROJECT_ROOT / "db" / "nifty100.db")
    _install_noop_cache()
    import streamlit as st

    with patch.object(st, "connection", return_value=_DummyConn()):
        yield


# ---------------------------------------------------------------------------
# Module import smoke tests (8 screens + app + db utils)
# ---------------------------------------------------------------------------
PAGE_MODULES = [
    "src.dashboard.pages.home",
    "src.dashboard.pages.profile",
    "src.dashboard.pages.screener",
    "src.dashboard.pages.peers",
    "src.dashboard.pages.trends",
    "src.dashboard.pages.sectors",
    "src.dashboard.pages.capital",
    "src.dashboard.pages.reports",
]


@pytest.mark.parametrize("modname", [*PAGE_MODULES, "src.dashboard.app", "src.dashboard.utils.db"])
def test_module_imports(modname: str) -> None:
    """Every dashboard module imports cleanly under no-op cache."""
    importlib.import_module(modname)


@pytest.mark.parametrize("modname", PAGE_MODULES)
def test_page_module_exposes_render(modname: str) -> None:
    """Each page module must expose a render() callable."""
    mod = importlib.import_module(modname)
    assert callable(getattr(mod, "render", None)), f"{modname} missing render()"


def test_app_registers_eight_pages() -> None:
    """The app PAGES registry must contain exactly the 8 Day-22 screens."""
    from src.dashboard import app

    assert len(app.PAGES) == 8
    expected = {
        "Home",
        "Company Profile",
        "Screener",
        "Peer Comparison",
        "Trends",
        "Sectors",
        "Capital Allocation",
        "Reports",
    }
    labels = {k.split(" ", 1)[1] for k in app.PAGES}
    assert expected == labels


# ---------------------------------------------------------------------------
# db.py query function contract
# ---------------------------------------------------------------------------
REQUIRED_QUERIES = [
    "get_companies",
    "get_ratios",
    "get_pl",
    "get_bs",
    "get_cf",
    "get_sectors",
    "get_peers",
    "get_valuation",
    "get_peer_groups",
    "get_latest_ratios",
    "get_peer_percentiles",
    "run_sql",
    "invalidate_cache",
]


@pytest.mark.parametrize("fn_name", REQUIRED_QUERIES)
def test_db_module_exposes_function(fn_name: str) -> None:
    """db.py must expose every documented query helper."""
    from src.dashboard.utils import db

    assert callable(getattr(db, fn_name, None)), f"db.{fn_name} missing"


def test_get_companies_returns_full_universe() -> None:
    from src.dashboard.utils import db

    df = db.get_companies()
    assert len(df) == 92
    assert "ticker" in df.columns
    assert "company_name" in df.columns
    assert "broad_sector" in df.columns


def test_get_ratios_tcs_history() -> None:
    from src.dashboard.utils import db

    df = db.get_ratios("TCS")
    assert len(df) >= 5
    assert "return_on_equity_pct" in df.columns


def test_get_ratios_specific_year() -> None:
    from src.dashboard.utils import db

    df = db.get_ratios("TCS", year="2024-03")
    assert len(df) == 1
    assert df.iloc[0]["company_id"] == "TCS"


def test_get_pl_bs_cf_return_history() -> None:
    from src.dashboard.utils import db

    assert len(db.get_pl("TCS")) >= 5
    assert len(db.get_bs("TCS")) >= 5
    assert len(db.get_cf("TCS")) >= 5


def test_get_sectors_covers_all_companies() -> None:
    from src.dashboard.utils import db

    df = db.get_sectors()
    assert len(df) == 92


def test_get_peer_groups_returns_11_groups() -> None:
    from src.dashboard.utils import db

    df = db.get_peer_groups()
    assert len(df) == 11
    assert set(df["peer_group_name"]) == {
        "Automobiles",
        "Consumer Finance",
        "FMCG",
        "IT Services",
        "Life Insurance",
        "Oil & Gas",
        "Pharmaceuticals",
        "Power & Utilities",
        "Private Banks",
        "Public Banks",
        "Steel & Metals",
    }


def test_get_peers_it_services_membership() -> None:
    from src.dashboard.utils import db

    df = db.get_peers("IT Services")
    assert set(df["ticker"]) == {"TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"} or set(
        df["ticker"]
    ) == {"TCS", "INFY", "HCLTECH", "LTIM", "TECHM"}


def test_get_valuation_includes_fcf_yield() -> None:
    from src.dashboard.utils import db

    df = db.get_valuation("TCS")
    assert "fcf_yield_pct" in df.columns
    assert "pe_ratio" in df.columns
    assert len(df) >= 1


def test_invalidate_cache_runs_without_error() -> None:
    from src.dashboard.utils import db

    # Should not raise even under the no-op cache mock
    db.invalidate_cache()


# ---------------------------------------------------------------------------
# Streamlit page config (must be present in app.py source)
# ---------------------------------------------------------------------------
def test_app_sets_page_config_wide_layout() -> None:
    """app.py must set page config to wide layout with the right title."""
    app_src = (PROJECT_ROOT / "src" / "dashboard" / "app.py").read_text()
    assert 'page_title="Nifty 100 Analytics"' in app_src
    assert 'layout="wide"' in app_src
    assert 'initial_sidebar_state="expanded"' in app_src


def test_pages_directory_has_eight_files() -> None:
    pages_dir = PROJECT_ROOT / "src" / "dashboard" / "pages"
    files = sorted(p.name for p in pages_dir.glob("[0-9][0-9]_*.py"))
    assert files == [
        "01_home.py",
        "02_profile.py",
        "03_screener.py",
        "04_peers.py",
        "05_trends.py",
        "06_sectors.py",
        "07_capital.py",
        "08_reports.py",
    ]
