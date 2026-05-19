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

"""Build TypeScript dataset rows from collected pull requests.

Mirrors :mod:`swefficiency.collect.build_dataset` (Python). Two changes:

* Filter routes through :mod:`swefficiency.perf_filter` exactly as the
  Python pipeline does -- the perf filter is language-agnostic and works
  on commit messages / titles.
* Every emitted row is tagged ``language='ts'`` so downstream consumers
  can dispatch without re-detecting.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

from swefficiency.collect.utils import (
    PatchFetchError,
    Repo,
    extract_patches,
    write_to_dlq,
)
from swefficiency.perf_filter.attributes.filter import is_perf_pr
from swefficiency.perf_filter.utils import stream_jsonl

logger = logging.getLogger(__name__)


def is_valid_instance(instance: dict) -> bool:
    if not instance.get("repo"):
        return False
    if not instance.get("base_commit"):
        return False
    if not instance.get("instance_id"):
        return False
    return True


def create_instance(
    pr: dict, repo: str, repo_obj: Repo, language: str = "ts"
) -> dict:
    instance_id = f"{repo.replace('/', '__')}-{pr.get('number')}"
    try:
        patch, test_patch = extract_patches(pr, repo_obj)
        patch_fetch_failed = False
    except PatchFetchError as e:
        logger.warning("extract_patches failed for %s: %s", instance_id, e)
        patch, test_patch = None, None
        patch_fetch_failed = True
        write_to_dlq(
            "build_dataset_ts_fetch_failed.jsonl",
            {
                "instance_id": instance_id,
                "repo": repo,
                "stage": "extract_patches_ts",
                "error_type": type(e).__name__,
                "error": str(e),
            },
        )

    instance: dict[str, Any] = {
        "instance_id": instance_id,
        "repo": repo,
        "pull_number": int(pr.get("number")) if pr.get("number") is not None else None,
        "base_commit": (pr.get("base") or {}).get("sha"),
        "patch": patch,
        "test_patch": test_patch,
        "problem_statement": (pr.get("title") or "") + "\n\n" + (pr.get("body") or ""),
        "hints_text": "",
        "created_at": pr.get("created_at"),
        "version": "",
        "language": language,
        "patch_fetch_failed": patch_fetch_failed,
    }
    return instance


def build_dataset_ts(
    repo: str,
    pulls_path: Path,
    output_dir: Path,
    *,
    resume: bool = True,
    max_pulls: Optional[int] = None,
    token=None,
) -> tuple[int, int, int]:
    """Iterate ``pulls_path`` and emit ``.all`` + ``.filtered`` JSONL files.

    Returns ``(completed, perf_kept, fetch_failed)``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # extract_patches needs a Repo object (it reads repo.token for the diff
    # fetch). Construct it once per repo, mirroring the Python pipeline.
    owner, name = repo.split("/", 1)
    repo_obj = Repo(owner, name, token=token if token is not None else os.environ.get("GITHUB_TOKEN"))
    all_output = output_dir / (repo.replace("/", "__") + "_ts.all.jsonl")
    filtered_output = output_dir / (repo.replace("/", "__") + "_ts.perf.jsonl")
    seen_prs_path = Path(str(all_output) + ".seen_prs")

    seen_prs: set[str] = set()
    write_mode_all = "w"
    write_mode_filtered = "w"
    completed = 0
    perf_kept = 0
    fetch_failed = 0

    if resume and seen_prs_path.exists():
        seen_prs = {line.strip() for line in seen_prs_path.read_text().splitlines() if line.strip()}
        write_mode_all = "a"
        write_mode_filtered = "a"
        logger.info("Loaded %d seen instance ids from %s", len(seen_prs), seen_prs_path)
    elif resume and all_output.exists():
        logger.info("Bootstrapping seen_prs from %s (one-time cost)", all_output)
        with open(all_output) as f, open(seen_prs_path, "w") as ledger:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                iid = obj.get("instance_id")
                if iid:
                    seen_prs.add(iid)
                    ledger.write(iid + "\n")
        write_mode_all = "a"
        write_mode_filtered = "a"

    with open(all_output, write_mode_all) as all_f, \
         open(filtered_output, write_mode_filtered) as filtered_f, \
         open(seen_prs_path, "a") as seen_prs_f:
        for pr in stream_jsonl(str(pulls_path)):
            if max_pulls is not None and completed >= max_pulls:
                break
            instance = create_instance(pr, repo, repo_obj, language="ts")
            if not is_valid_instance(instance):
                continue
            if instance["instance_id"] in seen_prs:
                continue
            print(json.dumps(instance), file=all_f, flush=True)
            print(instance["instance_id"], file=seen_prs_f, flush=True)
            completed += 1
            if instance["patch_fetch_failed"]:
                fetch_failed += 1
                continue
            # is_perf_pr reads the raw PR's title/body/labels, not the
            # derived instance dict.
            if is_perf_pr(repo, pr):
                print(json.dumps(instance), file=filtered_f, flush=True)
                perf_kept += 1

    return completed, perf_kept, fetch_failed


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True, help="GitHub org/repo (e.g. lodash/lodash)")
    p.add_argument("--pulls-path", required=True, type=Path, help="JSONL of PRs")
    p.add_argument("--output-dir", required=True, type=Path, help="Output directory")
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--max-pulls", type=int, default=None)
    return p


def main(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=os.environ.get("SWEFF_LOG_LEVEL", "INFO"))
    completed, perf_kept, fetch_failed = build_dataset_ts(
        repo=args.repo,
        pulls_path=args.pulls_path,
        output_dir=args.output_dir,
        resume=not args.no_resume,
        max_pulls=args.max_pulls,
    )
    logger.info(
        "build_dataset_ts done: completed=%d perf_kept=%d fetch_failed=%d",
        completed, perf_kept, fetch_failed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
