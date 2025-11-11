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

import pandas as pd

reports_dir = Path("eval_reports")

for report_file in sorted(reports_dir.glob("*.csv")):
    if "gold" in report_file.name:
        continue

    df = pd.read_csv(report_file)

    # # Floor assuming that "pred_speedup_ratio" is always 1.0.
    # df["do_nothing_pred_speedup_ratio"] = 1.0 / df["gold_speedup_ratio"]

    # # Harmonic mean function of do_nothing_pred_speedup_ratio.
    # print("bruh", len(df) / (1 / df["do_nothing_pred_speedup_ratio"]).sum())

    # Compute proportion of instances with correctness < 1.0.
    total_instances = len(df)
    incorrect_instances = (df["correctness"] < 1.0).sum()
    proportion_incorrect = (
        incorrect_instances / total_instances if total_instances > 0 else 0.0
    )

    # Compute proportion of instances with correctness == 1.0 and raw_pred_speedup_ratio < 1.0.
    correct_but_no_speedup = (
        (df["correctness"] == 1.0) & (df["raw_pred_speedup_ratio"] < 1.0)
    ).sum()
    proportion_correct_but_no_speedup = (
        correct_but_no_speedup / total_instances if total_instances > 0 else 0.0
    )

    # Compute proportion of instances with correctness == 1.0 and raw_pred_speedup_ratio >= 1.0 but human_speedup_ratio < 1.0.
    correct_with_speedup_but_human_no_speedup = (
        (df["correctness"] == 1.0)
        & (df["raw_pred_speedup_ratio"] >= 1.0)
        & (df["human_speedup_ratio"] < 1.0)
    ).sum()
    proportion_correct_with_speedup_but_human_no_speedup = (
        correct_with_speedup_but_human_no_speedup / total_instances
        if total_instances > 0
        else 0.0
    )

    # Compute proportin of instances with human_speedup_ratio >= 1.0.
    human_speedup_or_better = (df["human_speedup_ratio"] >= 1.0).sum()
    proportion_human_speedup_or_better = (
        human_speedup_or_better / total_instances if total_instances > 0 else 0.0
    )

    print(f"Report: {report_file.name}")
    print(f"  Total instances: {total_instances}")
    print(f"  Proportion incorrect (correctness < 1.0): {proportion_incorrect:.4f}")
    print(
        f"  Proportion correct but no speedup (correctness == 1.0 and raw_pred_speedup_ratio < 1.0): {proportion_correct_but_no_speedup:.4f}"
    )
    print(
        f"  Proportion correct with speedup but human no speedup (correctness == 1.0 and raw_pred_speedup_ratio >= 1.0 but human_speedup_ratio < 1.0): {proportion_correct_with_speedup_but_human_no_speedup:.4f}"
    )
    print(
        f"  Proportion with human speedup or better (human_speedup_ratio >= 1.0): {proportion_human_speedup_or_better:.4f}"
    )
    print()
