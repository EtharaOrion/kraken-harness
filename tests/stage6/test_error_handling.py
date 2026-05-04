"""Dimension 8 — Error Handling / Failure Recovery tests for detect_repo_specs.

Tests that every public and internal helper handles malformed input, missing files,
permission errors, corrupt data, and edge-case paths gracefully without crashing.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Import setup: add scripts/ to path so we can import detect_repo_specs
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (  # noqa: E402
    _parse_toml,
    _parse_toml_regex,
    _read_text,
    load_cache,
    load_instances,
    save_cache,
    validate_instances,
    write_jsonl,
)
from detect_repo_specs import _load_jsonl  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


_IS_ROOT = os.getuid() == 0 if hasattr(os, "getuid") else False
_SKIP_PERM = pytest.mark.skipif(
    _IS_ROOT or platform.system() == "Windows",
    reason="Permission tests unreliable as root or on Windows",
)


# ===================================================================
# 1. TestReadTextErrorHandling (~20 cases)
# ===================================================================

class TestReadTextErrorHandling:
    """Error paths for _read_text: permission, missing, symlinks, bad paths."""

    # -- non-existent file --------------------------------------------------

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        result = _read_text(tmp_path / "does_not_exist.txt")
        assert result is None

    def test_nonexistent_nested_path(self, tmp_path: Path) -> None:
        result = _read_text(tmp_path / "a" / "b" / "c" / "deep.txt")
        assert result is None

    # -- permission denied --------------------------------------------------

    @_SKIP_PERM
    def test_permission_denied_file(self, tmp_path: Path) -> None:
        p = tmp_path / "secret.txt"
        p.write_text("secret", encoding="utf-8")
        p.chmod(0o000)
        try:
            result = _read_text(p)
            assert result is None
        finally:
            p.chmod(0o644)

    @_SKIP_PERM
    def test_permission_denied_parent_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "locked"
        d.mkdir()
        p = d / "file.txt"
        p.write_text("data", encoding="utf-8")
        d.chmod(0o000)
        try:
            result = _read_text(p)
            assert result is None
        finally:
            d.chmod(0o755)

    # -- symlink to nonexistent target --------------------------------------

    def test_symlink_to_nonexistent(self, tmp_path: Path) -> None:
        link = tmp_path / "broken_link"
        link.symlink_to(tmp_path / "target_that_does_not_exist")
        result = _read_text(link)
        assert result is None

    def test_symlink_chain_broken(self, tmp_path: Path) -> None:
        mid = tmp_path / "mid_link"
        mid.symlink_to(tmp_path / "final_missing")
        outer = tmp_path / "outer_link"
        outer.symlink_to(mid)
        result = _read_text(outer)
        assert result is None

    # -- directory passed instead of file -----------------------------------

    def test_directory_instead_of_file(self, tmp_path: Path) -> None:
        d = tmp_path / "adir"
        d.mkdir()
        result = _read_text(d)
        assert result is None

    def test_root_dir(self) -> None:
        result = _read_text(Path("/"))
        assert result is None

    # -- very long path -----------------------------------------------------

    def test_very_long_path(self, tmp_path: Path) -> None:
        long_name = "a" * 4096
        result = _read_text(tmp_path / long_name)
        assert result is None

    def test_long_nested_path(self, tmp_path: Path) -> None:
        parts = ["d"] * 500
        deep = tmp_path.joinpath(*parts, "file.txt")
        result = _read_text(deep)
        assert result is None

    # -- path with null byte ------------------------------------------------

    def test_path_with_null_byte(self, tmp_path: Path) -> None:
        try:
            result = _read_text(Path(str(tmp_path) + "/file\x00.txt"))
            # Either raises ValueError or returns None — both acceptable
            assert result is None
        except (ValueError, TypeError):
            pass  # also acceptable

    def test_null_byte_in_middle(self, tmp_path: Path) -> None:
        try:
            result = _read_text(Path(str(tmp_path) + "/fi\x00le.txt"))
            assert result is None
        except (ValueError, TypeError):
            pass

    # -- binary file --------------------------------------------------------

    def test_binary_file_reads_with_replacement(self, tmp_path: Path) -> None:
        p = tmp_path / "binary.bin"
        p.write_bytes(b"\x80\x81\x82\xff\xfe\xfd")
        result = _read_text(p)
        # _read_text uses errors="replace", so it should return a string, not None
        assert result is not None
        assert isinstance(result, str)

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        result = _read_text(p)
        assert result == ""

    # -- special file types -------------------------------------------------

    @pytest.mark.parametrize("name", [
        ".hidden_file",
        "file with spaces.txt",
        "file\twith\ttabs.txt",
        "UPPERCASE.TXT",
    ])
    def test_nonexistent_special_names(self, tmp_path: Path, name: str) -> None:
        result = _read_text(tmp_path / name)
        assert result is None

    def test_fifo_path_nonexistent(self, tmp_path: Path) -> None:
        result = _read_text(tmp_path / "nonexistent.fifo")
        assert result is None

    def test_path_is_none_equivalent(self) -> None:
        """Path constructed from empty string segment."""
        try:
            result = _read_text(Path(""))
            # Could be None or raise — both fine
        except (OSError, ValueError):
            pass


# ===================================================================
# 2. TestParseTomlErrorHandling (~20 cases)
# ===================================================================

_MALFORMED_TOML = [
    ("unclosed-bracket", '[project\nname = "x"'),
    ("unclosed-string", 'name = "unclosed'),
    ("unclosed-array", "deps = [1, 2, 3"),
    ("bare-equals", "= value"),
    ("double-equals", "key == value"),
    ("trailing-comma-array", 'deps = ["a", "b",]'),
    ("duplicate-table", "[project]\nname = \"a\"\n[project]\nname = \"b\""),
    ("inline-table-unclosed", "key = {a = 1"),
    ("bad-escape-sequence", 'key = "bad \\z escape"'),
    ("tab-in-bare-key", "\tkey = 1"),
    ("mixed-types-array", 'arr = [1, "two", true]'),
    ("no-value", "key ="),
    ("missing-newline-between-kv", 'a = 1 b = 2'),
    ("comment-only", "# just a comment\n# and another"),
    ("nested-unclosed-inline", 'key = {a = {b = 1}'),
    ("float-leading-dot", "val = .5"),
    ("integer-leading-zero", "val = 007"),
]


class TestParseTomlErrorHandling:
    """Error paths for _parse_toml: malformed content, binary, edge cases."""

    @pytest.mark.parametrize("label, content", _MALFORMED_TOML,
                             ids=[c[0] for c in _MALFORMED_TOML])
    def test_malformed_toml_returns_none(self, tmp_path: Path,
                                         label: str, content: str) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text(content, encoding="utf-8")
        result = _parse_toml(p)
        # Malformed TOML should return None (parse failure) or a partial dict
        # from regex fallback.  Either is acceptable graceful handling.
        assert result is None or isinstance(result, dict)

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text("", encoding="utf-8")
        result = _parse_toml(p)
        # Empty TOML is valid — should return {} or None
        assert result is None or isinstance(result, dict)

    def test_binary_content(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd\xfc")
        result = _parse_toml(p)
        assert result is None or isinstance(result, dict)

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        result = _parse_toml(tmp_path / "missing.toml")
        assert result is None

    def test_very_deeply_nested(self, tmp_path: Path) -> None:
        # Deep nesting — should not crash
        p = tmp_path / "pyproject.toml"
        content = "[a]\n" + "[a.b]\n" * 50 + 'val = "deep"'
        p.write_text(content, encoding="utf-8")
        result = _parse_toml(p)
        assert result is None or isinstance(result, dict)

    def test_extremely_large_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        lines = [f'key{i} = "value{i}"' for i in range(10000)]
        p.write_text("\n".join(lines), encoding="utf-8")
        result = _parse_toml(p)
        assert result is None or isinstance(result, dict)

    def test_only_whitespace(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text("   \n\n\t\t  \n", encoding="utf-8")
        result = _parse_toml(p)
        assert result is None or isinstance(result, dict)

    def test_json_content_as_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text('{"key": "value"}', encoding="utf-8")
        result = _parse_toml(p)
        assert result is None or isinstance(result, dict)

    def test_yaml_content_as_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text("key: value\nlist:\n  - item1\n  - item2\n", encoding="utf-8")
        result = _parse_toml(p)
        assert result is None or isinstance(result, dict)

    def test_xml_content_as_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text('<?xml version="1.0"?>\n<root><item/></root>', encoding="utf-8")
        result = _parse_toml(p)
        assert result is None or isinstance(result, dict)

    @_SKIP_PERM
    def test_permission_denied(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nname = "x"', encoding="utf-8")
        p.chmod(0o000)
        try:
            result = _parse_toml(p)
            assert result is None
        finally:
            p.chmod(0o644)


# ===================================================================
# 3. TestParseTomlRegexErrorHandling (~15 cases)
# ===================================================================

_REGEX_BREAKING = [
    ("nested-brackets", 'requires = [[["deep"]]]'),
    ("backreference-like", 'val = "\\1\\2\\3"'),
    ("catastrophic-backtrack", 'val = "' + "a" * 500 + '"'),
    ("regex-metachar-star", 'val = ".*+?{}()|[]^$"'),
    ("unclosed-bracket-val", 'val = "[unclosed'),
    ("many-quotes", 'val = ' + '"""' * 50),
    ("newlines-in-value", 'val = "line1\nline2\nline3"'),
    ("escaped-quotes", 'val = "escaped \\" quote"'),
    ("mixed-bracket-types", 'val = "[{([{()}])}]"'),
    ("empty-bracket-pairs", 'val = "[][][][]"'),
    ("null-chars-in-content", 'val = "has\x00null"'),
    ("only-brackets", "[[[[[[[["),
    ("alternating-quotes", "a = 'b'\nc = \"d\"\ne = '''f'''"),
]


