#!/usr/bin/env python3
"""
Stage V: Execution-based Filtering (Statistical Significance).

Post-eval filter that applies the paper's criterion:
    μ_pre - μ_post > 2σ_post

Reads perf_summary.txt files from gold eval output, parses Before Mean/SD
and After Mean/SD, and retains only instances where the performance improvement
exceeds 2 standard deviations of the post-edit runtime noise.

Paper reference (Appendix C.5):
  "We retain only those instances where μ_pre − μ_post > 2σ_post"
  "This ensures the observed speedup is unlikely due to measurement noise."

Usage:
    python scripts/significance_filter.py \
        --dataset final-dataset.jsonl \
        --eval_dir logs/run_evaluation/RUN_ID/gold \
        --output significant-dataset.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_perf_summary(perf_summary_path: Path) -> Optional[dict]:
    """Parse perf_summary.txt to extract Before/After Mean and SD.
    
    The harness writes perf_summary.txt in this format:
        Before Mean: 0.3223
        Before SD: 0.0029
        After Mean: 0.0635
        After SD: 0.0004
        Improvement: 507.52%
    
    Also handles scientific notation (e.g., 1.23e-05) and the older inline format:
        Before Mean: 0.3223 (SD: 0.0029)
    """
    if not perf_summary_path.exists():
        return None
    
    text = perf_summary_path.read_text()
    
    # Number pattern: handles decimal and scientific notation
    _NUM = r'([\d.]+(?:[eE][+-]?\d+)?)'
    
    # Try separate-line format first (what the harness actually writes)
    before_mean_match = re.search(r'Before\s+Mean:\s*' + _NUM, text)
    before_sd_match = re.search(r'Before\s+SD:\s*' + _NUM, text)
    after_mean_match = re.search(r'After\s+Mean:\s*' + _NUM, text)
    after_sd_match = re.search(r'After\s+SD:\s*' + _NUM, text)
    
    if before_mean_match and before_sd_match and after_mean_match and after_sd_match:
        return {
            "before_mean": float(before_mean_match.group(1)),
            "before_sd": float(before_sd_match.group(1)),
            "after_mean": float(after_mean_match.group(1)),
            "after_sd": float(after_sd_match.group(1)),
        }
    
    # Fallback: try inline parenthetical format (legacy)
    before_match = re.search(
        r'Before\s+Mean:\s*' + _NUM + r'\s*\(SD:\s*' + _NUM + r'\)', text
    )
    after_match = re.search(
        r'After\s+Mean:\s*' + _NUM + r'\s*\(SD:\s*' + _NUM + r'\)', text
    )
    
    if before_match and after_match:
        return {
            "before_mean": float(before_match.group(1)),
            "before_sd": float(before_match.group(2)),
            "after_mean": float(after_match.group(1)),
            "after_sd": float(after_match.group(2)),
        }
    
    return None


def is_significant(perf: dict, sigma_threshold: float = 2.0) -> Tuple[bool, str]:
    """Apply paper criterion: μ_pre - μ_post > threshold * σ_post.
    
    Returns (is_significant, reason).
    """
    mu_pre = perf["before_mean"]
    mu_post = perf["after_mean"]
    sigma_post = perf["after_sd"]
    
    improvement = mu_pre - mu_post
    threshold = sigma_threshold * sigma_post
    
    if mu_post >= mu_pre:
        return False, f"no improvement (pre={mu_pre:.6f}, post={mu_post:.6f})"
    
    if sigma_post == 0:
        # Zero variance — if there's any improvement, it's significant
        if improvement > 0:
            return True, f"zero variance, improvement={improvement:.6f}"
        return False, "zero variance, no improvement"
    
    if improvement > threshold:
        snr = improvement / sigma_post
        return True, f"SNR={snr:.2f} > {sigma_threshold} (improvement={improvement:.6f}, 2σ_post={threshold:.6f})"
    else:
        snr = improvement / sigma_post if sigma_post > 0 else 0
        return False, f"SNR={snr:.2f} ≤ {sigma_threshold} (improvement={improvement:.6f}, 2σ_post={threshold:.6f})"


def main():
    parser = argparse.ArgumentParser(
        description="Filter instances by statistical significance of gold speedup (paper Stage V)."
    )
    parser.add_argument(
        "--dataset", required=True, help="Input dataset JSONL"
    )
    parser.add_argument(
        "--eval_dir", required=True, help="Gold eval output directory"
    )
    parser.add_argument(
        "--output", required=True, help="Output filtered dataset JSONL"
    )
    parser.add_argument(
        "--sigma", type=float, default=2.0,
        help="Sigma threshold for significance (default: 2.0, paper: 2.0)"
    )
    parser.add_argument(
        "--keep_all", action="store_true",
        help="Keep all instances (add significance flag instead of dropping)"
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
    logger.info(f"Significance threshold: {args.sigma}σ")

    # Apply significance filter
    stats = {
        "total": len(instances),
        "significant": 0,
        "not_significant": 0,
        "no_perf_data": 0,
        "sigma_threshold": args.sigma,
    }

    kept = []
    dropped = []
    details = []

    for inst in instances:
        instance_id = inst["instance_id"]
        perf_path = eval_dir / instance_id / "perf_summary.txt"
        
        perf = parse_perf_summary(perf_path)
        
        if perf is None:
            stats["no_perf_data"] += 1
            detail = {"instance_id": instance_id, "status": "no_perf_data", "reason": "perf_summary.txt missing or unparseable"}
            details.append(detail)
            if args.keep_all:
                inst["significance_status"] = "no_data"
                kept.append(inst)
            else:
                dropped.append(instance_id)
            continue
        
        sig, reason = is_significant(perf, args.sigma)
        
        speedup = perf["before_mean"] / perf["after_mean"] if perf["after_mean"] > 0 else float("inf")
        
        detail = {
            "instance_id": instance_id,
            "status": "significant" if sig else "not_significant",
            "reason": reason,
            "before_mean": perf["before_mean"],
            "after_mean": perf["after_mean"],
            "before_sd": perf["before_sd"],
            "after_sd": perf["after_sd"],
            "speedup": round(speedup, 4),
        }
        details.append(detail)
        
        if sig:
            stats["significant"] += 1
            if args.keep_all:
                inst["significance_status"] = "significant"
            inst["gold_speedup"] = speedup
            kept.append(inst)
        else:
            stats["not_significant"] += 1
            if args.keep_all:
                inst["significance_status"] = "not_significant"
                inst["gold_speedup"] = speedup
                kept.append(inst)
            else:
                dropped.append(instance_id)

    # Write output
    with open(output_path, "w") as f:
        for inst in kept:
            f.write(json.dumps(inst) + "\n")

    # Write detailed stats
    stats_path = output_path.parent / f"{output_path.stem}_significance_stats.json"
    stats["kept"] = len(kept)
    stats["dropped"] = len(dropped)
    stats["dropped_ids"] = dropped
    stats["details"] = details

    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Results:")
    logger.info(f"  Significant:       {stats['significant']}/{stats['total']}")
    logger.info(f"  Not significant:   {stats['not_significant']}/{stats['total']}")
    logger.info(f"  No perf data:      {stats['no_perf_data']}/{stats['total']}")
    logger.info(f"  Kept:              {len(kept)} → {output_path}")
    if dropped:
        logger.info(f"  Dropped:           {len(dropped)} instances")

    # Significance filter yield from paper: depends on workload quality
    # Paper had 47% non-significant with LLM workloads
    sig_rate = (stats["significant"] / (stats["total"] - stats["no_perf_data"]) * 100) if (stats["total"] - stats["no_perf_data"]) > 0 else 0
    logger.info(f"  Significance rate: {sig_rate:.1f}% (paper target: >50% with manual workloads)")


if __name__ == "__main__":
    main()
