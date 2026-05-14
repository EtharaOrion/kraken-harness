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

"""Harness constants for the C++ pipeline.

This file mirrors ``swefficiency.harness.constants`` (which is Python-only)
for C++ task instances. It does **not** import from constants.py at top
level beyond ``TestStatus`` (the enum is language-agnostic and we reuse it
verbatim so reporting downstream stays consistent).

Phase 1 scope: CMake-based projects only. Bazel / Meson / autotools will
land in Phase 2 (see .sisyphus/plans/cpp_pipeline.md, Section 8).
"""

from typing import TypedDict

# Reuse the language-agnostic enum verbatim so grading/log_parsers_cpp
# return statuses that are interoperable with the Python pipeline's
# downstream consumers (reports, perf filter, etc.).
from swefficiency.harness.constants import TestStatus  # noqa: F401 (re-export)


# ---------------------------------------------------------------------------
# Instance schema additions
# ---------------------------------------------------------------------------


class SWEfficiencyInstanceCpp(TypedDict, total=False):
    """Structured view of a C++ task instance.

    Mirrors :class:`SWEfficiencyInstance` from harness/constants.py but with
    C++-specific fields. ``total=False`` so partial / migrated rows still
    type-check.
    """

    # Mandatory across all pipelines.
    instance_id: str
    repo: str
    base_commit: str
    patch: str
    test_patch: str
    problem_statement: str
    hints_text: str
    created_at: str
    version: str

    # New language tag — always "cpp" for instances created by this pipeline.
    language: str

    # C++-specific spec fields.
    cpp_standard: str  # e.g. "17", "20"
    build_system: str  # one of {"cmake", "bazel", "meson", "autotools"}; phase 1: only "cmake"
    build_cmd: str
    test_framework: str  # one of {"gtest", "ctest", "catch2", "googlebenchmark"}
    test_cmd: str
    test_cmd_override: str
    cmake_flags: list  # e.g. ["-DFMT_TEST=ON"]
    system_pkgs: list  # apt-installable, e.g. ["libopenblas-dev"]
    packages_source: str  # "vcpkg.json" | "conanfile.txt" | ""
    pre_install_cmds: list
    log_parser_type: str  # selects a MAP_REPO_TO_PARSER_CPP key

    # Carried over for orchestration parity with the Python pipeline.
    workload: str
    patch_fetch_failed: bool


# ---------------------------------------------------------------------------
# Build system identifiers
# ---------------------------------------------------------------------------

BUILD_CMAKE = "cmake"
BUILD_CMAKE_NINJA = "cmake_ninja"
BUILD_BAZEL = "bazel"  # phase 2
BUILD_MESON = "meson"  # phase 2
BUILD_AUTOTOOLS = "autotools"  # phase 2

# Set of build systems supported in Phase 1.
SUPPORTED_BUILD_SYSTEMS_CPP = {BUILD_CMAKE, BUILD_CMAKE_NINJA}


# ---------------------------------------------------------------------------
# Test framework identifiers
# ---------------------------------------------------------------------------

TEST_FRAMEWORK_GTEST = "gtest"
TEST_FRAMEWORK_CTEST = "ctest"
TEST_FRAMEWORK_CATCH2 = "catch2"
TEST_FRAMEWORK_GOOGLE_BENCHMARK = "googlebenchmark"

SUPPORTED_TEST_FRAMEWORKS_CPP = {
    TEST_FRAMEWORK_GTEST,
    TEST_FRAMEWORK_CTEST,
    TEST_FRAMEWORK_CATCH2,
    TEST_FRAMEWORK_GOOGLE_BENCHMARK,
}


# ---------------------------------------------------------------------------
# Test command templates
#
# Each template lands as the instance's ``test_cmd`` unless overridden by
# ``test_cmd_override``. Templates take the project's build dir as ``$BUILD``
# (default ``/testbed/build``) and append test discovery flags appropriate
# for the framework.
# ---------------------------------------------------------------------------

# GoogleTest standalone binary (e.g. `./build/test/fmt-test`). Outputs JSON
# at a known path; stderr/stdout still goes to the eval log. Switch to XML
# via TEST_GTEST_XML for repos whose JSON output is broken.
TEST_GTEST_JSON = (
    "--gtest_output=json:/tmp/gtest_results.json --gtest_color=no"
)
TEST_GTEST_XML = "--gtest_output=xml:/tmp/gtest_results.xml --gtest_color=no"
TEST_GTEST_STDOUT = "--gtest_color=no"

# CTest is the canonical entry point for ctest-driven projects (fmt,
# nlohmann/json, eigen). --output-junit writes the JUnit-format report at a
# known path while --output-on-failure keeps a readable log on stdout.
TEST_CTEST_JUNIT = (
    "ctest --test-dir build --output-on-failure --output-junit"
    " /tmp/ctest_results.xml -j$(nproc)"
)
TEST_CTEST_STDOUT = "ctest --test-dir build --output-on-failure -j$(nproc)"

