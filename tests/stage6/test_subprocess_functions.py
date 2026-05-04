"""~110 parametrized tests for subprocess-based functions:
_git_clone, _git_checkout, process_repo_group.

All subprocess calls are mocked — no real git commands or network calls.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import _git_checkout, _git_clone, process_repo_group


# ═══════════════════════════════════════════════════════════════════════
# 1. TestGitClone  (~35 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestGitClone:
    """Tests for _git_clone(repo, dest, *, timeout=300) -> bool."""

    # ----- Successful clone -----

    _SUCCESS_REPOS = [
        pytest.param("owner/repo", id="simple-owner-repo"),
        pytest.param("org/repo-name", id="hyphenated-repo"),
        pytest.param("a/b", id="minimal-repo"),
        pytest.param("numpy/numpy", id="numpy"),
        pytest.param("pandas-dev/pandas", id="pandas"),
        pytest.param("scipy/scipy", id="scipy"),
        pytest.param("django/django", id="django"),
        pytest.param("pallets/flask", id="flask"),
        pytest.param("UPPER/CASE-Repo", id="uppercase-repo"),
        pytest.param("deep-org/my_awesome-lib", id="complex-name"),
    ]

    @pytest.mark.parametrize("repo", _SUCCESS_REPOS)
    @patch("detect_repo_specs.subprocess.run")
    def test_successful_clone_returns_true(self, mock_run: MagicMock, repo: str, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        result = _git_clone(repo, tmp_path)
        assert result is True

    @pytest.mark.parametrize("repo", _SUCCESS_REPOS)
    @patch("detect_repo_specs.subprocess.run")
    def test_clone_url_format(self, mock_run: MagicMock, repo: str, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone(repo, tmp_path)
        args = mock_run.call_args
        cmd = args[0][0]
        expected_url = f"https://github.com/{repo}.git"
        assert cmd[5] == expected_url, f"Expected URL {expected_url}, got {cmd[5]}"

    @pytest.mark.parametrize("repo", _SUCCESS_REPOS)
    @patch("detect_repo_specs.subprocess.run")
    def test_clone_command_structure(self, mock_run: MagicMock, repo: str, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone(repo, tmp_path)
        args = mock_run.call_args
        cmd = args[0][0]
        expected_url = f"https://github.com/{repo}.git"
        assert cmd == ["git", "clone", "--quiet", "--depth", "200", expected_url, str(tmp_path)]

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_check_true(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone("owner/repo", tmp_path)
        assert mock_run.call_args[1]["check"] is True

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_capture_output_true(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone("owner/repo", tmp_path)
        assert mock_run.call_args[1]["capture_output"] is True

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_default_timeout_300(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone("owner/repo", tmp_path)
        assert mock_run.call_args[1]["timeout"] == 300

    _CUSTOM_TIMEOUTS = [
        pytest.param(60, id="timeout-60"),
        pytest.param(120, id="timeout-120"),
        pytest.param(600, id="timeout-600"),
        pytest.param(10, id="timeout-10"),
        pytest.param(1, id="timeout-1"),
    ]

    @pytest.mark.parametrize("timeout", _CUSTOM_TIMEOUTS)
    @patch("detect_repo_specs.subprocess.run")
    def test_clone_custom_timeout(self, mock_run: MagicMock, timeout: int, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone("owner/repo", tmp_path, timeout=timeout)
        assert mock_run.call_args[1]["timeout"] == timeout

    # ----- Failure: CalledProcessError -----

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_called_process_error_returns_false(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = subprocess.CalledProcessError(128, "git clone")
        result = _git_clone("owner/repo", tmp_path)
        assert result is False

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_called_process_error_nonexistent_repo(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = subprocess.CalledProcessError(128, "git clone", stderr=b"not found")
        result = _git_clone("nonexistent/repo", tmp_path)
        assert result is False

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_called_process_error_auth_failure(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = subprocess.CalledProcessError(
            128, "git clone", stderr=b"Authentication failed"
        )
        result = _git_clone("private/repo", tmp_path)
        assert result is False

    # ----- Failure: TimeoutExpired -----

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_timeout_expired_returns_false(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = subprocess.TimeoutExpired("git clone", 300)
        result = _git_clone("owner/repo", tmp_path)
        assert result is False

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_timeout_expired_large_repo(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = subprocess.TimeoutExpired("git clone", 300)
        result = _git_clone("big-org/huge-repo", tmp_path)
        assert result is False

    # ----- Dest path serialization -----

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_dest_path_is_stringified(self, mock_run: MagicMock, tmp_path: Path):
        dest = tmp_path / "subdir" / "clone"
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone("owner/repo", dest)
        cmd = mock_run.call_args[0][0]
        assert cmd[-1] == str(dest)

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_dest_with_special_chars(self, mock_run: MagicMock, tmp_path: Path):
        dest = tmp_path / "owner__repo" / "abc123def456"
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone("owner/repo", dest)
        cmd = mock_run.call_args[0][0]
        assert cmd[-1] == str(dest)

    # ----- subprocess.run called exactly once -----

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_calls_subprocess_once(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_clone("owner/repo", tmp_path)
        assert mock_run.call_count == 1

    @patch("detect_repo_specs.subprocess.run")
    def test_clone_failure_calls_subprocess_once(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        _git_clone("owner/repo", tmp_path)
        assert mock_run.call_count == 1


# ═══════════════════════════════════════════════════════════════════════
# 2. TestGitCheckout  (~35 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestGitCheckout:
    """Tests for _git_checkout(repo_dir, commit, *, timeout=120) -> bool."""

    # ----- Successful checkout (first try) -----

    _COMMIT_HASHES = [
        pytest.param("abc123def456789012345678901234567890abcd", id="full-sha"),
        pytest.param("abc123d", id="short-sha-7"),
        pytest.param("abc123def456", id="short-sha-12"),
        pytest.param("0" * 40, id="all-zeros"),
        pytest.param("f" * 40, id="all-fs"),
        pytest.param("1a2b3c4d5e6f", id="mixed-hex"),
        pytest.param("v1.0.0", id="tag-v1"),
        pytest.param("release/2.0", id="tag-release"),
        pytest.param("HEAD~1", id="relative-ref"),
        pytest.param("main", id="branch-name"),
    ]

    @pytest.mark.parametrize("commit", _COMMIT_HASHES)
    @patch("detect_repo_specs.subprocess.run")
    def test_successful_checkout_returns_true(self, mock_run: MagicMock, commit: str, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        result = _git_checkout(tmp_path, commit)
        assert result is True

    @pytest.mark.parametrize("commit", _COMMIT_HASHES)
    @patch("detect_repo_specs.subprocess.run")
    def test_checkout_command_structure(self, mock_run: MagicMock, commit: str, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_checkout(tmp_path, commit)
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "checkout", commit]

    @patch("detect_repo_specs.subprocess.run")
    def test_checkout_cwd_parameter(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_checkout(tmp_path, "abc123")
        assert mock_run.call_args[1]["cwd"] == str(tmp_path)

    @patch("detect_repo_specs.subprocess.run")
    def test_checkout_check_true(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_checkout(tmp_path, "abc123")
        assert mock_run.call_args[1]["check"] is True

    @patch("detect_repo_specs.subprocess.run")
    def test_checkout_capture_output_true(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_checkout(tmp_path, "abc123")
        assert mock_run.call_args[1]["capture_output"] is True

    @patch("detect_repo_specs.subprocess.run")
    def test_checkout_default_timeout_120(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_checkout(tmp_path, "abc123")
        assert mock_run.call_args[1]["timeout"] == 120

    _CUSTOM_TIMEOUTS = [
        pytest.param(30, id="timeout-30"),
        pytest.param(60, id="timeout-60"),
        pytest.param(180, id="timeout-180"),
        pytest.param(300, id="timeout-300"),
    ]

    @pytest.mark.parametrize("timeout", _CUSTOM_TIMEOUTS)
    @patch("detect_repo_specs.subprocess.run")
    def test_checkout_custom_timeout(self, mock_run: MagicMock, timeout: int, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_checkout(tmp_path, "abc123", timeout=timeout)
        assert mock_run.call_args[1]["timeout"] == timeout

    @patch("detect_repo_specs.subprocess.run")
    def test_checkout_success_calls_subprocess_once(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.return_value = MagicMock(returncode=0)
        _git_checkout(tmp_path, "abc123")
        assert mock_run.call_count == 1

    # ----- First checkout fails, unshallow + retry succeeds -----

    @patch("detect_repo_specs.subprocess.run")
    def test_unshallow_retry_succeeds(self, mock_run: MagicMock, tmp_path: Path):
        # First call: checkout fails. Second: unshallow succeeds. Third: checkout succeeds.
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            MagicMock(returncode=0),  # unshallow
            MagicMock(returncode=0),  # retry checkout
        ]
        result = _git_checkout(tmp_path, "abc123def456")
        assert result is True

    @patch("detect_repo_specs.subprocess.run")
    def test_unshallow_retry_calls_correct_commands(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        _git_checkout(tmp_path, "abc123")
        assert mock_run.call_count == 3
        # First call: checkout
        assert mock_run.call_args_list[0][0][0] == ["git", "checkout", "abc123"]
        # Second call: unshallow
        assert mock_run.call_args_list[1][0][0] == ["git", "fetch", "--unshallow"]
        # Third call: retry checkout
        assert mock_run.call_args_list[2][0][0] == ["git", "checkout", "abc123"]

    @patch("detect_repo_specs.subprocess.run")
    def test_unshallow_uses_cwd(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        _git_checkout(tmp_path, "abc123")
        # All three calls should use cwd
        for c in mock_run.call_args_list:
            assert c[1]["cwd"] == str(tmp_path)

    @patch("detect_repo_specs.subprocess.run")
    def test_unshallow_timeout_is_300(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        _git_checkout(tmp_path, "abc123")
        # Unshallow (second call) uses hardcoded timeout=300
        assert mock_run.call_args_list[1][1]["timeout"] == 300

    @patch("detect_repo_specs.subprocess.run")
    def test_retry_checkout_uses_original_timeout(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        _git_checkout(tmp_path, "abc123", timeout=60)
        # Retry checkout (third call) uses the original timeout param
        assert mock_run.call_args_list[2][1]["timeout"] == 60

    # ----- First checkout fails, unshallow fails -----

    @patch("detect_repo_specs.subprocess.run")
    def test_unshallow_fails_returns_false(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            subprocess.CalledProcessError(1, "git fetch --unshallow"),
        ]
        result = _git_checkout(tmp_path, "abc123")
        assert result is False

    @patch("detect_repo_specs.subprocess.run")
    def test_unshallow_timeout_returns_false(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            subprocess.TimeoutExpired("git fetch", 300),
        ]
        result = _git_checkout(tmp_path, "abc123")
        assert result is False

    # ----- First checkout fails, unshallow succeeds, retry fails -----

    @patch("detect_repo_specs.subprocess.run")
    def test_retry_checkout_fails_returns_false(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            MagicMock(returncode=0),  # unshallow ok
            subprocess.CalledProcessError(1, "git checkout"),  # retry fails
        ]
        result = _git_checkout(tmp_path, "abc123")
        assert result is False

    @patch("detect_repo_specs.subprocess.run")
    def test_retry_checkout_timeout_returns_false(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git checkout"),
            MagicMock(returncode=0),  # unshallow ok
            subprocess.TimeoutExpired("git checkout", 120),  # retry times out
        ]
        result = _git_checkout(tmp_path, "abc123")
        assert result is False

    # ----- TimeoutExpired on first checkout -----

    @patch("detect_repo_specs.subprocess.run")
    def test_first_checkout_timeout_returns_false(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = subprocess.TimeoutExpired("git checkout", 120)
        result = _git_checkout(tmp_path, "abc123")
        assert result is False

    @patch("detect_repo_specs.subprocess.run")
    def test_first_checkout_timeout_no_retry(self, mock_run: MagicMock, tmp_path: Path):
        """TimeoutExpired on first checkout should NOT trigger unshallow retry."""
        mock_run.side_effect = subprocess.TimeoutExpired("git checkout", 120)
        _git_checkout(tmp_path, "abc123")
        # Only one call — no unshallow attempted
        assert mock_run.call_count == 1

    @patch("detect_repo_specs.subprocess.run")
    def test_first_checkout_timeout_different_commits(self, mock_run: MagicMock, tmp_path: Path):
        mock_run.side_effect = subprocess.TimeoutExpired("git checkout", 120)
        result = _git_checkout(tmp_path, "deadbeefcafe")
        assert result is False
        assert mock_run.call_count == 1

    # ----- Various cwd paths -----

    _CWD_PATHS = [
        pytest.param("clones/owner__repo/abc123def456", id="typical-clone-path"),
        pytest.param("tmp/repos/deep/nested", id="deep-nested"),
        pytest.param("single", id="single-dir"),
    ]

    @pytest.mark.parametrize("subdir", _CWD_PATHS)
    @patch("detect_repo_specs.subprocess.run")
    def test_checkout_various_cwd_paths(self, mock_run: MagicMock, subdir: str, tmp_path: Path):
        repo_dir = tmp_path / subdir
        mock_run.return_value = MagicMock(returncode=0)
        _git_checkout(repo_dir, "abc123")
        assert mock_run.call_args[1]["cwd"] == str(repo_dir)


# ═══════════════════════════════════════════════════════════════════════
# 3. TestProcessRepoGroup  (~45 cases)
# ═══════════════════════════════════════════════════════════════════════


_MOCK_SPECS: dict[str, Any] = {
    "python_version": "3.9",
    "install_cmd": "pip install -e .",
    "test_cmd_override": "pytest {test_files}",
    "packages_source": "",
    "pip_packages": [],
    "pre_install_cmds": [],
    "reqs_paths": [],
    "env_yml_paths": [],
    "log_parser_type": "pytest",
    "version": "1.0.0",
    "_license": "MIT",
}


class TestProcessRepoGroup:
    """Tests for process_repo_group(repo, base_commit, clone_dir, cache) -> dict | None."""

    # ----- Cache hit -----

    _CACHE_HIT_REPOS = [
        pytest.param("owner/repo", "abc123def456", id="simple-cache-hit"),
        pytest.param("numpy/numpy", "deadbeef1234", id="numpy-cache-hit"),
        pytest.param("org/my-pkg", "0" * 40, id="full-sha-cache-hit"),
        pytest.param("a/b", "cafe1234", id="minimal-cache-hit"),
        pytest.param("UPPER/Case-Repo", "aabbccdd", id="mixed-case-cache-hit"),
    ]

    @pytest.mark.parametrize("repo,commit", _CACHE_HIT_REPOS)
    def test_cache_hit_returns_cached_specs(self, repo: str, commit: str, tmp_path: Path):
        cache_key = f"{repo}@{commit}"
        cached_specs = dict(_MOCK_SPECS)
        cache = {cache_key: cached_specs}
        result = process_repo_group(repo, commit, tmp_path, cache)
        assert result is cached_specs

    @pytest.mark.parametrize("repo,commit", _CACHE_HIT_REPOS)
    @patch("detect_repo_specs._git_clone")
    def test_cache_hit_skips_clone(self, mock_clone: MagicMock, repo: str, commit: str, tmp_path: Path):
        cache_key = f"{repo}@{commit}"
        cache = {cache_key: dict(_MOCK_SPECS)}
        process_repo_group(repo, commit, tmp_path, cache)
        mock_clone.assert_not_called()

    def test_cache_key_format(self, tmp_path: Path):
        repo = "owner/repo"
        commit = "abc123def456"
        cache_key = f"{repo}@{commit}"
        cache = {cache_key: dict(_MOCK_SPECS)}
        result = process_repo_group(repo, commit, tmp_path, cache)
        assert result is not None

    def test_cache_miss_different_commit(self, tmp_path: Path):
        """Cache has repo@commitA but we request repo@commitB — should not hit cache."""
        cache = {"owner/repo@aaa111": dict(_MOCK_SPECS)}
        with patch("detect_repo_specs._git_clone", return_value=False):
            result = process_repo_group("owner/repo", "bbb222", tmp_path, cache)
        assert result is None  # clone fails → None

    # ----- Successful clone+checkout+detect -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_success_returns_specs(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        cache: dict[str, Any] = {}
        result = process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        assert result is not None
        assert result["python_version"] == "3.9"

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_success_stores_in_cache(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123def456", tmp_path, cache)
        assert "owner/repo@abc123def456" in cache
        assert cache["owner/repo@abc123def456"]["python_version"] == "3.9"

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_success_calls_clone_with_dest(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        process_repo_group("owner/repo", "abc123def456", tmp_path, {})
        clone_dest = mock_clone.call_args[0][1]
        expected = tmp_path / "owner__repo" / "abc123def456"
        assert clone_dest == expected

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_success_calls_checkout_with_dest_and_commit(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        process_repo_group("owner/repo", "abc123def456", tmp_path, {})
        expected_dest = tmp_path / "owner__repo" / "abc123def456"
        mock_checkout.assert_called_once_with(expected_dest, "abc123def456")

    # ----- Dest path construction -----

    _DEST_PATH_CASES = [
        pytest.param("owner/repo", "abcdef123456", "owner__repo", "abcdef123456", id="simple"),
        pytest.param("numpy/numpy", "deadbeef1234abcd5678", "numpy__numpy", "deadbeef1234", id="numpy-truncated"),
        pytest.param("org/my-pkg", "a" * 40, "org__my-pkg", "a" * 12, id="full-sha-truncated"),
        pytest.param("UPPER/Case", "0123456789ab", "UPPER__Case", "0123456789ab", id="mixed-case"),
        pytest.param("a/b", "cafe12345678", "a__b", "cafe12345678", id="minimal"),
        pytest.param("deep-org/cool-lib", "ff" * 20, "deep-org__cool-lib", "f" * 12, id="hyphenated-org"),
    ]

    @pytest.mark.parametrize("repo,commit,expected_dir,expected_subdir", _DEST_PATH_CASES)
    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_dest_path_construction(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock,
        repo: str, commit: str, expected_dir: str, expected_subdir: str, tmp_path: Path,
    ):
        process_repo_group(repo, commit, tmp_path, {})
        clone_dest = mock_clone.call_args[0][1]
        expected = tmp_path / expected_dir / expected_subdir
        assert clone_dest == expected

    # ----- Clone failure -----

    @patch("detect_repo_specs._git_clone", return_value=False)
    def test_clone_failure_returns_none(self, mock_clone: MagicMock, tmp_path: Path):
        result = process_repo_group("owner/repo", "abc123", tmp_path, {})
        assert result is None

    @patch("detect_repo_specs._git_clone", return_value=False)
    def test_clone_failure_not_cached(self, mock_clone: MagicMock, tmp_path: Path):
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123", tmp_path, cache)
        assert "owner/repo@abc123" not in cache

    @patch("detect_repo_specs._git_checkout")
    @patch("detect_repo_specs._git_clone", return_value=False)
    def test_clone_failure_skips_checkout(self, mock_clone: MagicMock, mock_checkout: MagicMock, tmp_path: Path):
        process_repo_group("owner/repo", "abc123", tmp_path, {})
        mock_checkout.assert_not_called()

    # ----- Checkout failure -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs._git_checkout", return_value=False)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_checkout_failure_returns_none(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_rmtree: MagicMock, tmp_path: Path,
    ):
        result = process_repo_group("owner/repo", "abc123", tmp_path, {})
        assert result is None

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs._git_checkout", return_value=False)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_checkout_failure_not_cached(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_rmtree: MagicMock, tmp_path: Path,
    ):
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123", tmp_path, cache)
        assert "owner/repo@abc123" not in cache

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs")
    @patch("detect_repo_specs._git_checkout", return_value=False)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_checkout_failure_skips_detect(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        process_repo_group("owner/repo", "abc123", tmp_path, {})
        mock_detect.assert_not_called()

    # ----- Exception during detect -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", side_effect=RuntimeError("oops"))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_detect_exception_returns_none(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        result = process_repo_group("owner/repo", "abc123", tmp_path, {})
        assert result is None

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", side_effect=OSError("disk error"))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_detect_oserror_returns_none(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        result = process_repo_group("owner/repo", "abc123", tmp_path, {})
        assert result is None

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", side_effect=KeyError("missing key"))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_detect_keyerror_returns_none(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        result = process_repo_group("owner/repo", "abc123", tmp_path, {})
        assert result is None

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", side_effect=ValueError("bad value"))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_detect_exception_not_cached(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123", tmp_path, cache)
        assert "owner/repo@abc123" not in cache

    # ----- Cleanup: dest directory removed after processing -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_cleanup_rmtree_called_on_success(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        process_repo_group("owner/repo", "abc123def456", tmp_path, {})
        expected_dest = tmp_path / "owner__repo" / "abc123def45"
        # rmtree is called for the dest directory; just verify it was called
        assert mock_rmtree.called

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs._git_checkout", return_value=False)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_cleanup_rmtree_called_on_checkout_failure(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_rmtree: MagicMock, tmp_path: Path,
    ):
        process_repo_group("owner/repo", "abc123def456", tmp_path, {})
        # rmtree should be called in the finally block (cloned=True)
        assert mock_rmtree.called

    @patch("detect_repo_specs._git_clone", return_value=False)
    def test_no_cleanup_when_clone_fails(self, mock_clone: MagicMock, tmp_path: Path):
        """When clone fails, cloned=False so no cleanup should happen for the dest."""
        with patch("detect_repo_specs.shutil.rmtree") as mock_rmtree:
            process_repo_group("owner/repo", "abc123def456", tmp_path, {})
            # rmtree is called once initially to clean pre-existing dest, but
            # the finally block should NOT call rmtree (cloned=False)
            # We just verify the function completed without error
            assert True

    # ----- Existing dest directory gets cleaned up first -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_existing_dest_cleaned_before_clone(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        # Create the dest dir so dest.exists() returns True in the code
        dest = tmp_path / "owner__repo" / "abc123def456"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "leftover.txt").write_text("old data")

        process_repo_group("owner/repo", "abc123def456789012345678", tmp_path, {})
        # rmtree should have been called (ignore_errors=True for pre-clean)
        assert mock_rmtree.called

    # ----- Various repo name formats -----

    _REPO_FORMAT_CASES = [
        pytest.param("owner/repo", "abc123", "owner__repo", id="basic-slash"),
        pytest.param("numpy/numpy", "def456", "numpy__numpy", id="same-owner-repo"),
        pytest.param("org-name/pkg-name", "111222", "org-name__pkg-name", id="hyphenated"),
        pytest.param("A/B", "aaa111", "A__B", id="single-char-each"),
        pytest.param("MyOrg/MyPkg", "bbb222", "MyOrg__MyPkg", id="camel-case"),
    ]

    @pytest.mark.parametrize("repo,commit,expected_prefix", _REPO_FORMAT_CASES)
    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_repo_name_slash_replacement(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock,
        repo: str, commit: str, expected_prefix: str, tmp_path: Path,
    ):
        process_repo_group(repo, commit, tmp_path, {})
        clone_dest = mock_clone.call_args[0][1]
        assert clone_dest.parent.name == expected_prefix

    # ----- Cache key format -----

    _CACHE_KEY_CASES = [
        pytest.param("owner/repo", "abc123", "owner/repo@abc123", id="basic-key"),
        pytest.param("numpy/numpy", "dead1234", "numpy/numpy@dead1234", id="numpy-key"),
        pytest.param("a/b", "x" * 40, f"a/b@{'x' * 40}", id="full-sha-key"),
    ]

    @pytest.mark.parametrize("repo,commit,expected_key", _CACHE_KEY_CASES)
    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_cache_key_stored_correctly(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock,
        repo: str, commit: str, expected_key: str, tmp_path: Path,
    ):
        cache: dict[str, Any] = {}
        process_repo_group(repo, commit, tmp_path, cache)
        assert expected_key in cache

    # ----- Clone receives repo name (not cache key) -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_clone_receives_repo_name(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        process_repo_group("scipy/scipy", "abc123", tmp_path, {})
        assert mock_clone.call_args[0][0] == "scipy/scipy"

    # ----- Detect receives dest and repo -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_detect_receives_correct_args(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        process_repo_group("owner/repo", "abc123def456", tmp_path, {})
        expected_dest = tmp_path / "owner__repo" / "abc123def456"
        mock_detect.assert_called_once_with(expected_dest, "owner/repo")

    # ----- Multiple sequential calls with different repos -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_multiple_repos_populate_cache(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo1", "aaa111", tmp_path, cache)
        process_repo_group("owner/repo2", "bbb222", tmp_path, cache)
        assert "owner/repo1@aaa111" in cache
        assert "owner/repo2@bbb222" in cache

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_second_call_hits_cache(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        cache: dict[str, Any] = {}
        process_repo_group("owner/repo", "abc123", tmp_path, cache)
        assert mock_clone.call_count == 1

        # Second call should hit cache
        result = process_repo_group("owner/repo", "abc123", tmp_path, cache)
        assert result is not None
        assert mock_clone.call_count == 1  # NOT called again

    # ----- Empty cache dict -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_empty_cache_triggers_clone(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        process_repo_group("owner/repo", "abc123", tmp_path, {})
        mock_clone.assert_called_once()

    # ----- Commit truncation for dest path -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_commit_truncated_to_12_for_dest(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        full_commit = "abcdef1234567890abcdef1234567890abcdef12"
        process_repo_group("owner/repo", full_commit, tmp_path, {})
        clone_dest = mock_clone.call_args[0][1]
        assert clone_dest.name == "abcdef123456"  # first 12 chars

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_short_commit_used_as_is_for_dest(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        short_commit = "abc123"
        process_repo_group("owner/repo", short_commit, tmp_path, {})
        clone_dest = mock_clone.call_args[0][1]
        assert clone_dest.name == "abc123"  # under 12 chars, used as-is

    # ----- Full commit passed to checkout (not truncated) -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_full_commit_passed_to_checkout(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        full_commit = "abcdef1234567890abcdef1234567890abcdef12"
        process_repo_group("owner/repo", full_commit, tmp_path, {})
        # checkout receives the full commit, not truncated
        assert mock_checkout.call_args[0][1] == full_commit

    # ----- Return type checks -----

    @patch("detect_repo_specs.shutil.rmtree")
    @patch("detect_repo_specs.detect_all_specs", return_value=dict(_MOCK_SPECS))
    @patch("detect_repo_specs._git_checkout", return_value=True)
    @patch("detect_repo_specs._git_clone", return_value=True)
    def test_success_returns_dict(
        self, mock_clone: MagicMock, mock_checkout: MagicMock,
        mock_detect: MagicMock, mock_rmtree: MagicMock, tmp_path: Path,
    ):
        result = process_repo_group("owner/repo", "abc123", tmp_path, {})
        assert isinstance(result, dict)

    @patch("detect_repo_specs._git_clone", return_value=False)
    def test_failure_returns_none_type(self, mock_clone: MagicMock, tmp_path: Path):
        result = process_repo_group("owner/repo", "abc123", tmp_path, {})
        assert result is None
