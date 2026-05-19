# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for swefficiency.harness.log_parsers_ts.

Covers parser-level schema contracts (each test parser returns
dict[str, TestStatus value]) plus the bench parser's milliseconds ->
seconds conversion and the PERF_START/PERF_END sentinel contract.

Fixtures are hand-built from documented Vitest schemas.
"""
from __future__ import annotations

import json

from swefficiency.harness.constants import TestStatus
from swefficiency.harness.log_parsers_ts import (
    MAP_REPO_TO_PARSER_TS,
    PERF_END_TAG,
    PERF_START_TAG,
    parse_log_ts_best_effort,
    parse_log_vitest_bench_json,
    parse_log_vitest_json,
    parse_log_vitest_junit,
    parse_perf_log_ts,
)


# ---------------------------------------------------------------------------
# Vitest JSON reporter
# ---------------------------------------------------------------------------

def test_vitest_json_passed_failed_skipped():
    payload = json.dumps({
        "testResults": [{
            "assertionResults": [
                {"fullName": "foo passes", "status": "passed"},
                {"fullName": "foo fails", "status": "failed"},
                {"fullName": "foo skipped", "status": "skipped"},
            ],
        }],
    })
    out = parse_log_vitest_json(payload)
    assert out["foo passes"] == TestStatus.PASSED.value
    assert out["foo fails"] == TestStatus.FAILED.value
    assert out["foo skipped"] == TestStatus.SKIPPED.value


def test_vitest_json_invalid_returns_empty():
    assert parse_log_vitest_json("not json") == {}
    assert parse_log_vitest_json("") == {}


# ---------------------------------------------------------------------------
# Vitest JUnit XML reporter
# ---------------------------------------------------------------------------

def test_vitest_junit_passed_failed_skipped():
    xml = (
        '<testsuites>'
        '<testsuite name="S">'
        '<testcase name="foo passes" classname="S"/>'
        '<testcase name="foo fails" classname="S">'
        '<failure type="AssertionError">boom</failure>'
        '</testcase>'
        '<testcase name="foo skipped" classname="S">'
        '<skipped message="x"/>'
        '</testcase>'
        '</testsuite>'
        '</testsuites>'
    )
    out = parse_log_vitest_junit(xml)
    assert out["S.foo passes"] == TestStatus.PASSED.value
    assert out["S.foo fails"] == TestStatus.FAILED.value
    assert out["S.foo skipped"] == TestStatus.SKIPPED.value


def test_vitest_junit_invalid_returns_empty():
    assert parse_log_vitest_junit("<<<bad") == {}
    assert parse_log_vitest_junit("") == {}


# ---------------------------------------------------------------------------
# Vitest bench JSON (milliseconds in, seconds out)
# ---------------------------------------------------------------------------

def test_vitest_bench_json_converts_ms_to_seconds():
    payload = json.dumps({
        "files": [{
            "groups": [{
                "benchmarks": [
                    {"name": "name", "result": {"mean": 12.5, "sd": 0.5}},
                ],
            }],
        }],
    })
    out = parse_log_vitest_bench_json(payload)
    assert out == [("name", 0.0125, 0.0005)]


def test_vitest_bench_json_real_vitest4_schema():
    payload = json.dumps({
        "files": [{
            "filepath": "/tmp/w/workload.bench.ts",
            "groups": [{
                "fullName": "workload.bench.ts > smoke",
                "benchmarks": [
                    {"name": "noop1", "mean": 0.213, "sd": 0.045, "hz": 4.7e6},
                    {"name": "noop2", "mean": 0.418, "sd": 3.75, "hz": 2.4e6},
                ],
            }],
        }],
    })
    out = parse_log_vitest_bench_json(payload)
    assert out == [
        ("noop1", 0.213 / 1000, 0.045 / 1000),
        ("noop2", 0.418 / 1000, 3.75 / 1000),
    ]


def test_vitest_bench_invalid_returns_empty():
    assert parse_log_vitest_bench_json("nope") == []
    assert parse_log_vitest_bench_json("") == []


# ---------------------------------------------------------------------------
# PERF sentinel block
# ---------------------------------------------------------------------------

def test_parse_perf_log_ts_reads_seconds():
    log = (
        "noise above\n"
        f"{PERF_START_TAG}\n"
        "Mean: 0.0125\n"
        "Std Dev: 0.0005\n"
        f"{PERF_END_TAG}\n"
        "noise below\n"
    )
    mean_s, std_s = parse_perf_log_ts(log)
    assert mean_s == 0.0125
    assert std_s == 0.0005


# ---------------------------------------------------------------------------
# Best-effort composite + repo map fallback
# ---------------------------------------------------------------------------

def test_best_effort_recognises_vitest_json():
    payload = json.dumps({
        "testResults": [{
            "assertionResults": [
                {"fullName": "foo passes", "status": "passed"},
            ],
        }],
    })
    out = parse_log_ts_best_effort(payload)
    assert out["foo passes"] == TestStatus.PASSED.value


def test_best_effort_falls_through_to_junit():
    xml = (
        '<testsuites>'
        '<testsuite name="S">'
        '<testcase name="foo passes" classname="S"/>'
        '</testsuite>'
        '</testsuites>'
    )
    out = parse_log_ts_best_effort(xml)
    assert out["S.foo passes"] == TestStatus.PASSED.value


def test_best_effort_empty():
    assert parse_log_ts_best_effort("") == {}


def test_map_repo_to_parser_ts_has_tier1_entries():
    expected = {
        "lodash/lodash",
        "axios/axios",
        "expressjs/express",
        "prettier/prettier",
        "vitest-dev/vitest",
        "microsoft/typescript",
    }
    assert expected.issubset(set(MAP_REPO_TO_PARSER_TS.keys()))


def test_map_repo_to_parser_ts_values_are_callable():
    for repo, fn in MAP_REPO_TO_PARSER_TS.items():
        assert callable(fn), f"{repo} parser is not callable"


def test_map_repo_to_parser_ts_unknown_falls_back():
    parser = MAP_REPO_TO_PARSER_TS["unknown/repo"]
    assert callable(parser)
    assert parser("") == {}
