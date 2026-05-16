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

"""Regression tests pinning the C++ harness correctness fixes.

Each test locks one previously-broken behavior so it cannot silently
regress: enrichment dataflow, resolution status on empty test lists,
empty-patch grading, sentinel-bounded perf parsing, the report improvement
sign, and the discovery token rotator.
"""

import pytest

from swefficiency.harness.constants import (
    FAIL_TO_PASS,
    KEY_INSTANCE_ID,
    PASS_TO_PASS,
    ResolvedStatus,
)


# --- enrichment dataflow ---------------------------------------------------

def test_synthesize_specs_reads_top_level_fields():
    """detect_repo_specs_cpp writes enrichment to the instance top level;
    _synthesize_specs_cpp must pick it up (it used to look only for a
    non-existent 'repo_specs' subkey, so every repo fell back to defaults)."""
    from swefficiency.harness.dynamic_specs_cpp import _synthesize_specs_cpp

    specs = _synthesize_specs_cpp({
        "repo": "unknown/repo",
        "base_commit": "deadbeef",
        "cpp_standard": "20",
        "system_pkgs": ["libcustom-dev"],
        "min_cmake_version": "3.25",
        "test_framework": "catch2",
    })
    assert specs["cpp_standard"] == "20"
    assert "libcustom-dev" in specs["system_pkgs"]
    assert specs["min_cmake"] == "3.25"
    assert specs["test_framework"] == "catch2"


def test_synthesize_specs_bare_instance_uses_defaults():
    from swefficiency.harness.dynamic_specs_cpp import _synthesize_specs_cpp

    specs = _synthesize_specs_cpp({"repo": "unknown/repo", "base_commit": "x"})
    assert specs["language"] == "cpp"
    assert specs["cpp_standard"]
    assert specs["test_framework"]


# --- resolution status -----------------------------------------------------

def test_resolution_status_empty_lists_not_resolved():
    """No verifiable tests => NO, not FULL. compute_*_to_pass return 1.0 on an
    empty list, which used to mark every coverage-stubbed instance resolved."""
    from swefficiency.harness.grading_cpp import get_resolution_status

    empty = {
        FAIL_TO_PASS: {"success": [], "failure": []},
        PASS_TO_PASS: {"success": [], "failure": []},
    }
    assert get_resolution_status(empty) == ResolvedStatus.NO.value


def test_resolution_status_all_pass_is_full():
    from swefficiency.harness.grading_cpp import get_resolution_status

    rep = {
        FAIL_TO_PASS: {"success": ["t1"], "failure": []},
        PASS_TO_PASS: {"success": ["t2"], "failure": []},
    }
    assert get_resolution_status(rep) == ResolvedStatus.FULL.value


def test_resolution_status_partial():
    from swefficiency.harness.grading_cpp import get_resolution_status

    rep = {
        FAIL_TO_PASS: {"success": ["t1"], "failure": ["t2"]},
        PASS_TO_PASS: {"success": ["t3"], "failure": []},
    }
    assert get_resolution_status(rep) == ResolvedStatus.PARTIAL.value


# --- empty-patch grading ---------------------------------------------------

def test_eval_report_empty_patch_is_none():
    """An empty-string model_patch must grade as 'no patch', not a real one."""
    from swefficiency.harness.grading_cpp import get_eval_report_cpp

    rep = get_eval_report_cpp(
        test_spec=None,
        prediction={KEY_INSTANCE_ID: "x", "model_patch": ""},
        log_path="",
        include_tests_status=False,
    )
    assert rep["x"]["patch_is_None"] is True
    assert rep["x"]["resolved"] is False


def test_eval_report_none_patch_is_none():
    from swefficiency.harness.grading_cpp import get_eval_report_cpp

    rep = get_eval_report_cpp(
        test_spec=None,
        prediction={KEY_INSTANCE_ID: "x", "model_patch": None},
        log_path="",
        include_tests_status=False,
    )
    assert rep["x"]["patch_is_None"] is True


# --- parse_perf_output: sentinel-bounded ----------------------------------

def test_parse_perf_output_ignores_text_outside_sentinels():
    """Mean:/Std Dev: lines outside PERF_START/PERF_END must be ignored."""
    from swefficiency.harness.test_spec import parse_perf_output

    raw = (
        "Mean: 999.0\n"
        "Std Dev: 888.0\n"
        "PERF_START:\n"
        "Mean: 1.5\n"
        "Std Dev: 0.25\n"
        "PERF_END:\n"
        "Mean: 777.0\n"
    )
    mean, sd = parse_perf_output(raw)
    assert mean == 1.5
    assert sd == 0.25


# --- report improvement sign ----------------------------------------------

def test_report_improvement_positive_for_speedup():
    """A speedup (after < before) must report a positive improvement %."""
    report = pytest.importorskip("swefficiency.report")

    r = report.parse_perf_summary(
        "Before Mean: 1.0\nBefore Std: 0.1\nAfter Mean: 0.5\nAfter Std: 0.05"
    )
    assert r["improvement"] == pytest.approx(50.0)


def test_report_improvement_negative_for_regression():
    report = pytest.importorskip("swefficiency.report")

    r = report.parse_perf_summary(
        "Before Mean: 1.0\nBefore Std: 0.1\nAfter Mean: 2.0\nAfter Std: 0.1"
    )
    assert r["improvement"] < 0


# --- discovery token rotator ----------------------------------------------

def test_token_rotator_round_robins():
    from swefficiency.collect.discover_repos_cpp import _TokenRotator

    r = _TokenRotator(["a", "b", "c"])
    assert [r.next() for _ in range(7)] == ["a", "b", "c", "a", "b", "c", "a"]
    assert r.size == 3


def test_token_rotator_rejects_empty():
    from swefficiency.collect.discover_repos_cpp import _TokenRotator

    with pytest.raises(ValueError):
        _TokenRotator([])
