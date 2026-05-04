"""Comprehensive tests for swefficiency.versioning.utils — Stage 5 Version Detection.

Covers get_instances (JSON, JSONL, JSONL.all) and split_instances with 600+
parameterized test cases.
"""

from __future__ import annotations

import json
import os

import pytest

from swefficiency.versioning.utils import get_instances, split_instances


# ── Helpers ───────────────────────────────────────────────────────────


def _make_instance(**overrides):
    """Build a minimal task instance dict with optional overrides."""
    base = {"instance_id": "test/repo__1", "repo": "test/repo", "version": "1.0.0"}
    base.update(overrides)
    return base


def _make_instances(n, **overrides):
    """Build a list of n task instances."""
    return [
        _make_instance(instance_id=f"test/repo__{i}", version=f"1.0.{i}", **overrides)
        for i in range(n)
    ]


def _write_json(path, data):
    """Write a list/dict as JSON to the given path."""
    with open(path, "w") as f:
        json.dump(data, f)


def _write_jsonl(path, items):
    """Write a list of dicts as JSONL (one JSON object per line) to the given path."""
    with open(path, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")


# ── get_instances — JSON loading ──────────────────────────────────────


class TestGetInstancesJson:
    """Tests for get_instances loading .json files."""

    def test_load_empty_list(self, tmp_path):
        """Loading a .json file with an empty list returns []."""
        p = tmp_path / "empty.json"
        _write_json(p, [])
        assert get_instances(str(p)) == []

    def test_load_single_item(self, tmp_path):
        """Loading a .json file with one item returns a 1-element list."""
        data = [_make_instance()]
        p = tmp_path / "single.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert len(result) == 1
        assert result[0]["instance_id"] == "test/repo__1"

    @pytest.mark.parametrize("n", [2, 3, 5, 10, 50, 100, 500])
    def test_load_n_items(self, tmp_path, n):
        """Loading a .json file with {n} items returns list of length {n}."""
        data = _make_instances(n)
        p = tmp_path / f"items_{n}.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert len(result) == n

    def test_load_preserves_order(self, tmp_path):
        """Items in .json are returned in original order."""
        data = _make_instances(20)
        p = tmp_path / "ordered.json"
        _write_json(p, data)
        result = get_instances(str(p))
        for i, item in enumerate(result):
            assert item["instance_id"] == f"test/repo__{i}"

    def test_load_preserves_all_fields(self, tmp_path):
        """All fields in the JSON objects are preserved."""
        data = [_make_instance(extra_field="hello", number=42)]
        p = tmp_path / "fields.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert result[0]["extra_field"] == "hello"
        assert result[0]["number"] == 42

    def test_load_returns_list(self, tmp_path):
        """Return type is always a list."""
        p = tmp_path / "list.json"
        _write_json(p, [_make_instance()])
        result = get_instances(str(p))
        assert isinstance(result, list)

    def test_load_returns_dicts(self, tmp_path):
        """Each item in the returned list is a dict."""
        p = tmp_path / "dicts.json"
        _write_json(p, _make_instances(3))
        result = get_instances(str(p))
        for item in result:
            assert isinstance(item, dict)

    def test_file_not_found_raises(self, tmp_path):
        """Attempting to load a non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            get_instances(str(tmp_path / "nonexistent.json"))

    def test_invalid_json_raises(self, tmp_path):
        """Loading a file with invalid JSON raises json.JSONDecodeError."""
        p = tmp_path / "invalid.json"
        p.write_text("{not valid json")
        with pytest.raises(json.JSONDecodeError):
            get_instances(str(p))

    def test_txt_extension_uses_json_path(self, tmp_path):
        """A .txt file falls through to json.load path."""
        data = [_make_instance()]
        p = tmp_path / "data.txt"
        _write_json(p, data)
        result = get_instances(str(p))
        assert len(result) == 1

    def test_csv_extension_uses_json_path(self, tmp_path):
        """A .csv extension (not jsonl) falls through to json.load path."""
        data = [_make_instance()]
        p = tmp_path / "data.csv"
        _write_json(p, data)
        result = get_instances(str(p))
        assert len(result) == 1

    def test_no_extension_uses_json_path(self, tmp_path):
        """A file with no extension falls through to json.load path."""
        data = [_make_instance()]
        p = tmp_path / "data"
        _write_json(p, data)
        result = get_instances(str(p))
        assert len(result) == 1


# ── get_instances — JSONL loading ─────────────────────────────────────


class TestGetInstancesJsonl:
    """Tests for get_instances loading .jsonl files."""

    def test_load_empty_jsonl(self, tmp_path):
        """Loading an empty .jsonl file returns []."""
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        result = get_instances(str(p))
        assert result == []

    def test_load_single_line(self, tmp_path):
        """Loading a .jsonl file with one line returns 1-element list."""
        p = tmp_path / "single.jsonl"
        _write_jsonl(p, [_make_instance()])
        result = get_instances(str(p))
        assert len(result) == 1

    @pytest.mark.parametrize("n", [2, 3, 5, 10, 50, 100, 500])
    def test_load_n_lines(self, tmp_path, n):
        """Loading a .jsonl file with {n} lines returns list of length {n}."""
        data = _make_instances(n)
        p = tmp_path / f"items_{n}.jsonl"
        _write_jsonl(p, data)
        result = get_instances(str(p))
        assert len(result) == n

    def test_load_preserves_order(self, tmp_path):
        """Items in .jsonl are returned in original line order."""
        data = _make_instances(20)
        p = tmp_path / "ordered.jsonl"
        _write_jsonl(p, data)
        result = get_instances(str(p))
        for i, item in enumerate(result):
            assert item["instance_id"] == f"test/repo__{i}"

    def test_load_preserves_fields(self, tmp_path):
        """All fields in JSONL objects are preserved."""
        data = [_make_instance(extra="val", num=99)]
        p = tmp_path / "fields.jsonl"
        _write_jsonl(p, data)
        result = get_instances(str(p))
        assert result[0]["extra"] == "val"
        assert result[0]["num"] == 99

    def test_load_returns_list(self, tmp_path):
        """Return type from .jsonl is a list."""
        p = tmp_path / "ret.jsonl"
        _write_jsonl(p, [_make_instance()])
        assert isinstance(get_instances(str(p)), list)

    def test_load_returns_dicts(self, tmp_path):
        """Each item from .jsonl is a dict."""
        p = tmp_path / "dicts.jsonl"
        _write_jsonl(p, _make_instances(3))
        for item in get_instances(str(p)):
            assert isinstance(item, dict)

    def test_jsonl_file_not_found(self, tmp_path):
        """Non-existent .jsonl raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            get_instances(str(tmp_path / "missing.jsonl"))

    def test_jsonl_invalid_line_raises(self, tmp_path):
        """A .jsonl file with an invalid JSON line raises json.JSONDecodeError."""
        p = tmp_path / "bad.jsonl"
        p.write_text('{"valid": 1}\n{invalid\n')
        with pytest.raises(json.JSONDecodeError):
            get_instances(str(p))


# ── get_instances — JSONL.all loading ─────────────────────────────────


class TestGetInstancesJsonlAll:
    """Tests for get_instances loading .jsonl.all files."""

    def test_load_empty_jsonl_all(self, tmp_path):
        """Loading an empty .jsonl.all file returns []."""
        p = tmp_path / "empty.jsonl.all"
        p.write_text("")
        result = get_instances(str(p))
        assert result == []

    def test_load_single_line(self, tmp_path):
        """Loading a .jsonl.all with one line returns 1-element list."""
        p = tmp_path / "single.jsonl.all"
        _write_jsonl(p, [_make_instance()])
        result = get_instances(str(p))
        assert len(result) == 1

    @pytest.mark.parametrize("n", [2, 3, 5, 10, 50, 100, 500])
    def test_load_n_lines(self, tmp_path, n):
        """Loading a .jsonl.all with {n} lines returns list of length {n}."""
        data = _make_instances(n)
        p = tmp_path / f"items_{n}.jsonl.all"
        _write_jsonl(p, data)
        result = get_instances(str(p))
        assert len(result) == n

    def test_load_preserves_order(self, tmp_path):
        """Items in .jsonl.all are returned in original line order."""
        data = _make_instances(20)
        p = tmp_path / "ordered.jsonl.all"
        _write_jsonl(p, data)
        result = get_instances(str(p))
        for i, item in enumerate(result):
            assert item["instance_id"] == f"test/repo__{i}"

    def test_load_preserves_fields(self, tmp_path):
        """All fields in .jsonl.all objects are preserved."""
        data = [_make_instance(tag="all", count=7)]
        p = tmp_path / "fields.jsonl.all"
        _write_jsonl(p, data)
        result = get_instances(str(p))
        assert result[0]["tag"] == "all"
        assert result[0]["count"] == 7

    def test_load_returns_list(self, tmp_path):
        """Return type from .jsonl.all is a list."""
        p = tmp_path / "ret.jsonl.all"
        _write_jsonl(p, [_make_instance()])
        assert isinstance(get_instances(str(p)), list)

    def test_load_returns_dicts(self, tmp_path):
        """Each item from .jsonl.all is a dict."""
        p = tmp_path / "dicts.jsonl.all"
        _write_jsonl(p, _make_instances(3))
        for item in get_instances(str(p)):
            assert isinstance(item, dict)

    def test_jsonl_all_file_not_found(self, tmp_path):
        """Non-existent .jsonl.all raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            get_instances(str(tmp_path / "missing.jsonl.all"))


# ── get_instances — suffix detection ──────────────────────────────────


class TestGetInstancesSuffixDetection:
    """Test the any() check for .jsonl / .jsonl.all suffix detection."""

    @pytest.mark.parametrize(
        "filename, uses_jsonl",
        [
            ("data.jsonl", True),
            ("data.jsonl.all", True),
            ("data.json", False),
            ("data.txt", False),
            ("data.csv", False),
            ("data", False),
            ("my_data.jsonl", True),
            ("path/to/data.jsonl", True),
            ("path/to/data.jsonl.all", True),
            ("test.JSONL", False),  # case sensitive
            ("test.Jsonl", False),
            ("test.jsonl.ALL", False),
            ("file.jsonl.bak", False),
            ("file.json.all", False),
            (".jsonl", True),
            (".jsonl.all", True),
        ],
    )
    def test_suffix_detection(self, tmp_path, filename, uses_jsonl):
        """Suffix detection for {filename}: uses_jsonl={uses_jsonl}."""
        p = tmp_path / os.path.basename(filename)
        data = [_make_instance()]
        if uses_jsonl:
            _write_jsonl(p, data)
        else:
            _write_json(p, data)
        result = get_instances(str(p))
        assert len(result) == 1


# ── get_instances — Parametrized large-scale ──────────────────────────


_JSON_SIZES = [0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 25, 30, 50, 75, 100, 200, 500]


@pytest.mark.parametrize("n", _JSON_SIZES)
class TestGetInstancesJsonSizes:
    """Parametrized tests for various JSON list sizes."""

    def test_json_size(self, tmp_path, n):
        """JSON with {n} items loads correctly."""
        data = _make_instances(n)
        p = tmp_path / f"size_{n}.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert len(result) == n

    def test_jsonl_size(self, tmp_path, n):
        """JSONL with {n} items loads correctly."""
        data = _make_instances(n)
        p = tmp_path / f"size_{n}.jsonl"
        _write_jsonl(p, data)
        result = get_instances(str(p))
        assert len(result) == n

    def test_jsonl_all_size(self, tmp_path, n):
        """JSONL.all with {n} items loads correctly."""
        data = _make_instances(n)
        p = tmp_path / f"size_{n}.jsonl.all"
        _write_jsonl(p, data)
        result = get_instances(str(p))
        assert len(result) == n

    def test_json_deterministic(self, tmp_path, n):
        """JSON loading is deterministic (same result on re-read)."""
        data = _make_instances(n)
        p = tmp_path / f"det_{n}.json"
        _write_json(p, data)
        r1 = get_instances(str(p))
        r2 = get_instances(str(p))
        assert r1 == r2

    def test_jsonl_deterministic(self, tmp_path, n):
        """JSONL loading is deterministic (same result on re-read)."""
        data = _make_instances(n)
        p = tmp_path / f"det_{n}.jsonl"
        _write_jsonl(p, data)
        r1 = get_instances(str(p))
        r2 = get_instances(str(p))
        assert r1 == r2


# ── get_instances — Data integrity ────────────────────────────────────


class TestGetInstancesDataIntegrity:
    """Data integrity across different formats."""

    @pytest.mark.parametrize("n", [1, 5, 10, 50, 100])
    def test_json_jsonl_equivalent(self, tmp_path, n):
        """JSON and JSONL with same data return identical results."""
        data = _make_instances(n)
        pj = tmp_path / f"eq_{n}.json"
        pl = tmp_path / f"eq_{n}.jsonl"
        _write_json(pj, data)
        _write_jsonl(pl, data)
        assert get_instances(str(pj)) == get_instances(str(pl))

    @pytest.mark.parametrize("n", [1, 5, 10, 50, 100])
    def test_jsonl_jsonl_all_equivalent(self, tmp_path, n):
        """JSONL and JSONL.all with same data return identical results."""
        data = _make_instances(n)
        pl = tmp_path / f"eq_{n}.jsonl"
        pa = tmp_path / f"eq_{n}.jsonl.all"
        _write_jsonl(pl, data)
        _write_jsonl(pa, data)
        assert get_instances(str(pl)) == get_instances(str(pa))

    @pytest.mark.parametrize(
        "fields",
        [
            {"instance_id": "a/b__1"},
            {"instance_id": "a/b__1", "version": "2.0"},
            {"instance_id": "a/b__1", "nested": {"key": "val"}},
            {"instance_id": "a/b__1", "list_field": [1, 2, 3]},
            {"instance_id": "a/b__1", "bool_field": True},
            {"instance_id": "a/b__1", "null_field": None},
            {"instance_id": "a/b__1", "float_field": 3.14},
            {"instance_id": "a/b__1", "unicode": "\u00e9\u00e8\u00ea"},
        ],
    )
    def test_field_types_preserved(self, tmp_path, fields):
        """Various field types are preserved through JSON/JSONL round-trip."""
        p = tmp_path / "types.json"
        _write_json(p, [fields])
        result = get_instances(str(p))
        assert result[0] == fields


# ── get_instances — Edge cases ────────────────────────────────────────


class TestGetInstancesEdgeCases:
    """Edge cases for get_instances."""

    def test_json_with_nested_lists(self, tmp_path):
        """JSON items can contain nested lists."""
        data = [{"id": 1, "tags": ["a", "b", "c"]}]
        p = tmp_path / "nested.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert result[0]["tags"] == ["a", "b", "c"]

    def test_json_with_deeply_nested_objects(self, tmp_path):
        """JSON items can contain deeply nested objects."""
        data = [{"id": 1, "meta": {"inner": {"deep": True}}}]
        p = tmp_path / "deep.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert result[0]["meta"]["inner"]["deep"] is True

    def test_jsonl_trailing_newline(self, tmp_path):
        """JSONL file with trailing newline doesn't create extra item."""
        p = tmp_path / "trailing.jsonl"
        p.write_text('{"id": 1}\n{"id": 2}\n')
        result = get_instances(str(p))
        assert len(result) == 2

    def test_jsonl_no_trailing_newline(self, tmp_path):
        """JSONL file without trailing newline still works."""
        p = tmp_path / "notrail.jsonl"
        p.write_text('{"id": 1}\n{"id": 2}')
        result = get_instances(str(p))
        assert len(result) == 2

    def test_json_large_string_values(self, tmp_path):
        """JSON with large string values loads correctly."""
        data = [{"id": 1, "content": "x" * 10000}]
        p = tmp_path / "large.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert len(result[0]["content"]) == 10000

    def test_json_unicode_keys(self, tmp_path):
        """JSON with unicode keys loads correctly."""
        data = [{"cl\u00e9": "valeur", "id": 1}]
        p = tmp_path / "unicode.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert "cl\u00e9" in result[0]

    def test_json_empty_string_values(self, tmp_path):
        """JSON with empty string values loads correctly."""
        data = [{"id": "", "value": ""}]
        p = tmp_path / "empty_str.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert result[0]["id"] == ""

    def test_json_numeric_values(self, tmp_path):
        """JSON with various numeric types loads correctly."""
        data = [{"int": 42, "float": 3.14, "neg": -1, "zero": 0, "big": 10**15}]
        p = tmp_path / "nums.json"
        _write_json(p, data)
        result = get_instances(str(p))
        assert result[0]["int"] == 42
        assert result[0]["float"] == 3.14

    def test_jsonl_empty_objects(self, tmp_path):
        """JSONL with empty objects loads correctly."""
        p = tmp_path / "empty_obj.jsonl"
        p.write_text("{}\n{}\n{}\n")
        result = get_instances(str(p))
        assert len(result) == 3
        assert all(item == {} for item in result)


# ── split_instances — Basic behavior ─────────────────────────────────


class TestSplitInstancesBasic:
    """Basic behavioral tests for split_instances."""

    def test_split_empty_list(self):
        """Splitting empty list into n=1 returns [[]]."""
        result = split_instances([], 1)
        assert result == [[]]

    def test_split_single_item_n1(self):
        """Splitting [x] into 1 part returns [[x]]."""
        result = split_instances([1], 1)
        assert result == [[1]]

    def test_split_returns_list(self):
        """Return type is a list."""
        result = split_instances([1, 2, 3], 2)
        assert isinstance(result, list)

    def test_split_sublists_are_lists(self):
        """Each sublist is a list."""
        result = split_instances([1, 2, 3], 2)
        for sub in result:
            assert isinstance(sub, list)

    def test_split_n_sublists_returned(self):
        """Exactly n sublists are returned."""
        result = split_instances([1, 2, 3, 4, 5], 3)
        assert len(result) == 3

    def test_split_preserves_all_items(self):
        """All items from the input appear in the output."""
        items = list(range(10))
        result = split_instances(items, 3)
        flat = [x for sub in result for x in sub]
        assert sorted(flat) == sorted(items)

    def test_split_preserves_order(self):
        """Items appear in original order when sublists are concatenated."""
        items = list(range(20))
        result = split_instances(items, 4)
        flat = [x for sub in result for x in sub]
        assert flat == items

    def test_split_no_duplicates(self):
        """No duplicates introduced by splitting."""
        items = list(range(15))
        result = split_instances(items, 4)
        flat = [x for sub in result for x in sub]
        assert len(flat) == len(set(flat))

    def test_split_contiguous_slices(self):
        """Each sublist is a contiguous slice of the original."""
        items = list(range(20))
        result = split_instances(items, 4)
        start = 0
        for sub in result:
            assert sub == items[start : start + len(sub)]
            start += len(sub)

    def test_split_n_equals_len(self):
        """Splitting n items into n parts gives n singletons."""
        items = list(range(5))
        result = split_instances(items, 5)
        assert len(result) == 5
        for sub in result:
            assert len(sub) == 1


# ── split_instances — Remainder distribution ─────────────────────────


class TestSplitInstancesRemainder:
    """Tests verifying the remainder distribution algorithm."""

    def test_no_remainder_equal_split(self):
        """When len % n == 0, all sublists have equal length."""
        result = split_instances(list(range(12)), 4)
        assert all(len(sub) == 3 for sub in result)

    def test_remainder_first_sublists_longer(self):
        """When remainder exists, first R sublists get 1 extra item."""
        result = split_instances(list(range(10)), 3)
        # 10 / 3 = 3 remainder 1 => first 1 sublist has 4, rest have 3
        assert len(result[0]) == 4
        assert len(result[1]) == 3
        assert len(result[2]) == 3

    def test_remainder_2(self):
        """Remainder of 2: first 2 sublists get extra item."""
        result = split_instances(list(range(11)), 3)
        # 11 / 3 = 3 remainder 2 => first 2 have 4, last has 3
        assert len(result[0]) == 4
        assert len(result[1]) == 4
        assert len(result[2]) == 3

    def test_remainder_all_get_extra(self):
        """When remainder == n-1, all but last get extra item."""
        result = split_instances(list(range(7)), 4)
        # 7 / 4 = 1 remainder 3 => first 3 have 2, last has 1
        assert len(result[0]) == 2
        assert len(result[1]) == 2
        assert len(result[2]) == 2
        assert len(result[3]) == 1


# ── split_instances — Edge cases ──────────────────────────────────────


class TestSplitInstancesEdgeCases:
    """Edge cases for split_instances."""

    def test_n_equals_1(self):
        """n=1 returns the original list as single sublist."""
        items = list(range(10))
        result = split_instances(items, 1)
        assert len(result) == 1
        assert result[0] == items

    def test_n_greater_than_len(self):
        """n > len returns some empty sublists."""
        result = split_instances([1, 2], 5)
        assert len(result) == 5
        flat = [x for sub in result for x in sub]
        assert sorted(flat) == [1, 2]
        # 3 sublists should be empty
        empty_count = sum(1 for sub in result if len(sub) == 0)
        assert empty_count == 3

    def test_n_much_greater_than_len(self):
        """n >> len still works correctly."""
        result = split_instances([1], 100)
        assert len(result) == 100
        flat = [x for sub in result for x in sub]
        assert flat == [1]

    def test_empty_list_n_greater_1(self):
        """Empty list with n > 1 returns n empty sublists."""
        result = split_instances([], 5)
        assert len(result) == 5
        assert all(sub == [] for sub in result)

    def test_string_items(self):
        """Works with string items."""
        result = split_instances(["a", "b", "c", "d"], 2)
        flat = [x for sub in result for x in sub]
        assert flat == ["a", "b", "c", "d"]

    def test_mixed_type_items(self):
        """Works with mixed-type items."""
        items = [1, "two", 3.0, None, True]
        result = split_instances(items, 2)
        flat = [x for sub in result for x in sub]
        assert flat == items

    def test_dict_items(self):
        """Works with dict items (like task instances)."""
        items = _make_instances(10)
        result = split_instances(items, 3)
        flat = [x for sub in result for x in sub]
        assert flat == items

    def test_nested_list_items(self):
        """Works with nested list items."""
        items = [[1, 2], [3, 4], [5, 6]]
        result = split_instances(items, 2)
        flat = [x for sub in result for x in sub]
        assert flat == items


# ── split_instances — Parametrized (list_size, n) combinations ────────


# Generate a wide range of (size, n) combinations
_SPLIT_COMBOS = []
for size in range(0, 31):
    for n in range(1, min(size + 5, 21)):
        _SPLIT_COMBOS.append((size, n))
# Add some larger sizes
for size in [50, 75, 100, 200, 500, 1000]:
    for n in [1, 2, 3, 4, 5, 7, 10, 13, 17, 20, 50]:
        if n <= size + 5:
            _SPLIT_COMBOS.append((size, n))


@pytest.mark.parametrize("size, n", _SPLIT_COMBOS)
class TestSplitInstancesParametrized:
    """Parametrized tests over many (size, n) combinations."""

    def test_correct_number_of_sublists(self, size, n):
        """split_instances(range({size}), {n}) returns {n} sublists."""
        result = split_instances(list(range(size)), n)
        assert len(result) == n

    def test_all_items_preserved(self, size, n):
        """All {size} items preserved when split into {n} parts."""
        items = list(range(size))
        result = split_instances(items, n)
        flat = [x for sub in result for x in sub]
        assert flat == items

    def test_no_duplicates(self, size, n):
        """No duplicates when splitting {size} items into {n} parts."""
        items = list(range(size))
        result = split_instances(items, n)
        flat = [x for sub in result for x in sub]
        assert len(flat) == len(set(flat)) if size > 0 else True

    def test_sublist_lengths_valid(self, size, n):
        """Sublist lengths are either floor or ceil of size/n."""
        result = split_instances(list(range(size)), n)
        avg = size // n
        for sub in result:
            assert len(sub) in (avg, avg + 1)

    def test_remainder_distribution(self, size, n):
        """First (size % n) sublists have length (size // n + 1)."""
        result = split_instances(list(range(size)), n)
        remainder = size % n
        for i, sub in enumerate(result):
            expected_len = (size // n + 1) if i < remainder else (size // n)
            assert len(sub) == expected_len


# ── split_instances — Exact lengths ──────────────────────────────────


@pytest.mark.parametrize(
    "size, n, expected_lengths",
    [
        (0, 1, [0]),
        (1, 1, [1]),
        (2, 1, [2]),
        (3, 1, [3]),
        (1, 2, [1, 0]),
        (2, 2, [1, 1]),
        (3, 2, [2, 1]),
        (4, 2, [2, 2]),
        (5, 2, [3, 2]),
        (1, 3, [1, 0, 0]),
        (2, 3, [1, 1, 0]),
        (3, 3, [1, 1, 1]),
        (4, 3, [2, 1, 1]),
        (5, 3, [2, 2, 1]),
        (6, 3, [2, 2, 2]),
        (7, 3, [3, 2, 2]),
        (8, 3, [3, 3, 2]),
        (9, 3, [3, 3, 3]),
        (10, 3, [4, 3, 3]),
        (10, 4, [3, 3, 2, 2]),
        (10, 5, [2, 2, 2, 2, 2]),
        (10, 7, [2, 2, 2, 1, 1, 1, 1]),
        (10, 10, [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]),
        (10, 11, [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0]),
        (100, 3, [34, 33, 33]),
        (100, 7, [15, 15, 14, 14, 14, 14, 14]),
        (1000, 3, [334, 333, 333]),
    ],
)
def test_exact_sublist_lengths(size, n, expected_lengths):
    """split_instances(range({size}), {n}) produces sublists of lengths {expected_lengths}."""
    result = split_instances(list(range(size)), n)
    actual_lengths = [len(sub) for sub in result]
    assert actual_lengths == expected_lengths


# ── split_instances — Total item count ────────────────────────────────


@pytest.mark.parametrize("size", list(range(0, 51)) + [75, 100, 200, 500, 1000])
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 10, 13])
class TestSplitTotalCount:
    """Total item count after split equals original size."""

    def test_total_equals_size(self, size, n):
        """Total items after split({size}, {n}) equals {size}."""
        result = split_instances(list(range(size)), n)
        total = sum(len(sub) for sub in result)
        assert total == size


