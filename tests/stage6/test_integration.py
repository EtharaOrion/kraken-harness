from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import detect_all_specs


def _w(repo, relpath, content):
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")


def _wb(repo, relpath, data):
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _md(repo, relpath):
    (repo / relpath).mkdir(parents=True, exist_ok=True)


def _assert_all(result, **kw):
    for key, val in kw.items():
        assert result[key] == val, f"{key!r}: expected {val!r}, got {result[key]!r}"


# =====================================================================
# Category 1: Real-world repo archetypes (~200 tests)
# =====================================================================

_ARCHETYPE_CASES = []

# --- numpy-like repos ---
_numpy_python_versions = ["3.9", "3.10", "3.11", "3.12"]
_numpy_meson_versions = ["0.12", "0.13", "0.14", "1.0"]
for i, pyver in enumerate(_numpy_python_versions):
    for j, mver in enumerate(_numpy_meson_versions):
        _ARCHETYPE_CASES.append(pytest.param(
            f"numpy_like_{i}_{j}",
            {
                "pyproject.toml": f"""\
[project]
name = "mynumpy"
version = "1.{i}.{j}"
requires-python = ">={pyver}"
[build-system]
requires = ["meson-python>={mver}", "numpy", "cython"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                "LICENSE": "BSD 3-Clause License\nRedistribution and use in source and binary forms",
                "meson.build": "project('mynumpy', 'c', 'fortran')",
                "setup.py": "# legacy\nfrom numpy.distutils.core import setup\nsetup()",
                "mynumpy/__init__.py": f'__version__ = "1.{i}.{j}"\n',
                "solver.f90": "! Fortran solver",
            },
            dict(
                python_version=pyver,
                install_cmd="pip install --no-build-isolation -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=["apt-get install -y build-essential",
                                  "apt-get install -y meson ninja-build",
                                  "apt-get install -y gfortran"],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version=f"1.{i}.{j}",
                _license="BSD-3-Clause",
            ),
            id=f"numpy-like-py{pyver}-meson{mver}",
        ))

# --- pandas-like repos ---
_pandas_versions = ["3.8", "3.9", "3.10", "3.11", "3.12"]
for i, pyver in enumerate(_pandas_versions):
    _ARCHETYPE_CASES.append(pytest.param(
        f"pandas_like_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "mypandas"
version = "2.{i}.0"
requires-python = ">={pyver}"
[build-system]
requires = ["setuptools>=61", "wheel", "cython>=0.29"]
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            "setup.py": "from setuptools import setup, Extension\next_modules=[Extension('m','m.c')]\nsetup(ext_modules=ext_modules)",
            "requirements.txt": "numpy>=1.20\nscipy\n",
            "tests/__init__.py": "",
        },
        dict(
            python_version=pyver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="requirements.txt",
            pip_packages=[],
            pre_install_cmds=["apt-get install -y build-essential"],
            reqs_paths=["requirements.txt"],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"2.{i}.0",
            _license="BSD-3-Clause",
        ),
        id=f"pandas-like-py{pyver}",
    ))

# --- flask-like repos ---
_flask_versions = ["3.8", "3.9", "3.10", "3.11"]
for i, pyver in enumerate(_flask_versions):
    _ARCHETYPE_CASES.append(pytest.param(
        f"flask_like_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "myflask"
version = "3.{i}.0"
requires-python = ">={pyver}"
[build-system]
requires = ["setuptools", "wheel"]
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            "requirements/base.txt": "werkzeug\njinja2\n",
            "requirements/dev.txt": "pytest\ncoverage\n",
            "tests/__init__.py": "",
        },
        dict(
            python_version=pyver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="requirements.txt",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=["requirements/base.txt", "requirements/dev.txt"],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"3.{i}.0",
            _license="BSD-3-Clause",
        ),
        id=f"flask-like-py{pyver}",
    ))

# --- django-like repos ---
for i in range(5):
    _ARCHETYPE_CASES.append(pytest.param(
        f"django_like_{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="mydjango", version="4.{i}", python_requires=">=3.10")',
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            "requirements.txt": "asgiref\nsqlparse\n",
            "tests/__init__.py": "",
            "tox.ini": "[tox]\nenvlist = py310\n\n[testenv]\ncommands = python runtests.py",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="python runtests.py",
            packages_source="requirements.txt",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=["requirements.txt"],
            env_yml_paths=[],
            log_parser_type="django",
            version=f"4.{i}",
            _license="BSD-3-Clause",
        ),
        id=f"django-like-v4.{i}",
    ))

# --- scikit-learn-like repos ---
for i in range(4):
    pyver = ["3.9", "3.10", "3.11", "3.12"][i]
    _ARCHETYPE_CASES.append(pytest.param(
        f"sklearn_like_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "mysklearn"
version = "1.{i}.0"
requires-python = ">={pyver}"
[build-system]
requires = ["meson-python>=0.13", "numpy>=1.20", "cython>=0.29"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            "meson.build": "project('mysklearn', 'c', 'cython')",
            "setup.py": "# legacy setup\nfrom setuptools import setup, Extension\next_modules=[]\nsetup()\n# uses openblas",
            "requirements.txt": "numpy\nscipy\n",
        },
        dict(
            python_version=pyver,
            install_cmd="pip install --no-build-isolation -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="requirements.txt",
            pip_packages=[],
            pre_install_cmds=["apt-get install -y build-essential",
                              "apt-get install -y meson ninja-build",
                              "apt-get install -y libopenblas-dev"],
            reqs_paths=["requirements.txt"],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.{i}.0",
            _license="BSD-3-Clause",
        ),
        id=f"sklearn-like-py{pyver}",
    ))

# --- sympy-like repos ---
for i in range(5):
    _ARCHETYPE_CASES.append(pytest.param(
        f"sympy_like_{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="mysympy", version="1.1{i}", python_requires=">=3.8")',
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            "tox.ini": "[tox]\nenvlist = py39\n\n[testenv]\ncommands = bin/test",
            "tests/__init__.py": "",
            "bin/test": "#!/usr/bin/env python\nprint('test')",
        },
        dict(
            python_version="3.8",
            install_cmd="pip install -e .",
            test_cmd_override="bin/test",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="sympy",
            version=f"1.1{i}",
            _license="BSD-3-Clause",
        ),
        id=f"sympy-like-v1.1{i}",
    ))

# --- fastapi-like repos ---
for i in range(5):
    pyver = ["3.8", "3.9", "3.10", "3.11", "3.12"][i]
    _ARCHETYPE_CASES.append(pytest.param(
        f"fastapi_like_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "myfastapi"
version = "0.{i+100}.0"
requires-python = ">={pyver}"
dependencies = ["starlette>=0.27", "pydantic>=2.0"]
[build-system]
requires = ["hatchling"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "MIT License\nPermission is hereby granted",
            "tests/__init__.py": "",
        },
        dict(
            python_version=pyver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=["starlette>=0.27", "pydantic>=2.0"],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"0.{i+100}.0",
            _license="MIT",
        ),
        id=f"fastapi-like-py{pyver}",
    ))

# --- poetry-project repos ---
for i in range(5):
    pyver = ["3.8", "3.9", "3.10", "3.11", "3.12"][i]
    _ARCHETYPE_CASES.append(pytest.param(
        f"poetry_project_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "mypoetry"
version = "0.{i}.0"
requires-python = ">={pyver}"
dependencies = ["click>=8.0", "rich>=12.0"]
[build-system]
requires = ["poetry-core>=1.0"]
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "LICENSE": "MIT License\nPermission is hereby granted",
            "tests/__init__.py": "",
        },
        dict(
            python_version=pyver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=["click>=8.0", "rich>=12.0"],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"0.{i}.0",
            _license="MIT",
        ),
        id=f"poetry-project-py{pyver}",
    ))

# --- flit-project repos ---
for i in range(5):
    pyver = ["3.8", "3.9", "3.10", "3.11", "3.12"][i]
    _ARCHETYPE_CASES.append(pytest.param(
        f"flit_project_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "myflit"
version = "1.{i}.0"
requires-python = ">={pyver}"
[build-system]
requires = ["flit_core>=3.2"]
[tool.pytest.ini_options]
addopts = "-q"
""",
            "LICENSE": "MIT License\nPermission is hereby granted",
            "tests/__init__.py": "",
        },
        dict(
            python_version=pyver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.{i}.0",
            _license="MIT",
        ),
        id=f"flit-project-py{pyver}",
    ))

