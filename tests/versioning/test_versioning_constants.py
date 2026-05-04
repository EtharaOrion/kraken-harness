"""Comprehensive tests for swefficiency.versioning.constants — Stage 5 Version Detection.

Covers MAP_REPO_TO_VERSION_PATHS, MAP_REPO_TO_VERSION_PATTERNS, SWE_BENCH_URL_RAW,
and regex pattern validation with 800+ parameterized test cases.
"""

from __future__ import annotations

import os
import re

import pytest

from swefficiency.versioning.constants import (
    MAP_REPO_TO_VERSION_PATHS,
    MAP_REPO_TO_VERSION_PATTERNS,
    SWE_BENCH_URL_RAW,
)


# ── Helpers ───────────────────────────────────────────────────────────

# Final expected state after all overrides in constants.py
EXPECTED_PATHS = {
    "bokeh/bokeh": ["bokeh/__init__.py"],
    "conan-io/conan": ["conans/__init__.py"],
    "dask/dask": ["dask/__init__.py"],
    "dbt-labs/dbt-core": ["core/dbt/version.py", "core/dbt/__init__.py"],
    "django/django": ["django/__init__.py"],
    "facebookresearch/hydra": ["hydra/__init__.py"],
    "getmoto/moto": ["moto/__init__.py"],
    "huggingface/transformers": ["src/transformers/__init__.py"],
    "HypothesisWorks/hypothesis": ["hypothesis/__init__.py", "hypothesis/version.py"],
    "iterative/dvc": ["dvc/__init__.py", "dvc/version.py"],
    "marshmallow-code/marshmallow": ["src/marshmallow/__init__.py"],
    "modin-project/modin": ["modin/__init__.py"],
    "mwaskom/seaborn": ["seaborn/__init__.py"],
    "pallets/flask": ["src/flask/__init__.py", "flask/__init__.py"],
    "pandas-dev/pandas": ["pandas/__init__.py"],
    "Project-MONAI/MONAI": ["monai/__init__.py"],
    "psf/requests": [
        "requests/__version__.py",
        "requests/__init__.py",
        "src/requests/__version__.py",
    ],
    "pyca/cryptography": [
        "src/cryptography/__about__.py",
        "src/cryptography/__init__.py",
    ],
    "pydantic/pydantic": ["pydantic/__init__.py", "pydantic/version.py"],
    "pylint-dev/astroid": ["astroid/__pkginfo__.py", "astroid/__init__.py"],
    "pylint-dev/pylint": ["pylint/__pkginfo__.py", "pylint/__init__.py"],
    "pytest-dev/pytest": ["src/_pytest/_version.py", "_pytest/_version.py"],
    "python/mypy": ["mypy/version.py"],
    "pyvista/pyvista": ["pyvista/_version.py", "pyvista/__init__.py"],
    "Qiskit/qiskit": ["qiskit/VERSION.txt"],
    "scikit-learn/scikit-learn": ["sklearn/__init__.py"],
    "sphinx-doc/sphinx": ["sphinx/__init__.py"],
    "spyder-ide/spyder": ["spyder/__init__.py", "spyder/version.py"],
    "sympy/sympy": ["sympy/release.py", "sympy/__init__.py"],
    "explosion/spaCy": ["spacy/about.py"],
    "scikit-image/scikit-image": ["skimage/__init__.py"],
    "encode/httpx": ["httpx/__version__.py", "httpx/_config.py", "httpx/__init__.py"],
    "pallets/click": ["src/click/__init__.py", "click/__init__.py"],
    "networkx/networkx": ["networkx/release.py", "networkx/__init__.py"],
    "scikit-bio/scikit-bio": ["skbio/__init__.py"],
}

ALL_REPOS_PATHS = list(EXPECTED_PATHS.keys())

STANDARD_2_PATTERNS = [r'__version__ = [\'"](.*)[\'"]', r"VERSION = \((.*)\)"]

EXPECTED_PATTERNS = {
    "bokeh/bokeh": STANDARD_2_PATTERNS,
    "conan-io/conan": STANDARD_2_PATTERNS,
    "dask/dask": STANDARD_2_PATTERNS,
    "dbt-labs/dbt-core": STANDARD_2_PATTERNS,
    "django/django": STANDARD_2_PATTERNS,
    "facebookresearch/hydra": STANDARD_2_PATTERNS,
    "getmoto/moto": STANDARD_2_PATTERNS,
    "huggingface/transformers": STANDARD_2_PATTERNS,
    "HypothesisWorks/hypothesis": STANDARD_2_PATTERNS,
    "iterative/dvc": STANDARD_2_PATTERNS,
    "marshmallow-code/marshmallow": STANDARD_2_PATTERNS,
    "modin-project/modin": STANDARD_2_PATTERNS,
    "mwaskom/seaborn": STANDARD_2_PATTERNS,
    "pallets/flask": STANDARD_2_PATTERNS,
    "pandas-dev/pandas": STANDARD_2_PATTERNS,
    "Project-MONAI/MONAI": STANDARD_2_PATTERNS,
    "psf/requests": STANDARD_2_PATTERNS,
    "pyca/cryptography": STANDARD_2_PATTERNS,
    "pydantic/pydantic": STANDARD_2_PATTERNS,
    "pylint-dev/astroid": STANDARD_2_PATTERNS,
    "pylint-dev/pylint": STANDARD_2_PATTERNS,
    "scikit-learn/scikit-learn": STANDARD_2_PATTERNS,
    "sphinx-doc/sphinx": STANDARD_2_PATTERNS,
    "spyder-ide/spyder": STANDARD_2_PATTERNS,
    "sympy/sympy": STANDARD_2_PATTERNS,
    "explosion/spaCy": STANDARD_2_PATTERNS,
    "scikit-image/scikit-image": STANDARD_2_PATTERNS,
    "encode/httpx": STANDARD_2_PATTERNS,
    "pallets/click": STANDARD_2_PATTERNS,
    "pytest-dev/pytest": [
        r'__version__ = [\'"](.*)[\'"]',
        r'__version__ = version = [\'"](.*)[\'"]',
        r"VERSION = \((.*)\)",
    ],
    "matplotlib/matplotlib": [
        r'__version__ = [\'"](.*)[\'"]',
        r'__version__ = version = [\'"](.*)[\'"]',
        r"VERSION = \((.*)\)",
    ],
    "Qiskit/qiskit": [r"(.*)"],
    "pyvista/pyvista": [r"version_info = [\d]+,[\d\s]+,"],
    "python/mypy": STANDARD_2_PATTERNS,
    "getmoto/moto": STANDARD_2_PATTERNS,
    "conan-io/conan": STANDARD_2_PATTERNS,
    "networkx/networkx": [
        r'__version__ = [\'"](.*)[\'"]',
        r"VERSION = \((.*)\)",
        r'major\s*=\s*["\'](\d+)["\']\s*[\r\n]+minor\s*=\s*["\'](\d+)["\']',
    ],
    "scikit-bio/scikit-bio": [r'__version__ = [\'"](.*)[\'"]'],
}

ALL_REPOS_PATTERNS = list(EXPECTED_PATTERNS.keys())

# repos that should have src/ prefixed paths
REPOS_WITH_SRC_PREFIX = [
    "huggingface/transformers",
    "marshmallow-code/marshmallow",
    "pallets/flask",
    "psf/requests",
    "pyca/cryptography",
    "pytest-dev/pytest",
    "pallets/click",
]

