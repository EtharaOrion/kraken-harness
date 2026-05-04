"""~1500 parametrized tests for detect_version()."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import detect_version


# ─── helpers ───────────────────────────────────────────────────────────

def _write(repo: Path, relpath: str, content: str) -> None:
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# 1. pyproject.toml  (~250 cases)
# ═══════════════════════════════════════════════════════════════════════

_PYPROJECT_VERSIONS = [
    ("1.0.0", "1.0.0"),
    ("0.0.1", "0.0.1"),
    ("0.1.0", "0.1.0"),
    ("2.0.0", "2.0.0"),
    ("10.20.30", "10.20.30"),
    ("1.2.3", "1.2.3"),
    ("0.0.0", "0.0.0"),
    ("99.99.99", "99.99.99"),
    ("1.0.0a1", "1.0.0a1"),
    ("1.0.0b2", "1.0.0b2"),
    ("2.0.0rc1", "2.0.0rc1"),
    ("1.0.0.dev1", "1.0.0.dev1"),
    ("1.0.0.post1", "1.0.0.post1"),
    ("3.0.0alpha1", "3.0.0alpha1"),
    ("4.0.0beta2", "4.0.0beta2"),
    ("1.0.0.dev0", "1.0.0.dev0"),
    ("1.0.0.dev123", "1.0.0.dev123"),
    ("1.0.0a0", "1.0.0a0"),
    ("1.0.0b0", "1.0.0b0"),
    ("1.0.0rc0", "1.0.0rc0"),
    ("1.0.0.post0", "1.0.0.post0"),
    ("0.0.1.dev5", "0.0.1.dev5"),
    ("3.2.1", "3.2.1"),
    ("5.4.3.2.1", "5.4.3.2.1"),
    ("1.2.3.4", "1.2.3.4"),
    ("0.1", "0.1"),
    ("1.0", "1.0"),
    ("100.200.300", "100.200.300"),
    ("1.0.0-beta", "1.0.0-beta"),
    ("1.0.0+local", "1.0.0+local"),
    ("1.0.0+build.123", "1.0.0+build.123"),
    ("2024.1.1", "2024.1.1"),
    ("2024.01.01", "2024.01.01"),
    ("0.0.0.0.0.1", "0.0.0.0.0.1"),
    ("v1.0.0", "v1.0.0"),
    ("V2.0.0", "V2.0.0"),
    ("1.0.0-alpha.1", "1.0.0-alpha.1"),
    ("1.0.0-rc.1+build.1", "1.0.0-rc.1+build.1"),
    ("0.1.0.dev20240101", "0.1.0.dev20240101"),
    ("1.0.0.a1", "1.0.0.a1"),
    ("12.0.0", "12.0.0"),
    ("0.99.0", "0.99.0"),
    ("3.11.0", "3.11.0"),
    ("7.0.0", "7.0.0"),
    ("6.5.4", "6.5.4"),
    ("8.1.2.3", "8.1.2.3"),
    ("0.0.1a1", "0.0.1a1"),
    ("0.0.1b1", "0.0.1b1"),
    ("0.0.1rc1", "0.0.1rc1"),
    ("1.0.0.final", "1.0.0.final"),
]

_PYPROJECT_REPO_NAMES = [
    "owner/mypackage",
    "numpy/numpy",
    "pandas-dev/pandas",
    "org/cool-lib",
    "user/tool",
]


def _pyproject_ids():
    ids = []
    for ver, _ in _PYPROJECT_VERSIONS:
        for rn in _PYPROJECT_REPO_NAMES:
            ids.append(f"pyproject-{ver}-{rn.replace('/', '_')}")
    return ids


def _pyproject_params():
    params = []
    for ver, expected in _PYPROJECT_VERSIONS:
        for rn in _PYPROJECT_REPO_NAMES:
            params.append((ver, rn, expected))
    return params


@pytest.mark.parametrize(
    "version_str,repo_name,expected",
    _pyproject_params(),
    ids=_pyproject_ids(),
)
def test_pyproject_version(tmp_path, version_str, repo_name, expected):
    _write(tmp_path, "pyproject.toml", f'[project]\nname = "pkg"\nversion = "{version_str}"\n')
    assert detect_version(tmp_path, repo_name) == expected


_PYPROJECT_NO_VERSION_CASES = [
    ("no-version-key", '[project]\nname = "pkg"\n'),
    ("no-project-section", '[tool.setuptools]\npackages = ["pkg"]\n'),
    ("empty-file", ""),
    ("version-empty-string", '[project]\nversion = ""\n'),
    ("version-in-tool-section", '[tool.poetry]\nversion = "1.0.0"\n'),
    ("commented-version", '[project]\nname = "pkg"\n# version = "1.0.0"\n'),
    ("project-no-keys", "[project]\n"),
    ("version-under-wrong-table", '[build-system]\nversion = "1.0.0"\n'),
    ("malformed-toml", '[project\nversion = "1.0.0"\n'),
    ("nested-wrong", '[project.optional-dependencies]\nversion = "1.0.0"\n'),
]


@pytest.mark.parametrize(
    "label,content",
    _PYPROJECT_NO_VERSION_CASES,
    ids=[c[0] for c in _PYPROJECT_NO_VERSION_CASES],
)
def test_pyproject_no_version(tmp_path, label, content):
    _write(tmp_path, "pyproject.toml", content)
    assert detect_version(tmp_path, "owner/pkg") is None


# ═══════════════════════════════════════════════════════════════════════
# 2. setup.py version=  (~250 cases)
# ═══════════════════════════════════════════════════════════════════════

_SETUP_PY_VERSIONS_DOUBLE = [
    "0.1.0", "1.0.0", "2.3.4", "10.0.0", "0.0.1", "1.2.3a1",
    "1.2.3b2", "1.2.3rc1", "1.0.0.dev1", "1.0.0.post1", "3.0.0",
    "0.99.0", "5.4.3", "7.8.9", "100.0.0", "1.0", "0.1",
    "2024.1.1", "1.0.0+local", "1.0.0-beta", "4.5.6.7",
    "0.0.0", "99.99.99", "1.0.0a0", "1.0.0b0",
    "1.0.0rc0", "1.0.0.dev0", "6.0.0", "8.1.2",
    "9.0.0.post2",
]

_SETUP_PY_VERSIONS_SINGLE = [
    "0.1.0", "1.0.0", "2.3.4", "10.0.0", "0.0.1", "1.2.3a1",
    "1.2.3b2", "1.2.3rc1", "1.0.0.dev1", "1.0.0.post1", "3.0.0",
    "0.99.0", "5.4.3", "7.8.9", "100.0.0", "1.0", "0.1",
    "2024.1.1", "1.0.0+local", "1.0.0-beta", "4.5.6.7",
    "0.0.0", "99.99.99", "1.0.0a0", "1.0.0b0",
    "1.0.0rc0", "1.0.0.dev0", "6.0.0", "8.1.2",
    "9.0.0.post2",
]

_SETUP_PY_TEMPLATES = [
    ("setup-double-nospace", 'from setuptools import setup\nsetup(\n    name="pkg",\n    version="{ver}",\n)'),
    ("setup-single-nospace", "from setuptools import setup\nsetup(\n    name='pkg',\n    version='{ver}',\n)"),
    ("setup-double-space", 'from setuptools import setup\nsetup(\n    name="pkg",\n    version = "{ver}",\n)'),
    ("setup-single-space", "from setuptools import setup\nsetup(\n    name='pkg',\n    version = '{ver}',\n)"),
    ("setup-double-multispace", 'from setuptools import setup\nsetup(\n    name="pkg",\n    version  =  "{ver}",\n)'),
    ("setup-inline", 'setup(version="{ver}", name="pkg")'),
    ("setup-tab-sep", 'setup(\n\tversion="{ver}",\n\tname="pkg",\n)'),
    ("setup-version-first", 'setup(version="{ver}", name="pkg", packages=[])'),
]


def _setup_py_params():
    params = []
    for tpl_name, tpl in _SETUP_PY_TEMPLATES:
        versions = _SETUP_PY_VERSIONS_DOUBLE if "double" in tpl_name or "space" in tpl_name or "inline" in tpl_name or "tab" in tpl_name or "first" in tpl_name else _SETUP_PY_VERSIONS_SINGLE
        for ver in versions:
            params.append((tpl_name, tpl, ver))
    return params


def _setup_py_ids():
    return [f"setup-py-{t[0]}-{t[2]}" for t in _setup_py_params()]


@pytest.mark.parametrize(
    "tpl_name,template,version",
    _setup_py_params(),
    ids=_setup_py_ids(),
)
def test_setup_py_version(tmp_path, tpl_name, template, version):
    content = template.format(ver=version)
    _write(tmp_path, "setup.py", content)
    assert detect_version(tmp_path, "owner/pkg") == version


_SETUP_PY_NO_MATCH = [
    ("version-variable", 'VERSION = "1.0.0"\nsetup(version=VERSION, name="pkg")', None),
    ("fstring", 'v = "1.0.0"\nsetup(version=f"{v}", name="pkg")', None),
    ("no-version-kwarg", 'setup(name="pkg", packages=["pkg"])', None),
    ("empty-setup-py", "", None),
    ("version-call", 'setup(version=get_version(), name="pkg")', None),
    ("version-import", 'from pkg import __version__\nsetup(version=__version__)', None),
    ("version-dict", 'setup(**{"version": "1.0.0"})', None),
    ("commented-still-matches", '# version="1.0.0"\nsetup(name="pkg")', "1.0.0"),
    ("comment-block-still-matches", '"""\nversion="1.0.0"\n"""\nsetup(name="pkg")', "1.0.0"),
    ("concat-partial-match", 'setup(version="1." + "0.0", name="pkg")', "1."),
]


@pytest.mark.parametrize(
    "label,content,expected",
    _SETUP_PY_NO_MATCH,
    ids=[c[0] for c in _SETUP_PY_NO_MATCH],
)
def test_setup_py_edge_cases(tmp_path, label, content, expected):
    _write(tmp_path, "setup.py", content)
    assert detect_version(tmp_path, "owner/nonexistent_pkg_xyz") == expected


# ═══════════════════════════════════════════════════════════════════════
# 3. setup.cfg [metadata] version  (~200 cases)
# ═══════════════════════════════════════════════════════════════════════

_SETUP_CFG_VERSIONS = [
    "0.1.0", "1.0.0", "2.3.4", "10.0.0", "0.0.1", "1.2.3a1",
    "1.2.3b2", "1.2.3rc1", "1.0.0.dev1", "1.0.0.post1", "3.0.0",
    "0.99.0", "5.4.3", "7.8.9", "100.0.0", "1.0", "0.1",
    "2024.1.1", "4.5.6.7", "0.0.0", "99.99.99", "1.0.0a0",
    "1.0.0b0", "1.0.0rc0", "1.0.0.dev0", "6.0.0", "8.1.2",
    "9.0.0.post2", "1.0.0.final", "3.2.1", "11.0.0", "0.2.0",
    "0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.7.0", "0.8.0",
    "0.9.0", "1.1.0", "1.1.1", "2.0.0", "2.1.0", "2.2.0",
    "3.3.3", "4.4.4", "5.5.5", "6.6.6", "7.7.7", "8.8.8",
]

_SETUP_CFG_REPO_NAMES = [
    "owner/pkg",
    "numpy/numpy",
    "pandas-dev/pandas",
    "org/my-lib",
]


def _setup_cfg_valid_params():
    params = []
    for ver in _SETUP_CFG_VERSIONS:
        for rn in _SETUP_CFG_REPO_NAMES:
            params.append((ver, rn))
    return params


def _setup_cfg_valid_ids():
    return [f"cfg-{v}-{r.replace('/', '_')}" for v, r in _setup_cfg_valid_params()]


@pytest.mark.parametrize(
    "version,repo_name",
    _setup_cfg_valid_params(),
    ids=_setup_cfg_valid_ids(),
)
def test_setup_cfg_version(tmp_path, version, repo_name):
    _write(tmp_path, "setup.cfg", f"[metadata]\nname = pkg\nversion = {version}\n")
    assert detect_version(tmp_path, repo_name) == version


_SETUP_CFG_FILTERED = [
    ("attr-simple", "attr:pkg.__version__"),
    ("attr-nested", "attr:pkg.version.__version__"),
    ("attr-src", "attr:src.pkg.__version__"),
    ("file-VERSION", "file:VERSION"),
    ("file-version-txt", "file:version.txt"),
    ("file-src", "file:src/pkg/VERSION"),
    ("attr-uppercase", "attr:PKG.__version__"),
    ("attr-with-space", "attr: pkg.__version__"),
    ("file-with-space", "file: VERSION"),
    ("attr-deep", "attr:pkg.sub.mod.__version__"),
]


@pytest.mark.parametrize(
    "label,ver_value",
    _SETUP_CFG_FILTERED,
    ids=[c[0] for c in _SETUP_CFG_FILTERED],
)
def test_setup_cfg_filtered(tmp_path, label, ver_value):
    _write(tmp_path, "setup.cfg", f"[metadata]\nname = pkg\nversion = {ver_value}\n")
    assert detect_version(tmp_path, "owner/nonexistent_pkg_xyz") is None


_SETUP_CFG_NO_VERSION = [
    ("no-metadata", "[options]\npackages = find:\n"),
    ("metadata-no-version", "[metadata]\nname = pkg\n"),
    ("empty-file", ""),
    ("wrong-section", "[options.extras_require]\nversion = 1.0.0\n"),
    ("malformed", "[metadata\nversion = 1.0.0\n"),
]


@pytest.mark.parametrize(
    "label,content",
    _SETUP_CFG_NO_VERSION,
    ids=[c[0] for c in _SETUP_CFG_NO_VERSION],
)
def test_setup_cfg_no_version(tmp_path, label, content):
    _write(tmp_path, "setup.cfg", content)
    assert detect_version(tmp_path, "owner/nonexistent_pkg_xyz") is None


# ═══════════════════════════════════════════════════════════════════════
# 4. __version__ in source code  (~400 cases)
# ═══════════════════════════════════════════════════════════════════════

_INIT_VERSIONS = [
    "0.1.0", "1.0.0", "2.3.4", "10.0.0", "0.0.1", "1.2.3a1",
    "1.2.3b2", "1.2.3rc1", "1.0.0.dev1", "1.0.0.post1", "3.0.0",
    "0.99.0", "5.4.3", "7.8.9", "100.0.0", "1.0", "0.1",
    "2024.1.1", "4.5.6.7", "0.0.0", "99.99.99",
]

_VERSION_LINE_FORMATS = [
    ('__version__ = "{ver}"', "dq-nospace"),
    ("__version__ = '{ver}'", "sq-nospace"),
    ('__version__="{ver}"', "dq-noeq-space"),
    ("__version__='{ver}'", "sq-noeq-space"),
    ('__version__  =  "{ver}"', "dq-multispace"),
    ("__version__  =  '{ver}'", "sq-multispace"),
    ('__version__\t=\t"{ver}"', "dq-tab"),
    ("__version__\t=\t'{ver}'", "sq-tab"),
]

_SOURCE_FILES = [
    ("{pkg}/__init__.py", "init"),
    ("{pkg}/version.py", "version"),
    ("{pkg}/_version.py", "_version"),
    ("src/{pkg}/__init__.py", "src-init"),
    ("src/{pkg}/version.py", "src-version"),
    ("src/{pkg}/_version.py", "src-_version"),
]


def _init_version_params():
    params = []
    repo_cases = [
        ("owner/mypackage", "mypackage"),
        ("owner/my-package", "my_package"),
        ("org/Cool-Lib", "cool_lib"),
    ]
    for repo_name, pkg in repo_cases:
        for fpath_tpl, file_label in _SOURCE_FILES:
            for ver in _INIT_VERSIONS[:7]:
                for line_tpl, fmt_label in _VERSION_LINE_FORMATS[:2]:
                    params.append((repo_name, pkg, fpath_tpl, file_label, ver, line_tpl, fmt_label))
    for repo_name, pkg in repo_cases:
        for fpath_tpl, file_label in _SOURCE_FILES[:2]:
            for ver in _INIT_VERSIONS:
                params.append((repo_name, pkg, fpath_tpl, file_label, ver, '__version__ = "{ver}"', "dq-default"))
    for fpath_tpl, file_label in _SOURCE_FILES:
        for line_tpl, fmt_label in _VERSION_LINE_FORMATS:
            for ver in _INIT_VERSIONS[:5]:
                params.append(("owner/testpkg", "testpkg", fpath_tpl, file_label, ver, line_tpl, fmt_label))
    return params


def _init_version_ids():
    return [
        f"src-{p[3]}-{p[6]}-{p[4]}-{p[1]}"
        for p in _init_version_params()
    ]


@pytest.mark.parametrize(
    "repo_name,pkg,fpath_tpl,file_label,version,line_tpl,fmt_label",
    _init_version_params(),
    ids=_init_version_ids(),
)
def test_source_version(tmp_path, repo_name, pkg, fpath_tpl, file_label, version, line_tpl, fmt_label):
    fpath = fpath_tpl.format(pkg=pkg)
    line = line_tpl.format(ver=version)
    _write(tmp_path, fpath, line + "\n")
    assert detect_version(tmp_path, repo_name) == version


_UNDERSCORE_REMOVAL_REPOS = [
    ("owner/my-package", "my_package", "mypackage"),
    ("owner/my-cool-lib", "my_cool_lib", "mycoollib"),
    ("org/a-b-c", "a_b_c", "abc"),
    ("user/x-y", "x_y", "xy"),
    ("dev/one-two-three", "one_two_three", "onetwothree"),
]


def _underscore_fallback_params():
    params = []
    for repo_name, _, nouscore in _UNDERSCORE_REMOVAL_REPOS:
        for fpath_tpl, file_label in _SOURCE_FILES:
            for ver in _INIT_VERSIONS[:4]:
                params.append((repo_name, nouscore, fpath_tpl, file_label, ver))
    return params


def _underscore_fallback_ids():
    return [
        f"nouscore-{p[3]}-{p[4]}-{p[1]}"
        for p in _underscore_fallback_params()
    ]


@pytest.mark.parametrize(
    "repo_name,nouscore_pkg,fpath_tpl,file_label,version",
    _underscore_fallback_params(),
    ids=_underscore_fallback_ids(),
)
def test_source_version_underscore_removal(tmp_path, repo_name, nouscore_pkg, fpath_tpl, file_label, version):
    fpath = fpath_tpl.format(pkg=nouscore_pkg)
    _write(tmp_path, fpath, f'__version__ = "{version}"\n')
    assert detect_version(tmp_path, repo_name) == version


_SOURCE_NO_MATCH_CASES = [
    ("no-dunder", '{pkg}/__init__.py', 'VERSION = "1.0.0"\n', None),
    ("triple-quoted", '{pkg}/__init__.py', "__version__ = '''1.0.0'''\n", None),
    ("no-quotes", '{pkg}/__init__.py', "__version__ = 1\n", None),
    ("backtick", '{pkg}/__init__.py', "__version__ = `1.0.0`\n", None),
    ("empty-file", '{pkg}/__init__.py', "", None),
    ("wrong-var", '{pkg}/__init__.py', 'version = "1.0.0"\n', None),
    ("multiline-val", '{pkg}/__init__.py', '__version__ = (\n    "1.0.0"\n)\n', None),
    ("commented-still-matches", '{pkg}/__init__.py', '# __version__ = "1.0.0"\n', "1.0.0"),
]


@pytest.mark.parametrize(
    "label,fpath_tpl,content,expected",
    _SOURCE_NO_MATCH_CASES,
    ids=[c[0] for c in _SOURCE_NO_MATCH_CASES],
)
def test_source_version_edge(tmp_path, label, fpath_tpl, content, expected):
    fpath = fpath_tpl.format(pkg="mypkg")
    _write(tmp_path, fpath, content)
    assert detect_version(tmp_path, "owner/mypkg") == expected


# ═══════════════════════════════════════════════════════════════════════
# 5. VERSION file  (~150 cases)
# ═══════════════════════════════════════════════════════════════════════

_VERSION_FILE_VALID = [
    "0.1.0", "1.0.0", "2.3.4", "10.0.0", "0.0.1", "1.2.3a1",
    "1.2.3b2", "1.2.3rc1", "1.0.0.dev1", "1.0.0.post1", "3.0.0",
    "0.99.0", "5.4.3", "7.8.9", "100.0.0", "1.0", "0.1",
    "2024.1.1", "4.5.6.7", "0.0.0", "99.99.99", "1.0.0a0",
    "1.0.0b0", "1.0.0rc0", "1.0.0.dev0", "6.0.0", "8.1.2",
    "9.0.0.post2", "3.2.1", "11.0.0",
]


def _version_file_params():
    params = []
    for fname in ("VERSION", "version.txt"):
        for ver in _VERSION_FILE_VALID:
            params.append((fname, ver, ver))
        for ver in _VERSION_FILE_VALID[:15]:
            params.append((fname, ver + "\n", ver))
        for ver in _VERSION_FILE_VALID[:10]:
            params.append((fname, "  " + ver + "  \n", ver))
        for ver in _VERSION_FILE_VALID[:10]:
            params.append((fname, ver + "\nsome extra line\n", ver))
    return params


def _version_file_ids():
    return [f"vf-{p[0]}-{p[2]}-{i}" for i, p in enumerate(_version_file_params())]


@pytest.mark.parametrize(
    "filename,content,expected",
    _version_file_params(),
    ids=_version_file_ids(),
)
def test_version_file(tmp_path, filename, content, expected):
    _write(tmp_path, filename, content)
    assert detect_version(tmp_path, "owner/nonexistent_pkg_xyz") == expected


_VERSION_FILE_INVALID = [
    ("no-digits-start", "VERSION", "versionstring"),
    ("alpha-only", "VERSION", "abc"),
    ("no-dot", "VERSION", "123"),
    ("empty", "VERSION", ""),
    ("no-digits-start-txt", "version.txt", "versionstring"),
    ("alpha-only-txt", "version.txt", "abc"),
    ("no-dot-txt", "version.txt", "123"),
    ("empty-txt", "version.txt", ""),
    ("just-dot", "VERSION", "."),
    ("dot-digits", "VERSION", ".1.0"),
    ("hyphen-start", "VERSION", "-1.0.0"),
]


@pytest.mark.parametrize(
    "label,filename,content",
    _VERSION_FILE_INVALID,
    ids=[c[0] for c in _VERSION_FILE_INVALID],
)
def test_version_file_invalid(tmp_path, label, filename, content):
    _write(tmp_path, filename, content)
    assert detect_version(tmp_path, "owner/nonexistent_pkg_xyz") is None


# ═══════════════════════════════════════════════════════════════════════
# 6. Not found → None  (~100 cases)
# ═══════════════════════════════════════════════════════════════════════

_NONE_CASES = [
    "empty-repo",
    "only-readme",
    "only-license",
    "only-gitignore",
    "only-makefile",
    "only-dockerfile",
    "only-requirements",
    "only-tox-ini",
    "only-ci-yaml",
    "only-docs-dir",
]

_NONE_FILES = {
    "empty-repo": [],
    "only-readme": [("README.md", "# My Project\n")],
    "only-license": [("LICENSE", "MIT\n")],
    "only-gitignore": [(".gitignore", "*.pyc\n")],
    "only-makefile": [("Makefile", "all:\n\techo hello\n")],
    "only-dockerfile": [("Dockerfile", "FROM python:3.10\n")],
    "only-requirements": [("requirements.txt", "numpy\n")],
    "only-tox-ini": [("tox.ini", "[tox]\nenvlist = py310\n")],
    "only-ci-yaml": [(".github/workflows/ci.yml", "name: CI\n")],
    "only-docs-dir": [("docs/index.md", "# Docs\n")],
}

_WRONG_PKG_REPOS = [
    "owner/nonexistent_pkg_xyz",
    "org/totally_missing",
    "user/no-such-thing",
    "dev/aaaa",
    "company/bbbb-cccc",
]

_WRONG_PKG_SOURCE_FILES = [
    ("wrongpkg/__init__.py", '__version__ = "1.0.0"\n'),
    ("otherpkg/version.py", '__version__ = "2.0.0"\n'),
    ("badname/_version.py", '__version__ = "3.0.0"\n'),
    ("src/wrongpkg/__init__.py", '__version__ = "4.0.0"\n'),
    ("src/otherpkg/version.py", '__version__ = "5.0.0"\n'),
]


def _none_params():
    params = []
    for case in _NONE_CASES:
        for rn in _WRONG_PKG_REPOS:
            params.append((case, rn, _NONE_FILES[case]))
    for rn in _WRONG_PKG_REPOS:
        for fpath, content in _WRONG_PKG_SOURCE_FILES:
            params.append((f"wrong-pkg-{fpath.replace('/', '-')}", rn, [(fpath, content)]))
    return params


def _none_ids():
    return [f"none-{p[0]}-{p[1].replace('/', '_')}" for p in _none_params()]


@pytest.mark.parametrize(
    "case_name,repo_name,files",
    _none_params(),
    ids=_none_ids(),
)
def test_not_found(tmp_path, case_name, repo_name, files):
    for relpath, content in files:
        _write(tmp_path, relpath, content)
    assert detect_version(tmp_path, repo_name) is None


# ═══════════════════════════════════════════════════════════════════════
# 7. Priority cascade  (~150 cases)
# ═══════════════════════════════════════════════════════════════════════

_CASCADE_VERSIONS_A = [
    "1.0.0", "2.0.0", "3.0.0", "4.0.0", "5.0.0",
    "0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0",
]

_CASCADE_VERSIONS_B = [
    "10.0.0", "20.0.0", "30.0.0", "40.0.0", "50.0.0",
    "0.10.0", "0.20.0", "0.30.0", "0.40.0", "0.50.0",
]

_CASCADE_VERSIONS_C = [
    "100.0.0", "200.0.0", "300.0.0", "400.0.0", "500.0.0",
    "0.100.0", "0.200.0", "0.300.0", "0.400.0", "0.500.0",
]


def _cascade_params():
    params = []
    for i in range(len(_CASCADE_VERSIONS_A)):
        va = _CASCADE_VERSIONS_A[i]
        vb = _CASCADE_VERSIONS_B[i]
        vc = _CASCADE_VERSIONS_C[i]
        params.append(("pyproject-over-setup-py", va, vb, None, None, None, va))
        params.append(("pyproject-over-cfg", va, None, vb, None, None, va))
        params.append(("pyproject-over-init", va, None, None, vb, None, va))
        params.append(("pyproject-over-version-file", va, None, None, None, vb, va))
        params.append(("setup-py-over-cfg", None, va, vb, None, None, va))
        params.append(("setup-py-over-init", None, va, None, vb, None, va))
        params.append(("setup-py-over-version-file", None, va, None, None, vb, va))
        params.append(("cfg-over-init", None, None, va, vb, None, va))
        params.append(("cfg-over-version-file", None, None, va, None, vb, va))
        params.append(("init-over-version-file", None, None, None, va, vb, va))
        params.append(("pyproject-over-all", va, vb, vc, vc, vc, va))
        params.append(("setup-py-over-rest", None, va, vb, vc, vc, va))
        params.append(("cfg-over-rest", None, None, va, vb, vc, va))
        params.append(("all-present-pyproject-wins", va, vb, vc, vc, vc, va))
        params.append(("init-only", None, None, None, va, None, va))
    return params


def _cascade_ids():
    return [f"cascade-{p[0]}-{i}" for i, p in enumerate(_cascade_params())]


@pytest.mark.parametrize(
    "label,pyproject_ver,setup_py_ver,cfg_ver,init_ver,vfile_ver,expected",
    _cascade_params(),
    ids=_cascade_ids(),
)
def test_priority_cascade(
    tmp_path, label, pyproject_ver, setup_py_ver, cfg_ver, init_ver, vfile_ver, expected,
):
    if pyproject_ver:
        _write(tmp_path, "pyproject.toml", f'[project]\nname = "pkg"\nversion = "{pyproject_ver}"\n')
    if setup_py_ver:
        _write(tmp_path, "setup.py", f'setup(version="{setup_py_ver}", name="pkg")\n')
    if cfg_ver:
        _write(tmp_path, "setup.cfg", f"[metadata]\nname = pkg\nversion = {cfg_ver}\n")
    if init_ver:
        _write(tmp_path, "mypkg/__init__.py", f'__version__ = "{init_ver}"\n')
    if vfile_ver:
        _write(tmp_path, "VERSION", f"{vfile_ver}\n")
    assert detect_version(tmp_path, "owner/mypkg") == expected
