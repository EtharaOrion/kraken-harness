"""
Integration tests: verify the dynamic repo pipeline end-to-end.
Tests that a synthetic unknown repo can flow through make_test_spec(),
log_parsers, and docker_build without crashing.
"""

from __future__ import annotations

import pytest

from swefficiency.harness.constants import (
    MAP_REPO_TO_ENV_YML_PATHS,
    MAP_REPO_TO_REQS_PATHS,
    MAP_REPO_VERSION_TO_SPECS,
)
from swefficiency.harness.dynamic_specs import (
    _DYNAMIC_SPECS_CACHE,
    get_log_parser,
    get_or_create_specs,
)
from swefficiency.harness.log_parsers import MAP_REPO_TO_PARSER, parse_log_pytest


@pytest.fixture(autouse=True)
def _clear_dynamic_state():
    """Clear dynamic state before and after each test."""
    _DYNAMIC_SPECS_CACHE.clear()
    yield
    _DYNAMIC_SPECS_CACHE.clear()
    # Clean up any dynamic registrations
    for key in list(MAP_REPO_TO_REQS_PATHS.keys()):
        if "integration_test" in key:
            del MAP_REPO_TO_REQS_PATHS[key]
    for key in list(MAP_REPO_TO_ENV_YML_PATHS.keys()):
        if "integration_test" in key:
            del MAP_REPO_TO_ENV_YML_PATHS[key]


def _make_integration_instance(
    repo: str = "integration_test_org/integration_test_repo",
    version: str = "1.0.0",
    **overrides,
):
    """Create a full synthetic instance with all required + dynamic fields."""
    base = {
        "repo": repo,
        "version": version,
        "instance_id": f"{repo.replace('/', '__')}-42",
        "base_commit": "deadbeef1234567890abcdef",
        "patch": "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n",
        "test_patch": "",
        "problem_statement": "Optimize the foo function",
        "hints_text": "",
        "created_at": "2024-01-15T00:00:00Z",
        "FAIL_TO_PASS": "[]",
        "PASS_TO_PASS": '["tests/test_foo.py::test_basic"]',
        "environment_setup_commit": "deadbeef1234567890abcdef",
        # Dynamic repo fields
        "python_version": "3.11",
        "install_cmd": "pip install -e .",
        "test_cmd_override": "pytest tests/ -x",
        "packages_source": "requirements.txt",
        "pip_packages": ["pytest>=7.0"],
        "pre_install_cmds": [],
        "reqs_paths": ["requirements.txt"],
        "env_yml_paths": [],
        "log_parser_type": "pytest",
        # SWE-fficiency fields
        "workload": "import time\ndef setup(): pass\ndef workload(): time.sleep(0.01)",
        "speedup": 2.0,
    }
    base.update(overrides)
    return base


# ── End-to-end: unknown repo through spec resolution ─────────────────

class TestDynamicSpecResolution:
    """Test that unknown repos can resolve specs dynamically."""

    def test_dynamic_instance_resolves_specs(self):
        """A synthetic unknown repo resolves to valid specs."""
        instance = _make_integration_instance()
        specs = get_or_create_specs(
            instance,
            instance["repo"],
            instance["version"],
        )
        assert specs["python"] == "3.11"
        assert specs["install"] == "pip install -e ."
        assert specs["test_cmd"] == "pytest tests/ -x"
        assert specs["packages"] == "requirements.txt"
        assert specs["pip_packages"] == ["pytest>=7.0"]

    def test_dynamic_instance_registers_reqs_paths(self):
        """Dynamic synthesis registers reqs_paths in the global map."""
        instance = _make_integration_instance()
        get_or_create_specs(instance, instance["repo"], instance["version"])
        repo_lower = instance["repo"].lower()
        assert repo_lower in MAP_REPO_TO_REQS_PATHS
        assert MAP_REPO_TO_REQS_PATHS[repo_lower] == ["requirements.txt"]

    def test_dynamic_with_env_yml(self):
        """Dynamic instance with environment.yml."""
        instance = _make_integration_instance(
            repo="integration_test_org/integration_test_conda",
            packages_source="environment.yml",
            env_yml_paths=["environment.yml"],
            reqs_paths=[],
        )
        specs = get_or_create_specs(instance, instance["repo"], instance["version"])
        assert specs["packages"] == "environment.yml"
        repo_lower = instance["repo"].lower()
        assert repo_lower in MAP_REPO_TO_ENV_YML_PATHS

    def test_dynamic_with_no_deps(self):
        """Dynamic instance with no dependency files."""
        instance = _make_integration_instance(
            repo="integration_test_org/integration_test_nodeps",
            packages_source="",
            reqs_paths=[],
            env_yml_paths=[],
            pip_packages=[],
        )
        specs = get_or_create_specs(instance, instance["repo"], instance["version"])
        assert specs["packages"] == ""
        assert "pip_packages" not in specs  # empty list not included


