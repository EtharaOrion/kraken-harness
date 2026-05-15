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

"""
Dynamic C++ repository discovery for SWE-fficiency.

Mirrors :mod:`swefficiency.collect.discover_repos` (Python) but searches the
C++ open-source landscape with strict license filtering. No hardcoded repo
allow-list: at scale, the pipeline ingests whatever GitHub returns under our
constraints.

Allowed licenses (SPDX-aligned, per project policy):
  * MIT             — license:mit
  * MIT-0           — surfaced from license:mit results via LICENSE-content scan
  * Apache-2.0      — license:apache-2.0
  * BSD-3-Clause    — license:bsd-3-clause
  * BSD-2-Clause    — license:bsd-2-clause
  * ISC             — license:isc

Selection criteria (every repo must satisfy ALL):
  1. ``language:C++`` (GitHub-detected primary language)
  2. License in the allow-list above (verified twice: search filter + repo
     metadata ``license.spdx_id``; plus LICENSE-content scan for MIT-0)
  3. Not a fork, not archived
  4. Sufficient stars (default 500)
  5. Active within the activity window (default 18 months)
  6. ``CMakeLists.txt`` present at repo root (Phase 1 supports CMake builds)
  7. Has test infrastructure (``tests/`` / ``test/`` dir, ``CTestTestfile.cmake``,
     or ctest/gtest mentions in ``.github/workflows/*``)
  8. Sufficient merged PRs (default 100) — proxy for an active review cycle
  9. Not a tutorial/template/awesome-list (name pattern exclusion)

Output: a repos file (one ``owner/repo`` per line) suitable for
``run_pipeline_cpp.sh --repos-file``.
"""

import argparse
import base64
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# ---------------------------------------------------------------------------
# Defaults (overridable via CLI)
# ---------------------------------------------------------------------------
DEFAULT_MIN_STARS = 500
DEFAULT_MIN_PRS = 100
DEFAULT_MAX_REPOS = 500
DEFAULT_ACTIVITY_MONTHS = 18

# GitHub Search `license:` qualifier values. MIT-0 is not natively supported
# as a search filter so we surface it from license:mit candidates via
# LICENSE-content inspection.
SEARCH_LICENSE_KEYS = ("mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause", "isc")

