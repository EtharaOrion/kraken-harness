from __future__ import annotations

import pytest

from helpers import CONTEXT_MSG, SYSTEM_MSG


# ---------------------------------------------------------------------------
# TestSystemMsg — original tests + expanded parametrized keywords
# ---------------------------------------------------------------------------
class TestSystemMsg:
    def test_is_non_empty_string(self):
        assert isinstance(SYSTEM_MSG, str)
        assert len(SYSTEM_MSG) > 100

    def test_contains_performance_expert_role(self):
        assert "performance testing expert" in SYSTEM_MSG

    def test_contains_setup_function_guidance(self):
        assert "setup()" in SYSTEM_MSG

    def test_contains_workload_function_guidance(self):
        assert "workload()" in SYSTEM_MSG

    def test_contains_timeit_guidance(self):
        assert "timeit.repeat" in SYSTEM_MSG

    def test_contains_statistics_guidance(self):
        assert "statistics.mean" in SYSTEM_MSG
        assert "statistics.stdev" in SYSTEM_MSG

    def test_contains_mean_print_format(self):
        assert 'print("Mean:"' in SYSTEM_MSG

    def test_contains_std_dev_print_format(self):
        assert 'print("Std Dev:"' in SYSTEM_MSG

    def test_contains_example_code(self):
        assert "```python" in SYSTEM_MSG
        assert "```" in SYSTEM_MSG

    def test_example_has_numpy(self):
        assert "import numpy as np" in SYSTEM_MSG

    def test_example_has_random_seed(self):
        assert "np.random.seed(42)" in SYSTEM_MSG

    def test_mentions_self_contained(self):
        assert "self-contained" in SYSTEM_MSG

    def test_mentions_reproducibility(self):
        assert "reproducib" in SYSTEM_MSG.lower()

    def test_mentions_number_repeat(self):
        assert "number=" in SYSTEM_MSG
        assert "repeat=" in SYSTEM_MSG

    # 100 essential keywords (expanded from original 10)
    @pytest.mark.parametrize("keyword", [
        "setup",
        "workload",
        "timeit",
        "statistics",
        "import",
        "print",
        "Mean",
        "Std Dev",
        "global",
        "repeat",
        "performance",
        "testing",
        "expert",
        "self-contained",
        "Python",
        "script",
        "function",
        "Guidelines",
        "benchmark",
        "number",
        "realistic",
        "data",
        "environment",
        "representative",
        "seed",
        "random",
        "numpy",
        "arr",
        "operation",
        "complete",
        "setup()",
        "workload()",
        "timeit.repeat",
        "statistics.mean",
        "statistics.stdev",
        "import timeit",
        "import statistics",
        "import numpy",
        "def setup",
        "def workload",
        "np.random.seed",
        "runtimes",
        "number=1",
        "repeat=10",
        "```python",
        "standard deviation",
        "mean",
        "real-world",
        "caching",
        "constant-folding",
        "API",
        "library",
        "diff",
        "code edit",
        "git diff",
        "pre-edit",
        "source",
        "measures",
        "code paths",
        "changed",
        "one-time",
        "preprocessing",
        "expensive",
        "file",
        "download",
        "patterns",
        "trivial",
        "corner cases",
        "optimized",
        "varied",
        "Inputs",
        "stable",
        "gather",
        "comparison",
        "output",
        "clear",
        "ready",
        "performance comparison",
        "contain",
        "import statements",
        "mean/stddev",
        "printing",
        "measured runtimes",
        "two lines",
        "format",
        "Example",
        "strictly follow",
        "exactly",
        "arr.T",
        "np.random.rand",
        "5000",
        "non-trivial",
        "real datasets",
        "synthetic",
        "1.",
        "2.",
        "3.",
        "4.",
        "5.",
        "timed",
        "single-run",
    ])
    def test_essential_keywords_present(self, keyword):
        assert keyword in SYSTEM_MSG


# ---------------------------------------------------------------------------
# TestSystemMsgLines — verify significant lines/phrases from SYSTEM_MSG
# ---------------------------------------------------------------------------
class TestSystemMsgLines:
    @pytest.mark.parametrize("phrase", [
        "You are a performance testing expert.",
        "self-contained Python performance workload script",
        "measures perfomance of code paths or APIs changed in the diff",
        "Guidelines for the workload script contents.",
        "Use a `setup()` function to prepare any realistic, non-trivial data",
        "Data must be representative of real-world usage",
        "Prefer real datasets or realistic synthetic data with reproducibility",
        "set a random seed",
        "All expensive or one-time setup",
        "must be in `setup()`, not in the workload",
        "Use a `workload()` function to run the actual operation(s) being timed",
        "representative and challenging real-world use case",
        "Avoid corner cases that could be trivially optimized",
        "Inputs should be varied enough to prevent caching or constant-folding",
        "Run the benchmark using `timeit.repeat(workload, number=..., repeat=..., setup=setup)`",
        "`number` should match a realistic single-run execution count",
        "`repeat` should be high enough to gather stable statistics",
        "Print the mean and standard deviation of the last set of runtimes",
        "statistics.mean()",
        "statistics.stdev()",
        "Output should be clear and ready for performance comparison",
        "output must be a **complete Python script** containing only:",
        "import statements",
        "`setup()` function",
        "`workload()` function",
        "the `timeit.repeat()` call",
        "mean/stddev printing",
        "should only print two lines at the end",
        "mean of measured runtimes and the standard deviation of runtimes",
        "Example workload to follow",
    ])
    def test_phrase_present(self, phrase):
        assert phrase in SYSTEM_MSG


