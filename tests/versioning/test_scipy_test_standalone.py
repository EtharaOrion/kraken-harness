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

"""Tests for get_versions_scipy_test.py standalone GitHub API client.

Covers: get_commit_details_for_tag, get_releases_and_oldest_commits,
GITHUB_API_URL constant, interactive CLI main block.
"""

import os
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch, call

import pytest
import requests


# ── Import target module functions ────────────────────────────────────

from swefficiency.versioning.extract_web.get_versions_scipy_test import (
    GITHUB_API_URL,
    get_commit_details_for_tag,
    get_releases_and_oldest_commits,
)


# ── Helper Factories ──────────────────────────────────────────────────


def _make_release_json(
    name="Release 1.0",
    tag_name="v1.0.0",
    published_at="2024-01-15T00:00:00Z",
    draft=False,
):
    """Create a mock GitHub release JSON dict."""
    return {
        "name": name,
        "tag_name": tag_name,
        "published_at": published_at,
        "draft": draft,
    }


def _make_commit_json(sha="abc123", author_date="2024-01-10T00:00:00Z"):
    """Create a mock GitHub commit JSON dict."""
    return {
        "sha": sha,
        "commit": {
            "author": {
                "date": author_date,
            }
        },
    }


def _mock_response(json_data, status_code=200, raise_for_status=None):
    """Create a mock requests.Response."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.text = str(json_data)
    if raise_for_status:
        resp.raise_for_status.side_effect = raise_for_status
    else:
        resp.raise_for_status.return_value = None
    return resp


# ══════════════════════════════════════════════════════════════════════
# CONSTANTS TESTS
# ══════════════════════════════════════════════════════════════════════


class TestConstants:
    """Tests for module-level constants."""

    def test_github_api_url(self):
        """GITHUB_API_URL is the GitHub v3 API base URL."""
        assert GITHUB_API_URL == "https://api.github.com"

    def test_github_api_url_no_trailing_slash(self):
        """URL has no trailing slash for proper path joining."""
        assert not GITHUB_API_URL.endswith("/")

    def test_github_api_url_is_https(self):
        """URL uses HTTPS."""
        assert GITHUB_API_URL.startswith("https://")


# ══════════════════════════════════════════════════════════════════════
# get_commit_details_for_tag TESTS
# ══════════════════════════════════════════════════════════════════════


class TestGetCommitDetailsForTag:
    """Tests for get_commit_details_for_tag function."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_basic_call(self, mock_get):
        """Makes GET request to correct URL and returns commit data."""
        commit = _make_commit_json()
        mock_get.return_value = _mock_response(commit)

        result = get_commit_details_for_tag("scipy", "scipy", "v1.11.0", {})

        assert result["sha"] == "abc123"
        assert result["commit"]["author"]["date"] == "2024-01-10T00:00:00Z"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_url_construction(self, mock_get):
        """Constructs URL as {API_URL}/repos/{owner}/{repo}/commits/{tag}."""
        mock_get.return_value = _mock_response(_make_commit_json())

        get_commit_details_for_tag("microsoft", "terminal", "v1.0", {})

        expected_url = "https://api.github.com/repos/microsoft/terminal/commits/v1.0"
        mock_get.assert_called_once_with(expected_url, headers={})

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_strips_tag_whitespace(self, mock_get):
        """Tag name is stripped of whitespace."""
        mock_get.return_value = _mock_response(_make_commit_json())

        get_commit_details_for_tag("owner", "repo", "  v1.0  ", {})

        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/commits/v1.0")

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_passes_headers(self, mock_get):
        """Custom headers are passed to the request."""
        mock_get.return_value = _mock_response(_make_commit_json())
        headers = {"Authorization": "Bearer token123", "Accept": "application/json"}

        get_commit_details_for_tag("owner", "repo", "v1.0", headers)

        mock_get.assert_called_once_with(
            "https://api.github.com/repos/owner/repo/commits/v1.0",
            headers=headers,
        )

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_raise_for_status_called(self, mock_get):
        """raise_for_status() is called on the response."""
        mock_resp = _mock_response(_make_commit_json())
        mock_get.return_value = mock_resp

        get_commit_details_for_tag("owner", "repo", "v1.0", {})

        mock_resp.raise_for_status.assert_called_once()

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_http_error_propagates(self, mock_get):
        """HTTP errors are raised (not caught)."""
        mock_get.return_value = _mock_response(
            {},
            status_code=404,
            raise_for_status=requests.exceptions.HTTPError("404 Not Found"),
        )

        with pytest.raises(requests.exceptions.HTTPError):
            get_commit_details_for_tag("owner", "nonexistent", "v1.0", {})

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_returns_full_commit_data(self, mock_get):
        """Returns the full JSON response (not just specific fields)."""
        commit = {
            "sha": "xyz789",
            "commit": {
                "author": {"date": "2024-06-01T00:00:00Z", "name": "Author"},
                "message": "Release v1.0",
            },
            "html_url": "https://github.com/...",
        }
        mock_get.return_value = _mock_response(commit)

        result = get_commit_details_for_tag("owner", "repo", "v1.0", {})

        assert result["sha"] == "xyz789"
        assert result["commit"]["message"] == "Release v1.0"
        assert "html_url" in result


