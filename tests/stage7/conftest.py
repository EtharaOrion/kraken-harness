from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

STAGE7_DIR = Path(__file__).resolve().parent
if str(STAGE7_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE7_DIR))

_test_counts: dict[str, int] = {"passed": 0, "failed": 0}


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
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
    passed = _test_counts["passed"]
    failed = _test_counts["failed"]
    total = passed + failed
    terminalreporter.write_line("")
    terminalreporter.write_line(
        f"{passed} passed, {failed} failed out of {total} tests"
    )
