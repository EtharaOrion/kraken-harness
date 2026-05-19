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

"""TypeScript ``TestSpec`` and script generators.

Mirrors ``test_spec.py`` (and its cpp sibling) but the entire
build/test/coverage/perf machinery is rewritten for Node 20 + Vitest +
``tsc --noEmit`` + v8 coverage + ``vitest bench`` (tinybench underneath).

Critical container paths (mirror Python pipeline):
    /testbed                            repo root (cloned by setup_repo.sh)
    /tmp/patch.diff                     applied patch
    /tmp/workload.bench.ts              LLM-generated benchmark source
    /tmp/vitest_results.json            Vitest JSON reporter output
    /tmp/vitest_results.junit.xml       Vitest JUnit reporter output
    /tmp/vitest_bench.json              Vitest bench JSON output
    coverage/coverage-final.json        v8 coverage output (under /testbed)
    /tmp/all_tests.txt                  discovered test names (one per line)
"""

from __future__ import annotations

import hashlib
import json
import textwrap
import traceback
from dataclasses import dataclass
from typing import Any, Optional, Union, cast

from swefficiency.harness.constants import (
    FAIL_TO_PASS,
    KEY_INSTANCE_ID,
    PASS_TO_PASS,
    SWEfficiencyInstance,
)
from swefficiency.harness.constants_ts import (
    TS_BUILD_DIR,
    TS_COVERAGE_OUTPUT_LOCATION,
    TS_PERF_RESULTS_LOCATION,
    TS_PERF_WORKLOAD_SCRIPT_LOCATION,
    TS_TEST_RESULTS_JSON_LOCATION,
    TS_TEST_RESULTS_JUNIT_LOCATION,
)
from swefficiency.harness.dockerfiles_ts import (
    get_dockerfile_annotate_instance_ts,
    get_dockerfile_base_ts,
    get_dockerfile_env_ts,
    get_dockerfile_instance_ts,
)
from swefficiency.harness.utils import get_test_directives

DIFF_MODIFIED_FILE_REGEX = r"--- a/(.*)"

REPO_DIRECTORY = TS_BUILD_DIR
PATCH_PATH = "/tmp/patch.diff"
WORKLOAD_SRC_PATH = TS_PERF_WORKLOAD_SCRIPT_LOCATION
WORKLOAD_RESULTS_PATH = TS_PERF_RESULTS_LOCATION
TEST_RESULTS_JSON_PATH = TS_TEST_RESULTS_JSON_LOCATION
TEST_RESULTS_JUNIT_PATH = TS_TEST_RESULTS_JUNIT_LOCATION
COVERAGE_DIR = f"{REPO_DIRECTORY}/coverage"
COVERAGE_JSON_PATH = f"{REPO_DIRECTORY}/{TS_COVERAGE_OUTPUT_LOCATION}"
PER_TEST_COVERAGE_DIR = "/tmp/raw_coverage_data"
ALL_TESTS_PATH = "/tmp/all_tests.txt"
BENCH_DIR = f"{REPO_DIRECTORY}/__bench__"
BENCH_TARGET_PATH = f"{BENCH_DIR}/workload.bench.ts"

BUILD_TIMEOUT_OVERRIDES_TS: dict[str, Optional[int]] = {
    "microsoft/typescript": 5400,
    "vitest-dev/vitest": 1800,
    "prettier/prettier": 1200,
    "expressjs/express": 900,
    "axios/axios": 900,
    "lodash/lodash": 900,
}


@dataclass
class TestSpecTs:
    """TypeScript analog of ``TestSpec`` -- same field layout, different scripts."""

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
        return "sweb.base.ts:latest"

    @property
    def env_image_key(self) -> str:
        h = hashlib.sha256()
        h.update(str(self.env_script_list).encode("utf-8"))
        return f"sweb.env.ts.{h.hexdigest()[:22]}:latest"

    @property
    def instance_image_key(self) -> str:
        return f"sweb.eval.ts.{self.instance_id}:latest"

    @property
    def annotate_instance_image_key(self) -> str:
        return f"sweb.eval.ts.{self.instance_id}.annotate:latest"

    def get_instance_container_name(self, run_id: Optional[str] = None) -> str:
        if not run_id:
            return f"sweb.eval.ts.{self.instance_id}"
        return f"sweb.eval.ts.{self.instance_id}.{run_id}"

    @property
    def base_dockerfile(self) -> str:
        return get_dockerfile_base_ts(self.platform)

    @property
    def env_dockerfile(self) -> str:
        return get_dockerfile_env_ts(self.platform)

    @property
    def instance_dockerfile(self) -> str:
        return get_dockerfile_instance_ts(self.platform, self.env_image_key)

    @property
    def annotate_instance_dockerfile(self) -> str:
        return get_dockerfile_annotate_instance_ts(self.platform, self.instance_image_key)

    @property
    def platform(self) -> str:
        # Phase 1 ships single-arch linux/amd64 images (the EC2 production
        # target). Build platform, container-create platform, and host must
        # agree; returning the host arch broke eval on arm64 dev machines
        # against the amd64-built instance images.
        return "linux/x86_64"