# ── INTEGRATION TESTS ─────────────────────────────────────────────────


class TestIntegrationGetInstancesWithSplit:
    """Integration: get_instances feeds directly into split_instances."""

    def test_json_load_then_split(self, tmp_path):
        """Load JSON instances then split them."""
        data = [{"id": f"inst_{i}", "repo": "test/test"} for i in range(20)]
        p = tmp_path / "tasks.json"
        p.write_text(json.dumps(data))
        loaded = get_instances(str(p))
        assert len(loaded) == 20
        splits = split_instances(loaded, 4)
        assert len(splits) == 4
        total = sum(len(s) for s in splits)
        assert total == 20
        # Verify data integrity — all instances present
        all_ids = {inst["id"] for s in splits for inst in s}
        assert all_ids == {f"inst_{i}" for i in range(20)}

    def test_jsonl_load_then_split(self, tmp_path):
        """Load JSONL instances then split them."""
        data = [{"id": f"inst_{i}", "repo": "numpy/numpy"} for i in range(15)]
        p = tmp_path / "tasks.jsonl"
        p.write_text("\n".join(json.dumps(d) for d in data))
        loaded = get_instances(str(p))
        assert len(loaded) == 15
        splits = split_instances(loaded, 3)
        assert len(splits) == 3
        assert sum(len(s) for s in splits) == 15

    def test_jsonl_all_load_then_split(self, tmp_path):
        """Load .jsonl.all instances then split them."""
        data = [{"id": f"task_{i}"} for i in range(10)]
        p = tmp_path / "data.jsonl.all"
        p.write_text("\n".join(json.dumps(d) for d in data))
        loaded = get_instances(str(p))
        splits = split_instances(loaded, 5)
        assert sum(len(s) for s in splits) == 10

    def test_empty_json_then_split(self, tmp_path):
        """Empty JSON list splits into empty sublists."""
        p = tmp_path / "empty.json"
        p.write_text("[]")
        loaded = get_instances(str(p))
        assert len(loaded) == 0
        splits = split_instances(loaded, 3)
        assert len(splits) == 3
        assert all(len(s) == 0 for s in splits)

    def test_single_instance_split_to_many_workers(self, tmp_path):
        """Single instance split to many workers."""
        p = tmp_path / "one.json"
        p.write_text('[{"id": "only"}]')
        loaded = get_instances(str(p))
        splits = split_instances(loaded, 10)
        assert len(splits) == 10
        non_empty = [s for s in splits if len(s) > 0]
        assert len(non_empty) == 1
        assert non_empty[0][0]["id"] == "only"

    @pytest.mark.parametrize("n_instances", [1, 3, 7, 13, 50, 100])
    @pytest.mark.parametrize("n_workers", [1, 2, 3, 4, 8])
    def test_load_split_round_trip(self, tmp_path, n_instances, n_workers):
        """Parametrized: load N instances, split by W workers, verify completeness."""
        data = [{"id": i, "val": f"v{i}"} for i in range(n_instances)]
        p = tmp_path / "data.json"
        p.write_text(json.dumps(data))
        loaded = get_instances(str(p))
        splits = split_instances(loaded, n_workers)
        # All items accounted for
        all_items = [item for s in splits for item in s]
        assert len(all_items) == n_instances
        # Ordering preserved within sublists
        flat_ids = [item["id"] for item in all_items]
        assert flat_ids == list(range(n_instances))


