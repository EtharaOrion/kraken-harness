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
Dynamic TypeScript repository discovery for SWE-fficiency.

Mirrors :mod:`swefficiency.collect.discover_repos` (Python) but searches the
TypeScript open-source landscape with strict license filtering. No hardcoded
repo allow-list: at scale, the pipeline ingests whatever GitHub returns under
our constraints.

Allowed licenses (SPDX-aligned, per project policy):
  * MIT             — license:mit
  * MIT-0           — surfaced from license:mit results via LICENSE-content scan
  * Apache-2.0      — license:apache-2.0
  * BSD-3-Clause    — license:bsd-3-clause
  * BSD-2-Clause    — license:bsd-2-clause
  * ISC             — license:isc

Selection criteria (every repo must satisfy ALL):
  1. ``language:TypeScript`` (GitHub-detected primary language)
  2. License in the allow-list above (verified twice: search filter + repo
     metadata ``license.spdx_id``; plus LICENSE-content scan for MIT-0)
  3. Not a fork, not archived
  4. Sufficient stars (default 500)
  5. Active within the activity window (default 18 months)
  6. ``package.json`` AND ``tsconfig.json`` present at repo root
     (Phase 1 supports TypeScript projects with both manifests)
  7. Has test infrastructure (``tests/`` / ``test/`` dir, ``vitest.config.ts``,
     or vitest/test mentions in ``.github/workflows/*``)
  8. Sufficient merged PRs (default 100) — proxy for an active review cycle
  9. Not a tutorial/template/awesome-list (name pattern exclusion)

Output: a repos file (one ``owner/repo`` per line) suitable for
``run_pipeline_ts.sh --repos-file``.
"""

import argparse
import base64
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# TypeScript-specific topics that frequently correlate with perf-relevant
# libraries. Used to fan out searches and broaden coverage; not required.
TS_TOPICS = (
    "typescript",
    "nodejs",
    "javascript",
    "library",
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
# Token rotation (multi-PAT round-robin for throughput at scale)
# ---------------------------------------------------------------------------

class _TokenRotator:
    """Thread-safe round-robin over a list of GitHub PATs.

    GitHub rate limits are per-token (5000/hr core, 30/min secondary on
    ``/search/issues``), so N tokens deliver roughly N x discovery throughput.
    The single-token path is a no-op rotator wrapping ``[token]``.
    """

    def __init__(self, tokens: list[str]) -> None:
        if not tokens:
            raise ValueError("at least one GitHub token required")
        self._tokens = list(tokens)
        self._idx = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        with self._lock:
            tok = self._tokens[self._idx % len(self._tokens)]
            self._idx += 1
            return tok

    @property
    def size(self) -> int:
        return len(self._tokens)


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
    """Back off on an HTTP 403. Handles all three GitHub cases:

    1. Secondary rate limit with a ``Retry-After`` header (seconds).
    2. Primary rate limit exhausted (``X-RateLimit-Remaining: 0``) -> wait for
       ``X-RateLimit-Reset``.
    3. Secondary rate limit without a ``Retry-After`` header -> fixed backoff.

    Previously only case 2 was handled, so a secondary-limit 403 fell straight
    through and the caller mis-read the failure as 'resource not found'.
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            sleep_for = int(retry_after) + 1
        except ValueError:
            sleep_for = 60
        logger.warning("Secondary rate limit; sleeping %ds (Retry-After)", sleep_for)
        time.sleep(sleep_for)
        return
    remaining = int(response.headers.get("X-RateLimit-Remaining", 1) or 1)
    if remaining == 0:
        reset = int(response.headers.get("X-RateLimit-Reset", 0) or 0)
        sleep_for = max(0, reset - int(time.time())) + 5
        logger.warning("Rate limited. Sleeping %ds for reset...", sleep_for)
        time.sleep(sleep_for)
    else:
        logger.warning("HTTP 403 without rate-limit headers; backing off 30s")
        time.sleep(30)


def _gh_get(url: str, rotator: _TokenRotator, params: Optional[dict] = None,
            max_retries: int = 3) -> Optional[requests.Response]:
    """GET ``url`` rotating tokens per attempt (so retries try a fresh PAT)."""
    for attempt in range(max_retries):
        headers = _get_headers(rotator.next())
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
                 topic: Optional[str] = None, star_band=None) -> str:
    cutoff = (datetime.utcnow() - timedelta(days=activity_months * 30)).strftime("%Y-%m-%d")
    if star_band is None:
        stars_q = f"stars:>={min_stars}"
    else:
        lo, hi = star_band
        stars_q = f"stars:>={lo}" if hi is None else f"stars:{lo}..{hi}"
    parts = [
        "language:TypeScript",
        f"license:{license_key}",
        stars_q,
        f"pushed:>={cutoff}",
        "fork:false",
        "archived:false",
    ]
    if topic:
        parts.append(f"topic:{topic}")
    return " ".join(parts)


def search_repos(rotator: _TokenRotator, *, min_stars: int, max_repos: int,
                 activity_months: int, topics: Optional[list] = None) -> list[dict]:
    """Fan out searches across allowed licenses and (optionally) topics.

    GitHub's Search API caps results at 1000 per query. We split by license
    (5 queries) and optionally by topic (adds N more queries) to maximise
    distinct repos returned within the cap.
    """
    def _star_bands(low):
        edges = [low]
        for mult in (2, 4, 8, 20, 50, 150):
            e = low * mult
            if e > edges[-1]:
                edges.append(e)
        bands = []
        for i in range(len(edges) - 1):
            bands.append((edges[i], edges[i + 1] - 1))
        bands.append((edges[-1], None))
        return bands

    queries: list[str] = []
    for lic in SEARCH_LICENSE_KEYS:
        for band in _star_bands(min_stars):
            if topics:
                for t in topics:
                    queries.append(_build_query(lic, min_stars, activity_months,
                                                topic=t, star_band=band))
            else:
                queries.append(_build_query(lic, min_stars, activity_months,
                                            star_band=band))

    found: dict[str, dict] = {}
    found_lock = threading.Lock()

    def _run_query(query: str) -> None:
        """Paginate one search query, merging hits into the shared dict."""
        page = 1
        per_page = 100
        while True:
            with found_lock:
                if len(found) >= max_repos:
                    return
            resp = _gh_get(
                f"{GITHUB_API}/search/repositories",
                rotator,
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
                return
            data = resp.json()
            items = data.get("items", [])
            if not items:
                return
            with found_lock:
                for repo in items:
                    full = repo.get("full_name", "")
                    if not full or full in found:
                        continue
                    lname = full.lower()
                    if any(p in lname for p in EXCLUDE_NAME_PATTERNS):
                        continue
                    found[full] = repo
                stop = len(found) >= max_repos
            total = data.get("total_count", 0)
            if stop or page * per_page >= min(total, 1000):
                return
            page += 1

    # Queries run in parallel: each call rotates tokens and GitHub's secondary
    # search rate limit is per-token, so N tokens give ~N x throughput. _gh_get
    # already backs off on HTTP 403, so no blanket sleep between pages is needed.
    logger.info("Searching %d license/topic queries...", len(queries))
    with ThreadPoolExecutor(max_workers=max(1, rotator.size)) as exe:
        list(exe.map(_run_query, queries))
    logger.info("Found %d unique candidate repos across all licenses/topics", len(found))
    return list(found.values())


# ---------------------------------------------------------------------------
# Per-repo validation
# ---------------------------------------------------------------------------

def fetch_license_content(rotator: _TokenRotator, owner: str, name: str) -> str:
    """Return decoded LICENSE content (lowercased), empty string on failure."""
    resp = _gh_get(f"{GITHUB_API}/repos/{owner}/{name}/license", rotator)
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


def classify_license(repo: dict, rotator: _TokenRotator) -> Optional[str]:
    """Return the allow-listed SPDX ID for this repo, or None if not allowed.

    The repo's metadata ``license.spdx_id`` is the first-line check. For
    ``MIT`` results we additionally inspect LICENSE content to surface
    ``MIT-0`` (which GitHub classifies as ``MIT``).
    """
    spdx = (repo.get("license") or {}).get("spdx_id") or ""
    if spdx in ALLOWED_SPDX_IDS - {"MIT-0"}:
        if spdx == "MIT":
            content = fetch_license_content(
                rotator, repo["owner"]["login"], repo["name"]
            )
            if content and any(m in content for m in MIT_ZERO_MARKERS):
                return "MIT-0"
            return "MIT"
        return spdx
    return None


def check_ts_root(rotator: _TokenRotator, owner: str, name: str) -> bool:
    """Return True iff both package.json and tsconfig.json exist at repo root."""
    pkg = _gh_get(
        f"{GITHUB_API}/repos/{owner}/{name}/contents/package.json",
        rotator,
    )
    if pkg is None or pkg.status_code != 200:
        return False
    tsc = _gh_get(
        f"{GITHUB_API}/repos/{owner}/{name}/contents/tsconfig.json",
        rotator,
    )
    return bool(tsc is not None and tsc.status_code == 200)


def check_tests(rotator: _TokenRotator, owner: str, name: str) -> bool:
    """Heuristic: tests/ or test/ dir, or vitest.config.ts, or vitest/test in CI."""
    resp = _gh_get(f"{GITHUB_API}/repos/{owner}/{name}/contents/", rotator)
    if resp is None or resp.status_code != 200:
        return False
    try:
        contents = resp.json()
    except Exception:
        return False
    if not isinstance(contents, list):
        return False
    names = {item.get("name", "").lower() for item in contents}
    if names & {"tests", "test", "__tests__", "spec", "specs"}:
        return True
    if names & {"vitest.config.ts", "vitest.config.js", "vitest.config.mts", "vitest.config.mjs"}:
        return True
    # CI fallback: check .github/workflows
    if ".github" in names:
        wf = _gh_get(
            f"{GITHUB_API}/repos/{owner}/{name}/contents/.github/workflows",
            rotator,
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


def count_merged_prs(rotator: _TokenRotator, owner: str, name: str) -> int:
    resp = _gh_get(
        f"{GITHUB_API}/search/issues",
        rotator,
        params={"q": f"repo:{owner}/{name} is:pr is:merged", "per_page": 1},
    )
    if resp is None or resp.status_code != 200:
        return 0
    return int(resp.json().get("total_count", 0))


def _validate_single(
    repo: dict,
    rotator: _TokenRotator,
    *,
    min_prs: int,
    require_ts_root: bool,
    require_tests: bool,
    skip_pr_count: bool,
) -> Optional[dict]:
    """Validate a single repo. Returns the enriched repo dict or ``None``."""
    full = repo["full_name"]
    owner = repo["owner"]["login"]
    name = repo["name"]
    stars = repo.get("stargazers_count", 0)

    spdx = classify_license(repo, rotator)
    if spdx is None:
        logger.info("  ✗ %s: license not allowed (%s)",
                    full, (repo.get("license") or {}).get("spdx_id"))
        return None
    repo["_license_spdx"] = spdx

    if require_ts_root and not check_ts_root(rotator, owner, name):
        logger.info("  ✗ %s: missing package.json and/or tsconfig.json at root", full)
        return None

    if require_tests and not check_tests(rotator, owner, name):
        logger.info("  ✗ %s: no test infrastructure detected", full)
        return None

    if skip_pr_count:
        # -1 = not measured; downstream `ranked` output still sorts by stars
        # when merged_prs is uniform across all entries.
        repo["_merged_prs"] = -1
    else:
        n_prs = count_merged_prs(rotator, owner, name)
        if n_prs < min_prs:
            logger.info("  ✗ %s: only %d merged PRs (need >= %d)",
                        full, n_prs, min_prs)
            return None
        repo["_merged_prs"] = n_prs

    logger.info("  ✓ %s (⭐%d, license=%s, prs=%d)",
                full, stars, spdx, repo["_merged_prs"])
    return repo


def validate_repos(
    repos: list[dict],
    rotator: _TokenRotator,
    *,
    min_prs: int,
    require_ts_root: bool,
    require_tests: bool,
    skip_pr_count: bool = False,
    max_workers: Optional[int] = None,
    stream_path: Optional[str] = None,
) -> list[dict]:
    """Validate ``repos`` in parallel. Returns the enriched, passing subset.

    Worker count defaults to the number of tokens in ``rotator`` since each
    in-flight request consumes one token's rate-limit budget.

    When ``stream_path`` is provided, every repo that passes validation is
    appended to that path as a single JSONL row immediately (flush + fsync
    per row) so partial progress survives a crash and external observers can
    tail the file in real time. The final ``write_output`` call still emits
    the canonical batched output; the stream is a sidecar.
    """
    if max_workers is None:
        max_workers = max(1, rotator.size)
    out: list[dict] = []

    stream_f = None
    stream_lock = threading.Lock()
    if stream_path:
        parent = os.path.dirname(stream_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        stream_f = open(stream_path, "w", encoding="utf-8")
        logger.info("Streaming validated repos to %s (real-time append)", stream_path)

    logger.info(
        "Validating %d repos with %d worker(s) over %d token(s); skip_pr_count=%s",
        len(repos), max_workers, rotator.size, skip_pr_count,
    )
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futs = {
                exe.submit(
                    _validate_single,
                    repo,
                    rotator,
                    min_prs=min_prs,
                    require_ts_root=require_ts_root,
                    require_tests=require_tests,
                    skip_pr_count=skip_pr_count,
                ): repo["full_name"]
                for repo in repos
            }
            for fut in as_completed(futs):
                try:
                    result = fut.result()
                except Exception:
                    logger.exception("validation worker raised for %s", futs[fut])
                    continue
                if result is not None:
                    out.append(result)
                    if stream_f is not None:
                        with stream_lock:
                            stream_f.write(json.dumps({
                                "full_name": result["full_name"],
                                "stars": result.get("stargazers_count", 0),
                                "license": result.get("_license_spdx", ""),
                                "merged_prs": result.get("_merged_prs", 0),
                                "description": result.get("description", ""),
                                "topics": result.get("topics", []),
                                "pushed_at": result.get("pushed_at", ""),
                            }) + "\n")
                            stream_f.flush()
                            try:
                                os.fsync(stream_f.fileno())
                            except OSError:
                                pass
    finally:
        if stream_f is not None:
            stream_f.close()
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
                "# Auto-discovered TypeScript repos for SWE-fficiency\n"
                f"# Generated: {datetime.now().isoformat()}\n"
                f"# Total: {len(ranked)} repos\n"
                "# Filter: language:TypeScript + license in {MIT, MIT-0, Apache-2.0, "
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
        "--require-ts-root",
        action="store_true",
        default=True,
        help="Require package.json AND tsconfig.json at root (default: True)",
    )
    parser.add_argument(
        "--no-require-ts-root", dest="require_ts_root", action="store_false"
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
        help="Skip license + ts-root + tests + PR-count validation",
    )
    parser.add_argument(
        "--no-pr-count",
        action="store_true",
        help="Skip the per-repo merged-PR count gate (saves one /search/issues "
             "call per candidate; trades quality for throughput). Affected repos "
             "will report merged_prs=-1.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Parallel workers for validation (default: number of tokens supplied)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub PAT or comma-separated list (default: GITHUB_TOKENS / GITHUB_TOKEN)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Resolve token list. --token may be a single PAT or comma-separated;
    # otherwise GITHUB_TOKENS (comma-separated) > GITHUB_TOKEN (single).
    tokens: list[str] = []
    if args.token:
        tokens = [t.strip() for t in args.token.split(",") if t.strip()]
    if not tokens:
        raw = os.environ.get("GITHUB_TOKENS", "")
        if raw:
            tokens = [t.strip() for t in raw.split(",") if t.strip()]
    if not tokens:
        single = os.environ.get("GITHUB_TOKEN", "").strip()
        if single:
            tokens = [single]
    if not tokens:
        logger.error("No GitHub token. Set GITHUB_TOKEN/GITHUB_TOKENS or pass --token.")
        return 1
    rotator = _TokenRotator(tokens)
    logger.info("Token rotator: %d PAT(s)", rotator.size)

    candidates = search_repos(
        rotator,
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
            rotator,
            min_prs=args.min_prs,
            require_ts_root=args.require_ts_root,
            require_tests=args.require_tests,
            skip_pr_count=args.no_pr_count,
            max_workers=args.max_workers,
            stream_path=str(args.output) + ".stream.jsonl",
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
