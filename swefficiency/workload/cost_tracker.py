# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Persistent USD cost tracker with hard cap for LLM-driven runs.

A 10k-instance workload generation pass can cost $300-$1500. Without a hard
cap, a misconfigured retry loop can blow that out to four figures unnoticed.
This module gives the caller two guarantees:

* :meth:`CostTracker.add` raises :class:`CostLimitExceeded` once the running
  total would cross the cap, so the calling code can abort the worker pool.
* The running total is flushed to a JSON file after every increment, so
  resumed runs pick up the prior total instead of starting at $0.

Typical use::

    from swefficiency.workload.cost_tracker import (
        CostTracker, CostLimitExceeded,
    )

    tracker = CostTracker.for_run(run_id="2026-05-14-glm5")
    try:
        tracker.add(0.07)
    except CostLimitExceeded:
        logger.error("Budget hit, aborting")
        raise

Env vars:
    SWEFF_LLM_COST_CAP_USD   Hard ceiling. Default: unlimited (no cap).
    SWEFF_COST_STATE_DIR     Directory for persisted cost state JSON.
                             Default: ``artifacts/cost_state/``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CostLimitExceeded(RuntimeError):
    """Raised when an ``add()`` would push the total over the configured cap."""

    def __init__(self, total: float, cap: float, attempted: float) -> None:
        super().__init__(
            f"Cost cap exceeded: would spend ${total:.4f} (cap=${cap:.4f}, "
            f"this call=${attempted:.4f})"
        )
        self.total = total
        self.cap = cap
        self.attempted = attempted


def _default_state_dir() -> Path:
    raw = os.environ.get("SWEFF_COST_STATE_DIR")
    if raw:
        return Path(raw)
    return Path("artifacts/cost_state")


def _env_cap_usd() -> Optional[float]:
    raw = os.environ.get("SWEFF_LLM_COST_CAP_USD")
    if raw is None or raw == "":
        return None
    try:
        cap = float(raw)
    except ValueError:
        logger.warning("Invalid SWEFF_LLM_COST_CAP_USD=%r, treating as unlimited", raw)
        return None
    if cap <= 0:
        logger.warning(
            "SWEFF_LLM_COST_CAP_USD=%s is non-positive, treating as unlimited", raw
        )
        return None
    return cap


class CostTracker:
    """Thread-safe USD spend tracker with optional persistence and cap."""

    def __init__(
        self,
        *,
        cap_usd: Optional[float] = None,
        state_path: Optional[Path] = None,
        initial_total: float = 0.0,
    ) -> None:
        self.cap_usd = cap_usd
        self.state_path = state_path
        self._total = float(initial_total)
        self._calls = 0
        self._lock = threading.Lock()
        if self.state_path is not None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_run(
        cls,
        run_id: str,
        *,
        cap_usd: Optional[float] = None,
        state_dir: Optional[Path] = None,
    ) -> "CostTracker":
        """Construct a tracker whose state file is keyed by ``run_id``.

        Resumes from any existing state file under ``state_dir``. ``cap_usd``
        defaults to ``SWEFF_LLM_COST_CAP_USD`` env var (None = unlimited).
        """
        if cap_usd is None:
            cap_usd = _env_cap_usd()
        if state_dir is None:
            state_dir = _default_state_dir()
        safe_run_id = run_id.replace("/", "_").replace("\\", "_")
        state_path = state_dir / f"{safe_run_id}.json"
        initial_total = 0.0
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                initial_total = float(state.get("total_usd", 0.0))
                logger.info(
                    "Resuming cost tracker for %s: prior total $%.4f",
                    run_id, initial_total,
                )
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.warning(
                    "Could not load prior cost state %s: %s (starting fresh)",
                    state_path, e,
                )
        return cls(
            cap_usd=cap_usd,
            state_path=state_path,
            initial_total=initial_total,
        )

    @property
    def total(self) -> float:
        with self._lock:
            return self._total

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def add(self, cost_usd: float) -> float:
        """Add ``cost_usd`` to the running total. Returns the new total.

        Always commits the cost first (so accounting stays accurate even when
        a worker overruns the cap), THEN raises :class:`CostLimitExceeded` if
        a cap is set and the new total exceeds it. The caller should treat
        the exception as a signal to abort scheduling further work.
        """
        if cost_usd < 0:
            raise ValueError(f"cost_usd must be >= 0, got {cost_usd}")
        if cost_usd == 0:
            return self.total
        with self._lock:
            self._total += cost_usd
            self._calls += 1
            self._persist_locked()
            new_total = self._total
        if self.cap_usd is not None and new_total > self.cap_usd:
            raise CostLimitExceeded(
                total=new_total, cap=self.cap_usd, attempted=cost_usd,
            )
        return new_total

    def _persist_locked(self) -> None:
        if self.state_path is None:
            return
        state = {
            "total_usd": round(self._total, 6),
            "calls": self._calls,
            "cap_usd": self.cap_usd,
            "updated_at": time.time(),
        }
        try:
            tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            tmp.write_text(json.dumps(state))
            tmp.replace(self.state_path)
        except OSError as e:
            logger.warning("Failed to persist cost state to %s: %s", self.state_path, e)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_usd": round(self._total, 6),
                "calls": self._calls,
                "cap_usd": self.cap_usd,
                "remaining_usd": (
                    None if self.cap_usd is None else round(self.cap_usd - self._total, 6)
                ),
            }
