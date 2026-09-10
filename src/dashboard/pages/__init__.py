"""Dashboard page registry.

Each screen lives in a numeric-prefixed module ``01_home.py`` … ``08_reports.py``
per the spec's ``pages/`` directory layout (so native Streamlit multi-page
mode also works when ``pages/`` is placed under the dashboard root). This
package re-exports each screen under a friendly alias so ``app.py`` can
dispatch without coupling to the file-numbering scheme.
"""

from __future__ import annotations

import importlib as _il
import sys as _sys
from types import ModuleType as _ModuleType


def _reexport(num: str, alias: str) -> _ModuleType:
    mod = _il.import_module(f"src.dashboard.pages.{num}_{alias}")
    _sys.modules[f"src.dashboard.pages.{alias}"] = mod
    return mod


home = _reexport("01", "home")
profile = _reexport("02", "profile")
screener = _reexport("03", "screener")
peers = _reexport("04", "peers")
trends = _reexport("05", "trends")
sectors = _reexport("06", "sectors")
capital = _reexport("07", "capital")
reports = _reexport("08", "reports")

__all__ = [
    "capital",
    "home",
    "peers",
    "profile",
    "reports",
    "screener",
    "sectors",
    "trends",
]
