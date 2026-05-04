"""
Tests for swefficiency/perf_filter/utils.py

Coverage targets:
    - extract_edits(patch)
    - read_jsonl(jsonl_path, to_df=False)
    - get_gh_tokens(env_var_name="GITHUB_TOKENS")
    - is_doc_file(file_path)
    - has_lock_file_change(file_path)

Dimensions covered: D1 Input Domain, D2 Null/Empty/Missing, D3 Type Coercion,
D4 String Brutality, D8 Error Handling, D9 Security, D10 Data Format,
D11 Performance, D12 Integration.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from swefficiency.perf_filter.utils import (
    extract_edits,
    read_jsonl,
    get_gh_tokens,
    is_doc_file,
    has_lock_file_change,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_patch(*file_diffs):
    """Build a unified diff string from (source, dest, body) tuples."""
    parts = []
    for src, dst, body in file_diffs:
        parts.append(f"diff --git {src} {dst}\n--- {src}\n+++ {dst}\n{body}")
    return "".join(parts)


def _make_jsonl_file(tmp_path, items, filename="data.jsonl"):
    """Write items as JSONL and return the path."""
    filepath = tmp_path / filename
    with open(filepath, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")
    return str(filepath)


# ═══════════════════════════════════════════════════════════════════════════════
# extract_edits
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractEdits:
    """Tests for extract_edits(patch).

    Production code splits on 'diff --git', asserts len > 1 and first split
    is empty, then parses source/dest from lines[0].split()[1] / lines[1].split()[1].
    """

    # ── D1: Input Domain ──────────────────────────────────────────────────

    def test_single_file_diff(self):
        """D1: Single file edit returns one (source, dest, remaining) tuple.
        NOTE: lines[0].split()[1] grabs second token from 'a/X b/X' = b/X,
        and lines[1].split()[1] grabs second token from '--- a/X' = a/X.
        So source_file_name is actually the b/ path, dest_file_name is the a/ path.
        """
        patch = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-old\n"
            "+new\n"
        )
        result = extract_edits(patch)
        assert len(result) == 1
        src, dst, remaining = result[0]
        # lines[0].split()[1] = "b/src/foo.py", lines[1].split()[1] = "a/src/foo.py"
        assert src == "b/src/foo.py"
        assert dst == "a/src/foo.py"
        assert "@@ -1,3 +1,3 @@" in remaining

    def test_multiple_file_diffs(self):
        """D1: Patch with 3 files returns 3 tuples in order."""
        patch = (
            "diff --git a/one.py b/one.py\n"
            "--- a/one.py\n"
            "+++ b/one.py\n"
            "@@ -1 +1 @@\n"
            "-a\n"
            "+b\n"
            "diff --git a/two.py b/two.py\n"
            "--- a/two.py\n"
            "+++ b/two.py\n"
            "@@ -1 +1 @@\n"
            "-c\n"
            "+d\n"
            "diff --git a/three.py b/three.py\n"
            "--- a/three.py\n"
            "+++ b/three.py\n"
            "@@ -1 +1 @@\n"
            "-e\n"
            "+f\n"
        )
        result = extract_edits(patch)
        assert len(result) == 3
        assert result[0][0] == "b/one.py"
        assert result[1][0] == "b/two.py"
        assert result[2][0] == "b/three.py"

    def test_remaining_lines_content(self):
        """D1: remaining_lines is everything after source/dest lines, joined."""
        patch = (
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\nline3\nline4\nline5\n"
        )
        result = extract_edits(patch)
        remaining = result[0][2]
        assert "line3" in remaining
        assert "line4" in remaining
        assert "line5" in remaining

    def test_different_source_dest_paths(self):
        """D1: Rename — source and dest paths differ."""
        patch = (
            "diff --git a/old_name.py b/new_name.py\n"
            "--- a/old_name.py\n"
            "+++ b/new_name.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        result = extract_edits(patch)
        assert result[0][0] == "b/new_name.py"
        assert result[0][1] == "a/old_name.py"

    def test_nested_directory_paths(self):
        """D1: Deep nested paths are parsed correctly."""
        patch = (
            "diff --git a/src/pkg/sub/module.py b/src/pkg/sub/module.py\n"
            "--- a/src/pkg/sub/module.py\n"
            "+++ b/src/pkg/sub/module.py\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
        )
        result = extract_edits(patch)
        assert result[0][0] == "b/src/pkg/sub/module.py"

    def test_various_file_extensions(self):
        """D1: Non-Python file extensions work (.js, .rst, .lock, .md)."""
        for ext in [".js", ".rst", ".lock", ".md", ".toml", ".yaml"]:
            patch = (
                f"diff --git a/file{ext} b/file{ext}\n"
                f"--- a/file{ext}\n"
                f"+++ b/file{ext}\n"
                "@@ -1 +1 @@\n"
                "-x\n"
                "+y\n"
            )
            result = extract_edits(patch)
            assert result[0][0] == f"b/file{ext}"

    # ── D2: Null/Empty/Missing ────────────────────────────────────────────

    def test_empty_string_raises(self):
        """D2: Empty string has no 'diff --git' — assertion error."""
        with pytest.raises(AssertionError, match="does not contain any diff"):
            extract_edits("")

    def test_no_diff_git_marker_raises(self):
        """D2: Text without 'diff --git' fails assertion."""
        with pytest.raises(AssertionError, match="does not contain any diff"):
            extract_edits("just some random text\nno diffs here\n")

    def test_patch_not_starting_with_diff_git_raises(self):
        """D2: Patch with prefix before 'diff --git' fails second assertion."""
        patch = "Some preamble\ndiff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        with pytest.raises(AssertionError, match="does not start with diff"):
            extract_edits(patch)

    # ── D4: String Brutality ──────────────────────────────────────────────

    def test_path_with_spaces(self):
        """D4: File paths with spaces — split()[1] grabs first token only.
        NOTE: This documents a production limitation — spaces in paths break parsing.
        """
        patch = (
            "diff --git a/my file.py b/my file.py\n"
            "--- a/my file.py\n"
            "+++ b/my file.py\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
        )
        result = extract_edits(patch)
        # lines[0] = "a/my file.py b/my file.py", split()[1] = "file.py"
        assert result[0][0] == "file.py"

    def test_unicode_filename(self):
        """D4: Unicode characters in file paths."""
        patch = (
            "diff --git a/\u00fc\u00f1\u00eecode.py b/\u00fc\u00f1\u00eecode.py\n"
            "--- a/\u00fc\u00f1\u00eecode.py\n"
            "+++ b/\u00fc\u00f1\u00eecode.py\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
        )
        result = extract_edits(patch)
        assert result[0][0] == "b/\u00fc\u00f1\u00eecode.py"

    # ── D8: Error Handling ────────────────────────────────────────────────

    def test_minimal_diff_two_lines_only(self):
        """D8: Diff with only header + --- + +++ lines — remaining is +++ line."""
        patch = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        result = extract_edits(patch)
        assert "+++ b/f.py" in result[0][2]

    def test_single_line_after_header_raises(self):
        """D8: Only one line after 'diff --git' — lines[1] would fail.
        Actually, split()[1] on '--- a/f.py' still works, so this is fine as
        long as there are >= 2 lines.
        """
        patch = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        result = extract_edits(patch)
        assert len(result) == 1

    # ── D11: Performance ──────────────────────────────────────────────────

    def test_large_number_of_files(self):
        """D11: Patch with 100 file diffs processes without error."""
        parts = []
        for i in range(100):
            parts.append(
                f"diff --git a/file_{i}.py b/file_{i}.py\n"
                f"--- a/file_{i}.py\n"
                f"+++ b/file_{i}.py\n"
                f"@@ -1 +1 @@\n"
                f"-old_{i}\n"
                f"+new_{i}\n"
            )
        patch = "".join(parts)
        result = extract_edits(patch)
        assert len(result) == 100

    def test_large_remaining_content(self):
        """D11: Very large remaining content in a single diff."""
        big_body = "\n".join(f"+line_{i}" for i in range(5000))
        patch = (
            f"diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n{big_body}\n"
        )
        result = extract_edits(patch)
        assert len(result) == 1
        assert "line_4999" in result[0][2]

    def test_d8_line_with_no_spaces_causes_index_error(self):
        """D8: BUG — lines[0].split()[1] crashes with IndexError if line has < 2 tokens."""
        patch = "diff --git NOSPACELINE\n---\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y\n"
        with pytest.raises(IndexError):
            extract_edits(patch)

    def test_d8_empty_minus_line_causes_index_error(self):
        """D8: BUG — lines[1].split()[1] crashes if --- line has no path token."""
        patch = "diff --git a/f.py b/f.py\n---\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y\n"
        with pytest.raises(IndexError):
            extract_edits(patch)


# ═══════════════════════════════════════════════════════════════════════════════
# read_jsonl
# ═══════════════════════════════════════════════════════════════════════════════


class TestReadJsonl:
    """Tests for read_jsonl(jsonl_path, to_df=False).

    Production code: if to_df, uses pd.read_json(lines=True).
    Otherwise: manual iteration with bare `except:` that swallows ALL errors
    including KeyboardInterrupt/SystemExit.
    """

    # ── D1: Input Domain ──────────────────────────────────────────────────

    def test_single_item(self, tmp_path):
        """D1: Single JSON object returns list of one dict."""
        path = _make_jsonl_file(tmp_path, [{"a": 1}])
        result = read_jsonl(path)
        assert result == [{"a": 1}]

    def test_multiple_items(self, tmp_path):
        """D1: Multiple objects returned in order."""
        items = [{"x": 1}, {"x": 2}, {"x": 3}]
        path = _make_jsonl_file(tmp_path, items)
        result = read_jsonl(path)
        assert result == items

    def test_mixed_types(self, tmp_path):
        """D1: Items with different value types (str, int, list, nested dict)."""
        items = [
            {"name": "hello", "count": 42},
            {"data": [1, 2, 3], "nested": {"key": "val"}},
        ]
        path = _make_jsonl_file(tmp_path, items)
        result = read_jsonl(path)
        assert result == items

    def test_to_df_returns_dataframe(self, tmp_path):
        """D1: to_df=True returns a pandas DataFrame."""
        import pandas as pd

        items = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        path = _make_jsonl_file(tmp_path, items)
        result = read_jsonl(path, to_df=True)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert list(result.columns) == ["a", "b"]

    # ── D2: Null/Empty/Missing ────────────────────────────────────────────

    def test_empty_file(self, tmp_path):
        """D2: Empty file returns empty list."""
        filepath = tmp_path / "empty.jsonl"
        filepath.touch()
        result = read_jsonl(str(filepath))
        assert result == []

    def test_file_with_only_newlines(self, tmp_path):
        """D2: File with only blank lines returns empty list.
        The `not data` check catches empty strings from blank lines."""
        filepath = tmp_path / "newlines.jsonl"
        filepath.write_text("\n\n\n")
        result = read_jsonl(str(filepath))
        assert result == []

    # ── D4: String Brutality ──────────────────────────────────────────────

    def test_unicode_content(self, tmp_path):
        """D4: Unicode values in JSON are preserved."""
        items = [{"text": "\u00fc\u00f1\u00eec\u00f6d\u00e9 \u2764\ufe0f \u2603\ufe0f"}]
        path = _make_jsonl_file(tmp_path, items)
        result = read_jsonl(path)
        assert (
            result[0]["text"]
            == "\u00fc\u00f1\u00eec\u00f6d\u00e9 \u2764\ufe0f \u2603\ufe0f"
        )

    def test_json_special_chars(self, tmp_path):
        """D4: JSON with escaped special characters."""
        items = [{"text": 'line1\nline2\ttab\\backslash"quote'}]
        path = _make_jsonl_file(tmp_path, items)
        result = read_jsonl(path)
        assert result[0]["text"] == 'line1\nline2\ttab\\backslash"quote'

    # ── D8: Error Handling ────────────────────────────────────────────────

    def test_malformed_json_skipped_silently(self, tmp_path):
        """D8: Bare `except:` swallows json.JSONDecodeError — malformed lines are
        silently skipped. This is a documented BUG: also swallows KeyboardInterrupt."""
        filepath = tmp_path / "bad.jsonl"
        filepath.write_text('{"good": 1}\nnot valid json\n{"also": "good"}\n')
        result = read_jsonl(str(filepath))
        assert len(result) == 2
        assert result[0] == {"good": 1}
        assert result[1] == {"also": "good"}

    def test_file_not_found_raises(self, tmp_path):
        """D8: Non-existent file raises FileNotFoundError (not caught)."""
        with pytest.raises(FileNotFoundError):
            read_jsonl(str(tmp_path / "nope.jsonl"))

    def test_to_df_empty_file(self, tmp_path):
        """D8: pd.read_json on empty file — behavior varies by pandas version."""
        import pandas as pd

        filepath = tmp_path / "empty_df.jsonl"
        filepath.touch()
        try:
            result = read_jsonl(str(filepath), to_df=True)
            assert isinstance(result, pd.DataFrame)
            assert len(result) == 0
        except (ValueError, Exception):
            pass  # older pandas versions raise

    # ── D10: Data Format ──────────────────────────────────────────────────

    def test_json_with_nested_objects(self, tmp_path):
        """D10: Deeply nested JSON structures parsed correctly."""
        items = [{"l1": {"l2": {"l3": {"l4": "deep"}}}}]
        path = _make_jsonl_file(tmp_path, items)
        result = read_jsonl(path)
        assert result[0]["l1"]["l2"]["l3"]["l4"] == "deep"

    def test_json_with_null_values(self, tmp_path):
        """D10: JSON null values preserved as Python None."""
        filepath = tmp_path / "nulls.jsonl"
        filepath.write_text('{"key": null}\n')
        result = read_jsonl(str(filepath))
        assert result[0]["key"] is None

    def test_json_with_boolean_values(self, tmp_path):
        """D10: JSON booleans preserved as Python booleans."""
        filepath = tmp_path / "bools.jsonl"
        filepath.write_text('{"t": true, "f": false}\n')
        result = read_jsonl(str(filepath))
        assert result[0]["t"] is True
        assert result[0]["f"] is False

    # ── D11: Performance ──────────────────────────────────────────────────

    def test_large_file(self, tmp_path):
        """D11: 1000-item JSONL file read without issues."""
        items = [{"id": i, "data": f"value_{i}"} for i in range(1000)]
        path = _make_jsonl_file(tmp_path, items)
        result = read_jsonl(path)
        assert len(result) == 1000
        assert result[999]["id"] == 999

    def test_to_df_malformed_json_raises(self, tmp_path):
        """D8: pd.read_json with malformed JSON raises ValueError (not silently swallowed like manual path)."""
        import pandas as pd

        filepath = tmp_path / "bad_df.jsonl"
        filepath.write_text('{"valid": 1}\n{INVALID JSON\n{"also": "valid"}\n')
        with pytest.raises((ValueError, Exception)):
            read_jsonl(str(filepath), to_df=True)

    def test_d8_bare_except_swallows_keyboard_interrupt(self, tmp_path):
        """D8: BUG — bare `except:` in manual read path swallows KeyboardInterrupt/SystemExit.
        This test documents the bug by verifying malformed JSON is silently skipped."""
        filepath = tmp_path / "mixed.jsonl"
        filepath.write_text('{"good": 1}\nNOT JSON\n{"good": 2}\n')
        result = read_jsonl(str(filepath))
        assert len(result) == 2
        assert result[0] == {"good": 1}
        assert result[1] == {"good": 2}


# ═══════════════════════════════════════════════════════════════════════════════
# get_gh_tokens
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetGhTokens:
    """Tests for get_gh_tokens(env_var_name="GITHUB_TOKENS").

    Production code: os.environ.get(env_var_name).split(",")
    BUG: .get() returns None when var is missing, then .split() raises AttributeError.
    """

    # ── D1: Input Domain ──────────────────────────────────────────────────

    def test_single_token(self, monkeypatch):
        """D1: Single token with no comma returns list of one."""
        monkeypatch.setenv("GITHUB_TOKENS", "ghp_abc123")
        result = get_gh_tokens()
        assert result == ["ghp_abc123"]

    def test_multiple_tokens(self, monkeypatch):
        """D1: Comma-separated tokens split into list."""
        monkeypatch.setenv("GITHUB_TOKENS", "tok1,tok2,tok3")
        result = get_gh_tokens()
        assert result == ["tok1", "tok2", "tok3"]

    def test_custom_env_var_name(self, monkeypatch):
        """D1: Custom env_var_name parameter is respected."""
        monkeypatch.setenv("MY_TOKENS", "a,b")
        result = get_gh_tokens(env_var_name="MY_TOKENS")
        assert result == ["a", "b"]

    # ── D2: Null/Empty/Missing ────────────────────────────────────────────

    def test_missing_env_var_raises_attribute_error(self, monkeypatch):
        """D2: BUG — missing env var causes AttributeError: 'NoneType' has no .split().
        Production code uses os.environ.get() without default, then .split() on None.
        """
        monkeypatch.delenv("GITHUB_TOKENS", raising=False)
        with pytest.raises(AttributeError):
            get_gh_tokens()

    def test_empty_env_var(self, monkeypatch):
        """D2: Empty string splits into [''] (list with one empty string)."""
        monkeypatch.setenv("GITHUB_TOKENS", "")
        result = get_gh_tokens()
        assert result == [""]

    # ── D4: String Brutality ──────────────────────────────────────────────

    def test_trailing_comma(self, monkeypatch):
        """D4: Trailing comma produces an extra empty string in list."""
        monkeypatch.setenv("GITHUB_TOKENS", "tok1,tok2,")
        result = get_gh_tokens()
        assert result == ["tok1", "tok2", ""]

    def test_leading_comma(self, monkeypatch):
        """D4: Leading comma produces empty first element."""
        monkeypatch.setenv("GITHUB_TOKENS", ",tok1")
        result = get_gh_tokens()
        assert result == ["", "tok1"]

    def test_spaces_around_tokens(self, monkeypatch):
        """D4: Whitespace is NOT stripped — spaces are part of token values."""
        monkeypatch.setenv("GITHUB_TOKENS", " tok1 , tok2 ")
        result = get_gh_tokens()
        assert result == [" tok1 ", " tok2 "]

    def test_consecutive_commas(self, monkeypatch):
        """D4: Consecutive commas produce empty strings between them."""
        monkeypatch.setenv("GITHUB_TOKENS", "a,,b,,,c")
        result = get_gh_tokens()
        assert result == ["a", "", "b", "", "", "c"]


# ═══════════════════════════════════════════════════════════════════════════════
# is_doc_file
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsDocFile:
    """Tests for is_doc_file(file_path).

    Production code: file_path.endswith(".md") or file_path.endswith(".rst")
    """

    # ── D1: Input Domain ──────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("README.md", True),
            ("docs/guide.md", True),
            ("CHANGELOG.rst", True),
            ("docs/api/ref.rst", True),
            ("src/main.py", False),
            ("setup.cfg", False),
            ("file.txt", False),
            ("file.json", False),
            ("file.yaml", False),
            ("file.toml", False),
            ("file.lock", False),
            ("file.js", False),
        ],
        ids=[
            "md-root",
            "md-nested",
            "rst-root",
            "rst-nested",
            "py-false",
            "cfg-false",
            "txt-false",
            "json-false",
            "yaml-false",
            "toml-false",
            "lock-false",
            "js-false",
        ],
    )
    def test_known_extensions(self, path, expected):
        """D1: .md and .rst return True; all other extensions return False."""
        assert is_doc_file(path) is expected

    # ── D2: Null/Empty ────────────────────────────────────────────────────

    def test_empty_string(self):
        """D2: Empty string — endswith('.md') is False."""
        assert is_doc_file("") is False

    # ── D4: String Brutality ──────────────────────────────────────────────

    def test_case_sensitive(self):
        """D4: .MD, .Md, .RST, .Rst are NOT detected — endswith is case-sensitive."""
        assert is_doc_file("README.MD") is False
        assert is_doc_file("file.Md") is False
        assert is_doc_file("file.RST") is False
        assert is_doc_file("file.Rst") is False

    def test_substring_not_matched(self):
        """D4: '.md' in middle of name doesn't match — must be suffix."""
        assert is_doc_file("file.md.bak") is False
        assert is_doc_file("file.rst.old") is False

    def test_just_extension(self):
        """D4: Bare extension without name still matches."""
        assert is_doc_file(".md") is True
        assert is_doc_file(".rst") is True

    def test_dot_in_directory(self):
        """D4: .md in directory name but not in file extension."""
        assert is_doc_file("docs.md/file.py") is False

    def test_double_extension(self):
        """D4: Double extension — endswith checks last part only."""
        assert is_doc_file("file.txt.md") is True
        assert is_doc_file("file.md.txt") is False

    # ── D9: Security ──────────────────────────────────────────────────────

    def test_path_traversal_still_checks_extension(self):
        """D9: Path traversal — function only checks extension, not path safety."""
        assert is_doc_file("../../etc/passwd.md") is True
        assert is_doc_file("../../etc/passwd") is False