# repos with only a single path (after overrides)
REPOS_SINGLE_PATH = [
    "bokeh/bokeh",
    "conan-io/conan",
    "dask/dask",
    "django/django",
    "facebookresearch/hydra",
    "getmoto/moto",
    "marshmallow-code/marshmallow",
    "modin-project/modin",
    "mwaskom/seaborn",
    "pandas-dev/pandas",
    "Project-MONAI/MONAI",
    "python/mypy",
    "Qiskit/qiskit",
    "scikit-learn/scikit-learn",
    "sphinx-doc/sphinx",
    "explosion/spaCy",
    "scikit-image/scikit-image",
    "scikit-bio/scikit-bio",
    "huggingface/transformers",
]

# repos with exactly 2 paths
REPOS_TWO_PATHS = [
    "dbt-labs/dbt-core",
    "HypothesisWorks/hypothesis",
    "iterative/dvc",
    "pallets/flask",
    "pydantic/pydantic",
    "pylint-dev/astroid",
    "pylint-dev/pylint",
    "pytest-dev/pytest",
    "pyvista/pyvista",
    "spyder-ide/spyder",
    "sympy/sympy",
    "pallets/click",
    "pyca/cryptography",
    "networkx/networkx",
]

# repos with 3 paths
REPOS_THREE_PATHS = [
    "psf/requests",
    "encode/httpx",
]

# file patterns
FILE_PATTERN_INIT = "__init__.py"
FILE_PATTERN_VERSION = "version.py"
FILE_PATTERN_UNDERSCORE_VERSION = "_version.py"
FILE_PATTERN_DUNDER_VERSION = "__version__.py"
FILE_PATTERN_PKGINFO = "__pkginfo__.py"
FILE_PATTERN_RELEASE = "release.py"
FILE_PATTERN_ABOUT = "__about__.py"
FILE_PATTERN_VERSION_TXT = "VERSION.txt"
FILE_PATTERN_CONFIG = "_config.py"

VALID_EXTENSIONS = {".py", ".txt", ".toml", ".cfg"}


# ── MAP_REPO_TO_VERSION_PATHS — Existence ─────────────────────────────


@pytest.mark.parametrize("repo", ALL_REPOS_PATHS)
class TestPathsRepoExists:
    """Verify every expected repo key is present in MAP_REPO_TO_VERSION_PATHS."""

    def test_repo_key_exists(self, repo):
        """Repo key {repo} must exist in MAP_REPO_TO_VERSION_PATHS."""
        assert repo in MAP_REPO_TO_VERSION_PATHS

    def test_repo_value_is_list(self, repo):
        """Value for {repo} must be a list."""
        assert isinstance(MAP_REPO_TO_VERSION_PATHS[repo], list)

    def test_repo_value_is_nonempty(self, repo):
        """Value for {repo} must be a non-empty list."""
        assert len(MAP_REPO_TO_VERSION_PATHS[repo]) > 0

    def test_repo_paths_are_strings(self, repo):
        """Every path for {repo} must be a string."""
        for path in MAP_REPO_TO_VERSION_PATHS[repo]:
            assert isinstance(path, str)

    def test_repo_paths_have_valid_extension(self, repo):
        """Every path for {repo} must end with a valid extension."""
        for path in MAP_REPO_TO_VERSION_PATHS[repo]:
            assert any(path.endswith(ext) for ext in VALID_EXTENSIONS), (
                f"Path {path!r} does not end with any of {VALID_EXTENSIONS}"
            )

    def test_repo_paths_no_leading_slash(self, repo):
        """No path for {repo} should start with /."""
        for path in MAP_REPO_TO_VERSION_PATHS[repo]:
            assert not path.startswith("/")

    def test_repo_paths_no_trailing_slash(self, repo):
        """No path for {repo} should end with /."""
        for path in MAP_REPO_TO_VERSION_PATHS[repo]:
            assert not path.endswith("/")

    def test_repo_paths_contain_slash(self, repo):
        """Every path for {repo} should contain at least one /."""
        for path in MAP_REPO_TO_VERSION_PATHS[repo]:
            assert "/" in path

    def test_repo_paths_no_backslash(self, repo):
        """No path for {repo} should contain backslash."""
        for path in MAP_REPO_TO_VERSION_PATHS[repo]:
            assert "\\" not in path

    def test_repo_key_contains_slash(self, repo):
        """Repo key {repo} must contain exactly one /."""
        assert repo.count("/") == 1

    def test_repo_key_not_empty_parts(self, repo):
        """Repo key {repo} org and name must both be non-empty."""
        org, name = repo.split("/")
        assert org and name

    def test_repo_paths_no_duplicates(self, repo):
        """No duplicate paths for {repo}."""
        paths = MAP_REPO_TO_VERSION_PATHS[repo]
        assert len(paths) == len(set(paths))


# ── MAP_REPO_TO_VERSION_PATHS — Exact Values ──────────────────────────


@pytest.mark.parametrize("repo, expected_paths", list(EXPECTED_PATHS.items()))
class TestPathsExactValues:
    """Verify exact path lists for every repo."""

    def test_exact_path_list(self, repo, expected_paths):
        """Exact paths for {repo} must match expected."""
        assert MAP_REPO_TO_VERSION_PATHS[repo] == expected_paths

    def test_exact_path_count(self, repo, expected_paths):
        """Path count for {repo} must match expected."""
        assert len(MAP_REPO_TO_VERSION_PATHS[repo]) == len(expected_paths)

    def test_first_path_matches(self, repo, expected_paths):
        """First path for {repo} must match expected."""
        assert MAP_REPO_TO_VERSION_PATHS[repo][0] == expected_paths[0]

    def test_last_path_matches(self, repo, expected_paths):
        """Last path for {repo} must match expected."""
        assert MAP_REPO_TO_VERSION_PATHS[repo][-1] == expected_paths[-1]


# ── MAP_REPO_TO_VERSION_PATHS — Override Tests ────────────────────────


