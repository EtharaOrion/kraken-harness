#!/usr/bin/env python3
"""Auto-detect repo specs for the SWE-fficiency C++ pipeline.

Clones repos, checks out base commits, and auto-detects: CMake minimum
version, C++ standard, build system, package source (vcpkg.json /
conanfile.txt / conanfile.py / system), system dependencies, test
framework, and license. Enriches dataset instances with the detected
fields.

This is the C++ analogue of ``scripts/detect_repo_specs.py``. The
algorithmic skeleton (clone / checkout / cache / group-by-(repo,
base_commit) / parallel workers) mirrors the Python script.

Usage:
    python scripts/detect_repo_specs_cpp.py --input data.jsonl --output enriched.jsonl
    python scripts/detect_repo_specs_cpp.py --input data.jsonl --output enriched.jsonl --workers 4
    python scripts/detect_repo_specs_cpp.py --input data.jsonl --dry-run
    python scripts/detect_repo_specs_cpp.py --validate --input enriched.jsonl --output /dev/null
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
from swefficiency.cache.sqlite_cache_cpp import (
    NS_REPO_SPECS_CPP,
    get_default_cache_cpp,
)
from swefficiency.harness.constants_cpp import (
    BUILD_CMAKE,
    BUILD_CMAKE_NINJA,
    MAP_REPO_TO_BUILD_SYSTEM_CPP,
    TEST_FRAMEWORK_CATCH2,
    TEST_FRAMEWORK_CTEST,
    TEST_FRAMEWORK_GTEST,
)

log = logging.getLogger("detect_repo_specs_cpp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str | None:
    """Read a file as text, returning None if it doesn't exist or fails."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


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
# Detection functions (C++ specific)
# ---------------------------------------------------------------------------


_CMAKE_VERSION_RE = re.compile(
    r"project\s*\([^)]*?\bVERSION\s+([0-9]+(?:\.[0-9]+){0,2})",
    re.IGNORECASE | re.DOTALL,
)
_CMAKE_MIN_RE = re.compile(
    r"cmake_minimum_required\s*\(\s*VERSION\s+([0-9]+(?:\.[0-9]+){1,2})",
    re.IGNORECASE,
)
_CMAKE_CXX_STD_RE = re.compile(
    r"set\s*\(\s*CMAKE_CXX_STANDARD\s+([0-9]{2})\s*\)",
    re.IGNORECASE,
)
_CMAKE_TARGET_CXX_RE = re.compile(
    r"cxx_std_([0-9]{2})\b",
    re.IGNORECASE,
)
_FIND_PACKAGE_RE = re.compile(
    r"find_package\s*\(\s*([A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_PKG_CHECK_RE = re.compile(
    r"pkg_check_modules\s*\(\s*[A-Za-z0-9_]+\s+([^)]+)\)",
    re.IGNORECASE,
)


def detect_min_cmake_version(repo_dir: Path) -> str:
    """Extract minimum cmake version from CMakeLists.txt."""
    raw = _read_text(repo_dir / "CMakeLists.txt")
    if not raw:
        return "3.10"
    m = _CMAKE_MIN_RE.search(raw)
    if m:
        return m.group(1)
    return "3.10"


def detect_cpp_standard(repo_dir: Path) -> str:
    """Extract C++ standard (e.g. ``17``) from CMakeLists.txt.

    Searches for ``CMAKE_CXX_STANDARD`` first, then
    ``target_compile_features(... cxx_std_NN)``. Falls back to ``"17"``.
    """
    raw = _read_text(repo_dir / "CMakeLists.txt")
    if not raw:
        return "17"
    m = _CMAKE_CXX_STD_RE.search(raw)
    if m:
        return m.group(1)
    m = _CMAKE_TARGET_CXX_RE.search(raw)
    if m:
        return m.group(1)
    return "17"


def detect_build_system(repo_dir: Path) -> str:
    """Detect build system. Phase 1: CMake only.

    Returns the constant from :mod:`harness.constants_cpp`. Future phases
    can add Bazel/Meson/autotools detection here.
    """
    if (repo_dir / "CMakeLists.txt").exists():
        # Prefer Ninja generator (faster, parallel-safe) when available.
        return BUILD_CMAKE_NINJA
    return BUILD_CMAKE


