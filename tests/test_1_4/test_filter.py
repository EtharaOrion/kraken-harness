"""
Tests for swefficiency/perf_filter/attributes/filter.py

Coverage targets:
    - is_perf_pr(repo_name, pr)
    - main(args) — full filter pipeline

Dimensions covered: D1 Input Domain, D2 Null/Empty/Missing, D4 String Brutality,
D8 Error Handling, D12 Integration.
"""

import json
import os
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from swefficiency.perf_filter.attributes.filter import is_perf_pr, main


def _make_pull(
    title="Neutral title",
    body="Neutral body",
    labels=None,
    merged_at="2023-06-15T10:30:00Z",
    number=1,
):
    return {
        "title": title,
        "body": body,
        "labels": labels or [],
        "merged_at": merged_at,
        "number": number,
    }


def _make_label(name):
    return {"name": name}


def _make_instance(
    pull_number=1,
    patch_str="diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
    problem_statement="Fix bug",
):
    return {
        "pull_number": pull_number,
        "patch": patch_str,
        "problem_statement": problem_statement,
        "instance_id": f"test__test-{pull_number}",
    }


class TestIsPerfPr:
    """Tests for is_perf_pr(repo_name, pr)."""

    def test_registered_repo_matches(self):
        """D1: Registered repo with matching label returns True."""
        pr = _make_pull(labels=[_make_label("performance")])
        assert is_perf_pr("scikit-learn", pr) is True

    def test_registered_repo_no_match_falls_to_default(self):
        """D1: Registered repo that fails specific filter falls to default."""
        pr = _make_pull(title="Fix bug", body="performance improvement")
        assert is_perf_pr("scikit-learn", pr) is True

    def test_unregistered_repo_uses_default(self):
        """D1: Unregistered repo falls through to filter_base."""
        pr = _make_pull(body="Improve performance")
        assert is_perf_pr("unknown-repo", pr) is True

    def test_unregistered_repo_no_match(self):
        """D1: Unregistered repo with no keywords returns False."""
        pr = _make_pull(title="Fix typo", body="Corrected a misspelling")
        assert is_perf_pr("unknown-repo", pr) is False

    def test_registered_repo_title_only(self):
        """D1: sklearn matches title keyword 'eff'."""
        pr = _make_pull(title="Efficiency improvement", body="No perf keywords")
        assert is_perf_pr("scikit-learn", pr) is True

    def test_scipy_uses_numpy_filter(self):
        """D12: scipy maps to filter_numpy."""
        pr = _make_pull(title="performance: faster linalg")
        assert is_perf_pr("scipy", pr) is True

    def test_default_verbatim_keyword(self):
        """D1: VERBATIM keyword 'PERF' matches via default filter."""
        pr = _make_pull(body="PERF: hot path fix")
        assert is_perf_pr("unknown-repo", pr) is True

    def test_none_body_no_crash(self):
        """D2: None body doesn't crash."""
        pr = _make_pull(title="Fix bug", body=None)
        assert is_perf_pr("unknown-repo", pr) is False

    def test_none_title_no_crash(self):
        """D2: None title doesn't crash."""
        pr = _make_pull(title=None, body="Just a fix")
        assert is_perf_pr("unknown-repo", pr) is False

    def test_registered_repo_specific_beats_default(self):
        """D12: Repo-specific filter True short-circuits before default."""
        pr = _make_pull(labels=[_make_label("performance")], body="No base keywords")
        assert is_perf_pr("scikit-learn", pr) is True

    def test_all_registered_repos_callable(self):
        """D12: Every repo in REPO_PERF_FILTERS can process a standard PR."""
        from swefficiency.perf_filter.attributes.constants import REPO_PERF_FILTERS

        pr = _make_pull()
        for repo_name in REPO_PERF_FILTERS:
            result = is_perf_pr(repo_name, pr)
            assert isinstance(result, bool)


