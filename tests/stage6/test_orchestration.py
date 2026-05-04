"""~200 parametrized tests for detect_all_specs() orchestration logic."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import detect_all_specs

ALL_KEYS = {
    "python_version",
    "install_cmd",
    "test_cmd_override",
    "packages_source",
    "pip_packages",
    "pre_install_cmds",
    "reqs_paths",
    "env_yml_paths",
    "log_parser_type",
    "version",
    "_license",
}

DEFAULTS = {
    "python_version": "3.10",
    "install_cmd": "pip install -e .",
    "test_cmd_override": "pytest {test_files}",
    "packages_source": "",
    "pip_packages": [],
    "pre_install_cmds": [],
    "reqs_paths": [],
    "env_yml_paths": [],
    "log_parser_type": "pytest",
    "version": None,
    "_license": None,
}


def _write(repo: Path, relpath: str, content: str) -> None:
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# 1. Empty repo → all defaults  (~20 cases)
# ═══════════════════════════════════════════════════════════════════════

_EMPTY_REPO_NAMES = [
    "owner/repo",
    "org/my-package",
    "user/pkg_name",
    "company/tool",
    "dev/lib-foo",
    "alice/bob",
    "x/y",
    "long-org-name/long-repo-name",
    "UPPER/CASE",
    "MiXeD/CaSe-Pkg",
    "owner/repo123",
    "org/my_pkg_v2",
    "user/a-b-c-d",
    "dev/single",
    "company/multi-word-name",
    "test/empty",
    "foo/bar",
    "baz/qux",
    "numpy/numpy",
    "pandas-dev/pandas",
]


@pytest.mark.parametrize("repo_name", _EMPTY_REPO_NAMES, ids=[r.replace("/", "_") for r in _EMPTY_REPO_NAMES])
def test_empty_repo_defaults(tmp_path: Path, repo_name: str):
    result = detect_all_specs(tmp_path, repo_name)
    for key, default in DEFAULTS.items():
        assert result[key] == default, f"{key}: expected {default!r}, got {result[key]!r}"


# ═══════════════════════════════════════════════════════════════════════
# 2. Minimal Python project  (~30 cases)
# ═══════════════════════════════════════════════════════════════════════

_MINIMAL_PYPROJECT_CASES = [
    pytest.param(
        '[project]\nname = "mypkg"\nversion = "1.0.0"\nrequires-python = ">=3.9"\n',
        {"python_version": "3.9", "version": "1.0.0", "install_cmd": "pip install -e ."},
        id="pyproject-version-python",
    ),
    pytest.param(
        '[project]\nname = "mypkg"\nversion = "2.3.4"\n',
        {"python_version": "3.10", "version": "2.3.4"},
        id="pyproject-version-only",
    ),
    pytest.param(
        '[project]\nname = "mypkg"\nrequires-python = ">=3.8"\n',
        {"python_version": "3.8", "version": None},
        id="pyproject-python-only",
    ),
    pytest.param(
        '[build-system]\nrequires = ["setuptools"]\n[project]\nname = "x"\nversion = "0.1.0"\n',
        {"install_cmd": "pip install -e .", "version": "0.1.0"},
        id="pyproject-setuptools-version",
    ),
    pytest.param(
        '[build-system]\nrequires = ["flit-core>=3.2"]\n[project]\nname = "x"\nversion = "0.5.0"\n',
        {"install_cmd": "pip install -e .", "version": "0.5.0"},
        id="pyproject-flit-version",
    ),
    pytest.param(
        '[build-system]\nrequires = ["hatchling"]\n[project]\nname = "x"\nversion = "3.0.0"\n',
        {"install_cmd": "pip install -e .", "version": "3.0.0"},
        id="pyproject-hatchling-version",
    ),
    pytest.param(
        '[build-system]\nrequires = ["poetry-core"]\n[project]\nname = "x"\nversion = "1.2.3"\n',
        {"install_cmd": "pip install -e .", "version": "1.2.3"},
        id="pyproject-poetry-version",
    ),
    pytest.param(
        '[build-system]\nrequires = ["pdm-backend"]\n[project]\nname = "x"\nversion = "0.9.0"\n',
        {"install_cmd": "pip install -e .", "version": "0.9.0"},
        id="pyproject-pdm-version",
    ),
    pytest.param(
        '[tool.pytest.ini_options]\naddopts = "-v"\n',
        {"test_cmd_override": "pytest {test_files}", "log_parser_type": "pytest"},
        id="pyproject-pytest-config",
    ),
    pytest.param(
        '[project]\nname = "x"\nversion = "1.0.0"\nrequires-python = ">=3.11"\n\n[tool.pytest.ini_options]\naddopts = "-v"\n',
        {"python_version": "3.11", "version": "1.0.0", "test_cmd_override": "pytest {test_files}"},
        id="pyproject-full-no-buildsys",
    ),
]


@pytest.mark.parametrize("content,expected_subset", _MINIMAL_PYPROJECT_CASES)
def test_minimal_pyproject(tmp_path: Path, content: str, expected_subset: dict):
    _write(tmp_path, "pyproject.toml", content)
    result = detect_all_specs(tmp_path, "owner/mypkg")
    for key, val in expected_subset.items():
        assert result[key] == val, f"{key}: expected {val!r}, got {result[key]!r}"


_MINIMAL_SETUP_PY_CASES = [
    pytest.param(
        'from setuptools import setup\nsetup(name="pkg", version="1.0.0")\n',
        {"install_cmd": "pip install -e .", "version": "1.0.0"},
        id="setup-py-basic",
    ),
    pytest.param(
        'from setuptools import setup\nsetup(name="pkg", version="2.0.0", python_requires=">=3.9")\n',
        {"python_version": "3.9", "version": "2.0.0"},
        id="setup-py-python-requires",
    ),
    pytest.param(
        'from setuptools import setup\nsetup(name="pkg")\n',
        {"install_cmd": "pip install -e .", "version": None},
        id="setup-py-no-version",
    ),
    pytest.param(
        'from setuptools import setup, Extension\next = Extension("mod", sources=["mod.c"])\nsetup(name="pkg", ext_modules=[ext])\n',
        {"install_cmd": "pip install -e ."},
        id="setup-py-c-extension",
    ),
    pytest.param(
        'from distutils.core import setup\nsetup(name="pkg", version="0.5")\n',
        {"install_cmd": "pip install -e .", "version": "0.5"},
        id="setup-py-distutils",
    ),
]


@pytest.mark.parametrize("content,expected_subset", _MINIMAL_SETUP_PY_CASES)
def test_minimal_setup_py(tmp_path: Path, content: str, expected_subset: dict):
    _write(tmp_path, "setup.py", content)
    result = detect_all_specs(tmp_path, "owner/pkg")
    for key, val in expected_subset.items():
        assert result[key] == val, f"{key}: expected {val!r}, got {result[key]!r}"


_MINIMAL_SETUP_CFG_CASES = [
    pytest.param(
        "[metadata]\nname = pkg\nversion = 1.0.0\n",
        {"install_cmd": "pip install -e .", "version": "1.0.0"},
        id="cfg-basic",
    ),
    pytest.param(
        "[metadata]\nname = pkg\nversion = 2.5.0\n\n[options]\npython_requires = >=3.9\n",
        {"python_version": "3.9", "version": "2.5.0"},
        id="cfg-python-requires",
    ),
    pytest.param(
        "[metadata]\nname = pkg\n\n[tool:pytest]\naddopts = -v\n",
        {"test_cmd_override": "pytest {test_files}"},
        id="cfg-pytest-section",
    ),
    pytest.param(
        "[metadata]\nname = pkg\nversion = 0.1\n",
        {"version": "0.1"},
        id="cfg-short-version",
    ),
    pytest.param(
        "[metadata]\nname = pkg\nversion = 3.2.1\nlicense = MIT\n",
        {"version": "3.2.1"},
        id="cfg-with-license-meta",
    ),
    pytest.param(
        "[metadata]\nname = pkg\nversion = attr: pkg.__version__\n",
        {"version": None},
        id="cfg-attr-version-skipped",
    ),
    pytest.param(
        "[metadata]\nname = pkg\nversion = file: VERSION\n",
        {"version": None},
        id="cfg-file-version-skipped",
    ),
    pytest.param(
        "[metadata]\nname = pkg\n",
        {"install_cmd": "pip install -e .", "version": None},
        id="cfg-no-version",
    ),
    pytest.param(
        "[options]\npackages = find:\n",
        {"install_cmd": "pip install -e ."},
        id="cfg-no-metadata",
    ),
    pytest.param(
        "[metadata]\nname = pkg\nversion = 4.0.0\n\n[options]\npython_requires = >=3.12\n\n[tool:pytest]\naddopts = -v\n",
        {"python_version": "3.12", "version": "4.0.0", "test_cmd_override": "pytest {test_files}"},
        id="cfg-full-featured",
    ),
]


@pytest.mark.parametrize("content,expected_subset", _MINIMAL_SETUP_CFG_CASES)
def test_minimal_setup_cfg(tmp_path: Path, content: str, expected_subset: dict):
    _write(tmp_path, "setup.cfg", content)
    result = detect_all_specs(tmp_path, "owner/pkg")
    for key, val in expected_subset.items():
        assert result[key] == val, f"{key}: expected {val!r}, got {result[key]!r}"


# ═══════════════════════════════════════════════════════════════════════
# 3. Full-featured repos  (~50 cases)
# ═══════════════════════════════════════════════════════════════════════

_NUMPY_LIKE_PYPROJECT = """\
[build-system]
requires = ["meson-python>=0.12.0", "numpy>=1.20", "cython>=0.29"]