# --- pdm-project repos ---
for i in range(5):
    pyver = ["3.8", "3.9", "3.10", "3.11", "3.12"][i]
    _ARCHETYPE_CASES.append(pytest.param(
        f"pdm_project_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "mypdm"
version = "2.{i}.0"
requires-python = ">={pyver}"
dependencies = ["httpx>=0.24"]
[build-system]
requires = ["pdm-backend"]
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "LICENSE": "Apache License\nVersion 2.0, January 2004",
            "tests/__init__.py": "",
        },
        dict(
            python_version=pyver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=["httpx>=0.24"],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"2.{i}.0",
            _license="Apache-2.0",
        ),
        id=f"pdm-project-py{pyver}",
    ))

# --- Additional archetype variations to reach ~200 ---
_license_bodies = {
    "MIT": "MIT License\nPermission is hereby granted",
    "Apache-2.0": "Apache License\nVersion 2.0, January 2004",
    "BSD-3-Clause": "BSD 3-Clause License\nRedistribution and use",
    "BSD-2-Clause": "BSD 2-Clause\nSimplified BSD",
    "ISC": "ISC License\nPermission to use, copy",
}
_backends = [
    ("setuptools>=64", "pip install -e ."),
    ("hatchling>=1.0", "pip install -e ."),
    ("flit-core>=3.2", "pip install -e ."),
    ("poetry-core>=1.0", "pip install -e ."),
    ("pdm-backend>=2.0", "pip install -e ."),
]
for li, (lic_name, lic_body) in enumerate(_license_bodies.items()):
    for bi, (backend, install_cmd) in enumerate(_backends):
        for pyver in ["3.9", "3.10", "3.11"]:
            idx = li * 15 + bi * 3 + ["3.9", "3.10", "3.11"].index(pyver)
            _ARCHETYPE_CASES.append(pytest.param(
                f"archetype_combo_{idx}",
                {
                    "pyproject.toml": f"""\
[project]
name = "combo{idx}"
version = "0.{idx}.1"
requires-python = ">={pyver}"
[build-system]
requires = ["{backend}"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                    "LICENSE": lic_body,
                    "tests/__init__.py": "",
                },
                dict(
                    python_version=pyver,
                    install_cmd=install_cmd,
                    test_cmd_override="pytest {test_files}",
                    packages_source="",
                    pip_packages=[],
                    pre_install_cmds=[],
                    reqs_paths=[],
                    env_yml_paths=[],
                    log_parser_type="pytest",
                    version=f"0.{idx}.1",
                    _license=lic_name,
                ),
                id=f"archetype-combo-{lic_name}-{backend.split('>')[0]}-py{pyver}",
            ))


@pytest.mark.parametrize("name,files,expected", _ARCHETYPE_CASES)
def test_archetype(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/myproject")
    _assert_all(result, **expected)


# =====================================================================
# Category 2: Variations of each archetype (~300 tests)
# =====================================================================

_VARIATION_CASES = []

# Variation: different python version files + pyproject
_pyver_file_versions = [
    "3.8.0", "3.8.16", "3.9.0", "3.9.18", "3.10.0", "3.10.13",
    "3.11.0", "3.11.7", "3.12.0", "3.12.1",
]
for i, pv in enumerate(_pyver_file_versions):
    expected_ver = pv[:pv.rfind(".")]  # e.g. "3.8"
    _VARIATION_CASES.append(pytest.param(
        f"pyver_file_{i}",
        {
            ".python-version": pv,
            "pyproject.toml": """\
[project]
name = "pkg"
version = "1.0.0"
requires-python = ">=3.12"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "MIT License",
            "tests/__init__.py": "",
        },
        dict(
            python_version=expected_ver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version="1.0.0",
            _license="MIT",
        ),
        id=f"variation-pyver-file-{pv}",
    ))