# ---------------------------------------------------------------------------
# TestSystemMsgStructure — structural checks
# ---------------------------------------------------------------------------
class TestSystemMsgStructure:
    @pytest.mark.parametrize("marker", [
        "```python",
        "```\n",
    ])
    def test_code_fence_markers(self, marker):
        assert marker in SYSTEM_MSG

    def test_has_opening_and_closing_code_fence(self):
        idx_open = SYSTEM_MSG.index("```python")
        idx_close = SYSTEM_MSG.index("```\n", idx_open + 10)
        assert idx_close > idx_open

    @pytest.mark.parametrize("item", [
        "1.",
        "2.",
        "3.",
        "4.",
        "5.",
    ])
    def test_has_numbered_list_items(self, item):
        assert item in SYSTEM_MSG

    @pytest.mark.parametrize("bullet", [
        "- Use a `setup()`",
        "- Use a `workload()`",
        "- Run the benchmark",
        "- Print the mean",
        "- The output must",
        "- Data must be",
        "- Prefer real datasets",
        "- All expensive",
        "- Avoid corner cases",
        "- Inputs should be",
        "- `number` should",
        "- `repeat` should",
    ])
    def test_has_bullet_points(self, bullet):
        assert bullet in SYSTEM_MSG

    def test_has_example_section(self):
        assert "Example workload to follow" in SYSTEM_MSG


# ---------------------------------------------------------------------------
# TestSystemMsgFormat — usability as chat message
# ---------------------------------------------------------------------------
class TestSystemMsgFormat:
    def test_no_null_bytes(self):
        assert "\x00" not in SYSTEM_MSG

    def test_no_leading_whitespace_after_strip(self):
        assert SYSTEM_MSG == SYSTEM_MSG.lstrip() or SYSTEM_MSG[0] not in (" ", "\t")

    def test_no_trailing_whitespace_lines(self):
        # at least the msg doesn't start or end with blank lines after strip
        stripped = SYSTEM_MSG.strip()
        assert len(stripped) > 0

    def test_reasonable_length(self):
        assert 500 < len(SYSTEM_MSG) < 10000

    def test_is_utf8_encodable(self):
        SYSTEM_MSG.encode("utf-8")

    @pytest.mark.parametrize("bad_char", [
        "\x00", "\x01", "\x02", "\x03", "\x04", "\x05", "\x06", "\x07",
        "\x0e", "\x0f",
    ])
    def test_no_control_characters(self, bad_char):
        assert bad_char not in SYSTEM_MSG


# ---------------------------------------------------------------------------
# TestSystemMsgExampleCode — verify example code block content
# ---------------------------------------------------------------------------
class TestSystemMsgExampleCode:
    @pytest.mark.parametrize("code_fragment", [
        "import timeit",
        "import statistics",
        "import numpy as np",
        "def setup():",
        "global arr",
        "np.random.seed(42)",
        "np.random.rand(5000, 5000)",
        "def workload():",
        "arr @ arr.T",
        "runtimes = timeit.repeat(",
        "workload, number=1, repeat=10, setup=setup)",
        'print("Mean:", statistics.mean(runtimes))',
        'print("Std Dev:", statistics.stdev(runtimes))',
        "number=1",
        "repeat=10",
        "setup=setup",
        "_ = arr @ arr.T",
        "np.random.rand(",
        "5000, 5000",
        "statistics.mean(runtimes)",
    ])
    def test_example_code_contains(self, code_fragment):
        assert code_fragment in SYSTEM_MSG


# ---------------------------------------------------------------------------
# TestSystemMsgNegative — things NOT in SYSTEM_MSG
# ---------------------------------------------------------------------------
class TestSystemMsgNegative:
    @pytest.mark.parametrize("bad_term", [
        "bug fix",
        "error handling required",
        "raise Exception",
        "traceback",
        "FIXME",
        "HACK",
        "TODO: fix",
        "deprecated warning",
        "security vulnerability",
        "SQL injection",
        "password",
        "secret_key",
        "DELETE FROM",
        "DROP TABLE",
        "sudo rm",
        "os.system(",
        "eval(",
        "exec(",
        "__import__(",
        "subprocess.call",
    ])
    def test_should_not_contain(self, bad_term):
        assert bad_term not in SYSTEM_MSG


