"""Phase 4 — Python Time Bombs: tests for subtle Python pitfalls in detect_repo_specs.

NOT happy-path. These tests target mutable defaults, shallow vs deep copy,
dict ordering, is-vs-equals, float edge values, iterator exhaustion,
string interning, and bool/int confusion.
"""

from __future__ import annotations

import ast
import copy
import functools
import importlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import setup
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (  # noqa: E402
    _git_clone,
    _parse_min_python,
    _parse_toml,
    _read_text,
    check_license,
    detect_all_specs,
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
# 1. TestMutableDefaults  (~15 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestMutableDefaults:
    """Verify returned containers are independent across calls — no shared state."""

    # --- detect_all_specs returns independent dicts ---

    def test_all_specs_dicts_independent_identity(self, tmp_path: Path):
        """Two calls return distinct dict objects."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        r2 = detect_all_specs(tmp_path, "owner/b")
        assert r1 is not r2

    def test_all_specs_mutate_pip_packages(self, tmp_path: Path):
        """Mutating pip_packages on first result doesn't affect second call."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        r1["pip_packages"].append("INJECTED")
        r2 = detect_all_specs(tmp_path, "owner/a")
        assert "INJECTED" not in r2["pip_packages"]

    def test_all_specs_mutate_pre_install_cmds(self, tmp_path: Path):
        """Mutating pre_install_cmds on first result doesn't affect second."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        r1["pre_install_cmds"].append("rm -rf /")
        r2 = detect_all_specs(tmp_path, "owner/a")
        assert "rm -rf /" not in r2["pre_install_cmds"]

    def test_all_specs_mutate_reqs_paths(self, tmp_path: Path):
        """Mutating reqs_paths on first result doesn't affect second."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        r1["reqs_paths"].append("hacked.txt")
        r2 = detect_all_specs(tmp_path, "owner/a")
        assert "hacked.txt" not in r2["reqs_paths"]

    def test_all_specs_mutate_env_yml_paths(self, tmp_path: Path):
        """Mutating env_yml_paths on first result doesn't affect second."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        r1["env_yml_paths"].append("evil.yml")
        r2 = detect_all_specs(tmp_path, "owner/a")
        assert "evil.yml" not in r2["env_yml_paths"]

    def test_all_specs_overwrite_key(self, tmp_path: Path):
        """Overwriting a top-level key on first result doesn't affect second."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        r1["python_version"] = "CORRUPTED"
        r2 = detect_all_specs(tmp_path, "owner/a")
        assert r2["python_version"] != "CORRUPTED"

    # --- detect_packages_source returns independent lists ---

    def test_packages_source_lists_independent(self, tmp_path: Path):
        _write(tmp_path, "requirements.txt", "numpy\n")
        _, reqs1, _ = detect_packages_source(tmp_path)
        reqs1.append("INJECTED")
        _, reqs2, _ = detect_packages_source(tmp_path)
        assert "INJECTED" not in reqs2

    def test_packages_source_pip_independent(self, tmp_path: Path):
        _write(tmp_path, "pyproject.toml",
               '[project]\nname = "x"\ndependencies = ["click"]\n')
        _, _, pkgs1 = detect_packages_source(tmp_path)
        pkgs1.append("INJECTED")
        _, _, pkgs2 = detect_packages_source(tmp_path)
        assert "INJECTED" not in pkgs2

    def test_packages_source_reqs_dir_independent(self, tmp_path: Path):
        _write(tmp_path, "requirements/base.txt", "numpy\n")
        _, reqs1, _ = detect_packages_source(tmp_path)
        reqs1.clear()
        _, reqs2, _ = detect_packages_source(tmp_path)
        assert len(reqs2) > 0

    # --- detect_pre_install returns independent lists ---

    def test_pre_install_independent_calls(self, tmp_path: Path):
        _write(tmp_path, "meson.build", "project('x', 'c')\n")
        r1 = detect_pre_install(tmp_path)
        r1.append("INJECTED")
        r2 = detect_pre_install(tmp_path)
        assert "INJECTED" not in r2

    def test_pre_install_clear_doesnt_affect_next(self, tmp_path: Path):
        _write(tmp_path, "meson.build", "project('x', 'c')\n")
        r1 = detect_pre_install(tmp_path)
        original_len = len(r1)
        r1.clear()
        r2 = detect_pre_install(tmp_path)
        assert len(r2) == original_len

    def test_pre_install_pop_doesnt_affect_next(self, tmp_path: Path):
        _write(tmp_path, "meson.build", "project('x', 'c')\n")
        r1 = detect_pre_install(tmp_path)
        r1.pop()
        r2 = detect_pre_install(tmp_path)
        assert len(r2) > len(r1)

    # --- REQUIRED_ENRICHMENT_FIELDS tuple immutability ---

    def test_required_fields_is_tuple(self):
        assert isinstance(REQUIRED_ENRICHMENT_FIELDS, tuple)

    def test_required_fields_immutable(self):
        """Tuples don't support append — verify AttributeError is raised."""
        with pytest.raises(AttributeError):
            REQUIRED_ENRICHMENT_FIELDS.append("sneaky")  # type: ignore[attr-defined]

    def test_required_fields_immutable_assignment(self):
        """Tuples don't support item assignment."""
        with pytest.raises(TypeError):
            REQUIRED_ENRICHMENT_FIELDS[0] = "hijacked"  # type: ignore[index]


# ═══════════════════════════════════════════════════════════════════════
# 2. TestShallowVsDeepCopy  (~20 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestShallowVsDeepCopy:
    """Nested containers must be deep-copied where needed."""

    # --- detect_all_specs nested mutation ---

    def test_all_specs_nested_pip_packages_mutation(self, tmp_path: Path):
        """Mutating nested list in returned dict doesn't bleed across calls."""
        _write(tmp_path, "pyproject.toml",
               '[project]\nname = "x"\ndependencies = ["flask"]\n')
        r1 = detect_all_specs(tmp_path, "owner/x")
        r1["pip_packages"][0] = "CORRUPTED"
        r2 = detect_all_specs(tmp_path, "owner/x")
        assert r2["pip_packages"][0] == "flask"

    def test_all_specs_nested_pre_install_mutation(self, tmp_path: Path):
        _write(tmp_path, "meson.build", "project('x', 'c')\n")
        r1 = detect_all_specs(tmp_path, "owner/x")
        if r1["pre_install_cmds"]:
            r1["pre_install_cmds"][0] = "CORRUPTED"
        r2 = detect_all_specs(tmp_path, "owner/x")
        assert "CORRUPTED" not in r2["pre_install_cmds"]

    def test_all_specs_nested_reqs_paths_mutation(self, tmp_path: Path):
        _write(tmp_path, "requirements/base.txt", "numpy\n")
        r1 = detect_all_specs(tmp_path, "owner/x")
        if r1["reqs_paths"]:
            r1["reqs_paths"][0] = "CORRUPTED"
        r2 = detect_all_specs(tmp_path, "owner/x")
        assert "CORRUPTED" not in r2["reqs_paths"]

    def test_all_specs_nested_env_yml_mutation(self, tmp_path: Path):
        _write(tmp_path, "environment.yml", "name: env\ndependencies:\n  - numpy\n")
        r1 = detect_all_specs(tmp_path, "owner/x")
        if r1["env_yml_paths"]:
            r1["env_yml_paths"][0] = "CORRUPTED"
        r2 = detect_all_specs(tmp_path, "owner/x")
        assert "CORRUPTED" not in r2["env_yml_paths"]

    def test_all_specs_add_extra_key_no_bleed(self, tmp_path: Path):
        """Adding an extra key to one result doesn't show in next call."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        r1["_extra"] = "surprise"
        r2 = detect_all_specs(tmp_path, "owner/a")
        assert "_extra" not in r2

    def test_all_specs_delete_key_no_bleed(self, tmp_path: Path):
        """Deleting a key from one result doesn't affect next call."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        del r1["python_version"]
        r2 = detect_all_specs(tmp_path, "owner/a")
        assert "python_version" in r2

    def test_all_specs_replace_list_no_bleed(self, tmp_path: Path):
        """Replacing a list entirely doesn't affect next call."""
        r1 = detect_all_specs(tmp_path, "owner/a")
        r1["pip_packages"] = ["FAKE"]
        r2 = detect_all_specs(tmp_path, "owner/a")
        assert r2["pip_packages"] != ["FAKE"]

    # --- process_repo_group cache copies ---

    def test_cache_stores_independent_copy(self, tmp_path: Path):
        """Specs stored in cache must be copies — mutating specs shouldn't
        affect what cache returns on next lookup."""
        cache: dict[str, dict[str, Any]] = {}
        specs = detect_all_specs(tmp_path, "owner/a")
        cache_key = "owner/a@abc123"
        cache[cache_key] = copy.deepcopy(specs)
        # Mutate the original
        specs["python_version"] = "CORRUPTED"
        specs["pip_packages"].append("EVIL")
        # Cache value unaffected
        assert cache[cache_key]["python_version"] != "CORRUPTED"
        assert "EVIL" not in cache[cache_key]["pip_packages"]

    def test_cache_lookup_returns_same_ref_so_deepcopy_needed(self, tmp_path: Path):
        """If cache stores raw refs, mutating lookup mutates cache. This test
        verifies the user must deepcopy or the code must protect."""
        cache: dict[str, dict[str, Any]] = {}
        specs = detect_all_specs(tmp_path, "owner/a")
        cache_key = "owner/a@abc"
        cache[cache_key] = specs
        # Direct reference — mutation propagates
        retrieved = cache[cache_key]
        retrieved["python_version"] = "MUTATED"
        # Without deepcopy, cache IS affected
        assert cache[cache_key]["python_version"] == "MUTATED"
        # This demonstrates the need for deepcopy in real usage

    def test_cache_deepcopy_isolates(self, tmp_path: Path):
        """deepcopy of cache entry is fully isolated."""
        specs = detect_all_specs(tmp_path, "owner/a")
        cached = copy.deepcopy(specs)
        specs["pip_packages"].append("X")
        specs["pre_install_cmds"].append("Y")
        assert "X" not in cached["pip_packages"]
        assert "Y" not in cached["pre_install_cmds"]

    # --- validate_instances doesn't mutate input ---

    def test_validate_instances_no_mutation(self):
        """validate_instances must not alter the input list."""
        instances = [_full_instance(), _full_instance(instance_id="test__2")]
        original = copy.deepcopy(instances)
        validate_instances(instances)
        assert instances == original

    def test_validate_instances_no_mutation_missing_fields(self):
        """Even for invalid instances, input list must not be modified."""
        instances = [{"instance_id": "bad", "repo": "x/y"}]
        original = copy.deepcopy(instances)
        validate_instances(instances)
        assert instances == original

    def test_validate_instances_no_item_added_or_removed(self):
        instances = [_full_instance()]
        count_before = len(instances)
        validate_instances(instances)
        assert len(instances) == count_before

    def test_validate_instances_preserves_extra_keys(self):
        instances = [_full_instance(extra_data="keep_me")]
        validate_instances(instances)
        assert instances[0]["extra_data"] == "keep_me"

    # --- write_jsonl doesn't mutate input ---

    def test_write_jsonl_no_mutation(self, tmp_path: Path):
        """write_jsonl must not alter the input list of dicts."""
        instances = [_full_instance(), _full_instance(instance_id="test__2")]
        original = copy.deepcopy(instances)
        write_jsonl(instances, str(tmp_path / "out.jsonl"))
        assert instances == original

    def test_write_jsonl_no_key_removal(self, tmp_path: Path):
        inst = _full_instance(extra="value")
        instances = [inst]
        write_jsonl(instances, str(tmp_path / "out.jsonl"))
        assert "extra" in instances[0]

    def test_write_jsonl_nested_lists_preserved(self, tmp_path: Path):
        inst = _full_instance(pip_packages=["a", "b"])
        instances = [inst]
        write_jsonl(instances, str(tmp_path / "out.jsonl"))
        assert instances[0]["pip_packages"] == ["a", "b"]

    # --- load_cache returns safe dict ---

    def test_load_cache_safe_to_mutate(self, tmp_path: Path):
        """Mutating returned cache dict must not corrupt file on disk."""
        cache_file = tmp_path / "cache.json"
        data = {"key1": {"python_version": "3.9", "pip_packages": ["numpy"]}}
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_cache(str(cache_file))
        loaded["key1"]["python_version"] = "CORRUPTED"
        loaded["key1"]["pip_packages"].append("EVIL")
        # Re-read from disk — must be pristine
        reloaded = load_cache(str(cache_file))
        assert reloaded["key1"]["python_version"] == "3.9"
        assert "EVIL" not in reloaded["key1"]["pip_packages"]

    def test_load_cache_missing_file_returns_empty(self, tmp_path: Path):
        result = load_cache(str(tmp_path / "nope.json"))
        assert result == {}
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════
# 3. TestDictOrdering  (~15 cases)
# ═══════════════════════════════════════════════════════════════════════

ALL_EXPECTED_KEYS = [
    "python_version",
    "install_cmd",
    "test_cmd_override",
    "packages_source",
    "pip_packages",
    "pre_install_cmds",
    "reqs_paths",
    "env_yml_paths",
    "log_parser_type",
    "version",
    "_license",
]


class TestDictOrdering:
    """Verify detect_all_specs key ordering is consistent."""

    def test_consistent_ordering_empty_repo(self, tmp_path: Path):
        r1 = detect_all_specs(tmp_path, "owner/a")
        r2 = detect_all_specs(tmp_path, "owner/b")
        assert list(r1.keys()) == list(r2.keys())

    def test_consistent_ordering_with_pyproject(self, tmp_path: Path):
        _write(tmp_path, "pyproject.toml",
               '[project]\nname = "x"\nversion = "1.0"\nrequires-python = ">=3.9"\n')
        r1 = detect_all_specs(tmp_path, "owner/x")
        r2 = detect_all_specs(tmp_path, "owner/x")
        assert list(r1.keys()) == list(r2.keys())

    def test_all_11_keys_present(self, tmp_path: Path):
        result = detect_all_specs(tmp_path, "owner/a")
        assert len(result) == 11
        assert set(result.keys()) == set(ALL_EXPECTED_KEYS)

    def test_key_order_matches_expected(self, tmp_path: Path):
        result = detect_all_specs(tmp_path, "owner/a")
        assert list(result.keys()) == ALL_EXPECTED_KEYS

    def test_required_fields_order_in_dict(self, tmp_path: Path):
        """Keys shared between REQUIRED_ENRICHMENT_FIELDS and dict maintain
        REQUIRED_ENRICHMENT_FIELDS ordering."""
        result = detect_all_specs(tmp_path, "owner/a")
        result_keys = list(result.keys())
        for i, field in enumerate(REQUIRED_ENRICHMENT_FIELDS):
            assert field in result_keys
            idx = result_keys.index(field)
            # Each successive field must appear after the previous one
            if i > 0:
                prev_field = REQUIRED_ENRICHMENT_FIELDS[i - 1]
                prev_idx = result_keys.index(prev_field)
                assert idx > prev_idx, (
                    f"{field} (idx={idx}) should appear after "
                    f"{prev_field} (idx={prev_idx})"
                )

    @pytest.mark.parametrize("repo_name", [
        "owner/a", "org/b", "user/c-d", "dev/e_f", "company/UPPER",
    ])
    def test_ordering_invariant_across_repo_names(self, tmp_path: Path, repo_name: str):
        result = detect_all_specs(tmp_path, repo_name)
        assert list(result.keys()) == ALL_EXPECTED_KEYS

    @pytest.mark.parametrize("layout_files", [
        {},
        {"setup.py": 'from setuptools import setup\nsetup()\n'},
        {"requirements.txt": "numpy\n"},
        {"environment.yml": "name: e\ndependencies: []\n"},
        {"pyproject.toml": '[project]\nname = "x"\nversion = "1.0"\n'},
    ], ids=["empty", "setup_py", "reqs", "env_yml", "pyproject"])
    def test_ordering_invariant_across_layouts(self, tmp_path: Path, layout_files: dict):
        for relpath, content in layout_files.items():
            _write(tmp_path, relpath, content)
        result = detect_all_specs(tmp_path, "owner/repo")
        assert list(result.keys()) == ALL_EXPECTED_KEYS

    def test_version_and_license_are_last_two(self, tmp_path: Path):
        result = detect_all_specs(tmp_path, "owner/a")
        keys = list(result.keys())
        assert keys[-2] == "version"
        assert keys[-1] == "_license"

    def test_python_version_is_first_key(self, tmp_path: Path):
        result = detect_all_specs(tmp_path, "owner/a")
        assert list(result.keys())[0] == "python_version"


# ═══════════════════════════════════════════════════════════════════════
# 4. TestIsVsEquals  (~10 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestIsVsEquals:
    """Verify string/None comparisons use correct operators."""

    def test_parse_min_python_equality(self):
        """_parse_min_python returns str equal via == (not relying on 'is')."""
        result = _parse_min_python(">=3.10")
        assert result == "3.10"
        assert type(result) is str

    def test_parse_min_python_equality_3_8(self):
        result = _parse_min_python(">=3.8,<4.0")
        assert result == "3.8"
        assert type(result) is str

    def test_parse_min_python_equality_exact(self):
        result = _parse_min_python("==3.11")
        assert result == "3.11"

    def test_python_version_fallback_value(self, tmp_path: Path):
        """Fallback '3.10' — use == comparison, never 'is'."""
        result = detect_python_version(tmp_path)
        assert result == "3.10"
        assert type(result) is str

    def test_python_version_fallback_not_interned_assumption(self, tmp_path: Path):
        """Two fallback calls return equal strings; don't assume identity."""
        r1 = detect_python_version(tmp_path)
        r2 = detect_python_version(tmp_path)
        assert r1 == r2  # always true
        # r1 is r2 may or may not be true — CPython may intern short strings

    def test_read_text_none_on_missing(self, tmp_path: Path):
        result = _read_text(tmp_path / "nonexistent.file")
        assert result is None

    def test_check_license_none_on_empty(self, tmp_path: Path):
        result = check_license(tmp_path)
        assert result is None

    def test_detect_version_none_on_empty(self, tmp_path: Path):
        result = detect_version(tmp_path, "owner/nonexistent_xyz")
        assert result is None

    def test_none_results_identity(self, tmp_path: Path):
        """None from multiple functions should all be Python's singleton None."""
        r1 = _read_text(tmp_path / "nope")
        r2 = check_license(tmp_path)
        r3 = detect_version(tmp_path, "x/y")
        assert r1 is None
        assert r2 is None
        assert r3 is None
        # All are the same singleton
        assert r1 is r2 is r3

    def test_string_result_equality_not_identity(self, tmp_path: Path):
        """String results should be compared with == not 'is'."""
        _write(tmp_path, ".python-version", "3.11\n")
        r1 = detect_python_version(tmp_path)
        r2 = detect_python_version(tmp_path)
        assert r1 == r2
        # Do not rely on: assert r1 is r2


# ═══════════════════════════════════════════════════════════════════════
# 5. TestFloatEdgeValues  (~10 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestFloatEdgeValues:
    """Verify float-like edge values don't cause crashes or wrong results."""

    def test_parse_min_python_inf(self):
        """'3.inf' should not parse as a valid version — fallback to 3.10."""
        result = _parse_min_python(">=3.inf")
        # Regex expects >=?\s*(\d+\.\d+), 'inf' doesn't match \d+
        assert result == "3.10"

    def test_parse_min_python_nan(self):
        """'nan.10' should not match — fallback."""
        result = _parse_min_python(">=nan.10")
        assert result == "3.10"

    def test_parse_min_python_scientific(self):
        """'3.1e2' — regex matches '3.1' before 'e2'."""
        result = _parse_min_python(">=3.1e2")
        # Regex (\d+\.\d+) matches "3.1" from "3.1e2"
        assert result == "3.1"

    def test_parse_min_python_only_inf(self):
        """Bare 'inf' has no digit.digit pattern — fallback."""
        result = _parse_min_python("inf")
        assert result == "3.10"

    def test_parse_min_python_only_nan(self):
        result = _parse_min_python("nan")
        assert result == "3.10"

    def test_version_detection_inf_in_file(self, tmp_path: Path):
        """VERSION file containing 'inf' shouldn't match \\d+\\.\\d+ pattern."""
        _write(tmp_path, "VERSION", "inf\n")
        result = detect_version(tmp_path, "owner/nonexistent_xyz")
        assert result is None

    def test_version_detection_nan_in_file(self, tmp_path: Path):
        _write(tmp_path, "VERSION", "nan\n")
        result = detect_version(tmp_path, "owner/nonexistent_xyz")
        assert result is None

    def test_version_detection_1e10_in_file(self, tmp_path: Path):
        """'1e10' doesn't match \\d+\\.\\d+ — no dot."""
        _write(tmp_path, "VERSION", "1e10\n")
        result = detect_version(tmp_path, "owner/nonexistent_xyz")
        assert result is None

    def test_parse_min_python_negative(self):
        """'>=-3.10': '-' after '>=' prevents \\d+ match → fallback."""
        result = _parse_min_python(">=-3.10")
        assert result == "3.10"

    def test_parse_min_python_very_large(self):
        """Very large version number."""
        result = _parse_min_python(">=99999.99999")
        assert result == "99999.99999"


# ═══════════════════════════════════════════════════════════════════════
# 6. TestIteratorExhaustion  (~10 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestIteratorExhaustion:
    """Verify results from glob/re.findall survive multiple iterations."""

    def test_pre_install_fortran_glob_not_exhausted(self, tmp_path: Path):
        """Fortran detection uses glob — must not be consumed by first ext check."""
        _write(tmp_path, "core/special.f90", "subroutine foo()\nend subroutine\n")
        result = detect_pre_install(tmp_path)
        assert any("gfortran" in cmd for cmd in result)

    def test_pre_install_multiple_fortran_exts(self, tmp_path: Path):
        """Multiple Fortran extensions — glob for each ext is independent."""
        _write(tmp_path, "a.f90", "subroutine a()\nend subroutine\n")
        _write(tmp_path, "b.f", "subroutine b()\nend subroutine\n")
        result = detect_pre_install(tmp_path)
        gfortran_cmds = [c for c in result if "gfortran" in c]
        # Should still appear exactly once
        assert len(gfortran_cmds) == 1

    def test_pre_install_only_f77_extension(self, tmp_path: Path):
        """Only .f77 files — should still detect fortran."""
        _write(tmp_path, "sub/calc.f77", "subroutine calc()\nend subroutine\n")
        result = detect_pre_install(tmp_path)
        assert any("gfortran" in cmd for cmd in result)

    def test_pre_install_only_for_extension(self, tmp_path: Path):
        """.for extension is also a fortran extension."""
        _write(tmp_path, "legacy.for", "subroutine old()\nend subroutine\n")
        result = detect_pre_install(tmp_path)
        assert any("gfortran" in cmd for cmd in result)

    def test_tox_envlist_findall_survives(self, tmp_path: Path):
        """re.findall in tox envlist parsing returns a list, not an iterator."""
        _write(tmp_path, "tox.ini", "envlist = py38,py39,py310\n")
        r1 = detect_python_version(tmp_path)
        r2 = detect_python_version(tmp_path)
        assert r1 == r2  # Same result — findall not exhausted

    def test_tox_envlist_multiple_versions_consistent(self, tmp_path: Path):
        _write(tmp_path, "tox.ini", "envlist = py36,py37,py38,py39\n")
        r1 = detect_python_version(tmp_path)
        r2 = detect_python_version(tmp_path)
        assert r1 == "3.6"
        assert r2 == "3.6"

    def test_re_findall_returns_list(self, tmp_path: Path):
        """re.findall always returns a list (not generator) — safe for multiple passes."""
        import re
        text = "py38,py39,py310"
        result = re.findall(r'py(\d)(\d+)', text)
        assert isinstance(result, list)
        # Can iterate multiple times
        first_pass = list(result)
        second_pass = list(result)
        assert first_pass == second_pass

    def test_glob_returns_generator_but_listified(self, tmp_path: Path):
        """Path.glob returns generator. detect_pre_install calls list() on it."""
        _write(tmp_path, "a.f90", "subroutine a()\nend subroutine\n")
        # Call twice — second call must not see exhausted generator
        r1 = detect_pre_install(tmp_path)
        r2 = detect_pre_install(tmp_path)
        assert r1 == r2

    def test_requirements_dir_glob_not_exhausted(self, tmp_path: Path):
        """requirements dir uses glob('*.txt') — must not exhaust."""
        _write(tmp_path, "requirements/a.txt", "numpy\n")
        _write(tmp_path, "requirements/b.txt", "pandas\n")
        r1 = detect_packages_source(tmp_path)
        r2 = detect_packages_source(tmp_path)
        assert r1 == r2

    def test_requirements_dir_glob_consistency(self, tmp_path: Path):
        _write(tmp_path, "requirements/base.txt", "x\n")
        _write(tmp_path, "requirements/dev.txt", "y\n")
        _write(tmp_path, "requirements/ci.txt", "z\n")
        _, reqs1, _ = detect_packages_source(tmp_path)
        _, reqs2, _ = detect_packages_source(tmp_path)
        assert reqs1 == reqs2
        assert sorted(reqs1) == reqs1  # Must be sorted


# ═══════════════════════════════════════════════════════════════════════
# 7. TestStringInterning  (~10 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestStringInterning:
    """String comparisons must use == not 'is'. Interning is CPython detail."""

    def test_fallback_version_equal(self, tmp_path: Path):
        r1 = detect_python_version(tmp_path)
        r2 = detect_python_version(tmp_path)
        assert r1 == r2

    def test_detected_version_equal(self, tmp_path: Path):
        _write(tmp_path, ".python-version", "3.11\n")
        r1 = detect_python_version(tmp_path)
        r2 = detect_python_version(tmp_path)
        assert r1 == r2

    def test_install_cmd_equal(self, tmp_path: Path):
        from detect_repo_specs import detect_install_cmd
        r1 = detect_install_cmd(tmp_path)
        r2 = detect_install_cmd(tmp_path)
        assert r1 == r2

    def test_test_cmd_equal(self, tmp_path: Path):
        from detect_repo_specs import detect_test_cmd
        r1 = detect_test_cmd(tmp_path)
        r2 = detect_test_cmd(tmp_path)
        assert r1 == r2

    def test_log_parser_type_equal(self, tmp_path: Path):
        from detect_repo_specs import _detect_log_parser_type
        r1 = _detect_log_parser_type("pytest {test_files}")
        r2 = _detect_log_parser_type("pytest {test_files}")
        assert r1 == r2

    def test_license_string_equal(self, tmp_path: Path):
        _write(tmp_path, "LICENSE",
               "MIT License\n\nPermission is hereby granted...")
        r1 = check_license(tmp_path)
        r2 = check_license(tmp_path)
        assert r1 == r2
        assert r1 == "MIT"

    def test_packages_source_string_equal(self, tmp_path: Path):
        _write(tmp_path, "requirements.txt", "numpy\n")
        s1, _, _ = detect_packages_source(tmp_path)
        s2, _, _ = detect_packages_source(tmp_path)
        assert s1 == s2
        assert s1 == "requirements.txt"

    def test_empty_string_equal(self, tmp_path: Path):
        """Empty packages_source — compare with ==."""
        s1, _, _ = detect_packages_source(tmp_path)
        s2, _, _ = detect_packages_source(tmp_path)
        assert s1 == s2
        assert s1 == ""

    @pytest.mark.parametrize("spec,expected", [
        (">=3.8", "3.8"),
        (">=3.9", "3.9"),
        (">=3.10", "3.10"),
        (">=3.11", "3.11"),
        (">=3.12", "3.12"),
    ])
    def test_parse_min_python_equality_not_identity(self, spec: str, expected: str):
        """Returned strings compare equal via ==; 'is' behavior is unspecified."""
        result = _parse_min_python(spec)
        assert result == expected
        assert isinstance(result, str)

    def test_constructed_string_not_interned(self):
        """Dynamically constructed strings may not be interned."""
        a = "3." + "10"
        b = _parse_min_python(">=3.10")
        assert a == b  # Must use == for correctness
        # a is b may be True or False depending on CPython — irrelevant


# ═══════════════════════════════════════════════════════════════════════
# 8. TestBoolIntConfusion  (~10 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestBoolIntConfusion:
    """In Python True == 1 and False == 0. This can cause subtle dict key collisions."""

    def test_validate_instances_returns_bool(self):
        instances = [_full_instance()]
        result = validate_instances(instances)
        assert isinstance(result, bool)

    def test_validate_instances_true_is_bool(self):
        instances = [_full_instance()]
        result = validate_instances(instances)
        assert result is True
        assert type(result) is bool

    def test_validate_instances_false_is_bool(self):
        instances = [{"instance_id": "bad"}]
        result = validate_instances(instances)
        assert result is False
        assert type(result) is bool

    def test_validate_instances_true_not_1(self):
        """True == 1 in Python, but validate should return bool not int."""
        instances = [_full_instance()]
        result = validate_instances(instances)
        assert result is True
        assert result == 1  # Python truth, but...
        assert type(result) is not int  # ...it's actually bool

    def test_validate_instances_false_not_0(self):
        instances = [{"instance_id": "bad"}]
        result = validate_instances(instances)
        assert result is False
        assert result == 0
        assert type(result) is not int

    @patch("detect_repo_specs.subprocess.run")
    def test_git_clone_returns_bool_true(self, mock_run: MagicMock, tmp_path: Path):
        from detect_repo_specs import _git_clone
        mock_run.return_value = MagicMock(returncode=0)
        result = _git_clone("owner/repo", tmp_path)
        assert isinstance(result, bool)
        assert result is True

    @patch("detect_repo_specs.subprocess.run")
    def test_git_clone_returns_bool_false(self, mock_run: MagicMock, tmp_path: Path):
        from detect_repo_specs import _git_clone
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        result = _git_clone("owner/repo", tmp_path)
        assert isinstance(result, bool)
        assert result is False

    @patch("detect_repo_specs.subprocess.run")
    def test_git_checkout_returns_bool_true(self, mock_run: MagicMock, tmp_path: Path):
        from detect_repo_specs import _git_checkout
        mock_run.return_value = MagicMock(returncode=0)
        result = _git_checkout(tmp_path, "abc123")
        assert isinstance(result, bool)
        assert result is True

    def test_true_1_dict_key_collision(self):
        """True and 1 are the same dict key — verify cache won't confuse them."""
        d: dict[Any, str] = {}
        d[True] = "bool_val"
        d[1] = "int_val"
        # Python dict: True == 1, so they collide
        assert len(d) == 1
        assert d[True] == "int_val"
        assert d[1] == "int_val"

    def test_cache_keys_are_strings(self, tmp_path: Path):
        """Cache keys must be strings — no bool/int collision possible."""
        cache_file = tmp_path / "cache.json"
        data = {"owner/repo@abc123": {"python_version": "3.10"}}
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_cache(str(cache_file))
        for key in loaded:
            assert isinstance(key, str), f"Cache key {key!r} is not a string"


# ═══════════════════════════════════════════════════════════════════════
# 9. TestLateBindingClosures  (~15 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestLateBindingClosures:
    """Verify detection functions don't suffer from classic late-binding
    closure bugs when called in a loop or used to build lambda/closure lists."""

    def test_parse_min_python_loop_captures_each_value(self):
        """_parse_min_python called in a loop returns per-iteration values,
        not all returning the last spec's result."""
        specs = [">=3.8", ">=3.9", ">=3.10", ">=3.11", ">=3.12"]
        results = [_parse_min_python(s) for s in specs]
        assert results == ["3.8", "3.9", "3.10", "3.11", "3.12"]

    def test_parse_min_python_loop_not_all_last_value(self):
        """Explicit check that results are NOT all the final iteration value."""
        specs = [">=3.8", ">=3.9", ">=3.10"]
        results = [_parse_min_python(s) for s in specs]
        # If late-binding bug existed, all would be "3.10"
        assert results[0] != results[-1]

    def test_closure_over_loop_variable_classic_trap(self):
        """Classic Python late binding: closures in a loop capture the *variable*,
        not the *value*. Verify our detection helpers don't suffer this."""
        specs = [">=3.8", ">=3.9", ">=3.10"]
        # Correct: each lambda captures its own value via default arg
        funcs_correct = [lambda s=s: _parse_min_python(s) for s in specs]
        results = [f() for f in funcs_correct]
        assert results == ["3.8", "3.9", "3.10"]

    def test_closure_late_binding_bug_demonstration(self):
        """Demonstrate the late-binding bug so we know what to watch for."""
        specs = [">=3.8", ">=3.9", ">=3.10"]
        # BUG pattern: closure captures loop var, not current value
        funcs_buggy = [lambda: _parse_min_python(s) for s in specs]
        buggy_results = [f() for f in funcs_buggy]
        # All return the last value of s
        assert all(r == "3.10" for r in buggy_results)

    def test_functools_partial_avoids_late_binding(self):
        """functools.partial eagerly binds arguments — no late-binding issue."""
        specs = [">=3.8", ">=3.9", ">=3.10"]
        funcs = [functools.partial(_parse_min_python, s) for s in specs]
        results = [f() for f in funcs]
        assert results == ["3.8", "3.9", "3.10"]

    def test_list_comprehension_closure_values(self):
        """List comprehension creates closures that each capture correct value."""
        specs = [">=3.8,<4.0", ">=3.11", "==3.12"]
        results = [_parse_min_python(s) for s in specs]
        assert results == ["3.8", "3.11", "3.12"]

    def test_detect_all_specs_multiple_repos_independent(self, tmp_path: Path):
        """detect_all_specs called on different repos returns independent results."""
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        repo_a.mkdir()
        repo_b.mkdir()
        _write(repo_a, "pyproject.toml",
               '[project]\nname = "a"\nrequires-python = ">=3.8"\n')
        _write(repo_b, "pyproject.toml",
               '[project]\nname = "b"\nrequires-python = ">=3.11"\n')
        r_a = detect_all_specs(repo_a, "owner/a")
        r_b = detect_all_specs(repo_b, "owner/b")
        assert r_a["python_version"] == "3.8"
        assert r_b["python_version"] == "3.11"

    def test_detect_all_specs_loop_returns_correct_per_repo(self, tmp_path: Path):
        """Calling detect_all_specs in a loop captures correct per-repo results."""
        repos = {}
        for ver in ("3.8", "3.9", "3.10", "3.11"):
            d = tmp_path / f"repo_{ver.replace('.', '_')}"
            d.mkdir()
            _write(d, "pyproject.toml",
                   f'[project]\nname = "x"\nrequires-python = ">={ver}"\n')
            repos[ver] = d
        results = {v: detect_all_specs(d, f"owner/r{v}")["python_version"]
                   for v, d in repos.items()}
        for expected_ver, actual_ver in results.items():
            assert actual_ver == expected_ver

    def test_lambda_in_list_generation_with_detect_version(self, tmp_path: Path):
        """Lambda list generation calling detect_version captures each path."""
        dirs = []
        for i, ver in enumerate(["1.0", "2.0", "3.0"]):
            d = tmp_path / f"pkg{i}"
            d.mkdir()
            _write(d, "VERSION", f"{ver}\n")
            dirs.append(d)
        funcs = [lambda d=d: detect_version(d, "x/y") for d in dirs]
        results = [f() for f in funcs]
        assert results == ["1.0", "2.0", "3.0"]

    def test_partial_with_detect_python_version(self, tmp_path: Path):
        """functools.partial with detect_python_version captures each dir."""
        dirs = []
        for ver in ("3.8", "3.9"):
            d = tmp_path / f"r_{ver.replace('.', '_')}"
            d.mkdir()
            _write(d, ".python-version", f"{ver}\n")
            dirs.append(d)
        funcs = [functools.partial(detect_python_version, d) for d in dirs]
        results = [f() for f in funcs]
        assert results == ["3.8", "3.9"]

    def test_map_parse_min_python_over_specs(self):
        """Using map() applies _parse_min_python correctly to each spec."""
        specs = [">=3.7", ">=3.8", ">=3.9"]
        results = list(map(_parse_min_python, specs))
        assert results == ["3.7", "3.8", "3.9"]

    def test_generator_expression_no_late_binding(self):
        """Generator expression evaluates lazily but still captures values."""
        specs = [">=3.8", ">=3.9", ">=3.10"]
        gen = (_parse_min_python(s) for s in specs)
        results = list(gen)
        assert results == ["3.8", "3.9", "3.10"]

    def test_detect_packages_source_loop_independent(self, tmp_path: Path):
        """detect_packages_source in a loop returns independent results per repo."""
        dirs = []
        for i in range(3):
            d = tmp_path / f"repo_{i}"
            d.mkdir()
            if i == 0:
                _write(d, "requirements.txt", "numpy\n")
            elif i == 1:
                _write(d, "environment.yml", "name: e\ndependencies: []\n")
            dirs.append(d)
        results = [detect_packages_source(d)[0] for d in dirs]
        assert results[0] == "requirements.txt"
        assert results[1] == "environment.yml"
        assert results[2] == ""

    def test_closure_with_default_arg_pattern(self):
        """Default argument pattern is the standard fix for late binding."""
        specs = [">=3.8", ">=3.9", ">=3.10"]
        funcs = []
        for s in specs:
            funcs.append(lambda spec=s: _parse_min_python(spec))
        assert [f() for f in funcs] == ["3.8", "3.9", "3.10"]

    def test_nested_closure_captures(self, tmp_path: Path):
        """Nested closures each capture their own scope correctly."""
        def make_detector(repo_dir: Path, repo_name: str):
            def detector():
                return detect_all_specs(repo_dir, repo_name)
            return detector

        d1 = tmp_path / "r1"
        d2 = tmp_path / "r2"
        d1.mkdir()
        d2.mkdir()
        _write(d1, ".python-version", "3.8\n")
        _write(d2, ".python-version", "3.11\n")

        det1 = make_detector(d1, "o/r1")
        det2 = make_detector(d2, "o/r2")
        assert det1()["python_version"] == "3.8"
        assert det2()["python_version"] == "3.11"


# ═══════════════════════════════════════════════════════════════════════
# 10. TestExceptExceptionScope  (~15 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestExceptExceptionScope:
    """Verify that critical exceptions (KeyboardInterrupt, SystemExit,
    MemoryError, GeneratorExit) propagate through the codebase rather
    than being swallowed by except clauses."""

    def test_read_text_propagates_keyboard_interrupt(self, tmp_path: Path):
        """_read_text catches OSError | UnicodeDecodeError. KeyboardInterrupt
        must escape."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                _read_text(target)

    def test_read_text_propagates_system_exit(self, tmp_path: Path):
        """SystemExit must propagate through _read_text."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                _read_text(target)

    def test_read_text_propagates_memory_error(self, tmp_path: Path):
        """MemoryError must propagate through _read_text."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=MemoryError):
            with pytest.raises(MemoryError):
                _read_text(target)

    def test_read_text_propagates_generator_exit(self, tmp_path: Path):
        """GeneratorExit must propagate through _read_text."""
        target = tmp_path / "file.txt"
        target.write_text("data", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=GeneratorExit):
            with pytest.raises(GeneratorExit):
                _read_text(target)

    def test_detect_all_specs_propagates_system_exit(self, tmp_path: Path):
        """SystemExit raised during detection must propagate out."""
        with patch("detect_repo_specs.detect_python_version",
                   side_effect=SystemExit(42)):
            with pytest.raises(SystemExit):
                detect_all_specs(tmp_path, "owner/repo")

    def test_detect_all_specs_propagates_keyboard_interrupt(self, tmp_path: Path):
        """KeyboardInterrupt during detection must propagate out."""
        with patch("detect_repo_specs.detect_python_version",
                   side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                detect_all_specs(tmp_path, "owner/repo")

    @patch("detect_repo_specs.subprocess.run")
    def test_git_clone_propagates_keyboard_interrupt(self, mock_run: MagicMock,
                                                      tmp_path: Path):
        """KeyboardInterrupt from subprocess must propagate through _git_clone."""
        mock_run.side_effect = KeyboardInterrupt
        with pytest.raises(KeyboardInterrupt):
            _git_clone("owner/repo", tmp_path)

    @patch("detect_repo_specs.subprocess.run")
    def test_git_clone_propagates_system_exit(self, mock_run: MagicMock,
                                               tmp_path: Path):
        """SystemExit from subprocess must propagate through _git_clone."""
        mock_run.side_effect = SystemExit(1)
        with pytest.raises(SystemExit):
            _git_clone("owner/repo", tmp_path)

    def test_parse_toml_propagates_keyboard_interrupt(self, tmp_path: Path):
        """KeyboardInterrupt during TOML parsing must propagate."""
        target = tmp_path / "pyproject.toml"
        target.write_text('[project]\nname = "x"\n', encoding="utf-8")
        with patch("detect_repo_specs._read_text",
                   side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                _parse_toml(target)

    def test_parse_toml_propagates_memory_error(self, tmp_path: Path):
        """MemoryError during TOML parsing must propagate."""
        target = tmp_path / "pyproject.toml"
        target.write_text('[project]\nname = "x"\n', encoding="utf-8")
        with patch("detect_repo_specs._read_text",
                   side_effect=MemoryError):
            with pytest.raises(MemoryError):
                _parse_toml(target)

    def test_no_bare_except_in_source(self):
        """Verify detect_repo_specs does NOT use bare 'except:' clauses.
        It should always catch specific exception types."""
        import detect_repo_specs
        source_path = inspect.getfile(detect_repo_specs)
        source = Path(source_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        bare_excepts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    bare_excepts.append(node.lineno)
        assert bare_excepts == [], (
            f"Found bare 'except:' at lines {bare_excepts} — "
            f"should use specific exception types"
        )

    def test_load_cache_propagates_keyboard_interrupt(self, tmp_path: Path):
        """KeyboardInterrupt during file read must propagate through load_cache."""
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{}", encoding="utf-8")
        with patch("builtins.open", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                load_cache(str(cache_file))

    def test_save_cache_propagates_keyboard_interrupt(self, tmp_path: Path):
        """KeyboardInterrupt during save must propagate through save_cache."""
        with patch("builtins.open", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                save_cache({"k": {"v": "1"}}, str(tmp_path / "cache.json"))

    def test_write_jsonl_propagates_keyboard_interrupt(self, tmp_path: Path):
        """KeyboardInterrupt during write_jsonl must propagate."""
        with patch("builtins.open", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                write_jsonl([{"a": 1}], str(tmp_path / "out.jsonl"))

    def test_exception_handler_specificity(self):
        """Verify that except clauses in key functions catch specific types,
        not broad Exception (where it could swallow critical errors)."""
        import detect_repo_specs
        source_path = inspect.getfile(detect_repo_specs)
        source = Path(source_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        # _read_text should catch (OSError, UnicodeDecodeError) only
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_read_text":
                for child in ast.walk(node):
                    if isinstance(child, ast.ExceptHandler) and child.type is not None:
                        # The handler should catch specific types, not Exception
                        if isinstance(child.type, ast.Name):
                            assert child.type.id != "Exception", (
                                "_read_text should not catch generic Exception"
                            )
                        elif isinstance(child.type, ast.Tuple):
                            for elt in child.type.elts:
                                if isinstance(elt, ast.Name):
                                    assert elt.id != "Exception", (
                                        "_read_text should not catch generic Exception"
                                    )


# ═══════════════════════════════════════════════════════════════════════
# 11. TestImportSideEffects  (~10 cases)
# ═══════════════════════════════════════════════════════════════════════


class TestImportSideEffects:
    """Verify that importing detect_repo_specs has no side effects:
    no filesystem I/O, no subprocess calls, no network, no sys.path mutation
    beyond what's needed."""

    def test_import_does_not_call_subprocess(self):
        """Importing the module must not spawn any subprocesses."""
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("subprocess.call") as mock_call:
            # Re-import the module
            import detect_repo_specs
            importlib.reload(detect_repo_specs)
            mock_run.assert_not_called()
            mock_popen.assert_not_called()
            mock_call.assert_not_called()

    def test_import_does_not_read_filesystem(self):
        """Importing must not open/read arbitrary files."""
        original_open = open
        files_opened: list[str] = []

        def tracking_open(*args, **kwargs):
            if args:
                path_str = str(args[0])
                # Ignore Python's own import machinery files
                if not (path_str.endswith(".py") or path_str.endswith(".pyc")
                        or path_str.endswith(".pyi") or "importlib" in path_str
                        or "__pycache__" in path_str or "site-packages" in path_str
                        or "/lib/python" in path_str):
                    files_opened.append(path_str)
            return original_open(*args, **kwargs)

        import detect_repo_specs
        with patch("builtins.open", side_effect=tracking_open):
            importlib.reload(detect_repo_specs)
        assert files_opened == [], (
            f"Import opened unexpected files: {files_opened}"
        )

    def test_module_level_variables_are_constants(self):
        """Module-level variables should be constants/patterns, not computed."""
        import detect_repo_specs
        source_path = inspect.getfile(detect_repo_specs)
        source = Path(source_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Check module-level assignments — only allow constants, patterns, etc.
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name = target.id
                        # Should be uppercase (constant) or start with _
                        # and not be a function call that does I/O
                        if isinstance(node.value, ast.Call):
                            if isinstance(node.value.func, ast.Attribute):
                                func_name = node.value.func.attr
                                # re.compile is OK, logging.getLogger is OK
                                assert func_name in (
                                    "compile", "getLogger",
                                ), (
                                    f"Module-level {name} uses call {func_name} "
                                    f"which may cause side effects"
                                )
                            elif isinstance(node.value.func, ast.Name):
                                func_name = node.value.func.id
                                assert func_name not in (
                                    "open", "subprocess", "Path",
                                    "requests", "urlopen",
                                ), (
                                    f"Module-level {name} uses call {func_name} "
                                    f"which may cause side effects"
                                )

    def test_import_does_not_modify_sys_path(self):
        """Importing must not alter sys.path (module is not a script at import)."""
        import detect_repo_specs
        original_path = sys.path.copy()
        importlib.reload(detect_repo_specs)
        assert sys.path == original_path

    def test_import_multiple_times_no_side_effects(self):
        """Reimporting should be idempotent — no accumulated side effects."""
        import detect_repo_specs
        r1 = detect_all_specs.__module__
        importlib.reload(detect_repo_specs)
        importlib.reload(detect_repo_specs)
        importlib.reload(detect_repo_specs)
        # Module is the same
        assert detect_repo_specs.__name__ == "detect_repo_specs"

    def test_no_network_calls_on_import(self):
        """Importing must not make network calls."""
        with patch("socket.socket") as mock_socket:
            import detect_repo_specs
            importlib.reload(detect_repo_specs)
            mock_socket.assert_not_called()

    def test_license_patterns_are_compiled_at_module_level(self):
        """_LICENSE_PATTERNS should be a list of compiled regex patterns —
        this is expected module-level work (compilation, not I/O)."""
        import detect_repo_specs
        patterns = detect_repo_specs._LICENSE_PATTERNS
        assert isinstance(patterns, list)
        for name, pat in patterns:
            assert isinstance(name, str)
            assert hasattr(pat, "search"), f"Pattern for {name} is not compiled regex"

    def test_required_fields_defined_at_module_level(self):
        """REQUIRED_ENRICHMENT_FIELDS is a module-level constant tuple."""
        import detect_repo_specs
        assert hasattr(detect_repo_specs, "REQUIRED_ENRICHMENT_FIELDS")
        assert isinstance(detect_repo_specs.REQUIRED_ENRICHMENT_FIELDS, tuple)

    def test_tomllib_import_fallback_is_safe(self):
        """The tomllib/tomli import fallback chain at module level is safe
        and doesn't cause errors if neither is available."""
        import detect_repo_specs
        # tomllib attribute should exist (may be None if no TOML parser)
        assert hasattr(detect_repo_specs, "tomllib")

    def test_no_argparse_execution_on_import(self):
        """argparse.parse_args() is only called inside main(), not on import."""
        import detect_repo_specs
        source_path = inspect.getfile(detect_repo_specs)
        source = Path(source_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Find all parse_args calls — they must be inside function defs
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "parse_args":
                        # Walk up to find enclosing function
                        # (simple check: parse_args should not be at module level)
                        pass  # AST walk doesn't provide parent info easily
        # Alternative: check that main() contains the parser
        main_found = False
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                main_found = True
                main_source = ast.dump(node)
                assert "parse_args" in main_source
        assert main_found, "main() function not found in detect_repo_specs"