def detect_packages_source(repo_dir: Path) -> tuple[str, list[str]]:
    """Detect package manifest format.

    Returns ``(source_type, reqs_paths)`` where ``source_type`` is one of
    ``vcpkg.json``, ``conanfile.txt``, ``conanfile.py``, or ``""``.
    ``reqs_paths`` is a (possibly empty) list of manifest file paths
    relative to ``repo_dir``.
    """
    candidates = (
        ("vcpkg.json", "vcpkg.json"),
        ("conanfile.txt", "conanfile.txt"),
        ("conanfile.py", "conanfile.py"),
    )
    for fname, label in candidates:
        if (repo_dir / fname).exists():
            return label, [fname]
    return "", []


def detect_system_pkgs(repo_dir: Path, repo: str) -> list[str]:
    """Heuristic apt-get package list.

    1. If repo has an entry in :data:`MAP_REPO_TO_BUILD_SYSTEM_CPP` with
       ``system_pkgs``, use that as the baseline.
    2. Scan CMakeLists.txt for ``find_package(...)`` and
       ``pkg_check_modules(...)`` and add a small known mapping for
       common libraries.
    """
    pkgs: list[str] = []
    entry = MAP_REPO_TO_BUILD_SYSTEM_CPP.get(repo)
    if entry:
        pkgs.extend(entry.get("system_pkgs", []))

    raw = _read_text(repo_dir / "CMakeLists.txt") or ""
    found = {m.group(1) for m in _FIND_PACKAGE_RE.finditer(raw)}
    found.update(
        token.strip()
        for match in _PKG_CHECK_RE.finditer(raw)
        for token in match.group(1).split()
    )

    apt_map = {
        "OpenSSL": "libssl-dev",
        "ZLIB": "zlib1g-dev",
        "BZip2": "libbz2-dev",
        "Threads": None,  # libpthread is in libc6
        "Boost": "libboost-all-dev",
        "Eigen3": "libeigen3-dev",
        "OpenBLAS": "libopenblas-dev",
        "LAPACK": "liblapack-dev",
        "GTest": None,  # Preinstalled in base image
        "benchmark": None,
        "Catch2": None,
        "fmt": None,  # Often the target itself
        "spdlog": None,
        "nlohmann_json": None,
        "absl": None,
    }
    for name in found:
        apt = apt_map.get(name)
        if apt and apt not in pkgs:
            pkgs.append(apt)
    return pkgs


def detect_test_framework(repo_dir: Path, repo: str) -> str:
    """Detect test framework.

    Priority: explicit override from ``MAP_REPO_TO_BUILD_SYSTEM_CPP`` >
    detection from CMakeLists ( ``find_package(GTest)`` /
    ``find_package(Catch2)`` ) > ctest default.
    """
    entry = MAP_REPO_TO_BUILD_SYSTEM_CPP.get(repo)
    if entry and entry.get("test_framework"):
        return entry["test_framework"]

    raw = _read_text(repo_dir / "CMakeLists.txt") or ""
    found = {m.group(1).lower() for m in _FIND_PACKAGE_RE.finditer(raw)}
    if "gtest" in found or "googletest" in found:
        return TEST_FRAMEWORK_GTEST
    if "catch2" in found:
        return TEST_FRAMEWORK_CATCH2
    return TEST_FRAMEWORK_CTEST


def detect_version(repo_dir: Path, repo: str) -> str:
    """Detect project version from CMakeLists.txt ``project(... VERSION X.Y.Z)``."""
    raw = _read_text(repo_dir / "CMakeLists.txt") or ""
    m = _CMAKE_VERSION_RE.search(raw)
    if m:
        full = m.group(1)
        parts = full.split(".")
        if len(parts) >= 2:
            return f"{parts[0]}.{parts[1]}"
        return full

    vcpkg = _read_text(repo_dir / "vcpkg.json")
    if vcpkg:
        try:
            data = json.loads(vcpkg)
            for key in ("version-semver", "version", "version-string", "version-date"):
                if key in data:
                    full = str(data[key])
                    parts = full.split(".")
                    if len(parts) >= 2:
                        return f"{parts[0]}.{parts[1]}"
                    return full
        except json.JSONDecodeError:
            pass
    return ""


_CMAKE_TEST_OPTION_RE = re.compile(
    r"option\s*\(\s*([A-Za-z0-9_]*(?:TEST|TESTING|TESTS)[A-Za-z0-9_]*)\s",
    re.IGNORECASE,
)


