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

"""Utility functions for the performance filter pipeline.

Handles:
  - Unified diff parsing (extract_edits)
  - JSONL streaming and reading
  - File classification (test, doc, CI, deps, benchmark, lock)
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Generator

import pandas as pd

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DIFF PARSING
# ─────────────────────────────────────────────────────────────────────────────


def extract_edits(patch: str) -> list[tuple[str, str, str]]:
    """
    Parse a unified diff and extract (source_path, dest_path, diff_content) per file.

    Handles:
      - Normal file edits
      - Binary file diffs ("Binary files ... differ")
      - File renames ("rename from ... rename to ...")
      - New file mode
      - Deleted file mode
      - Git binary patch format

    Returns empty list for empty/None patches instead of crashing.
    """
    if not patch or not patch.strip():
        return []

    split_by_diff_git = patch.split("diff --git")
    edits = []

    if len(split_by_diff_git) <= 1:
        logger.warning("Patch does not contain any 'diff --git' markers")
        return []

    for diff_git in split_by_diff_git[1:]:
        diff_git = diff_git.strip()
        if not diff_git:
            continue

        lines = diff_git.split("\n")
        header_line = lines[0]  # " a/path/to/file b/path/to/file"

        # Parse source and dest from the header
        # Format: " a/path/file b/path/file"
        parts = header_line.split()
        if len(parts) < 2:
            logger.debug(f"Skipping malformed diff header: {header_line[:100]}")
            continue

        # Extract paths, stripping a/ and b/ prefixes
        source_path = parts[0]
        dest_path = parts[1]
        if source_path.startswith("a/"):
            source_path = source_path[2:]
        if dest_path.startswith("b/"):
            dest_path = dest_path[2:]

        # Handle special cases in remaining lines
        remaining_lines = lines[1:]
        remaining_content = "\n".join(remaining_lines)

        # Skip binary diffs (no useful content to analyze)
        if "Binary files" in remaining_content and "differ" in remaining_content:
            edits.append((source_path, dest_path, ""))
            continue

        # Handle rename-only (no content change)
        if any(line.startswith("rename from") for line in remaining_lines):
            # Extract actual paths from rename headers if present
            for line in remaining_lines:
                if line.startswith("rename from "):
                    source_path = line[len("rename from "):]
                elif line.startswith("rename to "):
                    dest_path = line[len("rename to "):]

        edits.append((source_path, dest_path, remaining_content))

    return edits


# ─────────────────────────────────────────────────────────────────────────────
# JSONL I/O
# ─────────────────────────────────────────────────────────────────────────────


def read_jsonl(jsonl_path: str, to_df=False):
    """Read JSONL file. Logs and counts errors instead of silently swallowing them."""
    if to_df:
        return pd.read_json(jsonl_path, lines=True)

    jsonl_items = []
    errors = 0
    with open(jsonl_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                jsonl_items.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"JSON decode error at {jsonl_path}:{line_num}: {e}")
            except UnicodeDecodeError as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"Unicode error at {jsonl_path}:{line_num}: {e}")

    if errors > 0:
        logger.warning(f"Total read errors in {jsonl_path}: {errors} (of {line_num} lines)")

    return jsonl_items


def stream_jsonl(jsonl_path: str) -> Generator[dict, None, None]:
    """Stream JSONL line-by-line for memory-efficient processing at scale.

    Use this instead of read_jsonl() when processing millions of records.
    """
    errors = 0
    with open(jsonl_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                errors += 1
                if errors <= 10:
                    logger.warning(f"Stream error at {jsonl_path}:{line_num}: {e}")

    if errors > 0:
        logger.warning(f"Total stream errors in {jsonl_path}: {errors}")


def write_jsonl(items: list[dict], output_path: str):
    """Write list of dicts to JSONL file."""
    with open(output_path, "w") as f:
        for item in items:
            print(json.dumps(item), file=f, flush=False)


# ─────────────────────────────────────────────────────────────────────────────
# FILE CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

# Test file detection patterns (for Criterion 1: reject PRs that modify tests)
TEST_PATH_PATTERNS = [
    r"(^|/)tests?/",             # test/ or tests/ directory
    r"(^|/)testing/",            # testing/ directory
    r"(^|/)test_[^/]+\.py$",     # test_*.py files
    r"(^|/)[^/]*_test\.py$",     # *_test.py files
    r"(^|/)conftest\.py$",       # pytest conftest
    r"(^|/)fixtures?/",          # fixtures/ directory
]
_TEST_PATH_RE = re.compile("|".join(TEST_PATH_PATTERNS))

# Documentation file extensions and paths
DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc", ".asciidoc"}
DOC_PATH_PATTERNS = [
    r"(^|/)docs?/",              # doc/ or docs/ directory
    r"(^|/)documentation/",
    r"(^|/)CHANGES",
    r"(^|/)CHANGELOG",
    r"(^|/)HISTORY",
    r"(^|/)NEWS",
    r"(^|/)AUTHORS",
    r"(^|/)CONTRIBUTORS",
]
_DOC_PATH_RE = re.compile("|".join(DOC_PATH_PATTERNS), re.IGNORECASE)

# CI/automation file patterns
CI_FILE_PATTERNS = [
    ".github/workflows/",
    ".github/actions/",
    ".circleci/",
    ".travis.yml",
    "Jenkinsfile",
    "azure-pipelines",
    ".gitlab-ci",
    "tox.ini",
    "noxfile.py",
    ".pre-commit-config.yaml",
]

# Dependency file patterns — use EXACT filename or suffix matching, not substring
DEPS_FILE_EXACT = {
    "setup.cfg",
    "setup.py",
    "pyproject.toml",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "pdm.lock",
}
DEPS_FILE_SUFFIXES = [
    "requirements.txt",
    "requirements.in",
    "constraints.txt",
]
DEPS_FILE_PREFIXES = [
    "requirements",  # requirements-dev.txt, requirements_test.txt, etc.
]

# Benchmark/performance test files (separate from unit tests)
BENCHMARK_PATH_PATTERNS = [
    r"(^|/)benchmarks?/",
    r"(^|/)bench_[^/]+\.py$",
    r"(^|/)[^/]*_bench\.py$",
    r"(^|/)asv_bench/",
    r"(^|/)perf/",
]
_BENCHMARK_PATH_RE = re.compile("|".join(BENCHMARK_PATH_PATTERNS))


def is_test_file(file_path: str) -> bool:
    """Check if a file path is a test file (Criterion 1).

    Returns True for test_*.py, *_test.py, files in tests/ directories, conftest.py, etc.
    Does NOT flag benchmark files as test files (those are separate).
    """
    # Benchmark files are NOT test files for our purposes
    if _BENCHMARK_PATH_RE.search(file_path):
        return False
    return bool(_TEST_PATH_RE.search(file_path))


def is_doc_file(file_path: str) -> bool:
    """Check if a file is documentation (expanded from original .md/.rst only)."""
    ext = Path(file_path).suffix.lower()
    if ext in DOC_EXTENSIONS:
        return True
    if _DOC_PATH_RE.search(file_path):
        return True
    return False


def is_ci_file(file_path: str) -> bool:
    """Check if file is CI/automation configuration."""
    return any(pattern in file_path for pattern in CI_FILE_PATTERNS)


def is_deps_file(file_path: str) -> bool:
    """Check if file is a dependency specification.

    Uses exact filename matching and suffix/prefix checks to avoid
    false positives like 'requirements_parser.py'.
    """
    basename = Path(file_path).name

    # Exact match
    if basename in DEPS_FILE_EXACT:
        return True

    # Suffix match (e.g., ends with requirements.txt)
    if any(basename.endswith(suffix) for suffix in DEPS_FILE_SUFFIXES):
        return True

    # Prefix match — but ONLY for .txt/.in files (avoid requirements_parser.py)
    if any(basename.startswith(prefix) for prefix in DEPS_FILE_PREFIXES):
        ext = Path(basename).suffix.lower()
        if ext in {".txt", ".in", ".cfg", ""}:
            return True

    return False


def is_benchmark_file(file_path: str) -> bool:
    """Check if file is a benchmark/performance test (not excluded, just classified)."""
    return bool(_BENCHMARK_PATH_RE.search(file_path))


def has_lock_file_change(file_path: str) -> bool:
    """Check if file is a lockfile."""
    return file_path.endswith(".lock")


def is_config_file(file_path: str) -> bool:
    """Check if file is a configuration file (Makefile, Dockerfile, etc.)."""
    basename = Path(file_path).name.lower()
    config_names = {
        "makefile", "dockerfile", ".dockerignore", ".gitignore",
        ".editorconfig", ".flake8", ".pylintrc", ".mypy.ini",
        "mypy.ini", "pyrightconfig.json", ".coveragerc",
    }
    config_extensions = {".cfg", ".ini", ".toml", ".yaml", ".yml"}

    if basename in config_names:
        return True
    ext = Path(file_path).suffix.lower()
    # Only flag as config if it's in root-level config directories
    if ext in config_extensions and "/" not in file_path:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# GITHUB TOKENS
# ─────────────────────────────────────────────────────────────────────────────


def get_gh_tokens(env_var_name="GITHUB_TOKENS"):
    gh_tokens = os.environ.get(env_var_name, "").split(",")
    return [t.strip() for t in gh_tokens if t.strip()]
