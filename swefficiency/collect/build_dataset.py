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

"""Build task instances from scraped pull requests.

Supports --filter-early to apply perf keyword filtering at Stage I (reduces
downstream volume ~95% for large repos). When disabled (default), ALL merged
PRs pass through and filtering happens at Stage II.
"""

import argparse
import json
import logging
import os
from typing import Optional

from swefficiency.collect.utils import (
    Repo,
    extract_patches,
    extract_problem_statement_and_hints,
    write_to_dlq,
)
from swefficiency.perf_filter.attributes.filter import is_perf_pr

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_instance(repo: Repo, pull: dict) -> dict:
    """
    Create a single task instance from a pull request.

    extract_patches() returns (None, None) on fetch failure (distinct from
    ("", "") meaning the PR genuinely has no diff). We preserve the None
    sentinels in the output dict and tag fetch_failed=True so downstream
    metrics can distinguish data-loss from empty PRs.
    """
    patch, test_patch = extract_patches(pull, repo)
    fetch_failed = patch is None and test_patch is None
    problem_statement, hints = extract_problem_statement_and_hints(pull, repo)

    return {
        "repo": repo.repo.full_name,
        "pull_number": pull["number"],
        "instance_id": (repo.repo.full_name + "-" + str(pull["number"])).replace(
            "/", "__"
        ),
        "issue_numbers": pull["resolved_issues"],
        "base_commit": pull["base"]["sha"],
        "patch": patch if patch is not None else "",
        "test_patch": test_patch if test_patch is not None else "",
        "patch_fetch_failed": fetch_failed,
        "problem_statement": problem_statement,
        "hints_text": hints,
        "created_at": pull["created_at"],
    }


def is_valid_pull(pull: dict) -> bool:
    """
    Check whether PR has an associated issue and is merged

    Args:
        pull (dict): pull request object
    Returns:
        bool: whether PR is valid
    """
    if pull["merged_at"] is None:
        return False
    # SWE-fficency change: We don't need to check for resolved issues.
    # if "resolved_issues" not in pull or len(pull["resolved_issues"]) < 1:
    #     return False
    return True


def is_valid_instance(instance: dict) -> bool:
    """
    Check whether task instance has all required fields for task instance creation

    Args:
        instance (dict): task instance object
    Returns:
        bool: whether task instance is valid
    """
    if instance["patch"] is None or instance["patch"] == "":
        return False
    # SWE-fficiency change: We don't need to check for problem statement.
    # if instance["problem_statement"] is None or instance["problem_statement"] == "":
    #     return False
    return True


def has_test_patch(instance: dict) -> bool:
    """
    Check whether task instance has a test suite

    Args:
        instance (dict): task instance object
    Returns:
        bool: whether task instance has a test suite
    """
    if instance["test_patch"] is None or instance["test_patch"].strip() == "":
        return False
    return True


def main(
    pr_file: str,
    output: str,
    token: Optional[str] = None,
    canonical_repo: Optional[str] = None,
    filter_early: bool = False,
):
    """
    Main thread for creating task instances from pull requests

    Args:
        pr_file (str): path to pull request JSONL file
        output (str): output file name
        token (str): GitHub token
        canonical_repo (str): canonical owner/repo name (prevents GitHub fork resolution)
        filter_early (bool): if True, apply perf keyword filter at this stage
    """
    if token is None:
        # Get GitHub token from environment variable if not provided
        token = os.environ.get("GITHUB_TOKEN")

    def load_repo(repo_name):
        # Return repo object for a given repo name
        owner, repo = repo_name.split("/")
        return Repo(owner, repo, token=token)

    repos = dict()
    completed = 0
    with_tests = 0
    total_instances = 0
    filtered_out = 0
    fetch_failed_count = 0
    all_output = output + ".all"
    seen_prs = set()

    # Continue where we left off if output file already exists
    if os.path.exists(all_output):
        with open(all_output) as f:
            for line in f:
                pr = json.loads(line)
                if "instance_id" not in pr:
                    pr["instance_id"] = (
                        pr["repo"] + "-" + str(pr["pull_number"])
                    ).replace("/", "__")
                instance_id = pr["instance_id"]
                seen_prs.add(instance_id)
                if is_valid_instance(pr):
                    completed += 1
                    if has_test_patch(pr):
                        with_tests += 1
    logger.info(
        f"Will skip {len(seen_prs)} pull requests that have already been inspected"
    )

    # Write to .all file for all PRs
    write_mode_all = "w" if not os.path.exists(all_output) else "a"
    with open(all_output, write_mode_all) as all_output:
        # Write to output file for PRs with test suites
        write_mode = "w" if not os.path.exists(output) else "a"
        with open(output, write_mode) as output:
            for ix, line in enumerate(open(pr_file)):
                total_instances += 1
                pull = json.loads(line)
                pr_repo_name = canonical_repo or pull["base"]["repo"]["full_name"]
                if ix % 100 == 0:
                    logger.info(
                        f"[{pr_repo_name}] (Up to {ix} checked) "
                        f"{completed} valid, {with_tests} with tests."
                    )
                instance_id = (
                    pr_repo_name + "-" + str(pull["number"])
                )
                instance_id = instance_id.replace("/", "__")
                if instance_id in seen_prs:
                    seen_prs -= {instance_id}
                    continue
                if not is_valid_pull(pull):
                    continue

                repo_name = pr_repo_name
                if repo_name not in repos:
                    repos[repo_name] = load_repo(repo_name)
                repo = repos[repo_name]

                # Early perf filtering: skip non-perf PRs at Stage I
                # This reduces downstream volume ~95% but may miss edge cases.
                # The dynamic filter (filter_base) handles any repo without a
                # repo-specific filter — no more hardcoded filter-per-repo needed.
                if filter_early:
                    if not is_perf_pr(repo.name, pull):
                        filtered_out += 1
                        continue

                instance = create_instance(repo, pull)
                if instance.get("patch_fetch_failed"):
                    fetch_failed_count += 1
                    write_to_dlq(
                        "build_dataset_fetch_failed.jsonl",
                        {
                            "instance_id": instance["instance_id"],
                            "repo": instance["repo"],
                            "pull_number": instance["pull_number"],
                        },
                    )
                if is_valid_instance(instance):
                    # If valid, write to .all output file
                    print(
                        json.dumps(instance), end="\n", flush=True, file=all_output
                    )  # write all instances to a separate file
                    completed += 1
                    if has_test_patch(instance):
                        # If has test suite, write to output file
                        print(json.dumps(instance), end="\n", flush=True, file=output)
                        with_tests += 1
    logger.info(
        f"[{', '.join(repos.keys())}] Total instances: {total_instances}, "
        f"completed: {completed}, with tests: {with_tests}, "
        f"patch_fetch_failed: {fetch_failed_count} (see artifacts/dlq/)"
    )
    if filter_early:
        logger.info(
            f"[{', '.join(repos.keys())}] Early filter removed {filtered_out} non-perf PRs"
        )
    logger.info(
        f"[{', '.join(repos.keys())}] Skipped {len(seen_prs)} pull requests that have already been inspected"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pr_file", type=str, help="Path to pull request JSONL file")
    parser.add_argument("output", type=str, help="Output file name")
    parser.add_argument("--token", type=str, help="GitHub token")
    parser.add_argument(
        "--filter-early",
        action="store_true",
        default=False,
        help="Apply perf keyword filter at Stage I (reduces volume ~95%%)",
    )
    args = parser.parse_args()
    main(
        pr_file=args.pr_file,
        output=args.output,
        token=args.token,
        filter_early=args.filter_early,
    )
