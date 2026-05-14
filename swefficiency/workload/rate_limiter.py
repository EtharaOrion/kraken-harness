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

"""Thread-safe token bucket for LLM request rate limiting.

Bedrock, Anthropic, and OpenAI all enforce per-minute request/token quotas.
A naive ThreadPoolExecutor with N workers will burst N concurrent calls at
startup and trip the quota immediately. This module gives each call site a
shared TokenBucket that smooths bursts to the steady-state rate.

Typical use:

    from swefficiency.workload.rate_limiter import get_default_bucket

    bucket = get_default_bucket()  # rate from env or default
    bucket.acquire()  # blocks until a token is available
    response = completion(...)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


_DEFAULT_RATE_PER_MIN = 60.0  # 1 req/sec — conservative default
_DEFAULT_BURST = 10           # short bursts allowed up to this many tokens


class TokenBucket:
    """Thread-safe token bucket.

    Tokens refill at ``rate_per_second`` until ``capacity`` is reached.
    ``acquire()`` blocks until a token is available (or ``timeout`` elapses,
    in which case it raises :class:`TimeoutError`).
    """

    def __init__(
        self,
        rate_per_second: float,
        capacity: float,
        *,
        initial_tokens: Optional[float] = None,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError(f"rate_per_second must be > 0, got {rate_per_second}")
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        self.rate = float(rate_per_second)
        self.capacity = float(capacity)
        self._tokens = float(initial_tokens) if initial_tokens is not None else float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_refill = now

    def acquire(self, n: float = 1.0, *, timeout: Optional[float] = None) -> None:
        """Block until ``n`` tokens are available.

        Raises :class:`TimeoutError` if ``timeout`` elapses first.
        """
        if n <= 0:
            return
        if n > self.capacity:
            raise ValueError(
                f"requested {n} tokens exceeds capacity {self.capacity}"
            )
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                self._refill_locked()
                if self._tokens >= n:
                    self._tokens -= n
                    return
                # Time until ``n`` tokens are available, given current state.
                missing = n - self._tokens
                wait_for = missing / self.rate
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"TokenBucket.acquire timed out after {timeout}s"
                        )
                    wait_for = min(wait_for, remaining)
                # Cap wait_for so we re-check periodically even if another
                # thread sneaks in. ``wait`` releases the lock while sleeping.
                self._cond.wait(timeout=max(wait_for, 0.01))

    def try_acquire(self, n: float = 1.0) -> bool:
        """Non-blocking variant. Returns True if tokens were consumed."""
        with self._lock:
            self._refill_locked()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    @property
    def available_tokens(self) -> float:
        with self._lock:
            self._refill_locked()
            return self._tokens


_DEFAULT_BUCKET: Optional[TokenBucket] = None
_DEFAULT_BUCKET_LOCK = threading.Lock()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, falling back to %s", name, raw, default)
        return default


def get_default_bucket() -> TokenBucket:
    """Return the process-wide default bucket, creating it on first call.

    Rate and burst are controlled by env vars:

    * ``SWEFF_LLM_RATE_PER_MIN`` — sustained requests per minute (default 60).
    * ``SWEFF_LLM_BURST``         — short-term burst capacity (default 10).
    """
    global _DEFAULT_BUCKET
    if _DEFAULT_BUCKET is not None:
        return _DEFAULT_BUCKET
    with _DEFAULT_BUCKET_LOCK:
        if _DEFAULT_BUCKET is None:
            rate_per_min = _env_float("SWEFF_LLM_RATE_PER_MIN", _DEFAULT_RATE_PER_MIN)
            burst = _env_float("SWEFF_LLM_BURST", _DEFAULT_BURST)
            _DEFAULT_BUCKET = TokenBucket(
                rate_per_second=rate_per_min / 60.0,
                capacity=burst,
            )
            logger.info(
                "Initialized default LLM rate limiter: %.2f req/min (burst=%.0f)",
                rate_per_min,
                burst,
            )
    return _DEFAULT_BUCKET


def reset_default_bucket() -> None:
    """Test helper. Drop the singleton so the next call picks up new env."""
    global _DEFAULT_BUCKET
    with _DEFAULT_BUCKET_LOCK:
        _DEFAULT_BUCKET = None
