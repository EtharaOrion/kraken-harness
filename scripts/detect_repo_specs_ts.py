#!/usr/bin/env python3
"""Auto-detect repo specs for the SWE-fficiency TypeScript pipeline.

Clones repos, checks out base commits, and auto-detects: Node version,
build system (node-only via ``package.json`` + ``tsconfig.json``),
package manager (autodetected from lockfile), package source, system
dependencies, test framework, perf framework, and license. Enriches
dataset instances with the detected fields.

This is the TypeScript analogue of the C++ sibling detector.
The algorithmic skeleton (clone / checkout / cache / group-by-(repo,
base_commit) / parallel workers) mirrors that script.

Phase 1 contract:
    * Only ``vitest`` is recognized as a test framework. Repos using
      jest / mocha / ava / jasmine / tap are flagged ``unsupported`` and
      their instances are skipped (no silent remapping).
    * Perf framework is always ``vitest-bench`` (tinybench).
    * Package manager is autodetected from lockfiles via
      :func:`detect_package_manager_ts` (pnpm > yarn > bun > npm).

Usage:
    python scripts/detect_repo_specs_ts.py --input data.jsonl --output enriched.jsonl
    python scripts/detect_repo_specs_ts.py --input data.jsonl --output enriched.jsonl --workers 4
    python scripts/detect_repo_specs_ts.py --input data.jsonl --dry-run
    python scripts/detect_repo_specs_ts.py --validate --input enriched.jsonl --output /dev/null
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from swefficiency.cache.sqlite_cache import SqliteKVCache
from swefficiency.cache.sqlite_cache_ts import (
    NS_REPO_SPECS_TS,
    get_default_cache_ts,
)
from swefficiency.harness.constants_ts import (
    BUILD_NODE,
    MAP_REPO_TO_BUILD_SYSTEM_TS,
    NODE_VERSION,
    TEST_FRAMEWORK_VITEST,
)
from swefficiency.harness.dynamic_specs_ts import detect_package_manager_ts

log = logging.getLogger("detect_repo_specs_ts")


# Test frameworks recognized explicitly as not-vitest. Phase 1 surfaces
# these as ``unsupported`` so callers skip instead of silently mapping.
_UNSUPPORTED_TEST_FRAMEWORKS = (
    "jest",
    "@jest/core",
    "ts-jest",
    "mocha",
    "ava",
    "jasmine",
    "tap",
    "tape",
    "karma",
)

PERF_FRAMEWORK_VITEST_BENCH = "vitest-bench"
LOG_PARSER_TYPE_TS = "ts_vitest_json"
UNSUPPORTED = "unsupported"

_NODE_VERSION_RE = re.compile(r"(\d+)(?:\.\d+){0,2}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str | None:
    """Read a file as text, returning None if it doesn't exist or fails."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


def _read_package_json(repo_dir: Path) -> dict[str, Any] | None:
    """Load and parse the top-level ``package.json``. None on any failure."""
    raw = _read_text(repo_dir / "package.json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("Failed to parse %s/package.json: %s", repo_dir, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def _collect_deps(pkg: dict[str, Any]) -> dict[str, str]:
    """Merge dependencies / devDependencies / optional / peer into one dict."""
    out: dict[str, str] = {}
    for key in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ):
        section = pkg.get(key)
        if isinstance(section, dict):
            for name, version in section.items():
                if isinstance(name, str):
                    out[name] = str(version) if version is not None else ""
    return out


def _git_clone(repo: str, dest: Path, *, timeout: int = 300) -> bool:
    """Clone a GitHub repo to dest. Returns True on success."""
    url = f"https://github.com/{repo}.git"
    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "200", url, str(dest)],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("Clone failed for %s: %s", repo, exc)
        return False