# Variation: different license files (LICENSE.md, LICENCE.txt, COPYING, etc)
_license_filenames = ["LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.txt", "COPYING"]
_license_contents = {
    "MIT": "MIT License",
    "Apache-2.0": "Apache License\nVersion 2.0",
    "BSD-3-Clause": "BSD 3-Clause License",
    "ISC": "ISC License",
}
for fn in _license_filenames:
    for lic_name, lic_content in _license_contents.items():
        _VARIATION_CASES.append(pytest.param(
            f"lic_file_{fn}_{lic_name}",
            {
                fn: lic_content,
                "pyproject.toml": """\
[project]
name = "pkg"
version = "1.0.0"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                "tests/__init__.py": "",
            },
            dict(
                python_version="3.10",
                install_cmd="pip install -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=[],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version="1.0.0",
                _license=lic_name,
            ),
            id=f"variation-licfile-{fn.replace('.', '_')}-{lic_name}",
        ))

# Variation: extra files that should not affect detection
_extra_file_sets = [
    {"README.md": "# Readme", "CHANGELOG.md": "# Changes"},
    {"Makefile": "test:\n\tpytest", "Dockerfile": "FROM python:3.10"},
    {".gitignore": "*.pyc", ".editorconfig": "[*]\nindent_size = 4"},
    {"docs/index.rst": "Welcome", "docs/conf.py": "project = 'pkg'"},
    {"examples/demo.py": "print('demo')", "scripts/build.sh": "#!/bin/bash"},
    {"MANIFEST.in": "include LICENSE", "mypy.ini": "[mypy]\nstrict = True"},
    {".github/workflows/ci.yml": "name: CI", ".pre-commit-config.yaml": "repos: []"},
    {"noxfile.py": "import nox", "tasks.py": "from invoke import task"},
    {"conftest.py": "import pytest", ".coveragerc": "[run]\nsource = pkg"},
    {"data/sample.json": '{"key": "val"}', "assets/logo.png": "PNG_PLACEHOLDER"},
]
for idx, extra_files in enumerate(_extra_file_sets):
    files = {
        "pyproject.toml": """\
[project]
name = "pkg"
version = "2.0.0"
requires-python = ">=3.10"
[build-system]
requires = ["hatchling"]
[tool.pytest.ini_options]
addopts = "-v"
""",
        "LICENSE": "MIT License",
        "tests/__init__.py": "",
    }
    files.update(extra_files)
    _VARIATION_CASES.append(pytest.param(
        f"extra_files_{idx}",
        files,
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version="2.0.0",
            _license="MIT",
        ),
        id=f"variation-extra-files-{idx}",
    ))

# Variation: meson repos with different fortran exts
_fortran_exts = [".f90", ".f", ".f77", ".for"]
for ext in _fortran_exts:
    for i in range(5):
        _VARIATION_CASES.append(pytest.param(
            f"meson_fortran_{ext}_{i}",
            {
                "pyproject.toml": f"""\
[project]
name = "sci{i}"
version = "0.{i}.0"
requires-python = ">=3.10"
[build-system]
requires = ["meson-python>=0.13"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                "meson.build": "project('sci', 'c', 'fortran')",
                f"solver{i}{ext}": "! Fortran source",
                "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            },
            dict(
                python_version="3.10",
                install_cmd="pip install --no-build-isolation -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=["apt-get install -y build-essential",
                                  "apt-get install -y meson ninja-build",
                                  "apt-get install -y gfortran"],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version=f"0.{i}.0",
                _license="BSD-3-Clause",
            ),
            id=f"variation-meson-fortran{ext}-{i}",
        ))

# Variation: repos with BLAS keywords
_blas_variations = [
    "uses blas for linalg",
    "depends on openblas",
    "links to lapack",
    "BLAS backend",
    "OpenBLAS required",
]
for i, blas_text in enumerate(_blas_variations):
    for backend in ["meson-python>=0.13", "scikit-build>=0.17"]:
        _VARIATION_CASES.append(pytest.param(
            f"blas_var_{i}_{backend.split('>=')[0]}",
            {
                "pyproject.toml": f"""\
[project]
name = "blaslib"
version = "0.{i}.0"
requires-python = ">=3.10"
description = "{blas_text}"
[build-system]
requires = ["{backend}"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                "meson.build": "project('blaslib', 'c')",
                "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            },
            dict(
                python_version="3.10",
                install_cmd="pip install --no-build-isolation -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=["apt-get install -y build-essential",
                                  "apt-get install -y meson ninja-build",
                                  "apt-get install -y libopenblas-dev"],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version=f"0.{i}.0",
                _license="BSD-3-Clause",
            ),
            id=f"variation-blas-{i}-{backend.split('>=')[0].replace('-', '')}",
        ))

# Variation: different dependency sources combined with archetypes
_dep_source_variations = [
    ("environment.yml", {"environment.yml": "name: env\ndependencies:\n  - numpy"}, "environment.yml", [], [], ["environment.yml"]),
    ("environment.yaml", {"environment.yaml": "name: env\ndependencies:\n  - numpy"}, "environment.yaml", [], [], ["environment.yaml"]),
    ("requirements.txt", {"requirements.txt": "numpy>=1.20\npandas"}, "requirements.txt", ["requirements.txt"], [], []),
    ("requirements_dir", {"requirements/base.txt": "numpy", "requirements/dev.txt": "pytest"}, "requirements.txt", ["requirements/base.txt", "requirements/dev.txt"], [], []),
]
for dep_name, dep_files, source, reqs, pips, envs in _dep_source_variations:
    for backend, cmd in [("setuptools>=64", "pip install -e ."), ("hatchling", "pip install -e .")]:
        files = {
            "pyproject.toml": f"""\
[project]
name = "deptest"
version = "1.0.0"
[build-system]
requires = ["{backend}"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "MIT License",
            "tests/__init__.py": "",
        }
        files.update(dep_files)
        _VARIATION_CASES.append(pytest.param(
            f"dep_source_{dep_name}_{backend.split('>=')[0]}",
            files,
            dict(
                python_version="3.10",
                install_cmd=cmd,
                test_cmd_override="pytest {test_files}",
                packages_source=source,
                pip_packages=pips,
                pre_install_cmds=[],
                reqs_paths=reqs,
                env_yml_paths=envs,
                log_parser_type="pytest",
                version="1.0.0",
                _license="MIT",
            ),
            id=f"variation-depsource-{dep_name}-{backend.split('>=')[0]}",
        ))

# Variation: version detection from different sources
for i in range(10):
    _VARIATION_CASES.append(pytest.param(
        f"version_from_init_{i}",
        {
            "pyproject.toml": """\
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "setup.py": "from setuptools import setup\nsetup(name='mypkg')",
            "mypkg/__init__.py": f'__version__ = "5.{i}.0"',
            "LICENSE": "MIT License",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"5.{i}.0",
            _license="MIT",
        ),
        id=f"variation-version-init-{i}",
    ))

# Variation: version from VERSION file
for i in range(10):
    _VARIATION_CASES.append(pytest.param(
        f"version_from_vfile_{i}",
        {
            "setup.py": "from setuptools import setup\nsetup(name='otherpkg')",
            "VERSION": f"9.{i}.0",
            "LICENSE": "Apache License\nVersion 2.0",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"9.{i}.0",
            _license="Apache-2.0",
        ),
        id=f"variation-version-file-{i}",
    ))

# Variation: setup.cfg python version
for i, pyver in enumerate(["3.7", "3.8", "3.9", "3.10", "3.11"]):
    _VARIATION_CASES.append(pytest.param(
        f"cfg_pyver_{i}",
        {
            "setup.cfg": f"[metadata]\nname = pkg\nversion = 1.0.{i}\n\n[options]\npython_requires = >={pyver}",
            "LICENSE": "ISC License",
        },
        dict(
            python_version=pyver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.0.{i}",
            _license="ISC",
        ),
        id=f"variation-cfg-pyver-{pyver}",
    ))

# Variation: tox.ini python version detection
_tox_envlists = [
    ("py38,py39", "3.8"),
    ("py39,py310", "3.10"),
    ("py310,py311", "3.10"),
    ("py311,py312", "3.11"),
    ("py312", "3.12"),
    ("py38", "3.8"),
    ("py39", "3.9"),
    ("py310", "3.10"),
]
for el, expected_ver in _tox_envlists:
    _VARIATION_CASES.append(pytest.param(
        f"tox_pyver_{el}",
        {
            "tox.ini": f"[tox]\nenvlist = {el}\n\n[testenv]\ncommands = pytest tests/",
            "setup.py": "from setuptools import setup\nsetup(name='pkg')",
            "tests/__init__.py": "",
            "LICENSE": "MIT License",
        },
        dict(
            python_version=expected_ver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license="MIT",
        ),
        id=f"variation-tox-pyver-{el}",
    ))

# Variation: pyproject dependencies as pip_packages
for i in range(10):
    deps = [f'"dep{j}>=1.0"' for j in range(i + 1)]
    deps_str = ", ".join(deps)
    deps_list = [f"dep{j}>=1.0" for j in range(i + 1)]
    _VARIATION_CASES.append(pytest.param(
        f"pip_packages_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "pkg{i}"
version = "1.0.0"
dependencies = [{deps_str}]
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "MIT License",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=deps_list,
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version="1.0.0",
            _license="MIT",
        ),
        id=f"variation-pip-packages-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", _VARIATION_CASES)
def test_variation(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/mypkg")
    _assert_all(result, **expected)


# =====================================================================
# Category 3: Minimal repos (~100 tests)
# =====================================================================

_MINIMAL_CASES = []

# Just pyproject.toml
for i in range(10):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_pyproject_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "min{i}"
version = "0.0.{i}"
[build-system]
requires = ["setuptools"]
""",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"0.0.{i}",
            _license=None,
        ),
        id=f"minimal-pyproject-only-{i}",
    ))

# Just setup.py
for i in range(10):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_setup_py_{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="min{i}", version="0.{i}.0")',
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"0.{i}.0",
            _license=None,
        ),
        id=f"minimal-setup-py-only-{i}",
    ))

# Just setup.cfg
for i in range(10):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_setup_cfg_{i}",
        {
            "setup.cfg": f"[metadata]\nname = min{i}\nversion = 0.{i}.0",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"0.{i}.0",
            _license=None,
        ),
        id=f"minimal-setup-cfg-only-{i}",
    ))

# Nothing at all (empty repo)
for i in range(10):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_empty_{i}",
        {},
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-empty-{i}",
    ))

# Just README
for i in range(5):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_readme_{i}",
        {"README.md": f"# Project {i}"},
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-readme-only-{i}",
    ))

# Just a test directory
for i in range(5):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_tests_dir_{i}",
        {"tests/test_something.py": "def test_x(): pass"},
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest tests/",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-tests-dir-{i}",
    ))

# Just test/ directory
for i in range(5):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_test_dir_{i}",
        {"test/test_something.py": "def test_x(): pass"},
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest test/",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-test-dir-{i}",
    ))