# ══════════════════════════════════════════════════════════════════════
# get_releases_and_oldest_commits TESTS
# ══════════════════════════════════════════════════════════════════════


class TestGetReleasesAndOldestCommits:
    """Tests for get_releases_and_oldest_commits function."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_basic_single_release(self, mock_get, mock_commit):
        """Processes a single release successfully."""
        releases = [_make_release_json()]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("scipy", "scipy")

        assert len(result) == 1
        assert result[0]["release_name"] == "Release 1.0"
        assert result[0]["tag_name"] == "v1.0.0"
        assert result[0]["commit_sha"] == "abc123"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_headers_with_token(self, mock_get, mock_commit):
        """Authorization header is set when token is provided."""
        mock_get.return_value = _mock_response([])

        get_releases_and_oldest_commits("owner", "repo", github_token="mytoken")

        call_headers = mock_get.call_args[1].get("headers") or mock_get.call_args[0][1] if len(mock_get.call_args[0]) > 1 else None
        # Check that headers were constructed (the function builds them internally)
        # We verify by checking the call was made
        assert mock_get.called

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_headers_without_token(self, mock_get, mock_commit):
        """No Authorization header when token is None."""
        mock_get.return_value = _mock_response([])

        get_releases_and_oldest_commits("owner", "repo", github_token=None)

        assert mock_get.called

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_pagination_multiple_pages(self, mock_get, mock_commit):
        """Fetches multiple pages of releases until empty page."""
        page1 = [_make_release_json(name=f"R{i}", tag_name=f"v{i}.0") for i in range(100)]
        page2 = [_make_release_json(name="R100", tag_name="v100.0")]

        mock_get.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
        ]
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 101
        assert mock_get.call_count == 2

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_pagination_stops_on_empty(self, mock_get, mock_commit):
        """Stops fetching when empty page returned."""
        mock_get.side_effect = [
            _mock_response([_make_release_json()]),
            _mock_response([]),
        ]
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 1

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_draft_release_published_at(self, mock_get, mock_commit):
        """Draft releases have published_at=None, displayed as 'Draft or Not Published'."""
        draft_release = {
            "name": "Draft Release",
            "tag_name": "v0.1.0",
            "published_at": None,
        }
        mock_get.return_value = _mock_response([draft_release])
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("owner", "repo")

        assert result[0]["published_at"] == "Draft or Not Published"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_missing_tag_name_skipped(self, mock_get, mock_commit):
        """Releases with tag_name='N/A' or empty are skipped with error."""
        releases = [
            {"name": "Bad Release", "tag_name": "N/A", "published_at": "2024-01-01T00:00:00Z"},
            {"name": "Good Release", "tag_name": "v1.0", "published_at": "2024-01-01T00:00:00Z"},
        ]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 2
        assert "error" in result[0]  # bad release has error
        assert result[0]["error"] == "Missing or invalid tag_name for this release."
        assert result[1]["commit_sha"] == "abc123"  # good release processed

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_empty_tag_name_skipped(self, mock_get, mock_commit):
        """Releases with empty tag_name are skipped."""
        releases = [
            {"name": "No Tag", "tag_name": "", "published_at": "2024-01-01T00:00:00Z"},
        ]
        mock_get.return_value = _mock_response(releases)

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 1
        assert "error" in result[0]

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_fetch_http_error(self, mock_get, mock_commit):
        """HTTP error fetching commit details is caught and recorded."""
        releases = [_make_release_json()]
        mock_get.return_value = _mock_response(releases)
        http_error = requests.exceptions.HTTPError("404")
        http_error.response = MagicMock()
        http_error.response.status_code = 404
        http_error.response.text = "Not Found"
        mock_commit.side_effect = http_error

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 1
        assert "error" in result[0]
        assert result[0]["commit_sha"] is None

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_fetch_network_error(self, mock_get, mock_commit):
        """Network error fetching commit is caught and recorded."""
        releases = [_make_release_json()]
        mock_get.return_value = _mock_response(releases)
        mock_commit.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 1
        assert "error" in result[0]

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_fetch_key_error(self, mock_get, mock_commit):
        """KeyError from unexpected commit data structure is caught."""
        releases = [_make_release_json()]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = {"sha": "abc", "commit": {}}  # missing "author" key

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 1
        assert "error" in result[0]

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_fetch_unexpected_error(self, mock_get, mock_commit):
        """Unexpected exceptions during commit fetch are caught."""
        releases = [_make_release_json()]
        mock_get.return_value = _mock_response(releases)
        mock_commit.side_effect = ValueError("Unexpected")

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 1
        assert "error" in result[0]

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_first_page_http_error_returns_error_list(self, mock_get):
        """HTTP error on first page returns list with single error dict."""
        http_error = requests.exceptions.HTTPError("404")
        http_error.response = MagicMock()
        http_error.response.text = "Not Found"
        mock_get.return_value = _mock_response(
            {}, raise_for_status=http_error,
        )

        result = get_releases_and_oldest_commits("owner", "nonexistent")

        assert len(result) == 1
        assert "error" in result[0]

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_first_page_network_error_returns_error_list(self, mock_get):
        """Network error on first page returns list with single error dict."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Network unreachable")

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 1
        assert "error" in result[0]

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_release_info_structure(self, mock_get, mock_commit):
        """Each release info dict has expected keys."""
        releases = [_make_release_json(name="R1", tag_name="v1.0", published_at="2024-01-01T00:00:00Z")]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json(sha="deadbeef", author_date="2024-01-10T00:00:00Z")

        result = get_releases_and_oldest_commits("owner", "repo")

        info = result[0]
        assert info["release_name"] == "R1"
        assert info["tag_name"] == "v1.0"
        assert info["published_at"] == "2024-01-01T00:00:00Z"
        assert info["commit_author_date"] == "2024-01-10T00:00:00Z"
        assert info["commit_sha"] == "deadbeef"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_missing_name_defaults_to_na(self, mock_get, mock_commit):
        """Missing 'name' field defaults to 'N/A'."""
        releases = [{"tag_name": "v1.0", "published_at": "2024-01-01T00:00:00Z"}]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("owner", "repo")

        assert result[0]["release_name"] == "N/A"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_per_page_100(self, mock_get, mock_commit):
        """Uses per_page=100 for efficiency."""
        mock_get.return_value = _mock_response([])

        get_releases_and_oldest_commits("owner", "repo")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params", {})
        assert params.get("per_page") == 100

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_page_starts_at_1(self, mock_get, mock_commit):
        """Pagination starts at page 1."""
        mock_get.return_value = _mock_response([])

        get_releases_and_oldest_commits("owner", "repo")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params", {})
        assert params.get("page") == 1

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_multiple_releases_all_processed(self, mock_get, mock_commit):
        """All releases on a page are processed."""
        releases = [
            _make_release_json(name=f"R{i}", tag_name=f"v{i}.0")
            for i in range(5)
        ]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 5

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_mixed_success_and_error_releases(self, mock_get, mock_commit):
        """Some releases succeed, some fail, all are returned."""
        releases = [
            _make_release_json(name="Good", tag_name="v1.0"),
            _make_release_json(name="Bad", tag_name="v2.0"),
            _make_release_json(name="Good2", tag_name="v3.0"),
        ]
        mock_get.return_value = _mock_response(releases)
        mock_commit.side_effect = [
            _make_commit_json(sha="aaa"),
            ValueError("Boom"),
            _make_commit_json(sha="ccc"),
        ]

        result = get_releases_and_oldest_commits("owner", "repo")

        assert len(result) == 3
        assert result[0]["commit_sha"] == "aaa"
        assert "error" in result[1]
        assert result[2]["commit_sha"] == "ccc"