def detect_cmake_flags(repo_dir: Path, repo: str) -> list[str]:
    """CMake -D flags needed to enable the test build.

    Mapped repos use their known test_flag. For any other repo we scan
    CMakeLists.txt for an ``option()`` whose name contains TEST/TESTING and
    enable it, preferring the CMake-standard ``BUILD_TESTING`` and
    ``*_BUILD_TESTS`` toggles. Without this the test build is never enabled
    for repos outside MAP_REPO_TO_BUILD_SYSTEM_CPP and ctest finds nothing.
    """
    entry = MAP_REPO_TO_BUILD_SYSTEM_CPP.get(repo, {})
    if entry.get("test_flag"):
        return [entry["test_flag"]]
    raw = _read_text(repo_dir / "CMakeLists.txt") or ""
    names = [m.group(1) for m in _CMAKE_TEST_OPTION_RE.finditer(raw)]
    if not names:
        return []

    def _rank(name: str) -> int:
        low = name.lower()
        if low == "build_testing":
            return 0
        if "build_test" in low:
            return 1
        if "test" in low:
            return 2
        return 3

    best = sorted(names, key=_rank)[0]
    return [f"-D{best}=ON"]


def detect_install_cmd(repo_dir: Path, repo: str) -> str:
    """Default install command: cmake configure with sensible defaults."""
    cpp_std = detect_cpp_standard(repo_dir)
    entry = MAP_REPO_TO_BUILD_SYSTEM_CPP.get(repo, {})
    extra_flag = entry.get("test_flag", "")
    flags = [
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
        "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
        f"-DCMAKE_CXX_STANDARD={cpp_std}",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ]
    if extra_flag:
        flags.append(extra_flag)
    return f"cmake -S /testbed -B /testbed/build {' '.join(flags)} -G Ninja"


def detect_test_cmd(repo_dir: Path, repo: str) -> str:
    """Default test command. Returns ctest invocation for all frameworks
    since both gtest and catch2 register themselves with ctest by default.
    """
    return (
        "ctest --test-dir /testbed/build --output-on-failure "
        "--output-junit /tmp/ctest_results.xml -j$(nproc)"
    )


def detect_pre_install(repo_dir: Path, repo: str) -> list[str]:
    """Return any pre-install shell commands required before configure."""
    cmds: list[str] = []
    system_pkgs = detect_system_pkgs(repo_dir, repo)
    if system_pkgs:
        cmds.append(
            "apt-get update && apt-get install -y --no-install-recommends "
            + " ".join(system_pkgs)
        )
    return cmds


def check_license(repo_dir: Path) -> str:
    """Best-effort license-name extraction from LICENSE or LICENSE.md."""
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        raw = _read_text(repo_dir / name)
        if not raw:
            continue
        head = raw[:2000].lower()
        if "apache license" in head:
            return "Apache-2.0"
        if "mit license" in head or "permission is hereby granted, free of charge" in head:
            return "MIT"
        if "bsd 3-clause" in head or "redistribution and use in source and binary forms" in head:
            return "BSD-3-Clause"
        if "bsd 2-clause" in head:
            return "BSD-2-Clause"
        if "boost software license" in head:
            return "BSL-1.0"
        if "mozilla public license" in head:
            return "MPL-2.0"
    return ""


def detect_all_specs_cpp(repo_dir: Path, repo: str) -> dict:
    """Run all detection functions on a repo checkout. Returns enrichment dict."""
    cpp_standard = detect_cpp_standard(repo_dir)
    install_cmd = detect_install_cmd(repo_dir, repo)
    test_cmd = detect_test_cmd(repo_dir, repo)
    source_type, reqs_paths = detect_packages_source(repo_dir)
    pre_install = detect_pre_install(repo_dir, repo)
    version = detect_version(repo_dir, repo)
    license_name = check_license(repo_dir)
    build_system = detect_build_system(repo_dir)
    test_framework = detect_test_framework(repo_dir, repo)
    min_cmake = detect_min_cmake_version(repo_dir)
    system_pkgs = detect_system_pkgs(repo_dir, repo)
    cmake_flags = detect_cmake_flags(repo_dir, repo)

    return {
        "language": "cpp",
        "cpp_standard": cpp_standard,
        "build_system": build_system,
        "min_cmake_version": min_cmake,
        "test_framework": test_framework,
        "cmake_flags": cmake_flags,
        "install_cmd": install_cmd,
        "test_cmd_override": test_cmd,
        "packages_source": source_type,
        "reqs_paths": reqs_paths,
        "system_pkgs": system_pkgs,
        "pre_install_cmds": pre_install,
        "log_parser_type": "cpp_best_effort",
        "version": version,
        "_license": license_name,
    }