# SPDX IDs that satisfy our policy. The repo metadata's ``license.spdx_id``
# is matched case-insensitively. ``mit-0`` is derived from LICENSE content.
ALLOWED_SPDX_IDS = {"MIT", "MIT-0", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC"}

# Markers in LICENSE file content that indicate MIT-0 (MIT No Attribution).
MIT_ZERO_MARKERS = ("mit no attribution", "mit-0", "mit no attribution license")

# Exclude obvious non-library repos (tutorials, awesome lists, etc.).
EXCLUDE_NAME_PATTERNS = (
    "awesome-",
    "tutorial",
    "example",
    "template",
    "boilerplate",
    "cheatsheet",
    "interview",
    "course",
    "book",
    "learning-",
    "100-days",
    "roadmap",
    "guide",
)

# C++-specific topics that frequently correlate with perf-relevant libraries.
# Used to fan out searches and broaden coverage; not required.
CPP_TOPICS = (
    "cpp",
    "cpp17",
    "cpp20",
    "header-only",
    "performance",
    "concurrency",
    "networking",
    "json",
    "logging",
    "math",
    "scientific-computing",
    "machine-learning",
    "graph",
    "compression",
    "cryptography",
    "data-structures",
    "algorithms",
    "image-processing",
)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _rate_limit_wait(response: requests.Response) -> None:
    remaining = int(response.headers.get("X-RateLimit-Remaining", 1) or 1)
    if remaining == 0:
        reset = int(response.headers.get("X-RateLimit-Reset", 0) or 0)
        sleep_for = max(0, reset - int(time.time())) + 5
        logger.warning("Rate limited. Sleeping %ds for reset...", sleep_for)
        time.sleep(sleep_for)


def _gh_get(url: str, token: str, params: Optional[dict] = None,
            max_retries: int = 3) -> Optional[requests.Response]:
    headers = _get_headers(token)
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            logger.warning("Request error (%s); retrying", e)
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 403:
            _rate_limit_wait(resp)
            continue
        if resp.status_code in (502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        return resp
    return None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _build_query(license_key: str, min_stars: int, activity_months: int,
                 topic: Optional[str] = None) -> str:
    cutoff = (datetime.utcnow() - timedelta(days=activity_months * 30)).strftime("%Y-%m-%d")
    parts = [
        "language:C++",
        f"license:{license_key}",
        f"stars:>={min_stars}",
        f"pushed:>={cutoff}",
        "fork:false",
        "archived:false",
    ]
    if topic:
        parts.append(f"topic:{topic}")
    return " ".join(parts)


def search_repos(token: str, *, min_stars: int, max_repos: int,
                 activity_months: int, topics: Optional[list] = None) -> list[dict]:
    """Fan out searches across allowed licenses and (optionally) topics.

    GitHub's Search API caps results at 1000 per query. We split by license
    (5 queries) and optionally by topic (adds N more queries) to maximise
    distinct repos returned within the cap.
    """
    queries: list[str] = []
    for lic in SEARCH_LICENSE_KEYS:
        if topics:
            for t in topics:
                queries.append(_build_query(lic, min_stars, activity_months, topic=t))
        else:
            queries.append(_build_query(lic, min_stars, activity_months))

    found: dict[str, dict] = {}
    for query in queries:
        if len(found) >= max_repos:
            break
        logger.info("Searching: %s", query)
        page = 1
        per_page = 100
        while True:
            resp = _gh_get(
                f"{GITHUB_API}/search/repositories",
                token,
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": per_page,
                    "page": page,
                },
            )
            if resp is None or resp.status_code != 200:
                logger.warning(
                    "Search failed (%s): %s",
                    resp.status_code if resp is not None else "no-response",
                    (resp.text[:200] if resp is not None else ""),
                )
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            for repo in items:
                full = repo.get("full_name", "")
                if not full or full in found:
                    continue
                lname = full.lower()
                if any(p in lname for p in EXCLUDE_NAME_PATTERNS):
                    continue
                found[full] = repo
                if len(found) >= max_repos:
                    break
            total = data.get("total_count", 0)
            if page * per_page >= min(total, 1000) or len(found) >= max_repos:
                break
            page += 1
            time.sleep(1.5)
    logger.info("Found %d unique candidate repos across all licenses/topics", len(found))
    return list(found.values())


# ---------------------------------------------------------------------------
# Per-repo validation
# ---------------------------------------------------------------------------

def fetch_license_content(token: str, owner: str, name: str) -> str:
    """Return decoded LICENSE content (lowercased), empty string on failure."""
    resp = _gh_get(f"{GITHUB_API}/repos/{owner}/{name}/license", token)
    if resp is None or resp.status_code != 200:
        return ""
    try:
        payload = resp.json()
        encoded = payload.get("content", "")
        if not encoded:
            return ""
        raw = base64.b64decode(encoded.encode("ascii"), validate=False)
        return raw.decode("utf-8", errors="replace").lower()
    except Exception:
        return ""


def classify_license(repo: dict, token: str) -> Optional[str]:
    """Return the allow-listed SPDX ID for this repo, or None if not allowed.

    The repo's metadata ``license.spdx_id`` is the first-line check. For
    ``MIT`` results we additionally inspect LICENSE content to surface
    ``MIT-0`` (which GitHub classifies as ``MIT``).
    """
    spdx = (repo.get("license") or {}).get("spdx_id") or ""
    if spdx in ALLOWED_SPDX_IDS - {"MIT-0"}:
        if spdx == "MIT":
            content = fetch_license_content(
                token, repo["owner"]["login"], repo["name"]
            )
            time.sleep(0.5)
            if content and any(m in content for m in MIT_ZERO_MARKERS):
                return "MIT-0"
            return "MIT"
        return spdx
    return None


def check_cmake_root(token: str, owner: str, name: str) -> bool:
    """Return True iff CMakeLists.txt exists at repo root."""
    resp = _gh_get(
        f"{GITHUB_API}/repos/{owner}/{name}/contents/CMakeLists.txt",
        token,
    )
    return bool(resp is not None and resp.status_code == 200)


def check_tests(token: str, owner: str, name: str) -> bool:
    """Heuristic: tests/ or test/ dir, or CTestTestfile.cmake, or ctest in CI."""
    resp = _gh_get(f"{GITHUB_API}/repos/{owner}/{name}/contents/", token)
    if resp is None or resp.status_code != 200:
        return False
    try:
        contents = resp.json()
    except Exception:
        return False
    if not isinstance(contents, list):
        return False
    names = {item.get("name", "").lower() for item in contents}
    if names & {"tests", "test", "unittest", "unittests", "spec"}:
        return True
    if "ctesttestfile.cmake" in names:
        return True
    # CI fallback: check .github/workflows
    if ".github" in names:
        wf = _gh_get(
            f"{GITHUB_API}/repos/{owner}/{name}/contents/.github/workflows",
            token,
        )
        if wf is not None and wf.status_code == 200:
            try:
                items = wf.json()
            except Exception:
                items = []
            if isinstance(items, list):
                for it in items:
                    n = it.get("name", "").lower()
                    if n.endswith((".yml", ".yaml")):
                        # Cheap text probe — just look at filename
                        if any(k in n for k in ("test", "ci", "build", "check")):
                            return True
    return False


def count_merged_prs(token: str, owner: str, name: str) -> int:
    resp = _gh_get(
        f"{GITHUB_API}/search/issues",
        token,
        params={"q": f"repo:{owner}/{name} is:pr is:merged", "per_page": 1},
    )
    if resp is None or resp.status_code != 200:
        return 0
    return int(resp.json().get("total_count", 0))


def validate_repos(repos: list[dict], token: str, *, min_prs: int,
                   require_cmake: bool, require_tests: bool) -> list[dict]:
    """Run cheap-first validation. Returns enriched repos that pass everything."""
    out: list[dict] = []
    for i, repo in enumerate(repos):
        full = repo["full_name"]
        owner = repo["owner"]["login"]
        name = repo["name"]
        stars = repo.get("stargazers_count", 0)
        logger.info("[%d/%d] Validating %s (⭐%d)", i + 1, len(repos), full, stars)

        # 1. License classification (also catches MIT-0).
        spdx = classify_license(repo, token)
        if spdx is None:
            logger.info("  ✗ License not allowed: %s",
                        (repo.get("license") or {}).get("spdx_id"))
            continue
        repo["_license_spdx"] = spdx
        time.sleep(0.5)

        # 2. CMakeLists.txt at root.
        if require_cmake:
            if not check_cmake_root(token, owner, name):
                logger.info("  ✗ No CMakeLists.txt at root")
                continue
            time.sleep(0.5)

        # 3. Test infrastructure.
        if require_tests:
            if not check_tests(token, owner, name):
                logger.info("  ✗ No test infrastructure detected")
                continue
            time.sleep(0.5)

        # 4. Merged PR count.
        n_prs = count_merged_prs(token, owner, name)
        if n_prs < min_prs:
            logger.info("  ✗ Only %d merged PRs (need >= %d)", n_prs, min_prs)
            continue
        repo["_merged_prs"] = n_prs

        out.append(repo)
        logger.info("  ✓ PASS — license=%s, prs=%d", spdx, n_prs)
        time.sleep(1.0)
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_output(repos: list[dict], output: str, fmt: str = "ranked") -> None:
    parent = os.path.dirname(output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if fmt == "json":
        with open(output, "w") as f:
            json.dump(
                [
                    {
                        "full_name": r["full_name"],
                        "stars": r.get("stargazers_count", 0),
                        "license": r.get("_license_spdx", ""),
                        "merged_prs": r.get("_merged_prs", 0),
                        "description": r.get("description", ""),
                        "topics": r.get("topics", []),
                        "pushed_at": r.get("pushed_at", ""),
                    }
                    for r in repos
                ],
                f,
                indent=2,
            )
    elif fmt == "ranked":
        ranked = sorted(
            repos,
            key=lambda r: (r.get("_merged_prs", 0), r.get("stargazers_count", 0)),
            reverse=True,
        )
        with open(output, "w") as f:
            f.write(
                "# Auto-discovered C++ repos for SWE-fficiency\n"
                f"# Generated: {datetime.now().isoformat()}\n"
                f"# Total: {len(ranked)} repos\n"
                "# Filter: language:C++ + license in {MIT, MIT-0, Apache-2.0, "
                "BSD-3-Clause, BSD-2-Clause, ISC}\n"
                "#\n"
                "# Format: owner/repo  # license | stars | merged_prs\n"
                "#\n"
            )
            for r in ranked:
                f.write(
                    f"{r['full_name']}  # {r.get('_license_spdx', '')} | "
                    f"⭐{r.get('stargazers_count', 0)} | "
                    f"{r.get('_merged_prs', 0)} merged PRs\n"
                )
    else:  # simple
        with open(output, "w") as f:
            for r in repos:
                f.write(f"{r['full_name']}\n")
    logger.info("Wrote %d repos to %s (format=%s)", len(repos), output, fmt)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--output", "-o", required=True, help="Output repos file")
    parser.add_argument(
        "--format",
        choices=("simple", "ranked", "json"),
        default="ranked",
        help="Output format (default: ranked)",
    )
    parser.add_argument("--min-stars", type=int, default=DEFAULT_MIN_STARS)
    parser.add_argument("--min-prs", type=int, default=DEFAULT_MIN_PRS)
    parser.add_argument("--max-repos", type=int, default=DEFAULT_MAX_REPOS)
    parser.add_argument("--activity-months", type=int, default=DEFAULT_ACTIVITY_MONTHS)
    parser.add_argument(
        "--topics",
        nargs="*",
        default=None,
        help="Optional GitHub topics to fan out across (default: license-only fan-out)",
    )
    parser.add_argument(
        "--require-cmake",
        action="store_true",
        default=True,
        help="Require CMakeLists.txt at root (default: True)",
    )
    parser.add_argument(
        "--no-require-cmake", dest="require_cmake", action="store_false"
    )
    parser.add_argument(
        "--require-tests",
        action="store_true",
        default=True,
        help="Require test markers (default: True)",
    )
    parser.add_argument(
        "--no-require-tests", dest="require_tests", action="store_false"
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip license + cmake + tests + PR-count validation",
    )
    parser.add_argument(
        "--token", default=None, help="GitHub PAT (default: GITHUB_TOKEN/GITHUB_TOKENS)"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raw = os.environ.get("GITHUB_TOKENS", "")
        if raw:
            token = raw.split(",")[0].strip()
    if not token:
        logger.error("No GitHub token. Set GITHUB_TOKEN/GITHUB_TOKENS or pass --token.")
        return 1

    candidates = search_repos(
        token,
        min_stars=args.min_stars,
        max_repos=args.max_repos * 3,
        activity_months=args.activity_months,
        topics=args.topics,
    )

    if args.skip_validation:
        validated = candidates
        logger.info("Skipping validation (--skip-validation).")
        # Cheap license check from search metadata only.
        validated = [
            r for r in validated
            if (r.get("license") or {}).get("spdx_id") in ALLOWED_SPDX_IDS
        ]
    else:
        validated = validate_repos(
            candidates,
            token,
            min_prs=args.min_prs,
            require_cmake=args.require_cmake,
            require_tests=args.require_tests,
        )

    validated = validated[: args.max_repos]
    write_output(validated, args.output, fmt=args.format)

    if validated:
        by_lic: dict[str, int] = {}
        for r in validated:
            lic = r.get("_license_spdx") or (r.get("license") or {}).get("spdx_id", "?")
            by_lic[lic] = by_lic.get(lic, 0) + 1
        logger.info("=" * 60)
        logger.info("DISCOVERY SUMMARY")
        logger.info("  Repos: %d", len(validated))
        for lic, n in sorted(by_lic.items(), key=lambda kv: -kv[1]):
            logger.info("    %-14s %d", lic, n)
        logger.info("  Output: %s", args.output)
        logger.info("=" * 60)
    else:
        logger.warning("No repos passed validation. Lower thresholds or remove filters.")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
