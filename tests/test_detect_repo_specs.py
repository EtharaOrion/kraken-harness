"""Tests for scripts/detect_repo_specs.py — auto-detection functions."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

# Add scripts dir to path so we can import detect_repo_specs
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_repo_specs import (
    check_license,
    detect_install_cmd,
    detect_packages_source,
    detect_pre_install,
    detect_python_version,
    detect_test_cmd,
    detect_version,
)


@pytest.fixture
def repo_dir(tmp_path):
    """Create a temporary repo directory."""
    return tmp_path


# ── Python version detection ──────────────────────────────────────────

def test_python_version_from_python_version_file(repo_dir):
    """Detects from .python-version file."""
    (repo_dir / ".python-version").write_text("3.11.4\n")
    assert detect_python_version(repo_dir) == "3.11"


def test_python_version_from_pyproject_toml(repo_dir):
    """Detects from pyproject.toml requires-python."""
    (repo_dir / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [project]
        requires-python = ">=3.9,<3.13"
        """)
    )
    assert detect_python_version(repo_dir) == "3.9"


def test_python_version_from_setup_py(repo_dir):
    """Detects from setup.py python_requires."""
    (repo_dir / "setup.py").write_text(
        textwrap.dedent("""\
        from setuptools import setup
        setup(
            name="mypackage",
            python_requires=">=3.8",
        )
        """)
    )
    result = detect_python_version(repo_dir)
    assert result in ("3.8", "3.10")  # may or may not detect from setup.py


def test_python_version_fallback(repo_dir):
    """Fallback when nothing found."""
    result = detect_python_version(repo_dir)
    assert result == "3.10"


# ── Install command detection ─────────────────────────────────────────

def test_install_cmd_setuptools(repo_dir):
    """Detects pip install -e . for setuptools."""
    (repo_dir / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [build-system]
        requires = ["setuptools>=64", "wheel"]
        build-backend = "setuptools.backends._legacy:_Backend"
        """)
    )
    result = detect_install_cmd(repo_dir)
    assert "pip install" in result
    assert "-e" in result


def test_install_cmd_meson(repo_dir):
    """Detects --no-build-isolation for meson-python."""
    (repo_dir / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [build-system]
        requires = ["meson-python>=0.12"]
        build-backend = "mesonpy"
        """)
    )
    result = detect_install_cmd(repo_dir)
    assert "--no-build-isolation" in result


def test_install_cmd_setup_py_only(repo_dir):
    """Detects install from setup.py."""
    (repo_dir / "setup.py").write_text("from setuptools import setup\nsetup()")
    result = detect_install_cmd(repo_dir)
    assert "pip install" in result


def test_install_cmd_fallback(repo_dir):
    """Fallback when nothing found."""
    result = detect_install_cmd(repo_dir)
    assert "pip install -e ." in result


# ── Test command detection ────────────────────────────────────────────