class TestIntegrationDataIntegrity:
    """Integration: verify data round-trips through get_instances preserve content."""

    def test_complex_nested_data_preserved(self, tmp_path):
        """Nested dicts and lists survive JSON round-trip."""
        data = [
            {"id": "complex", "nested": {"a": [1, 2, 3]}, "tags": ["perf", "opt"]},
            {"id": "simple", "version": "1.0"},
        ]
        p = tmp_path / "complex.json"
        p.write_text(json.dumps(data))
        loaded = get_instances(str(p))
        assert loaded[0]["nested"]["a"] == [1, 2, 3]
        assert loaded[0]["tags"] == ["perf", "opt"]
        assert loaded[1]["version"] == "1.0"

    def test_unicode_content_preserved(self, tmp_path):
        """Unicode characters survive JSON round-trip."""
        data = [{"id": "unicode", "desc": "Héllo wörld 日本語"}]
        p = tmp_path / "unicode.json"
        p.write_text(json.dumps(data, ensure_ascii=False))
        loaded = get_instances(str(p))
        assert loaded[0]["desc"] == "Héllo wörld 日本語"

    def test_jsonl_preserves_per_line_parsing(self, tmp_path):
        """Each JSONL line is independently parsed."""
        lines = [
            '{"id": "a", "val": 1}',
            '{"id": "b", "val": 2}',
            '{"id": "c", "val": 3}',
        ]
        p = tmp_path / "test.jsonl"
        p.write_text("\n".join(lines))
        loaded = get_instances(str(p))
        assert len(loaded) == 3
        assert [d["id"] for d in loaded] == ["a", "b", "c"]


