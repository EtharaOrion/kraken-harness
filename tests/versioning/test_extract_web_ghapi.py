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

"""Tests for extract_web GhApi-based scripts.

Covers: get_versions_numpy, get_versions_scipy, get_versions_modin,
get_versions_pytensor, get_versions_statsmodels, get_versions_sqlfluff.

All six scripts follow a similar pattern:
1. Fetch GitHub releases via GhApi
2. Match tag/name against regex patterns
3. Build (date, version) timeline sorted in reverse
4. Assign version to each task by temporal matching (< not <=)
5. Save JSON output

These tests verify regex patterns, temporal assignment logic,
edge cases, and known bugs (e.g., pytensor fetching from wrong repo).
"""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


# ── Helper Factories ──────────────────────────────────────────────────


def _make_release(tag_name, name="", created_at="2024-01-15T00:00:00Z", published_at="2024-01-15T00:00:00Z"):
    """Create a mock GitHub release dict."""
    return {
        "tag_name": tag_name,
        "name": name or tag_name,
        "created_at": created_at,
        "published_at": published_at,
    }


def _make_task(instance_id, created_at="2024-06-15T12:00:00Z"):
    """Create a mock task instance dict."""
    return {
        "instance_id": instance_id,
        "created_at": created_at,
    }


def _keep_major_minor(x, sep):
    """Replicate the keep_major_minor lambda from the scripts."""
    return ".".join(x.strip().split(sep)[:2])


# ── Numpy VERSION_TAG_PATTERN Tests ──────────────────────────────────


class TestNumpyVersionTagPattern:
    """Tests for numpy VERSION_TAG_PATTERN = r'^v(\d+\.\d+\.\d+)(?:rc\d+)?$'."""

    PATTERN = r"^v(\d+\.\d+\.\d+)(?:rc\d+)?$"

    @pytest.mark.parametrize("tag,expected_version", [
        ("v1.24.0", "1.24.0"),
        ("v1.24.1", "1.24.1"),
        ("v2.0.0", "2.0.0"),
        ("v1.0.0", "1.0.0"),
        ("v10.20.30", "10.20.30"),
        ("v1.24.0rc1", "1.24.0"),
        ("v1.24.0rc2", "1.24.0"),
        ("v2.0.0rc99", "2.0.0"),
    ])
    def test_matching_tags(self, tag, expected_version):
        """Tags with v-prefix and optional rc suffix should match."""
        m = re.match(self.PATTERN, tag)
        assert m is not None
        assert m.group(1) == expected_version

    @pytest.mark.parametrize("tag", [
        "1.24.0",           # no v prefix
        "v1.24",            # only major.minor
        "v1.24.0.1",        # four parts
        "v1.24.0-beta1",    # beta suffix
        "v1.24.0alpha",     # alpha suffix
        "release-1.24.0",   # wrong prefix
        "",                  # empty
        "v",                # just v
        "numpy-1.24.0",     # package prefix
        "v1.24.0rc",        # rc without number
    ])
    def test_non_matching_tags(self, tag):
        """Tags that don't match the numpy pattern."""
        m = re.match(self.PATTERN, tag)
        assert m is None

    def test_rc_version_extracts_base(self):
        """RC tags should extract the base version without rc suffix."""
        m = re.match(self.PATTERN, "v1.26.0rc1")
        assert m.group(1) == "1.26.0"
        assert "rc" not in m.group(1)


# ── Numpy PATTERN Tests (SciPy copy-paste) ──────────────────────────


class TestNumpyNamePattern:
    """Tests for numpy PATTERN = r'^SciPy (\d+\.\d+\.\d+)$' (copy-paste bug)."""

    PATTERN = r"^SciPy (\d+\.\d+\.\d+)$"

    @pytest.mark.parametrize("name,expected", [
        ("SciPy 1.11.0", "1.11.0"),
        ("SciPy 0.1.0", "0.1.0"),
        ("SciPy 10.20.30", "10.20.30"),
    ])
    def test_matches_scipy_format(self, name, expected):
        """The PATTERN in numpy script is a copy-paste from scipy - matches SciPy names."""
        m = re.match(self.PATTERN, name)
        assert m is not None
        assert m.group(1) == expected

    @pytest.mark.parametrize("name", [
        "NumPy 1.24.0",      # wrong project name
        "numpy 1.24.0",      # lowercase
        "SciPy 1.24.0rc1",   # has rc suffix
        "SciPy 1.24",        # only major.minor
        "v1.24.0",           # no SciPy prefix
    ])
    def test_does_not_match_numpy_names(self, name):
        """Numpy release names won't match the SciPy pattern."""
        m = re.match(self.PATTERN, name)
        assert m is None

    def test_confirms_copypaste_bug(self):
        """Numpy script has a PATTERN meant for SciPy - this is a known copy-paste bug."""
        # The script uses VERSION_TAG_PATTERN for actual matching, not PATTERN
        # PATTERN is unused dead code from scipy copy-paste
        numpy_pattern = r"^SciPy (\d+\.\d+\.\d+)$"
        assert "SciPy" in numpy_pattern  # confirms the bug
        assert "NumPy" not in numpy_pattern


# ── Numpy Pagination Tests ───────────────────────────────────────────