# Just requirements.txt
for i in range(5):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_reqs_{i}",
        {"requirements.txt": f"dep{i}>=1.0"},
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="requirements.txt",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=["requirements.txt"],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-reqs-only-{i}",
    ))

# Just environment.yml
for i in range(5):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_env_yml_{i}",
        {"environment.yml": f"name: env{i}\ndependencies:\n  - numpy"},
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="environment.yml",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=["environment.yml"],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-env-yml-{i}",
    ))

# Just .python-version
for i, ver in enumerate(["3.8.1", "3.9.7", "3.10.4", "3.11.2", "3.12.0"]):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_pyver_file_{i}",
        {".python-version": ver},
        dict(
            python_version=ver[:ver.rfind(".")],
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-pyver-file-{ver}",
    ))

# Pyproject with no build-system and no project
for i in range(5):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_pyproject_tool_only_{i}",
        {"pyproject.toml": f"[tool.black]\nline-length = {80 + i}"},
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-pyproject-tool-only-{i}",
    ))

# Just tox.ini
for i in range(5):
    _MINIMAL_CASES.append(pytest.param(
        f"minimal_tox_{i}",
        {"tox.ini": f"[tox]\nenvlist = py3{i+8}\n\n[testenv]\ncommands = pytest tests/"},
        dict(
            python_version=f"3.{i+8}",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"minimal-tox-only-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", _MINIMAL_CASES)
def test_minimal(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/minpkg")
    _assert_all(result, **expected)


# =====================================================================
# Category 4: Complex repos (~200 tests)
# =====================================================================

_COMPLEX_CASES = []

# Multiple config files competing: pyproject + setup.py + setup.cfg
for i in range(10):
    _COMPLEX_CASES.append(pytest.param(
        f"complex_all_configs_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "complex{i}"
version = "1.{i}.0"
requires-python = ">=3.11"
[build-system]
requires = ["setuptools>=64"]
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "setup.py": f'from setuptools import setup\nsetup(name="complex{i}", version="2.{i}.0", python_requires=">=3.9")',
            "setup.cfg": f"[metadata]\nname = complex{i}\nversion = 3.{i}.0\n\n[options]\npython_requires = >=3.8\n\n[tool:pytest]\naddopts = -v",
            "tox.ini": f"[tox]\nenvlist = py39\n\n[testenv]\ncommands = pytest tests/",
            "tests/__init__.py": "",
            "LICENSE": "MIT License",
        },
        dict(
            python_version="3.11",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.{i}.0",
            _license="MIT",
        ),
        id=f"complex-all-configs-{i}",
    ))

# environment.yml + requirements.txt (environment.yml wins)
for i in range(10):
    _COMPLEX_CASES.append(pytest.param(
        f"complex_env_plus_reqs_{i}",
        {
            "environment.yml": f"name: env{i}\ndependencies:\n  - numpy",
            "requirements.txt": f"numpy>={i}.0\npandas",
            "setup.py": f'from setuptools import setup\nsetup(name="envpkg{i}", version="1.{i}.0")',
            "LICENSE": "Apache License\nVersion 2.0",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="environment.yml",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=["environment.yml"],
            log_parser_type="pytest",
            version=f"1.{i}.0",
            _license="Apache-2.0",
        ),
        id=f"complex-env-plus-reqs-{i}",
    ))

# src layout vs flat layout
for i in range(10):
    _COMPLEX_CASES.append(pytest.param(
        f"complex_src_layout_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "srcpkg{i}"
requires-python = ">=3.10"
[build-system]
requires = ["setuptools>=64"]
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "src/srcpkg/__init__.py": f'__version__ = "4.{i}.0"',
            "tests/__init__.py": "",
            "LICENSE": "MIT License",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"4.{i}.0",
            _license="MIT",
        ),
        id=f"complex-src-layout-{i}",
    ))

# Flat layout
for i in range(10):
    _COMPLEX_CASES.append(pytest.param(
        f"complex_flat_layout_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "flatpkg{i}"
requires-python = ">=3.10"
[build-system]
requires = ["setuptools>=64"]
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            f"flatpkg{i}/__init__.py": f'__version__ = "3.{i}.0"',
            "tests/__init__.py": "",
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"3.{i}.0",
            _license="BSD-3-Clause",
        ),
        id=f"complex-flat-layout-{i}",
    ))

# Repo name package derivation with hyphens
_repo_name_cases = [
    ("owner/my-package", "my_package", "7.0.0"),
    ("owner/cool-lib", "cool_lib", "7.1.0"),
    ("org/data-tools", "data_tools", "7.2.0"),
    ("user/web-framework", "web_framework", "7.3.0"),
    ("dev/py-utils", "py_utils", "7.4.0"),
]
for repo_name, pkg_dir, ver in _repo_name_cases:
    for layout in ["flat", "src"]:
        if layout == "flat":
            init_path = f"{pkg_dir}/__init__.py"
        else:
            init_path = f"src/{pkg_dir}/__init__.py"
        _COMPLEX_CASES.append(pytest.param(
            f"complex_reponame_{pkg_dir}_{layout}",
            {
                "pyproject.toml": """\
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                init_path: f'__version__ = "{ver}"',
                "LICENSE": "MIT License",
            },
            dict(
                python_version="3.10",
                install_cmd="pip install -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=[],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version=ver,
                _license="MIT",
            ),
            id=f"complex-reponame-{pkg_dir}-{layout}",
        ))

# Multiple requirements dirs
for i in range(10):
    req_files = {}
    expected_paths = []
    for j in range(i + 1):
        fname = f"requirements/req{j}.txt"
        req_files[fname] = f"dep{j}>=1.0"
        expected_paths.append(fname)
    expected_paths.sort()
    files = {
        "pyproject.toml": """\
[project]
name = "multireq"
version = "1.0.0"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
        "LICENSE": "MIT License",
    }
    files.update(req_files)
    _COMPLEX_CASES.append(pytest.param(
        f"complex_multi_reqs_{i}",
        files,
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="requirements.txt",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=expected_paths,
            env_yml_paths=[],
            log_parser_type="pytest",
            version="1.0.0",
            _license="MIT",
        ),
        id=f"complex-multi-reqs-{i}",
    ))

# Meson + C ext + fortran + BLAS (full scientific stack)
for i in range(10):
    _COMPLEX_CASES.append(pytest.param(
        f"complex_full_sci_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "fullsci{i}"
version = "0.{i}.0"
requires-python = ">=3.10"
[build-system]
requires = ["meson-python>=0.13", "cython>=0.29"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "meson.build": f"project('fullsci{i}', 'c', 'fortran')",
            "setup.py": "from setuptools import setup, Extension\next_modules=[Extension('m','m.c')]\nsetup(ext_modules=ext_modules)\n# openblas",
            f"linalg{i}.f90": "! Fortran linalg",
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            "requirements.txt": "numpy\nscipy",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install --no-build-isolation -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="requirements.txt",
            pip_packages=[],
            pre_install_cmds=["apt-get install -y build-essential",
                              "apt-get install -y meson ninja-build",
                              "apt-get install -y gfortran",
                              "apt-get install -y libopenblas-dev"],
            reqs_paths=["requirements.txt"],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"0.{i}.0",
            _license="BSD-3-Clause",
        ),
        id=f"complex-full-sci-{i}",
    ))

# Competing test commands
for i in range(10):
    _COMPLEX_CASES.append(pytest.param(
        f"complex_test_priority_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "testpri{i}"
version = "1.{i}.0"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "setup.cfg": f"[metadata]\nname = testpri{i}\n\n[tool:pytest]\naddopts = -v",
            "tox.ini": f"[tox]\nenvlist = py39\n\n[testenv]\ncommands = nosetests tests/",
            "tests/__init__.py": "",
            "test/__init__.py": "",
            "LICENSE": "MIT License",
        },
        dict(
            python_version="3.9",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.{i}.0",
            _license="MIT",
        ),
        id=f"complex-test-priority-{i}",
    ))

