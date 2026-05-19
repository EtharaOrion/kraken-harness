#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Full preflight for a 10k-instance autonomous TypeScript run.

Standalone fork of ``scripts/validate_run.py``. The Python preflight is
left untouched. This script adds:

* All shared infrastructure checks (GitHub tokens, AWS creds, ECR, Docker,
  disk space, FD limit, cost state) — duplicated here so the ts pipeline
  has zero edges into the Python validator file.
* TypeScript toolchain probe (Node 20+, package manager, vitest CLI).
* TypeScript libraries probe (vitest, vitest bench, @vitest/coverage-v8).
* Optional ts dataset validation via ``validate_dataset_ts.py``.

Image-tag references for this pipeline: ``sweb.eval.ts.<id>``,
``sweb.env.ts.<hash>``, ``sweb.base.ts``. Run-IDs follow the
``ts_<repo>_<timestamp>`` convention. Per-instance result files inside
the container live at ``/tmp/vitest_results.json``,
``/tmp/vitest_results.junit.xml``, and ``/tmp/vitest_bench.json``;
coverage lands at ``coverage/coverage-final.json`` (vitest v8 format).

Exits 0 if every check passes (or is downgraded to a WARN). Non-zero on the
first FAIL. Pass ``--strict`` to escalate WARN to FAIL.

Usage:
    python scripts/validate_run_ts.py [--dataset PATH] [--strict] \\
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
# Infrastructure checks (shared with Python preflight; duplicated here to
# keep the ts pipeline free of any edge into validate_run.py).
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
    if not region:
        return _warn(
            "aws_credentials",
            "AWS credentials present but no AWS_REGION/AWS_DEFAULT_REGION set.",
            "Export AWS_REGION=us-east-1 (or your chosen region).",
        )
    return _ok("aws_credentials", f"credentials present; region={region}")


def check_ecr_registry() -> CheckResult:
    registry = os.environ.get("ECR_REGISTRY")
    if not registry:
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
            "Point --dataset at the ts JSONL produced by run_pipeline_ts.sh.",
        )
    try:
        from scripts.validate_dataset_ts import validate_dataset_ts
    except ImportError as e:
        return _warn(
            "dataset",
            f"could not import validate_dataset_ts helper: {e}",
            "Run scripts/validate_dataset_ts.py manually.",
        )
    count, errors, warnings = validate_dataset_ts(dataset_path)
    if errors:
        return _fail(
            "dataset",
            f"{count} records; {len(errors)} validation error(s).",
            "Run scripts/validate_dataset_ts.py for full error list.",
        )
    detail = f"{count} records valid"
    if warnings:
        detail += f"; {len(warnings)} non-fatal warning(s)"
    return _ok("dataset", detail)


# ---------------------------------------------------------------------------
# TypeScript toolchain checks (always-on for this script).
# ---------------------------------------------------------------------------

_TS_TOOLS_REQUIRED = ("node",)
_TS_PACKAGE_MANAGERS = ("npm", "pnpm", "yarn")


def check_ts_toolchain() -> CheckResult:
    """Verify host has Node 20+ and at least one package manager."""
    missing = [name for name in _TS_TOOLS_REQUIRED if shutil.which(name) is None]
    if missing:
        return _warn(
            "ts_toolchain",
            f"missing: {', '.join(missing)}",
            "Bundled in ts Docker base image; only required for host-side runs.",
            "Install Node 20+: https://nodejs.org/ (or use nvm/fnm/volta).",
        )
    pms_present = [name for name in _TS_PACKAGE_MANAGERS if shutil.which(name) is not None]
    if not pms_present:
        return _warn(
            "ts_toolchain",
            "no package manager (npm/pnpm/yarn) on PATH",
            "Bundled in ts Docker base image; only required for host-side runs.",
            "Install at least one of npm, pnpm, or yarn.",
        )
    try:
        proc = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _warn("ts_toolchain", f"node probe failed: {e}")
    import re as _re
    match = _re.search(r"v(\d+)\.\d+\.\d+", proc.stdout)
    if not match:
        return _warn("ts_toolchain", "could not parse node version output")
    major = int(match.group(1))
    if major < 20:
        return _fail(
            "ts_toolchain",
            f"node major version {major} too old (need >= 20).",
            "Install Node 20+: nvm install 20 && nvm use 20.",
        )
    return _ok(
        "ts_toolchain",
        f"node {major}.x, package manager(s): {', '.join(pms_present)}",
    )


def check_ts_libraries() -> CheckResult:
    """Probe for vitest CLI and ``@vitest/coverage-v8`` reachable on host."""
    missing = []
    if shutil.which("vitest") is None:
        try:
            proc = subprocess.run(
                ["npx", "--no-install", "vitest", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode != 0:
                missing.append("vitest")
        except (OSError, subprocess.TimeoutExpired):
            missing.append("vitest")
    coverage_pkg_paths = (
        REPO_ROOT / "node_modules" / "@vitest" / "coverage-v8" / "package.json",
        Path.home() / "node_modules" / "@vitest" / "coverage-v8" / "package.json",
    )
    if not any(p.exists() for p in coverage_pkg_paths):
        missing.append("@vitest/coverage-v8")
    if missing:
        return _warn(
            "ts_libraries",
            f"host missing: {', '.join(missing)}",
            "Bundled in ts Docker base image; only required for host-side runs.",
        )
    return _ok("ts_libraries", "vitest + @vitest/coverage-v8 present")


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
        ("ts_toolchain", check_ts_toolchain),
        ("ts_libraries", check_ts_libraries),
    ]
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
    print(" SWE-fficiency ts run preflight")
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
        help="Optional path to JSONL dataset to validate via validate_dataset_ts.py.",
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
        "--strict",
        action="store_true",
        help="Treat WARN as FAIL (non-zero exit).",
    )
    args = parser.parse_args(argv)

    results, exit_code = run_checks(args)
    print_report(results)
    if exit_code == 0:
        print(" ts preflight: OK")
    else:
        print(" ts preflight: FAILED — fix above before launching.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
