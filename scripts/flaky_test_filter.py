#!/usr/bin/env python3
"""
Stage V Supplement: Flaky Test Detection.

Runs correctness tests N times per instance and identifies tests that produce
inconsistent results (flaky). Removes flaky tests from covering_tests lists.

Paper reference (Appendix C.5):
  "We run correctness tests 10 times to filter flaky tests."

This script post-processes the results of N correctness runs (produced by
the shell pipeline running eval N times with different run suffixes).

Usage:
    python scripts/flaky_test_filter.py \
        --dataset coverage-filtered.jsonl \
        --eval_dirs logs/run_evaluation/RUN_ID_flaky_1/gold \
                    logs/run_evaluation/RUN_ID_flaky_2/gold \
                    ... \
        --output flaky-filtered.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tarfile
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_test_results(eval_dir: Path, instance_id: str) -> Optional[dict]:
    """Load test results from a single eval run.
    
    Tries covering_test_status.json first, then test_status.tar.
    Returns dict of {test_name: "PASSED"|"FAILED"|"ERROR"}.
    """
    # Try covering_test_status.json
    ct_status = eval_dir / instance_id / "covering_test_status.json"
    if ct_status.exists():
        try:
            data = json.loads(ct_status.read_text())
            if isinstance(data, dict) and data:
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Try correctness_output.txt — parse pytest output
    corr_output = eval_dir / instance_id / "correctness_output.txt"
    if corr_output.exists():
        text = corr_output.read_text()
        results = {}
        for line in text.splitlines():
            # pytest output format: "PASSED tests/test_foo.py::test_bar"
            line = line.strip()
            if line.startswith("PASSED "):
                test_name = line[7:].strip()
                results[test_name] = "PASSED"
            elif line.startswith("FAILED "):
                test_name = line[7:].strip()
                results[test_name] = "FAILED"
            elif line.startswith("ERROR "):
                test_name = line[6:].strip()
                results[test_name] = "ERROR"
        if results:
            return results
    
    return None


def detect_flaky_tests(
    eval_dirs: list,
    instance_id: str,
) -> tuple:
    """Detect flaky tests across N runs.
    
    Returns (flaky_tests: set, stable_tests: set, total_runs: int).
    A test is flaky if it doesn't produce the same result across ALL runs.
    """
    all_results = []
    for eval_dir in eval_dirs:
        results = load_test_results(eval_dir, instance_id)
        if results:
            all_results.append(results)
    
    if not all_results:
        return set(), set(), 0
    
    # Collect all test names across runs
    all_test_names = set()
    for results in all_results:
        all_test_names.update(results.keys())
    
    flaky = set()
    stable = set()
    
    for test_name in all_test_names:
        outcomes = set()
        for results in all_results:
            outcome = results.get(test_name, "MISSING")
            outcomes.add(outcome)
        
        if len(outcomes) == 1 and "MISSING" not in outcomes:
            # Consistent across all runs
            stable.add(test_name)
        else:
            # Inconsistent or missing in some runs
            flaky.add(test_name)
    
    return flaky, stable, len(all_results)


def main():
    parser = argparse.ArgumentParser(
        description="Detect and remove flaky tests from covering_tests (paper Stage V)."
    )
    parser.add_argument(
        "--dataset", required=True, help="Input dataset JSONL (with covering_tests)"
    )
    parser.add_argument(
        "--eval_dirs", nargs="+", required=True,
        help="Gold eval output directories from N correctness runs"
    )
    parser.add_argument(
        "--output", required=True, help="Output filtered dataset JSONL"
    )
    parser.add_argument(
        "--min_runs", type=int, default=3,
        help="Minimum number of successful runs required to trust flaky detection (default: 3)"
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    eval_dirs = [Path(d) for d in args.eval_dirs]
    output_path = Path(args.output)

    if not dataset_path.exists():
        logger.error(f"Dataset not found: {dataset_path}")
        sys.exit(1)

    valid_dirs = [d for d in eval_dirs if d.exists()]
    if not valid_dirs:
        logger.error(f"No valid eval directories found")
        sys.exit(1)
    logger.info(f"Found {len(valid_dirs)}/{len(eval_dirs)} valid eval directories")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load dataset
    instances = []
    with open(dataset_path) as f:
        for line in f:
            if line.strip():
                instances.append(json.loads(line))

    logger.info(f"Loaded {len(instances)} instances from {dataset_path}")
    logger.info(f"Min runs for flaky detection: {args.min_runs}")

    # Detect flaky tests per instance
    stats = {
        "total": len(instances),
        "instances_with_flaky": 0,
        "instances_all_flaky": 0,
        "total_flaky_tests": 0,
        "total_stable_tests": 0,
        "instances_insufficient_runs": 0,
    }

    kept = []
    dropped = []
    details = []

    for inst in instances:
        instance_id = inst["instance_id"]
        covering_tests = inst.get("covering_tests", [])
        
        if not covering_tests:
            # No covering tests to filter
            kept.append(inst)
            continue
        
        flaky, stable, num_runs = detect_flaky_tests(valid_dirs, instance_id)
        
        if num_runs < args.min_runs:
            stats["instances_insufficient_runs"] += 1
            detail = {
                "instance_id": instance_id,
                "status": "insufficient_runs",
                "runs": num_runs,
                "min_required": args.min_runs,
            }
            details.append(detail)
            # Keep instance as-is if we don't have enough runs to judge
            kept.append(inst)
            continue
        
        # Filter covering_tests to remove flaky ones
        # covering_tests may be test file paths or test IDs
        original_count = len(covering_tests)
        filtered_tests = []
        removed_tests = []
        
        for test in covering_tests:
            # Exact match only — do NOT use startswith() prefix matching.
            # Prefix matching removes ALL tests from a file when only one is flaky.
            is_flaky = test in flaky
            
            if is_flaky:
                removed_tests.append(test)
            else:
                filtered_tests.append(test)
        
        detail = {
            "instance_id": instance_id,
            "status": "filtered" if removed_tests else "clean",
            "original_covering_tests": original_count,
            "remaining_covering_tests": len(filtered_tests),
            "flaky_removed": len(removed_tests),
            "removed_tests": removed_tests[:10],  # Cap for readability
            "runs_analyzed": num_runs,
        }
        details.append(detail)
        
        if removed_tests:
            stats["instances_with_flaky"] += 1
            stats["total_flaky_tests"] += len(removed_tests)
        
        stats["total_stable_tests"] += len(filtered_tests)
        
        if filtered_tests:
            inst["covering_tests"] = filtered_tests
            if removed_tests:
                inst["flaky_tests_removed"] = removed_tests
            kept.append(inst)
        else:
            # ALL covering tests are flaky — drop instance
            stats["instances_all_flaky"] += 1
            dropped.append(instance_id)

    # Write output
    with open(output_path, "w") as f:
        for inst in kept:
            f.write(json.dumps(inst) + "\n")

    # Write stats
    stats_path = output_path.parent / f"{output_path.stem}_flaky_stats.json"
    stats["kept"] = len(kept)
    stats["dropped"] = len(dropped)
    stats["dropped_ids"] = dropped
    stats["details"] = details

    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Results:")
    logger.info(f"  Instances with flaky tests: {stats['instances_with_flaky']}/{stats['total']}")
    logger.info(f"  Instances ALL flaky:         {stats['instances_all_flaky']}/{stats['total']}")
    logger.info(f"  Total flaky tests removed:   {stats['total_flaky_tests']}")
    logger.info(f"  Total stable tests kept:     {stats['total_stable_tests']}")
    logger.info(f"  Insufficient runs:           {stats['instances_insufficient_runs']}")
    logger.info(f"  Kept:                        {len(kept)} → {output_path}")
    if dropped:
        logger.info(f"  Dropped (all flaky):         {len(dropped)} instances")


if __name__ == "__main__":
    main()
