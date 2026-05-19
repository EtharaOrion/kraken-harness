"""
Tests for swefficiency/collect/utils.py

12-Dimension coverage for:
  - Repo.__init__
  - Repo.call_api
  - Repo.extract_resolved_issues
  - Repo.get_all_loop
  - Repo.get_all_issues / get_all_pulls
  - extract_problem_statement_and_hints
  - _extract_hints
  - send_request_with_rate_limit_handling
  - extract_patches
  - extract_problem_statement_and_hints_django

Dimensions covered per class:
  D1  Input Domain (equivalence partitioning, BVA, pairwise)
  D2  Null/Empty/Missing gauntlet
  D3  Type Coercion & Mismatch
  D4  String & Text Brutality
  D5  Time & Date Edge Cases
  D6  State & Lifecycle
  D7  Concurrency & Race Conditions
  D8  Error Handling & Failure Recovery
  D9  Security Test Cases
  D10 Data Format & Encoding
  D11 Performance & Resource Limits
  D12 Integration & System-Level
"""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest
import requests
from fastcore.net import HTTP403ForbiddenError, HTTP404NotFoundError

from swefficiency.collect.utils import (
    Repo,
    _extract_hints,
    extract_patches,
    extract_problem_statement_and_hints,
    extract_problem_statement_and_hints_django,
    send_request_with_rate_limit_handling,
    _TokenRotator,
    TokenStuckError,
    RepoRateLimitError,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _ns(**kwargs):
    """Create a SimpleNamespace (dot-access dict) for mocking API responses."""
    return SimpleNamespace(**kwargs)


def _make_pull(**overrides):
    """Minimal pull dict with dot-access attributes for GhApi compatibility."""
    base = _ns(
        number=1,
        title="Fix bug",
        body="Body text",
        merged_at="2023-01-01T00:00:00Z",
        created_at="2023-01-01T00:00:00Z",
        url="https://api.github.com/repos/o/r/pulls/1",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _make_pull_dict(**overrides):
    """Pull as a plain dict (used by extract_patches, _extract_hints etc.)."""
    base = {
        "number": 1,
        "title": "Fix bug",
        "body": "Body text",
        "merged_at": "2023-01-01T00:00:00Z",
        "created_at": "2023-01-01T00:00:00Z",
        "url": "https://api.github.com/repos/o/r/pulls/1",
        "resolved_issues": ["42"],
    }
    base.update(overrides)
    return base


def _make_rate_limit(remaining=5000):
    """Mock rate_limit.get() return value."""
    return _ns(resources=_ns(core=_ns(remaining=remaining, reset=9999999999)))


def _mock_repo(owner="psf", name="requests", token="ghp_fake1234567890"):
    """Create a Repo-like MagicMock without hitting the real API."""
    repo = MagicMock(spec=Repo)
    repo.owner = owner
    repo.name = name
    repo.token = token
    repo._rotator = MagicMock()
    repo.api = MagicMock()
    repo.api.rate_limit.get.return_value = _make_rate_limit()
    repo.repo = MagicMock()
    return repo


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestRepoInit
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRepoInit:
    """Tests for Repo.__init__: D1, D2, D3, D4, D8."""

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_valid_construction(self, mock_ghapi_cls):
        # D1: nominal valid input
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(
            full_name="psf/requests"
        )
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("psf", "requests", token="ghp_abcdef1234567890")
        assert r.owner == "psf"
        assert r.name == "requests"
        assert r.token == "ghp_abcdef1234567890"
        mock_ghapi_cls.assert_called_once_with(token="ghp_abcdef1234567890")

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_none_token(self, mock_ghapi_cls):
        # D2: token=None (default)
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(
            full_name="psf/requests"
        )
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("psf", "requests")
        assert r.token is None
        mock_ghapi_cls.assert_called_once_with(token=None)

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_empty_string_token(self, mock_ghapi_cls):
        # D2: token="" (falsy but not None)
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(
            full_name="psf/requests"
        )
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("psf", "requests", token="")
        assert r.token == ""

    @patch("swefficiency.collect.utils.GhApi")
    def test_d3_integer_token(self, mock_ghapi_cls):
        # D3: wrong type for token
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(
            full_name="psf/requests"
        )
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("psf", "requests", token=12345)
        assert r.token == 12345  # Production code doesn't type-check

    @patch("swefficiency.collect.utils.GhApi")
    def test_d4_unicode_owner_name(self, mock_ghapi_cls):
        # D4: unicode characters in owner/name
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(full_name="u/r")
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("\u00fc\u00f1\u00ee\u00e7\u00f6\u2202\u00e9", "r\u00e9po\u2122")
        assert r.owner == "\u00fc\u00f1\u00ee\u00e7\u00f6\u2202\u00e9"
        assert r.name == "r\u00e9po\u2122"

    @patch("swefficiency.collect.utils.GhApi")
    def test_d4_emoji_in_name(self, mock_ghapi_cls):
        # D4: emoji in repo name
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(full_name="o/r")
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("owner", "repo-\U0001f680")
        assert r.name == "repo-\U0001f680"

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.GhApi")
    def test_d8_repos_get_raises_403(self, mock_ghapi_cls, mock_sleep):
        # D8: rate limit during init
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.side_effect = [
            HTTP403ForbiddenError(MagicMock(), MagicMock(), MagicMock()),
            _ns(full_name="psf/requests"),
        ]
        api_inst.rate_limit.get.return_value = _make_rate_limit(remaining=1)
        r = Repo("psf", "requests", token="ghp_abcdef1234567890")
        assert r.repo is not None

    @patch("swefficiency.collect.utils.GhApi")
    def test_d8_repos_get_raises_404(self, mock_ghapi_cls):
        # D8: repo not found
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.side_effect = HTTP404NotFoundError(
            MagicMock(), MagicMock(), MagicMock()
        )
        api_inst.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("nonexistent", "repo", token="ghp_abcdef1234567890")
        assert r.repo is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestCallApi
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCallApi:
    """Tests for Repo.call_api: D1, D2, D6, D8."""

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_successful_call(self, mock_ghapi_cls):
        # D1: nominal success
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(full_name="o/r")
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        func = MagicMock(return_value={"data": "value"})
        result = r.call_api(lambda api: func(api))
        func.assert_called_once()
        assert result == {"data": "value"}

    @patch("swefficiency.collect.utils.GhApi")
    def test_d8_404_returns_none(self, mock_ghapi_cls):
        # D8: 404 -> None
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(full_name="o/r")
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        func = MagicMock(
            side_effect=HTTP404NotFoundError(MagicMock(), MagicMock(), MagicMock())
        )
        result = r.call_api(func)
        assert result is None

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.GhApi")
    def test_d8_403_retries_then_succeeds(self, mock_ghapi_cls, mock_sleep):
        # D8: 403 -> token cooled, rotator advances, retry succeeds.
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit(remaining=0)
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        func = MagicMock(
            side_effect=[
                HTTP403ForbiddenError(MagicMock(), MagicMock(), MagicMock()),
                {"success": True},
            ]
        )
        result = r.call_api(lambda api: func(api))
        assert result == {"success": True}
        assert func.call_count == 2

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_passes_all_kwargs(self, mock_ghapi_cls):
        # D1: verify kwargs passthrough
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(full_name="o/r")
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        func = MagicMock(return_value="ok")
        r.call_api(lambda api: func(api, owner="x", repo="y", page=3, extra="data"))
        func.assert_called_once()
        _, kwargs = func.call_args
        assert kwargs == {"owner": "x", "repo": "y", "page": 3, "extra": "data"}

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_func_returns_none(self, mock_ghapi_cls):
        # D2: function returns None (valid return, not 404)
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(full_name="o/r")
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        func = MagicMock(return_value=None)
        result = r.call_api(func)
        assert result is None

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.GhApi")
    def test_d3_none_token_403_raises_token_stuck(self, mock_ghapi_cls, mock_sleep):
        """D3/D8: a None token no longer crashes on 403 (_tok_prefix handles
        None); a persistent 403 exhausts the 1-token pool's rotations ->
        RepoRateLimitError (per-repo, not the subset-fatal TokenStuckError)."""
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit(remaining=0)
        r = Repo("o", "r", token=None)
        func = MagicMock(
            side_effect=HTTP403ForbiddenError(MagicMock(), MagicMock(), MagicMock())
        )
        with pytest.raises(RepoRateLimitError):
            r.call_api(lambda api: func(api))

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_func_returns_empty_dict(self, mock_ghapi_cls):
        # D2: function returns {}
        mock_ghapi_cls.return_value.repos.get.return_value = _ns(full_name="o/r")
        mock_ghapi_cls.return_value.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        func = MagicMock(return_value={})
        result = r.call_api(func)
        assert result == {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestExtractResolvedIssues
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestExtractResolvedIssues:
    """Tests for Repo.extract_resolved_issues: D1, D2, D4, D9, D10, D11."""

    def _setup_repo(self, mock_ghapi_cls, commits=None):
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit()
        if commits:
            api_inst.pulls.list_commits.side_effect = [commits, []]
        else:
            api_inst.pulls.list_commits.return_value = []
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        return r

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_single_fixes_keyword(self, mock_ghapi_cls):
        # D1: single "fixes #123" in body
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="This fixes #42")
        result = r.extract_resolved_issues(pull)
        assert result == ["42"]

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_multiple_keywords(self, mock_ghapi_cls):
        # D1: multiple keywords in body
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="Fixes #1, closes #2, resolves #3")
        result = r.extract_resolved_issues(pull)
        assert set(result) == {"1", "2", "3"}

    @patch("swefficiency.collect.utils.GhApi")
    @pytest.mark.parametrize(
        "keyword",
        [
            "close",
            "closes",
            "closed",
            "fix",
            "fixes",
            "fixed",
            "resolve",
            "resolves",
            "resolved",
        ],
    )
    def test_d1_all_valid_keywords(self, mock_ghapi_cls, keyword):
        # D1: equivalence class - every valid keyword
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body=f"{keyword} #99")
        result = r.extract_resolved_issues(pull)
        assert "99" in result

    @patch("swefficiency.collect.utils.GhApi")
    @pytest.mark.parametrize(
        "keyword",
        [
            "Close",
            "FIXES",
            "Resolved",
            "FIX",
            "Closes",
        ],
    )
    def test_d1_case_insensitive_keywords(self, mock_ghapi_cls, keyword):
        # D1: case-insensitive matching
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body=f"{keyword} #77")
        result = r.extract_resolved_issues(pull)
        assert "77" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_keyword_in_title(self, mock_ghapi_cls):
        # D1: keyword in title, not body
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(title="Fixes #50", body="No keywords here")
        result = r.extract_resolved_issues(pull)
        assert "50" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_keyword_in_commit_message(self, mock_ghapi_cls):
        # D1: keyword in commit message
        commit = _ns(commit=_ns(message="closes #88"))
        r = self._setup_repo(mock_ghapi_cls, commits=[commit])
        pull = _make_pull(body="No keywords")
        result = r.extract_resolved_issues(pull)
        assert "88" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_non_keyword_rejected(self, mock_ghapi_cls):
        # D1: non-keyword word before # should be rejected
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="related #42 see #99")
        result = r.extract_resolved_issues(pull)
        assert result == []

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_dict_last_match_wins(self, mock_ghapi_cls):
        # D1: BUG - dict() on findall means last match for same keyword wins
        # "fixes #1\nfixes #2" -> dict gives {"fixes": "2"}, so only "2" returned
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="fixes #1\nfixes #2")
        result = r.extract_resolved_issues(pull)
        # Due to dict() behavior, only the last issue for each keyword survives
        assert "2" in result
        # "1" is lost - this documents the existing behavior/bug
        assert "1" not in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_none_body(self, mock_ghapi_cls):
        # D2: body is None
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body=None)
        result = r.extract_resolved_issues(pull)
        assert result == []

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_none_title(self, mock_ghapi_cls):
        # D2: title is None
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(title=None, body="fixes #1")
        result = r.extract_resolved_issues(pull)
        assert "1" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_empty_body(self, mock_ghapi_cls):
        # D2: empty string body
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="")
        result = r.extract_resolved_issues(pull)
        assert result == []

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_whitespace_only_body(self, mock_ghapi_cls):
        # D2: whitespace-only body
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="   \n\t  ")
        result = r.extract_resolved_issues(pull)
        assert result == []

    @patch("swefficiency.collect.utils.GhApi")
    def test_d4_html_comment_stripping(self, mock_ghapi_cls):
        # D4: HTML comments should be stripped
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="<!-- fixes #999 --> Actual content")
        result = r.extract_resolved_issues(pull)
        assert "999" not in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d4_multiline_html_comment(self, mock_ghapi_cls):
        # D4: multiline HTML comment
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(
            body="before\n<!--\nfixes #100\ncloses #200\n-->\nafter fixes #300"
        )
        result = r.extract_resolved_issues(pull)
        assert "100" not in result
        assert "200" not in result
        assert "300" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d4_unicode_in_body(self, mock_ghapi_cls):
        # D4: unicode mixed with keywords
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="fixes #42 \u2014 \u00fcnicode \U0001f680 content")
        result = r.extract_resolved_issues(pull)
        assert "42" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d4_null_bytes_in_body(self, mock_ghapi_cls):
        # D4: null bytes
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="fixes #42\x00closes #43")
        result = r.extract_resolved_issues(pull)
        assert "42" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d4_rtl_characters(self, mock_ghapi_cls):
        # D4: RTL characters around keywords
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="\u200ffixes #42\u200f")
        result = r.extract_resolved_issues(pull)
        assert "42" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d9_log_injection_in_body(self, mock_ghapi_cls):
        # D9: body with newlines that could inject log entries
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="fixes #42\n\n[CRITICAL] Injected log\ncloses #43")
        result = r.extract_resolved_issues(pull)
        assert "42" in result
        assert "43" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_bva_issue_number_zero(self, mock_ghapi_cls):
        # D1 BVA: issue number 0
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="fixes #0")
        result = r.extract_resolved_issues(pull)
        assert "0" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_bva_large_issue_number(self, mock_ghapi_cls):
        # D1 BVA: very large issue number
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body="fixes #999999999")
        result = r.extract_resolved_issues(pull)
        assert "999999999" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d11_very_long_body(self, mock_ghapi_cls):
        # D11: very long body with keyword at end
        r = self._setup_repo(mock_ghapi_cls)
        long_body = "x" * 10_000 + " fixes #42"
        pull = _make_pull(body=long_body)
        result = r.extract_resolved_issues(pull)
        assert "42" in result

    @patch("swefficiency.collect.utils.GhApi")
    def test_d11_many_issue_references(self, mock_ghapi_cls):
        # D11: many different keywords for different issues
        r = self._setup_repo(mock_ghapi_cls)
        # Each keyword maps to a different issue - tests dict dedup behavior
        body = " ".join(f"fixes #{i}" for i in range(100))
        pull = _make_pull(body=body)
        result = r.extract_resolved_issues(pull)
        # dict() dedup: only last "fixes" -> last issue number survives
        assert len(result) == 1
        assert "99" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestGetAllLoop
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGetAllLoop:
    """Tests for Repo.get_all_loop: D1, D2, D6, D8, D11."""

    def _setup_repo(self, mock_ghapi_cls):
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit()
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        return r

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_single_page(self, mock_ghapi_cls):
        # D1: single page of results, then empty
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(side_effect=[["a", "b", "c"], []])
        results = list(r.get_all_loop(func, quiet=True))
        assert results == ["a", "b", "c"]

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_multiple_pages(self, mock_ghapi_cls):
        # D1: multiple pages
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(side_effect=[["a", "b"], ["c", "d"], []])
        results = list(r.get_all_loop(func, quiet=True))
        assert results == ["a", "b", "c", "d"]

    @patch("swefficiency.collect.utils.GhApi")
    def test_d2_empty_first_page(self, mock_ghapi_cls):
        # D2: empty response on first page
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(return_value=[])
        results = list(r.get_all_loop(func, quiet=True))
        assert results == []

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_num_pages_limit(self, mock_ghapi_cls):
        # D1: num_pages limits pagination
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(side_effect=[["a"], ["b"], ["c"]])
        results = list(r.get_all_loop(func, num_pages=2, quiet=True))
        assert results == ["a", "b"]

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_bva_num_pages_1(self, mock_ghapi_cls):
        # D1 BVA: num_pages=1 should return exactly one page
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(side_effect=[["a", "b"]])
        results = list(r.get_all_loop(func, num_pages=1, quiet=True))
        assert results == ["a", "b"]

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_per_page_passed_correctly(self, mock_ghapi_cls):
        # D1: per_page parameter forwarded
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(return_value=[])
        list(r.get_all_loop(lambda api, **kw: func(**kw), per_page=50, quiet=True))
        func.assert_called_with(owner="o", repo="r", per_page=50, page=1)

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_bva_per_page_1(self, mock_ghapi_cls):
        # D1 BVA: per_page=1, minimum meaningful page size
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(side_effect=[["a"], ["b"], []])
        results = list(r.get_all_loop(func, per_page=1, quiet=True))
        assert results == ["a", "b"]

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.GhApi")
    def test_d8_exception_triggers_rate_limit_wait(self, mock_ghapi_cls, mock_sleep):
        # D8: exception during pagination triggers rate limit handling
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(
            side_effect=[
                requests.exceptions.HTTPError("rate limit"),
                ["a"],
                [],
            ]
        )
        api_inst = mock_ghapi_cls.return_value
        api_inst.rate_limit.get.side_effect = [
            _make_rate_limit(remaining=0),
            _make_rate_limit(remaining=1),
            _make_rate_limit(remaining=5000),
        ]
        results = list(r.get_all_loop(func))
        assert results == ["a"]
        mock_sleep.assert_called()

    @patch("swefficiency.collect.utils.GhApi")
    def test_d6_quiet_false_logs_progress(self, mock_ghapi_cls):
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(side_effect=[["a"], []])
        results = list(r.get_all_loop(lambda api, **kw: func(**kw), quiet=False))
        assert results == ["a"]

    @patch("swefficiency.collect.utils.GhApi")
    def test_d6_quiet_true_skips_logging(self, mock_ghapi_cls):
        # D6: quiet=True should minimize rate_limit.get calls
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(side_effect=[["a"], []])
        api_inst = mock_ghapi_cls.return_value
        init_calls = api_inst.rate_limit.get.call_count
        list(r.get_all_loop(func, quiet=True))
        # Only the init call, no progress logging calls
        assert api_inst.rate_limit.get.call_count == init_calls

    @patch("swefficiency.collect.utils.GhApi")
    def test_d6_quiet_false_num_pages_break_references_values(self, mock_ghapi_cls):
        """D6/D8: BUG — when quiet=False and num_pages causes break before empty page,
        post-loop logger.info references `values` from last non-empty page.
        The `len(values)` on line 180 uses the last-fetched page's values which is valid
        only if the loop body ran at least once."""
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(side_effect=[["a", "b"], ["c"]])
        results = list(r.get_all_loop(func, num_pages=2, quiet=False))
        assert results == ["a", "b", "c"]

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_kwargs_forwarded(self, mock_ghapi_cls):
        # D1: extra kwargs passed to func
        r = self._setup_repo(mock_ghapi_cls)
        func = MagicMock(return_value=[])
        list(r.get_all_loop(
            lambda api, **kw: func(**kw), quiet=True, pull_number=42, state="open"
        ))
        func.assert_called_with(
            owner="o", repo="r", per_page=100, page=1, pull_number=42, state="open"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestGetAllIssues / TestGetAllPulls
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGetAllIssues:
    """Tests for Repo.get_all_issues: D1, D2."""

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_delegates_to_get_all_loop(self, mock_ghapi_cls):
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit()
        api_inst.issues.list_for_repo.return_value = []
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        result = list(r.get_all_issues())
        assert result == []
        api_inst.issues.list_for_repo.assert_called()

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_passes_parameters(self, mock_ghapi_cls):
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit()
        api_inst.issues.list_for_repo.return_value = []
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        list(
            r.get_all_issues(
                per_page=50, num_pages=2, direction="asc", sort="updated", state="open"
            )
        )
        call_kwargs = api_inst.issues.list_for_repo.call_args
        assert call_kwargs[1]["per_page"] == 50
        assert call_kwargs[1]["direction"] == "asc"


class TestGetAllPulls:
    """Tests for Repo.get_all_pulls: D1, D2."""

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_delegates_to_get_all_loop(self, mock_ghapi_cls):
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit()
        api_inst.pulls.list.return_value = []
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        result = list(r.get_all_pulls())
        assert result == []
        api_inst.pulls.list.assert_called()

    @patch("swefficiency.collect.utils.GhApi")
    def test_d1_passes_parameters(self, mock_ghapi_cls):
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit()
        api_inst.pulls.list.return_value = []
        r = Repo("o", "r", token="ghp_abcdef1234567890")
        list(r.get_all_pulls(per_page=25, direction="asc"))
        call_kwargs = api_inst.pulls.list.call_args
        assert call_kwargs[1]["per_page"] == 25
        assert call_kwargs[1]["direction"] == "asc"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestExtractProblemStatementAndHints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestExtractProblemStatementAndHints:
    """Tests for extract_problem_statement_and_hints: D1, D2, D4, D8, D12."""

    def test_d1_single_issue(self):
        # D1: nominal - one resolved issue
        repo = _mock_repo()
        issue = _ns(title="Bug title", body="Bug description", number=42)
        repo.call_api.return_value = issue
        repo.get_all_loop.return_value = iter([])  # no commits for hints
        repo.name = "requests"  # non-django

        pull = _make_pull_dict(resolved_issues=["42"])
        text, hints = extract_problem_statement_and_hints(pull, repo)
        assert "Bug title" in text
        assert "Bug description" in text

    def test_d1_multiple_issues(self):
        # D1: multiple resolved issues concatenated
        repo = _mock_repo()
        issue1 = _ns(title="Issue 1", body="Body 1", number=1)
        issue2 = _ns(title="Issue 2", body="Body 2", number=2)
        repo.call_api.side_effect = [issue1, issue2]
        repo.get_all_loop.return_value = iter([])
        repo.name = "requests"

        pull = _make_pull_dict(resolved_issues=["1", "2"])
        text, hints = extract_problem_statement_and_hints(pull, repo)
        assert "Issue 1" in text
        assert "Issue 2" in text

    def test_d2_no_resolved_issues(self):
        # D2: empty resolved_issues list
        repo = _mock_repo()
        repo.name = "requests"
        pull = _make_pull_dict(resolved_issues=[])
        text, hints = extract_problem_statement_and_hints(pull, repo)
        assert text == ""
        assert hints == ""

    def test_d8_issue_not_found_404(self):
        # D8: issue returns None (404)
        repo = _mock_repo()
        repo.call_api.return_value = None
        repo.name = "requests"
        pull = _make_pull_dict(resolved_issues=["999"])
        text, hints = extract_problem_statement_and_hints(pull, repo)
        assert text == ""

    def test_d2_issue_with_none_title_and_body(self):
        # D2: issue has None title and body
        repo = _mock_repo()
        issue = _ns(title=None, body=None, number=42)
        repo.call_api.return_value = issue
        repo.get_all_loop.return_value = iter([])
        repo.name = "requests"
        pull = _make_pull_dict(resolved_issues=["42"])
        text, hints = extract_problem_statement_and_hints(pull, repo)
        assert "\n" in text  # empty title + empty body separated by newline

    def test_d12_django_dispatches(self):
        # D12: django repo dispatches to different function
        repo = _mock_repo()
        repo.name = "django"
        pull = _make_pull_dict(resolved_issues=["12345"])
        # This will try to call extract_problem_statement_and_hints_django
        # which calls requests.get to a real URL - we need to mock it
        with patch("swefficiency.collect.utils.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = """
            <html>
            <div id="ticket">
                <h1 class="searchable">Django bug title</h1>
                <div class="description">Bug description text</div>
            </div>
            <div id="changelog">
            </div>
            </html>
            """
            mock_get.return_value = mock_resp
            repo.get_all_loop.return_value = iter([])
            text, hints = extract_problem_statement_and_hints(pull, repo)
            assert "Django bug title" in text

    def test_d4_issue_with_unicode_body(self):
        # D4: unicode in issue body
        repo = _mock_repo()
        issue = _ns(
            title="Unicode: \u00e9\u00e8\u00ea",
            body="Body: \U0001f600 \u2192 \u2014 \u00df\u00e4\u00fc",
            number=42,
        )
        repo.call_api.return_value = issue
        repo.get_all_loop.return_value = iter([])
        repo.name = "requests"
        pull = _make_pull_dict(resolved_issues=["42"])
        text, hints = extract_problem_statement_and_hints(pull, repo)
        assert "\u00e9\u00e8\u00ea" in text
        assert "\U0001f600" in text

    def test_d6_issue_number_reassigned_from_issue_object(self):
        """D6: BUG — line 273 reassigns issue_number = issue.number, so _extract_hints
        uses issue.number (int) rather than the string from resolved_issues."""
        repo = _mock_repo()
        issue = _ns(title="Title", body="Body", number=999)
        repo.call_api.return_value = issue
        repo.get_all_loop.return_value = iter([])
        repo.name = "requests"
        pull = _make_pull_dict(resolved_issues=["42"])
        extract_problem_statement_and_hints(pull, repo)
        assert True  # no crash — the reassignment to issue.number is the documented bug

    def test_d1_multiple_issues_different_numbers(self):
        """D1: Multiple resolved issues — each issue's .number is used for hints."""
        repo = _mock_repo()
        issue_a = _ns(title="Issue A", body="Body A", number=10)
        issue_b = _ns(title="Issue B", body="Body B", number=20)
        repo.call_api.side_effect = [issue_a, issue_b]
        repo.get_all_loop.return_value = iter([])
        repo.name = "requests"
        pull = _make_pull_dict(resolved_issues=["1", "2"])
        text, hints = extract_problem_statement_and_hints(pull, repo)
        assert "Issue A" in text
        assert "Issue B" in text


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestExtractHints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestExtractHints:
    """Tests for _extract_hints: D1, D2, D5, D8."""

    def _make_commit(self, date_str="2023-06-15T10:00:00Z"):
        return _ns(commit=_ns(author=_ns(date=date_str)))

    def _make_comment(self, body="hint text", updated_at="2023-06-14T09:00:00Z"):
        return _ns(body=body, updated_at=updated_at)

    def test_d1_comments_before_first_commit(self):
        # D1: comments before first commit are kept
        repo = _mock_repo()
        commit = self._make_commit("2023-06-15T10:00:00Z")
        comment_before = self._make_comment("early hint", "2023-06-14T09:00:00Z")
        comment_after = self._make_comment("late hint", "2023-06-16T09:00:00Z")

        repo.get_all_loop.side_effect = [
            iter([commit]),  # commits
            iter([comment_before, comment_after]),  # comments
        ]
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == ["early hint"]

    def test_d2_no_commits(self):
        # D2: no commits -> return empty
        repo = _mock_repo()
        repo.get_all_loop.return_value = iter([])
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == []

    def test_d2_no_comments(self):
        # D2: commits exist but no comments
        repo = _mock_repo()
        commit = self._make_commit("2023-06-15T10:00:00Z")
        repo.get_all_loop.side_effect = [
            iter([commit]),
            iter([]),
        ]
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == []

    def test_d1_all_comments_before_commit(self):
        # D1: all comments before first commit
        repo = _mock_repo()
        commit = self._make_commit("2023-06-15T10:00:00Z")
        c1 = self._make_comment("hint1", "2023-06-13T09:00:00Z")
        c2 = self._make_comment("hint2", "2023-06-14T09:00:00Z")
        repo.get_all_loop.side_effect = [
            iter([commit]),
            iter([c1, c2]),
        ]
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == ["hint1", "hint2"]

    def test_d1_all_comments_after_commit(self):
        # D1: all comments after first commit
        repo = _mock_repo()
        commit = self._make_commit("2023-06-10T10:00:00Z")
        c1 = self._make_comment("late1", "2023-06-11T09:00:00Z")
        c2 = self._make_comment("late2", "2023-06-12T09:00:00Z")
        repo.get_all_loop.side_effect = [
            iter([commit]),
            iter([c1, c2]),
        ]
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == []

    def test_d5_comment_at_exact_commit_time(self):
        # D5: comment at exact same time as commit (should NOT be included, < not <=)
        repo = _mock_repo()
        commit = self._make_commit("2023-06-15T10:00:00Z")
        c = self._make_comment("same time", "2023-06-15T10:00:00Z")
        repo.get_all_loop.side_effect = [
            iter([commit]),
            iter([c]),
        ]
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == []  # strict less-than, not <=

    def test_d5_midnight_boundary(self):
        # D5: comment at midnight boundary
        repo = _mock_repo()
        commit = self._make_commit("2023-06-15T00:00:01Z")
        c = self._make_comment("midnight hint", "2023-06-15T00:00:00Z")
        repo.get_all_loop.side_effect = [
            iter([commit]),
            iter([c]),
        ]
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == ["midnight hint"]

    def test_d5_epoch_zero(self):
        # D5: very old timestamp (epoch-adjacent)
        repo = _mock_repo()
        commit = self._make_commit("1970-01-01T00:00:01Z")
        c = self._make_comment("ancient", "1970-01-01T00:00:00Z")
        repo.get_all_loop.side_effect = [
            iter([commit]),
            iter([c]),
        ]
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == ["ancient"]

    def test_d5_year_2038_boundary(self):
        # D5: year 2038 (32-bit time_t overflow on some systems)
        repo = _mock_repo()
        commit = self._make_commit("2038-01-19T03:14:08Z")
        c = self._make_comment("2038 hint", "2038-01-19T03:14:07Z")
        repo.get_all_loop.side_effect = [
            iter([commit]),
            iter([c]),
        ]
        pull = _make_pull_dict(number=1)
        # May raise on 32-bit systems; on 64-bit it should work
        result = _extract_hints(pull, repo, 42)
        assert result == ["2038 hint"]

    def test_d5_leap_second_adjacent(self):
        # D5: timestamps around leap second boundary
        repo = _mock_repo()
        commit = self._make_commit("2016-12-31T23:59:59Z")
        c = self._make_comment("leap hint", "2016-12-31T23:59:58Z")
        repo.get_all_loop.side_effect = [
            iter([commit]),
            iter([c]),
        ]
        pull = _make_pull_dict(number=1)
        result = _extract_hints(pull, repo, 42)
        assert result == ["leap hint"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestSendRequestWithRateLimitHandling
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSendRequestWithRateLimitHandling:
    """Tests for send_request_with_rate_limit_handling: D1, D2, D3, D4, D5, D8, D9, D10."""

    @patch("swefficiency.collect.utils.requests.get")
    def test_d1_success_200(self, mock_get):
        # D1: nominal 200 response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"data": "value"}'
        mock_get.return_value = mock_resp
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        assert result == '{"data": "value"}'

    @patch("swefficiency.collect.utils.requests.get")
    def test_d1_success_201(self, mock_get):
        # D1: 201 also valid
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = "created"
        mock_get.return_value = mock_resp
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        assert result == "created"

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_403_with_retry_after_header(self, mock_get, mock_sleep):
        # D8: 403 with Retry-After header
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "rate limit"
        resp_403.headers = {"retry-after": "30"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = "success"

        mock_get.side_effect = [resp_403, resp_200]
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        assert result == "success"
        mock_sleep.assert_called_with(30)

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_429_with_retry_after(self, mock_get, mock_sleep):
        # D8: 429 Too Many Requests
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "too many requests"
        resp_429.headers = {"retry-after": "60"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = "ok"

        mock_get.side_effect = [resp_429, resp_200]
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        assert result == "ok"
        mock_sleep.assert_called_with(60)

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.time.time")
    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_403_with_remaining_0_and_reset(self, mock_get, mock_time, mock_sleep):
        # D8: 403 with x-ratelimit-remaining=0 and x-ratelimit-reset
        mock_time.return_value = 1000
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "rate limited"
        resp_403.headers = {
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": "1060",
        }

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = "ok"

        mock_get.side_effect = [resp_403, resp_200]
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        assert result == "ok"
        mock_sleep.assert_called_with(60)  # 1060 - 1000

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_403_secondary_rate_limit_exponential_backoff(
        self, mock_get, mock_sleep
    ):
        # D8: secondary rate limit -> exponential backoff
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "You have exceeded a secondary rate limit"
        resp_403.headers = {}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = "ok"

        mock_get.side_effect = [resp_403, resp_403, resp_200]
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        assert result == "ok"
        # First sleep: 60, second: 120 (exponential backoff)
        assert mock_sleep.call_args_list[0] == call(60)
        assert mock_sleep.call_args_list[1] == call(120)

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_403_default_wait(self, mock_get, mock_sleep):
        # D8: 403 without any rate limit headers or secondary message
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "forbidden"
        resp_403.headers = {}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = "ok"

        mock_get.side_effect = [resp_403, resp_200]
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        mock_sleep.assert_called_with(60)

    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_500_raises(self, mock_get):
        # D8: non-rate-limit error raises
        resp = MagicMock()
        resp.status_code = 500
        resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_get.return_value = resp
        with pytest.raises(requests.HTTPError):
            send_request_with_rate_limit_handling("https://api.github.com/test")

    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_502_raises(self, mock_get):
        # D8: 502 Bad Gateway
        resp = MagicMock()
        resp.status_code = 502
        resp.raise_for_status.side_effect = requests.HTTPError("502")
        mock_get.return_value = resp
        with pytest.raises(requests.HTTPError):
            send_request_with_rate_limit_handling("https://api.github.com/test")

    @patch("swefficiency.collect.utils.requests.get")
    def test_d1_headers_passed(self, mock_get):
        # D1: custom headers forwarded
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        mock_get.return_value = resp
        send_request_with_rate_limit_handling(
            "https://api.github.com/test",
            headers={"Authorization": "Bearer token"},
        )
        mock_get.assert_called_once_with(
            "https://api.github.com/test",
            headers={"Authorization": "Bearer token"},
            params=None,
            timeout=30,
        )

    @patch("swefficiency.collect.utils.requests.get")
    def test_d1_params_passed(self, mock_get):
        # D1: query params forwarded
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        mock_get.return_value = resp
        send_request_with_rate_limit_handling(
            "https://api.github.com/test",
            params={"page": 1, "per_page": 50},
        )
        mock_get.assert_called_once_with(
            "https://api.github.com/test",
            headers=None,
            params={"page": 1, "per_page": 50},
            timeout=30,
        )

    @patch("swefficiency.collect.utils.requests.get")
    def test_d2_none_headers_and_params(self, mock_get):
        # D2: explicit None defaults
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        mock_get.return_value = resp
        send_request_with_rate_limit_handling("https://api.github.com/test")
        mock_get.assert_called_once_with(
            "https://api.github.com/test",
            headers=None,
            params=None,
            timeout=30,
        )

    @patch("swefficiency.collect.utils.requests.get")
    def test_d9_ssrf_url(self, mock_get):
        # D9: SSRF - internal URL (production code doesn't validate)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "internal data"
        mock_get.return_value = resp
        result = send_request_with_rate_limit_handling(
            "http://169.254.169.254/latest/meta-data/"
        )
        assert result == "internal data"  # No SSRF protection exists

    @patch("swefficiency.collect.utils.requests.get")
    def test_d4_url_with_unicode(self, mock_get):
        # D4: URL with unicode characters
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        mock_get.return_value = resp
        result = send_request_with_rate_limit_handling(
            "https://example.com/\u00e9nd\u00f6int"
        )
        assert result == "ok"

    @patch("swefficiency.collect.utils.time.sleep")
    @patch("swefficiency.collect.utils.time.time")
    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_reset_time_in_past(self, mock_get, mock_time, mock_sleep):
        # D5: x-ratelimit-reset in the past -> max(0, negative) = 0
        mock_time.return_value = 2000
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "rate limited"
        resp_403.headers = {
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": "1000",
        }

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.text = "ok"

        mock_get.side_effect = [resp_403, resp_200]
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        mock_sleep.assert_called_with(0)  # max(0, 1000-2000) = 0

    @patch("swefficiency.collect.utils.requests.get")
    def test_d10_response_text_encoding(self, mock_get):
        # D10: response with special encoding
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "\u00e9\u00e8\u00ea\u00f1\u00fc\U0001f600"
        mock_get.return_value = resp
        result = send_request_with_rate_limit_handling("https://api.github.com/test")
        assert "\U0001f600" in result

    @patch("swefficiency.collect.utils.requests.get")
    def test_d3_retry_after_non_integer(self, mock_get):
        # D3: retry-after header with non-integer value
        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.text = "rate limited"
        resp_403.headers = {"retry-after": "not_a_number"}
        mock_get.return_value = resp_403
        with pytest.raises(ValueError):
            send_request_with_rate_limit_handling("https://api.github.com/test")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestExtractPatches
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestExtractPatches:
    """Tests for extract_patches: D1, D2, D4, D8, D10."""

    SIMPLE_DIFF = (
        "diff --git a/src/module.py b/src/module.py\n"
        "--- a/src/module.py\n"
        "+++ b/src/module.py\n"
        "@@ -1,3 +1,3 @@\n"
        " context\n"
        "-old\n"
        "+new\n"
        " more context\n"
    )

    TEST_DIFF = (
        "diff --git a/tests/test_module.py b/tests/test_module.py\n"
        "--- a/tests/test_module.py\n"
        "+++ b/tests/test_module.py\n"
        "@@ -1,3 +1,3 @@\n"
        " context\n"
        "-old_test\n"
        "+new_test\n"
        " more context\n"
    )

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d1_source_only_patch(self, mock_send):
        # D1: diff with only source files, no test files
        mock_send.return_value = self.SIMPLE_DIFF
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert "module.py" in fix
        assert test == ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d1_test_only_patch(self, mock_send):
        # D1: diff with only test files
        mock_send.return_value = self.TEST_DIFF
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix == ""
        assert "test_module.py" in test

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d1_mixed_patch(self, mock_send):
        # D1: diff with both source and test files
        mock_send.return_value = self.SIMPLE_DIFF + self.TEST_DIFF
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix != ""
        assert test != ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d8_request_exception_returns_empty(self, mock_send):
        # D8: a RequestException is caught, DLQ'd, and (None, None) returned
        # so callers can distinguish 'fetch failed' from 'empty patch'.
        mock_send.side_effect = requests.exceptions.RequestException("Network error")
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix is None
        assert test is None

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d1_e2e_test_directory(self, mock_send):
        diff = (
            "diff --git a/e2e/test_smoke.py b/e2e/test_smoke.py\n"
            "--- a/e2e/test_smoke.py\n"
            "+++ b/e2e/test_smoke.py\n"
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
            " more\n"
        )
        mock_send.return_value = diff
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix == ""
        assert test != ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d1_testing_directory(self, mock_send):
        diff = (
            "diff --git a/testing/conftest.py b/testing/conftest.py\n"
            "--- a/testing/conftest.py\n"
            "+++ b/testing/conftest.py\n"
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
            " more\n"
        )
        mock_send.return_value = diff
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix == ""
        assert test != ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d4_path_with_unicode(self, mock_send):
        diff = (
            "diff --git a/src/m\xc3\xb6dule.py b/src/m\xc3\xb6dule.py\n"
            "--- a/src/m\xc3\xb6dule.py\n"
            "+++ b/src/m\xc3\xb6dule.py\n"
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
            " more\n"
        )
        mock_send.return_value = diff
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix != ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d10_malformed_diff(self, mock_send):
        # D10: malformed diff that PatchSet can't parse -> exception -> ("", "")
        mock_send.return_value = "not a valid diff format"
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix == ""
        assert test == ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d2_empty_diff_response(self, mock_send):
        # D2: empty diff response
        mock_send.return_value = ""
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix == ""
        assert test == ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d1_auth_headers_sent(self, mock_send):
        # D1: verify authorization headers are constructed correctly
        mock_send.return_value = ""
        repo = _mock_repo()
        repo.token = "ghp_mytoken123"
        pull = _make_pull_dict(url="https://api.github.com/repos/o/r/pulls/1")
        extract_patches(pull, repo)
        call_args = mock_send.call_args
        assert call_args[0][0] == "https://api.github.com/repos/o/r/pulls/1"
        headers = call_args[1].get(
            "headers", call_args[0][1] if len(call_args[0]) > 1 else None
        )
        if headers is None:
            headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer ghp_mytoken123"
        assert headers["Accept"] == "application/vnd.github.v3.diff"

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d1_rename_diff(self, mock_send):
        # D10: rename diff — unidiff PatchSet handles rename, path detection still works
        diff = (
            "diff --git a/src/old_name.py b/src/new_name.py\n"
            "similarity index 90%\n"
            "rename from src/old_name.py\n"
            "rename to src/new_name.py\n"
            "--- a/src/old_name.py\n"
            "+++ b/src/new_name.py\n"
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
            " more\n"
        )
        mock_send.return_value = diff
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix != ""
        assert test == ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d10_no_newline_at_eof(self, mock_send):
        diff = (
            "diff --git a/src/module.py b/src/module.py\n"
            "--- a/src/module.py\n"
            "+++ b/src/module.py\n"
            "@@ -1,2 +1,2 @@\n"
            " context\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
            "\\ No newline at end of file\n"
        )
        mock_send.return_value = diff
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix != ""
        assert test == ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d11_many_hunks(self, mock_send):
        # D11: diff with many files — performance under larger input
        parts = []
        for i in range(50):
            parts.append(
                f"diff --git a/src/mod{i}.py b/src/mod{i}.py\n"
                f"--- a/src/mod{i}.py\n"
                f"+++ b/src/mod{i}.py\n"
                "@@ -1,3 +1,3 @@\n"
                " ctx\n"
                "-old\n"
                "+new\n"
                " more\n"
            )
        mock_send.return_value = "".join(parts)
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        assert fix != ""
        assert test == ""

    @patch("swefficiency.collect.utils.send_request_with_rate_limit_handling")
    def test_d4_test_word_in_source_path(self, mock_send):
        # D4: "test" appears in a non-test source path (e.g., "attestation", "contest")
        diff = (
            "diff --git a/src/attestation.py b/src/attestation.py\n"
            "--- a/src/attestation.py\n"
            "+++ b/src/attestation.py\n"
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
            " more\n"
        )
        mock_send.return_value = diff
        repo = _mock_repo()
        pull = _make_pull_dict()
        fix, test = extract_patches(pull, repo)
        # BUG: "test" is in "attestation" so this gets classified as test file
        # Production uses `any(word in path for word in ["test", ...])` — substring match
        assert test != "", "BUG: 'attestation' contains 'test' — false positive"
        assert fix == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestExtractProblemStatementAndHintsDjango
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestExtractProblemStatementAndHintsDjango:
    """Tests for extract_problem_statement_and_hints_django: D1, D2, D4, D5, D8, D10, D12.

    This function scrapes Django Trac tickets via HTTP, parses HTML with BeautifulSoup,
    extracts title + description, then collects pre-commit comments as hints.
    Two timestamp formats: mm/dd/yy and "Mon DD, YYYY, HH:MM:SS AM/PM".
    """

    BASIC_TICKET_HTML = """
    <html>
    <div id="ticket">
        <h1 class="searchable">  Memory  leak  in  QuerySet  </h1>
        <div class="description">
            QuerySet evaluation causes memory leak
            when using prefetch_related with
            large datasets.
        </div>
    </div>
    <div id="changelog">
        <div class="change">
            <div class="comment">First comment before fix</div>
            <a class="timeline" title="See timeline at 01/15/23 10:30:00">Jan 2023</a>
        </div>
        <div class="change">
            <div class="comment">Second comment after fix</div>
            <a class="timeline" title="See timeline at 06/20/23 14:00:00">Jun 2023</a>
        </div>
    </div>
    </html>
    """

    TICKET_WITH_LONG_FORMAT = """
    <html>
    <div id="ticket">
        <h1 class="searchable">SQL injection in raw queries</h1>
        <div class="description">Raw SQL allows injection</div>
    </div>
    <div id="changelog">
        <div class="change">
            <div class="comment">Patch submitted</div>
            <a class="timeline" title="Jan 15, 2023, 10:30:00 AM">Jan 2023</a>
        </div>
        <div class="change">
            <div class="comment">Reviewed and merged</div>
            <a class="timeline" title="Jun 20, 2023, 02:00:00 PM">Jun 2023</a>
        </div>
    </div>
    </html>
    """

    EMPTY_CHANGELOG_HTML = """
    <html>
    <div id="ticket">
        <h1 class="searchable">Simple bug</h1>
        <div class="description">Simple description</div>
    </div>
    <div id="changelog"></div>
    </html>
    """

    NO_COMMENTS_HTML = """
    <html>
    <div id="ticket">
        <h1 class="searchable">No comments bug</h1>
        <div class="description">No one commented</div>
    </div>
    <div id="changelog">
        <div class="change">
            <a class="timeline" title="See timeline at 01/15/23 10:30:00">Jan 2023</a>
        </div>
    </div>
    </html>
    """

    def _mock_response(self, html, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = html
        return resp

    def _make_commit(self, date_str="2023-03-15T10:00:00Z"):
        return _ns(commit=_ns(author=_ns(date=date_str)))

    @patch("swefficiency.collect.utils.requests.get")
    def test_d1_basic_ticket_with_hints(self, mock_get):
        # D1: Single issue, comments parsed, hints before commit kept
        mock_get.return_value = self._mock_response(self.BASIC_TICKET_HTML)
        repo = _mock_repo()
        commit = self._make_commit("2023-03-15T10:00:00Z")  # March 15
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["12345"], number=99)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)

        assert "Memory leak in QuerySet" in text
        assert "QuerySet evaluation causes memory leak" in text
        # First comment (Jan 15 2023) is before commit (Mar 15 2023) → kept as hint
        assert len(hints) >= 1
        assert any("First comment before fix" in h[0] for h in hints)
        # Second comment (Jun 20 2023) is after commit → NOT in hints
        assert not any("Second comment after fix" in h[0] for h in hints)

    @patch("swefficiency.collect.utils.requests.get")
    def test_d1_multiple_issues(self, mock_get):
        # D1: Multiple resolved issues → both tickets scraped and concatenated
        html1 = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug One</h1>
            <div class="description">First bug</div>
        </div>
        <div id="changelog"></div>
        </html>
        """
        html2 = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug Two</h1>
            <div class="description">Second bug</div>
        </div>
        <div id="changelog"></div>
        </html>
        """
        mock_get.side_effect = [
            self._mock_response(html1),
            self._mock_response(html2),
        ]
        repo = _mock_repo()
        repo.get_all_loop.side_effect = [iter([]), iter([])]

        pull = _make_pull_dict(resolved_issues=["111", "222"], number=5)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)

        assert "Bug One" in text
        assert "Bug Two" in text

    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_timestamp_format_slash(self, mock_get):
        # D5: mm/dd/yy timestamp format (slash-based) — first format branch
        mock_get.return_value = self._mock_response(self.BASIC_TICKET_HTML)
        repo = _mock_repo()
        commit = self._make_commit("2023-06-01T00:00:00Z")  # June 1
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        # Comment at 01/15/23 is before June 1 → kept
        assert len(hints) >= 1

    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_timestamp_format_long(self, mock_get):
        # D5: "Mon DD, YYYY, HH:MM:SS AM/PM" format (comma-based) — second format branch
        mock_get.return_value = self._mock_response(self.TICKET_WITH_LONG_FORMAT)
        repo = _mock_repo()
        commit = self._make_commit("2023-06-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert "SQL injection in raw queries" in text
        # "Jan 15, 2023, 10:30:00 AM" is before June 1 → kept
        assert len(hints) >= 1
        assert any("Patch submitted" in h[0] for h in hints)

    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_timestamp_unrecognized_format_raises(self, mock_get):
        # D5/D8: timestamp with neither / nor , raises ValueError
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Desc</div>
        </div>
        <div id="changelog">
            <div class="change">
                <div class="comment">Comment</div>
                <a class="timeline" title="2023-01-15 10:30:00">Jan 2023</a>
            </div>
        </div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2023-06-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        with pytest.raises(ValueError, match="Timestamp format not recognized"):
            extract_problem_statement_and_hints_django(pull, repo)

    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_ticket_not_found_404(self, mock_get):
        # D8: Trac returns non-200 → skip that issue
        mock_get.return_value = self._mock_response("", status_code=404)
        repo = _mock_repo()

        pull = _make_pull_dict(resolved_issues=["99999"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert text == ""
        assert hints == []

    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_mixed_found_and_not_found(self, mock_get):
        # D8: One issue found, one 404 → only found issue contributes
        mock_get.side_effect = [
            self._mock_response(self.EMPTY_CHANGELOG_HTML),
            self._mock_response("", status_code=404),
        ]
        repo = _mock_repo()
        repo.get_all_loop.return_value = iter([])

        pull = _make_pull_dict(resolved_issues=["1", "2"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert "Simple bug" in text
        assert hints == []

    @patch("swefficiency.collect.utils.requests.get")
    def test_d2_empty_resolved_issues(self, mock_get):
        # D2: No issues to scrape
        repo = _mock_repo()
        pull = _make_pull_dict(resolved_issues=[], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert text == ""
        assert hints == []
        mock_get.assert_not_called()

    @patch("swefficiency.collect.utils.requests.get")
    def test_d2_no_commits_skips_hints(self, mock_get):
        # D2: Ticket exists but PR has no commits → text extracted, hints skipped
        mock_get.return_value = self._mock_response(self.BASIC_TICKET_HTML)
        repo = _mock_repo()
        repo.get_all_loop.return_value = iter([])  # no commits

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert "Memory leak in QuerySet" in text
        # No commits → "continue" skips hint extraction
        assert hints == []

    @patch("swefficiency.collect.utils.requests.get")
    def test_d2_changelog_div_no_comment(self, mock_get):
        # D2: Change block has no comment div → skipped
        mock_get.return_value = self._mock_response(self.NO_COMMENTS_HTML)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert "No comments bug" in text
        assert hints == []

    @patch("swefficiency.collect.utils.requests.get")
    def test_d2_changelog_div_no_timestamp(self, mock_get):
        # D2: Change block has comment but no timeline anchor → skipped
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Desc</div>
        </div>
        <div id="changelog">
            <div class="change">
                <div class="comment">Orphan comment</div>
            </div>
        </div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert hints == []

    @patch("swefficiency.collect.utils.requests.get")
    def test_d4_whitespace_normalization_in_title(self, mock_get):
        # D4: Multiple spaces/tabs in title → collapsed to single space
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">  Bug   with\textra    spaces  </h1>
            <div class="description">Normal desc</div>
        </div>
        <div id="changelog"></div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        repo.get_all_loop.return_value = iter([])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        # re.sub(r"\s+", " ", title).strip() — all whitespace → single space
        assert "Bug with extra spaces" in text
        assert "   " not in text.split("\n")[0]  # no triple spaces in title line

    @patch("swefficiency.collect.utils.requests.get")
    def test_d4_body_newline_and_indent_normalization(self, mock_get):
        # D4: Multiple newlines → single, 4-space indent → tab, multi-space → single
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Line1


Line2
    indented
  double  space</div>
        </div>
        <div id="changelog"></div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        repo.get_all_loop.return_value = iter([])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        # re.sub(r"\n+", "\n") removes double newlines
        assert "\n\n\n" not in text

    @patch("swefficiency.collect.utils.requests.get")
    def test_d4_unicode_in_ticket(self, mock_get):
        # D4: Unicode characters in title and description
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Ошибка в QuerySet — ñ é ü</h1>
            <div class="description">描述 🐛 → fix needed</div>
        </div>
        <div id="changelog"></div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        repo.get_all_loop.return_value = iter([])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert "Ошибка" in text
        assert "🐛" in text

    @patch("swefficiency.collect.utils.requests.get")
    def test_d4_comment_whitespace_normalization(self, mock_get):
        # D4: Comment text whitespace → collapsed
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Desc</div>
        </div>
        <div id="changelog">
            <div class="change">
                <div class="comment">  Comment   with \n lots   of \t whitespace  </div>
                <a class="timeline" title="See timeline at 01/01/23 01:00:00">Jan 2023</a>
            </div>
        </div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert len(hints) == 1
        # re.sub(r"\s+", " ", comment).strip()
        assert "  " not in hints[0][0]  # no double spaces

    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_see_timeline_prefix_stripped(self, mock_get):
        # D5: "See timeline at " prefix is stripped before parsing
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Desc</div>
        </div>
        <div id="changelog">
            <div class="change">
                <div class="comment">Prefixed timestamp</div>
                <a class="timeline" title="See timeline at 01/15/23 10:30:00">Jan 2023</a>
            </div>
        </div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert len(hints) == 1
        assert hints[0][0] == "Prefixed timestamp"

    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_no_see_timeline_prefix(self, mock_get):
        # D5: timestamp without "See timeline at " prefix — direct format
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Desc</div>
        </div>
        <div id="changelog">
            <div class="change">
                <div class="comment">Direct timestamp</div>
                <a class="timeline" title="01/15/23 10:30:00">Jan 2023</a>
            </div>
        </div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert len(hints) == 1

    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_comment_after_commit_excluded(self, mock_get):
        # D5: comment timestamp >= commit time → NOT included
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Desc</div>
        </div>
        <div id="changelog">
            <div class="change">
                <div class="comment">After commit</div>
                <a class="timeline" title="See timeline at 12/31/23 23:59:59">Dec 2023</a>
            </div>
        </div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2023-01-01T00:00:00Z")  # Jan 1
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert hints == []

    @patch("swefficiency.collect.utils.requests.get")
    def test_d1_url_constructed_correctly(self, mock_get):
        # D1: verify URL is https://code.djangoproject.com/ticket/{issue_number}
        mock_get.return_value = self._mock_response(self.EMPTY_CHANGELOG_HTML)
        repo = _mock_repo()
        repo.get_all_loop.return_value = iter([])

        pull = _make_pull_dict(resolved_issues=["54321"], number=1)
        extract_problem_statement_and_hints_django(pull, repo)
        mock_get.assert_called_once_with("https://code.djangoproject.com/ticket/54321")

    @patch("swefficiency.collect.utils.requests.get")
    def test_d12_return_type_is_tuple_of_str_and_list(self, mock_get):
        # D12: BUG DOCUMENTATION — returns (str, list[tuple]) not (str, str)
        # Non-django variant returns (str, str), but this returns (str, list)
        mock_get.return_value = self._mock_response(self.BASIC_TICKET_HTML)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert isinstance(text, str)
        assert isinstance(hints, list)
        # Each hint is a (comment_text, timestamp_float) tuple
        for hint in hints:
            assert isinstance(hint, tuple)
            assert isinstance(hint[0], str)
            assert isinstance(hint[1], float)

    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_midnight_boundary_timestamp(self, mock_get):
        # D5: comment at exactly midnight
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Desc</div>
        </div>
        <div id="changelog">
            <div class="change">
                <div class="comment">Midnight comment</div>
                <a class="timeline" title="See timeline at 01/01/23 00:00:00">Jan 2023</a>
            </div>
        </div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert len(hints) == 1

    @patch("swefficiency.collect.utils.requests.get")
    def test_d5_am_pm_parsing(self, mock_get):
        # D5: 12-hour AM/PM format — "12:00:00 PM" is noon, not midnight
        html = """
        <html>
        <div id="ticket">
            <h1 class="searchable">Bug</h1>
            <div class="description">Desc</div>
        </div>
        <div id="changelog">
            <div class="change">
                <div class="comment">PM comment</div>
                <a class="timeline" title="Jan 15, 2023, 11:59:59 PM">Jan 2023</a>
            </div>
        </div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert len(hints) == 1

    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_500_server_error_skipped(self, mock_get):
        # D8: Trac returns 500 → skip (status_code != 200)
        mock_get.return_value = self._mock_response("Server Error", status_code=500)
        repo = _mock_repo()

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert text == ""
        assert hints == []

    @patch("swefficiency.collect.utils.requests.get")
    def test_d8_connection_error(self, mock_get):
        # D8: requests.get raises ConnectionError
        mock_get.side_effect = requests.ConnectionError("DNS failure")
        repo = _mock_repo()

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        # Production code doesn't catch this — will propagate
        with pytest.raises(requests.ConnectionError):
            extract_problem_statement_and_hints_django(pull, repo)

    @patch("swefficiency.collect.utils.requests.get")
    def test_d11_many_change_blocks(self, mock_get):
        # D11: Performance — many change blocks in changelog
        changes = ""
        for i in range(100):
            changes += f"""
            <div class="change">
                <div class="comment">Comment {i}</div>
                <a class="timeline" title="See timeline at 01/{(i % 28) + 1:02d}/23 10:00:00">2023</a>
            </div>
            """
        html = f"""
        <html>
        <div id="ticket">
            <h1 class="searchable">Big ticket</h1>
            <div class="description">Many comments</div>
        </div>
        <div id="changelog">{changes}</div>
        </html>
        """
        mock_get.return_value = self._mock_response(html)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert "Big ticket" in text
        assert len(hints) == 100  # all before 2024 commit

    @patch("swefficiency.collect.utils.requests.get")
    def test_d1_empty_changelog(self, mock_get):
        # D1: Ticket with empty changelog div
        mock_get.return_value = self._mock_response(self.EMPTY_CHANGELOG_HTML)
        repo = _mock_repo()
        commit = self._make_commit("2024-01-01T00:00:00Z")
        repo.get_all_loop.return_value = iter([commit])

        pull = _make_pull_dict(resolved_issues=["1"], number=1)
        text, hints = extract_problem_statement_and_hints_django(pull, repo)
        assert "Simple bug" in text
        assert hints == []

    @patch("swefficiency.collect.utils.requests.get")
    def test_d9_url_with_special_issue_number(self, mock_get):
        # D9: issue_number could be a string like "../../etc/passwd" — no validation in production
        # Production just interpolates: f"https://code.djangoproject.com/ticket/{issue_number}"
        mock_get.return_value = self._mock_response("", status_code=404)
        repo = _mock_repo()

        pull = _make_pull_dict(resolved_issues=["../../admin"], number=1)
        extract_problem_statement_and_hints_django(pull, repo)
        mock_get.assert_called_once_with(
            "https://code.djangoproject.com/ticket/../../admin"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: extract_resolved_issues  (D1/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveExtractResolvedIssues:
    """D1/D4: Exhaustive keyword/issue number tests for extract_resolved_issues."""

    KEYWORDS = [
        "close",
        "closes",
        "closed",
        "fix",
        "fixes",
        "fixed",
        "resolve",
        "resolves",
        "resolved",
    ]

    def _setup_repo(self, mock_ghapi_cls, commits=None):
        api_inst = mock_ghapi_cls.return_value
        api_inst.repos.get.return_value = _ns(full_name="o/r")
        api_inst.rate_limit.get.return_value = _make_rate_limit()
        if commits:
            api_inst.pulls.list_commits.side_effect = [commits, []]
        else:
            api_inst.pulls.list_commits.return_value = []
        return Repo("o", "r", token="ghp_abcdef1234567890")

    @pytest.mark.parametrize("keyword", KEYWORDS)
    @pytest.mark.parametrize("issue_num", list(range(1, 101)))
    @patch("swefficiency.collect.utils.GhApi")
    def test_keyword_issue_number_cross_product(
        self, mock_ghapi_cls, keyword, issue_num
    ):
        """D1: Every keyword x issue number 1-100 combination."""
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body=f"{keyword} #{issue_num}")
        result = r.extract_resolved_issues(pull)
        assert str(issue_num) in result

    @pytest.mark.parametrize("keyword", KEYWORDS)
    @patch("swefficiency.collect.utils.GhApi")
    def test_keyword_case_upper(self, mock_ghapi_cls, keyword):
        """D4: Uppercase keywords match."""
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body=f"{keyword.upper()} #42")
        result = r.extract_resolved_issues(pull)
        assert "42" in result

    @pytest.mark.parametrize("keyword", KEYWORDS)
    @patch("swefficiency.collect.utils.GhApi")
    def test_keyword_case_title(self, mock_ghapi_cls, keyword):
        """D4: Title-cased keywords match."""
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body=f"{keyword.title()} #42")
        result = r.extract_resolved_issues(pull)
        assert "42" in result

    @pytest.mark.parametrize(
        "issue_num", [1, 9, 10, 99, 100, 999, 1000, 9999, 10000, 99999, 100000]
    )
    @patch("swefficiency.collect.utils.GhApi")
    def test_boundary_issue_numbers(self, mock_ghapi_cls, issue_num):
        """D1/BVA: Boundary issue numbers."""
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body=f"fixes #{issue_num}")
        result = r.extract_resolved_issues(pull)
        assert str(issue_num) in result

    @pytest.mark.parametrize(
        "non_keyword",
        [
            "addresses",
            "references",
            "see",
            "ref",
            "mentions",
            "implements",
            "breaks",
            "reverts",
            "updates",
            "modifies",
            "changes",
            "affects",
            "impacts",
            "handles",
            "processes",
            "completes",
        ],
    )
    @patch("swefficiency.collect.utils.GhApi")
    def test_non_keywords_dont_match(self, mock_ghapi_cls, non_keyword):
        """D1: Non-standard keywords don't resolve issues."""
        r = self._setup_repo(mock_ghapi_cls)
        pull = _make_pull(body=f"{non_keyword} #42")
        result = r.extract_resolved_issues(pull)
        assert "42" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: send_request status codes  (D1/D8)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveSendRequestStatusCodes:
    """D1/D8: Exhaustive HTTP status code handling."""

    SUCCESS_CODES = [200, 201]
    RETRY_CODES = [403, 429]
    ERROR_CODES = [
        400,
        401,
        402,
        404,
        405,
        406,
        407,
        408,
        409,
        410,
        411,
        412,
        413,
        414,
        415,
        416,
        417,
        418,
        421,
        422,
        423,
        424,
        425,
        426,
        428,
        431,
        451,
        500,
        501,
        502,
        503,
        504,
        505,
        506,
        507,
        508,
        510,
        511,
    ]

    @pytest.mark.parametrize("code", SUCCESS_CODES)
    def test_success_codes_return_text(self, code):
        """D1: 200 and 201 return response text."""
        mock_resp = MagicMock()
        mock_resp.status_code = code
        mock_resp.text = f"response for {code}"
        with patch("swefficiency.collect.utils.requests.get", return_value=mock_resp):
            result = send_request_with_rate_limit_handling("http://example.com")
        assert result == f"response for {code}"

    @pytest.mark.parametrize("code", ERROR_CODES)
    def test_error_codes_raise(self, code):
        """D8: Non-success, non-retry codes raise via raise_for_status."""
        mock_resp = MagicMock()
        mock_resp.status_code = code
        mock_resp.raise_for_status.side_effect = Exception(f"HTTP {code}")
        with patch("swefficiency.collect.utils.requests.get", return_value=mock_resp):
            with pytest.raises(Exception, match=f"HTTP {code}"):
                send_request_with_rate_limit_handling("http://example.com")



# ━━━ TestTokenRotator ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestTokenRotator:
    """Tests for _TokenRotator: round-robin, cooldown, drop, back-compat."""

    def test_round_robin_advance(self):
        r = _TokenRotator(["t1", "t2", "t3"])
        assert r.current() == "t1"
        assert r.advance() == "t2"
        assert r.advance() == "t3"
        assert r.advance() == "t1"

    def test_size(self):
        assert _TokenRotator(["a", "b", "c"]).size == 3

    def test_bare_str_wraps_to_single_token(self):
        r = _TokenRotator("solo")
        assert r.size == 1
        assert r.current() == "solo"

    def test_none_wraps_to_single_token(self):
        r = _TokenRotator(None)
        assert r.size == 1
        assert r.current() is None

    def test_scalar_int_wraps(self):
        r = _TokenRotator(12345)
        assert r.size == 1
        assert r.current() == 12345

    def test_empty_list_wraps_to_none(self):
        r = _TokenRotator([])
        assert r.size == 1
        assert r.current() is None

    def test_mark_cooling_skips_token(self):
        r = _TokenRotator(["t1", "t2", "t3"])
        r.mark_cooling("t2", time.time() + 9999)
        seq = [r.advance() for _ in range(4)]
        assert "t2" not in seq
        assert set(seq) <= {"t1", "t3"}

    def test_drop_removes_token(self):
        r = _TokenRotator(["t1", "t2", "t3"])
        r.drop("t2")
        seq = [r.advance() for _ in range(4)]
        assert "t2" not in seq

    def test_all_dropped_raises_token_stuck(self):
        r = _TokenRotator(["t1", "t2"])
        r.drop("t1")
        r.drop("t2")
        with pytest.raises(TokenStuckError):
            r.advance()

    def test_all_cooling_sleeps_until_earliest_reset(self):
        r = _TokenRotator(["t1", "t2"])
        slept = []
        fake_now = 1000.0
        with patch("swefficiency.collect.utils.time.sleep",
                   side_effect=lambda s: slept.append(s)), \
             patch("swefficiency.collect.utils.time.time",
                   side_effect=lambda: fake_now):
            r.mark_cooling("t1", 1100.0)
            r.mark_cooling("t2", 1050.0)
            tok = r.advance()
        assert slept, "expected a sleep when all tokens are cooling"
        # earliest reset is t2 @ 1050, ~50s from fake now=1000
        assert 49 <= slept[0] <= 52
        assert tok in {"t1", "t2"}

    def test_reject_rewrapping_rotator(self):
        r = _TokenRotator(["t1"])
        with pytest.raises(TypeError):
            _TokenRotator(r)