# ── END-TO-END TESTS ─────────────────────────────────────────────────


class TestEndToEndVersioningUtilsWorkflow:
    """E2E: simulate the full workflow as used by get_versions.main()."""

    def test_e2e_load_split_build_save_merge(self, tmp_path):
        """Simulate: load instances -> split -> each worker saves -> merge."""
        # Create instances file
        instances = [
            {"instance_id": f"test__{i}", "repo": "test/test", "base_commit": f"abc{i}"}
            for i in range(12)
        ]
        instances_path = tmp_path / "tasks.json"
        instances_path.write_text(json.dumps(instances))

        # Load and split (as main() does)
        loaded = get_instances(str(instances_path))
        assert len(loaded) == 12
        splits = split_instances(loaded, 3)
        assert len(splits) == 3

        # Simulate each worker saving results
        for i, split in enumerate(splits):
            for inst in split:
                inst["version"] = f"1.{i}"
            save_path = tmp_path / f"test__test_versions_{i}.json"
            save_path.write_text(json.dumps(split))

        # Verify all saved files are complete
        total_saved = 0
        for i in range(3):
            save_path = tmp_path / f"test__test_versions_{i}.json"
            assert save_path.exists()
            saved = json.loads(save_path.read_text())
            total_saved += len(saved)
        assert total_saved == 12

    def test_e2e_jsonl_pipeline(self, tmp_path):
        """E2E: JSONL load -> split -> per-worker process -> recombine."""
        instances = [
            {"instance_id": f"scipy__{i}", "repo": "scipy/scipy", "base_commit": f"def{i}"}
            for i in range(8)
        ]
        p = tmp_path / "scipy.jsonl"
        p.write_text("\n".join(json.dumps(inst) for inst in instances))

        loaded = get_instances(str(p))
        splits = split_instances(loaded, 2)

        # Process each split
        all_results = []
        for split in splits:
            for inst in split:
                inst["version"] = "1.10"
            all_results.extend(split)

        assert len(all_results) == 8
        assert all(r["version"] == "1.10" for r in all_results)

    def test_e2e_mix_mode_simulation(self, tmp_path):
        """E2E: simulate mix mode — first pass finds some, second pass finds rest."""
        instances = [
            {"instance_id": f"inst_{i}", "repo": "test/test", "base_commit": f"c{i}"}
            for i in range(10)
        ]
        p = tmp_path / "tasks.json"
        p.write_text(json.dumps(instances))

        loaded = get_instances(str(p))
        splits = split_instances(loaded, 2)

        # First pass (web): some found, some not
        not_found = []
        for split in splits:
            for inst in split:
                if int(inst["instance_id"].split("_")[1]) % 3 == 0:
                    not_found.append(inst)
                else:
                    inst["version"] = "2.0"

        # Second pass (build): process not_found
        assert len(not_found) == 4  # 0, 3, 6, 9
        splits2 = split_instances(not_found, 2)
        for split in splits2:
            for inst in split:
                inst["version"] = "2.0_build"

        all_results = loaded
        assert len(all_results) == 10
        assert all("version" in r for r in all_results)

    def test_e2e_large_scale_split_recombine(self, tmp_path):
        """E2E: 500 instances, 8 workers, verify perfect reconstruction."""
        instances = [{"id": i, "data": f"payload_{i}"} for i in range(500)]
        p = tmp_path / "large.json"
        p.write_text(json.dumps(instances))

        loaded = get_instances(str(p))
        splits = split_instances(loaded, 8)

        # Recombine
        recombined = [item for s in splits for item in s]
        assert len(recombined) == 500
        assert [item["id"] for item in recombined] == list(range(500))

    def test_e2e_repo_prefix_derivation(self, tmp_path):
        """E2E: verify repo prefix derivation matches main() logic."""
        instances = [
            {"instance_id": "i0", "repo": "scikit-learn/scikit-learn", "base_commit": "abc"}
        ]
        p = tmp_path / "tasks.json"
        p.write_text(json.dumps(instances))
        loaded = get_instances(str(p))
        # main() does: repo_prefix = data_tasks[0]["repo"].replace("/", "__")
        repo_prefix = loaded[0]["repo"].replace("/", "__")
        assert repo_prefix == "scikit-learn__scikit-learn"