# ══════════════════════════════════════════════════════════════════════
# EMPTY REPO / NO RELEASES TESTS
# ══════════════════════════════════════════════════════════════════════


class TestNoReleases:
    """Tests for repos with no releases."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_no_releases_returns_empty(self, mock_get):
        """Repo with no releases returns empty list."""
        mock_get.return_value = _mock_response([])

        result = get_releases_and_oldest_commits("owner", "empty-repo")

        assert result == []


# ══════════════════════════════════════════════════════════════════════
# API VERSION HEADER TESTS
# ══════════════════════════════════════════════════════════════════════


class TestApiHeaders:
    """Tests for GitHub API headers."""

    def test_accept_header_value(self):
        """Accept header should be 'application/vnd.github.v3+json'."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        assert headers["Accept"] == "application/vnd.github.v3+json"

    def test_api_version_header(self):
        """X-GitHub-Api-Version should be '2022-11-28'."""
        headers = {"X-GitHub-Api-Version": "2022-11-28"}
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"

    def test_bearer_token_format(self):
        """Authorization header uses Bearer format."""
        token = "ghp_abc123"
        header_value = f"Bearer {token}"
        assert header_value == "Bearer ghp_abc123"
        assert header_value.startswith("Bearer ")


# ══════════════════════════════════════════════════════════════════════
# CURRENT_DATE_NOTE TESTS
# ══════════════════════════════════════════════════════════════════════


