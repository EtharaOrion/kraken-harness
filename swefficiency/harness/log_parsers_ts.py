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

"""Log parsers for TypeScript test frameworks.

Mirrors :mod:`swefficiency.harness.log_parsers` for the TypeScript pipeline.
Test parsers return the same shape — ``dict[test_name, TestStatus value]`` —
so downstream grading code can treat TypeScript and Python results
interchangeably.

Supported parsers (Phase 1):

* Vitest JSON reporter (``--reporter=json --outputFile.json=...``)
* Vitest JUnit XML reporter (``--reporter=junit --outputFile.junit=...``)
* Vitest bench JSON (``vitest bench --reporter=json``)

The bench parser deliberately diverges from the test-parser contract: it
returns ``list[tuple[name, mean_seconds, std_seconds]]`` so the workload
runner can emit the ``PERF_START`` / ``Mean:`` / ``Std Dev:`` / ``PERF_END``
sentinel block in SECONDS — Vitest reports milliseconds by default, so we
divide by 1000 at extraction time.

Each parser is forgiving: malformed input yields an empty result so the
caller can fall back gracefully to a coarser parser (typically JUnit XML
when JSON is absent).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Callable

from swefficiency.harness.constants import TestStatus


# ---------------------------------------------------------------------------
# Vitest JSON reporter.
#
# Schema (Vitest >= 1.x with --reporter=json):
#
# {
#   "testResults": [{
#     "assertionResults": [{
#       "fullName": "Suite > nested > test name",
#       "status": "passed"|"failed"|"skipped"|"pending"|"todo"
#     }, ...]
#   }, ...]
# }
# ---------------------------------------------------------------------------


def parse_log_vitest_json(log: str) -> dict[str, str]:
    """Parse a Vitest --reporter=json blob.

    Returns ``dict[<fullName>, TestStatus.value]``. If ``log`` is not
    parseable JSON or doesn't match the expected schema, returns ``{}``.
    """
    test_status_map: dict[str, str] = {}
    try:
        data = json.loads(log)
    except (ValueError, TypeError):
        return test_status_map

    results = data.get("testResults") or []
    if not isinstance(results, list):
        return test_status_map

    for file_result in results:
        if not isinstance(file_result, dict):
            continue
        assertions = file_result.get("assertionResults") or []
        if not isinstance(assertions, list):
            continue
        for case in assertions:
            if not isinstance(case, dict):
                continue
            full_name = case.get("fullName") or case.get("title") or ""
            if not full_name:
                continue
            status = (case.get("status") or "").lower()

            if status == "passed":
                test_status_map[full_name] = TestStatus.PASSED.value
            elif status == "failed":
                test_status_map[full_name] = TestStatus.FAILED.value
            elif status in ("skipped", "pending", "todo"):
                test_status_map[full_name] = TestStatus.SKIPPED.value
            else:
                test_status_map[full_name] = TestStatus.ERROR.value

    return test_status_map


# ---------------------------------------------------------------------------
# Vitest JUnit XML reporter (standard JUnit schema).
#
# Schema (JUnit):
#
# <testsuites>
#   <testsuite name="..." tests="..." failures="..." skipped="..." errors="..." time="...">
#     <testcase name="..." classname="..." time="...">
#       [<failure type="..." message="...">trace</failure>]
#       [<error type="..." message="...">trace</error>]
#       [<skipped message="..."/>]
#     </testcase>
#   </testsuite>
# </testsuites>
# ---------------------------------------------------------------------------


def _parse_junit_xml(log: str, *, default_classname: str = "") -> dict[str, str]:
    test_status_map: dict[str, str] = {}
    if not log:
        return test_status_map
    try:
        root = ET.fromstring(log)
    except ET.ParseError:
        return test_status_map

    if root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    elif root.tag == "testsuite":
        suites = [root]
    else:
        return test_status_map

    for suite in suites:
        suite_name = suite.attrib.get("name", default_classname)
        for case in suite.findall("testcase"):
            name = case.attrib.get("name", "")
            classname = case.attrib.get("classname", suite_name)
            full_name = (
                f"{classname}.{name}" if classname and name else (name or classname)
            )
            if not full_name:
                continue

            if case.find("failure") is not None:
                test_status_map[full_name] = TestStatus.FAILED.value
            elif case.find("error") is not None:
                test_status_map[full_name] = TestStatus.ERROR.value
            elif case.find("skipped") is not None:
                test_status_map[full_name] = TestStatus.SKIPPED.value
            else:
                test_status_map[full_name] = TestStatus.PASSED.value

    return test_status_map


def parse_log_vitest_junit(log: str) -> dict[str, str]:
    """Parse a Vitest --reporter=junit blob (JUnit-compatible)."""
    return _parse_junit_xml(log, default_classname="Vitest")


# ---------------------------------------------------------------------------
# Vitest bench JSON (tinybench underneath).
#
# Schema (vitest >= 1.x with `vitest bench --reporter=json`):
#
# {
#   "files": [{
#     "groups": [{
#       "benchmarks": [{
#         "name": "BenchName",
#         "result": {"mean": <ms>, "sd": <ms>, "hz": <ops/s>}
#       }, ...]
#     }, ...]
#   }, ...]
# }
#
# Vitest reports milliseconds by default; we convert to seconds at the
# extraction boundary so downstream perf sentinels stay in SECONDS exactly
# as the cpp pipeline's bench parser did.
# ---------------------------------------------------------------------------


_MS_TO_SECONDS = 1e-3


def parse_log_vitest_bench_json(log: str) -> list[tuple[str, float, float]]:
    """Parse a Vitest bench --reporter=json blob.

    Returns a list of ``(name, mean_seconds, std_seconds)`` tuples. If
    ``log`` is not parseable JSON or doesn't match the expected schema,
    returns ``[]``.
    """
    results: list[tuple[str, float, float]] = []
    try:
        data = json.loads(log)
    except (ValueError, TypeError):
        return results

    files = data.get("files") or []
    if not isinstance(files, list):
        return results

    def _take(bench: object) -> None:
        if not isinstance(bench, dict):
            return
        name = bench.get("name", "")
        if not name:
            return
        result = bench.get("result") if isinstance(bench.get("result"), dict) else {}
        mean_ms = result.get("mean") if result else None
        sd_ms = result.get("sd") if result else None
        if mean_ms is None:
            mean_ms = bench.get("mean")
        if sd_ms is None:
            sd_ms = bench.get("sd")
        if mean_ms is None or sd_ms is None:
            return
        try:
            mean_s = float(mean_ms) * _MS_TO_SECONDS
            std_s = float(sd_ms) * _MS_TO_SECONDS
        except (TypeError, ValueError):
            return
        results.append((name, mean_s, std_s))

    for file_entry in files:
        if not isinstance(file_entry, dict):
            continue
        for bench in file_entry.get("benchmarks") or []:
            _take(bench)
        for group in file_entry.get("groups") or []:
            if not isinstance(group, dict):
                continue
            for bench in group.get("benchmarks") or []:
                _take(bench)

    return results


# ---------------------------------------------------------------------------
# Perf sentinel block parser.
#
# Re-uses the regex from harness/test_spec.py's ``parse_perf_output`` so
# the TypeScript pipeline emits the exact same ``PERF_START:`` / ``Mean:``
# / ``Std Dev:`` / ``PERF_END:`` contract the Python pipeline already
# consumes downstream.
# ---------------------------------------------------------------------------


PERF_START_TAG = "PERF_START:"
PERF_END_TAG = "PERF_END:"

_PERF_SENTINEL_RE = re.compile(r"(?:Mean|Std\s*Dev):\s*([\S]+)")


def parse_perf_log_ts(log: str) -> tuple[float, float]:
    """Parse the ``PERF_START``/``PERF_END`` sentinel block.

    Returns ``(mean_seconds, std_seconds)``. Raises ``ValueError`` if the
    sentinels are missing — matching ``parse_perf_output`` in test_spec.py.
    """
    cleaned = "\n".join(
        l for l in log.splitlines() if not l.startswith("+")
    ) + "\n"

    start_index = cleaned.find(PERF_START_TAG)
    end_index = cleaned.find(PERF_END_TAG)
    if start_index == -1 or end_index == -1:
        raise ValueError("Perf tags not found in output.")

    perf_text = cleaned[start_index + len(PERF_START_TAG) : end_index]
    matches = _PERF_SENTINEL_RE.findall(perf_text)
    if len(matches) < 2:
        raise ValueError("Mean/Std Dev not found between perf sentinels.")
    return float(matches[0]), float(matches[1])


# ---------------------------------------------------------------------------
# Top-level convenience dispatchers.
#
# ``parse_test_log_ts`` tries JSON first (richer schema), then JUnit XML.
# Later parsers don't overwrite earlier ones, matching the precedence
# "JSON wins if present".
# ---------------------------------------------------------------------------


def parse_test_log_ts(log: str) -> dict[str, str]:
    """Best-effort Vitest test-log parser; tries JSON then JUnit XML."""
    result = parse_log_vitest_json(log)
    if result:
        return result
    return parse_log_vitest_junit(log)


def parse_log_ts_best_effort(log: str) -> dict[str, str]:
    """Try every supported test parser; return the union of their successes."""
    result: dict[str, str] = {}
    for parser in (
        parse_log_vitest_json,
        parse_log_vitest_junit,
    ):
        try:
            partial = parser(log) or {}
        except Exception:
            partial = {}
        for k, v in partial.items():
            result.setdefault(k, v)
    return result


# ---------------------------------------------------------------------------
# Repo → parser map (Phase 1 shortlist).
#
# Mirrors the ``_ParserMapWithFallback`` pattern from log_parsers_cpp.py so
# unknown repos fall through to the best-effort parser.
# ---------------------------------------------------------------------------


MAP_REPO_TO_PARSER_TS: dict[str, Callable[[str], dict[str, str]]] = {
    "lodash/lodash": parse_log_vitest_json,
    "axios/axios": parse_log_vitest_json,
    "expressjs/express": parse_log_vitest_json,
    "prettier/prettier": parse_log_vitest_json,
    "vitest-dev/vitest": parse_log_vitest_json,
    "microsoft/typescript": parse_log_vitest_json,
}


LOWER_MAP_REPO_TO_PARSER_TS = {k.lower(): v for k, v in MAP_REPO_TO_PARSER_TS.items()}


class _ParserMapWithFallbackTs(dict):
    def __missing__(self, key):
        return parse_log_ts_best_effort


MAP_REPO_TO_PARSER_TS = _ParserMapWithFallbackTs(LOWER_MAP_REPO_TO_PARSER_TS)
