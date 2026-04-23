"""
Dynamic spec resolution for arbitrary repos not in MAP_REPO_VERSION_TO_SPECS.

Three-tier fallback:
1. Hardcoded MAP_REPO_VERSION_TO_SPECS (backward compat for known repos)
2. Synthesize from auto-detected instance fields (python_version, install_cmd, etc.)
3. Raise NotImplementedError (neither hardcoded nor auto-detected)
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

from swefficiency.harness.constants import (
    MAP_REPO_TO_ENV_YML_PATHS,
    MAP_REPO_TO_REQS_PATHS,
    MAP_REPO_VERSION_TO_SPECS,
)

if TYPE_CHECKING:
    from swefficiency.harness.constants import SWEfficiencyInstance

logger = logging.getLogger(__name__)

_DYNAMIC_SPECS_CACHE: dict[tuple[str, str, str], dict] = {}
_CACHE_LOCK = threading.Lock()


def get_or_create_specs(
    instance: SWEfficiencyInstance, repo: str, version: str
) -> dict:
    repo = repo.lower()

    if repo in MAP_REPO_VERSION_TO_SPECS:
        repo_specs = MAP_REPO_VERSION_TO_SPECS[repo]
        if version in repo_specs:
            return repo_specs[version]

    # Use instance_id in cache key: instances sharing the same (repo, version)
    # may have different install_cmd / test_cmd_override fields.
    instance_id = instance.get("instance_id", "")
    cache_key = (repo, version, instance_id)
    with _CACHE_LOCK:
        if cache_key in _DYNAMIC_SPECS_CACHE:
            return _DYNAMIC_SPECS_CACHE[cache_key]

        if "python_version" not in instance and "install_cmd" not in instance:
            raise NotImplementedError(
                f"Repo {repo} version {version} not in MAP_REPO_VERSION_TO_SPECS "
                f"and instance has no auto-detected fields (python_version, install_cmd). "
                f"Run scripts/detect_repo_specs.py to enrich your dataset first."
            )

        specs = _synthesize_specs(instance)
        _register_dynamic_paths(instance, repo)
        _DYNAMIC_SPECS_CACHE[cache_key] = specs

    logger.info(
        "Synthesized specs for %s@%s: python=%s install=%s",
        repo,
        version,
        specs.get("python", "?"),
        specs.get("install", "?"),
    )
    return specs


def _synthesize_specs(instance: SWEfficiencyInstance) -> dict:
    specs: dict = {
        "python": instance.get("python_version", "3.10"),
        "install": instance.get("install_cmd", "pip install -e ."),
        "test_cmd": instance.get("test_cmd_override", "pytest {test_files}"),
    }

    packages_source = instance.get("packages_source", "")
    if packages_source == "requirements.txt":
        specs["packages"] = "requirements.txt"
    elif packages_source == "environment.yml":
        specs["packages"] = "environment.yml"
    else:
        specs["packages"] = ""

    pip_packages = instance.get("pip_packages", [])
    if pip_packages:
        specs["pip_packages"] = pip_packages

    pre_install = instance.get("pre_install_cmds", [])
    if pre_install:
        specs["pre_install"] = pre_install

    return specs


def _register_dynamic_paths(instance: SWEfficiencyInstance, repo: str) -> None:
    repo = repo.lower()

    reqs_paths = instance.get("reqs_paths")
    if reqs_paths and repo not in MAP_REPO_TO_REQS_PATHS:
        MAP_REPO_TO_REQS_PATHS[repo] = reqs_paths

    env_yml_paths = instance.get("env_yml_paths")
    if env_yml_paths and repo not in MAP_REPO_TO_ENV_YML_PATHS:
        MAP_REPO_TO_ENV_YML_PATHS[repo] = env_yml_paths


def get_log_parser(repo: str) -> Callable:
    from swefficiency.harness.log_parsers import (
        MAP_REPO_TO_PARSER,
        parse_log_pytest,
    )

    repo = repo.lower()
    return MAP_REPO_TO_PARSER.get(repo, parse_log_pytest)


def get_log_parser_by_type(parser_type: str | None) -> Callable:
    if not parser_type:
        from swefficiency.harness.log_parsers import parse_log_pytest

        return parse_log_pytest

    from swefficiency.harness import log_parsers

    _PARSER_TYPE_MAP = {
        "pytest": log_parsers.parse_log_pytest,
        "pytest_v2": log_parsers.parse_log_pytest_v2,
        "django": log_parsers.parse_log_django,
        "sympy": log_parsers.parse_log_sympy,
        "astropy": log_parsers.parse_log_astropy,
        "numpy": log_parsers.parse_log_numpy,
        "scipy": log_parsers.parse_log_numpy,
    }
    return _PARSER_TYPE_MAP.get(parser_type, log_parsers.parse_log_pytest)
