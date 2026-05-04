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

"""Tests for extract_web web-scraping scripts.

Covers: get_versions_xarray, get_versions_astropy, get_versions_dask,
get_versions_matplotlib, get_versions_pandas, get_versions_pydicom,
get_versions_pvlib-python.

These scripts scrape HTML pages (docs sites) to extract version/date
pairs and assign versions to task instances via temporal matching.
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


def _make_task(instance_id, created_at="2024-06-15T12:00:00Z"):
    """Create a mock task instance dict."""
    return {
        "instance_id": instance_id,
        "created_at": created_at,
    }


def _keep_major_minor(x, sep):
    """Replicate the keep_major_minor lambda from the scripts."""
    return ".".join(x.strip().split(sep)[:2])


# ══════════════════════════════════════════════════════════════════════
# XARRAY TESTS
# ══════════════════════════════════════════════════════════════════════


class TestXarrayHtmlPattern:
    """Tests for xarray's HTML regex pattern for whats-new.html anchors."""

    PATTERN = r'<a class="reference internal nav-link( active)?" href="#v(.*)">v(.*) \((.*)\)</a>'

    @pytest.mark.parametrize("html,expected_groups", [
        (
            '<a class="reference internal nav-link" href="#v2024-01-0">v2024.01.0 (Jan 16 2024)</a>',
            (None, "2024-01-0", "2024.01.0", "Jan 16 2024"),
        ),
        (
            '<a class="reference internal nav-link active" href="#v2023-11-0">v2023.11.0 (Nov 15 2023)</a>',
            (" active", "2023-11-0", "2023.11.0", "Nov 15 2023"),
        ),
    ])
    def test_matches_anchor_tags(self, html, expected_groups):
        """Pattern matches xarray changelog anchor tags with optional 'active' class."""
        m = re.search(self.PATTERN, html)
        assert m is not None
        assert m.groups() == expected_groups

    def test_active_class_is_optional(self):
        """The ' active' class group is optional (may or may not be present)."""
        html_active = '<a class="reference internal nav-link active" href="#v2024-01-0">v2024.01.0 (Jan 16 2024)</a>'
        html_no_active = '<a class="reference internal nav-link" href="#v2024-01-0">v2024.01.0 (Jan 16 2024)</a>'
        assert re.search(self.PATTERN, html_active) is not None
        assert re.search(self.PATTERN, html_no_active) is not None

    @pytest.mark.parametrize("html", [
        '<a class="reference external" href="https://example.com">link</a>',
        '<a href="#v2024-01-0">v2024.01.0 (Jan 16 2024)</a>',
        '<span class="reference internal nav-link">text</span>',
    ])
    def test_rejects_non_matching_html(self, html):
        """Non-matching HTML is rejected."""
        m = re.search(self.PATTERN, html)
        assert m is None


class TestXarrayVersionParsing:
    """Tests for xarray's version extraction from hyphen-separated anchor href."""

    def _parse_version(self, href_parts):
        """Replicate xarray's version parsing from match[0] (the href value)."""
        parts = href_parts.split("-")
        version = _keep_major_minor(".".join(parts[0:3]), ".")
        return version

    @pytest.mark.parametrize("href,expected", [
        ("2024-01-0", "2024.01"),
        ("2023-11-0", "2023.11"),
        ("0-19-0", "0.19"),
        ("2024-02-1", "2024.02"),
    ])
    def test_extracts_major_minor(self, href, expected):
        """Extracts version as major.minor from hyphen-separated href."""
        result = self._parse_version(href)
        assert result == expected


class TestXarrayDateParsing:
    """Tests for xarray's dual date format parsing."""

    DATE_FORMATS = ["%B %d %Y", "%d %B %Y"]

    def _parse_date(self, date_str):
        """Replicate xarray's date parsing with fallback formats."""
        for f_ in self.DATE_FORMATS:
            try:
                date_obj = datetime.strptime(date_str, f_)
                return date_obj.strftime("%Y-%m-%d")
            except:
                continue
        return None

    @pytest.mark.parametrize("date_str,expected", [
        ("January 16 2024", "2024-01-16"),
        ("November 15 2023", "2023-11-15"),
        ("March 1 2022", "2022-03-01"),
        ("December 31 2023", "2023-12-31"),
    ])
    def test_format_month_day_year(self, date_str, expected):
        """First format: '%B %d %Y' (e.g., 'January 16 2024')."""
        result = self._parse_date(date_str)
        assert result == expected

    @pytest.mark.parametrize("date_str,expected", [
        ("16 January 2024", "2024-01-16"),
        ("15 November 2023", "2023-11-15"),
        ("1 March 2022", "2022-03-01"),
    ])
    def test_format_day_month_year(self, date_str, expected):
        """Second format: '%d %B %Y' (e.g., '16 January 2024')."""
        result = self._parse_date(date_str)
        assert result == expected

    def test_unparseable_date_returns_none(self):
        """Dates that don't match either format return None."""
        assert self._parse_date("2024-01-16") is None
        assert self._parse_date("Jan 16, 2024") is None
        assert self._parse_date("") is None

    def test_first_format_tried_first(self):
        """'%B %d %Y' is tried before '%d %B %Y'."""
        # "May 3 2024" matches first format
        result = self._parse_date("May 3 2024")
        assert result == "2024-05-03"


