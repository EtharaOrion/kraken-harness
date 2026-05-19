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

"""Harness constants for the TypeScript pipeline.

This file mirrors ``swefficiency.harness.constants`` (which is Python-only)
for TypeScript task instances. It does **not** import from constants.py at
top level beyond ``TestStatus`` (the enum is language-agnostic and we reuse
it verbatim so reporting downstream stays consistent).

Phase 1 scope: Vitest-based projects only. Other test runners will land in
Phase 2 (see .sisyphus/plans/ts_pipeline.md).
"""

from typing import TypedDict

# Reuse the language-agnostic enum verbatim so grading/log_parsers_ts
# return statuses that are interoperable with the Python pipeline's
# downstream consumers (reports, perf filter, etc.).
from swefficiency.harness.constants import TestStatus  # noqa: F401 (re-export)


# ---------------------------------------------------------------------------
# Language tag
# ---------------------------------------------------------------------------

LANGUAGE_TAG = "ts"


# ---------------------------------------------------------------------------
# Instance schema additions
# ---------------------------------------------------------------------------


class SWEfficiencyInstanceTs(TypedDict, total=False):
    """Structured view of a TypeScript task instance.

    Mirrors :class:`SWEfficiencyInstance` from harness/constants.py but with
    TypeScript-specific fields. ``total=False`` so partial / migrated rows
    still type-check.
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

    # New language tag — always "ts" for instances created by this pipeline.
    language: str

    # TypeScript-specific spec fields.
    node_version: str  # e.g. "20"
    build_system: str  # one of {"node"}; phase 1: only "node"
    build_cmd: str
    test_framework: str  # phase 1: only "vitest"
    test_cmd: str
    test_cmd_override: str
    package_manager: str  # one of {"npm", "pnpm", "yarn", "bun"}; detect at runtime
    system_pkgs: list  # apt-installable, e.g. ["git"]
    packages_source: str  # "package.json" | ""
    pre_install_cmds: list
    log_parser_type: str  # selects a MAP_REPO_TO_PARSER_TS key

    # Carried over for orchestration parity with the Python pipeline.
    workload: str
    patch_fetch_failed: bool


# ---------------------------------------------------------------------------
# Build system identifiers
# ---------------------------------------------------------------------------

BUILD_NODE = "node"

# Set of build systems supported in Phase 1.
SUPPORTED_BUILD_SYSTEMS_TS = {BUILD_NODE}


# ---------------------------------------------------------------------------
# Node / package-manager identifiers
# ---------------------------------------------------------------------------

NODE_VERSION = "20"
PACKAGE_MANAGERS = ["npm", "pnpm", "yarn", "bun"]
DEFAULT_PACKAGE_MANAGER = "npm"


# ---------------------------------------------------------------------------
# Test framework identifiers
# ---------------------------------------------------------------------------

TEST_FRAMEWORK_VITEST = "vitest"

SUPPORTED_TEST_FRAMEWORKS_TS = {
    TEST_FRAMEWORK_VITEST,
}


# ---------------------------------------------------------------------------
# Test command templates
#
# Each template lands as the instance's ``test_cmd`` unless overridden by
# ``test_cmd_override``. Vitest is invoked via the autodetected package
# manager at runtime; the constants here are the *flags* that select
# reporters / output paths so downstream parsers can find results.
# ---------------------------------------------------------------------------

# Vitest with JSON + JUnit reporters. JSON drives our log_parsers_ts;
# JUnit is kept for interoperability with CI consumers. `tsc --noEmit`
# handles typecheck separately (Vitest itself uses esbuild and skips
# type errors).
TEST_VITEST_JSON_JUNIT = (
    "vitest run"
    " --reporter=json --reporter=junit"
    " --outputFile.json=/tmp/vitest_results.json"
    " --outputFile.junit=/tmp/vitest_results.junit.xml"
)
TEST_VITEST_STDOUT = "vitest run --reporter=default"

# Vitest bench (tinybench underneath) used by the workload step. JSON
# output lands at the path the workload runner reads to compute HSR.
TEST_VITEST_BENCH_JSON = (
    "vitest bench"
    " --run"
    " --reporter=json"
    " --outputFile=/tmp/vitest_bench.json"
)

# Typecheck step (no emit). Vitest skips this on its own.
TEST_TSC_NOEMIT = "tsc --noEmit"

# Coverage step. v8 provider writes coverage-final.json by default.
TEST_VITEST_COVERAGE = (
    "vitest run --coverage --coverage.provider=v8"
    " --coverage.reporter=json"
)


# ---------------------------------------------------------------------------
# Repo → build system map (Phase 1 shortlist).
#
# Tier-1 shortlist: lodash/lodash, axios/axios, expressjs/express,
# prettier/prettier, vitest-dev/vitest, microsoft/TypeScript. All entries
# share the Phase 1 build/test contract: Node + Vitest, with the package
# manager autodetected at runtime from lockfile presence.
# ---------------------------------------------------------------------------

MAP_REPO_TO_BUILD_SYSTEM_TS: dict[str, dict] = {
    "lodash/lodash": {
        "build_system": BUILD_NODE,
        "node_version": NODE_VERSION,
        "test_framework": TEST_FRAMEWORK_VITEST,
        "package_manager": "detect",
        "system_pkgs": [],
    },
    "axios/axios": {
        "build_system": BUILD_NODE,
        "node_version": NODE_VERSION,
        "test_framework": TEST_FRAMEWORK_VITEST,
        "package_manager": "detect",
        "system_pkgs": [],
    },
    "expressjs/express": {
        "build_system": BUILD_NODE,
        "node_version": NODE_VERSION,
        "test_framework": TEST_FRAMEWORK_VITEST,
        "package_manager": "detect",
        "system_pkgs": [],
    },
    "prettier/prettier": {
        "build_system": BUILD_NODE,
        "node_version": NODE_VERSION,
        "test_framework": TEST_FRAMEWORK_VITEST,
        "package_manager": "detect",
        "system_pkgs": [],
    },
    "vitest-dev/vitest": {
        "build_system": BUILD_NODE,
        "node_version": NODE_VERSION,
        "test_framework": TEST_FRAMEWORK_VITEST,
        "package_manager": "detect",
        "system_pkgs": [],
    },
    "microsoft/TypeScript": {
        "build_system": BUILD_NODE,
        "node_version": NODE_VERSION,
        "test_framework": TEST_FRAMEWORK_VITEST,
        "package_manager": "detect",
        "system_pkgs": [],
    },
}

# Tier-1 shortlist of canonical repos used as the candidate pool for
# Phase 1 dataset construction.
TIER1_REPOS_TS = [
    "lodash/lodash",
    "axios/axios",
    "expressjs/express",
    "prettier/prettier",
    "vitest-dev/vitest",
    "microsoft/TypeScript",
]

# Phase 1 default repo used when no repo is specified.
DEFAULT_REPO_TS = "lodash/lodash"


# ---------------------------------------------------------------------------
# Repo → primary log parser map (Phase 1 shortlist).
#
# Filled in by log_parsers_ts.py once the parser functions are defined.
# We expose the mapping by repo string so the canonical lookup happens via
# the same _ParserMapWithFallback pattern used by the Python pipeline.
# ---------------------------------------------------------------------------

# Default fallback parser name — resolved to the actual callable in
# log_parsers_ts.MAP_REPO_TO_PARSER_TS. Kept here so callers wanting just
# the *name* (e.g. for logging) don't need to import the parser module.
DEFAULT_PARSER_NAME_TS = "parse_log_vitest_json"


# ---------------------------------------------------------------------------
# Container / host path conventions for the TypeScript pipeline.
#
# Mirror /testbed-based conventions from harness/test_spec.py but keep
# TypeScript artifacts under distinct names so a runner that ever
# hybridizes can coexist.
# ---------------------------------------------------------------------------

TS_BUILD_DIR = "/testbed"
TS_PERF_WORKLOAD_SCRIPT_LOCATION = "/tmp/workload.bench.ts"
TS_PERF_RESULTS_LOCATION = "/tmp/vitest_bench.json"
TS_TEST_RESULTS_JSON_LOCATION = "/tmp/vitest_results.json"
TS_TEST_RESULTS_JUNIT_LOCATION = "/tmp/vitest_results.junit.xml"
TS_COVERAGE_OUTPUT_LOCATION = "coverage/coverage-final.json"
TS_NODE_MODULES_CACHE_DIR = "/root/.cache/node_modules"


# ---------------------------------------------------------------------------
# Docker image name constants
# ---------------------------------------------------------------------------

IMAGE_BASE_TS = "sweb.base.ts"
IMAGE_ENV_TS_PREFIX = "sweb.env.ts"  # full tag: sweb.env.ts.<hash>
IMAGE_EVAL_TS_PREFIX = "sweb.eval.ts"  # full tag: sweb.eval.ts.<id>


# ---------------------------------------------------------------------------
# Run identifier conventions
# ---------------------------------------------------------------------------

RUN_ID_PREFIX_TS = "ts_"


# ---------------------------------------------------------------------------
# Cache namespaces / environment variables / directories
# ---------------------------------------------------------------------------

NS_VERSION_TS = "NS_VERSION_TS"
NS_REPO_SPECS_TS = "NS_REPO_SPECS_TS"
CACHE_DB_TS = "cache_ts.db"

ENV_WORKLOAD_MODEL_TS = "WORKLOAD_MODEL_TS"
ENV_SWEFF_VALIDATE_TS_WORKLOAD = "SWEFF_VALIDATE_TS_WORKLOAD"

ARTIFACTS_DIR_TS = "artifacts_ts"
WORKLOAD_GEN_LOG_DIR_TS = "logs/workload_generation_ts"
RUN_EVAL_LOG_DIR_TS = "logs/run_evaluation_ts"
EVAL_REPORTS_DIR_TS = "eval_reports_ts"


# ---------------------------------------------------------------------------
# SPDX license allow-list (identical to the C++ pipeline).
# ---------------------------------------------------------------------------

SPDX_ALLOWLIST = {
    "Apache-2.0",
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "Zlib",
    "BSL-1.0",
}


# Reasonable Phase 1 defaults if dynamic_specs_ts can't synthesize.
DEFAULT_NODE_VERSION = NODE_VERSION