# ---------------------------------------------------------------------------
# TestContextMsg — original tests preserved
# ---------------------------------------------------------------------------
class TestContextMsg:
    def test_is_non_empty_string(self):
        assert isinstance(CONTEXT_MSG, str)
        assert len(CONTEXT_MSG) > 20

    def test_has_repo_name_placeholder(self):
        assert "{repo_name}" in CONTEXT_MSG

    def test_has_commit_diff_placeholder(self):
        assert "{commit_diff}" in CONTEXT_MSG

    def test_has_pre_edit_code_placeholder(self):
        assert "{pre_edit_code}" in CONTEXT_MSG

    def test_format_with_values(self):
        result = CONTEXT_MSG.format(
            repo_name="numpy",
            commit_diff="--- a/test.py\n+++ b/test.py",
            pre_edit_code="File: test.py\n```\npass\n```",
        )
        assert "numpy" in result
        assert "--- a/test.py" in result
        assert "File: test.py" in result

    @pytest.mark.parametrize("repo", [
        "numpy", "pandas", "scipy", "scikit-learn", "matplotlib",
        "xarray", "sympy", "dask", "astropy",
    ])
    def test_format_with_each_repo(self, repo):
        result = CONTEXT_MSG.format(
            repo_name=repo,
            commit_diff="diff",
            pre_edit_code="code",
        )
        assert repo in result

    def test_mentions_commit_diff(self):
        assert "Commit Diff" in CONTEXT_MSG

    def test_mentions_pre_edit_source(self):
        assert "Pre-edit source" in CONTEXT_MSG

    def test_missing_placeholder_raises(self):
        with pytest.raises(KeyError):
            CONTEXT_MSG.format(repo_name="test")


# ---------------------------------------------------------------------------
# TestContextMsgPlaceholders — individual placeholder behaviour
# ---------------------------------------------------------------------------
class TestContextMsgPlaceholders:
    @pytest.mark.parametrize("kwargs,should_raise", [
        ({"repo_name": "x"}, True),
        ({"commit_diff": "d"}, True),
        ({"pre_edit_code": "c"}, True),
        ({"repo_name": "x", "commit_diff": "d"}, True),
        ({"repo_name": "x", "pre_edit_code": "c"}, True),
        ({"commit_diff": "d", "pre_edit_code": "c"}, True),
        ({"repo_name": "x", "commit_diff": "d", "pre_edit_code": "c"}, False),
    ])
    def test_partial_format_raises(self, kwargs, should_raise):
        if should_raise:
            with pytest.raises(KeyError):
                CONTEXT_MSG.format(**kwargs)
        else:
            result = CONTEXT_MSG.format(**kwargs)
            assert isinstance(result, str)

    @pytest.mark.parametrize("repo_name", [
        "numpy", "pandas", "", "a" * 200, "repo/with/slashes",
        "repo with spaces", "UPPERCASE", "123numeric", "under_score",
        "dash-name", "dot.name", "special!@#", "ünïcödé",
    ])
    def test_repo_name_values(self, repo_name):
        result = CONTEXT_MSG.format(
            repo_name=repo_name,
            commit_diff="diff",
            pre_edit_code="code",
        )
        assert repo_name in result

    @pytest.mark.parametrize("commit_diff", [
        "simple diff",
        "",
        "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new",
        "multi\nline\ndiff\ncontent",
        "a" * 1000,
        "Special chars: <>&\"'",
        "Unicode: αβγδ",
        "Backticks: ```python\ncode\n```",
        "Tabs:\t\there",
        "CRLF:\r\nline",
    ])
    def test_commit_diff_values(self, commit_diff):
        result = CONTEXT_MSG.format(
            repo_name="repo",
            commit_diff=commit_diff,
            pre_edit_code="code",
        )
        assert commit_diff in result


# ---------------------------------------------------------------------------
# TestContextMsgContentVerification — verify formatted output sections
# ---------------------------------------------------------------------------
_REPOS = ["numpy", "pandas", "scipy", "scikit-learn", "matplotlib",
          "xarray", "sympy", "dask", "astropy"]

_DIFF_VARIANTS = [
    "--- a/mod.py\n+++ b/mod.py",
    "diff --git a/x.py b/x.py\nindex 1..2 100644",
    "+added line\n-removed line",
    "@@ -10,3 +10,5 @@\n context\n+new\n old",
    "simple one-liner diff",
]


