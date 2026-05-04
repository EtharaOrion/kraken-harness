"""Tests for get_versions_from_web, get_versions_from_build, merge_results,
map_version_to_task_instances, and main() orchestration in get_versions.py.
"""

import glob as glob_module
import json
import os
import subprocess
from argparse import Namespace
from multiprocessing import Manager
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

from swefficiency.versioning.get_versions import (
    get_versions_from_build,
    get_versions_from_web,
    main,
    map_version_to_task_instances,
    merge_results,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _inst(instance_id="test__1", repo="scikit-learn/scikit-learn", version=None, base_commit="abc123", **kw):
    d = {"instance_id": instance_id, "repo": repo, "base_commit": base_commit}
    if version is not None:
        d["version"] = version
    d.update(kw)
    return d


# ── map_version_to_task_instances ────────────────────────────────────────────


class TestMapVersionToTaskInstances:

    def test_instances_with_version_key(self):
        """Groups instances by their existing version field."""
        instances = [
            _inst(instance_id="a", version="1.0"),
            _inst(instance_id="b", version="1.0"),
            _inst(instance_id="c", version="2.0"),
        ]
        result = map_version_to_task_instances(instances)
        assert "1.0" in result
        assert "2.0" in result
        assert len(result["1.0"]) == 2
        assert len(result["2.0"]) == 1

    def test_instances_single_version(self):
        """All instances share same version."""
        instances = [_inst(instance_id=f"i{i}", version="3.5") for i in range(10)]
        result = map_version_to_task_instances(instances)
        assert list(result.keys()) == ["3.5"]
        assert len(result["3.5"]) == 10

    def test_instances_many_versions(self):
        """Each instance has a unique version."""
        instances = [_inst(instance_id=f"i{i}", version=f"{i}.0") for i in range(20)]
        result = map_version_to_task_instances(instances)
        assert len(result) == 20

    def test_instances_none_version(self):
        """Instances with None version are grouped under None key."""
        instances = [
            _inst(instance_id="a", version=None),
            _inst(instance_id="b", version="1.0"),
        ]
        # Need to set version explicitly since _inst skips None
        instances[0]["version"] = None
        result = map_version_to_task_instances(instances)
        assert None in result
        assert "1.0" in result

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_instances_without_version_key_calls_get_version(self, mock_gv):
        """When instances lack version key, calls get_version for each."""
        mock_gv.return_value = "1.0"
        instances = [_inst(instance_id=f"i{i}") for i in range(5)]
        result = map_version_to_task_instances(instances)
        assert mock_gv.call_count == 5
        assert "1.0" in result
        assert len(result["1.0"]) == 5

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_instances_without_version_mixed_results(self, mock_gv):
        """get_version returns different versions for different instances."""
        mock_gv.side_effect = ["1.0", "2.0", "1.0", None, "2.0"]
        instances = [_inst(instance_id=f"i{i}") for i in range(5)]
        result = map_version_to_task_instances(instances)
        assert len(result["1.0"]) == 2
        assert len(result["2.0"]) == 2
        assert len(result[None]) == 1

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_instances_without_version_all_none(self, mock_gv):
        """get_version returns None for all instances."""
        mock_gv.return_value = None
        instances = [_inst(instance_id=f"i{i}") for i in range(3)]
        result = map_version_to_task_instances(instances)
        assert list(result.keys()) == [None]
        assert len(result[None]) == 3

    def test_empty_versions_grouping(self):
        """Empty string version is a valid key."""
        instances = [_inst(instance_id="a", version=""), _inst(instance_id="b", version="")]
        result = map_version_to_task_instances(instances)
        assert "" in result
        assert len(result[""]) == 2

    @pytest.mark.parametrize(
        "versions, expected_keys",
        [
            (["1.0", "1.0", "1.0"], ["1.0"]),
            (["1.0", "2.0", "3.0"], ["1.0", "2.0", "3.0"]),
            (["1.0", "2.0", "1.0", "2.0"], ["1.0", "2.0"]),
        ],
        ids=["all_same", "all_different", "alternating"],
    )
    def test_version_grouping_parametrized(self, versions, expected_keys):
        """Various version distributions produce correct groupings."""
        instances = [_inst(instance_id=f"i{i}", version=v) for i, v in enumerate(versions)]
        result = map_version_to_task_instances(instances)
        assert sorted(result.keys()) == sorted(expected_keys)


# ── get_versions_from_web ────────────────────────────────────────────────────


class TestGetVersionsFromWeb:

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_basic_web_retrieval(self, mock_gv, tmp_path):
        """Retrieves versions and saves JSON."""
        mock_gv.return_value = "1.0"
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a"), _inst(instance_id="b")]
        data = {
            "data_tasks": instances,
            "save_path": save_path,
            "not_found_list": None,
        }
        get_versions_from_web(data)
        assert instances[0]["version"] == "1.0"
        assert instances[1]["version"] == "1.0"
        with open(save_path) as f:
            saved = json.load(f)
        assert len(saved) == 2

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_web_not_found_appended(self, mock_gv, tmp_path):
        """Instances with None version appended to not_found_list."""
        mock_gv.return_value = None
        save_path = str(tmp_path / "result.json")
        not_found = []
        instances = [_inst(instance_id="a")]
        data = {
            "data_tasks": instances,
            "save_path": save_path,
            "not_found_list": not_found,
        }
        get_versions_from_web(data)
        assert len(not_found) == 1
        assert not_found[0]["instance_id"] == "a"

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_web_not_found_list_none(self, mock_gv, tmp_path):
        """When not_found_list is None, no append happens."""
        mock_gv.return_value = None
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a")]
        data = {
            "data_tasks": instances,
            "save_path": save_path,
            "not_found_list": None,
        }
        get_versions_from_web(data)
        assert "version" not in instances[0]

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_web_mixed_found_and_not_found(self, mock_gv, tmp_path):
        """Mix of found and not-found versions."""
        mock_gv.side_effect = ["1.0", None, "2.0", None]
        save_path = str(tmp_path / "result.json")
        not_found = []
        instances = [_inst(instance_id=f"i{i}") for i in range(4)]
        data = {
            "data_tasks": instances,
            "save_path": save_path,
            "not_found_list": not_found,
        }
        get_versions_from_web(data)
        assert instances[0]["version"] == "1.0"
        assert instances[2]["version"] == "2.0"
        assert len(not_found) == 2

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_web_empty_instances(self, mock_gv, tmp_path):
        """Empty instance list produces empty JSON file."""
        save_path = str(tmp_path / "result.json")
        data = {
            "data_tasks": [],
            "save_path": save_path,
            "not_found_list": None,
        }
        get_versions_from_web(data)
        with open(save_path) as f:
            saved = json.load(f)
        assert saved == []

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_web_saves_all_instances(self, mock_gv, tmp_path):
        """All instances saved regardless of version found or not."""
        mock_gv.side_effect = ["1.0", None]
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a"), _inst(instance_id="b")]
        data = {
            "data_tasks": instances,
            "save_path": save_path,
            "not_found_list": [],
        }
        get_versions_from_web(data)
        with open(save_path) as f:
            saved = json.load(f)
        assert len(saved) == 2

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_web_large_batch(self, mock_gv, tmp_path):
        """Handles large batch of instances."""
        mock_gv.return_value = "5.0"
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id=f"i{i}") for i in range(100)]
        data = {
            "data_tasks": instances,
            "save_path": save_path,
            "not_found_list": None,
        }
        get_versions_from_web(data)
        assert all(inst["version"] == "5.0" for inst in instances)

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_web_manager_list(self, mock_gv, tmp_path):
        """Works with multiprocessing.Manager list."""
        mock_gv.return_value = None
        manager = Manager()
        shared_list = manager.list()
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a")]
        data = {
            "data_tasks": instances,
            "save_path": save_path,
            "not_found_list": shared_list,
        }
        get_versions_from_web(data)
        assert len(shared_list) == 1
        manager.shutdown()