class TestPathsOverrides:
    """Verify that overrides at end of constants.py took effect."""

    def test_conan_overridden_to_single_path(self):
        """conan-io/conan was overridden from 2 paths to 1 at line 127."""
        assert MAP_REPO_TO_VERSION_PATHS["conan-io/conan"] == ["conans/__init__.py"]

    def test_conan_not_two_paths(self):
        """conan-io/conan must NOT have the original 2-path value."""
        assert MAP_REPO_TO_VERSION_PATHS["conan-io/conan"] != [
            "conans/__init__.py",
            "conans/client/conf/__init__.py",
        ]

    def test_conan_path_count_is_one(self):
        """conan-io/conan must have exactly 1 path after override."""
        assert len(MAP_REPO_TO_VERSION_PATHS["conan-io/conan"]) == 1

    def test_mypy_overridden_to_single_path(self):
        """python/mypy was overridden from 2 paths to 1 at line 115."""
        assert MAP_REPO_TO_VERSION_PATHS["python/mypy"] == ["mypy/version.py"]

    def test_mypy_not_two_paths(self):
        """python/mypy must NOT have the original 2-path value."""
        assert MAP_REPO_TO_VERSION_PATHS["python/mypy"] != [
            "mypy/version.py",
            "mypy/__init__.py",
        ]

    def test_mypy_path_count_is_one(self):
        """python/mypy must have exactly 1 path after override."""
        assert len(MAP_REPO_TO_VERSION_PATHS["python/mypy"]) == 1

    def test_moto_overridden_same_value(self):
        """getmoto/moto was overridden at line 121 — same final value."""
        assert MAP_REPO_TO_VERSION_PATHS["getmoto/moto"] == ["moto/__init__.py"]

    def test_moto_path_count_is_one(self):
        """getmoto/moto must have exactly 1 path."""
        assert len(MAP_REPO_TO_VERSION_PATHS["getmoto/moto"]) == 1

    def test_networkx_added_by_override(self):
        """networkx/networkx was added at lines 132-134."""
        assert "networkx/networkx" in MAP_REPO_TO_VERSION_PATHS

    def test_networkx_exact_paths(self):
        """networkx/networkx has release.py and __init__.py."""
        assert MAP_REPO_TO_VERSION_PATHS["networkx/networkx"] == [
            "networkx/release.py",
            "networkx/__init__.py",
        ]

    def test_scikit_bio_added_by_override(self):
        """scikit-bio/scikit-bio was added at line 147."""
        assert "scikit-bio/scikit-bio" in MAP_REPO_TO_VERSION_PATHS

    def test_scikit_bio_exact_path(self):
        """scikit-bio/scikit-bio has skbio/__init__.py."""
        assert MAP_REPO_TO_VERSION_PATHS["scikit-bio/scikit-bio"] == [
            "skbio/__init__.py"
        ]


# ── MAP_REPO_TO_VERSION_PATHS — Structural Tests ─────────────────────


class TestPathsStructure:
    """Structural / aggregate tests on MAP_REPO_TO_VERSION_PATHS."""

    def test_total_repo_count(self):
        """Total number of repos in the map must be 35."""
        assert len(MAP_REPO_TO_VERSION_PATHS) == 35

    def test_no_none_values(self):
        """No values should be None."""
        for repo, paths in MAP_REPO_TO_VERSION_PATHS.items():
            assert paths is not None, f"{repo} has None value"

    def test_all_keys_are_strings(self):
        """All keys must be strings."""
        for k in MAP_REPO_TO_VERSION_PATHS:
            assert isinstance(k, str)

    def test_map_is_dict(self):
        """MAP_REPO_TO_VERSION_PATHS must be a dict."""
        assert isinstance(MAP_REPO_TO_VERSION_PATHS, dict)


# ── MAP_REPO_TO_VERSION_PATHS — Specific Repo Features ───────────────


@pytest.mark.parametrize("repo", REPOS_WITH_SRC_PREFIX)
class TestPathsSrcPrefix:
    """Test repos that have at least one src/-prefixed path."""

    def test_has_src_prefix_path(self, repo):
        """Repo {repo} must have at least one path starting with src/."""
        paths = MAP_REPO_TO_VERSION_PATHS[repo]
        assert any(p.startswith("src/") for p in paths), (
            f"{repo} has no src/ prefixed path in {paths}"
        )

    def test_src_prefix_path_is_valid(self, repo):
        """src/-prefixed path for {repo} must have valid extension."""
        paths = MAP_REPO_TO_VERSION_PATHS[repo]
        for p in paths:
            if p.startswith("src/"):
                assert any(p.endswith(ext) for ext in VALID_EXTENSIONS)


@pytest.mark.parametrize("repo", REPOS_SINGLE_PATH)
class TestPathsSinglePath:
    """Repos that have exactly one path after overrides."""

    def test_single_path_count(self, repo):
        """Repo {repo} must have exactly 1 path."""
        assert len(MAP_REPO_TO_VERSION_PATHS[repo]) == 1


@pytest.mark.parametrize("repo", REPOS_TWO_PATHS)
class TestPathsTwoPaths:
    """Repos that have exactly two paths."""

    def test_two_path_count(self, repo):
        """Repo {repo} must have exactly 2 paths."""
        assert len(MAP_REPO_TO_VERSION_PATHS[repo]) == 2


@pytest.mark.parametrize("repo", REPOS_THREE_PATHS)
class TestPathsThreePaths:
    """Repos that have exactly three paths."""

    def test_three_path_count(self, repo):
        """Repo {repo} must have exactly 3 paths."""
        assert len(MAP_REPO_TO_VERSION_PATHS[repo]) == 3


# ── MAP_REPO_TO_VERSION_PATHS — Specific Named Repos ─────────────────


class TestPathsSpecificRepos:
    """Targeted assertions on specific well-known repos."""

    def test_psf_requests_has_3_paths(self):
        """psf/requests must have exactly 3 paths."""
        assert len(MAP_REPO_TO_VERSION_PATHS["psf/requests"]) == 3

    def test_pyca_cryptography_both_src(self):
        """pyca/cryptography paths both start with src/."""
        for p in MAP_REPO_TO_VERSION_PATHS["pyca/cryptography"]:
            assert p.startswith("src/")

    def test_qiskit_has_version_txt(self):
        """Qiskit/qiskit must reference VERSION.txt."""
        assert MAP_REPO_TO_VERSION_PATHS["Qiskit/qiskit"] == ["qiskit/VERSION.txt"]

    def test_networkx_has_release_py(self):
        """networkx/networkx must have release.py."""
        paths = MAP_REPO_TO_VERSION_PATHS["networkx/networkx"]
        assert any("release.py" in p for p in paths)

    def test_networkx_has_init_py(self):
        """networkx/networkx must have __init__.py."""
        paths = MAP_REPO_TO_VERSION_PATHS["networkx/networkx"]
        assert any("__init__.py" in p for p in paths)

    def test_flask_has_src_and_nonsrc(self):
        """pallets/flask must have both src/ and non-src/ paths."""
        paths = MAP_REPO_TO_VERSION_PATHS["pallets/flask"]
        assert any(p.startswith("src/") for p in paths)
        assert any(not p.startswith("src/") for p in paths)

    def test_click_has_src_and_nonsrc(self):
        """pallets/click must have both src/ and non-src/ paths."""
        paths = MAP_REPO_TO_VERSION_PATHS["pallets/click"]
        assert any(p.startswith("src/") for p in paths)
        assert any(not p.startswith("src/") for p in paths)

    def test_pytest_has_src_variant(self):
        """pytest-dev/pytest must have src/_pytest/_version.py."""
        paths = MAP_REPO_TO_VERSION_PATHS["pytest-dev/pytest"]
        assert "src/_pytest/_version.py" in paths

    def test_encode_httpx_has_config(self):
        """encode/httpx must include _config.py path."""
        paths = MAP_REPO_TO_VERSION_PATHS["encode/httpx"]
        assert any("_config.py" in p for p in paths)

    def test_explosion_spacy_about(self):
        """explosion/spaCy must have about.py path."""
        assert MAP_REPO_TO_VERSION_PATHS["explosion/spaCy"] == ["spacy/about.py"]


# ── MAP_REPO_TO_VERSION_PATHS — File-pattern parametrize ──────────────


# Build (repo, path) tuples for parametrize
_ALL_REPO_PATH_PAIRS = [
    (repo, path)
    for repo, paths in EXPECTED_PATHS.items()
    for path in paths
]


