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

"""Script to collect pull requests and convert them to candidate task instances.

Supports multiple input methods for repos:
  --repos owner/repo1 owner/repo2 ...   (inline list)
  --repos-file path/to/repos.txt        (one owner/repo per line, # comments ok)
  --repos-json path/to/repos.json       (JSON array of strings or objects)

Tokens are distributed across repos for parallel scraping.
"""

import argparse
import json
import logging
import os
import traceback
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from concurrent.futures.process import BrokenProcessPool

from dotenv import load_dotenv

from swefficiency.collect.build_dataset import main as build_dataset
from swefficiency.collect.print_pulls import main as print_pulls
from swefficiency.collect.utils import write_to_dlq, _TokenRotator, TokenStuckError

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

CHUNK_TIMEOUT_S = int(os.environ.get("SWEFF_CHUNK_TIMEOUT_S", "14400"))

def load_repos_from_file(repos_file: str) -> list[str]:
    """
    Load repository list from a file.

    Supports formats:
    - Simple: one owner/repo per line
    - Ranked (from discover_repos.py): "owner/repo  # comment" lines
    - Comments (#) and blank lines are skipped
    """
    repos = []
    with open(repos_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Handle ranked format: "owner/repo  # stars | est_perf_prs | density"
            repo_name = line.split("#")[0].strip()
            # Handle any trailing whitespace or extra fields
            repo_name = repo_name.split()[0] if repo_name else ""
            if "/" in repo_name:
                repos.append(repo_name)
            else:
                logger.warning(f"Skipping invalid repo line: {line!r}")
    return repos


def load_repos_from_json(repos_json: str) -> list[str]:
    """
    Load repository list from a JSON file.

    Accepts three shapes:
    - Array of strings:  ["owner/repo1", "owner/repo2"]
    - Array of objects:  [{"full_name": "owner/repo1", ...}, ...]
                         (the format emitted by discover_repos.py --format json)
    - Object wrapper:    {"repos": [...]}  where [...] is either of the above

    Entries without a valid "owner/repo" shape are skipped with a warning.
    """
    with open(repos_json, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = data.get("repos", [])
    if not isinstance(data, list):
        raise ValueError(
            f"{repos_json}: expected a JSON array or {{'repos': [...]}}, "
            f"got {type(data).__name__}"
        )

    repos = []
    for entry in data:
        if isinstance(entry, str):
            repo_name = entry.strip()
        elif isinstance(entry, dict):
            repo_name = str(entry.get("full_name") or entry.get("repo") or "").strip()
        else:
            logger.warning(f"Skipping invalid repo entry: {entry!r}")
            continue
        if "/" in repo_name:
            repos.append(repo_name)
        else:
            logger.warning(f"Skipping invalid repo entry: {entry!r}")
    return repos


def split_instances(input_list: list, n: int) -> list:
    """
    Split a list into n approximately equal length sublists

    Args:
        input_list (list): List to split
        n (int): Number of sublists to split into
    Returns:
        result (list): List of sublists
    """
    avg_length = len(input_list) // n
    remainder = len(input_list) % n
    result, start = [], 0

    for i in range(n):
        length = avg_length + 1 if i < remainder else avg_length
        sublist = input_list[start : start + length]
        result.append(sublist)
        start += length

    return result


def construct_data_files(data: dict):
    """
    Combine multiple .all PR files into a single fine tuning dataset.

    Args:
        data (dict): keys: repos, path_prs, path_tasks, max_pulls,
            cutoff_date, tokens (a private disjoint token subset for this
            worker, used to build one _TokenRotator).
    """
    repos, path_prs, path_tasks, max_pulls, cutoff_date, tokens = (
        data["repos"],
        data["path_prs"],
        data["path_tasks"],
        data["max_pulls"],
        data["cutoff_date"],
        data["tokens"],
    )
    # One rotator per worker process, shared by every Repo this worker builds,
    # so token cooldown/quota state persists across all repos in the chunk.
    rotator = _TokenRotator(tokens)

    # completed_repos.txt ledger: a repo listed here was fully scraped on a
    # prior run, so we skip it without spending any GitHub API calls.
    ledger_path = os.path.join(path_tasks, "completed_repos.txt")
    completed = set()
    if os.path.exists(ledger_path):
        with open(ledger_path, encoding="utf-8") as f:
            completed = {ln.strip() for ln in f if ln.strip()}

    for idx, repo in enumerate(repos):
        repo = repo.strip(",").strip()
        repo_name = repo.replace("/", "__")
        if repo in completed:
            print(f"\U0001F4C1 {repo} already in completed_repos.txt, skipping (0 API calls)")
            continue
        try:
            path_pr = os.path.join(path_prs, f"{repo_name}-prs.jsonl")
            if cutoff_date:
                path_pr = path_pr.replace(".jsonl", f"-{cutoff_date}.jsonl")
            # Always call print_pulls: its line-count resume completes a
            # partially-scraped file, and the completed_repos.txt ledger
            # already skips fully-finished repos. Trusting a bare
            # os.path.exists() check would accept a truncated PR file from
            # a worker killed mid-scrape.
            print(f"Fetching/resuming PR data for {repo} -> {path_pr}")
            print_pulls(
                repo, path_pr, rotator, max_pulls=max_pulls, cutoff_date=cutoff_date
            )

            path_task = os.path.join(path_tasks, f"{repo_name}-task-instances.jsonl")
            if not os.path.exists(path_task):
                print(f"Task instance data for {repo} not found, creating...")
                build_dataset(path_pr, path_task, rotator, canonical_repo=repo)
                print(
                    f"\u2705 Successfully saved task instance data for {repo} to {path_task}"
                )
            else:
                print(
                    f"\U0001F4C1 Task instance data for {repo} already exists at {path_task}, skipping..."
                )
            # Mark the repo done so future runs skip it (POSIX append is atomic).
            with open(ledger_path, "a", encoding="utf-8") as f:
                f.write(repo + "\n")
            completed.add(repo)
        except TokenStuckError as e:
            # This worker's entire token subset is exhausted/revoked: it cannot
            # process any further repo. DLQ the remainder and stop the worker.
            remaining = [r.strip(",").strip() for r in repos[idx:]]
            print(f"Token subset exhausted at {repo}: {e}; DLQ-ing {len(remaining)} repos")
            for r in remaining:
                write_to_dlq(
                    "task_pipeline_token_exhausted.jsonl",
                    {
                        "repo": r,
                        "stage": "construct_data_files",
                        "error_type": "TokenStuckError",
                        "error": str(e),
                    },
                )
            return
        except Exception as e:
            print("-" * 80)
            print(f"Something went wrong for {repo}, skipping: {e}")
            print("Here is the full traceback:")
            traceback.print_exc()
            print("-" * 80)
            write_to_dlq(
                "task_pipeline_repo_failures.jsonl",
                {
                    "repo": repo,
                    "stage": "construct_data_files",
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                },
            )


def main(
    repos: list = None,
    path_prs: str = ".",
    path_tasks: str = ".",
    max_pulls: int = None,
    cutoff_date: str = None,
    repos_file: str = None,
    repos_json: str = None,
):
    """
    Spawns multiple threads given multiple GitHub tokens for collecting fine tuning data

    Args:
        repos (list): List of repositories to retrieve instruction data for
        repos_file (str): Path to file containing repos (one per line)
        repos_json (str): Path to JSON file containing repos (array or {'repos': [...]})
        path_prs (str): Path to save PR data files to
        path_tasks (str): Path to save task instance data files to
        max_pulls (int): Maximum number of PRs to fetch per repo
        cutoff_date (str): Cutoff date for PRs to consider in format YYYYMMDD
    """
    # Resolve repos from --repos, --repos-file, and/or --repos-json
    all_repos = []
    if repos:
        all_repos.extend(repos)
    if repos_file:
        file_repos = load_repos_from_file(repos_file)
        all_repos.extend(file_repos)
        logger.info(f"Loaded {len(file_repos)} repos from {repos_file}")
    if repos_json:
        json_repos = load_repos_from_json(repos_json)
        all_repos.extend(json_repos)
        logger.info(f"Loaded {len(json_repos)} repos from {repos_json}")

    if not all_repos:
        raise ValueError(
            "No repos specified. Use --repos, --repos-file, or --repos-json."
        )

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for r in all_repos:
        r_clean = r.strip()
        if r_clean not in seen:
            seen.add(r_clean)
            deduped.append(r_clean)
    all_repos = deduped

    path_prs, path_tasks = os.path.abspath(path_prs), os.path.abspath(path_tasks)
    print(f"Will save PR data to {path_prs}")
    print(f"Will save task instance data to {path_tasks}")
    print(f"Processing {len(all_repos)} repos: {all_repos[:10]}{'...' if len(all_repos) > 10 else ''}")

    tokens = os.getenv("GITHUB_TOKENS")
    if not tokens:
        raise Exception(
            "Missing GITHUB_TOKENS, consider rerunning with GITHUB_TOKENS=$(gh auth token)"
        )
    tokens = [t.strip() for t in tokens.split(",") if t.strip()]
    if not tokens:
        raise Exception("GITHUB_TOKENS is empty")

    # Partition tokens into K disjoint subsets (Model B). Each worker process
    # owns a PRIVATE subset and rotates within it -- no cross-process token
    # collision. K=3 (subsets of ~3) when >=9 tokens are available.
    n_workers = 3 if len(tokens) >= 9 else max(1, len(tokens) // 3)
    token_subsets = [[] for _ in range(n_workers)]
    for i, tok in enumerate(tokens):
        token_subsets[i % n_workers].append(tok)

    # Stride-assign repos across chunks. discover_repos.py emits a ranked
    # (cost-descending) file, so striding spreads heavy repos evenly.
    repo_chunks = [[] for _ in range(n_workers)]
    for i, r in enumerate(all_repos):
        repo_chunks[i % n_workers].append(r)

    data_pooled = [
        {
            "repos": repo_chunks[w],
            "path_prs": path_prs,
            "path_tasks": path_tasks,
            "max_pulls": max_pulls,
            "cutoff_date": cutoff_date,
            "tokens": token_subsets[w],
        }
        for w in range(n_workers)
        if repo_chunks[w]
    ]

    print(
        f"Scraping with {len(data_pooled)} worker(s); "
        f"{len(tokens)} tokens in {n_workers} disjoint subset(s)"
    )

    # ProcessPoolExecutor instead of Pool.map: surfaces BrokenProcessPool
    # on worker death and lets surviving chunks complete. Per-repo failures
    # are handled inside construct_data_files; this outer net catches
    # SIGKILL/OOM/crash scenarios and DLQs the affected chunk's repos.
    with ProcessPoolExecutor(max_workers=len(data_pooled)) as executor:
        future_to_repos = {
            executor.submit(construct_data_files, data): data["repos"]
            for data in data_pooled
        }
        try:
            for future in as_completed(future_to_repos, timeout=CHUNK_TIMEOUT_S):
                chunk_repos = future_to_repos[future]
                try:
                    future.result()
                except BrokenProcessPool as e:
                    logger.error(f"Worker died handling repos {chunk_repos!r}: {e}")
                    for repo in chunk_repos:
                        write_to_dlq(
                            "task_pipeline_worker_died.jsonl",
                            {
                                "repo": repo,
                                "stage": "construct_data_files",
                                "error_type": "BrokenProcessPool",
                                "error": str(e),
                            },
                        )
                except Exception as e:
                    tb = traceback.format_exc()
                    logger.error(f"Uncaught error in chunk {chunk_repos!r}: {e}")
                    for repo in chunk_repos:
                        write_to_dlq(
                            "task_pipeline_chunk_failures.jsonl",
                            {
                                "repo": repo,
                                "stage": "construct_data_files",
                                "error_type": type(e).__name__,
                                "error": str(e),
                                "traceback": tb,
                            },
                        )
        except FuturesTimeoutError:
            pending = [f for f in future_to_repos if not f.done()]
            logger.error(
                f"ProcessPool overall timeout after {CHUNK_TIMEOUT_S}s; "
                f"{len(pending)} stuck chunk(s) covering "
                f"{sum(len(future_to_repos[f]) for f in pending)} repos"
            )
            for future in pending:
                future.cancel()
                chunk_repos = future_to_repos[future]
                for repo in chunk_repos:
                    write_to_dlq(
                        "task_pipeline_stuck.jsonl",
                        {
                            "repo": repo,
                            "stage": "construct_data_files",
                            "error_type": "TimeoutError",
                            "error": f"chunk did not complete within {CHUNK_TIMEOUT_S}s",
                        },
                    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repos",
        nargs="+",
        help="List of repositories (e.g., `sqlfluff/sqlfluff`) to create task instances for",
    )
    parser.add_argument(
        "--repos-file",
        "--repos_file",
        type=str,
        dest="repos_file",
        help="Path to file with repos (one owner/repo per line). Output of discover_repos.py.",
    )
    parser.add_argument(
        "--repos-json",
        "--repos_json",
        type=str,
        dest="repos_json",
        help=(
            "Path to JSON file with repos. Accepts an array of 'owner/repo' "
            "strings, an array of objects with a 'full_name' key (the "
            "discover_repos.py --format json output), or {'repos': [...]}."
        ),
    )
    parser.add_argument(
        "--path_prs", type=str, help="Path to folder to save PR data files to"
    )
    parser.add_argument(
        "--path_tasks",
        type=str,
        help="Path to folder to save task instance data files to",
    )
    parser.add_argument(
        "--max_pulls", type=int, help="Maximum number of pulls to log", default=None
    )
    parser.add_argument(
        "--cutoff_date",
        type=str,
        help="Cutoff date for PRs to consider in format YYYYMMDD",
        default=None,
    )
    args = parser.parse_args()
    main(**vars(args))
