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

"""C++ ``TestSpec`` and script generators.

Mirrors ``test_spec.py`` but the entire build/test/coverage/perf machinery is
rewritten for CMake + GTest/CTest/Catch2 + Google Benchmark + gcov/lcov.

Critical container paths (mirror Python pipeline):
    /testbed                       repo root (cloned by setup_repo.sh)
    /tmp/patch.diff                applied patch
    /tmp/workload.cc               LLM-generated benchmark source
    /tmp/workload_bin              compiled benchmark
    /tmp/workload_gbench.json      Google Benchmark JSON output
    /tmp/ctest_results.xml         JUnit-format CTest output
    /tmp/gtest_results.xml         JUnit-format GTest output
    /tmp/raw_coverage_data/        gcovr per-test JSON files
    /tmp/all_tests.txt             discovered test names (one per line)
"""

from __future__ import annotations

import hashlib
import json
import platform
import textwrap
import traceback
from dataclasses import dataclass
from typing import Any, Optional, Union, cast

from swefficiency.harness.constants import (
    FAIL_TO_PASS,
    KEY_INSTANCE_ID,
    PASS_TO_PASS,
    USE_X86,
    SWEfficiencyInstance,
)
from swefficiency.harness.constants_cpp import (
    BUILD_CMAKE,
    BUILD_CMAKE_NINJA,
    MAP_REPO_TO_BUILD_SYSTEM_CPP,
    TEST_FRAMEWORK_CATCH2,
    TEST_FRAMEWORK_CTEST,
    TEST_FRAMEWORK_GTEST,
)
from swefficiency.harness.dockerfiles_cpp import (
    get_dockerfile_annotate_instance_cpp,
    get_dockerfile_base_cpp,
    get_dockerfile_env_cpp,
    get_dockerfile_instance_cpp,
)
from swefficiency.harness.utils import get_test_directives

DIFF_MODIFIED_FILE_REGEX = r"--- a/(.*)"

REPO_DIRECTORY = "/testbed"
BUILD_DIR = "/testbed/build"
PATCH_PATH = "/tmp/patch.diff"
WORKLOAD_SRC_PATH = "/tmp/workload.cc"
WORKLOAD_BIN_PATH = "/tmp/workload_bin"
WORKLOAD_JSON_PATH = "/tmp/workload_gbench.json"
CTEST_RESULTS_PATH = "/tmp/ctest_results.xml"
GTEST_RESULTS_PATH = "/tmp/gtest_results.xml"
PER_TEST_COVERAGE_DIR = "/tmp/raw_coverage_data"
ALL_TESTS_PATH = "/tmp/all_tests.txt"

BUILD_TIMEOUT_OVERRIDES_CPP: dict[str, Optional[int]] = {
    "abseil/abseil-cpp": 3600,
    "eigen-mirror/eigen": 5400,
    "fmtlib/fmt": 900,
    "gabime/spdlog": 900,
    "nlohmann/json": 1200,
    "ericniebler/range-v3": 1800,
}


