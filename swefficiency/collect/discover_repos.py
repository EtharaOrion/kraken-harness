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
Dynamic repository discovery for SWE-fficiency pipeline.

Finds Python repositories on GitHub that are likely to contain performance
optimization PRs, based on criteria derived from the SWE-fficiency paper:

  1. Python language (primary)
  2. Sufficient PR history (>= 200 merged PRs)
  3. Active maintenance (pushed within last 12 months)
  4. Has test infrastructure (pytest, unittest, or tox)
  5. Installable (setup.py, pyproject.toml, or setup.cfg present)
  6. Sufficient stars (proxy for code quality and review rigor)
  7. Not a tutorial/template/awesome-list (has actual library code)

Output: A repos file (one owner/repo per line) suitable for --repos-file.
"""

import argparse
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
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# GitHub Search API base
GITHUB_API = "https://api.github.com"

# Default criteria thresholds
DEFAULT_MIN_STARS = 1000
DEFAULT_MIN_PRS = 200
DEFAULT_MAX_REPOS = 500
DEFAULT_ACTIVITY_MONTHS = 12

# Topics that indicate performance-relevant Python libraries
PERF_RELEVANT_TOPICS = [
    "machine-learning",
    "data-science",
    "scientific-computing",
    "web-framework",
    "api-framework",
    "database",
    "networking",
    "http",
    "async",
    "concurrency",
    "numerical-computing",
    "image-processing",
    "natural-language-processing",
    "deep-learning",
    "data-processing",
    "parser",
    "serialization",
    "validation",
    "orm",
    "cli",
]

# Repos to always exclude (forks, meta-repos, non-library repos)
EXCLUDE_PATTERNS = [
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
]


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

def get_headers(token: str) -> dict:
    """Build auth headers for GitHub API."""
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


def _gh_get(
    url: str,
    rotator: "_TokenRotator",
    params: Optional[dict] = None,
    max_retries: int = 4,
) -> Optional[requests.Response]:
    """GET ``url`` rotating tokens per attempt (so retries try a fresh PAT).

    Returns the final :class:`requests.Response`, or ``None`` if every attempt
    failed. 403 (rate limit) and transient 5xx responses are retried; the
    round-robin rotator means each retry burns a *different* token's budget.
    """
    for attempt in range(max_retries):
        headers = get_headers(rotator.next())
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


def search_repos(
    rotator: "_TokenRotator",
    min_stars: int = DEFAULT_MIN_STARS,
    max_repos: int = DEFAULT_MAX_REPOS,
    activity_months: int = DEFAULT_ACTIVITY_MONTHS,
    topics: Optional[list] = None,
) -> list[dict]:
    """
    Search GitHub for Python repos meeting our criteria.

    Uses the GitHub Search API with pagination. Searches by:
    - language:python
    - stars:>=min_stars
    - pushed:>={date N months ago}
    - NOT fork

    Returns list of repo metadata dicts.
    """
    cutoff_date = (datetime.now() - timedelta(days=activity_months * 30)).strftime(
        "%Y-%m-%d"
    )

    # GitHub Search returns at most 1000 results per query, so a single
    # stars:>=N query silently caps the candidate pool at 1000. Shard the
    # star axis into bands -- each sub-query gets its own 1000-result budget
    # and the union covers the whole qualifying population.
    def _star_bands(low):
        edges = [low]
        for mult in (2, 4, 8, 20, 50, 150):
            e = low * mult
            if e > edges[-1]:
                edges.append(e)
        bands = []
        for i in range(len(edges) - 1):
            bands.append((edges[i], edges[i + 1] - 1))
        bands.append((edges[-1], None))  # open-ended top band
        return bands

    base = f"language:python pushed:>={cutoff_date} fork:false"
    queries = []
    for lo, hi in _star_bands(min_stars):
        stars_q = f"stars:>={lo}" if hi is None else f"stars:{lo}..{hi}"
        shard = f"{base} {stars_q}"
        if topics:
            for topic in topics:
                queries.append(f"{shard} topic:{topic}")
        else:
            queries.append(shard)

    all_repos = {}
    for query in queries:
        if len(all_repos) >= max_repos:
            break
        page = 1
        per_page = 100  # GitHub max
        while len(all_repos) < max_repos:
            params = {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": per_page,
                "page": page,
            }
            response = _gh_get(
                f"{GITHUB_API}/search/repositories", rotator, params=params
            )
            if response is None:
                logger.error("Search request failed after retries: %s", query)
                break
            if response.status_code != 200:
                logger.error(
                    f"Search failed: {response.status_code} - {response.text[:200]}"
                )
                break
            data = response.json()
            items = data.get("items", [])
            if not items:
                break
            for repo in items:
                full_name = repo["full_name"]
                if any(pat in full_name.lower() for pat in EXCLUDE_PATTERNS):
                    continue
                if full_name not in all_repos:
                    all_repos[full_name] = repo
            # GitHub Search API caps at 1000 results per query.
            if page * per_page >= min(data.get("total_count", 0), 1000):
                break
            page += 1
            time.sleep(2)  # Be nice to GitHub

    logger.info(
        f"Found {len(all_repos)} candidate repos from search "
        f"({len(queries)} star-band queries)"
    )
    return list(all_repos.values())[:max_repos]


def check_repo_has_tests(rotator: "_TokenRotator", owner: str, repo: str) -> bool:
    """
    Quick check if repo has test infrastructure by looking for common test markers.
    Checks repo root for: pytest.ini, conftest.py, tox.ini, tests/ directory,
    or pytest in pyproject.toml/setup.cfg.
    """
    response = _gh_get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/", rotator)
    if response is None or response.status_code != 200:
        return False

    contents = response.json()
    if not isinstance(contents, list):
        return False

    names = {item["name"].lower() for item in contents}

    # Direct test markers
    test_markers = {"tests", "test", "pytest.ini", "conftest.py", "tox.ini", "noxfile.py"}
    if test_markers & names:
        return True

    # Check pyproject.toml for pytest config
    if "pyproject.toml" in names:
        return True  # Assume modern Python project has tests

    return False


def check_repo_installable(rotator: "_TokenRotator", owner: str, repo: str) -> bool:
    """Check if repo is pip-installable (has setup.py, pyproject.toml, or setup.cfg)."""
    response = _gh_get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/", rotator)
    if response is None or response.status_code != 200:
        return False

    contents = response.json()
    if not isinstance(contents, list):
        return False

    names = {item["name"].lower() for item in contents}
    install_markers = {"setup.py", "pyproject.toml", "setup.cfg"}
    return bool(install_markers & names)


def check_pr_count(rotator: "_TokenRotator", owner: str, repo: str, min_prs: int) -> int:
    """
    Estimate PR count using the GitHub Search API (issues endpoint with is:pr).
    Returns estimated count, or 0 if the request fails.
    """
    # Use search to count merged PRs
    query = f"repo:{owner}/{repo} is:pr is:merged"
    params = {"q": query, "per_page": 1}

    response = _gh_get(f"{GITHUB_API}/search/issues", rotator, params=params)
    if response is None or response.status_code != 200:
        return 0

    return response.json().get("total_count", 0)


def estimate_perf_pr_density(rotator: "_TokenRotator", owner: str, repo: str) -> float:
    """
    Estimate the density of performance-related PRs by sampling.
    Returns ratio of perf PRs to total merged PRs (0.0-1.0).
    """
    # Search for PRs with performance keywords in title/body
    perf_keywords = "performance OR speedup OR optimize OR profiling OR benchmark OR latency"
    query = f"repo:{owner}/{repo} is:pr is:merged {perf_keywords}"
    params = {"q": query, "per_page": 1}

    response = _gh_get(f"{GITHUB_API}/search/issues", rotator, params=params)
    if response is None or response.status_code != 200:
        return 0.0

    perf_count = response.json().get("total_count", 0)

    # Get total merged PRs
    total_query = f"repo:{owner}/{repo} is:pr is:merged"
    total_params = {"q": total_query, "per_page": 1}
    total_response = _gh_get(
        f"{GITHUB_API}/search/issues", rotator, params=total_params
    )

    if total_response is None or total_response.status_code != 200:
        return 0.0

    total_count = total_response.json().get("total_count", 0)

    if total_count == 0:
        return 0.0

    return perf_count / total_count


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _checkpoint_record(repo: dict) -> dict:
    """The metadata subset persisted to the crash-recovery sidecar."""
    return {
        "full_name": repo["full_name"],
        "stargazers_count": repo.get("stargazers_count", 0),
        "_pr_count": repo.get("_pr_count", 0),
        "_perf_density": repo.get("_perf_density", 0),
        "_estimated_perf_prs": repo.get("_estimated_perf_prs", 0),
        "description": repo.get("description", ""),
        "topics": repo.get("topics", []),
        "pushed_at": repo.get("pushed_at", ""),
    }


def _append_checkpoint(path: str, lock: threading.Lock, repo: dict) -> None:
    """Append one passing repo to the crash-recovery sidecar (thread-safe).

    ``write_repos_file`` only writes the final output once, at the very end of
    ``main()``. A crash mid-validation would otherwise lose the whole pass, so
    every repo that PASSES is also streamed here immediately as JSONL.
    """
    try:
        with lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(_checkpoint_record(repo)) + "\n")
    except Exception as exc:  # checkpointing must never abort discovery
        logger.warning("checkpoint append failed for %s: %s", repo.get("full_name"), exc)


def _validate_single(
    repo: dict,
    rotator: "_TokenRotator",
    *,
    min_prs: int,
    require_tests: bool,
    require_installable: bool,
    min_perf_density: float,
    checkpoint_path: Optional[str],
    checkpoint_lock: threading.Lock,
) -> Optional[dict]:
    """Validate a single repo. Returns the enriched repo dict or ``None``.

    Cheap checks run first so an early reject costs the fewest API calls.
    """
    owner = repo["owner"]["login"]
    name = repo["name"]
    full_name = repo["full_name"]

    # Check 1: PR count (cheap -- single search query)
    pr_count = check_pr_count(rotator, owner, name, min_prs)
    if pr_count < min_prs:
        logger.info("[%s] \u2717 Insufficient PRs: %d < %d", full_name, pr_count, min_prs)
        return None

    # Check 2: Installable (cheap -- single contents call)
    if require_installable and not check_repo_installable(rotator, owner, name):
        logger.info("[%s] \u2717 Not installable (no setup.py/pyproject.toml)", full_name)
        return None

    # Check 3: Has tests (cheap -- single contents call, often cached)
    if require_tests and not check_repo_has_tests(rotator, owner, name):
        logger.info("[%s] \u2717 No test infrastructure detected", full_name)
        return None

    # Check 4: Performance PR density (2 search queries)
    perf_density = estimate_perf_pr_density(rotator, owner, name)
    if perf_density < min_perf_density:
        logger.info(
            "[%s] \u2717 Low perf PR density: %.3f < %s",
            full_name, perf_density, min_perf_density,
        )
        return None

    # Passed all checks
    repo["_pr_count"] = pr_count
    repo["_perf_density"] = perf_density
    repo["_estimated_perf_prs"] = int(pr_count * perf_density)
    if checkpoint_path:
        _append_checkpoint(checkpoint_path, checkpoint_lock, repo)
    logger.info(
        "[%s] \u2713 PASS - PRs:%d, perf_density:%.3f, est_perf_prs:%d",
        full_name, pr_count, perf_density, repo["_estimated_perf_prs"],
    )
    return repo


def validate_repos(
    repos: list[dict],
    rotator: "_TokenRotator",
    min_prs: int = DEFAULT_MIN_PRS,
    require_tests: bool = True,
    require_installable: bool = True,
    min_perf_density: float = 0.01,
    checkpoint_path: Optional[str] = None,
    max_workers: Optional[int] = None,
) -> list[dict]:
    """
    Validate candidate repos against SWE-fficiency requirements, in parallel.

    Validation is the dominant API cost, so it is fanned out across a thread
    pool. Worker count defaults to the number of tokens in ``rotator`` because
    each in-flight request consumes one token's rate-limit budget; the
    round-robin rotator keeps the load balanced across every PAT.

    Returns repos enriched with validation metadata.
    """
    if max_workers is None:
        max_workers = max(1, rotator.size)

    # Fresh run: discard any stale checkpoint sidecar from a previous attempt.
    if checkpoint_path and os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
    checkpoint_lock = threading.Lock()

    validated: list[dict] = []
    logger.info(
        "Validating %d repos with %d worker(s) over %d token(s)",
        len(repos), max_workers, rotator.size,
    )
    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futs = {
            exe.submit(
                _validate_single,
                repo,
                rotator,
                min_prs=min_prs,
                require_tests=require_tests,
                require_installable=require_installable,
                min_perf_density=min_perf_density,
                checkpoint_path=checkpoint_path,
                checkpoint_lock=checkpoint_lock,
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
                validated.append(result)

    return validated


def write_repos_file(repos: list[dict], output: str, format: str = "simple") -> None:
    """
    Write validated repos to output file.

    Formats:
    - simple: one owner/repo per line (for --repos-file)
    - json: full metadata (for analysis)
    - ranked: sorted by estimated perf PRs, with comments
    """
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    if format == "json":
        with open(output, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "full_name": r["full_name"],
                        "stars": r["stargazers_count"],
                        "pr_count": r.get("_pr_count", 0),
                        "perf_density": r.get("_perf_density", 0),
                        "estimated_perf_prs": r.get("_estimated_perf_prs", 0),
                        "description": r.get("description", ""),
                        "topics": r.get("topics", []),
                        "pushed_at": r.get("pushed_at", ""),
                    }
                    for r in repos
                ],
                f,
                indent=2,
            )
    elif format == "ranked":
        # Sort by estimated perf PRs descending
        repos_sorted = sorted(
            repos, key=lambda r: r.get("_estimated_perf_prs", 0), reverse=True
        )
        with open(output, "w", encoding="utf-8") as f:
            f.write(
                "# Auto-discovered repos for SWE-fficiency pipeline\n"
                f"# Generated: {datetime.now().isoformat()}\n"
                f"# Total: {len(repos_sorted)} repos\n"
                "#\n"
                "# Format: owner/repo  # stars | est_perf_prs | density\n"
                "#\n"
            )
            for r in repos_sorted:
                stars = r["stargazers_count"]
                est = r.get("_estimated_perf_prs", 0)
                density = r.get("_perf_density", 0)
                f.write(f"{r['full_name']}  # \u2b50{stars} | ~{est} perf PRs | {density:.1%}\n")
    else:
        # Simple: one per line
        with open(output, "w", encoding="utf-8") as f:
            for r in repos:
                f.write(f"{r['full_name']}\n")

    logger.info(f"Wrote {len(repos)} repos to {output} (format={format})")


def _resolve_tokens(cli_token: Optional[str]) -> list[str]:
    """Collect every available GitHub PAT for round-robin rotation.

    Precedence: ``--token`` (accepts a single PAT or a comma-separated list),
    else ``GITHUB_TOKENS`` (comma-separated), else ``GITHUB_TOKEN`` (single).
    """
    raw = (
        cli_token
        or os.environ.get("GITHUB_TOKENS")
        or os.environ.get("GITHUB_TOKEN")
        or ""
    )
    return [t.strip() for t in raw.split(",") if t.strip()]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        required=True,
        help="Output file path (repos list)",
    )
    parser.add_argument(
        "--format",
        choices=["simple", "json", "ranked"],
        default="ranked",
        help="Output format (default: ranked)",
    )
    parser.add_argument(
        "--min-stars",
        type=int,
        default=DEFAULT_MIN_STARS,
        help=f"Minimum GitHub stars (default: {DEFAULT_MIN_STARS})",
    )
    parser.add_argument(
        "--min-prs",
        type=int,
        default=DEFAULT_MIN_PRS,
        help=f"Minimum merged PRs (default: {DEFAULT_MIN_PRS})",
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=DEFAULT_MAX_REPOS,
        help=f"Maximum repos to return (default: {DEFAULT_MAX_REPOS})",
    )
    parser.add_argument(
        "--activity-months",
        type=int,
        default=DEFAULT_ACTIVITY_MONTHS,
        help=f"Must have been pushed within N months (default: {DEFAULT_ACTIVITY_MONTHS})",
    )
    parser.add_argument(
        "--min-perf-density",
        type=float,
        default=0.01,
        help="Minimum ratio of perf PRs to total PRs (default: 0.01 = 1%%)",
    )
    parser.add_argument(
        "--topics",
        nargs="*",
        default=None,
        help="Filter by GitHub topics (default: broad search)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip PR count/test/install validation (faster, less precise)",
    )
    parser.add_argument(
        "--include-existing",
        type=str,
        default=None,
        help="Path to existing repos file - include these without re-validation",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="GitHub token, or comma-separated list of tokens "
        "(default: GITHUB_TOKENS / GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Parallel validation workers (default: number of tokens)",
    )

    args = parser.parse_args()

    tokens = _resolve_tokens(args.token)
    if not tokens:
        raise ValueError(
            "No GitHub token. Set GITHUB_TOKEN/GITHUB_TOKENS or pass --token."
        )
    rotator = _TokenRotator(tokens)
    logger.info("Token rotator initialised with %d PAT(s)", rotator.size)

    # Step 1: Search for candidate repos
    logger.info(
        f"Searching for Python repos: stars>={args.min_stars}, "
        f"active within {args.activity_months}mo, max={args.max_repos}"
    )
    candidates = search_repos(
        rotator,
        min_stars=args.min_stars,
        max_repos=args.max_repos * 3,  # Over-fetch since validation filters many
        activity_months=args.activity_months,
        topics=args.topics,
    )

    # Step 2: Validate candidates
    if not args.skip_validation:
        logger.info(f"Validating {len(candidates)} candidates...")
        validated = validate_repos(
            repos=candidates,
            rotator=rotator,
            min_prs=args.min_prs,
            min_perf_density=args.min_perf_density,
            checkpoint_path=args.output + ".partial.jsonl",
            max_workers=args.max_workers,
        )
    else:
        validated = candidates
        logger.info("Skipping validation (--skip-validation)")

    # Step 3: Include existing repos if specified
    if args.include_existing and os.path.exists(args.include_existing):
        existing = set()
        with open(args.include_existing, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Handle ranked format: "owner/repo  # comment"
                    repo_name = line.split("#")[0].strip().split()[0]
                    existing.add(repo_name)

        # Add existing repos that aren't already in validated
        validated_names = {r["full_name"] for r in validated}
        for repo_name in existing:
            if repo_name not in validated_names:
                validated.append(
                    {
                        "full_name": repo_name,
                        "stargazers_count": 0,
                        "_pr_count": 0,
                        "_perf_density": 0,
                        "_estimated_perf_prs": 0,
                        "description": "(from existing repos file)",
                        "topics": [],
                        "pushed_at": "",
                        "owner": {"login": repo_name.split("/")[0]},
                        "name": repo_name.split("/")[1],
                    }
                )
        logger.info(f"Included {len(existing)} repos from {args.include_existing}")

    # Step 4: Write output
    # Limit to max_repos
    validated = validated[: args.max_repos]
    write_repos_file(validated, args.output, format=args.format)

    # Summary
    if validated:
        total_est_perf = sum(r.get("_estimated_perf_prs", 0) for r in validated)
        logger.info(
            f"\n{'='*60}\n"
            f"DISCOVERY SUMMARY\n"
            f"  Repos found: {len(validated)}\n"
            f"  Estimated total perf PRs: ~{total_est_perf}\n"
            f"  Output: {args.output}\n"
            f"{'='*60}"
        )
    else:
        logger.warning("No repos passed validation. Try lowering thresholds.")


if __name__ == "__main__":
    main()
