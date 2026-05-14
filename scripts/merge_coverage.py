#!/usr/bin/env python3
"""
Stage III Post-Processing: Merge coverage results into dataset JSONL.

Reads covering_tests.txt from eval output directories, injects them into
the dataset instances, and drops instances without any covering tests.

Paper reference (Appendix C.3):
  "We keep only those PRs where at least one unit test intersects with the edit."

Usage:
    python scripts/merge_coverage.py \
        --dataset enriched.jsonl \
        --eval_dir logs/run_evaluation/RUN_ID/gold \
        --output filtered_with_coverage.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_covering_tests(eval_dir: Path, instance_id: str) -> Optional[list]:
    """Load covering_tests.txt for a given instance from eval output."""
    # Try direct path: eval_dir/instance_id/covering_tests.txt
    ct_file = eval_dir / instance_id / "covering_tests.txt"
    if ct_file.exists():
        text = ct_file.read_text().strip()
        if text:
            return [t.strip() for t in text.splitlines() if t.strip()]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Merge coverage results into dataset and filter instances without coverage."
    )
    parser.add_argument(
        "--dataset", required=True, help="Input dataset JSONL (enriched/versioned)"
    )
    parser.add_argument(
        "--eval_dir", required=True, help="Eval output directory (e.g., logs/run_evaluation/RUN_ID/gold)"
    )
    parser.add_argument(
        "--output", required=True, help="Output filtered dataset JSONL"
    )
    parser.add_argument(
        "--keep_all", action="store_true",
        help="Keep all instances (mark empty coverage instead of dropping)"
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    eval_dir = Path(args.eval_dir)
    output_path = Path(args.output)

    if not dataset_path.exists():
        logger.error(f"Dataset not found: {dataset_path}")
        sys.exit(1)

    if not eval_dir.exists():
        logger.error(f"Eval directory not found: {eval_dir}")
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load dataset
    instances = []
    with open(dataset_path) as f:
        for line in f:
            if line.strip():
                instances.append(json.loads(line))

    logger.info(f"Loaded {len(instances)} instances from {dataset_path}")

    # Merge coverage data
    stats = {
        "total": len(instances),
        "with_coverage": 0,
        "without_coverage": 0,
        "total_covering_tests": 0,
    }

    kept = []
    dropped = []

    for inst in instances:
        instance_id = inst["instance_id"]
        covering_tests = load_covering_tests(eval_dir, instance_id)

        if covering_tests:
            inst["covering_tests"] = covering_tests
            stats["with_coverage"] += 1
            stats["total_covering_tests"] += len(covering_tests)
            kept.append(inst)
        else:
            stats["without_coverage"] += 1
            if args.keep_all:
                inst["covering_tests"] = []
                kept.append(inst)
            else:
                dropped.append(instance_id)

    # Write output
    with open(output_path, "w") as f:
        for inst in kept:
            f.write(json.dumps(inst) + "\n")

    # Write stats
    stats_path = output_path.parent / f"{output_path.stem}_coverage_stats.json"
    stats["kept"] = len(kept)
    stats["dropped"] = len(dropped)
    stats["dropped_ids"] = dropped
    stats["avg_covering_tests"] = (
        stats["total_covering_tests"] / stats["with_coverage"]
        if stats["with_coverage"] > 0
        else 0
    )

    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Results:")
    logger.info(f"  With coverage:    {stats['with_coverage']}/{stats['total']}")
    logger.info(f"  Without coverage: {stats['without_coverage']}/{stats['total']}")
    logger.info(f"  Avg tests/inst:   {stats['avg_covering_tests']:.1f}")
    logger.info(f"  Kept:             {len(kept)} → {output_path}")
    if dropped:
        logger.info(f"  Dropped:          {len(dropped)} instances")
        for iid in dropped[:10]:
            logger.info(f"    - {iid}")
        if len(dropped) > 10:
            logger.info(f"    ... and {len(dropped) - 10} more")

    # Paper yield: 9,257 → 1,041 = 88.8% dropout
    dropout_pct = (stats["without_coverage"] / stats["total"] * 100) if stats["total"] > 0 else 0
    logger.info(f"  Dropout rate:     {dropout_pct:.1f}% (paper: ~88.8%)")


if __name__ == "__main__":
    main()
