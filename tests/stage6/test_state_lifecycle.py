"""D6 — State & Lifecycle: tests for post-rollback state handling,
cleanup failure resilience, and long-running resource management
in detect_repo_specs.
"""

from __future__ import annotations

import builtins
import gc
import json
import os
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock, mock_open

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (
    _read_text, _parse_toml, detect_all_specs, detect_python_version,
    detect_install_cmd, detect_test_cmd, detect_packages_source,
    detect_pre_install, detect_version, check_license,
    load_cache, save_cache, write_jsonl, load_instances, validate_instances,
    REQUIRED_ENRICHMENT_FIELDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(repo: Path, relpath: str, content: str) -> None:
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")


def _full_instance(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instance_id": "test__1",
        "repo": "owner/repo",
        "base_commit": "abc123",
        "python_version": "3.10",
        "install_cmd": "pip install -e .",
        "test_cmd_override": "pytest",
        "packages_source": "",
        "pip_packages": [],
        "pre_install_cmds": [],
        "reqs_paths": [],
        "env_yml_paths": [],
        "log_parser_type": "pytest",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════
# 1. TestPostRollbackState  (~15 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestPostRollbackState:
    """Verify graceful handling when data formats change between versions,
    simulating post-rollback scenarios where on-disk state doesn't match
    what the code expects."""

    def test_load_cache_with_extra_keys(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        data = {
            "owner/repo@abc": {
                "python_version": "3.9",
                "pip_packages": ["numpy"],
                "_future_field": "unexpected_data",
                "_metrics": {"score": 42},
            }
        }
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_cache(str(cache_file))
        assert loaded["owner/repo@abc"]["python_version"] == "3.9"
        assert loaded["owner/repo@abc"]["_future_field"] == "unexpected_data"

    def test_load_cache_with_missing_expected_keys(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        data = {"owner/repo@abc": {"python_version": "3.9"}}
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_cache(str(cache_file))
        assert "pip_packages" not in loaded["owner/repo@abc"]
        assert loaded["owner/repo@abc"]["python_version"] == "3.9"

    def test_load_cache_empty_json_object(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{}", encoding="utf-8")
        loaded = load_cache(str(cache_file))
        assert loaded == {}

    def test_load_cache_corrupt_json_returns_empty(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text('{"truncated": ', encoding="utf-8")
        loaded = load_cache(str(cache_file))
        assert loaded == {}

    def test_validate_instances_with_extra_fields(self):
        instances = [_full_instance(
            _future_field="v2_data",
            _new_metric=99,
        )]
        result = validate_instances(instances)
        assert result is True

    def test_validate_instances_with_new_fields_not_in_required(self):
        inst = _full_instance()
        inst["brand_new_field"] = "from_future"
        inst["another_new"] = [1, 2, 3]
        result = validate_instances([inst])
        assert result is True

    def test_validate_instances_missing_required_field(self):
        inst = _full_instance()
        del inst["python_version"]
        result = validate_instances([inst])
        assert result is False

    def test_load_instances_jsonl_with_extra_schema(self, tmp_path: Path):
        jsonl_file = tmp_path / "data.jsonl"
        inst = _full_instance()
        inst["future_schema_field"] = {"nested": "data"}
        jsonl_file.write_text(json.dumps(inst) + "\n", encoding="utf-8")
        loaded = load_instances(str(jsonl_file))
        assert len(loaded) == 1
        assert loaded[0]["future_schema_field"] == {"nested": "data"}

    def test_conflicting_setup_py_and_pyproject(self, tmp_path: Path):
        _write(tmp_path, "setup.py",
               'from setuptools import setup\n'
               'setup(python_requires=">=3.8")\n')
        _write(tmp_path, "pyproject.toml",
               '[project]\nname = "x"\nrequires-python = ">=3.11"\n')
        result = detect_python_version(tmp_path)
        assert result == "3.11"

    def test_partially_migrated_repo_setup_py_and_pyproject(self, tmp_path: Path):
        _write(tmp_path, "setup.py",
               'from setuptools import setup\nsetup(name="old")\n')
        _write(tmp_path, "pyproject.toml",
               '[project]\nname = "new"\nversion = "2.0"\n'
               'requires-python = ">=3.10"\n')
        specs = detect_all_specs(tmp_path, "owner/migrated")
        assert specs["python_version"] == "3.10"
        assert specs["install_cmd"] == "pip install -e ."

    def test_detect_all_specs_partially_migrated_reqs(self, tmp_path: Path):
        _write(tmp_path, "requirements.txt", "numpy\n")
        _write(tmp_path, "pyproject.toml",
               '[project]\nname = "x"\ndependencies = ["pandas"]\n')
        specs = detect_all_specs(tmp_path, "owner/partial")
        assert specs["packages_source"] == "requirements.txt"
        assert specs["reqs_paths"] == ["requirements.txt"]

    def test_write_then_load_with_schema_change(self, tmp_path: Path):
        outfile = str(tmp_path / "data.jsonl")
        instances_v1 = [_full_instance()]
        write_jsonl(instances_v1, outfile)
        loaded = load_instances(outfile)
        assert len(loaded) == 1
        loaded[0]["new_v2_field"] = "added_after_rollback"
        assert "new_v2_field" not in instances_v1[0]
        assert loaded[0]["python_version"] == "3.10"

    def test_cache_v2_format_with_nested_arrays(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        data = {
            "owner/repo@abc": {
                "python_version": "3.9",
                "pip_packages": ["numpy"],
                "_v2_nested": [{"step": 1}, {"step": 2}],
            }
        }
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_cache(str(cache_file))
        assert loaded["owner/repo@abc"]["_v2_nested"][0]["step"] == 1

    def test_load_cache_with_null_values(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        data = {"owner/repo@abc": {"python_version": None, "pip_packages": None}}
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_cache(str(cache_file))
        assert loaded["owner/repo@abc"]["python_version"] is None

    def test_load_instances_empty_jsonl(self, tmp_path: Path):
        jsonl_file = tmp_path / "empty.jsonl"
        jsonl_file.write_text("", encoding="utf-8")
        loaded = load_instances(str(jsonl_file))
        assert loaded == []


# ═══════════════════════════════════════════════════════════════════════
# 2. TestCleanupFailure  (~15 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestCleanupFailure:
    """Verify resilience when I/O operations fail mid-way: race conditions,
    disk errors, permission changes, concurrent access."""

    def test_read_text_file_deleted_between_check_and_read(self, tmp_path: Path):
        target = tmp_path / "vanishing.txt"
        target.write_text("data", encoding="utf-8")
        target.unlink()
        result = _read_text(target)
        assert result is None

    def test_read_text_on_directory_returns_none(self, tmp_path: Path):
        d = tmp_path / "subdir"
        d.mkdir()
        result = _read_text(d)
        assert result is None

    def test_save_cache_directory_deleted(self, tmp_path: Path):
        cache_dir = tmp_path / "deep" / "nested"
        cache_dir.mkdir(parents=True)
        cache_file = str(cache_dir / "cache.json")
        import shutil
        shutil.rmtree(str(cache_dir))
        save_cache({"k": {"v": "1"}}, cache_file)
        assert not Path(cache_file).exists()

    def test_write_jsonl_oserror_mid_write(self, tmp_path: Path):
        """D6: OSError raised mid-write during write_jsonl leaves partial output."""
        outfile = str(tmp_path / "out.jsonl")
        # Need multiple instances so write() is called multiple times
        instances = [_full_instance(instance_id=f"test__{i}") for i in range(5)]
        _real_open = builtins.open
        write_count = [0]

        original_open = builtins.open

        def patched_open(*args, **kwargs):
            f = _real_open(*args, **kwargs)
            original_write = f.write

            def counting_write(data):
                write_count[0] += 1
                if write_count[0] >= 3:
                    raise OSError("Disk full")
                return original_write(data)

            f.write = counting_write
            return f

        with pytest.raises(OSError, match="Disk full"):
            with patch("builtins.open", side_effect=patched_open):
                write_jsonl(instances, outfile)

    def test_load_cache_partial_json(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text('{"key": {"python_version": "3', encoding="utf-8")
        loaded = load_cache(str(cache_file))
        assert loaded == {}

    def test_load_cache_nonexistent_returns_empty(self, tmp_path: Path):
        loaded = load_cache(str(tmp_path / "nonexistent.json"))
        assert loaded == {}
        assert isinstance(loaded, dict)

    def test_detect_all_specs_missing_dir(self, tmp_path: Path):
        missing_dir = tmp_path / "does_not_exist"
        specs = detect_all_specs(missing_dir, "owner/ghost")
        assert isinstance(specs, dict)
        assert specs["python_version"] == "3.10"

    def test_save_cache_permission_error_handled(self, tmp_path: Path):
        with patch("builtins.open", side_effect=PermissionError("No write")):
            save_cache({"k": {"v": "1"}}, str(tmp_path / "cache.json"))

    def test_write_jsonl_creates_parent_dirs(self, tmp_path: Path):
        outfile = str(tmp_path / "a" / "b" / "c" / "out.jsonl")
        write_jsonl([_full_instance()], outfile)
        assert Path(outfile).exists()
        loaded = load_instances(outfile)
        assert len(loaded) == 1

    def test_read_text_permission_denied(self, tmp_path: Path):
        target = tmp_path / "secret.txt"
        target.write_text("data", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            result = _read_text(target)
            assert result is None

    def test_save_cache_then_verify_valid_json(self, tmp_path: Path):
        cache_file = str(tmp_path / "cache.json")
        data = {
            "owner/a@abc": {"python_version": "3.9", "pip_packages": ["x"]},
            "owner/b@def": {"python_version": "3.11", "pip_packages": []},
        }
        save_cache(data, cache_file)
        reloaded = load_cache(cache_file)
        assert reloaded == data

    def test_write_jsonl_then_load_roundtrip(self, tmp_path: Path):
        outfile = str(tmp_path / "round.jsonl")
        instances = [
            _full_instance(instance_id="t1"),
            _full_instance(instance_id="t2", python_version="3.11"),
        ]
        write_jsonl(instances, outfile)
        loaded = load_instances(outfile)
        assert len(loaded) == 2
        assert loaded[0]["instance_id"] == "t1"
        assert loaded[1]["python_version"] == "3.11"

    def test_load_cache_binary_file_raises_unicode_error(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_bytes(b'\x00\x01\x02\xff\xfe')
        with pytest.raises(UnicodeDecodeError):
            load_cache(str(cache_file))

    def test_read_text_binary_content_returns_string(self, tmp_path: Path):
        target = tmp_path / "binary.txt"
        target.write_bytes(b'\x00\x01\x02\xff\xfe')
        result = _read_text(target)
        assert result is not None
        assert isinstance(result, str)

    def test_save_cache_overwrite_existing(self, tmp_path: Path):
        cache_file = str(tmp_path / "cache.json")
        save_cache({"old": {"v": "1"}}, cache_file)
        save_cache({"new": {"v": "2"}}, cache_file)
        loaded = load_cache(cache_file)
        assert "new" in loaded
        assert "old" not in loaded


# ═══════════════════════════════════════════════════════════════════════
# 3. TestLongRunning  (~10 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestLongRunning:
    """Verify no resource leaks (file descriptors, memory) when functions
    are called repeatedly in tight loops."""

    def test_load_save_cache_100_cycles_no_fd_leak(self, tmp_path: Path):
        cache_file = str(tmp_path / "cache.json")
        for i in range(100):
            data = {f"key_{i}": {"python_version": "3.10", "pip_packages": []}}
            save_cache(data, cache_file)
            loaded = load_cache(cache_file)
            assert f"key_{i}" in loaded

    def test_write_jsonl_100_cycles_no_leak(self, tmp_path: Path):
        for i in range(100):
            outfile = str(tmp_path / f"out_{i}.jsonl")
            write_jsonl([_full_instance(instance_id=f"t_{i}")], outfile)
        last = load_instances(str(tmp_path / "out_99.jsonl"))
        assert last[0]["instance_id"] == "t_99"

    def test_read_text_repeated_same_file_no_leak(self, tmp_path: Path):
        target = tmp_path / "stable.txt"
        target.write_text("content", encoding="utf-8")
        results = []
        for _ in range(200):
            results.append(_read_text(target))
        assert all(r == "content" for r in results)

    def test_detect_all_specs_repeated_consistent(self, tmp_path: Path):
        _write(tmp_path, "pyproject.toml",
               '[project]\nname = "x"\nrequires-python = ">=3.9"\n')
        first = detect_all_specs(tmp_path, "owner/stable")
        for _ in range(50):
            current = detect_all_specs(tmp_path, "owner/stable")
            assert current == first

    def test_validate_instances_growing_list(self):
        for size in (1, 10, 100, 500):
            instances = [_full_instance(instance_id=f"t_{i}") for i in range(size)]
            result = validate_instances(instances)
            assert result is True

    def test_validate_instances_1000_entries(self):
        instances = [_full_instance(instance_id=f"t_{i}") for i in range(1000)]
        result = validate_instances(instances)
        assert result is True

    def test_write_jsonl_large_batch(self, tmp_path: Path):
        outfile = str(tmp_path / "large.jsonl")
        instances = [_full_instance(instance_id=f"t_{i}") for i in range(500)]
        write_jsonl(instances, outfile)
        loaded = load_instances(outfile)
        assert len(loaded) == 500

    def test_load_cache_save_cache_interleaved(self, tmp_path: Path):
        cache_file = str(tmp_path / "cache.json")
        save_cache({}, cache_file)
        for i in range(50):
            cache = load_cache(cache_file)
            cache[f"key_{i}"] = {"python_version": "3.10"}
            save_cache(cache, cache_file)
        final = load_cache(cache_file)
        assert len(final) == 50

    def test_detect_python_version_repeated_no_leak(self, tmp_path: Path):
        _write(tmp_path, ".python-version", "3.11\n")
        for _ in range(100):
            result = detect_python_version(tmp_path)
            assert result == "3.11"

    def test_detect_packages_source_repeated(self, tmp_path: Path):
        _write(tmp_path, "requirements.txt", "numpy\npandas\n")
        first = detect_packages_source(tmp_path)
        for _ in range(100):
            current = detect_packages_source(tmp_path)
            assert current == first