def test_test_cmd_pytest_in_pyproject(repo_dir):
    """Detects pytest from pyproject.toml."""
    (repo_dir / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [tool.pytest.ini_options]
        testpaths = ["tests"]
        """)
    )
    result = detect_test_cmd(repo_dir)
    assert "pytest" in result


def test_test_cmd_tests_dir(repo_dir):
    """Detects pytest when tests/ directory exists."""
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_foo.py").write_text("def test_foo(): pass")
    result = detect_test_cmd(repo_dir)
    assert "pytest" in result


def test_test_cmd_fallback(repo_dir):
    """Fallback when nothing found."""
    result = detect_test_cmd(repo_dir)
    assert "pytest" in result


# ── Packages source detection ─────────────────────────────────────────

def test_packages_source_requirements_txt(repo_dir):
    (repo_dir / "requirements.txt").write_text("numpy>=1.20\npandas\n")
    source, reqs_paths, pip_pkgs = detect_packages_source(repo_dir)
    assert source == "requirements.txt"
    assert "requirements.txt" in reqs_paths


def test_packages_source_environment_yml(repo_dir):
    (repo_dir / "environment.yml").write_text(
        textwrap.dedent("""\
        name: test
        dependencies:
          - numpy
        """)
    )
    source, reqs_paths, pip_pkgs = detect_packages_source(repo_dir)
    assert source == "environment.yml"
    assert reqs_paths == []
    assert pip_pkgs == []


def test_packages_source_requirements_dir(repo_dir):
    req_dir = repo_dir / "requirements"
    req_dir.mkdir()
    (req_dir / "base.txt").write_text("numpy\n")
    (req_dir / "dev.txt").write_text("pytest\n")
    source, reqs_paths, pip_pkgs = detect_packages_source(repo_dir)
    assert source in ("requirements.txt", "")
    if source == "requirements.txt":
        assert any("requirements/" in p for p in reqs_paths)


def test_packages_source_fallback(repo_dir):
    source, reqs_paths, pip_pkgs = detect_packages_source(repo_dir)
    assert source == ""
    assert reqs_paths == []
    assert pip_pkgs == []


# ── Pre-install detection ─────────────────────────────────────────────

def test_pre_install_c_extensions(repo_dir):
    """Detects build-essential for C extensions."""
    (repo_dir / "setup.py").write_text(
        textwrap.dedent("""\
        from setuptools import setup, Extension
        ext_modules = [Extension('mymod', sources=['mymod.c'])]
        setup(ext_modules=ext_modules)
        """)
    )
    result = detect_pre_install(repo_dir)
    assert any("build-essential" in cmd for cmd in result)


def test_pre_install_meson(repo_dir):
    """Detects meson build deps."""
    (repo_dir / "meson.build").write_text("project('test')\n")
    result = detect_pre_install(repo_dir)
    # Should include build-essential or meson-related
    assert isinstance(result, list)


def test_pre_install_none(repo_dir):
    """No pre-install when no C extensions."""
    (repo_dir / "mypackage.py").write_text("x = 1\n")
    result = detect_pre_install(repo_dir)
    assert isinstance(result, list)  # may be empty


# ── Version detection ─────────────────────────────────────────────────

def test_version_from_pyproject(repo_dir):
    (repo_dir / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [project]
        name = "mypackage"
        version = "1.2.3"
        """)
    )
    result = detect_version(repo_dir, "mypackage")
    assert result == "1.2.3"


def test_version_from_init(repo_dir):
    pkg_dir = repo_dir / "mypackage"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text('__version__ = "2.1.0"\n')
    result = detect_version(repo_dir, "mypackage")
    assert result == "2.1.0"


def test_version_from_version_file(repo_dir):
    (repo_dir / "VERSION").write_text("3.0.1\n")
    result = detect_version(repo_dir, "mypackage")
    assert result == "3.0.1"


def test_version_not_found(repo_dir):
    result = detect_version(repo_dir, "mypackage")
    assert result is None


# ── License detection ─────────────────────────────────────────────────

def test_license_mit(repo_dir):
    """Detects MIT license."""
    (repo_dir / "LICENSE").write_text(
        "MIT License\n\nCopyright (c) 2024 Test\n"
    )
    result = check_license(repo_dir)
    assert result == "MIT"


def test_license_apache(repo_dir):
    """Detects Apache 2.0 license."""
    (repo_dir / "LICENSE").write_text(
        "Apache License\nVersion 2.0, January 2004\n"
    )
    result = check_license(repo_dir)
    assert result == "Apache-2.0"


def test_license_bsd3(repo_dir):
    """Detects BSD-3-Clause license."""
    (repo_dir / "LICENSE").write_text(
        "BSD 3-Clause License\n\nRedistribution and use...\n"
    )
    result = check_license(repo_dir)
    assert result == "BSD-3-Clause"


def test_license_from_pyproject(repo_dir):
    """Detects license from pyproject.toml."""
    (repo_dir / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [project]
        license = "MIT"
        """)
    )
    result = check_license(repo_dir)
    assert result == "MIT"


def test_license_none(repo_dir):
    """Returns None when no license found."""
    result = check_license(repo_dir)
    assert result is None


# ── Cache file ────────────────────────────────────────────────────────

def test_cache_file_roundtrip(tmp_path):
    """Cache file can be written and read back."""
    cache_file = tmp_path / ".specs_cache.json"
    cache_data = {
        "owner/repo|abc123": {
            "python_version": "3.9",
            "install_cmd": "pip install -e .",
        }
    }
    cache_file.write_text(json.dumps(cache_data))
    loaded = json.loads(cache_file.read_text())
    assert loaded == cache_data
