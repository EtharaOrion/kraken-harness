"""Shared fixtures and configuration for Stage 6 test suite.

Tests for scripts/detect_repo_specs.py — auto-detection of repo build specifications.
"""

from __future__ import annotations

import logging
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Import setup: add scripts/ to path so we can import detect_repo_specs
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (  # noqa: E402
    _detect_log_parser_type,
    _parse_min_python,
    _parse_toml,
    _parse_toml_regex,
    _read_text,
    check_license,
    detect_all_specs,
    detect_install_cmd,
    detect_packages_source,
    detect_pre_install,
    detect_python_version,
    detect_test_cmd,
    detect_version,
    load_cache,
    load_instances,
    save_cache,
    validate_instances,
    write_jsonl,
    REQUIRED_ENRICHMENT_FIELDS,
)

# ---------------------------------------------------------------------------
# Logging — per-session file logger
# ---------------------------------------------------------------------------
log = logging.getLogger("stage6_tests")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_test_counts: dict[str, int] = {"passed": 0, "failed": 0}


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Print each test result as 'PASSED | test_name' or 'FAILED | test_name'."""
    if report.when == "call":
        status = "PASSED" if report.passed else "FAILED"
        print(f"\n{status} | {report.head_line}")
        if report.passed:
            _test_counts["passed"] += 1
        else:
            _test_counts["failed"] += 1
    elif report.when == "setup" and report.failed:
        print(f"\nFAILED | {report.head_line}")
        _test_counts["failed"] += 1


def pytest_terminal_summary(
    terminalreporter: Any,
    exitstatus: int,
    config: Any,
) -> None:
    """Print summary: 'X passed, Y failed out of Z tests'."""
    passed = _test_counts["passed"]
    failed = _test_counts["failed"]
    total = passed + failed
    terminalreporter.write_line("")
    terminalreporter.write_line(
        f"{passed} passed, {failed} failed out of {total} tests"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Fresh temporary directory simulating a repo checkout."""
    return tmp_path


@pytest.fixture
def make_pyproject(repo: Path):
    """Helper to write a pyproject.toml with given content."""
    def _make(content: str) -> Path:
        p = repo / "pyproject.toml"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p
    return _make


@pytest.fixture
def make_setup_py(repo: Path):
    """Helper to write a setup.py with given content."""
    def _make(content: str) -> Path:
        p = repo / "setup.py"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p
    return _make


@pytest.fixture
def make_setup_cfg(repo: Path):
    """Helper to write a setup.cfg with given content."""
    def _make(content: str) -> Path:
        p = repo / "setup.cfg"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p
    return _make


@pytest.fixture
def make_tox_ini(repo: Path):
    """Helper to write a tox.ini with given content."""
    def _make(content: str) -> Path:
        p = repo / "tox.ini"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p
    return _make


@pytest.fixture
def make_file(repo: Path):
    """Helper to write any file relative to repo root."""
    def _make(relpath: str, content: str) -> Path:
        p = repo / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p
    return _make


@pytest.fixture
def make_binary_file(repo: Path):
    """Helper to write a binary file relative to repo root."""
    def _make(relpath: str, data: bytes) -> Path:
        p = repo / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p
    return _make


@pytest.fixture
def empty_instance() -> dict[str, Any]:
    """A minimal SWEfficiencyInstance-like dict for testing."""
    return {
        "repo": "owner/repo",
        "instance_id": "test__1",
        "base_commit": "abc123def456",
    }


@pytest.fixture
def enriched_instance() -> dict[str, Any]:
    """A fully enriched instance with all required fields."""
    return {
        "repo": "owner/repo",
        "instance_id": "test__1",
        "base_commit": "abc123def456",
        "python_version": "3.10",
        "install_cmd": "pip install -e .",
        "test_cmd_override": "pytest {test_files}",
        "packages_source": "",
        "pip_packages": [],
        "pre_install_cmds": [],
        "reqs_paths": [],
        "env_yml_paths": [],
        "log_parser_type": "pytest",
    }