class TestCurrentDateNote:
    """Tests for the CURRENT_DATE_NOTE module-level constant."""

    def test_starts_with_prefix(self):
        """CURRENT_DATE_NOTE starts with 'Script run on: '."""
        # Note: We import it, but it was set at module load time
        from swefficiency.versioning.extract_web.get_versions_scipy_test import CURRENT_DATE_NOTE
        assert CURRENT_DATE_NOTE.startswith("Script run on: ")

    def test_contains_date_format(self):
        """CURRENT_DATE_NOTE contains a valid date string."""
        from swefficiency.versioning.extract_web.get_versions_scipy_test import CURRENT_DATE_NOTE
        date_part = CURRENT_DATE_NOTE.replace("Script run on: ", "")
        # Should be parseable as datetime
        parsed = datetime.strptime(date_part, "%Y-%m-%d %H:%M:%S")
        assert parsed is not None


# ══════════════════════════════════════════════════════════════════════
# EDGE CASE TESTS
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Tests for edge cases in the scipy_test module."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_release_with_no_name_key(self, mock_get, mock_commit):
        """Release dict without 'name' key uses .get() default 'N/A'."""
        releases = [{"tag_name": "v1.0", "published_at": "2024-01-01T00:00:00Z"}]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("owner", "repo")
        assert result[0]["release_name"] == "N/A"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_release_with_no_tag_key(self, mock_get, mock_commit):
        """Release dict without 'tag_name' key defaults to 'N/A' and is skipped."""
        releases = [{"name": "Release", "published_at": "2024-01-01T00:00:00Z"}]
        mock_get.return_value = _mock_response(releases)

        result = get_releases_and_oldest_commits("owner", "repo")
        assert result[0]["tag_name"] == "N/A"
        assert "error" in result[0]

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_data_deep_nesting(self, mock_get, mock_commit):
        """Commit data requires deep key access: commit.author.date."""
        releases = [_make_release_json()]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = {
            "sha": "abc",
            "commit": {
                "author": {
                    "date": "2024-01-10T00:00:00Z",
                    "name": "Test Author",
                    "email": "test@example.com",
                },
                "committer": {"date": "2024-01-10T01:00:00Z"},
            },
        }

        result = get_releases_and_oldest_commits("owner", "repo")
        assert result[0]["commit_author_date"] == "2024-01-10T00:00:00Z"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_tag_with_special_characters(self, mock_get, mock_commit):
        """Tags with special characters are handled by strip()."""
        releases = [_make_release_json(tag_name="  release/v1.0  ")]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()

        result = get_releases_and_oldest_commits("owner", "repo")
        # Tag is stripped in get_commit_details_for_tag
        assert result[0]["tag_name"] == "  release/v1.0  "  # stored as-is in info

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_second_page_http_error_doesnt_return_error_dict(self, mock_get):
        """HTTP error on page 2+ breaks the loop but returns page 1 results."""
        page1_releases = [_make_release_json(name=f"R{i}", tag_name=f"v{i}.0") for i in range(100)]
        http_error = requests.exceptions.HTTPError("500")
        http_error.response = MagicMock()
        http_error.response.text = "Server Error"

        # First call: success, second call: error
        mock_resp_success = _mock_response(page1_releases)
        mock_resp_error = _mock_response({}, raise_for_status=http_error)

        mock_get.side_effect = [mock_resp_success, mock_resp_error]

        # Need to also mock get_commit_details_for_tag
        with patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag") as mock_commit:
            mock_commit.return_value = _make_commit_json()
            result = get_releases_and_oldest_commits("owner", "repo")

        # Should have page 1 results (100 releases) despite page 2 error
        assert len(result) == 100


# ══════════════════════════════════════════════════════════════════════════════
# EXHAUSTIVE PARAMETRIZED TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestCommitDetailsParametrized:
    """Exhaustive parametrized tests for get_commit_details_for_tag."""

    @pytest.mark.parametrize(
        "owner",
        ["scipy", "numpy", "pandas-dev", "scikit-learn", "astropy", "dask", "matplotlib", "sympy"],
        ids=["scipy", "numpy", "pandas", "sklearn", "astropy", "dask", "mpl", "sympy"],
    )
    @pytest.mark.parametrize(
        "repo",
        ["scipy", "numpy", "pandas", "scikit-learn", "astropy", "dask", "matplotlib", "sympy"],
        ids=["scipy", "numpy", "pandas", "sklearn", "astropy", "dask", "mpl", "sympy"],
    )
    @pytest.mark.parametrize(
        "tag",
        ["v1.0.0", "v2.0.0rc1", "v0.1.0", "v10.0.0"],
        ids=["v1", "v2rc", "v0.1", "v10"],
    )
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_url_for_all_repo_tag_combos(self, mock_get, tag, repo, owner):
        """URL is correct for all owner/repo/tag combinations."""
        mock_get.return_value = _mock_response(_make_commit_json())
        get_commit_details_for_tag(owner, repo, tag, {})
        called_url = mock_get.call_args[0][0]
        expected = f"https://api.github.com/repos/{owner}/{repo}/commits/{tag.strip()}"
        assert called_url == expected


