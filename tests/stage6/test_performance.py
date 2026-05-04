"""Dimension 11 — Performance / Resource Limits tests for detect_repo_specs.py.

Validates that detection functions handle large inputs, deep directory trees,
big datasets, adversarial regex patterns, and concurrent cache access without
crashing or exceeding reasonable time bounds.

No correctness checks — only resource handling and timing.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (  # noqa: E402
    _load_jsonl,
    _parse_min_python,
    _parse_toml,
    _parse_toml_regex,
    _read_text,
    check_license,
    detect_install_cmd,
    detect_packages_source,
    detect_pre_install,
    detect_python_version,
    detect_test_cmd,
    detect_version,
    load_cache,
    save_cache,
    validate_instances,
    write_jsonl,
)



def _timed(fn, *args, **kwargs) -> tuple[Any, float]:
    """Call *fn* and return (result, elapsed_seconds)."""
    t0 = time.monotonic()
    result = fn(*args, **kwargs)
    return result, time.monotonic() - t0


def _make_large_toml(tmp_path: Path, size_mb: float, *, name: str = "pyproject.toml") -> Path:
    """Create a pyproject.toml padded with comments to ~size_mb megabytes."""
    header = '[project]\nrequires-python = ">=3.9"\nversion = "1.0.0"\n'
    pad_line = "# " + "x" * 98 + "\n"
    lines_needed = int((size_mb * 1_048_576 - len(header)) / len(pad_line))
    p = tmp_path / name
    p.write_text(header + pad_line * lines_needed, encoding="utf-8")
    return p


def _full_instance(**overrides: Any) -> dict[str, Any]:
    base = {
        "instance_id": "perf__1",
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


# ===================================================================
# 1. TestLargeFileHandling (~20 cases)
# ===================================================================

class TestLargeFileHandling:
    """Verify detection functions complete on large files without crashing."""

    @pytest.mark.parametrize("size_mb", [1, 5, 10], ids=["1MB", "5MB", "10MB"])
    def test_parse_toml_large_file(self, tmp_path: Path, size_mb: float):
        p = _make_large_toml(tmp_path, size_mb)
        result, elapsed = _timed(_parse_toml, p)
        assert elapsed < 30

    @pytest.mark.parametrize("size_mb", [1, 5, 10], ids=["1MB", "5MB", "10MB"])
    def test_parse_toml_regex_large_file(self, tmp_path: Path, size_mb: float):
        p = _make_large_toml(tmp_path, size_mb)
        result, elapsed = _timed(_parse_toml_regex, p)
        assert elapsed < 30

    @pytest.mark.parametrize("size_mb", [1, 5, 10], ids=["1MB", "5MB", "10MB"])
    def test_detect_install_cmd_large_setup_py(self, tmp_path: Path, size_mb: float):
        p = tmp_path / "setup.py"
        header = "from setuptools import setup\nsetup(name='pkg')\n"
        pad = "# " + "p" * 98 + "\n"
        lines = int((size_mb * 1_048_576 - len(header)) / len(pad))
        p.write_text(header + pad * lines, encoding="utf-8")
        _, elapsed = _timed(detect_install_cmd, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("size_mb", [1, 5], ids=["1MB", "5MB"])
    def test_detect_python_version_large_setup_cfg(self, tmp_path: Path, size_mb: float):
        p = tmp_path / "setup.cfg"
        header = "[options]\npython_requires = >=3.9\n"
        pad = "# " + "c" * 98 + "\n"
        lines = int((size_mb * 1_048_576 - len(header)) / len(pad))
        p.write_text(header + pad * lines, encoding="utf-8")
        _, elapsed = _timed(detect_python_version, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("dep_count", [10000, 15000], ids=["10k-deps", "15k-deps"])
    def test_parse_toml_regex_many_deps(self, tmp_path: Path, dep_count: int):
        deps = ", ".join(f'"dep-{i}>=0.{i}"' for i in range(dep_count))
        content = f'[project]\ndependencies = [{deps}]\n'
        p = tmp_path / "pyproject.toml"
        p.write_text(content, encoding="utf-8")
        _, elapsed = _timed(_parse_toml_regex, p)
        assert elapsed < 30

    @pytest.mark.parametrize("ext_count", [1000, 2000], ids=["1k-exts", "2k-exts"])
    def test_detect_pre_install_many_ext_modules(self, tmp_path: Path, ext_count: int):
        lines = ["from setuptools import setup, Extension"]
        lines.append("ext_modules = [")
        for i in range(ext_count):
            lines.append(f"    Extension('mod{i}', ['mod{i}.c']),")
        lines.append("]")
        lines.append("setup(ext_modules=ext_modules)")
        p = tmp_path / "setup.py"
        p.write_text("\n".join(lines), encoding="utf-8")
        _, elapsed = _timed(detect_pre_install, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("size_mb", [1, 5], ids=["1MB", "5MB"])
    def test_read_text_large(self, tmp_path: Path, size_mb: float):
        p = tmp_path / "big.txt"
        p.write_text("a" * int(size_mb * 1_048_576), encoding="utf-8")
        _, elapsed = _timed(_read_text, p)
        assert elapsed < 30

    def test_detect_version_large_setup_py(self, tmp_path: Path):
        header = "from setuptools import setup\nsetup(version='9.8.7')\n"
        pad = "# " + "v" * 98 + "\n"
        lines = int((5 * 1_048_576 - len(header)) / len(pad))
        (tmp_path / "setup.py").write_text(header + pad * lines, encoding="utf-8")
        _, elapsed = _timed(detect_version, tmp_path, "owner/repo")
        assert elapsed < 30

    def test_detect_test_cmd_large_tox(self, tmp_path: Path):
        header = "[testenv]\ncommands = pytest {posargs}\n"
        pad = "# " + "t" * 98 + "\n"
        lines = int((2 * 1_048_576 - len(header)) / len(pad))
        (tmp_path / "tox.ini").write_text(header + pad * lines, encoding="utf-8")
        _, elapsed = _timed(detect_test_cmd, tmp_path)
        assert elapsed < 30


# ===================================================================
# 2. TestDeepDirectoryTrees (~15 cases)
# ===================================================================

class TestDeepDirectoryTrees:
    """Verify functions that scan directories handle deep trees gracefully."""

    @pytest.mark.parametrize("depth", [50, 100], ids=["50-deep", "100-deep"])
    def test_detect_pre_install_deep_fortran(self, tmp_path: Path, depth: int):
        """Fortran file buried *depth* levels deep — should NOT be detected
        (only top-level and one level deep scanned), but must not crash."""
        parts = [f"d{i}" for i in range(depth)]
        deep_dir = tmp_path.joinpath(*parts)
        deep_dir.mkdir(parents=True, exist_ok=True)
        (deep_dir / "solver.f90").write_text("! deep fortran", encoding="utf-8")
        _, elapsed = _timed(detect_pre_install, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("n_files", [1000, 5000, 10000],
                             ids=["1k-files", "5k-files", "10k-files"])
    def test_detect_pre_install_many_top_level_files(self, tmp_path: Path, n_files: int):
        """Many files at top level — verify detect_pre_install completes."""
        for i in range(n_files):
            (tmp_path / f"file_{i:05d}.py").write_text("# python", encoding="utf-8")
        _, elapsed = _timed(detect_pre_install, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("n_files", [1000, 5000],
                             ids=["1k-files", "5k-files"])
    def test_detect_packages_source_many_files(self, tmp_path: Path, n_files: int):
        """Many files at top level — verify detect_packages_source completes."""
        for i in range(n_files):
            (tmp_path / f"mod_{i:05d}.py").write_text("# mod", encoding="utf-8")
        _, elapsed = _timed(detect_packages_source, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("depth", [20, 50], ids=["20-deep", "50-deep"])
    def test_deep_requirements_dir(self, tmp_path: Path, depth: int):
        """Deeply nested requirements/ directory — function should still complete."""
        parts = ["requirements"] + [f"sub{i}" for i in range(depth)]
        deep = tmp_path.joinpath(*parts)
        deep.mkdir(parents=True, exist_ok=True)
        (deep / "base.txt").write_text("requests\n", encoding="utf-8")
        _, elapsed = _timed(detect_packages_source, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("n_files", [500, 2000],
                             ids=["500-files", "2k-files"])
    def test_detect_python_version_many_files(self, tmp_path: Path, n_files: int):
        """Many files at top level — detect_python_version must still complete."""
        for i in range(n_files):
            (tmp_path / f"src_{i:05d}.py").write_text("pass", encoding="utf-8")
        _, elapsed = _timed(detect_python_version, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("n_dirs", [200, 500],
                             ids=["200-dirs", "500-dirs"])
    def test_check_license_many_subdirs(self, tmp_path: Path, n_dirs: int):
        """Many subdirectories — check_license only reads specific files at root."""
        for i in range(n_dirs):
            (tmp_path / f"pkg_{i:04d}").mkdir()
        (tmp_path / "LICENSE").write_text("MIT License\n" * 10, encoding="utf-8")
        _, elapsed = _timed(check_license, tmp_path)
        assert elapsed < 30

    def test_detect_version_wide_repo(self, tmp_path: Path):
        """2000 top-level files — detect_version must complete."""
        for i in range(2000):
            (tmp_path / f"x_{i:05d}.txt").write_text("data", encoding="utf-8")
        _, elapsed = _timed(detect_version, tmp_path, "owner/repo")
        assert elapsed < 30


# ===================================================================
# 3. TestLargeDatasets (~20 cases)
# ===================================================================

class TestLargeDatasets:
    """Verify I/O functions handle large numbers of instances."""

    @pytest.mark.parametrize("count", [5000, 10000], ids=["5k", "10k"])
    def test_write_jsonl_large(self, tmp_path: Path, count: int):
        insts = [{"instance_id": f"inst_{i}", "val": i} for i in range(count)]
        p = tmp_path / "out.jsonl"
        _, elapsed = _timed(write_jsonl, insts, str(p))
        assert elapsed < 30
        assert p.exists()

    @pytest.mark.parametrize("count", [5000, 10000], ids=["5k", "10k"])
    def test_load_jsonl_large(self, tmp_path: Path, count: int):
        p = tmp_path / "data.jsonl"
        lines = [json.dumps({"id": i, "data": "x" * 100}) for i in range(count)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result, elapsed = _timed(_load_jsonl, p)
        assert elapsed < 30
        assert len(result) == count

    @pytest.mark.parametrize("count", [2000, 5000], ids=["2k", "5k"])
    def test_load_cache_large(self, tmp_path: Path, count: int):
        p = tmp_path / "cache.json"
        data = {f"repo_{i}@abc{i}": {"python_version": "3.10", "install_cmd": "pip install -e ."} for i in range(count)}
        p.write_text(json.dumps(data), encoding="utf-8")
        result, elapsed = _timed(load_cache, str(p))
        assert elapsed < 30
        assert len(result) == count

    @pytest.mark.parametrize("count", [2000, 5000], ids=["2k", "5k"])
    def test_save_cache_large(self, tmp_path: Path, count: int):
        p = tmp_path / "cache.json"
        data = {f"repo_{i}": {"specs": {"v": i}} for i in range(count)}
        _, elapsed = _timed(save_cache, data, str(p))
        assert elapsed < 30
        assert p.exists()

    @pytest.mark.parametrize("count", [2000, 5000], ids=["2k", "5k"])
    def test_save_load_cache_roundtrip_large(self, tmp_path: Path, count: int):
        p = tmp_path / "cache.json"
        data = {f"key_{i}": {"python_version": "3.9", "idx": i} for i in range(count)}
        save_cache(data, str(p))
        result, elapsed = _timed(load_cache, str(p))
        assert elapsed < 30
        assert len(result) == count

    @pytest.mark.parametrize("count", [5000, 10000], ids=["5k", "10k"])
    def test_validate_instances_large(self, tmp_path: Path, count: int):
        insts = [_full_instance(instance_id=f"perf__{i}") for i in range(count)]
        result, elapsed = _timed(validate_instances, insts)
        assert elapsed < 30
        assert result is True

    @pytest.mark.parametrize("count", [5000, 10000], ids=["5k", "10k"])
    def test_validate_instances_large_all_missing(self, tmp_path: Path, count: int):
        insts = [{"instance_id": f"bad__{i}"} for i in range(count)]
        result, elapsed = _timed(validate_instances, insts)
        assert elapsed < 30
        assert result is False

    @pytest.mark.parametrize("count", [5000, 10000], ids=["5k", "10k"])
    def test_write_read_roundtrip_large(self, tmp_path: Path, count: int):
        insts = [{"id": i, "payload": "y" * 200} for i in range(count)]
        p = tmp_path / "rt.jsonl"
        write_jsonl(insts, str(p))
        result, elapsed = _timed(_load_jsonl, p)
        assert elapsed < 30
        assert len(result) == count


# ===================================================================
# 4. TestRegexPerformance (~15 cases)
# ===================================================================

class TestRegexPerformance:
    """Verify regex-based functions don't exhibit catastrophic backtracking."""

    @pytest.mark.parametrize("length", [10000, 50000, 100000],
                             ids=["10k-chars", "50k-chars", "100k-chars"])
    def test_parse_min_python_long_spec(self, length: int):
        """Very long specifier string — _parse_min_python must not hang."""
        spec = ">=3.8," + ",".join(f"!=3.{i}.{j}" for i in range(100) for j in range(100))
        spec = spec[:length] if len(spec) >= length else spec + ",>=3.9" * (length // 6)
        _, elapsed = _timed(_parse_min_python, spec)
        assert elapsed < 10

    @pytest.mark.parametrize("pattern_name,content", [
        ("nested_brackets", '[build-system]\nrequires = [' + '"a",' * 5000 + '"z"]\n'),
        ("many_sections", "\n".join(f"[section_{i}]\nkey = \"val\"" for i in range(5000)) + '\n[build-system]\nrequires = ["setuptools"]\n'),
        ("repeated_project", ('[project]\n' + 'name = "x"\n') * 2000),
        ("long_inline_value", f'requires-python = "{">=3.8," * 5000}>=3.9"\n'),
        ("mixed_whitespace", '[build-system]\n' + 'requires \t = \t ["setuptools"]\n' + '  # padding\n' * 10000),
    ], ids=["nested-brackets", "many-sections", "repeated-project",
            "long-inline-value", "mixed-whitespace"])
    def test_parse_toml_regex_adversarial(self, tmp_path: Path, pattern_name: str, content: str):
        p = tmp_path / "pyproject.toml"
        p.write_text(content, encoding="utf-8")
        _, elapsed = _timed(_parse_toml_regex, p)
        assert elapsed < 30

    @pytest.mark.parametrize("size", [10000, 50000], ids=["10k", "50k"])
    def test_detect_python_version_huge_python_version_file(self, tmp_path: Path, size: int):
        """Huge .python-version file — detect_python_version must still complete."""
        content = "3.10\n" + "# comment line padding\n" * size
        (tmp_path / ".python-version").write_text(content, encoding="utf-8")
        _, elapsed = _timed(detect_python_version, tmp_path)
        assert elapsed < 10

    @pytest.mark.parametrize("size_mb", [1, 2], ids=["1MB", "2MB"])
    def test_check_license_large_license_file(self, tmp_path: Path, size_mb: float):
        """License file with 1MB+ of text — check_license must complete."""
        header = "MIT License\n\nPermission is hereby granted, free of charge, to any person...\n"
        pad = "Additional terms and conditions " * 100 + "\n"
        lines = int((size_mb * 1_048_576 - len(header)) / len(pad))
        (tmp_path / "LICENSE").write_text(header + pad * lines, encoding="utf-8")
        _, elapsed = _timed(check_license, tmp_path)
        assert elapsed < 30

    def test_parse_toml_regex_dotall_backtrack(self, tmp_path: Path):
        """Adversarial input targeting the re.DOTALL build-system regex:
        [build-system] followed by many lines before requires = [...].
        """
        filler = "\n".join(f"option_{i} = {i}" for i in range(5000))
        content = f'[build-system]\n{filler}\nrequires = ["setuptools"]\n'
        p = tmp_path / "pyproject.toml"
        p.write_text(content, encoding="utf-8")
        _, elapsed = _timed(_parse_toml_regex, p)
        assert elapsed < 30

    def test_parse_toml_regex_project_deps_backtrack(self, tmp_path: Path):
        """Adversarial input targeting the re.DOTALL [project] dependencies regex."""
        filler = "\n".join(f"field_{i} = \"value_{i}\"" for i in range(5000))
        content = f'[project]\n{filler}\ndependencies = ["numpy"]\n'
        p = tmp_path / "pyproject.toml"
        p.write_text(content, encoding="utf-8")
        _, elapsed = _timed(_parse_toml_regex, p)
        assert elapsed < 30

    def test_detect_python_version_large_setup_py_regex(self, tmp_path: Path):
        """Large setup.py — python_requires regex must not hang."""
        header = "python_requires='>=3.8'\n"
        pad = "# " + "r" * 98 + "\n"
        lines = int((3 * 1_048_576 - len(header)) / len(pad))
        (tmp_path / "setup.py").write_text(header + pad * lines, encoding="utf-8")
        _, elapsed = _timed(detect_python_version, tmp_path)
        assert elapsed < 30


# ===================================================================
# 5. TestConcurrentCacheAccess (~10 cases)
# ===================================================================

class TestConcurrentCacheAccess:
    """Verify save_cache / load_cache under concurrent threading pressure."""

    @pytest.mark.parametrize("n_threads", [2, 4, 8], ids=["2-threads", "4-threads", "8-threads"])
    def test_concurrent_save_cache(self, tmp_path: Path, n_threads: int):
        """Multiple threads calling save_cache simultaneously."""
        p = str(tmp_path / "cache.json")
        errors: list[Exception] = []

        def writer(tid: int):
            try:
                data = {f"repo_{tid}_{i}": {"v": i} for i in range(200)}
                save_cache(data, p)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        t0 = time.monotonic()
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)
        elapsed = time.monotonic() - t0

        assert elapsed < 30
        assert len(errors) == 0
        loaded = load_cache(p)
        assert isinstance(loaded, dict)

    @pytest.mark.parametrize("n_threads", [2, 4], ids=["2-threads", "4-threads"])
    def test_concurrent_load_while_save(self, tmp_path: Path, n_threads: int):
        """load_cache while save_cache is writing."""
        p = str(tmp_path / "cache.json")
        save_cache({"seed": {"v": 0}}, p)
        errors: list[Exception] = []

        def writer():
            try:
                for i in range(50):
                    save_cache({f"w_{i}": {"v": i}}, p)
            except Exception as exc:
                errors.append(exc)

        def reader():
            try:
                for _ in range(50):
                    load_cache(p)
            except Exception as exc:
                errors.append(exc)

        threads = []
        for _ in range(n_threads):
            threads.append(threading.Thread(target=writer))
            threads.append(threading.Thread(target=reader))

        t0 = time.monotonic()
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)
        elapsed = time.monotonic() - t0

        assert elapsed < 30
        assert len(errors) == 0

    def test_concurrent_save_then_load(self, tmp_path: Path):
        """Save from multiple threads, then verify load works."""
        results: dict[int, str] = {}
        p_template = str(tmp_path / "cache_{}.json")
        errors: list[Exception] = []

        def worker(tid: int):
            try:
                p = p_template.format(tid)
                data = {f"repo_{tid}": {"tid": tid}}
                save_cache(data, p)
                loaded = load_cache(p)
                results[tid] = loaded
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        t0 = time.monotonic()
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)
        elapsed = time.monotonic() - t0

        assert elapsed < 30
        assert len(errors) == 0
        assert len(results) == 8

    def test_concurrent_write_jsonl(self, tmp_path: Path):
        """Multiple threads writing different JSONL files concurrently."""
        errors: list[Exception] = []

        def writer(tid: int):
            try:
                insts = [{"tid": tid, "i": i} for i in range(500)]
                write_jsonl(insts, str(tmp_path / f"out_{tid}.jsonl"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(6)]
        t0 = time.monotonic()
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)
        elapsed = time.monotonic() - t0

        assert elapsed < 30
        assert len(errors) == 0
        for t in range(6):
            assert (tmp_path / f"out_{t}.jsonl").exists()

    def test_concurrent_validate(self, tmp_path: Path):
        """Multiple threads validating instances concurrently."""
        insts = [_full_instance(instance_id=f"cv__{i}") for i in range(2000)]
        errors: list[Exception] = []
        results: list[bool] = []
        lock = threading.Lock()

        def validator():
            try:
                r = validate_instances(insts)
                with lock:
                    results.append(r)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=validator) for _ in range(4)]
        t0 = time.monotonic()
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)
        elapsed = time.monotonic() - t0

        assert elapsed < 30
        assert len(errors) == 0
        assert all(r is True for r in results)


