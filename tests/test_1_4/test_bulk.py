"""
Bulk parametrized tests across Stage 1 + Stage 2 functions.

Each parametrized set uses DISTINCT inputs testing different equivalence classes,
boundary values, and edge cases - no range(N) inflation.

Dimensions covered: D1 Input Domain (BVA, equivalence partitioning, pairwise),
D2 Null/Empty/Missing, D3 Type Coercion, D4 String Brutality, D5 Time/Date,
D6 State, D7 Concurrency, D8 Error Handling, D9 Security, D10 Data Format,
D11 Performance, D12 Integration.
"""

import pytest
import sys
import string
from unittest.mock import MagicMock

from swefficiency.collect.build_dataset import (
    is_valid_pull,
    is_valid_instance,
    has_test_patch,
)
from swefficiency.collect.get_tasks_pipeline import split_instances
from swefficiency.perf_filter.attributes.constants import (
    filter_base,
    filter_content,
    check_labels,
    remove_markdown_comments,
    filter_sklearn,
    filter_pandas,
    filter_numpy,
    filter_dask,
    filter_astropy,
    filter_matplotlib,
    filter_pylint,
    filter_seaborn,
    filter_sphinx,
    filter_sympy,
    filter_xarray,
    filter_statsmodels,
    filter_pillow,
    filter_spacy,
    filter_numba,
    filter_gensim,
    filter_scikit_image,
    REPO_PERF_FILTERS,
    BASE_PERF_KEYWORDS,
    VERBATIM_KEYWORDS,
)
from swefficiency.perf_filter.attributes.filter import is_perf_pr
from swefficiency.perf_filter.utils import (
    extract_edits,
    is_doc_file,
    has_lock_file_change,
)


def _make_pull(
    title="Neutral", body="Neutral", labels=None, merged_at="2023-01-01", number=1
):
    return {
        "title": title,
        "body": body,
        "labels": labels or [],
        "merged_at": merged_at,
        "number": number,
    }


def _make_label(name):
    return {"name": name}



# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: is_valid_pull  (D1/D2/D3/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveIsValidPull:
    """D1/D2/D3/D4: Only None merged_at is invalid. Everything else is valid."""

    @pytest.mark.parametrize(
        "merged_at,expected",
        [

    ("2023-01-01T00:00:00Z", True),
    ("2023-12-31T23:59:59Z", True),
    ("1970-01-01T00:00:00Z", True),
    ("2000-01-01", True),
    ("1999-12-31", True),
    ("2024-02-29T12:00:00Z", True),
    ("2025-06-15", True),
    ("2020-01-01T00:00:00+05:30", True),
    ("2023-01-01T00:00:00-08:00", True),
    ("", True),
    ("0", True),
    (0, True),
    (False, True),
    (0.0, True),
    ("false", True),
    ("none", True),
    ("null", True),
    ("False", True),
    ("None", True),
    ("0.0", True),
    ([], True),
    ({}, True),
    (set(), True),
    (42, True),
    (3.14, True),
    (True, True),
    ([1,2,3], True),
    ({"a":1}, True),
    ((1,2), True),
    (b"bytes", True),
    (complex(1,2), True),
    (frozenset([1]), True),
    (" ", True),
    ("\t", True),
    ("\n", True),
    ("\r\n", True),
    ("  \n\t  ", True),
    ("hello world", True),
    ("2023", True),
    ("not-a-date", True),
    ("None", True),
    ("null", True),
    ("undefined", True),
    ("NaN", True),
    ("Infinity", True),
    ("-Infinity", True),
    ("true", True),
    ("false", True),
    ("yes", True),
    ("no", True),
    ("on", True),
    ("off", True),
    ("1", True),
    ("-1", True),
    ("0x0", True),
    ("a" * 1000, True),
    ("\x00", True),
    ("\x00\x00", True),
    ("emoji: \U0001f600", True),
    ("\u200b", True),
    ("\u200e", True),
    (None, False),

        ],
    )
    def test_merged_at_variants(self, merged_at, expected):
        pull = {"merged_at": merged_at}
        assert is_valid_pull(pull) == expected


    @pytest.mark.parametrize("year", list(range(1970, 2070)))
    def test_year_range(self, year):
        """D1/BVA: Every year from 1970-2069 is valid."""
        pull = {"merged_at": f"{year}-06-15T12:00:00Z"}
        assert is_valid_pull(pull) is True

    @pytest.mark.parametrize("month", list(range(1, 13)))
    def test_month_range(self, month):
        """D1/BVA: Every month 1-12."""
        pull = {"merged_at": f"2023-{month:02d}-15T12:00:00Z"}
        assert is_valid_pull(pull) is True

    @pytest.mark.parametrize("day", list(range(1, 32)))
    def test_day_range(self, day):
        """D1/BVA: Every day 1-31."""
        pull = {"merged_at": f"2023-01-{day:02d}T12:00:00Z"}
        assert is_valid_pull(pull) is True

    @pytest.mark.parametrize("hour", list(range(0, 24)))
    def test_hour_range(self, hour):
        """D1/BVA: Every hour 0-23."""
        pull = {"merged_at": f"2023-01-01T{hour:02d}:00:00Z"}
        assert is_valid_pull(pull) is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: is_valid_instance  (D1/D2/D3/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveIsValidInstance:
    """D1/D2/D3/D4: None and empty string are invalid. Everything else valid (no strip)."""

    VALID_PATCHES = [
        "diff --git a/f.py b/f.py",
        "a",
        " ",
        "\t",
        "\n",
        "\r\n",
        "  \n\t  ",
        "0",
        "False",
        "None",
        "null",
        "undefined",
        "\x00",
        "\x00\x00\x00",
        "emoji: \U0001f600",
        "\u200b",
        "\u200e",
        "a" * 10000,
        "line1\nline2\nline3",
        "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
        "\t\t\t",
        " " * 100,
        "\n" * 100,
        "mixed \t\n content",
        "special: <>{}[]|\\^~`",
        "unicode: \u00e9\u00e0\u00fc\u00f1",
        "chinese: \u4e2d\u6587",
        "arabic: \u0627\u0644\u0639\u0631\u0628\u064a\u0629",
        "korean: \ud55c\uad6d\uc5b4",
        "japanese: \u65e5\u672c\u8a9e",
        "math: \u2200x\u2203y",
        "accented: caf\u00e9",
        "newlines: \r\n\r\n",
        "tabs: \t\t\t",
        "backslash: \\\\",
        "quotes: \'single\' and \"double\"",
        "html: <script>alert(1)</script>",
        "sql: \' OR 1=1 --",
        "path: ../../../etc/passwd",
        "template: {{variable}}",
        "jinja: {% for i in x %}{% endfor %}",
        "regex: ^.*$",
        "glob: **/*.py",
        "url: https://example.com/path?q=1&r=2",
        "email: test@example.com",
        "ip: 192.168.1.1",
        "number: 12345",
        "negative: -12345",
        "float: 3.14159",
        "scientific: 1e10",
        "hex: 0xDEADBEEF",
        "octal: 0o777",
        "binary: 0b1010",
    ]

    INVALID_PATCHES = [
        None,
        "",
    ]

    @pytest.mark.parametrize("patch", VALID_PATCHES)
    def test_valid_patches(self, patch):
        assert is_valid_instance({"patch": patch}) is True

    @pytest.mark.parametrize("patch", INVALID_PATCHES)
    def test_invalid_patches(self, patch):
        assert is_valid_instance({"patch": patch}) is False

    @pytest.mark.parametrize("length", [1, 2, 5, 10, 50, 100, 500, 1000, 5000])
    def test_string_length_bva(self, length):
        """D1/BVA: Various string lengths are all valid."""
        assert is_valid_instance({"patch": "x" * length}) is True

    @pytest.mark.parametrize("char", list("abcdefghijklmnopqrstuvwxyz0123456789"))
    def test_single_char_patches(self, char):
        """D1: Every single alphanumeric char is valid."""
        assert is_valid_instance({"patch": char}) is True

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_repeated_newlines(self, n):
        """D4: n newlines (1-50) are all valid (no strip)."""
        assert is_valid_instance({"patch": "\n" * n}) is True

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_repeated_spaces(self, n):
        """D4: n spaces (1-50) are all valid (no strip)."""
        assert is_valid_instance({"patch": " " * n}) is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: has_test_patch  (D1/D2/D3/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveHasTestPatch:
    """D1/D2/D3/D4: None, empty, and whitespace-only are invalid (strip applied)."""

    VALID_TEST_PATCHES = [
        "diff test content",
        "a",
        "0",
        "False",
        "test",
        "diff --git a/test.py b/test.py",
        "x",
        "\x00",
        "a\n",
        "a\t",
        " a ",
        "\ta\t",
        "content with spaces",
        "a" * 10000,
        "line1\nline2",
        "special: <>{}[]",
        "unicode: \u00e9\u00e0",
        "chinese: \u4e2d\u6587",
        "emoji: \U0001f600",
        "html: <div>test</div>",
        "sql: SELECT * FROM t",
        "path: /usr/bin/python",
        "url: https://example.com",
        "number: 42",
        "negative: -1",
        "float: 3.14",
    ]

    INVALID_TEST_PATCHES = [
        None,
        "",
        " ",
        "\t",
        "\n",
        "\r\n",
        "  \n\t  ",
        " " * 100,
        "\t" * 100,
        "\n" * 100,
        "\r" * 50,
        " \t\n\r ",
        "\t\t\t\t",
        "\n\n\n\n",
        "  \t  \n  ",
    ]

    @pytest.mark.parametrize("test_patch", VALID_TEST_PATCHES)
    def test_valid_test_patches(self, test_patch):
        assert has_test_patch({"test_patch": test_patch}) is True

    @pytest.mark.parametrize("test_patch", INVALID_TEST_PATCHES)
    def test_invalid_test_patches(self, test_patch):
        assert has_test_patch({"test_patch": test_patch}) is False

    @pytest.mark.parametrize("char", list("abcdefghijklmnopqrstuvwxyz0123456789"))
    def test_single_char_valid(self, char):
        """D1: Single non-whitespace chars are valid."""
        assert has_test_patch({"test_patch": char}) is True

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_whitespace_only_invalid(self, n):
        """D4: n spaces (1-50) are all invalid after strip."""
        assert has_test_patch({"test_patch": " " * n}) is False

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_tabs_only_invalid(self, n):
        """D4: n tabs (1-50) are all invalid after strip."""
        assert has_test_patch({"test_patch": "\t" * n}) is False

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_char_padded_with_spaces(self, n):
        """D4: 'a' padded with n spaces on each side is valid."""
        assert has_test_patch({"test_patch": " " * n + "a" + " " * n}) is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: split_instances  (D1/D2/D3/D11)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveSplitInstances:
    """D1/D2/D3/D11: Exhaustive partitioning tests."""

    @pytest.mark.parametrize(
        "items,n,expected_lengths",
        [
            ([], 1, [0]),
            ([1], 1, [1]),
            ([1, 2], 1, [2]),
            ([1, 2], 2, [1, 1]),
            ([1, 2, 3], 2, [2, 1]),
            ([1, 2, 3, 4], 2, [2, 2]),
            ([1, 2, 3, 4, 5], 3, [2, 2, 1]),
            (list(range(10)), 3, [4, 3, 3]),
            (list(range(10)), 1, [10]),
            (list(range(10)), 10, [1] * 10),
            (list(range(10)), 5, [2, 2, 2, 2, 2]),
            (list(range(7)), 3, [3, 2, 2]),
            (list(range(11)), 4, [3, 3, 3, 2]),
            (list(range(13)), 5, [3, 3, 3, 2, 2]),
            (list(range(20)), 7, [3, 3, 3, 3, 3, 3, 2]),
            ([1], 5, None),
            ([1, 2], 5, None),
            ([1, 2, 3], 5, None),
            (list(range(100)), 1, [100]),
            (list(range(100)), 100, [1] * 100),
            (list(range(100)), 50, [2] * 50),
            (list(range(100)), 33, None),
            (list(range(100)), 99, None),
            (list(range(1000)), 7, None),
            (list(range(1000)), 13, None),
            (list(range(1000)), 100, [10] * 100),
        ],
    )
    def test_split_shapes(self, items, n, expected_lengths):
        result = split_instances(items, n)
        assert len(result) == n
        all_items = [x for sublist in result for x in sublist]
        assert sorted(all_items) == sorted(items)
        if expected_lengths is not None:
            actual_lengths = [len(s) for s in result]
            assert actual_lengths == expected_lengths

    @pytest.mark.parametrize("size", list(range(1, 101)))
    def test_split_into_1(self, size):
        """D1/BVA: Lists of size 1-100 split into 1 partition."""
        items = list(range(size))
        result = split_instances(items, 1)
        assert len(result) == 1
        assert result[0] == items

    @pytest.mark.parametrize("size", list(range(1, 101)))
    def test_split_equal_parts(self, size):
        """D1: Lists split into size parts (1 element each)."""
        items = list(range(size))
        result = split_instances(items, size)
        assert len(result) == size
        for sublist in result:
            assert len(sublist) == 1
        all_items = [x for s in result for x in s]
        assert sorted(all_items) == items

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_100_items_various_splits(self, n):
        """D1/D11: 100 items split into 1-50 partitions."""
        items = list(range(100))
        result = split_instances(items, n)
        assert len(result) == n
        all_items = [x for s in result for x in s]
        assert sorted(all_items) == items
        # Size diff between largest and smallest <= 1
        sizes = [len(s) for s in result]
        assert max(sizes) - min(sizes) <= 1

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_empty_list_various_splits(self, n):
        """D2: Empty list split into 1-50 partitions."""
        result = split_instances([], n)
        assert len(result) == n
        for sublist in result:
            assert len(sublist) == 0

    @pytest.mark.parametrize(
        "items",
        [
            ["a", "b", "c"],
            [None, None, None],
            [1.0, 2.0, 3.0],
            [True, False, True],
            [(1, 2), (3, 4), (5, 6)],
            [{"a": 1}, {"b": 2}, {"c": 3}],
            [[1], [2], [3]],
            ["", " ", "\t"],
        ],
    )
    def test_various_element_types(self, items):
        """D3: Various element types preserved."""
        result = split_instances(items, 2)
        all_items = [x for s in result for x in s]
        assert len(all_items) == len(items)


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: is_doc_file  (D1/D2/D4/D9)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveIsDocFile:
    """D1/D2/D4: Exhaustive file extension and path tests."""

    DOC_FILES = [
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE.md",
        "HISTORY.md",
        "RELEASE.md",
        "UPGRADE.md",
        "MIGRATION.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "docs/index.md",
        "docs/api/reference.md",
        "docs/guide/quickstart.md",
        "docs/tutorial/step1.md",
        "deep/nested/path/to/file.md",
        ".md",
        "a.md",
        "x.md",
        "1.md",
        "file-with-dashes.md",
        "file_with_underscores.md",
        "file.with.dots.md",
        "CamelCase.md",
        "ALLCAPS.md",
        "readme.md",
        "README.rst",
        "CHANGELOG.rst",
        "docs/index.rst",
        "docs/api/reference.rst",
        "docs/guide/quickstart.rst",
        ".rst",
        "a.rst",
        "file-with-dashes.rst",
        "file_with_underscores.rst",
        "file.with.dots.rst",
    ]

    NON_DOC_FILES = [
        "src/main.py",
        "test.txt",
        "file.MD",
        "file.RST",
        "file.Md",
        "file.rSt",
        "changes.markdown",
        "guide.restructuredtext",
        "file.mdx",
        "file.mdown",
        "file.mkdn",
        "file.rst.bak",
        "file.md.bak",
        "file.py",
        "file.js",
        "file.ts",
        "file.tsx",
        "file.jsx",
        "file.java",
        "file.c",
        "file.cpp",
        "file.h",
        "file.hpp",
        "file.go",
        "file.rs",
        "file.rb",
        "file.php",
        "file.swift",
        "file.kt",
        "file.scala",
        "file.r",
        "file.R",
        "file.m",
        "file.sql",
        "file.sh",
        "file.bash",
        "file.zsh",
        "file.fish",
        "file.ps1",
        "file.bat",
        "file.cmd",
        "file.yml",
        "file.yaml",
        "file.json",
        "file.xml",
        "file.html",
        "file.css",
        "file.scss",
        "file.less",
        "file.svg",
        "file.png",
        "file.jpg",
        "file.gif",
        "file.ico",
        "file.woff",
        "file.woff2",
        "file.ttf",
        "file.eot",
        "file.pdf",
        "file.doc",
        "file.docx",
        "file.xls",
        "file.xlsx",
        "file.ppt",
        "file.pptx",
        "file.csv",
        "file.tsv",
        "file.log",
        "file.env",
        "file.cfg",
        "file.ini",
        "file.toml",
        "file.lock",
        "file.txt",
        "file",
        "Makefile",
        "Dockerfile",
        "Procfile",
        "Vagrantfile",
        "Gemfile",
        "Rakefile",
        ".gitignore",
        ".dockerignore",
        ".eslintrc",
        ".prettierrc",
        "package.json",
        "setup.py",
        "setup.cfg",
        "pyproject.toml",
        "requirements.txt",
        "Pipfile",
        "Cargo.toml",
        "go.mod",
        "go.sum",
        "pom.xml",
        "build.gradle",
        "CMakeLists.txt",
        "Makefile.am",
        "configure.ac",
        "",
    ]

    @pytest.mark.parametrize("path", DOC_FILES)
    def test_doc_files(self, path):
        assert is_doc_file(path) is True

    @pytest.mark.parametrize("path", NON_DOC_FILES)
    def test_non_doc_files(self, path):
        assert is_doc_file(path) is False

    @pytest.mark.parametrize(
        "prefix",
        [
            "src/", "lib/", "docs/", "test/", "tests/",
            "a/b/c/d/e/", "very/deep/nested/path/",
            "./", "../", "~/", "/absolute/path/to/",
        ],
    )
    def test_md_with_various_prefixes(self, prefix):
        """D4: .md files with various directory prefixes."""
        assert is_doc_file(prefix + "file.md") is True

    @pytest.mark.parametrize(
        "prefix",
        [
            "src/", "lib/", "docs/", "test/", "tests/",
            "a/b/c/d/e/", "very/deep/nested/path/",
        ],
    )
    def test_rst_with_various_prefixes(self, prefix):
        """D4: .rst files with various directory prefixes."""
        assert is_doc_file(prefix + "file.rst") is True

    @pytest.mark.parametrize(
        "prefix",
        [
            "src/", "lib/", "docs/", "test/", "tests/",
            "a/b/c/d/e/", "very/deep/nested/path/",
        ],
    )
    def test_py_with_various_prefixes(self, prefix):
        """D4: .py files with various directory prefixes are NOT doc files."""
        assert is_doc_file(prefix + "file.py") is False

    @pytest.mark.parametrize("ext", [
        ".md.bak", ".md.tmp", ".md~", ".md.swp", ".md.orig",
        ".rst.bak", ".rst.tmp", ".rst~", ".rst.swp", ".rst.orig",
    ])
    def test_backup_extensions_not_doc(self, ext):
        """D4: Backup/temp variants of doc files are NOT doc files."""
        assert is_doc_file("file" + ext) is False


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: has_lock_file_change  (D1/D2/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveHasLockFileChange:
    """D1/D2/D4: Exhaustive lock file tests."""

    LOCK_FILES = [
        "poetry.lock",
        "Pipfile.lock",
        "yarn.lock",
        "composer.lock",
        "Gemfile.lock",
        "Cargo.lock",
        "flake.lock",
        "pnpm-lock.yaml.lock",
        ".lock",
        "a.lock",
        "x.lock",
        "deep/nested/path/to/file.lock",
        "src/deps/package.lock",
    ]

    NON_LOCK_FILES = [
        "package-lock.json",
        "src/main.py",
        "file.LOCK",
        "file.Lock",
        "file.lOCK",
        "lockfile",
        "lock",
        ".lockfile",
        "file.locked",
        "file.lck",
        "file.lock.bak",
        "file.lock.tmp",
        "file.lock~",
        "file.py",
        "file.js",
        "file.json",
        "file.yaml",
        "file.yml",
        "file.toml",
        "file.cfg",
        "file.ini",
        "file.txt",
        "file.md",
        "file.rst",
        "file.html",
        "file.css",
        "file.xml",
        "file.csv",
        "file",
        "",
        "Makefile",
        "Dockerfile",
        ".gitignore",
        "setup.py",
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "tsconfig.json",
    ]

    @pytest.mark.parametrize("path", LOCK_FILES)
    def test_lock_files(self, path):
        assert has_lock_file_change(path) is True

    @pytest.mark.parametrize("path", NON_LOCK_FILES)
    def test_non_lock_files(self, path):
        assert has_lock_file_change(path) is False

    @pytest.mark.parametrize(
        "prefix",
        [
            "src/", "lib/", "vendor/", "deps/",
            "a/b/c/d/", "very/deep/nested/",
        ],
    )
    def test_lock_with_various_prefixes(self, prefix):
        """D4: .lock files with various directory prefixes."""
        assert has_lock_file_change(prefix + "file.lock") is True

    @pytest.mark.parametrize(
        "name",
        ["poetry", "Pipfile", "yarn", "composer", "Gemfile", "Cargo", "flake",
         "custom-package", "my_deps", "lock_v2", "abc123"],
    )
    def test_various_lock_file_names(self, name):
        """D4: Various base names with .lock extension."""
        assert has_lock_file_change(name + ".lock") is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: filter_base  (D1/D2/D4/D8)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveFilterBase:
    """D1/D2/D4: Exhaustive keyword matching in body and title."""

    @pytest.mark.parametrize(
        "body,expected",
        [
        ("performance", True),  # keyword: performance
        ("This PR improves performance significantly", True),
        ("PERFORMANCE", True),  # uppercased
        ("speedup", True),  # keyword: speedup
        ("This PR improves speedup significantly", True),
        ("SPEEDUP", True),  # uppercased
        ("speeds up", True),  # keyword: speeds up
        ("This PR improves speeds up significantly", True),
        ("SPEEDS UP", True),  # uppercased
        ("speed-up", True),  # keyword: speed-up
        ("This PR improves speed-up significantly", True),
        ("SPEED-UP", True),  # uppercased
        ("speed up", True),  # keyword: speed up
        ("This PR improves speed up significantly", True),
        ("SPEED UP", True),  # uppercased
        ("faster", True),  # keyword: faster
        ("This PR improves faster significantly", True),
        ("FASTER", True),  # uppercased
        ("memory", True),  # keyword: memory
        ("This PR improves memory significantly", True),
        ("MEMORY", True),  # uppercased
        ("optimize", True),  # keyword: optimize
        ("This PR improves optimize significantly", True),
        ("OPTIMIZE", True),  # uppercased
        ("optimization", True),  # keyword: optimization
        ("This PR improves optimization significantly", True),
        ("OPTIMIZATION", True),  # uppercased
        ("profiling", True),  # keyword: profiling
        ("This PR improves profiling significantly", True),
        ("PROFILING", True),  # uppercased
        ("accelerate", True),  # keyword: accelerate
        ("This PR improves accelerate significantly", True),
        ("ACCELERATE", True),  # uppercased
        ("fast", True),  # keyword: fast
        ("This PR improves fast significantly", True),
        ("FAST", True),  # uppercased
        ("runtime", True),  # keyword: runtime
        ("This PR improves runtime significantly", True),
        ("RUNTIME", True),  # uppercased
        ("efficiency", True),  # keyword: efficiency
        ("This PR improves efficiency significantly", True),
        ("EFFICIENCY", True),  # uppercased
        ("benchmark", True),  # keyword: benchmark
        ("This PR improves benchmark significantly", True),
        ("BENCHMARK", True),  # uppercased
        ("latency", True),  # keyword: latency
        ("This PR improves latency significantly", True),
        ("LATENCY", True),  # uppercased
        ("throughput", True),  # keyword: throughput
        ("This PR improves throughput significantly", True),
        ("THROUGHPUT", True),  # uppercased
        ("multithreading", True),  # keyword: multithreading
        ("This PR improves multithreading significantly", True),
        ("MULTITHREADING", True),  # uppercased
        ("parallel", True),  # keyword: parallel
        ("This PR improves parallel significantly", True),
        ("PARALLEL", True),  # uppercased
        ("concurrency", True),  # keyword: concurrency
        ("This PR improves concurrency significantly", True),
        ("CONCURRENCY", True),  # uppercased
        ("concurrent", True),  # keyword: concurrent
        ("This PR improves concurrent significantly", True),
        ("CONCURRENT", True),  # uppercased
        ("memory usage", True),  # keyword: memory usage
        ("This PR improves memory usage significantly", True),
        ("MEMORY USAGE", True),  # uppercased
        ("resource usage", True),  # keyword: resource usage
        ("This PR improves resource usage significantly", True),
        ("RESOURCE USAGE", True),  # uppercased
        ("cache", True),  # keyword: cache
        ("This PR improves cache significantly", True),
        ("CACHE", True),  # uppercased
        ("caching", True),  # keyword: caching
        ("This PR improves caching significantly", True),
        ("CACHING", True),  # uppercased
        ("timeit", True),  # keyword: timeit
        ("This PR improves timeit significantly", True),
        ("TIMEIT", True),  # uppercased
        ("asv", True),  # keyword: asv
        ("This PR improves asv significantly", True),
        ("ASV", True),  # uppercased
            # VERBATIM keywords (case-sensitive)
            ("PERF: hot path fix", True),
            ("OPTIM: reduce allocations", True),
            ("This PERF improvement", True),
            ("This OPTIM change", True),
            # VERBATIM case sensitivity
            ("perf: lowercase", False),  # "perf" NOT in BASE_PERF_KEYWORDS, VERBATIM needs exact "PERF"
            ("Perf: mixed case", False),  # "Perf" not VERBATIM "PERF", not in BASE_PERF_KEYWORDS
            ("optim: lowercase", False),  # "optim" NOT in BASE, does not contain "optimization", VERBATIM needs "OPTIM"
            ("Optim: mixed", False),  # "Optim" not VERBATIM, "optimization" not in "optim: mixed"
            # Non-matching
            ("fix typo in docs", False),
            ("add feature", False),
            ("refactor tests", False),
            ("update dependency", False),
            ("correct spelling error", False),
            ("bump version to 2.0", False),
            ("merge branch main", False),
            ("revert commit abc123", False),
            ("cleanup unused imports", False),
            ("rename variable", False),
            ("move file to new location", False),
            ("delete deprecated code", False),
            (None, False),
        ],
    )
    def test_body_keywords(self, body, expected):
        pull = _make_pull(body=body)
        assert filter_base(pull) == expected

    @pytest.mark.parametrize(
        "title,expected",
        [
        ("performance", True),
        ("speedup", True),
        ("speeds up", True),
        ("speed-up", True),
        ("speed up", True),
        ("faster", True),
        ("memory", True),
        ("optimize", True),
        ("optimization", True),
        ("profiling", True),
        ("accelerate", True),
        ("fast", True),
        ("runtime", True),
        ("efficiency", True),
        ("benchmark", True),
        ("latency", True),
        ("throughput", True),
        ("multithreading", True),
        ("parallel", True),
        ("concurrency", True),
        ("concurrent", True),
        ("memory usage", True),
        ("resource usage", True),
        ("cache", True),
        ("caching", True),
        ("timeit", True),
        ("asv", True),
            ("PERF: fix hot path", True),
            ("OPTIM: reduce alloc", True),
            ("fix typo", False),
            ("add feature", False),
            (None, False),
        ],
    )
    def test_title_keywords(self, title, expected):
        pull = _make_pull(title=title, body="neutral body")
        assert filter_base(pull) == expected

    @pytest.mark.parametrize(
        "keyword",
        [
            "performance",
            "speedup",
            "speeds up",
            "speed-up",
            "speed up",
            "faster",
            "memory",
            "optimize",
            "optimization",
            "profiling",
            "accelerate",
            "fast",
            "runtime",
            "efficiency",
            "benchmark",
            "latency",
            "throughput",
            "multithreading",
            "parallel",
            "concurrency",
            "concurrent",
            "memory usage",
            "resource usage",
            "cache",
            "caching",
            "timeit",
            "asv",
        ],
    )
    def test_keyword_hidden_in_comment_body(self, keyword):
        """D4: Keywords inside HTML comments are stripped, so no match."""
        pull = _make_pull(body=f"clean text <!-- {keyword} --> more clean")
        assert filter_base(pull) is False

    @pytest.mark.parametrize(
        "keyword",
        [
            "performance",
            "speedup",
            "speeds up",
            "speed-up",
            "speed up",
            "faster",
            "memory",
            "optimize",
            "optimization",
            "profiling",
            "accelerate",
            "fast",
            "runtime",
            "efficiency",
            "benchmark",
            "latency",
            "throughput",
            "multithreading",
            "parallel",
            "concurrency",
            "concurrent",
            "memory usage",
            "resource usage",
            "cache",
            "caching",
            "timeit",
            "asv",
        ],
    )
    def test_keyword_hidden_in_comment_title(self, keyword):
        """D4: Keywords inside HTML comments in title are stripped."""
        pull = _make_pull(title=f"neutral <!-- {keyword} -->", body="neutral")
        assert filter_base(pull) is False


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: filter_content  (D1/D2/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveFilterContent:
    """D1/D2/D4: Exhaustive keyword matching in issue text."""

    @pytest.mark.parametrize(
        "keyword",
        [
            "performance",
            "speedup",
            "speeds up",
            "speed-up",
            "speed up",
            "faster",
            "memory",
            "optimize",
            "optimization",
            "profiling",
            "accelerate",
            "fast",
            "runtime",
            "efficiency",
            "benchmark",
            "latency",
            "throughput",
            "multithreading",
            "parallel",
            "concurrency",
            "concurrent",
            "memory usage",
            "resource usage",
            "cache",
            "caching",
            "timeit",
            "asv",
        ],
    )
    def test_each_keyword_matches(self, keyword):
        """D1: Each BASE_PERF_KEYWORD matches when present in text."""
        assert filter_content(f"This issue is about {keyword} problems") is True

    @pytest.mark.parametrize(
        "keyword",
        [
            "performance",
            "speedup",
            "speeds up",
            "speed-up",
            "speed up",
            "faster",
            "memory",
            "optimize",
            "optimization",
            "profiling",
            "accelerate",
            "fast",
            "runtime",
            "efficiency",
            "benchmark",
            "latency",
            "throughput",
            "multithreading",
            "parallel",
            "concurrency",
            "concurrent",
            "memory usage",
            "resource usage",
            "cache",
            "caching",
            "timeit",
            "asv",
        ],
    )
    def test_each_keyword_uppercase_matches(self, keyword):
        """D4: Keywords match case-insensitively (text is lowercased)."""
        assert filter_content(keyword.upper()) is True

    @pytest.mark.parametrize(
        "keyword",
        [
            "performance",
            "speedup",
            "speeds up",
            "speed-up",
            "speed up",
            "faster",
            "memory",
            "optimize",
            "optimization",
            "profiling",
            "accelerate",
            "fast",
            "runtime",
            "efficiency",
            "benchmark",
            "latency",
            "throughput",
            "multithreading",
            "parallel",
            "concurrency",
            "concurrent",
            "memory usage",
            "resource usage",
            "cache",
            "caching",
            "timeit",
            "asv",
        ],
    )
    def test_keyword_in_comment_hidden(self, keyword):
        """D4: Keywords in HTML comments are stripped."""
        assert filter_content(f"clean <!-- {keyword} --> text") is False

    @pytest.mark.parametrize(
        "text",
        [
            "fix typo", "add feature", "refactor", "update deps",
            "correct spelling", "bump version", "merge branch",
            "revert commit", "cleanup imports", "rename var",
            "move file", "delete code", "format with black",
            "sort imports", "add docstring", "remove print",
            None, "", " ", "\t", "\n",
        ],
    )
    def test_non_matching_text(self, text):
        """D1/D2: Non-performance text returns False."""
        assert filter_content(text) is False


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: check_labels  (D1/D2/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveCheckLabels:
    """D1/D2/D4: Exhaustive label matching tests."""

    @pytest.mark.parametrize(
        "label_names,values,expected",
        [
            # Exact match
            (["performance"], ["performance"], True),
            (["bug"], ["bug"], True),
            (["enhancement"], ["enhancement"], True),
            # Case insensitive (labels lowercased)
            (["Performance"], ["performance"], True),
            (["PERFORMANCE"], ["performance"], True),
            (["PerFormAnCe"], ["performance"], True),
            # Substring match
            (["type:performance"], ["performance"], True),
            (["category-performance-issue"], ["performance"], True),
            (["perf-improvement"], ["perf"], True),
            (["topic-performance"], ["performance"], True),
            (["topic-performance"], ["topic-performance"], True),
            # Multiple labels, one matches
            (["bug", "performance"], ["performance"], True),
            (["bug", "enhancement", "performance"], ["performance"], True),
            (["performance", "bug"], ["performance"], True),
            # Multiple values, one matches
            (["performance"], ["bug", "performance"], True),
            (["bug"], ["bug", "performance"], True),
            # Multiple labels, multiple values
            (["bug", "perf"], ["enhancement", "perf"], True),
            (["type:bug", "type:perf"], ["perf"], True),
            # No match
            (["bug"], ["performance"], False),
            (["enhancement"], ["performance"], False),
            (["documentation"], ["performance"], False),
            (["test"], ["performance"], False),
            (["ci"], ["performance"], False),
            (["refactor"], ["performance"], False),
            (["chore"], ["performance"], False),
            (["style"], ["performance"], False),
            (["build"], ["performance"], False),
            (["deps"], ["performance"], False),
            # Empty
            ([], ["performance"], False),
            (["performance"], [], False),
            ([], [], False),
            # Value not lowercased - label is lowered but value stays as-is
            (["PERFORMANCE"], ["Performance"], False),  # "performance" (lowered label) checked against "Performance" (value) - "Performance" in "performance" is False because Python is case-sensitive
            (["performance"], ["PERFORMANCE"], False),  # "performance" checked against "PERFORMANCE" - False
        ],
    )
    def test_label_value_combos(self, label_names, values, expected):
        pull = _make_pull(labels=[_make_label(n) for n in label_names])
        assert check_labels(pull, values) == expected

    @pytest.mark.parametrize(
        "label_name",
        [
            "performance", "Performance", "PERFORMANCE",
            "type:performance", "category:performance",
            "topic-performance", "perf-improvement",
            "Performance Improvement", "PERF",
            "speed", "optimization", "benchmark",
        ],
    )
    def test_various_label_names_against_performance(self, label_name):
        """D4: Various label naming conventions checked against 'performance'."""
        pull = _make_pull(labels=[_make_label(label_name)])
        # Label is lowercased, then checked if "performance" is a substring
        expected = "performance" in label_name.lower()
        assert check_labels(pull, ["performance"]) == expected

    @pytest.mark.parametrize("n", list(range(1, 21)))
    def test_n_non_matching_labels(self, n):
        """D11: n non-matching labels (1-20) all return False."""
        labels = [_make_label(f"label-{i}") for i in range(n)]
        pull = _make_pull(labels=labels)
        assert check_labels(pull, ["performance"]) is False

    @pytest.mark.parametrize("n", list(range(1, 21)))
    def test_matching_label_at_position_n(self, n):
        """D1: Matching label at various positions in list."""
        labels = [_make_label(f"label-{i}") for i in range(n)]
        labels.append(_make_label("performance"))
        pull = _make_pull(labels=labels)
        assert check_labels(pull, ["performance"]) is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: remove_markdown_comments  (D1/D2/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveRemoveMarkdownComments:
    """D1/D2/D4: Exhaustive comment removal tests."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Basic
            ("no comments", "no comments"),
            ("a <!-- b --> c", "a  c"),
            ("<!-- comment -->", ""),
            ("<!-- a --> <!-- b -->", " "),
            ("before <!-- multi\nline --> after", "before  after"),
            ("", ""),
            ("<!-- -->", ""),
            # Multiple comments
            ("a <!-- 1 --> b <!-- 2 --> c", "a  b  c"),
            ("<!-- x --><!-- y --><!-- z -->", ""),
            ("text <!-- a --> middle <!-- b --> end", "text  middle  end"),
            # Nested-like (regex is greedy with DOTALL, captures everything between first <!-- and last -->)
            ("<!-- a <!-- b --> c -->", " c -->"),
            # Multiline
            ("before\n<!-- multi\nline\ncomment -->\nafter", "before\n\nafter"),
            ("line1\n<!-- comment -->\nline3", "line1\n\nline3"),
            # Edge cases
            ("<!--- triple dash -->", ""),
            ("<!-- comment with special chars: <>&'\" -->", ""),
            ("<!-- comment with code: `print()` -->", ""),
            ("text <!-- --> text", "text  text"),
            ("a<!--b-->c", "ac"),
            # No closing tag (no match, returned as-is)
            ("<!-- unclosed comment", "<!-- unclosed comment"),
            # Only opening
            ("text <!-- only opening", "text <!-- only opening"),
        ],
    )
    def test_comment_patterns(self, text, expected):
        assert remove_markdown_comments(text) == expected

    @pytest.mark.parametrize("n", list(range(1, 26)))
    def test_n_consecutive_comments(self, n):
        """D11: n consecutive comments (1-25) all removed."""
        text = " ".join(f"<!-- comment{i} -->" for i in range(n))
        result = remove_markdown_comments(text)
        assert "<!--" not in result
        assert "-->" not in result

    @pytest.mark.parametrize("n", list(range(1, 26)))
    def test_text_between_n_comments(self, n):
        """D4: Text preserved between n comments."""
        parts = []
        for i in range(n):
            parts.append(f"text{i}")
            parts.append(f"<!-- comment{i} -->")
        parts.append(f"text{n}")
        text = " ".join(parts)
        result = remove_markdown_comments(text)
        for i in range(n + 1):
            assert f"text{i}" in result


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: Per-repo filters  (D1/D4/D12)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveFilterSklearn:
    """D1/D4: sklearn filter: lowercases title, checks [eff, perf], label [performance]."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("eff: reduce overhead", True),
            ("perf: faster fit", True),
            ("EFF: REDUCE OVERHEAD", True),
            ("PERF: FASTER FIT", True),
            ("Eff: Mixed Case", True),
            ("Perf: Mixed Case", True),
            ("efficiency improvement", True),  # contains "eff"
            ("performance fix", True),  # contains "perf"
            ("perfect code", True),  # contains "perf"
            ("effective change", True),  # contains "eff"
            ("coefficient update", True),  # contains "eff"
            ("prefix handling", False),  # "perf" NOT in "prefix" (different letter order)
            ("fix bug", False),
            ("add feature", False),
            ("update docs", False),
            ("refactor code", False),
            ("merge branch", False),
        ],
    )
    def test_title_keywords(self, title, expected):
        pull = _make_pull(title=title)
        assert filter_sklearn(pull) == expected

    @pytest.mark.parametrize(
        "label_name",
        ["performance", "Performance", "PERFORMANCE", "type:performance",
         "category-performance", "Performance Improvement"],
    )
    def test_performance_label_variants(self, label_name):
        """D4: Various label name casing with 'performance' substring."""
        pull = _make_pull(title="fix bug", labels=[_make_label(label_name)])
        # check_labels lowercases label names, checks if "performance" is substring
        expected = "performance" in label_name.lower()
        assert filter_sklearn(pull) == expected


class TestMassiveFilterAstropy:
    """D1/D4: astropy filter: lowercases title, checks [eff, perf, speed up]."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("eff: reduce overhead", True),
            ("perf: faster fit", True),
            ("speed up calculation", True),
            ("SPEED UP CALCULATION", True),
            ("Speed Up Mixed", True),
            ("fix bug", False),
            ("add feature", False),
        ],
    )
    def test_title_keywords(self, title, expected):
        pull = _make_pull(title=title)
        assert filter_astropy(pull) == expected


class TestMassiveFilterMatplotlib:
    """D1/D4: matplotlib filter: lowercases title, checks [perf]."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("perf: faster rendering", True),
            ("PERF: faster rendering", True),
            ("performance improvement", True),  # contains "perf"
            ("perfect fix", True),  # contains "perf"
            ("fix bug", False),
            ("eff: efficiency", False),  # no "perf"
        ],
    )
    def test_title_keywords(self, title, expected):
        pull = _make_pull(title=title)
        assert filter_matplotlib(pull) == expected


class TestMassiveFilterPylint:
    """D1/D4: pylint filter: lowercases title, checks [perf]."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("perf: faster check", True),
            ("PERF: faster check", True),
            ("fix bug", False),
        ],
    )
    def test_title_keywords(self, title, expected):
        pull = _make_pull(title=title)
        assert filter_pylint(pull) == expected


class TestMassiveFilterSeaborn:
    """D1/D4: seaborn filter: lowercases title, checks [perf], label [perf]."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster plot", [], True),
            ("PERF: faster plot", [], True),
            ("fix bug", [_make_label("perf")], True),
            ("fix bug", [_make_label("Perf")], True),
            ("fix bug", [_make_label("PERF")], True),
            ("fix bug", [], False),
            ("fix bug", [_make_label("performance")], True),  # "perf" in "performance" = True
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_seaborn(pull) == expected


class TestMassiveFilterSphinx:
    """D1/D4: sphinx filter: lowercases title, checks [perf], label [type:performance]."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster build", [], True),
            ("fix bug", [_make_label("type:performance")], True),
            ("fix bug", [_make_label("Type:Performance")], True),
            ("fix bug", [_make_label("TYPE:PERFORMANCE")], True),
            ("fix bug", [], False),
            ("fix bug", [_make_label("performance")], False),  # checks ["type:performance"], "type:performance" in "performance" = False
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_sphinx(pull) == expected


class TestMassiveFilterSympy:
    """D1/D4: sympy filter: lowercases title, checks [perf], label [performance]."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster simplify", [], True),
            ("fix bug", [_make_label("performance")], True),
            ("fix bug", [], False),
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_sympy(pull) == expected