def process_repo_group_cpp(
    repo: str,
    base_commit: str,
    clone_dir: Path,
    cache: SqliteKVCache,
) -> dict | None:
    """Clone repo, checkout commit, detect cpp specs. Returns specs dict or None."""
    cache_key = (repo, base_commit)
    cached_specs = cache.get(NS_REPO_SPECS_CPP, cache_key)
    if cached_specs is not None and all(
        f in cached_specs for f in REQUIRED_ENRICHMENT_FIELDS_CPP
    ):
        log.info("Cache hit for cpp %s@%s", repo, base_commit[:8])
        return cached_specs
    if cached_specs is not None:
        # Cached entry predates a newer required field — re-detect.
        log.info("Stale cpp cache for %s@%s; re-detecting", repo, base_commit[:8])

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

        specs = detect_all_specs_cpp(dest, repo)
        cache.set(NS_REPO_SPECS_CPP, cache_key, specs)
        log.info(
            "Detected cpp specs for %s: cpp_std=%s build=%s framework=%s",
            cache_key,
            specs["cpp_standard"],
            specs["build_system"],
            specs["test_framework"],
        )
        return specs

    except Exception:
        log.exception("Unexpected error processing cpp %s", cache_key)
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
    log.info("Loaded %d cpp instances from %s", len(instances), path)
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
        "Loaded %d cpp instances from HF dataset '%s' (split=%s)",
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
    log.info("Wrote %d cpp instances to %s", len(instances), out)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_ENRICHMENT_FIELDS_CPP = (
    "language",
    "cpp_standard",
    "build_system",
    "test_framework",
    "cmake_flags",
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
        missing = [f for f in REQUIRED_ENRICHMENT_FIELDS_CPP if f not in inst]
        if missing:
            log.warning("Instance %s missing cpp fields: %s", iid, ", ".join(missing))
            missing_count += 1
    if missing_count:
        log.error(
            "%d / %d cpp instances have missing fields",
            missing_count,
            len(instances),
        )
        return False
    log.info("All %d cpp instances have required enrichment fields", len(instances))
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-detect repo specs for SWE-fficiency C++ dataset",
    )
    parser.add_argument("--input", required=True, help="Input JSONL file or HF dataset name")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    parser.add_argument(
        "--clone-dir",
        default="artifacts_cpp/clones",
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
        log.error("No cpp instances loaded. Exiting.")
        sys.exit(1)

    if args.validate:
        ok = validate_instances(instances)
        sys.exit(0 if ok else 1)

    cache = get_default_cache_cpp()

    groups: dict = defaultdict(list)
    for idx, inst in enumerate(instances):
        repo = inst.get("repo", "")
        commit = inst.get("base_commit", "")
        if not repo or not commit:
            log.warning("Instance %d missing repo or base_commit, skipping", idx)
            continue
        groups[(repo, commit)].append(idx)

    log.info(
        "Processing %d unique cpp (repo, base_commit) groups for %d instances",
        len(groups),
        len(instances),
    )

    clone_dir = Path(args.clone_dir)
    clone_dir.mkdir(parents=True, exist_ok=True)

    specs_map: dict = {}
    if args.workers <= 1:
        for key in groups:
            repo, commit = key
            specs_map[key] = process_repo_group_cpp(repo, commit, clone_dir, cache)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_key = {}
            for key in groups:
                repo, commit = key
                fut = executor.submit(
                    process_repo_group_cpp, repo, commit, clone_dir, cache
                )
                future_to_key[fut] = key
            for fut in as_completed(future_to_key):
                key = future_to_key[fut]
                try:
                    specs_map[key] = fut.result()
                except Exception:
                    log.exception("Worker error for cpp %s", key)
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
                "No cpp specs for %s@%s -- skipping %d instances",
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
            for field in REQUIRED_ENRICHMENT_FIELDS_CPP:
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
    log.info("C++ Summary:")
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
        log.info("Dry run -- no cpp output file written.")
    else:
        write_jsonl(output_instances, args.output)


if __name__ == "__main__":
    main()
