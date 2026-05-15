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
Report generation for SWE-fficiency evaluation results.
"""

import json
import multiprocessing
from functools import partial
from pathlib import Path
from typing import Dict, List, Tuple

import datasets
import pandas as pd
from tqdm import tqdm

from swefficiency.harness.log_parsers import MAP_REPO_TO_PARSER


def parse_perf_summary(perf_summary: str) -> Dict[str, float]:
    """Parse performance summary file content.

    Expected format (4 lines, each with 'label: value'):
        Before Mean: <float>
        Before Std: <float>
        After Mean: <float>
        After Std: <float>

    Returns default values (all zeros, 0% improvement) on malformed input.
    """
    try:
        perf_lines = perf_summary.strip().splitlines()
        if len(perf_lines) < 4:
            raise ValueError(
                f"Expected at least 4 lines, got {len(perf_lines)}"
            )

        before_mean = float(perf_lines[0].split(":")[1].strip())
        before_std = float(perf_lines[1].split(":")[1].strip())
        after_mean = float(perf_lines[2].split(":")[1].strip())
        after_std = float(perf_lines[3].split(":")[1].strip())
    except (IndexError, ValueError) as e:
        print(f"Warning: Failed to parse perf_summary: {e}")
        return {
            "before_mean": 0.0,
            "after_mean": 0.0,
            "before_std": 0.0,
            "after_std": 0.0,
            "improvement": 0.0,
        }

    # Positive improvement == faster after the patch (after_mean < before_mean).
    # The operands were reversed, so every speedup was reported as a negative
    # percentage and every regression as a positive one.
    improvement = (
        (before_mean - after_mean) / before_mean * 100
        if before_mean != 0
        else 0.0
    )

    return {
        "before_mean": before_mean,
        "after_mean": after_mean,
        "before_std": before_std,
        "after_std": after_std,
        "improvement": improvement,
    }


def get_number_of_patch_modified_lines(git_patch_text: str) -> int:
    """Count the number of modified lines in a git patch text."""
    num_lines = 0
    for line in git_patch_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            num_lines += 1
        if line.startswith("-") and not line.startswith("---"):
            num_lines += 1
    return num_lines


def evaluate_instance(
    instance: dict, gold_run: Path, pred_run: Path, use_correctness_files: bool = True
) -> Dict:
    """
    Evaluate a single instance comparing gold and prediction runs.

    Args:
        instance: Dataset instance with instance_id, PASS_TO_PASS, patch, repo
        gold_run: Path to gold run directory
        pred_run: Path to prediction run directory
        use_correctness_files: Whether to use pre-computed correctness files

    Returns:
        Dictionary with evaluation metrics for this instance
    """
    instance_id = instance["instance_id"]
    pass_to_pass = instance["PASS_TO_PASS"]
    if isinstance(pass_to_pass, str):
        pass_to_pass = json.loads(pass_to_pass)

    gold_run_entry = gold_run / instance_id / "perf_summary.txt"
    pred_run_entry = pred_run / instance_id / "perf_summary.txt"

    # Track data quality flags
    data_quality_flags = []
    has_pred_perf = pred_run_entry.exists()
    has_gold_perf = gold_run_entry.exists()

    # Compute prediction speedup ratio.
    if has_pred_perf:
        pred_perf_info = parse_perf_summary(pred_run_entry.read_text())
        after_mean = pred_perf_info["after_mean"]
        pred_speedup_ratio = (
            pred_perf_info["before_mean"] / after_mean if after_mean != 0 else 1.0
        )
    else:
        pred_speedup_ratio = 1.0  # No speedup if no prediction run exists
        # Check if patch was corrupt (couldn't be applied)
        patch_diff = pred_run / instance_id / "patch.diff"
        if patch_diff.exists():
            patch_text = patch_diff.read_text()
            if "error:" in patch_text.lower() or len(patch_text.strip()) == 0:
                data_quality_flags.append("CORRUPT_PATCH")
            else:
                data_quality_flags.append("NO_PERF_DATA")
        else:
            data_quality_flags.append("NO_PERF_DATA")

    # Compute gold speedup ratio.
    if has_gold_perf:
        gold_perf_info = parse_perf_summary(gold_run_entry.read_text())
        after_mean = gold_perf_info["after_mean"]
        gold_speedup_ratio = (
            gold_perf_info["before_mean"] / after_mean if after_mean != 0 else 1.0
        )
    else:
        gold_speedup_ratio = 1.0
        gold_perf_info = {"before_mean": 0.0}

    # Flag gold slowdowns
    if gold_speedup_ratio < 1.0:
        data_quality_flags.append("GOLD_SLOWDOWN")

    num_modified_lines = get_number_of_patch_modified_lines(instance["patch"])

    # If there are no PASS_TO_PASS tests, correctness is vacuously 1.0.
    # This handles instances where covering_tests point to non-test files
    # (e.g. CI configs, requirements files) and no Python tests exist.
    # Standard practice: SWE-bench treats empty PASS_TO_PASS as vacuously correct.
    if not pass_to_pass:
        data_quality_flags.append("UNVERIFIABLE_CORRECTNESS")
        return {
            "instance_id": instance_id,
            "raw_pred_speedup_ratio": pred_speedup_ratio,
            "pred_speedup_ratio": pred_speedup_ratio,
            "gold_speedup_ratio": gold_speedup_ratio,
            "human_speedup_ratio": (
                pred_speedup_ratio / gold_speedup_ratio
                if gold_speedup_ratio != 0
                else 0
            ),
            "correctness": 1.0,
            "correctness_pct": 1.0,
            "pre_edit_runtime": gold_perf_info["before_mean"],
            "patch_length": num_modified_lines,
            "has_pred_perf": has_pred_perf,
            "data_quality": "|".join(data_quality_flags) if data_quality_flags else "PERF_ONLY",
        }

    # Check that pass to pass tests are still passing.
    correctness_dir = pred_run / instance_id / "raw_correctness_output"

    if not correctness_dir.exists():
        data_quality_flags.append("NO_CORRECTNESS_DATA")
        return {
            "instance_id": instance_id,
            "raw_pred_speedup_ratio": pred_speedup_ratio,
            "pred_speedup_ratio": 1.0,
            "gold_speedup_ratio": gold_speedup_ratio,
            "human_speedup_ratio": (
                1.0 / gold_speedup_ratio if gold_speedup_ratio != 0 else 0
            ),
            "correctness": 0.0,
            "correctness_pct": 0.0,
            "pre_edit_runtime": gold_perf_info["before_mean"],
            "patch_length": num_modified_lines,
            "has_pred_perf": has_pred_perf,
            "data_quality": "|".join(data_quality_flags) if data_quality_flags else "NO_CORRECTNESS_DATA",
        }

    if not use_correctness_files:
        pred_statuses = {}
        for test_output in correctness_dir.glob("*.txt"):
            test_output_text = test_output.read_text()
            pred_statuses.update(
                MAP_REPO_TO_PARSER[instance["repo"]](test_output_text)
            )
    else:
        pred_statuses = json.loads(
            (pred_run / instance_id / "covering_test_status.json").read_text()
        )

    passed_tests = []
    for test in pass_to_pass:
        if "PASS" in pred_statuses.get(test, ""):
            passed_tests.append(test)

    passed_tests = set(passed_tests)
    correctness_pct = len(passed_tests) / len(pass_to_pass) if pass_to_pass else 1.0
    adjusted_pred_speedup_ratio = 1.0 if correctness_pct != 1.0 else pred_speedup_ratio

    # Determine data quality for verified instances
    if correctness_pct == 1.0 and has_pred_perf:
        quality = "VERIFIED"
    elif not data_quality_flags:
        quality = "VERIFIED"
    else:
        quality = "|".join(data_quality_flags)

    return {
        "instance_id": instance_id,
        "raw_pred_speedup_ratio": pred_speedup_ratio,
        "pred_speedup_ratio": adjusted_pred_speedup_ratio,
        "gold_speedup_ratio": gold_speedup_ratio,
        "human_speedup_ratio": (
            adjusted_pred_speedup_ratio / gold_speedup_ratio
            if gold_speedup_ratio != 0
            else 0
        ),
        "correctness": 0.0 if correctness_pct != 1.0 else 1.0,
        "correctness_pct": correctness_pct,
        "pre_edit_runtime": gold_perf_info["before_mean"],
        "patch_length": num_modified_lines,
        "has_pred_perf": has_pred_perf,
        "data_quality": quality,
    }


def compute_performance_breakdown(df: pd.DataFrame) -> Dict:
    """
    Compute performance breakdown metrics from evaluation results.

    Instances without actual perf data (has_pred_perf=False) are EXCLUDED from
    the 4-way category proportions and overall score. They are reported separately
    as 'proportion_excluded'. This prevents fake SR=1.0 defaults from polluting
    the category breakdown.

    Args:
        df: DataFrame with evaluation results

    Returns:
        Dictionary with breakdown metrics
    """
    total_instances = len(df)
    if total_instances == 0:
        return {
            "total_instances": 0,
            "overall_score": 0.0,
            "proportion_incorrect": 0.0,
            "proportion_correct_but_no_speedup": 0.0,
            "proportion_correct_with_speedup_but_human_no_speedup": 0.0,
            "proportion_human_speedup_or_better": 0.0,
            "proportion_excluded": 0.0,
        }

    # Separate evaluable instances (has actual perf data) from excluded ones
    has_perf_col = "has_pred_perf" in df.columns
    if has_perf_col:
        evaluable = df[df["has_pred_perf"] == True]
        excluded = df[df["has_pred_perf"] == False]
    else:
        evaluable = df
        excluded = df.iloc[0:0]  # empty

    effective_n = len(evaluable)
    n_excluded = len(excluded)

    # Overall score computed ONLY over evaluable instances
    if effective_n > 0:
        eval_floored = evaluable["human_speedup_ratio"].clip(lower=0.001)
        overall_score = effective_n / (1 / eval_floored).sum()
    else:
        overall_score = 0.0

    # 4-way category proportions computed ONLY over evaluable instances
    # Then divided by total_instances so all 5 proportions (4 + excluded) sum to 1.0
    incorrect_instances = (evaluable["correctness"] < 1.0).sum() if effective_n > 0 else 0

    correct_but_no_speedup = (
        (evaluable["correctness"] == 1.0) & (evaluable["raw_pred_speedup_ratio"] < 1.0)
    ).sum() if effective_n > 0 else 0

    correct_with_speedup_but_human_no_speedup = (
        (evaluable["correctness"] == 1.0)
        & (evaluable["raw_pred_speedup_ratio"] >= 1.0)
        & (evaluable["human_speedup_ratio"] < 1.0)
    ).sum() if effective_n > 0 else 0

    human_speedup_or_better = (
        (evaluable["correctness"] == 1.0)
        & (evaluable["raw_pred_speedup_ratio"] >= 1.0)
        & (evaluable["human_speedup_ratio"] >= 1.0)
    ).sum() if effective_n > 0 else 0

    result = {
        "total_instances": total_instances,
        "effective_n": effective_n,
        "instances_excluded": n_excluded,
        "overall_score": round(overall_score, 4),
        "proportion_incorrect": round(incorrect_instances / total_instances, 4),
        "proportion_correct_but_no_speedup": round(
            correct_but_no_speedup / total_instances, 4
        ),
        "proportion_correct_with_speedup_but_human_no_speedup": round(
            correct_with_speedup_but_human_no_speedup / total_instances, 4
        ),
        "proportion_human_speedup_or_better": round(
            human_speedup_or_better / total_instances, 4
        ),
        "proportion_excluded": round(n_excluded / total_instances, 4),
    }

    # Count correctness-verified vs unverifiable
    verified_correct = 0
    unverifiable_correct = 0
    if "data_quality" in df.columns:
        verified_correct = len(df[
            (df["correctness"] == 1.0) &
            (~df["data_quality"].str.contains("UNVERIFIABLE", na=False)) &
            (~df["data_quality"].str.contains("PERF_ONLY", na=False)) &
            (~df["data_quality"].str.contains("NO_PERF", na=False)) &
            (~df["data_quality"].str.contains("CORRUPT", na=False))
        ])
        unverifiable_correct = len(df[
            df["data_quality"].str.contains("UNVERIFIABLE", na=False)
        ])

    result["correctness_verified_count"] = verified_correct
    result["correctness_unverifiable_count"] = unverifiable_correct
    result["caveats"] = []
    if n_excluded > 0:
        result["caveats"].append(
            f"{n_excluded} instance(s) excluded from score — no perf data "
            f"(corrupt patch or eval failure). NOT included in overall_score or category proportions."
        )
    if unverifiable_correct > 0:
        result["caveats"].append(
            f"{unverifiable_correct} instance(s) have empty PASS_TO_PASS tests; "
            f"correctness is vacuously 1.0 (standard SWE-bench practice, disclosed)"
        )
    gold_slowdowns = (df["gold_speedup_ratio"] < 1.0).sum()
    if gold_slowdowns > 0:
        result["caveats"].append(
            f"{gold_slowdowns} instance(s) where gold expert patch actually slows code down; "
            f"model can 'beat expert' by regressing less"
        )

    return result


def generate_report(
    gold_run: Path,
    pred_run: Path,
    output_dir: Path,
    num_workers: int = 4,
    dataset_name: str = "swefficiency/swefficiency",
) -> Tuple[pd.DataFrame, Dict, Path, Path]:
    """
    Generate evaluation report comparing gold and prediction runs.

    Args:
        gold_run: Path to gold run directory
        pred_run: Path to prediction run directory
        output_dir: Output directory for reports
        num_workers: Number of parallel workers
        dataset_name: HuggingFace dataset name

    Returns:
        DataFrame with evaluation results
    """
    # Support local JSONL files as dataset source
    dataset_path = Path(dataset_name)
    if dataset_path.exists() and dataset_path.suffix == ".jsonl":
        import json as _json
        with open(dataset_path) as _f:
            ds = [_json.loads(line) for line in _f if line.strip()]
    else:
        ds = datasets.load_dataset(dataset_name, split="test")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_name = pred_run.name

    worker = partial(evaluate_instance, gold_run=gold_run, pred_run=pred_run)
    with multiprocessing.Pool(num_workers) as pool:
        results = list(
            tqdm(
                pool.imap(worker, ds, chunksize=1),
                total=len(ds),
                desc="Evaluating instances",
            )
        )

    results_df = pd.DataFrame(results)

    # Save CSV report
    csv_path = output_dir / f"eval_report_{report_name}.csv"
    results_df.to_csv(csv_path, index=False)

    # Compute and save JSON report with breakdown
    breakdown = compute_performance_breakdown(results_df)
    breakdown["report"] = csv_path.name
    json_path = output_dir / f"eval_report_{report_name}.json"
    with open(json_path, "w") as f:
        json.dump(breakdown, f, indent=2)

    return results_df, breakdown, csv_path, json_path
