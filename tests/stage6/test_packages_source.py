"""Tests for detect_packages_source() — ~800 parametrized cases."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import detect_packages_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(repo: Path, relpath: str, content: str = "") -> Path:
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _mkdir(repo: Path, relpath: str) -> Path:
    p = repo / relpath
    p.mkdir(parents=True, exist_ok=True)
    return p


# ===================================================================
# 1. environment.yml exists → ("environment.yml", [], [])  ~100 cases
# ===================================================================

ENV_YML_CONTENTS = [
    "",
    "name: base",
    "name: test\nchannels:\n  - defaults",
    "name: myenv\nchannels:\n  - conda-forge\ndependencies:\n  - python=3.9",
    "name: env\ndependencies:\n  - numpy\n  - pandas\n  - scipy",
    "name: env\ndependencies:\n  - python=3.10\n  - pip:\n    - torch",
    "name: env\nchannels:\n  - conda-forge\n  - defaults\ndependencies:\n  - python>=3.8\n  - numpy>=1.21",
    "name: env\nprefix: /opt/conda/envs/myenv",
    "# just a comment",
    "name: test-env\ndependencies:\n  - requests==2.28.0",
    "name: env\ndependencies:\n  - python\n  - pip:\n    - flask\n    - gunicorn",
    "channels:\n  - conda-forge",
    "name: myenv\ndependencies: []",
    "name: myproject\nchannels:\n  - pytorch\n  - conda-forge\ndependencies:\n  - pytorch\n  - torchvision",
    "---\nname: env",
    "{invalid yaml content}",
    "name: env\ndependencies:\n  - python=3.11\n  - numpy\n  - scipy\n  - matplotlib\n  - pandas\n  - scikit-learn",
    "name: env\nvariables:\n  ENV_VAR: value",
    "name: base\nchannels:\n  - defaults\n  - conda-forge\n  - bioconda",
    "name: env\ndependencies:\n  - python\n  - pip:\n    - -e .",
]

_extra_yml = []
for i in range(80):
    _extra_yml.append(f"name: auto_env_{i}")
ENV_YML_CONTENTS.extend(_extra_yml)


@pytest.mark.parametrize("content", ENV_YML_CONTENTS, ids=[f"env_yml_{i}" for i in range(len(ENV_YML_CONTENTS))])
def test_env_yml_exists(tmp_path: Path, content: str):
    _write(tmp_path, "environment.yml", content.replace("\\n", "\n"))
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yml"
    assert reqs == []
    assert pkgs == []


# ===================================================================
# 2. environment.yaml exists → ("environment.yaml", [], [])  ~50 cases
# ===================================================================

ENV_YAML_CONTENTS = [
    "",
    "name: base",
    "name: env\nchannels:\n  - defaults",
    "name: myenv\ndependencies:\n  - python=3.9\n  - numpy",
    "# yaml comment only",
    "name: env\ndependencies:\n  - pip:\n    - torch",
    "channels:\n  - conda-forge\n  - bioconda",
    "name: test\ndependencies: []",
    "name: env\nprefix: /home/user/envs/test",
    "{bad yaml}",
]

_extra_yaml = []
for i in range(40):
    _extra_yaml.append(f"name: yaml_env_{i}")
ENV_YAML_CONTENTS.extend(_extra_yaml)


@pytest.mark.parametrize("content", ENV_YAML_CONTENTS, ids=[f"env_yaml_{i}" for i in range(len(ENV_YAML_CONTENTS))])
def test_env_yaml_exists(tmp_path: Path, content: str):
    _write(tmp_path, "environment.yaml", content.replace("\\n", "\n"))
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yaml"
    assert reqs == []
    assert pkgs == []


# ===================================================================
# 3. requirements.txt exists → ("requirements.txt", ["requirements.txt"], [])  ~150 cases
# ===================================================================

REQS_TXT_CONTENTS = [
    "",
    "numpy",
    "numpy==1.21.0",
    "numpy>=1.21",
    "numpy>=1.21,<2.0",
    "numpy~=1.21",
    "numpy!=1.20",
    "pandas",
    "pandas>=1.3.0",
    "scipy>=1.7",
    "# this is a comment",
    "# comment\nnumpy",
    "-r base.txt",
    "-r base.txt\nnumpy",
    "-c constraints.txt",
    "--index-url https://pypi.org/simple",
    "--extra-index-url https://download.pytorch.org/whl/cpu",
    "numpy\npandas\nscipy",
    "numpy\npandas\nscipy\nmatplotlib\nseaborn",
    "requests[security]>=2.28",
    "flask[async]",
    "package @ https://example.com/package.tar.gz",
    "package @ file:///local/path",
    "-e .",
    "-e .[dev]",
    ".",
    "./subpackage",
    "git+https://github.com/user/repo.git",
    "git+https://github.com/user/repo.git@v1.0#egg=package",
    "numpy ; python_version >= '3.8'",
    "numpy ; sys_platform == 'linux'",
    "numpy\n\n# section\npandas\n\n# another\nscipy",
    "   numpy   ",
    "\nnumpy\n\n",
    "numpy==1.21.0\npandas==1.3.5\nscipy==1.7.3\nmatplotlib==3.5.0",
    "torch>=1.10\ntorchvision>=0.11\ntorchaudio>=0.10",
    "Django>=3.2,<4.0\ndjangorestframework>=3.12",
    "pytest>=7.0\npytest-cov>=3.0\npytest-xdist",
    "black>=22.0\nruff>=0.0.1\nmypy>=0.9",
    "sphinx>=4.0\nsphinx-rtd-theme\nnumpydoc",
    "\n\n\n",
    "   \n   \n   ",
    "NUMPY",
    "Numpy",
    "numpy[all]",
    "numpy[all,extra]>=1.21",
    "setuptools>=60\nwheel",
    "cython>=0.29",
    "pybind11>=2.9",
]

_extra_reqs = []
for i in range(100):
    _extra_reqs.append(f"auto-package-{i}>=0.{i}")
REQS_TXT_CONTENTS.extend(_extra_reqs)


@pytest.mark.parametrize("content", REQS_TXT_CONTENTS, ids=[f"reqs_txt_{i}" for i in range(len(REQS_TXT_CONTENTS))])
def test_reqs_txt_exists(tmp_path: Path, content: str):
    _write(tmp_path, "requirements.txt", content.replace("\\n", "\n"))
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "requirements.txt"
    assert reqs == ["requirements.txt"]
    assert pkgs == []


# ===================================================================
# 4. requirements/ directory with .txt files  ~150 cases
# ===================================================================

REQS_DIR_CASES = []

single_files = ["base.txt", "dev.txt", "test.txt", "prod.txt", "docs.txt",
                 "ci.txt", "lint.txt", "typing.txt", "all.txt", "common.txt",
                 "install.txt", "build.txt", "runtime.txt", "optional.txt",
                 "extra.txt", "minimal.txt", "full.txt", "core.txt",
                 "testing.txt", "development.txt"]
for f in single_files:
    REQS_DIR_CASES.append((
        {f"requirements/{f}": "numpy"},
        ("requirements.txt", [f"requirements/{f}"], []),
    ))

combo_pairs = [
    (["base.txt", "dev.txt"], ["requirements/base.txt", "requirements/dev.txt"]),
    (["base.txt", "test.txt"], ["requirements/base.txt", "requirements/test.txt"]),
    (["dev.txt", "test.txt"], ["requirements/dev.txt", "requirements/test.txt"]),
    (["base.txt", "prod.txt"], ["requirements/base.txt", "requirements/prod.txt"]),
    (["ci.txt", "dev.txt"], ["requirements/ci.txt", "requirements/dev.txt"]),
    (["docs.txt", "lint.txt"], ["requirements/docs.txt", "requirements/lint.txt"]),
]
for files, expected_paths in combo_pairs:
    REQS_DIR_CASES.append((
        {f"requirements/{f}": "pkg" for f in files},
        ("requirements.txt", expected_paths, []),
    ))

combo_triples = [
    (["base.txt", "dev.txt", "test.txt"], ["requirements/base.txt", "requirements/dev.txt", "requirements/test.txt"]),
    (["base.txt", "dev.txt", "prod.txt"], ["requirements/base.txt", "requirements/dev.txt", "requirements/prod.txt"]),
    (["ci.txt", "dev.txt", "test.txt"], ["requirements/ci.txt", "requirements/dev.txt", "requirements/test.txt"]),
    (["docs.txt", "lint.txt", "typing.txt"], ["requirements/docs.txt", "requirements/lint.txt", "requirements/typing.txt"]),
]
for files, expected_paths in combo_triples:
    REQS_DIR_CASES.append((
        {f"requirements/{f}": "pkg" for f in files},
        ("requirements.txt", expected_paths, []),
    ))

all5 = ["base.txt", "dev.txt", "docs.txt", "lint.txt", "test.txt"]
REQS_DIR_CASES.append((
    {f"requirements/{f}": "pkg" for f in all5},
    ("requirements.txt", [f"requirements/{f}" for f in sorted(all5)], []),
))

all_many = sorted(["base.txt", "dev.txt", "docs.txt", "lint.txt", "test.txt", "prod.txt", "ci.txt", "typing.txt"])
REQS_DIR_CASES.append((
    {f"requirements/{f}": "pkg" for f in all_many},
    ("requirements.txt", [f"requirements/{f}" for f in all_many], []),
))

for f in single_files[:10]:
    REQS_DIR_CASES.append((
        {f"requirements/{f}": ""},
        ("requirements.txt", [f"requirements/{f}"], []),
    ))

for f in single_files[:10]:
    REQS_DIR_CASES.append((
        {f"requirements/{f}": "# just a comment\nnumpy>=1.0"},
        ("requirements.txt", [f"requirements/{f}"], []),
    ))

for i in range(60):
    fname = f"auto_{i}.txt"
    REQS_DIR_CASES.append((
        {f"requirements/{fname}": f"auto-pkg-{i}"},
        ("requirements.txt", [f"requirements/{fname}"], []),
    ))

for i in range(10):
    files_set = sorted([f"gen_{i}_a.txt", f"gen_{i}_b.txt"])
    REQS_DIR_CASES.append((
        {f"requirements/{f}": "pkg" for f in files_set},
        ("requirements.txt", [f"requirements/{f}" for f in files_set], []),
    ))


@pytest.mark.parametrize("file_map,expected", REQS_DIR_CASES,
                         ids=[f"reqs_dir_{i}" for i in range(len(REQS_DIR_CASES))])
def test_reqs_dir(tmp_path: Path, file_map: dict, expected: tuple):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == expected[0]
    assert reqs == expected[1]
    assert pkgs == expected[2]


REQS_DIR_NON_TXT_ONLY_CASES = [
    {"requirements/base.cfg": "numpy"},
    {"requirements/base.ini": "numpy"},
    {"requirements/base.in": "numpy"},
    {"requirements/base.pip": "numpy"},
    {"requirements/README.md": "info"},
    {"requirements/.gitkeep": ""},
    {"requirements/base.yml": "deps"},
    {"requirements/Makefile": "all:"},
    {"requirements/base.cfg": "x", "requirements/dev.ini": "y"},
    {"requirements/base.in": "x", "requirements/dev.pip": "y"},
]


@pytest.mark.parametrize("file_map", REQS_DIR_NON_TXT_ONLY_CASES,
                         ids=[f"reqs_dir_nontxt_{i}" for i in range(len(REQS_DIR_NON_TXT_ONLY_CASES))])
def test_reqs_dir_non_txt_only_fallback(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == ""
    assert reqs == []
    assert pkgs == []


REQS_DIR_MIXED_TXT_NONTXT = []
for i in range(10):
    REQS_DIR_MIXED_TXT_NONTXT.append((
        {f"requirements/base.txt": "numpy", f"requirements/extra_{i}.cfg": "pandas"},
        ("requirements.txt", ["requirements/base.txt"], []),
    ))


@pytest.mark.parametrize("file_map,expected", REQS_DIR_MIXED_TXT_NONTXT,
                         ids=[f"reqs_dir_mixed_{i}" for i in range(len(REQS_DIR_MIXED_TXT_NONTXT))])
def test_reqs_dir_mixed_txt_nontxt(tmp_path: Path, file_map: dict, expected: tuple):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == expected[0]
    assert reqs == expected[1]
    assert pkgs == expected[2]


def test_reqs_dir_empty_dir_fallback(tmp_path: Path):
    _mkdir(tmp_path, "requirements")
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == ""
    assert reqs == []
    assert pkgs == []


# ===================================================================
# 5. pyproject.toml project.dependencies  ~150 cases
# ===================================================================

PYPROJECT_DEPS_CASES = []

single_deps = [
    "numpy", "pandas", "scipy", "matplotlib", "requests", "flask",
    "django", "fastapi", "sqlalchemy", "pydantic", "pytest", "click",
    "rich", "httpx", "aiohttp", "celery", "redis", "boto3",
    "pillow", "cryptography",
]
for dep in single_deps:
    toml_content = f'[project]\nname = "mypkg"\ndependencies = ["{dep}"]'
    PYPROJECT_DEPS_CASES.append((toml_content, ("", [], [dep])))

versioned_deps = [
    ("numpy>=1.21", ["numpy>=1.21"]),
    ("numpy>=1.21,<2.0", ["numpy>=1.21,<2.0"]),
    ("numpy~=1.21", ["numpy~=1.21"]),
    ("numpy==1.21.0", ["numpy==1.21.0"]),
    ("numpy!=1.20", ["numpy!=1.20"]),
    ("pandas>=1.3.0", ["pandas>=1.3.0"]),
    ("scipy>=1.7.3", ["scipy>=1.7.3"]),
    ("requests[security]>=2.28", ["requests[security]>=2.28"]),
    ("flask[async]", ["flask[async]"]),
    ("Django>=3.2,<4.0", ["Django>=3.2,<4.0"]),
]
for dep_str, expected_list in versioned_deps:
    toml_content = f'[project]\nname = "mypkg"\ndependencies = ["{dep_str}"]'
    PYPROJECT_DEPS_CASES.append((toml_content, ("", [], expected_list)))

multi_deps_combos = [
    (["numpy", "pandas"], ["numpy", "pandas"]),
    (["numpy", "pandas", "scipy"], ["numpy", "pandas", "scipy"]),
    (["flask", "gunicorn", "redis"], ["flask", "gunicorn", "redis"]),
    (["pytest", "pytest-cov", "pytest-xdist"], ["pytest", "pytest-cov", "pytest-xdist"]),
    (["numpy>=1.21", "pandas>=1.3"], ["numpy>=1.21", "pandas>=1.3"]),
    (["torch>=1.10", "torchvision>=0.11"], ["torch>=1.10", "torchvision>=0.11"]),
]
for deps_list, expected_list in multi_deps_combos:
    deps_str = ", ".join(f'"{d}"' for d in deps_list)
    toml_content = f'[project]\nname = "mypkg"\ndependencies = [{deps_str}]'
    PYPROJECT_DEPS_CASES.append((toml_content, ("", [], expected_list)))

for i in range(60):
    dep = f"auto-dep-{i}>=0.{i}.0"
    toml_content = f'[project]\nname = "gen"\ndependencies = ["{dep}"]'
    PYPROJECT_DEPS_CASES.append((toml_content, ("", [], [dep])))

for i in range(20):
    deps = [f"gen-pkg-{i}-{j}" for j in range(3)]
    deps_str = ", ".join(f'"{d}"' for d in deps)
    toml_content = f'[project]\nname = "gen"\ndependencies = [{deps_str}]'
    PYPROJECT_DEPS_CASES.append((toml_content, ("", [], deps)))


@pytest.mark.parametrize("toml_content,expected", PYPROJECT_DEPS_CASES,
                         ids=[f"pyproject_deps_{i}" for i in range(len(PYPROJECT_DEPS_CASES))])
def test_pyproject_deps(tmp_path: Path, toml_content: str, expected: tuple):
    _write(tmp_path, "pyproject.toml", toml_content.replace("\\n", "\n"))
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == expected[0]
    assert reqs == expected[1]
    assert pkgs == expected[2]


PYPROJECT_NO_DEPS_CASES = [
    '[project]\nname = "mypkg"',
    '[project]\nname = "mypkg"\ndependencies = []',
    '[build-system]\nrequires = ["setuptools"]',
    '[tool.pytest.ini_options]\naddopts = "-v"',
    '',
    '[project]\nname = "mypkg"\nversion = "1.0"',
    '[project]\nname = "mypkg"\n[project.optional-dependencies]\ndev = ["pytest"]',
    '# just a comment',
]

for i in range(22):
    PYPROJECT_NO_DEPS_CASES.append(f'[project]\nname = "no_deps_{i}"\nversion = "{i}.0"')


@pytest.mark.parametrize("toml_content", PYPROJECT_NO_DEPS_CASES,
                         ids=[f"pyproject_nodeps_{i}" for i in range(len(PYPROJECT_NO_DEPS_CASES))])
def test_pyproject_no_deps_fallback(tmp_path: Path, toml_content: str):
    _write(tmp_path, "pyproject.toml", toml_content.replace("\\n", "\n"))
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == ""
    assert reqs == []
    assert pkgs == []


# ===================================================================
# 6. Fallback → ("", [], [])  ~50 cases
# ===================================================================

FALLBACK_FILE_SETS = [
    {},
    {"setup.py": "from setuptools import setup\nsetup()"},
    {"setup.cfg": "[metadata]\nname = pkg"},
    {"Makefile": "all:\n\techo hello"},
    {"README.md": "# My Project"},
    {"LICENSE": "MIT"},
    {".gitignore": "*.pyc"},
    {"src/main.py": "print('hello')"},
    {"tox.ini": "[tox]\nenvlist = py39"},
    {"Dockerfile": "FROM python:3.9"},
    {".github/workflows/ci.yml": "name: CI"},
    {"docs/index.rst": "Welcome"},
    {"setup.py": "setup()", "setup.cfg": "[metadata]\nname = x"},
    {"Makefile": "test:", "README.md": "# Readme"},
    {"src/__init__.py": "", "src/app.py": "pass"},
    {".pre-commit-config.yaml": "repos: []"},
    {"MANIFEST.in": "include *.txt"},
    {"CHANGELOG.md": "# Changes"},
    {"conftest.py": "import pytest"},
    {"mypy.ini": "[mypy]\nstrict = true"},
]

for i in range(30):
    FALLBACK_FILE_SETS.append({f"src/module_{i}.py": f"# module {i}"})


@pytest.mark.parametrize("file_map", FALLBACK_FILE_SETS,
                         ids=[f"fallback_{i}" for i in range(len(FALLBACK_FILE_SETS))])
def test_fallback(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == ""
    assert reqs == []
    assert pkgs == []


# ===================================================================
# 7. Priority cascade  ~150 cases
# ===================================================================

PRIORITY_ENV_YML_OVER_REQS_TXT = []
for i in range(25):
    PRIORITY_ENV_YML_OVER_REQS_TXT.append({
        "environment.yml": f"name: env_{i}",
        "requirements.txt": f"pkg-{i}",
    })


@pytest.mark.parametrize("file_map", PRIORITY_ENV_YML_OVER_REQS_TXT,
                         ids=[f"prio_yml_over_reqs_{i}" for i in range(len(PRIORITY_ENV_YML_OVER_REQS_TXT))])
def test_priority_env_yml_over_reqs_txt(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yml"
    assert reqs == []
    assert pkgs == []


PRIORITY_ENV_YML_OVER_REQS_DIR = []
for i in range(15):
    PRIORITY_ENV_YML_OVER_REQS_DIR.append({
        "environment.yml": f"name: env_{i}",
        f"requirements/base.txt": f"pkg-{i}",
    })


@pytest.mark.parametrize("file_map", PRIORITY_ENV_YML_OVER_REQS_DIR,
                         ids=[f"prio_yml_over_reqsdir_{i}" for i in range(len(PRIORITY_ENV_YML_OVER_REQS_DIR))])
def test_priority_env_yml_over_reqs_dir(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yml"
    assert reqs == []
    assert pkgs == []


PRIORITY_ENV_YML_OVER_PYPROJECT = []
for i in range(15):
    PRIORITY_ENV_YML_OVER_PYPROJECT.append({
        "environment.yml": f"name: env_{i}",
        "pyproject.toml": f'[project]\nname = "pkg"\ndependencies = ["dep-{i}"]',
    })


@pytest.mark.parametrize("file_map", PRIORITY_ENV_YML_OVER_PYPROJECT,
                         ids=[f"prio_yml_over_pyproject_{i}" for i in range(len(PRIORITY_ENV_YML_OVER_PYPROJECT))])
def test_priority_env_yml_over_pyproject(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yml"
    assert reqs == []
    assert pkgs == []


PRIORITY_ENV_YAML_OVER_REQS_TXT = []
for i in range(15):
    PRIORITY_ENV_YAML_OVER_REQS_TXT.append({
        "environment.yaml": f"name: env_{i}",
        "requirements.txt": f"pkg-{i}",
    })


@pytest.mark.parametrize("file_map", PRIORITY_ENV_YAML_OVER_REQS_TXT,
                         ids=[f"prio_yaml_over_reqs_{i}" for i in range(len(PRIORITY_ENV_YAML_OVER_REQS_TXT))])
def test_priority_env_yaml_over_reqs_txt(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yaml"
    assert reqs == []
    assert pkgs == []


PRIORITY_ENV_YML_OVER_YAML = []
for i in range(15):
    PRIORITY_ENV_YML_OVER_YAML.append({
        "environment.yml": f"name: yml_{i}",
        "environment.yaml": f"name: yaml_{i}",
    })


@pytest.mark.parametrize("file_map", PRIORITY_ENV_YML_OVER_YAML,
                         ids=[f"prio_yml_over_yaml_{i}" for i in range(len(PRIORITY_ENV_YML_OVER_YAML))])
def test_priority_env_yml_over_yaml(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yml"
    assert reqs == []
    assert pkgs == []


PRIORITY_REQS_TXT_OVER_REQS_DIR = []
for i in range(15):
    PRIORITY_REQS_TXT_OVER_REQS_DIR.append({
        "requirements.txt": f"main-pkg-{i}",
        f"requirements/base.txt": f"base-pkg-{i}",
    })


@pytest.mark.parametrize("file_map", PRIORITY_REQS_TXT_OVER_REQS_DIR,
                         ids=[f"prio_reqstxt_over_reqsdir_{i}" for i in range(len(PRIORITY_REQS_TXT_OVER_REQS_DIR))])
def test_priority_reqs_txt_over_reqs_dir(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "requirements.txt"
    assert reqs == ["requirements.txt"]
    assert pkgs == []


PRIORITY_REQS_TXT_OVER_PYPROJECT = []
for i in range(15):
    PRIORITY_REQS_TXT_OVER_PYPROJECT.append({
        "requirements.txt": f"main-pkg-{i}",
        "pyproject.toml": f'[project]\nname = "pkg"\ndependencies = ["dep-{i}"]',
    })


@pytest.mark.parametrize("file_map", PRIORITY_REQS_TXT_OVER_PYPROJECT,
                         ids=[f"prio_reqstxt_over_pyproject_{i}" for i in range(len(PRIORITY_REQS_TXT_OVER_PYPROJECT))])
def test_priority_reqs_txt_over_pyproject(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "requirements.txt"
    assert reqs == ["requirements.txt"]
    assert pkgs == []


PRIORITY_REQS_DIR_OVER_PYPROJECT = []
for i in range(15):
    PRIORITY_REQS_DIR_OVER_PYPROJECT.append({
        f"requirements/base.txt": f"dir-pkg-{i}",
        "pyproject.toml": f'[project]\nname = "pkg"\ndependencies = ["dep-{i}"]',
    })


@pytest.mark.parametrize("file_map", PRIORITY_REQS_DIR_OVER_PYPROJECT,
                         ids=[f"prio_reqsdir_over_pyproject_{i}" for i in range(len(PRIORITY_REQS_DIR_OVER_PYPROJECT))])
def test_priority_reqs_dir_over_pyproject(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "requirements.txt"
    assert reqs == ["requirements/base.txt"]
    assert pkgs == []


PRIORITY_ALL_PRESENT = []
for i in range(10):
    PRIORITY_ALL_PRESENT.append({
        "environment.yml": f"name: all_{i}",
        "environment.yaml": f"name: all_yaml_{i}",
        "requirements.txt": f"all-req-{i}",
        f"requirements/base.txt": f"all-dir-{i}",
        "pyproject.toml": f'[project]\nname = "all"\ndependencies = ["dep-{i}"]',
    })


@pytest.mark.parametrize("file_map", PRIORITY_ALL_PRESENT,
                         ids=[f"prio_all_{i}" for i in range(len(PRIORITY_ALL_PRESENT))])
def test_priority_all_present(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yml"
    assert reqs == []
    assert pkgs == []


PRIORITY_ENV_YAML_OVER_REQS_DIR = []
for i in range(5):
    PRIORITY_ENV_YAML_OVER_REQS_DIR.append({
        "environment.yaml": f"name: env_{i}",
        f"requirements/dev.txt": f"pkg-{i}",
    })


@pytest.mark.parametrize("file_map", PRIORITY_ENV_YAML_OVER_REQS_DIR,
                         ids=[f"prio_yaml_over_reqsdir_{i}" for i in range(len(PRIORITY_ENV_YAML_OVER_REQS_DIR))])
def test_priority_env_yaml_over_reqs_dir(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yaml"
    assert reqs == []
    assert pkgs == []


PRIORITY_ENV_YAML_OVER_PYPROJECT = []
for i in range(5):
    PRIORITY_ENV_YAML_OVER_PYPROJECT.append({
        "environment.yaml": f"name: env_{i}",
        "pyproject.toml": f'[project]\nname = "p"\ndependencies = ["d-{i}"]',
    })


@pytest.mark.parametrize("file_map", PRIORITY_ENV_YAML_OVER_PYPROJECT,
                         ids=[f"prio_yaml_over_pyproject_{i}" for i in range(len(PRIORITY_ENV_YAML_OVER_PYPROJECT))])
def test_priority_env_yaml_over_pyproject(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yaml"
    assert reqs == []
    assert pkgs == []


PRIORITY_NO_YML_NO_YAML_NO_REQS_TXT_REQS_DIR_AND_PYPROJECT = []
for i in range(5):
    PRIORITY_NO_YML_NO_YAML_NO_REQS_TXT_REQS_DIR_AND_PYPROJECT.append({
        f"requirements/base.txt": f"dir-pkg-{i}",
        f"requirements/dev.txt": f"dir-dev-{i}",
        "pyproject.toml": f'[project]\nname = "p"\ndependencies = ["dep-{i}"]',
    })


@pytest.mark.parametrize("file_map", PRIORITY_NO_YML_NO_YAML_NO_REQS_TXT_REQS_DIR_AND_PYPROJECT,
                         ids=[f"prio_reqsdir_multi_over_pyproject_{i}" for i in range(len(PRIORITY_NO_YML_NO_YAML_NO_REQS_TXT_REQS_DIR_AND_PYPROJECT))])
def test_priority_reqs_dir_multi_over_pyproject(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "requirements.txt"
    assert reqs == ["requirements/base.txt", "requirements/dev.txt"]
    assert pkgs == []


PRIORITY_ENV_YML_OVER_EVERYTHING = []
for i in range(5):
    PRIORITY_ENV_YML_OVER_EVERYTHING.append({
        "environment.yml": f"name: e_{i}",
        "environment.yaml": f"name: ea_{i}",
        "requirements.txt": f"r-{i}",
        f"requirements/base.txt": f"rb-{i}",
        f"requirements/dev.txt": f"rd-{i}",
        "pyproject.toml": f'[project]\nname = "p"\ndependencies = ["d-{i}"]',
        "setup.py": "from setuptools import setup\nsetup()",
    })


@pytest.mark.parametrize("file_map", PRIORITY_ENV_YML_OVER_EVERYTHING,
                         ids=[f"prio_yml_over_everything_{i}" for i in range(len(PRIORITY_ENV_YML_OVER_EVERYTHING))])
def test_priority_env_yml_over_everything(tmp_path: Path, file_map: dict):
    for relpath, content in file_map.items():
        _write(tmp_path, relpath, content)
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == "environment.yml"
    assert reqs == []
    assert pkgs == []


def test_reqs_dir_is_file_not_dir(tmp_path: Path):
    _write(tmp_path, "requirements", "not a directory")
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == ""
    assert reqs == []
    assert pkgs == []


def test_pyproject_deps_not_list_string(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "p"\ndependencies = "numpy"')
    src, reqs, pkgs = detect_packages_source(tmp_path)
    assert src == ""
    assert reqs == []
    assert pkgs == []