# License priority: file over pyproject
for i, (file_lic, pyproject_lic) in enumerate([
    ("MIT License", "Apache-2.0"),
    ("BSD 3-Clause License", "MIT"),
    ("Apache License\nVersion 2.0", "BSD-3-Clause"),
    ("ISC License", "MIT"),
    ("BSD 2-Clause\nSimplified BSD", "Apache-2.0"),
]):
    expected_lic = {"MIT License": "MIT", "BSD 3-Clause License": "BSD-3-Clause",
                    "Apache License\nVersion 2.0": "Apache-2.0", "ISC License": "ISC",
                    "BSD 2-Clause\nSimplified BSD": "BSD-2-Clause"}[file_lic]
    _COMPLEX_CASES.append(pytest.param(
        f"complex_lic_priority_{i}",
        {
            "LICENSE": file_lic,
            "pyproject.toml": f"""\
[project]
name = "licpri{i}"
version = "1.0.{i}"
license = "{pyproject_lic}"
[build-system]
requires = ["setuptools"]
""",
        },
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.0.{i}",
            _license=expected_lic,
        ),
        id=f"complex-lic-priority-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", _COMPLEX_CASES)
def test_complex(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    # Use appropriate repo name for version detection in reponame tests
    repo_name = "owner/myproject"
    if "reponame" in name:
        for rn, _, _ in _repo_name_cases:
            if name.split("_")[2] in rn:
                repo_name = rn
                break
    elif "flat_layout" in name:
        idx = int(name.split("_")[-1])
        repo_name = f"owner/flatpkg{idx}"
    elif "src_layout" in name:
        idx = int(name.split("_")[-1])
        repo_name = "owner/srcpkg"
    result = detect_all_specs(tmp_path, repo_name)
    _assert_all(result, **expected)


# =====================================================================
# Category 5: Edge case repos (~200 tests)
# =====================================================================

_EDGE_CASES = []

# Binary files mixed in
for i in range(10):
    _EDGE_CASES.append(pytest.param(
        f"edge_binary_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "binpkg{i}"
version = "1.{i}.0"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "MIT License",
            "tests/__init__.py": "",
        },
        [("data/binary.bin", bytes(range(256)) * (i + 1))],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.{i}.0",
            _license="MIT",
        ),
        id=f"edge-binary-mixed-{i}",
    ))

# Deeply nested structure
for depth in range(1, 11):
    nested = "/".join([f"d{j}" for j in range(depth)])
    _EDGE_CASES.append(pytest.param(
        f"edge_deep_nested_{depth}",
        {
            "pyproject.toml": f"""\
[project]
name = "deep{depth}"
version = "0.{depth}.0"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            f"{nested}/module.py": "x = 1",
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"0.{depth}.0",
            _license="MIT",
        ),
        id=f"edge-deep-nested-{depth}",
    ))

# Unicode content in files
_unicode_contents = [
    "# Comment with unicode: cafe resume",
    "# Chinese: \u4f60\u597d",
    "# Japanese: \u3053\u3093\u306b\u3061\u306f",
    "# Korean: \uc548\ub155\ud558\uc138\uc694",
    "# Arabic: \u0645\u0631\u062d\u0628\u0627",
    "# Emoji: star sun moon",
    "# Greek: \u03b1\u03b2\u03b3",
    "# Math: \u2200x\u2208R",
    "# Accented: naive resume cafe",
    "# Russian: \u041f\u0440\u0438\u0432\u0435\u0442",
]
for i, uc in enumerate(_unicode_contents):
    _EDGE_CASES.append(pytest.param(
        f"edge_unicode_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "unicodepkg"
version = "1.0.{i}"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            f"module_{i}.py": uc,
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.0.{i}",
            _license="MIT",
        ),
        id=f"edge-unicode-content-{i}",
    ))

# Very large files (content)
for i in range(10):
    large_content = "# " + "x" * (1000 * (i + 1)) + "\n"
    _EDGE_CASES.append(pytest.param(
        f"edge_large_file_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "largepkg{i}"
version = "1.{i}.0"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            f"large_{i}.py": large_content,
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.{i}.0",
            _license="MIT",
        ),
        id=f"edge-large-file-{i}",
    ))

# Empty config files
_empty_configs = [
    ("pyproject.toml", ""),
    ("setup.py", ""),
    ("setup.cfg", ""),
    ("tox.ini", ""),
    ("requirements.txt", ""),
]
for i, (fname, content_val) in enumerate(_empty_configs):
    _EDGE_CASES.append(pytest.param(
        f"edge_empty_config_{i}",
        {fname: content_val},
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="" if fname != "requirements.txt" else "requirements.txt",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=["requirements.txt"] if fname == "requirements.txt" else [],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license=None,
        ),
        id=f"edge-empty-config-{fname.replace('.', '_')}",
    ))

# Malformed TOML
for i in range(5):
    _EDGE_CASES.append(pytest.param(
        f"edge_malformed_toml_{i}",
        {
            "pyproject.toml": f"[project\nname = broken{i}",
            "setup.py": f'from setuptools import setup\nsetup(name="fallback{i}", version="9.{i}.0")',
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"9.{i}.0",
            _license="MIT",
        ),
        id=f"edge-malformed-toml-{i}",
    ))

# environment.yaml (not yml)
for i in range(5):
    _EDGE_CASES.append(pytest.param(
        f"edge_env_yaml_{i}",
        {
            "environment.yaml": f"name: env{i}\ndependencies:\n  - numpy",
            "setup.py": f'from setuptools import setup\nsetup(name="yamlpkg{i}")',
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="environment.yaml",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=["environment.yaml"],
            log_parser_type="pytest",
            version=None,
            _license="MIT",
        ),
        id=f"edge-env-yaml-{i}",
    ))

# Fortran one level deep (detected)
for ext in [".f90", ".f", ".f77", ".for"]:
    for i in range(3):
        _EDGE_CASES.append(pytest.param(
            f"edge_fortran_one_deep_{ext}_{i}",
            {
                "pyproject.toml": f"""\
[project]
name = "fortpkg{i}"
version = "1.0.{i}"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                f"sub/solver{i}{ext}": "! Fortran source",
                "LICENSE": "BSD 3-Clause License\nRedistribution and use",
            },
            [],
            dict(
                python_version="3.10",
                install_cmd="pip install -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=["apt-get install -y build-essential",
                                  "apt-get install -y gfortran"],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version=f"1.0.{i}",
                _license="BSD-3-Clause",
            ),
            id=f"edge-fortran-1deep{ext}-{i}",
        ))