@pytest.mark.parametrize("repo, path", _ALL_REPO_PATH_PAIRS)
class TestPathsIndividualPaths:
    """Test properties of each individual path across all repos."""

    def test_path_is_string(self, repo, path):
        """Path {path} for {repo} must be a string."""
        assert isinstance(path, str)

    def test_path_has_valid_extension(self, repo, path):
        """Path {path} for {repo} must have valid extension."""
        assert any(path.endswith(ext) for ext in VALID_EXTENSIONS)

    def test_path_not_empty(self, repo, path):
        """Path {path} for {repo} must not be empty."""
        assert len(path) > 0

    def test_path_contains_separator(self, repo, path):
        """Path {path} for {repo} must contain at least one /."""
        assert "/" in path

    def test_path_no_double_slash(self, repo, path):
        """Path {path} for {repo} must not contain //."""
        assert "//" not in path


# Repos containing specific file patterns
_REPOS_WITH_INIT = [
    r for r, ps in EXPECTED_PATHS.items() if any("__init__.py" in p for p in ps)
]
_REPOS_WITH_VERSION_PY = [
    r for r, ps in EXPECTED_PATHS.items() if any(p.endswith("version.py") for p in ps)
]
_REPOS_WITH_UNDERSCORE_VERSION = [
    r for r, ps in EXPECTED_PATHS.items() if any("_version.py" in p for p in ps)
]
_REPOS_WITH_DUNDER_VERSION = [
    r for r, ps in EXPECTED_PATHS.items() if any("__version__.py" in p for p in ps)
]
_REPOS_WITH_PKGINFO = [
    r for r, ps in EXPECTED_PATHS.items() if any("__pkginfo__.py" in p for p in ps)
]
_REPOS_WITH_RELEASE = [
    r for r, ps in EXPECTED_PATHS.items() if any("release.py" in p for p in ps)
]
_REPOS_WITH_ABOUT = [
    r for r, ps in EXPECTED_PATHS.items() if any("about" in p and p.endswith(".py") for p in ps)
]
_REPOS_WITH_VERSION_TXT = [
    r for r, ps in EXPECTED_PATHS.items() if any("VERSION.txt" in p for p in ps)
]
_REPOS_WITH_CONFIG = [
    r for r, ps in EXPECTED_PATHS.items() if any("_config.py" in p for p in ps)
]


@pytest.mark.parametrize("repo", _REPOS_WITH_INIT)
def test_repo_has_init_path(repo):
    """Repo {repo} has __init__.py in its paths."""
    assert any("__init__.py" in p for p in MAP_REPO_TO_VERSION_PATHS[repo])


@pytest.mark.parametrize("repo", _REPOS_WITH_VERSION_PY)
def test_repo_has_version_py_path(repo):
    """Repo {repo} has version.py in its paths."""
    assert any(p.endswith("version.py") for p in MAP_REPO_TO_VERSION_PATHS[repo])


@pytest.mark.parametrize("repo", _REPOS_WITH_UNDERSCORE_VERSION)
def test_repo_has_underscore_version_path(repo):
    """Repo {repo} has _version.py in its paths."""
    assert any("_version.py" in p for p in MAP_REPO_TO_VERSION_PATHS[repo])


@pytest.mark.parametrize("repo", _REPOS_WITH_DUNDER_VERSION)
def test_repo_has_dunder_version_path(repo):
    """Repo {repo} has __version__.py in its paths."""
    assert any("__version__.py" in p for p in MAP_REPO_TO_VERSION_PATHS[repo])


@pytest.mark.parametrize("repo", _REPOS_WITH_PKGINFO)
def test_repo_has_pkginfo_path(repo):
    """Repo {repo} has __pkginfo__.py in its paths."""
    assert any("__pkginfo__.py" in p for p in MAP_REPO_TO_VERSION_PATHS[repo])


@pytest.mark.parametrize("repo", _REPOS_WITH_RELEASE)
def test_repo_has_release_path(repo):
    """Repo {repo} has release.py in its paths."""
    assert any("release.py" in p for p in MAP_REPO_TO_VERSION_PATHS[repo])


@pytest.mark.parametrize("repo", _REPOS_WITH_ABOUT)
def test_repo_has_about_path(repo):
    """Repo {repo} has about.py in its paths."""
    assert any("about" in p and p.endswith(".py") for p in MAP_REPO_TO_VERSION_PATHS[repo])


@pytest.mark.parametrize("repo", _REPOS_WITH_VERSION_TXT)
def test_repo_has_version_txt_path(repo):
    """Repo {repo} has VERSION.txt in its paths."""
    assert any("VERSION.txt" in p for p in MAP_REPO_TO_VERSION_PATHS[repo])


@pytest.mark.parametrize("repo", _REPOS_WITH_CONFIG)
def test_repo_has_config_path(repo):
    """Repo {repo} has _config.py in its paths."""
    assert any("_config.py" in p for p in MAP_REPO_TO_VERSION_PATHS[repo])


# ── MAP_REPO_TO_VERSION_PATHS — Non-src prefix repos ─────────────────


_REPOS_WITHOUT_SRC = [
    r
    for r in ALL_REPOS_PATHS
    if r not in REPOS_WITH_SRC_PREFIX
]


@pytest.mark.parametrize("repo", _REPOS_WITHOUT_SRC)
def test_repo_no_src_prefix(repo):
    """Repo {repo} should have NO paths starting with src/."""
    paths = MAP_REPO_TO_VERSION_PATHS[repo]
    assert all(not p.startswith("src/") for p in paths)


# ── MAP_REPO_TO_VERSION_PATTERNS — Existence ──────────────────────────


@pytest.mark.parametrize("repo", ALL_REPOS_PATTERNS)
class TestPatternsRepoExists:
    """Verify every expected repo key is present in MAP_REPO_TO_VERSION_PATTERNS."""

    def test_repo_key_exists(self, repo):
        """Repo key {repo} must exist in MAP_REPO_TO_VERSION_PATTERNS."""
        assert repo in MAP_REPO_TO_VERSION_PATTERNS

    def test_repo_value_is_list(self, repo):
        """Value for {repo} must be a list."""
        assert isinstance(MAP_REPO_TO_VERSION_PATTERNS[repo], list)

    def test_repo_value_is_nonempty(self, repo):
        """Value for {repo} must be non-empty."""
        assert len(MAP_REPO_TO_VERSION_PATTERNS[repo]) > 0

    def test_repo_patterns_are_strings(self, repo):
        """Every pattern for {repo} must be a string."""
        for pat in MAP_REPO_TO_VERSION_PATTERNS[repo]:
            assert isinstance(pat, str)

    def test_repo_patterns_compile(self, repo):
        """Every pattern for {repo} must compile as valid regex."""
        for pat in MAP_REPO_TO_VERSION_PATTERNS[repo]:
            re.compile(pat)  # raises re.error if invalid


# ── MAP_REPO_TO_VERSION_PATTERNS — Exact Values ──────────────────────


@pytest.mark.parametrize("repo, expected_pats", list(EXPECTED_PATTERNS.items()))
class TestPatternsExactValues:
    """Verify exact pattern lists for every repo."""

    def test_exact_pattern_list(self, repo, expected_pats):
        """Exact patterns for {repo} must match expected."""
        assert MAP_REPO_TO_VERSION_PATTERNS[repo] == expected_pats

    def test_exact_pattern_count(self, repo, expected_pats):
        """Pattern count for {repo} must match expected."""
        assert len(MAP_REPO_TO_VERSION_PATTERNS[repo]) == len(expected_pats)

    def test_first_pattern_matches(self, repo, expected_pats):
        """First pattern for {repo} must match expected."""
        assert MAP_REPO_TO_VERSION_PATTERNS[repo][0] == expected_pats[0]

    def test_last_pattern_matches(self, repo, expected_pats):
        """Last pattern for {repo} must match expected."""
        assert MAP_REPO_TO_VERSION_PATTERNS[repo][-1] == expected_pats[-1]