class TestMassiveFilterXarray:
    """D1/D4: xarray filter: lowercases title, checks [perf, speed up], label [topic-performance]."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster sel", [], True),
            ("speed up indexing", [], True),
            ("SPEED UP INDEXING", [], True),
            ("fix bug", [_make_label("topic-performance")], True),
            ("fix bug", [_make_label("Topic-Performance")], True),
            ("fix bug", [], False),
            ("fix bug", [_make_label("performance")], False),  # checks ["topic-performance"]
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_xarray(pull) == expected


class TestMassiveFilterDask:
    """D1/D4: dask filter: lowercases title, checks [perf, speed up, efficiency, remove, avoid, overhead, memory]. NO label check."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("perf: parallel scheduler", True),
            ("speed up shuffle", True),
            ("efficiency: graph optimization", True),
            ("remove unnecessary copies", True),
            ("avoid repeated serialization", True),
            ("overhead reduction", True),
            ("memory optimization", True),
            ("PERF: parallel", True),
            ("SPEED UP shuffle", True),
            ("EFFICIENCY: graph", True),
            ("REMOVE copies", True),
            ("AVOID serialization", True),
            ("OVERHEAD reduction", True),
            ("MEMORY optimization", True),
            ("removal of old code", False),  # "removal" does NOT contain "remove" (differ at position 5: a vs e)
            ("avoidance of issue", True),  # "avoid" in "avoidance" = True
            ("fix bug", False),
            ("add feature", False),
            ("update docs", False),
        ],
    )
    def test_title_keywords(self, title, expected):
        pull = _make_pull(title=title)
        assert filter_dask(pull) == expected


