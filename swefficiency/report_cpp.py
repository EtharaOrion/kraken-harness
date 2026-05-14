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

"""C++ analog of ``report.py``.

Reuses the perf-summary parser, patch-line counter, and breakdown computation
from ``report.py`` (language-agnostic). Forks ``evaluate_instance`` and
``generate_report`` so that test-output parsing routes through
``MAP_REPO_TO_PARSER_CPP`` instead of the Python parser map.
"""

from __future__ import annotations

import json
import multiprocessing
from functools import partial
from pathlib import Path
from typing import Dict, Tuple

import datasets
import pandas as pd
from tqdm import tqdm

from swefficiency.harness.log_parsers_cpp import (
    MAP_REPO_TO_PARSER_CPP,
    parse_log_cpp_best_effort,
)
from swefficiency.report import (
    compute_performance_breakdown,
    get_number_of_patch_modified_lines,
    parse_perf_summary,
)


def evaluate_instance_cpp(
    instance: dict,
    gold_run: Path,
    pred_run: Path,
    use_correctness_files: bool = True,
) -> Dict:
    """C++ version of ``report.evaluate_instance``.

    Behaviorally identical to the Python pipeline except the per-test status
    parsing falls back to ``MAP_REPO_TO_PARSER_CPP`` (with a
    ``parse_log_cpp_best_effort`` fallback for unknown repos).
    """
    instance_id = instance["instance_id"]
    pass_to_pass = instance["PASS_TO_PASS"]
    if isinstance(pass_to_pass, str):
        pass_to_pass = json.loads(pass_to_pass)

    gold_run_entry = gold_run / instance_id / "perf_summary.txt"
    pred_run_entry = pred_run / instance_id / "perf_summary.txt"

    data_quality_flags: list[str] = []
    has_pred_perf = pred_run_entry.exists()
    has_gold_perf = gold_run_entry.exists()

    if has_pred_perf:
        pred_perf_info = parse_perf_summary(pred_run_entry.read_text())
        after_mean = pred_perf_info["after_mean"]
        pred_speedup_ratio = (
            pred_perf_info["before_mean"] / after_mean if after_mean != 0 else 1.0
        )
    else:
        pred_speedup_ratio = 1.0
        patch_diff = pred_run / instance_id / "patch.diff"
        if patch_diff.exists():
            patch_text = patch_diff.read_text()
            if "error:" in patch_text.lower() or len(patch_text.strip()) == 0:
                data_quality_flags.append("CORRUPT_PATCH")
            else:
                data_quality_flags.append("NO_PERF_DATA")
        else:
            data_quality_flags.append("NO_PERF_DATA")

    if has_gold_perf:
        gold_perf_info = parse_perf_summary(gold_run_entry.read_text())
        after_mean = gold_perf_info["after_mean"]
        gold_speedup_ratio = (
            gold_perf_info["before_mean"] / after_mean if after_mean != 0 else 1.0
        )
    else:
        gold_speedup_ratio = 1.0
        gold_perf_info = {"before_mean": 0.0}

    if gold_speedup_ratio < 1.0:
        data_quality_flags.append("GOLD_SLOWDOWN")

    num_modified_lines = get_number_of_patch_modified_lines(instance["patch"])

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
        pred_statuses: dict[str, str] = {}
        parser = MAP_REPO_TO_PARSER_CPP.get(instance["repo"], parse_log_cpp_best_effort)
        for test_output in correctness_dir.glob("*.txt"):
            pred_statuses.update(parser(test_output.read_text(errors="ignore")))
    else:
        pred_statuses = json.loads(
            (pred_run / instance_id / "covering_test_status.json").read_text()
        )

    passed_tests = {t for t in pass_to_pass if "PASS" in pred_statuses.get(t, "")}
    correctness_pct = len(passed_tests) / len(pass_to_pass) if pass_to_pass else 1.0
    adjusted_pred_speedup_ratio = 1.0 if correctness_pct != 1.0 else pred_speedup_ratio

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


def generate_report_cpp(
    gold_run: Path,
    pred_run: Path,
    output_dir: Path,
    num_workers: int = 4,
    dataset_name: str = "swefficiency/swefficiency-cpp",
) -> Tuple[pd.DataFrame, Dict, Path, Path]:
    """C++ analog of ``report.generate_report``."""
    dataset_path = Path(dataset_name)
    if dataset_path.exists() and dataset_path.suffix == ".jsonl":
        with open(dataset_path) as _f:
            ds = [json.loads(line) for line in _f if line.strip()]
    else:
        ds = datasets.load_dataset(dataset_name, split="test")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_name = pred_run.name

    worker = partial(evaluate_instance_cpp, gold_run=gold_run, pred_run=pred_run)
    with multiprocessing.Pool(num_workers) as pool:
        results = list(
            tqdm(
                pool.imap(worker, ds, chunksize=1),
                total=len(ds),
                desc="Evaluating cpp instances",
            )
        )

    results_df = pd.DataFrame(results)

    csv_path = output_dir / f"eval_report_cpp_{report_name}.csv"
    results_df.to_csv(csv_path, index=False)

    breakdown = compute_performance_breakdown(results_df)
    breakdown["report"] = csv_path.name
    breakdown["language"] = "cpp"
    json_path = output_dir / f"eval_report_cpp_{report_name}.json"
    with open(json_path, "w") as f:
        json.dump(breakdown, f, indent=2)

    return results_df, breakdown, csv_path, json_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate C++ evaluation report.")
    parser.add_argument("--gold-run", required=True, type=Path)
    parser.add_argument("--pred-run", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--dataset-name", default="swefficiency/swefficiency-cpp")
    args = parser.parse_args()

    _, breakdown, _, _ = generate_report_cpp(
        args.gold_run, args.pred_run, args.output_dir, args.num_workers, args.dataset_name
    )
    print(json.dumps(breakdown, indent=2))
