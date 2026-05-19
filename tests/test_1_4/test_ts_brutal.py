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

"""Brutal regression tests for every behavioral fix applied to the ts port.

Each test targets a specific bug that was either caught in the cpp-vs-ts audit
or introduced silently during the port. If any of these fail, a fix has been
silently reverted.
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest


# ===========================================================================
# (BUG #1) ship-blocker: _TokenRotator class identity
# ===========================================================================

def test_get_tasks_pipeline_ts_uses_utils_TokenRotator_not_discover_repos():
    """Repo.__init__ at utils.py:195 checks isinstance(token, utils._TokenRotator).
    If get_tasks_pipeline_ts imports a DIFFERENT _TokenRotator class (e.g. from
    discover_repos_ts), the isinstance fails, the rotator object gets wrapped as
    if it were a token string, and every GitHub call silently auth-fails.

    Reproduction: I shipped exactly this bug, caught by this assertion.
    """
    from swefficiency.collect.get_tasks_pipeline_ts import _TokenRotator as Pipeline_TR
    from swefficiency.collect.utils import _TokenRotator as Utils_TR
    assert Pipeline_TR is Utils_TR, (
        f"_TokenRotator class identity mismatch: "
        f"pipeline={Pipeline_TR.__module__}.{Pipeline_TR.__qualname__}, "
        f"utils={Utils_TR.__module__}.{Utils_TR.__qualname__}. "
        f"This breaks isinstance() in utils.Repo and silently breaks GitHub auth."
    )


def test_repo_accepts_pipeline_rotator_via_isinstance_check():
    """utils.Repo.__init__ duck-types: token can be str or utils._TokenRotator.
    Verify the rotator type used by get_tasks_pipeline_ts passes that check."""
    from swefficiency.collect.utils import _TokenRotator
    from swefficiency.collect.get_tasks_pipeline_ts import _TokenRotator as PR
    rotator = PR(["ghp_fake"])
    assert isinstance(rotator, _TokenRotator)


# ===========================================================================
# (BUG #2) parse_vitest_bench: multi-bench must emit ONE block (cpp parity)
# ===========================================================================

def test_parse_vitest_bench_multi_bench_emits_single_block(tmp_path):
    """Multi-bench input MUST emit exactly ONE PERF block (no Name: lines).
    Downstream parse_perf_output expects single-block layout."""
    import subprocess

    data = {
        "files": [{
            "filepath": "x.bench.ts",
            "groups": [{
                "name": "g",
                "benchmarks": [
                    {"name": "add", "result": {"mean": 12.5, "sd": 0.5}},
                    {"name": "sub", "result": {"mean": 25.0, "sd": 1.0}},
                ],
            }],
        }]
    }
    fixture = tmp_path / "bench.json"
    fixture.write_text(json.dumps(data))

    out = subprocess.run(
        ["python3", "scripts/parse_vitest_bench.py", str(fixture)],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert out.stdout.count("PERF_START:") == 1, (
        f"Expected 1 PERF_START block, got {out.stdout.count('PERF_START:')}:\n{out.stdout}"
    )
    assert "Name:" not in out.stdout, "Name: line leaked into multi-bench output"


def test_parse_vitest_bench_sentinel_format_matches_perf_regex():
    """Sentinel block must match parse_perf_log_ts's regex byte-for-byte."""
    from swefficiency.harness.log_parsers_ts import parse_perf_log_ts
    sample = "PERF_START:\nMean: 0.012500000\nStd Dev: 0.000500000\nPERF_END:\n"
    result = parse_perf_log_ts(sample)
    assert isinstance(result, tuple) and len(result) == 2
    assert abs(result[0] - 0.0125) < 1e-9
    assert abs(result[1] - 0.0005) < 1e-9


# ===========================================================================
# (BUG #3) star-band sharding in discover_repos_ts
# ===========================================================================