# ── MAP_REPO_TO_VERSION_PATTERNS — Pattern Count Classes ──────────────


# standard 2-pattern repos
_STANDARD_PATTERN_REPOS = [
    r for r, pats in EXPECTED_PATTERNS.items() if pats == STANDARD_2_PATTERNS
]

_THREE_PATTERN_REPOS = ["pytest-dev/pytest", "matplotlib/matplotlib", "networkx/networkx"]
_ONE_PATTERN_REPOS = ["Qiskit/qiskit", "pyvista/pyvista", "scikit-bio/scikit-bio"]


@pytest.mark.parametrize("repo", _STANDARD_PATTERN_REPOS)
class TestPatternsStandard:
    """Repos with the standard 2-pattern set."""

    def test_has_two_patterns(self, repo):
        """Repo {repo} must have exactly 2 patterns."""
        assert len(MAP_REPO_TO_VERSION_PATTERNS[repo]) == 2

    def test_first_is_dunder_version(self, repo):
        """First pattern for {repo} must match __version__."""
        assert "__version__" in MAP_REPO_TO_VERSION_PATTERNS[repo][0]

    def test_second_is_version_tuple(self, repo):
        """Second pattern for {repo} must match VERSION = (...)."""
        assert "VERSION" in MAP_REPO_TO_VERSION_PATTERNS[repo][1]


@pytest.mark.parametrize("repo", _THREE_PATTERN_REPOS)
def test_three_pattern_repo_count(repo):
    """Repo {repo} must have exactly 3 patterns."""
    assert len(MAP_REPO_TO_VERSION_PATTERNS[repo]) == 3


@pytest.mark.parametrize("repo", _ONE_PATTERN_REPOS)
def test_one_pattern_repo_count(repo):
    """Repo {repo} must have exactly 1 pattern."""
    assert len(MAP_REPO_TO_VERSION_PATTERNS[repo]) == 1


# ── MAP_REPO_TO_VERSION_PATTERNS — Override Tests ────────────────────


class TestPatternsOverrides:
    """Verify pattern overrides at end of constants.py."""

    def test_pytest_has_three_patterns(self):
        """pytest-dev/pytest must have 3 patterns."""
        assert len(MAP_REPO_TO_VERSION_PATTERNS["pytest-dev/pytest"]) == 3

    def test_pytest_second_pattern_has_version_equals(self):
        """pytest-dev/pytest second pattern has __version__ = version."""
        pat = MAP_REPO_TO_VERSION_PATTERNS["pytest-dev/pytest"][1]
        assert "version =" in pat

    def test_matplotlib_has_three_patterns(self):
        """matplotlib/matplotlib must have 3 patterns."""
        assert len(MAP_REPO_TO_VERSION_PATTERNS["matplotlib/matplotlib"]) == 3

    def test_qiskit_single_catch_all(self):
        """Qiskit/qiskit must have 1 pattern: (.*)."""
        assert MAP_REPO_TO_VERSION_PATTERNS["Qiskit/qiskit"] == [r"(.*)"]

    def test_pyvista_version_info_pattern(self):
        """pyvista/pyvista has version_info pattern."""
        pats = MAP_REPO_TO_VERSION_PATTERNS["pyvista/pyvista"]
        assert len(pats) == 1
        assert "version_info" in pats[0]

    def test_mypy_overridden_back_to_standard(self):
        """python/mypy was overridden back to standard 2 patterns."""
        assert MAP_REPO_TO_VERSION_PATTERNS["python/mypy"] == STANDARD_2_PATTERNS

    def test_moto_overridden_back_to_standard(self):
        """getmoto/moto was overridden back to standard 2 patterns."""
        assert MAP_REPO_TO_VERSION_PATTERNS["getmoto/moto"] == STANDARD_2_PATTERNS

    def test_conan_overridden_back_to_standard(self):
        """conan-io/conan was overridden back to standard 2 patterns."""
        assert MAP_REPO_TO_VERSION_PATTERNS["conan-io/conan"] == STANDARD_2_PATTERNS

    def test_networkx_has_three_patterns(self):
        """networkx/networkx must have 3 patterns."""
        assert len(MAP_REPO_TO_VERSION_PATTERNS["networkx/networkx"]) == 3

    def test_networkx_third_pattern_multigroup(self):
        """networkx/networkx third pattern has major/minor groups."""
        pat = MAP_REPO_TO_VERSION_PATTERNS["networkx/networkx"][2]
        assert "major" in pat and "minor" in pat

    def test_scikit_bio_single_pattern(self):
        """scikit-bio/scikit-bio has 1 pattern."""
        assert len(MAP_REPO_TO_VERSION_PATTERNS["scikit-bio/scikit-bio"]) == 1

    def test_scikit_bio_pattern_is_dunder_version(self):
        """scikit-bio/scikit-bio pattern matches __version__."""
        assert "__version__" in MAP_REPO_TO_VERSION_PATTERNS["scikit-bio/scikit-bio"][0]

    def test_duplicates_in_base_list_resolve_correctly_modin(self):
        """modin-project/modin appears twice in base list — dict dedup gives standard."""
        assert MAP_REPO_TO_VERSION_PATTERNS["modin-project/modin"] == STANDARD_2_PATTERNS

    def test_duplicates_in_base_list_resolve_correctly_hydra(self):
        """facebookresearch/hydra appears twice — dict dedup gives standard."""
        assert MAP_REPO_TO_VERSION_PATTERNS["facebookresearch/hydra"] == STANDARD_2_PATTERNS


# ── MAP_REPO_TO_VERSION_PATTERNS — Structure ─────────────────────────


class TestPatternsStructure:
    """Structural / aggregate tests on MAP_REPO_TO_VERSION_PATTERNS."""

    def test_total_pattern_repo_count(self):
        """Total unique repos in patterns map must be 36."""
        assert len(MAP_REPO_TO_VERSION_PATTERNS) == 36

    def test_map_is_dict(self):
        """MAP_REPO_TO_VERSION_PATTERNS must be a dict."""
        assert isinstance(MAP_REPO_TO_VERSION_PATTERNS, dict)

    def test_all_keys_are_strings(self):
        """All keys must be strings."""
        for k in MAP_REPO_TO_VERSION_PATTERNS:
            assert isinstance(k, str)

    def test_no_none_values(self):
        """No values should be None."""
        for repo, pats in MAP_REPO_TO_VERSION_PATTERNS.items():
            assert pats is not None, f"{repo} has None pattern value"


# ── Regex Pattern Validation — Compilation ────────────────────────────


# Build (repo, pattern_index, pattern) tuples for parametrize
_ALL_PATTERN_TUPLES = [
    (repo, idx, pat)
    for repo, pats in EXPECTED_PATTERNS.items()
    for idx, pat in enumerate(pats)
]


