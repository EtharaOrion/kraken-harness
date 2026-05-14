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

Tokens are distributed across repos for parallel scraping.
"""

import argparse
import logging
import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool

from dotenv import load_dotenv

from swefficiency.collect.build_dataset import main as build_dataset
from swefficiency.collect.print_pulls import main as print_pulls
from swefficiency.collect.utils import write_to_dlq

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_repos_from_file(repos_file: str) -> list[str]:
    """
    Load repository list from a file.

    Supports formats:
    - Simple: one owner/repo per line
    - Ranked (from discover_repos.py): "owner/repo  # comment" lines
    - Comments (#) and blank lines are skipped
    """
    repos = []
    with open(repos_file) as f:
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
    Logic for combining multiple .all PR files into a single fine tuning dataset

    Args:
        data (dict): Dictionary containing the following keys:
            repos (list): List of repositories to retrieve instruction data for
            path_prs (str): Path to save PR data files to
            path_tasks (str): Path to save task instance data files to
            token (str): GitHub token to use for API requests
    """
    repos, path_prs, path_tasks, max_pulls, cutoff_date, token = (
        data["repos"],
        data["path_prs"],
        data["path_tasks"],
        data["max_pulls"],
        data["cutoff_date"],
        data["token"],
    )
    for repo in repos:
        repo = repo.strip(",").strip()
        repo_name = repo.replace("/", "__")
        try:
            path_pr = os.path.join(path_prs, f"{repo_name}-prs.jsonl")
            if cutoff_date:
                path_pr = path_pr.replace(".jsonl", f"-{cutoff_date}.jsonl")
            if not os.path.exists(path_pr):
                print(f"Pull request data for {repo} not found, creating...")
                print_pulls(
                    repo, path_pr, token, max_pulls=max_pulls, cutoff_date=cutoff_date
                )
                print(f"✅ Successfully saved PR data for {repo} to {path_pr}")
            else:
                print(
                    f"📁 Pull request data for {repo} already exists at {path_pr}, skipping..."
                )

            path_task = os.path.join(path_tasks, f"{repo_name}-task-instances.jsonl")
            if not os.path.exists(path_task):
                print(f"Task instance data for {repo} not found, creating...")
                build_dataset(path_pr, path_task, token, canonical_repo=repo)
                print(
                    f"✅ Successfully saved task instance data for {repo} to {path_task}"
                )
            else:
                print(
                    f"📁 Task instance data for {repo} already exists at {path_task}, skipping..."
                )
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
):
    """
    Spawns multiple threads given multiple GitHub tokens for collecting fine tuning data

    Args:
        repos (list): List of repositories to retrieve instruction data for
        repos_file (str): Path to file containing repos (one per line)
        path_prs (str): Path to save PR data files to
        path_tasks (str): Path to save task instance data files to
        max_pulls (int): Maximum number of PRs to fetch per repo
        cutoff_date (str): Cutoff date for PRs to consider in format YYYYMMDD
    """
    # Resolve repos from --repos or --repos-file
    all_repos = []
    if repos:
        all_repos.extend(repos)
    if repos_file:
        file_repos = load_repos_from_file(repos_file)
        all_repos.extend(file_repos)
        logger.info(f"Loaded {len(file_repos)} repos from {repos_file}")

    if not all_repos:
        raise ValueError(
            "No repos specified. Use --repos or --repos-file."
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
    tokens = tokens.split(",")
    data_task_lists = split_instances(all_repos, len(tokens))

    data_pooled = [
        {
            "repos": repos_chunk,
            "path_prs": path_prs,
            "path_tasks": path_tasks,
            "max_pulls": max_pulls,
            "cutoff_date": cutoff_date,
            "token": token,
        }
        for repos_chunk, token in zip(data_task_lists, tokens)
    ]

    # ProcessPoolExecutor instead of Pool.map: surfaces BrokenProcessPool
    # on worker death and lets surviving chunks complete. Per-repo failures
    # are handled inside construct_data_files; this outer net catches
    # SIGKILL/OOM/crash scenarios and DLQs the affected chunk's repos.
    with ProcessPoolExecutor(max_workers=len(tokens)) as executor:
        future_to_repos = {
            executor.submit(construct_data_files, data): data["repos"]
            for data in data_pooled
        }
        for future in as_completed(future_to_repos):
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
