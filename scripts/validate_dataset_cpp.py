#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Pre-flight schema validator for C++ task instances.

Standalone fork of ``scripts/validate_dataset.py``. The Python validator is
left untouched so the Python harness is unaffected. This module enforces the
shape SWE-fficiency cpp inference + eval requires:

REQUIRED_NON_EMPTY  — instance_id, repo, version, base_commit, patch
REQUIRED_PRESENT    — test_patch, hints_text, created_at,
                      environment_setup_commit, FAIL_TO_PASS, PASS_TO_PASS
SWEFF_REQUIRED_CPP  — workload, cpp_standard, install_cmd

Plus regex checks: SHA, instance_id pattern, repo path, and
language-aware workload sniffing (Google Benchmark .cc with #include +
BENCHMARK macros). NOT a full preflight (no docker/AWS/disk/fd checks —
see ``scripts/validate_run_cpp.py`` for those).

Usage:
    python scripts/validate_dataset_cpp.py <dataset.jsonl> [--strict]

Exit code: 0 if all records valid; 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Regex constants (same as the Python validator — these are content-shape
# checks, not language-specific). Duplicated here intentionally so the cpp
# validator never imports from the Python validator.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_INSTANCE_ID_RE = re.compile(r"^[a-z][\w.-]*__[\w.-]+-\d+$")
_REPO_RE = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$")

# Required for every cpp instance.
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

# C++ pipeline inference + eval requirements. cpp_standard takes the role
# python_version plays in the Python pipeline.
SWEFF_REQUIRED_CPP = [
    "workload",
    "cpp_standard",
    "install_cmd",
]


def validate_instance_cpp(idx: int, record: dict):
    """Validate a single cpp dataset record. Returns (errors, warnings)."""
    errors: list = []
    warnings: list = []
    iid = record.get("instance_id", f"<missing-at-line-{idx + 1}>")

    # Optional language gate — if present, must be 'cpp'.
    language = record.get("language")
    if language is not None and language != "cpp":
        errors.append(
            f"[{iid}] language={language!r} (expected 'cpp' or omitted "
            "to default to cpp in this validator)"
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

    for field in SWEFF_REQUIRED_CPP:
        val = record.get(field)
        if val is None:
            errors.append(f"[{iid}] Missing SWE-fficiency cpp field: {field}")
        elif isinstance(val, str) and not val.strip():
            errors.append(f"[{iid}] Empty SWE-fficiency cpp field: {field}")

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

    # Workload language sniff (cpp only — Google Benchmark .cc).
    workload = record.get("workload", "")
    if isinstance(workload, str) and workload:
        if "BENCHMARK" not in workload and "#include" not in workload:
            errors.append(
                f"[{iid}] workload doesn't look like C++ Google Benchmark code"
            )

    # PASS_TO_PASS / FAIL_TO_PASS / covering_tests must be lists when present.
    for list_field in ("PASS_TO_PASS", "FAIL_TO_PASS", "covering_tests"):
        val = record.get(list_field)
        if val is not None and not isinstance(val, list):
            errors.append(
                f"[{iid}] {list_field} should be a list, got {type(val).__name__}"
            )

    return errors, warnings


def validate_dataset_cpp(path: Path):
    """Validate a JSONL of cpp instances. Returns (count, errors, warnings)."""
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
            errs, warns = validate_instance_cpp(idx, record)
            all_errors.extend(errs)
            all_warnings.extend(warns)
            count += 1
    return count, all_errors, all_warnings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Path to cpp dataset JSONL.")
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

    count, errors, warnings = validate_dataset_cpp(path)
    print(f"Count: {count}, Errors: {len(errors)}, Warnings: {len(warnings)}")
    for e in errors:
        print(f"  ERROR  {e}")
    for w in warnings:
        print(f"  WARN   {w}")
    if errors:
        print("FAIL: cpp dataset has validation errors")
        return 1
    if warnings and args.strict:
        print("FAIL: cpp dataset has warnings (--strict)")
        return 1
    print("OK: cpp dataset validates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
