"""Tests for swefficiency.harness.dynamic_specs — the dynamic spec registry."""

from __future__ import annotations

import threading

import pytest

from swefficiency.harness.constants import (
    MAP_REPO_TO_ENV_YML_PATHS,
    MAP_REPO_TO_REQS_PATHS,
    MAP_REPO_VERSION_TO_SPECS,
)
from swefficiency.harness.dynamic_specs import (
    _DYNAMIC_SPECS_CACHE,
    get_log_parser,
    get_log_parser_by_type,
    get_or_create_specs,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the dynamic specs cache before every test."""
    _DYNAMIC_SPECS_CACHE.clear()
    yield
    _DYNAMIC_SPECS_CACHE.clear()


# ── Tier 1: Hardcoded repo passthrough ──────────────────────────────

def test_hardcoded_repo_returns_existing_specs():
    """Known repo+version returns the MAP entry unchanged."""
    # numpy 1.15 is registered in the hardcoded map
    repo = "numpy/numpy"
    version = "1.15"
    assert repo.lower() in MAP_REPO_VERSION_TO_SPECS
    assert version in MAP_REPO_VERSION_TO_SPECS[repo.lower()]

    instance = {
        "repo": repo,
        "version": version,
        "instance_id": "test",
        "base_commit": "abc",
        "patch": "",
        "test_patch": "",
        "problem_statement": "",
        "hints_text": "",
        "created_at": "",
        "FAIL_TO_PASS": "",
        "PASS_TO_PASS": "",
        "environment_setup_commit": "",
    }
    specs = get_or_create_specs(instance, repo, version)
    assert specs is MAP_REPO_VERSION_TO_SPECS[repo.lower()][version]


def test_hardcoded_repo_case_insensitive():
    """Lookup is case-insensitive."""
    instance = {
        "repo": "NumPy/NumPy",
        "version": "1.15",
        "instance_id": "test",
        "base_commit": "abc",
        "patch": "",
        "test_patch": "",
        "problem_statement": "",
        "hints_text": "",
        "created_at": "",
        "FAIL_TO_PASS": "",
        "PASS_TO_PASS": "",
        "environment_setup_commit": "",
    }
    specs = get_or_create_specs(instance, "NumPy/NumPy", "1.15")
    assert "python" in specs


# ── Tier 2: Synthesize from instance fields ─────────────────────────

def _make_dynamic_instance(**overrides):
    """Helper to create a test instance with dynamic fields."""
    base = {
        "repo": "neworg/newrepo",
        "version": "2.0",
        "instance_id": "neworg__newrepo-123",
        "base_commit": "deadbeef",
        "patch": "",
        "test_patch": "",
        "problem_statement": "",
        "hints_text": "",
        "created_at": "",
        "FAIL_TO_PASS": "",
        "PASS_TO_PASS": "",
        "environment_setup_commit": "",
        "python_version": "3.11",
        "install_cmd": "pip install -e .[dev]",
        "test_cmd_override": "pytest tests/ -x",
        "packages_source": "requirements.txt",
        "pip_packages": ["pytest", "cython"],
        "pre_install_cmds": ["apt-get install -y libfoo-dev"],
        "reqs_paths": ["requirements.txt", "requirements/dev.txt"],
        "env_yml_paths": [],
    }
    base.update(overrides)
    return base


def test_synthesize_from_instance_fields():
    """Unknown repo with auto-detected fields creates valid specs."""
    instance = _make_dynamic_instance()
    specs = get_or_create_specs(instance, "neworg/newrepo", "2.0")

    assert specs["python"] == "3.11"
    assert specs["install"] == "pip install -e .[dev]"
    assert specs["test_cmd"] == "pytest tests/ -x"
    assert specs["packages"] == "requirements.txt"
    assert specs["pip_packages"] == ["pytest", "cython"]
    assert specs["pre_install"] == ["apt-get install -y libfoo-dev"]


def test_synthesize_environment_yml():
    """packages_source=environment.yml sets packages correctly."""
    instance = _make_dynamic_instance(packages_source="environment.yml")
    specs = get_or_create_specs(instance, "neworg/newrepo", "2.0")
    assert specs["packages"] == "environment.yml"


def test_synthesize_empty_packages_source():
    """packages_source='' sets packages to empty string (inline conda)."""
    instance = _make_dynamic_instance(packages_source="")
    specs = get_or_create_specs(instance, "neworg/newrepo", "2.0")
    assert specs["packages"] == ""


def test_synthesize_defaults_when_fields_minimal():
    """Only python_version is enough to trigger synthesis."""
    instance = _make_dynamic_instance()
    # Remove optional fields to test defaults
    del instance["install_cmd"]
    del instance["test_cmd_override"]
    del instance["packages_source"]
    del instance["pip_packages"]
    del instance["pre_install_cmds"]
    del instance["reqs_paths"]

    specs = get_or_create_specs(instance, "neworg/newrepo", "2.0")
    assert specs["python"] == "3.11"
    assert specs["install"] == "pip install -e ."
    assert specs["test_cmd"] == "pytest {test_files}"
    assert specs["packages"] == ""
    assert "pip_packages" not in specs
    assert "pre_install" not in specs


def test_synthesized_specs_are_cached():
    """Second call returns cached specs."""
    instance = _make_dynamic_instance()
    specs1 = get_or_create_specs(instance, "neworg/newrepo", "2.0")
    specs2 = get_or_create_specs(instance, "neworg/newrepo", "2.0")
    assert specs1 is specs2


# ── Tier 3: Missing fields raises ────────────────────────────────────

def test_unknown_repo_no_fields_raises():
    """Unknown repo without auto-detected fields raises NotImplementedError."""
    instance = {
        "repo": "unknown/repo",
        "version": "1.0",
        "instance_id": "test",
        "base_commit": "abc",
        "patch": "",
        "test_patch": "",
        "problem_statement": "",
        "hints_text": "",
        "created_at": "",
        "FAIL_TO_PASS": "",
        "PASS_TO_PASS": "",
        "environment_setup_commit": "",
    }
    with pytest.raises(NotImplementedError, match="detect_repo_specs.py"):
        get_or_create_specs(instance, "unknown/repo", "1.0")


# ── Dynamic path registration ────────────────────────────────────────

def test_dynamic_reqs_path_registration():
    """Synthesis registers reqs_paths into MAP_REPO_TO_REQS_PATHS."""
    repo = "dynamic_test_org/dynamic_test_repo"
    instance = _make_dynamic_instance(
        repo=repo,
        reqs_paths=["requirements.txt", "requirements/dev.txt"],
    )
    get_or_create_specs(instance, repo, "2.0")
    assert repo.lower() in MAP_REPO_TO_REQS_PATHS
    assert MAP_REPO_TO_REQS_PATHS[repo.lower()] == [
        "requirements.txt",
        "requirements/dev.txt",
    ]
    # Cleanup
    MAP_REPO_TO_REQS_PATHS.pop(repo.lower(), None)


def test_dynamic_env_yml_path_registration():
    """Synthesis registers env_yml_paths into MAP_REPO_TO_ENV_YML_PATHS."""
    repo = "dynamic_test_org/dynamic_env_repo"
    instance = _make_dynamic_instance(
        repo=repo,
        packages_source="environment.yml",
        env_yml_paths=["environment.yml"],
    )
    get_or_create_specs(instance, repo, "2.0")
    assert repo.lower() in MAP_REPO_TO_ENV_YML_PATHS
    assert MAP_REPO_TO_ENV_YML_PATHS[repo.lower()] == ["environment.yml"]
    # Cleanup
    MAP_REPO_TO_ENV_YML_PATHS.pop(repo.lower(), None)


def test_no_registration_when_paths_empty():
    """Empty reqs_paths/env_yml_paths don't register."""
    repo = "dynamic_test_org/no_paths_repo"
    instance = _make_dynamic_instance(repo=repo, reqs_paths=[], env_yml_paths=[])
    get_or_create_specs(instance, repo, "2.0")
    assert repo.lower() not in MAP_REPO_TO_REQS_PATHS
    assert repo.lower() not in MAP_REPO_TO_ENV_YML_PATHS


# ── Log parser ────────────────────────────────────────────────────────

def test_get_log_parser_known_repo():
    """Known repo returns its specific parser."""
    from swefficiency.harness.log_parsers import parse_log_django

    parser = get_log_parser("django/django")
    assert parser is parse_log_django


def test_get_log_parser_unknown_repo():
    """Unknown repo returns pytest parser (fallback)."""
    from swefficiency.harness.log_parsers import parse_log_pytest

    parser = get_log_parser("totally_unknown/repo")
    assert parser is parse_log_pytest


def test_get_log_parser_by_type_pytest():
    """Type 'pytest' returns pytest parser."""
    from swefficiency.harness.log_parsers import parse_log_pytest

    parser = get_log_parser_by_type("pytest")
    assert parser is parse_log_pytest


def test_get_log_parser_by_type_django():
    """Type 'django' returns django parser."""
    from swefficiency.harness.log_parsers import parse_log_django

    parser = get_log_parser_by_type("django")
    assert parser is parse_log_django


def test_get_log_parser_by_type_none():
    """None type returns pytest parser."""
    from swefficiency.harness.log_parsers import parse_log_pytest

    parser = get_log_parser_by_type(None)
    assert parser is parse_log_pytest


def test_get_log_parser_by_type_unknown():
    """Unknown type returns pytest parser (fallback)."""
    from swefficiency.harness.log_parsers import parse_log_pytest

    parser = get_log_parser_by_type("nonexistent")
    assert parser is parse_log_pytest


# ── Thread safety ─────────────────────────────────────────────────────

def test_concurrent_get_or_create_specs():
    """Multiple threads synthesizing the same repo don't corrupt cache."""
    results = []
    errors = []

    def worker():
        try:
            instance = _make_dynamic_instance(
                repo="concurrent/repo",
                version="1.0",
            )
            specs = get_or_create_specs(instance, "concurrent/repo", "1.0")
            results.append(specs)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 10
    # All results should be the same object (cached)
    assert all(r is results[0] for r in results)