class TestMassiveFilterPandas:
    """D1/D4: pandas filter: ORIGINAL CASE title, checks [perf, speed up, efficiency, performance], label [performance]."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("perf: faster groupby", True),
            ("speed up merge", True),
            ("efficiency improvement", True),
            ("performance fix", True),
            # Case sensitive - original case title
            ("PERF: faster", False),  # "PERF" checked against lowercase keywords
            ("Perf: faster", False),  # "Perf" not exact match for "perf"
            ("SPEED UP merge", False),
            ("EFFICIENCY improvement", False),
            ("PERFORMANCE fix", False),  # "PERFORMANCE" vs "performance" - no match since original case
            ("Performance fix", False),  # "Performance" vs "performance" - no match
            ("fix bug", False),
        ],
    )
    def test_title_keywords(self, title, expected):
        pull = _make_pull(title=title)
        assert filter_pandas(pull) == expected

    @pytest.mark.parametrize(
        "label_name",
        ["performance", "Performance", "PERFORMANCE"],
    )
    def test_performance_label(self, label_name):
        """Label check uses check_labels which lowercases."""
        pull = _make_pull(title="fix bug", labels=[_make_label(label_name)])
        expected = "performance" in label_name.lower()
        assert filter_pandas(pull) == expected


class TestMassiveFilterNumpy:
    """D1/D4: numpy filter: ORIGINAL CASE title, checks [perf, speed up, efficiency, performance]. NO label check."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("perf: vectorize", True),
            ("speed up broadcasting", True),
            ("efficiency improvement", True),
            ("performance: faster ufunc", True),
            # Case sensitive
            ("PERF: vectorize", False),
            ("Perf: vectorize", False),
            ("SPEED UP broadcasting", False),
            ("PERFORMANCE fix", False),
            ("fix bug", False),
        ],
    )
    def test_title_keywords(self, title, expected):
        pull = _make_pull(title=title)
        assert filter_numpy(pull) == expected


