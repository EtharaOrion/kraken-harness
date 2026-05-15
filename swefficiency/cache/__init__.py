"""Persistent caches for SWE-fficiency pipeline.

Currently exposes :class:`SqliteKVCache` and a singleton accessor
:func:`get_default_cache` for sharing detection results across runs and
across worker processes.
"""

from swefficiency.cache.sqlite_cache import (
    NS_REPO_SPECS,
    NS_VERSION,
    SqliteKVCache,
    get_default_cache,
)

__all__ = [
    "NS_REPO_SPECS",
    "NS_VERSION",
    "SqliteKVCache",
    "get_default_cache",
]