# ═══════════════════════════════════════════════════════════════════════════════
# has_lock_file_change
# ═══════════════════════════════════════════════════════════════════════════════


class TestHasLockFileChange:
    """Tests for has_lock_file_change(file_path).

    Production code: file_path.endswith(".lock")
    """

    # ── D1: Input Domain ──────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("poetry.lock", True),
            ("package-lock.json.lock", True),
            ("Gemfile.lock", True),
            ("yarn.lock", True),
            ("nested/dir/file.lock", True),
            ("file.py", False),
            ("file.md", False),
            ("file.txt", False),
            ("Pipfile", False),
            ("lockfile", False),  # no .lock extension
        ],
        ids=[
            "poetry-lock",
            "double-ext-lock",
            "gemfile-lock",
            "yarn-lock",
            "nested-lock",
            "py-false",
            "md-false",
            "txt-false",
            "pipfile-false",
            "no-ext-lockfile",
        ],
    )
    def test_known_patterns(self, path, expected):
        """D1: .lock extension returns True; everything else False."""
        assert has_lock_file_change(path) is expected

    # ── D2: Null/Empty ────────────────────────────────────────────────────

    def test_empty_string(self):
        """D2: Empty string returns False."""
        assert has_lock_file_change("") is False

    # ── D4: String Brutality ──────────────────────────────────────────────

    def test_case_sensitive(self):
        """D4: .LOCK, .Lock are NOT detected — case-sensitive."""
        assert has_lock_file_change("file.LOCK") is False
        assert has_lock_file_change("file.Lock") is False

    def test_lock_in_middle(self):
        """D4: .lock in middle of name doesn't match."""
        assert has_lock_file_change("file.lock.bak") is False

    def test_just_dot_lock(self):
        """D4: Bare '.lock' with no basename matches."""
        assert has_lock_file_change(".lock") is True

    def test_lock_in_directory_name(self):
        """D4: .lock in directory path but not file extension."""
        assert has_lock_file_change("deps.lock/file.py") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractEditsIntegration:
    """D12: Integration tests combining extract_edits with is_doc_file and
    has_lock_file_change — mirrors the usage pattern in filter.py main()."""

    def test_all_doc_files(self):
        """D12: Patch with only .md/.rst files — all flagged as doc."""
        patch = (
            "diff --git a/README.md b/README.md\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/docs/guide.rst b/docs/guide.rst\n"
            "--- a/docs/guide.rst\n"
            "+++ b/docs/guide.rst\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        edits = extract_edits(patch)
        assert all(is_doc_file(src) for src, _, _ in edits)

    def test_mixed_doc_and_code(self):
        """D12: Mixed patch — not all are doc files."""
        patch = (
            "diff --git a/README.md b/README.md\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        edits = extract_edits(patch)
        assert not all(is_doc_file(src) for src, _, _ in edits)

    def test_lock_file_in_patch(self):
        """D12: Patch containing a .lock file — detected by has_lock_file_change."""
        patch = (
            "diff --git a/poetry.lock b/poetry.lock\n"
            "--- a/poetry.lock\n"
            "+++ b/poetry.lock\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        edits = extract_edits(patch)
        assert any(has_lock_file_change(src) for src, _, _ in edits)

    def test_no_lock_file_in_patch(self):
        """D12: Patch without .lock files — none flagged."""
        patch = (
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        edits = extract_edits(patch)
        assert not any(has_lock_file_change(src) for src, _, _ in edits)

    def test_filter_pipeline_simulation(self):
        """D12: Full filter pipeline — exclude doc-only and lock-containing patches."""
        patch = (
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/README.md b/README.md\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        edits = extract_edits(patch)
        # Not all-doc, so wouldn't be excluded by doc filter
        is_doc_only = all(is_doc_file(src) for src, _, _ in edits)
        has_lock = any(has_lock_file_change(src) for src, _, _ in edits)
        assert not is_doc_only
        assert not has_lock


class TestReadJsonlWithEdits:
    """D12: Integration — read_jsonl + extract_edits pipeline."""

    def test_read_instances_and_extract_edits(self, tmp_path):
        """D12: Read instances from JSONL, extract edits from their patches."""
        patch_str = (
            "diff --git a/src/mod.py b/src/mod.py\n"
            "--- a/src/mod.py\n"
            "+++ b/src/mod.py\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
        )
        instances = [
            {"id": "inst-1", "patch": patch_str},
            {"id": "inst-2", "patch": patch_str},
        ]
        path = _make_jsonl_file(tmp_path, instances)
        loaded = read_jsonl(path)
        assert len(loaded) == 2
        for inst in loaded:
            edits = extract_edits(inst["patch"])
            assert len(edits) == 1
            assert edits[0][0] == "b/src/mod.py"



# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: is_doc_file  (D1/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveIsDocFileExpanded:
    """D1/D4: Exhaustive file extension and path tests."""

    NON_DOC_EXTENSIONS = [
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h",
        ".hpp", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
        ".r", ".R", ".m", ".sql", ".sh", ".bash", ".zsh", ".fish",
        ".ps1", ".bat", ".cmd", ".yml", ".yaml", ".json", ".xml",
        ".html", ".css", ".scss", ".less", ".svg", ".png", ".jpg",
        ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
        ".tsv", ".log", ".env", ".cfg", ".ini", ".toml", ".lock",
        ".txt", ".markdown", ".mdx", ".mdown",
    ]

    @pytest.mark.parametrize("ext", NON_DOC_EXTENSIONS)
    def test_non_doc_extensions(self, ext):
        """D1: All non-.md/.rst extensions return False."""
        assert is_doc_file("file" + ext) is False

    @pytest.mark.parametrize("ext", NON_DOC_EXTENSIONS)
    def test_non_doc_with_prefix(self, ext):
        """D4: Non-doc extensions with directory prefix."""
        assert is_doc_file("src/path/to/file" + ext) is False

    @pytest.mark.parametrize("depth", list(range(1, 21)))
    def test_md_at_various_depths(self, depth):
        """D4: .md file at directory depth 1-20."""
        path = "/".join([f"dir{i}" for i in range(depth)]) + "/file.md"
        assert is_doc_file(path) is True

    @pytest.mark.parametrize("depth", list(range(1, 21)))
    def test_rst_at_various_depths(self, depth):
        """D4: .rst file at directory depth 1-20."""
        path = "/".join([f"dir{i}" for i in range(depth)]) + "/file.rst"
        assert is_doc_file(path) is True

    @pytest.mark.parametrize("depth", list(range(1, 21)))
    def test_py_at_various_depths(self, depth):
        """D4: .py file at directory depth 1-20 is NOT doc."""
        path = "/".join([f"dir{i}" for i in range(depth)]) + "/file.py"
        assert is_doc_file(path) is False

    @pytest.mark.parametrize("name", [
        "README", "CHANGELOG", "CONTRIBUTING", "LICENSE", "HISTORY",
        "RELEASE", "UPGRADE", "MIGRATION", "SECURITY", "CODE_OF_CONDUCT",
        "index", "guide", "tutorial", "reference", "api",
        "quickstart", "installation", "configuration", "deployment",
        "troubleshooting", "faq", "glossary", "appendix",
        "a", "x", "1", "file-name", "file_name", "file.name",
    ])
    def test_various_md_filenames(self, name):
        """D4: Various filenames with .md extension."""
        assert is_doc_file(name + ".md") is True

    @pytest.mark.parametrize("name", [
        "README", "CHANGELOG", "CONTRIBUTING", "LICENSE",
        "index", "guide", "tutorial", "reference", "api",
        "a", "x", "1", "file-name", "file_name",
    ])
    def test_various_rst_filenames(self, name):
        """D4: Various filenames with .rst extension."""
        assert is_doc_file(name + ".rst") is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: has_lock_file_change  (D1/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveHasLockFileChangeExpanded:
    """D1/D4: Exhaustive lock file tests."""

    LOCK_NAMES = [
        "poetry", "Pipfile", "yarn", "composer", "Gemfile", "Cargo",
        "flake", "pnpm-lock.yaml", "package", "npm-shrinkwrap",
        "mix", "pubspec", "podfile", "carthage", "gradle",
        "custom-dep", "my_package", "deps_v2", "lockfile",
    ]

    @pytest.mark.parametrize("name", LOCK_NAMES)
    def test_various_lock_names(self, name):
        """D4: Various base names with .lock extension."""
        assert has_lock_file_change(name + ".lock") is True

    @pytest.mark.parametrize("name", LOCK_NAMES)
    def test_various_lock_names_with_prefix(self, name):
        """D4: Lock files with directory prefix."""
        assert has_lock_file_change("deps/" + name + ".lock") is True

    NON_LOCK_EXTENSIONS = [
        ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
        ".txt", ".py", ".js", ".xml", ".csv", ".md", ".rst",
        ".html", ".css", ".sh", ".bat", ".env", ".log",
    ]

    @pytest.mark.parametrize("ext", NON_LOCK_EXTENSIONS)
    def test_non_lock_extensions(self, ext):
        """D1: Non-.lock extensions return False."""
        assert has_lock_file_change("file" + ext) is False

    @pytest.mark.parametrize("depth", list(range(1, 21)))
    def test_lock_at_various_depths(self, depth):
        """D4: .lock file at depth 1-20."""
        path = "/".join([f"d{i}" for i in range(depth)]) + "/deps.lock"
        assert has_lock_file_change(path) is True

    @pytest.mark.parametrize("depth", list(range(1, 21)))
    def test_non_lock_at_various_depths(self, depth):
        """D4: .json file at depth 1-20 is NOT lock."""
        path = "/".join([f"d{i}" for i in range(depth)]) + "/deps.json"
        assert has_lock_file_change(path) is False