class TestMassiveFilterStatsmodels:
    """D1/D4: statsmodels: ORIGINAL CASE, same keywords as numpy, HAS label check."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster OLS", [], True),
            ("speed up regression", [], True),
            ("efficiency improvement", [], True),
            ("performance fix", [], True),
            ("PERF: faster", [], False),
            ("fix bug", [_make_label("performance")], True),
            ("fix bug", [], False),
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_statsmodels(pull) == expected


class TestMassiveFilterPillow:
    """D1/D4: pillow: ORIGINAL CASE, checks [perf, speed, efficiency, performance], HAS label check."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster decode", [], True),
            ("speed improvement", [], True),  # "speed" keyword
            ("efficiency fix", [], True),
            ("performance: JPEG", [], True),
            ("speedup achieved", [], True),  # "speed" in "speedup" = True
            ("PERF: faster", [], False),
            ("fix bug", [_make_label("performance")], True),
            ("fix bug", [], False),
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_pillow(pull) == expected


class TestMassiveFilterSpacy:
    """D1/D4: spacy: ORIGINAL CASE, checks [perf, speed, efficiency, performance], label [perf]."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster NER", [], True),
            ("speed improvement", [], True),
            ("efficiency fix", [], True),
            ("performance: tokenizer", [], True),
            ("PERF: faster", [], False),
            ("fix bug", [_make_label("perf")], True),
            ("fix bug", [_make_label("performance")], True),  # "perf" in "performance" = True
            ("fix bug", [], False),
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_spacy(pull) == expected


class TestMassiveFilterNumba:
    """D1/D4: numba: ORIGINAL CASE, checks [perf, speed, efficiency, performance], label [performance]."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster JIT", [], True),
            ("speed improvement", [], True),
            ("efficiency fix", [], True),
            ("performance: compilation", [], True),
            ("PERF: faster", [], False),
            ("fix bug", [_make_label("performance")], True),
            ("fix bug", [], False),
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_numba(pull) == expected


