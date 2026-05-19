# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for swefficiency.versioning.get_versions_ts."""
from __future__ import annotations

import json
import os
import subprocess
from unittest import mock

import pytest

# Must run BEFORE importing get_versions_ts so the module's cache-safe accessor
# observes the env var on first call; mirrors tests/versioning/conftest.py.
os.environ.setdefault("SWEFF_DISABLE_CACHE", "1")

from swefficiency.versioning import get_versions_ts
from swefficiency.versioning.constants_ts import (
    GENERIC_VERSION_PATTERNS_TS,
    MAP_REPO_TO_VERSION_PATHS_TS,
    NS_VERSION_TS,
)


def test_ns_version_ts_is_non_empty_string():
    assert isinstance(NS_VERSION_TS, str)
    assert NS_VERSION_TS


@pytest.mark.parametrize("raw,expected", [
    ("4.17.21", "4.17.21"),
    ("v3.4.5", "3.4.5"),
    ("V1.0.0-rc.1", "1.0.0-rc.1"),
    ("3", "3"),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_normalize_version_ts(raw, expected):
    assert get_versions_ts._normalize_version_ts(raw) == expected


def test_find_version_in_package_json_field():
    text = '{"name": "lodash", "version": "4.17.21"}'
    assert get_versions_ts._find_version_in_text(text, GENERIC_VERSION_PATTERNS_TS) == "4.17.21"


def test_find_version_returns_none_when_nothing_matches():
    assert get_versions_ts._find_version_in_text("random noise", GENERIC_VERSION_PATTERNS_TS) is None


def test_find_version_skips_empty_input():
    assert get_versions_ts._find_version_in_text("", GENERIC_VERSION_PATTERNS_TS) is None


def test_get_version_for_repo_ts_reads_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "lodash", "version": "4.17.21"}),
        encoding="utf-8",
    )
    assert get_versions_ts.get_version_for_repo_ts(str(tmp_path)) == "4.17.21"


def test_get_version_for_repo_ts_ignores_other_package_json_fields(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({
            "name": "axios",
            "description": "Promise based HTTP client",
            "version": "1.6.2",
            "license": "MIT",
        }),
        encoding="utf-8",
    )
    assert get_versions_ts.get_version_for_repo_ts(str(tmp_path)) == "1.6.2"


def test_get_version_for_repo_ts_git_tag_fallback(tmp_path):
    assert not (tmp_path / "package.json").exists()

    completed = subprocess.CompletedProcess(
        args=["git", "-C", str(tmp_path), "tag", "--sort=-v:refname"],
        returncode=0,
        stdout="v4.17.21\nv4.17.20\nv4.17.19\n",
        stderr="",
    )
    with mock.patch.object(
        get_versions_ts.subprocess, "run", return_value=completed
    ) as mock_run:
        out = get_versions_ts.get_version_for_repo_ts(str(tmp_path))

    assert out == "4.17.21"
    mock_run.assert_called_once()
    called_args = mock_run.call_args.args[0]
    assert called_args[:2] == ["git", "-C"]
    assert "tag" in called_args
    assert "--sort=-v:refname" in called_args


def test_get_version_for_repo_ts_git_tag_fallback_unversioned_tags_skipped(tmp_path):
    completed = subprocess.CompletedProcess(
        args=["git", "-C", str(tmp_path), "tag", "--sort=-v:refname"],
        returncode=0,
        stdout="release-candidate\nnightly\nv2.3.4\n",
        stderr="",
    )
    with mock.patch.object(
        get_versions_ts.subprocess, "run", return_value=completed
    ):
        assert get_versions_ts.get_version_for_repo_ts(str(tmp_path)) == "2.3.4"


def test_get_version_for_repo_ts_none_path_returns_none():
    assert get_versions_ts.get_version_for_repo_ts(None) is None


def test_get_version_for_repo_ts_missing_dir_returns_none(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert get_versions_ts.get_version_for_repo_ts(str(missing)) is None


def test_get_version_missing_repo_key_raises_keyerror():
    with pytest.raises(KeyError):
        get_versions_ts.get_version({"base_commit": "abc"})


def test_get_version_missing_base_commit_raises_keyerror():
    with pytest.raises(KeyError):
        get_versions_ts.get_version({"repo": "lodash/lodash"})


def test_get_version_non_dict_raises_typeerror():
    with pytest.raises(TypeError):
        get_versions_ts.get_version("not a dict")  # type: ignore[arg-type]


def test_get_version_build_mode_reads_local_package_json(tmp_path):
    fake_repo = tmp_path / "lodash_clone"
    fake_repo.mkdir()
    (fake_repo / "package.json").write_text(
        json.dumps({"name": "lodash", "version": "4.17.21"}),
        encoding="utf-8",
    )
    out = get_versions_ts.get_version(
        {"repo": "lodash/lodash", "base_commit": "abc"},
        is_build=True,
        path_repo=str(fake_repo),
    )
    assert out == "4.17.21"


def test_get_version_build_mode_missing_path_returns_none(tmp_path):
    out = get_versions_ts.get_version(
        {"repo": "lodash/lodash", "base_commit": "abc"},
        is_build=True,
        path_repo=str(tmp_path / "does-not-exist"),
    )
    assert out is None


def test_tier1_ts_repos_have_version_paths():
    expected = {
        "lodash/lodash", "axios/axios", "expressjs/express",
        "prettier/prettier", "vitest-dev/vitest", "microsoft/TypeScript",
    }
    assert expected.issubset(set(MAP_REPO_TO_VERSION_PATHS_TS.keys()))