[project]
name = "scipy"
version = "1.12.0"
requires-python = ">=3.9"
dependencies = ["numpy>=1.20"]
license = {text = "BSD-3-Clause"}

[tool.pytest.ini_options]
addopts = "-v"
"""

_FLASK_LIKE_PYPROJECT = """\
[build-system]
requires = ["setuptools", "wheel"]

[project]
name = "flask"
version = "3.0.0"
requires-python = ">=3.8"
dependencies = ["werkzeug>=3.0", "jinja2>=3.1", "click>=8.1"]
license = {text = "MIT"}

[tool.pytest.ini_options]
addopts = "-v"
"""

_DJANGO_LIKE = {
    "setup.py": 'from setuptools import setup\nsetup(name="django", version="5.0.0", python_requires=">=3.10")\n',
}

_FULL_FEATURED_CASES: list[tuple[str, dict[str, str], str, dict[str, Any]]] = []

_MESON_VARIANTS = [
    ("meson-python>=0.12.0", "1.12.0", "3.9"),
    ("meson-python>=0.13", "2.0.0", "3.10"),
    ("meson-python>=1.0", "0.5.0", "3.8"),
    ("mesonpy>=0.5", "1.0.0", "3.9"),
    ("scikit-build>=0.15", "3.0.0", "3.8"),
    ("scikit-build-core>=0.5", "1.5.0", "3.9"),
]

for i, (meson_req, ver, pyver) in enumerate(_MESON_VARIANTS):
    _FULL_FEATURED_CASES.append((
        f"numpy-like-{i}",
        {
            "pyproject.toml": (
                f'[build-system]\nrequires = ["{meson_req}", "numpy>=1.20", "cython>=0.29"]\n\n'
                f'[project]\nname = "pkg"\nversion = "{ver}"\nrequires-python = ">={pyver}"\n'
                f'dependencies = ["numpy>=1.20"]\n\n[tool.pytest.ini_options]\naddopts = "-v"\n'
            ),
        },
        "owner/pkg",
        {
            "python_version": pyver,
            "install_cmd": "pip install --no-build-isolation -e .",
            "test_cmd_override": "pytest {test_files}",
            "version": ver,
            "log_parser_type": "pytest",
            "pip_packages": ["numpy>=1.20"],
            "packages_source": "",
        },
    ))

_FLASK_VARIANTS = [
    ("3.0.0", "3.8", ["werkzeug>=3.0", "jinja2>=3.1"]),
    ("2.3.0", "3.8", ["werkzeug>=2.3", "jinja2>=3.1", "click>=8.1"]),
    ("1.0.0", "3.7", ["werkzeug>=1.0"]),
]

for i, (ver, pyver, deps) in enumerate(_FLASK_VARIANTS):
    deps_str = ", ".join(f'"{d}"' for d in deps)
    _FULL_FEATURED_CASES.append((
        f"flask-like-{i}",
        {
            "pyproject.toml": (
                f'[build-system]\nrequires = ["setuptools", "wheel"]\n\n'
                f'[project]\nname = "flask"\nversion = "{ver}"\nrequires-python = ">={pyver}"\n'
                f'dependencies = [{deps_str}]\nlicense = {{text = "MIT"}}\n\n'
                f'[tool.pytest.ini_options]\naddopts = "-v"\n'
            ),
            "LICENSE": "MIT License\n\nPermission is hereby granted...",
        },
        "pallets/flask",
        {
            "python_version": pyver,
            "install_cmd": "pip install -e .",
            "version": ver,
            "_license": "MIT",
            "pip_packages": list(deps),
            "log_parser_type": "pytest",
        },
    ))

_DJANGO_VARIANTS = [
    ("5.0.0", "3.10"),
    ("4.2.0", "3.8"),
    ("3.2.0", "3.6"),
]

for i, (ver, pyver) in enumerate(_DJANGO_VARIANTS):
    _FULL_FEATURED_CASES.append((
        f"django-like-{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="django", version="{ver}", python_requires=">={pyver}")\n',
            "LICENSE": "BSD 3-Clause License\n\nRedistribution and use in source and binary forms, with or without modification, are permitted provided that the following three conditions are met...",
        },
        "django/django",
        {
            "python_version": pyver,
            "install_cmd": "pip install -e .",
            "version": ver,
            "_license": "BSD-3-Clause",
        },
    ))

_FULL_FEATURED_CASES.append((
    "numpy-like-fortran",
    {
        "pyproject.toml": (
            '[build-system]\nrequires = ["meson-python>=0.12.0"]\n\n'
            '[project]\nname = "scipy"\nversion = "1.12.0"\nrequires-python = ">=3.9"\n\n'
            '[tool.pytest.ini_options]\naddopts = "-v"\n'
        ),
        "meson.build": "project('scipy', 'c', 'fortran')\n",
        "core/special.f90": "! Fortran source\nsubroutine foo()\nend subroutine\n",
    },
    "scipy/scipy",
    {
        "python_version": "3.9",
        "install_cmd": "pip install --no-build-isolation -e .",
        "version": "1.12.0",
        "pre_install_cmds": [
            "apt-get install -y build-essential",
            "apt-get install -y meson ninja-build",
            "apt-get install -y gfortran",
        ],
    },
))

_FULL_FEATURED_CASES.append((
    "numpy-like-blas",
    {
        "pyproject.toml": (
            '[build-system]\nrequires = ["meson-python>=0.12.0"]\n\n'
            '[project]\nname = "numpy"\nversion = "2.0.0"\nrequires-python = ">=3.9"\n'
            '# openblas dependency\n\n'
            '[tool.pytest.ini_options]\naddopts = "-v"\n'
        ),
        "meson.build": "project('numpy', 'c')\n",
    },
    "numpy/numpy",
    {
        "install_cmd": "pip install --no-build-isolation -e .",
        "pre_install_cmds": [
            "apt-get install -y build-essential",
            "apt-get install -y meson ninja-build",
            "apt-get install -y libopenblas-dev",
        ],
    },
))

_FULL_FEATURED_CASES.append((
    "meson-fortran-blas",
    {
        "pyproject.toml": (
            '[build-system]\nrequires = ["meson-python>=0.12.0"]\n\n'
            '[project]\nname = "scipy"\nversion = "1.13.0"\nrequires-python = ">=3.9"\n'
            '# requires blas/lapack\n\n'
            '[tool.pytest.ini_options]\naddopts = "-v"\n'
        ),
        "meson.build": "project('scipy', 'c', 'fortran')\n",
        "linalg/solve.f90": "subroutine solve()\nend subroutine\n",
    },
    "scipy/scipy",
    {
        "pre_install_cmds": [
            "apt-get install -y build-essential",
            "apt-get install -y meson ninja-build",
            "apt-get install -y gfortran",
            "apt-get install -y libopenblas-dev",
        ],
    },
))

_FULL_FEATURED_CASES.append((
    "c-extension-setup-py",
    {
        "setup.py": 'from setuptools import setup, Extension\next = Extension("mod", sources=["mod.c"])\nsetup(name="pkg", ext_modules=[ext], version="1.0.0")\n',
    },
    "owner/pkg",
    {
        "install_cmd": "pip install -e .",
        "pre_install_cmds": ["apt-get install -y build-essential"],
        "version": "1.0.0",
    },
))

_FULL_FEATURED_CASES.append((
    "cython-setup-py",
    {
        "setup.py": 'from Cython.Build import cythonize\nfrom setuptools import setup\nsetup(name="pkg", ext_modules=cythonize("*.pyx"), version="0.5.0")\n',
    },
    "owner/pkg",
    {
        "pre_install_cmds": ["apt-get install -y build-essential"],
        "version": "0.5.0",
    },
))

_FULL_FEATURED_CASES.append((
    "requirements-txt-project",
    {
        "setup.py": 'from setuptools import setup\nsetup(name="pkg", version="1.0.0")\n',
        "requirements.txt": "numpy>=1.20\npandas>=1.3\n",
    },
    "owner/pkg",
    {
        "packages_source": "requirements.txt",
        "reqs_paths": ["requirements.txt"],
        "pip_packages": [],
        "version": "1.0.0",
    },
))

_FULL_FEATURED_CASES.append((
    "requirements-dir-project",
    {
        "setup.py": 'from setuptools import setup\nsetup(name="pkg", version="2.0.0")\n',
        "requirements/base.txt": "numpy\n",
        "requirements/dev.txt": "pytest\n",
    },
    "owner/pkg",
    {
        "packages_source": "requirements.txt",
        "reqs_paths": ["requirements/base.txt", "requirements/dev.txt"],
        "version": "2.0.0",
    },
))

for i, lic_data in enumerate([
    ("MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files, to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:", "MIT"),
    ("Apache License\nVersion 2.0, January 2004", "Apache-2.0"),
    ("BSD 3-Clause License\n\nRedistribution and use in source and binary forms, with or without modification, are permitted provided that the following three conditions are met:", "BSD-3-Clause"),
    ("BSD 2-Clause Simplified BSD License", "BSD-2-Clause"),
    ("ISC License\n\nCopyright (c) 2024", "ISC"),
]):
    lic_text, lic_name = lic_data
    _FULL_FEATURED_CASES.append((
        f"license-file-{lic_name}",
        {
            "setup.py": 'from setuptools import setup\nsetup(name="pkg")\n',
            "LICENSE": lic_text,
        },
        "owner/pkg",
        {"_license": lic_name},
    ))

_FULL_FEATURED_CASES.append((
    "test-dir-tests",
    {
        "setup.py": 'from setuptools import setup\nsetup(name="pkg")\n',
        "tests/__init__.py": "",
        "tests/test_basic.py": "def test_one(): pass\n",
    },
    "owner/pkg",
    {
        "test_cmd_override": "pytest tests/",
        "log_parser_type": "pytest",
    },
))

_FULL_FEATURED_CASES.append((
    "test-dir-test",
    {
        "setup.py": 'from setuptools import setup\nsetup(name="pkg")\n',
        "test/__init__.py": "",
        "test/test_basic.py": "def test_one(): pass\n",
    },
    "owner/pkg",
    {
        "test_cmd_override": "pytest test/",
        "log_parser_type": "pytest",
    },
))

_FULL_FEATURED_CASES.append((
    "tox-pytest-cmd",
    {
        "tox.ini": "[testenv]\ncommands = pytest tests/\n",
    },
    "owner/pkg",
    {
        "test_cmd_override": "pytest {test_files}",
        "log_parser_type": "pytest",
    },
))

_FULL_FEATURED_CASES.append((
    "pyproject-deps-no-reqs",
    {
        "pyproject.toml": (
            '[project]\nname = "x"\nversion = "1.0.0"\n'
            'dependencies = ["requests>=2.28", "click>=8.0"]\n'
        ),
    },
    "owner/x",
    {
        "packages_source": "",
        "pip_packages": ["requests>=2.28", "click>=8.0"],
        "reqs_paths": [],
    },
))

_FULL_FEATURED_CASES.append((
    "pyproject-license-text-mit",
    {
        "pyproject.toml": (
            '[project]\nname = "x"\nversion = "1.0.0"\n'
            'license = {text = "MIT"}\n'
        ),
    },
    "owner/x",
    {"_license": "MIT"},
))

_FULL_FEATURED_CASES.append((
    "python-version-file",
    {
        ".python-version": "3.11.5\n",
        "setup.py": 'from setuptools import setup\nsetup(name="pkg")\n',
    },
    "owner/pkg",
    {"python_version": "3.11"},
))

_FULL_FEATURED_CASES.append((
    "python-version-file-priority",
    {
        ".python-version": "3.12.0\n",
        "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.8"\n',
    },
    "owner/x",
    {"python_version": "3.12"},
))

_FULL_FEATURED_CASES.append((
    "version-file-fallback",
    {
        "VERSION": "5.0.0\n",
    },
    "owner/nonexistent_pkg_xyz",
    {"version": "5.0.0"},
))

_FULL_FEATURED_CASES.append((
    "version-txt-fallback",
    {
        "version.txt": "3.2.1\n",
    },
    "owner/nonexistent_pkg_xyz",
    {"version": "3.2.1"},
))

_FULL_FEATURED_CASES.append((
    "init-version-fallback",
    {
        "mypkg/__init__.py": '__version__ = "7.0.0"\n',
    },
    "owner/mypkg",
    {"version": "7.0.0"},
))


def _full_featured_ids():
    return [c[0] for c in _FULL_FEATURED_CASES]


@pytest.mark.parametrize(
    "label,files,repo_name,expected_subset",
    _FULL_FEATURED_CASES,
    ids=_full_featured_ids(),
)
def test_full_featured(tmp_path: Path, label: str, files: dict, repo_name: str, expected_subset: dict):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, repo_name)
    for key, val in expected_subset.items():
        assert result[key] == val, f"[{label}] {key}: expected {val!r}, got {result[key]!r}"


# ═══════════════════════════════════════════════════════════════════════
# 4. env_yml_paths logic  (~30 cases)
# ═══════════════════════════════════════════════════════════════════════

_ENV_YML_CASES = [
    pytest.param("environment.yml", ["environment.yml"], "environment.yml", id="env-yml"),
    pytest.param("environment.yaml", ["environment.yaml"], "environment.yaml", id="env-yaml"),
]


@pytest.mark.parametrize("filename,expected_paths,expected_source", _ENV_YML_CASES)
def test_env_yml_populated(tmp_path: Path, filename: str, expected_paths: list, expected_source: str):
    _write(tmp_path, filename, "name: myenv\ndependencies:\n  - numpy\n")
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["env_yml_paths"] == expected_paths
    assert result["packages_source"] == expected_source
    assert result["reqs_paths"] == []
    assert result["pip_packages"] == []


_ENV_YML_NOT_POPULATED_SOURCES = [
    pytest.param({}, "", id="empty-no-env"),
    pytest.param({"requirements.txt": "numpy\n"}, "requirements.txt", id="reqs-txt-no-env"),
    pytest.param({"setup.py": 'from setuptools import setup\nsetup()\n'}, "", id="setup-py-no-env"),
    pytest.param(
        {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["click"]\n'},
        "",
        id="pyproject-deps-no-env",
    ),
    pytest.param({"requirements/base.txt": "numpy\n"}, "requirements.txt", id="reqs-dir-no-env"),
]


@pytest.mark.parametrize("files,expected_source", _ENV_YML_NOT_POPULATED_SOURCES)
def test_env_yml_not_populated(tmp_path: Path, files: dict, expected_source: str):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["env_yml_paths"] == []
    assert result["packages_source"] == expected_source


_ENV_YML_CONTENTS = [
    "name: myenv\ndependencies:\n  - numpy\n",
    "name: base\ndependencies:\n  - python=3.9\n  - scipy\n",
    "name: test\nchannels:\n  - conda-forge\ndependencies:\n  - pandas\n",
    "name: dev\ndependencies:\n  - pip:\n    - flask\n",
    "name: prod\ndependencies: []\n",
]

_ENV_YML_REPO_NAMES = [
    "owner/repo",
    "org/my-package",
    "user/pkg_name",
    "company/tool",
]


def _env_yml_content_params():
    params = []
    for fname in ("environment.yml", "environment.yaml"):
        for content in _ENV_YML_CONTENTS:
            for repo_name in _ENV_YML_REPO_NAMES:
                params.append((fname, content, repo_name))
    return params


def _env_yml_content_ids():
    return [
        f"env-content-{p[0].replace('.', '_')}-{i}"
        for i, p in enumerate(_env_yml_content_params())
    ]


@pytest.mark.parametrize(
    "filename,content,repo_name",
    _env_yml_content_params(),
    ids=_env_yml_content_ids(),
)
def test_env_yml_various_contents(tmp_path: Path, filename: str, content: str, repo_name: str):
    _write(tmp_path, filename, content)
    result = detect_all_specs(tmp_path, repo_name)
    assert result["env_yml_paths"] == [filename]
    assert result["packages_source"] == filename


# ═══════════════════════════════════════════════════════════════════════
# 5. Various repo name formats  (~30 cases)
# ═══════════════════════════════════════════════════════════════════════

_REPO_NAME_VERSION_CASES = [
    pytest.param("owner/mypackage", "mypackage", "1.0.0", id="simple-name"),
    pytest.param("owner/my-package", "my_package", "2.0.0", id="hyphenated-name"),
    pytest.param("org/Cool-Lib", "cool_lib", "3.0.0", id="mixed-case-hyphen"),
    pytest.param("user/PKG", "pkg", "4.0.0", id="uppercase-name"),
    pytest.param("dev/a-b-c", "a_b_c", "5.0.0", id="multi-hyphen"),
    pytest.param("company/UPPER-CASE", "upper_case", "6.0.0", id="all-upper-hyphen"),
    pytest.param("test/x", "x", "7.0.0", id="single-char"),
    pytest.param("test/xy", "xy", "8.0.0", id="two-char"),
    pytest.param("deep/some-long-package-name", "some_long_package_name", "9.0.0", id="long-hyphen"),
    pytest.param("org/pkg123", "pkg123", "10.0.0", id="name-with-digits"),
    pytest.param("user/my_pkg", "my_pkg", "11.0.0", id="underscore-name"),
    pytest.param("dev/Pkg-Name", "pkg_name", "12.0.0", id="title-case-hyphen"),
    pytest.param("owner/a", "a", "0.1.0", id="single-letter-pkg"),
    pytest.param("org/ab-cd-ef", "ab_cd_ef", "0.2.0", id="triple-hyphen"),
    pytest.param("user/Foo-Bar-Baz", "foo_bar_baz", "0.3.0", id="title-triple-hyphen"),
]


@pytest.mark.parametrize("repo_name,pkg_dir,version", _REPO_NAME_VERSION_CASES)
def test_repo_name_version_detection(tmp_path: Path, repo_name: str, pkg_dir: str, version: str):
    _write(tmp_path, f"{pkg_dir}/__init__.py", f'__version__ = "{version}"\n')
    result = detect_all_specs(tmp_path, repo_name)
    assert result["version"] == version


_REPO_NAME_UNDERSCORE_FALLBACK = [
    pytest.param("owner/my-package", "mypackage", "1.0.0", id="fallback-hyphen-to-nounderscore"),
    pytest.param("org/a-b-c", "abc", "2.0.0", id="fallback-multi-hyphen-to-nounderscore"),
    pytest.param("user/x-y", "xy", "3.0.0", id="fallback-short-hyphen"),
    pytest.param("dev/foo-bar-baz", "foobarbaz", "4.0.0", id="fallback-triple-hyphen"),
    pytest.param("test/one-two-three", "onetwothree", "5.0.0", id="fallback-long-hyphen"),
]


@pytest.mark.parametrize("repo_name,nounderscore_pkg,version", _REPO_NAME_UNDERSCORE_FALLBACK)
def test_repo_name_underscore_removal_fallback(tmp_path: Path, repo_name: str, nounderscore_pkg: str, version: str):
    _write(tmp_path, f"{nounderscore_pkg}/__init__.py", f'__version__ = "{version}"\n')
    result = detect_all_specs(tmp_path, repo_name)
    assert result["version"] == version


_REPO_NAME_NO_MATCH = [
    pytest.param("owner/mypkg", "otherpkg", id="completely-different"),
    pytest.param("org/foo", "bar", id="no-relation"),
    pytest.param("user/abc", "xyz", id="no-overlap"),
    pytest.param("dev/pkg1", "pkg2", id="similar-but-different"),
    pytest.param("test/lib-a", "lib_b", id="different-suffix"),
    pytest.param("company/tool-x", "tool_y", id="different-last-part"),
    pytest.param("org/cool", "kool", id="phonetically-similar"),
    pytest.param("user/my-app", "your_app", id="different-prefix"),
    pytest.param("dev/left", "right", id="opposites"),
    pytest.param("test/up", "down", id="opposites-short"),
]


@pytest.mark.parametrize("repo_name,wrong_pkg", _REPO_NAME_NO_MATCH)
def test_repo_name_no_version_match(tmp_path: Path, repo_name: str, wrong_pkg: str):
    _write(tmp_path, f"{wrong_pkg}/__init__.py", '__version__ = "9.9.9"\n')
    result = detect_all_specs(tmp_path, repo_name)
    assert result["version"] is None


# ═══════════════════════════════════════════════════════════════════════
# 6. Verify all dict keys present  (~20 cases)
# ═══════════════════════════════════════════════════════════════════════

_KEY_CHECK_LAYOUTS: list[tuple[str, dict[str, str]]] = [
    ("empty", {}),
    ("pyproject-only", {"pyproject.toml": '[project]\nname = "x"\nversion = "1.0"\n'}),
    ("setup-py-only", {"setup.py": "from setuptools import setup\nsetup()\n"}),
    ("setup-cfg-only", {"setup.cfg": "[metadata]\nname = foo\n"}),
    ("requirements-only", {"requirements.txt": "numpy\n"}),
    ("env-yml-only", {"environment.yml": "name: env\ndependencies:\n  - numpy\n"}),
    ("env-yaml-only", {"environment.yaml": "name: env\ndependencies: []\n"}),
    ("license-only", {"LICENSE": "MIT License\n\nPermission is hereby granted..."}),
    ("tests-dir-only", {"tests/__init__.py": ""}),
    ("test-dir-only", {"test/__init__.py": ""}),
    ("tox-only", {"tox.ini": "[testenv]\ncommands = pytest\n"}),
    ("python-version-only", {".python-version": "3.11\n"}),
    ("version-file-only", {"VERSION": "1.0.0\n"}),
    ("meson-only", {"meson.build": "project('x', 'c')\n"}),
    ("fortran-only", {"core/math.f90": "subroutine foo()\nend subroutine\n"}),
    ("full-project", {
        "pyproject.toml": '[build-system]\nrequires = ["setuptools"]\n\n[project]\nname = "x"\nversion = "1.0"\nrequires-python = ">=3.9"\n\n[tool.pytest.ini_options]\naddopts = "-v"\n',
        "LICENSE": "MIT License\n\nPermission is hereby granted...",
        "requirements.txt": "numpy\n",
    }),
    ("complex-project", {
        "setup.py": 'from setuptools import setup\nsetup(name="pkg", version="2.0")\n',
        "setup.cfg": "[metadata]\nname = pkg\n\n[options]\npython_requires = >=3.8\n\n[tool:pytest]\naddopts = -v\n",
        "LICENSE": "Apache License\nVersion 2.0\n",
    }),
    ("all-files", {
        ".python-version": "3.12\n",
        "pyproject.toml": '[build-system]\nrequires = ["setuptools"]\n\n[project]\nname = "x"\nversion = "1.0"\n\n[tool.pytest.ini_options]\naddopts = "-v"\n',
        "setup.py": "from setuptools import setup\nsetup()\n",
        "setup.cfg": "[metadata]\nname = x\n",
        "requirements.txt": "numpy\n",
        "LICENSE": "MIT License\n\nPermission is hereby granted...",
        "tox.ini": "[testenv]\ncommands = pytest\n",
    }),
    ("binary-files-only", {"data.bin": ""}),
    ("nested-structure", {
        "src/pkg/__init__.py": '__version__ = "3.0.0"\n',
        "tests/test_a.py": "def test_a(): pass\n",
    }),
]


@pytest.mark.parametrize(
    "label,files",
    _KEY_CHECK_LAYOUTS,
    ids=[c[0] for c in _KEY_CHECK_LAYOUTS],
)
def test_all_keys_present(tmp_path: Path, label: str, files: dict):
    for relpath, content in files.items():
        _write(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/repo")
    assert set(result.keys()) == ALL_KEYS, f"Missing or extra keys: {set(result.keys()) ^ ALL_KEYS}"
    assert isinstance(result["python_version"], str)
    assert isinstance(result["install_cmd"], str)
    assert isinstance(result["test_cmd_override"], str)
    assert isinstance(result["packages_source"], str)
    assert isinstance(result["pip_packages"], list)
    assert isinstance(result["pre_install_cmds"], list)
    assert isinstance(result["reqs_paths"], list)
    assert isinstance(result["env_yml_paths"], list)
    assert isinstance(result["log_parser_type"], str)
    assert result["version"] is None or isinstance(result["version"], str)
    assert result["_license"] is None or isinstance(result["_license"], str)


# ═══════════════════════════════════════════════════════════════════════
# 7. Combination / composition tests  (~20 cases)
# ═══════════════════════════════════════════════════════════════════════

def test_combo_env_yml_overrides_reqs(tmp_path: Path):
    _write(tmp_path, "environment.yml", "name: env\ndependencies:\n  - numpy\n")
    _write(tmp_path, "requirements.txt", "pandas\n")
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["packages_source"] == "environment.yml"
    assert result["env_yml_paths"] == ["environment.yml"]
    assert result["reqs_paths"] == []


def test_combo_env_yaml_overrides_reqs(tmp_path: Path):
    _write(tmp_path, "environment.yaml", "name: env\ndependencies:\n  - numpy\n")
    _write(tmp_path, "requirements.txt", "pandas\n")
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["packages_source"] == "environment.yaml"
    assert result["env_yml_paths"] == ["environment.yaml"]


def test_combo_reqs_txt_over_pyproject_deps(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "numpy\n")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\ndependencies = ["click"]\n')
    result = detect_all_specs(tmp_path, "owner/x")
    assert result["packages_source"] == "requirements.txt"
    assert result["reqs_paths"] == ["requirements.txt"]
    assert result["pip_packages"] == []


def test_combo_meson_with_env_yml(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", '[build-system]\nrequires = ["meson-python>=0.12"]\n\n[project]\nname = "x"\nversion = "1.0"\n')
    _write(tmp_path, "environment.yml", "name: env\ndependencies:\n  - numpy\n")
    result = detect_all_specs(tmp_path, "owner/x")
    assert result["install_cmd"] == "pip install --no-build-isolation -e ."
    assert result["env_yml_paths"] == ["environment.yml"]
    assert result["packages_source"] == "environment.yml"


def test_combo_pyproject_pytest_overrides_tests_dir(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", '[tool.pytest.ini_options]\naddopts = "-v"\n')
    (tmp_path / "tests").mkdir()
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["test_cmd_override"] == "pytest {test_files}"


def test_combo_setup_cfg_pytest_overrides_tests_dir(tmp_path: Path):
    _write(tmp_path, "setup.cfg", "[metadata]\nname = pkg\n\n[tool:pytest]\naddopts = -v\n")
    (tmp_path / "tests").mkdir()
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["test_cmd_override"] == "pytest {test_files}"


def test_combo_python_version_over_pyproject(tmp_path: Path):
    _write(tmp_path, ".python-version", "3.12\n")
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.8"\n')
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["python_version"] == "3.12"


def test_combo_pyproject_version_over_setup_py(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\nversion = "1.0.0"\n')
    _write(tmp_path, "setup.py", 'from setuptools import setup\nsetup(name="x", version="2.0.0")\n')
    result = detect_all_specs(tmp_path, "owner/x")
    assert result["version"] == "1.0.0"


def test_combo_pyproject_version_over_cfg(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\nversion = "1.0.0"\n')
    _write(tmp_path, "setup.cfg", "[metadata]\nname = x\nversion = 2.0.0\n")
    result = detect_all_specs(tmp_path, "owner/x")
    assert result["version"] == "1.0.0"


def test_combo_setup_py_version_over_cfg(tmp_path: Path):
    _write(tmp_path, "setup.py", 'from setuptools import setup\nsetup(name="x", version="1.0.0")\n')
    _write(tmp_path, "setup.cfg", "[metadata]\nname = x\nversion = 2.0.0\n")
    result = detect_all_specs(tmp_path, "owner/x")
    assert result["version"] == "1.0.0"


def test_combo_license_file_over_pyproject(tmp_path: Path):
    _write(tmp_path, "LICENSE", "Apache License\nVersion 2.0, January 2004")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\nlicense = {text = "MIT"}\n')
    result = detect_all_specs(tmp_path, "owner/x")
    assert result["_license"] == "Apache-2.0"


def test_combo_full_scipy_like(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", (
        '[build-system]\nrequires = ["meson-python>=0.12.0", "cython>=0.29", "numpy>=1.20"]\n\n'
        '[project]\nname = "scipy"\nversion = "1.12.0"\nrequires-python = ">=3.9"\n'
        'dependencies = ["numpy>=1.20"]\nlicense = {text = "BSD-3-Clause"}\n'
        '# uses openblas for linear algebra\n\n'
        '[tool.pytest.ini_options]\naddopts = "-v"\n'
    ))
    _write(tmp_path, "meson.build", "project('scipy', 'c', 'fortran')\ndependency('openblas')\n")
    _write(tmp_path, "linalg/solve.f90", "subroutine solve()\nend subroutine\n")
    _write(tmp_path, "LICENSE", "BSD 3-Clause License\n\nRedistribution and use in source and binary forms, with or without modification, are permitted provided that the following three conditions are met:\n")
    result = detect_all_specs(tmp_path, "scipy/scipy")
    assert result["python_version"] == "3.9"
    assert result["install_cmd"] == "pip install --no-build-isolation -e ."
    assert result["test_cmd_override"] == "pytest {test_files}"
    assert result["version"] == "1.12.0"
    assert result["_license"] == "BSD-3-Clause"
    assert result["log_parser_type"] == "pytest"
    assert result["pip_packages"] == ["numpy>=1.20"]
    assert "apt-get install -y build-essential" in result["pre_install_cmds"]
    assert "apt-get install -y meson ninja-build" in result["pre_install_cmds"]
    assert "apt-get install -y gfortran" in result["pre_install_cmds"]
    assert "apt-get install -y libopenblas-dev" in result["pre_install_cmds"]
    assert result["env_yml_paths"] == []


def test_combo_full_flask_like(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", (
        '[build-system]\nrequires = ["setuptools", "wheel"]\n\n'
        '[project]\nname = "flask"\nversion = "3.0.0"\nrequires-python = ">=3.8"\n'
        'dependencies = ["werkzeug>=3.0", "jinja2>=3.1", "click>=8.1"]\n'
        'license = {text = "MIT"}\n\n'
        '[tool.pytest.ini_options]\naddopts = "-v"\n'
    ))
    _write(tmp_path, "LICENSE", "MIT License\n\nPermission is hereby granted, free of charge...")
    _write(tmp_path, "tests/__init__.py", "")
    result = detect_all_specs(tmp_path, "pallets/flask")
    assert result["python_version"] == "3.8"
    assert result["install_cmd"] == "pip install -e ."
    assert result["test_cmd_override"] == "pytest {test_files}"
    assert result["version"] == "3.0.0"
    assert result["_license"] == "MIT"
    assert result["pip_packages"] == ["werkzeug>=3.0", "jinja2>=3.1", "click>=8.1"]
    assert result["pre_install_cmds"] == []
    assert result["env_yml_paths"] == []


def test_combo_full_django_like(tmp_path: Path):
    _write(tmp_path, "setup.py", 'from setuptools import setup\nsetup(name="django", version="5.0.0", python_requires=">=3.10")\n')
    _write(tmp_path, "LICENSE", "BSD 3-Clause License\n\nRedistribution and use in source and binary forms, with or without modification, are permitted provided that the following three conditions are met:\n")
    _write(tmp_path, "tests/__init__.py", "")
    result = detect_all_specs(tmp_path, "django/django")
    assert result["python_version"] == "3.10"
    assert result["install_cmd"] == "pip install -e ."
    assert result["version"] == "5.0.0"
    assert result["_license"] == "BSD-3-Clause"
    assert result["pre_install_cmds"] == []


def test_combo_log_parser_pytest_default(tmp_path: Path):
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["log_parser_type"] == "pytest"


def test_combo_log_parser_from_tests_dir(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["test_cmd_override"] == "pytest tests/"
    assert result["log_parser_type"] == "pytest"


def test_combo_reqs_dir_sorted(tmp_path: Path):
    _write(tmp_path, "requirements/dev.txt", "pytest\n")
    _write(tmp_path, "requirements/base.txt", "numpy\n")
    _write(tmp_path, "requirements/ci.txt", "coverage\n")
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["reqs_paths"] == ["requirements/base.txt", "requirements/ci.txt", "requirements/dev.txt"]
    assert result["packages_source"] == "requirements.txt"


def test_combo_no_version_no_license(tmp_path: Path):
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["version"] is None
    assert result["_license"] is None


def test_combo_pre_install_build_essential_first(tmp_path: Path):
    _write(tmp_path, "meson.build", "project('x', 'c')\n")
    result = detect_all_specs(tmp_path, "owner/repo")
    assert result["pre_install_cmds"][0] == "apt-get install -y build-essential"
    assert "apt-get install -y meson ninja-build" in result["pre_install_cmds"]