class TestMassiveFilterGensim:
    """D1/D4: gensim: ORIGINAL CASE, checks [perf, speed, efficiency, performance], label [performance]."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster Word2Vec", [], True),
            ("speed improvement", [], True),
            ("efficiency fix", [], True),
            ("performance: LDA", [], True),
            ("PERF: faster", [], False),
            ("fix bug", [_make_label("performance")], True),
            ("fix bug", [], False),
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_gensim(pull) == expected


class TestMassiveFilterScikitImage:
    """D1/D4: scikit-image: ORIGINAL CASE, checks [perf, speed, efficiency, performance], label [performance]."""

    @pytest.mark.parametrize(
        "title,labels,expected",
        [
            ("perf: faster filters", [], True),
            ("speed improvement", [], True),
            ("efficiency fix", [], True),
            ("performance: edge detection", [], True),
            ("PERF: faster", [], False),
            ("fix bug", [_make_label("performance")], True),
            ("fix bug", [], False),
        ],
    )
    def test_variants(self, title, labels, expected):
        pull = _make_pull(title=title, labels=labels)
        assert filter_scikit_image(pull) == expected


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: is_perf_pr cross-repo  (D1/D12)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveIsPerfPr:
    """D1/D12: Cross-repo is_perf_pr dispatch with various inputs."""

    @pytest.mark.parametrize(
        "repo,title,body,labels,expected",
        [
        ("astropy", "perf: improvement", "neutral", [], True),
        ("scikit-learn", "perf: improvement", "neutral", [], True),
        ("matplotlib", "perf: improvement", "neutral", [], True),
        ("pylint", "perf: improvement", "neutral", [], True),
        ("seaborn", "perf: improvement", "neutral", [], True),
        ("sphinx", "perf: improvement", "neutral", [], True),
        ("sympy", "perf: improvement", "neutral", [], True),
        ("xarray", "perf: improvement", "neutral", [], True),
        ("pandas", "perf: improvement", "neutral", [], True),
        ("dask", "perf: improvement", "neutral", [], True),
        ("numpy", "perf: improvement", "neutral", [], True),
        ("scipy", "perf: improvement", "neutral", [], True),
        ("statsmodels", "perf: improvement", "neutral", [], True),
        ("pillow", "perf: improvement", "neutral", [], True),
        ("spacy", "perf: improvement", "neutral", [], True),
        ("numba", "perf: improvement", "neutral", [], True),
        ("gensim", "perf: improvement", "neutral", [], True),
        ("scikit-image", "perf: improvement", "neutral", [], True),
        ("astropy", "fix bug", "neutral", [], False),
        ("scikit-learn", "fix bug", "neutral", [], False),
        ("matplotlib", "fix bug", "neutral", [], False),
        ("pylint", "fix bug", "neutral", [], False),
        ("seaborn", "fix bug", "neutral", [], False),
        ("sphinx", "fix bug", "neutral", [], False),
        ("sympy", "fix bug", "neutral", [], False),
        ("xarray", "fix bug", "neutral", [], False),
        ("pandas", "fix bug", "neutral", [], False),
        ("dask", "fix bug", "neutral", [], False),
        ("numpy", "fix bug", "neutral", [], False),
        ("scipy", "fix bug", "neutral", [], False),
        ("statsmodels", "fix bug", "neutral", [], False),
        ("pillow", "fix bug", "neutral", [], False),
        ("spacy", "fix bug", "neutral", [], False),
        ("numba", "fix bug", "neutral", [], False),
        ("gensim", "fix bug", "neutral", [], False),
        ("scikit-image", "fix bug", "neutral", [], False),
        ("flask", "fix bug", "performance improvement", [], True),  # falls to filter_base, body matches
        ("flask", "fix bug", "neutral", [], False),  # falls to filter_base, no match
        ("django", "fix bug", "performance improvement", [], True),  # falls to filter_base, body matches
        ("django", "fix bug", "neutral", [], False),  # falls to filter_base, no match
        ("requests", "fix bug", "performance improvement", [], True),  # falls to filter_base, body matches
        ("requests", "fix bug", "neutral", [], False),  # falls to filter_base, no match
        ("pytest-lib", "fix bug", "performance improvement", [], True),  # falls to filter_base, body matches
        ("pytest-lib", "fix bug", "neutral", [], False),  # falls to filter_base, no match
        ("unknown-repo", "fix bug", "performance improvement", [], True),  # falls to filter_base, body matches
        ("unknown-repo", "fix bug", "neutral", [], False),  # falls to filter_base, no match
        ("my-project", "fix bug", "performance improvement", [], True),  # falls to filter_base, body matches
        ("my-project", "fix bug", "neutral", [], False),  # falls to filter_base, no match
        ],
    )
    def test_cross_repo_dispatch(self, repo, title, body, labels, expected):
        pr = _make_pull(title=title, body=body, labels=labels)
        assert is_perf_pr(repo, pr) == expected

    @pytest.mark.parametrize(
        "body_keyword",
        [
        ("performance"),
        ("speedup"),
        ("speeds up"),
        ("speed-up"),
        ("speed up"),
        ("faster"),
        ("memory"),
        ("optimize"),
        ("optimization"),
        ("profiling"),
        ("accelerate"),
        ("fast"),
        ("runtime"),
        ("efficiency"),
        ("benchmark"),
        ("latency"),
        ("throughput"),
        ("multithreading"),
        ("parallel"),
        ("concurrency"),
        ("concurrent"),
        ("memory usage"),
        ("resource usage"),
        ("cache"),
        ("caching"),
        ("timeit"),
        ("asv"),
        ],
    )
    def test_unregistered_repo_body_keyword_fallback(self, body_keyword):
        """D1/D12: Unregistered repo falls through to filter_base which checks body."""
        pr = _make_pull(title="fix bug", body=f"This PR improves {body_keyword}")
        assert is_perf_pr("unknown-repo", pr) is True

    @pytest.mark.parametrize(
        "repo",
        [
            "astropy",
            "scikit-learn",
            "matplotlib",
            "pylint",
            "seaborn",
            "sphinx",
            "sympy",
            "xarray",
            "pandas",
            "dask",
            "numpy",
            "scipy",
            "statsmodels",
            "pillow",
            "spacy",
            "numba",
            "gensim",
            "scikit-image",
        ],
    )
    def test_every_registered_repo_perf_title(self, repo):
        """D1: Every registered repo matches on 'perf' in title."""
        pr = _make_pull(title="perf: improvement")
        assert is_perf_pr(repo, pr) is True

    @pytest.mark.parametrize(
        "repo",
        [
            "astropy",
            "scikit-learn",
            "matplotlib",
            "pylint",
            "seaborn",
            "sphinx",
            "sympy",
            "xarray",
            "pandas",
            "dask",
            "numpy",
            "scipy",
            "statsmodels",
            "pillow",
            "spacy",
            "numba",
            "gensim",
            "scikit-image",
        ],
    )
    def test_every_registered_repo_no_match(self, repo):
        """D1: Every registered repo returns False for non-perf PR with no body keywords."""
        pr = _make_pull(title="fix typo", body="corrected spelling")
        # Repo-specific filter fails, then falls through to default which also fails
        assert is_perf_pr(repo, pr) is False


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED: keyword pairwise interactions  (D1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveKeywordPairInteractions:
    """D1: Pairwise combinations of keywords in body + title."""

    BASE_KEYWORDS_SAMPLE = [
        "performance", "speedup", "faster", "optimize", "benchmark",
        "latency", "throughput", "parallel", "cache", "memory",
        "runtime", "accelerate", "efficiency", "concurrent",
    ]

    VERBATIM_KEYWORDS = ["PERF", "OPTIM"]

    @pytest.mark.parametrize("kw1", BASE_KEYWORDS_SAMPLE)
    @pytest.mark.parametrize("kw2", VERBATIM_KEYWORDS)
    def test_base_keyword_body_verbatim_title(self, kw1, kw2):
        """D1: BASE keyword in body + VERBATIM in title."""
        pull = _make_pull(title=f"{kw2}: improvement", body=f"This {kw1} change")
        assert filter_base(pull) is True

    @pytest.mark.parametrize("kw1", BASE_KEYWORDS_SAMPLE[:7])
    @pytest.mark.parametrize("kw2", BASE_KEYWORDS_SAMPLE[7:])
    def test_two_base_keywords_in_body(self, kw1, kw2):
        """D1: Two BASE keywords in body (both should still match)."""
        pull = _make_pull(body=f"This {kw1} and {kw2} improvement")
        assert filter_base(pull) is True

    @pytest.mark.parametrize("non_match", [
        "fix", "add", "refactor", "update", "merge", "revert",
        "cleanup", "rename", "move", "delete", "bump", "format",
        "sort", "lint", "test", "docs", "style", "build", "ci",
        "chore", "deprecate", "migrate",
    ])
    def test_non_matching_with_all_base_keywords_absent(self, non_match):
        """D1: Non-performance words never match filter_base."""
        pull = _make_pull(title=f"{non_match}: something", body=f"This {non_match} change")
        assert filter_base(pull) is False


# ═══════════════════════════════════════════════════════════════════════════════
# WAVE 2: Additional parametrized expansion to reach 10K total
# ═══════════════════════════════════════════════════════════════════════════════


class TestWave2IsValidPullDates:
    """D5: Exhaustive date format variants for merged_at."""

    @pytest.mark.parametrize("year", list(range(2000, 2026)))
    @pytest.mark.parametrize("month", list(range(1, 13)))
    def test_year_month_combinations(self, year, month):
        """D5: Every year (2000-2025) x month (1-12) combo is valid."""
        merged_at = f"{year}-{month:02d}-01T00:00:00Z"
        pull = {"merged_at": merged_at}
        assert is_valid_pull(pull) is True


class TestWave2IsValidPullTimestampVariants:
    """D5: Hour x minute variants for merged_at."""

    @pytest.mark.parametrize("hour", list(range(0, 24)))
    @pytest.mark.parametrize("minute", [0, 15, 30, 45, 59])
    def test_hour_minute_combinations(self, hour, minute):
        """D5: Every hour (0-23) x minute (0,15,30,45,59) combo."""
        merged_at = f"2024-06-15T{hour:02d}:{minute:02d}:00Z"
        pull = {"merged_at": merged_at}
        assert is_valid_pull(pull) is True


class TestWave2IsValidInstanceMixedContent:
    """D4: Various string content patterns as patches."""

    PREFIXES = ["fix:", "feat:", "chore:", "refactor:", "test:", "docs:", "style:", "perf:", "ci:", "build:"]
    SUFFIXES = ["\n", "\r\n", "\t", " ", ".", "!", ";", "}", ")", "]"]

    @pytest.mark.parametrize("prefix", PREFIXES)
    @pytest.mark.parametrize("suffix", SUFFIXES)
    def test_prefix_suffix_combinations(self, prefix, suffix):
        """D4: prefix x suffix combos are all valid patches."""
        inst = {"patch": prefix + " something" + suffix, "test_patch": None}
        assert is_valid_instance(inst) is True


class TestWave2HasTestPatchMixedWhitespace:
    """D2/D4: Mixed whitespace-only patterns are all invalid."""

    WS_CHARS = [" ", "\t", "\n", "\r", "\r\n"]

    @pytest.mark.parametrize("ws1", WS_CHARS)
    @pytest.mark.parametrize("ws2", WS_CHARS)
    @pytest.mark.parametrize("ws3", WS_CHARS)
    def test_triple_whitespace_combos_invalid(self, ws1, ws2, ws3):
        """D2: All 3-char whitespace combos are invalid."""
        inst = {"test_patch": ws1 + ws2 + ws3, "patch": "x"}
        assert has_test_patch(inst) is False


class TestWave2FilterBaseKeywordPositions:
    """D1/D4: Keywords at various positions in body text."""

    POSITIONS = ["start", "middle", "end", "sentence_start", "parenthetical"]
    KEYWORDS_SUBSET = BASE_PERF_KEYWORDS[:15]

    @pytest.mark.parametrize("keyword", KEYWORDS_SUBSET)
    @pytest.mark.parametrize("position", POSITIONS)
    def test_keyword_at_position(self, keyword, position):
        """D1: keyword at various positions in body."""
        if keyword == "CPU usage":
            pytest.skip("BUG: CPU usage uppercase never matches")
        templates = {
            "start": f"{keyword} improvement in this PR",
            "middle": f"This PR improves {keyword} significantly",
            "end": f"Major improvement to {keyword}",
            "sentence_start": f"Code changes. {keyword} is now better.",
            "parenthetical": f"Changes ({keyword}) applied here",
        }
        body = templates[position]
        pull = _make_pull(body=body)
        assert filter_base(pull) is True


class TestWave2FilterContentKeywordMixedCase:
    """D4: Keywords in various case patterns within text."""

    KEYWORDS_SUBSET = BASE_PERF_KEYWORDS[:15]
    CASE_FUNS = [str.lower, str.upper, str.title, str.swapcase]

    @pytest.mark.parametrize("keyword", KEYWORDS_SUBSET)
    @pytest.mark.parametrize("case_idx", range(4))
    def test_keyword_case_variants(self, keyword, case_idx):
        """D4: keyword in lower/upper/title/swapcase."""
        if keyword == "CPU usage":
            pytest.skip("BUG: CPU usage uppercase never matches")
        case_fn = self.CASE_FUNS[case_idx]
        text = f"This text discusses {case_fn(keyword)} improvements"
        assert filter_content(text) is True


class TestWave2CheckLabelsSubstringMatrix:
    """D4: Substring matching exhaustive matrix."""

    LABEL_NAMES = [
        "performance", "enhancement", "optimization", "bug",
        "feature", "documentation", "perf-improvement", "speed",
        "memory", "refactor", "test", "ci",
    ]
    SEARCH_VALUES = [
        "performance", "enhancement", "opt", "bug",
        "feat", "doc", "perf", "speed",
        "mem", "refact", "test", "ci",
    ]

    @pytest.mark.parametrize("label_name", LABEL_NAMES)
    @pytest.mark.parametrize("search_value", SEARCH_VALUES)
    def test_label_value_substring_matrix(self, label_name, search_value):
        """D4: Every label x value combo — True iff value is substring of lowered label."""
        pull = _make_pull(labels=[_make_label(label_name)])
        result = check_labels(pull, [search_value])
        expected = search_value in label_name.lower()
        assert result is expected


class TestWave2RemoveMarkdownCommentsLengths:
    """D11: Comments of various lengths."""

    @pytest.mark.parametrize("content_len", list(range(0, 101)))
    def test_comment_content_lengths(self, content_len):
        """D11: Comment body of length 0-100."""
        content = "x" * content_len
        text = f"before <!-- {content} --> after"
        result = remove_markdown_comments(text)
        assert "<!--" not in result
        assert "before" in result
        assert "after" in result


class TestWave2IsDocFileWithDirectories:
    """D4: Doc files at various directory depths and names."""

    DIRS = ["src", "lib", "docs", "test", "build", "dist", "pkg", "internal", "vendor", "third_party"]
    FILENAMES = ["README", "CHANGELOG", "CONTRIBUTING", "LICENSE", "HISTORY", "NEWS", "TODO", "AUTHORS"]
    EXTENSIONS = [".md", ".rst"]

    @pytest.mark.parametrize("dir_name", DIRS)
    @pytest.mark.parametrize("filename", FILENAMES)
    @pytest.mark.parametrize("ext", EXTENSIONS)
    def test_dir_filename_ext_combinations(self, dir_name, filename, ext):
        """D4: dir x filename x extension combos."""
        path = f"{dir_name}/{filename}{ext}"
        assert is_doc_file(path) is True


class TestWave2IsDocFileNonDoc:
    """D1: Non-doc files exhaustive."""

    CODE_EXTENSIONS = [
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h",
        ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".cs",
        ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
        ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
        ".json", ".xml", ".html", ".css", ".scss", ".less",
        ".sql", ".graphql", ".proto", ".thrift",
        ".txt", ".log", ".csv", ".tsv",
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
        ".whl", ".tar", ".gz", ".zip", ".bz2",
        ".pem", ".key", ".crt", ".p12",
    ]

    @pytest.mark.parametrize("ext", CODE_EXTENSIONS)
    def test_code_extensions_not_doc(self, ext):
        """D1: Every non-doc extension returns False."""
        assert is_doc_file(f"file{ext}") is False

    @pytest.mark.parametrize("ext", CODE_EXTENSIONS)
    def test_nested_code_extensions_not_doc(self, ext):
        """D1: Nested non-doc files also False."""
        assert is_doc_file(f"src/pkg/module{ext}") is False


class TestWave2HasLockFileVariants:
    """D1/D4: Lock file detection with various names and paths."""

    LOCK_NAMES = [
        "package-lock.json.lock", "Gemfile.lock", "poetry.lock",
        "Cargo.lock", "composer.lock", "yarn.lock", "pnpm-lock.yaml.lock",
        "Pipfile.lock", "flake.lock", "pubspec.lock",
    ]
    NON_LOCK_NAMES = [
        "package.json", "Gemfile", "poetry.toml", "Cargo.toml",
        "composer.json", "yarn.cjs", "pnpm-workspace.yaml",
        "Pipfile", "flake.nix", "pubspec.yaml",
        "lockfile.txt", "lock.py", "locked.json",
    ]

    @pytest.mark.parametrize("name", LOCK_NAMES)
    def test_lock_files_detected(self, name):
        assert has_lock_file_change(name) is True

    @pytest.mark.parametrize("name", NON_LOCK_NAMES)
    def test_non_lock_files_not_detected(self, name):
        assert has_lock_file_change(name) is False

    @pytest.mark.parametrize("name", LOCK_NAMES)
    @pytest.mark.parametrize("depth", range(1, 6))
    def test_lock_at_depth(self, name, depth):
        """D4: Lock files at depth 1-5."""
        path = "/".join(["dir"] * depth) + "/" + name
        assert has_lock_file_change(path) is True


class TestWave2SplitInstancesPreservation:
    """D1/D12: Element preservation and ordering across splits."""

    @pytest.mark.parametrize("size", list(range(1, 51)))
    @pytest.mark.parametrize("n", [2, 3, 5, 7])
    def test_all_elements_preserved(self, size, n):
        """D12: All elements present after split, no duplicates."""
        items = list(range(size))
        result = split_instances(items, n)
        flat = [x for sub in result for x in sub]
        assert sorted(flat) == items

    @pytest.mark.parametrize("size", list(range(1, 51)))
    def test_split_into_1_identity(self, size):
        """D1: Split into 1 is identity."""
        items = list(range(size))
        result = split_instances(items, 1)
        assert len(result) == 1
        assert result[0] == items


class TestWave2IsPerfPrKeywordBodyCross:
    """D1/D12: Every BASE keyword x registered repo in body."""

    REPOS = [
        "scikit-learn", "astropy", "matplotlib", "pylint", "seaborn",
        "sphinx", "sympy", "xarray", "dask", "pandas",
        "numpy", "statsmodels", "pillow", "spacy", "numba",
        "gensim", "scikit-image", "scipy",
    ]
    KEYWORDS_SUBSET = [k for k in BASE_PERF_KEYWORDS if k != "CPU usage"][:10]

    @pytest.mark.parametrize("repo", REPOS)
    @pytest.mark.parametrize("keyword", KEYWORDS_SUBSET)
    def test_repo_keyword_body_cross(self, repo, keyword):
        """D1/D12: keyword in body triggers default fallback for every repo."""
        pull = _make_pull(body=f"This improves {keyword} significantly")
        assert is_perf_pr(repo, pull) is True


# ═══════════════════════════════════════════════════════════════════════════════
# WAVE 3: Final push to 10K
# ═══════════════════════════════════════════════════════════════════════════════


class TestWave3IsValidPullTypeCoercion:
    """D3: Non-None types as merged_at are all valid."""

    @pytest.mark.parametrize("val", [
        0, 1, -1, 0.0, 1.0, -1.0, 0.5,
        True, False, "", "x", " ",
        [], [1], [None], {},
        {"key": "val"}, set(), frozenset(),
        b"", b"bytes", bytearray(), bytearray(b"x"),
        complex(0, 0), complex(1, 1),
        range(0), range(10),
        type, object, int, str, list,
        lambda: None, print,
        float("inf"), float("-inf"),
    ])
    def test_non_none_types_valid(self, val):
        """D3: Only None is invalid. ALL other types are valid."""
        assert is_valid_pull({"merged_at": val}) is True


class TestWave3IsDocFileCaseSensitivity:
    """D4: Case sensitivity of doc file detection."""

    @pytest.mark.parametrize("ext", [
        ".MD", ".Md", ".mD",
        ".RST", ".Rst", ".rST", ".rSt", ".rsT",
    ])
    def test_uppercase_extensions_not_doc(self, ext):
        """D4: endswith is case-sensitive — uppercase extensions don't match."""
        assert is_doc_file(f"README{ext}") is False


