"""Configuration constants for OpenHands inference mode.

Mirrors ``config.py`` / ``constants.py`` from openhands-benchmarks but
adapted for the official SWE-fficiency harness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# ── Docker images ──────────────────────────────────────────────────────
DOCKER_IMAGE_PREFIX: Final[str] = "ghcr.io/swefficiency/swefficiency-images"
EVAL_AGENT_SERVER_IMAGE: Final[str] = "ghcr.io/openhands/eval-agent-server"
DEFAULT_BUILD_TARGET: Final[str] = "source-minimal"

# ── Paths ──────────────────────────────────────────────────────────────
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SDK_ROOT: Final[Path] = REPO_ROOT / "vendor" / "software-agent-sdk"
DEFAULT_LOG_DIR: Final[Path] = REPO_ROOT / "logs" / "run_inference"

# ── Agent defaults ─────────────────────────────────────────────────────
DEFAULT_MAX_ITERATIONS: Final[int] = 500
DEFAULT_MAX_FAKE_RESPONSES: Final[int] = 10
CONVERSATION_TIMEOUT: Final[int] = 3600  # seconds

# ── Docker resource defaults ───────────────────────────────────────────
DEFAULT_NUM_WORKERS: Final[int] = 2
DEFAULT_CPUS_PER_WORKER: Final[int] = 4
DEFAULT_MEM_LIMIT: Final[str] = "32g"
DEFAULT_MEM_RESERVATION: Final[str] = "16g"
DEFAULT_CPUS_TO_SKIP: Final[int] = 4

# ── Git config (suppress advise noise inside containers) ───────────────
GIT_SETUP_COMMANDS: Final[list[str]] = [
    "git config --global core.pager ''",
    "git config --global advice.detachedHead false",
    "git config --global user.email 'evaluation@swefficiency.dev'",
    "git config --global user.name 'SWEfficiency Agent'",
]

# ── Environment setup commands ─────────────────────────────────────────
ENV_SETUP_COMMANDS: Final[list[str]] = [
    "export PIP_CACHE_DIR=~/.cache/pip",
]
