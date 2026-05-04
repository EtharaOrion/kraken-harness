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

import argparse
import multiprocessing
from functools import partial
from pathlib import Path

import datasets
import pandas as pd
from tqdm import tqdm

from swefficiency.report import evaluate_instance


def main(gold_run, pred_run, num_workers, output_dir):
    ds = datasets.load_dataset("swefficiency/swefficiency", split="test")
    ds_lite = datasets.load_dataset("swefficiency/swefficiency_lite", split="test")

    ds_lite_instance_ids = {item["instance_id"] for item in ds_lite}
    ds = [item for item in ds if item["instance_id"] in ds_lite_instance_ids]

    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    run_name = f"eval_report_{pred_run.name}"

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
    results_df.to_csv(output_dir / f"{run_name}.csv", index=False)
    print(f"Evaluation report saved to {output_dir / f'{run_name}.csv'}")

    floored_human_speedup = results_df["human_speedup_ratio"].clip(lower=0.001)
    harmonic_mean_human_speedup = len(results_df) / (1 / floored_human_speedup).sum()

    print(f"Average Human Speedup Ratio: {harmonic_mean_human_speedup}x")
    print(f"Correctness Percentage: {results_df['correctness'].mean() * 100}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gold_run", type=Path, required=True, help="Path to the ground truth run dir"
    )
    parser.add_argument(
        "--pred_run", type=Path, required=True, help="Path to the predicted run dir"
    )
    parser.add_argument(
        "--num_workers",
        type=int,
        default=4,
        help="Number of workers for parallel processing",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=Path("./eval_reports_lite"),
        help="Output directory for the report",
    )

    args = parser.parse_args()
    main(**vars(args))