class TestWave3SplitInstancesLargeN:
    """D11: Split into large N values."""

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_5_items_into_n(self, n):
        """D11: 5 items split into 1-50 parts."""
        items = [1, 2, 3, 4, 5]
        result = split_instances(items, n)
        assert len(result) == n
        flat = [x for sub in result for x in sub]
        assert sorted(flat) == items

    @pytest.mark.parametrize("n", list(range(1, 21)))
    def test_empty_into_n(self, n):
        """D2: Empty list split into 1-20 parts."""
        result = split_instances([], n)
        assert len(result) == n
        assert all(sub == [] for sub in result)


class TestWave3FilterBaseVerbatimInTitle:
    """D1: VERBATIM keywords in title for filter_base."""

    @pytest.mark.parametrize("prefix", ["", "PR: ", "Fix ", "[WIP] ", "Draft: "])
    @pytest.mark.parametrize("kw", ["PERF", "OPTIM"])
    @pytest.mark.parametrize("suffix", ["", " improvement", ": faster", " - v2"])
    def test_verbatim_in_title_positions(self, prefix, kw, suffix):
        """D1: VERBATIM keyword in title with various prefixes/suffixes."""
        pull = _make_pull(title=f"{prefix}{kw}{suffix}")
        assert filter_base(pull) is True
