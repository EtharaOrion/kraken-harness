"""Thread- and process-safe SQLite-backed key-value cache.

Used to persist expensive detection results (version lookups, repo spec
detection) across pipeline runs and across worker processes. The same DB
file can be safely opened by many processes thanks to WAL journaling +
SQLite's file-level locking.

Default location: ``$SWEFF_CACHE_DB`` or ``$XDG_CACHE_HOME/swefficiency/cache.db``
(falling back to ``~/.cache/swefficiency/cache.db``).

The cache is intentionally simple: a single ``kv`` table with
``(namespace, key)`` as primary key and a JSON-encoded value. Callers
choose namespaces; see :data:`NS_VERSION` and :data:`NS_REPO_SPECS`.

Multiprocessing notes:
- :class:`SqliteKVCache` is safe to share across threads in the same
  process (per-thread connections via ``threading.local``).
- After a fork, the singleton returned by :func:`get_default_cache` is
  inherited by the child; ``_conn`` detects the PID change and opens a
  fresh connection in the child rather than reusing the parent's file
  descriptor.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Namespace constants — keep stable; they end up as TEXT in the table.
NS_VERSION = "version"
NS_REPO_SPECS = "repo_specs"

_BUSY_TIMEOUT_MS = 30_000
_CONNECT_TIMEOUT_S = 30.0


def _default_db_path() -> Path:
    env = os.environ.get("SWEFF_CACHE_DB")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base).expanduser() / "swefficiency" / "cache.db"
    return Path.home() / ".cache" / "swefficiency" / "cache.db"


class SqliteKVCache:
    """Thread- and fork-safe (namespace, key) -> JSON value cache."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
        self._db_path = Path(db_path).expanduser() if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    @property
    def path(self) -> Path:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        pid = os.getpid()
        local_pid = getattr(self._local, "pid", None)
        if local_pid != pid:
            # Either first use in this thread, or we just woke up after a fork
            # and the inherited connection (if any) belongs to the parent.
            old = getattr(self._local, "conn", None)
            if old is not None and local_pid == pid:
                try:
                    old.close()
                except sqlite3.Error:
                    pass
            self._local.conn = None
            self._local.pid = pid

        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=_CONNECT_TIMEOUT_S,
                check_same_thread=False,
                isolation_level=None,  # autocommit
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            self._local.conn = conn
            self._ensure_schema(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kv (
                    namespace  TEXT NOT NULL,
                    key        TEXT NOT NULL,
                    value      TEXT NOT NULL,
                    fetched_at REAL NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
                """
            )
            self._schema_ready = True

    @staticmethod
    def _key_to_str(key: Any) -> str:
        if isinstance(key, str):
            return key
        if isinstance(key, (tuple, list)):
            # \x1f = ASCII Unit Separator — extremely unlikely in repo/commit strings
            return "\x1f".join("" if p is None else str(p) for p in key)
        return str(key)

    def get(
        self,
        namespace: str,
        key: Any,
        *,
        max_age_seconds: Optional[float] = None,
    ) -> Any:
        """Return cached value or ``None`` if missing/expired/corrupt."""
        kstr = self._key_to_str(key)
        try:
            row = self._conn().execute(
                "SELECT value, fetched_at FROM kv WHERE namespace = ? AND key = ?",
                (namespace, kstr),
            ).fetchone()
        except sqlite3.Error as exc:
            logger.warning("Cache read failed for %s/%s: %s", namespace, kstr, exc)
            return None
        if row is None:
            return None
        value_json, fetched_at = row
        if max_age_seconds is not None and (time.time() - float(fetched_at)) > max_age_seconds:
            return None
        try:
            return json.loads(value_json)
        except json.JSONDecodeError:
            logger.warning(
                "Cache value for %s/%s is malformed JSON; ignoring", namespace, kstr
            )
            return None

    def set(self, namespace: str, key: Any, value: Any) -> bool:
        """Store ``value`` (must be JSON-serializable). Returns success."""
        kstr = self._key_to_str(key)
        try:
            value_json = json.dumps(value)
        except (TypeError, ValueError) as exc:
            logger.warning("Skipping cache.set for %s/%s: %s", namespace, kstr, exc)
            return False
        try:
            self._conn().execute(
                "INSERT OR REPLACE INTO kv (namespace, key, value, fetched_at) "
                "VALUES (?, ?, ?, ?)",
                (namespace, kstr, value_json, time.time()),
            )
            return True
        except sqlite3.Error as exc:
            logger.warning("Cache write failed for %s/%s: %s", namespace, kstr, exc)
            return False

    def __contains__(self, ns_key: tuple[str, Any]) -> bool:
        namespace, key = ns_key
        return self.get(namespace, key) is not None

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._local.conn = None


_DEFAULT_CACHE: SqliteKVCache | None = None
_DEFAULT_LOCK = threading.Lock()


def get_default_cache() -> SqliteKVCache:
    """Return a process-wide singleton cache backed by the default DB.

    Returns the same instance per process; safe across forks because the
    underlying connection is re-opened lazily per-PID inside ``_conn``.
    """
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_CACHE is None:
                _DEFAULT_CACHE = SqliteKVCache()
    return _DEFAULT_CACHE


def reset_default_cache() -> None:
    """Drop the singleton (for tests)."""
    global _DEFAULT_CACHE
    with _DEFAULT_LOCK:
        if _DEFAULT_CACHE is not None:
            _DEFAULT_CACHE.close()
        _DEFAULT_CACHE = None
