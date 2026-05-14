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

"""Log parsers for C++ test frameworks.

Mirrors :mod:`swefficiency.harness.log_parsers` for the C++ pipeline. Every
parser returns the same shape — ``dict[test_name, TestStatus value]`` — so
downstream grading code can treat C++ and Python results interchangeably.

Supported parsers (Phase 1):

* GoogleTest JSON  (``--gtest_output=json``)
* GoogleTest XML   (``--gtest_output=xml``)
* GoogleTest stdout (no flag; regex parse of ``[ OK ] ... / [ FAILED ]``)
* CTest JUnit XML  (``ctest --output-junit``)
* CTest stdout     (``ctest`` summary line regex)
* Catch2 JUnit XML (``--reporter=junit --out=...``)
* Google Benchmark JSON (``--benchmark_format=json``)

Each parser is forgiving: malformed input yields ``{}`` so the caller can
fall back gracefully to a coarser parser (typically the stdout variant).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Callable

from swefficiency.harness.constants import TestStatus


# ---------------------------------------------------------------------------
# GoogleTest JSON.
#
# Schema (gtest 1.11+):
#
# {
#   "testsuites": [{
#     "name": "Suite",
#     "tests": int, "failures": int, "skipped": int, "time": float,
#     "testsuite": [{
#       "name": "Case", "classname": "Suite",
#       "status": "RUN"|"NOTRUN",
#       "result": "COMPLETED"|"SKIPPED"|"SUPPRESSED",
#       "failures": [...], "skipped": "reason"  (when present)
#     }]
#   }]
# }
# ---------------------------------------------------------------------------


def parse_log_gtest_json(log: str) -> dict[str, str]:
    """Parse a GoogleTest --gtest_output=json blob.

    Returns ``dict[<suite>.<name>, TestStatus.value]``. If ``log`` is not
    parseable JSON or doesn't match the expected schema, returns ``{}``.
    """
    test_status_map: dict[str, str] = {}
    try:
        data = json.loads(log)
    except (ValueError, TypeError):
        return test_status_map

    suites = data.get("testsuites") or []
    if not isinstance(suites, list):
        return test_status_map

    for suite in suites:
        if not isinstance(suite, dict):
            continue
        suite_name = suite.get("name", "")
        cases = suite.get("testsuite") or suite.get("testcases") or []
        if not isinstance(cases, list):
            continue
        for case in cases:
            if not isinstance(case, dict):
                continue
            case_name = case.get("name", "")
            classname = case.get("classname", suite_name)
            full_name = f"{classname}.{case_name}" if classname else case_name
            if not full_name or full_name == ".":
                continue

            status = case.get("status", "")
            result = case.get("result", "")
            failures = case.get("failures") or []
            skipped = case.get("skipped")

            if status == "NOTRUN" or result in ("SKIPPED", "SUPPRESSED") or skipped:
                test_status_map[full_name] = TestStatus.SKIPPED.value
            elif failures:
                test_status_map[full_name] = TestStatus.FAILED.value
            elif result == "COMPLETED" and status == "RUN":
                test_status_map[full_name] = TestStatus.PASSED.value
            else:
                test_status_map[full_name] = TestStatus.ERROR.value

    return test_status_map


# ---------------------------------------------------------------------------
# GoogleTest XML (and CTest JUnit XML — same JUnit schema).
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


def parse_log_gtest_xml(log: str) -> dict[str, str]:
    """Parse a GoogleTest --gtest_output=xml blob (JUnit-compatible)."""
    return _parse_junit_xml(log)


def parse_log_ctest_junit(log: str) -> dict[str, str]:
    """Parse a CTest --output-junit blob (same JUnit schema as gtest XML)."""
    return _parse_junit_xml(log)


# ---------------------------------------------------------------------------
# GoogleTest stdout — regex-based fallback.
#
# Per-test lines look like:
#   [ RUN      ] Suite.TestName
#   [       OK ] Suite.TestName (3 ms)
#   [  FAILED  ] Suite.TestName
#   [  SKIPPED ] Suite.TestName
#   [  DISABLED ] Suite.DISABLED_TestName
# ---------------------------------------------------------------------------


_GTEST_STDOUT_LINE_RE = re.compile(
    r"^\[\s+(RUN|OK|FAILED|SKIPPED|DISABLED|PASSED)\s+\]\s+(\S+\.\S+)"
)


def parse_log_gtest_stdout(log: str) -> dict[str, str]:
    """Parse plain GoogleTest stdout into the test_name → status map."""
    test_status_map: dict[str, str] = {}
    if not log:
        return test_status_map
    for line in log.splitlines():
        m = _GTEST_STDOUT_LINE_RE.match(line)
        if not m:
            continue
        verb, full_name = m.group(1), m.group(2)
        if verb == "OK" or verb == "PASSED":
            test_status_map[full_name] = TestStatus.PASSED.value
        elif verb == "FAILED":
            test_status_map[full_name] = TestStatus.FAILED.value
        elif verb in ("SKIPPED", "DISABLED"):
            test_status_map[full_name] = TestStatus.SKIPPED.value
        elif verb == "RUN":
            test_status_map.setdefault(full_name, TestStatus.ERROR.value)
    return test_status_map


# ---------------------------------------------------------------------------
# CTest stdout — summary lines.
#
# Per-test lines look like:
#   Test #12: my.test ........................   Passed   0.04 sec
#   Test  #1: foo.test .......................***Failed  0.02 sec
#   Test  #5: baz.test ......................   Skipped
# ---------------------------------------------------------------------------


_CTEST_STDOUT_LINE_RE = re.compile(
    r"^\s*Test\s+#\d+:\s+(\S+)\s+\.+\s*(\*\*\*)?\s*(Passed|Failed|Skipped|Timeout|Not Run)",
    re.IGNORECASE,
)


def parse_log_ctest_stdout(log: str) -> dict[str, str]:
    """Parse plain CTest stdout into the test_name → status map."""
    test_status_map: dict[str, str] = {}
    if not log:
        return test_status_map
    for line in log.splitlines():
        m = _CTEST_STDOUT_LINE_RE.match(line)
        if not m:
            continue
        name, status = m.group(1), m.group(3).lower()
        if status == "passed":
            test_status_map[name] = TestStatus.PASSED.value
        elif status == "failed" or status == "timeout":
            test_status_map[name] = TestStatus.FAILED.value
        elif status == "skipped" or status == "not run":
            test_status_map[name] = TestStatus.SKIPPED.value
    return test_status_map


# ---------------------------------------------------------------------------
# Catch2 JUnit XML — same JUnit schema as gtest XML.
#
# Catch2 also emits a native XML reporter, but Catch2 v3's `junit` reporter
# is byte-for-byte JUnit compatible. We keep a thin alias so callers can
# select by intent.
# ---------------------------------------------------------------------------


def parse_log_catch2_junit(log: str) -> dict[str, str]:
    """Parse a Catch2 --reporter=junit blob."""
    return _parse_junit_xml(log, default_classname="Catch2")


def parse_log_catch2_xml(log: str) -> dict[str, str]:
    """Parse Catch2's native XML reporter (different from JUnit).

    Native schema:
      <Catch>
        <Group name="...">
          <TestCase name="..." filename="..." line="...">
            <Section name="...">[...]<Result type="..."/></Section>
            <OverallResult success="true|false"/>
          </TestCase>
        </Group>
      </Catch>
    """
    test_status_map: dict[str, str] = {}
    if not log:
        return test_status_map
    try:
        root = ET.fromstring(log)
    except ET.ParseError:
        return test_status_map

    if root.tag not in ("Catch", "Catch2TestRun"):
        return _parse_junit_xml(log, default_classname="Catch2")

    for testcase in root.iter("TestCase"):
        name = testcase.attrib.get("name", "")
        if not name:
            continue
        overall = testcase.find("OverallResult")
        if overall is None:
            test_status_map[name] = TestStatus.ERROR.value
            continue
        success = overall.attrib.get("success", "").lower()
        skips = testcase.findall(".//Skip")
        if skips:
            test_status_map[name] = TestStatus.SKIPPED.value
        elif success == "true":
            test_status_map[name] = TestStatus.PASSED.value
        else:
            test_status_map[name] = TestStatus.FAILED.value

    return test_status_map


# ---------------------------------------------------------------------------
# Google Benchmark JSON.
#
# Schema (Google Benchmark 1.5+):
#
# {
#   "context": {...},
#   "benchmarks": [
#     {
#       "name": "BM_Foo/8",
#       "run_type": "iteration"|"aggregate",
#       "aggregate_name": "mean"|"median"|"stddev"|"cv"  (only when run_type==aggregate),
#       "iterations": int,
#       "real_time": float, "cpu_time": float,
#       "time_unit": "ns"|"us"|"ms"|"s",
#       "threads": int
#     }, ...
#   ]
# }
#
# Benchmarks aren't really "tests" in the pass/fail sense — every run that
# completes counts as PASSED. We surface them so workload-level eval and
# perf-significance filtering can see the same name-keyed view as tests.
# ---------------------------------------------------------------------------


def parse_log_google_benchmark_json(log: str) -> dict[str, str]:
    """Parse a Google Benchmark --benchmark_format=json blob.

    Treats every completed iteration as PASSED. Aggregate rows are
    deliberately ignored so we don't double-count the same logical run.
    """
    test_status_map: dict[str, str] = {}
    try:
        data = json.loads(log)
    except (ValueError, TypeError):
        return test_status_map
    benchmarks = data.get("benchmarks")
    if not isinstance(benchmarks, list):
        return test_status_map
    for bench in benchmarks:
        if not isinstance(bench, dict):
            continue
        name = bench.get("name", "")
        if not name:
            continue
        if bench.get("run_type") == "aggregate":
            continue
        if bench.get("error_occurred"):
            test_status_map[name] = TestStatus.ERROR.value
        else:
            test_status_map[name] = TestStatus.PASSED.value
    return test_status_map


# ---------------------------------------------------------------------------
# Composite "best-effort" parser.
#
# For repos where we don't know which output format will land (CI tools
# sometimes mix gtest output with ctest summaries), try JSON → JUnit XML →
# stdout regexes in order and merge results. Later parsers don't overwrite
# earlier ones, matching the precedence "JSON wins if present".
# ---------------------------------------------------------------------------


def parse_log_cpp_best_effort(log: str) -> dict[str, str]:
    """Try every supported parser; return the union of their successes."""
    result: dict[str, str] = {}
    for parser in (
        parse_log_gtest_json,
        parse_log_gtest_xml,
        parse_log_ctest_junit,
        parse_log_catch2_junit,
        parse_log_catch2_xml,
        parse_log_google_benchmark_json,
        parse_log_ctest_stdout,
        parse_log_gtest_stdout,
    ):
        try:
            partial = parser(log) or {}
        except Exception:
            partial = {}
        for k, v in partial.items():
            result.setdefault(k, v)
    return result


MAP_REPO_TO_PARSER_CPP: dict[str, Callable[[str], dict[str, str]]] = {
    "fmtlib/fmt": parse_log_ctest_junit,
    "gabime/spdlog": parse_log_catch2_junit,
    "nlohmann/json": parse_log_ctest_junit,
    "abseil/abseil-cpp": parse_log_gtest_json,
    "ericniebler/range-v3": parse_log_catch2_junit,
    "eigen-mirror/eigen": parse_log_ctest_junit,
}


LOWER_MAP_REPO_TO_PARSER_CPP = {k.lower(): v for k, v in MAP_REPO_TO_PARSER_CPP.items()}


class _ParserMapWithFallbackCpp(dict):
    def __missing__(self, key):
        return parse_log_cpp_best_effort


MAP_REPO_TO_PARSER_CPP = _ParserMapWithFallbackCpp(LOWER_MAP_REPO_TO_PARSER_CPP)
