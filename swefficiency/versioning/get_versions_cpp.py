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

"""Version detection for C++ task instances.

Mirrors :mod:`swefficiency.versioning.get_versions` (Python) but consults
the ``NS_VERSION_CPP`` cache namespace and uses C++ regex bundles from
:mod:`swefficiency.versioning.constants_cpp`. Same dual mode (GitHub
``raw.githubusercontent.com`` for unfetched commits / local-fs for build
mode) and same retry/backoff semantics.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Iterable, Optional

import requests

from swefficiency.versioning.constants_cpp import (
    GENERIC_VERSION_PATTERNS_CPP,
    MAP_REPO_TO_VERSION_PATHS_CPP,
    MAP_REPO_TO_VERSION_PATTERNS_CPP,
    _FALLBACK_VERSION_PATHS_CPP,
)

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 30
_HTTP_MAX_RETRIES = 3
_HTTP_BACKOFF_BASE = 1.5


def _get_version_cache_safe():
    """Return cache or None if disabled / import fails. Matches Python pipeline."""
    if os.environ.get("SWEFF_DISABLE_CACHE"):
        return None
    try:
        from swefficiency.cache.sqlite_cache import get_default_cache  # local import
    except Exception:
        return None
    try:
        return get_default_cache()
    except Exception:
        return None


def _normalize_version(raw: str) -> Optional[str]:
    """Normalize a raw version match into a clean string (or None)."""
    if raw is None:
        return None
    v = raw.strip()
    if not v:
        return None
    if "(" in v:
        v = v.split("(", 1)[0].strip()
    cleaned = re.sub(r"[^0-9.]", "", v)
    cleaned = cleaned.strip(".")
    if not cleaned:
        return None
    parts = cleaned.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return cleaned


def _fetch_url_with_retry(url: str) -> Optional[str]:
    """GET ``url`` with bounded retry. 404 -> None; other errors -> retry then None."""
    last_error: Optional[BaseException] = None
    for attempt in range(_HTTP_MAX_RETRIES):
        try:
            response = requests.get(url, timeout=_HTTP_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            last_error = e
            time.sleep(_HTTP_BACKOFF_BASE ** attempt)
            continue

        status = response.status_code
        if status == 200:
            return response.text
        if status == 404:
            return None
        if 500 <= status < 600 or status in (429, 408):
            last_error = RuntimeError(f"HTTP {status} on {url}")
            time.sleep(_HTTP_BACKOFF_BASE ** attempt)
            continue
        return None
    logger.debug("fetch failed after retries: %s (%s)", url, last_error)
    return None


def _candidate_paths(repo: str) -> Iterable[str]:
    paths = list(MAP_REPO_TO_VERSION_PATHS_CPP.get(repo, []))
    for fallback in _FALLBACK_VERSION_PATHS_CPP:
        if fallback not in paths:
            paths.append(fallback)
    return paths


def _candidate_patterns(repo: str) -> Iterable[str]:
    return MAP_REPO_TO_VERSION_PATTERNS_CPP.get(repo, GENERIC_VERSION_PATTERNS_CPP)


def _find_version_in_text(text: str, patterns: Iterable[str]) -> Optional[str]:
    if not text:
        return None
    for pattern in patterns:
        try:
            match = re.search(pattern, text, re.MULTILINE)
        except re.error:
            continue
        if match:
            return _normalize_version(match.group(1))
    return None


def _read_local(path_repo: str, version_path: str) -> Optional[str]:
    target = os.path.join(path_repo, version_path)
    if not os.path.isfile(target):
        return None
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _read_github(repo: str, base_commit: str, version_path: str) -> Optional[str]:
    url = f"https://raw.githubusercontent.com/{repo}/{base_commit}/{version_path}"
    return _fetch_url_with_retry(url)


def _get_version_impl(
    instance: dict, is_build: bool = False, path_repo: Optional[str] = None
) -> Optional[str]:
    repo = instance["repo"]
    base_commit = instance["base_commit"]

    patterns = list(_candidate_patterns(repo))
    for version_path in _candidate_paths(repo):
        if is_build:
            if path_repo is None:
                continue
            text = _read_local(path_repo, version_path)
        else:
            text = _read_github(repo, base_commit, version_path)
        if not text:
            continue
        found = _find_version_in_text(text, patterns)
        if found:
            return found
    return None


def get_version(
    instance: dict, is_build: bool = False, path_repo: Optional[str] = None
) -> Optional[str]:
    """Cached, retry-bounded version lookup for a C++ task instance.

    Returns ``None`` on miss. Cache key is ``(repo, base_commit)`` under the
    ``NS_VERSION_CPP`` namespace so Python and C++ namespaces never collide.
    """
    repo = instance["repo"]
    base_commit = instance["base_commit"]

    cache = _get_version_cache_safe()
    cache_usable = (
        cache is not None
        and isinstance(repo, str)
        and bool(repo)
        and isinstance(base_commit, str)
        and bool(base_commit)
    )

    if cache_usable:
        try:
            from swefficiency.cache.sqlite_cache import NS_VERSION_CPP
            cached = cache.get(NS_VERSION_CPP, (repo, base_commit))
            if cached:
                return cached
        except Exception:
            logger.debug("cache read failed", exc_info=True)

    version = _get_version_impl(instance, is_build=is_build, path_repo=path_repo)

    if cache_usable and version:
        try:
            from swefficiency.cache.sqlite_cache import NS_VERSION_CPP
            cache.set(NS_VERSION_CPP, (repo, base_commit), version)
        except Exception:
            logger.debug("cache write failed", exc_info=True)

    return version


def map_version_to_task_instances_cpp(task_instances):
    """Group task instances by detected version. Same contract as Python."""
    grouped: dict[str, list] = {}
    for instance in task_instances:
        version = instance.get("version") or get_version(instance)
        if version is None:
            continue
        instance["version"] = version
        grouped.setdefault(version, []).append(instance)
    return grouped



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _process_instance(instance: dict, retrieval_method: str, path_repo: Optional[str]) -> dict:
    """Worker: detect version, attach to copy, return."""
    out = dict(instance)
    if out.get("version"):
        return out
    try:
        version = get_version(
            out,
            is_build=(retrieval_method == "build"),
            path_repo=path_repo,
        )
    except (KeyError, TypeError) as exc:
        logger.warning("skipping %s: %s", out.get("instance_id", "<unknown>"), exc)
        return out
    if version:
        out["version"] = version
    return out


def _load_instances(path: str) -> list:
    instances = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                instances.append(__import__("json").loads(line))
            except Exception as exc:
                logger.warning("skip invalid JSON at %s:%d (%s)", path, line_no, exc)
    return instances


def main(argv: Optional[list] = None) -> int:
    """CLI mirroring ``swefficiency.versioning.get_versions``."""
    import argparse
    import concurrent.futures
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Detect versions for C++ task instances")
    parser.add_argument("--instances_path", required=True, help="JSONL of task instances.")
    parser.add_argument(
        "--retrieval_method",
        choices=("github", "build"),
        default="github",
        help="github => fetch raw.githubusercontent.com; build => read path_repo on disk.",
    )
    parser.add_argument("--path_repo", default=None, help="Local repo path for retrieval_method=build.")
    parser.add_argument("--num_workers", type=int, default=4, help="Parallel worker threads.")
    parser.add_argument("--output_dir", required=True, help="Output dir (writes <stem>_versions.json).")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    instances = _load_instances(args.instances_path)
    if not instances:
        logger.error("no instances loaded from %s", args.instances_path)
        return 1
    logger.info("loaded %d instances", len(instances))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.instances_path).stem
    out_path = out_dir / f"{stem}_versions.json"

    enriched: list = []
    if args.num_workers <= 1:
        for inst in instances:
            enriched.append(_process_instance(inst, args.retrieval_method, args.path_repo))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
            futures = [
                pool.submit(_process_instance, inst, args.retrieval_method, args.path_repo)
                for inst in instances
            ]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    enriched.append(fut.result())
                except Exception:
                    logger.exception("worker raised; instance dropped")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2)

    versioned = sum(1 for x in enriched if x.get("version"))
    logger.info("wrote %d (versioned=%d) to %s", len(enriched), versioned, out_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())