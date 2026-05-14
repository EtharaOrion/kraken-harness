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
Stage II: Performance PR Attribute Filter.

Implements the paper's 3-criterion filter (Appendix C.2, arxiv 2511.06090):

  Criterion 1: Does NOT contribute test changes.
               PRs that add/modify test files are dropped (makes dataset
               instance-wise disjoint from SWE-bench).

  Criterion 2: Contains performance keywords OR repo-specific performance labels.
               28 keywords specified in paper (PAPER_PERF_KEYWORDS).
               Optional --extended-keywords adds recall for 10k+ scale.

  Criterion 3: PR contains meaningful changes to the AST.
               Uses tree-sitter (preferred) or regex fallback to reject
               comment-only, docstring-only, and whitespace-only changes.

Pipeline interface (preserved):
  python -m swefficiency.perf_filter.attributes.filter \\
      --prs_path <prs.jsonl> \\
      --instances_path <instances.jsonl> \\
      --output_dir <output/>

Output: {stem}_attribute.jsonl in output_dir.
Downstream: feeds Stage 5 (versioning).

Design:
  - Fully dynamic: works for ANY Python repo without configuration.
  - Streaming: processes records one at a time for 100k+ scale.
  - No pandas dependency (avoids DataFrame OOM at 4M+ records).
  - Repo-specific label overrides still available but never required.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from swefficiency.perf_filter import utils
from swefficiency.perf_filter.attributes import constants
from swefficiency.perf_filter.attributes.ast_filter import has_meaningful_ast_changes

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# BACKWARD COMPATIBILITY
# ─────────────────────────────────────────────────────────────────────────────


def is_perf_pr(repo_name: str, pull: dict) -> bool:
    """Backward-compatible wrapper for Stage I early filtering.

    Used by build_dataset.py when --filter-early is passed.
    Delegates to the universal filter_base (Criterion 2 only).
    repo_name is accepted but ignored — filter is fully dynamic.
    """
    return constants.filter_base(pull)


# ─────────────────────────────────────────────────────────────────────────────
# CRITERION 1: Test change detection
# ─────────────────────────────────────────────────────────────────────────────


def has_test_changes(patch: str) -> bool:
    """Check if a patch modifies test files.

    Paper: "Drop if PR adds/modifies test files. This makes dataset
    instance-wise disjoint from SWE-bench."

    Benchmark files (asv_bench/, perf/) are NOT counted as test changes.
    """
    if not patch:
        return False

    edits = utils.extract_edits(patch)
    for source_path, dest_path, _ in edits:
        for fpath in (source_path, dest_path):
            if utils.is_test_file(fpath):
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# CRITERION 2: Performance keyword / label matching
# ─────────────────────────────────────────────────────────────────────────────


def has_perf_signal(pull: dict, use_extended: bool = False) -> bool:
    """Check if a PR has performance-related signals in metadata.

    Checks (in order):
      1. Negative title keywords → reject early (CI bumps, docs, typos)
      2. PR labels → any common performance label (dynamic, works for any repo)
      3. PR title/body → keyword match (paper's 28 or extended set)
      4. Word-boundary keywords ("fast" with \\b to avoid "FastAPI", "breakfast")
      5. Verbatim case-sensitive keywords ("PERF", "OPTIM")

    This is the UNIVERSAL filter — no repo-specific logic needed.
    """
    return constants.filter_base(pull, use_extended=use_extended)


def has_perf_content(problem_statement: str, use_extended: bool = False) -> bool:
    """Check if the problem statement / issue text contains perf keywords."""
    return constants.filter_content(problem_statement, use_extended=use_extended)


# ─────────────────────────────────────────────────────────────────────────────
# CONTENT EXCLUSION (non-meaningful changes)
# ─────────────────────────────────────────────────────────────────────────────