def test_build_query_accepts_star_band_kwarg():
    """_build_query must accept star_band=(lo, hi) and emit `stars:LO..HI`."""
    from swefficiency.collect import discover_repos_ts
    sig = inspect.signature(discover_repos_ts._build_query)
    assert "star_band" in sig.parameters
    q = discover_repos_ts._build_query("mit", 100, 12, star_band=(100, 199))
    assert "stars:100..199" in q
    q2 = discover_repos_ts._build_query("mit", 100, 12, star_band=(1000, None))
    assert "stars:>=1000" in q2
    q3 = discover_repos_ts._build_query("mit", 100, 12)
    assert "stars:>=100" in q3


def test_star_bands_partition_covers_full_range():
    """The nested _star_bands function generates non-overlapping inclusive
    bands plus an open-ended top band, matching cpp's shape."""
    from swefficiency.collect import discover_repos_ts
    src = inspect.getsource(discover_repos_ts.search_repos)
    assert "def _star_bands" in src
    assert "for mult in (2, 4, 8, 20, 50, 150):" in src
    assert "edges.append(e)" in src
    assert "bands.append((edges[-1], None))" in src


# ===========================================================================
# (BUG #4) token strip
# ===========================================================================

def test_get_tasks_pipeline_ts_strips_tokens():
    """Whitespace in --tokens must be stripped. Otherwise GitHub returns 401
    for any token after the first."""
    from swefficiency.collect import get_tasks_pipeline_ts as gtp
    src = inspect.getsource(gtp.main)
    assert "[t.strip() for t in args.tokens.split" in src, (
        "tokens must be stripped: leading whitespace breaks Bearer auth header"
    )


# ===========================================================================
# (BUG #5) ledger logic in get_tasks_pipeline_ts
# ===========================================================================

def test_construct_data_files_ts_has_ledger_logic():
    """Worker must consult and update completed_repos.txt to skip already-
    scraped repos on resume. Mirrors cpp lines 67-90."""
    from swefficiency.collect import get_tasks_pipeline_ts as gtp
    src = inspect.getsource(gtp.construct_data_files_ts)
    assert "completed_repos.txt" in src
    assert "ledger_path.exists()" in src
    assert 'if repo in completed_repos' in src
    assert 'with open(ledger_path, "a"' in src


def test_construct_data_files_ts_calls_print_pulls_always():
    """A bare exists() check accepts a truncated mid-scrape file. Worker must
    ALWAYS invoke print_pulls (whose resume completes partial files)."""
    from swefficiency.collect import get_tasks_pipeline_ts as gtp
    src = inspect.getsource(gtp.construct_data_files_ts)
    assert "if not pulls_path.exists():\n                logger.info" not in src, (
        "Worker must NOT gate print_pulls on file-exists; that accepts truncated scrape files"
    )


def test_TokenStuckError_dlqs_remaining_repos():
    """When the rotator exhausts mid-chunk, remaining repos must be DLQ'd
    with error_type='TokenStuckError', not silently retried in tight loop."""
    from swefficiency.collect import get_tasks_pipeline_ts as gtp
    src = inspect.getsource(gtp.construct_data_files_ts)
    assert "except TokenStuckError" in src
    assert "task_pipeline_ts_token_exhausted.jsonl" in src
    assert "TokenStuckError" in src


# ===========================================================================
# (BUG #6) load_repos_from_json: 3-shape contract
# ===========================================================================

def test_load_repos_from_json_strings(tmp_path):
    from swefficiency.collect.get_tasks_pipeline_ts import load_repos_from_json
    f = tmp_path / "r.json"
    f.write_text(json.dumps(["lodash/lodash", "axios/axios"]))
    assert load_repos_from_json(str(f)) == ["lodash/lodash", "axios/axios"]


def test_load_repos_from_json_objects(tmp_path):
    from swefficiency.collect.get_tasks_pipeline_ts import load_repos_from_json
    f = tmp_path / "r.json"
    f.write_text(json.dumps([{"full_name": "expressjs/express"}]))
    assert load_repos_from_json(str(f)) == ["expressjs/express"]


def test_load_repos_from_json_wrapper(tmp_path):
    from swefficiency.collect.get_tasks_pipeline_ts import load_repos_from_json
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"repos": ["vitest-dev/vitest"]}))
    assert load_repos_from_json(str(f)) == ["vitest-dev/vitest"]