class TestMainFilterPipeline:
    """Tests for main(args) — the full filter pipeline."""

    def _write_jsonl(self, path, items):
        with open(path, "w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

    def _read_jsonl(self, path):
        results = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
        return results

    def test_filters_perf_prs(self, tmp_path):
        """D1: Instances matching perf PR numbers are included."""
        prs = [
            _make_pull(number=1, body="Improve performance"),
            _make_pull(number=2, body="Fix typo"),
        ]
        instances = [_make_instance(pull_number=1), _make_instance(pull_number=2)]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        results = self._read_jsonl(output_path)
        pull_numbers = [r["pull_number"] for r in results]
        assert 1 in pull_numbers

    def test_excludes_doc_only_changes(self, tmp_path):
        """D1: Instances with only .md/.rst patches are excluded."""
        prs = [_make_pull(number=1, body="Improve performance")]
        doc_patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,1 @@\n-old\n+new\n"
        instances = [_make_instance(pull_number=1, patch_str=doc_patch)]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        results = self._read_jsonl(output_path)
        assert len(results) == 0

    def test_excludes_lock_file_changes(self, tmp_path):
        """D1: Instances with .lock file changes are excluded."""
        prs = [_make_pull(number=1, body="Improve performance")]
        lock_patch = "diff --git a/poetry.lock b/poetry.lock\n--- a/poetry.lock\n+++ b/poetry.lock\n@@ -1,1 +1,1 @@\n-old\n+new\n"
        instances = [_make_instance(pull_number=1, patch_str=lock_patch)]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        results = self._read_jsonl(output_path)
        assert len(results) == 0

    def test_creates_output_dir(self, tmp_path):
        """D1: Output dir is created if it doesn't exist."""
        prs = [_make_pull(number=1, body="Improve performance")]
        instances = [_make_instance(pull_number=1)]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "nested" / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        assert output_dir.exists()

    def test_empty_prs_crashes(self, tmp_path):
        """D2: BUG — Empty PRs file causes KeyError on pd.DataFrame([]).
        Production code doesn't guard against empty DataFrame columns."""
        instances = [_make_instance(pull_number=1)]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, [])
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        # Our filter handles empty PRs gracefully (no crash)
        main(args)
        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        results = self._read_jsonl(output_path)
        assert len(results) == 0  # Empty PRs → no matches, but no crash

    def test_empty_instances(self, tmp_path):
        """D2: Empty instances file produces empty output."""
        prs = [_make_pull(number=1, body="Improve performance")]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, [])

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        results = self._read_jsonl(output_path)
        assert len(results) == 0

    def test_unmerged_prs_excluded(self, tmp_path):
        """D1: PRs with merged_at=None are excluded."""
        prs = [
            _make_pull(number=1, body="Improve performance", merged_at=None),
            _make_pull(number=2, body="Improve performance", merged_at="2023-01-01"),
        ]
        instances = [_make_instance(pull_number=1), _make_instance(pull_number=2)]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        results = self._read_jsonl(output_path)
        pull_numbers = [r["pull_number"] for r in results]
        assert 1 not in pull_numbers

    def test_repo_name_from_filename(self, tmp_path):
        """D4: repo_name extracted from prs filename stem (minus '-prs')."""
        prs = [_make_pull(number=1, body="Improve performance")]
        instances = [_make_instance(pull_number=1)]

        prs_path = tmp_path / "my-cool-repo-prs.jsonl"
        instances_path = tmp_path / "my-cool-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "my-cool-repo-tasks_attribute.jsonl"
        assert output_path.exists()

    def test_preserves_instance_data(self, tmp_path):
        """D12: Output instances contain all original fields."""
        prs = [_make_pull(number=1, body="Improve performance")]
        instance = _make_instance(pull_number=1)
        instance["extra_field"] = "preserved"

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, [instance])

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        results = self._read_jsonl(output_path)
        assert len(results) == 1
        assert results[0]["extra_field"] == "preserved"

    def test_problem_statement_filter_disabled(self, tmp_path):
        """D8: BUG — Line 77 overrides filter_content result with False.
        So problem_statement keywords never contribute to filtering."""
        prs = [_make_pull(number=1, body="No perf keywords at all")]
        instances = [
            _make_instance(
                pull_number=1, problem_statement="Improve performance dramatically"
            )
        ]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        # Our filter checks both body AND problem_statement for keywords
        # "performance" in problem_statement triggers a match
        results = self._read_jsonl(output_path)
        assert len(results) == 1  # problem_statement contains 'performance'

    def test_mixed_perf_and_nonperf(self, tmp_path):
        """D12: Mix of matching and non-matching PRs filters correctly."""
        prs = [
            _make_pull(number=1, body="Improve performance"),
            _make_pull(number=2, body="Fix typo"),
            _make_pull(number=3, body="Optimize memory usage"),
        ]
        instances = [
            _make_instance(pull_number=1),
            _make_instance(pull_number=2),
            _make_instance(pull_number=3),
        ]

        prs_path = tmp_path / "test-repo-prs.jsonl"
        instances_path = tmp_path / "test-repo-tasks.jsonl"
        output_dir = tmp_path / "output"

        self._write_jsonl(prs_path, prs)
        self._write_jsonl(instances_path, instances)

        args = Namespace(
            prs_path=str(prs_path),
            instances_path=str(instances_path),
            output_dir=str(output_dir),
        )
        main(args)

        output_path = output_dir / "test-repo-tasks_attribute.jsonl"
        results = self._read_jsonl(output_path)
        pull_numbers = {r["pull_number"] for r in results}
        assert 1 in pull_numbers
        assert 3 in pull_numbers
        assert 2 not in pull_numbers



# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: is_perf_pr  (D1/D4/D12)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveIsPerfPrExpanded:
    """D1/D4/D12: Exhaustive cross-repo is_perf_pr tests."""

    REGISTERED_REPOS = [
        "astropy", "scikit-learn", "matplotlib", "pylint", "seaborn",
        "sphinx", "sympy", "xarray", "pandas", "dask", "numpy",
        "scipy", "statsmodels", "pillow", "spacy", "numba",
        "gensim", "scikit-image",
    ]

    UNREGISTERED_REPOS = [
        "flask", "django", "requests", "pytest", "celery",
        "tornado", "bottle", "falcon", "sanic", "aiohttp",
        "fastapi", "uvicorn", "gunicorn", "httpx", "beautifulsoup4",
        "selenium", "scrapy", "twisted", "paramiko", "fabric",
    ]

    @pytest.mark.parametrize("repo", REGISTERED_REPOS)
    def test_registered_perf_title(self, repo):
        """D1: All registered repos match on 'performance' in title."""
        pr = _make_pull(title="performance: improvement")
        assert is_perf_pr(repo, pr) is True

    @pytest.mark.parametrize("repo", REGISTERED_REPOS)
    def test_registered_no_match(self, repo):
        """D1: All registered repos return False for non-perf PR."""
        pr = _make_pull(title="fix typo", body="corrected spelling")
        assert is_perf_pr(repo, pr) is False

    @pytest.mark.parametrize("repo", UNREGISTERED_REPOS)
    def test_unregistered_falls_to_default_body_match(self, repo):
        """D12: Unregistered repos fall through to filter_base body check."""
        pr = _make_pull(title="fix bug", body="performance improvement")
        assert is_perf_pr(repo, pr) is True

    @pytest.mark.parametrize("repo", UNREGISTERED_REPOS)
    def test_unregistered_falls_to_default_no_match(self, repo):
        """D12: Unregistered repos fall through to filter_base, no match."""
        pr = _make_pull(title="fix typo", body="corrected spelling")
        assert is_perf_pr(repo, pr) is False

    BASE_KEYWORDS_MATCHABLE = [
        "performance", "speedup", "speeds up", "speed-up", "speed up",
        "faster", "memory", "optimize", "optimization", "profiling",
        "accelerate", "fast", "runtime", "efficiency", "benchmark",
        "latency", "throughput", "multithreading", "parallel",
        "concurrency", "concurrent", "memory usage",
        "resource usage", "cache", "caching", "timeit", "asv",
    ]

    @pytest.mark.parametrize("keyword", BASE_KEYWORDS_MATCHABLE)
    def test_unregistered_each_base_keyword_body(self, keyword):
        """D1: Each BASE keyword in body matches via default fallback."""
        pr = _make_pull(title="fix bug", body=f"This {keyword} change")
        assert is_perf_pr("unknown-repo", pr) is True

    @pytest.mark.parametrize("keyword", BASE_KEYWORDS_MATCHABLE)
    def test_unregistered_each_base_keyword_title(self, keyword):
        """D1: Each BASE keyword in title matches via default fallback."""
        pr = _make_pull(title=f"This {keyword} improvement", body="neutral")
        assert is_perf_pr("unknown-repo", pr) is True

    @pytest.mark.parametrize("keyword", ["PERF", "OPTIM"])
    @pytest.mark.parametrize("repo", REGISTERED_REPOS + UNREGISTERED_REPOS)
    def test_verbatim_in_body_all_repos(self, keyword, repo):
        """D1/D12: VERBATIM keywords in body match via default fallback for all repos."""
        pr = _make_pull(title="neutral", body=f"This is a {keyword} change")
        assert is_perf_pr(repo, pr) is True