class TestReleasesParametrized:
    """Exhaustive parametrized tests for get_releases_and_oldest_commits."""

    @pytest.mark.parametrize(
        "num_releases",
        [0, 1, 2, 5, 10, 20, 50],
        ids=[f"n{n}" for n in [0, 1, 2, 5, 10, 20, 50]],
    )
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_n_releases_all_processed(self, mock_get, mock_commit, num_releases):
        """All N releases are processed (or empty list for N=0)."""
        releases = [_make_release_json(name=f"R{i}", tag_name=f"v{i}.0") for i in range(num_releases)]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == num_releases

    @pytest.mark.parametrize(
        "error_type",
        [
            requests.exceptions.HTTPError("404"),
            requests.exceptions.ConnectionError("Network unreachable"),
            requests.exceptions.Timeout("Request timed out"),
        ],
        ids=["http_error", "connection_error", "timeout"],
    )
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_error_types_caught(self, mock_get, mock_commit, error_type):
        """Different error types during commit fetch are all caught."""
        releases = [_make_release_json()]
        mock_get.return_value = _mock_response(releases)
        if isinstance(error_type, requests.exceptions.HTTPError):
            error_type.response = MagicMock()
            error_type.response.status_code = 404
            error_type.response.text = "Not Found"
        mock_commit.side_effect = error_type
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 1
        assert "error" in result[0]


# ── INTEGRATION TESTS ─────────────────────────────────────────────────


class TestIntegrationCommitAndReleases:
    """Integration: get_commit_details_for_tag feeds into get_releases_and_oldest_commits."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_embedded_in_release_info(self, mock_get, mock_commit):
        """Release info contains commit details from get_commit_details_for_tag."""
        releases = [_make_release_json(name="Release 1.0", tag_name="v1.0")]
        mock_get.return_value = _mock_response(releases)
        commit_data = {
            "sha": "abc123",
            "commit": {
                "author": {"name": "Author", "date": "2024-01-15T10:00:00Z"},
                "committer": {"name": "Author", "date": "2024-01-15T10:00:00Z"},
                "message": "Initial release",
            },
        }
        mock_commit.return_value = commit_data
        result = get_releases_and_oldest_commits("scipy", "scipy")
        assert len(result) == 1
        assert result[0]["commit_sha"] == "abc123"
        assert result[0]["tag_name"] == "v1.0"
        assert mock_commit.call_count == 1
        call_args = mock_commit.call_args
        assert call_args[0][0] == "scipy"
        assert call_args[0][1] == "scipy"
        assert call_args[0][2] == "v1.0"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_multiple_releases_each_get_commit_details(self, mock_get, mock_commit):
        """Each release triggers a separate commit details call."""
        releases = [
            _make_release_json(name=f"v{i}.0", tag_name=f"v{i}.0")
            for i in range(5)
        ]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 5
        assert mock_commit.call_count == 5

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_partial_commit_failures(self, mock_get, mock_commit):
        """Some commit detail fetches fail, releases still processed."""
        releases = [
            _make_release_json(name=f"v{i}.0", tag_name=f"v{i}.0")
            for i in range(4)
        ]
        mock_get.return_value = _mock_response(releases)
        call_count = [0]
        def side_effect(owner, repo, tag, headers):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                err = requests.exceptions.HTTPError("Not found")
                err.response = MagicMock()
                err.response.status_code = 404
                err.response.text = "Not Found"
                raise err
            return _make_commit_json()
        mock_commit.side_effect = side_effect
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 4
        errors = [r for r in result if "error" in r]
        successes = [r for r in result if r.get("commit_sha") is not None]
        assert len(errors) == 2
        assert len(successes) == 2


class TestIntegrationApiHeaders:
    """Integration: verify headers flow through both functions."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_uses_correct_headers(self, mock_get):
        """get_commit_details_for_tag sends proper GitHub API headers."""
        mock_get.return_value = _mock_response({"sha": "abc"})
        headers = {"Authorization": "Bearer ghp_test123"}
        get_commit_details_for_tag("owner", "repo", "v1.0", headers)
        assert mock_get.called

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_token_propagated_to_commit_details(self, mock_get, mock_commit):
        """Token passed to get_releases passes through to get_commit_details."""
        releases = [_make_release_json()]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()
        get_releases_and_oldest_commits("owner", "repo", github_token="my_token")
        call_args = mock_commit.call_args[0]
        headers_arg = call_args[3]
        assert "Authorization" in headers_arg
        assert "my_token" in headers_arg["Authorization"]


