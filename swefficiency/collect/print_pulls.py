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


"""Given the `<owner/name>` of a GitHub repo, this script writes the raw information for all the repo's PRs to a single `.jsonl` file.

Supports resume: if output file already exists, counts existing lines and skips
that many PRs before writing new ones (append mode).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastcore.xtras import obj2dict

from swefficiency.collect.utils import Repo

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def count_existing_lines(filepath: str) -> int:
    """Count lines in existing file for resume support."""
    if not os.path.exists(filepath):
        return 0
    with open(filepath, encoding="utf-8") as f:
        return sum(1 for _ in f)


def log_all_pulls(
    repo: Repo,
    output: str,
    max_pulls: int = None,
    cutoff_date: str = None,
    resume: bool = True,
) -> None:
    """
    Iterate over all pull requests in a repository and log them to a file.

    Args:
        repo (Repo): repository object
        output (str): output file name
        max_pulls (int): max PRs to fetch
        cutoff_date (str): stop fetching PRs older than this date
        resume (bool): if True and output exists, append new PRs only
    """
    cutoff_date = (
        datetime.strptime(cutoff_date, "%Y%m%d").strftime("%Y-%m-%dT%H:%M:%SZ")
        if cutoff_date is not None
        else None
    )

    # Resume support: skip PRs already in the output file. We key on the PR
    # *number*, not a line count -- get_all_pulls() is ordered newest-first,
    # so PRs that closed between runs appear at the TOP of the list; a
    # line-count skip would drop those new PRs and re-write old ones.
    seen_numbers: set = set()
    write_mode = "w"
    if resume and os.path.exists(output):
        with open(output, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    seen_numbers.add(json.loads(line)["number"])
                except (ValueError, KeyError, TypeError):
                    continue
        if seen_numbers:
            write_mode = "a"
            logger.info(
                f"[{repo.owner}/{repo.name}] Resuming: "
                f"{len(seen_numbers)} PRs already in file"
            )

    new_written = 0
    with open(output, write_mode, encoding="utf-8") as file:
        for pull in repo.get_all_pulls():
            # Desc-by-created order: the first PR older than the cutoff means
            # every remaining PR is older too, so we can stop.
            if cutoff_date is not None and pull.created_at < cutoff_date:
                break
            if pull.number in seen_numbers:
                continue
            if max_pulls is not None and new_written >= max_pulls:
                break
            setattr(pull, "resolved_issues", repo.extract_resolved_issues(pull))
            print(json.dumps(obj2dict(pull)), end="\n", flush=True, file=file)
            new_written += 1

    total = count_existing_lines(output)
    logger.info(
        f"[{repo.owner}/{repo.name}] Total PRs in file: {total} "
        f"(+{new_written} this run)"
    )


def main(
    repo_name: str,
    output: str,
    token: Optional[str] = None,
    max_pulls: int = None,
    cutoff_date: str = None,
    resume: bool = True,
):
    """
    Logic for logging all pull requests in a repository

    Args:
        repo_name (str): name of the repository
        output (str): output file name
        token (str, optional): GitHub token
        max_pulls (int): max PRs to fetch
        cutoff_date (str): cutoff date YYYYMMDD
        resume (bool): resume from existing file if present
    """
    if token is None:
        token = os.environ.get("GITHUB_TOKEN")
    owner, repo = repo_name.split("/")
    repo = Repo(owner, repo, token=token)
    log_all_pulls(repo, output, max_pulls=max_pulls, cutoff_date=cutoff_date, resume=resume)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_name", type=str, help="Name of the repository")
    parser.add_argument("output", type=str, help="Output file name")
    parser.add_argument("--token", type=str, help="GitHub token")
    parser.add_argument(
        "--max_pulls", type=int, help="Maximum number of pulls to log", default=None
    )
    parser.add_argument(
        "--cutoff_date",
        type=str,
        help="Cutoff date for PRs to consider in format YYYYMMDD",
        default=None,
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable resume mode (overwrite existing file)",
    )
    args = parser.parse_args()
    main(
        repo_name=args.repo_name,
        output=args.output,
        token=args.token,
        max_pulls=args.max_pulls,
        cutoff_date=args.cutoff_date,
        resume=not args.no_resume,
    )