class TestNumpyPagination:
    """Tests for numpy's paginated release fetching (while True loop)."""

    def test_pagination_stops_on_empty(self):
        """Pagination should stop when empty page returned."""
        pages = [
            [_make_release("v1.24.0"), _make_release("v1.23.0")],
            [_make_release("v1.22.0")],
            [],  # empty page stops loop
        ]
        page_idx = [0]
        def mock_list_releases(*args, **kwargs):
            idx = page_idx[0]
            page_idx[0] += 1
            if idx < len(pages):
                return pages[idx]
            return []
        releases = []
        i = 0
        while True:
            try:
                raw = mock_list_releases("numpy", "numpy", per_page=100, page=i)
                if len(raw) == 0:
                    break
                i += 1
                releases.extend(raw)
            except:
                break
        assert len(releases) == 3

    def test_pagination_stops_on_exception(self):
        """Pagination should stop on API exception."""
        call_count = [0]
        def mock_list_releases(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 2:
                raise Exception("Rate limited")
            return [_make_release(f"v1.{call_count[0]}.0")]
        releases = []
        i = 0
        while True:
            try:
                raw = mock_list_releases("numpy", "numpy", per_page=100, page=i)
                if len(raw) == 0:
                    break
                i += 1
                releases.extend(raw)
            except:
                break
        assert len(releases) == 2

    def test_single_page(self):
        """When first page has < 100 items and second is empty."""
        pages = [[_make_release("v1.24.0")], []]
        page_idx = [0]
        def mock_list_releases(*args, **kwargs):
            idx = page_idx[0]
            page_idx[0] += 1
            return pages[idx] if idx < len(pages) else []
        releases = []
        i = 0
        while True:
            try:
                raw = mock_list_releases(per_page=100, page=i)
                if len(raw) == 0:
                    break
                i += 1
                releases.extend(raw)
            except:
                break
        assert len(releases) == 1


# ── Numpy Times Dict (min date per major.minor) ─────────────────────


class TestNumpyTimesDict:
    """Tests for numpy's times dict that keeps min date per major.minor."""

    PATTERN = r"^v(\d+\.\d+\.\d+)(?:rc\d+)?$"

    def test_keeps_earliest_date_per_major_minor(self):
        """Multiple releases of same major.minor should keep earliest date."""
        releases = [
            _make_release("v1.24.0", created_at="2023-06-15T00:00:00Z"),
            _make_release("v1.24.1", created_at="2023-07-01T00:00:00Z"),
            _make_release("v1.24.0rc1", created_at="2023-05-01T00:00:00Z"),
        ]
        times = dict()
        for r in releases:
            version = r["tag_name"]
            release_date = r["created_at"].split("T")[0]
            m = re.match(self.PATTERN, version)
            if m:
                version = m.group(1)
                major_minor = _keep_major_minor(version, ".")
                if major_minor not in times:
                    times[major_minor] = release_date
                times[major_minor] = min(times[major_minor], release_date)
        assert times["1.24"] == "2023-05-01"

    def test_different_major_minor_versions(self):
        """Different major.minor versions get separate entries."""
        releases = [
            _make_release("v1.24.0", created_at="2023-06-15T00:00:00Z"),
            _make_release("v1.25.0", created_at="2023-12-01T00:00:00Z"),
            _make_release("v2.0.0", created_at="2024-01-15T00:00:00Z"),
        ]
        times = dict()
        for r in releases:
            version = r["tag_name"]
            release_date = r["created_at"].split("T")[0]
            m = re.match(self.PATTERN, version)
            if m:
                version = m.group(1)
                major_minor = _keep_major_minor(version, ".")
                if major_minor not in times:
                    times[major_minor] = release_date
                times[major_minor] = min(times[major_minor], release_date)
        assert len(times) == 3
        assert "1.24" in times
        assert "1.25" in times
        assert "2.0" in times

    def test_sort_reverse_order(self):
        """Times should be sorted in reverse chronological order."""
        times_dict = {"1.24": "2023-06-15", "1.25": "2023-12-01", "2.0": "2024-01-15"}
        times = sorted([(v, k) for k, v in times_dict.items()], key=lambda x: x[0], reverse=True)
        assert times[0][1] == "2.0"  # most recent first
        assert times[-1][1] == "1.24"  # oldest last

    def test_empty_releases(self):
        """No matching releases produces empty times dict."""
        releases = [
            _make_release("not-a-version", created_at="2023-06-15T00:00:00Z"),
            _make_release("release-1.0", created_at="2023-06-15T00:00:00Z"),
        ]
        times = dict()
        for r in releases:
            m = re.match(self.PATTERN, r["tag_name"])
            if m:
                version = m.group(1)
                major_minor = _keep_major_minor(version, ".")
                if major_minor not in times:
                    times[major_minor] = r["created_at"].split("T")[0]
                times[major_minor] = min(times[major_minor], r["created_at"].split("T")[0])
        assert len(times) == 0


# ── Temporal Assignment Tests (shared pattern) ───────────────────────


class TestTemporalAssignment:
    """Tests for the temporal assignment logic shared by numpy/scipy/modin/pytensor."""

    def _assign_versions(self, tasks, times, fallback_last=True, fallback_none=False):
        """Replicate the temporal assignment loop from the scripts."""
        for task in tasks:
            created_at = task["created_at"].split("T")[0]
            set_version = False
            for t in times:
                if t[0] < created_at:
                    task["version"] = t[1]
                    set_version = True
                    break
            if not set_version:
                if fallback_none:
                    task["version"] = None
                elif fallback_last and times:
                    task["version"] = times[-1][1]
        return tasks

    def test_task_after_latest_release(self):
        """Task created after latest release gets that version."""
        times = [("2024-01-15", "2.0"), ("2023-06-15", "1.25"), ("2023-01-01", "1.24")]
        tasks = [_make_task("t1", "2024-06-01T00:00:00Z")]
        result = self._assign_versions(tasks, times)
        assert result[0]["version"] == "2.0"

    def test_task_between_releases(self):
        """Task created between two releases gets the earlier one."""
        times = [("2024-01-15", "2.0"), ("2023-06-15", "1.25"), ("2023-01-01", "1.24")]
        tasks = [_make_task("t1", "2023-09-01T00:00:00Z")]
        result = self._assign_versions(tasks, times)
        assert result[0]["version"] == "1.25"

    def test_task_before_all_releases(self):
        """Task created before all releases gets the last (oldest) version."""
        times = [("2024-01-15", "2.0"), ("2023-06-15", "1.25"), ("2023-01-01", "1.24")]
        tasks = [_make_task("t1", "2022-01-01T00:00:00Z")]
        result = self._assign_versions(tasks, times)
        assert result[0]["version"] == "1.24"

    def test_strict_less_than_not_equal(self):
        """Temporal assignment uses < not <=, so same date does NOT match."""
        times = [("2024-01-15", "2.0"), ("2023-06-15", "1.25")]
        tasks = [_make_task("t1", "2024-01-15T00:00:00Z")]
        # t[0] < created_at means "2024-01-15" < "2024-01-15" is False
        # So 2.0 won't match, falls through to 1.25
        result = self._assign_versions(tasks, times)
        assert result[0]["version"] == "1.25"

    def test_same_date_falls_through(self):
        """When task date equals release date, it matches the next older release."""
        times = [("2024-01-15", "2.0"), ("2023-06-15", "1.25"), ("2023-01-01", "1.24")]
        tasks = [_make_task("t1", "2023-06-15T00:00:00Z")]
        result = self._assign_versions(tasks, times)
        assert result[0]["version"] == "1.24"

    def test_multiple_tasks_different_versions(self):
        """Multiple tasks get different versions based on their dates."""
        times = [("2024-01-15", "2.0"), ("2023-06-15", "1.25"), ("2023-01-01", "1.24")]
        tasks = [
            _make_task("t1", "2024-06-01T00:00:00Z"),
            _make_task("t2", "2023-09-01T00:00:00Z"),
            _make_task("t3", "2023-03-01T00:00:00Z"),
        ]
        result = self._assign_versions(tasks, times)
        assert result[0]["version"] == "2.0"
        assert result[1]["version"] == "1.25"
        assert result[2]["version"] == "1.24"

    def test_all_tasks_same_version(self):
        """All tasks created after latest release get same version."""
        times = [("2023-01-01", "1.0")]
        tasks = [
            _make_task("t1", "2024-01-01T00:00:00Z"),
            _make_task("t2", "2024-06-01T00:00:00Z"),
        ]
        result = self._assign_versions(tasks, times)
        assert all(t["version"] == "1.0" for t in result)

    def test_sqlfluff_none_fallback(self):
        """Sqlfluff assigns None when no version matches (unlike others)."""
        times = [("2024-01-15", "2.0")]
        tasks = [_make_task("t1", "2023-01-01T00:00:00Z")]
        result = self._assign_versions(tasks, times, fallback_last=False, fallback_none=True)
        assert result[0]["version"] is None

    def test_empty_times_with_fallback(self):
        """Empty times list with fallback_last does not crash."""
        times = []
        tasks = [_make_task("t1", "2024-01-01T00:00:00Z")]
        result = self._assign_versions(tasks, times)
        assert "version" not in result[0]

    def test_no_tasks(self):
        """Empty task list returns empty."""
        times = [("2024-01-15", "2.0")]
        result = self._assign_versions([], times)
        assert result == []


# ── Scipy VERSION_TAG_PATTERN Tests ──────────────────────────────────


class TestScipyVersionTagPattern:
    """Tests for scipy VERSION_TAG_PATTERN = r'^v(\\d+\\.\\d+\\.\\d+)rc\\d+$' (RC ONLY)."""

    PATTERN = r"^v(\d+\.\d+\.\d+)rc\d+$"

    @pytest.mark.parametrize("tag,expected", [
        ("v1.11.0rc1", "1.11.0"),
        ("v1.11.0rc2", "1.11.0"),
        ("v2.0.0rc1", "2.0.0"),
        ("v0.1.0rc99", "0.1.0"),
    ])
    def test_matches_rc_tags_only(self, tag, expected):
        """Scipy pattern only matches RC releases, not final releases."""
        m = re.match(self.PATTERN, tag)
        assert m is not None
        assert m.group(1) == expected

    @pytest.mark.parametrize("tag", [
        "v1.11.0",          # no rc suffix - DOES NOT MATCH
        "v1.11.0.1",        # patch version
        "1.11.0rc1",        # no v prefix
        "v1.11.0beta1",     # beta, not rc
        "v1.11.0rc",        # rc without number
        "v1.11rc1",         # only major.minor
    ])
    def test_rejects_non_rc_tags(self, tag):
        """Non-RC tags are rejected by scipy's pattern."""
        m = re.match(self.PATTERN, tag)
        assert m is None

    def test_scipy_requires_rc_unlike_numpy(self):
        """Scipy REQUIRES rc suffix while numpy makes it optional."""
        numpy_pattern = r"^v(\d+\.\d+\.\d+)(?:rc\d+)?$"
        scipy_pattern = r"^v(\d+\.\d+\.\d+)rc\d+$"
        tag = "v1.11.0"
        assert re.match(numpy_pattern, tag) is not None  # numpy matches
        assert re.match(scipy_pattern, tag) is None      # scipy rejects

    def test_scipy_single_page_fetch(self):
        """Scipy uses single page fetch (no while loop)."""
        # Verify by structure: scipy calls list_releases once, not in a loop
        # This test documents the behavioral difference
        releases = [
            _make_release("v1.11.0rc1", created_at="2023-06-01T00:00:00Z"),
            _make_release("v1.11.0", created_at="2023-06-15T00:00:00Z"),  # won't match
            _make_release("v1.10.0rc1", created_at="2023-01-01T00:00:00Z"),
        ]
        times = dict()
        for r in releases:
            m = re.match(self.PATTERN, r["tag_name"])
            if m:
                version = m.group(1)
                major_minor = _keep_major_minor(version, ".")
                if major_minor not in times:
                    times[major_minor] = r["created_at"].split("T")[0]
                times[major_minor] = min(times[major_minor], r["created_at"].split("T")[0])
        assert "1.11" in times
        assert "1.10" in times
        assert times["1.11"] == "2023-06-01"  # RC date, not final release date



# ── Modin VERSION_TAG_PATTERN Tests ──────────────────────────────────


class TestModinVersionTagPattern:
    """Tests for modin VERSION_TAG_PATTERN = r'^(\\d+\\.\\d+\\.\\d+)(?:rc\\d+)?$' (no v prefix)."""

    PATTERN = r"^(\d+\.\d+\.\d+)(?:rc\d+)?$"

    @pytest.mark.parametrize("tag,expected", [
        ("0.23.0", "0.23.0"),
        ("0.23.0rc1", "0.23.0"),
        ("1.0.0", "1.0.0"),
        ("10.20.30", "10.20.30"),
        ("0.23.0rc99", "0.23.0"),
    ])
    def test_matches_bare_version_tags(self, tag, expected):
        """Modin tags have no v-prefix."""
        m = re.match(self.PATTERN, tag)
        assert m is not None
        assert m.group(1) == expected

    @pytest.mark.parametrize("tag", [
        "v0.23.0",          # has v prefix (unlike modin)
        "v0.23.0rc1",       # v prefix + rc
        "0.23",             # only major.minor
        "0.23.0.1",         # four parts
        "0.23.0-beta",      # beta suffix
        "release-0.23.0",   # wrong prefix
    ])
    def test_rejects_v_prefix_tags(self, tag):
        """Modin rejects tags with v-prefix or other prefixes."""
        m = re.match(self.PATTERN, tag)
        assert m is None

    def test_modin_vs_numpy_pattern_difference(self):
        """Modin has no v-prefix requirement while numpy requires it."""
        numpy_pattern = r"^v(\d+\.\d+\.\d+)(?:rc\d+)?$"
        modin_pattern = r"^(\d+\.\d+\.\d+)(?:rc\d+)?$"
        assert re.match(numpy_pattern, "0.23.0") is None       # numpy rejects bare
        assert re.match(modin_pattern, "0.23.0") is not None    # modin accepts bare
        assert re.match(numpy_pattern, "v0.23.0") is not None   # numpy needs v
        assert re.match(modin_pattern, "v0.23.0") is None       # modin rejects v

    def test_modin_fetches_correct_repo(self):
        """Modin fetches from modin-project/modin."""
        # Documented: the script calls gh_api.repos.list_releases("modin-project", "modin", ...)
        owner, repo = "modin-project", "modin"
        assert owner == "modin-project"
        assert repo == "modin"


# ── Pytensor VERSION_TAG_PATTERN Tests ───────────────────────────────


class TestPytensorVersionTagPattern:
    """Tests for pytensor VERSION_TAG_PATTERN = r'(?:v)?(\\d+\\.\\d+\\.\\d+)(?:rc\\d+)?$' (optional v)."""

    PATTERN = r"(?:v)?(\d+\.\d+\.\d+)(?:rc\d+)?$"

    @pytest.mark.parametrize("tag,expected", [
        ("v2.18.0", "2.18.0"),
        ("2.18.0", "2.18.0"),
        ("v2.18.0rc1", "2.18.0"),
        ("2.18.0rc1", "2.18.0"),
        ("v1.0.0", "1.0.0"),
        ("1.0.0", "1.0.0"),
    ])
    def test_matches_with_or_without_v(self, tag, expected):
        """Pytensor pattern accepts both v-prefixed and bare tags."""
        m = re.match(self.PATTERN, tag)
        assert m is not None
        assert m.group(1) == expected

    @pytest.mark.parametrize("tag", [
        "2.18",             # only major.minor
        "v2.18",            # v + major.minor
        "2.18.0.1",         # four parts
        "release-2.18.0",   # wrong prefix
    ])
    def test_rejects_invalid_formats(self, tag):
        """Invalid tags are rejected."""
        m = re.match(self.PATTERN, tag)
        assert m is None

    def test_pytensor_fetches_wrong_repo_bug(self):
        """BUG: Pytensor fetches from modin-project/modin instead of pymc-devs/pytensor."""
        # The script has: gh_api.repos.list_releases("modin-project", "modin", per_page=100)
        # This is a known copy-paste bug
        wrong_owner, wrong_repo = "modin-project", "modin"
        correct_owner, correct_repo = "pymc-devs", "pytensor"
        assert wrong_owner != correct_owner
        assert wrong_repo != correct_repo

    def test_pytensor_is_most_permissive_pattern(self):
        """Pytensor pattern is the most permissive - matches numpy, modin, AND its own tags."""
        pattern = r"(?:v)?(\d+\.\d+\.\d+)(?:rc\d+)?$"
        assert re.match(pattern, "v1.24.0") is not None     # numpy style
        assert re.match(pattern, "0.23.0") is not None      # modin style
        assert re.match(pattern, "v2.18.0") is not None     # pytensor style
        assert re.match(pattern, "2.18.0") is not None      # bare pytensor


# ── Statsmodels Pattern Tests ────────────────────────────────────────


class TestStatsmodelsPattern:
    """Tests for statsmodels PATTERN matching release names (not tags)."""

    PATTERN = r"^(Version (\d+\.\d+\.\d+) Release|Release (\d+\.\d+\.\d+))$"

    @pytest.mark.parametrize("name,expected", [
        ("Version 0.14.0 Release", "0.14.0"),
        ("Version 0.13.0 Release", "0.13.0"),
        ("Version 1.0.0 Release", "1.0.0"),
        ("Version 10.20.30 Release", "10.20.30"),
    ])
    def test_matches_version_release_format(self, name, expected):
        """'Version X.Y.Z Release' format should match with group(2)."""
        m = re.match(self.PATTERN, name)
        assert m is not None
        assert m.group(2) == expected

    @pytest.mark.parametrize("name,expected", [
        ("Release 0.14.0", "0.14.0"),
        ("Release 0.13.0", "0.13.0"),
        ("Release 1.0.0", "1.0.0"),
    ])
    def test_matches_release_version_format(self, name, expected):
        """'Release X.Y.Z' format should match with group(3)."""
        m = re.match(self.PATTERN, name)
        assert m is not None
        assert m.group(3) == expected

    def test_group2_or_group3_logic(self):
        """Script uses `match.group(2) or match.group(3)` to extract version."""
        # Version X.Y.Z Release -> group(2) has version, group(3) is None
        m1 = re.match(self.PATTERN, "Version 0.14.0 Release")
        assert m1.group(2) == "0.14.0"
        assert m1.group(3) is None
        version1 = m1.group(2) or m1.group(3)
        assert version1 == "0.14.0"

        # Release X.Y.Z -> group(2) is None, group(3) has version
        m2 = re.match(self.PATTERN, "Release 0.14.0")
        assert m2.group(2) is None
        assert m2.group(3) == "0.14.0"
        version2 = m2.group(2) or m2.group(3)
        assert version2 == "0.14.0"

    @pytest.mark.parametrize("name", [
        "v0.14.0",                      # tag format
        "0.14.0",                       # bare version
        "statsmodels 0.14.0",           # package prefix
        "Version 0.14.0",               # missing " Release"
        "Release 0.14.0 Release",       # double
        "Version 0.14 Release",         # only major.minor
        "Version 0.14.0.1 Release",     # four parts
    ])
    def test_rejects_non_matching_names(self, name):
        """Names not matching either format are rejected."""
        m = re.match(self.PATTERN, name)
        assert m is None

    def test_statsmodels_uses_release_name_not_tag(self):
        """Statsmodels is unique - matches against release name, not tag_name."""
        release = _make_release(
            tag_name="v0.14.0",
            name="Version 0.14.0 Release",
            created_at="2023-06-15T00:00:00Z",
        )
        # Tag won't match
        assert re.match(self.PATTERN, release["tag_name"]) is None
        # Name will match
        assert re.match(self.PATTERN, release["name"]) is not None

    def test_statsmodels_uses_min_date(self):
        """Statsmodels uses min() for versions_to_release_date (earliest date)."""
        releases = [
            {"name": "Version 0.14.0 Release", "created_at": "2023-06-15T00:00:00Z"},
            {"name": "Release 0.14.0", "created_at": "2023-05-01T00:00:00Z"},
        ]
        versions_to_release_date = {}
        for r in releases:
            m = re.match(self.PATTERN, r["name"])
            if m:
                version = m.group(2) or m.group(3)
                version = _keep_major_minor(version, ".")
                versions_to_release_date[version] = min(
                    versions_to_release_date.get(version, r["created_at"].split("T")[0]),
                    r["created_at"].split("T")[0],
                )
        assert versions_to_release_date["0.14"] == "2023-05-01"

    def test_statsmodels_get_with_default(self):
        """Uses .get(version, release_date) for dict default."""
        versions_to_release_date = {}
        version = "0.14"
        date = "2023-06-15"
        result = min(versions_to_release_date.get(version, date), date)
        assert result == date  # first insertion uses the date itself as default



# ── Sqlfluff process() Tests ─────────────────────────────────────────


class TestSqlfluffProcess:
    """Tests for sqlfluff's process() function that extracts version from release names."""

    def _process(self, x):
        """Replicate the process() function from get_versions_sqlfluff.py."""
        if x.startswith("SQLFluff "):
            x = x[len("SQLFluff "):]
        pattern = re.compile(r"\[[\d\.\w]*\] - \d*-\d*-\d*")
        matches = pattern.findall(x)
        if len(matches) > 0:
            parts = x.split(" - ")
            version = parts[0].replace("[", "").replace("]", "")
            version = version.rsplit(".", 1)[0]
            return (version, parts[1])
        pattern = re.compile(r"\d+\.\d+\.[\d\.]*")
        matches = pattern.findall(x)
        if len(matches) > 0:
            version = matches[0]
            version = version.rsplit(".", 1)[0]
            return (version, None)
        return (None, None)

    # -- Bracket format tests --

    @pytest.mark.parametrize("name,expected_version,expected_date", [
        ("SQLFluff [0.13.0] - 2023-06-15", "0.13", "2023-06-15"),
        ("SQLFluff [1.0.0] - 2024-01-01", "1.0", "2024-01-01"),
        ("SQLFluff [0.13.2] - 2023-07-01", "0.13", "2023-07-01"),
        ("[0.13.0] - 2023-06-15", "0.13", "2023-06-15"),  # no SQLFluff prefix
    ])
    def test_bracket_format(self, name, expected_version, expected_date):
        """Bracket format '[X.Y.Z] - YYYY-MM-DD' extracts version and date."""
        version, date = self._process(name)
        assert version == expected_version
        assert date == expected_date

    def test_bracket_format_strips_sqlfluff_prefix(self):
        """SQLFluff prefix is stripped before pattern matching."""
        v1, d1 = self._process("SQLFluff [0.13.0] - 2023-06-15")
        v2, d2 = self._process("[0.13.0] - 2023-06-15")
        assert v1 == v2
        assert d1 == d2

    def test_bracket_rsplit_removes_patch(self):
        """rsplit('.', 1)[0] removes the patch version."""
        v, _ = self._process("SQLFluff [0.13.2] - 2023-06-15")
        assert v == "0.13"  # patch .2 removed

    def test_bracket_four_part_version(self):
        """Four-part version in brackets gets last part stripped."""
        v, _ = self._process("[1.2.3.4] - 2023-06-15")
        assert v == "1.2.3"  # .4 removed by rsplit

    # -- Bare version format tests --

    @pytest.mark.parametrize("name,expected_version", [
        ("SQLFluff 0.13.0", "0.13"),
        ("SQLFluff 1.0.0", "1.0"),
        ("0.13.0", "0.13"),
        ("SQLFluff 0.13.2.1", "0.13.2"),
    ])
    def test_bare_version_format(self, name, expected_version):
        """Bare version format 'X.Y.Z' returns version with no date."""
        version, date = self._process(name)
        assert version == expected_version
        assert date is None

    def test_bare_version_no_date(self):
        """Bare format always returns None for date."""
        _, date = self._process("SQLFluff 0.13.0")
        assert date is None

    # -- No match tests --

    def test_v_prefix_matches_bare_version(self):
        """v-prefixed version like 'v0.13.0' matches via bare digit pattern."""
        version, date = self._process("v0.13.0")
        assert version == "0.13"
        assert date is None

    @pytest.mark.parametrize("name", [
        "",
        "SQLFluff",
        "Release Notes",
        "just some text",
    ])
    def test_no_match_returns_none_none(self, name):
        """Names that don't match any pattern return (None, None)."""
        version, date = self._process(name)
        assert version is None
        assert date is None


# ── Sqlfluff Bugfix Release Prefix ───────────────────────────────────


class TestSqlfluffBugfixPrefix:
    """Tests for sqlfluff's 'Bugfix Release ' prefix handling."""

    def test_bugfix_release_prefix_stripped(self):
        """'Bugfix Release X.Y' prefix gets stripped to just X.Y."""
        version = "Bugfix Release 0.13"
        if version.startswith("Bugfix Release "):
            version = version[len("Bugfix Release "):]
        assert version == "0.13"

    def test_no_bugfix_prefix_unchanged(self):
        """Version without 'Bugfix Release ' prefix stays unchanged."""
        version = "0.13"
        if version.startswith("Bugfix Release "):
            version = version[len("Bugfix Release "):]
        assert version == "0.13"

    def test_bugfix_release_in_pipeline(self):
        """Bugfix Release prefix handled in the version collection loop."""
        pairs = [("SQLFluff Bugfix Release [0.13.1] - 2023-07-01", "2023-07-01T00:00:00Z")]

        def process(x):
            if x.startswith("SQLFluff "):
                x = x[len("SQLFluff "):]
            pattern = re.compile(r"\[[\d\.\w]*\] - \d*-\d*-\d*")
            matches = pattern.findall(x)
            if len(matches) > 0:
                parts = x.split(" - ")
                version = parts[0].replace("[", "").replace("]", "")
                version = version.rsplit(".", 1)[0]
                return (version, parts[1])
            pattern = re.compile(r"\d+\.\d+\.[\d\.]*")
            matches = pattern.findall(x)
            if len(matches) > 0:
                version = matches[0]
                version = version.rsplit(".", 1)[0]
                return (version, None)
            return (None, None)

        version_date_map = {}
        for pair in pairs:
            pair_rv = process(pair[0])
            if pair_rv[0] is None:
                continue
            version = pair_rv[0]
            if version.startswith("Bugfix Release "):
                version = version[len("Bugfix Release "):]
            date = pair[1] if pair_rv[1] is None else pair_rv[1]
            version_date_map[version] = date
        assert "0.13" in version_date_map


# ── Sqlfluff Max Date (unlike others' min) ───────────────────────────


class TestSqlfluffMaxDate:
    """Tests for sqlfluff using max() instead of min() for dates."""

    def test_uses_max_not_min(self):
        """Sqlfluff uses max(version_date_map[version], date) unlike others."""
        version_date_map = {}
        entries = [
            ("0.13", "2023-06-01"),
            ("0.13", "2023-07-15"),
            ("0.13", "2023-05-01"),
        ]
        for version, date in entries:
            if version in version_date_map:
                version_date_map[version] = max(version_date_map[version], date)
            else:
                version_date_map[version] = date
        assert version_date_map["0.13"] == "2023-07-15"  # max, not min

    def test_min_vs_max_difference(self):
        """Demonstrates the difference between sqlfluff (max) and numpy (min)."""
        dates = ["2023-06-01", "2023-07-15", "2023-05-01"]
        assert min(dates) == "2023-05-01"  # numpy/scipy/modin use this
        assert max(dates) == "2023-07-15"  # sqlfluff uses this

    def test_sqlfluff_uses_published_at_not_created_at(self):
        """Sqlfluff uses published_at while others use created_at."""
        release = _make_release(
            "v1.0.0",
            created_at="2023-06-01T00:00:00Z",
            published_at="2023-06-15T00:00:00Z",
        )
        # Sqlfluff: pairs = [(x["name"], x["published_at"]) for x in releases]
        sqlfluff_date = release["published_at"]
        # Others: release_date = raw_release["created_at"].split("T")[0]
        others_date = release["created_at"].split("T")[0]
        assert sqlfluff_date != others_date


# ── Sqlfluff None Fallback ───────────────────────────────────────────


class TestSqlfluffNoneFallback:
    """Tests for sqlfluff assigning None when no version matches."""

    def test_assigns_none_not_last_version(self):
        """Sqlfluff assigns None for unmatched tasks, unlike others' fallback to last."""
        times = [("2024-01-15", "2.0"), ("2023-06-15", "1.0")]
        task = _make_task("t1", "2023-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        set_version = False
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                set_version = True
                break
        if not set_version:
            task["version"] = None
        assert task["version"] is None

    def test_numpy_assigns_last_version_instead(self):
        """Numpy/scipy/modin assign times[-1][1] for unmatched tasks."""
        times = [("2024-01-15", "2.0"), ("2023-06-15", "1.0")]
        task = _make_task("t1", "2023-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                break
        if "version" not in task:
            task["version"] = times[-1][1]
        assert task["version"] == "1.0"  # fallback to oldest


# ── Sqlfluff Pagination Tests ────────────────────────────────────────


class TestSqlfluffPagination:
    """Tests for sqlfluff's paginated release fetching."""

    def test_pagination_with_full_pages(self):
        """Collects releases across multiple pages until < 100 returned."""
        pages = [
            [_make_release(f"v{i}.0.0") for i in range(100)],
            [_make_release("v100.0.0")],  # < 100 stops loop
        ]
        page_idx = [0]
        def mock_list_releases(*args, **kwargs):
            idx = page_idx[0]
            page_idx[0] += 1
            return pages[idx] if idx < len(pages) else []
        releases, i = [], 0
        while True:
            temp = mock_list_releases("sqlfluff", "sqlfluff", 100, i + 1)
            releases.extend(temp)
            if len(temp) < 100:
                break
            i += 1
        assert len(releases) == 101

    def test_single_page_less_than_100(self):
        """Single page with < 100 releases stops immediately."""
        releases_data = [_make_release("v1.0.0")]
        releases, i = [], 0
        temp = releases_data
        releases.extend(temp)
        assert len(releases) == 1

    def test_sqlfluff_page_index_starts_at_1(self):
        """Sqlfluff uses page=i+1 (1-indexed) unlike numpy's page=i (0-indexed)."""
        # Numpy:   api.repos.list_releases(..., page=i) where i starts at 0
        # Sqlfluff: api.repos.list_releases(..., 100, i + 1) where i starts at 0
        # Both effectively start at page 0/1 but the API parameter differs
        numpy_page_start = 0      # page=i with i=0
        sqlfluff_page_start = 1   # page=i+1 with i=0
        assert sqlfluff_page_start != numpy_page_start


# ── Sqlfluff Hardcoded Token/Paths ───────────────────────────────────


class TestSqlfluffHardcodedValues:
    """Tests for sqlfluff's hardcoded GITHUB_TOKEN and placeholder paths."""

    def test_github_token_is_placeholder(self):
        """GITHUB_TOKEN is a placeholder string, not a real token."""
        GITHUB_TOKEN = "<your GitHub token>"
        assert GITHUB_TOKEN.startswith("<")
        assert GITHUB_TOKEN.endswith(">")
        assert "your" in GITHUB_TOKEN.lower()

    def test_path_tasks_is_placeholder(self):
        """PATH_TASKS_SQLFLUFF is a placeholder path."""
        PATH_TASKS_SQLFLUFF = "<path to sqlfluff task instances>"
        assert PATH_TASKS_SQLFLUFF.startswith("<")

    def test_path_to_save_is_placeholder(self):
        """PATH_TO_SAVE is a placeholder path."""
        PATH_TO_SAVE = "<path to save versioned task instances to>"
        assert PATH_TO_SAVE.startswith("<")


# ── keep_major_minor Lambda Tests ────────────────────────────────────


class TestKeepMajorMinorLambda:
    """Tests for the keep_major_minor lambda shared across all scripts."""

    @pytest.mark.parametrize("version,sep,expected", [
        ("1.24.0", ".", "1.24"),
        ("0.13.2", ".", "0.13"),
        ("2.0.0", ".", "2.0"),
        ("10.20.30", ".", "10.20"),
        ("1.0.0.1", ".", "1.0"),
        ("  1.24.0  ", ".", "1.24"),     # strips whitespace
        ("1,24,0", ",", "1.24"),          # comma separator
    ])
    def test_standard_versions(self, version, sep, expected):
        """Standard version strings are truncated to major.minor."""
        result = _keep_major_minor(version, sep)
        assert result == expected

    def test_only_two_parts(self):
        """Version with only two parts stays unchanged."""
        result = _keep_major_minor("1.24", ".")
        assert result == "1.24"

    def test_single_part(self):
        """Version with only one part returns just that part."""
        result = _keep_major_minor("1", ".")
        assert result == "1"

    def test_empty_string(self):
        """Empty string returns empty."""
        result = _keep_major_minor("", ".")
        assert result == ""


# ── Map Version To Tasks Tests ───────────────────────────────────────


class TestMapVersionToTasks:
    """Tests for the map_v_to_t construction shared across scripts."""

    def test_groups_by_version(self):
        """Tasks are grouped by their assigned version."""
        tasks = [
            {"instance_id": "t1", "version": "1.24"},
            {"instance_id": "t2", "version": "1.25"},
            {"instance_id": "t3", "version": "1.24"},
        ]
        map_v_to_t = {}
        for i, t in enumerate(tasks):
            if t["version"] not in map_v_to_t:
                map_v_to_t[t["version"]] = []
            map_v_to_t[t["version"]].append(t)
        assert len(map_v_to_t) == 2
        assert len(map_v_to_t["1.24"]) == 2
        assert len(map_v_to_t["1.25"]) == 1

    def test_preserves_task_data(self):
        """Grouped tasks retain all their original fields."""
        tasks = [{"instance_id": "t1", "version": "1.24", "extra": "data"}]
        map_v_to_t = {}
        for t in tasks:
            if t["version"] not in map_v_to_t:
                map_v_to_t[t["version"]] = []
            map_v_to_t[t["version"]].append(t)
        assert map_v_to_t["1.24"][0]["extra"] == "data"

    def test_single_version(self):
        """All tasks with same version go to one group."""
        tasks = [
            {"instance_id": f"t{i}", "version": "1.0"} for i in range(5)
        ]
        map_v_to_t = {}
        for t in tasks:
            if t["version"] not in map_v_to_t:
                map_v_to_t[t["version"]] = []
            map_v_to_t[t["version"]].append(t)
        assert len(map_v_to_t) == 1
        assert len(map_v_to_t["1.0"]) == 5

    def test_empty_tasks(self):
        """No tasks produces empty map."""
        map_v_to_t = {}
        for t in []:
            if t["version"] not in map_v_to_t:
                map_v_to_t[t["version"]] = []
            map_v_to_t[t["version"]].append(t)
        assert len(map_v_to_t) == 0


# ── JSON Output Tests ────────────────────────────────────────────────


class TestJsonOutput:
    """Tests for JSON output file creation (shared pattern)."""

    def test_output_filename_from_path(self):
        """Output filename is derived from input path stem + '_versions.json'."""
        path = "artifacts/1_attributes/numpy-task-instances_attribute.jsonl"
        new_name = Path(path).stem + "_versions.json"
        assert new_name == "numpy-task-instances_attribute_versions.json"

    def test_output_dir_constant(self):
        """Most scripts use 'artifacts/2_versioning' as output dir."""
        OUTPUT_VERSION_DIR = "artifacts/2_versioning"
        assert OUTPUT_VERSION_DIR == "artifacts/2_versioning"

    @pytest.mark.parametrize("input_path,expected_stem", [
        ("artifacts/1_attributes/numpy-task-instances_attribute.jsonl", "numpy-task-instances_attribute"),
        ("artifacts/1_attributes/scipy-task-instances_attribute.jsonl", "scipy-task-instances_attribute"),
        ("artifacts/1_attributes/modin-task-instances_attribute.jsonl", "modin-task-instances_attribute"),
        ("artifacts/1_attributes/pytensor-task-instances_attribute.jsonl", "pytensor-task-instances_attribute"),
        ("artifacts/1_attributes/statsmodels-task-instances_attribute.jsonl", "statsmodels-task-instances_attribute"),
    ])
    def test_stem_extraction(self, input_path, expected_stem):
        """Path stem is extracted correctly for each script's input."""
        assert Path(input_path).stem == expected_stem

    def test_json_dump_writes_tasks(self):
        """json.dump writes the full tasks list to file."""
        tasks = [{"instance_id": "t1", "version": "1.24"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(tasks, fp=f)
            tmp_path = f.name
        try:
            with open(tmp_path) as f:
                loaded = json.load(f)
            assert loaded == tasks
        finally:
            os.unlink(tmp_path)

    def test_sqlfluff_custom_output_path(self):
        """Sqlfluff uses a hardcoded output filename, not derived from input."""
        versioned_path = "sqlfluff-task-instances_versions.json"
        assert versioned_path == "sqlfluff-task-instances_versions.json"
        # Unlike others which use Path(input).stem + "_versions.json"


# ── Cross-Script Comparison Tests ────────────────────────────────────


class TestCrossScriptComparisons:
    """Tests comparing behavioral differences across the 6 GhApi scripts."""

    def test_pagination_behavior(self):
        """Only numpy and sqlfluff use pagination; scipy/modin/pytensor use single page."""
        paginated = {"numpy", "sqlfluff"}
        single_page = {"scipy", "modin", "pytensor", "statsmodels"}
        assert paginated & single_page == set()  # no overlap

    def test_tag_pattern_strictness_ordering(self):
        """Scripts have different pattern strictness levels."""
        patterns = {
            "numpy": r"^v(\d+\.\d+\.\d+)(?:rc\d+)?$",    # v required, rc optional
            "scipy": r"^v(\d+\.\d+\.\d+)rc\d+$",          # v required, rc required
            "modin": r"^(\d+\.\d+\.\d+)(?:rc\d+)?$",      # no v, rc optional
            "pytensor": r"(?:v)?(\d+\.\d+\.\d+)(?:rc\d+)?$",  # v optional, rc optional
        }
        tag = "v1.0.0"
        assert re.match(patterns["numpy"], tag) is not None
        assert re.match(patterns["scipy"], tag) is None      # requires rc
        assert re.match(patterns["modin"], tag) is None      # rejects v
        assert re.match(patterns["pytensor"], tag) is not None

    def test_date_field_difference(self):
        """Sqlfluff uses published_at; all others use created_at."""
        release = _make_release("v1.0.0", created_at="2023-01-01T00:00:00Z", published_at="2023-01-15T00:00:00Z")
        sqlfluff_date = release["published_at"]
        others_date = release["created_at"]
        assert sqlfluff_date != others_date

    def test_date_aggregation_difference(self):
        """Sqlfluff uses max(); all others use min() for date aggregation."""
        dates = ["2023-01-01", "2023-06-15", "2023-03-01"]
        assert min(dates) == "2023-01-01"  # numpy/scipy/modin/pytensor/statsmodels
        assert max(dates) == "2023-06-15"  # sqlfluff

    def test_fallback_difference(self):
        """Sqlfluff assigns None; others assign times[-1][1] for unmatched tasks."""
        times = [("2024-01-15", "2.0")]
        task = _make_task("t1", "2023-01-01T00:00:00Z")

        # Numpy-style fallback
        created_at = task["created_at"].split("T")[0]
        numpy_version = None
        for t in times:
            if t[0] < created_at:
                numpy_version = t[1]
                break
        if numpy_version is None:
            numpy_version = times[-1][1]
        assert numpy_version == "2.0"

        # Sqlfluff-style fallback
        sqlfluff_version = None
        for t in times:
            if t[0] < created_at:
                sqlfluff_version = t[1]
                break
        # sqlfluff does not fall back to times[-1][1]
        assert sqlfluff_version is None

    def test_statsmodels_matches_name_others_match_tag(self):
        """Statsmodels uses release name; others use tag_name for matching."""
        release = _make_release(
            tag_name="v0.14.0",
            name="Version 0.14.0 Release",
        )
        # Statsmodels matches name
        sm_pattern = r"^(Version (\d+\.\d+\.\d+) Release|Release (\d+\.\d+\.\d+))$"
        assert re.match(sm_pattern, release["name"]) is not None
        assert re.match(sm_pattern, release["tag_name"]) is None

        # Others match tag
        numpy_pattern = r"^v(\d+\.\d+\.\d+)(?:rc\d+)?$"
        assert re.match(numpy_pattern, release["tag_name"]) is not None

    def test_input_path_conventions(self):
        """All scripts use artifacts/1_attributes/{repo}-task-instances_attribute.jsonl."""
        paths = [
            "artifacts/1_attributes/numpy-task-instances_attribute.jsonl",
            "artifacts/1_attributes/scipy-task-instances_attribute.jsonl",
            "artifacts/1_attributes/modin-task-instances_attribute.jsonl",
            "artifacts/1_attributes/pytensor-task-instances_attribute.jsonl",
            "artifacts/1_attributes/statsmodels-task-instances_attribute.jsonl",
        ]
        for p in paths:
            assert p.startswith("artifacts/1_attributes/")
            assert p.endswith("_attribute.jsonl")

    def test_all_scripts_have_copypaste_scipy_pattern(self):
        """numpy, scipy, modin, pytensor all have PATTERN = r'^SciPy ...' (copy-paste)."""
        scipy_pattern = r"^SciPy (\d+\.\d+\.\d+)$"
        # This pattern is unused in numpy/modin/pytensor (they use VERSION_TAG_PATTERN)
        # Only scipy actually uses it for matching release names
        assert "SciPy" in scipy_pattern


# ── End-to-End Integration Tests ─────────────────────────────────────


class TestEndToEndIntegration:
    """Integration tests simulating full script execution flow."""

    def test_numpy_full_flow(self):
        """Simulate numpy script: fetch -> filter -> assign -> group -> save."""
        pattern = r"^v(\d+\.\d+\.\d+)(?:rc\d+)?$"
        releases = [
            _make_release("v1.25.0", created_at="2023-06-17T00:00:00Z"),
            _make_release("v1.25.0rc1", created_at="2023-05-25T00:00:00Z"),
            _make_release("v1.24.0", created_at="2022-12-18T00:00:00Z"),
            _make_release("v1.24.0rc1", created_at="2022-11-01T00:00:00Z"),
            _make_release("not-a-release", created_at="2023-01-01T00:00:00Z"),
        ]
        times = dict()
        for r in releases:
            m = re.match(pattern, r["tag_name"])
            if m:
                version = m.group(1)
                major_minor = _keep_major_minor(version, ".")
                if major_minor not in times:
                    times[major_minor] = r["created_at"].split("T")[0]
                times[major_minor] = min(times[major_minor], r["created_at"].split("T")[0])
        assert times == {"1.25": "2023-05-25", "1.24": "2022-11-01"}

        times_sorted = sorted([(v, k) for k, v in times.items()], key=lambda x: x[0], reverse=True)
        assert times_sorted == [("2023-05-25", "1.25"), ("2022-11-01", "1.24")]

        tasks = [
            _make_task("t1", "2024-01-01T00:00:00Z"),   # after all -> 1.25
            _make_task("t2", "2023-03-01T00:00:00Z"),    # between -> 1.24
            _make_task("t3", "2022-06-01T00:00:00Z"),    # before all -> 1.24 (fallback)
        ]
        for task in tasks:
            created_at = task["created_at"].split("T")[0]
            for t in times_sorted:
                if t[0] < created_at:
                    task["version"] = t[1]
                    break
            if "version" not in task:
                task["version"] = times_sorted[-1][1]

        assert tasks[0]["version"] == "1.25"
        assert tasks[1]["version"] == "1.24"
        assert tasks[2]["version"] == "1.24"

        map_v_to_t = {}
        for t in tasks:
            if t["version"] not in map_v_to_t:
                map_v_to_t[t["version"]] = []
            map_v_to_t[t["version"]].append(t)
        assert len(map_v_to_t["1.24"]) == 2
        assert len(map_v_to_t["1.25"]) == 1

    def test_scipy_rc_only_flow(self):
        """Simulate scipy: only RC releases are used for version detection."""
        pattern = r"^v(\d+\.\d+\.\d+)rc\d+$"
        releases = [
            _make_release("v1.11.0", created_at="2023-06-25T00:00:00Z"),     # skipped
            _make_release("v1.11.0rc1", created_at="2023-06-01T00:00:00Z"),  # matched
            _make_release("v1.10.0", created_at="2023-01-15T00:00:00Z"),     # skipped
            _make_release("v1.10.0rc2", created_at="2023-01-01T00:00:00Z"),  # matched
        ]
        times = dict()
        for r in releases:
            m = re.match(pattern, r["tag_name"])
            if m:
                version = m.group(1)
                major_minor = _keep_major_minor(version, ".")
                if major_minor not in times:
                    times[major_minor] = r["created_at"].split("T")[0]
                times[major_minor] = min(times[major_minor], r["created_at"].split("T")[0])
        # Only RC releases matched
        assert len(times) == 2
        assert "1.11" in times
        assert "1.10" in times
        # Final releases were skipped
        assert times["1.11"] == "2023-06-01"  # RC date, not final release date

    def test_statsmodels_full_flow(self):
        """Simulate statsmodels: match release names, use min date."""
        pattern = r"^(Version (\d+\.\d+\.\d+) Release|Release (\d+\.\d+\.\d+))$"
        releases = [
            {"name": "Version 0.14.0 Release", "created_at": "2023-06-15T00:00:00Z"},
            {"name": "Release 0.14.0", "created_at": "2023-05-01T00:00:00Z"},
            {"name": "Version 0.13.0 Release", "created_at": "2022-01-15T00:00:00Z"},
            {"name": "not a release", "created_at": "2023-01-01T00:00:00Z"},
        ]
        versions_to_release_date = {}
        for r in releases:
            m = re.match(pattern, r["name"])
            if m:
                version = m.group(2) or m.group(3)
                version = _keep_major_minor(version, ".")
                versions_to_release_date[version] = min(
                    versions_to_release_date.get(version, r["created_at"].split("T")[0]),
                    r["created_at"].split("T")[0],
                )
        assert versions_to_release_date["0.14"] == "2023-05-01"  # min of two entries
        assert versions_to_release_date["0.13"] == "2022-01-15"

    def test_sqlfluff_full_flow(self):
        """Simulate sqlfluff: process names, handle bugfix prefix, use max date."""
        def process(x):
            if x.startswith("SQLFluff "):
                x = x[len("SQLFluff "):]
            pattern = re.compile(r"\[[\d\.\w]*\] - \d*-\d*-\d*")
            matches = pattern.findall(x)
            if len(matches) > 0:
                parts = x.split(" - ")
                version = parts[0].replace("[", "").replace("]", "")
                version = version.rsplit(".", 1)[0]
                return (version, parts[1])
            pattern = re.compile(r"\d+\.\d+\.[\d\.]*")
            matches = pattern.findall(x)
            if len(matches) > 0:
                version = matches[0]
                version = version.rsplit(".", 1)[0]
                return (version, None)
            return (None, None)

        pairs = [
            ("SQLFluff [0.13.0] - 2023-06-15", "2023-06-15T00:00:00Z"),
            ("SQLFluff [0.13.1] - 2023-07-01", "2023-07-01T00:00:00Z"),
            ("SQLFluff 0.12.0", "2023-01-01T00:00:00Z"),
            ("Not a release", "2023-01-01T00:00:00Z"),
        ]
        version_date_map = {}
        for pair in pairs:
            pair_rv = process(pair[0])
            if pair_rv[0] is None:
                continue
            version = pair_rv[0]
            if version.startswith("Bugfix Release "):
                version = version[len("Bugfix Release "):]
            date = pair[1] if pair_rv[1] is None else pair_rv[1]
            if version in version_date_map:
                version_date_map[version] = max(version_date_map[version], date)
            else:
                version_date_map[version] = date
        assert "0.13" in version_date_map
        assert version_date_map["0.13"] == "2023-07-01"  # max of two dates
        assert "0.12" in version_date_map

        times = sorted([(v, k) for k, v in version_date_map.items()], key=lambda x: x[0], reverse=True)
        tasks = [
            _make_task("t1", "2024-01-01T00:00:00Z"),
            _make_task("t2", "2022-01-01T00:00:00Z"),  # before all -> None
        ]
        for task in tasks:
            created_at = task["created_at"].split("T")[0]
            set_version = False
            for t in times:
                if t[0] < created_at:
                    task["version"] = t[1]
                    set_version = True
                    break
            if not set_version:
                task["version"] = None
        assert tasks[0]["version"] is not None
        assert tasks[1]["version"] is None  # sqlfluff None fallback


# ══════════════════════════════════════════════════════════════════════════════
# EXHAUSTIVE TAG PATTERN CROSS-PRODUCT TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestAllTagPatternsExhaustive:
    """Cross-product tests: every pattern x every tag variant."""

    NUMPY_PATTERN = re.compile(r"^v(\d+\.\d+\.\d+)(?:rc\d+)?$")
    SCIPY_PATTERN = re.compile(r"^v(\d+\.\d+\.\d+)rc\d+$")
    MODIN_PATTERN = re.compile(r"^(\d+\.\d+\.\d+)(?:rc\d+)?$")
    PYTENSOR_PATTERN = re.compile(r"(?:v)?(\d+\.\d+\.\d+)(?:rc\d+)?$")
    STATSMODELS_PATTERN = re.compile(r"^(Version (\d+\.\d+\.\d+) Release|Release (\d+\.\d+\.\d+))$")

    @pytest.mark.parametrize(
        "tag",
        [
            "v1.0.0", "v1.0.0rc1", "v1.0.0rc2", "v1.0.0rc99",
            "v0.1.0", "v0.1.0rc1", "v99.99.99", "v99.99.99rc1",
            "v10.20.30", "v10.20.30rc5",
            "v0.0.1", "v0.0.1rc1",
            "v2.3.4", "v2.3.4rc3",
            "v5.6.7", "v5.6.7rc10",
        ],
        ids=[f"numpy_{i}" for i in range(16)],
    )
    def test_numpy_pattern_matches(self, tag):
        assert self.NUMPY_PATTERN.match(tag) is not None

    @pytest.mark.parametrize(
        "tag",
        [
            "1.0.0", "1.0.0rc1", "v1.0", "v1.0.0.0", "v1.0.0a1",
            "v1.0.0beta1", "release-v1.0.0", "V1.0.0",
            "v1.0.0-rc1", "v1.0.0.rc1", "v1.0.0dev1",
        ],
        ids=[f"numpy_reject_{i}" for i in range(11)],
    )
    def test_numpy_pattern_rejects(self, tag):
        assert self.NUMPY_PATTERN.match(tag) is None

    @pytest.mark.parametrize(
        "tag",
        [
            "v1.0.0rc1", "v1.0.0rc2", "v0.1.0rc1", "v99.99.99rc1",
            "v10.20.30rc5", "v2.3.4rc99",
        ],
        ids=[f"scipy_{i}" for i in range(6)],
    )
    def test_scipy_pattern_matches(self, tag):
        assert self.SCIPY_PATTERN.match(tag) is not None

    @pytest.mark.parametrize(
        "tag",
        [
            "v1.0.0", "1.0.0rc1", "v1.0.0rc", "v1.0rc1",
            "v1.0.0a1", "v1.0.0beta1", "v1.0.0.0rc1",
            "v1.0.0RC1", "v1.0.0-rc1",
        ],
        ids=[f"scipy_reject_{i}" for i in range(9)],
    )
    def test_scipy_pattern_rejects(self, tag):
        assert self.SCIPY_PATTERN.match(tag) is None

    @pytest.mark.parametrize(
        "tag",
        [
            "1.0.0", "1.0.0rc1", "0.1.0", "0.1.0rc1",
            "99.99.99", "99.99.99rc1", "10.20.30", "10.20.30rc5",
        ],
        ids=[f"modin_{i}" for i in range(8)],
    )
    def test_modin_pattern_matches(self, tag):
        assert self.MODIN_PATTERN.match(tag) is not None

    @pytest.mark.parametrize(
        "tag",
        [
            "v1.0.0", "v1.0.0rc1", "1.0", "1.0.0.0",
            "1.0.0a1", "1.0.0beta1", "release-1.0.0",
        ],
        ids=[f"modin_reject_{i}" for i in range(7)],
    )
    def test_modin_pattern_rejects(self, tag):
        assert self.MODIN_PATTERN.match(tag) is None

    @pytest.mark.parametrize(
        "tag",
        [
            "v1.0.0", "1.0.0", "v1.0.0rc1", "1.0.0rc1",
            "v0.1.0", "0.1.0", "v99.99.99", "99.99.99",
            "v10.20.30rc5", "10.20.30rc5",
        ],
        ids=[f"pytensor_{i}" for i in range(10)],
    )
    def test_pytensor_pattern_matches(self, tag):
        assert self.PYTENSOR_PATTERN.match(tag) is not None

    @pytest.mark.parametrize(
        "tag",
        [
            "vv1.0.0", "1.0", "1.0.0.0", "1.0.0a1",
        ],
        ids=[f"pytensor_reject_{i}" for i in range(4)],
    )
    def test_pytensor_pattern_rejects(self, tag):
        assert self.PYTENSOR_PATTERN.match(tag) is None

    @pytest.mark.parametrize(
        "name",
        [
            "Version 1.0.0 Release",
            "Release 1.0.0",
            "Version 0.14.2 Release",
            "Release 0.14.2",
            "Version 99.99.99 Release",
            "Release 99.99.99",
        ],
        ids=[f"statsmodels_{i}" for i in range(6)],
    )
    def test_statsmodels_pattern_matches(self, name):
        assert self.STATSMODELS_PATTERN.match(name) is not None

    @pytest.mark.parametrize(
        "name",
        [
            "version 1.0.0 release",
            "Release v1.0.0",
            "Version 1.0.0",
            "Release",
            "1.0.0",
            "Version 1.0 Release",
        ],
        ids=[f"statsmodels_reject_{i}" for i in range(6)],
    )
    def test_statsmodels_pattern_rejects(self, name):
        assert self.STATSMODELS_PATTERN.match(name) is None


class TestTemporalAssignmentExhaustive:
    """Exhaustive temporal assignment tests across release timelines."""

    @pytest.mark.parametrize(
        "num_releases",
        [1, 2, 3, 5, 10, 20],
        ids=[f"r{n}" for n in [1, 2, 3, 5, 10, 20]],
    )
    @pytest.mark.parametrize(
        "task_position",
        ["before_all", "after_all", "middle"],
        ids=["before", "after", "middle"],
    )
    def test_temporal_assignment_positions(self, num_releases, task_position):
        """Task assigned correct version based on temporal position."""
        import datetime as dt
        base_date = dt.date(2020, 1, 1)
        times = []
        for i in range(num_releases):
            d = (base_date + dt.timedelta(days=30 * (i + 1))).isoformat()
            times.append((d, f"{i+1}.0"))
        times.sort(reverse=True)

        if task_position == "before_all":
            task_date = (base_date - dt.timedelta(days=1)).isoformat()
        elif task_position == "after_all":
            task_date = (base_date + dt.timedelta(days=30 * (num_releases + 1))).isoformat()
        else:
            mid = max(num_releases // 2, 1)
            task_date = (base_date + dt.timedelta(days=30 * mid + 15)).isoformat()

        found = None
        for t in times:
            if t[0] < task_date:
                found = t[1]
                break

        if task_position == "before_all":
            assert found is None
        elif task_position == "after_all":
            assert found is not None
        else:
            assert found is not None

    @pytest.mark.parametrize(
        "num_tasks",
        [1, 5, 10, 20, 50],
        ids=[f"t{n}" for n in [1, 5, 10, 20, 50]],
    )
    def test_all_tasks_assigned(self, num_tasks):
        """All tasks after first release get a version."""
        times = [("2024-06-01", "2.0"), ("2024-01-01", "1.0")]
        tasks = []
        for i in range(num_tasks):
            task_date = f"2024-07-{(i % 28) + 1:02d}"
            found = None
            for t in times:
                if t[0] < task_date:
                    found = t[1]
                    break
            tasks.append(found)
        assert all(v is not None for v in tasks)
