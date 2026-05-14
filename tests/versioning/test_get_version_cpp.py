# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for swefficiency.versioning.get_versions_cpp.

Same disable-cache discipline as the Python version tests via the existing
``tests/versioning/conftest.py`` (sets SWEFF_DISABLE_CACHE=1).

Tests cover:
  * ``_normalize_version`` truncation rules (matches Python contract)
  * ``_find_version_in_text`` pattern selection
  * ``get_version`` bracket-access contract (b6)
  * ``get_version`` cache namespace isolation (NS_VERSION_CPP)
  * ``get_version`` GitHub-mode + build-mode dispatch
"""
from __future__ import annotations

import os
from unittest import mock

import pytest

# Disable cache for every test in this module — matches versioning conftest.
os.environ.setdefault("SWEFF_DISABLE_CACHE", "1")

from swefficiency.versioning import get_versions_cpp
from swefficiency.versioning.constants_cpp import (
    GENERIC_VERSION_PATTERNS_CPP,
    MAP_REPO_TO_VERSION_PATHS_CPP,
    MAP_REPO_TO_VERSION_PATTERNS_CPP,
)


# ---------------------------------------------------------------------------
# _normalize_version
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("10.2.1", "10.2"),
    ("10.2", "10.2"),
    ("v3.4.5", "3.4"),
    ("1.0.0-rc1", "1.0"),
    ("3", "3"),
    ("3.x", "3"),
    ("", None),
    ("  ", None),
    ("not-a-version", None),
])
def test_normalize_version(raw, expected):
    assert get_versions_cpp._normalize_version(raw) == expected


def test_normalize_version_strips_parenthesis():
    assert get_versions_cpp._normalize_version("5.6 (alpha)") == "5.6"


# ---------------------------------------------------------------------------
# _find_version_in_text + pattern bundles
# ---------------------------------------------------------------------------

def test_find_version_cmake_project_block():
    text = "project(\n  FMT\n  VERSION 10.2.1\n  LANGUAGES CXX)\n"
    patterns = MAP_REPO_TO_VERSION_PATTERNS_CPP.get("fmtlib/fmt", GENERIC_VERSION_PATTERNS_CPP)
    out = get_versions_cpp._find_version_in_text(text, patterns)
    assert out == "10.2"


def test_find_version_vcpkg_style_json_field():
    text = '{"name": "demo", "version": "3.4.7"}'
    out = get_versions_cpp._find_version_in_text(text, GENERIC_VERSION_PATTERNS_CPP)
    assert out == "3.4"


def test_find_version_returns_none_when_nothing_matches():
    assert get_versions_cpp._find_version_in_text("random noise", GENERIC_VERSION_PATTERNS_CPP) is None


def test_find_version_skips_empty_input():
    assert get_versions_cpp._find_version_in_text("", GENERIC_VERSION_PATTERNS_CPP) is None


# ---------------------------------------------------------------------------
# get_version bracket-access contract
# ---------------------------------------------------------------------------

def test_get_version_missing_repo_key_raises_keyerror():
    """Bracket access must surface the contract failure (b6)."""
    with pytest.raises(KeyError):
        get_versions_cpp.get_version({"base_commit": "abc"})


def test_get_version_missing_base_commit_raises_keyerror():
    with pytest.raises(KeyError):
        get_versions_cpp.get_version({"repo": "fmtlib/fmt"})


def test_get_version_non_dict_raises_typeerror():
    with pytest.raises(TypeError):
        get_versions_cpp.get_version("not a dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_version GitHub-mode dispatch
# ---------------------------------------------------------------------------

@mock.patch("swefficiency.versioning.get_versions_cpp._fetch_url_with_retry")
def test_get_version_returns_normalized_string(mock_fetch):
    """First probed path that returns text + matches pattern wins."""
    mock_fetch.return_value = "project(FMT VERSION 9.1.0 LANGUAGES CXX)\n"
    out = get_versions_cpp.get_version({
        "repo": "fmtlib/fmt",
        "base_commit": "abcdef123456",
    })
    assert out == "9.1"
    assert mock_fetch.called


@mock.patch("swefficiency.versioning.get_versions_cpp._fetch_url_with_retry")
def test_get_version_returns_none_when_no_path_yields_match(mock_fetch):
    mock_fetch.return_value = None
    out = get_versions_cpp.get_version({
        "repo": "fmtlib/fmt",
        "base_commit": "0" * 40,
    })
    assert out is None


@mock.patch("swefficiency.versioning.get_versions_cpp._fetch_url_with_retry")
def test_get_version_unknown_repo_uses_fallback_paths(mock_fetch):
    """Unknown repos should still probe FALLBACK paths + generic patterns."""
    mock_fetch.return_value = '{"version": "2.3.4"}'
    out = get_versions_cpp.get_version({
        "repo": "some/unknown-repo",
        "base_commit": "deadbeefcafe",
    })
    assert out == "2.3"


# ---------------------------------------------------------------------------
# get_version build-mode (local file) dispatch
# ---------------------------------------------------------------------------

def test_get_version_build_mode_reads_local_file(tmp_path):
    fake_repo = tmp_path / "fmt_clone"
    fake_repo.mkdir()
    (fake_repo / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.8)\n"
        "project(FMT VERSION 10.0.0 LANGUAGES CXX)\n"
    )
    out = get_versions_cpp.get_version(
        {"repo": "fmtlib/fmt", "base_commit": "abc"},
        is_build=True,
        path_repo=str(fake_repo),
    )
    assert out == "10.0"


def test_get_version_build_mode_missing_path_returns_none(tmp_path):
    out = get_versions_cpp.get_version(
        {"repo": "fmtlib/fmt", "base_commit": "abc"},
        is_build=True,
        path_repo=str(tmp_path / "does-not-exist"),
    )
    assert out is None


# ---------------------------------------------------------------------------
# map_version_to_task_instances_cpp
# ---------------------------------------------------------------------------

@mock.patch("swefficiency.versioning.get_versions_cpp.get_version")
def test_map_version_to_task_instances_groups_by_version(mock_get):
    mock_get.side_effect = ["10.2", "10.2", "9.1", None]
    instances = [
        {"repo": "fmtlib/fmt", "base_commit": "a"},
        {"repo": "fmtlib/fmt", "base_commit": "b"},
        {"repo": "fmtlib/fmt", "base_commit": "c"},
        {"repo": "fmtlib/fmt", "base_commit": "d"},  # None → dropped
    ]
    grouped = get_versions_cpp.map_version_to_task_instances_cpp(instances)
    assert set(grouped.keys()) == {"10.2", "9.1"}
    assert len(grouped["10.2"]) == 2
    assert len(grouped["9.1"]) == 1


# ---------------------------------------------------------------------------
# Constant shape sanity
# ---------------------------------------------------------------------------

def test_six_tier1_repos_have_version_paths():
    expected = {
        "fmtlib/fmt", "gabime/spdlog", "nlohmann/json",
        "abseil/abseil-cpp", "ericniebler/range-v3", "eigen-mirror/eigen",
    }
    assert expected.issubset(set(MAP_REPO_TO_VERSION_PATHS_CPP.keys()))


def test_six_tier1_repos_have_patterns():
    """Each Tier-1 repo either has explicit patterns or falls back to generic."""
    for repo in (
        "fmtlib/fmt", "gabime/spdlog", "nlohmann/json",
        "abseil/abseil-cpp", "ericniebler/range-v3", "eigen-mirror/eigen",
    ):
        patterns = MAP_REPO_TO_VERSION_PATTERNS_CPP.get(repo, GENERIC_VERSION_PATTERNS_CPP)
        assert patterns, f"{repo} has no version patterns"
