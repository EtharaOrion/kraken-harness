#!/usr/bin/env python3
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

"""Full preflight for a 10k-instance autonomous run.

``validate_dataset.py`` covers the dataset shape. This script adds the
infrastructure checks an autonomous run will silently fail on without:

* GitHub tokens                — collect/* and patch fetching.
* AWS credentials              — Bedrock LLM calls, S3 logs.
* ECR registry reachability    — instance image pulls.
* Docker daemon                — image builds and container runs.
* Free disk space              — image cache + per-instance work dirs.
* File-descriptor headroom     — concurrent docker connections.
* Cost-tracker state           — prior partial spend across resumes.

Exits 0 if every check passes (or is downgraded to a WARN). Non-zero on the
first FAIL. Pass ``--strict`` to escalate WARN to FAIL.

Usage:
    python scripts/validate_run.py [--dataset PATH] [--strict] \\
        [--min-disk-gb 50] [--min-fds 4096]
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass
class CheckResult:
    name: str
    status: str  # "PASS" | "WARN" | "FAIL" | "SKIP"
    detail: str = ""
    suggestions: List[str] = field(default_factory=list)


def _ok(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name, "PASS", detail)


def _warn(name: str, detail: str, *suggestions: str) -> CheckResult:
    return CheckResult(name, "WARN", detail, list(suggestions))


def _fail(name: str, detail: str, *suggestions: str) -> CheckResult:
    return CheckResult(name, "FAIL", detail, list(suggestions))


def _skip(name: str, reason: str) -> CheckResult:
    return CheckResult(name, "SKIP", reason)


# ---------------------------------------------------------------------------
# Individual checks. Each returns a CheckResult.
# ---------------------------------------------------------------------------

def check_github_tokens() -> CheckResult:
    raw = os.environ.get("GITHUB_TOKENS") or os.environ.get("GITHUB_TOKEN", "")
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    if not tokens:
        return _fail(
            "github_tokens",
            "No GITHUB_TOKENS or GITHUB_TOKEN env var set.",
            "Export GITHUB_TOKENS=<comma-separated PATs> before launching.",
        )
    bad = [t for t in tokens if not (t.startswith(("ghp_", "github_pat_", "gho_")))]
    if bad:
        return _warn(
            "github_tokens",
            f"{len(bad)}/{len(tokens)} tokens do not match a known PAT prefix.",
            "Confirm tokens are unrevoked GitHub PATs with public_repo scope.",
        )
    return _ok("github_tokens", f"{len(tokens)} token(s) configured.")


def check_aws_credentials() -> CheckResult:
    have_keys = bool(os.environ.get("AWS_ACCESS_KEY_ID")) and bool(
        os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    have_profile = bool(os.environ.get("AWS_PROFILE"))
    have_role = bool(os.environ.get("AWS_ROLE_ARN"))
    have_creds_file = (Path.home() / ".aws" / "credentials").exists()
    if not (have_keys or have_profile or have_role or have_creds_file):
        return _fail(
            "aws_credentials",
            "No AWS credentials source detected.",
            "Set AWS_PROFILE or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, or run aws configure.",
        )
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    detail = "credentials present"
    if region:
        detail += f"; region={region}"
    else:
        return _warn(
            "aws_credentials",
            "AWS credentials present but no AWS_REGION/AWS_DEFAULT_REGION set.",
            "Export AWS_REGION=us-east-1 (or your chosen region).",
        )
    return _ok("aws_credentials", detail)


def check_ecr_registry() -> CheckResult:
    registry = os.environ.get("ECR_REGISTRY")
    if not registry:
        # Best-effort derive from account + region.
        account = os.environ.get("AWS_ACCOUNT_ID")
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        if account and region:
            registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
        else:
            return _warn(
                "ecr_registry",
                "ECR_REGISTRY not set and cannot be derived.",
                "Set ECR_REGISTRY=<acct>.dkr.ecr.<region>.amazonaws.com.",
            )
    host = registry.split("/")[0]
    try:
        socket.setdefaulttimeout(5)
        socket.gethostbyname(host)
    except socket.gaierror as e:
        return _fail(
            "ecr_registry",
            f"DNS resolution for {host} failed: {e}",
            "Check VPC DNS / outbound network / proxy config.",
        )
    finally:
        socket.setdefaulttimeout(None)
    return _ok("ecr_registry", f"resolved {host}")


def check_docker_daemon() -> CheckResult:
    if shutil.which("docker") is None:
        return _fail(
            "docker_daemon",
            "docker CLI not found on PATH.",
            "Install Docker Engine or Docker Desktop and ensure docker is on PATH.",
        )
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return _fail(
            "docker_daemon",
            f"docker version probe failed: {e}",
            "Start the Docker daemon (systemctl start docker / open Docker Desktop).",
        )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        return _fail(
            "docker_daemon",
            f"docker version returned {proc.returncode}: {stderr}",
            "Start the Docker daemon and confirm your user is in the docker group.",
        )
    return _ok("docker_daemon", f"server version {proc.stdout.strip()}")


def check_disk_space(min_gb: float) -> CheckResult:
    # Disk under DOCKER_DATA_ROOT if set, else /var/lib/docker if exists, else /.
    candidates = []
    if "DOCKER_DATA_ROOT" in os.environ:
        candidates.append(Path(os.environ["DOCKER_DATA_ROOT"]))
    candidates.append(Path("/var/lib/docker"))
    candidates.append(Path("/"))
    for path in candidates:
        if path.exists():
            target = path
            break
    else:
        target = Path("/")
    usage = shutil.disk_usage(str(target))
    free_gb = usage.free / (1024 ** 3)
    detail = f"{free_gb:.1f} GB free on {target}"
    if free_gb < min_gb:
        return _fail(
            "disk_space",
            f"{detail}; needed >= {min_gb:.0f} GB.",
            f"Prune images: docker system prune -af",
            f"Move {target} to a larger volume or attach EBS.",
        )
    if free_gb < min_gb * 1.5:
        return _warn(
            "disk_space",
            f"{detail}; below 1.5x safety margin ({min_gb*1.5:.0f} GB).",
        )
    return _ok("disk_space", detail)


def check_fd_limit(min_fds: int) -> CheckResult:
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (ValueError, OSError) as e:
        return _warn("fd_limit", f"could not read RLIMIT_NOFILE: {e}")
    if soft < min_fds:
        return _fail(
            "fd_limit",
            f"soft RLIMIT_NOFILE={soft}, need >= {min_fds} (hard={hard}).",
            f"ulimit -n {min_fds}  (or raise hard limit in /etc/security/limits.conf).",
        )
    return _ok("fd_limit", f"soft={soft}, hard={hard}")


def check_cost_state(run_id: Optional[str]) -> CheckResult:
    state_dir = Path(os.environ.get("SWEFF_COST_STATE_DIR", "artifacts/cost_state"))
    cap_raw = os.environ.get("SWEFF_LLM_COST_CAP_USD", "")
    cap_msg = f"cap=${cap_raw}" if cap_raw else "cap=unlimited"
    if run_id is None:
        if not state_dir.exists():
            return _ok("cost_state", f"{cap_msg}; no prior state dir.")
        files = list(state_dir.glob("*.json"))
        return _ok(
            "cost_state",
            f"{cap_msg}; {len(files)} prior run state file(s) at {state_dir}.",
        )
    safe = run_id.replace("/", "_").replace("\\", "_")
    state_path = state_dir / f"{safe}.json"
    if not state_path.exists():
        return _ok("cost_state", f"{cap_msg}; fresh run ({state_path} absent).")
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return _warn(
            "cost_state",
            f"prior state {state_path} exists but is unreadable: {e}",
            "Delete the corrupted state file before resuming.",
        )
    total = float(state.get("total_usd", 0.0))
    calls = int(state.get("calls", 0))
    detail = f"resuming run_id={run_id}: prior spend ${total:.4f} over {calls} calls; {cap_msg}"
    if cap_raw:
        try:
            cap = float(cap_raw)
            if total >= cap:
                return _fail(
                    "cost_state",
                    f"prior total ${total:.4f} >= cap ${cap:.4f}.",
                    "Raise SWEFF_LLM_COST_CAP_USD or pick a new --run-id.",
                )
            if total >= 0.8 * cap:
                return _warn(
                    "cost_state",
                    f"prior total ${total:.4f} is >= 80% of cap ${cap:.4f}.",
                )
        except ValueError:
            pass
    return _ok("cost_state", detail)


def check_dataset(dataset_path: Optional[Path]) -> CheckResult:
    if dataset_path is None:
        return _skip("dataset", "no --dataset passed")
    if not dataset_path.exists():
        return _fail(
            "dataset",
            f"{dataset_path} does not exist.",
            "Point --dataset at the JSONL produced by run_pipeline.sh.",
        )
    try:
        from scripts.validate_dataset import validate_dataset  # noqa: WPS433
    except ImportError as e:
        return _warn(
            "dataset",
            f"could not import validate_dataset helper: {e}",
            "Run scripts/validate_dataset.py manually.",
        )
    count, errors, warnings = validate_dataset(dataset_path)
    if errors:
        return _fail(
            "dataset",
            f"{count} records; {len(errors)} validation error(s).",
            "Run scripts/validate_dataset.py for full error list.",
        )
    detail = f"{count} records valid"
    if warnings:
        detail += f"; {len(warnings)} non-fatal warning(s)"
    return _ok("dataset", detail)


# ---------------------------------------------------------------------------
# C++ toolchain checks (opt-in via --cpp)
# ---------------------------------------------------------------------------

_CPP_TOOLS_REQUIRED = ("g++", "cmake", "ninja", "ccache", "gcov", "lcov", "gcovr")


def check_cpp_toolchain() -> CheckResult:
    """Verify host has C++17 build and coverage tooling.

    The Docker base image (``sweb.base.cpp:latest``) carries all of these.
    This check is for hosts running tests directly or to fail fast before a
    10k-instance run.
    """
    missing = [name for name in _CPP_TOOLS_REQUIRED if shutil.which(name) is None]
    if missing:
        return _warn(
            "cpp_toolchain",
            f"missing: {', '.join(missing)}",
            "Bundled in cpp Docker base image; only required for host-side runs.",
            "Ubuntu: apt-get install gcc-12 g++-12 cmake ninja-build ccache lcov gcovr",
        )
    try:
        proc = subprocess.run(
            ["g++", "--version"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _warn("cpp_toolchain", f"g++ probe failed: {e}")
    import re as _re
    match = _re.search(r"\b(\d+)\.\d+\.\d+\b", proc.stdout)
    if not match:
        return _warn("cpp_toolchain", "could not parse g++ version output")
    major = int(match.group(1))
    if major < 9:
        return _fail(
            "cpp_toolchain",
            f"g++ major version {major} too old (need >= 9 for C++17).",
            "Install gcc-12: apt-get install gcc-12 g++-12.",
        )
    return _ok("cpp_toolchain", f"g++ {major}.x, all tools present")


def check_cpp_libraries() -> CheckResult:
    """Probe for GoogleTest 1.14+ and Google Benchmark 1.8+ headers."""
    gtest_paths = ("/usr/include/gtest/gtest.h", "/usr/local/include/gtest/gtest.h")
    bench_paths = (
        "/usr/include/benchmark/benchmark.h",
        "/usr/local/include/benchmark/benchmark.h",
    )
    missing = []
    if not any(Path(p).exists() for p in gtest_paths):
        missing.append("GoogleTest")
    if not any(Path(p).exists() for p in bench_paths):
        missing.append("Google Benchmark")
    if missing:
        return _warn(
            "cpp_libraries",
            f"host missing: {', '.join(missing)}",
            "Bundled in cpp Docker base image; only required for host-side runs.",
        )
    return _ok("cpp_libraries", "GoogleTest + Google Benchmark headers present")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

_GLYPHS = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}


def run_checks(args: argparse.Namespace) -> Tuple[List[CheckResult], int]:
    checks: List[Tuple[str, Callable[[], CheckResult]]] = [
        ("github_tokens", check_github_tokens),
        ("aws_credentials", check_aws_credentials),
        ("ecr_registry", check_ecr_registry),
        ("docker_daemon", check_docker_daemon),
        ("disk_space", lambda: check_disk_space(args.min_disk_gb)),
        ("fd_limit", lambda: check_fd_limit(args.min_fds)),
        ("cost_state", lambda: check_cost_state(args.run_id)),
        ("dataset", lambda: check_dataset(Path(args.dataset) if args.dataset else None)),
    ]
    if getattr(args, "cpp", False):
        checks.extend([
            ("cpp_toolchain", check_cpp_toolchain),
            ("cpp_libraries", check_cpp_libraries),
        ])
    results: List[CheckResult] = []
    for _, fn in checks:
        try:
            results.append(fn())
        except Exception as e:  # noqa: BLE001 — preflight must never blow up itself
            results.append(_warn(fn.__name__, f"check raised unexpectedly: {e}"))
    exit_code = 0
    for r in results:
        if r.status == "FAIL":
            exit_code = 1
        elif r.status == "WARN" and args.strict:
            exit_code = 1
    return results, exit_code


def print_report(results: List[CheckResult]) -> None:
    print()
    print("=" * 60)
    print(" SWE-fficiency run preflight")
    print("=" * 60)
    for r in results:
        glyph = _GLYPHS.get(r.status, "[?]")
        print(f"{glyph} {r.name:18s}  {r.detail}")
        for s in r.suggestions:
            print(f"            -> {s}")
    counts = {k: sum(1 for r in results if r.status == k) for k in _GLYPHS}
    print("-" * 60)
    print(
        f" Summary: {counts['PASS']} pass, {counts['WARN']} warn, "
        f"{counts['FAIL']} fail, {counts['SKIP']} skip"
    )
    print()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        help="Optional path to JSONL dataset to validate via validate_dataset.py.",
    )
    parser.add_argument(
        "--run-id",
        help="If given, also check the persisted cost-tracker state for this run.",
    )
    parser.add_argument(
        "--min-disk-gb",
        type=float,
        default=float(os.environ.get("SWEFF_MIN_DISK_GB", "50")),
        help="Minimum free disk space in GB on the Docker data dir.",
    )
    parser.add_argument(
        "--min-fds",
        type=int,
        default=int(os.environ.get("SWEFF_MIN_FDS", "4096")),
        help="Minimum soft RLIMIT_NOFILE.",
    )
    parser.add_argument(
        "--cpp",
        action="store_true",
        help="Also check C++ build/coverage toolchain (gcc-12, cmake, ninja, lcov, gcovr, GoogleTest, Google Benchmark).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat WARN as FAIL (non-zero exit).",
    )
    args = parser.parse_args(argv)

    results, exit_code = run_checks(args)
    print_report(results)
    if exit_code == 0:
        print(" preflight: OK")
    else:
        print(" preflight: FAILED — fix above before launching.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
