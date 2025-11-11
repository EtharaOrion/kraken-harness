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

from pathlib import Path

import numpy as np
import tqdm
from datasets import load_dataset

from swefficiency.harness.run_validation import parse_perf_summary

ds = load_dataset("swefficiency/swefficiency", split="test")
gold_dir = Path("logs/run_evaluation/ground_truth2/gold")
synthetic_dir = Path("logs/run_evaluation/synthetic_workloads/gold")

gold_speedups = []
synthetic_speedups = []

for instance in tqdm.tqdm(ds, total=len(ds), desc="Processing instances"):
    instance_id = instance["instance_id"]
    gold_run_entry = gold_dir / instance_id / "perf_summary.txt"
    if gold_run_entry.exists():
        gold_perf_info = parse_perf_summary(gold_run_entry.read_text())
        gold_speedup_ratio = (
            gold_perf_info["before_mean"] / gold_perf_info["after_mean"]
        )
    else:
        gold_speedup_ratio = 1.0

    synthetic_entry = synthetic_dir / instance_id / "perf_summary.txt"
    if synthetic_entry.exists():
        synthetic_perf_info = parse_perf_summary(synthetic_entry.read_text())
        synthetic_speedup_ratio = (
            synthetic_perf_info["before_mean"] / synthetic_perf_info["after_mean"]
        )
    else:
        synthetic_speedup_ratio = 1.0

    gold_speedups.append(gold_speedup_ratio)
    synthetic_speedups.append(synthetic_speedup_ratio)


# Write out CSV file with instance_id, gold_speedup, synthetic_speedup
import pandas as pd

df = pd.DataFrame(
    {
        "instance_id": [instance["instance_id"] for instance in ds],
        "gold_speedup": gold_speedups,
        "synthetic_speedup": synthetic_speedups,
    }
)
df.to_csv("synthetic_workload_distribution.csv", index=False)
print("Saved synthetic_workload_distribution.csv")
