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

"""Dynamic spec synthesis for TypeScript instances.

Mirrors :mod:`swefficiency.harness.dynamic_specs`. The spec dict returned by
:func:`get_or_create_specs_ts` is the TypeScript analog of the Python
pipeline's ``SPECS_*`` constants and feeds straight into
``test_spec_ts.make_*_script_list``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Optional

from swefficiency.harness.constants_ts import (
    BUILD_NODE,
    DEFAULT_PACKAGE_MANAGER,
    MAP_REPO_TO_BUILD_SYSTEM_TS,
    NODE_VERSION,
    TEST_FRAMEWORK_VITEST,
    TEST_VITEST_JSON_JUNIT,
)

logger = logging.getLogger(__name__)

_DYNAMIC_SPECS_CACHE_TS: dict[tuple[str, str], dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()


def detect_package_manager_ts(repo_dir: str) -> str:
    """Return the package manager implied by lockfiles in ``repo_dir``.

    Lockfile precedence (matches the locked stack contract):
        pnpm-lock.yaml    -> "pnpm"
        yarn.lock         -> "yarn"
        bun.lockb         -> "bun"
        package-lock.json -> "npm"
        none              -> "npm" (fallback)
    """
    candidates = (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("package-lock.json", "npm"),
    )
    for lockfile, pm in candidates:
        if os.path.isfile(os.path.join(repo_dir, lockfile)):
            return pm
    return DEFAULT_PACKAGE_MANAGER


def detect_build_system_ts(repo_dir: str) -> str:
    """Return ``"node"`` if ``repo_dir`` looks like a TypeScript project.

    Phase 1 contract: both ``package.json`` and ``tsconfig.json`` must be
    present at the repo root. Anything else is rejected with a descriptive
    error rather than silently falling back.
    """
    pkg_json = os.path.join(repo_dir, "package.json")
    ts_cfg = os.path.join(repo_dir, "tsconfig.json")
    missing = [
        name for name, path in (("package.json", pkg_json), ("tsconfig.json", ts_cfg))
        if not os.path.isfile(path)
    ]
    if missing:
        raise ValueError(
            f"TypeScript build system detection failed in {repo_dir!r}: "
            f"missing required file(s) at repo root: {', '.join(missing)}"
        )
    return BUILD_NODE


def detect_test_framework_ts(repo_dir: str) -> str:
    """Return ``"vitest"`` if ``repo_dir``'s package.json declares vitest.

    Phase 1 is vitest-only; any other test framework triggers a fail-fast
    error so callers don't silently produce broken specs.
    """
    pkg_path = os.path.join(repo_dir, "package.json")
    if not os.path.isfile(pkg_path):
        raise ValueError(
            f"TypeScript test framework detection failed in {repo_dir!r}: "
            "package.json not found at repo root"
        )
    try:
        with open(pkg_path, "r", encoding="utf-8") as fh:
            pkg = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"TypeScript test framework detection failed in {repo_dir!r}: "
            f"could not parse package.json ({exc})"
        ) from exc

    deps = {}
    for key in ("dependencies", "devDependencies"):
        section = pkg.get(key) or {}
        if isinstance(section, dict):
            deps.update(section)
    if "vitest" in deps:
        return TEST_FRAMEWORK_VITEST
    raise ValueError(
        f"TypeScript test framework detection failed in {repo_dir!r}: "
        "vitest not found in dependencies/devDependencies (Phase 1 is "
        "vitest-only)"
    )


def _default_specs(repo: str) -> dict[str, Any]:
    repo_specs = (
        MAP_REPO_TO_BUILD_SYSTEM_TS.get(repo)
        or MAP_REPO_TO_BUILD_SYSTEM_TS.get(repo.lower(), {})
    )
    pkg_mgr = repo_specs.get("package_manager", DEFAULT_PACKAGE_MANAGER)
    if pkg_mgr == "detect":
        pkg_mgr = DEFAULT_PACKAGE_MANAGER
    return {
        "language": "ts",
        "build_system": repo_specs.get("build_system", BUILD_NODE),
        "node_version": repo_specs.get("node_version", NODE_VERSION),
        "test_framework": repo_specs.get("test_framework", TEST_FRAMEWORK_VITEST),
        "package_manager": pkg_mgr,
        "system_pkgs": list(repo_specs.get("system_pkgs", [])),
        "packages_source": "package.json",
        "pre_install_cmds": [],
        "install_cmd": f"cd /testbed && {pkg_mgr} install",
        "build_cmd": "cd /testbed && npx tsc --noEmit",
        "test_cmd": f"cd /testbed && npx {TEST_VITEST_JSON_JUNIT}",
    }


def _synthesize_specs_ts(instance: dict) -> dict[str, Any]:
    repo = instance.get("repo", "")
    base_commit = instance.get("base_commit", "")
    base = _default_specs(repo)

    # Detected via detect_repo_specs_ts. That script writes enrichment fields
    # onto the instance top level (there is no "repo_specs" subkey) and uses
    # a couple of different field names. Normalize both here so detection
    # results actually reach the build/test commands instead of being
    # silently dropped.
    repo_specs = instance.get("repo_specs") or {}
    if not repo_specs:
        repo_specs = {
            "node_version": instance.get("node_version"),
            "package_manager": instance.get("package_manager"),
            "system_pkgs": instance.get("system_pkgs"),
            "packages_source": instance.get("packages_source"),
            "pre_install_cmds": instance.get("pre_install_cmds"),
            "install_cmd": instance.get("install_cmd"),
            "build_cmd": instance.get("build_cmd"),
            "test_cmd": instance.get("test_cmd") or instance.get("test_cmd_override"),
            "test_framework": instance.get("test_framework"),
        }
    # install_cmd / build_cmd are intentionally NOT copied through: the
    # Phase 1 Node path in test_spec_ts builds those commands itself from
    # package_manager + build_system. A detected install_cmd would shadow
    # that logic and drop the per-repo package_manager autodetect.
    for key in ("node_version", "package_manager", "system_pkgs",
                "packages_source", "pre_install_cmds",
                "test_cmd", "test_framework"):
        if key in repo_specs and repo_specs[key]:
            base[key] = repo_specs[key]

    # If a per-instance package_manager was supplied, rewrite the
    # install_cmd to use it (the default builds the string from
    # DEFAULT_PACKAGE_MANAGER which may not match).
    pkg_mgr = base.get("package_manager") or DEFAULT_PACKAGE_MANAGER
    if pkg_mgr and pkg_mgr != DEFAULT_PACKAGE_MANAGER:
        base["install_cmd"] = f"cd /testbed && {pkg_mgr} install"

    # system_pkgs always installed via apt-get.
    sys_pkgs = base.get("system_pkgs") or []
    if sys_pkgs:
        apt_cmd = "apt-get update && apt-get install -y --no-install-recommends " + " ".join(sys_pkgs)
        base.setdefault("pre_install_cmds", []).insert(0, apt_cmd)

    base["repo"] = repo
    base["base_commit"] = base_commit
    return base


def get_or_create_specs_ts(
    instance: dict, repo: Optional[str] = None, version: Optional[str] = None
) -> dict[str, Any]:
    """Process-local memoized specs synthesis.

    Cache key is ``(repo, version)`` (matches Python pipeline; instance_id
    is NOT part of the key since instances sharing repo@version share
    specs).
    """
    repo = repo or instance.get("repo", "")
    version = version or instance.get("version", "")
    cache_key = (repo, version)

    with _CACHE_LOCK:
        cached = _DYNAMIC_SPECS_CACHE_TS.get(cache_key)
    if cached is not None:
        return cached

    specs = _synthesize_specs_ts(instance)
    with _CACHE_LOCK:
        _DYNAMIC_SPECS_CACHE_TS[cache_key] = specs
    return specs