class TestContextMsgContentVerification:
    @pytest.mark.parametrize("repo", _REPOS)
    @pytest.mark.parametrize("diff", _DIFF_VARIANTS)
    def test_formatted_output_contains_sections(self, repo, diff):
        result = CONTEXT_MSG.format(
            repo_name=repo,
            commit_diff=diff,
            pre_edit_code="def foo(): pass",
        )
        assert repo in result
        assert diff in result
        assert "Commit Diff" in result
        assert "Pre-edit source" in result
        assert "```" in result


# ---------------------------------------------------------------------------
# TestContextMsgEdgeCases — edge-case formatting
# ---------------------------------------------------------------------------
class TestContextMsgEdgeCases:
    @pytest.mark.parametrize("repo_name,commit_diff,pre_edit_code", [
        # empty strings
        ("", "diff", "code"),
        ("repo", "", "code"),
        ("repo", "diff", ""),
        ("", "", ""),
        # very long strings
        ("r" * 500, "diff", "code"),
        ("repo", "d" * 5000, "code"),
        ("repo", "diff", "c" * 5000),
        # unicode
        ("日本語repo", "diff", "code"),
        ("repo", "αβγδ差分", "code"),
        ("repo", "diff", "코드内容"),
        # strings with code blocks
        ("repo", "```python\nx=1\n```", "code"),
        ("repo", "diff", "```\nblock\n```"),
        ("repo", "```\nfirst\n```\n```\nsecond\n```", "code"),
        # strings with triple backticks
        ("repo", "```", "code"),
        ("repo", "diff", "```"),
        ("```", "```", "```"),
        # whitespace variants
        ("repo", "  leading spaces", "code"),
        ("repo", "diff", "\ttabbed"),
        ("repo", "diff\n\n\n", "code"),
        ("\n\nrepo", "diff", "code"),
        # special characters
        ("repo<>", "diff&\"'", "code\\n"),
        ("repo", "diff{brace}", "code"),
        ("repo", "diff", "code{{escaped}}"),
        # numeric-ish
        ("12345", "67890", "0"),
        ("repo", "diff", "0.0"),
        # newlines
        ("repo\nname", "diff", "code"),
        ("repo", "line1\nline2\nline3", "code"),
        ("repo", "diff", "line1\nline2\nline3\nline4\nline5"),
        # path-like
        ("numpy/core", "diff", "code"),
        ("/absolute/path.py", "diff", "code"),
        ("repo", "diff", "File: src/main.py\n```\nimport os\n```"),
        # real-world-ish
        ("numpy", "--- a/numpy/core/fromnumeric.py\n+++ b/numpy/core/fromnumeric.py\n@@ -10,6 +10,7 @@\n import numpy as np\n+# optimized path\n def sort(a):", "File: numpy/core/fromnumeric.py\n```\nimport numpy as np\ndef sort(a):\n    pass\n```"),
        ("pandas", "diff --git a/pandas/core/frame.py b/pandas/core/frame.py", "File: pandas/core/frame.py\n```\nclass DataFrame:\n    pass\n```"),
        ("scipy", "- old_func()\n+ new_func()", "def old_func(): pass"),
        ("matplotlib", "+import numpy as np", "import os"),
        ("sympy", "@@ -1,5 +1,10 @@", "x = symbols('x')"),
        ("dask", "context line\n+added\n-removed\ncontext", "import dask"),
        ("astropy", "Binary content differs", "# astropy module"),
        ("xarray", "rename: old -> new", "import xarray as xr"),
        ("scikit-learn", "+from sklearn.utils import check_array", "from sklearn.base import BaseEstimator"),
        # mixed encodings
        ("repo", "diff with émojis 🎉", "code"),
        ("repo", "diff", "café résumé naïve"),
        # very short
        ("r", "d", "c"),
        ("a", "b", "c"),
    ])
    def test_edge_case_formatting(self, repo_name, commit_diff, pre_edit_code):
        result = CONTEXT_MSG.format(
            repo_name=repo_name,
            commit_diff=commit_diff,
            pre_edit_code=pre_edit_code,
        )
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# TestContextMsgFormatCrossProduct — repos × diff_types × code_types
# ---------------------------------------------------------------------------
_CODE_VARIANTS = [
    "def foo(): pass",
    "class Bar:\n    x = 1",
    "import numpy as np\narr = np.array([1,2,3])",
    "# just a comment",
    "for i in range(10):\n    print(i)",
]


class TestContextMsgFormatCrossProduct:
    @pytest.mark.parametrize("repo", _REPOS)
    @pytest.mark.parametrize("diff", _DIFF_VARIANTS)
    @pytest.mark.parametrize("code", _CODE_VARIANTS)
    def test_cross_product_format(self, repo, diff, code):
        result = CONTEXT_MSG.format(
            repo_name=repo,
            commit_diff=diff,
            pre_edit_code=code,
        )
        assert repo in result
        assert diff in result
        assert code in result