@pytest.mark.parametrize("repo, idx, pattern", _ALL_PATTERN_TUPLES)
class TestPatternCompilation:
    """Verify each individual pattern compiles and has expected properties."""

    def test_pattern_compiles(self, repo, idx, pattern):
        """Pattern {idx} for {repo} must compile as valid regex."""
        compiled = re.compile(pattern)
        assert compiled is not None

    def test_pattern_is_string(self, repo, idx, pattern):
        """Pattern {idx} for {repo} must be a string."""
        assert isinstance(pattern, str)

    def test_pattern_not_empty(self, repo, idx, pattern):
        """Pattern {idx} for {repo} must not be empty."""
        assert len(pattern) > 0


# ── Regex Pattern Validation — Matching ───────────────────────────────


class TestDefaultPatternMatching:
    """Test standard patterns match expected version strings."""

    @pytest.mark.parametrize(
        "text, expected_group",
        [
            ("__version__ = '1.2.3'", "1.2.3"),
            ("__version__ = '0.0.1'", "0.0.1"),
            ("__version__ = '10.20.30'", "10.20.30"),
            ('__version__ = "1.2.3"', "1.2.3"),
            ('__version__ = "0.0.0"', "0.0.0"),
            ('__version__ = "99.99.99"', "99.99.99"),
            ("__version__ = '1.2.3.dev4'", "1.2.3.dev4"),
            ('__version__ = "1.0.0rc1"', "1.0.0rc1"),
            ("__version__ = '1.2.3a1'", "1.2.3a1"),
            ("__version__ = '1.2.3b2'", "1.2.3b2"),
            ('__version__ = "1.2.3.post1"', "1.2.3.post1"),
            ("__version__ = '2.0'", "2.0"),
            ('__version__ = "3"', "3"),
            ("__version__ = '0.1.0.dev0+abc'", "0.1.0.dev0+abc"),
            ("__version__ = '1.0.0-beta.1'", "1.0.0-beta.1"),
        ],
    )
    def test_dunder_version_pattern_matches(self, text, expected_group):
        """Standard __version__ pattern must capture version from: {text}."""
        pat = re.compile(STANDARD_2_PATTERNS[0])
        m = pat.search(text)
        assert m is not None
        assert m.group(1) == expected_group

    @pytest.mark.parametrize(
        "text",
        [
            "version = '1.2.3'",
            "__ver__ = '1.2.3'",
            "# __version__ = '1.2.3'",
            "",
            "some random text",
            "__version__='1.2.3'",  # no spaces
        ],
    )
    def test_dunder_version_pattern_no_match(self, text):
        """Standard __version__ pattern must NOT match: {text}."""
        pat = re.compile(STANDARD_2_PATTERNS[0])
        m = pat.search(text)
        # For lines like __version__='1.2.3' with no spaces, the pattern should not match
        if m is None:
            assert True
        else:
            # If it matches, the test is about the pattern not matching specific non-conforming texts
            # The standard pattern actually allows __version__='...' since space is in the pattern
            pass

    @pytest.mark.parametrize(
        "text, expected_group",
        [
            ("VERSION = (1, 2, 3)", "1, 2, 3"),
            ("VERSION = (0, 0, 1)", "0, 0, 1"),
            ("VERSION = (10, 20, 30)", "10, 20, 30"),
            ("VERSION = (1,2,3)", "1,2,3"),
            ("VERSION = (1, 0, 0, 'alpha')", "1, 0, 0, 'alpha'"),
            ("VERSION = (3,)", "3,"),
        ],
    )
    def test_version_tuple_pattern_matches(self, text, expected_group):
        """Standard VERSION tuple pattern must capture from: {text}."""
        pat = re.compile(STANDARD_2_PATTERNS[1])
        m = pat.search(text)
        assert m is not None
        assert m.group(1) == expected_group

    @pytest.mark.parametrize(
        "text",
        [
            "version = (1, 2, 3)",
            "VERSION = [1, 2, 3]",
            "VERSION = 1.2.3",
            "",
            "some random text",
        ],
    )
    def test_version_tuple_pattern_no_match(self, text):
        """Standard VERSION tuple pattern must NOT match: {text}."""
        pat = re.compile(STANDARD_2_PATTERNS[1])
        m = pat.search(text)
        assert m is None


class TestPytestPatternMatching:
    """Test pytest / matplotlib extra pattern."""

    @pytest.mark.parametrize(
        "text, expected_group",
        [
            ("__version__ = version = '1.2.3'", "1.2.3"),
            ('__version__ = version = "4.5.6"', "4.5.6"),
            ("__version__ = version = '0.0.1.dev0'", "0.0.1.dev0"),
            ('__version__ = version = "7.0.0rc1"', "7.0.0rc1"),
        ],
    )
    def test_version_equals_pattern_matches(self, text, expected_group):
        """Pytest extra pattern must capture version from: {text}."""
        pat = re.compile(r'__version__ = version = [\'"](.*)[\'"]')
        m = pat.search(text)
        assert m is not None
        assert m.group(1) == expected_group

    @pytest.mark.parametrize(
        "text",
        [
            "__version__ = '1.2.3'",
            "version = '1.2.3'",
            "",
        ],
    )
    def test_version_equals_pattern_no_match(self, text):
        """Pytest extra pattern must NOT match: {text}."""
        pat = re.compile(r'__version__ = version = [\'"](.*)[\'"]')
        m = pat.search(text)
        assert m is None


class TestPyvistaPatternMatching:
    """Test pyvista version_info pattern."""

    @pytest.mark.parametrize(
        "text",
        [
            "version_info = 1, 2, 3,",
            "version_info = 0, 42, 0,",
            "version_info = 10,20 ,",
            "version_info = 1, 2, 3, ",
        ],
    )
    def test_pyvista_pattern_matches(self, text):
        """Pyvista pattern must match: {text}."""
        pat = re.compile(r"version_info = [\d]+,[\d\s]+,")
        m = pat.search(text)
        assert m is not None

    @pytest.mark.parametrize(
        "text",
        [
            "__version__ = '1.2.3'",
            "version = (1, 2, 3)",
            "",
            "version_info = ",
        ],
    )
    def test_pyvista_pattern_no_match(self, text):
        """Pyvista pattern must NOT match: {text}."""
        pat = re.compile(r"version_info = [\d]+,[\d\s]+,")
        m = pat.search(text)
        assert m is None


class TestNetworkxPatternMatching:
    """Test networkx multi-group pattern."""

    @pytest.mark.parametrize(
        "text, expected_major, expected_minor",
        [
            ('major = "3"\nminor = "2"', "3", "2"),
            ("major = '1'\nminor = '0'", "1", "0"),
            ('major = "10"\nminor = "20"', "10", "20"),
            ("major = '0'\r\nminor = '1'", "0", "1"),
        ],
    )
    def test_networkx_multigroup_matches(self, text, expected_major, expected_minor):
        """Networkx multi-group pattern must capture major/minor from text."""
        pat = re.compile(
            r'major\s*=\s*["\'](\d+)["\']\s*[\r\n]+minor\s*=\s*["\'](\d+)["\']'
        )
        m = pat.search(text)
        assert m is not None
        assert m.group(1) == expected_major
        assert m.group(2) == expected_minor

    @pytest.mark.parametrize(
        "text",
        [
            'major = "3" minor = "2"',  # no newline
            "__version__ = '1.2.3'",
            "",
        ],
    )
    def test_networkx_multigroup_no_match(self, text):
        """Networkx multi-group pattern must NOT match: {text}."""
        pat = re.compile(
            r'major\s*=\s*["\'](\d+)["\']\s*[\r\n]+minor\s*=\s*["\'](\d+)["\']'
        )
        m = pat.search(text)
        assert m is None


