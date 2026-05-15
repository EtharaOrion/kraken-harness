# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""C++ pipeline cache namespaces + dedicated DB accessor.

Mirrors :mod:`swefficiency.cache.sqlite_cache` for the C++ pipeline. We do
NOT modify ``sqlite_cache.py`` or ``cache/__init__.py`` (shared with the
Python harness — see project requirement that cpp lives in ``*_cpp.py``).

The :class:`~swefficiency.cache.sqlite_cache.SqliteKVCache` backend is
generic infrastructure; this module reuses it via import (cpp depending on
Python infra is safe — the inverse is what we forbid). A separate DB file
(``cache_cpp.db``) keeps cpp/python keyspaces fully isolated on disk too,
even though the namespace prefixes (``NS_VERSION_CPP``,
``NS_REPO_SPECS_CPP``) already prevent in-DB collision.

Public API:
    NS_VERSION_CPP, NS_REPO_SPECS_CPP   — namespace constants
    get_default_cache_cpp()             — process-wide singleton accessor
    reset_default_cache_cpp()           — test helper

Environment overrides (mirroring the shared module):
    SWEFF_DISABLE_CACHE       — bypass cache entirely (callers handle None)
    SWEFF_CACHE_DB_CPP        — explicit cpp DB path (highest priority)
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
NS_VERSION_CPP = "version_cpp"
NS_REPO_SPECS_CPP = "repo_specs_cpp"

__all__ = [
    "NS_VERSION_CPP",
    "NS_REPO_SPECS_CPP",
    "get_default_cache_cpp",
    "reset_default_cache_cpp",
]


_DEFAULT_CACHE: Optional[SqliteKVCache] = None
_DEFAULT_CACHE_LOCK = threading.Lock()


def _default_db_path_cpp() -> Path:
    """Resolve the default cpp cache DB path.

    Resolution order:
      1. ``SWEFF_CACHE_DB_CPP`` env (explicit override)
      2. Sibling of ``SWEFF_CACHE_DB`` if set (replaces ``cache.db`` -> ``cache_cpp.db``)
      3. ``$XDG_CACHE_HOME/swefficiency/cache_cpp.db``
      4. ``~/.cache/swefficiency/cache_cpp.db``
    """
    if "SWEFF_CACHE_DB_CPP" in os.environ:
        return Path(os.environ["SWEFF_CACHE_DB_CPP"]).expanduser()
    py_db = os.environ.get("SWEFF_CACHE_DB")
    if py_db:
        py_path = Path(py_db).expanduser()
        return py_path.with_name(py_path.stem + "_cpp" + py_path.suffix)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "swefficiency" / "cache_cpp.db"
    return Path.home() / ".cache" / "swefficiency" / "cache_cpp.db"


def get_default_cache_cpp() -> SqliteKVCache:
    """Return a process-wide singleton :class:`SqliteKVCache` for the cpp pipeline.

    Uses double-checked locking so multiple threads racing here observe the
    same instance. Subsequent forks will see this instance via the standard
    backend's per-thread/per-process connection discipline.
    """
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        with _DEFAULT_CACHE_LOCK:
            if _DEFAULT_CACHE is None:
                _DEFAULT_CACHE = SqliteKVCache(_default_db_path_cpp())
    return _DEFAULT_CACHE


def reset_default_cache_cpp() -> None:
    """Test helper: drop the singleton (does not delete the DB file)."""
    global _DEFAULT_CACHE
    with _DEFAULT_CACHE_LOCK:
        if _DEFAULT_CACHE is not None:
            try:
                _DEFAULT_CACHE.close()
            except Exception:
                pass
        _DEFAULT_CACHE = None