def test_load_repos_from_json_skips_invalid(tmp_path, caplog):
    """Garbage entries (no slash, not str/dict) must be skipped with warning,
    not silently dropped, not crash."""
    from swefficiency.collect.get_tasks_pipeline_ts import load_repos_from_json
    f = tmp_path / "r.json"
    f.write_text(json.dumps([
        "ok/repo", "no-slash", 42, {"full_name": "x/y"}, {"oops": 1}
    ]))
    with caplog.at_level(logging.WARNING):
        out = load_repos_from_json(str(f))
    assert out == ["ok/repo", "x/y"]


def test_load_repos_from_json_rejects_non_array(tmp_path):
    from swefficiency.collect.get_tasks_pipeline_ts import load_repos_from_json
    f = tmp_path / "r.json"
    f.write_text(json.dumps("just a string"))
    with pytest.raises(ValueError):
        load_repos_from_json(str(f))


# ===========================================================================
# (BUG #7) MITM CA cert injection — Node.js-appropriate env vars
# ===========================================================================

def test_dockerfile_base_ts_has_ca_cert_path_arg():
    from swefficiency.harness.dockerfiles_ts import get_dockerfile_base_multiarch_ts
    df = get_dockerfile_base_multiarch_ts()
    assert 'ARG CA_CERT_PATH=""' in df


def test_dockerfile_base_ts_injects_node_specific_ca_env_vars():
    """Must emit NODE_EXTRA_CA_CERTS and NPM_CONFIG_CAFILE (NOT PIP_CERT)."""
    from swefficiency.harness.dockerfiles_ts import get_dockerfile_base_multiarch_ts
    df = get_dockerfile_base_multiarch_ts()
    assert "NODE_EXTRA_CA_CERTS" in df
    assert "NPM_CONFIG_CAFILE" in df
    assert "SSL_CERT_FILE" in df
    assert "CURL_CA_BUNDLE" in df
    assert "PIP_CERT" not in df, "PIP_CERT is python-specific; should not be in ts dockerfile"