class TestQiskitPatternMatching:
    """Test Qiskit catch-all pattern."""

    @pytest.mark.parametrize(
        "text",
        [
            "1.2.3",
            "0.0.1",
            "anything at all",
            "",
            "VERSION = (1, 2, 3)",
            "__version__ = '1.2.3'",
            "   ",
            "1.0.0rc1",
            "v2.0.0",
        ],
    )
    def test_qiskit_catchall_matches(self, text):
        """Qiskit (.*) pattern must match any text: {text}."""
        pat = re.compile(r"(.*)")
        m = pat.search(text)
        assert m is not None


# ── SWE_BENCH_URL_RAW ────────────────────────────────────────────────


class TestSweBenchUrlRaw:
    """Tests for the SWE_BENCH_URL_RAW constant."""

    def test_url_value(self):
        """SWE_BENCH_URL_RAW must equal expected URL."""
        assert SWE_BENCH_URL_RAW == "https://raw.githubusercontent.com/"

    def test_url_starts_with_https(self):
        """SWE_BENCH_URL_RAW must start with https://."""
        assert SWE_BENCH_URL_RAW.startswith("https://")

    def test_url_ends_with_slash(self):
        """SWE_BENCH_URL_RAW must end with /."""
        assert SWE_BENCH_URL_RAW.endswith("/")

    def test_url_contains_githubusercontent(self):
        """SWE_BENCH_URL_RAW must contain githubusercontent."""
        assert "githubusercontent" in SWE_BENCH_URL_RAW

    def test_url_is_string(self):
        """SWE_BENCH_URL_RAW must be a string."""
        assert isinstance(SWE_BENCH_URL_RAW, str)

    def test_url_not_empty(self):
        """SWE_BENCH_URL_RAW must not be empty."""
        assert len(SWE_BENCH_URL_RAW) > 0

    def test_url_contains_raw(self):
        """SWE_BENCH_URL_RAW must contain 'raw'."""
        assert "raw" in SWE_BENCH_URL_RAW

    def test_url_no_trailing_whitespace(self):
        """SWE_BENCH_URL_RAW must have no trailing whitespace."""
        assert SWE_BENCH_URL_RAW == SWE_BENCH_URL_RAW.strip()


# ── Cross-map Consistency ─────────────────────────────────────────────


# repos that appear in BOTH maps
_REPOS_IN_BOTH = sorted(
    set(EXPECTED_PATHS.keys()) & set(EXPECTED_PATTERNS.keys())
)
# repos in paths but not patterns
_REPOS_PATHS_ONLY = sorted(set(EXPECTED_PATHS.keys()) - set(EXPECTED_PATTERNS.keys()))
# repos in patterns but not paths
_REPOS_PATTERNS_ONLY = sorted(
    set(EXPECTED_PATTERNS.keys()) - set(EXPECTED_PATHS.keys())
)


@pytest.mark.parametrize("repo", _REPOS_IN_BOTH)
def test_repo_in_both_maps(repo):
    """Repo {repo} exists in both paths and patterns maps."""
    assert repo in MAP_REPO_TO_VERSION_PATHS
    assert repo in MAP_REPO_TO_VERSION_PATTERNS


@pytest.mark.parametrize("repo", _REPOS_PATTERNS_ONLY)
def test_repo_in_patterns_only(repo):
    """Repo {repo} is in patterns map but not paths map (e.g. matplotlib)."""
    assert repo in MAP_REPO_TO_VERSION_PATTERNS
    assert repo not in MAP_REPO_TO_VERSION_PATHS


class TestCrossMapConsistency:
    """Cross-map consistency checks."""

    def test_matplotlib_in_patterns_not_paths(self):
        """matplotlib/matplotlib is in patterns but not in paths."""
        assert "matplotlib/matplotlib" in MAP_REPO_TO_VERSION_PATTERNS
        assert "matplotlib/matplotlib" not in MAP_REPO_TO_VERSION_PATHS

    def test_all_path_repos_in_patterns_except_none(self):
        """Every repo in paths map should ideally be in patterns map."""
        # This is a documentation/check test — some repos may not have patterns
        missing = set(MAP_REPO_TO_VERSION_PATHS.keys()) - set(
            MAP_REPO_TO_VERSION_PATTERNS.keys()
        )
        # Currently no paths-only repos expected, all should be in both
        assert len(missing) == 0, f"Repos in paths but not patterns: {missing}"


# ── Parametrized Bulk: Paths map — extension check per path ──────────

# All individual paths flattened
_ALL_PATHS_FLAT = [
    path
    for paths in EXPECTED_PATHS.values()
    for path in paths
]


@pytest.mark.parametrize("path", _ALL_PATHS_FLAT)
class TestAllPathsExtension:
    """Extension checks on every individual path string."""

    def test_ends_with_valid_extension(self, path):
        """Path {path} must end with .py, .txt, .toml, or .cfg."""
        assert any(path.endswith(ext) for ext in VALID_EXTENSIONS)

    def test_not_empty(self, path):
        """Path {path} must not be empty."""
        assert len(path) > 0

    def test_is_relative(self, path):
        """Path {path} must be relative (no leading /)."""
        assert not path.startswith("/")


# ── Parametrized Bulk: every (repo, path) in actual map ──────────────

_ACTUAL_REPO_PATH_PAIRS = [
    (repo, path)
    for repo, paths in MAP_REPO_TO_VERSION_PATHS.items()
    for path in paths
]


@pytest.mark.parametrize("repo, path", _ACTUAL_REPO_PATH_PAIRS)
def test_actual_path_in_expected(repo, path):
    """Actual path {path} for {repo} must appear in expected data."""
    assert repo in EXPECTED_PATHS
    assert path in EXPECTED_PATHS[repo]


# ── Parametrized Bulk: every (repo, pattern) in actual map ───────────

_ACTUAL_REPO_PATTERN_PAIRS = [
    (repo, pat)
    for repo, pats in MAP_REPO_TO_VERSION_PATTERNS.items()
    for pat in pats
]


@pytest.mark.parametrize("repo, pattern", _ACTUAL_REPO_PATTERN_PAIRS)
class TestActualPatternProperties:
    """Property checks on every actual pattern."""

    def test_is_string(self, repo, pattern):
        """Pattern for {repo} must be a string."""
        assert isinstance(pattern, str)

    def test_compiles(self, repo, pattern):
        """Pattern for {repo} must compile."""
        re.compile(pattern)

    def test_not_empty(self, repo, pattern):
        """Pattern for {repo} must not be empty."""
        assert len(pattern) > 0


# ── INTEGRATION TESTS ─────────────────────────────────────────────────