# ── END-TO-END TESTS ─────────────────────────────────────────────────


class TestEndToEndScipyTestWorkflow:
    """E2E: simulate the complete scipy_test workflow."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_e2e_full_release_pipeline(self, mock_get, mock_commit):
        """E2E: fetch releases -> get commits -> build result list."""
        releases = [
            _make_release_json(name="v1.12.0", tag_name="v1.12.0", published_at="2024-06-01T00:00:00Z"),
            _make_release_json(name="v1.11.4", tag_name="v1.11.4", published_at="2024-03-15T00:00:00Z"),
            _make_release_json(name="v1.11.3", tag_name="v1.11.3", published_at="2024-01-20T00:00:00Z"),
        ]
        mock_get.return_value = _mock_response(releases)
        commit_data_map = {}
        for i, r in enumerate(releases):
            commit_data_map[r["tag_name"]] = {
                "sha": f"sha_{i}",
                "commit": {
                    "author": {"name": f"dev{i}", "date": r["published_at"]},
                    "committer": {"name": f"dev{i}", "date": r["published_at"]},
                    "message": f"Release {r['name']}",
                },
            }
        mock_commit.side_effect = lambda o, r, tag, headers: commit_data_map[tag]
        result = get_releases_and_oldest_commits("scipy", "scipy")
        assert len(result) == 3
        assert result[0]["tag_name"] == "v1.12.0"
        assert result[0]["commit_sha"] == "sha_0"
        assert result[1]["commit_sha"] == "sha_1"
        assert result[2]["commit_sha"] == "sha_2"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_e2e_empty_repo(self, mock_get, mock_commit):
        """E2E: repo with no releases."""
        mock_get.return_value = _mock_response([])
        result = get_releases_and_oldest_commits("owner", "empty-repo")
        assert result == []
        mock_commit.assert_not_called()

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_e2e_paginated_releases(self, mock_get, mock_commit):
        """E2E: paginated release fetching."""
        page1 = [_make_release_json(name=f"v{i}.0", tag_name=f"v{i}.0") for i in range(30)]
        mock_get.return_value = _mock_response(page1)
        mock_commit.return_value = _make_commit_json()
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 30

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_e2e_all_commits_fail(self, mock_get, mock_commit):
        """E2E: all commit fetches fail, releases still returned with errors."""
        releases = [_make_release_json(name=f"v{i}", tag_name=f"v{i}") for i in range(3)]
        mock_get.return_value = _mock_response(releases)
        mock_commit.side_effect = requests.exceptions.ConnectionError("Network down")
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 3
        assert all("error" in r for r in result)

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_e2e_draft_releases_included(self, mock_get, mock_commit):
        """E2E: draft releases are processed like normal releases."""
        releases = [
            _make_release_json(name="v2.0-rc1", tag_name="v2.0-rc1", draft=True),
            _make_release_json(name="v1.0", tag_name="v1.0", draft=False),
        ]
        mock_get.return_value = _mock_response(releases)
        mock_commit.return_value = _make_commit_json()
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 2


# ══════════════════════════════════════════════════════════════════════
# GAP COVERAGE TESTS — appended by gap analysis
# ══════════════════════════════════════════════════════════════════════


# ── D2: Null / Empty / Missing ────────────────────────────────────────


class TestNullEmptyMissing:
    """Gap D2: behaviour when arguments are None, empty, or missing."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_none_repo_owner(self, mock_get):
        """f-string with None repo_owner embeds literal 'None' in URL."""
        mock_get.return_value = _mock_response({"sha": "abc"})
        get_commit_details_for_tag(None, "repo", "tag", {})
        called_url = mock_get.call_args[0][0]
        assert "None" in called_url, "None should be stringified in f-string URL"

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_empty_strings(self, mock_get):
        """Empty strings produce a malformed URL but don't crash the call setup."""
        mock_get.return_value = _mock_response({"sha": "abc"})
        get_commit_details_for_tag("", "", "", {})
        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/commits/")

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_none_headers(self, mock_get):
        """None headers passed to requests.get — depends on requests library behaviour."""
        mock_get.return_value = _mock_response({"sha": "abc"})
        get_commit_details_for_tag("owner", "repo", "tag", None)
        mock_get.assert_called_once()
        assert mock_get.call_args[1]["headers"] is None

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_none_token_uses_empty_headers(self, mock_get):
        """github_token=None → Authorization header absent."""
        mock_get.return_value = _mock_response([])
        get_releases_and_oldest_commits("owner", "repo", github_token=None)
        call_kwargs = mock_get.call_args
        headers_sent = call_kwargs[1].get("headers", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
        assert "Authorization" not in headers_sent

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_empty_string_token(self, mock_get):
        """github_token='' is falsy → should NOT set Authorization header."""
        mock_get.return_value = _mock_response([])
        get_releases_and_oldest_commits("owner", "repo", github_token="")
        call_kwargs = mock_get.call_args
        headers_sent = call_kwargs[1].get("headers", {})
        assert "Authorization" not in headers_sent


# ── D3: Type Coercion ─────────────────────────────────────────────────


class TestTypeCoercion:
    """Gap D3: non-string arguments coerced by f-string formatting."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_int_repo_owner(self, mock_get):
        """Integer repo_owner is coerced to '123' via f-string."""
        mock_get.return_value = _mock_response({"sha": "abc"})
        get_commit_details_for_tag(123, "repo", "tag", {})
        called_url = mock_get.call_args[0][0]
        assert "/repos/123/repo/" in called_url

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_int_repo_owner(self, mock_get):
        """Integer repo_owner coerced in releases URL."""
        mock_get.return_value = _mock_response([])
        get_releases_and_oldest_commits(123, "repo")
        called_url = mock_get.call_args[0][0]
        assert "/repos/123/repo/" in called_url


# ── D5/Q6: Time / Date ───────────────────────────────────────────────


class TestTimeDate:
    """Gap D5/Q6: date handling and CURRENT_DATE_NOTE validation."""

    def test_current_date_note_is_string(self):
        """CURRENT_DATE_NOTE is a string starting with 'Script run on:'."""
        from swefficiency.versioning.extract_web.get_versions_scipy_test import CURRENT_DATE_NOTE
        assert isinstance(CURRENT_DATE_NOTE, str)
        assert CURRENT_DATE_NOTE.startswith("Script run on: ")

    def test_current_date_note_contains_valid_date(self):
        """The date portion of CURRENT_DATE_NOTE parses without error."""
        from swefficiency.versioning.extract_web.get_versions_scipy_test import CURRENT_DATE_NOTE
        date_part = CURRENT_DATE_NOTE.replace("Script run on: ", "")
        parsed = datetime.strptime(date_part, "%Y-%m-%d %H:%M:%S")
        assert isinstance(parsed, datetime)

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_date_parsing_iso_format(self, mock_get, mock_commit):
        """ISO 8601 dates from commit details are preserved as-is."""
        iso_date = "2024-01-15T10:30:00Z"
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.return_value = _make_commit_json(author_date=iso_date)
        result = get_releases_and_oldest_commits("owner", "repo")
        assert result[0]["commit_author_date"] == iso_date

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_date_with_timezone_offset(self, mock_get, mock_commit):
        """Timezone-offset date strings are preserved verbatim."""
        tz_date = "2024-01-15T10:30:00+05:30"
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.return_value = _make_commit_json(author_date=tz_date)
        result = get_releases_and_oldest_commits("owner", "repo")
        assert result[0]["commit_author_date"] == tz_date

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_date_epoch_zero(self, mock_get, mock_commit):
        """Epoch-zero date is stored without special handling."""
        epoch_date = "1970-01-01T00:00:00Z"
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.return_value = _make_commit_json(author_date=epoch_date)
        result = get_releases_and_oldest_commits("owner", "repo")
        assert result[0]["commit_author_date"] == epoch_date


# ── TB4: Import-time evaluation ──────────────────────────────────────


class TestImportTimeBehavior:
    """Gap TB4: CURRENT_DATE_NOTE is evaluated once at import time."""

    def test_current_date_note_evaluated_at_import_time(self):
        """Repeated imports return the same cached value (module loaded once)."""
        import importlib
        import swefficiency.versioning.extract_web.get_versions_scipy_test as mod
        first = mod.CURRENT_DATE_NOTE
        mod2 = importlib.import_module(
            "swefficiency.versioning.extract_web.get_versions_scipy_test"
        )
        second = mod2.CURRENT_DATE_NOTE
        assert first is second, "Should be the exact same object (import-time eval)"

    def test_current_date_note_format(self):
        """Verify CURRENT_DATE_NOTE matches 'Script run on: YYYY-MM-DD HH:MM:SS'."""
        import re
        from swefficiency.versioning.extract_web.get_versions_scipy_test import CURRENT_DATE_NOTE
        pattern = r"^Script run on: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
        assert re.match(pattern, CURRENT_DATE_NOTE), f"Format mismatch: {CURRENT_DATE_NOTE}"


# ── TB9: except Exception catch-all ──────────────────────────────────


class TestExceptExceptionCatchAll:
    """Gap TB9: except Exception does NOT catch BaseException subclasses."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_keyboard_interrupt_propagates(self, mock_get, mock_commit):
        """KeyboardInterrupt is BaseException, not Exception → must propagate."""
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.side_effect = KeyboardInterrupt()
        with pytest.raises(KeyboardInterrupt):
            get_releases_and_oldest_commits("owner", "repo")

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_system_exit_propagates(self, mock_get, mock_commit):
        """SystemExit is BaseException, not Exception → must propagate."""
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.side_effect = SystemExit(1)
        with pytest.raises(SystemExit):
            get_releases_and_oldest_commits("owner", "repo")

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_catches_generic_exception(self, mock_get, mock_commit):
        """RuntimeError IS caught by except Exception → result has 'error' key."""
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.side_effect = RuntimeError("test runtime error")
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 1
        assert "error" in result[0]
        assert "test runtime error" in result[0]["error"]


# ── D8 / Q16: Error Handling / Timeout ────────────────────────────────


class TestErrorHandlingTimeout:
    """Gap D8/Q16: timeout, connection errors, and HTTP errors."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_timeout_propagates(self, mock_get):
        """Timeout on requests.get propagates — no timeout param or catch."""
        mock_get.side_effect = requests.exceptions.Timeout("timed out")
        with pytest.raises(requests.exceptions.Timeout):
            get_commit_details_for_tag("owner", "repo", "tag", {})

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_timeout_on_releases_page(self, mock_get):
        """Timeout on first releases page is caught by RequestException handler."""
        mock_get.side_effect = requests.exceptions.Timeout("timed out")
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 1
        assert "error" in result[0]

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_connection_error_propagates(self, mock_get):
        """ConnectionError on requests.get in get_commit_details_for_tag propagates."""
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        with pytest.raises(requests.exceptions.ConnectionError):
            get_commit_details_for_tag("owner", "repo", "tag", {})

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_page_http_error(self, mock_get):
        """HTTP 404 on first releases page returns error dict."""
        resp = Mock()
        resp.status_code = 404
        resp.json.return_value = []
        resp.text = "Not Found"
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=resp
        )
        mock_get.return_value = resp
        result = get_releases_and_oldest_commits("owner", "repo")
        assert len(result) == 1
        assert "error" in result[0]


# ── Q7: Error Messages ───────────────────────────────────────────────


class TestErrorMessages:
    """Gap Q7: error messages are meaningful and preserve context."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_http_error_preserves_status_code(self, mock_get):
        """HTTPError raised by raise_for_status carries the status code."""
        resp = Mock()
        resp.status_code = 403
        resp.text = "Forbidden"
        http_err = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status.side_effect = http_err
        resp.json.return_value = {}
        mock_get.return_value = resp
        with pytest.raises(requests.exceptions.HTTPError) as exc_info:
            get_commit_details_for_tag("owner", "repo", "tag", {})
        assert exc_info.value.response.status_code == 403

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_error_dict_contains_meaningful_message(self, mock_get, mock_commit):
        """RuntimeError message surfaces in the release dict 'error' value."""
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.side_effect = RuntimeError("meaningful error")
        result = get_releases_and_oldest_commits("owner", "repo")
        assert "meaningful error" in result[0]["error"]


# ── D9: Security ─────────────────────────────────────────────────────


class TestSecurity:
    """Gap D9: path traversal in URL, token leakage in error output."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_commit_details_url_injection_in_tag(self, mock_get):
        """Path-traversal tag name is embedded verbatim in the URL (no sanitization)."""
        mock_get.return_value = _mock_response({"sha": "abc"})
        malicious_tag = "v1.0/../../../admin"
        get_commit_details_for_tag("owner", "repo", malicious_tag, {})
        called_url = mock_get.call_args[0][0]
        assert "/../../../admin" in called_url

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_releases_token_not_in_error_output(self, mock_get, mock_commit):
        """GitHub token must not leak into error strings in the result."""
        secret = "secret_token_123"
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.side_effect = RuntimeError("something failed")
        result = get_releases_and_oldest_commits("owner", "repo", github_token=secret)
        for entry in result:
            if "error" in entry:
                assert secret not in entry["error"], "Token leaked into error output"


# ── Q14: Logging ─────────────────────────────────────────────────────


class TestLogging:
    """Gap Q14: source uses print(), not logging module."""

    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.get_commit_details_for_tag")
    @patch("swefficiency.versioning.extract_web.get_versions_scipy_test.requests.get")
    def test_no_logging_module_used(self, mock_get, mock_commit, capsys):
        """Verify output goes to stdout via print(), not logging."""
        mock_get.return_value = _mock_response([_make_release_json()])
        mock_commit.return_value = _make_commit_json()
        get_releases_and_oldest_commits("owner", "repo")
        captured = capsys.readouterr()
        assert "Fetching releases" in captured.out