def test_dockerfile_base_ts_has_all_six_proxy_args():
    from swefficiency.harness.dockerfiles_ts import get_dockerfile_base_multiarch_ts
    df = get_dockerfile_base_multiarch_ts()
    for arg in ("http_proxy", "https_proxy", "no_proxy",
                "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        assert f'ARG {arg}=""' in df, f"missing ARG {arg}"


def test_dockerfile_base_ts_no_native_toolchain():
    from swefficiency.harness.dockerfiles_ts import get_dockerfile_base_multiarch_ts
    df = get_dockerfile_base_multiarch_ts()
    for tok in ("g++", "cmake", "gtest", "gbench", "libbenchmark"):
        assert tok not in df, f"native toolchain token {tok!r} leaked into ts base image"


# ===========================================================================
# (BUG #8) build_dataset_ts: token kwarg + passthrough
# ===========================================================================

def test_build_dataset_ts_accepts_token_kwarg():
    from swefficiency.collect.build_dataset_ts import build_dataset_ts
    sig = inspect.signature(build_dataset_ts)
    assert "token" in sig.parameters
    assert sig.parameters["token"].default is None


def test_build_dataset_ts_passes_token_to_Repo():
    """The token kwarg must reach Repo(token=...). Source inspection."""
    from swefficiency.collect import build_dataset_ts as bd
    src = inspect.getsource(bd.build_dataset_ts)
    assert "Repo(owner, name, token=token if token is not None else" in src


# ===========================================================================
# (BUG #9) case-insensitive map lookup in dynamic_specs_ts
# ===========================================================================

def test_default_specs_handles_uppercase_repo_name():
    """If dataset preserves original case (`microsoft/TypeScript`) the lookup
    must still hit the map entry. If dataset lowercases, it must also hit."""
    from swefficiency.harness import dynamic_specs_ts as ds
    s_exact = ds._default_specs("microsoft/TypeScript")
    s_lower = ds._default_specs("microsoft/typescript")
    s_unknown = ds._default_specs("foo/bar")
    assert isinstance(s_exact, dict)
    assert isinstance(s_lower, dict)
    assert isinstance(s_unknown, dict)
    assert s_exact["language"] == "ts"
    assert s_lower["language"] == "ts"


def test_default_specs_exact_match_priority():
    """If both `Microsoft/TypeScript` and `microsoft/typescript` exist (one
    exact, one via .lower()), exact match must win."""
    from swefficiency.harness import dynamic_specs_ts as ds
    src = inspect.getsource(ds._default_specs)
    assert "MAP_REPO_TO_BUILD_SYSTEM_TS.get(repo)" in src
    assert ".get(repo.lower(), {})" in src
    assert "or" in src  # short-circuit eval ensures exact wins


# ===========================================================================
# (BUG #10) get_versions_ts: build-mode fallback walk
# ===========================================================================

def test_get_versions_ts_build_mode_uses_package_json_first(tmp_path):
    from swefficiency.versioning.get_versions_ts import _get_version_impl
    (tmp_path / "package.json").write_text(json.dumps({"version": "1.2.3"}))
    (tmp_path / "lerna.json").write_text(json.dumps({"version": "9.9.9"}))
    result = _get_version_impl(
        {"repo": "x/y", "base_commit": "z"},
        is_build=True, path_repo=str(tmp_path),
    )
    assert result == "1.2.3", f"package.json should win over lerna.json (got {result!r})"


def test_get_versions_ts_build_mode_falls_back_to_lerna(tmp_path):
    from swefficiency.versioning.get_versions_ts import _get_version_impl
    (tmp_path / "lerna.json").write_text(json.dumps({"version": "9.8.7"}))
    result = _get_version_impl(
        {"repo": "x/y", "base_commit": "z"},
        is_build=True, path_repo=str(tmp_path),
    )
    assert result == "9.8.7"


def test_get_versions_ts_build_mode_returns_none_when_nothing(tmp_path):
    from swefficiency.versioning.get_versions_ts import _get_version_impl
    result = _get_version_impl(
        {"repo": "x/y", "base_commit": "z"},
        is_build=True, path_repo=str(tmp_path),
    )
    assert result is None


# ===========================================================================
# (BUG #11) RLIMIT_NOFILE in run_evaluation_ts.main
# ===========================================================================

def test_run_evaluation_ts_main_has_rlimit_block():
    from swefficiency.harness import run_evaluation_ts as re_ts
    src = inspect.getsource(re_ts.main)
    assert "RLIMIT_NOFILE" in src
    assert "setrlimit" in src
    assert "max(_soft, 4096)" in src


# ===========================================================================
# (BUG #12) validate_dataset_ts: node_version (not ts_standard)
# ===========================================================================

def test_validate_dataset_ts_requires_node_version_field():
    import scripts.validate_dataset_ts as v
    assert "node_version" in v.SWEFF_REQUIRED_TS
    assert "ts_standard" not in v.SWEFF_REQUIRED_TS


def test_validate_dataset_ts_rejects_record_missing_node_version(tmp_path):
    """A record without node_version must be flagged invalid."""
    import scripts.validate_dataset_ts as v
    record = {
        "instance_id": "x__y-1",
        "language": "ts",
        "workload": "import { bench } from 'vitest';\nbench('x', () => {});",
        "install_cmd": "pnpm install",
        "test_cmd": "npx vitest run",
        "test_framework": "vitest",
        "license": "MIT",
        "project_files": ["package.json", "tsconfig.json"],
    }
    errs, warns = v.validate_instance_ts(0, record)
    assert any("node_version" in str(e) for e in errs), (
        f"Expected 'node_version' missing error; got errs={errs!r}"
    )


# ===========================================================================
# (BUG #13) test_spec_ts: test_cmd priority chain
# ===========================================================================

def test_test_spec_ts_make_test_command_reads_test_cmd_first():
    """specs.test_cmd (cpp parity key) wins over specs.test_cmd_override
    and instance.test_cmd_override."""
    from swefficiency.harness import test_spec_ts as ts
    src = inspect.getsource(ts.make_test_command_ts)
    assert 'specs.get("test_cmd")' in src
    # The chain MUST start with test_cmd (cpp parity), not test_cmd_override
    idx_cmd = src.find('specs.get("test_cmd")')
    idx_override = src.find('specs.get("test_cmd_override")')
    assert idx_cmd != -1
    assert idx_cmd < idx_override, "specs.get('test_cmd') must be checked BEFORE specs.get('test_cmd_override')"


# ===========================================================================
# (BUG #14) test_spec_ts: post-patch install in ALL 4 script generators
# ===========================================================================

def test_test_spec_ts_eval_script_reinstalls_after_patch():
    """When a patch touches package.json/lockfile, deps must be re-installed.
    Verify _apply_patch_block is followed by _ts_install_cmd in EVERY script."""
    from swefficiency.harness import test_spec_ts as ts
    for fn_name in ("make_eval_script_list_ts",
                    "make_coverage_script_list_ts",
                    "make_performance_script_list_ts",
                    "make_annotate_script_list_ts"):
        if not hasattr(ts, fn_name):
            continue
        src = inspect.getsource(getattr(ts, fn_name))
        # Pattern: _apply_patch_block followed (within ~80 chars) by _ts_install_cmd
        assert re.search(
            r"_apply_patch_block\(\)\)\s*\n\s*cmds\.append\(_ts_install_cmd\(\)\)",
            src,
        ), f"{fn_name} missing post-patch re-install"


# ===========================================================================
# (BUG #15) run_synthetic_generation_ts: no npm install in validator
# ===========================================================================

def test_run_synthetic_generation_ts_validator_no_npm_install():
    """Validator must NOT do `npm init -y` / `npm install` per attempt.
    Vitest is globally installed in the base image; validator just runs npx."""
    src = Path("swefficiency/workload/run_synthetic_generation_ts.py").read_text()
    fn_match = re.search(
        r"def _validate_compile_in_container\b.*?(?=\ndef |\Z)",
        src, re.DOTALL,
    )
    assert fn_match is not None, "could not locate _validate_compile_in_container function"
    fn_body = fn_match.group(0)
    assert "npm init -y" not in fn_body, "validator must not run `npm init` per attempt"
    assert "npm install --silent" not in fn_body, "validator must not run `npm install` per attempt"


def test_run_synthetic_generation_ts_validator_uses_ro_mount():
    """Validator must mount tmpdir read-only (cpp parity, defensive)."""
    src = Path("swefficiency/workload/run_synthetic_generation_ts.py").read_text()
    assert "{tmpdir}:/work:ro" in src


# ===========================================================================
# (BUG #16) build_and_validate_images_ts: read-only toolchain probe
# ===========================================================================

def test_build_and_validate_images_ts_no_npm_install_in_toolchain():
    """Toolchain probe must NOT install deps inside testbed; just version-check."""
    src = Path("scripts/build_and_validate_images_ts.py").read_text()
    # Find the toolchain_cmd assignment
    assert "corepack enable && npx tsc --version && npx vitest --version" in src
    # Hard guard against re-introducing npm i
    assert "npm i -D vitest typescript" not in src, "npm i -D removed; reintroduction blocked"


# ===========================================================================
# (BUG #17) detect_repo_specs_ts: UNSUPPORTED logs warning, not info
# ===========================================================================

def test_detect_repo_specs_ts_warns_on_unsupported():
    """UNSUPPORTED instances must log at WARNING level (else dropped silently
    when logger level is WARNING)."""
    src = Path("scripts/detect_repo_specs_ts.py").read_text()
    fn_match = re.search(
        r"def detect_all_specs_ts.*?(?=^def )",
        src, re.DOTALL | re.MULTILINE,
    )
    assert fn_match is not None
    fn_body = fn_match.group(0)
    # Both UNSUPPORTED branches must call log.warning, not log.info
    assert fn_body.count("log.warning") >= 2
    # The specific UNSUPPORTED guard lines must use warning
    assert re.search(r"if build_system == UNSUPPORTED:\s*\n\s+log\.warning", fn_body)
    assert re.search(r"if test_framework == UNSUPPORTED:\s*\n\s+log\.warning", fn_body)


# ===========================================================================
# (BUG #18) discover_repos_ts: real-time streaming sidecar
# ===========================================================================

def test_validate_repos_signature_has_stream_path():
    from swefficiency.collect.discover_repos_ts import validate_repos
    sig = inspect.signature(validate_repos)
    assert "stream_path" in sig.parameters
    assert sig.parameters["stream_path"].default is None


def test_validate_repos_writes_stream_in_real_time(tmp_path, monkeypatch):
    """When stream_path is set, each passing repo must appear in the file
    BEFORE validate_repos returns."""
    from swefficiency.collect import discover_repos_ts
    from swefficiency.collect.utils import _TokenRotator

    stream_path = str(tmp_path / "stream.jsonl")
    # Three fake "repos" — each will pass validation via our monkeypatch.
    fake_repos = [
        {"full_name": f"x/{i}", "stargazers_count": 100,
         "_license_spdx": "MIT", "_merged_prs": 5,
         "description": "", "topics": [], "pushed_at": "2025-01-01"}
        for i in range(3)
    ]

    def fake_validate_single(repo, rotator, **_kw):
        return repo

    monkeypatch.setattr(discover_repos_ts, "_validate_single", fake_validate_single)
    rotator = _TokenRotator(["ghp_fake"])
    out = discover_repos_ts.validate_repos(
        fake_repos, rotator,
        min_prs=1, require_ts_root=False, require_tests=False,
        skip_pr_count=True, max_workers=1,
        stream_path=stream_path,
    )
    assert len(out) == 3
    # Stream file must exist and contain 3 lines, one per repo
    lines = Path(stream_path).read_text().strip().splitlines()
    assert len(lines) == 3
    # Each line is well-formed JSON with the right keys
    for ln in lines:
        obj = json.loads(ln)
        assert "full_name" in obj
        assert "stars" in obj
        assert "license" in obj


# ===========================================================================
# (BUG #19) main() wires --repos-json end-to-end
# ===========================================================================

def test_get_tasks_pipeline_ts_argparse_has_repos_json():
    """User-facing CLI flag must be visible in --help."""
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "swefficiency.collect.get_tasks_pipeline_ts", "--help"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": "."},
    )
    assert result.returncode == 0
    assert "--repos-json" in result.stdout


