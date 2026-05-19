# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""TS pipeline cache namespaces + dedicated DB accessor.

Mirrors :mod:`swefficiency.cache.sqlite_cache` for the TS pipeline. We do
NOT modify ``sqlite_cache.py`` or ``cache/__init__.py`` (shared with the
Python harness — see project requirement that ts lives in ``*_ts.py``).

The :class:`~swefficiency.cache.sqlite_cache.SqliteKVCache` backend is
generic infrastructure; this module reuses it via import (ts depending on
Python infra is safe — the inverse is what we forbid). A separate DB file
(``cache_ts.db``) keeps ts/python keyspaces fully isolated on disk too,
even though the namespace prefixes (``NS_VERSION_TS``,
``NS_REPO_SPECS_TS``) already prevent in-DB collision.

Public API:
    NS_VERSION_TS, NS_REPO_SPECS_TS   — namespace constants
    get_default_cache_ts()             — process-wide singleton accessor
    reset_default_cache_ts()           — test helper

Environment overrides (mirroring the shared module):
    SWEFF_DISABLE_CACHE       — bypass cache entirely (callers handle None)
    SWEFF_CACHE_DB_TS         — explicit ts DB path (highest priority)
    SWEFF_CACHE_DB            — falls back to a sibling of the python DB
    XDG_CACHE_HOME            — base for default location
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from swefficiency.cache.sqlite_cache import SqliteKVCache

# Cache namespaces (prefixes within the kv table). Keep distinct from the
# python NS_VERSION / NS_REPO_SPECS used by the Python harness so the two
# pipelines never collide on (namespace, key).
NS_VERSION_TS = "version_ts"
NS_REPO_SPECS_TS = "repo_specs_ts"

__all__ = [
    "NS_VERSION_TS",
    "NS_REPO_SPECS_TS",
    "get_default_cache_ts",
    "reset_default_cache_ts",
]


_DEFAULT_CACHE: Optional[SqliteKVCache] = None
_DEFAULT_CACHE_LOCK = threading.Lock()


def _default_db_path_ts() -> Path:
    """Resolve the default ts cache DB path.

    Resolution order:
      1. ``SWEFF_CACHE_DB_TS`` env (explicit override)
      2. Sibling of ``SWEFF_CACHE_DB`` if set (replaces ``cache.db`` -> ``cache_ts.db``)
      3. ``$XDG_CACHE_HOME/swefficiency/cache_ts.db``
      4. ``~/.cache/swefficiency/cache_ts.db``
    """
    if "SWEFF_CACHE_DB_TS" in os.environ:
        return Path(os.environ["SWEFF_CACHE_DB_TS"]).expanduser()
    py_db = os.environ.get("SWEFF_CACHE_DB")
    if py_db:
        py_path = Path(py_db).expanduser()
        return py_path.with_name(py_path.stem + "_ts" + py_path.suffix)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "swefficiency" / "cache_ts.db"
    return Path.home() / ".cache" / "swefficiency" / "cache_ts.db"


def get_default_cache_ts() -> SqliteKVCache:
    """Return a process-wide singleton :class:`SqliteKVCache` for the ts pipeline.

    Uses double-checked locking so multiple threads racing here observe the
    same instance. Subsequent forks will see this instance via the standard
    backend's per-thread/per-process connection discipline.
    """
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        with _DEFAULT_CACHE_LOCK:
            if _DEFAULT_CACHE is None:
                _DEFAULT_CACHE = SqliteKVCache(_default_db_path_ts())
    return _DEFAULT_CACHE


def reset_default_cache_ts() -> None:
    """Test helper: drop the singleton (does not delete the DB file)."""
    global _DEFAULT_CACHE
    with _DEFAULT_CACHE_LOCK:
        if _DEFAULT_CACHE is not None:
            try:
                _DEFAULT_CACHE.close()
            except Exception:
                pass
        _DEFAULT_CACHE = None