# ===================================================================
# 6. Additional edge-case performance tests
# ===================================================================

class TestAdditionalPerformance:

    @pytest.mark.parametrize("n_license_files", [50, 100],
                             ids=["50-license-files", "100-license-files"])
    def test_check_license_many_candidate_files(self, tmp_path: Path, n_license_files: int):
        """Many unrelated files named close to LICENSE — should still complete fast."""
        for i in range(n_license_files):
            (tmp_path / f"LICENSE_{i}.bak").write_text("not a license\n" * 100, encoding="utf-8")
        (tmp_path / "LICENSE").write_text("MIT License\nPermission is hereby granted...\n", encoding="utf-8")
        _, elapsed = _timed(check_license, tmp_path)
        assert elapsed < 10

    @pytest.mark.parametrize("n_req_files", [100, 500],
                             ids=["100-req-files", "500-req-files"])
    def test_detect_packages_source_many_req_files(self, tmp_path: Path, n_req_files: int):
        reqs_dir = tmp_path / "requirements"
        reqs_dir.mkdir()
        for i in range(n_req_files):
            (reqs_dir / f"req_{i:04d}.txt").write_text(f"pkg-{i}\n", encoding="utf-8")
        _, elapsed = _timed(detect_packages_source, tmp_path)
        assert elapsed < 30

    @pytest.mark.parametrize("size_kb", [100, 500], ids=["100KB", "500KB"])
    def test_detect_install_cmd_large_pyproject(self, tmp_path: Path, size_kb: int):
        header = '[build-system]\nrequires = ["setuptools"]\n[project]\nname = "pkg"\n'
        pad = "# " + "z" * 98 + "\n"
        lines = int((size_kb * 1024 - len(header)) / len(pad))
        (tmp_path / "pyproject.toml").write_text(header + pad * lines, encoding="utf-8")
        _, elapsed = _timed(detect_install_cmd, tmp_path)
        assert elapsed < 10

    def test_detect_all_detection_functions_empty_large_repo(self, tmp_path: Path):
        """Run every detect function on a repo with 5000 unrelated files."""
        for i in range(5000):
            (tmp_path / f"file_{i:05d}.dat").write_text("data", encoding="utf-8")
        funcs_and_args = [
            (detect_python_version, (tmp_path,)),
            (detect_install_cmd, (tmp_path,)),
            (detect_test_cmd, (tmp_path,)),
            (detect_packages_source, (tmp_path,)),
            (detect_pre_install, (tmp_path,)),
            (detect_version, (tmp_path, "owner/repo")),
            (check_license, (tmp_path,)),
        ]
        for fn, args in funcs_and_args:
            _, elapsed = _timed(fn, *args)
            assert elapsed < 10

    @pytest.mark.parametrize("line_count", [50000, 100000],
                             ids=["50k-lines", "100k-lines"])
    def test_load_jsonl_many_lines(self, tmp_path: Path, line_count: int):
        p = tmp_path / "big.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for i in range(line_count):
                f.write(json.dumps({"i": i}) + "\n")
        _, elapsed = _timed(_load_jsonl, p)
        assert elapsed < 30

    @pytest.mark.parametrize("payload_kb", [10, 50], ids=["10KB-payload", "50KB-payload"])
    def test_write_jsonl_large_payloads(self, tmp_path: Path, payload_kb: int):
        insts = [{"id": i, "blob": "x" * (payload_kb * 1024)} for i in range(100)]
        p = tmp_path / "big_payload.jsonl"
        _, elapsed = _timed(write_jsonl, insts, str(p))
        assert elapsed < 30

    def test_save_cache_deeply_nested_values(self, tmp_path: Path):
        """Cache with deeply nested dict values."""
        def _nest(depth: int) -> dict:
            if depth == 0:
                return {"leaf": True}
            return {"level": _nest(depth - 1)}
        data = {f"key_{i}": _nest(50) for i in range(100)}
        p = str(tmp_path / "deep_cache.json")
        _, elapsed = _timed(save_cache, data, p)
        assert elapsed < 10
        loaded, elapsed2 = _timed(load_cache, p)
        assert elapsed2 < 10
        assert len(loaded) == 100