def get_test_specs_from_dataset_ts(
    dataset: Union[list[SWEfficiencyInstance], list[TestSpecTs]],
) -> list[TestSpecTs]:
    """Idempotent: convert instance dicts into ``TestSpecTs`` objects."""
    if not dataset:
        return []
    if isinstance(dataset[0], TestSpecTs):
        return cast(list[TestSpecTs], dataset)

    out: list[TestSpecTs] = []
    for inst in dataset:
        try:
            out.append(make_test_spec_ts(inst))
        except NotImplementedError:
            continue
        except Exception as e:
            print(
                f"Error creating ts test spec for instance "
                f"{inst[KEY_INSTANCE_ID]} version {inst.get('version')}: {e}"
            )
            traceback.print_exc()
    return out


def make_repo_script_list_ts(
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


def _detect_package_manager_block() -> list[str]:
    """Runtime-equivalent of :func:`detect_package_manager_ts`.

    Inspects ``/testbed`` lockfiles to set ``PM`` for downstream commands.
    Lockfile precedence (matches the spec): pnpm > yarn > bun > npm.
    """
    return [
        f"cd {REPO_DIRECTORY}",
        "if [ -f pnpm-lock.yaml ]; then PM=pnpm",
        "elif [ -f yarn.lock ]; then PM=yarn",
        "elif [ -f bun.lockb ]; then PM=bun",
        "elif [ -f package-lock.json ]; then PM=npm",
        "else PM=npm",
        "fi",
        'echo "Detected package manager: $PM"',
        "export PM",
    ]


def make_env_script_list_ts(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
) -> list[str]:
    """Install system packages + corepack + package-manager install.

    Node toolchain only, no Python build tooling. The pm install is guarded
    by the presence of ``/testbed/package.json`` because the env Dockerfile
    layer runs before the instance layer clones the repo; the per-operation
    scripts redo install after clone.
    """
    cmds: list[str] = ["export DEBIAN_FRONTEND=noninteractive"]

    system_pkgs = specs.get("system_pkgs", []) or []
    if system_pkgs:
        cmds.append("apt-get update")
        cmds.append("apt-get install -y --no-install-recommends " + " ".join(system_pkgs))
        cmds.append("apt-get clean && rm -rf /var/lib/apt/lists/*")

    # Enable corepack so per-repo pnpm/yarn shims resolve without extra
    # global installs. This is the ts-equivalent of the cpp env step's
    # vcpkg / conan bootstrap.
    cmds.append("corepack enable || true")

    # Autodetect the package manager via lockfile precedence and run its
    # install. If /testbed isn't cloned yet (env image precedes instance
    # image), fall through cleanly; per-operation scripts redo install
    # post-clone.
    cmds.extend([
        f'if [ -f "{REPO_DIRECTORY}/package.json" ]; then',
        f'  cd {REPO_DIRECTORY}',
        '  if [ -f pnpm-lock.yaml ]; then PM=pnpm',
        '  elif [ -f yarn.lock ]; then PM=yarn',
        '  elif [ -f bun.lockb ]; then PM=bun',
        '  elif [ -f package-lock.json ]; then PM=npm',
        '  else PM=npm',
        '  fi',
        '  echo "Detected package manager: $PM"',
        '  "$PM" install || npm install || true',
        "else",
        f'  echo "Deferring pm install: {REPO_DIRECTORY} not present at env-image build"',
        "fi",
    ])

    for extra in specs.get("env_patches", []) or []:
        cmds.append(extra)

    cmds.append("node --version || true")
    cmds.append("npx --yes tsc --version || true")
    return cmds


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


def _ts_install_cmd() -> str:
    """`<pm> install` using runtime-detected ``$PM``."""
    return f'cd {REPO_DIRECTORY} && "$PM" install'


def _ts_typecheck_cmd() -> str:
    """`tsc --noEmit` gated on tsconfig presence (only when project has one)."""
    return (
        f'cd {REPO_DIRECTORY} && '
        '{ [ -f tsconfig.json ] && npx --yes tsc --noEmit; } || '
        'echo "skip tsc (no tsconfig)"'
    )


def make_test_command_ts(instance: SWEfficiencyInstance, specs: dict) -> str:
    """Vitest invocation with JSON+JUnit reporters at the locked paths."""
    custom = (
        specs.get("test_cmd")
        or specs.get("test_cmd_override")
        or instance.get("test_cmd_override")
    )
    if custom:
        return custom
    return (
        f"cd {REPO_DIRECTORY} && npx vitest run "
        "--reporter=default --reporter=json --reporter=junit "
        f"--outputFile.json={TEST_RESULTS_JSON_PATH} "
        f"--outputFile.junit={TEST_RESULTS_JUNIT_PATH}"
    )


def make_eval_script_list_ts(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Reset → install → patch → typecheck → test. Patch BEFORE build."""
    cmds: list[str] = [
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
    ]
    cmds.extend(_detect_package_manager_block())
    cmds.append(_ts_install_cmd())
    cmds.extend(_apply_patch_block())
    cmds.append(_ts_install_cmd())
    cmds.append(_ts_typecheck_cmd())
    cmds.append(make_test_command_ts(instance, specs))
    return cmds


def _discover_tests_block() -> list[str]:
    """Best-effort discovery of test ids by reading vitest's JSON output.

    Vitest's ``--reporter=json`` emits ``assertionResults[].fullName`` per
    test. We run once to populate the JSON, then a Node one-liner extracts
    names into ``ALL_TESTS_PATH`` (mirrors ``ctest -N`` enumeration).
    """
    extract = (
        "const fs=require('fs');let d={};"
        f"try{{d=JSON.parse(fs.readFileSync('{TEST_RESULTS_JSON_PATH}','utf8'))}}catch(e){{}}"
        "const out=[];(d.testResults||[]).forEach(f=>(f.assertionResults||[]).forEach("
        "a=>{if(a.fullName)out.push(a.fullName)}));"
        f"fs.writeFileSync('{ALL_TESTS_PATH}',out.join('\\n')+'\\n');"
    )
    return [
        f"mkdir -p $(dirname {ALL_TESTS_PATH})",
        f"cd {REPO_DIRECTORY}",
        "npx vitest run --reporter=json "
        f"--outputFile.json={TEST_RESULTS_JSON_PATH} > /dev/null 2>&1 || true",
        f"node -e \"{extract}\" || true",
        f'echo "Discovered $(wc -l < {ALL_TESTS_PATH}) tests"',
    ]


def make_coverage_script_list_ts(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Single-pass v8 coverage; result lands at ``coverage/coverage-final.json``.

    Vitest's v8 provider emits a single coverage-final.json per run, so we
    don't replicate the cpp pipeline's per-test lcov loop -- per-test
    attribution is not part of the locked Phase 1 contract.
    """
    cmds: list[str] = [
        f"mkdir -p {PER_TEST_COVERAGE_DIR}",
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
    ]
    cmds.extend(_detect_package_manager_block())
    cmds.append(_ts_install_cmd())
    cmds.extend(_apply_patch_block())
    cmds.append(_ts_install_cmd())
    cmds.append(_ts_typecheck_cmd())
    cmds.extend(_discover_tests_block())
    cmds.append(
        f"cd {repo_directory} && npx vitest run --coverage "
        "--coverage.provider=v8 "
        "--coverage.reporter=json "
        f"--coverage.reportsDirectory={COVERAGE_DIR} "
        "|| true"
    )
    cmds.append(
        f'[ -f {COVERAGE_JSON_PATH} ] && '
        f'cp {COVERAGE_JSON_PATH} {PER_TEST_COVERAGE_DIR}/coverage-final.json || '
        'echo "No coverage-final.json produced"'
    )
    return cmds


def make_meaningful_edit_script_list_ts(
    instance: SWEfficiencyInstance,
    specs: dict,
    treesitter_env_name: Optional[str],
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Phase 1 stub. Emits sentinels + a single warning line so the eval
    harness's ``check_ast_result`` accepts the edit as meaningful.
    Real tree-sitter-typescript analysis is Phase 2.
    """
    return [
        "echo 'SWEPERF_AST_START'",
        "echo 'Warning: ts AST check stubbed - all edits accepted as meaningful'",
        "echo 'SWEPERF_AST_END'",
    ]


def _emit_perf_sentinels_block() -> list[str]:
    """Parse ``vitest_bench.json`` and emit the PERF sentinel block.

    The downstream :func:`parse_perf_log_ts` (log_parsers_ts) consumes
    ``PERF_START:`` / ``Mean: <s>`` / ``Std Dev: <s>`` / ``PERF_END:`` in
    SECONDS. Vitest reports milliseconds, so we divide by 1000 at the
    extraction boundary.
    """
    script_path = "/tmp/parse_vitest_bench.js"
    script_body = textwrap.dedent(
        f"""
        const fs=require('fs');
        let data={{}};
        try{{data=JSON.parse(fs.readFileSync('{WORKLOAD_RESULTS_PATH}','utf8'))}}catch(e){{}}
        const samples=[];
        for(const f of (data.files||[])){{
          for(const g of (f.groups||[])){{
            for(const b of (g.benchmarks||[])){{
              // Vitest 4.x: mean/sd FLAT on the benchmark dict; legacy
              // fixtures nest them under "result". Try both.
              const r=b.result||{{}};
              const mean=Number(r.mean!==undefined?r.mean:b.mean);
              const sd=Number(r.sd!==undefined?r.sd:b.sd);
              if(Number.isFinite(mean)&&Number.isFinite(sd)) samples.push([mean,sd]);
            }}
          }}
          for(const b of (f.benchmarks||[])){{
            const r=b.result||{{}};
            const mean=Number(r.mean!==undefined?r.mean:b.mean);
            const sd=Number(r.sd!==undefined?r.sd:b.sd);
            if(Number.isFinite(mean)&&Number.isFinite(sd)) samples.push([mean,sd]);
          }}
        }}
        let mean=0, sd=0;
        if(samples.length){{
          mean=samples.reduce((a,b)=>a+b[0],0)/samples.length;
          sd=samples.reduce((a,b)=>a+b[1],0)/samples.length;
        }}
        const meanS=(mean*1e-3).toFixed(9);
        const sdS=(sd*1e-3).toFixed(9);
        console.log('PERF_START:');
        console.log('Mean: '+meanS);
        console.log('Std Dev: '+sdS);
        console.log('PERF_END:');
        """
    ).strip()
    heredoc = f"cat > {script_path} <<'PARSE_EOF'\n{script_body}\nPARSE_EOF"
    return [
        heredoc,
        f"node {script_path} || "
        "(echo 'PERF_START:'; echo 'Mean: 0'; echo 'Std Dev: 0'; echo 'PERF_END:')",
    ]


def _stage_workload_block() -> list[str]:
    return [
        f'[ -f {WORKLOAD_SRC_PATH} ] || (echo "Missing workload at {WORKLOAD_SRC_PATH}"; exit 1)',
        f"mkdir -p {BENCH_DIR}",
        f"cp {WORKLOAD_SRC_PATH} {BENCH_TARGET_PATH}",
    ]


def make_performance_script_list_ts(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Stage workload, run ``vitest bench``, emit PERF_START/Mean/Std Dev/PERF_END."""
    cmds: list[str] = [
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
    ]
    cmds.extend(_detect_package_manager_block())
    cmds.append(_ts_install_cmd())
    cmds.extend(_apply_patch_block())
    cmds.append(_ts_install_cmd())
    cmds.append(_ts_typecheck_cmd())
    cmds.extend(_stage_workload_block())
    cmds.append(
        f"cd {repo_directory} && taskset -c 0 npx vitest bench --run --no-coverage "
        f"--outputJson={WORKLOAD_RESULTS_PATH} "
        "__bench__/workload.bench.ts || true"
    )
    cmds.extend(_emit_perf_sentinels_block())
    return cmds


def make_performance_profiling_script_list_ts(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Node ``--cpu-prof`` profile of the workload run (best-effort).

    Replaces the cpp pipeline's ``perf record`` (Linux perf isn't installed
    in node:20-bookworm-slim and adds significant image weight). The
    ``.cpuprofile`` artifacts can be loaded into Chrome DevTools or
    flamegraph tools downstream.
    """
    cmds: list[str] = [
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
    ]
    cmds.extend(_detect_package_manager_block())
    cmds.append(_ts_install_cmd())
    cmds.extend(_apply_patch_block())
    cmds.append(_ts_install_cmd())
    cmds.append(_ts_typecheck_cmd())
    cmds.extend(_stage_workload_block())
    cmds.append("mkdir -p /tmp/node_cpuprof")
    cmds.append(
        f"cd {repo_directory} && "
        "NODE_OPTIONS='--cpu-prof --cpu-prof-dir=/tmp/node_cpuprof' "
        "taskset -c 0 npx vitest bench --run --no-coverage "
        f"--outputJson={WORKLOAD_RESULTS_PATH} __bench__/workload.bench.ts || true"
    )
    cmds.append("ls -la /tmp/node_cpuprof || true")
    cmds.append("head -200 /tmp/node_cpuprof/*.cpuprofile 2>/dev/null || true")
    return cmds


def get_correctness_script_list_ts(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Run the eval test command and stash JSON/JUnit outputs."""
    test_directives = get_test_directives(instance)
    _ = test_directives
    cmds: list[str] = [
        f"cd {repo_directory}",
        f"git reset --hard {base_commit}",
    ]
    cmds.extend(_detect_package_manager_block())
    cmds.append(_ts_install_cmd())
    cmds.extend(_apply_patch_block())
    cmds.append(_ts_install_cmd())
    cmds.append(_ts_typecheck_cmd())
    cmds.append("mkdir -p /tmp/raw_correctness_output")
    cmds.append(
        f"{make_test_command_ts(instance, specs)} "
        "> /tmp/raw_correctness_output/all.txt 2>&1 || true"
    )
    cmds.append(
        f'[ -f {TEST_RESULTS_JSON_PATH} ] && '
        f'cp {TEST_RESULTS_JSON_PATH} /tmp/raw_correctness_output/vitest_results.json || true'
    )
    cmds.append(
        f'[ -f {TEST_RESULTS_JUNIT_PATH} ] && '
        f'cp {TEST_RESULTS_JUNIT_PATH} /tmp/raw_correctness_output/vitest_results.junit.xml || true'
    )
    return cmds


def get_introspection_guard_cmds_ts(
    instance: SWEfficiencyInstance,
    specs: dict,
    env_name: str,
    repo_directory: str,
    base_commit: str,
    test_patch: str,
) -> list[str]:
    """Phase 1 no-op guard. Future: detect AST-level patch tampering."""
    return ["echo 'ts introspection guard: no-op'"]


def make_test_spec_ts(
    instance: SWEfficiencyInstance,
    observed_versions: Optional[set] = None,
) -> TestSpecTs:
    if isinstance(instance, TestSpecTs):
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
    # Guarantee test_patch on the instance dict: the shared get_test_directives
    # (called by get_correctness_script_list_ts) bracket-accesses it.
    instance = {**instance, "test_patch": instance.get("test_patch", "")}
    test_patch = instance["test_patch"]

    # No allow-list: dynamic_specs_ts.get_or_create_specs_ts synthesizes defaults
    # for repos not in MAP_REPO_TO_BUILD_SYSTEM_TS. Unknown repos get the standard
    # Node + Vitest path; per-repo overrides (system_pkgs, test_cmd) come from
    # detect_repo_specs_ts.py at enrichment time.
    build_timeout = BUILD_TIMEOUT_OVERRIDES_TS.get(repo)

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

    from swefficiency.harness.dynamic_specs_ts import get_or_create_specs_ts

    specs = get_or_create_specs_ts(instance, repo, version)

    if observed_versions is not None:
        if version in observed_versions:
            raise RuntimeError(f"Version already observed: {version}")
        observed_versions.add(version)

    env_name = "testbed"
    repo_directory = REPO_DIRECTORY

    repo_script_list = make_repo_script_list_ts(specs, repo, repo_directory, base_commit)
    env_script_list = make_env_script_list_ts(instance, specs, env_name)
    eval_script_list = make_eval_script_list_ts(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    coverage_script_list = make_coverage_script_list_ts(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    meaningful_edit_script_list = make_meaningful_edit_script_list_ts(
        instance, specs, None, repo_directory, base_commit, test_patch
    )
    performance_script_list = make_performance_script_list_ts(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    performance_profiling_script_list = make_performance_profiling_script_list_ts(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    correctness_script_list = get_correctness_script_list_ts(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )
    introspection_guard_script_list = get_introspection_guard_cmds_ts(
        instance, specs, env_name, repo_directory, base_commit, test_patch
    )

    workload_text = instance.get("workload", "") or ""
    if not isinstance(workload_text, str) or workload_text.strip() in ("", "nan"):
        workload_text = None

    return TestSpecTs(
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