# Catch2 v3 ships a reporter selectable via --reporter=junit and
# --out=<file>. Catch2 v2 lacks --out at the binary level but accepts -r
# junit -o <file>.
TEST_CATCH2_XML = (
    "--reporter=junit --out=/tmp/catch2_results.xml --colour-mode=none"
)
TEST_CATCH2_V2_XML = "-r junit -o /tmp/catch2_results.xml"

# Google Benchmark binary flags used by the workload step. Repetitions/
# min_time tuned to match the noise-reduction guidance in the research
# distillation (see b11/b12: 10 repetitions, 1s min_time, JSON output).
TEST_GOOGLE_BENCHMARK_JSON = (
    "--benchmark_format=json"
    " --benchmark_repetitions=10"
    " --benchmark_display_aggregates_only=true"
    " --benchmark_min_time=1.0s"
    " --benchmark_color=false"
)


# ---------------------------------------------------------------------------
# Repo → build system map (Phase 1 shortlist).
#
# Values match those captured in the research distillation (b11/b12). Each
# entry must contain ``build_system``; the rest are optional.
# ---------------------------------------------------------------------------

MAP_REPO_TO_BUILD_SYSTEM_CPP: dict[str, dict] = {
    "fmtlib/fmt": {
        "build_system": BUILD_CMAKE_NINJA,
        "min_cmake": "3.8",
        "test_flag": "-DFMT_TEST=ON",
        "system_pkgs": [],
        "test_framework": TEST_FRAMEWORK_CTEST,
    },
    "gabime/spdlog": {
        "build_system": BUILD_CMAKE_NINJA,
        "min_cmake": "3.10",
        "test_flag": "-DSPDLOG_BUILD_TESTS=ON",
        "system_pkgs": [],
        "test_framework": TEST_FRAMEWORK_CATCH2,
    },
    "nlohmann/json": {
        "build_system": BUILD_CMAKE_NINJA,
        "min_cmake": "3.5",
        "test_flag": "-DJSON_BuildTests=ON",
        "system_pkgs": [],
        "test_framework": TEST_FRAMEWORK_CTEST,
    },
    "abseil/abseil-cpp": {
        "build_system": BUILD_CMAKE_NINJA,
        "min_cmake": "3.16",
        "test_flag": "-DABSL_BUILD_TESTING=ON",
        "system_pkgs": [],
        "test_framework": TEST_FRAMEWORK_GTEST,
    },
    "ericniebler/range-v3": {
        "build_system": BUILD_CMAKE_NINJA,
        "min_cmake": "3.6",
        "test_flag": "-DRANGE_V3_TESTS=ON",
        "system_pkgs": [],
        "test_framework": TEST_FRAMEWORK_CATCH2,
    },
    "eigen-mirror/eigen": {
        "build_system": BUILD_CMAKE_NINJA,
        "min_cmake": "3.17",
        "test_flag": "-DEIGEN_BUILD_TESTING=ON",
        "system_pkgs": ["libopenblas-dev", "liblapack-dev"],
        "test_framework": TEST_FRAMEWORK_CTEST,
    },
}


# ---------------------------------------------------------------------------
# Repo → primary log parser map (Phase 1 shortlist).
#
# Filled in by log_parsers_cpp.py once the parser functions are defined.
# We expose the mapping by repo string so the canonical lookup happens via
# the same _ParserMapWithFallback pattern used by the Python pipeline.
# ---------------------------------------------------------------------------

# Default fallback parser name — resolved to the actual callable in
# log_parsers_cpp.MAP_REPO_TO_PARSER_CPP. Kept here so callers wanting just
# the *name* (e.g. for logging) don't need to import the parser module.
DEFAULT_PARSER_NAME_CPP = "parse_log_gtest_stdout"


# ---------------------------------------------------------------------------
# Container / host path conventions for the C++ pipeline.
#
# Mirror /testbed-based conventions from harness/test_spec.py but keep C++
# artifacts under distinct names so a runner that ever hybridizes can
# coexist.
# ---------------------------------------------------------------------------

CPP_BUILD_DIR = "/testbed/build"
CPP_PERF_WORKLOAD_SCRIPT_LOCATION = "/tmp/workload.cc"
CPP_PERF_WORKLOAD_BINARY_LOCATION = "/tmp/workload_bin"
CPP_PERF_RESULTS_LOCATION = "/tmp/workload_results.json"
CPP_COVERAGE_OUTPUT_LOCATION = "/tmp/coverage.info"
CPP_COVERAGE_JSON_LOCATION = "/tmp/coverage.json"
CPP_CCACHE_DIR = "/root/.cache/ccache"

# Reasonable Phase 1 defaults if dynamic_specs_cpp can't synthesize.
DEFAULT_CPP_STANDARD = "17"
DEFAULT_CMAKE_VERSION = "3.22"
DEFAULT_GCC_VERSION = "12"
DEFAULT_CLANG_VERSION = "15"