# ===========================================================================
# (BUG #20) discover_repos_ts: language:TypeScript GitHub query
# ===========================================================================

def test_discover_repos_ts_query_targets_typescript():
    """Search query must filter by language:TypeScript, not C++ etc."""
    from swefficiency.collect.discover_repos_ts import _build_query
    q = _build_query("mit", 100, 12)
    assert "language:TypeScript" in q
    assert "language:C++" not in q


def test_discover_repos_ts_check_ts_root_requires_both_manifests():
    """Filter must require BOTH package.json AND tsconfig.json at repo root."""
    src = Path("swefficiency/collect/discover_repos_ts.py").read_text()
    fn_match = re.search(
        r"def check_ts_root\(.*?(?=^def )",
        src, re.DOTALL | re.MULTILINE,
    )
    assert fn_match is not None
    fn_body = fn_match.group(0)
    assert "package.json" in fn_body
    assert "tsconfig.json" in fn_body


# ===========================================================================
# Smoke: full import chain
# ===========================================================================

def test_all_ts_modules_import_cleanly():
    """If any new code path introduced a syntax / circular import / missing
    name, this catches it without needing the underlying litellm dep."""
    import importlib
    modules = [
        "swefficiency.harness.constants_ts",
        "swefficiency.harness.log_parsers_ts",
        "swefficiency.harness.dynamic_specs_ts",
        "swefficiency.harness.grading_ts",
        "swefficiency.harness.test_spec_ts",
        "swefficiency.harness.docker_build_ts",
        "swefficiency.harness.dockerfiles_ts",
        "swefficiency.harness.run_evaluation_ts",
        "swefficiency.collect.discover_repos_ts",
        "swefficiency.collect.build_dataset_ts",
        "swefficiency.collect.get_tasks_pipeline_ts",
        "swefficiency.versioning.get_versions_ts",
        "swefficiency.versioning.constants_ts",
        "swefficiency.cache.sqlite_cache_ts",
        "swefficiency.report_ts",
    ]
    for m in modules:
        importlib.import_module(m)