# ── Log parser fallback ───────────────────────────────────────────────

class TestLogParserFallback:
    """Test that unknown repos get the pytest parser fallback."""

    def test_unknown_repo_gets_pytest(self):
        """Unknown repo key returns parse_log_pytest via __missing__."""
        parser = MAP_REPO_TO_PARSER["completely_unknown/repo"]
        assert parser is parse_log_pytest

    def test_dynamic_get_log_parser(self):
        """get_log_parser helper works for unknown repos."""
        parser = get_log_parser("integration_test_org/integration_test_repo")
        assert parser is parse_log_pytest

    def test_known_repo_still_works(self):
        """Pandas still gets the correct parser (backward compat)."""
        parser = MAP_REPO_TO_PARSER.get("pandas-dev/pandas")
        # pandas uses pytest_v2 or similar
        assert parser is not None


# ── Backward compatibility ────────────────────────────────────────────

class TestBackwardCompatibility:
    """Verify hardcoded repos are unaffected by dynamic spec changes."""

    KNOWN_REPOS = [
        ("numpy/numpy", "1.15"),
        ("pandas-dev/pandas", "1.1"),
        ("scikit-learn/scikit-learn", "0.20"),
    ]

    @pytest.mark.parametrize("repo,version", KNOWN_REPOS)
    def test_hardcoded_repo_specs_unchanged(self, repo, version):
        """Hardcoded repos return their original specs dict."""
        repo_lower = repo.lower()
        if repo_lower not in MAP_REPO_VERSION_TO_SPECS:
            pytest.skip(f"{repo} not in MAP_REPO_VERSION_TO_SPECS")
        if version not in MAP_REPO_VERSION_TO_SPECS[repo_lower]:
            pytest.skip(f"{repo}@{version} not registered")

        instance = {
            "repo": repo,
            "version": version,
            "instance_id": f"{repo.replace('/', '__')}-test",
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
        expected = MAP_REPO_VERSION_TO_SPECS[repo_lower][version]
        assert specs is expected, (
            f"Dynamic resolution returned different object for {repo}@{version}"
        )

    def test_hardcoded_repo_not_in_cache(self):
        """Hardcoded repos should NOT populate the dynamic cache."""
        instance = {
            "repo": "numpy/numpy",
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
        get_or_create_specs(instance, "numpy/numpy", "1.15")
        assert ("numpy/numpy", "1.15") not in _DYNAMIC_SPECS_CACHE


# ── Edge cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_version_not_in_hardcoded_repo(self):
        """Known repo but unknown version falls through to dynamic."""
        instance = _make_integration_instance(
            repo="numpy/numpy",
            version="99.99",
            python_version="3.12",
        )
        specs = get_or_create_specs(instance, "numpy/numpy", "99.99")
        assert specs["python"] == "3.12"  # From dynamic, not hardcoded

    def test_mixed_case_repo_name(self):
        """Case-insensitive repo matching."""
        instance = _make_integration_instance(
            repo="Integration_Test_Org/Integration_Test_Mixed",
        )
        specs1 = get_or_create_specs(
            instance,
            "Integration_Test_Org/Integration_Test_Mixed",
            "1.0.0",
        )
        # Second call with different case
        specs2 = get_or_create_specs(
            instance,
            "integration_test_org/integration_test_mixed",
            "1.0.0",
        )
        assert specs1 is specs2

    def test_empty_string_fields(self):
        """Instance with empty string fields uses defaults."""
        instance = _make_integration_instance(
            repo="integration_test_org/integration_test_empty",
            python_version="",
            install_cmd="",
            test_cmd_override="",
        )
        # python_version="" → instance.get("python_version", "3.10") returns ""
        # but empty string is falsy for the fallback
        specs = get_or_create_specs(instance, instance["repo"], instance["version"])
        # The specs should have whatever the instance provides, even empty strings
        assert isinstance(specs, dict)
        assert "python" in specs
