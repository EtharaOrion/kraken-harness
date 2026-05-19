# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for swefficiency.harness.constants_ts.

Pins down the shape of MAP_REPO_TO_BUILD_SYSTEM_TS and the test-framework
constants the test_spec_ts pipeline relies on. If you change a repo's
build_system or test_framework, update this test in the same commit.
"""
from __future__ import annotations

import pytest

from swefficiency.harness.constants_ts import (
    BUILD_NODE,
    DEFAULT_REPO_TS,
    IMAGE_BASE_TS,
    IMAGE_ENV_TS_PREFIX,
    IMAGE_EVAL_TS_PREFIX,
    LANGUAGE_TAG,
    MAP_REPO_TO_BUILD_SYSTEM_TS,
    SUPPORTED_BUILD_SYSTEMS_TS,
    SUPPORTED_TEST_FRAMEWORKS_TS,
    TEST_FRAMEWORK_VITEST,
    TS_PERF_RESULTS_LOCATION,
    TS_PERF_WORKLOAD_SCRIPT_LOCATION,
    TestStatus,
)


# ---------------------------------------------------------------------------
# Top-level constant shapes
# ---------------------------------------------------------------------------

def test_test_status_enum_values():
    """TestStatus re-exported from constants.py — must match."""
    assert TestStatus.PASSED.value == "PASSED"
    assert TestStatus.FAILED.value == "FAILED"
    assert TestStatus.SKIPPED.value == "SKIPPED"
    assert TestStatus.ERROR.value == "ERROR"
    assert TestStatus.XFAIL.value == "XFAIL"


def test_language_tag_is_ts():
    assert LANGUAGE_TAG == "ts"


def test_build_system_constants_are_strings():
    assert isinstance(BUILD_NODE, str)
    assert BUILD_NODE == "node"
    assert BUILD_NODE in SUPPORTED_BUILD_SYSTEMS_TS


def test_test_framework_allowlist_phase1_vitest_only():
    """Phase 1 supports Vitest only (locked decision)."""
    assert TEST_FRAMEWORK_VITEST == "vitest"
    assert SUPPORTED_TEST_FRAMEWORKS_TS == {TEST_FRAMEWORK_VITEST}


def test_default_phase1_repo_is_lodash():
    assert DEFAULT_REPO_TS == "lodash/lodash"


def test_workload_container_paths():
    """Workload script + perf result locations are pinned for runner contract."""
    assert TS_PERF_WORKLOAD_SCRIPT_LOCATION == "/tmp/workload.bench.ts"
    assert TS_PERF_RESULTS_LOCATION == "/tmp/vitest_bench.json"


def test_image_tag_prefixes():
    assert IMAGE_BASE_TS == "sweb.base.ts"
    assert IMAGE_ENV_TS_PREFIX.startswith("sweb.env.ts")
    assert IMAGE_EVAL_TS_PREFIX.startswith("sweb.eval.ts")


# ---------------------------------------------------------------------------
# MAP_REPO_TO_BUILD_SYSTEM_TS shape (locked: 6 Tier-1 repos)
# ---------------------------------------------------------------------------

EXPECTED_REPOS = (
    "lodash/lodash",
    "axios/axios",
    "expressjs/express",
    "prettier/prettier",
    "vitest-dev/vitest",
    "microsoft/TypeScript",
)


def test_map_contains_six_tier1_repos():
    for repo in EXPECTED_REPOS:
        assert repo in MAP_REPO_TO_BUILD_SYSTEM_TS, (
            f"{repo!r} missing from MAP_REPO_TO_BUILD_SYSTEM_TS "
            "(locked Phase 1 Tier-1 scope)"
        )


REQUIRED_FIELDS = (
    "build_system",
    "node_version",
    "test_framework",
    "package_manager",
    "system_pkgs",
)


@pytest.mark.parametrize("repo", EXPECTED_REPOS)
def test_each_repo_has_required_fields(repo):
    entry = MAP_REPO_TO_BUILD_SYSTEM_TS[repo]
    for field in REQUIRED_FIELDS:
        assert field in entry, f"{repo}: missing field {field!r}"


@pytest.mark.parametrize("repo", EXPECTED_REPOS)
def test_each_repo_build_system_is_node(repo):
    """Phase 1 supports Node only (locked decision)."""
    bs = MAP_REPO_TO_BUILD_SYSTEM_TS[repo]["build_system"]
    assert bs == BUILD_NODE, (
        f"{repo}: build_system={bs!r} not in node family"
    )


@pytest.mark.parametrize("repo", EXPECTED_REPOS)
def test_each_repo_test_framework_is_vitest(repo):
    """Phase 1 supports Vitest only."""
    tf = MAP_REPO_TO_BUILD_SYSTEM_TS[repo]["test_framework"]
    assert tf == TEST_FRAMEWORK_VITEST, (
        f"{repo}: test_framework={tf!r} not vitest"
    )


@pytest.mark.parametrize("repo", EXPECTED_REPOS)
def test_each_repo_system_pkgs_is_list(repo):
    pkgs = MAP_REPO_TO_BUILD_SYSTEM_TS[repo]["system_pkgs"]
    assert isinstance(pkgs, list), f"{repo}: system_pkgs must be list"
    for pkg in pkgs:
        assert isinstance(pkg, str)


@pytest.mark.parametrize("repo", EXPECTED_REPOS)
def test_each_repo_package_manager_autodetect(repo):
    """Phase 1 autodetects the package manager from lockfile presence."""
    pm = MAP_REPO_TO_BUILD_SYSTEM_TS[repo]["package_manager"]
    assert pm == "detect", (
        f"{repo}: package_manager={pm!r}; phase 1 autodetects at runtime"
    )