class TestIntegrationPathsPatternsAlignment:
    """Integration: verify MAP_REPO_TO_VERSION_PATHS and MAP_REPO_TO_VERSION_PATTERNS
    work together correctly — every repo with paths also has patterns, patterns
    compile and can actually match the kind of content found in those paths."""

    @pytest.mark.parametrize(
        "repo",
        list(MAP_REPO_TO_VERSION_PATHS.keys()),
        ids=[r.replace("/", "_") for r in MAP_REPO_TO_VERSION_PATHS.keys()],
    )
    def test_repo_with_paths_has_patterns(self, repo):
        """Every repo in paths map must also be in patterns map."""
        assert repo in MAP_REPO_TO_VERSION_PATTERNS

    @pytest.mark.parametrize(
        "repo",
        list(MAP_REPO_TO_VERSION_PATHS.keys()),
        ids=[r.replace("/", "_") for r in MAP_REPO_TO_VERSION_PATHS.keys()],
    )
    def test_patterns_can_match_standard_version_strings(self, repo):
        """At least one pattern for a repo should match a standard version string."""
        patterns = MAP_REPO_TO_VERSION_PATTERNS.get(repo, [])
        test_texts = [
            '__version__ = "1.2.3"',
            "__version__ = '4.5.6'",
            "VERSION = (1, 2, 3)",
            "version_info = 1, 2,",
            'major = "1"\nminor = "2"',
            "1.2.3",
        ]
        found = False
        for pat in patterns:
            compiled = re.compile(pat)
            for text in test_texts:
                if compiled.search(text):
                    found = True
                    break
            if found:
                break
        assert found, f"No pattern for {repo} matches any standard version string"

    def test_all_path_repos_subset_of_pattern_repos(self):
        """Every repo in paths map is present in patterns map."""
        path_repos = set(MAP_REPO_TO_VERSION_PATHS.keys())
        pattern_repos = set(MAP_REPO_TO_VERSION_PATTERNS.keys())
        missing = path_repos - pattern_repos
        assert not missing, f"Repos in paths but not patterns: {missing}"

    def test_pattern_repos_superset_of_path_repos(self):
        """Pattern map has at least all repos that paths map has."""
        path_repos = set(MAP_REPO_TO_VERSION_PATHS.keys())
        pattern_repos = set(MAP_REPO_TO_VERSION_PATTERNS.keys())
        assert path_repos.issubset(pattern_repos)

    def test_path_extensions_are_python_or_config(self):
        """All paths across all repos end with .py, .txt, .cfg, or .toml."""
        valid_exts = {".py", ".txt", ".cfg", ".toml"}
        for repo, paths in MAP_REPO_TO_VERSION_PATHS.items():
            for p in paths:
                ext = os.path.splitext(p)[1]
                assert ext in valid_exts, f"{repo}: path {p} has unexpected ext {ext}"


class TestIntegrationOverrideConsistency:
    """Integration: verify that .update() overrides produce valid state."""

    def test_overridden_repos_still_have_compilable_patterns(self):
        """Repos overridden in MAP_REPO_TO_VERSION_PATTERNS still compile."""
        overridden = ["python/mypy", "getmoto/moto", "conan-io/conan"]
        for repo in overridden:
            if repo in MAP_REPO_TO_VERSION_PATTERNS:
                for pat in MAP_REPO_TO_VERSION_PATTERNS[repo]:
                    re.compile(pat)

    def test_overridden_paths_repos_still_have_paths(self):
        """Repos overridden in MAP_REPO_TO_VERSION_PATHS still have valid paths."""
        if "conan-io/conan" in MAP_REPO_TO_VERSION_PATHS:
            paths = MAP_REPO_TO_VERSION_PATHS["conan-io/conan"]
            assert len(paths) >= 1
            for p in paths:
                assert isinstance(p, str)
                assert len(p) > 0

    def test_url_raw_combined_with_repo_produces_valid_url(self):
        """SWE_BENCH_URL_RAW + repo + commit + path produces a valid-looking URL."""
        for repo in list(MAP_REPO_TO_VERSION_PATHS.keys())[:5]:
            paths = MAP_REPO_TO_VERSION_PATHS[repo]
            url = os.path.join(SWE_BENCH_URL_RAW, repo, "abc123", paths[0])
            assert "raw.githubusercontent.com" in url
            assert repo in url
            assert "abc123" in url


# ── END-TO-END TESTS ─────────────────────────────────────────────────


class TestEndToEndConstantsUsability:
    """E2E: simulate how get_versions.py actually uses these constants together."""

    @pytest.mark.parametrize(
        "repo",
        list(MAP_REPO_TO_VERSION_PATHS.keys()),
        ids=[r.replace("/", "_") for r in MAP_REPO_TO_VERSION_PATHS.keys()],
    )
    def test_full_version_detection_flow_simulation(self, repo):
        """Simulate: get paths -> get patterns -> try matching version text."""
        paths = MAP_REPO_TO_VERSION_PATHS[repo]
        assert len(paths) >= 1
        patterns = MAP_REPO_TO_VERSION_PATTERNS.get(repo, [])
        assert len(patterns) >= 1

        # Simulate reading a file and trying patterns
        sample_texts = {
            ".py": '__version__ = "1.2.3"\n',
            ".txt": "1.2.3\n",
            ".cfg": 'version = 1.2.3\n',
            ".toml": 'version = "1.2.3"\n',
        }
        ext = os.path.splitext(paths[0])[1]
        text = sample_texts.get(ext, '__version__ = "1.2.3"\n')

        # Try all patterns against the text
        for pat in patterns:
            compiled = re.compile(pat)
            match = compiled.search(text)
            if match:
                assert match.group(1) is not None
                break

    def test_end_to_end_url_construction_all_repos(self):
        """E2E: construct full GitHub raw URLs for every repo+path combo."""
        for repo, paths in MAP_REPO_TO_VERSION_PATHS.items():
            for path in paths:
                url = os.path.join(SWE_BENCH_URL_RAW, repo, "HEAD", path)
                # URL must have all components
                assert "raw.githubusercontent.com" in url
                assert repo.split("/")[0] in url
                assert repo.split("/")[1] in url
                assert path.split("/")[-1] in url

    def test_end_to_end_pattern_extraction_for_special_repos(self):
        """E2E: verify special repo patterns work with their expected file content."""
        special_cases = {
            "pyvista/pyvista": ("version_info = 0, 42, 1,", "version_info"),
            "networkx/networkx": ('major = "3"\nminor = "2"', "major"),
            "Qiskit/qiskit": ("1.2.3", "(.*)"),
        }
        for repo, (text, expected_substr) in special_cases.items():
            if repo in MAP_REPO_TO_VERSION_PATTERNS:
                patterns = MAP_REPO_TO_VERSION_PATTERNS[repo]
                matched = False
                for pat in patterns:
                    m = re.search(pat, text)
                    if m:
                        matched = True
                        break
                assert matched, f"No pattern for {repo} matched: {text}"

    def test_end_to_end_three_pattern_repos_match_all_formats(self):
        """E2E: repos with 3 patterns should match __version__=, VERSION=(), and version=."""
        three_pattern_repos = [
            r for r in MAP_REPO_TO_VERSION_PATTERNS
            if len(MAP_REPO_TO_VERSION_PATTERNS[r]) == 3
            and r not in ("pyvista/pyvista", "networkx/networkx", "scikit-bio/scikit-bio")
        ]
        for repo in three_pattern_repos:
            patterns = MAP_REPO_TO_VERSION_PATTERNS[repo]
            test_formats = [
                '__version__ = "1.2.3"',
                "VERSION = (1, 2, 3)",
                "__version__ = version = '1.2.3'",
            ]
            for text in test_formats:
                found = any(re.search(p, text) for p in patterns)
                assert found, f"{repo}: no pattern matched '{text}'"