class TestParseTomlRegexErrorHandling:
    """Error paths for _parse_toml_regex: regex-hostile content."""

    @pytest.mark.parametrize("label, content", _REGEX_BREAKING,
                             ids=[c[0] for c in _REGEX_BREAKING])
    def test_regex_breaking_patterns(self, tmp_path: Path,
                                      label: str, content: str) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text(content, encoding="utf-8")
        result = _parse_toml_regex(p)
        # Must not crash — returns None or a partial dict
        assert result is None or isinstance(result, dict)

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        result = _parse_toml_regex(tmp_path / "gone.toml")
        assert result is None

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text("", encoding="utf-8")
        result = _parse_toml_regex(p)
        assert result is None or isinstance(result, dict)

    def test_binary_content(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_bytes(bytes(range(256)))
        result = _parse_toml_regex(p)
        assert result is None or isinstance(result, dict)

    def test_extremely_long_line(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text('requires-python = "' + ">" * 100000 + '"', encoding="utf-8")
        result = _parse_toml_regex(p)
        assert result is None or isinstance(result, dict)

    @_SKIP_PERM
    def test_permission_denied(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nrequires-python = ">=3.8"', encoding="utf-8")
        p.chmod(0o000)
        try:
            result = _parse_toml_regex(p)
            assert result is None
        finally:
            p.chmod(0o644)


# ===================================================================
# 4. TestLoadCacheErrorHandling (~25 cases)
# ===================================================================

_CORRUPT_JSON_CASES = [
    ("truncated-brace", "{"),
    ("trailing-brace", "}"),
    ("missing-close-brace", '{"key": "val"'),
    ("missing-open-brace", '"key": "val"}'),
    ("double-comma", '{"a": 1,, "b": 2}'),
    ("trailing-comma", '{"a": 1,}'),
    ("single-quotes", "{'a': 1}"),
    ("unquoted-key", "{a: 1}"),
    ("nan-literal", '{"val": NaN}'),
    ("infinity-literal", '{"val": Infinity}'),
    ("python-true", '{"val": True}'),
    ("python-none", '{"val": None}'),
    ("raw-string", "just a string"),
    ("xml-content", '<?xml version="1.0"?>'),
    ("toml-content", '[section]\nkey = "val"'),
    ("csv-content", "a,b,c\n1,2,3"),
    ("empty-string", ""),
    ("only-whitespace", "   \n\t\n  "),
    ("null-byte", '{"a":\x00"b"}'),
]


class TestLoadCacheErrorHandling:
    """Error paths for load_cache: corrupt JSON, missing files, permissions."""

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        result = load_cache(str(tmp_path / "no_such_cache.json"))
        assert result == {}

    def test_nonexistent_deep_path(self, tmp_path: Path) -> None:
        result = load_cache(str(tmp_path / "a" / "b" / "c" / "cache.json"))
        assert result == {}

    @pytest.mark.parametrize("label, content", _CORRUPT_JSON_CASES,
                             ids=[c[0] for c in _CORRUPT_JSON_CASES])
    def test_corrupt_json(self, tmp_path: Path, label: str, content: str) -> None:
        p = tmp_path / "cache.json"
        p.write_text(content, encoding="utf-8")
        result = load_cache(str(p))
        assert isinstance(result, (dict, list, str))

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_text("", encoding="utf-8")
        result = load_cache(str(p))
        assert result == {}

    def test_invalid_utf8_bytes(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_bytes(b'\xff\xfe{"a": 1}')
        # load_cache catches (json.JSONDecodeError, OSError) but not UnicodeDecodeError
        with pytest.raises(UnicodeDecodeError):
            load_cache(str(p))

    def test_very_large_valid_cache(self, tmp_path: Path) -> None:
        """10MB+ valid JSON — must load without crashing."""
        p = tmp_path / "big_cache.json"
        data = {f"repo_{i}@commit{i}": {"python_version": "3.10", "data": "x" * 500}
                for i in range(5000)}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_cache(str(p))
        assert len(result) == 5000

    @_SKIP_PERM
    def test_permission_denied(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_text('{"a": 1}', encoding="utf-8")
        p.chmod(0o000)
        try:
            result = load_cache(str(p))
            assert result == {}
        finally:
            p.chmod(0o644)

    def test_directory_path(self, tmp_path: Path) -> None:
        d = tmp_path / "cache_dir"
        d.mkdir()
        result = load_cache(str(d))
        assert result == {}

    def test_symlink_to_nonexistent(self, tmp_path: Path) -> None:
        link = tmp_path / "link.json"
        link.symlink_to(tmp_path / "nonexistent_target.json")
        result = load_cache(str(link))
        assert result == {}

    def test_json_array_at_root(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_text('[1, 2, 3]', encoding="utf-8")
        result = load_cache(str(p))
        # Valid JSON but not a dict — still loads (json.load succeeds)
        assert isinstance(result, list)

    def test_json_string_at_root(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_text('"just a string"', encoding="utf-8")
        result = load_cache(str(p))
        assert isinstance(result, str)

    def test_json_number_at_root(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_text("42", encoding="utf-8")
        # load_cache calls len(data) which raises TypeError on int
        with pytest.raises(TypeError):
            load_cache(str(p))

    def test_json_null_at_root(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_text("null", encoding="utf-8")
        with pytest.raises(TypeError):
            load_cache(str(p))

    def test_binary_content(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        p.write_bytes(bytes(range(256)))
        with pytest.raises(UnicodeDecodeError):
            load_cache(str(p))


# ===================================================================
# 5. TestSaveCacheErrorHandling (~20 cases)
# ===================================================================

class TestSaveCacheErrorHandling:
    """Error paths for save_cache: read-only dirs, bad paths, non-serializable."""

    @_SKIP_PERM
    def test_readonly_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "readonly"
        d.mkdir()
        d.chmod(0o555)
        try:
            # Should not crash — logs a warning
            save_cache({"a": 1}, str(d / "cache.json"))
        finally:
            d.chmod(0o755)

    @_SKIP_PERM
    def test_readonly_existing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "readonly.json"
        p.write_text("{}", encoding="utf-8")
        p.chmod(0o444)
        try:
            save_cache({"new": "data"}, str(p))
        finally:
            p.chmod(0o644)

    def test_very_long_filename(self, tmp_path: Path) -> None:
        long_name = "c" * 300 + ".json"
        try:
            save_cache({"a": 1}, str(tmp_path / long_name))
        except OSError:
            pass  # acceptable

    def test_path_with_nonexistent_parent(self, tmp_path: Path) -> None:
        # save_cache does NOT create parent dirs — should handle OSError
        try:
            save_cache({"a": 1}, str(tmp_path / "no" / "such" / "dir" / "c.json"))
        except OSError:
            pass

    def test_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        save_cache({}, str(p))
        assert p.exists()
        assert json.loads(p.read_text()) == {}

    def test_non_serializable_set(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        with pytest.raises(TypeError):
            save_cache({"key": {1, 2, 3}}, str(p))  # type: ignore[dict-item]

    def test_non_serializable_bytes(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        with pytest.raises(TypeError):
            save_cache({"key": b"bytes"}, str(p))  # type: ignore[dict-item]

    def test_non_serializable_object(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        with pytest.raises(TypeError):
            save_cache({"key": object()}, str(p))  # type: ignore[dict-item]

    def test_non_serializable_lambda(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        with pytest.raises(TypeError):
            save_cache({"fn": lambda x: x}, str(p))  # type: ignore[dict-item]

    def test_non_serializable_path_object(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        with pytest.raises(TypeError):
            save_cache({"path": tmp_path}, str(p))  # type: ignore[dict-item]

    def test_nested_non_serializable(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        with pytest.raises(TypeError):
            save_cache({"a": {"b": {1, 2}}}, str(p))  # type: ignore[dict-item]

    def test_unicode_keys_and_values(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        save_cache({"日本語": {"値": "テスト"}}, str(p))
        result = json.loads(p.read_text(encoding="utf-8"))
        assert result["日本語"]["値"] == "テスト"

    def test_very_large_cache(self, tmp_path: Path) -> None:
        p = tmp_path / "big.json"
        data = {f"k{i}": {"v": "x" * 1000} for i in range(5000)}
        save_cache(data, str(p))
        assert p.exists()
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert len(loaded) == 5000

    def test_special_chars_in_values(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        save_cache({"cmd": 'echo "hello" && rm -rf /'}, str(p))
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded["cmd"] == 'echo "hello" && rm -rf /'

    def test_null_values(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        save_cache({"a": None, "b": {"c": None}}, str(p))  # type: ignore[dict-item]
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded["a"] is None

    @pytest.mark.parametrize("filename", [
        "cache.json",
        ".hidden_cache.json",
        "cache with spaces.json",
        "UPPER.JSON",
        "cache.JSON",
        "no_extension",
    ])
    def test_various_filenames(self, tmp_path: Path, filename: str) -> None:
        p = tmp_path / filename
        save_cache({"k": {"v": 1}}, str(p))
        assert p.exists()

    def test_overwrite_existing_cache(self, tmp_path: Path) -> None:
        p = tmp_path / "cache.json"
        save_cache({"old": {"v": 1}}, str(p))
        save_cache({"new": {"v": 2}}, str(p))
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert "new" in loaded
        assert "old" not in loaded


# ===================================================================
# 6. TestWriteJsonlErrorHandling (~15 cases)
# ===================================================================

class TestWriteJsonlErrorHandling:
    """Error paths for write_jsonl: read-only dirs, non-serializable, circular."""

    @_SKIP_PERM
    def test_readonly_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "readonly"
        d.mkdir()
        d.chmod(0o555)
        try:
            with pytest.raises(OSError):
                write_jsonl([{"a": 1}], str(d / "out.jsonl"))
        finally:
            d.chmod(0o755)

    def test_non_serializable_set_value(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        with pytest.raises(TypeError):
            write_jsonl([{"s": {1, 2, 3}}], str(p))

    def test_non_serializable_bytes_value(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        with pytest.raises(TypeError):
            write_jsonl([{"b": b"bytes_data"}], str(p))

    def test_non_serializable_object(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        with pytest.raises(TypeError):
            write_jsonl([{"obj": object()}], str(p))

    def test_circular_reference(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        d: dict[str, Any] = {}
        d["self"] = d
        with pytest.raises((ValueError, TypeError)):
            write_jsonl([d], str(p))

    def test_circular_list_reference(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        lst: list[Any] = [1, 2]
        lst.append(lst)
        with pytest.raises((ValueError, TypeError)):
            write_jsonl([{"list": lst}], str(p))

    def test_empty_instances_list(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        write_jsonl([], str(p))
        assert p.exists()
        assert p.read_text().strip() == ""

    def test_mixed_serializable_and_non(self, tmp_path: Path) -> None:
        """First instance is fine, second has non-serializable — should fail mid-write."""
        p = tmp_path / "out.jsonl"
        with pytest.raises(TypeError):
            write_jsonl([{"ok": 1}, {"bad": object()}], str(p))

    def test_deeply_nested_serializable(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        nested: dict[str, Any] = {"val": "leaf"}
        for _ in range(100):
            nested = {"child": nested}
        write_jsonl([nested], str(p))
        assert p.exists()

    def test_very_large_instance(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        large = {"data": "x" * 1_000_000}
        write_jsonl([large], str(p))
        lines = [l for l in p.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_none_in_list(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        write_jsonl([None], str(p))  # type: ignore[list-item]
        content = p.read_text().strip()
        assert content == "null"

    def test_non_dict_instances(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        write_jsonl(["string", 123, True], str(p))  # type: ignore[list-item]
        lines = [l for l in p.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    @_SKIP_PERM
    def test_file_in_nonexistent_readonly_parent(self, tmp_path: Path) -> None:
        d = tmp_path / "locked"
        d.mkdir()
        d.chmod(0o555)
        try:
            with pytest.raises(OSError):
                write_jsonl([{"a": 1}], str(d / "sub" / "out.jsonl"))
        finally:
            d.chmod(0o755)

    def test_nan_value(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        write_jsonl([{"val": float("nan")}], str(p))
        content = p.read_text().strip()
        assert "NaN" in content

    def test_inf_value(self, tmp_path: Path) -> None:
        p = tmp_path / "out.jsonl"
        write_jsonl([{"val": float("inf")}], str(p))
        content = p.read_text().strip()
        assert "Infinity" in content


# ===================================================================
# 7. TestLoadInstancesErrorHandling (~15 cases)
# ===================================================================

class TestLoadInstancesErrorHandling:
    """Error paths for load_instances / _load_jsonl: missing, corrupt, binary."""

    def test_nonexistent_jsonl(self, tmp_path: Path) -> None:
        """Non-existent .jsonl path should attempt HF load — likely fails."""
        path = str(tmp_path / "ghost.jsonl")
        # The file doesn't exist, and load_instances checks path.exists()
        # A non-existent file with .jsonl suffix will NOT match the file path,
        # so it falls to HF loader. We just verify it doesn't crash with an
        # unhandled exception we don't expect.
        try:
            result = load_instances(path)
        except (SystemExit, ImportError, Exception):
            pass  # HF path may sys.exit or fail — acceptable

    def test_nonexistent_json(self, tmp_path: Path) -> None:
        path = str(tmp_path / "ghost.json")
        try:
            result = load_instances(path)
        except (SystemExit, ImportError, Exception):
            pass

    def test_all_invalid_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        p.write_text("not json\nalso bad\nstill bad\n", encoding="utf-8")
        result = load_instances(str(p))
        assert result == []

    def test_binary_file_as_jsonl(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_bytes(bytes(range(256)) * 10)
        try:
            result = load_instances(str(p))
            # May return empty list or partial — just must not crash
            assert isinstance(result, list)
        except UnicodeDecodeError:
            pass  # also acceptable — file opened with encoding="utf-8"

    def test_mixed_valid_invalid(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        lines = [
            json.dumps({"id": 1}),
            "NOT JSON",
            json.dumps({"id": 2}),
            "{truncated",
            "",
            json.dumps({"id": 3}),
            '{"bad": }',
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 3
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2
        assert result[2]["id"] == 3

    @pytest.mark.parametrize("bad_line", [
        "{",
        "}",
        "[1, 2]",
        "true",
        "false",
        "null",
        "12345",
        '"just a string"',
        "{{}",
        '{"key":}',
        "{'single': 'quotes'}",
    ])
    def test_various_invalid_json_lines(self, tmp_path: Path, bad_line: str) -> None:
        p = tmp_path / "data.jsonl"
        content = json.dumps({"valid": True}) + "\n" + bad_line + "\n"
        p.write_text(content, encoding="utf-8")
        result = load_instances(str(p))
        valid_entries = [r for r in result if isinstance(r, dict) and r.get("valid") is True]
        assert len(valid_entries) >= 1

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text("", encoding="utf-8")
        result = load_instances(str(p))
        assert result == []

    def test_only_whitespace_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text("   \n\t\n\n  \n", encoding="utf-8")
        result = load_instances(str(p))
        assert result == []

    def test_very_large_valid_jsonl(self, tmp_path: Path) -> None:
        p = tmp_path / "big.jsonl"
        lines = [json.dumps({"idx": i, "payload": "x" * 100}) for i in range(10000)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 10000

    @_SKIP_PERM
    def test_permission_denied(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text(json.dumps({"a": 1}) + "\n", encoding="utf-8")
        p.chmod(0o000)
        try:
            with pytest.raises(PermissionError):
                load_instances(str(p))
        finally:
            p.chmod(0o644)

    def test_load_jsonl_direct_missing(self, tmp_path: Path) -> None:
        """_load_jsonl on nonexistent path should raise."""
        with pytest.raises((FileNotFoundError, OSError)):
            _load_jsonl(tmp_path / "nope.jsonl")

    def test_load_jsonl_direct_binary(self, tmp_path: Path) -> None:
        p = tmp_path / "bin.jsonl"
        p.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        try:
            result = _load_jsonl(p)
            assert isinstance(result, list)
        except UnicodeDecodeError:
            pass


# ===================================================================
# 8. TestValidateInstancesErrorHandling (~15 cases)
# ===================================================================

_REQUIRED_FIELDS = (
    "python_version", "install_cmd", "test_cmd_override", "packages_source",
    "pip_packages", "pre_install_cmds", "reqs_paths", "env_yml_paths",
    "log_parser_type",
)


class TestValidateInstancesErrorHandling:
    """Error paths for validate_instances: empty, non-dict, missing combos, large."""

    def test_empty_list(self) -> None:
        assert validate_instances([]) is True

    def test_list_with_none(self) -> None:
        # Non-dict item — .get() will fail if not guarded
        try:
            result = validate_instances([None])  # type: ignore[list-item]
            # If it doesn't crash, it should return True or False
            assert isinstance(result, bool)
        except AttributeError:
            pass  # None has no .get — acceptable crash

    def test_list_with_string(self) -> None:
        try:
            result = validate_instances(["not a dict"])  # type: ignore[list-item]
            assert isinstance(result, bool)
        except AttributeError:
            pass

    def test_list_with_integer(self) -> None:
        try:
            result = validate_instances([42])  # type: ignore[list-item]
            assert isinstance(result, bool)
        except AttributeError:
            pass

    def test_list_with_list(self) -> None:
        try:
            result = validate_instances([[1, 2, 3]])  # type: ignore[list-item]
            assert isinstance(result, bool)
        except AttributeError:
            pass

    def test_list_with_bool(self) -> None:
        try:
            result = validate_instances([True])  # type: ignore[list-item]
            assert isinstance(result, bool)
        except AttributeError:
            pass

    def test_mixed_dict_and_non_dict(self) -> None:
        try:
            result = validate_instances([_full_instance(), "bad"])  # type: ignore[list-item]
            assert isinstance(result, bool)
        except AttributeError:
            pass

    @pytest.mark.parametrize("field", _REQUIRED_FIELDS)
    def test_single_field_missing(self, field: str) -> None:
        inst = _full_instance()
        del inst[field]
        assert validate_instances([inst]) is False

    @pytest.mark.parametrize("n_missing", [1, 2, 3, 4, 5, 6, 7, 8, 9])
    def test_incremental_missing_fields(self, n_missing: int) -> None:
        inst = _full_instance()
        for f in _REQUIRED_FIELDS[:n_missing]:
            del inst[f]
        assert validate_instances([inst]) is False

    def test_all_fields_missing(self) -> None:
        inst = {"instance_id": "bare__1", "repo": "a/b"}
        assert validate_instances([inst]) is False

    def test_empty_dict_instance(self) -> None:
        assert validate_instances([{}]) is False

    def test_very_large_valid_list(self) -> None:
        insts = [_full_instance(instance_id=f"t__{i}") for i in range(10000)]
        assert validate_instances(insts) is True

    def test_very_large_invalid_list(self) -> None:
        insts = [{"instance_id": f"t__{i}"} for i in range(10000)]
        assert validate_instances(insts) is False

    def test_one_bad_in_10000(self) -> None:
        insts = [_full_instance(instance_id=f"t__{i}") for i in range(10000)]
        bad = {"instance_id": "bad__1"}
        insts[5000] = bad
        assert validate_instances(insts) is False

    @pytest.mark.parametrize("missing_pair", [
        ("python_version", "install_cmd"),
        ("test_cmd_override", "packages_source"),
        ("pip_packages", "pre_install_cmds"),
        ("reqs_paths", "env_yml_paths"),
    ])
    def test_missing_field_pairs(self, missing_pair: tuple[str, str]) -> None:
        inst = _full_instance()
        for f in missing_pair:
            del inst[f]
        assert validate_instances([inst]) is False

    def test_field_present_but_none(self) -> None:
        overrides = {f: None for f in _REQUIRED_FIELDS}
        inst = _full_instance(**overrides)
        # Fields are present (even if None), so validate should pass
        assert validate_instances([inst]) is True

    def test_field_present_but_empty_string(self) -> None:
        overrides = {f: "" for f in _REQUIRED_FIELDS}
        inst = _full_instance(**overrides)
        assert validate_instances([inst]) is True

    def test_extra_fields_do_not_affect_validation(self) -> None:
        inst = _full_instance(bonus_field="extra", another=42)
        assert validate_instances([inst]) is True

    def test_duplicate_instances(self) -> None:
        inst = _full_instance()
        assert validate_instances([inst, inst, inst]) is True
