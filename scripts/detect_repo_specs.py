#!/usr/bin/env python3
"""Auto-detect repo specs for SWE-fficiency dataset.

Clones repos, checks out base commits, and auto-detects Python version,
install commands, test commands, dependencies, and other build specs.
Enriches dataset instances with the detected fields.

Usage:
    python scripts/detect_repo_specs.py --input data.jsonl --output enriched.jsonl
    python scripts/detect_repo_specs.py --input data.jsonl --output enriched.jsonl --workers 4
    python scripts/detect_repo_specs.py --input data.jsonl --dry-run
    python scripts/detect_repo_specs.py --validate --input enriched.jsonl --output /dev/null
"""

from __future__ import annotations

import argparse
import configparser
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from swefficiency.cache.sqlite_cache import (
    NS_REPO_SPECS,
    SqliteKVCache,
    get_default_cache,
)

# TOML parsing: prefer stdlib tomllib (3.11+), fallback to tomli, then regex
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

log = logging.getLogger("detect_repo_specs")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str | None:
    """Read a file as text, returning None if it doesn't exist or fails."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


def _parse_toml(path: Path) -> dict[str, Any] | None:
    """Parse a TOML file. Returns None on failure or missing tomllib."""
    if tomllib is None:
        return _parse_toml_regex(path)
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return tomllib.loads(raw)
    except Exception:
        return None


def _parse_toml_regex(path: Path) -> dict[str, Any] | None:
    """Minimal regex-based TOML extraction when tomllib is unavailable.

    Only extracts a small subset of keys we actually need.
    Returns a nested dict mimicking real TOML parse output.
    """
    raw = _read_text(path)
    if raw is None:
        return None
    result: dict[str, Any] = {}

    # requires-python
    m = re.search(r'requires-python\s*=\s*"([^"]*)"', raw)
    if m:
        result.setdefault("project", {})["requires-python"] = m.group(1)

    # version
    m = re.search(r'^\s*version\s*=\s*"([^"]*)"', raw, re.MULTILINE)
    if m:
        result.setdefault("project", {})["version"] = m.group(1)

    # build-system requires
    m = re.search(r'\[build-system\][^\[]*requires\s*=\s*\[([^\]]*)\]', raw, re.DOTALL)
    if m:
        reqs = re.findall(r'"([^"]*)"', m.group(1))
        result.setdefault("build-system", {})["requires"] = reqs

    # tool.pytest.ini_options
    if re.search(r'\[tool\.pytest\.ini_options\]', raw):
        result.setdefault("tool", {}).setdefault("pytest", {})["ini_options"] = {}

    # project.dependencies
    m = re.search(r'\[project\][^\[]*dependencies\s*=\s*\[([^\]]*)\]', raw, re.DOTALL)
    if m:
        deps = re.findall(r'"([^"]*)"', m.group(1))
        result.setdefault("project", {})["dependencies"] = deps

    # project.license
    m = re.search(r'\[project\][^\[]*license\s*=\s*\{[^}]*text\s*=\s*"([^"]*)"', raw, re.DOTALL)
    if m:
        result.setdefault("project", {}).setdefault("license", {})["text"] = m.group(1)

    return result if result else None


def _parse_min_python(spec: str) -> str:
    """Extract minimum Python version from a specifier like '>=3.8,<3.12'."""
    m = re.search(r'>=?\s*(\d+\.\d+)', spec)
    if m:
        return m.group(1)
    # Handle ==
    m = re.search(r'==\s*(\d+\.\d+)', spec)
    if m:
        return m.group(1)
    return "3.10"


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
        # Shallow clone may not include the commit; unshallow and retry
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
# Detection Functions
# ---------------------------------------------------------------------------

def detect_python_version(repo_dir: Path) -> str:
    """Detect minimum Python version for the repo.

    Priority: .python-version → pyproject.toml → setup.py → setup.cfg → tox.ini → fallback
    """
    # 1. .python-version
    pv = _read_text(repo_dir / ".python-version")
    if pv:
        first = pv.strip().splitlines()[0].strip()
        m = re.match(r'(\d+\.\d+)', first)
        if m:
            return m.group(1)

    # 2. pyproject.toml requires-python
    toml = _parse_toml(repo_dir / "pyproject.toml")
    if toml:
        rp = (toml.get("project") or {}).get("requires-python")
        if rp:
            return _parse_min_python(rp)

    # 3. setup.py python_requires
    setup_py = _read_text(repo_dir / "setup.py")
    if setup_py:
        m = re.search(r'python_requires\s*=\s*["\']([^"\']+)["\']', setup_py)
        if m:
            return _parse_min_python(m.group(1))

    # 4. setup.cfg python_requires
    cfg = _read_text(repo_dir / "setup.cfg")
    if cfg:
        cp = configparser.ConfigParser()
        try:
            cp.read_string(cfg)
            rp = cp.get("options", "python_requires", fallback=None)
            if rp:
                return _parse_min_python(rp)
        except configparser.Error:
            pass

    # 5. tox.ini envlist
    tox = _read_text(repo_dir / "tox.ini")
    if tox:
        m = re.search(r'envlist\s*=\s*(.+)', tox)
        if m:
            pyvers = re.findall(r'py(\d)(\d+)', m.group(1))
            if pyvers:
                versions = sorted({f"{major}.{minor}" for major, minor in pyvers})
                if versions:
                    return versions[0]

    # 6. Fallback
    return "3.10"


def detect_install_cmd(repo_dir: Path) -> str:
    """Detect installation command for the repo.

    Priority: pyproject.toml build-system → setup.py → setup.cfg → fallback
    """
    toml = _parse_toml(repo_dir / "pyproject.toml")
    if toml:
        bs = toml.get("build-system") or {}
        requires = bs.get("requires") or []
        requires_lower = " ".join(r.lower() for r in requires)

        # C-extension build systems need --no-build-isolation
        if any(kw in requires_lower for kw in ("meson-python", "mesonpy", "scikit-build")):
            return "pip install --no-build-isolation -e ."

        # Standard build backends
        if any(kw in requires_lower for kw in (
            "setuptools", "flit-core", "flit_core", "hatchling",
            "poetry-core", "poetry_core", "pdm-backend", "pdm-pep517",
        )):
            return "pip install -e ."

        # Has build-system but unknown backend — still try editable install
        if requires:
            return "pip install -e ."

    # setup.py
    if (repo_dir / "setup.py").exists():
        return "pip install -e ."

    # setup.cfg with metadata
    cfg = _read_text(repo_dir / "setup.cfg")
    if cfg:
        cp = configparser.ConfigParser()
        try:
            cp.read_string(cfg)
            if cp.has_section("metadata"):
                return "pip install -e ."
        except configparser.Error:
            pass

    return "pip install -e ."


def detect_test_cmd(repo_dir: Path) -> str:
    """Detect test command for the repo.

    Priority: pyproject.toml pytest config → setup.cfg pytest → tox.ini → test dirs → fallback
    """
    # 1. pyproject.toml tool.pytest.ini_options
    toml = _parse_toml(repo_dir / "pyproject.toml")
    if toml:
        tool = toml.get("tool") or {}
        if "pytest" in tool and "ini_options" in tool["pytest"]:
            return "pytest {test_files}"

    # 2. setup.cfg [tool:pytest]
    cfg = _read_text(repo_dir / "setup.cfg")
    if cfg:
        cp = configparser.ConfigParser()
        try:
            cp.read_string(cfg)
            if cp.has_section("tool:pytest"):
                return "pytest {test_files}"
        except configparser.Error:
            pass

    # 3. tox.ini test command
    tox = _read_text(repo_dir / "tox.ini")
    if tox:
        # Look for [testenv] commands
        m = re.search(r'\[testenv\]\s*\n(?:.*\n)*?commands\s*=\s*(.+)', tox)
        if m:
            cmd_line = m.group(1).strip()
            # Extract the first meaningful command
            if "pytest" in cmd_line:
                return "pytest {test_files}"
            # Return it cleaned up if it looks like a real command
            first_cmd = cmd_line.split("\n")[0].strip()
            if first_cmd and not first_cmd.startswith("{"):
                # Replace tox substitutions
                first_cmd = re.sub(r'\{[^}]*\}', '', first_cmd).strip()
                if first_cmd:
                    return first_cmd

    # 4. Check for test directories
    if (repo_dir / "tests").is_dir():
        return "pytest tests/"
    if (repo_dir / "test").is_dir():
        return "pytest test/"

    # 5. Fallback
    return "pytest {test_files}"


def detect_packages_source(repo_dir: Path) -> tuple[str, list[str], list[str]]:
    """Detect where dependencies come from.

    Returns: (source_type, reqs_paths, pip_packages)
    """
    # environment.yml / environment.yaml
    for name in ("environment.yml", "environment.yaml"):
        if (repo_dir / name).exists():
            return (name, [], [])

    # requirements.txt
    if (repo_dir / "requirements.txt").exists():
        return ("requirements.txt", ["requirements.txt"], [])

    # requirements/ directory
    reqs_dir = repo_dir / "requirements"
    if reqs_dir.is_dir():
        txt_files = sorted(str(p.relative_to(repo_dir)) for p in reqs_dir.glob("*.txt"))
        if txt_files:
            return ("requirements.txt", txt_files, [])

    # pyproject.toml project.dependencies
    toml = _parse_toml(repo_dir / "pyproject.toml")
    if toml:
        deps = (toml.get("project") or {}).get("dependencies")
        if deps and isinstance(deps, list):
            return ("", [], list(deps))

    return ("", [], [])


def detect_pre_install(repo_dir: Path) -> list[str]:
    """Detect system-level pre-install commands.

    Checks for C extensions, Meson, Fortran, BLAS/LAPACK usage.
    """
    cmds: list[str] = []
    needs_build_essential = False

    # Check setup.py for C extensions
    setup_py = _read_text(repo_dir / "setup.py")
    if setup_py:
        if any(kw in setup_py for kw in ("ext_modules", "Extension(", "cythonize")):
            needs_build_essential = True

    # Check for meson.build
    if (repo_dir / "meson.build").exists():
        cmds.append("apt-get install -y meson ninja-build")
        needs_build_essential = True

    # Check for Fortran files
    fortran_exts = (".f90", ".f", ".f77", ".for")
    has_fortran = False
    for ext in fortran_exts:
        # Quick scan: check top-level and one level deep
        if list(repo_dir.glob(f"*{ext}")) or list(repo_dir.glob(f"*/*{ext}")):
            has_fortran = True
            break
    if has_fortran:
        cmds.append("apt-get install -y gfortran")
        needs_build_essential = True

    # Check for BLAS/LAPACK usage (in setup.py or pyproject.toml)
    check_files = [setup_py or ""]
    pyproject_raw = _read_text(repo_dir / "pyproject.toml") or ""
    check_files.append(pyproject_raw)
    combined = "\n".join(check_files).lower()
    if any(kw in combined for kw in ("blas", "lapack", "openblas")):
        cmds.append("apt-get install -y libopenblas-dev")
        needs_build_essential = True

    if needs_build_essential:
        cmds.insert(0, "apt-get install -y build-essential")

    return cmds


def detect_version(repo_dir: Path, repo_name: str) -> str | None:
    """Detect the package version.

    Priority: pyproject.toml → setup.py → setup.cfg → __init__.py patterns → None
    """
    # 1. pyproject.toml version
    toml = _parse_toml(repo_dir / "pyproject.toml")
    if toml:
        ver = (toml.get("project") or {}).get("version")
        if ver and isinstance(ver, str):
            return ver

    # 2. setup.py version=
    setup_py = _read_text(repo_dir / "setup.py")
    if setup_py:
        m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', setup_py)
        if m:
            return m.group(1)

    # 3. setup.cfg version
    cfg = _read_text(repo_dir / "setup.cfg")
    if cfg:
        cp = configparser.ConfigParser()
        try:
            cp.read_string(cfg)
            ver = cp.get("metadata", "version", fallback=None)
            if ver and not ver.startswith("attr:") and not ver.startswith("file:"):
                return ver
        except configparser.Error:
            pass

    # 4. Common __version__ patterns in source code
    # Derive package name from repo name: "owner/repo-name" → "repo_name"
    pkg_name = repo_name.split("/")[-1].replace("-", "_").lower()
    # Also try without underscores
    candidates = [pkg_name]
    if "_" in pkg_name:
        candidates.append(pkg_name.replace("_", ""))

    version_files = [
        "{pkg}/__init__.py",
        "{pkg}/version.py",
        "{pkg}/_version.py",
        "src/{pkg}/__init__.py",
        "src/{pkg}/version.py",
        "src/{pkg}/_version.py",
    ]

    for pkg in candidates:
        for pattern in version_files:
            fpath = repo_dir / pattern.format(pkg=pkg)
            content = _read_text(fpath)
            if content:
                m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
                if m:
                    return m.group(1)

    # 5. Try VERSION file
    for vf in ("VERSION", "version.txt"):
        content = _read_text(repo_dir / vf)
        if content:
            ver = content.strip().splitlines()[0].strip()
            if re.match(r'\d+\.\d+', ver):
                return ver

    return None


_LICENSE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("MIT", re.compile(r'\bMIT License\b|Permission is hereby granted.*MIT', re.IGNORECASE | re.DOTALL)),
    ("MIT-0", re.compile(r'\bMIT-0\b|MIT No Attribution', re.IGNORECASE)),
    ("Apache-2.0", re.compile(r'Apache License.*Version 2\.0|Licensed under the Apache License', re.IGNORECASE | re.DOTALL)),
    ("BSD-3-Clause", re.compile(r'BSD 3-Clause|Redistribution and use.*three conditions', re.IGNORECASE | re.DOTALL)),
    ("BSD-2-Clause", re.compile(r'BSD 2-Clause|Simplified BSD', re.IGNORECASE)),
    ("ISC", re.compile(r'\bISC License\b|ISC license', re.IGNORECASE)),
]


def check_license(repo_dir: Path) -> str | None:
    """Check the license of a repo.

    Checks LICENSE files and pyproject.toml classifiers. Returns license name or None.
    """
    # Check license files
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md",
                 "LICENCE.txt", "COPYING", "COPYING.md"):
        content = _read_text(repo_dir / name)
        if content:
            for lic_name, pat in _LICENSE_PATTERNS:
                if pat.search(content):
                    return lic_name

    # Check pyproject.toml
    toml = _parse_toml(repo_dir / "pyproject.toml")
    if toml:
        project = toml.get("project") or {}

        # license field
        lic = project.get("license")
        if isinstance(lic, dict):
            lic_text = lic.get("text", "") or lic.get("expression", "")
        elif isinstance(lic, str):
            lic_text = lic
        else:
            lic_text = ""
        if lic_text:
            lic_upper = lic_text.upper()
            for lic_name, _ in _LICENSE_PATTERNS:
                if lic_name.upper() in lic_upper:
                    return lic_name

        # classifiers
        classifiers = project.get("classifiers") or []
        for cls in classifiers:
            if "License" not in cls:
                continue
            cls_lower = cls.lower()
            if "mit" in cls_lower and "mit-0" not in cls_lower:
                return "MIT"
            if "mit-0" in cls_lower or "no attribution" in cls_lower:
                return "MIT-0"
            if "apache" in cls_lower and "2.0" in cls_lower:
                return "Apache-2.0"
            if "bsd" in cls_lower:
                if "3" in cls_lower:
                    return "BSD-3-Clause"
                if "2" in cls_lower:
                    return "BSD-2-Clause"
            if "isc" in cls_lower:
                return "ISC"

    return None


def _detect_log_parser_type(test_cmd: str) -> str:
    """Infer the log parser type from the test command."""
    if "runtests.py" in test_cmd:
        return "django"
    if "bin/test" in test_cmd:
        return "sympy"
    return "pytest"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def detect_all_specs(repo_dir: Path, repo: str) -> dict[str, Any]:
    """Run all detection functions on a repo checkout. Returns enrichment dict."""
    python_version = detect_python_version(repo_dir)
    install_cmd = detect_install_cmd(repo_dir)
    test_cmd = detect_test_cmd(repo_dir)
    source_type, reqs_paths, pip_packages = detect_packages_source(repo_dir)
    pre_install = detect_pre_install(repo_dir)
    version = detect_version(repo_dir, repo)
    license_name = check_license(repo_dir)
    log_parser = _detect_log_parser_type(test_cmd)

    env_yml_paths: list[str] = []
    if source_type in ("environment.yml", "environment.yaml"):
        env_yml_paths = [source_type]

    return {
        "python_version": python_version,
        "install_cmd": install_cmd,
        "test_cmd_override": test_cmd,
        "packages_source": source_type,
        "pip_packages": pip_packages,
        "pre_install_cmds": pre_install,
        "reqs_paths": reqs_paths,
        "env_yml_paths": env_yml_paths,
        "log_parser_type": log_parser,
        "version": version,
        "_license": license_name,
    }


def process_repo_group(
    repo: str,
    base_commit: str,
    clone_dir: Path,
    cache: SqliteKVCache,
) -> dict[str, Any] | None:
    """Clone repo, checkout commit, detect specs. Returns specs dict or None on failure."""
    cache_key = (repo, base_commit)
    cached_specs = cache.get(NS_REPO_SPECS, cache_key)
    if cached_specs is not None:
        log.info("Cache hit for %s@%s", repo, base_commit[:8])
        return cached_specs

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

        specs = detect_all_specs(dest, repo)
        cache.set(NS_REPO_SPECS, cache_key, specs)
        log.info("Detected specs for %s: python=%s install=%s", cache_key,
                 specs["python_version"], specs["install_cmd"])
        return specs

    except Exception:
        log.exception("Unexpected error processing %s", cache_key)
        return None
    finally:
        # Clean up clone to save disk space
        if cloned and dest.exists():
            try:
                shutil.rmtree(dest)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_instances(input_path: str, split: str = "test") -> list[dict[str, Any]]:
    """Load instances from JSONL file or HuggingFace dataset."""
    path = Path(input_path)
    if path.exists() and path.suffix in (".jsonl", ".json"):
        return _load_jsonl(path)
    # Try HuggingFace datasets
    return _load_hf(input_path, split)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load instances from a JSONL file."""
    instances = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                instances.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning("Skipping invalid JSON at line %d: %s", line_no, exc)
    log.info("Loaded %d instances from %s", len(instances), path)
    return instances


