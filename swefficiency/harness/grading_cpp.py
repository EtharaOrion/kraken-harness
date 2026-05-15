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

"""C++ grading: mirrors ``grading.py`` but routes logs to C++ parsers.

Without this fork, ``_ParserMapWithFallback`` in ``grading.py`` silently
falls back to ``parse_log_pytest`` for every C++ instance and emits an
empty test-status map (every test treated as missing → F2P=0).
"""

from pathlib import Path
from typing import Any, Optional

from swefficiency.harness.constants import (
    APPLY_PATCH_FAIL,
    APPLY_PATCH_PASS,
    FAIL_TO_FAIL,
    FAIL_TO_PASS,
    KEY_INSTANCE_ID,
    PASS_TO_FAIL,
    PASS_TO_PASS,
    RESET_FAILED,
    TESTS_ERROR,
    TESTS_TIMEOUT,
    ResolvedStatus,
    TestStatus,
)
from swefficiency.harness.log_parsers_cpp import (
    MAP_REPO_TO_PARSER_CPP,
    parse_log_cpp_best_effort,
)
from swefficiency.harness.test_spec_cpp import TestSpecCpp


def test_passed(case: str, sm: dict[str, str]) -> bool:
    return case in sm and sm[case] in [TestStatus.PASSED.value, TestStatus.XFAIL.value]


def test_failed(case: str, sm: dict[str, str]) -> bool:
    return case not in sm or any(
        sm[case] == status
        for status in [TestStatus.FAILED.value, TestStatus.ERROR.value]
    )


def get_logs_eval_cpp(
    log_fp: str,
    repo: Optional[str] = None,
) -> tuple[dict[str, str], bool]:
    """Parse C++ test output. Returns ``(status_map, patch_applied_ok)``.

    If ``repo`` is passed, route via :data:`MAP_REPO_TO_PARSER_CPP` directly.
    If ``repo`` is None, fall back to reverse-engineering the repo from the
    log path's parent dir (legacy; brittle for instance IDs with multiple
    dashes such as ``owner__repo-pr-1234-5``).

    Unknown repos route to :func:`parse_log_cpp_best_effort` instead of
    raising ``KeyError`` (which is what the previous unguarded subscript did,
    and what the dynamic discover stage would trigger on every unseen repo).
    """
    if repo is None:
        sample_id = str(Path(log_fp).parent.stem)
        repo = "-".join(sample_id.replace("__", "/").split("-")[:-1])
    log_parser = MAP_REPO_TO_PARSER_CPP.get(repo, parse_log_cpp_best_effort)

    with open(log_fp) as f:
        content = f.read()
        bad_markers = [
            APPLY_PATCH_FAIL,
            RESET_FAILED,
            TESTS_ERROR,
            TESTS_TIMEOUT,
            "Failed to reset task environment",
        ]
        if any(x in content for x in bad_markers) or "applied patch" not in content.lower():
            return {}, False

        content = content.split(f"{APPLY_PATCH_PASS} (pred)")[-1]
        return log_parser(content), True


def get_eval_tests_report(
    eval_sm: dict[str, str],
    gold_results: dict[str, str],
    calculate_to_fail: bool = False,
) -> dict[str, dict[str, list[str]]]:
    f2p_success, f2p_failure = [], []
    for tc in gold_results[FAIL_TO_PASS]:
        if test_passed(tc, eval_sm):
            f2p_success.append(tc)
        elif test_failed(tc, eval_sm):
            f2p_failure.append(tc)

    p2p_success, p2p_failure = [], []
    for tc in gold_results[PASS_TO_PASS]:
        if test_passed(tc, eval_sm):
            p2p_success.append(tc)
        elif test_failed(tc, eval_sm):
            p2p_failure.append(tc)

    results: dict[str, dict[str, list[str]]] = {
        FAIL_TO_PASS: {"success": f2p_success, "failure": f2p_failure},
        PASS_TO_PASS: {"success": p2p_success, "failure": p2p_failure},
    }

    if calculate_to_fail:
        f2f_success, f2f_failure = [], []
        for tc in gold_results.get(FAIL_TO_FAIL, []):
            if test_passed(tc, eval_sm):
                f2f_success.append(tc)
            elif test_failed(tc, eval_sm):
                f2f_failure.append(tc)
        p2f_success, p2f_failure = [], []
        for tc in gold_results.get(PASS_TO_FAIL, []):
            if test_passed(tc, eval_sm):
                p2f_success.append(tc)
            elif test_failed(tc, eval_sm):
                p2f_failure.append(tc)
        results.update({
            FAIL_TO_FAIL: {"success": f2f_success, "failure": f2f_failure},
            PASS_TO_FAIL: {"success": p2f_success, "failure": p2f_failure},
        })
    return results


def compute_fail_to_pass(report: dict[str, dict[str, Any]]) -> float:
    total = len(report[FAIL_TO_PASS]["success"]) + len(report[FAIL_TO_PASS]["failure"])
    if total == 0:
        return 1
    return len(report[FAIL_TO_PASS]["success"]) / total


def compute_pass_to_pass(report: dict[str, dict[str, Any]]) -> float:
    total = len(report[PASS_TO_PASS]["success"]) + len(report[PASS_TO_PASS]["failure"])
    if total == 0:
        return 1
    return len(report[PASS_TO_PASS]["success"]) / total


def get_resolution_status(report: dict[str, dict[str, Any]]) -> str:
    f2p = compute_fail_to_pass(report)
    p2p = compute_pass_to_pass(report)
    if f2p == 1 and p2p == 1:
        return ResolvedStatus.FULL.value
    elif 0 < f2p < 1 and p2p == 1:
        return ResolvedStatus.PARTIAL.value
    return ResolvedStatus.NO.value


def get_eval_report_cpp(
    test_spec: TestSpecCpp,
    prediction: dict[str, str],
    log_path: str,
    include_tests_status: bool,
    repo: Optional[str] = None,
) -> dict[str, Any]:
    """C++ analog of ``get_eval_report``."""
    report_map: dict[str, Any] = {}
    instance_id = prediction[KEY_INSTANCE_ID]
    report_map[instance_id] = {
        "patch_is_None": False,
        "patch_exists": False,
        "patch_successfully_applied": False,
        "resolved": False,
    }

    if prediction.get("model_patch") is None:
        report_map[instance_id]["patch_is_None"] = True
        return report_map
    report_map[instance_id]["patch_exists"] = True

    eval_sm, found = get_logs_eval_cpp(log_path, repo=repo or test_spec.repo)
    if not found:
        return report_map
    report_map[instance_id]["patch_successfully_applied"] = True

    eval_ref = {
        KEY_INSTANCE_ID: test_spec.instance_id,
        FAIL_TO_PASS: test_spec.FAIL_TO_PASS,
        PASS_TO_PASS: test_spec.PASS_TO_PASS,
    }
    report = get_eval_tests_report(eval_sm, eval_ref)
    if get_resolution_status(report) == ResolvedStatus.FULL.value:
        report_map[instance_id]["resolved"] = True

    if include_tests_status:
        report_map[instance_id]["tests_status"] = report
    return report_map
