#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Pre-flight schema validator for TypeScript task instances.

Standalone fork of ``scripts/validate_dataset.py``. The Python validator is
left untouched so the Python harness is unaffected. This module enforces the
shape SWE-fficiency ts inference + eval requires:

REQUIRED_NON_EMPTY  — instance_id, repo, version, base_commit, patch
REQUIRED_PRESENT    — test_patch, hints_text, created_at,
                      environment_setup_commit, FAIL_TO_PASS, PASS_TO_PASS
SWEFF_REQUIRED_TS   — workload, node_version, install_cmd
PHASE_1_LOCKED      — language=="ts", test_framework=="vitest", SPDX in
                      allow-list, package.json + tsconfig.json present.

Plus regex checks: SHA, instance_id pattern, repo path, and
language-aware workload sniffing (Vitest bench .ts/.bench.ts with
``bench(`` calls and ``import`` lines). NOT a full preflight (no
docker/AWS/disk/fd checks — see ``scripts/validate_run_ts.py`` for those).

Usage:
    python scripts/validate_dataset_ts.py <dataset.jsonl> [--strict]

Exit code: 0 if all records valid; 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Regex constants (same as the Python validator — these are content-shape
# checks, not language-specific). Duplicated here intentionally so the ts
# validator never imports from the Python validator.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_INSTANCE_ID_RE = re.compile(r"^[a-z][\w.-]*__[\w.-]+-\d+$")
_REPO_RE = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$")

# Phase 1: vitest-only. Other JS test frameworks are rejected with an
# explicit message so users aren't left guessing why their dataset failed.
_ACCEPTED_TEST_FRAMEWORK = "vitest"
_REJECTED_TEST_FRAMEWORKS = ("jest", "mocha", "jasmine", "ava")

# SPDX allow-list locked at the Phase 1 stack level.
_ALLOWED_SPDX = {
    "MIT",
    "MIT-0",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
}

# Tokens that indicate a C++/CMake leak into a TypeScript record. If any of
# these literal substrings appear in workload/install_cmd/test_cmd, the
# record is rejected — TypeScript instances must not reference the C++
# toolchain.
_FORBIDDEN_TOKENS = (
    "CMakeLists",
    "gbench",
    "gtest",
    "catch2",
    "ctest",
    "cmake",
    "g++",
)

# Required for every ts instance.
REQUIRED_NON_EMPTY = [
    "instance_id",
    "repo",
    "version",
    "base_commit",
    "patch",
]

WARN_IF_EMPTY = [
    "problem_statement",
]

REQUIRED_PRESENT = [
    "test_patch",
    "hints_text",
    "created_at",
    "environment_setup_commit",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
]

# TypeScript pipeline inference + eval requirements. node_version takes the
# role python_version plays in the Python pipeline (target ECMAScript /
# TypeScript language level, e.g. "ES2022").
SWEFF_REQUIRED_TS = [
    "workload",
    "node_version",
    "install_cmd",
]

# Phase 1 stack lock — fields that must be present and well-shaped.
PHASE_1_REQUIRED_PROJECT_FILES = [
    "package.json",
    "tsconfig.json",
]


def _scan_forbidden_tokens(iid: str, field: str, value) -> list:
    """Return errors if `value` mentions C++/CMake tokens."""
    errs: list = []
    if not isinstance(value, str) or not value:
        return errs
    for tok in _FORBIDDEN_TOKENS:
        if tok in value:
            errs.append(
                f"[{iid}] {field} mentions forbidden C++/CMake token "
                f"{tok!r} (TypeScript records must not reference the C++ "
                f"toolchain)"
            )
    return errs


def validate_instance_ts(idx: int, record: dict):
    """Validate a single ts dataset record. Returns (errors, warnings)."""
    errors: list = []
    warnings: list = []
    iid = record.get("instance_id", f"<missing-at-line-{idx + 1}>")

    # Language gate — required and locked to 'ts'.
    language = record.get("language")
    if language is None:
        errors.append(
            f"[{iid}] Missing required field: language (expected 'ts')"
        )
    elif language != "ts":
        errors.append(
            f"[{iid}] language={language!r} (expected 'ts')"
        )

    # Test framework gate — Phase 1 vitest-only.
    test_framework = record.get("test_framework")
    if test_framework is None:
        errors.append(
            f"[{iid}] Missing required field: test_framework "
            f"(expected {_ACCEPTED_TEST_FRAMEWORK!r})"
        )
    elif isinstance(test_framework, str):
        tf_lower = test_framework.strip().lower()
        if tf_lower in _REJECTED_TEST_FRAMEWORKS:
            errors.append(
                f"[{iid}] test_framework={test_framework!r} is rejected: "
                f"Phase 1 is vitest-only. Re-export with "
                f"test_framework='vitest'."
            )
        elif tf_lower != _ACCEPTED_TEST_FRAMEWORK:
            errors.append(
                f"[{iid}] test_framework={test_framework!r} not accepted "
                f"(expected {_ACCEPTED_TEST_FRAMEWORK!r})"
            )

    # SPDX license gate.
    license_id = record.get("license") or record.get("spdx_license")
    if license_id is None:
        errors.append(
            f"[{iid}] Missing required field: license (SPDX identifier, one "
            f"of {sorted(_ALLOWED_SPDX)})"
        )
    elif isinstance(license_id, str):
        if license_id.strip() not in _ALLOWED_SPDX:
            errors.append(
                f"[{iid}] license={license_id!r} not in SPDX allow-list "
                f"{sorted(_ALLOWED_SPDX)}"
            )

    # Project files gate — package.json + tsconfig.json must be present.
    project_files = record.get("project_files")
    pf_set: set = set()
    if isinstance(project_files, dict):
        pf_set = {str(k) for k in project_files.keys()}
    elif isinstance(project_files, list):
        pf_set = {str(x) for x in project_files}
    elif project_files is not None:
        errors.append(
            f"[{iid}] project_files should be a list or dict, got "
            f"{type(project_files).__name__}"
        )
    for required_file in PHASE_1_REQUIRED_PROJECT_FILES:
        if required_file not in pf_set:
            errors.append(
                f"[{iid}] project_files missing required entry: "
                f"{required_file!r}"
            )

    for field in REQUIRED_NON_EMPTY:
        val = record.get(field)
        if val is None:
            errors.append(f"[{iid}] Missing required field: {field}")
        elif isinstance(val, str) and not val.strip():
            errors.append(f"[{iid}] Empty required field: {field}")

    for field in REQUIRED_PRESENT:
        if field not in record:
            errors.append(f"[{iid}] Missing field: {field}")

    for field in WARN_IF_EMPTY:
        val = record.get(field, "")
        if isinstance(val, str) and not val.strip():
            warnings.append(
                f"[{iid}] WARN: {field} is empty (not required for inference)"
            )

    for field in SWEFF_REQUIRED_TS:
        val = record.get(field)
        if val is None:
            errors.append(f"[{iid}] Missing SWE-fficiency ts field: {field}")
        elif isinstance(val, str) and not val.strip():
            errors.append(f"[{iid}] Empty SWE-fficiency ts field: {field}")

    # Forbidden token scan on toolchain-shaped fields.
    for field in ("workload", "install_cmd", "test_cmd"):
        errors.extend(_scan_forbidden_tokens(iid, field, record.get(field)))

    # Structural validations (mirror the Python validator).
    instance_id = record.get("instance_id", "")
    if instance_id and not _INSTANCE_ID_RE.match(instance_id.lower()):
        if not re.match(r"^[\w][\w.-]*-\d+$", instance_id):
            errors.append(
                f"[{iid}] instance_id has unexpected format: {instance_id!r}"
            )

    repo = record.get("repo", "")
    if repo and not _REPO_RE.match(repo):
        errors.append(f"[{iid}] repo has unexpected format: {repo!r}")

    base_commit = record.get("base_commit", "")
    if base_commit and not _SHA_RE.match(base_commit.lower()):
        errors.append(
            f"[{iid}] base_commit is not a valid 7-40 char SHA: {base_commit!r}"
        )

    version = record.get("version", "")
    if isinstance(version, str) and version:
        pass
    elif isinstance(version, (int, float)):
        pass
    else:
        errors.append(f"[{iid}] version is invalid: {version!r}")

    # Patch should look like a unified diff.
    patch = record.get("patch", "")
    if isinstance(patch, str) and patch and "diff" not in patch.lower():
        errors.append(f"[{iid}] patch doesn't look like a unified diff")

    test_patch = record.get("test_patch")
    if isinstance(test_patch, str) and test_patch and "diff" not in test_patch.lower():
        errors.append(f"[{iid}] test_patch doesn't look like a unified diff")

    # Workload language sniff (ts only — Vitest bench .ts).
    workload = record.get("workload", "")
    if isinstance(workload, str) and workload:
        if "bench(" not in workload and "import" not in workload:
            errors.append(
                f"[{iid}] workload doesn't look like TypeScript Vitest bench "
                f"code (expected 'bench(' call or 'import' statement)"
            )

    # PASS_TO_PASS / FAIL_TO_PASS / covering_tests must be lists when present.
    for list_field in ("PASS_TO_PASS", "FAIL_TO_PASS", "covering_tests"):
        val = record.get(list_field)
        if val is not None and not isinstance(val, list):
            errors.append(
                f"[{iid}] {list_field} should be a list, got {type(val).__name__}"
            )

    return errors, warnings


def validate_dataset_ts(path: Path):
    """Validate a JSONL of ts instances. Returns (count, errors, warnings)."""
    all_errors: list = []
    all_warnings: list = []
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                all_errors.append(
                    f"[line {idx + 1}] failed to parse JSON: {e}"
                )
                continue
            errs, warns = validate_instance_ts(idx, record)
            all_errors.extend(errs)
            all_warnings.extend(warns)
            count += 1
    return count, all_errors, all_warnings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Path to ts dataset JSONL.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (non-zero exit).",
    )
    args = parser.parse_args(argv)

    path = Path(args.dataset)
    if not path.exists():
        print(f"ERROR: dataset not found: {path}", file=sys.stderr)
        return 1

    count, errors, warnings = validate_dataset_ts(path)
    print(f"Count: {count}, Errors: {len(errors)}, Warnings: {len(warnings)}")
    for e in errors:
        print(f"  ERROR  {e}")
    for w in warnings:
        print(f"  WARN   {w}")
    if errors:
        print("FAIL: ts dataset has validation errors")
        return 1
    if warnings and args.strict:
        print("FAIL: ts dataset has warnings (--strict)")
        return 1
    print("OK: ts dataset validates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