# ── Gap Coverage Tests ────────────────────────────────────────────────


class TestNullEmptyMissing:
    """D2/Q1/Q2: Null, empty, and missing input handling."""

    def test_get_instances_none_path_raises_attribute_error(self):
        with pytest.raises(AttributeError):
            get_instances(None)

    def test_get_instances_empty_string_path_raises(self):
        with pytest.raises(FileNotFoundError):
            get_instances("")

    def test_split_instances_none_list_raises_type_error(self):
        with pytest.raises(TypeError):
            split_instances(None, 3)

    def test_split_instances_none_n_raises_type_error(self):
        with pytest.raises(TypeError):
            split_instances([1, 2, 3], None)

    def test_split_instances_empty_list_returns_empty_sublists(self):
        result = split_instances([], 3)
        assert result == [[], [], []]


class TestTypeCoercion:
    """D3: Type coercion and wrong-type argument handling."""

    def test_get_instances_int_path_raises_attribute_error(self):
        with pytest.raises(AttributeError):
            get_instances(123)

    def test_get_instances_list_path_raises(self):
        with pytest.raises(AttributeError):
            get_instances(["/some/path"])

    def test_split_instances_string_instead_of_list(self):
        result = split_instances("hello", 2)
        assert result == ["hel", "lo"]

    def test_split_instances_string_n_raises_type_error(self):
        with pytest.raises(TypeError):
            split_instances([1, 2], "2")

    def test_split_instances_float_n_raises_type_error(self):
        with pytest.raises(TypeError):
            split_instances([1, 2], 2.5)