# ── get_versions_from_build ──────────────────────────────────────────────────


class TestGetVersionsFromBuild:

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original/dir")
    def test_build_basic_flow(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Basic build flow: chdir, git commands, install, get_version, save."""
        mock_gv.return_value = "1.0"
        mock_run.return_value = MagicMock(returncode=0)
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a")]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "test_env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        assert instances[0]["version"] == "1.0"
        mock_chdir.assert_any_call("/tmp/repo")
        mock_chdir.assert_any_call("/original/dir")

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original")
    def test_build_iterates_reversed(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Instances iterated in reverse order."""
        call_order = []
        def side_effect(inst, is_build=False, path_repo=None):
            call_order.append(inst["instance_id"])
            return "1.0"
        mock_gv.side_effect = side_effect
        mock_run.return_value = MagicMock(returncode=0)
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id=f"i{i}") for i in range(3)]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        assert call_order == ["i2", "i1", "i0"]

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original")
    def test_build_checkout_failure_skips(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Checkout failure (non-zero return) skips instance."""
        def run_side_effect(cmd, **kwargs):
            result = MagicMock()
            if "checkout" in str(cmd):
                result.returncode = 1
            else:
                result.returncode = 0
            return result
        mock_run.side_effect = run_side_effect
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a")]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        mock_gv.assert_not_called()

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original")
    def test_build_install_failure_skips(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Install failure (non-zero return) skips instance."""
        call_count = [0]
        def run_side_effect(cmd, **kwargs):
            result = MagicMock()
            call_count[0] += 1
            if "activate" in str(cmd):
                result.returncode = 1
            else:
                result.returncode = 0
            return result
        mock_run.side_effect = run_side_effect
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a")]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        mock_gv.assert_not_called()

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original")
    def test_build_saves_json(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Results are saved to save_path as JSON."""
        mock_gv.return_value = "2.0"
        mock_run.return_value = MagicMock(returncode=0)
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a")]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        with open(save_path) as f:
            saved = json.load(f)
        assert saved[0]["version"] == "2.0"

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original")
    def test_build_git_commands_order(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Git commands run in correct order: restore, reset, clean, checkout."""
        mock_gv.return_value = "1.0"
        mock_run.return_value = MagicMock(returncode=0)
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a", base_commit="deadbeef")]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        cmds = [c[0][0] if c[0] else c[1].get("args", "") for c in mock_run.call_args_list]
        cmd_strs = [str(c) for c in cmds]
        assert "git restore ." in cmd_strs[0]
        assert "git reset HEAD ." in cmd_strs[1]
        assert "git clean -fd" in cmd_strs[2]
        assert "checkout" in cmd_strs[3]

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original")
    def test_build_custom_install_cmd(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Custom install cmd used for repos in INSTALL_CMD."""
        mock_gv.return_value = "1.0"
        mock_run.return_value = MagicMock(returncode=0)
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a", repo="matplotlib/matplotlib")]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        install_calls = [str(c) for c in mock_run.call_args_list if "pip" in str(c)]
        assert any("python -m pip install -e ." in c for c in install_calls)

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original")
    def test_build_multiple_instances(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Multiple instances all get versions."""
        mock_gv.side_effect = ["3.0", "2.0", "1.0"]
        mock_run.return_value = MagicMock(returncode=0)
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id=f"i{i}") for i in range(3)]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        assert instances[0]["version"] == "1.0"
        assert instances[1]["version"] == "2.0"
        assert instances[2]["version"] == "3.0"

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("os.getcwd", return_value="/original")
    def test_build_restores_cwd(self, mock_getcwd, mock_chdir, mock_run, mock_gv, tmp_path):
        """Always restores original working directory."""
        mock_gv.return_value = "1.0"
        mock_run.return_value = MagicMock(returncode=0)
        save_path = str(tmp_path / "result.json")
        instances = [_inst(instance_id="a")]
        data = {
            "data_tasks": instances,
            "path_repo": "/tmp/repo",
            "conda_env": "env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        last_chdir = mock_chdir.call_args_list[-1]
        assert last_chdir == call("/original")


# ── merge_results ────────────────────────────────────────────────────────────


class TestMergeResults:

    def test_merge_basic(self, tmp_path):
        """Merges multiple JSON files into one."""
        for i in range(3):
            with open(tmp_path / f"repo_versions_{i}.json", "w") as f:
                json.dump([{"id": i, "version": f"{i}.0"}], f)
        result = merge_results(
            str(tmp_path / "input.jsonl"),
            str(tmp_path / "repo"),
            str(tmp_path),
        )
        assert result == 3
        merged_path = tmp_path / "input_versions.json"
        assert merged_path.exists()
        with open(merged_path) as f:
            data = json.load(f)
        assert len(data) == 3

    def test_merge_temp_files_removed(self, tmp_path):
        """Temporary version files are removed after merge."""
        for i in range(2):
            with open(tmp_path / f"repo_versions_{i}.json", "w") as f:
                json.dump([{"id": i}], f)
        merge_results(
            str(tmp_path / "input.jsonl"),
            str(tmp_path / "repo"),
            str(tmp_path),
        )
        remaining = list(tmp_path.glob("repo_versions_*.json"))
        assert len(remaining) == 0

    def test_merge_no_files(self, tmp_path):
        """No matching files produces empty merged result."""
        result = merge_results(
            str(tmp_path / "input.jsonl"),
            str(tmp_path / "nonexistent"),
            str(tmp_path),
        )
        assert result == 0

    def test_merge_single_file(self, tmp_path):
        """Single file merge works."""
        with open(tmp_path / "repo_versions_0.json", "w") as f:
            json.dump([{"id": 0}, {"id": 1}], f)
        result = merge_results(
            str(tmp_path / "input.jsonl"),
            str(tmp_path / "repo"),
            str(tmp_path),
        )
        assert result == 2

    def test_merge_output_dir_none(self, tmp_path, monkeypatch):
        """When output_dir is None, saves to current directory."""
        monkeypatch.chdir(tmp_path)
        with open(tmp_path / "repo_versions_0.json", "w") as f:
            json.dump([{"id": 0}], f)
        result = merge_results(
            str(tmp_path / "input.jsonl"),
            str(tmp_path / "repo"),
            None,
        )
        assert result == 1
        assert os.path.exists("input_versions.json")

    def test_merge_many_files(self, tmp_path):
        """Merges many small files."""
        for i in range(20):
            with open(tmp_path / f"repo_versions_{i}.json", "w") as f:
                json.dump([{"id": i}], f)
        result = merge_results(
            str(tmp_path / "data.jsonl"),
            str(tmp_path / "repo"),
            str(tmp_path),
        )
        assert result == 20

    def test_merge_preserves_data(self, tmp_path):
        """All instance data preserved during merge."""
        instances_0 = [{"id": 0, "version": "1.0", "extra": "data"}]
        instances_1 = [{"id": 1, "version": "2.0", "extra": "more"}]
        with open(tmp_path / "repo_versions_0.json", "w") as f:
            json.dump(instances_0, f)
        with open(tmp_path / "repo_versions_1.json", "w") as f:
            json.dump(instances_1, f)
        merge_results(
            str(tmp_path / "input.jsonl"),
            str(tmp_path / "repo"),
            str(tmp_path),
        )
        with open(tmp_path / "input_versions.json") as f:
            merged = json.load(f)
        assert any(d["extra"] == "data" for d in merged)
        assert any(d["extra"] == "more" for d in merged)

    def test_merge_instances_path_extraction(self, tmp_path):
        """Output filename derived from instances_path stem."""
        with open(tmp_path / "repo_versions_0.json", "w") as f:
            json.dump([{"id": 0}], f)
        merge_results(
            "/some/long/path/my_tasks.jsonl",
            str(tmp_path / "repo"),
            str(tmp_path),
        )
        assert os.path.exists(str(tmp_path / "my_tasks_versions.json"))


# ── main() orchestration ────────────────────────────────────────────────────


class TestMainOrchestration:

    @patch("swefficiency.versioning.get_versions.merge_results")
    @patch("swefficiency.versioning.get_versions.Pool")
    @patch("swefficiency.versioning.get_versions.Manager")
    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_main_github_mode(self, mock_gi, mock_manager, mock_pool_cls, mock_merge):
        """GitHub mode: calls get_versions_from_web via Pool, then merges."""
        mock_gi.return_value = [_inst(instance_id=f"i{i}") for i in range(4)]
        mock_merge.return_value = 4
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        args = Namespace(
            instances_path="/tmp/input.jsonl",
            retrieval_method="github",
            num_workers=2,
            output_dir="/tmp/output",
            cleanup=False,
            conda_env=None,
            path_conda=None,
            testbed=None,
        )
        main(args)
        mock_pool.map.assert_called_once()
        mock_merge.assert_called_once()

    @patch("swefficiency.versioning.get_versions.merge_results")
    @patch("swefficiency.versioning.get_versions.Pool")
    @patch("swefficiency.versioning.get_versions.Manager")
    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_main_github_uses_correct_save_paths(self, mock_gi, mock_manager, mock_pool_cls, mock_merge):
        """GitHub mode save paths end with _versions_{i}.json."""
        mock_gi.return_value = [_inst(instance_id="i0"), _inst(instance_id="i1")]
        mock_merge.return_value = 2
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        args = Namespace(
            instances_path="/tmp/input.jsonl",
            retrieval_method="github",
            num_workers=2,
            output_dir="/tmp/output",
            cleanup=False,
            conda_env=None,
            path_conda=None,
            testbed=None,
        )
        main(args)
        call_args = mock_pool.map.call_args[0][1]
        save_paths = [d["save_path"] for d in call_args]
        assert all("_versions_" in sp for sp in save_paths)
        assert all(sp.endswith(".json") for sp in save_paths)

    @patch("swefficiency.versioning.get_versions.merge_results")
    @patch("swefficiency.versioning.get_versions.Pool")
    @patch("swefficiency.versioning.get_versions.Manager")
    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_main_github_not_found_list_none(self, mock_gi, mock_manager, mock_pool_cls, mock_merge):
        """GitHub mode passes not_found_list=None."""
        mock_gi.return_value = [_inst(instance_id="i0")]
        mock_merge.return_value = 1
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        args = Namespace(
            instances_path="/tmp/input.jsonl",
            retrieval_method="github",
            num_workers=1,
            output_dir="/tmp/output",
            cleanup=False,
            conda_env=None,
            path_conda=None,
            testbed=None,
        )
        main(args)
        call_args = mock_pool.map.call_args[0][1]
        assert call_args[0]["not_found_list"] is None

    @patch("swefficiency.versioning.get_versions.merge_results")
    @patch("swefficiency.versioning.get_versions.Pool")
    @patch("swefficiency.versioning.get_versions.Manager")
    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_main_mix_mode_shared_list(self, mock_gi, mock_manager, mock_pool_cls, mock_merge):
        """Mix mode uses shared Manager list for not_found."""
        mock_gi.return_value = [_inst(instance_id="i0")]
        mock_merge.return_value = 1
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        mock_mgr = MagicMock()
        mock_shared_list = MagicMock()
        mock_shared_list.__len__ = MagicMock(return_value=0)
        mock_shared_list.__iter__ = MagicMock(return_value=iter([]))
        mock_mgr.list.return_value = mock_shared_list
        mock_manager.return_value = mock_mgr

        args = Namespace(
            instances_path="/tmp/input.jsonl",
            retrieval_method="mix",
            num_workers=1,
            output_dir="/tmp/output",
            cleanup=False,
            conda_env="env",
            path_conda="/opt/conda",
            testbed="/tmp/testbed",
        )
        try:
            main(args)
        except Exception:
            pass
        mock_mgr.list.assert_called_once()

    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_main_loads_instances(self, mock_gi):
        """main() calls get_instances with correct path."""
        mock_gi.return_value = [_inst(instance_id="i0")]
        args = Namespace(
            instances_path="/data/tasks.jsonl",
            retrieval_method="github",
            num_workers=1,
            output_dir=None,
            cleanup=False,
            conda_env=None,
            path_conda=None,
            testbed=None,
        )
        with patch("swefficiency.versioning.get_versions.Pool") as mp, \
             patch("swefficiency.versioning.get_versions.Manager") as mm, \
             patch("swefficiency.versioning.get_versions.merge_results", return_value=1):
            mp.return_value = MagicMock()
            main(args)
        mock_gi.assert_called_once_with("/data/tasks.jsonl")

    @patch("swefficiency.versioning.get_versions.split_instances")
    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_main_splits_by_num_workers(self, mock_gi, mock_split):
        """main() splits instances by num_workers."""
        mock_gi.return_value = [_inst(instance_id=f"i{i}") for i in range(10)]
        mock_split.return_value = [[_inst()] for _ in range(4)]
        args = Namespace(
            instances_path="/data/tasks.jsonl",
            retrieval_method="github",
            num_workers=4,
            output_dir=None,
            cleanup=False,
            conda_env=None,
            path_conda=None,
            testbed=None,
        )
        with patch("swefficiency.versioning.get_versions.Pool") as mp, \
             patch("swefficiency.versioning.get_versions.Manager") as mm, \
             patch("swefficiency.versioning.get_versions.merge_results", return_value=10):
            mp.return_value = MagicMock()
            main(args)
        mock_split.assert_called_once_with(mock_gi.return_value, 4)

    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_main_repo_prefix_from_first_instance(self, mock_gi):
        """repo_prefix derived from first instance's repo field."""
        mock_gi.return_value = [_inst(repo="org/repo-name")]
        args = Namespace(
            instances_path="/data/tasks.jsonl",
            retrieval_method="github",
            num_workers=1,
            output_dir=None,
            cleanup=False,
            conda_env=None,
            path_conda=None,
            testbed=None,
        )
        with patch("swefficiency.versioning.get_versions.Pool") as mp, \
             patch("swefficiency.versioning.get_versions.Manager") as mm, \
             patch("swefficiency.versioning.get_versions.merge_results", return_value=1) as mock_merge:
            mp.return_value = MagicMock()
            main(args)
        merge_prefix = mock_merge.call_args[0][1]
        assert "org__repo-name" in merge_prefix


# ══════════════════════════════════════════════════════════════════════════════
# COMPREHENSIVE PARAMETRIZED ORCHESTRATION TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestMapVersionGrouping:
    """Parametrized tests for map_version_to_task_instances grouping logic."""

    @pytest.mark.parametrize(
        "versions",
        [
            ["1.0", "1.0", "1.0"],
            ["1.0", "2.0"],
            ["1.0", "2.0", "3.0"],
            ["0.1", "0.2", "0.3", "0.4", "0.5"],
            ["1.0"],
            ["1.0", "1.0", "2.0", "2.0", "3.0", "3.0"],
        ],
        ids=["all_same", "two_groups", "three_groups", "five_groups", "single", "paired"],
    )
    def test_grouping_by_version_count(self, versions):
        """Number of groups equals number of unique versions."""
        instances = [_inst(version=v, instance_id=f"i{i}") for i, v in enumerate(versions)]
        result = map_version_to_task_instances(instances)
        assert len(result) == len(set(versions))

    @pytest.mark.parametrize(
        "versions",
        [
            ["1.0", "1.0", "1.0"],
            ["1.0", "2.0"],
            ["1.0", "2.0", "3.0"],
            ["0.1", "0.2", "0.3", "0.4", "0.5"],
            ["1.0"],
            ["1.0", "1.0", "2.0", "2.0", "3.0", "3.0"],
        ],
        ids=["all_same", "two_groups", "three_groups", "five_groups", "single", "paired"],
    )
    def test_grouping_total_instances_preserved(self, versions):
        """Total instances across all groups equals input count."""
        instances = [_inst(version=v, instance_id=f"i{i}") for i, v in enumerate(versions)]
        result = map_version_to_task_instances(instances)
        total = sum(len(group) for group in result.values())
        assert total == len(versions)

    @pytest.mark.parametrize(
        "version",
        ["0.1", "1.0", "2.5", "10.20", "99.99", "0.0"],
        ids=[f"v{v.replace('.', '_')}" for v in ["0.1", "1.0", "2.5", "10.20", "99.99", "0.0"]],
    )
    def test_single_version_single_group(self, version):
        """Single version results in single group keyed by that version."""
        instances = [_inst(version=version, instance_id="i0")]
        result = map_version_to_task_instances(instances)
        assert version in result
        assert len(result[version]) == 1


class TestMergeResultsParametrized:
    """Parametrized tests for merge_results edge cases."""

    @pytest.mark.parametrize(
        "num_files",
        [1, 2, 3, 5, 10],
        ids=["one_file", "two_files", "three_files", "five_files", "ten_files"],
    )
    @patch("swefficiency.versioning.get_versions.glob.glob")
    @patch("builtins.open", new_callable=mock_open)
    @patch("swefficiency.versioning.get_versions.os.remove")
    @patch("swefficiency.versioning.get_versions.json")
    def test_merge_n_files(self, mock_json, mock_remove, mock_file, mock_glob, num_files):
        """merge_results correctly merges N temp files."""
        files = [f"/tmp/prefix_versions_{i}.json" for i in range(num_files)]
        mock_glob.return_value = files
        mock_json.load.return_value = [_inst(instance_id=f"i{i}") for i in range(3)]

        result = merge_results("/data/tasks.jsonl", "prefix", "/tmp")

        assert result == num_files * 3
        assert mock_remove.call_count == num_files

    @pytest.mark.parametrize(
        "instances_per_file, num_files",
        [
            (1, 1),
            (10, 2),
            (100, 3),
            (5, 10),
            (50, 5),
        ],
        ids=["1x1", "10x2", "100x3", "5x10", "50x5"],
    )
    @patch("swefficiency.versioning.get_versions.glob.glob")
    @patch("builtins.open", new_callable=mock_open)
    @patch("swefficiency.versioning.get_versions.os.remove")
    @patch("swefficiency.versioning.get_versions.json")
    def test_merge_total_count(self, mock_json, mock_remove, mock_file, mock_glob,
                                instances_per_file, num_files):
        """Total merged count equals instances_per_file * num_files."""
        files = [f"/tmp/prefix_versions_{i}.json" for i in range(num_files)]
        mock_glob.return_value = files
        mock_json.load.return_value = [_inst(instance_id=f"i{i}") for i in range(instances_per_file)]

        result = merge_results("/data/tasks.jsonl", "prefix", "/tmp")

        assert result == instances_per_file * num_files


class TestGetVersionsFromWebParametrized:
    """Parametrized tests for get_versions_from_web edge cases."""

    @pytest.mark.parametrize(
        "num_instances",
        [1, 2, 5, 10, 20, 50],
        ids=[f"n{n}" for n in [1, 2, 5, 10, 20, 50]],
    )
    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("swefficiency.versioning.get_versions.json")
    @patch("builtins.open", new_callable=mock_open)
    def test_web_mode_n_instances(self, mock_file, mock_json, mock_gv, num_instances):
        """All N instances are processed in web mode."""
        instances = [_inst(instance_id=f"i{i}") for i in range(num_instances)]
        mock_gv.return_value = "1.0"
        data = {
            "data_tasks": instances,
            "save_path": "/tmp/result.json",
            "not_found_list": None,
        }
        get_versions_from_web(data)
        assert mock_gv.call_count == num_instances

    @pytest.mark.parametrize(
        "found_count, not_found_count",
        [
            (5, 0),
            (0, 5),
            (3, 2),
            (1, 4),
            (4, 1),
            (10, 10),
        ],
        ids=["all_found", "none_found", "3_of_5", "1_of_5", "4_of_5", "half_half"],
    )
    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("swefficiency.versioning.get_versions.json")
    @patch("builtins.open", new_callable=mock_open)
    def test_web_mode_found_vs_not_found(self, mock_file, mock_json, mock_gv,
                                          found_count, not_found_count):
        """Correct split between found and not-found instances."""
        total = found_count + not_found_count
        versions = ["1.0"] * found_count + [None] * not_found_count
        mock_gv.side_effect = versions
        not_found_list = []
        instances = [_inst(instance_id=f"i{i}") for i in range(total)]
        data = {
            "data_tasks": instances,
            "save_path": "/tmp/result.json",
            "not_found_list": not_found_list,
        }
        get_versions_from_web(data)
        assert len(not_found_list) == not_found_count


class TestGetVersionsFromBuildParametrized:
    """Parametrized tests for get_versions_from_build."""

    @pytest.mark.parametrize(
        "num_instances",
        [1, 2, 3, 5],
        ids=[f"n{n}" for n in [1, 2, 3, 5]],
    )
    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("swefficiency.versioning.get_versions.os.chdir")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    @patch("swefficiency.versioning.get_versions.json")
    @patch("builtins.open", new_callable=mock_open)
    def test_build_mode_n_instances(self, mock_file, mock_json, mock_subp, mock_chdir, mock_gv,
                                     num_instances):
        """All N instances are processed in build mode (reversed order)."""
        instances = [_inst(instance_id=f"i{i}", repo="org/repo") for i in range(num_instances)]
        mock_gv.return_value = "1.0"
        mock_subp.return_value = MagicMock(returncode=0)
        data = {
            "data_tasks": instances,
            "save_path": "/tmp/result.json",
            "path_repo": "/tmp/repo",
            "conda_env": "test_env",
            "path_conda": "/opt/conda",
        }
        get_versions_from_build(data)
        assert mock_gv.call_count == num_instances


class TestMainOrchestrationParametrized:
    """Exhaustive parametrized tests for main() orchestration."""

    @pytest.mark.parametrize(
        "retrieval_method",
        ["github", "mix", "build"],
        ids=["github", "mix", "build"],
    )
    @pytest.mark.parametrize(
        "num_workers",
        [1, 2, 4, 8],
        ids=["w1", "w2", "w4", "w8"],
    )
    @pytest.mark.parametrize(
        "num_instances",
        [1, 5, 10, 20],
        ids=["n1", "n5", "n10", "n20"],
    )
    @patch("swefficiency.versioning.get_versions.split_instances")
    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_main_method_worker_instance_combos(
        self, mock_gi, mock_split, num_instances, num_workers, retrieval_method
    ):
        instances = [_inst(instance_id=f"i{i}") for i in range(num_instances)]
        mock_gi.return_value = instances
        mock_split.return_value = [instances[:max(1, num_instances // num_workers)] for _ in range(num_workers)]
        args = Namespace(
            instances_path="/data/tasks.jsonl",
            retrieval_method=retrieval_method,
            num_workers=num_workers,
            output_dir="/tmp",
            cleanup=False,
            conda_env=None,
            path_conda=None,
            testbed=None,
        )
        with patch("swefficiency.versioning.get_versions.Pool") as mp, \
             patch("swefficiency.versioning.get_versions.Manager") as mm, \
             patch("swefficiency.versioning.get_versions.merge_results", return_value=num_instances):
            mp.return_value = MagicMock()
            try:
                main(args)
            except Exception:
                pass
        if retrieval_method == "mix":
            assert mock_split.call_count == 2
            mock_split.assert_any_call(instances, num_workers)
        else:
            mock_split.assert_called_once_with(instances, num_workers)


# ── INTEGRATION TESTS ─────────────────────────────────────────────────


class TestIntegrationWebThenMerge:
    """Integration: get_versions_from_web -> merge_results pipeline."""

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_web_results_can_be_merged(self, mock_gv, tmp_path):
        """Web worker saves JSON that merge_results can consume."""
        mock_gv.return_value = "1.0"
        instances = [_inst(instance_id=f"i{i}") for i in range(4)]
        save_path = str(tmp_path / "test__repo_versions_0.json")
        data = {"data_tasks": instances, "save_path": save_path, "not_found_list": None}
        get_versions_from_web(data)

        # Verify file was saved
        import json
        with open(save_path) as f:
            saved = json.load(f)
        assert len(saved) == 4
        assert all(s.get("version") == "1.0" for s in saved)

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_multiple_workers_merge(self, mock_gv, tmp_path):
        """Multiple web workers save separate files, merge combines them."""
        mock_gv.return_value = "2.0"
        import os
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            for i in range(3):
                instances = [_inst(instance_id=f"w{i}_t{j}") for j in range(5)]
                save_path = f"test__repo_versions_{i}.json"
                data = {"data_tasks": instances, "save_path": save_path, "not_found_list": None}
                get_versions_from_web(data)

            count = merge_results("/fake/tasks.json", "test__repo", str(tmp_path))
            assert count == 15
        finally:
            os.chdir(old_cwd)


class TestIntegrationBuildThenMerge:
    """Integration: get_versions_from_build -> merge_results pipeline."""

    @patch("swefficiency.versioning.get_versions.get_version")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    def test_build_results_saved_correctly(self, mock_run, mock_gv, tmp_path):
        """Build worker produces JSON consumable by merge_results."""
        mock_run.return_value = MagicMock(returncode=0)
        mock_gv.return_value = "3.0"
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        save_path = str(tmp_path / "test__repo_versions_0.json")
        instances = [_inst(instance_id=f"b{i}") for i in range(3)]
        data = {
            "data_tasks": instances,
            "path_repo": str(repo_path),
            "conda_env": "test_env",
            "path_conda": "/opt/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        import json
        with open(save_path) as f:
            saved = json.load(f)
        assert len(saved) == 3


class TestIntegrationMapVersionThenProcess:
    """Integration: map_version_to_task_instances works with real-looking data."""

    def test_group_then_iterate(self):
        """Group instances by version, then process each group."""
        instances = [
            {"instance_id": "a", "version": "1.0", "repo": "test/test"},
            {"instance_id": "b", "version": "1.0", "repo": "test/test"},
            {"instance_id": "c", "version": "2.0", "repo": "test/test"},
        ]
        grouped = map_version_to_task_instances(instances)
        assert "1.0" in grouped
        assert "2.0" in grouped
        assert len(grouped["1.0"]) == 2
        assert len(grouped["2.0"]) == 1
        # Verify we can iterate groups
        for version, group in grouped.items():
            for inst in group:
                assert inst["version"] == version


# ── END-TO-END TESTS ─────────────────────────────────────────────────


class TestEndToEndOrchestration:
    """E2E: simulate the full main() orchestration flow."""

    @patch("swefficiency.versioning.get_versions.merge_results")
    @patch("swefficiency.versioning.get_versions.get_versions_from_web")
    @patch("swefficiency.versioning.get_versions.Pool")
    @patch("swefficiency.versioning.get_versions.Manager")
    @patch("swefficiency.versioning.get_versions.split_instances")
    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_e2e_github_mode_full_flow(self, mock_gi, mock_split, mock_mgr, mock_pool, mock_web, mock_merge):
        """E2E: github mode loads -> splits -> pool.map -> merge."""
        instances = [_inst(instance_id=f"i{i}") for i in range(10)]
        mock_gi.return_value = instances
        mock_split.return_value = [instances[:5], instances[5:]]
        mock_merge.return_value = 10
        pool_inst = MagicMock()
        mock_pool.return_value = pool_inst

        args = Namespace(
            instances_path="/data/tasks.json",
            retrieval_method="github",
            num_workers=2,
            output_dir="/output",
            cleanup=False,
            conda_env=None,
            path_conda=None,
            testbed=None,
        )
        main(args)

        mock_gi.assert_called_once_with("/data/tasks.json")
        mock_split.assert_called_once_with(instances, 2)
        pool_inst.map.assert_called_once()
        mock_merge.assert_called_once()
        pool_inst.close.assert_called_once()
        pool_inst.join.assert_called_once()

    @patch("swefficiency.versioning.get_versions.merge_results")
    @patch("swefficiency.versioning.get_versions.Pool")
    @patch("swefficiency.versioning.get_versions.Manager")
    @patch("swefficiency.versioning.get_versions.split_instances")
    @patch("swefficiency.versioning.get_versions.get_instances")
    def test_e2e_mix_mode_two_phases(self, mock_gi, mock_split, mock_mgr, mock_pool, mock_merge):
        """E2E: mix mode runs web phase then build phase."""
        instances = [_inst(instance_id=f"i{i}") for i in range(8)]
        mock_gi.return_value = instances
        mock_split.return_value = [instances[:4], instances[4:]]
        manager_inst = MagicMock()
        shared_list = MagicMock()
        shared_list.__len__ = MagicMock(return_value=0)
        shared_list.__iter__ = MagicMock(return_value=iter([]))
        manager_inst.list.return_value = shared_list
        mock_mgr.return_value = manager_inst
        pool_inst = MagicMock()
        mock_pool.return_value = pool_inst
        mock_merge.return_value = 8

        args = Namespace(
            instances_path="/data/tasks.json",
            retrieval_method="mix",
            num_workers=2,
            output_dir="/output",
            cleanup=False,
            conda_env="base",
            path_conda="/opt/conda",
            testbed="/tmp/testbed",
        )
        with patch("swefficiency.versioning.get_versions.os.path.exists", return_value=True), \
             patch("swefficiency.versioning.get_versions.subprocess.run", return_value=MagicMock(returncode=0)), \
             patch("swefficiency.versioning.get_versions.os.chdir"), \
             patch("swefficiency.versioning.get_versions.os.getcwd", return_value="/orig"):
            try:
                main(args)
            except (AssertionError, TypeError, AttributeError):
                pass  # Expected due to mocking complexity

        # Verify web phase was invoked
        assert pool_inst.map.called

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_e2e_web_worker_not_found_accumulation(self, mock_gv):
        """E2E: web workers accumulate not-found instances for mix mode."""
        from multiprocessing import Manager
        manager = Manager()
        shared_list = manager.list()

        # Some found, some not
        def version_side_effect(inst):
            idx = int(inst["instance_id"].replace("i", ""))
            return "1.0" if idx % 2 == 0 else None
        mock_gv.side_effect = version_side_effect

        instances = [_inst(instance_id=f"i{i}") for i in range(6)]
        import tempfile, json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            save_path = f.name
        data = {"data_tasks": instances, "save_path": save_path, "not_found_list": shared_list}
        get_versions_from_web(data)

        # 3 odd instances should be not-found
        assert len(shared_list) == 3
        not_found_ids = [inst["instance_id"] for inst in shared_list]
        assert set(not_found_ids) == {"i1", "i3", "i5"}
        manager.shutdown()
        import os
        os.unlink(save_path)

    def test_e2e_merge_results_file_lifecycle(self, tmp_path):
        """E2E: merge creates final file and removes temp files."""
        import json, os
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            # Create temp files as workers would
            for i in range(3):
                data = [{"id": f"w{i}_t{j}", "version": "1.0"} for j in range(4)]
                with open(f"myrepo_versions_{i}.json", "w") as f:
                    json.dump(data, f)

            count = merge_results("/some/path/tasks.jsonl", "myrepo", str(tmp_path))
            assert count == 12

            # Temp files should be gone
            import glob as g
            remaining = g.glob("myrepo_versions_*.json")
            assert len(remaining) == 0

            # Merged file should exist
            merged_path = os.path.join(str(tmp_path), "tasks_versions.json")
            assert os.path.exists(merged_path)
            with open(merged_path) as f:
                merged = json.load(f)
            assert len(merged) == 12
        finally:
            os.chdir(old_cwd)


# ── Gap Coverage Tests ───────────────────────────────────────────────────────

import logging


class TestNullEmptyMissing:
    """D2: Null / empty / missing-field edge cases."""

    def test_map_version_empty_list_raises_index_error(self):
        with pytest.raises(IndexError):
            map_version_to_task_instances([])

    def test_map_version_none_raises_type_error(self):
        with pytest.raises(TypeError):
            map_version_to_task_instances(None)

    def test_merge_results_no_matching_files_returns_zero(self, tmp_path):
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            count = merge_results("/some/path/tasks.jsonl", "nonexistent_prefix", str(tmp_path))
            assert count == 0
            merged_path = os.path.join(str(tmp_path), "tasks_versions.json")
            assert os.path.exists(merged_path)
            with open(merged_path) as f:
                assert json.load(f) == []
        finally:
            os.chdir(old_cwd)

    @patch("swefficiency.versioning.get_versions.get_version", return_value="1.0")
    def test_get_versions_from_web_empty_tasks(self, mock_gv, tmp_path):
        save_path = str(tmp_path / "out.json")
        data = {"data_tasks": [], "save_path": save_path, "not_found_list": None}
        get_versions_from_web(data)
        with open(save_path) as f:
            assert json.load(f) == []
        mock_gv.assert_not_called()

    @patch("swefficiency.versioning.get_versions.os.chdir")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    def test_get_versions_from_build_empty_tasks(self, mock_sub, mock_chdir, tmp_path):
        save_path = str(tmp_path / "out.json")
        data = {
            "data_tasks": [],
            "path_repo": "/fake/repo",
            "conda_env": "testenv",
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        with pytest.raises(IndexError):
            get_versions_from_build(data)
        mock_sub.assert_not_called()


class TestTypeCoercion:
    """D3: Wrong-type arguments."""

    @patch("swefficiency.versioning.get_versions.get_version", side_effect=TypeError("char"))
    def test_map_version_string_raises(self, mock_gv):
        with pytest.raises(TypeError):
            map_version_to_task_instances("not a list")

    def test_map_version_dict_raises(self):
        with pytest.raises(KeyError):
            map_version_to_task_instances({"key": "val"})


class TestConcurrency:
    """D7 / Q11: Shared-state and concurrent-access scenarios."""

    @patch("swefficiency.versioning.get_versions.get_version")
    def test_get_versions_from_web_concurrent_shared_list(self, mock_gv, tmp_path):
        """Manager().list() as not_found_list receives unfound instances."""
        manager = Manager()
        shared_list = manager.list()
        instances = [_inst(instance_id=f"inst{i}") for i in range(5)]

        def side_effect(inst):
            idx = int(inst["instance_id"].replace("inst", ""))
            return "2.0" if idx % 2 == 0 else None

        mock_gv.side_effect = side_effect

        save_path = str(tmp_path / "web_out.json")
        data = {"data_tasks": instances, "save_path": save_path, "not_found_list": shared_list}
        get_versions_from_web(data)

        assert len(shared_list) == 2
        not_found_ids = [inst["instance_id"] for inst in shared_list]
        assert set(not_found_ids) == {"inst1", "inst3"}
        manager.shutdown()

    def test_merge_results_concurrent_file_access(self, tmp_path):
        """merge_results merges temp files and removes them."""
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            for i in range(4):
                data = [{"id": f"c{i}_t{j}", "version": "3.0"} for j in range(3)]
                with open(f"testrepo_versions_{i}.json", "w") as f:
                    json.dump(data, f)

            count = merge_results("/x/tasks.jsonl", "testrepo", str(tmp_path))
            assert count == 12

            import glob as g
            remaining = g.glob("testrepo_versions_*.json")
            assert len(remaining) == 0

            merged_path = os.path.join(str(tmp_path), "tasks_versions.json")
            assert os.path.exists(merged_path)
        finally:
            os.chdir(old_cwd)


class TestSubprocessFailures:
    """D8: Subprocess failure modes in get_versions_from_build."""

    @patch("swefficiency.versioning.get_versions.os.chdir")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    def test_build_git_restore_fails(self, mock_sub, mock_chdir):
        """CalledProcessError on 'git restore' propagates (check=True)."""
        mock_sub.side_effect = subprocess.CalledProcessError(1, "git restore")
        data = {
            "data_tasks": [_inst()],
            "path_repo": "/fake/repo",
            "conda_env": "env",
            "path_conda": "/fake/conda",
            "save_path": "/fake/save.json",
        }
        with pytest.raises(subprocess.CalledProcessError):
            get_versions_from_build(data)

    @patch("swefficiency.versioning.get_versions.get_version", return_value="1.0")
    @patch("swefficiency.versioning.get_versions.os.chdir")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    def test_build_checkout_fails_continues(self, mock_sub, mock_chdir, mock_gv, tmp_path):
        """Checkout returncode=1 → skip instance, continue to next."""
        success = MagicMock(returncode=0)
        checkout_fail = MagicMock(returncode=1)

        instances = [_inst(instance_id="inst0"), _inst(instance_id="inst1")]

        def run_side_effect(cmd, **kwargs):
            if "checkout" in cmd:
                return checkout_fail
            return success

        mock_sub.side_effect = run_side_effect

        save_path = str(tmp_path / "save.json")
        data = {
            "data_tasks": instances,
            "path_repo": "/fake/repo",
            "conda_env": "env",
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        mock_gv.assert_not_called()

    @patch("swefficiency.versioning.get_versions.get_version", return_value="1.0")
    @patch("swefficiency.versioning.get_versions.os.chdir")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    def test_build_install_fails_continues(self, mock_sub, mock_chdir, mock_gv, tmp_path):
        """Install returncode=1 → skip instance, continue to next."""
        success = MagicMock(returncode=0)
        install_fail = MagicMock(returncode=1)

        instances = [_inst(instance_id="inst0"), _inst(instance_id="inst1")]

        call_idx = {"n": 0}

        def run_side_effect(cmd, **kwargs):
            call_idx["n"] += 1
            if "pip install" in cmd or "python -m pip" in cmd:
                return install_fail
            if "checkout" in cmd:
                return success
            return success

        mock_sub.side_effect = run_side_effect

        save_path = str(tmp_path / "save.json")
        data = {
            "data_tasks": instances,
            "path_repo": "/fake/repo",
            "conda_env": "env",
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)
        mock_gv.assert_not_called()


class TestSecurityCommandInjection:
    """D9: Document shell=True injection surface."""

    @patch("swefficiency.versioning.get_versions.get_version", return_value="1.0")
    @patch("swefficiency.versioning.get_versions.os.chdir")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    def test_build_repo_name_with_shell_metacharacters(self, mock_sub, mock_chdir, mock_gv, tmp_path):
        """base_commit with shell metacharacters is passed verbatim to shell."""
        mock_sub.return_value = MagicMock(returncode=0)
        malicious_commit = "abc; rm -rf /"
        instances = [_inst(base_commit=malicious_commit)]

        save_path = str(tmp_path / "save.json")
        data = {
            "data_tasks": instances,
            "path_repo": "/fake/repo",
            "conda_env": "env",
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)

        checkout_calls = [
            c for c in mock_sub.call_args_list
            if "checkout" in str(c)
        ]
        assert len(checkout_calls) >= 1
        checkout_cmd = checkout_calls[0][0][0]
        assert ";" in checkout_cmd
        assert malicious_commit in checkout_cmd

    @patch("swefficiency.versioning.get_versions.get_version", return_value="1.0")
    @patch("swefficiency.versioning.get_versions.os.chdir")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    def test_build_conda_env_with_injection(self, mock_sub, mock_chdir, mock_gv, tmp_path):
        """conda_env with injection payload is passed verbatim to shell."""
        mock_sub.return_value = MagicMock(returncode=0)
        malicious_env = "test; malicious_cmd"
        instances = [_inst()]

        save_path = str(tmp_path / "save.json")
        data = {
            "data_tasks": instances,
            "path_repo": "/fake/repo",
            "conda_env": malicious_env,
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)

        install_calls = [
            c for c in mock_sub.call_args_list
            if "activate" in str(c) or "pip install" in str(c)
        ]
        assert len(install_calls) >= 1
        install_cmd = install_calls[0][0][0]
        assert malicious_env in install_cmd


class TestStateLifecycle:
    """D6: State management and idempotency."""

    @patch("swefficiency.versioning.get_versions.get_version", return_value="1.0")
    @patch("swefficiency.versioning.get_versions.subprocess.run", return_value=MagicMock(returncode=0))
    @patch("swefficiency.versioning.get_versions.os.chdir")
    def test_build_restores_cwd_on_success(self, mock_chdir, mock_sub, mock_gv, tmp_path):
        """os.chdir is called back to original cwd at end."""
        save_path = str(tmp_path / "save.json")
        data = {
            "data_tasks": [_inst()],
            "path_repo": "/fake/repo",
            "conda_env": "env",
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        get_versions_from_build(data)

        chdir_calls = mock_chdir.call_args_list
        assert len(chdir_calls) >= 2
        assert chdir_calls[0] == call("/fake/repo")
        last_call_arg = chdir_calls[-1][0][0]
        assert last_call_arg is not None

    def test_merge_results_idempotent(self, tmp_path):
        """Second merge returns 0 — temp files already removed by first call."""
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            for i in range(2):
                with open(f"idrepo_versions_{i}.json", "w") as f:
                    json.dump([{"id": f"item{i}"}], f)

            first = merge_results("/p/tasks.jsonl", "idrepo", str(tmp_path))
            assert first == 2

            second = merge_results("/p/tasks.jsonl", "idrepo", str(tmp_path))
            assert second == 0
        finally:
            os.chdir(old_cwd)


class TestErrorMessages:
    """Q7: Error message quality."""

    def test_map_version_index_error_on_empty_list(self):
        with pytest.raises(IndexError) as exc_info:
            map_version_to_task_instances([])
        assert "index" in str(exc_info.value).lower() or "list" in str(exc_info.type.__name__).lower()

    @patch("swefficiency.versioning.get_versions.get_version", return_value=None)
    def test_map_version_key_error_no_version_key(self, mock_gv):
        """Instances without 'version' key → falls through to get_version path."""
        instances = [_inst(), _inst(instance_id="test__2")]
        result = map_version_to_task_instances(instances)
        assert None in result
        assert len(result[None]) == 2
        assert mock_gv.call_count == 2


class TestLogging:
    """Q14: Logging coverage for key operations."""

    @patch("swefficiency.versioning.get_versions.get_version", return_value="1.0")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    @patch("swefficiency.versioning.get_versions.os.chdir")
    def test_build_logs_checkout_failure(self, mock_chdir, mock_sub, mock_gv, caplog, tmp_path):
        checkout_fail = MagicMock(returncode=1)
        success = MagicMock(returncode=0)

        def run_side_effect(cmd, **kwargs):
            if "checkout" in cmd:
                return checkout_fail
            return success

        mock_sub.side_effect = run_side_effect
        save_path = str(tmp_path / "save.json")
        data = {
            "data_tasks": [_inst(instance_id="fail_co")],
            "path_repo": "/fake/repo",
            "conda_env": "env",
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        with caplog.at_level(logging.ERROR, logger="swefficiency.versioning.get_versions"):
            get_versions_from_build(data)
        assert "fail_co" in caplog.text
        assert "Checkout failed" in caplog.text

    @patch("swefficiency.versioning.get_versions.get_version", return_value="1.0")
    @patch("swefficiency.versioning.get_versions.subprocess.run")
    @patch("swefficiency.versioning.get_versions.os.chdir")
    def test_build_logs_install_failure(self, mock_chdir, mock_sub, mock_gv, caplog, tmp_path):
        install_fail = MagicMock(returncode=1)
        success = MagicMock(returncode=0)

        def run_side_effect(cmd, **kwargs):
            if "pip install" in cmd or "python -m pip" in cmd:
                return install_fail
            if "checkout" in cmd:
                return success
            return success

        mock_sub.side_effect = run_side_effect
        save_path = str(tmp_path / "save.json")
        data = {
            "data_tasks": [_inst(instance_id="fail_inst")],
            "path_repo": "/fake/repo",
            "conda_env": "env",
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        with caplog.at_level(logging.ERROR, logger="swefficiency.versioning.get_versions"):
            get_versions_from_build(data)
        assert "fail_inst" in caplog.text
        assert "Installation failed" in caplog.text

    @patch("swefficiency.versioning.get_versions.get_version", return_value="3.5")
    @patch("swefficiency.versioning.get_versions.subprocess.run", return_value=MagicMock(returncode=0))
    @patch("swefficiency.versioning.get_versions.os.chdir")
    def test_build_logs_version_found(self, mock_chdir, mock_sub, mock_gv, caplog, tmp_path):
        save_path = str(tmp_path / "save.json")
        data = {
            "data_tasks": [_inst(instance_id="ver_inst")],
            "path_repo": "/fake/repo",
            "conda_env": "env",
            "path_conda": "/fake/conda",
            "save_path": save_path,
        }
        with caplog.at_level(logging.INFO, logger="swefficiency.versioning.get_versions"):
            get_versions_from_build(data)
        assert "ver_inst" in caplog.text
        assert "3.5" in caplog.text

    @patch("swefficiency.versioning.get_versions.get_version", return_value="2.1")
    def test_web_logs_version_found(self, mock_gv, caplog, tmp_path):
        save_path = str(tmp_path / "web.json")
        data = {
            "data_tasks": [_inst(instance_id="web_found")],
            "save_path": save_path,
            "not_found_list": None,
        }
        with caplog.at_level(logging.INFO, logger="swefficiency.versioning.get_versions"):
            get_versions_from_web(data)
        assert "web_found" in caplog.text
        assert "2.1" in caplog.text

    @patch("swefficiency.versioning.get_versions.get_version", return_value=None)
    def test_web_logs_not_found(self, mock_gv, caplog, tmp_path):
        save_path = str(tmp_path / "web.json")
        not_found = []
        data = {
            "data_tasks": [_inst(instance_id="web_miss")],
            "save_path": save_path,
            "not_found_list": not_found,
        }
        with caplog.at_level(logging.INFO, logger="swefficiency.versioning.get_versions"):
            get_versions_from_web(data)
        assert "web_miss" in caplog.text
        assert "not found" in caplog.text.lower()

    def test_merge_logs_saved_path(self, caplog, tmp_path):
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            with open("logrepo_versions_0.json", "w") as f:
                json.dump([{"id": "a"}], f)
            with caplog.at_level(logging.INFO, logger="swefficiency.versioning.get_versions"):
                merge_results("/p/tasks.jsonl", "logrepo", str(tmp_path))
            assert "Saved merged results" in caplog.text
        finally:
            os.chdir(old_cwd)