def _load_hf(dataset_name: str, split: str) -> list[dict[str, Any]]:
    """Load instances from a HuggingFace dataset."""
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError:
        log.error("Cannot load HF dataset '%s': `datasets` package not installed. "
                  "Install with: pip install datasets", dataset_name)
        sys.exit(1)

    ds = load_dataset(dataset_name, split=split)
    instances = [dict(row) for row in ds]  # type: ignore[arg-type]
    log.info("Loaded %d instances from HF dataset '%s' (split=%s)", len(instances), dataset_name, split)
    return instances


def write_jsonl(instances: list[dict[str, Any]], output_path: str) -> None:
    """Write instances to a JSONL file."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for inst in instances:
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")
    log.info("Wrote %d instances to %s", len(instances), out)



# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_ENRICHMENT_FIELDS = (
    "python_version", "install_cmd", "test_cmd_override", "packages_source",
    "pip_packages", "pre_install_cmds", "reqs_paths", "env_yml_paths",
    "log_parser_type",
)


def validate_instances(instances: list[dict[str, Any]]) -> bool:
    """Validate that all instances have the required enrichment fields."""
    missing_count = 0
    for inst in instances:
        iid = inst.get("instance_id", "<unknown>")
        missing = [f for f in REQUIRED_ENRICHMENT_FIELDS if f not in inst]
        if missing:
            log.warning("Instance %s missing fields: %s", iid, ", ".join(missing))
            missing_count += 1
    if missing_count:
        log.error("%d / %d instances have missing fields", missing_count, len(instances))
        return False
    log.info("All %d instances have required enrichment fields", len(instances))
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-detect repo specs for SWE-fficiency dataset",
    )
    parser.add_argument("--input", required=True, help="Input JSONL file or HF dataset name")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    parser.add_argument("--clone-dir", default="/tmp/repo_clones",
                        help="Directory for cloning repos")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel workers for cloning/detection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print detections without writing")
    parser.add_argument("--validate", action="store_true",
                        help="Validate existing JSONL has required fields")
    parser.add_argument("--license-filter", nargs="*",
                        default=["MIT", "MIT-0", "Apache-2.0", "BSD-3-Clause",
                                 "BSD-2-Clause", "ISC"],
                        help="Allowed licenses (empty = no filter)")
    parser.add_argument("--split", default="test",
                        help="HF dataset split (if using HF dataset)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load instances
    instances = load_instances(args.input, split=args.split)
    if not instances:
        log.error("No instances loaded. Exiting.")
        sys.exit(1)

    # Validate mode
    if args.validate:
        ok = validate_instances(instances)
        sys.exit(0 if ok else 1)

    # Load cache
    cache = get_default_cache()

    # Group instances by (repo, base_commit)
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, inst in enumerate(instances):
        repo = inst.get("repo", "")
        commit = inst.get("base_commit", "")
        if not repo or not commit:
            log.warning("Instance %d missing repo or base_commit, skipping",
                        idx)
            continue
        groups[(repo, commit)].append(idx)

    log.info("Processing %d unique (repo, base_commit) groups for %d instances",
             len(groups), len(instances))

    clone_dir = Path(args.clone_dir)
    clone_dir.mkdir(parents=True, exist_ok=True)

    # Process groups
    specs_map: dict[tuple[str, str], dict[str, Any] | None] = {}

    if args.workers <= 1:
        for key in groups:
            repo, commit = key
            specs_map[key] = process_repo_group(repo, commit, clone_dir, cache)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_key = {}
            for key in groups:
                repo, commit = key
                fut = executor.submit(process_repo_group, repo, commit, clone_dir, cache)
                future_to_key[fut] = key
            for fut in as_completed(future_to_key):
                key = future_to_key[fut]
                try:
                    specs_map[key] = fut.result()
                except Exception:
                    log.exception("Worker error for %s", key)
                    specs_map[key] = None


    # Apply specs to instances and collect stats
    enriched = 0
    skipped_license = 0
    skipped_failure = 0
    license_filter = set(args.license_filter) if args.license_filter else set()

    output_instances: list[dict[str, Any]] = []

    for (repo, commit), idxs in groups.items():
        specs = specs_map.get((repo, commit))
        if specs is None:
            skipped_failure += len(idxs)
            log.warning("No specs for %s@%s — skipping %d instances", repo, commit[:8], len(idxs))
            continue

        # License filter
        if license_filter and specs.get("_license") not in license_filter:
            skipped_license += len(idxs)
            log.info("License '%s' for %s not in filter — skipping %d instances",
                     specs.get("_license"), repo, len(idxs))
            continue

        for idx in idxs:
            inst = dict(instances[idx])  # copy
            # Apply enrichment fields
            for field in REQUIRED_ENRICHMENT_FIELDS:
                inst[field] = specs[field]
            # version: only set if detected and not already present
            if specs.get("version") and not inst.get("version"):
                inst["version"] = specs["version"]
            output_instances.append(inst)
            enriched += 1

    # Also add instances that had no (repo, commit) grouping
    all_grouped_idxs = set()
    for idxs in groups.values():
        all_grouped_idxs.update(idxs)
    for idx, inst in enumerate(instances):
        if idx not in all_grouped_idxs:
            output_instances.append(inst)

    # Summary
    log.info("=" * 60)
    log.info("Summary:")
    log.info("  Total instances:    %d", len(instances))
    log.info("  Unique repos:       %d", len(groups))
    log.info("  Enriched:           %d", enriched)
    log.info("  Skipped (license):  %d", skipped_license)
    log.info("  Skipped (failure):  %d", skipped_failure)
    log.info("=" * 60)

    if args.dry_run:
        # Print detections to stdout
        for key, specs in specs_map.items():
            if specs is not None:
                repo, commit = key
                print(f"\n--- {repo} @ {commit[:8]} ---")
                for k, v in specs.items():
                    if k != "_license":
                        print(f"  {k}: {v}")
                    else:
                        print(f"  license: {v}")
        log.info("Dry run — no output file written.")
    else:
        write_jsonl(output_instances, args.output)


if __name__ == "__main__":
    main()
