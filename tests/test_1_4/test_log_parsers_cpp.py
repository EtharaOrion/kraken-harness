# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for swefficiency.harness.log_parsers_cpp.

Covers parser-level schema contracts (each parser returns dict[str, TestStatus])
plus the best-effort composite and MAP_REPO_TO_PARSER_CPP registration.

Fixtures are hand-built from documented schemas (locked decision #8 in b15).
Real-world captures get added during the vertical slice once GoogleTest +
GoogleBenchmark binaries run.
"""
from __future__ import annotations

import json

import pytest

from swefficiency.harness.constants_cpp import TestStatus
from swefficiency.harness.log_parsers_cpp import (
    MAP_REPO_TO_PARSER_CPP,
    parse_log_catch2_xml,
    parse_log_cpp_best_effort,
    parse_log_ctest_junit,
    parse_log_google_benchmark_json,
    parse_log_gtest_json,
    parse_log_gtest_stdout,
    parse_log_gtest_xml,
)


# ---------------------------------------------------------------------------
# GTest JSON
# ---------------------------------------------------------------------------

def test_gtest_json_passed_and_failed():
    payload = json.dumps({
        "testsuites": [{
            "name": "MathSuite",
            "testsuite": [
                {"name": "adds", "classname": "MathSuite",
                 "status": "RUN", "result": "COMPLETED", "failures": []},
                {"name": "subs", "classname": "MathSuite",
                 "status": "RUN", "result": "COMPLETED",
                 "failures": [{"failure": "expected 1 got 2"}]},
            ],
        }],
    })
    out = parse_log_gtest_json(payload)
    assert out["MathSuite.adds"] == TestStatus.PASSED.value
    assert out["MathSuite.subs"] == TestStatus.FAILED.value


def test_gtest_json_skipped():
    payload = json.dumps({
        "testsuites": [{
            "name": "Suite",
            "testsuite": [
                {"name": "DISABLED_x", "classname": "Suite",
                 "status": "NOTRUN", "result": "SKIPPED", "failures": []},
            ],
        }],
    })
    out = parse_log_gtest_json(payload)
    assert out["Suite.DISABLED_x"] == TestStatus.SKIPPED.value


def test_gtest_json_invalid_returns_empty():
    assert parse_log_gtest_json("not json") == {}
    assert parse_log_gtest_json("") == {}


# ---------------------------------------------------------------------------
# GTest XML / JUnit
# ---------------------------------------------------------------------------

def test_gtest_xml_basic():
    xml = (
        '<testsuites>'
        '<testsuite name="S">'
        '<testcase name="t1" classname="S"/>'
        '<testcase name="t2" classname="S"><failure type="msg">boom</failure></testcase>'
        '<testcase name="t3" classname="S"><skipped message="x"/></testcase>'
        '</testsuite>'
        '</testsuites>'
    )
    out = parse_log_gtest_xml(xml)
    assert out["S.t1"] == TestStatus.PASSED.value
    assert out["S.t2"] == TestStatus.FAILED.value
    assert out["S.t3"] == TestStatus.SKIPPED.value


def test_ctest_junit_reuses_gtest_xml_schema():
    """CTest --output-junit emits the same JUnit format."""
    xml = (
        '<testsuites>'
        '<testsuite name="ct">'
        '<testcase name="alpha" classname="ct"/>'
        '<testcase name="beta" classname="ct"><failure/></testcase>'
        '</testsuite>'
        '</testsuites>'
    )
    out = parse_log_ctest_junit(xml)
    assert out["ct.alpha"] == TestStatus.PASSED.value
    assert out["ct.beta"] == TestStatus.FAILED.value


def test_gtest_xml_invalid_returns_empty():
    assert parse_log_gtest_xml("<<<bad") == {}


# ---------------------------------------------------------------------------
# GTest stdout
# ---------------------------------------------------------------------------

def test_gtest_stdout_pass_fail_skip():
    log = """
[==========] Running 3 tests from 1 test suite.
[ RUN      ] S.a
[       OK ] S.a (0 ms)
[ RUN      ] S.b
S.b: failure
[  FAILED  ] S.b (0 ms)
[ RUN      ] S.c
[  SKIPPED ] S.c (0 ms)
"""
    out = parse_log_gtest_stdout(log)
    assert out["S.a"] == TestStatus.PASSED.value
    assert out["S.b"] == TestStatus.FAILED.value
    assert out["S.c"] == TestStatus.SKIPPED.value


def test_gtest_stdout_empty():
    assert parse_log_gtest_stdout("") == {}


# ---------------------------------------------------------------------------
# Catch2 XML
# ---------------------------------------------------------------------------

def test_catch2_xml_basic():
    xml = (
        '<Catch>'
        '<TestCase name="passes" filename="t.cc">'
        '<OverallResult success="true"/>'
        '</TestCase>'
        '<TestCase name="fails" filename="t.cc">'
        '<OverallResult success="false"/>'
        '</TestCase>'
        '</Catch>'
    )
    out = parse_log_catch2_xml(xml)
    assert out["passes"] == TestStatus.PASSED.value
    assert out["fails"] == TestStatus.FAILED.value


def test_catch2_xml_invalid_returns_empty():
    assert parse_log_catch2_xml("not xml") == {}


# ---------------------------------------------------------------------------
# Google Benchmark JSON
# ---------------------------------------------------------------------------

def test_google_benchmark_json_iterations_pass():
    payload = json.dumps({
        "context": {},
        "benchmarks": [
            {"name": "BM_x/100", "run_type": "iteration", "real_time": 1.2,
             "cpu_time": 1.1, "time_unit": "ns", "iterations": 100},
            {"name": "BM_x/100", "run_type": "aggregate", "aggregate_name": "mean",
             "real_time": 1.2, "cpu_time": 1.1, "time_unit": "ns"},
        ],
    })
    out = parse_log_google_benchmark_json(payload)
    assert out.get("BM_x/100") == TestStatus.PASSED.value


def test_google_benchmark_invalid_returns_empty():
    assert parse_log_google_benchmark_json("nope") == {}


# ---------------------------------------------------------------------------
# Best-effort composite + map fallback
# ---------------------------------------------------------------------------

def test_best_effort_recognises_gtest_xml():
    xml = '<testsuites><testsuite name="s"><testcase name="t" classname="s"/></testsuite></testsuites>'
    out = parse_log_cpp_best_effort(xml)
    assert out["s.t"] == TestStatus.PASSED.value


def test_best_effort_falls_through_to_stdout():
    log = "[ RUN      ] S.a\n[       OK ] S.a (1 ms)\n"
    out = parse_log_cpp_best_effort(log)
    assert out["S.a"] == TestStatus.PASSED.value


def test_best_effort_empty():
    assert parse_log_cpp_best_effort("") == {}


def test_map_repo_to_parser_cpp_has_tier1_entries():
    """6 Tier-1 repos must be registered (locked decision: vertical slice scope)."""
    expected = {
        "fmtlib/fmt",
        "gabime/spdlog",
        "nlohmann/json",
        "abseil/abseil-cpp",
        "ericniebler/range-v3",
        "eigen-mirror/eigen",
    }
    assert expected.issubset(set(MAP_REPO_TO_PARSER_CPP.keys()))


def test_map_repo_to_parser_cpp_values_are_callable():
    for repo, fn in MAP_REPO_TO_PARSER_CPP.items():
        assert callable(fn), f"{repo} parser is not callable"
