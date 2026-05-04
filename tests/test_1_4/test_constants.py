"""
Tests for swefficiency/perf_filter/attributes/constants.py

Coverage targets:
    - VERBATIM_KEYWORDS, BASE_PERF_KEYWORDS (constants validation)
    - check_labels(pull, value)
    - remove_markdown_comments(input_str)
    - filter_base(pull, keywords)
    - filter_content(issue_text, keywords)
    - 17 per-repo filter functions (filter_sklearn through filter_scikit_image)
    - REPO_PERF_FILTERS dict

Dimensions covered: D1 Input Domain, D2 Null/Empty/Missing, D3 Type Coercion,
D4 String Brutality, D8 Error Handling, D9 Security, D11 Performance,
D12 Integration.
"""

import pytest

from swefficiency.perf_filter.attributes.constants import (
    VERBATIM_KEYWORDS,
    BASE_PERF_KEYWORDS,
    check_labels,
    remove_markdown_comments,
    filter_base,
    filter_content,
    filter_sklearn,
    filter_astropy,
    filter_matplotlib,
    filter_pylint,
    filter_seaborn,
    filter_sphinx,
    filter_sympy,
    filter_xarray,
    filter_pandas,
    filter_dask,
    filter_numpy,
    filter_statsmodels,
    filter_pillow,
    filter_spacy,
    filter_numba,
    filter_gensim,
    filter_scikit_image,
    REPO_PERF_FILTERS,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_pull(title="Neutral title", body="Neutral body", labels=None):
    return {
        "title": title,
        "body": body,
        "labels": labels or [],
        "merged_at": "2023-06-15T10:30:00Z",
        "number": 1,
    }


def _make_label(name):
    return {"name": name}


# ═══════════════════════════════════════════════════════════════════════════════
# Keyword Constants
# ═══════════════════════════════════════════════════════════════════════════════


class TestKeywordConstants:
    """Validate structure and content of keyword lists."""

    def test_verbatim_keywords_type_and_contents(self):
        """D1: VERBATIM_KEYWORDS is a list of uppercase strings."""
        assert isinstance(VERBATIM_KEYWORDS, list)
        assert len(VERBATIM_KEYWORDS) == 2
        assert "PERF" in VERBATIM_KEYWORDS
        assert "OPTIM" in VERBATIM_KEYWORDS

    def test_verbatim_keywords_are_uppercase(self):
        """D1: All VERBATIM_KEYWORDS are uppercase (case-sensitive matching)."""
        for kw in VERBATIM_KEYWORDS:
            assert kw == kw.upper()

    def test_base_perf_keywords_type(self):
        """D1: BASE_PERF_KEYWORDS is a non-empty list of strings."""
        assert isinstance(BASE_PERF_KEYWORDS, list)
        assert len(BASE_PERF_KEYWORDS) > 0
        assert all(isinstance(kw, str) for kw in BASE_PERF_KEYWORDS)

    def test_base_perf_keywords_are_lowercase(self):
        """D1: Most BASE_PERF_KEYWORDS are lowercase.
        BUG: 'CPU usage' has uppercase 'CPU' — inconsistent with the rest."""
        non_lowercase = [kw for kw in BASE_PERF_KEYWORDS if kw != kw.lower()]
        assert non_lowercase == ["CPU usage"]

    def test_base_perf_keywords_has_known_entries(self):
        """D1: Known entries are present."""
        expected = [
            "performance",
            "speedup",
            "faster",
            "optimize",
            "memory",
            "benchmark",
            "latency",
            "throughput",
            "cache",
            "timeit",
            "asv",
        ]
        for kw in expected:
            assert kw in BASE_PERF_KEYWORDS, f"{kw!r} missing"

    def test_base_perf_keywords_has_duplicate_profiling(self):
        """D1: BUG documented — 'profiling' appears twice in the list."""
        count = BASE_PERF_KEYWORDS.count("profiling")
        assert count == 2

    def test_no_whitespace_only_keywords(self):
        """D2: No keyword is empty or whitespace-only."""
        for kw in BASE_PERF_KEYWORDS + VERBATIM_KEYWORDS:
            assert kw.strip() != ""


# ═══════════════════════════════════════════════════════════════════════════════
# check_labels
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckLabels:
    """Tests for check_labels(pull, value).

    Production code: lowercases label names, checks if any v in value
    is a substring of any label.
    """

    def test_exact_match(self):
        """D1: Exact label match returns True."""
        pull = _make_pull(labels=[_make_label("performance")])
        assert check_labels(pull, ["performance"]) is True

    def test_substring_match(self):
        """D1: Substring match — 'perf' is in 'performance'."""
        pull = _make_pull(labels=[_make_label("performance")])
        assert check_labels(pull, ["perf"]) is True

    def test_no_match(self):
        """D1: No matching label returns False."""
        pull = _make_pull(labels=[_make_label("bugfix")])
        assert check_labels(pull, ["performance"]) is False

    def test_case_insensitive_label(self):
        """D4: Label names are lowercased before comparison."""
        pull = _make_pull(labels=[_make_label("Performance")])
        assert check_labels(pull, ["performance"]) is True

    def test_case_insensitive_label_uppercase(self):
        """D4: All-uppercase label matched against lowercase value."""
        pull = _make_pull(labels=[_make_label("PERFORMANCE")])
        assert check_labels(pull, ["performance"]) is True

    def test_multiple_labels(self):
        """D1: Multiple labels — match if any label matches any value."""
        pull = _make_pull(labels=[_make_label("bugfix"), _make_label("performance")])
        assert check_labels(pull, ["perf"]) is True

    def test_multiple_values(self):
        """D1: Multiple values — match if any value matches any label."""
        pull = _make_pull(labels=[_make_label("enhancement")])
        assert check_labels(pull, ["perf", "enhancement"]) is True

    def test_empty_labels(self):
        """D2: No labels — returns False."""
        pull = _make_pull(labels=[])
        assert check_labels(pull, ["performance"]) is False

    def test_empty_values(self):
        """D2: No values to check — returns False."""
        pull = _make_pull(labels=[_make_label("performance")])
        assert check_labels(pull, []) is False

    def test_value_not_lowercased(self):
        """D4: Values are NOT lowercased by production code — uppercase value
        won't match lowercase label."""
        pull = _make_pull(labels=[_make_label("performance")])
        assert check_labels(pull, ["PERFORMANCE"]) is False

    def test_special_prefix_label(self):
        """D1: Labels like 'type:performance' matched by substring."""
        pull = _make_pull(labels=[_make_label("type:performance")])
        assert check_labels(pull, ["performance"]) is True

    def test_topic_prefix_label(self):
        """D1: Labels like 'topic-performance' matched by substring."""
        pull = _make_pull(labels=[_make_label("topic-performance")])
        assert check_labels(pull, ["topic-performance"]) is True


# ═══════════════════════════════════════════════════════════════════════════════
# remove_markdown_comments
# ═══════════════════════════════════════════════════════════════════════════════


class TestRemoveMarkdownComments:
    """Tests for remove_markdown_comments(input_str).

    Production code: re.sub(r"<!--.*?-->", "", input_str, flags=re.DOTALL)
    """

    def test_single_comment(self):
        """D1: Single comment removed."""
        assert (
            remove_markdown_comments("hello <!-- comment --> world") == "hello  world"
        )

    def test_multiple_comments(self):
        """D1: Multiple comments all removed."""
        text = "a <!-- c1 --> b <!-- c2 --> c"
        assert remove_markdown_comments(text) == "a  b  c"

    def test_multiline_comment(self):
        """D1: Comment spanning multiple lines removed (DOTALL flag)."""
        text = "before <!-- multi\nline\ncomment --> after"
        assert remove_markdown_comments(text) == "before  after"

    def test_no_comments(self):
        """D1: Text without comments returned unchanged."""
        text = "no comments here"
        assert remove_markdown_comments(text) == text

    def test_empty_comment(self):
        """D2: Empty comment <!-- --> removed."""
        assert remove_markdown_comments("a <!-- --> b") == "a  b"

    def test_empty_string(self):
        """D2: Empty string returns empty."""
        assert remove_markdown_comments("") == ""

    def test_nested_looking_comments(self):
        """D4: Regex is non-greedy — stops at first -->."""
        text = "a <!-- outer <!-- inner --> b --> c"
        result = remove_markdown_comments(text)
        assert result == "a  b --> c"

    def test_comment_with_perf_keyword(self):
        """D12: Keyword inside comment should be stripped before keyword check."""
        text = "Normal text <!-- performance optimization --> end"
        result = remove_markdown_comments(text)
        assert "performance" not in result
        assert "Normal text" in result


# ═══════════════════════════════════════════════════════════════════════════════
# filter_base
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilterBase:
    """Tests for filter_base(pull, keywords=BASE_PERF_KEYWORDS).

    BUG: Line 78 uses hardcoded BASE_PERF_KEYWORDS instead of the keywords param.
    So custom keywords param is partially ignored — only VERBATIM_KEYWORDS and
    BASE_PERF_KEYWORDS are ever used.
    """

    def test_perf_keyword_in_body(self):
        """D1: BASE_PERF_KEYWORDS match in body returns True."""
        pull = _make_pull(body="This fixes a performance issue")
        assert filter_base(pull) is True

    def test_perf_keyword_in_title(self):
        """D1: BASE_PERF_KEYWORDS match in title returns True."""
        pull = _make_pull(title="Optimize database query")
        assert filter_base(pull) is True

    def test_verbatim_keyword_in_body(self):
        """D1: VERBATIM_KEYWORDS match (case-sensitive) in body."""
        pull = _make_pull(body="PERF: improve hot path")
        assert filter_base(pull) is True

    def test_verbatim_keyword_in_title(self):
        """D1: VERBATIM_KEYWORDS match in title."""
        pull = _make_pull(title="OPTIM: reduce allocations")
        assert filter_base(pull) is True

    def test_no_match(self):
        """D1: No keywords found returns False."""
        pull = _make_pull(title="Fix typo", body="Corrected a spelling mistake")
        assert filter_base(pull) is False

    def test_case_insensitive_base_keywords(self):
        """D4: Body is lowercased before BASE_PERF_KEYWORDS check."""
        pull = _make_pull(body="PERFORMANCE improvements")
        assert filter_base(pull) is True

    def test_verbatim_is_case_sensitive(self):
        """D4: VERBATIM_KEYWORDS are checked against original case.
        'Perf' does not match 'PERF' since it's checked on original item."""
        pull = _make_pull(title="Perf fix", body="No keywords")
        result = filter_base(pull)
        # "perf" not in BASE_PERF_KEYWORDS, "Perf" doesn't match VERBATIM "PERF"
        assert result is False

    def test_none_body(self):
        """D2: None body — production code uses `or ""` to handle None."""
        pull = _make_pull(title="Fix bug", body=None)
        assert filter_base(pull) is False

    def test_none_title(self):
        """D2: None title — production code uses `or ""` to handle None."""
        pull = _make_pull(title=None, body="Just a fix")
        assert filter_base(pull) is False

    def test_markdown_comment_stripped(self):
        """D4: Keywords inside markdown comments are stripped before checking."""
        pull = _make_pull(body="Normal text <!-- performance --> end")
        assert filter_base(pull) is False

    def test_keyword_outside_comment(self):
        """D4: Keyword outside comment still matches."""
        pull = _make_pull(body="performance <!-- hidden --> improvement")
        assert filter_base(pull) is True

    def test_custom_keywords_param_bug(self):
        """D8: BUG — custom keywords param is ignored for base keyword check.
        Line 78 hardcodes BASE_PERF_KEYWORDS instead of using the keywords param.
        So even with custom keywords, the original BASE_PERF_KEYWORDS are used.
        """
        pull = _make_pull(body="This has my_custom_word in it")
        result = filter_base(pull, keywords=["my_custom_word"])
        assert result is False  # custom keyword NOT checked

    @pytest.mark.parametrize("kw", [k for k in BASE_PERF_KEYWORDS if k == k.lower()])
    def test_every_base_keyword_matches(self, kw):
        """D1: Every lowercase BASE_PERF_KEYWORD matches when present in body."""
        pull = _make_pull(body=f"This PR addresses {kw} concerns")
        assert filter_base(pull) is True

    def test_cpu_usage_keyword_never_matches(self):
        """D8: BUG — 'CPU usage' has uppercase 'CPU' but body is lowercased.
        So 'CPU usage' can never match via the lowercased check path."""
        pull = _make_pull(body="This has CPU usage info")
        assert filter_base(pull) is False

    @pytest.mark.parametrize("kw", VERBATIM_KEYWORDS)
    def test_every_verbatim_keyword_matches(self, kw):
        """D1: Every VERBATIM_KEYWORD matches in body (original case)."""
        pull = _make_pull(body=f"Tag: {kw} improvement")
        assert filter_base(pull) is True


# ═══════════════════════════════════════════════════════════════════════════════
# filter_content
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilterContent:
    """Tests for filter_content(issue_text, keywords=BASE_PERF_KEYWORDS).

    Lowercases text, removes markdown comments, checks keywords.
    Unlike filter_base, this DOES use the keywords param correctly.
    """

    def test_keyword_match(self):
        """D1: Keyword found returns True."""
        assert filter_content("This has performance issues") is True

    def test_no_match(self):
        """D1: No keyword returns False."""
        assert filter_content("Just a bugfix") is False

    def test_case_insensitive(self):
        """D4: Text is lowercased — uppercase keywords in text still match."""
        assert filter_content("PERFORMANCE is critical") is True

    def test_none_input(self):
        """D2: None returns False."""
        assert filter_content(None) is False

    def test_empty_string(self):
        """D2: Empty string returns False."""
        assert filter_content("") is False

    def test_markdown_comments_stripped(self):
        """D4: Keywords in markdown comments are stripped."""
        assert filter_content("normal <!-- performance --> text") is False

    def test_custom_keywords(self):
        """D1: Custom keywords param works correctly (unlike filter_base)."""
        assert (
            filter_content("my_special_word here", keywords=["my_special_word"]) is True
        )
        assert filter_content("nothing here", keywords=["my_special_word"]) is False

    @pytest.mark.parametrize("kw", [k for k in BASE_PERF_KEYWORDS if k == k.lower()])
    def test_every_base_keyword_matches(self, kw):
        """D1: Every lowercase BASE_PERF_KEYWORD matches."""
        assert filter_content(f"Regarding {kw} improvements") is True

    def test_cpu_usage_never_matches(self):
        """D8: BUG — 'CPU usage' can't match because text is lowercased but keyword has uppercase."""
        assert filter_content("CPU usage is high") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Per-Repo Filters: Lowercase Title Group
# (sklearn, astropy, matplotlib, pylint, seaborn, sphinx, sympy, xarray, dask)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilterSklearn:
    """filter_sklearn: labels=["performance"], title keywords=["eff","perf"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_sklearn(pull) is True

    def test_title_eff(self):
        pull = _make_pull(title="Efficiency improvement")
        assert filter_sklearn(pull) is True

    def test_title_perf(self):
        pull = _make_pull(title="Perf: reduce overhead")
        assert filter_sklearn(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix bug", labels=[_make_label("bugfix")])
        assert filter_sklearn(pull) is False

    def test_case_insensitive_title(self):
        """Title is lowercased — 'PERF' in title matches 'perf'."""
        pull = _make_pull(title="PERF improvement")
        assert filter_sklearn(pull) is True


class TestFilterAstropy:
    """filter_astropy: labels=["performance"], title=["eff","perf","speed up"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_astropy(pull) is True

    def test_title_speed_up(self):
        pull = _make_pull(title="Speed up coordinate transforms")
        assert filter_astropy(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Add feature")
        assert filter_astropy(pull) is False


class TestFilterMatplotlib:
    """filter_matplotlib: labels=["performance"], title=["perf"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_matplotlib(pull) is True

    def test_title_perf(self):
        pull = _make_pull(title="Perf: faster rendering")
        assert filter_matplotlib(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix axis labels")
        assert filter_matplotlib(pull) is False


class TestFilterPylint:
    """filter_pylint: labels=["performance"], title=["perf"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_pylint(pull) is True

    def test_title_perf(self):
        pull = _make_pull(title="Perf: faster checker")
        assert filter_pylint(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Add new check")
        assert filter_pylint(pull) is False


class TestFilterSeaborn:
    """filter_seaborn: labels=["perf"], title=["perf"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("perf")])
        assert filter_seaborn(pull) is True

    def test_title_perf(self):
        pull = _make_pull(title="perf: faster plotting")
        assert filter_seaborn(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Update docs")
        assert filter_seaborn(pull) is False


class TestFilterSphinx:
    """filter_sphinx: labels=["type:performance"], title=["perf"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("type:performance")])
        assert filter_sphinx(pull) is True

    def test_title_perf(self):
        pull = _make_pull(title="perf: faster build")
        assert filter_sphinx(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix docs")
        assert filter_sphinx(pull) is False


class TestFilterSympy:
    """filter_sympy: labels=["performance"], title=["perf"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_sympy(pull) is True

    def test_title_perf(self):
        pull = _make_pull(title="perf: simplify faster")
        assert filter_sympy(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Add integral")
        assert filter_sympy(pull) is False


class TestFilterXarray:
    """filter_xarray: labels=["topic-performance"], title=["perf","speed up"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("topic-performance")])
        assert filter_xarray(pull) is True

    def test_title_speed_up(self):
        pull = _make_pull(title="speed up merge operation")
        assert filter_xarray(pull) is True

    def test_title_perf(self):
        pull = _make_pull(title="perf: improve indexing")
        assert filter_xarray(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix dimension error")
        assert filter_xarray(pull) is False


class TestFilterDask:
    """filter_dask: no labels, title=["perf","speed up","efficiency","remove",
    "avoid","overhead","memory"]. Title is lowercased."""

    def test_title_perf(self):
        pull = _make_pull(title="perf: parallel scheduler")
        assert filter_dask(pull) is True

    def test_title_memory(self):
        pull = _make_pull(title="Reduce memory usage in shuffle")
        assert filter_dask(pull) is True

    def test_title_overhead(self):
        pull = _make_pull(title="Reduce overhead in task graph")
        assert filter_dask(pull) is True

    def test_title_remove(self):
        pull = _make_pull(title="Remove unnecessary copies")
        assert filter_dask(pull) is True

    def test_title_avoid(self):
        pull = _make_pull(title="Avoid repeated serialization")
        assert filter_dask(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix bug in scheduler")
        assert filter_dask(pull) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Per-Repo Filters: Original Case Title Group
# (pandas, numpy, statsmodels, pillow, spacy, numba, gensim, scikit_image)
# These filters do NOT lowercase the title — case-sensitive matching.
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilterPandas:
    """filter_pandas: labels=["performance"], title (ORIGINAL CASE)
    keywords=["perf","speed up","efficiency","performance"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_pandas(pull) is True

    def test_title_lowercase_perf(self):
        pull = _make_pull(title="perf: faster groupby")
        assert filter_pandas(pull) is True

    def test_title_uppercase_perf_no_match(self):
        """D4: Title NOT lowercased — 'PERF' doesn't match 'perf'."""
        pull = _make_pull(title="PERF improvement")
        assert filter_pandas(pull) is False

    def test_no_match(self):
        pull = _make_pull(title="Fix NA handling")
        assert filter_pandas(pull) is False


class TestFilterNumpy:
    """filter_numpy: NO labels, title (ORIGINAL CASE)
    keywords=["perf","speed up","efficiency","performance"]."""

    def test_title_performance(self):
        pull = _make_pull(title="performance: faster ufunc")
        assert filter_numpy(pull) is True

    def test_title_uppercase_no_match(self):
        """D4: Title NOT lowercased — 'PERFORMANCE' doesn't match 'performance'."""
        pull = _make_pull(title="PERFORMANCE fix")
        assert filter_numpy(pull) is False

    def test_no_match(self):
        pull = _make_pull(title="Fix dtype conversion")
        assert filter_numpy(pull) is False


class TestFilterStatsmodels:
    """filter_statsmodels: labels=["performance"], title (ORIGINAL CASE)."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_statsmodels(pull) is True

    def test_title_match(self):
        pull = _make_pull(title="performance: faster OLS")
        assert filter_statsmodels(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix p-value calculation")
        assert filter_statsmodels(pull) is False


class TestFilterPillow:
    """filter_pillow: labels=["performance"], title (ORIGINAL CASE)
    keywords=["perf","speed","efficiency","performance"]."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_pillow(pull) is True

    def test_title_speed(self):
        pull = _make_pull(title="speed up image resize")
        assert filter_pillow(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix EXIF parsing")
        assert filter_pillow(pull) is False


class TestFilterSpacy:
    """filter_spacy: labels=["perf"], title (ORIGINAL CASE)."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("perf")])
        assert filter_spacy(pull) is True

    def test_title_match(self):
        pull = _make_pull(title="performance: faster tokenizer")
        assert filter_spacy(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Add new NER model")
        assert filter_spacy(pull) is False


class TestFilterNumba:
    """filter_numba: labels=["performance"], title (ORIGINAL CASE)."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_numba(pull) is True

    def test_title_match(self):
        pull = _make_pull(title="perf: faster JIT compilation")
        assert filter_numba(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix typing issue")
        assert filter_numba(pull) is False


class TestFilterGensim:
    """filter_gensim: labels=["performance"], title (ORIGINAL CASE)."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_gensim(pull) is True

    def test_title_match(self):
        pull = _make_pull(title="efficiency: faster word2vec training")
        assert filter_gensim(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix vocabulary loading")
        assert filter_gensim(pull) is False


class TestFilterScikitImage:
    """filter_scikit_image: labels=["performance"], title (ORIGINAL CASE)."""

    def test_label_match(self):
        pull = _make_pull(labels=[_make_label("performance")])
        assert filter_scikit_image(pull) is True

    def test_title_match(self):
        pull = _make_pull(title="speed up convolution")
        assert filter_scikit_image(pull) is True

    def test_no_match(self):
        pull = _make_pull(title="Fix edge detection")
        assert filter_scikit_image(pull) is False


# ═══════════════════════════════════════════════════════════════════════════════
# REPO_PERF_FILTERS Registry
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepoPerfFilters:
    """Validate REPO_PERF_FILTERS dict."""

    def test_all_expected_repos_registered(self):
        """D1: All 19 expected repos + 'default' are in the dict."""
        expected = [
            "default",
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
        ]
        for repo in expected:
            assert repo in REPO_PERF_FILTERS, f"{repo!r} missing"

    def test_default_is_filter_base(self):
        """D1: 'default' maps to filter_base."""
        assert REPO_PERF_FILTERS["default"] is filter_base

    def test_scipy_aliases_numpy(self):
        """D1: 'scipy' maps to filter_numpy (documented alias)."""
        assert REPO_PERF_FILTERS["scipy"] is filter_numpy

    def test_all_values_are_callable(self):
        """D1: Every registered filter is callable."""
        for name, func in REPO_PERF_FILTERS.items():
            assert callable(func), f"{name!r} -> {func!r} is not callable"

    def test_all_filters_accept_pull_dict(self):
        """D12: Every filter can be called with a standard pull dict."""
        pull = _make_pull(title="neutral", body="neutral", labels=[])
        for name, func in REPO_PERF_FILTERS.items():
            if name == "default":
                result = func(pull)
            else:
                result = func(pull)
            assert isinstance(result, bool), f"{name!r} returned {type(result)}"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: is_perf_pr dispatching
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsPerfPrIntegration:
    """D12: Integration test for the dispatch logic used by filter.py's is_perf_pr.
    Tests that repo-specific filters and default fallback work together."""

    def test_registered_repo_uses_specific_filter(self):
        """D12: 'scikit-learn' uses filter_sklearn, not just default."""
        pull = _make_pull(
            title="eff: reduce overhead",
            body="No base keywords",
            labels=[],
        )
        # filter_sklearn matches 'eff' in title
        assert filter_sklearn(pull) is True
        # filter_base would NOT match (no BASE_PERF_KEYWORDS in body/title)
        assert filter_base(pull) is False

    def test_default_fallback_for_unregistered(self):
        """D12: Unregistered repo falls through to filter_base."""
        pull = _make_pull(body="Improve performance")
        assert filter_base(pull) is True

    def test_scipy_uses_numpy_filter(self):
        """D12: scipy dispatches to filter_numpy."""
        pull = _make_pull(title="performance: faster linalg")
        assert REPO_PERF_FILTERS["scipy"](pull) is True
        assert REPO_PERF_FILTERS["scipy"] is filter_numpy


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: filter_base  (D1/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveFilterBaseExpanded:
    """D1/D4: Exhaustive keyword placement and casing tests for filter_base."""

    @pytest.mark.parametrize(
        "body,expected",
        [
            ("performance", True),  # exact keyword
            ("prefix performance suffix", True),  # middle
            ("performance at start", True),  # start
            ("at end performance", True),  # end
            ("speedup", True),  # exact keyword
            ("prefix speedup suffix", True),  # middle
            ("speedup at start", True),  # start
            ("at end speedup", True),  # end
            ("speeds up", True),  # exact keyword
            ("prefix speeds up suffix", True),  # middle
            ("speeds up at start", True),  # start
            ("at end speeds up", True),  # end
            ("speed-up", True),  # exact keyword
            ("prefix speed-up suffix", True),  # middle
            ("speed-up at start", True),  # start
            ("at end speed-up", True),  # end
            ("speed up", True),  # exact keyword
            ("prefix speed up suffix", True),  # middle
            ("speed up at start", True),  # start
            ("at end speed up", True),  # end
            ("faster", True),  # exact keyword
            ("prefix faster suffix", True),  # middle
            ("faster at start", True),  # start
            ("at end faster", True),  # end
            ("memory", True),  # exact keyword
            ("prefix memory suffix", True),  # middle
            ("memory at start", True),  # start
            ("at end memory", True),  # end
            ("optimize", True),  # exact keyword
            ("prefix optimize suffix", True),  # middle
            ("optimize at start", True),  # start
            ("at end optimize", True),  # end
            ("optimization", True),  # exact keyword
            ("prefix optimization suffix", True),  # middle
            ("optimization at start", True),  # start
            ("at end optimization", True),  # end
            ("profiling", True),  # exact keyword
            ("prefix profiling suffix", True),  # middle
            ("profiling at start", True),  # start
            ("at end profiling", True),  # end
            ("accelerate", True),  # exact keyword
            ("prefix accelerate suffix", True),  # middle
            ("accelerate at start", True),  # start
            ("at end accelerate", True),  # end
            ("fast", True),  # exact keyword
            ("prefix fast suffix", True),  # middle
            ("fast at start", True),  # start
            ("at end fast", True),  # end
            ("runtime", True),  # exact keyword
            ("prefix runtime suffix", True),  # middle
            ("runtime at start", True),  # start
            ("at end runtime", True),  # end
            ("efficiency", True),  # exact keyword
            ("prefix efficiency suffix", True),  # middle
            ("efficiency at start", True),  # start
            ("at end efficiency", True),  # end
            ("benchmark", True),  # exact keyword
            ("prefix benchmark suffix", True),  # middle
            ("benchmark at start", True),  # start
            ("at end benchmark", True),  # end
            ("latency", True),  # exact keyword
            ("prefix latency suffix", True),  # middle
            ("latency at start", True),  # start
            ("at end latency", True),  # end
            ("throughput", True),  # exact keyword
            ("prefix throughput suffix", True),  # middle
            ("throughput at start", True),  # start
            ("at end throughput", True),  # end
            ("multithreading", True),  # exact keyword
            ("prefix multithreading suffix", True),  # middle
            ("multithreading at start", True),  # start
            ("at end multithreading", True),  # end
            ("parallel", True),  # exact keyword
            ("prefix parallel suffix", True),  # middle
            ("parallel at start", True),  # start
            ("at end parallel", True),  # end
            ("concurrency", True),  # exact keyword
            ("prefix concurrency suffix", True),  # middle
            ("concurrency at start", True),  # start
            ("at end concurrency", True),  # end
            ("concurrent", True),  # exact keyword
            ("prefix concurrent suffix", True),  # middle
            ("concurrent at start", True),  # start
            ("at end concurrent", True),  # end
            ("memory usage", True),  # exact keyword
            ("prefix memory usage suffix", True),  # middle
            ("memory usage at start", True),  # start
            ("at end memory usage", True),  # end
            ("resource usage", True),  # exact keyword
            ("prefix resource usage suffix", True),  # middle
            ("resource usage at start", True),  # start
            ("at end resource usage", True),  # end
            ("cache", True),  # exact keyword
            ("prefix cache suffix", True),  # middle
            ("cache at start", True),  # start
            ("at end cache", True),  # end
            ("caching", True),  # exact keyword
            ("prefix caching suffix", True),  # middle
            ("caching at start", True),  # start
            ("at end caching", True),  # end
            ("timeit", True),  # exact keyword
            ("prefix timeit suffix", True),  # middle
            ("timeit at start", True),  # start
            ("at end timeit", True),  # end
            ("asv", True),  # exact keyword
            ("prefix asv suffix", True),  # middle
            ("asv at start", True),  # start
            ("at end asv", True),  # end
        ],
    )
    def test_keyword_positions_in_body(self, body, expected):
        pull = _make_pull(body=body)
        assert filter_base(pull) == expected

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("performance", True),
            ("prefix performance suffix", True),
            ("speedup", True),
            ("prefix speedup suffix", True),
            ("speeds up", True),
            ("prefix speeds up suffix", True),
            ("speed-up", True),
            ("prefix speed-up suffix", True),
            ("speed up", True),
            ("prefix speed up suffix", True),
            ("faster", True),
            ("prefix faster suffix", True),
            ("memory", True),
            ("prefix memory suffix", True),
            ("optimize", True),
            ("prefix optimize suffix", True),
            ("optimization", True),
            ("prefix optimization suffix", True),
            ("profiling", True),
            ("prefix profiling suffix", True),
            ("accelerate", True),
            ("prefix accelerate suffix", True),
            ("fast", True),
            ("prefix fast suffix", True),
            ("runtime", True),
            ("prefix runtime suffix", True),
            ("efficiency", True),
            ("prefix efficiency suffix", True),
            ("benchmark", True),
            ("prefix benchmark suffix", True),
            ("latency", True),
            ("prefix latency suffix", True),
            ("throughput", True),
            ("prefix throughput suffix", True),
            ("multithreading", True),
            ("prefix multithreading suffix", True),
            ("parallel", True),
            ("prefix parallel suffix", True),
            ("concurrency", True),
            ("prefix concurrency suffix", True),
            ("concurrent", True),
            ("prefix concurrent suffix", True),
            ("memory usage", True),
            ("prefix memory usage suffix", True),
            ("resource usage", True),
            ("prefix resource usage suffix", True),
            ("cache", True),
            ("prefix cache suffix", True),
            ("caching", True),
            ("prefix caching suffix", True),
            ("timeit", True),
            ("prefix timeit suffix", True),
            ("asv", True),
            ("prefix asv suffix", True),
        ],
    )
    def test_keyword_positions_in_title(self, title, expected):
        pull = _make_pull(title=title, body="neutral")
        assert filter_base(pull) == expected

    @pytest.mark.parametrize(
        "body,expected",
        [
            ("PERFORMANCE", True),  # upper: performance
            ("Performance", True),  # title: performance
            ("PeRfOrMaNcE", True),  # alternating
            ("SPEEDUP", True),  # upper: speedup
            ("Speedup", True),  # title: speedup
            ("SpEeDuP", True),  # alternating
            ("SPEEDS UP", True),  # upper: speeds up
            ("Speeds Up", True),  # title: speeds up
            ("SpEeDs uP", True),  # alternating
            ("SPEED-UP", True),  # upper: speed-up
            ("Speed-Up", True),  # title: speed-up
            ("SpEeD-Up", True),  # alternating
            ("SPEED UP", True),  # upper: speed up
            ("Speed Up", True),  # title: speed up
            ("SpEeD Up", True),  # alternating
            ("FASTER", True),  # upper: faster
            ("Faster", True),  # title: faster
            ("FaStEr", True),  # alternating
            ("MEMORY", True),  # upper: memory
            ("Memory", True),  # title: memory
            ("MeMoRy", True),  # alternating
            ("OPTIMIZE", True),  # upper: optimize
            ("Optimize", True),  # title: optimize
            ("OpTiMiZe", True),  # alternating
            ("OPTIMIZATION", True),  # upper: optimization
            ("Optimization", True),  # title: optimization
            ("OpTiMiZaTiOn", True),  # alternating
            ("PROFILING", True),  # upper: profiling
            ("Profiling", True),  # title: profiling
            ("PrOfIlInG", True),  # alternating
            ("ACCELERATE", True),  # upper: accelerate
            ("Accelerate", True),  # title: accelerate
            ("AcCeLeRaTe", True),  # alternating
            ("FAST", True),  # upper: fast
            ("Fast", True),  # title: fast
            ("FaSt", True),  # alternating
            ("RUNTIME", True),  # upper: runtime
            ("Runtime", True),  # title: runtime
            ("RuNtImE", True),  # alternating
            ("EFFICIENCY", True),  # upper: efficiency
            ("Efficiency", True),  # title: efficiency
            ("EfFiCiEnCy", True),  # alternating
            ("BENCHMARK", True),  # upper: benchmark
            ("Benchmark", True),  # title: benchmark
            ("BeNcHmArK", True),  # alternating
            ("LATENCY", True),  # upper: latency
            ("Latency", True),  # title: latency
            ("LaTeNcY", True),  # alternating
            ("THROUGHPUT", True),  # upper: throughput
            ("Throughput", True),  # title: throughput
            ("ThRoUgHpUt", True),  # alternating
            ("MULTITHREADING", True),  # upper: multithreading
            ("Multithreading", True),  # title: multithreading
            ("MuLtItHrEaDiNg", True),  # alternating
            ("PARALLEL", True),  # upper: parallel
            ("Parallel", True),  # title: parallel
            ("PaRaLlEl", True),  # alternating
            ("CONCURRENCY", True),  # upper: concurrency
            ("Concurrency", True),  # title: concurrency
            ("CoNcUrReNcY", True),  # alternating
            ("CONCURRENT", True),  # upper: concurrent
            ("Concurrent", True),  # title: concurrent
            ("CoNcUrReNt", True),  # alternating
            ("MEMORY USAGE", True),  # upper: memory usage
            ("Memory Usage", True),  # title: memory usage
            ("MeMoRy uSaGe", True),  # alternating
            ("RESOURCE USAGE", True),  # upper: resource usage
            ("Resource Usage", True),  # title: resource usage
            ("ReSoUrCe uSaGe", True),  # alternating
            ("CACHE", True),  # upper: cache
            ("Cache", True),  # title: cache
            ("CaChE", True),  # alternating
            ("CACHING", True),  # upper: caching
            ("Caching", True),  # title: caching
            ("CaChInG", True),  # alternating
            ("TIMEIT", True),  # upper: timeit
            ("Timeit", True),  # title: timeit
            ("TiMeIt", True),  # alternating
            ("ASV", True),  # upper: asv
            ("Asv", True),  # title: asv
            ("AsV", True),  # alternating
        ],
    )
    def test_keyword_case_variants(self, body, expected):
        """D4: Case-insensitive matching (text is lowercased before check)."""
        pull = _make_pull(body=body)
        assert filter_base(pull) == expected


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: filter_content  (D1/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveFilterContentExpanded:
    """D1/D4: Exhaustive keyword tests for filter_content."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("performance", True),
            ("PERFORMANCE", True),
            ("Performance", True),
            ("prefix performance suffix", True),
            ("speedup", True),
            ("SPEEDUP", True),
            ("Speedup", True),
            ("prefix speedup suffix", True),
            ("speeds up", True),
            ("SPEEDS UP", True),
            ("Speeds Up", True),
            ("prefix speeds up suffix", True),
            ("speed-up", True),
            ("SPEED-UP", True),
            ("Speed-Up", True),
            ("prefix speed-up suffix", True),
            ("speed up", True),
            ("SPEED UP", True),
            ("Speed Up", True),
            ("prefix speed up suffix", True),
            ("faster", True),
            ("FASTER", True),
            ("Faster", True),
            ("prefix faster suffix", True),
            ("memory", True),
            ("MEMORY", True),
            ("Memory", True),
            ("prefix memory suffix", True),
            ("optimize", True),
            ("OPTIMIZE", True),
            ("Optimize", True),
            ("prefix optimize suffix", True),
            ("optimization", True),
            ("OPTIMIZATION", True),
            ("Optimization", True),
            ("prefix optimization suffix", True),
            ("profiling", True),
            ("PROFILING", True),
            ("Profiling", True),
            ("prefix profiling suffix", True),
            ("accelerate", True),
            ("ACCELERATE", True),
            ("Accelerate", True),
            ("prefix accelerate suffix", True),
            ("fast", True),
            ("FAST", True),
            ("Fast", True),
            ("prefix fast suffix", True),
            ("runtime", True),
            ("RUNTIME", True),
            ("Runtime", True),
            ("prefix runtime suffix", True),
            ("efficiency", True),
            ("EFFICIENCY", True),
            ("Efficiency", True),
            ("prefix efficiency suffix", True),
            ("benchmark", True),
            ("BENCHMARK", True),
            ("Benchmark", True),
            ("prefix benchmark suffix", True),
            ("latency", True),
            ("LATENCY", True),
            ("Latency", True),
            ("prefix latency suffix", True),
            ("throughput", True),
            ("THROUGHPUT", True),
            ("Throughput", True),
            ("prefix throughput suffix", True),
            ("multithreading", True),
            ("MULTITHREADING", True),
            ("Multithreading", True),
            ("prefix multithreading suffix", True),
            ("parallel", True),
            ("PARALLEL", True),
            ("Parallel", True),
            ("prefix parallel suffix", True),
            ("concurrency", True),
            ("CONCURRENCY", True),
            ("Concurrency", True),
            ("prefix concurrency suffix", True),
            ("concurrent", True),
            ("CONCURRENT", True),
            ("Concurrent", True),
            ("prefix concurrent suffix", True),
            ("memory usage", True),
            ("MEMORY USAGE", True),
            ("Memory Usage", True),
            ("prefix memory usage suffix", True),
            ("resource usage", True),
            ("RESOURCE USAGE", True),
            ("Resource Usage", True),
            ("prefix resource usage suffix", True),
            ("cache", True),
            ("CACHE", True),
            ("Cache", True),
            ("prefix cache suffix", True),
            ("caching", True),
            ("CACHING", True),
            ("Caching", True),
            ("prefix caching suffix", True),
            ("timeit", True),
            ("TIMEIT", True),
            ("Timeit", True),
            ("prefix timeit suffix", True),
            ("asv", True),
            ("ASV", True),
            ("Asv", True),
            ("prefix asv suffix", True),
        ],
    )
    def test_keyword_variants(self, text, expected):
        assert filter_content(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "fix typo",
            "add feature",
            "refactor",
            "update deps",
            "correct spelling",
            "bump version",
            "merge branch",
            "revert commit",
            "cleanup imports",
            "rename variable",
            "move file",
            "delete code",
            "format code",
            "sort imports",
            "add docstring",
            "remove print",
            "update readme",
            "add license",
            "fix indent",
            "add type hints",
            "remove unused",
            "simplify logic",
            "extract function",
            "inline variable",
            "rename class",
            "split module",
            "merge modules",
            "add logging",
            "remove debug",
            "update config",
            "fix test",
        ],
    )
    def test_non_matching_texts(self, text):
        """D1: Non-performance text returns False."""
        assert filter_content(text) is False


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: check_labels  (D1/D4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveCheckLabelsExpanded:
    """D1/D4: Exhaustive label matching."""

    LABEL_NAMES = [
        "bug",
        "enhancement",
        "feature",
        "documentation",
        "test",
        "ci",
        "refactor",
        "chore",
        "style",
        "build",
        "deps",
        "security",
        "breaking",
        "wontfix",
        "duplicate",
        "invalid",
        "question",
        "help wanted",
        "good first issue",
        "performance",
        "optimization",
        "benchmark",
        "profiling",
        "type:bug",
        "type:feature",
        "type:performance",
        "priority:high",
        "priority:low",
        "priority:medium",
        "status:in-progress",
        "status:review",
        "status:done",
        "area:core",
        "area:api",
        "area:cli",
        "area:docs",
        "topic-performance",
        "topic-testing",
        "topic-security",
        "category-performance",
        "category-bugfix",
    ]

    @pytest.mark.parametrize("label_name", LABEL_NAMES)
    def test_exact_self_match(self, label_name):
        """D1: Every label matches itself as value (lowercased)."""
        pull = _make_pull(labels=[_make_label(label_name)])
        assert check_labels(pull, [label_name.lower()]) is True

    @pytest.mark.parametrize("label_name", LABEL_NAMES)
    def test_no_match_against_unrelated(self, label_name):
        """D1: Labels don't match unrelated values."""
        if "zzz" not in label_name.lower():
            pull = _make_pull(labels=[_make_label(label_name)])
            assert check_labels(pull, ["zzz-nonexistent"]) is False

    @pytest.mark.parametrize("n_labels", list(range(1, 31)))
    def test_n_labels_last_matches(self, n_labels):
        """D11: Match found at position n (1-30)."""
        labels = [_make_label(f"unrelated-{i}") for i in range(n_labels - 1)]
        labels.append(_make_label("performance"))
        pull = _make_pull(labels=labels)
        assert check_labels(pull, ["performance"]) is True

    @pytest.mark.parametrize("n_values", list(range(1, 21)))
    def test_n_values_last_matches(self, n_values):
        """D11: Match with target value at position n (1-20)."""
        values = [f"unrelated-{i}" for i in range(n_values - 1)]
        values.append("performance")
        pull = _make_pull(labels=[_make_label("performance")])
        assert check_labels(pull, values) is True


# ═══════════════════════════════════════════════════════════════════════════════
# MASSIVE PARAMETRIZED EXPANSION: remove_markdown_comments  (D1/D4/D11)
# ═══════════════════════════════════════════════════════════════════════════════


class TestMassiveRemoveMarkdownCommentsExpanded:
    """D1/D4/D11: Exhaustive comment removal."""

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_n_comments_removed(self, n):
        """D11: 1-50 comments all removed."""
        text = " ".join(f"<!-- c{i} -->" for i in range(n))
        result = remove_markdown_comments(text)
        assert "<!--" not in result

    @pytest.mark.parametrize("n", list(range(1, 51)))
    def test_preserved_text_between_n_comments(self, n):
        """D4: Text between n comments preserved."""
        parts = []
        for i in range(n):
            parts.append(f"text{i} <!-- comment{i} -->")
        parts.append(f"text{n}")
        text = " ".join(parts)
        result = remove_markdown_comments(text)
        for i in range(n + 1):
            assert f"text{i}" in result

    @pytest.mark.parametrize("content_char", [chr(i) for i in range(32, 127)])
    def test_various_chars_inside_comment(self, content_char):
        """D4: Various characters inside comments are stripped."""
        text = f"before <!-- {content_char} --> after"
        result = remove_markdown_comments(text)
        assert result == "before  after"


# ═══════════════════════════════════════════════════════════════════════════════
# WAVE 2: Additional parametrized expansion
# ═══════════════════════════════════════════════════════════════════════════════

_ALL_REPOS_WITH_FILTERS = [
    "scikit-learn",
    "astropy",
    "matplotlib",
    "pylint",
    "seaborn",
    "sphinx",
    "sympy",
    "xarray",
    "dask",
    "pandas",
    "numpy",
    "statsmodels",
    "pillow",
    "spacy",
    "numba",
    "gensim",
    "scikit-image",
    "scipy",
]

_LOWERCASE_REPOS = [
    "scikit-learn",
    "astropy",
    "matplotlib",
    "pylint",
    "seaborn",
    "sphinx",
    "sympy",
    "xarray",
    "dask",
]
_ORIGINAL_CASE_REPOS = [
    "pandas",
    "numpy",
    "statsmodels",
    "pillow",
    "spacy",
    "numba",
    "gensim",
    "scikit-image",
]

_REPO_TITLE_KEYWORDS = {
    "scikit-learn": ["eff", "perf"],
    "astropy": ["eff", "perf", "speed up"],
    "matplotlib": ["perf"],
    "pylint": ["perf"],
    "seaborn": ["perf"],
    "sphinx": ["perf"],
    "sympy": ["perf"],
    "xarray": ["perf", "speed up"],
    "dask": ["perf", "speed up", "efficiency", "remove", "avoid", "overhead", "memory"],
    "pandas": ["perf", "speed up", "efficiency", "performance"],
    "numpy": ["perf", "speed up", "efficiency", "performance"],
    "statsmodels": ["perf", "speed up", "efficiency", "performance"],
    "pillow": ["perf", "speed", "efficiency", "performance"],
    "spacy": ["perf", "speed", "efficiency", "performance"],
    "numba": ["perf", "speed", "efficiency", "performance"],
    "gensim": ["perf", "speed", "efficiency", "performance"],
    "scikit-image": ["perf", "speed", "efficiency", "performance"],
}


class TestWave2FilterBaseAllKeywordsBody:
    """D1: Every BASE_PERF_KEYWORDS keyword in body, verified individually."""

    @pytest.mark.parametrize(
        "keyword", [k for k in BASE_PERF_KEYWORDS if k != "CPU usage"]
    )
    @pytest.mark.parametrize(
        "template",
        [
            "PR body: {kw}",
            "Improved {kw} handling",
            "{kw} is now faster",
            "({kw})",
            "[{kw}]",
            "{kw}\n\nMore text",
            "   {kw}   ",
        ],
    )
    def test_keyword_in_body_template(self, keyword, template):
        """D1: keyword in various body positions."""
        pull = _make_pull(body=template.format(kw=keyword))
        assert filter_base(pull) is True


class TestWave2FilterBaseAllKeywordsTitle:
    """D1: Every BASE_PERF_KEYWORDS keyword in title."""

    @pytest.mark.parametrize(
        "keyword", [k for k in BASE_PERF_KEYWORDS if k != "CPU usage"]
    )
    @pytest.mark.parametrize(
        "template",
        [
            "PR: {kw}",
            "Improve {kw}",
            "{kw} fix",
        ],
    )
    def test_keyword_in_title_template(self, keyword, template):
        """D1: keyword in various title positions."""
        pull = _make_pull(title=template.format(kw=keyword))
        assert filter_base(pull) is True


class TestWave2FilterContentAllKeywords:
    """D1: Every BASE keyword in text, all case variants."""

    @pytest.mark.parametrize(
        "keyword", [k for k in BASE_PERF_KEYWORDS if k != "CPU usage"]
    )
    @pytest.mark.parametrize("case_fn_name", ["lower", "upper", "title", "swapcase"])
    def test_keyword_case_in_text(self, keyword, case_fn_name):
        """D4: keyword in all case variants."""
        fn = getattr(str, case_fn_name)
        text = f"Discussion about {fn(keyword)} improvements"
        assert filter_content(text) is True


class TestWave2FilterContentNonMatching:
    """D1: Words that don't contain any BASE keyword."""

    NON_MATCHING = [
        "hello world",
        "just a regular PR",
        "fixed typo",
        "updated dependencies",
        "refactored code",
        "added tests",
        "removed dead code",
        "cleaned up imports",
        "formatting",
        "documentation update",
        "version bump",
        "release notes",
        "cherry-pick",
        "backport",
        "hotfix",
        "bugfix",
        "migration",
        "schema change",
        "api change",
        "logging",
        "debugging",
        "tracing",
        "authentication",
        "authorization",
        "encryption",
        "deployment",
        "configuration",
        "infrastructure",
        "UI update",
        "CSS change",
        "translation",
        "accessibility",
        "localization",
        "internationalization",
    ]

    @pytest.mark.parametrize("text", NON_MATCHING)
    def test_non_matching_text(self, text):
        """D1: Text without any performance keyword returns False."""
        assert filter_content(text) is False


class TestWave2CheckLabelsExhaustive:
    """D4: Exhaustive label name x search value combinations."""

    LABEL_NAMES = [
        "bug",
        "enhancement",
        "feature",
        "performance",
        "optimization",
        "speed",
        "memory",
        "cpu",
        "benchmark",
        "profiling",
        "regression",
        "improvement",
        "critical",
        "major",
        "minor",
        "patch",
        "breaking",
        "deprecation",
        "security",
        "maintenance",
    ]

    @pytest.mark.parametrize("label", LABEL_NAMES)
    def test_exact_self_match(self, label):
        """D1: Label matches itself."""
        pull = _make_pull(labels=[_make_label(label)])
        assert check_labels(pull, [label]) is True

    @pytest.mark.parametrize("label", LABEL_NAMES)
    def test_first_three_chars_match(self, label):
        """D4: First 3 chars of label as search value — substring match."""
        pull = _make_pull(labels=[_make_label(label)])
        prefix = label[:3]
        result = check_labels(pull, [prefix])
        assert result is (prefix in label.lower())

    @pytest.mark.parametrize("label", LABEL_NAMES)
    @pytest.mark.parametrize("unrelated", ["zzz", "xxx", "qqq", "jjj", "yyy"])
    def test_unrelated_no_match(self, label, unrelated):
        """D1: Unrelated search value doesn't match."""
        pull = _make_pull(labels=[_make_label(label)])
        assert check_labels(pull, [unrelated]) is False


class TestWave2PerRepoFilterTitleKeywords:
    """D1/D12: Every repo's title keywords verified systematically."""

    @pytest.mark.parametrize("repo", _LOWERCASE_REPOS)
    def test_lowercase_repo_title_keywords(self, repo):
        """D1: Each keyword for lowercase-title repos."""
        repo_filter = REPO_PERF_FILTERS[repo]
        for keyword in _REPO_TITLE_KEYWORDS.get(repo, []):
            pull = _make_pull(title=keyword)
            assert repo_filter(pull) is True, f"{repo}: '{keyword}' should match"

    @pytest.mark.parametrize("repo", _ORIGINAL_CASE_REPOS)
    def test_original_case_repo_title_keywords(self, repo):
        """D1: Each keyword for original-case repos."""
        repo_filter = REPO_PERF_FILTERS[repo]
        for keyword in _REPO_TITLE_KEYWORDS.get(repo, []):
            pull = _make_pull(title=keyword)
            assert repo_filter(pull) is True, f"{repo}: '{keyword}' should match"


class TestWave2PerRepoFilterNoMatch:
    """D1: Non-matching titles for all repos."""

    NON_PERF_TITLES = [
        "fix typo in docstring",
        "update CI configuration",
        "add new test case",
        "bump version to 2.0",
        "fix import error",
    ]

    @pytest.mark.parametrize("repo", _ALL_REPOS_WITH_FILTERS)
    @pytest.mark.parametrize("title", NON_PERF_TITLES)
    def test_non_perf_title_no_match(self, repo, title):
        """D1: Non-perf titles don't match repo-specific filters."""
        repo_filter = REPO_PERF_FILTERS[repo]
        pull = _make_pull(title=title)
        result = repo_filter(pull)
        assert result is False, f"{repo}: '{title}' should NOT match"


class TestWave2RemoveMarkdownCommentsNested:
    """D4: Various comment patterns."""

    @pytest.mark.parametrize("n", list(range(1, 31)))
    def test_n_word_comments(self, n):
        """D4: Comments with n words inside."""
        words = " ".join([f"word{i}" for i in range(n)])
        text = f"before <!-- {words} --> after"
        result = remove_markdown_comments(text)
        assert "before" in result
        assert "after" in result
        for i in range(n):
            assert f"word{i}" not in result

    @pytest.mark.parametrize(
        "char", [c for c in "abcdefghijklmnopqrstuvwxyz0123456789"]
    )
    def test_single_char_in_comment(self, char):
        """D4: Single character inside comment removed."""
        text = f"A <!-- {char} --> B"
        result = remove_markdown_comments(text)
        assert "A" in result
        assert "B" in result
