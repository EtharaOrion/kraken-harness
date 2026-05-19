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

"""Version detection for TypeScript task instances.

The canonical source is ``package.json`` parsed via ``json.load``. When
the manifest is missing or its ``version`` field is empty we fall back to
the latest matching git tag using :data:`FALLBACK_GIT_TAG_PATTERNS_TS` --
same semver heuristic shape as the language-neutral tag fallback. Cache
writes go under :data:`NS_VERSION_TS` so the python/ts namespaces never
collide.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Iterable, Optional

import requests

from swefficiency.versioning.constants_ts import (
    FALLBACK_GIT_TAG_PATTERNS_TS,
    GENERIC_VERSION_PATTERNS_TS,
    MAP_REPO_TO_VERSION_PATHS_TS,
    MAP_REPO_TO_VERSION_PATTERNS_TS,
    PACKAGE_JSON_VERSION_KEY,
    _FALLBACK_VERSION_PATHS_TS,
)

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 30
_HTTP_MAX_RETRIES = 3
_HTTP_BACKOFF_BASE = 1.5
_GIT_TIMEOUT_SECONDS = 30


def _get_version_cache_safe():
    if os.environ.get("SWEFF_DISABLE_CACHE"):
        return None
    try:
        from swefficiency.cache.sqlite_cache_ts import get_default_cache_ts
    except Exception:
        return None
    try:
        return get_default_cache_ts()
    except Exception:
        return None


def _normalize_version_ts(raw: Optional[str]) -> Optional[str]:
    # Preserve full semver (cpp truncates to major.minor; ts collect/ keys on x.y.z).
    if raw is None:
        return None
    v = raw.strip()
    if not v:
        return None
    if v[0] in ("v", "V"):
        v = v[1:].strip()
    return v or None


def _fetch_url_with_retry(url: str) -> Optional[str]:
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
    paths = list(MAP_REPO_TO_VERSION_PATHS_TS.get(repo, []))
    for fallback in _FALLBACK_VERSION_PATHS_TS:
        if fallback not in paths:
            paths.append(fallback)
    return paths


def _candidate_patterns(repo: str) -> Iterable[str]:
    return MAP_REPO_TO_VERSION_PATTERNS_TS.get(repo, GENERIC_VERSION_PATTERNS_TS)


def _extract_version_from_package_json_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get(PACKAGE_JSON_VERSION_KEY)
    if isinstance(v, str):
        return _normalize_version_ts(v)
    return None


def _find_version_in_text(text: str, patterns: Iterable[str]) -> Optional[str]:
    if not text:
        return None
    for pattern in patterns:
        try:
            match = re.search(pattern, text, re.MULTILINE)
        except re.error:
            continue
        if match:
            return _normalize_version_ts(match.group(1))
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


def _git_tag_fallback(path_repo: Optional[str]) -> Optional[str]:
    if not path_repo or not os.path.isdir(path_repo):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", path_repo, "tag", "--sort=-v:refname"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for tag in result.stdout.splitlines():
        tag = tag.strip()
        if not tag:
            continue
        for pattern in FALLBACK_GIT_TAG_PATTERNS_TS:
            try:
                m = re.search(pattern, tag)
            except re.error:
                continue
            if m:
                return _normalize_version_ts(m.group(1))
    return None


def get_version_for_repo_ts(path_repo: Optional[str]) -> Optional[str]:
    """Detect version for a local TypeScript repo.

    Primary: parse ``package.json`` (``json.load``) and read the
    :data:`PACKAGE_JSON_VERSION_KEY` field. Fallback: latest matching git
    tag via :data:`FALLBACK_GIT_TAG_PATTERNS_TS`. Returns ``None`` on miss.
    """
    if not path_repo:
        return None
    text = _read_local(path_repo, "package.json")
    if text is not None:
        v = _extract_version_from_package_json_text(text)
        if v:
            return v
    return _git_tag_fallback(path_repo)


def _get_version_impl(
    instance: dict, is_build: bool = False, path_repo: Optional[str] = None
) -> Optional[str]:
    repo = instance["repo"]
    base_commit = instance["base_commit"]

    if is_build:
        v = get_version_for_repo_ts(path_repo)
        if v:
            return v
        if path_repo is None:
            return None
        patterns = list(_candidate_patterns(repo))
        for version_path in _candidate_paths(repo):
            if version_path == "package.json":
                continue
            text = _read_local(path_repo, version_path)
            if not text:
                continue
            found = _find_version_in_text(text, patterns)
            if found:
                return found
        return None

    pkg_text = _read_github(repo, base_commit, "package.json")
    if pkg_text:
        v = _extract_version_from_package_json_text(pkg_text)
        if v:
            return v

    patterns = list(_candidate_patterns(repo))
    for version_path in _candidate_paths(repo):
        if version_path == "package.json":
            continue
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
    """Cached, retry-bounded version lookup for a TypeScript task instance.

    Returns ``None`` on miss. Cache key is ``(repo, base_commit)`` under the
    ``NS_VERSION_TS`` namespace so python/cpp/ts namespaces never collide.
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

    if cache_usable and cache is not None:
        try:
            from swefficiency.cache.sqlite_cache_ts import NS_VERSION_TS
            cached = cache.get(NS_VERSION_TS, (repo, base_commit))
            if cached:
                return cached
        except Exception:
            logger.debug("cache read failed", exc_info=True)

    version = _get_version_impl(instance, is_build=is_build, path_repo=path_repo)

    if cache_usable and cache is not None and version:
        try:
            from swefficiency.cache.sqlite_cache_ts import NS_VERSION_TS
            cache.set(NS_VERSION_TS, (repo, base_commit), version)
        except Exception:
            logger.debug("cache write failed", exc_info=True)

    return version


def map_version_to_task_instances_ts(task_instances):
    """Group task instances by detected version. Same contract as cpp/python."""
    grouped: dict[str, list] = {}
    for instance in task_instances:
        version = instance.get("version") or get_version(instance)
        if version is None:
            continue
        instance["version"] = version
        grouped.setdefault(version, []).append(instance)
    return grouped


def _process_instance(instance: dict, retrieval_method: str, path_repo: Optional[str]) -> dict:
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
                instances.append(json.loads(line))
            except Exception as exc:
                logger.warning("skip invalid JSON at %s:%d (%s)", path, line_no, exc)
    return instances


def main(argv: Optional[list] = None) -> int:
    import argparse
    import concurrent.futures
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Detect versions for TypeScript task instances")
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