def _git_checkout(repo_dir: Path, commit: str, *, timeout: int = 120) -> bool:
    """Checkout a specific commit. Fetches if shallow clone doesn't have it."""
    try:
        subprocess.run(
            ["git", "checkout", commit],
            cwd=str(repo_dir),
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        return True
    except subprocess.CalledProcessError:
        try:
            subprocess.run(
                ["git", "fetch", "--unshallow"],
                cwd=str(repo_dir),
                check=True,
                capture_output=True,
                timeout=300,
            )
            subprocess.run(
                ["git", "checkout", commit],
                cwd=str(repo_dir),
                check=True,
                capture_output=True,
                timeout=timeout,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("Checkout failed for %s in %s: %s", commit, repo_dir, exc)
            return False
    except subprocess.TimeoutExpired as exc:
        log.warning("Checkout timed out for %s: %s", commit, exc)
        return False


# ---------------------------------------------------------------------------
# Detection functions (TypeScript specific)
# ---------------------------------------------------------------------------


def detect_build_system(repo_dir: Path) -> str:
    """Detect build system. Phase 1: node-only.

    Returns :data:`BUILD_NODE` iff *both* ``package.json`` and
    ``tsconfig.json`` exist at the repo root. Anything else returns
    :data:`UNSUPPORTED` so the caller can skip the instance.
    """
    if (
        (repo_dir / "package.json").is_file()
        and (repo_dir / "tsconfig.json").is_file()
    ):
        return BUILD_NODE
    return UNSUPPORTED


def detect_build_scripts(repo_dir: Path) -> dict[str, str]:
    """Return ``scripts.build`` / ``scripts.test`` from package.json (if any)."""
    pkg = _read_package_json(repo_dir)
    if not pkg:
        return {}
    scripts = pkg.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("build", "test"):
        val = scripts.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def detect_test_framework(repo_dir: Path, repo: str) -> str:
    """Detect test framework.

    Priority: explicit override from ``MAP_REPO_TO_BUILD_SYSTEM_TS`` >
    ``vitest`` presence in package.json dependencies / devDependencies.
    Any other recognized framework (jest / mocha / ...) yields
    :data:`UNSUPPORTED` — Phase 1 refuses to silently remap.
    """
    entry = MAP_REPO_TO_BUILD_SYSTEM_TS.get(repo, {})
    override = entry.get("test_framework")
    if override and override != "detect":
        return override

    pkg = _read_package_json(repo_dir)
    if not pkg:
        return UNSUPPORTED
    deps = _collect_deps(pkg)
    if "vitest" in deps:
        return TEST_FRAMEWORK_VITEST
    for name in _UNSUPPORTED_TEST_FRAMEWORKS:
        if name in deps:
            log.info(
                "Repo %s declares non-vitest test framework %r; "
                "marking unsupported (Phase 1 is vitest-only)",
                repo,
                name,
            )
            return UNSUPPORTED
    return UNSUPPORTED


def detect_perf_framework(repo_dir: Path, repo: str) -> str:
    """Perf framework — Phase 1 always ``vitest-bench`` (tinybench)."""
    return PERF_FRAMEWORK_VITEST_BENCH


def detect_node_version(repo_dir: Path, repo: str) -> str:
    """Pull node major version from ``engines.node`` in package.json."""
    pkg = _read_package_json(repo_dir)
    if pkg:
        engines = pkg.get("engines")
        if isinstance(engines, dict):
            node_req = engines.get("node")
            if isinstance(node_req, str) and node_req.strip():
                m = _NODE_VERSION_RE.search(node_req)
                if m:
                    return m.group(1)
    entry = MAP_REPO_TO_BUILD_SYSTEM_TS.get(repo, {})
    return entry.get("node_version") or NODE_VERSION


def detect_packages_source(repo_dir: Path) -> tuple[str, list[str]]:
    """Detect package manifest format.

    Returns ``(source_type, reqs_paths)`` where ``source_type`` is
    ``"package.json"`` or ``""`` and ``reqs_paths`` is the manifest file
    list relative to ``repo_dir``.
    """
    if (repo_dir / "package.json").is_file():
        return "package.json", ["package.json"]
    return "", []


def detect_system_pkgs(repo_dir: Path, repo: str) -> list[str]:
    """Baseline apt package list from the per-repo override map.

    Pure TypeScript repos rarely need apt packages so we trust the
    :data:`MAP_REPO_TO_BUILD_SYSTEM_TS` override entry and don't scan the
    sources for native deps.
    """
    entry = MAP_REPO_TO_BUILD_SYSTEM_TS.get(repo, {})
    return list(entry.get("system_pkgs", []))


def detect_version(repo_dir: Path, repo: str) -> str:
    """Detect project version from package.json ``version`` field."""
    pkg = _read_package_json(repo_dir)
    if not pkg:
        return ""
    raw_version = pkg.get("version")
    if not isinstance(raw_version, str):
        return ""
    parts = raw_version.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return raw_version


def _runner_for_pm(pkg_mgr: str) -> str:
    """Return the script-runner invocation for a given package manager."""
    return {
        "npm": "npx",
        "pnpm": "pnpm exec",
        "yarn": "yarn",
        "bun": "bun x",
    }.get(pkg_mgr, "npx")


def detect_install_cmd(repo_dir: Path, repo: str) -> str:
    """Default install command for the autodetected package manager."""
    pkg_mgr = detect_package_manager_ts(str(repo_dir))
    return f"{pkg_mgr} install"


def detect_test_cmd(repo_dir: Path, repo: str) -> str:
    """Default test command — Vitest with JSON + JUnit reporters."""
    pkg_mgr = detect_package_manager_ts(str(repo_dir))
    runner = _runner_for_pm(pkg_mgr)
    return (
        f"{runner} vitest run "
        "--reporter=json --reporter=junit "
        "--outputFile.json=/tmp/vitest_results.json "
        "--outputFile.junit=/tmp/vitest_results.junit.xml"
    )


def detect_pre_install(repo_dir: Path, repo: str) -> list[str]:
    """Return any pre-install shell commands required before install."""
    cmds: list[str] = []
    system_pkgs = detect_system_pkgs(repo_dir, repo)
    if system_pkgs:
        cmds.append(
            "apt-get update && apt-get install -y --no-install-recommends "
            + " ".join(system_pkgs)
        )
    return cmds


def check_license(repo_dir: Path) -> str:
    """Best-effort license-name extraction.

    Checks LICENSE/COPYING text first, then falls back to package.json's
    ``license`` SPDX field.
    """
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        raw = _read_text(repo_dir / name)
        if not raw:
            continue
        head = raw[:2000].lower()
        if "apache license" in head:
            return "Apache-2.0"
        if (
            "mit license" in head
            or "permission is hereby granted, free of charge" in head
        ):
            return "MIT"
        if (
            "bsd 3-clause" in head
            or "redistribution and use in source and binary forms" in head
        ):
            return "BSD-3-Clause"
        if "bsd 2-clause" in head:
            return "BSD-2-Clause"
        if "isc license" in head:
            return "ISC"
        if "mozilla public license" in head:
            return "MPL-2.0"
    pkg = _read_package_json(repo_dir)
    if pkg:
        spdx = pkg.get("license")
        if isinstance(spdx, str) and spdx.strip():
            return spdx.strip()
    return ""


def detect_all_specs_ts(repo_dir: Path, repo: str) -> dict | None:
    """Run all detection functions on a repo checkout.

    Returns the enrichment dict, or ``None`` if the repo is unsupported in
    Phase 1 (missing package.json/tsconfig.json or non-vitest framework).
    """
    build_system = detect_build_system(repo_dir)
    if build_system == UNSUPPORTED:
        log.warning(
            "Repo %s missing package.json/tsconfig.json at root; "
            "skipping (unsupported)",
            repo,
        )
        return None

    test_framework = detect_test_framework(repo_dir, repo)
    if test_framework == UNSUPPORTED:
        log.warning(
            "Repo %s test framework is unsupported in Phase 1; skipping", repo
        )
        return None

    perf_framework = detect_perf_framework(repo_dir, repo)
    node_version = detect_node_version(repo_dir, repo)
    package_manager = detect_package_manager_ts(str(repo_dir))
    install_cmd = detect_install_cmd(repo_dir, repo)
    test_cmd = detect_test_cmd(repo_dir, repo)
    source_type, reqs_paths = detect_packages_source(repo_dir)
    pre_install = detect_pre_install(repo_dir, repo)
    version = detect_version(repo_dir, repo)
    license_name = check_license(repo_dir)
    system_pkgs = detect_system_pkgs(repo_dir, repo)
    build_scripts = detect_build_scripts(repo_dir)

    return {
        "language": "ts",
        "node_version": node_version,
        "build_system": build_system,
        "test_framework": test_framework,
        "perf_framework": perf_framework,
        "package_manager": package_manager,
        "install_cmd": install_cmd,
        "test_cmd_override": test_cmd,
        "packages_source": source_type,
        "reqs_paths": reqs_paths,
        "system_pkgs": system_pkgs,
        "pre_install_cmds": pre_install,
        "log_parser_type": LOG_PARSER_TYPE_TS,
        "build_scripts": build_scripts,
        "version": version,
        "_license": license_name,
    }


def process_repo_group_ts(
    repo: str,
    base_commit: str,
    clone_dir: Path,
    cache: SqliteKVCache,
) -> dict | None:
    """Clone repo, checkout commit, detect ts specs. Returns specs dict or None."""
    cache_key = (repo, base_commit)
    cached_specs = cache.get(NS_REPO_SPECS_TS, cache_key)
    if cached_specs is not None and all(
        f in cached_specs for f in REQUIRED_ENRICHMENT_FIELDS_TS
    ):
        log.info("Cache hit for ts %s@%s", repo, base_commit[:8])
        return cached_specs
    if cached_specs is not None:
        log.info("Stale ts cache for %s@%s; re-detecting", repo, base_commit[:8])

    dest = clone_dir / repo.replace("/", "__") / base_commit[:12]
    cloned = False

    try:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)

        if not _git_clone(repo, dest):
            return None
        cloned = True

        if not _git_checkout(dest, base_commit):
            return None

        specs = detect_all_specs_ts(dest, repo)
        if specs is None:
            return None
        cache.set(NS_REPO_SPECS_TS, cache_key, specs)
        log.info(
            "Detected ts specs for %s: node=%s build=%s framework=%s pkg_mgr=%s",
            cache_key,
            specs["node_version"],
            specs["build_system"],
            specs["test_framework"],
            specs["package_manager"],
        )
        return specs

    except Exception:
        log.exception("Unexpected error processing ts %s", cache_key)
        return None
    finally:
        if cloned and dest.exists():
            try:
                shutil.rmtree(dest)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def load_instances(input_path: str, split: str = "test") -> list:
    path = Path(input_path)
    if path.exists() and path.suffix in (".jsonl", ".json"):
        return _load_jsonl(path)
    return _load_hf(input_path, split)


def _load_jsonl(path: Path) -> list:
    instances: list = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                instances.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning("Skipping invalid JSON at line %d: %s", line_no, exc)
    log.info("Loaded %d ts instances from %s", len(instances), path)
    return instances


def _load_hf(dataset_name: str, split: str) -> list:
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError:
        log.error(
            "Cannot load HF dataset '%s': `datasets` package not installed. "
            "Install with: pip install datasets",
            dataset_name,
        )
        sys.exit(1)

    ds = load_dataset(dataset_name, split=split)
    instances = [dict(row) for row in ds]  # type: ignore[arg-type]
    log.info(
        "Loaded %d ts instances from HF dataset '%s' (split=%s)",
        len(instances),
        dataset_name,
        split,
    )
    return instances


def write_jsonl(instances: list, output_path: str) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for inst in instances:
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")
    log.info("Wrote %d ts instances to %s", len(instances), out)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_ENRICHMENT_FIELDS_TS = (
    "language",
    "node_version",
    "build_system",
    "test_framework",
    "perf_framework",
    "package_manager",
    "install_cmd",
    "test_cmd_override",
    "packages_source",
    "reqs_paths",
    "system_pkgs",
    "pre_install_cmds",
    "log_parser_type",
)


def validate_instances(instances: list) -> bool:
    missing_count = 0
    for inst in instances:
        iid = inst.get("instance_id", "<unknown>")
        missing = [f for f in REQUIRED_ENRICHMENT_FIELDS_TS if f not in inst]
        if missing:
            log.warning("Instance %s missing ts fields: %s", iid, ", ".join(missing))
            missing_count += 1
    if missing_count:
        log.error(
            "%d / %d ts instances have missing fields",
            missing_count,
            len(instances),
        )
        return False
    log.info("All %d ts instances have required enrichment fields", len(instances))
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-detect repo specs for SWE-fficiency TypeScript dataset",
    )
    parser.add_argument("--input", required=True, help="Input JSONL file or HF dataset name")
    parser.add_argument(
        "--output",
        default="repo_specs_ts.json",
        help="Output JSONL file path (convention: repo_specs_ts.json)",
    )
    parser.add_argument(
        "--clone-dir",
        default="artifacts_ts/clones",
        help="Directory for cloning repos",
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Parallel workers for cloning/detection"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print detections without writing"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate existing JSONL has required fields",
    )
    parser.add_argument(
        "--license-filter",
        nargs="*",
        default=[
            "MIT",
            "MIT-0",
            "Apache-2.0",
            "BSD-3-Clause",
            "BSD-2-Clause",
            "ISC",
            "BSL-1.0",
        ],
        help="Allowed licenses (empty = no filter)",
    )
    parser.add_argument(
        "--split", default="test", help="HF dataset split (if using HF dataset)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    instances = load_instances(args.input, split=args.split)
    if not instances:
        log.error("No ts instances loaded. Exiting.")
        sys.exit(1)

    if args.validate:
        ok = validate_instances(instances)
        sys.exit(0 if ok else 1)

    cache = get_default_cache_ts()

    groups: dict = defaultdict(list)
    for idx, inst in enumerate(instances):
        repo = inst.get("repo", "")
        commit = inst.get("base_commit", "")
        if not repo or not commit:
            log.warning("Instance %d missing repo or base_commit, skipping", idx)
            continue
        groups[(repo, commit)].append(idx)

    log.info(
        "Processing %d unique ts (repo, base_commit) groups for %d instances",
        len(groups),
        len(instances),
    )

    clone_dir = Path(args.clone_dir)
    clone_dir.mkdir(parents=True, exist_ok=True)

    specs_map: dict = {}
    if args.workers <= 1:
        for key in groups:
            repo, commit = key
            specs_map[key] = process_repo_group_ts(repo, commit, clone_dir, cache)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_key = {}
            for key in groups:
                repo, commit = key
                fut = executor.submit(
                    process_repo_group_ts, repo, commit, clone_dir, cache
                )
                future_to_key[fut] = key
            for fut in as_completed(future_to_key):
                key = future_to_key[fut]
                try:
                    specs_map[key] = fut.result()
                except Exception:
                    log.exception("Worker error for ts %s", key)
                    specs_map[key] = None

    enriched = 0
    skipped_license = 0
    skipped_failure = 0
    license_filter = set(args.license_filter) if args.license_filter else set()

    output_instances: list = []

    for (repo, commit), idxs in groups.items():
        specs = specs_map.get((repo, commit))
        if specs is None:
            skipped_failure += len(idxs)
            log.warning(
                "No ts specs for %s@%s -- skipping %d instances",
                repo,
                commit[:8],
                len(idxs),
            )
            continue

        if license_filter and specs.get("_license") not in license_filter:
            skipped_license += len(idxs)
            log.info(
                "License '%s' for %s not in filter -- skipping %d instances",
                specs.get("_license"),
                repo,
                len(idxs),
            )
            continue

        for idx in idxs:
            inst = dict(instances[idx])
            for field in REQUIRED_ENRICHMENT_FIELDS_TS:
                inst[field] = specs[field]
            if specs.get("version") and not inst.get("version"):
                inst["version"] = specs["version"]
            output_instances.append(inst)
            enriched += 1

    all_grouped_idxs: set = set()
    for idxs in groups.values():
        all_grouped_idxs.update(idxs)
    for idx, inst in enumerate(instances):
        if idx not in all_grouped_idxs:
            output_instances.append(inst)

    log.info("=" * 60)
    log.info("TypeScript Summary:")
    log.info("  Total instances:    %d", len(instances))
    log.info("  Unique repos:       %d", len(groups))
    log.info("  Enriched:           %d", enriched)
    log.info("  Skipped (license):  %d", skipped_license)
    log.info("  Skipped (failure):  %d", skipped_failure)
    log.info("=" * 60)

    if args.dry_run:
        for key, specs in specs_map.items():
            if specs is not None:
                repo, commit = key
                print(f"\n--- {repo} @ {commit[:8]} ---")
                for k, v in specs.items():
                    if k != "_license":
                        print(f"  {k}: {v}")
                    else:
                        print(f"  license: {v}")
        log.info("Dry run -- no ts output file written.")
    else:
        write_jsonl(output_instances, args.output)


if __name__ == "__main__":
    main()