def is_non_code_only(patch: str) -> bool:
    """Check if ALL changed files are non-code (docs, CI, deps, configs, lock files).

    DESIGN NOTE: This is an intentional 4th criterion beyond the paper's 3.
    Rationale: At 10k+ scale, ~15-20% of PRs matching perf keywords are actually
    doc updates or CI config changes that mention "performance" in commit messages.
    Filtering these early saves expensive downstream Docker eval.
    Paper's Criterion 3 (AST validation) partially overlaps but misses CI/config files.

    Returns True if the PR should be EXCLUDED (no meaningful code changes).
    Returns False if at least one file has code changes worth evaluating.
    """
    if not patch:
        return True

    edits = utils.extract_edits(patch)
    if not edits:
        return True

    for source_path, dest_path, _ in edits:
        # Use dest_path as the canonical path (renamed files, new files)
        fpath = dest_path or source_path

        if utils.is_doc_file(fpath):
            continue
        if utils.is_ci_file(fpath):
            continue
        if utils.is_deps_file(fpath):
            continue
        if utils.is_config_file(fpath):
            continue
        if utils.has_lock_file_change(fpath):
            continue

        # At least one file is actual code
        return False

    # All files are non-code
    return True


# ─────────────────────────────────────────────────────────────────────────────
# COMBINED FILTER — applies all 3 criteria
# ─────────────────────────────────────────────────────────────────────────────


class FilterResult:
    """Decision record for one instance."""
    __slots__ = ("instance_id", "passed", "reason")

    def __init__(self, instance_id: str, passed: bool, reason: str):
        self.instance_id = instance_id
        self.passed = passed
        self.reason = reason


def apply_filter(instance: dict, pr_lookup: dict, use_extended: bool = False) -> FilterResult:
    """Apply the full 3-criterion filter to a single instance.

    Args:
        instance: Task instance dict (from build_dataset). Must have 'patch',
                  'pull_number', 'problem_statement', and 'instance_id'.
        pr_lookup: Dict mapping pull_number (int) → PR dict (with title, body, labels).
        use_extended: Use extended keyword set (broader recall for 10k+ scale).

    Returns:
        FilterResult with passed=True/False and reason string.
    """
    iid = instance.get("instance_id", "unknown")
    patch = instance.get("patch", "")
    pull_number = instance.get("pull_number")
    if pull_number is not None:
        try:
            pull_number = int(pull_number)  # Normalize to int for consistent lookup
        except (ValueError, TypeError):
            pass
    problem_statement = instance.get("problem_statement", "")

    # ── Criterion 1: reject PRs that modify test files ──
    if has_test_changes(patch):
        return FilterResult(iid, False, "criterion1_test_changes")

    # ── Content exclusion: reject doc-only, CI-only, deps-only, etc. ──
    if is_non_code_only(patch):
        return FilterResult(iid, False, "non_code_only")

    # ── Criterion 2: must have perf signal in PR metadata OR problem statement ──
    pr = pr_lookup.get(pull_number)
    has_pr_signal = has_perf_signal(pr, use_extended=use_extended) if pr else False
    has_text_signal = has_perf_content(problem_statement, use_extended=use_extended)

    if not has_pr_signal and not has_text_signal:
        return FilterResult(iid, False, "criterion2_no_perf_keywords")

    # ── Criterion 3: meaningful AST changes ──
    if not has_meaningful_ast_changes(patch):
        return FilterResult(iid, False, "criterion3_no_ast_changes")

    return FilterResult(iid, True, "passed")


# ─────────────────────────────────────────────────────────────────────────────
# PR LOOKUP BUILDER
# ─────────────────────────────────────────────────────────────────────────────


def build_pr_lookup(prs_path: str) -> dict:
    """Build pull_number → PR dict mapping from PRs JSONL.

    Streams the file for memory efficiency. Only keeps merged PRs.
    """
    lookup = {}
    total = 0
    merged = 0
    for pr in utils.stream_jsonl(prs_path):
        total += 1
        # Only keep merged PRs
        if pr.get("merged_at"):
            pull_number = pr.get("number")
            if pull_number is not None:
                lookup[int(pull_number)] = pr  # Normalize to int for consistent lookups
                merged += 1

    logger.info(f"PR lookup: {merged} merged of {total} total from {prs_path}")
    return lookup


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — streaming pipeline
# ─────────────────────────────────────────────────────────────────────────────