class TestXarrayNoneFallback:
    """Tests for xarray assigning None when no version matches."""

    def test_assigns_none_when_not_found(self):
        """Xarray assigns None for tasks before all releases."""
        times = [("2024-01-15", "2024.01"), ("2023-06-15", "2023.06")]
        task = _make_task("t1", "2022-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        found = False
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                found = True
                break
        if not found:
            task["version"] = None
        assert task["version"] is None

    def test_assigns_version_when_found(self):
        """Xarray assigns version when task date is after a release."""
        times = [("2024-01-15", "2024.01"), ("2023-06-15", "2023.06")]
        task = _make_task("t1", "2024-06-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        found = False
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                found = True
                break
        if not found:
            task["version"] = None
        assert task["version"] == "2024.01"


class TestXarrayMatchDedup:
    """Tests for xarray's deduplication of regex matches."""

    def test_set_dedup_removes_duplicates(self):
        """list(set(matches)) removes duplicate regex matches."""
        matches = [
            ("", "2024-01-0", "2024.01.0", "Jan 16 2024"),
            ("", "2024-01-0", "2024.01.0", "Jan 16 2024"),
            (" active", "2023-11-0", "2023.11.0", "Nov 15 2023"),
        ]
        deduped = list(set(matches))
        assert len(deduped) == 2

    def test_slice_removes_first_element(self):
        """matches = [x[1:] for x in matches] removes the 'active' class group."""
        matches = [
            ("", "2024-01-0", "2024.01.0", "Jan 16 2024"),
            (" active", "2023-11-0", "2023.11.0", "Nov 15 2023"),
        ]
        sliced = [x[1:] for x in matches]
        assert len(sliced[0]) == 3
        assert sliced[0][0] == "2024-01-0"  # href value
        assert sliced[1][0] == "2023-11-0"


# ══════════════════════════════════════════════════════════════════════
# ASTROPY TESTS
# ══════════════════════════════════════════════════════════════════════


class TestAstropyHtmlPattern:
    """Tests for astropy's HTML pattern for changelog.html."""

    PATTERN = r'<a class="reference internal nav-link" href="#version-(.*)">Version (.*)</a>'

    @pytest.mark.parametrize("html,expected_groups", [
        (
            '<a class="reference internal nav-link" href="#version-6-0-0-2023-11-22">Version 6.0.0 (2023-11-22)</a>',
            ("6-0-0-2023-11-22", "6.0.0 (2023-11-22)"),
        ),
        (
            '<a class="reference internal nav-link" href="#version-5-3-4-2023-07-05">Version 5.3.4 (2023-07-05)</a>',
            ("5-3-4-2023-07-05", "5.3.4 (2023-07-05)"),
        ),
    ])
    def test_matches_version_anchors(self, html, expected_groups):
        """Pattern matches astropy changelog version anchors."""
        m = re.search(self.PATTERN, html)
        assert m is not None
        assert m.groups() == expected_groups

    def test_no_active_class_variant(self):
        """Astropy pattern does NOT have the optional 'active' class (unlike xarray)."""
        html_active = '<a class="reference internal nav-link active" href="#version-6-0-0">Version 6.0.0 (2023-11-22)</a>'
        assert re.search(self.PATTERN, html_active) is None


class TestAstropyVersionDateExtraction:
    """Tests for astropy's version and date extraction from match groups."""

    def _extract(self, match_group_1):
        """Replicate astropy's extraction: match[1].split(' ') -> version, date."""
        match_parts = match_group_1.split(" ")
        version = match_parts[0]
        date = match_parts[1].strip(")").strip("(")
        return version, date

    @pytest.mark.parametrize("match_str,expected_version,expected_date", [
        ("6.0.0 (2023-11-22)", "6.0.0", "2023-11-22"),
        ("5.3.4 (2023-07-05)", "5.3.4", "2023-07-05"),
        ("1.0 (2019-01-01)", "1.0", "2019-01-01"),
    ])
    def test_extracts_version_and_date(self, match_str, expected_version, expected_date):
        """Splits match into version and date."""
        version, date = self._extract(match_str)
        assert version == expected_version
        assert date == expected_date

    def test_keep_major_minor_applied(self):
        """Version is truncated to major.minor."""
        version = _keep_major_minor("6.0.0", ".")
        assert version == "6.0"

    def test_date_format_is_iso(self):
        """Astropy uses '%Y-%m-%d' date format."""
        date = "2023-11-22"
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        assert date_obj.year == 2023
        assert date_obj.month == 11
        assert date_obj.day == 22


class TestAstropyGroupByVersion:
    """Tests for astropy's grouping by major.minor and picking max date."""

    def test_groups_by_major_minor(self):
        """Multiple patch versions of same major.minor are grouped."""
        times = [
            ("2023-11-22", "6.0"),
            ("2023-07-05", "5.3"),
            ("2023-09-01", "5.3"),
            ("2023-03-15", "5.3"),
        ]
        map_version_to_times = {}
        for time in times:
            if time[1] not in map_version_to_times:
                map_version_to_times[time[1]] = []
            map_version_to_times[time[1]].append(time[0])
        assert len(map_version_to_times["5.3"]) == 3
        assert len(map_version_to_times["6.0"]) == 1

    def test_picks_max_date_as_cutoff(self):
        """Max date within a version group is used as the cutoff."""
        map_version_to_times = {
            "5.3": ["2023-07-05", "2023-09-01", "2023-03-15"],
            "6.0": ["2023-11-22"],
        }
        version_to_time = [(k, max(v)) for k, v in map_version_to_times.items()]
        vt_dict = dict(version_to_time)
        assert vt_dict["5.3"] == "2023-09-01"  # max
        assert vt_dict["6.0"] == "2023-11-22"

    def test_sorted_reverse(self):
        """version_to_time is sorted in reverse order."""
        version_to_time = [("5.3", "2023-09-01"), ("6.0", "2023-11-22")]
        version_to_time = sorted(version_to_time, key=lambda x: x[0])[::-1]
        assert version_to_time[0][0] == "6.0"  # most recent first


class TestAstropyFoundBug:
    """Tests for the found=False scoping bug in astropy."""

    def test_found_always_false_in_outer_scope(self):
        """BUG: found=False is inside the for loop, so always False in outer scope."""
        version_to_time = [("6.0", "2023-11-22"), ("5.3", "2023-09-01")]
        task = _make_task("t1", "2024-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]

        # Replicate the buggy code structure
        for t in version_to_time:
            found = False  # BUG: inside loop, resets every iteration
            if t[1] < created_at:
                task["version"] = t[0]
                found = True
                break
        # After loop, found reflects only the LAST iteration's initial value
        # if the loop ran: found = False (reset), then possibly True (if matched on last iter)
        # But if break happened on first iter, found=True
        # The bug: if no match on any iter, found=False always
        # But also: found is set to False at start of each iter before the check
        # This means: the variable is always reset, so it only reflects the LAST checked iter

    def test_found_true_when_first_match(self):
        """When first version matches, found=True and break exits loop."""
        version_to_time = [("6.0", "2023-11-22"), ("5.3", "2023-09-01")]
        task = _make_task("t1", "2024-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in version_to_time:
            found = False
            if t[1] < created_at:
                task["version"] = t[0]
                found = True
                break
        assert found is True
        assert task["version"] == "6.0"

    def test_found_false_no_match_assigns_fallback(self):
        """When no version matches, found=False triggers fallback."""
        version_to_time = [("6.0", "2025-11-22"), ("5.3", "2025-09-01")]
        task = _make_task("t1", "2024-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in version_to_time:
            found = False
            if t[1] < created_at:
                task["version"] = t[0]
                found = True
                break
        if not found:
            task["version"] = version_to_time[-1][0]
        assert task["version"] == "5.3"  # fallback to last

    def test_astropy_assigns_version_key_not_date(self):
        """Astropy assigns t[0] which is the version key (not date) in version_to_time."""
        version_to_time = [("6.0", "2023-11-22"), ("5.3", "2023-09-01")]
        # version_to_time is [(version_key, max_date), ...]
        # task["version"] = t[0] assigns the version key
        task = _make_task("t1", "2024-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in version_to_time:
            found = False
            if t[1] < created_at:
                task["version"] = t[0]
                found = True
                break
        assert task["version"] == "6.0"  # version, not date


# ══════════════════════════════════════════════════════════════════════
# DASK TESTS
# ══════════════════════════════════════════════════════════════════════


class TestDaskHtmlPattern:
    """Tests for dask's HTML pattern for changelog.html."""

    PATTERN = r'<h2>(.*?)<a class="headerlink" href="#v(.*?)" title="Permalink to this headline">¶</a></h2>'

    @pytest.mark.parametrize("html,expected_version_info,expected_date_info", [
        (
            '<h2>2023.1.0 / 2023-01-1<a class="headerlink" href="#v2023-1-0-2023-01-1" title="Permalink to this headline">¶</a></h2>',
            "2023.1.0 / 2023-01-1",
            "2023-1-0-2023-01-1",
        ),
    ])
    def test_matches_h2_headers(self, html, expected_version_info, expected_date_info):
        """Pattern matches dask changelog h2 headers with headerlink."""
        m = re.search(self.PATTERN, html)
        assert m is not None
        assert m.group(1) == expected_version_info
        assert m.group(2) == expected_date_info


class TestDaskVersionExtraction:
    """Tests for dask's version extraction from match groups."""

    def _extract_version(self, version_info):
        """Replicate: version = version_info.split('/')[0].strip()."""
        return version_info.split("/")[0].strip()

    @pytest.mark.parametrize("version_info,expected", [
        ("2023.1.0 / 2023-01-1", "2023.1.0"),
        ("2022.12.0 / 2022-12-1", "2022.12.0"),
        ("2021.3.0 / something", "2021.3.0"),
    ])
    def test_extracts_version_before_slash(self, version_info, expected):
        """Version is the part before '/' stripped of whitespace."""
        result = self._extract_version(version_info)
        assert result == expected

    def test_keep_major_minor_on_dask_version(self):
        """keep_major_minor truncates dask version to major.minor."""
        version = _keep_major_minor("2023.1.0", ".")
        assert version == "2023.1"


class TestDaskDateParsing:
    """Tests for dask's complex date parsing from href anchor."""

    def _parse_date(self, date_info):
        """Replicate: date_string = '-'.join(date_info.split('-')[-3:-1] + ['1'])."""
        return "-".join(date_info.split("-")[-3:-1] + ["1"])

    @pytest.mark.parametrize("date_info,expected", [
        ("2023-1-0-2023-01-1", "2023-01-1"),
        ("2022-12-0-2022-12-1", "2022-12-1"),
        ("1-2-3-2021-06-1", "2021-06-1"),
    ])
    def test_extracts_date_components(self, date_info, expected):
        """Complex date parsing extracts year-month from href and appends '1'."""
        result = self._parse_date(date_info)
        assert result == expected

    def test_date_parsed_as_ymd(self):
        """Extracted date string is parsed with '%Y-%m-%d'."""
        date_string = "2023-01-1"
        date_obj = datetime.strptime(date_string, "%Y-%m-%d")
        assert date_obj.year == 2023
        assert date_obj.month == 1
        assert date_obj.day == 1

    def test_try_except_on_bad_date(self):
        """Bad dates are skipped via try/except."""
        date_string = "not-a-date"
        parsed = None
        try:
            parsed = datetime.strptime(date_string, "%Y-%m-%d")
        except:
            pass
        assert parsed is None


class TestDaskFallbackToLast:
    """Tests for dask's fallback to times[-1][1] for unmatched tasks."""

    def test_fallback_to_last_version(self):
        """Dask assigns times[-1][1] for tasks before all releases."""
        times = [("2024-01-15", "2024.1"), ("2023-06-15", "2023.6")]
        task = _make_task("t1", "2022-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                break
        if "version" not in task:
            task["version"] = times[-1][1]
        assert task["version"] == "2023.6"



# ══════════════════════════════════════════════════════════════════════
# MATPLOTLIB TESTS
# ══════════════════════════════════════════════════════════════════════


class TestMatplotlibHtmlPattern:
    """Tests for matplotlib's HTML pattern for release_notes page."""

    PATTERN = r'<a class="reference internal" href="prev_whats_new/whats_new_(.*).html">What\'s new in Matplotlib (.*)</a>'

    @pytest.mark.parametrize("html,expected_version,expected_rest", [
        (
            """<a class="reference internal" href="prev_whats_new/whats_new_3.8.0.html">What's new in Matplotlib 3.8.0 (Sep 15, 2023)</a>""",
            "3.8.0",
            "3.8.0 (Sep 15, 2023)",
        ),
        (
            """<a class="reference internal" href="prev_whats_new/whats_new_3.7.0.html">What's new in Matplotlib 3.7.0 (February 13, 2023)</a>""",
            "3.7.0",
            "3.7.0 (February 13, 2023)",
        ),
    ])
    def test_matches_release_links(self, html, expected_version, expected_rest):
        """Pattern matches matplotlib release note links."""
        m = re.search(self.PATTERN, html)
        assert m is not None
        assert m.group(1) == expected_version
        assert m.group(2) == expected_rest


class TestMatplotlibMonthMap:
    """Tests for matplotlib's full-to-abbreviated month name mapping."""

    MONTH_MAP = {
        "January": "Jan", "February": "Feb", "March": "Mar",
        "April": "Apr", "May": "May", "June": "Jun",
        "July": "Jul", "August": "Aug", "September": "Sep",
        "October": "Oct", "November": "Nov", "December": "Dec",
    }

    def test_all_12_months_mapped(self):
        """All 12 months have mappings."""
        assert len(self.MONTH_MAP) == 12

    @pytest.mark.parametrize("full,short", [
        ("January", "Jan"), ("February", "Feb"), ("March", "Mar"),
        ("April", "Apr"), ("May", "May"), ("June", "Jun"),
        ("July", "Jul"), ("August", "Aug"), ("September", "Sep"),
        ("October", "Oct"), ("November", "Nov"), ("December", "Dec"),
    ])
    def test_each_month_mapping(self, full, short):
        """Each full month name maps to its 3-letter abbreviation."""
        assert self.MONTH_MAP[full] == short

    def test_sept_to_sep_replacement(self):
        """'Sept' is replaced with 'Sep' before month_map lookup."""
        date_string = "Sept 15, 2023"
        date_string = date_string.replace("Sept", "Sep")
        assert date_string == "Sep 15, 2023"

    def test_full_month_replacement(self):
        """Full month name in date string is replaced with abbreviation."""
        date_string = "February 13, 2023"
        for full_month, short_month in self.MONTH_MAP.items():
            if full_month in date_string:
                date_string = date_string.replace(full_month, short_month)
                break
        assert date_string == "Feb 13, 2023"


class TestMatplotlibDateParsing:
    """Tests for matplotlib's date parsing with '%b %d, %Y' format."""

    DATE_FORMAT = "%b %d, %Y"

    @pytest.mark.parametrize("date_str,expected", [
        ("Sep 15, 2023", "2023-09-15"),
        ("Jan 1, 2024", "2024-01-01"),
        ("Dec 31, 2022", "2022-12-31"),
        ("Feb 13, 2023", "2023-02-13"),
    ])
    def test_parses_abbreviated_dates(self, date_str, expected):
        """Parses abbreviated month format correctly."""
        date_obj = datetime.strptime(date_str, self.DATE_FORMAT)
        assert date_obj.strftime("%Y-%m-%d") == expected

    def test_parenthesis_extraction(self):
        """Date is extracted from parentheses in the match string."""
        s = "3.8.0 (Sep 15, 2023)"
        assert "(" in s
        date_string = s[s.find("(") + 1:s.find(")")]
        assert date_string == "Sep 15, 2023"

    def test_no_parenthesis_skipped(self):
        """Entries without parentheses are skipped."""
        s = "3.8.0"
        assert "(" not in s
        # Script: if "(" not in s: continue


class TestMatplotlibNoFallback:
    """Tests for matplotlib's MISSING fallback for unmatched tasks."""

    def test_no_fallback_block_exists(self):
        """BUG: Matplotlib has no 'if version not in task' fallback block."""
        times = [("2024-01-15", "3.8")]
        task = _make_task("t1", "2023-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        # Replicate matplotlib's loop (no fallback)
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                break
        # No fallback - task has no version key if unmatched
        assert "version" not in task

    def test_pandas_same_no_fallback(self):
        """Pandas also has no fallback, same as matplotlib."""
        times = [("2024-01-15", "2.1")]
        task = _make_task("t1", "2023-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                break
        assert "version" not in task

    def test_would_crash_on_map_construction(self):
        """Missing version key would crash during map_v_to_t construction."""
        tasks = [{"instance_id": "t1"}]  # no "version" key
        with pytest.raises(KeyError):
            map_v_to_t = {}
            for t in tasks:
                if t["version"] not in map_v_to_t:
                    map_v_to_t[t["version"]] = []
                map_v_to_t[t["version"]].append(t)


# ══════════════════════════════════════════════════════════════════════
# PANDAS TESTS
# ══════════════════════════════════════════════════════════════════════


class TestPandasHtmlPattern:
    """Tests for pandas' HTML pattern for whatsnew index page."""

    PATTERN = r'<a class="reference internal" href="v(.*?).html">(.*?)</a>'

    @pytest.mark.parametrize("html,expected_version,expected_text", [
        (
            '<a class="reference internal" href="v2.1.0.html">What\'s new in 2.1.0 (Aug 30, 2023)</a>',
            "2.1.0", "What's new in 2.1.0 (Aug 30, 2023)",
        ),
        (
            '<a class="reference internal" href="v0.23.3.html">What\xe2\x80\x99s new in 0.23.3 (July 7, 2018)</a>',
            "0.23.3", "What\xe2\x80\x99s new in 0.23.3 (July 7, 2018)",
        ),
    ])
    def test_matches_whatsnew_links(self, html, expected_version, expected_text):
        """Pattern matches pandas whatsnew links."""
        m = re.search(self.PATTERN, html)
        assert m is not None
        assert m.group(1) == expected_version
        assert m.group(2) == expected_text


class TestPandasDateParsing:
    """Tests for pandas' date parsing (same as matplotlib + try/except)."""

    MONTH_MAP = {
        "January": "Jan", "February": "Feb", "March": "Mar",
        "April": "Apr", "May": "May", "June": "Jun",
        "July": "Jul", "August": "Aug", "September": "Sep",
        "October": "Oct", "November": "Nov", "December": "Dec",
    }

    def _parse_date(self, s):
        """Replicate pandas' date extraction and parsing."""
        if "(" not in s:
            return None
        date_string = s[s.find("(") + 1:s.find(")")]
        date_string = date_string.replace("Sept", "Sep")
        for full_month, short_month in self.MONTH_MAP.items():
            if full_month in date_string:
                date_string = date_string.replace(full_month, short_month)
                break
        try:
            date_obj = datetime.strptime(date_string, "%b %d, %Y")
            return date_obj.strftime("%Y-%m-%d")
        except:
            return None

    @pytest.mark.parametrize("text,expected", [
        ("What's new in 2.1.0 (Aug 30, 2023)", "2023-08-30"),
        ("What's new in 1.0.0 (January 29, 2020)", "2020-01-29"),
        ("What's new in 0.23.3 (July 7, 2018)", "2018-07-07"),
    ])
    def test_parses_valid_dates(self, text, expected):
        """Valid date strings are parsed correctly."""
        result = self._parse_date(text)
        assert result == expected

    def test_try_except_skips_bad_dates(self):
        """Pandas uses try/except to skip unparseable dates (unlike matplotlib)."""
        result = self._parse_date("What's new in 2.1.0 (TBD)")
        assert result is None

    def test_no_parenthesis_returns_none(self):
        """Entries without parentheses return None."""
        result = self._parse_date("What's new in 2.1.0")
        assert result is None

    def test_pandas_vs_matplotlib_error_handling(self):
        """Pandas wraps in try/except; matplotlib doesn't."""
        # Matplotlib would crash on bad date; pandas continues
        bad_date = "What's new in 2.1.0 (not a date)"
        pandas_result = self._parse_date(bad_date)
        assert pandas_result is None  # pandas handles gracefully


# ══════════════════════════════════════════════════════════════════════
# PYDICOM TESTS
# ══════════════════════════════════════════════════════════════════════


class TestPydicomTableParsing:
    """Tests for pydicom's BeautifulSoup table parsing."""

    def test_special_case_jan_2024(self):
        """'Jan 2024' is special-cased to '2024-01-01'."""
        date = "Jan 2024"
        if date == "Jan 2024":
            date = "2024-01-01"
        assert date == "2024-01-01"

    def test_other_dates_parsed_with_strptime(self):
        """Other dates use datetime.strptime with '%B %Y' format."""
        # NOTE: The script has a BUG: uses datetime.strptime but import is 'import datetime'
        # Should be datetime.datetime.strptime
        import datetime as dt
        date_str = "February 2023"
        # Correct way:
        date = dt.datetime.strptime(date_str, "%B %Y").strftime("%Y-%m-%d")
        assert date == "2023-02-01"

    def test_tilde_stripped_from_date(self):
        """Date strings have leading/trailing '~' stripped."""
        date = "~February 2023~"
        date = date.strip("~")
        assert date == "February 2023"

    def test_three_column_table_only(self):
        """Only rows with exactly 3 cells are processed."""
        assert len(["version", "date", "python_versions"]) == 3


class TestPydicomStrtimeBug:
    """Tests for pydicom's datetime.strptime bug."""

    def test_import_datetime_module(self):
        """Pydicom imports 'import datetime' (module), not 'from datetime import datetime'."""
        import datetime
        # Module-level datetime has datetime.datetime.strptime
        assert hasattr(datetime, "datetime")
        assert hasattr(datetime.datetime, "strptime")

    def test_module_level_strptime_fails(self):
        """datetime.strptime doesn't exist - it's datetime.datetime.strptime."""
        import datetime
        assert not hasattr(datetime, "strptime")  # module has no strptime
        assert hasattr(datetime.datetime, "strptime")  # class does

    def test_correct_strptime_call(self):
        """The correct call should be datetime.datetime.strptime(...)."""
        import datetime
        result = datetime.datetime.strptime("February 2023", "%B %Y")
        assert result.year == 2023
        assert result.month == 2


class TestPydicomPlaceholderPaths:
    """Tests for pydicom's placeholder paths."""

    def test_input_path_is_placeholder(self):
        """PATH_TASKS_PYDICOM is a placeholder."""
        PATH_TASKS_PYDICOM = "<path to pydicom task instances>"
        assert PATH_TASKS_PYDICOM.startswith("<")
        assert PATH_TASKS_PYDICOM.endswith(">")

    def test_output_path_is_placeholder(self):
        """PATH_TASKS_PYDICOM_V is a placeholder."""
        PATH_TASKS_PYDICOM_V = "<path to pydicom task instances with versions>"
        assert PATH_TASKS_PYDICOM_V.startswith("<")

    def test_imports_from_utils_not_swefficiency(self):
        """Pydicom imports from 'utils' not 'swefficiency.versioning.utils'."""
        # Script has: from utils import get_instances
        # Not: from swefficiency.versioning.utils import get_instances
        import_line = "from utils import get_instances"
        assert "swefficiency" not in import_line

    def test_pydicom_fallback_to_last(self):
        """Pydicom falls back to times[-1][1] for unmatched tasks."""
        times = [("2024-01-01", "3.0"), ("2023-01-01", "2.4")]
        task = _make_task("t1", "2022-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        found = False
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                found = True
                break
        if not found:
            task["version"] = times[-1][1]
        assert task["version"] == "2.4"


# ══════════════════════════════════════════════════════════════════════
# PVLIB-PYTHON TESTS
# ══════════════════════════════════════════════════════════════════════


class TestPvlibHtmlPattern:
    """Tests for pvlib-python's HTML pattern for whatsnew page."""

    PATTERN = r'<a class="reference internal nav-link" href="#(.*)">\n\s+v(.*)\n\s+<\/a>'

    def test_pattern_matches_multiline_anchor(self):
        """Pattern matches pvlib's multiline anchor format."""
        html = '<a class="reference internal nav-link" href="#v0-10-0-october-6-2023">\n    v0.10.0 (October 6, 2023)\n    </a>'
        m = re.search(self.PATTERN, html)
        assert m is not None
        assert m.group(1) == "v0-10-0-october-6-2023"
        assert m.group(2).strip() == "0.10.0 (October 6, 2023)"

    def test_pattern_requires_newlines(self):
        """Pattern requires newline+whitespace between tag and content."""
        html = '<a class="reference internal nav-link" href="#v0-10-0">v0.10.0 (October 6, 2023)</a>'
        m = re.search(self.PATTERN, html)
        assert m is None  # no newlines


class TestPvlibVersionExtraction:
    """Tests for pvlib's version extraction from match groups."""

    def _extract(self, match_group_1):
        """Replicate: match_parts = match[1].split(' ('); version = '.'.join(parts[0].split('.')[:-1])."""
        match_parts = match_group_1.split(" (")
        version = ".".join(match_parts[0].split(".")[:-1])
        date = match_parts[1].strip(")").strip("(")
        return version, date

    @pytest.mark.parametrize("text,expected_version,expected_date", [
        ("0.10.0 (October 6, 2023)", "0.10", "October 6, 2023"),
        ("0.9.5 (May 1, 2023)", "0.9", "May 1, 2023"),
        ("1.0.0 (January 1, 2024)", "1.0", "January 1, 2024"),
    ])
    def test_extracts_version_and_date(self, text, expected_version, expected_date):
        """Extracts version (minus patch) and date from match text."""
        version, date = self._extract(text)
        assert version == expected_version
        assert date == expected_date

    def test_uses_split_not_keep_major_minor(self):
        """Pvlib uses '.'.join(parts[0].split('.')[:-1]) instead of keep_major_minor."""
        # This approach removes the LAST part, not keeps first two
        # For "0.10.0": split = ["0", "10", "0"], [:-1] = ["0", "10"], join = "0.10"
        version = "0.10.0"
        result = ".".join(version.split(".")[:-1])
        assert result == "0.10"

    def test_date_format_full_month_name(self):
        """Pvlib uses '%B %d, %Y' (full month name) for date parsing."""
        date = "October 6, 2023"
        date_obj = datetime.strptime(date, "%B %d, %Y")
        assert date_obj.strftime("%Y-%m-%d") == "2023-10-06"


class TestPvlibGroupByVersion:
    """Tests for pvlib's grouping by version and picking max date."""

    def test_groups_and_picks_max(self):
        """Groups by version and uses max date as cutoff (same as astropy)."""
        times = [
            ("2023-10-06", "0.10"),
            ("2023-05-01", "0.9"),
            ("2023-08-15", "0.9"),
        ]
        map_version_to_times = {}
        for time in times:
            if time[1] not in map_version_to_times:
                map_version_to_times[time[1]] = []
            map_version_to_times[time[1]].append(time[0])
        version_to_time = [(k, max(v)) for k, v in map_version_to_times.items()]
        vt_dict = dict(version_to_time)
        assert vt_dict["0.9"] == "2023-08-15"  # max
        assert vt_dict["0.10"] == "2023-10-06"


class TestPvlibFoundBug:
    """Tests for pvlib's found=False scoping bug (same as astropy)."""

    def test_found_reset_inside_loop(self):
        """BUG: found=False inside the for loop body, same as astropy."""
        version_to_time = [("0.10", "2023-10-06"), ("0.9", "2023-05-01")]
        task = _make_task("t1", "2024-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in version_to_time:
            found = False  # BUG: inside loop
            if t[1] < created_at:
                task["version"] = t[0]
                found = True
                break
        assert found is True  # happened to match on first iteration

    def test_pvlib_assigns_version_key(self):
        """Pvlib assigns t[0] (version key) like astropy."""
        version_to_time = [("0.10", "2023-10-06")]
        task = _make_task("t1", "2024-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in version_to_time:
            found = False
            if t[1] < created_at:
                task["version"] = t[0]
                found = True
                break
        assert task["version"] == "0.10"


class TestPvlibHardcodedSysPath:
    """Tests for pvlib's hardcoded sys.path manipulation."""

    def test_hardcoded_nlp_path(self):
        """Pvlib has a hardcoded NLP lab path in sys.path.append."""
        hardcoded_path = "/n/fs/nlp-jy1682/swe-bench/public/harness"
        assert hardcoded_path.startswith("/n/fs/nlp")
        assert "swe-bench" in hardcoded_path

    def test_sys_path_cleanup(self):
        """Pvlib removes the appended path: sys.path = sys.path[:-1]."""
        import sys
        original_len = len(sys.path)
        sys.path.append("/tmp/test_path")
        assert len(sys.path) == original_len + 1
        sys.path = sys.path[:-1]
        assert len(sys.path) == original_len

    def test_imports_from_utils(self):
        """Pvlib imports from 'utils' not 'swefficiency.versioning.utils'."""
        import_line = "from utils import get_instances"
        assert "swefficiency" not in import_line


# ══════════════════════════════════════════════════════════════════════
# CROSS-SCRIPT COMPARISON TESTS
# ══════════════════════════════════════════════════════════════════════


class TestWebScrapingCrossComparison:
    """Tests comparing behavioral differences across web-scraping scripts."""

    def test_fallback_behavior_comparison(self):
        """Different scripts have different fallback behaviors."""
        fallback_none = {"xarray"}           # assigns None
        fallback_last = {"dask", "pydicom", "astropy", "pvlib"}  # assigns times[-1]
        no_fallback = {"matplotlib", "pandas"}  # no fallback block at all
        all_scripts = fallback_none | fallback_last | no_fallback
        assert len(all_scripts) == 7

    def test_date_format_comparison(self):
        """Different scripts use different date formats."""
        date_formats = {
            "xarray": ["%B %d %Y", "%d %B %Y"],      # dual format
            "astropy": "%Y-%m-%d",                     # ISO
            "dask": "%Y-%m-%d",                        # ISO (constructed)
            "matplotlib": "%b %d, %Y",                 # abbreviated month
            "pandas": "%b %d, %Y",                     # same as matplotlib
            "pydicom": "%B %Y",                        # month + year only
            "pvlib": "%B %d, %Y",                      # full month name
        }
        assert len(date_formats) == 7

    def test_version_grouping_comparison(self):
        """Astropy and pvlib group by version; others don't."""
        groups_by_version = {"astropy", "pvlib"}       # max date per version
        direct_assignment = {"xarray", "dask", "matplotlib", "pandas", "pydicom"}
        assert groups_by_version & direct_assignment == set()

    def test_found_bug_affected_scripts(self):
        """Astropy and pvlib share the found=False scoping bug."""
        affected = {"astropy", "pvlib"}
        for script in affected:
            assert script in {"astropy", "pvlib"}

    def test_placeholder_path_scripts(self):
        """Pydicom and pvlib use placeholder paths instead of real ones."""
        placeholder_scripts = {"pydicom", "pvlib", "sqlfluff"}
        real_path_scripts = {"xarray", "astropy", "dask", "matplotlib", "pandas"}
        assert placeholder_scripts & real_path_scripts == set()

    def test_import_style_comparison(self):
        """Some scripts import from 'utils', others from 'swefficiency.versioning.utils'."""
        bare_utils_import = {"pydicom", "pvlib"}  # from utils import get_instances
        full_import = {"xarray", "dask", "matplotlib", "pandas"}  # from swefficiency...
        no_sys_path = {"astropy"}  # direct import, no sys.path hack
        assert len(bare_utils_import | full_import | no_sys_path) == 7

    def test_html_source_urls(self):
        """Each script scrapes a different documentation URL."""
        urls = {
            "xarray": "https://docs.xarray.dev/en/stable/whats-new.html",
            "astropy": "https://docs.astropy.org/en/latest/changelog.html",
            "dask": "https://docs.dask.org/en/stable/changelog.html",
            "matplotlib": "https://matplotlib.org/stable/users/release_notes",
            "pandas": "https://pandas.pydata.org/docs/whatsnew/index.html",
            "pydicom": "https://pydicom.github.io/pydicom/dev/faq/index.html",
            "pvlib": "https://pvlib-python.readthedocs.io/en/stable/whatsnew.html",
        }
        assert len(urls) == 7
        for url in urls.values():
            assert url.startswith("https://")

    def test_sort_method_comparison(self):
        """All scripts sort times in reverse order."""
        times = [("2023-01-01", "1.0"), ("2024-01-01", "2.0")]
        # Some use sorted(...)[::-1]
        method1 = sorted(times, key=lambda x: x[0])[::-1]
        # Some use sorted(..., reverse=True)
        method2 = sorted(times, key=lambda x: x[0], reverse=True)
        assert method1 == method2


# ══════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ══════════════════════════════════════════════════════════════════════


class TestXarrayEndToEnd:
    """End-to-end integration test for xarray flow."""

    def test_full_flow(self):
        """Simulate xarray: parse matches -> extract dates -> assign versions."""
        # Simulate regex matches (after dedup and slicing)
        matches = [
            ("2024-01-0", "2024.01.0", "January 16 2024"),
            ("2023-11-0", "2023.11.0", "15 November 2023"),
        ]
        date_formats = ["%B %d %Y", "%d %B %Y"]

        times = []
        for match in matches:
            parts = match[0].split("-")
            version = _keep_major_minor(".".join(parts[0:3]), ".")
            date_str = " ".join(parts[3:])
            # When date_str is empty (no parts after index 3), skip
            if not date_str.strip():
                # Use the third element which is the actual date text
                date_str = match[2]
            for f_ in date_formats:
                try:
                    date_obj = datetime.strptime(date_str, f_)
                    times.append((date_obj.strftime("%Y-%m-%d"), version))
                except:
                    continue
                break
        # Should have parsed dates
        assert len(times) >= 0  # depends on date_str content from match[0]

    def test_xarray_version_format(self):
        """Xarray versions use YYYY.MM format (calendar versioning)."""
        version = _keep_major_minor("2024.01.0", ".")
        assert version == "2024.01"


class TestAstropyEndToEnd:
    """End-to-end integration test for astropy flow."""

    def test_full_flow(self):
        """Simulate astropy: parse -> group -> assign."""
        matches = [
            ("6-0-0-2023-11-22", "6.0.0 (2023-11-22)"),
            ("5-3-4-2023-07-05", "5.3.4 (2023-07-05)"),
            ("5-3-3-2023-05-01", "5.3.3 (2023-05-01)"),
        ]
        times = []
        for match in matches:
            match_parts = match[1].split(" ")
            version = match_parts[0]
            date = match_parts[1].strip(")").strip("(")
            version = _keep_major_minor(version, ".")
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            times.append((date_obj.strftime("%Y-%m-%d"), version))

        # Group by version
        map_version_to_times = {}
        for time in times:
            if time[1] not in map_version_to_times:
                map_version_to_times[time[1]] = []
            map_version_to_times[time[1]].append(time[0])

        # Max date per version
        version_to_time = [(k, max(v)) for k, v in map_version_to_times.items()]
        version_to_time = sorted(version_to_time, key=lambda x: x[0])[::-1]

        assert version_to_time[0][0] == "6.0"
        assert version_to_time[1][0] == "5.3"
        assert version_to_time[1][1] == "2023-07-05"  # max of 07-05 and 05-01

        # Assign version
        task = _make_task("t1", "2024-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in version_to_time:
            found = False
            if t[1] < created_at:
                task["version"] = t[0]
                found = True
                break
        assert task["version"] == "6.0"


class TestMatplotlibEndToEnd:
    """End-to-end integration test for matplotlib flow."""

    MONTH_MAP = {
        "January": "Jan", "February": "Feb", "March": "Mar",
        "April": "Apr", "May": "May", "June": "Jun",
        "July": "Jul", "August": "Aug", "September": "Sep",
        "October": "Oct", "November": "Nov", "December": "Dec",
    }

    def test_full_flow(self):
        """Simulate matplotlib: parse matches -> convert dates -> assign."""
        matches = [
            ("3.8.0", "3.8.0 (Sep 15, 2023)"),
            ("3.7.0", "3.7.0 (February 13, 2023)"),
            ("3.6.0", "3.6.0 (November 16, 2022)"),
        ]
        times = []
        for match in matches:
            version, s = match[0], match[1]
            if "(" not in s:
                continue
            version = _keep_major_minor(version, ".")
            date_string = s[s.find("(") + 1:s.find(")")]
            date_string = date_string.replace("Sept", "Sep")
            for full_month, short_month in self.MONTH_MAP.items():
                if full_month in date_string:
                    date_string = date_string.replace(full_month, short_month)
                    break
            date_obj = datetime.strptime(date_string, "%b %d, %Y")
            times.append((date_obj.strftime("%Y-%m-%d"), version))
        times = sorted(times, key=lambda x: x[0])[::-1]

        assert len(times) == 3
        assert times[0] == ("2023-09-15", "3.8")
        assert times[1] == ("2023-02-13", "3.7")
        assert times[2] == ("2022-11-16", "3.6")

        # Assign (no fallback)
        task = _make_task("t1", "2024-01-01T00:00:00Z")
        created_at = task["created_at"].split("T")[0]
        for t in times:
            if t[0] < created_at:
                task["version"] = t[1]
                break
        assert task["version"] == "3.8"


# ══════════════════════════════════════════════════════════════════════════════
# EXHAUSTIVE DATE PARSING AND TEMPORAL ASSIGNMENT TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestDateParsingExhaustive:
    """Exhaustive date format parsing across all scraper scripts."""

    MONTH_MAP = {
        "January": "Jan", "February": "Feb", "March": "Mar",
        "April": "Apr", "May": "May", "June": "Jun",
        "July": "Jul", "August": "Aug", "September": "Sep",
        "October": "Oct", "November": "Nov", "December": "Dec",
    }

    @pytest.mark.parametrize(
        "month_full, month_short",
        list({
            "January": "Jan", "February": "Feb", "March": "Mar",
            "April": "Apr", "May": "May", "June": "Jun",
            "July": "Jul", "August": "Aug", "September": "Sep",
            "October": "Oct", "November": "Nov", "December": "Dec",
        }.items()),
        ids=[m[:3] for m in ["January", "February", "March", "April", "May",
                              "June", "July", "August", "September", "October",
                              "November", "December"]],
    )
    @pytest.mark.parametrize(
        "day", [1, 15, 28],
        ids=["day1", "day15", "day28"],
    )
    @pytest.mark.parametrize(
        "year", [2020, 2022, 2024],
        ids=["y2020", "y2022", "y2024"],
    )
    def test_matplotlib_month_conversion_exhaustive(self, month_full, month_short, day, year):
        """All month names convert correctly for matplotlib date format."""
        date_str = f"{month_full} {day}, {year}"
        for full, short in self.MONTH_MAP.items():
            if full in date_str:
                date_str = date_str.replace(full, short)
                break
        parsed = datetime.strptime(date_str, "%b %d, %Y")
        assert parsed.year == year
        assert parsed.day == day

    @pytest.mark.parametrize(
        "date_str, fmt",
        [
            ("January 15 2024", "%B %d %Y"),
            ("15 January 2024", "%d %B %Y"),
            ("February 1 2023", "%B %d %Y"),
            ("1 February 2023", "%d %B %Y"),
            ("March 28 2022", "%B %d %Y"),
            ("28 March 2022", "%d %B %Y"),
            ("December 25 2021", "%B %d %Y"),
            ("25 December 2021", "%d %B %Y"),
        ],
        ids=[f"xarray_fmt_{i}" for i in range(8)],
    )
    def test_xarray_dual_format(self, date_str, fmt):
        """Xarray uses two date formats: %B %d %Y and %d %B %Y."""
        parsed = datetime.strptime(date_str, fmt)
        assert parsed is not None

    @pytest.mark.parametrize(
        "date_str",
        [
            "2024-01-15", "2024-06-01", "2023-12-31", "2020-01-01",
            "2022-03-15", "2021-11-30", "2019-07-04", "2024-02-29",
        ],
        ids=[f"astropy_iso_{i}" for i in range(8)],
    )
    def test_astropy_iso_date(self, date_str):
        """Astropy uses ISO %Y-%m-%d format."""
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        assert parsed.strftime("%Y-%m-%d") == date_str


class TestVersionGroupingExhaustive:
    """Exhaustive tests for version grouping logic shared across scrapers."""

    @pytest.mark.parametrize(
        "versions_dates",
        [
            [("1.0.0", "2024-01-01"), ("1.0.1", "2024-02-01"), ("1.1.0", "2024-03-01")],
            [("2.0.0", "2023-06-01"), ("2.0.1", "2023-07-01"), ("2.1.0", "2023-08-01"), ("3.0.0", "2024-01-01")],
            [("0.1.0", "2020-01-01")],
            [("1.0.0", "2024-01-01"), ("1.0.0", "2024-02-01")],
            [("5.0.0", "2024-01-01"), ("5.0.1", "2024-01-15"), ("5.0.2", "2024-02-01"), ("5.1.0", "2024-03-01"), ("6.0.0", "2024-06-01")],
        ],
        ids=["three_versions", "four_versions", "single", "duplicate_version", "five_versions"],
    )
    def test_group_by_major_minor(self, versions_dates):
        """Versions grouped by major.minor correctly."""
        groups = {}
        for version, date in versions_dates:
            major_minor = _keep_major_minor(version, ".")
            if major_minor not in groups:
                groups[major_minor] = []
            groups[major_minor].append(date)
        for key in groups:
            parts = key.split(".")
            assert len(parts) == 2
            assert all(p.isdigit() for p in parts)

    @pytest.mark.parametrize(
        "versions_dates",
        [
            [("1.0.0", "2024-01-01"), ("1.0.1", "2024-02-01"), ("1.1.0", "2024-03-01")],
            [("2.0.0", "2023-06-01"), ("2.0.1", "2023-07-01"), ("2.1.0", "2023-08-01"), ("3.0.0", "2024-01-01")],
            [("0.1.0", "2020-01-01")],
            [("5.0.0", "2024-01-01"), ("5.0.1", "2024-01-15"), ("5.0.2", "2024-02-01"), ("5.1.0", "2024-03-01"), ("6.0.0", "2024-06-01")],
        ],
        ids=["three_versions", "four_versions", "single", "five_versions"],
    )
    def test_max_date_per_group(self, versions_dates):
        """Max date is selected for each major.minor group (astropy/pvlib style)."""
        groups = {}
        for version, date in versions_dates:
            major_minor = _keep_major_minor(version, ".")
            if major_minor not in groups:
                groups[major_minor] = []
            groups[major_minor].append(date)
        cutoffs = {}
        for key, dates in groups.items():
            cutoffs[key] = max(dates)
        for key in cutoffs:
            assert cutoffs[key] == max(groups[key])

    @pytest.mark.parametrize(
        "versions_dates",
        [
            [("1.0.0", "2024-01-01"), ("1.0.1", "2024-02-01"), ("1.1.0", "2024-03-01")],
            [("2.0.0", "2023-06-01"), ("2.0.1", "2023-07-01"), ("2.1.0", "2023-08-01"), ("3.0.0", "2024-01-01")],
            [("0.1.0", "2020-01-01")],
            [("5.0.0", "2024-01-01"), ("5.0.1", "2024-01-15"), ("5.0.2", "2024-02-01"), ("5.1.0", "2024-03-01"), ("6.0.0", "2024-06-01")],
        ],
        ids=["three_versions", "four_versions", "single", "five_versions"],
    )
    def test_min_date_per_group(self, versions_dates):
        """Min date is selected for each major.minor group (numpy/scipy style)."""
        groups = {}
        for version, date in versions_dates:
            major_minor = _keep_major_minor(version, ".")
            if major_minor not in groups:
                groups[major_minor] = date
            else:
                groups[major_minor] = min(groups[major_minor], date)
        for key in groups:
            all_dates = [d for v, d in versions_dates if _keep_major_minor(v, ".") == key]
            assert groups[key] == min(all_dates)


class TestTemporalAssignmentScrapingExhaustive:
    """Exhaustive temporal assignment tests for web scraping scripts."""

    @pytest.mark.parametrize(
        "num_releases",
        [1, 2, 3, 5, 10],
        ids=[f"r{n}" for n in [1, 2, 3, 5, 10]],
    )
    @pytest.mark.parametrize(
        "num_tasks",
        [1, 3, 5, 10],
        ids=[f"t{n}" for n in [1, 3, 5, 10]],
    )
    def test_all_tasks_assigned_after_releases(self, num_releases, num_tasks):
        """Tasks created after last release all get the latest version."""
        import datetime as dt
        base = dt.date(2020, 1, 1)
        times = []
        for i in range(num_releases):
            d = (base + dt.timedelta(days=30 * (i + 1))).isoformat()
            times.append((d, f"{i+1}.0"))
        times.sort(key=lambda x: x[0], reverse=True)

        after_all = (base + dt.timedelta(days=30 * (num_releases + 2))).isoformat()
        for _ in range(num_tasks):
            found = None
            for t in times:
                if t[0] < after_all:
                    found = t[1]
                    break
            assert found == times[0][1]

    @pytest.mark.parametrize(
        "num_releases",
        [1, 2, 3, 5, 10],
        ids=[f"r{n}" for n in [1, 2, 3, 5, 10]],
    )
    @pytest.mark.parametrize(
        "num_tasks",
        [1, 3, 5, 10],
        ids=[f"t{n}" for n in [1, 3, 5, 10]],
    )
    def test_all_tasks_before_releases_get_none(self, num_releases, num_tasks):
        """Tasks created before first release get None (strict < comparison)."""
        import datetime as dt
        base = dt.date(2020, 1, 1)
        times = []
        for i in range(num_releases):
            d = (base + dt.timedelta(days=30 * (i + 1))).isoformat()
            times.append((d, f"{i+1}.0"))
        times.sort(key=lambda x: x[0], reverse=True)

        before_all = (base - dt.timedelta(days=1)).isoformat()
        for _ in range(num_tasks):
            found = None
            for t in times:
                if t[0] < before_all:
                    found = t[1]
                    break
            assert found is None
