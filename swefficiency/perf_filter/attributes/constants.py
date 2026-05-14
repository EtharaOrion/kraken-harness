# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Performance PR filtering constants and keyword-based filters.

PAPER ALIGNMENT (Appendix C.2, arxiv 2511.06090):
  Stage II Criterion 2 specifies EXACTLY 28 keywords for PR metadata matching.
  These are preserved in PAPER_PERF_KEYWORDS below (do NOT modify).
  
  EXTENDED_PERF_KEYWORDS adds additional recall keywords for the scaled pipeline.
  The combined set is used by default for broader coverage at 10k+ scale.

DESIGN PHILOSOPHY:
  Universal filter_base() works for ANY Python repo via keyword + label matching.
  Repo-specific filters are OPTIONAL overrides for known repos with label conventions.
  For unknown repos, filter_base applies automatically.
"""

import re

# ─────────────────────────────────────────────────────────────────────────────
# KEYWORDS — PAPER-SPECIFIED (DO NOT MODIFY)
# ─────────────────────────────────────────────────────────────────────────────
# Exact 28 keywords from Appendix C.2 of arxiv 2511.06090
PAPER_PERF_KEYWORDS = [
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
    # "fast" — moved to WORD_BOUNDARY_KEYWORDS only (substring match catches FastAPI, breakfast)
    "runtime",
    "efficiency",
    "benchmark",
    "latency",
    "throughput",
    "multithreading",
    "parallel",
    "concurrency",
    "concurrent",
    "CPU usage",
    "memory usage",
    "resource usage",
    "cache",
    "caching",
    "timeit",
    "asv",
]

# ─────────────────────────────────────────────────────────────────────────────
# KEYWORDS — EXTENDED (for broader recall at scale)
# ─────────────────────────────────────────────────────────────────────────────

# Backward-compatible alias (tests and legacy code reference this name)
BASE_PERF_KEYWORDS = PAPER_PERF_KEYWORDS
# Additional keywords beyond the paper's 28, for catching implicit perf PRs.
# Used when --extended-keywords flag is passed to the filter.
EXTENDED_PERF_KEYWORDS = PAPER_PERF_KEYWORDS + [
    "bottleneck",
    "slow",
    "overhead",
    "vectorize",
    "vectorization",
    "allocat",         # allocate, allocation, allocator
    "gc",
    "garbage collect",
    "memoiz",          # memoize, memoization
    "lazy",
    "eager",
    "batch",
    "bulk",
    "regression",      # performance regression
    "time complex",    # time complexity
    "space complex",   # space complexity
]

# Keywords requiring word-boundary matching (avoid FastAPI, breakfast, etc.)
WORD_BOUNDARY_KEYWORDS = [
    "fast",
]

# Case-sensitive verbatim keywords
VERBATIM_KEYWORDS = [
    "PERF",
    "OPTIM",
]

# ─────────────────────────────────────────────────────────────────────────────
# NEGATIVE KEYWORDS — reject PRs matching these regardless of positive signals
# ─────────────────────────────────────────────────────────────────────────────
NEGATIVE_TITLE_KEYWORDS = [
    # CI/automation
    "bump",
    "pin",
    "pre-commit",
    "dependabot",
    "renovate",
    "github actions",
    "ci:",
    "ci(",
    "[ci]",
    # Documentation
    "translation",
    "translate",
    "typo",
    "docs:",
    "doc:",
    "[docs]",
    # Dependency management — NOTE: "deprecat" removed (too broad; perf PRs
    # often deprecate slow paths). Caught instead by content exclusion + Criterion 3.
    # Release automation
    "release:",
    "[release]",
    "changelog",
]

# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSAL FILTER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────


def check_labels(pull: dict, values: list[str]) -> bool:
    """Check if PR has any of the given label values (case-insensitive substring match)."""
    labels = pull.get("labels", [])
    if not labels:
        return False
    label_names = []
    for label in labels:
        if isinstance(label, dict):
            label_names.append(label.get("name", "").lower())
        elif isinstance(label, str):
            label_names.append(label.lower())
    return any(v in label_name for v in values for label_name in label_names)


def remove_markdown_comments(input_str: str) -> str:
    """Remove HTML/Markdown comments from text."""
    return re.sub(r"<!--.*?-->", "", input_str, flags=re.DOTALL)


def has_negative_title_keywords(pull: dict) -> bool:
    """Check if PR title contains negative keywords (likely NOT performance-related)."""
    title_lower = (pull.get("title") or "").lower()
    return any(neg in title_lower for neg in NEGATIVE_TITLE_KEYWORDS)


def filter_base(pull: dict, keywords=None, use_extended: bool = False):
    """
    Universal performance filter. Works for ANY repo without configuration.

    Implements paper Criterion 2:
    1. Reject if title contains negative keywords (CI bumps, docs, etc.)
    2. Accept if PR labels contain performance-related terms
    3. Accept if title/body contains performance keywords
    4. Accept if title/body matches WORD_BOUNDARY_KEYWORDS with \\b
    5. Accept if title/body contains VERBATIM_KEYWORDS (case-sensitive)
    
    Args:
        pull: PR dict with 'title', 'body', 'labels' fields
        keywords: Override keyword list (default: PAPER_PERF_KEYWORDS)
        use_extended: If True, use EXTENDED_PERF_KEYWORDS instead of paper-specified
    """
    if keywords is None:
        keywords = EXTENDED_PERF_KEYWORDS if use_extended else PAPER_PERF_KEYWORDS

    if has_negative_title_keywords(pull):
        return False

    # Check labels (works for any repo that uses perf-related labels)
    common_perf_labels = ["performance", "perf", "optimization", "speed", "benchmark"]
    if check_labels(pull, common_perf_labels):
        return True

    pull_body = pull.get("body") or ""
    pull_title = pull.get("title") or ""

    for item in [pull_body, pull_title]:
        item_lower = remove_markdown_comments(item.lower())

        if any(kw in item_lower for kw in keywords):
            return True

        if any(re.search(r'\b' + re.escape(kw) + r'\b', item_lower) for kw in WORD_BOUNDARY_KEYWORDS):
            return True

        if any(kw in item for kw in VERBATIM_KEYWORDS):
            return True

    return False


def filter_content(issue_text: str, keywords=None, use_extended: bool = False) -> bool:
    """Check if issue/problem statement text contains performance keywords."""
    if not issue_text:
        return False

    if keywords is None:
        keywords = EXTENDED_PERF_KEYWORDS if use_extended else PAPER_PERF_KEYWORDS

    issue_text_lower = remove_markdown_comments(issue_text.lower())
    return any(kw in issue_text_lower for kw in keywords)


# ─────────────────────────────────────────────────────────────────────────────
# REPO-SPECIFIC FILTER OVERRIDES (optional precision for known repos)
# ─────────────────────────────────────────────────────────────────────────────


def _make_label_filter(label_values: list[str], title_keywords: list[str] = None):
    """
    Factory: create a repo-specific filter that checks labels + optional title keywords.
    These are OPTIONAL precision overrides — filter_base handles everything for new repos.
    """
    if title_keywords is None:
        title_keywords = ["perf", "speed", "efficiency", "performance"]

    def _filter(pull: dict) -> bool:
        if has_negative_title_keywords(pull):
            return False
        if check_labels(pull, label_values):
            return True
        pr_title = (pull.get("title") or "").lower()
        if any(kw in pr_title for kw in title_keywords):
            return True
        return False

    return _filter


# Known repo-specific filters
filter_sklearn = _make_label_filter(["performance"])
filter_astropy = _make_label_filter(["performance"], ["eff", "perf", "speed up"])
filter_matplotlib = _make_label_filter(["performance"])
filter_pylint = _make_label_filter(["performance"])
filter_seaborn = _make_label_filter(["perf"])
filter_sphinx = _make_label_filter(["type:performance"])
filter_sympy = _make_label_filter(["performance"])
filter_xarray = _make_label_filter(["topic-performance"], ["perf", "speed up"])
filter_pandas = _make_label_filter(["performance"])
filter_dask = _make_label_filter([], ["perf", "speed up", "efficiency", "remove", "avoid", "overhead", "memory"])
filter_numpy = _make_label_filter([], ["perf", "speed up", "efficiency", "performance"])
filter_statsmodels = _make_label_filter(["performance"])
filter_pillow = _make_label_filter(["performance"], ["perf", "speed", "efficiency", "performance"])
filter_spacy = _make_label_filter(["perf"], ["perf", "speed", "efficiency", "performance"])
filter_numba = _make_label_filter(["performance"], ["perf", "speed", "efficiency", "performance"])
filter_gensim = _make_label_filter(["performance"], ["perf", "speed", "efficiency", "performance"])
filter_scikit_image = _make_label_filter(["performance"], ["perf", "speed", "efficiency", "performance"])

filter_flask = _make_label_filter(
    ["performance", "perf"],
    ["perf", "speed", "efficiency", "performance", "optimize",
     "benchmark", "latency", "throughput", "async", "cache",
     "memory", "profil", "response time", "request handling"],
)
filter_fastapi = _make_label_filter(
    ["performance", "perf"],
    ["perf", "speed", "efficiency", "performance", "optimize",
     "benchmark", "latency", "throughput", "async", "cache",
     "memory", "profil", "response time", "middleware",
     "streaming", "concurren"],
)

# ─────────────────────────────────────────────────────────────────────────────
# FILTER REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

REPO_PERF_FILTERS = {
    "default": filter_base,
    # Scientific Python
    "astropy": filter_astropy,
    "scikit-learn": filter_sklearn,
    "matplotlib": filter_matplotlib,
    "sympy": filter_sympy,
    "xarray": filter_xarray,
    "pandas": filter_pandas,
    "numpy": filter_numpy,
    "scipy": filter_numpy,
    "statsmodels": filter_statsmodels,
    "scikit-image": filter_scikit_image,
    # Web frameworks
    "flask": filter_flask,
    "fastapi": filter_fastapi,
    # ML/NLP
    "spacy": filter_spacy,
    "numba": filter_numba,
    "gensim": filter_gensim,
    "pillow": filter_pillow,
    # Tools
    "pylint": filter_pylint,
    "seaborn": filter_seaborn,
    "sphinx": filter_sphinx,
    "dask": filter_dask,
}
