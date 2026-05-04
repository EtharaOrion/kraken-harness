from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (  # noqa: E402
    load_instances,
    write_jsonl,
    load_cache,
    save_cache,
    validate_instances,
    REQUIRED_ENRICHMENT_FIELDS,
)
from detect_repo_specs import _load_jsonl  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_instance(**overrides: Any) -> dict[str, Any]:
    base = {
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


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ===================================================================
# 1. write_jsonl + read back (~40 cases)
# ===================================================================

class TestWriteJsonl:

    def test_single_instance(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        inst = [{"a": 1}]
        write_jsonl(inst, str(p))
        assert json.loads(p.read_text().strip()) == {"a": 1}

    def test_multiple_instances(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        insts = [{"i": i} for i in range(5)]
        write_jsonl(insts, str(p))
        lines = [l for l in p.read_text().splitlines() if l.strip()]
        assert len(lines) == 5
        for i, line in enumerate(lines):
            assert json.loads(line) == {"i": i}

    def test_empty_list(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([], str(p))
        assert p.read_text().strip() == ""

    def test_creates_parent_dirs(self, tmp_path: Path):
        p = tmp_path / "a" / "b" / "c" / "out.jsonl"
        write_jsonl([{"x": 1}], str(p))
        assert p.exists()

    def test_unicode_values(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        inst = [{"msg": "日本語テスト"}]
        write_jsonl(inst, str(p))
        loaded = json.loads(p.read_text(encoding="utf-8").strip())
        assert loaded["msg"] == "日本語テスト"

    def test_emoji_values(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([{"emoji": "🎉🚀"}], str(p))
        loaded = json.loads(p.read_text(encoding="utf-8").strip())
        assert loaded["emoji"] == "🎉🚀"

    def test_special_chars(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([{"c": 'line1\nline2\ttab"quote'}], str(p))
        lines = [l for l in p.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert json.loads(lines[0])["c"] == 'line1\nline2\ttab"quote'

    def test_nested_structure(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        nested = {"a": {"b": {"c": [1, 2, {"d": True}]}}}
        write_jsonl([nested], str(p))
        assert json.loads(p.read_text().strip()) == nested

    def test_boolean_and_null(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([{"t": True, "f": False, "n": None}], str(p))
        loaded = json.loads(p.read_text().strip())
        assert loaded == {"t": True, "f": False, "n": None}

    def test_numeric_types(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([{"int": 42, "float": 3.14, "neg": -7}], str(p))
        loaded = json.loads(p.read_text().strip())
        assert loaded["int"] == 42
        assert abs(loaded["float"] - 3.14) < 1e-9
        assert loaded["neg"] == -7

    def test_empty_dict(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([{}], str(p))
        assert json.loads(p.read_text().strip()) == {}

    def test_empty_string_values(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([{"a": "", "b": ""}], str(p))
        loaded = json.loads(p.read_text().strip())
        assert loaded == {"a": "", "b": ""}

    def test_list_values(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([{"items": [1, "two", 3.0]}], str(p))
        loaded = json.loads(p.read_text().strip())
        assert loaded["items"] == [1, "two", 3.0]

    def test_overwrite_existing(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        write_jsonl([{"old": 1}], str(p))
        write_jsonl([{"new": 2}], str(p))
        loaded = json.loads(p.read_text().strip())
        assert loaded == {"new": 2}

    def test_large_instance_count(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        insts = [{"idx": i, "data": f"val_{i}"} for i in range(100)]
        write_jsonl(insts, str(p))
        lines = [l for l in p.read_text().splitlines() if l.strip()]
        assert len(lines) == 100

    def test_long_string_value(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        long_str = "x" * 10000
        write_jsonl([{"s": long_str}], str(p))
        loaded = json.loads(p.read_text().strip())
        assert loaded["s"] == long_str

    @pytest.mark.parametrize("suffix", [".jsonl", ".json"])
    def test_file_suffix(self, tmp_path: Path, suffix: str):
        p = tmp_path / f"data{suffix}"
        write_jsonl([{"a": 1}], str(p))
        assert p.exists()

    @pytest.mark.parametrize("key", [
        "simple", "with space", "with-dash", "with_under", "with.dot",
        "UPPER", "MiXeD", "123numeric", "a" * 200,
    ])
    def test_various_keys(self, tmp_path: Path, key: str):
        p = tmp_path / "out.jsonl"
        write_jsonl([{key: "v"}], str(p))
        loaded = json.loads(p.read_text().strip())
        assert loaded[key] == "v"

    @pytest.mark.parametrize("val", [
        "", "hello", 0, 1, -1, 3.14, True, False, None,
        [], [1, 2], {}, {"nested": True},
    ])
    def test_various_values(self, tmp_path: Path, val: Any):
        p = tmp_path / "out.jsonl"
        write_jsonl([{"v": val}], str(p))
        loaded = json.loads(p.read_text().strip())
        assert loaded["v"] == val

    def test_roundtrip_full_instance(self, tmp_path: Path):
        p = tmp_path / "out.jsonl"
        inst = _full_instance()
        write_jsonl([inst], str(p))
        loaded = _load_jsonl(p)
        assert loaded == [inst]


# ===================================================================
# 2. load_instances from JSONL (~40 cases)
# ===================================================================

class TestLoadInstances:

    def test_load_single_jsonl(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        p.write_text(json.dumps({"a": 1}) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert result == [{"a": 1}]

    def test_load_multiple_jsonl(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        lines = [json.dumps({"i": i}) for i in range(3)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 3

    def test_load_json_suffix(self, tmp_path: Path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"a": 1}) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert result == [{"a": 1}]

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        p.write_text("", encoding="utf-8")
        result = load_instances(str(p))
        assert result == []

    def test_skips_empty_lines(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        content = json.dumps({"a": 1}) + "\n\n\n" + json.dumps({"b": 2}) + "\n"
        p.write_text(content, encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 2

    def test_skips_whitespace_only_lines(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        content = json.dumps({"a": 1}) + "\n   \n\t\n" + json.dumps({"b": 2}) + "\n"
        p.write_text(content, encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 2

    def test_skips_invalid_json(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        content = json.dumps({"a": 1}) + "\nNOT_JSON\n" + json.dumps({"b": 2}) + "\n"
        p.write_text(content, encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 2
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}

    def test_all_invalid_json(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        p.write_text("bad1\nbad2\nbad3\n", encoding="utf-8")
        result = load_instances(str(p))
        assert result == []

    def test_unicode_content(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        p.write_text(json.dumps({"name": "日本語"}, ensure_ascii=False) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert result[0]["name"] == "日本語"

    def test_nested_content(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        nested = {"a": {"b": [1, 2, {"c": 3}]}}
        p.write_text(json.dumps(nested) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert result == [nested]

    @pytest.mark.parametrize("count", [1, 5, 10, 50, 100])
    def test_various_counts(self, tmp_path: Path, count: int):
        p = tmp_path / "data.jsonl"
        lines = [json.dumps({"idx": i}) for i in range(count)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == count

    @pytest.mark.parametrize("n_empty", [1, 3, 5, 10])
    def test_leading_empty_lines(self, tmp_path: Path, n_empty: int):
        p = tmp_path / "data.jsonl"
        content = "\n" * n_empty + json.dumps({"a": 1}) + "\n"
        p.write_text(content, encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 1

    @pytest.mark.parametrize("n_empty", [1, 3, 5, 10])
    def test_trailing_empty_lines(self, tmp_path: Path, n_empty: int):
        p = tmp_path / "data.jsonl"
        content = json.dumps({"a": 1}) + "\n" + "\n" * n_empty
        p.write_text(content, encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 1

    @pytest.mark.parametrize("bad_line", [
        "{bad json",
        "just a string",
        "[1, 2, 3]",
        "12345",
        "'single quotes'",
        "True",
        "null",
    ])
    def test_various_invalid_json_lines(self, tmp_path: Path, bad_line: str):
        p = tmp_path / "data.jsonl"
        content = json.dumps({"valid": True}) + "\n" + bad_line + "\n"
        p.write_text(content, encoding="utf-8")
        result = load_instances(str(p))
        assert any(isinstance(r, dict) and r.get("valid") is True for r in result)

    def test_load_enriched_instance(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        inst = _full_instance()
        p.write_text(json.dumps(inst) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert result == [inst]

    def test_mixed_valid_invalid(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        lines = [
            json.dumps({"a": 1}),
            "INVALID",
            json.dumps({"b": 2}),
            "{incomplete",
            json.dumps({"c": 3}),
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = load_instances(str(p))
        assert len(result) == 3


# ===================================================================
# 2b. _load_jsonl direct tests
# ===================================================================

class TestLoadJsonl:

    def test_basic(self, tmp_path: Path):
        p = tmp_path / "f.jsonl"
        p.write_text(json.dumps({"k": "v"}) + "\n", encoding="utf-8")
        assert _load_jsonl(p) == [{"k": "v"}]

    def test_empty(self, tmp_path: Path):
        p = tmp_path / "f.jsonl"
        p.write_text("", encoding="utf-8")
        assert _load_jsonl(p) == []

    def test_skip_blank_lines(self, tmp_path: Path):
        p = tmp_path / "f.jsonl"
        p.write_text("\n\n" + json.dumps({"x": 1}) + "\n\n", encoding="utf-8")
        assert _load_jsonl(p) == [{"x": 1}]

    def test_skip_invalid(self, tmp_path: Path):
        p = tmp_path / "f.jsonl"
        p.write_text("BAD\n" + json.dumps({"x": 1}) + "\n", encoding="utf-8")
        assert _load_jsonl(p) == [{"x": 1}]

    def test_preserves_order(self, tmp_path: Path):
        p = tmp_path / "f.jsonl"
        lines = [json.dumps({"i": i}) for i in range(10)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = _load_jsonl(p)
        assert [r["i"] for r in result] == list(range(10))


# ===================================================================
# 3. load_cache (~30 cases)
# ===================================================================

class TestLoadCache:

    def test_missing_file(self, tmp_path: Path):
        result = load_cache(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        p.write_text("", encoding="utf-8")
        result = load_cache(str(p))
        assert result == {}

    def test_corrupted_json(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        p.write_text("{bad json", encoding="utf-8")
        result = load_cache(str(p))
        assert result == {}

    def test_valid_cache(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo1": {"python_version": "3.10"}}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_cache(str(p))
        assert result == data

    def test_empty_dict_cache(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        p.write_text("{}", encoding="utf-8")
        result = load_cache(str(p))
        assert result == {}

    def test_nested_cache(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"specs": {"a": 1, "b": [2, 3]}}}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_cache(str(p))
        assert result == data

    def test_unicode_cache(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"name": "日本語"}}
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = load_cache(str(p))
        assert result["repo"]["name"] == "日本語"

    def test_large_cache(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {f"repo_{i}": {"val": i} for i in range(200)}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_cache(str(p))
        assert len(result) == 200

    @pytest.mark.parametrize("bad_content", [
        "{incomplete",
        "{'single': 'quotes'}",
        "{trailing comma,}",
        "not json at all",
        "}{",
        "",
    ])
    def test_corrupted_content_returns_empty(self, tmp_path: Path, bad_content: str):
        p = tmp_path / "cache.json"
        p.write_text(bad_content, encoding="utf-8")
        result = load_cache(str(p))
        assert result == {}

    @pytest.mark.parametrize("valid_content,expected", [
        ('[]', []),
        ('"string"', "string"),
        ('[1,2,3]', [1, 2, 3]),
    ])
    def test_non_dict_valid_json(self, tmp_path: Path, valid_content: str, expected: Any):
        p = tmp_path / "cache.json"
        p.write_text(valid_content, encoding="utf-8")
        result = load_cache(str(p))
        assert result == expected

    def test_multiple_keys(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {
            "repo_a": {"python_version": "3.9"},
            "repo_b": {"python_version": "3.10"},
            "repo_c": {"python_version": "3.11"},
        }
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_cache(str(p))
        assert result == data

    def test_cache_with_all_enrichment_fields(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        inst = _full_instance()
        data = {"test__1": inst}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_cache(str(p))
        assert result["test__1"] == inst

    def test_nonexistent_deep_path(self, tmp_path: Path):
        result = load_cache(str(tmp_path / "a" / "b" / "c" / "cache.json"))
        assert result == {}

    @pytest.mark.parametrize("n", [0, 1, 5, 10, 50])
    def test_cache_sizes(self, tmp_path: Path, n: int):
        p = tmp_path / "cache.json"
        data = {f"k{i}": {"v": i} for i in range(n)}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_cache(str(p))
        assert len(result) == n


# ===================================================================
# 4. save_cache + load_cache roundtrip (~30 cases)
# ===================================================================

class TestSaveCacheRoundtrip:

    def test_basic_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"val": 1}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_empty_dict_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        save_cache({}, str(p))
        assert load_cache(str(p)) == {}

    def test_unicode_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"name": "日本語テスト🎉"}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_nested_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"a": {"b": {"c": {"d": [1, 2, 3]}}}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_large_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {f"repo_{i}": {"specs": {"v": i, "name": f"n_{i}"}} for i in range(100)}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_overwrite_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        save_cache({"old": {"v": 1}}, str(p))
        save_cache({"new": {"v": 2}}, str(p))
        result = load_cache(str(p))
        assert "new" in result
        assert "old" not in result

    def test_boolean_values_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"a": True, "b": False}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_null_values_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"a": None}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_list_values_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"pkgs": ["numpy", "scipy", "pandas"]}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_numeric_values_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"int": 42, "float": 3.14, "neg": -1}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_enriched_instance_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        inst = _full_instance()
        data = {inst["instance_id"]: inst}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_save_creates_file(self, tmp_path: Path):
        p = tmp_path / "new_cache.json"
        assert not p.exists()
        save_cache({"k": {"v": 1}}, str(p))
        assert p.exists()

    def test_save_indented(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        save_cache({"repo": {"v": 1}}, str(p))
        content = p.read_text(encoding="utf-8")
        assert "\n" in content

    def test_special_string_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"cmd": 'echo "hello world" && pip install \'pkg\''}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    @pytest.mark.parametrize("key", [
        "simple", "with-dash", "with_under", "with.dot", "UPPER",
        "a/b/c", "repo__instance", "123", "",
    ])
    def test_various_cache_keys(self, tmp_path: Path, key: str):
        p = tmp_path / "cache.json"
        data = {key: {"val": 1}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    @pytest.mark.parametrize("n", [1, 10, 50])
    def test_roundtrip_sizes(self, tmp_path: Path, n: int):
        p = tmp_path / "cache.json"
        data = {f"r{i}": {"v": i} for i in range(n)}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data

    def test_empty_string_values_roundtrip(self, tmp_path: Path):
        p = tmp_path / "cache.json"
        data = {"repo": {"a": "", "b": ""}}
        save_cache(data, str(p))
        assert load_cache(str(p)) == data


# ===================================================================
# 5. validate_instances (~60 cases)
# ===================================================================

class TestValidateInstances:

    def test_all_fields_present(self):
        assert validate_instances([_full_instance()]) is True

    def test_empty_list(self):
        assert validate_instances([]) is True

    def test_multiple_valid(self):
        insts = [_full_instance(instance_id=f"t__{i}") for i in range(5)]
        assert validate_instances(insts) is True

    def test_missing_all_enrichment_fields(self):
        inst = {"instance_id": "t__1", "repo": "a/b"}
        assert validate_instances([inst]) is False

    def test_one_valid_one_invalid(self):
        insts = [_full_instance(), {"instance_id": "bad", "repo": "x/y"}]
        assert validate_instances(insts) is False

    @pytest.mark.parametrize("field", REQUIRED_ENRICHMENT_FIELDS)
    def test_missing_single_field(self, field: str):
        inst = _full_instance()
        del inst[field]
        assert validate_instances([inst]) is False

    @pytest.mark.parametrize("field", REQUIRED_ENRICHMENT_FIELDS)
    def test_present_single_field_only(self, field: str):
        inst = {"instance_id": "t__1", field: "some_value"}
        result = validate_instances([inst])
        assert result is False

    @pytest.mark.parametrize("field", REQUIRED_ENRICHMENT_FIELDS)
    def test_all_except_one(self, field: str):
        inst = _full_instance()
        del inst[field]
        assert validate_instances([inst]) is False

    def test_extra_fields_ok(self):
        inst = _full_instance(extra_field="bonus")
        assert validate_instances([inst]) is True

    def test_empty_string_field_values(self):
        inst = _full_instance(python_version="", install_cmd="")
        assert validate_instances([inst]) is True

    def test_none_field_values(self):
        inst = _full_instance(python_version=None, install_cmd=None)
        assert validate_instances([inst]) is True

    def test_10_valid_instances(self):
        insts = [_full_instance(instance_id=f"t__{i}") for i in range(10)]
        assert validate_instances(insts) is True

    def test_10_invalid_instances(self):
        insts = [{"instance_id": f"t__{i}"} for i in range(10)]
        assert validate_instances(insts) is False

    def test_mixed_valid_invalid(self):
        valid = _full_instance(instance_id="good")
        invalid = {"instance_id": "bad"}
        assert validate_instances([valid, invalid]) is False

    def test_no_instance_id(self):
        inst = _full_instance()
        del inst["instance_id"]
        assert validate_instances([inst]) is True

    @pytest.mark.parametrize("missing_pair", [
        ("python_version", "install_cmd"),
        ("test_cmd_override", "packages_source"),
        ("pip_packages", "pre_install_cmds"),
        ("reqs_paths", "env_yml_paths"),
        ("log_parser_type", "python_version"),
    ])
    def test_missing_two_fields(self, missing_pair: tuple[str, str]):
        inst = _full_instance()
        for f in missing_pair:
            del inst[f]
        assert validate_instances([inst]) is False

    @pytest.mark.parametrize("n_missing", [1, 2, 3, 4, 5, 6, 7, 8, 9])
    def test_missing_n_fields(self, n_missing: int):
        inst = _full_instance()
        for f in REQUIRED_ENRICHMENT_FIELDS[:n_missing]:
            del inst[f]
        assert validate_instances([inst]) is False

    def test_all_fields_empty_lists(self):
        inst = _full_instance(
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
        )
        assert validate_instances([inst]) is True

    def test_all_fields_empty_strings(self):
        overrides = {f: "" for f in REQUIRED_ENRICHMENT_FIELDS}
        inst = _full_instance(**overrides)
        assert validate_instances([inst]) is True

    def test_large_batch_all_valid(self):
        insts = [_full_instance(instance_id=f"t__{i}") for i in range(100)]
        assert validate_instances(insts) is True

    def test_large_batch_one_invalid(self):
        insts = [_full_instance(instance_id=f"t__{i}") for i in range(100)]
        bad = {"instance_id": "bad"}
        insts.append(bad)
        assert validate_instances(insts) is False

    def test_instance_without_repo_field(self):
        inst = _full_instance()
        del inst["repo"]
        assert validate_instances([inst]) is True

    def test_numeric_field_values(self):
        inst = _full_instance(python_version=310, log_parser_type=0)
        assert validate_instances([inst]) is True


# ===================================================================
# 6. write_jsonl + load_instances roundtrip
# ===================================================================

class TestWriteLoadRoundtrip:

    def test_basic_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        insts = [{"a": 1}, {"b": 2}]
        write_jsonl(insts, str(p))
        assert load_instances(str(p)) == insts

    def test_enriched_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        insts = [_full_instance(instance_id=f"t__{i}") for i in range(5)]
        write_jsonl(insts, str(p))
        assert load_instances(str(p)) == insts

    def test_unicode_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        insts = [{"msg": "café"}, {"msg": "日本語"}, {"msg": "🎉"}]
        write_jsonl(insts, str(p))
        assert load_instances(str(p)) == insts

    def test_empty_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        write_jsonl([], str(p))
        assert load_instances(str(p)) == []

    def test_large_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        insts = [{"idx": i, "val": f"v{i}"} for i in range(200)]
        write_jsonl(insts, str(p))
        result = load_instances(str(p))
        assert len(result) == 200
        assert result[0] == {"idx": 0, "val": "v0"}
        assert result[-1] == {"idx": 199, "val": "v199"}

    @pytest.mark.parametrize("n", [1, 2, 10, 25, 50])
    def test_roundtrip_counts(self, tmp_path: Path, n: int):
        p = tmp_path / "data.jsonl"
        insts = [{"i": i} for i in range(n)]
        write_jsonl(insts, str(p))
        assert load_instances(str(p)) == insts

    def test_nested_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        insts = [{"deep": {"a": {"b": {"c": [1, 2, 3]}}}}]
        write_jsonl(insts, str(p))
        assert load_instances(str(p)) == insts

    def test_special_chars_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        insts = [{"cmd": 'echo "hello" && cat file.txt | grep \'pattern\''}]
        write_jsonl(insts, str(p))
        assert load_instances(str(p)) == insts

    def test_json_suffix_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.json"
        insts = [{"a": 1}]
        write_jsonl(insts, str(p))
        assert load_instances(str(p)) == insts

    def test_validate_after_roundtrip(self, tmp_path: Path):
        p = tmp_path / "data.jsonl"
        insts = [_full_instance(instance_id=f"t__{i}") for i in range(3)]
        write_jsonl(insts, str(p))
        loaded = load_instances(str(p))
        assert validate_instances(loaded) is True