@dataclass
class TestSpecCpp:
    """C++ analog of ``TestSpec`` — same field layout, different scripts."""

    instance_id: str
    repo: str
    version: str
    repo_script_list: list[str]
    eval_script_list: list[str]
    env_script_list: list[str]
    FAIL_TO_PASS: list[str]
    PASS_TO_PASS: list[str]
    base_commit: str

    coverage_script_list: list[str]
    meaningful_edit_script_list: list[str]
    performance_script_list: list[str]
    performance_profiling_script_list: list[str]
    correctness_script_list: list[str]
    introspection_guard_script_list: list[str]

    workload: Optional[str]
    covering_tests: Optional[list[str]]
    single_thread_tests: Optional[list[str]]

    build_timeout: Optional[int]

    @property
    def setup_env_script(self) -> str:
        return "\n".join(["#!/bin/bash", "set -exo pipefail"] + self.env_script_list) + "\n"

    @property
    def eval_script(self) -> str:
        return "\n".join(["#!/bin/bash", "set -xo pipefail"] + self.eval_script_list) + "\n"

    @property
    def install_repo_script(self) -> str:
        return "\n".join(["#!/bin/bash", "set -exo pipefail"] + self.repo_script_list) + "\n"

    @property
    def ast_meaningful_script(self) -> str:
        return (
            "\n".join(["#!/bin/bash", "set -xo pipefail"] + self.meaningful_edit_script_list)
            + "\n"
        )

    @property
    def coverage_script(self) -> str:
        return "\n".join(["#!/bin/bash", "set -xo pipefail"] + self.coverage_script_list) + "\n"

    @property
    def performance_script(self) -> str:
        return (
            "\n".join(["#!/bin/bash", "set -exo pipefail"] + self.performance_script_list) + "\n"
        )

    @property
    def performance_profiling_script(self) -> str:
        return (
            "\n".join(
                ["#!/bin/bash", "set -exo pipefail"] + self.performance_profiling_script_list
            )
            + "\n"
        )

    @property
    def correctness_script(self) -> str:
        return (
            "\n".join(["#!/bin/bash", "set -xo pipefail"] + self.correctness_script_list) + "\n"
        )

    @property
    def introspection_guard_script(self) -> str:
        return (
            "\n".join(
                ["#!/bin/bash", "set -exo pipefail"] + self.introspection_guard_script_list
            )
            + "\n"
        )

    @property
    def base_image_key(self) -> str:
        return "sweb.base.cpp:latest"

    @property
    def env_image_key(self) -> str:
        h = hashlib.sha256()
        h.update(str(self.env_script_list).encode("utf-8"))
        return f"sweb.env.cpp.{h.hexdigest()[:22]}:latest"

    @property
    def instance_image_key(self) -> str:
        return f"sweb.eval.cpp.{self.instance_id}:latest"

    @property
    def annotate_instance_image_key(self) -> str:
        return f"sweb.eval.cpp.{self.instance_id}.annotate:latest"

    def get_instance_container_name(self, run_id: Optional[str] = None) -> str:
        if not run_id:
            return f"sweb.eval.cpp.{self.instance_id}"
        return f"sweb.eval.cpp.{self.instance_id}.{run_id}"

    @property
    def base_dockerfile(self) -> str:
        return get_dockerfile_base_cpp(self.platform)

    @property
    def env_dockerfile(self) -> str:
        return get_dockerfile_env_cpp(self.platform)

    @property
    def instance_dockerfile(self) -> str:
        return get_dockerfile_instance_cpp(self.platform, self.env_image_key)

    @property
    def annotate_instance_dockerfile(self) -> str:
        return get_dockerfile_annotate_instance_cpp(self.platform, self.instance_image_key)

    @property
    def platform(self) -> str:
        machine = platform.machine()
        if machine in {"aarch64", "arm64"} and self.instance_id not in USE_X86:
            return "linux/arm64/v8"
        return "linux/x86_64"


def get_test_specs_from_dataset_cpp(
    dataset: Union[list[SWEfficiencyInstance], list[TestSpecCpp]],
) -> list[TestSpecCpp]:
    """Idempotent: convert instance dicts into ``TestSpecCpp`` objects."""
    if not dataset:
        return []
    if isinstance(dataset[0], TestSpecCpp):
        return cast(list[TestSpecCpp], dataset)

    out: list[TestSpecCpp] = []
    for inst in dataset:
        try:
            out.append(make_test_spec_cpp(inst))
        except NotImplementedError:
            continue
        except Exception as e:
            print(
                f"Error creating cpp test spec for instance "
                f"{inst[KEY_INSTANCE_ID]} version {inst.get('version')}: {e}"
            )
            traceback.print_exc()
    return out


