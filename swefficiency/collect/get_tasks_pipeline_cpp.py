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

"""Parallel orchestrator for C++ task scraping.

Mirrors :mod:`swefficiency.collect.get_tasks_pipeline` (Python). Each worker
process handles N repos and calls :mod:`build_dataset_cpp.build_dataset_cpp`.
Worker isolation via :class:`concurrent.futures.ProcessPoolExecutor`; per-repo
DLQ on exception; chunk-level timeout via ``SWEFF_CHUNK_TIMEOUT_S``.

Repos may be supplied via ``--repos`` (inline), ``--repos-file`` (one per line),
or ``--repos-json`` (JSON array of strings/objects, or ``{'repos': [...]}``).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from concurrent.futures import (
    ProcessPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Optional

from swefficiency.collect.build_dataset_cpp import build_dataset_cpp
from swefficiency.collect.print_pulls import main as print_pulls
from swefficiency.collect.utils import write_to_dlq, _TokenRotator, TokenStuckError

logger = logging.getLogger(__name__)

CHUNK_TIMEOUT_S = int(os.environ.get("SWEFF_CHUNK_TIMEOUT_S", "14400"))


def construct_data_files_cpp(data: dict) -> None:
    """Worker: build datasets for each repo in ``data['repos']``.

    The worker owns a private, disjoint token subset and builds one
    _TokenRotator from it (shared by every Repo it constructs). os.environ
    is set to the subset's first token for build_dataset_cpp's internal
    Repo; mutating os.environ is safe -- ProcessPool workers are separate
    processes.
    """
    tokens = list(data.get("tokens") or [])
    rotator = _TokenRotator(tokens)
    if tokens:
        os.environ["GITHUB_TOKEN"] = tokens[0]
    output_dir = Path(data["output_dir"])

    # completed_repos.txt ledger: skip repos fully scraped on a prior run.
    ledger_path = output_dir / "completed_repos.txt"
    completed: set = set()
    if ledger_path.exists():
        completed = {
            ln.strip()
            for ln in ledger_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }

    repos = data["repos"]
    for idx, repo in enumerate(repos):
        if repo in completed:
            logger.info("%s already in completed_repos.txt, skipping (0 API calls)", repo)
            continue
        try:
            pulls_dir = Path(data["pulls_dir"])
            pulls_dir.mkdir(parents=True, exist_ok=True)
            pulls_path = pulls_dir / (repo.replace("/", "__") + ".jsonl")
            # Scrape the repo's PRs if not already present.
            # Always call print_pulls: its resume completes a partially
            # scraped file; the completed_repos.txt ledger skips repos that
            # already finished. A bare exists() check would accept a file
            # truncated by a worker killed mid-scrape.
            logger.info("scraping/resuming PRs for %s -> %s", repo, pulls_path)
            print_pulls(
                repo,
                str(pulls_path),
                rotator,
                max_pulls=data.get("max_pulls"),
                cutoff_date=data.get("cutoff_date"),
            )
            if not pulls_path.exists():
                logger.warning("PR scrape produced no file for %s at %s", repo, pulls_path)
                write_to_dlq(
                    "task_pipeline_cpp_missing_pulls.jsonl",
                    {"repo": repo, "stage": "construct_data_files_cpp",
                     "error_type": "FileNotFoundError",
                     "error": f"PR scrape produced no file at {pulls_path}"},
                )
                continue
            completed_n, perf_kept, fetch_failed = build_dataset_cpp(
                repo=repo,
                pulls_path=pulls_path,
                output_dir=output_dir,
                resume=data.get("resume", True),
                max_pulls=data.get("max_pulls"),
                token=rotator,
            )
            logger.info(
                "[%s] completed=%d perf_kept=%d fetch_failed=%d",
                repo, completed_n, perf_kept, fetch_failed,
            )
            with open(ledger_path, "a", encoding="utf-8") as f:
                f.write(repo + "\n")
            completed.add(repo)
        except TokenStuckError as e:
            remaining = list(repos[idx:])
            logger.error("token subset exhausted at %s: %s; DLQ %d repos",
                          repo, e, len(remaining))
            for r in remaining:
                write_to_dlq(
                    "task_pipeline_cpp_token_exhausted.jsonl",
                    {"repo": r, "stage": "construct_data_files_cpp",
                     "error_type": "TokenStuckError", "error": str(e)},
                )
            return
        except Exception as e:
            logger.error("worker failure for %s: %s", repo, e)
            print("-" * 80)
            traceback.print_exc()
            print("-" * 80)
            write_to_dlq(
                "task_pipeline_cpp_repo_failures.jsonl",
                {"repo": repo, "stage": "construct_data_files_cpp",
                 "error_type": type(e).__name__,
                 "error": str(e),
                 "traceback": traceback.format_exc()},
            )


def _chunkify(repos: list, n: int) -> list:
    if n <= 0:
        return [repos]
    return [repos[i:i + n] for i in range(0, len(repos), n)]


def load_repos_from_json(repos_json: str) -> list:
    """Load a repository list from a JSON file.

    Accepts three shapes:
    - Array of strings:  ["owner/repo1", "owner/repo2"]
    - Array of objects:  [{"full_name": "owner/repo1", ...}, ...]
                         (the format emitted by discover_repos_cpp.py --format json)
    - Object wrapper:    {"repos": [...]}  where [...] is either of the above

    Entries without a valid "owner/repo" shape are skipped with a warning.
    """
    with open(repos_json, "r", encoding="utf-8") as f:
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
            logger.warning("Skipping invalid repo entry: %r", entry)
            continue
        if "/" in repo_name:
            repos.append(repo_name)
        else:
            logger.warning("Skipping invalid repo entry: %r", entry)
    return repos


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Repo specification: exactly one of --repos / --repos-file / --repos-json.
    # Flag names mirror the original Python pipeline's ``get_tasks_pipeline``
    # bash-friendly underscore style so ``run_pipeline_cpp.sh`` can dispatch
    # the cpp variant with the same flag shape as the Python variant.
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--repos", nargs="+",
                     help="GitHub org/repo strings to process")
    src.add_argument("--repos-file", type=Path,
                     help="File with one repo per line (#-comments allowed)")
    src.add_argument("--repos-json", type=Path,
                     help="JSON file: array of 'owner/repo' strings, array of "
                          "objects with 'full_name' (discover_repos_cpp --format "
                          "json output), or {'repos': [...]}.")
    parser.add_argument("--path_prs", required=True, type=Path,
                        help="Directory for raw PR JSONL files")
    parser.add_argument("--path_tasks", required=True, type=Path,
                        help="Directory for task-instance JSONL files")
    parser.add_argument("--tokens", default=os.environ.get("GITHUB_TOKENS", ""),
                        help="Comma-separated GitHub tokens (one worker per token)")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--max_pulls", type=int, default=None)
    parser.add_argument("--cutoff_date", default=None,
                        help="ISO date string (YYYYMMDD); accepted for parity with the "
                             "Python pipeline (Phase 1 reads all PRs; Phase 2 will wire "
                             "this into construct_data_files_cpp).")
    args = parser.parse_args(argv)

    # Resolve final repo list from either source.
    if args.repos_file is not None:
        repos = []
        with open(args.repos_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                # Strip inline comments. discover_repos_cpp's `ranked` format
                # emits lines like `owner/repo  # apache-2.0 | stars | PRs`,
                # so we must drop everything from the first '#' onward.
                repo_name = stripped.split("#", 1)[0].strip()
                # And drop any trailing whitespace-delimited tokens.
                repo_name = repo_name.split()[0] if repo_name else ""
                if repo_name:
                    repos.append(repo_name)
    elif args.repos_json is not None:
        repos = load_repos_from_json(str(args.repos_json))
    else:
        repos = list(args.repos)
    if not repos:
        parser.error(
            "No repos resolved (--repos / --repos-file / --repos-json produced "
            "empty list)"
        )

    logging.basicConfig(
        level=os.environ.get("SWEFF_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tokens = [t.strip() for t in args.tokens.split(",") if t.strip()]
    # Partition tokens into K disjoint subsets (Model B): each worker process
    # owns a PRIVATE subset and rotates within it -- no cross-process collision.
    if tokens:
        n_workers = 3 if len(tokens) >= 9 else max(1, len(tokens) // 3)
    else:
        n_workers = 1
    token_subsets = [[] for _ in range(n_workers)]
    for i, tok in enumerate(tokens):
        token_subsets[i % n_workers].append(tok)

    # Stride-assign repos so heavy repos (a ranked discovery file is
    # cost-descending) spread evenly across the worker chunks.
    repo_chunks = [[] for _ in range(n_workers)]
    for i, r in enumerate(repos):
        repo_chunks[i % n_workers].append(r)

    data_pooled = [
        {
            "repos": repo_chunks[w],
            "pulls_dir": str(args.path_prs),
            "output_dir": str(args.path_tasks),
            "resume": not args.no_resume,
            "max_pulls": args.max_pulls,
            "cutoff_date": args.cutoff_date,
            "tokens": token_subsets[w],
        }
        for w in range(n_workers)
        if repo_chunks[w]
    ]

    with ProcessPoolExecutor(max_workers=len(data_pooled)) as executor:
        future_to_repos = {
            executor.submit(construct_data_files_cpp, data): data["repos"]
            for data in data_pooled
        }
        try:
            for future in as_completed(future_to_repos, timeout=CHUNK_TIMEOUT_S):
                chunk_repos = future_to_repos[future]
                try:
                    future.result()
                except BrokenProcessPool as e:
                    logger.error("BrokenProcessPool on chunk %s: %s", chunk_repos, e)
                    for repo in chunk_repos:
                        write_to_dlq(
                            "task_pipeline_cpp_worker_died.jsonl",
                            {"repo": repo, "stage": "construct_data_files_cpp",
                             "error_type": "BrokenProcessPool", "error": str(e)},
                        )
                except Exception as e:
                    logger.error("chunk %s raised: %s", chunk_repos, e)
                    for repo in chunk_repos:
                        write_to_dlq(
                            "task_pipeline_cpp_chunk_failures.jsonl",
                            {"repo": repo, "stage": "construct_data_files_cpp",
                             "error_type": type(e).__name__, "error": str(e),
                             "traceback": traceback.format_exc()},
                        )
        except FuturesTimeoutError:
            pending = [f for f in future_to_repos if not f.done()]
            logger.error(
                "ProcessPool overall timeout after %ds; %d stuck chunk(s) covering %d repos",
                CHUNK_TIMEOUT_S, len(pending),
                sum(len(future_to_repos[f]) for f in pending),
            )
            for future in pending:
                future.cancel()
                chunk_repos = future_to_repos[future]
                for repo in chunk_repos:
                    write_to_dlq(
                        "task_pipeline_cpp_stuck.jsonl",
                        {"repo": repo, "stage": "construct_data_files_cpp",
                         "error_type": "TimeoutError",
                         "error": f"chunk did not complete within {CHUNK_TIMEOUT_S}s"},
                    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