class TestBoundaryValues:
    """D1: Boundary value edge cases."""

    def test_split_instances_n_zero_raises_zero_division_error(self):
        with pytest.raises(ZeroDivisionError):
            split_instances([1, 2, 3], 0)

    def test_split_instances_n_negative_returns_empty(self):
        result = split_instances([1, 2, 3], -1)
        assert result == []


class TestStringEdgeCases:
    """D4: String and text edge cases in file paths and content."""

    def test_get_instances_path_with_null_byte(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps([{"id": 1}]))
        path_with_null = str(p) + "\x00"
        with pytest.raises(ValueError):
            get_instances(path_with_null)

    def test_get_instances_jsonl_with_bom(self, tmp_path):
        p = tmp_path / "data.jsonl"
        content = '\ufeff{"id": 1}\n{"id": 2}\n'
        p.write_text(content, encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            get_instances(str(p))

    def test_get_instances_json_with_unicode_values(self, tmp_path):
        p = tmp_path / "unicode.json"
        data = [{"name": "café", "emoji": "🎉", "kanji": "漢字"}]
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = get_instances(str(p))
        assert result[0]["name"] == "café"
        assert result[0]["emoji"] == "🎉"
        assert result[0]["kanji"] == "漢字"

    def test_get_instances_very_long_path(self):
        with pytest.raises((FileNotFoundError, OSError)):
            get_instances("x" * 10000 + ".json")


class TestShallowDeepCopy:
    """TB12: Verify split_instances uses shallow references, not deep copies."""

    def test_split_instances_shares_references(self):
        items = [{"a": 1}]
        splits = split_instances(items, 1)
        splits[0][0]["a"] = 999
        assert items[0]["a"] == 999

    def test_split_instances_modifying_sublist_does_not_affect_other_sublists(self):
        items = [{"v": i} for i in range(4)]
        splits = split_instances(items, 2)
        splits[0][0]["v"] = -1
        assert splits[1][0]["v"] == 2
        assert splits[1][1]["v"] == 3


class TestIdempotency:
    """Q17: Repeated calls with same inputs produce identical results."""

    def test_get_instances_idempotent(self, tmp_path):
        p = tmp_path / "idem.json"
        p.write_text(json.dumps([{"x": 1}, {"x": 2}]))
        result1 = get_instances(str(p))
        result2 = get_instances(str(p))
        assert result1 == result2

    def test_split_instances_idempotent(self):
        data = list(range(10))
        result1 = split_instances(data, 3)
        result2 = split_instances(data, 3)
        assert result1 == result2


class TestFilePermissions:
    """Q18: File permission edge cases."""

    @pytest.mark.skipif(os.name == "nt", reason="Unix permissions only")
    def test_get_instances_unreadable_file(self, tmp_path):
        p = tmp_path / "locked.json"
        p.write_text(json.dumps([{"id": 1}]))
        os.chmod(str(p), 0o000)
        try:
            with pytest.raises(PermissionError):
                get_instances(str(p))
        finally:
            os.chmod(str(p), 0o644)


class TestUnicodePaths:
    """Q19: Unicode characters in file paths."""

    def test_get_instances_unicode_filename(self, tmp_path):
        p = tmp_path / "données.json"
        p.write_text(json.dumps([{"clé": "valeur"}]))
        result = get_instances(str(p))
        assert result == [{"clé": "valeur"}]

    def test_get_instances_path_with_spaces(self, tmp_path):
        p = tmp_path / "my data file.json"
        p.write_text(json.dumps([{"id": 42}]))
        result = get_instances(str(p))
        assert result == [{"id": 42}]


class TestPerformance:
    """D11: Performance with large inputs."""

    def test_split_instances_large_input(self):
        data = list(range(100_000))
        result = split_instances(data, 100)
        assert len(result) == 100
        total = sum(len(s) for s in result)
        assert total == 100_000

    def test_get_instances_large_json(self, tmp_path):
        p = tmp_path / "big.json"
        data = [{"idx": i, "payload": f"data_{i}"} for i in range(10_000)]
        p.write_text(json.dumps(data))
        result = get_instances(str(p))
        assert len(result) == 10_000
        assert result[0]["idx"] == 0
        assert result[9999]["idx"] == 9999
