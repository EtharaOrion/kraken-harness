"""
Shared fixtures for Stages 1-2 tests (Data Collection + Performance Filter).

All fixtures are actively used by test classes. No dead code.
"""

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── Pull Request Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def minimal_pull():
    """A minimal merged GitHub pull request dict with all required fields."""
    return {
        "number": 42,
        "title": "Fix slow serialization",
        "body": "This PR fixes a performance issue in the serializer.",
        "merged_at": "2023-06-15T10:30:00Z",
        "created_at": "2023-06-10T08:00:00Z",
        "updated_at": "2023-06-15T10:30:00Z",
        "user": {"login": "dev123"},
        "labels": [],
        "head": {"sha": "abc123def456"},
        "base": {"sha": "base123sha456", "ref": "main"},
        "commits": 1,
        "additions": 10,
        "deletions": 5,
        "changed_files": 2,
        "diff_url": "https://github.com/owner/repo/pull/42.diff",
        "html_url": "https://github.com/owner/repo/pull/42",
        "commits_url": "https://api.github.com/repos/owner/repo/pulls/42/commits",
    }


@pytest.fixture
def unmerged_pull(minimal_pull):
    """A pull request that was not merged (merged_at=None)."""
    return {**minimal_pull, "merged_at": None}


@pytest.fixture
def pull_with_perf_labels(minimal_pull):
    """A pull request with performance-related labels."""
    return {
        **minimal_pull,
        "labels": [
            {"name": "performance"},
            {"name": "enhancement"},
        ],
    }


@pytest.fixture
def pull_with_perf_title(minimal_pull):
    """A pull request with performance keywords in the title."""
    return {**minimal_pull, "title": "Optimize database query performance"}


@pytest.fixture
def pull_with_no_perf(minimal_pull):
    """A pull request with no performance indicators at all."""
    return {
        **minimal_pull,
        "title": "Add user profile page",
        "body": "This adds a new user profile page with avatar support.",
        "labels": [{"name": "feature"}],
    }


@pytest.fixture
def pull_fixing_issue(minimal_pull):
    """A pull request that references issues with fix/close/resolve keywords."""
    return {
        **minimal_pull,
        "title": "Fixes #123 slow query",
        "body": "Closes #456 and resolves #789.",
    }


# ─── Instance Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def valid_instance():
    """A valid task instance with all fields populated."""
    return {
        "repo": "owner/repo",
        "pull_number": 42,
        "instance_id": "owner__repo-42",
        "issue_numbers": ["123"],
        "base_commit": "base123sha456",
        "patch": (
            "diff --git a/file.py b/file.py\n"
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-old\n"
            "+new\n"
        ),
        "test_patch": (
            "diff --git a/tests/test_file.py b/tests/test_file.py\n"
            "--- a/tests/test_file.py\n"
            "+++ b/tests/test_file.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-old_test\n"
            "+new_test\n"
        ),
        "problem_statement": "The serializer is too slow for large payloads.",
        "hints_text": "Consider using a faster JSON library.",
        "created_at": "2023-06-10T08:00:00Z",
    }


@pytest.fixture
def instance_no_patch(valid_instance):
    return {**valid_instance, "patch": None}


@pytest.fixture
def instance_empty_patch(valid_instance):
    return {**valid_instance, "patch": ""}


@pytest.fixture
def instance_no_test_patch(valid_instance):
    return {**valid_instance, "test_patch": None}


@pytest.fixture
def instance_empty_test_patch(valid_instance):
    return {**valid_instance, "test_patch": ""}


@pytest.fixture
def instance_whitespace_test_patch(valid_instance):
    return {**valid_instance, "test_patch": "   \n  \t  "}


# ─── Diff / Patch Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def simple_diff():
    """A simple unified diff touching one non-test file."""
    return textwrap.dedent("""\
        diff --git a/src/module.py b/src/module.py
        --- a/src/module.py
        +++ b/src/module.py
        @@ -10,7 +10,7 @@
         def slow_func():
        -    time.sleep(1)
        +    pass
    """)


@pytest.fixture
def diff_with_test():
    """A diff that includes both source and test file changes."""
    return textwrap.dedent("""\
        diff --git a/src/module.py b/src/module.py
        --- a/src/module.py
        +++ b/src/module.py
        @@ -10,7 +10,7 @@
         def slow_func():
        -    time.sleep(1)
        +    pass
        diff --git a/tests/test_module.py b/tests/test_module.py
        --- a/tests/test_module.py
        +++ b/tests/test_module.py
        @@ -5,7 +5,7 @@
         def test_slow_func():
        -    assert slow_func() is None
        +    assert slow_func() == 0
    """)


# ─── Mock Repo / API Fixtures ────────────────────────────────────────────────


@pytest.fixture
def mock_repo():
    """A mock Repo object for testing without real GitHub API calls."""
    repo = MagicMock()
    repo.owner = "psf"
    repo.name = "requests"
    repo.repo = MagicMock()
    repo.token = "fake-token-123"
    repo.api = MagicMock()
    return repo


@pytest.fixture
def mock_ghapi():
    """A mocked GhApi instance with common return values."""
    api = MagicMock()
    api.repos.get.return_value = MagicMock()
    api.pulls.list.return_value = []
    api.pulls.get.return_value = {}
    api.issues.list_comments.return_value = []
    api.issues.get.return_value = {"title": "Bug report", "body": "Details here"}
    return api


# ─── Temporary File Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def tmp_jsonl_file(tmp_path):
    """Factory fixture: create a temporary JSONL file from a list of dicts."""

    def _create(data_list, filename="test.jsonl"):
        filepath = tmp_path / filename
        with open(filepath, "w", encoding="utf-8") as f:
            for item in data_list:
                f.write(json.dumps(item) + "\n")
        return filepath

    return _create


@pytest.fixture
def empty_jsonl(tmp_path):
    """An empty JSONL file."""
    filepath = tmp_path / "empty.jsonl"
    filepath.touch()
    return filepath


# ─── Environment Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def env_with_github_tokens(monkeypatch):
    """Set GITHUB_TOKENS environment variable with 3 tokens."""
    monkeypatch.setenv("GITHUB_TOKENS", "token1,token2,token3")


@pytest.fixture
def env_with_single_token(monkeypatch):
    """Set a single GITHUB_TOKEN."""
    monkeypatch.setenv("GITHUB_TOKEN", "single-token-123")


@pytest.fixture
def env_no_tokens(monkeypatch):
    """Ensure no GitHub tokens are set in the environment."""
    monkeypatch.delenv("GITHUB_TOKENS", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


# ─── Performance Keyword Fixtures ────────────────────────────────────────────


@pytest.fixture
def perf_keywords():
    """Standard performance keywords from BASE_PERF_KEYWORDS."""
    return [
        "performance",
        "speedup",
        "faster",
        "optimize",
        "memory",
        "benchmark",
        "latency",
        "throughput",
        "efficiency",
        "cache",
    ]


@pytest.fixture
def non_perf_keywords():
    """Keywords that should NOT trigger the performance filter."""
    return [
        "bugfix",
        "feature",
        "documentation",
        "typo",
        "readme",
        "license",
        "ci",
        "test",
        "refactor",
        "cleanup",
    ]