def make_repo_script_list_cpp(
    specs: dict,
    repo: str,
    repo_directory: str,
    base_commit: str,
) -> list[str]:
    """Clone repo, pin commit, scrub remote/tags/reflog. No conda."""
    cmds = [
        f"git clone -o origin https://github.com/{repo} {repo_directory}",
        f"chmod -R 777 {repo_directory}",
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
        "git remote remove origin",
        "git tag -d $(git tag -l) || true",
        "git reflog expire --expire=now --all",
        "git gc --prune=now --aggressive",
        f"TARGET_TIMESTAMP=$(git show -s --format=%ci {base_commit})",
        "AFTER_TIMESTAMP=$(date -d \"$TARGET_TIMESTAMP + 1 second\" '+%Y-%m-%d %H:%M:%S')",
        'COMMIT_COUNT=$(git log --oneline --all --since="$AFTER_TIMESTAMP" | wc -l)',
        '[ "$COMMIT_COUNT" -eq 0 ] || exit 1',
        "git -c user.name='Automated Test' -c user.email='automated@test.com' "
        "commit -a -m 'Fix environment' || true",
    ]
    for pre in specs.get("pre_install_cmds", []) or []:
        cmds.append(pre)
    return cmds


def make_env_script_list_cpp(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
) -> list[str]:
    """Install system packages + optional vcpkg/conan deps. No pip/conda."""
    cmds: list[str] = ["export DEBIAN_FRONTEND=noninteractive"]

    system_pkgs = specs.get("system_pkgs", []) or []
    if system_pkgs:
        cmds.append("apt-get update")
        cmds.append("apt-get install -y --no-install-recommends " + " ".join(system_pkgs))
        cmds.append("apt-get clean && rm -rf /var/lib/apt/lists/*")

    packages_source = specs.get("packages_source") or ""
    if packages_source == "vcpkg.json":
        cmds.extend([
            "if [ ! -d /opt/vcpkg ]; then "
            "git clone https://github.com/microsoft/vcpkg /opt/vcpkg && "
            "/opt/vcpkg/bootstrap-vcpkg.sh -disableMetrics; fi",
            f"cd {REPO_DIRECTORY} && /opt/vcpkg/vcpkg install --x-manifest-root={REPO_DIRECTORY}",
        ])
    elif packages_source == "conanfile.txt" or packages_source == "conanfile.py":
        cmds.extend([
            "pip3 install --no-cache-dir 'conan>=2.0'",
            "conan profile detect --force",
            f"cd {REPO_DIRECTORY} && conan install . --output-folder={BUILD_DIR} "
            "--build=missing -s build_type=Release",
        ])

    for extra in specs.get("env_patches", []) or []:
        cmds.append(extra)

    cmds.append("ccache --version || true")
    return cmds


def _cmake_configure_cmd(specs: dict) -> str:
    cmake_flags = specs.get("cmake_flags", []) or []
    extra = " ".join(cmake_flags)
    build_system = specs.get("build_system", BUILD_CMAKE_NINJA)
    generator = "-G Ninja" if build_system == BUILD_CMAKE_NINJA else ""
    return (
        f"cmake -S {REPO_DIRECTORY} -B {BUILD_DIR} "
        "-DCMAKE_BUILD_TYPE=Release "
        "-DCMAKE_C_COMPILER_LAUNCHER=ccache "
        "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache "
        f"-DCMAKE_CXX_STANDARD={specs.get('cpp_standard', '17')} "
        f"-DCMAKE_EXPORT_COMPILE_COMMANDS=ON "
        f"{generator} {extra}"
    ).strip()


def _cmake_build_cmd() -> str:
    return f"cmake --build {BUILD_DIR} -j$(nproc)"


def make_test_command_cpp(instance: SWEfficiencyInstance, specs: dict) -> str:
    test_framework = specs.get("test_framework", TEST_FRAMEWORK_CTEST)
    custom = specs.get("test_cmd")
    if custom:
        return custom
    if test_framework == TEST_FRAMEWORK_GTEST:
        return (
            f"cd {BUILD_DIR} && find . -type f -executable -name '*test*' "
            "-not -path '*/CMakeFiles/*' "
            f"| xargs -I{{}} sh -c \"{{}} --gtest_output=xml:{GTEST_RESULTS_PATH}\" || true"
        )
    if test_framework == TEST_FRAMEWORK_CATCH2:
        return (
            f"cd {BUILD_DIR} && ctest --output-on-failure "
            f"--output-junit {CTEST_RESULTS_PATH} -j$(nproc)"
        )
    return (
        f"ctest --test-dir {BUILD_DIR} --output-on-failure "
        f"--output-junit {CTEST_RESULTS_PATH} -j$(nproc)"
    )


