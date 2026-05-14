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

"""C++ analog of ``flaky_test_filter.py`` (Paper App. C.5, Stage V).

Reads N correctness-run logs for each instance, parses test statuses via
``log_parsers_cpp``, drops tests whose status is not stable across runs.

Input layout:
    <runs_root>/run_<i>/<instance_id>/test_output.txt   (for i in 0..N-1)

Output:
    Updates each instance's ``PASS_TO_PASS`` / ``FAIL_TO_PASS`` lists in
    ``<instances_path>`` to retain only stable tests. Writes the filtered
    dataset to ``<output_path>``.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import sys
from pathlib import Path

from swefficiency.harness.log_parsers_cpp import (
    MAP_REPO_TO_PARSER_CPP,
    parse_log_cpp_best_effort,
)

logger = logging.getLogger(__name__)


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _read_status_map(repo: str, log_path: Path) -> dict[str, str]:
    if not log_path.exists():
        return {}
    parser = MAP_REPO_TO_PARSER_CPP.get(repo, parse_log_cpp_best_effort)
    try:
        return parser(log_path.read_text(errors="ignore"))
    except Exception as e:
        logger.warning("Parser failed for %s: %s", log_path, e)
        return {}


def collect_statuses_across_runs(
    runs_root: Path,
    instance_id: str,
    repo: str,
    n_runs: int,
) -> dict[str, list[str]]:
    """Return ``{test_name: [status_run_0, status_run_1, ...]}`` (missing -> ``"MISSING"``)."""
    per_run: list[dict[str, str]] = []
    for i in range(n_runs):
        log_path = runs_root / f"run_{i}" / instance_id / "test_output.txt"
        per_run.append(_read_status_map(repo, log_path))

    all_tests: set[str] = set()
    for sm in per_run:
        all_tests.update(sm.keys())

    out: dict[str, list[str]] = {}
    for t in sorted(all_tests):
        out[t] = [sm.get(t, "MISSING") for sm in per_run]
    return out


def filter_flaky_tests(
    statuses: dict[str, list[str]],
    min_consistency: float = 1.0,
) -> tuple[set[str], dict[str, dict[str, int]]]:
    """Return ``(stable_tests, per_test_stats)``.

    A test is stable iff a single status occurs in >= ``min_consistency``
    fraction of the runs (default 1.0 = unanimous).
    """
    stable: set[str] = set()
    stats: dict[str, dict[str, int]] = {}
    for test, run_statuses in statuses.items():
        counter = collections.Counter(run_statuses)
        stats[test] = dict(counter)
        n = len(run_statuses)
        if n == 0:
            continue
        top_status, top_count = counter.most_common(1)[0]
        if top_status == "MISSING":
            continue
        if top_count / n >= min_consistency:
            stable.add(test)
    return stable, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances-path", required=True, type=Path)
    parser.add_argument("--runs-root", required=True, type=Path)
    parser.add_argument("--output-path", required=True, type=Path)
    parser.add_argument("--n-runs", type=int, default=10)
    parser.add_argument("--min-consistency", type=float, default=1.0)
    parser.add_argument(
        "--stats-output",
        type=Path,
        default=None,
        help="Optional path to write per-test stats JSON",
    )
    args = parser.parse_args(argv)

    instances = _load_jsonl(args.instances_path)
    logger.info("Loaded %d instances", len(instances))

    out_lines: list[str] = []
    stats_dump: dict[str, dict[str, dict[str, int]]] = {}
    n_kept = 0
    n_dropped = 0

    for inst in instances:
        iid = inst.get("instance_id")
        repo = inst.get("repo")
        if not iid or not repo:
            logger.warning("Skipping instance missing id/repo: %s", inst)
            continue

        statuses = collect_statuses_across_runs(
            args.runs_root, iid, repo, args.n_runs
        )
        stable, stats = filter_flaky_tests(statuses, args.min_consistency)
        stats_dump[iid] = stats

        original_p2p = set(inst.get("PASS_TO_PASS", []))
        original_f2p = set(inst.get("FAIL_TO_PASS", []))
        new_p2p = sorted(original_p2p & stable)
        new_f2p = sorted(original_f2p & stable)

        if not new_f2p:
            n_dropped += 1
            logger.info("Drop %s: zero stable FAIL_TO_PASS tests", iid)
            continue

        inst = dict(inst)
        inst["PASS_TO_PASS"] = new_p2p
        inst["FAIL_TO_PASS"] = new_f2p
        out_lines.append(json.dumps(inst))
        n_kept += 1

    args.output_path.write_text("\n".join(out_lines) + ("\n" if out_lines else ""))
    if args.stats_output:
        args.stats_output.write_text(json.dumps(stats_dump, indent=2))

    logger.info("Flaky filter: kept=%d dropped=%d", n_kept, n_dropped)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