# Fortran two levels deep (NOT detected)
for ext in [".f90", ".f", ".f77", ".for"]:
    for i in range(3):
        _EDGE_CASES.append(pytest.param(
            f"edge_fortran_two_deep_{ext}_{i}",
            {
                "pyproject.toml": f"""\
[project]
name = "deepfort{i}"
version = "2.0.{i}"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                f"a/b/solver{i}{ext}": "! Fortran source",
                "LICENSE": "MIT License",
            },
            [],
            dict(
                python_version="3.10",
                install_cmd="pip install -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=[],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version=f"2.0.{i}",
                _license="MIT",
            ),
            id=f"edge-fortran-2deep{ext}-{i}",
        ))

# Nested meson.build (not at root, NOT detected)
for i in range(5):
    _EDGE_CASES.append(pytest.param(
        f"edge_nested_meson_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "nestmeson{i}"
version = "1.0.{i}"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            f"sub{i}/meson.build": "project('x', 'c')",
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.0.{i}",
            _license="MIT",
        ),
        id=f"edge-nested-meson-{i}",
    ))

# setup.cfg version with attr: or file: prefix (should be skipped)
for i, prefix in enumerate(["attr:", "file:", "attr: ", "file: "]):
    _EDGE_CASES.append(pytest.param(
        f"edge_cfg_dynamic_ver_{i}",
        {
            "setup.cfg": f"[metadata]\nname = dynver{i}\nversion = {prefix}pkg.__version__",
            "VERSION": f"8.{i}.0",
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"8.{i}.0",
            _license="MIT",
        ),
        id=f"edge-cfg-dynamic-ver-{i}",
    ))

# Log parser type: django (runtests.py in test cmd)
for i in range(5):
    _EDGE_CASES.append(pytest.param(
        f"edge_log_parser_django_{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="djangoapp{i}", version="4.{i}")',
            "tox.ini": "[tox]\nenvlist = py310\n\n[testenv]\ncommands = python runtests.py",
            "tests/__init__.py": "",
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="python runtests.py",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="django",
            version=f"4.{i}",
            _license="BSD-3-Clause",
        ),
        id=f"edge-log-parser-django-{i}",
    ))

# Log parser type: sympy (bin/test in test cmd)
for i in range(5):
    _EDGE_CASES.append(pytest.param(
        f"edge_log_parser_sympy_{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="sympylike{i}", version="1.1{i}")',
            "tox.ini": "[tox]\nenvlist = py310\n\n[testenv]\ncommands = bin/test",
            "tests/__init__.py": "",
            "LICENSE": "BSD 3-Clause License\nRedistribution and use",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="bin/test",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="sympy",
            version=f"1.1{i}",
            _license="BSD-3-Clause",
        ),
        id=f"edge-log-parser-sympy-{i}",
    ))

# Version from version.txt
for i in range(5):
    _EDGE_CASES.append(pytest.param(
        f"edge_version_txt_{i}",
        {
            "version.txt": f"6.{i}.0",
            "setup.py": "from setuptools import setup\nsetup(name='vtxtpkg')",
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"6.{i}.0",
            _license="MIT",
        ),
        id=f"edge-version-txt-{i}",
    ))

# Underscore removal fallback for package name
for i, (repo, nouscore_pkg) in enumerate([
    ("owner/my-pkg", "mypkg"),
    ("owner/a-b-c", "abc"),
    ("owner/x-y", "xy"),
]):
    _EDGE_CASES.append(pytest.param(
        f"edge_underscore_removal_{i}",
        {
            "pyproject.toml": """\
[build-system]
requires = ["setuptools"]
""",
            f"{nouscore_pkg}/__init__.py": f'__version__ = "3.{i}.0"',
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"3.{i}.0",
            _license="MIT",
        ),
        id=f"edge-underscore-removal-{repo.replace('/', '_')}",
    ))

# Symlink handling (create if supported)
for i in range(5):
    _EDGE_CASES.append(pytest.param(
        f"edge_many_files_{i}",
        dict(
            [(f"src/mod{j}.py", f"x = {j}") for j in range(20 * (i + 1))]
            + [
                ("pyproject.toml", f"""\
[project]
name = "manypkg{i}"
version = "1.{i}.0"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
"""),
                ("LICENSE", "MIT License"),
                ("tests/__init__.py", ""),
            ]
        ),
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"1.{i}.0",
            _license="MIT",
        ),
        id=f"edge-many-files-{i}",
    ))

# Scikit-build triggers --no-build-isolation
for i in range(5):
    _EDGE_CASES.append(pytest.param(
        f"edge_scikit_build_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "skbuild{i}"
version = "0.{i}.0"
requires-python = ">=3.10"
[build-system]
requires = ["scikit-build-core>=0.5"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version="3.10",
            install_cmd="pip install --no-build-isolation -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"0.{i}.0",
            _license="MIT",
        ),
        id=f"edge-scikit-build-{i}",
    ))

# setup.py with python_requires using ==
for i in range(5):
    ver = f"3.{i+8}"
    _EDGE_CASES.append(pytest.param(
        f"edge_pyreq_eq_{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="eqpkg", python_requires="=={ver}")',
            "LICENSE": "MIT License",
        },
        [],
        dict(
            python_version=ver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source="",
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=[],
            env_yml_paths=[],
            log_parser_type="pytest",
            version=None,
            _license="MIT",
        ),
        id=f"edge-pyreq-eq-{ver}",
    ))


@pytest.mark.parametrize("name,files,binary_files,expected", _EDGE_CASES)
def test_edge(tmp_path, name, files, binary_files, expected):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    for relpath, data in binary_files:
        _wb(tmp_path, relpath, data)
    repo_name = "owner/myedgepkg"
    if "underscore_removal" in name:
        idx = int(name.split("_")[-1])
        repos = ["owner/my-pkg", "owner/a-b-c", "owner/x-y"]
        repo_name = repos[idx]
    result = detect_all_specs(tmp_path, repo_name)
    _assert_all(result, **expected)


# =====================================================================
# Category 6: Additional parametric variations to reach ~1000 tests
# =====================================================================

# --- More archetype combos with varied Python versions ---
_EXTRA_ARCH_CASES = []

_all_backends = [
    ("meson-python>=0.13", "pip install --no-build-isolation -e ."),
    ("scikit-build>=0.17", "pip install --no-build-isolation -e ."),
    ("setuptools>=64", "pip install -e ."),
    ("hatchling>=1.0", "pip install -e ."),
    ("flit-core>=3.2", "pip install -e ."),
    ("poetry-core>=1.0", "pip install -e ."),
    ("pdm-backend>=2.0", "pip install -e ."),
    ("pdm-pep517>=1.0", "pip install -e ."),
]

_all_licenses_for_extra = {
    "MIT": "MIT License",
    "Apache-2.0": "Apache License\nVersion 2.0",
    "BSD-3-Clause": "BSD 3-Clause License\nRedistribution and use",
    "BSD-2-Clause": "BSD 2-Clause\nSimplified BSD",
    "ISC": "ISC License",
}

_python_versions_extra = ["3.8", "3.9", "3.10", "3.11", "3.12"]

# 8 backends x 5 licenses x 5 python versions = 200 additional
for bi, (backend, install_cmd) in enumerate(_all_backends):
    for li, (lic_name, lic_body) in enumerate(_all_licenses_for_extra.items()):
        for pi, pyver in enumerate(_python_versions_extra):
            idx = bi * 25 + li * 5 + pi
            needs_meson = "meson" in backend.lower() or "scikit" in backend.lower()
            pre_install = []
            files = {
                "pyproject.toml": f"""\
[project]
name = "extra{idx}"
version = "0.{idx}.0"
requires-python = ">={pyver}"
[build-system]
requires = ["{backend}"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                "LICENSE": lic_body,
                "tests/__init__.py": "",
            }
            _EXTRA_ARCH_CASES.append(pytest.param(
                f"extra_arch_{idx}",
                files,
                dict(
                    python_version=pyver,
                    install_cmd=install_cmd,
                    test_cmd_override="pytest {test_files}",
                    packages_source="",
                    pip_packages=[],
                    pre_install_cmds=pre_install,
                    reqs_paths=[],
                    env_yml_paths=[],
                    log_parser_type="pytest",
                    version=f"0.{idx}.0",
                    _license=lic_name,
                ),
                id=f"extra-arch-{backend.split('>=')[0].split('>')[0]}-{lic_name}-py{pyver}",
            ))


@pytest.mark.parametrize("name,files,expected", _EXTRA_ARCH_CASES)
def test_extra_archetype(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/extrapkg")
    _assert_all(result, **expected)


# --- More version detection variations ---
_EXTRA_VERSION_CASES = []

# Version from setup.py with different formats
_setup_py_ver_formats = [
    ('version="{ver}"', "eq_no_space"),
    ('version = "{ver}"', "eq_space"),
    ("version=\'{ver}\'", "sq_no_space"),
    ("version = \'{ver}\'", "sq_space"),
]
for fi, (fmt, fmt_name) in enumerate(_setup_py_ver_formats):
    for vi in range(10):
        ver = f"{vi+1}.{vi}.{vi+2}"
        setup_content = f"from setuptools import setup\nsetup(name='vpkg', {fmt.format(ver=ver)})"
        _EXTRA_VERSION_CASES.append(pytest.param(
            f"extra_ver_setup_{fmt_name}_{vi}",
            {"setup.py": setup_content, "LICENSE": "MIT License"},
            ver,
            id=f"extra-ver-setup-{fmt_name}-{vi}",
        ))

# Version from _version.py
for i in range(10):
    ver = f"10.{i}.0"
    _EXTRA_VERSION_CASES.append(pytest.param(
        f"extra_ver_version_py_{i}",
        {
            "pyproject.toml": """\
[build-system]
requires = ["setuptools"]
""",
            "extraverpkg/_version.py": f'__version__ = "{ver}"',
            "LICENSE": "MIT License",
        },
        ver,
        id=f"extra-ver-version-py-{i}",
    ))

# Version from src layout
for i in range(10):
    ver = f"11.{i}.0"
    _EXTRA_VERSION_CASES.append(pytest.param(
        f"extra_ver_src_{i}",
        {
            "pyproject.toml": """\
[build-system]
requires = ["setuptools"]
""",
            "src/extraverpkg/__init__.py": f'__version__ = "{ver}"',
            "LICENSE": "MIT License",
        },
        ver,
        id=f"extra-ver-src-layout-{i}",
    ))

# Version from src/_version.py
for i in range(10):
    ver = f"12.{i}.0"
    _EXTRA_VERSION_CASES.append(pytest.param(
        f"extra_ver_src_version_{i}",
        {
            "pyproject.toml": """\
[build-system]
requires = ["setuptools"]
""",
            "src/extraverpkg/_version.py": f'__version__ = "{ver}"',
            "LICENSE": "MIT License",
        },
        ver,
        id=f"extra-ver-src-version-py-{i}",
    ))


@pytest.mark.parametrize("name,files,expected_version", _EXTRA_VERSION_CASES)
def test_extra_version(tmp_path, name, files, expected_version):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/extraverpkg")
    assert result["version"] == expected_version


# --- More dependency source combinations ---
_EXTRA_DEP_CASES = []

# requirements dir with different numbers of files
for count in range(1, 11):
    files = {
        "pyproject.toml": """\
[project]
name = "deppkg"
version = "1.0.0"
[build-system]
requires = ["setuptools"]
""",
        "LICENSE": "MIT License",
    }
    expected_paths = []
    for j in range(count):
        fname = f"requirements/r{j:02d}.txt"
        files[fname] = f"dep{j}>=1.0"
        expected_paths.append(fname)
    expected_paths.sort()
    _EXTRA_DEP_CASES.append(pytest.param(
        f"extra_dep_reqdir_{count}",
        files,
        "requirements.txt",
        expected_paths,
        [],
        [],
        id=f"extra-dep-reqdir-{count}-files",
    ))

# pyproject deps as pip_packages (no requirements.txt or env yml)
for count in range(1, 11):
    deps = [f'"extradep{j}>=1.0"' for j in range(count)]
    deps_list = [f"extradep{j}>=1.0" for j in range(count)]
    _EXTRA_DEP_CASES.append(pytest.param(
        f"extra_dep_pyproject_{count}",
        {
            "pyproject.toml": f"""\
[project]
name = "deppkg"
version = "1.0.0"
dependencies = [{", ".join(deps)}]
[build-system]
requires = ["setuptools"]
""",
            "LICENSE": "MIT License",
        },
        "",
        [],
        deps_list,
        [],
        id=f"extra-dep-pyproject-{count}-deps",
    ))

# environment.yml priority over requirements.txt
for i in range(5):
    _EXTRA_DEP_CASES.append(pytest.param(
        f"extra_dep_env_priority_{i}",
        {
            "environment.yml": f"name: env{i}\ndeps:\n  - numpy",
            "requirements.txt": f"req{i}>=1.0",
            "pyproject.toml": """\
[project]
name = "envpkg"
version = "1.0.0"
[build-system]
requires = ["setuptools"]
""",
            "LICENSE": "MIT License",
        },
        "environment.yml",
        [],
        [],
        ["environment.yml"],
        id=f"extra-dep-env-priority-{i}",
    ))


@pytest.mark.parametrize("name,files,exp_source,exp_reqs,exp_pips,exp_envs", _EXTRA_DEP_CASES)
def test_extra_dep_source(tmp_path, name, files, exp_source, exp_reqs, exp_pips, exp_envs):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/deppkg")
    assert result["packages_source"] == exp_source
    assert result["reqs_paths"] == exp_reqs
    assert result["pip_packages"] == exp_pips
    assert result["env_yml_paths"] == exp_envs


# --- More pre-install combination tests ---
_EXTRA_PRE_CASES = []

# C ext keywords in setup.py (various keywords)
_c_ext_keywords = [
    ("ext_modules = []", "ext_modules"),
    ("from setuptools import Extension\nExtension('m', ['m.c'])", "Extension"),
    ("from Cython.Build import cythonize\ncythonize(exts)", "cythonize"),
]
for ki, (kw_content, kw_name) in enumerate(_c_ext_keywords):
    for i in range(5):
        _EXTRA_PRE_CASES.append(pytest.param(
            f"extra_pre_cext_{kw_name}_{i}",
            {
                "setup.py": f"# pkg {i}\n{kw_content}",
                "pyproject.toml": f"""\
[project]
name = "cextpkg{i}"
version = "1.{i}.0"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                "LICENSE": "MIT License",
            },
            ["apt-get install -y build-essential"],
            id=f"extra-pre-cext-{kw_name}-{i}",
        ))

# meson.build at root
for i in range(10):
    _EXTRA_PRE_CASES.append(pytest.param(
        f"extra_pre_meson_{i}",
        {
            "meson.build": f"project('mpkg{i}', 'c')",
            "pyproject.toml": f"""\
[project]
name = "mpkg{i}"
version = "1.{i}.0"
[build-system]
requires = ["meson-python>=0.13"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "MIT License",
        },
        ["apt-get install -y build-essential", "apt-get install -y meson ninja-build"],
        id=f"extra-pre-meson-{i}",
    ))

# BLAS in pyproject only
for i in range(10):
    _EXTRA_PRE_CASES.append(pytest.param(
        f"extra_pre_blas_pyproject_{i}",
        {
            "pyproject.toml": f"""\
[project]
name = "blaspkg{i}"
version = "1.{i}.0"
description = "Uses openblas for linear algebra"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
            "LICENSE": "MIT License",
        },
        ["apt-get install -y build-essential", "apt-get install -y libopenblas-dev"],
        id=f"extra-pre-blas-pyproject-{i}",
    ))


@pytest.mark.parametrize("name,files,expected_pre_install", _EXTRA_PRE_CASES)
def test_extra_pre_install(tmp_path, name, files, expected_pre_install):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/prepkg")
    assert result["pre_install_cmds"] == expected_pre_install


# --- More test command detection ---
_EXTRA_TEST_CMD_CASES = []

# tests/ dir detection
for i in range(10):
    _EXTRA_TEST_CMD_CASES.append(pytest.param(
        f"extra_testcmd_tests_dir_{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="tcpkg{i}")',
            f"tests/test_mod{i}.py": f"def test_{i}(): pass",
            "LICENSE": "MIT License",
        },
        "pytest tests/",
        "pytest",
        id=f"extra-testcmd-tests-dir-{i}",
    ))

# test/ dir detection
for i in range(10):
    _EXTRA_TEST_CMD_CASES.append(pytest.param(
        f"extra_testcmd_test_dir_{i}",
        {
            "setup.py": f'from setuptools import setup\nsetup(name="tcpkg{i}")',
            f"test/test_mod{i}.py": f"def test_{i}(): pass",
            "LICENSE": "MIT License",
        },
        "pytest test/",
        "pytest",
        id=f"extra-testcmd-test-dir-{i}",
    ))

# setup.cfg [tool:pytest] detection
for i in range(10):
    _EXTRA_TEST_CMD_CASES.append(pytest.param(
        f"extra_testcmd_cfg_{i}",
        {
            "setup.cfg": f"[metadata]\nname = cfgpkg{i}\n\n[tool:pytest]\naddopts = -v",
            "LICENSE": "MIT License",
        },
        "pytest {test_files}",
        "pytest",
        id=f"extra-testcmd-cfg-{i}",
    ))


@pytest.mark.parametrize("name,files,expected_cmd,expected_parser", _EXTRA_TEST_CMD_CASES)
def test_extra_test_cmd(tmp_path, name, files, expected_cmd, expected_parser):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/tcpkg")
    assert result["test_cmd_override"] == expected_cmd
    assert result["log_parser_type"] == expected_parser


# =====================================================================
# Category 7: Final batch to reach ~1000 tests
# =====================================================================

_FINAL_CASES = []

# Full pipeline with license from pyproject classifiers
_classifier_licenses = [
    ("License :: OSI Approved :: MIT License", "MIT"),
    ("License :: OSI Approved :: Apache Software License 2.0", "Apache-2.0"),
    ("License :: OSI Approved :: BSD 3-Clause License", "BSD-3-Clause"),
    ("License :: OSI Approved :: BSD 2-Clause License", "BSD-2-Clause"),
    ("License :: OSI Approved :: ISC License (ISCL)", "ISC"),
]
for ci, (cls, expected_lic) in enumerate(_classifier_licenses):
    for pyver in ["3.9", "3.10", "3.11", "3.12"]:
        _FINAL_CASES.append(pytest.param(
            f"final_cls_lic_{ci}_{pyver}",
            {
                "pyproject.toml": f"""\
[project]
name = "clspkg"
version = "1.0.{ci}"
requires-python = ">={pyver}"
classifiers = ["{cls}"]
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                "tests/__init__.py": "",
            },
            dict(
                python_version=pyver,
                install_cmd="pip install -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=[],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version=f"1.0.{ci}",
                _license=expected_lic,
            ),
            id=f"final-cls-lic-{expected_lic}-py{pyver}",
        ))

# License from pyproject license dict with text key
for li, (lic_name, lic_text) in enumerate([
    ("MIT", "MIT"), ("Apache-2.0", "Apache-2.0"), ("BSD-3-Clause", "BSD-3-Clause"),
    ("BSD-2-Clause", "BSD-2-Clause"), ("ISC", "ISC"),
]):
    for i in range(4):
        _FINAL_CASES.append(pytest.param(
            f"final_lic_dict_{li}_{i}",
            {
                "pyproject.toml": f"""\
[project]
name = "dictlicpkg"
version = "2.{li}.{i}"
[project.license]
text = "{lic_text}"
[build-system]
requires = ["setuptools"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                "tests/__init__.py": "",
            },
            dict(
                python_version="3.10",
                install_cmd="pip install -e .",
                test_cmd_override="pytest {test_files}",
                packages_source="",
                pip_packages=[],
                pre_install_cmds=[],
                reqs_paths=[],
                env_yml_paths=[],
                log_parser_type="pytest",
                version=f"2.{li}.{i}",
                _license=lic_name,
            ),
            id=f"final-lic-dict-{lic_name}-{i}",
        ))

# Full end-to-end: all fields tested together across many repos
for i in range(20):
    pyver = ["3.8", "3.9", "3.10", "3.11", "3.12"][i % 5]
    backend = ["setuptools", "hatchling", "flit-core>=3.2", "poetry-core", "pdm-backend"][i % 5]
    lic_name = ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC", "BSD-2-Clause"][i % 5]
    lic_body = {
        "MIT": "MIT License",
        "Apache-2.0": "Apache License\nVersion 2.0",
        "BSD-3-Clause": "BSD 3-Clause License\nRedistribution and use",
        "ISC": "ISC License",
        "BSD-2-Clause": "BSD 2-Clause\nSimplified BSD",
    }[lic_name]
    has_reqs = i % 3 == 0
    has_tests_dir = i % 2 == 0
    files = {
        "pyproject.toml": f"""\
[project]
name = "finalpkg{i}"
version = "5.{i}.0"
requires-python = ">={pyver}"
[build-system]
requires = ["{backend}"]
[tool.pytest.ini_options]
addopts = "-v"
""",
        "LICENSE": lic_body,
    }
    source = ""
    reqs = []
    if has_reqs:
        files["requirements.txt"] = f"dep{i}>=1.0"
        source = "requirements.txt"
        reqs = ["requirements.txt"]
    if has_tests_dir:
        files["tests/__init__.py"] = ""
    _FINAL_CASES.append(pytest.param(
        f"final_e2e_{i}",
        files,
        dict(
            python_version=pyver,
            install_cmd="pip install -e .",
            test_cmd_override="pytest {test_files}",
            packages_source=source,
            pip_packages=[],
            pre_install_cmds=[],
            reqs_paths=reqs,
            env_yml_paths=[],
            log_parser_type="pytest",
            version=f"5.{i}.0",
            _license=lic_name,
        ),
        id=f"final-e2e-{i}",
    ))


@pytest.mark.parametrize("name,files,expected", _FINAL_CASES)
def test_final(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/finalpkg")
    _assert_all(result, **expected)


# =====================================================================
# Category 8: Last batch to ensure >= 1000
# =====================================================================

_LAST_BATCH_CASES = []

# More version + license + backend combos
_last_versions = ["0.1.0", "1.0.0", "2.0.0", "3.0.0", "10.0.0", "0.0.1", "99.99.99"]
_last_licenses_map = {"MIT": "MIT License", "Apache-2.0": "Apache License\nVersion 2.0"}
for vi, ver in enumerate(_last_versions):
    for li, (lic_name, lic_body) in enumerate(_last_licenses_map.items()):
        for bi, backend in enumerate(["setuptools", "hatchling", "flit-core>=3.2"]):
            _LAST_BATCH_CASES.append(pytest.param(
                f"last_{vi}_{li}_{bi}",
                {
                    "pyproject.toml": f"""\
[project]
name = "lastpkg"
version = "{ver}"
requires-python = ">=3.10"
[build-system]
requires = ["{backend}"]
[tool.pytest.ini_options]
addopts = "-v"
""",
                    "LICENSE": lic_body,
                    "tests/__init__.py": "",
                },
                dict(
                    python_version="3.10",
                    install_cmd="pip install -e .",
                    test_cmd_override="pytest {test_files}",
                    packages_source="",
                    pip_packages=[],
                    pre_install_cmds=[],
                    reqs_paths=[],
                    env_yml_paths=[],
                    log_parser_type="pytest",
                    version=ver,
                    _license=lic_name,
                ),
                id=f"last-{ver}-{lic_name}-{backend.split('>=')[0].split('>')[0]}",
            ))


@pytest.mark.parametrize("name,files,expected", _LAST_BATCH_CASES)
def test_last_batch(tmp_path, name, files, expected):
    for relpath, content in files.items():
        _w(tmp_path, relpath, content)
    result = detect_all_specs(tmp_path, "owner/lastpkg")
    _assert_all(result, **expected)