def main(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Output filename follows existing convention
    output_filename = Path(args.instances_path).stem.split(".")[0] + "_attribute.jsonl"
    output_path = output_dir / output_filename
    metrics_path = output_dir / (Path(args.instances_path).stem.split(".")[0] + "_filter_metrics.json")

    use_extended = getattr(args, "extended_keywords", False)

    # Build PR lookup (streaming, only merged)
    logger.info(f"Building PR lookup from {args.prs_path}")
    pr_lookup = build_pr_lookup(args.prs_path)
    logger.info(f"PR lookup ready: {len(pr_lookup)} merged PRs")

    # Stream instances and apply filter
    start_time = time.time()
    metrics = {
        "total": 0,
        "passed": 0,
        "rejected": {
            "criterion1_test_changes": 0,
            "criterion2_no_perf_keywords": 0,
            "criterion3_no_ast_changes": 0,
            "non_code_only": 0,
        },
        "use_extended_keywords": use_extended,
        "prs_path": str(args.prs_path),
        "instances_path": str(args.instances_path),
    }

    with open(str(output_path), "w") as output:
        for instance in utils.stream_jsonl(args.instances_path):
            metrics["total"] += 1

            result = apply_filter(instance, pr_lookup, use_extended=use_extended)

            if result.passed:
                metrics["passed"] += 1
                print(json.dumps(instance), file=output, flush=False)
            else:
                if result.reason in metrics["rejected"]:
                    metrics["rejected"][result.reason] += 1
                else:
                    metrics["rejected"][result.reason] = 1

            # Progress log every 10k
            if metrics["total"] % 10000 == 0:
                elapsed = time.time() - start_time
                rate = metrics["total"] / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Processed {metrics['total']:,} instances "
                    f"({metrics['passed']:,} passed, {rate:.0f}/sec)"
                )

    elapsed = time.time() - start_time
    metrics["elapsed_seconds"] = round(elapsed, 2)

    # Write metrics
    with open(str(metrics_path), "w") as f:
        json.dump(metrics, f, indent=2)

    # Summary
    total = metrics["total"]
    passed = metrics["passed"]
    rejected = metrics["rejected"]

    print(f"\n{'='*60}")
    print(f"Stage II Filter Results")
    print(f"{'='*60}")
    print(f"Total instances:       {total:>8,}")
    print(f"Passed (kept):         {passed:>8,}  ({100*passed/total:.1f}%)" if total else "")
    print(f"{'─'*60}")
    print(f"Rejected breakdown:")
    for reason, count in sorted(rejected.items(), key=lambda x: -x[1]):
        pct = 100 * count / total if total else 0
        print(f"  {reason:<35} {count:>8,}  ({pct:.1f}%)")
    print(f"{'─'*60}")
    print(f"Keywords mode:         {'extended' if use_extended else 'paper (28 exact)'}")
    print(f"Elapsed:               {elapsed:.1f}s")
    print(f"Output:                {output_path}")
    print(f"Metrics:               {metrics_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Stage II: Performance PR Attribute Filter (paper-aligned, dynamic)"
    )
    parser.add_argument(
        "--prs_path", type=str, required=True,
        help="Path to PRs JSONL file (from Stage I scraping)."
    )
    parser.add_argument(
        "--instances_path", type=str, required=True,
        help="Path to candidate task instances JSONL (from build_dataset)."
    )
    parser.add_argument(
        "--output_dir", type=str, required=True,
        help="Directory to save filtered output."
    )
    parser.add_argument(
        "--extended-keywords", action="store_true", default=False,
        help="Use extended keyword set (paper 28 + extras) for broader recall at scale."
    )

    args = parser.parse_args()
    main(args)
