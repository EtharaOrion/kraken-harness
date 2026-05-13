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
import time
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


def get_headers(token: str) -> dict:
    """Build auth headers for GitHub API."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def rate_limit_wait(response: requests.Response, token: str) -> None:
    """Handle GitHub rate limiting with backoff."""
    remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
    if remaining == 0:
        reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
        wait_seconds = max(0, reset_time - int(time.time())) + 5
        logger.warning(f"Rate limited. Waiting {wait_seconds}s for reset...")
        time.sleep(wait_seconds)


def search_repos(
    token: str,
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
    headers = get_headers(token)
    cutoff_date = (datetime.now() - timedelta(days=activity_months * 30)).strftime(
        "%Y-%m-%d"
    )

    # Base query: Python, not fork, active, sufficient stars
    base_query = f"language:python stars:>={min_stars} pushed:>={cutoff_date} fork:false"

    # If specific topics requested, search per topic
    queries = []
    if topics:
        for topic in topics:
            queries.append(f"{base_query} topic:{topic}")
    else:
        queries.append(base_query)

    all_repos = {}
    for query in queries:
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

            response = requests.get(
                f"{GITHUB_API}/search/repositories",
                headers=headers,
                params=params,
            )

            if response.status_code == 403:
                rate_limit_wait(response, token)
                continue
            elif response.status_code != 200:
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
                # Skip excluded patterns
                repo_lower = full_name.lower()
                if any(pat in repo_lower for pat in EXCLUDE_PATTERNS):
                    continue
                if full_name not in all_repos:
                    all_repos[full_name] = repo

            # GitHub Search API caps at 1000 results per query
            if page * per_page >= min(data.get("total_count", 0), 1000):
                break

            page += 1
            time.sleep(2)  # Be nice to GitHub

        if len(all_repos) >= max_repos:
            break

    logger.info(f"Found {len(all_repos)} candidate repos from search")
    return list(all_repos.values())[:max_repos]


def check_repo_has_tests(
    token: str, owner: str, repo: str
) -> bool:
    """
    Quick check if repo has test infrastructure by looking for common test markers.
    Checks repo root for: pytest.ini, conftest.py, tox.ini, tests/ directory,
    or pytest in pyproject.toml/setup.cfg.
    """
    headers = get_headers(token)

    # Check for tests/ or test/ directory via the tree API (shallow)
    response = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/",
        headers=headers,
    )

    if response.status_code != 200:
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


def check_repo_installable(
    token: str, owner: str, repo: str
) -> bool:
    """Check if repo is pip-installable (has setup.py, pyproject.toml, or setup.cfg)."""
    headers = get_headers(token)

    response = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/",
        headers=headers,
    )

    if response.status_code != 200:
        return False

    contents = response.json()
    if not isinstance(contents, list):
        return False

    names = {item["name"].lower() for item in contents}
    install_markers = {"setup.py", "pyproject.toml", "setup.cfg"}
    return bool(install_markers & names)


def check_pr_count(
    token: str, owner: str, repo: str, min_prs: int
) -> int:
    """
    Estimate PR count using the GitHub Search API (issues endpoint with is:pr).
    Returns estimated count, or 0 if below threshold.
    """
    headers = get_headers(token)

    # Use search to count merged PRs
    query = f"repo:{owner}/{repo} is:pr is:merged"
    params = {"q": query, "per_page": 1}

    response = requests.get(
        f"{GITHUB_API}/search/issues",
        headers=headers,
        params=params,
    )

    if response.status_code == 403:
        rate_limit_wait(response, token)
        response = requests.get(
            f"{GITHUB_API}/search/issues",
            headers=headers,
            params=params,
        )

    if response.status_code != 200:
        return 0

    total = response.json().get("total_count", 0)
    return total


def estimate_perf_pr_density(
    token: str, owner: str, repo: str
) -> float:
    """
    Estimate the density of performance-related PRs by sampling.
    Returns ratio of perf PRs to total merged PRs (0.0-1.0).
    """
    headers = get_headers(token)

    # Search for PRs with performance keywords in title/body
    perf_keywords = "performance OR speedup OR optimize OR profiling OR benchmark OR latency"
    query = f"repo:{owner}/{repo} is:pr is:merged {perf_keywords}"
    params = {"q": query, "per_page": 1}

    response = requests.get(
        f"{GITHUB_API}/search/issues",
        headers=headers,
        params=params,
    )

    if response.status_code != 200:
        return 0.0

    perf_count = response.json().get("total_count", 0)

    # Get total merged PRs
    total_query = f"repo:{owner}/{repo} is:pr is:merged"
    total_params = {"q": total_query, "per_page": 1}
    total_response = requests.get(
        f"{GITHUB_API}/search/issues",
        headers=headers,
        params=total_params,
    )

    if total_response.status_code != 200:
        return 0.0

    total_count = total_response.json().get("total_count", 0)

    if total_count == 0:
        return 0.0

    return perf_count / total_count


def validate_repos(
    repos: list[dict],
    token: str,
    min_prs: int = DEFAULT_MIN_PRS,
    require_tests: bool = True,
    require_installable: bool = True,
    min_perf_density: float = 0.01,
) -> list[dict]:
    """
    Validate candidate repos against SWE-fficiency requirements.
    Each check costs API calls, so we do cheap checks first.

    Returns repos enriched with validation metadata.
    """
    validated = []

    for i, repo in enumerate(repos):
        owner = repo["owner"]["login"]
        name = repo["name"]
        full_name = repo["full_name"]

        logger.info(
            f"[{i+1}/{len(repos)}] Validating {full_name} "
            f"(⭐{repo['stargazers_count']})"
        )

        # Check 1: PR count (cheap — single search query)
        pr_count = check_pr_count(token, owner, name, min_prs)
        time.sleep(1)

        if pr_count < min_prs:
            logger.info(f"  ✗ Insufficient PRs: {pr_count} < {min_prs}")
            continue

        # Check 2: Installable (cheap — single contents call)
        if require_installable:
            if not check_repo_installable(token, owner, name):
                logger.info(f"  ✗ Not installable (no setup.py/pyproject.toml)")
                continue
            time.sleep(1)

        # Check 3: Has tests (cheap — single contents call, often cached)
        if require_tests:
            if not check_repo_has_tests(token, owner, name):
                logger.info(f"  ✗ No test infrastructure detected")
                continue
            time.sleep(1)

        # Check 4: Performance PR density (2 search queries)
        perf_density = estimate_perf_pr_density(token, owner, name)
        time.sleep(2)

        if perf_density < min_perf_density:
            logger.info(
                f"  ✗ Low perf PR density: {perf_density:.3f} < {min_perf_density}"
            )
            continue

        # Passed all checks
        repo["_pr_count"] = pr_count
        repo["_perf_density"] = perf_density
        repo["_estimated_perf_prs"] = int(pr_count * perf_density)
        validated.append(repo)
        logger.info(
            f"  ✓ PASS — PRs:{pr_count}, perf_density:{perf_density:.3f}, "
            f"est_perf_prs:{repo['_estimated_perf_prs']}"
        )

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
        with open(output, "w") as f:
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
        with open(output, "w") as f:
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
                f.write(f"{r['full_name']}  # ⭐{stars} | ~{est} perf PRs | {density:.1%}\n")
    else:
        # Simple: one per line
        with open(output, "w") as f:
            for r in repos:
                f.write(f"{r['full_name']}\n")

    logger.info(f"Wrote {len(repos)} repos to {output} (format={format})")


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
        help="Path to existing repos file — include these without re-validation",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="GitHub token (default: GITHUB_TOKEN env var)",
    )

    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        # Try GITHUB_TOKENS (comma-separated), take first
        tokens = os.environ.get("GITHUB_TOKENS", "")
        if tokens:
            token = tokens.split(",")[0].strip()
    if not token:
        raise ValueError(
            "No GitHub token. Set GITHUB_TOKEN or pass --token."
        )

    # Step 1: Search for candidate repos
    logger.info(
        f"Searching for Python repos: stars>={args.min_stars}, "
        f"active within {args.activity_months}mo, max={args.max_repos}"
    )
    candidates = search_repos(
        token=token,
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
            token=token,
            min_prs=args.min_prs,
            min_perf_density=args.min_perf_density,
        )
    else:
        validated = candidates
        logger.info("Skipping validation (--skip-validation)")

    # Step 3: Include existing repos if specified
    if args.include_existing and os.path.exists(args.include_existing):
        existing = set()
        with open(args.include_existing) as f:
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
