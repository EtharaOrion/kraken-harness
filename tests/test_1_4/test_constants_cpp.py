# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for swefficiency.harness.constants_cpp.

Pins down the shape of MAP_REPO_TO_BUILD_SYSTEM_CPP and the test-framework
constants the test_spec_cpp pipeline relies on. If you change a repo's
build_system or test_framework, update this test in the same commit.
"""
from __future__ import annotations

import pytest

from swefficiency.harness.constants_cpp import (
    BUILD_CMAKE,
    BUILD_CMAKE_NINJA,
    MAP_REPO_TO_BUILD_SYSTEM_CPP,
    TEST_FRAMEWORK_CATCH2,
    TEST_FRAMEWORK_CTEST,
    TEST_FRAMEWORK_GOOGLE_BENCHMARK,
    TEST_FRAMEWORK_GTEST,
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


def test_build_system_constants_are_strings():
    assert isinstance(BUILD_CMAKE, str)
    assert isinstance(BUILD_CMAKE_NINJA, str)
    assert BUILD_CMAKE != BUILD_CMAKE_NINJA


def test_test_framework_constants_distinct():
    frameworks = {
        TEST_FRAMEWORK_GTEST,
        TEST_FRAMEWORK_CTEST,
        TEST_FRAMEWORK_CATCH2,
        TEST_FRAMEWORK_GOOGLE_BENCHMARK,
    }
    assert len(frameworks) == 4


# ---------------------------------------------------------------------------
# MAP_REPO_TO_BUILD_SYSTEM_CPP shape (locked: 6 Tier-1 repos)
# ---------------------------------------------------------------------------

EXPECTED_REPOS = (
    "fmtlib/fmt",
    "gabime/spdlog",
    "nlohmann/json",
    "abseil/abseil-cpp",
    "ericniebler/range-v3",
    "eigen-mirror/eigen",
)


def test_map_contains_six_tier1_repos():
    for repo in EXPECTED_REPOS:
        assert repo in MAP_REPO_TO_BUILD_SYSTEM_CPP, (
            f"{repo!r} missing from MAP_REPO_TO_BUILD_SYSTEM_CPP "
            "(locked Phase 1 Tier-1 scope per b13/b15)"
        )


REQUIRED_FIELDS = ("build_system", "min_cmake", "test_flag", "system_pkgs")


@pytest.mark.parametrize("repo", EXPECTED_REPOS)
def test_each_repo_has_required_fields(repo):
    entry = MAP_REPO_TO_BUILD_SYSTEM_CPP[repo]
    for field in REQUIRED_FIELDS:
        assert field in entry, f"{repo}: missing field {field!r}"


@pytest.mark.parametrize("repo", EXPECTED_REPOS)
def test_each_repo_build_system_is_cmake_family(repo):
    """Phase 1 supports CMake only (locked decision b15 §10b)."""
    bs = MAP_REPO_TO_BUILD_SYSTEM_CPP[repo]["build_system"]
    assert bs in {BUILD_CMAKE, BUILD_CMAKE_NINJA, "cmake", "cmake_ninja"}, (
        f"{repo}: build_system={bs!r} not in CMake family"
    )


@pytest.mark.parametrize("repo", EXPECTED_REPOS)
def test_each_repo_system_pkgs_is_list(repo):
    pkgs = MAP_REPO_TO_BUILD_SYSTEM_CPP[repo]["system_pkgs"]
    assert isinstance(pkgs, list), f"{repo}: system_pkgs must be list"
    for pkg in pkgs:
        assert isinstance(pkg, str)


def test_eigen_has_openblas_dep():
    """Eigen test suite needs OpenBLAS; locked entry per (b15) research."""
    pkgs = MAP_REPO_TO_BUILD_SYSTEM_CPP["eigen-mirror/eigen"]["system_pkgs"]
    assert any("openblas" in p for p in pkgs), (
        "eigen tests depend on libopenblas-dev (research distillation b15)"
    )


def test_spdlog_marked_as_catch2():
    """spdlog uses Catch2 — must be flagged so make_test_command_cpp routes correctly."""
    entry = MAP_REPO_TO_BUILD_SYSTEM_CPP["gabime/spdlog"]
    tf = entry.get("test_framework", "")
    assert "catch2" in tf.lower(), (
        "spdlog must declare test_framework=catch2 (research b15)"
    )


def test_fmt_has_ftest_on_flag():
    entry = MAP_REPO_TO_BUILD_SYSTEM_CPP["fmtlib/fmt"]
    assert "-DFMT_TEST=ON" in entry["test_flag"]


def test_json_has_buildtests_flag():
    entry = MAP_REPO_TO_BUILD_SYSTEM_CPP["nlohmann/json"]
    assert "-DJSON_BuildTests=ON" in entry["test_flag"]
