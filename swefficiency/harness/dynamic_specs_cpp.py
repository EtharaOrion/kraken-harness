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

"""Dynamic spec synthesis for C++ instances.

Mirrors :mod:`swefficiency.harness.dynamic_specs`. The spec dict returned by
:func:`get_or_create_specs_cpp` is the C++ analog of the Python pipeline's
``SPECS_*`` constants and feeds straight into
``test_spec_cpp.make_*_script_list``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from swefficiency.harness.constants_cpp import (
    BUILD_CMAKE_NINJA,
    DEFAULT_CMAKE_VERSION,
    DEFAULT_CPP_STANDARD,
    DEFAULT_GCC_VERSION,
    MAP_REPO_TO_BUILD_SYSTEM_CPP,
    TEST_FRAMEWORK_CTEST,
)

logger = logging.getLogger(__name__)

_DYNAMIC_SPECS_CACHE_CPP: dict[tuple[str, str], dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _default_specs(repo: str) -> dict[str, Any]:
    repo_specs = MAP_REPO_TO_BUILD_SYSTEM_CPP.get(repo, {})
    return {
        "language": "cpp",
        "build_system": repo_specs.get("build_system", BUILD_CMAKE_NINJA),
        "min_cmake": repo_specs.get("min_cmake", DEFAULT_CMAKE_VERSION),
        "cpp_standard": DEFAULT_CPP_STANDARD,
        "gcc_version": DEFAULT_GCC_VERSION,
        "test_framework": repo_specs.get("test_framework", TEST_FRAMEWORK_CTEST),
        "cmake_flags": [repo_specs["test_flag"]] if "test_flag" in repo_specs else [],
        "system_pkgs": list(repo_specs.get("system_pkgs", [])),
        "packages_source": "",
        "pre_install_cmds": [],
        "install_cmd": (
            "cmake -S /testbed -B /testbed/build "
            "-DCMAKE_BUILD_TYPE=Release "
            "-DCMAKE_C_COMPILER_LAUNCHER=ccache "
            "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache "
            "-G Ninja"
        ),
        "build_cmd": "cmake --build /testbed/build -j$(nproc)",
        "test_cmd": (
            "ctest --test-dir /testbed/build --output-on-failure "
            "--output-junit /tmp/ctest_results.xml -j$(nproc)"
        ),
    }


def _synthesize_specs_cpp(instance: dict) -> dict[str, Any]:
    repo = instance.get("repo", "")
    base_commit = instance.get("base_commit", "")
    base = _default_specs(repo)

    # Detected via detect_repo_specs_cpp; merge if present on the instance.
    repo_specs = instance.get("repo_specs") or {}
    for key in ("cpp_standard", "min_cmake", "system_pkgs", "packages_source",
                "cmake_flags", "pre_install_cmds", "install_cmd", "build_cmd",
                "test_cmd", "test_framework"):
        if key in repo_specs and repo_specs[key]:
            base[key] = repo_specs[key]

    # vcpkg / conan installation step (Phase 1: apt only; vcpkg deferred).
    pkgs_source = base.get("packages_source", "")
    if pkgs_source == "vcpkg.json":
        base.setdefault("pre_install_cmds", []).append(
            "cd /opt/vcpkg && ./vcpkg install --x-manifest-root=/testbed"
        )
    elif pkgs_source == "conanfile.txt":
        base.setdefault("pre_install_cmds", []).append(
            "cd /testbed && conan install . --build=missing"
        )

    # system_pkgs always installed via apt-get.
    sys_pkgs = base.get("system_pkgs") or []
    if sys_pkgs:
        apt_cmd = "apt-get update && apt-get install -y --no-install-recommends " + " ".join(sys_pkgs)
        base.setdefault("pre_install_cmds", []).insert(0, apt_cmd)

    base["repo"] = repo
    base["base_commit"] = base_commit
    return base


def get_or_create_specs_cpp(
    instance: dict, repo: Optional[str] = None, version: Optional[str] = None
) -> dict[str, Any]:
    """Process-local memoized specs synthesis.

    Cache key is ``(repo, version)`` (matches Python pipeline; instance_id
    is NOT part of the key since instances sharing repo@version share specs).
    """
    repo = repo or instance.get("repo", "")
    version = version or instance.get("version", "")
    cache_key = (repo, version)

    with _CACHE_LOCK:
        cached = _DYNAMIC_SPECS_CACHE_CPP.get(cache_key)
    if cached is not None:
        return cached

    specs = _synthesize_specs_cpp(instance)
    with _CACHE_LOCK:
        _DYNAMIC_SPECS_CACHE_CPP[cache_key] = specs
    return specs
