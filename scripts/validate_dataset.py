#!/usr/bin/env python3
"""Validate dataset JSONL before inference.

Checks every field required for Docker image building and inference.
Exit code 0 = all valid, non-zero = errors found.

Usage:
    python scripts/validate_dataset.py artifacts/final/new-repos-inference-ready.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_INSTANCE_ID_RE = re.compile(r"^[a-z0-9_]+-[a-z0-9_]+-\d+$")
_REPO_RE = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$")

# Fields that MUST be present and non-empty for image building + inference
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

# Fields that must exist (can be empty)
REQUIRED_PRESENT = [
    "test_patch",
    "hints_text",
    "created_at",
    "environment_setup_commit",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
]

# SWE-fficiency specific fields needed for inference
SWEFF_REQUIRED_NON_EMPTY = [
    "workload",
    "python_version",
    "install_cmd",
]


def validate_instance(idx: int, record: dict) -> list[str]:
    """Validate a single dataset record. Returns list of error strings."""
    errors: list[str] = []
    iid = record.get("instance_id", f"<missing-at-line-{idx + 1}>")

    # Required non-empty fields
    for field in REQUIRED_NON_EMPTY:
        val = record.get(field)
        if val is None:
            errors.append(f"[{iid}] Missing required field: {field}")
        elif isinstance(val, str) and not val.strip():
            errors.append(f"[{iid}] Empty required field: {field}")

    # Required present fields (can be empty)
    for field in REQUIRED_PRESENT:
        if field not in record:
            errors.append(f"[{iid}] Missing field: {field}")

    warnings: list[str] = []
    for field in WARN_IF_EMPTY:
        val = record.get(field, "")
        if isinstance(val, str) and not val.strip():
            warnings.append(f"[{iid}] WARN: {field} is empty (not required for inference)")

    # SWE-fficiency specific
    for field in SWEFF_REQUIRED_NON_EMPTY:
        val = record.get(field)
        if val is None:
            errors.append(f"[{iid}] Missing SWE-fficiency field: {field}")
        elif isinstance(val, str) and not val.strip():
            errors.append(f"[{iid}] Empty SWE-fficiency field: {field}")

    # Structural validations
    instance_id = record.get("instance_id", "")
    if instance_id and not _INSTANCE_ID_RE.match(instance_id.lower()):
        # Relaxed: just check it's non-empty and has reasonable chars
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
            f"[{iid}] base_commit is not a valid 40-char SHA: {base_commit!r}"
        )

    # Version should be a non-empty string
    version = record.get("version", "")
    if isinstance(version, str) and version:
        pass  # OK
    elif isinstance(version, (int, float)):
        pass  # OK (numeric version like 3.0)
    else:
        errors.append(f"[{iid}] version is invalid: {version!r}")

    # pip_packages should be a list
    pip_packages = record.get("pip_packages")
    if pip_packages is not None and not isinstance(pip_packages, list):
        errors.append(f"[{iid}] pip_packages should be a list, got {type(pip_packages).__name__}")

    # covering_tests should be a list
    covering_tests = record.get("covering_tests")
    if covering_tests is not None and not isinstance(covering_tests, list):
        errors.append(f"[{iid}] covering_tests should be a list, got {type(covering_tests).__name__}")

    # patch should contain diff markers
    patch = record.get("patch", "")
    if isinstance(patch, str) and patch and "diff" not in patch.lower():
        errors.append(f"[{iid}] patch doesn't look like a unified diff")

    # test_patch should contain diff markers
    test_patch = record.get("test_patch", "")
    if isinstance(test_patch, str) and test_patch and "diff" not in test_patch.lower():
        errors.append(f"[{iid}] test_patch doesn't look like a unified diff")

    # workload should contain code matching the instance language. Phase 1 cpp
    # pipeline emits Google Benchmark .cc — gate on language=='cpp'.
    workload = record.get("workload", "")
    language = record.get("language", "python")
    if isinstance(workload, str) and workload:
        if language == "cpp":
            if "BENCHMARK" not in workload and "#include" not in workload:
                errors.append(f"[{iid}] workload doesn't look like C++ Google Benchmark code")
        else:
            if "def " not in workload and "import " not in workload:
                errors.append(f"[{iid}] workload doesn't look like Python code")

    return errors, warnings


def validate_dataset(jsonl_path: Path) -> tuple[int, list[str], list[str]]:
    """Validate all records in a JSONL file.

    Returns (record_count, errors).
    """
    if not jsonl_path.exists():
        return 0, [f"Dataset file not found: {jsonl_path}"], []

    records: list[dict] = []
    parse_errors: list[str] = []

    with open(jsonl_path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                parse_errors.append(f"Line {i + 1}: JSON parse error: {e}")

    if parse_errors:
        return len(records), parse_errors, []

    if not records:
        return 0, ["Dataset is empty"], []

    all_errors: list[str] = []
    all_warnings: list[str] = []

    # Check for duplicate instance_ids
    seen_ids: set[str] = set()
    for rec in records:
        iid = rec.get("instance_id", "")
        if iid in seen_ids:
            all_errors.append(f"Duplicate instance_id: {iid}")
        seen_ids.add(iid)

    # Check for duplicate repos+base_commits (same repo+commit = same starting point)
    repo_commits: dict[str, list[str]] = {}
    for rec in records:
        key = f"{rec.get('repo', '')}@{rec.get('base_commit', '')}"
        repo_commits.setdefault(key, []).append(rec.get("instance_id", ""))

    # Validate each record
    for i, rec in enumerate(records):
        errors, warnings = validate_instance(i, rec)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    return len(records), all_errors, all_warnings


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_dataset.py <dataset.jsonl>")
        return 1

    jsonl_path = Path(sys.argv[1])
    count, errors, warnings = validate_dataset(jsonl_path)

    print(f"Dataset: {jsonl_path}")
    print(f"Records: {count}")

    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  WARN: {w}")

    if not errors:
        print(f"\nPASS: All {count} records valid")
        return 0

    print(f"\nFAILED: {len(errors)} validation errors:\n")
    for err in errors:
        print(f"  ERROR: {err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
