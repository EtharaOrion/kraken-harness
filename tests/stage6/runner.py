#!/usr/bin/env python3
"""Stage 6 Test Runner — runs all test files, generates per-file logs, and a consolidated report.

Usage:
    python tests/stage6/runner.py                  # Run all tests
    python tests/stage6/runner.py -k test_python   # Filter by keyword
    python tests/stage6/runner.py --parallel       # Run in parallel (requires pytest-xdist)
    python tests/stage6/runner.py --verbose        # Verbose output
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STAGE6_DIR = Path(__file__).resolve().parent
LOGS_DIR = STAGE6_DIR / "logs"
PROJECT_ROOT = STAGE6_DIR.parent.parent


def discover_test_files() -> list[Path]:
    """Find all test_*.py files in the stage6 directory."""
    return sorted(STAGE6_DIR.glob("test_*.py"))


def run_single_test_file(
    test_file: Path,
    extra_args: list[str],
    verbose: bool = False,
) -> dict:
    """Run a single test file via pytest and capture results.

    Returns a dict with:
        file, passed, failed, errors, skipped, total, duration_s, log_path, returncode
    """
    log_file = LOGS_DIR / f"{test_file.stem}.log"

    cmd = [
        sys.executable, "-m", "pytest",
        str(test_file),
        f"--tb=short",
        f"--no-header",
        "-q",
    ]
    if verbose:
        cmd.append("-v")
    cmd.extend(extra_args)

    start = time.monotonic()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=600,
    )
    duration = time.monotonic() - start

    # Write log
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"# Test file: {test_file.name}\n")
        f.write(f"# Timestamp: {datetime.datetime.now().isoformat()}\n")
        f.write(f"# Duration:  {duration:.2f}s\n")
        f.write(f"# Return code: {result.returncode}\n")
        f.write(f"# Command: {' '.join(cmd)}\n")
        f.write("=" * 80 + "\n\n")
        f.write("--- STDOUT ---\n")
        f.write(result.stdout)
        f.write("\n--- STDERR ---\n")
        f.write(result.stderr)

    # Parse summary from pytest output
    counts = _parse_pytest_summary(result.stdout)

    return {
        "file": test_file.name,
        "passed": counts.get("passed", 0),
        "failed": counts.get("failed", 0),
        "errors": counts.get("errors", 0),
        "skipped": counts.get("skipped", 0),
        "total": sum(counts.values()),
        "duration_s": round(duration, 2),
        "log_path": str(log_file),
        "returncode": result.returncode,
    }


def _parse_pytest_summary(stdout: str) -> dict[str, int]:
    """Parse pytest short summary line.

    Handles both the custom format ('X passed, Y failed out of Z tests')
    and standard pytest format ('150 passed, 3 failed, 2 skipped in 4.52s').
    """
    import re
    counts: dict[str, int] = {}
    for line in reversed(stdout.strip().splitlines()):
        custom = re.match(
            r'\s*(\d+)\s+passed,\s+(\d+)\s+failed\s+out\s+of\s+(\d+)\s+tests',
            line,
        )
        if custom:
            counts["passed"] = int(custom.group(1))
            counts["failed"] = int(custom.group(2))
            break
        matches = re.findall(r'(\d+)\s+(passed|failed|error|skipped|warnings?|deselected)', line)
        if matches:
            for count_str, label in matches:
                key = label.rstrip("s")
                if key in ("warning", "deselected"):
                    continue
                if key == "error":
                    key = "errors"
                counts[key] = int(count_str)
            break
    return counts


def generate_consolidated_report(results: list[dict], duration_total: float) -> str:
    """Generate a consolidated report string."""
    lines: list[str] = []
    lines.append("=" * 90)
    lines.append("  STAGE 6 — SPEC AUTO-DETECTION TEST SUITE — CONSOLIDATED REPORT")
    lines.append(f"  Generated: {datetime.datetime.now().isoformat()}")
    lines.append("=" * 90)
    lines.append("")

    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    total_tests = sum(r["total"] for r in results)

    lines.append(f"  TOTAL TESTS:  {total_tests}")
    lines.append(f"  PASSED:       {total_passed}")
    lines.append(f"  FAILED:       {total_failed}")
    lines.append(f"  ERRORS:       {total_errors}")
    lines.append(f"  SKIPPED:      {total_skipped}")
    lines.append(f"  DURATION:     {duration_total:.2f}s")
    lines.append("")

    # Per-file table
    header = f"  {'File':<40} {'Pass':>6} {'Fail':>6} {'Err':>5} {'Skip':>6} {'Total':>6} {'Time':>8} {'Status':>8}"
    lines.append(header)
    lines.append("  " + "-" * 85)

    for r in results:
        status = "PASS" if r["returncode"] == 0 else "FAIL"
        lines.append(
            f"  {r['file']:<40} {r['passed']:>6} {r['failed']:>6} {r['errors']:>5} "
            f"{r['skipped']:>6} {r['total']:>6} {r['duration_s']:>7.2f}s {status:>8}"
        )

    lines.append("  " + "-" * 85)
    all_pass = all(r["returncode"] == 0 for r in results)
    verdict = "ALL PASS" if all_pass else "FAILURES DETECTED"
    lines.append(f"  VERDICT: {verdict}")
    lines.append("=" * 90)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 6 test suite runner")
    parser.add_argument("-k", "--keyword", default="", help="pytest -k filter")
    parser.add_argument("--parallel", action="store_true", help="Run with pytest-xdist")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose pytest output")
    parser.add_argument("--file", default="", help="Run specific test file only")
    args = parser.parse_args()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    test_files = discover_test_files()
    if args.file:
        test_files = [f for f in test_files if args.file in f.name]

    if not test_files:
        print("No test files found in", STAGE6_DIR)
        sys.exit(1)

    print(f"Found {len(test_files)} test file(s):")
    for f in test_files:
        print(f"  - {f.name}")
    print()

    extra_args: list[str] = []
    if args.keyword:
        extra_args.extend(["-k", args.keyword])
    if args.parallel:
        extra_args.extend(["-n", "auto"])

    results: list[dict] = []
    total_start = time.monotonic()

    for test_file in test_files:
        print(f"Running {test_file.name}...", end=" ", flush=True)
        r = run_single_test_file(test_file, extra_args, verbose=args.verbose)
        results.append(r)
        status = "PASS" if r["returncode"] == 0 else "FAIL"
        print(f"{status} ({r['passed']} passed, {r['failed']} failed, {r['total']} total, {r['duration_s']:.1f}s)")

    total_duration = time.monotonic() - total_start

    # Generate consolidated report
    report = generate_consolidated_report(results, total_duration)
    print("\n" + report)

    # Write consolidated log
    consolidated_log = LOGS_DIR / "consolidated.log"
    with open(consolidated_log, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nConsolidated log: {consolidated_log}")

    # Write JSON results
    json_report = LOGS_DIR / "results.json"
    with open(json_report, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.datetime.now().isoformat(),
            "total_tests": sum(r["total"] for r in results),
            "total_passed": sum(r["passed"] for r in results),
            "total_failed": sum(r["failed"] for r in results),
            "total_duration_s": round(total_duration, 2),
            "files": results,
        }, f, indent=2)
    print(f"JSON report: {json_report}")

    # Per-file logs listing
    print(f"\nPer-file logs in: {LOGS_DIR}/")
    for r in results:
        print(f"  - {Path(r['log_path']).name}")

    # Exit code
    any_failure = any(r["returncode"] != 0 for r in results)
    sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