def _apply_patch_block() -> list[str]:
    return [
        f"cd {REPO_DIRECTORY}",
        f'if [ -s "{PATCH_PATH}" ]; then',
        f'  echo "Applied patch (pred)"',
        f'  git apply --allow-empty -v {PATCH_PATH} || (echo "APPLY_PATCH_FAIL"; exit 1)',
        f'  echo "Applied patch (pred) succeeded"',
        "else",
        '  echo "No patch supplied, applying empty patch"',
        '  echo "Applied patch (pred)"',
        "fi",
    ]


def make_eval_script_list_cpp(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Configure → patch → build → test. Patch BEFORE build per locked decision #6."""
    cmds: list[str] = [
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
        _cmake_configure_cmd(specs),
    ]
    cmds.extend(_apply_patch_block())
    cmds.append(_cmake_build_cmd())
    cmds.append(make_test_command_cpp(instance, specs))
    return cmds


def _discover_tests_block() -> list[str]:
    return [
        f"mkdir -p $(dirname {ALL_TESTS_PATH})",
        f"ctest --test-dir {BUILD_DIR} -N | "
        "awk '/^[ ]*Test [0-9]+:/ {print $3}' "
        f"> {ALL_TESTS_PATH} || true",
        f'echo "Discovered $(wc -l < {ALL_TESTS_PATH}) tests"',
    ]


def make_coverage_script_list_cpp(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Per-test coverage with ``lcov --zerocounters`` + ``--test-name`` annotation.

    Sequential (``xargs -P 1``) per locked decision #5 — reliable over fast for
    Phase 1.
    """
    cflags = (
        "-DCMAKE_C_FLAGS='--coverage -O0 -g' "
        "-DCMAKE_CXX_FLAGS='--coverage -O0 -g' "
        "-DCMAKE_EXE_LINKER_FLAGS='--coverage' "
        "-DCMAKE_SHARED_LINKER_FLAGS='--coverage'"
    )
    coverage_configure = _cmake_configure_cmd(specs) + " " + cflags
    cmds: list[str] = [
        f"mkdir -p {PER_TEST_COVERAGE_DIR}",
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
        f"rm -rf {BUILD_DIR}",
        coverage_configure,
    ]
    cmds.extend(_apply_patch_block())
    cmds.append(_cmake_build_cmd())
    cmds.extend(_discover_tests_block())

    per_test_loop = textwrap.dedent(
        f"""
        if [ -s {ALL_TESTS_PATH} ]; then
          IDX=0
          while IFS= read -r t; do
            [ -z "$t" ] && continue
            IDX=$((IDX+1))
            lcov --directory {BUILD_DIR} --zerocounters || true
            ctest --test-dir {BUILD_DIR} -R "^${{t}}$" --output-on-failure --no-tests=error \\
              || echo "Test $t exited non-zero"
            lcov --capture --directory {BUILD_DIR} \\
              --test-name "$t" \\
              --output-file {PER_TEST_COVERAGE_DIR}/test_${{IDX}}.info \\
              --rc geninfo_auto_base=1 --ignore-errors mismatch || true
            gcovr --root {repo_directory} \\
              --json {PER_TEST_COVERAGE_DIR}/${{IDX}}.json --json-pretty \\
              --filter '{repo_directory}' --gcov-ignore-parse-errors || true
            mv {PER_TEST_COVERAGE_DIR}/${{IDX}}.json {PER_TEST_COVERAGE_DIR}/"$t".json 2>/dev/null || true
          done < {ALL_TESTS_PATH}
        else
          echo "No tests discovered for coverage"
        fi
        """
    ).strip().splitlines()
    cmds.extend(per_test_loop)
    return cmds


def make_meaningful_edit_script_list_cpp(
    instance: SWEfficiencyInstance,
    specs: dict,
    treesitter_env_name: Optional[str],
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Phase 1 stub. Emits sentinels + a single warning line so the eval
    harness's ``check_ast_result`` accepts the edit as meaningful.
    Real libclang / tree-sitter-cpp analysis is Phase 2.
    """
    return [
        "echo 'SWEPERF_AST_START'",
        "echo 'Warning: cpp AST check stubbed - all edits accepted as meaningful'",
        "echo 'SWEPERF_AST_END'",
    ]


def _workload_compile_cmd(specs: dict) -> str:
    cxx_std = specs.get("cpp_standard", "17")
    return (
        f"g++ -O3 -std=c++{cxx_std} {WORKLOAD_SRC_PATH} "
        f"-I{REPO_DIRECTORY}/include -I{BUILD_DIR} "
        f"-L{BUILD_DIR} -lbenchmark -lpthread "
        f"-o {WORKLOAD_BIN_PATH}"
    )


def _workload_run_cmd() -> str:
    # Write benchmark JSON via --benchmark_out=. Redirecting stdout+stderr to
    # the JSON file (the prior `> {WORKLOAD_JSON_PATH} 2>&1` pattern) corrupts
    # the JSON with console summary and any runtime warnings printed to stderr,
    # which fails downstream parse_gbench.py silently.
    return (
        f"taskset -c 0 {WORKLOAD_BIN_PATH} "
        f"--benchmark_out={WORKLOAD_JSON_PATH} "
        "--benchmark_out_format=json "
        "--benchmark_repetitions=10 "
        "--benchmark_display_aggregates_only=true "
        "--benchmark_time_unit=s "
        "--benchmark_min_time=1.0s "
        "> /dev/null 2>&1 || true"
    )


def _emit_perf_sentinels_cmd() -> str:
    return (
        "echo 'START_AFTER_CHANGE:'; "
        f"python3 /tmp/parse_gbench.py {WORKLOAD_JSON_PATH}; "
        "echo 'END_AFTER_CHANGE:'"
    )


def make_performance_script_list_cpp(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Compile Google Benchmark workload, run it, emit ``Mean:``/``Std Dev:``."""
    return [
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
        _cmake_configure_cmd(specs),
    ] + _apply_patch_block() + [
        _cmake_build_cmd(),
        f'[ -f {WORKLOAD_SRC_PATH} ] || (echo "Missing workload at {WORKLOAD_SRC_PATH}"; exit 1)',
        _workload_compile_cmd(specs),
        _workload_run_cmd(),
        _emit_perf_sentinels_cmd(),
    ]


def make_performance_profiling_script_list_cpp(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """``perf record`` profile of the workload binary (best-effort)."""
    return [
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
        _cmake_configure_cmd(specs),
    ] + _apply_patch_block() + [
        _cmake_build_cmd(),
        f'[ -f {WORKLOAD_SRC_PATH} ] || (echo "Missing workload"; exit 1)',
        _workload_compile_cmd(specs),
        f"perf record -o /tmp/perf.data -- taskset -c 0 {WORKLOAD_BIN_PATH} "
        "--benchmark_repetitions=1 --benchmark_min_time=0.1s || true",
        "perf report --input=/tmp/perf.data --no-children --stdio "
        "> /tmp/perf.report 2>&1 || true",
        "head -200 /tmp/perf.report || true",
    ]


def get_correctness_script_list_cpp(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Run the eval test command and dump per-test status JSON."""
    test_directives = get_test_directives(instance)
    _ = test_directives
    return [
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
        _cmake_configure_cmd(specs),
    ] + _apply_patch_block() + [
        _cmake_build_cmd(),
        "mkdir -p /tmp/raw_correctness_output",
        f"{make_test_command_cpp(instance, specs)} > /tmp/raw_correctness_output/all.txt 2>&1 || true",
        f'[ -f {CTEST_RESULTS_PATH} ] && cp {CTEST_RESULTS_PATH} /tmp/raw_correctness_output/ctest_results.xml || true',
        f'[ -f {GTEST_RESULTS_PATH} ] && cp {GTEST_RESULTS_PATH} /tmp/raw_correctness_output/gtest_results.xml || true',
    ]


def get_introspection_guard_cmds_cpp(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Phase 1 no-op guard. Future: detect AST-level patch tampering."""
    return ["echo 'cpp introspection guard: no-op'"]


def make_test_spec_cpp(
    instance: SWEfficiencyInstance,
    observed_versions: Optional[set] = None,
) -> TestSpecCpp:
    if isinstance(instance, TestSpecCpp):
        return instance

    instance_id = instance[KEY_INSTANCE_ID]
    if instance_id != instance_id.lower():
        print(
            f"Instance {instance_id} has uppercase chars; converting to lowercase."
        )
        instance_id = instance_id.lower()

    repo = instance["repo"].lower()
    version = instance.get("version", "0.0")
    base_commit = instance["base_commit"]
    test_patch = instance.get("test_patch", "")

    # No allow-list: dynamic_specs_cpp.get_or_create_specs_cpp synthesizes defaults
    # for repos not in MAP_REPO_TO_BUILD_SYSTEM_CPP. Unknown repos get the standard
    # cmake/ninja/ctest path; per-repo overrides (system_pkgs, test_flag) come from
    # detect_repo_specs_cpp.py at enrichment time.
    build_timeout = BUILD_TIMEOUT_OVERRIDES_CPP.get(repo)

    def _from_json_or_obj(key: str) -> Any:
        v = instance.get(key)
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return v if v is not None else []

    pass_to_pass = _from_json_or_obj(PASS_TO_PASS)
    fail_to_pass = _from_json_or_obj(FAIL_TO_PASS)
    covering_tests = _from_json_or_obj("covering_tests")

    from swefficiency.harness.dynamic_specs_cpp import get_or_create_specs_cpp

    specs = get_or_create_specs_cpp(instance, repo, version)

    if observed_versions is not None:
        if version in observed_versions:
            raise RuntimeError(f"Version already observed: {version}")
        observed_versions.add(version)

    env_name = "testbed"
    repo_directory = REPO_DIRECTORY

    repo_script_list = make_repo_script_list_cpp(specs, repo, repo_directory, base_commit)
    env_script_list = make_env_script_list_cpp(instance, specs, env_name)
    eval_script_list = make_eval_script_list_cpp(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    coverage_script_list = make_coverage_script_list_cpp(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    meaningful_edit_script_list = make_meaningful_edit_script_list_cpp(
        instance, specs, None, repo_directory, base_commit, test_patch
    )
    performance_script_list = make_performance_script_list_cpp(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    performance_profiling_script_list = make_performance_profiling_script_list_cpp(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    correctness_script_list = get_correctness_script_list_cpp(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    introspection_guard_script_list = get_introspection_guard_cmds_cpp(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )

    workload_text = instance.get("workload", "") or ""
    if not isinstance(workload_text, str) or workload_text.strip() in ("", "nan"):
        workload_text = None

    return TestSpecCpp(
        instance_id=instance_id,
        repo=repo,
        version=str(version),
        repo_script_list=repo_script_list,
        env_script_list=env_script_list,
        eval_script_list=eval_script_list,
        FAIL_TO_PASS=fail_to_pass,
        PASS_TO_PASS=pass_to_pass,
        base_commit=base_commit,
        coverage_script_list=coverage_script_list,
        meaningful_edit_script_list=meaningful_edit_script_list,
        performance_script_list=performance_script_list,
        performance_profiling_script_list=performance_profiling_script_list,
        correctness_script_list=correctness_script_list,
        introspection_guard_script_list=introspection_guard_script_list,
        workload=workload_text,
        covering_tests=covering_tests,
        single_thread_tests=instance.get("single_thread_tests", []),
        build_timeout=build_timeout,
    )
