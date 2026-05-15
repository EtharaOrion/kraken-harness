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
"""

from __future__ import annotations

import argparse
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
from swefficiency.collect.utils import write_to_dlq

logger = logging.getLogger(__name__)

CHUNK_TIMEOUT_S = int(os.environ.get("SWEFF_CHUNK_TIMEOUT_S", "14400"))


def construct_data_files_cpp(data: dict) -> None:
    """Worker: build datasets for each repo in ``data['repos']``."""
    # Each worker process gets its own GitHub token so the 5000/hr core rate
    # limit is per-worker, not shared across all of them. Mutating os.environ
    # is safe here: ProcessPoolExecutor workers are separate processes.
    token = data.get("token")
    if token:
        os.environ["GITHUB_TOKEN"] = token
    output_dir = Path(data["output_dir"])
    for repo in data["repos"]:
        try:
            pulls_path = Path(data["pulls_dir"]) / (repo.replace("/", "__") + ".jsonl")
            if not pulls_path.exists():
                logger.warning("missing pulls jsonl for %s at %s", repo, pulls_path)
                write_to_dlq(
                    "task_pipeline_cpp_missing_pulls.jsonl",
                    {"repo": repo, "stage": "construct_data_files_cpp",
                     "error_type": "FileNotFoundError",
                     "error": f"missing pulls jsonl at {pulls_path}"},
                )
                continue
            completed, perf_kept, fetch_failed = build_dataset_cpp(
                repo=repo,
                pulls_path=pulls_path,
                output_dir=output_dir,
                resume=data.get("resume", True),
                max_pulls=data.get("max_pulls"),
            )
            logger.info(
                "[%s] completed=%d perf_kept=%d fetch_failed=%d",
                repo, completed, perf_kept, fetch_failed,
            )
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


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Repo specification: exactly one of --repos or --repos-file is required.
    # Flag names mirror the original Python pipeline's ``get_tasks_pipeline``
    # bash-friendly underscore style so ``run_pipeline_cpp.sh`` can dispatch
    # the cpp variant with the same flag shape as the Python variant.
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--repos", nargs="+",
                     help="GitHub org/repo strings to process")
    src.add_argument("--repos-file", type=Path,
                     help="File with one repo per line (#-comments allowed)")
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
    else:
        repos = list(args.repos)
    if not repos:
        parser.error("No repos resolved (--repos or --repos-file produced empty list)")

    logging.basicConfig(
        level=os.environ.get("SWEFF_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tokens = [t for t in args.tokens.split(",") if t.strip()]
    n_workers = max(1, len(tokens))
    chunk_size = max(1, len(repos) // n_workers)
    chunks = _chunkify(repos, chunk_size)

    data_pooled = [
        {
            "repos": chunk,
            "pulls_dir": str(args.path_prs),
            "output_dir": str(args.path_tasks),
            "resume": not args.no_resume,
            "max_pulls": args.max_pulls,
            "token": tokens[i % len(tokens)] if tokens else "",
        }
        for i, chunk in enumerate(chunks)
    ]

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
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
