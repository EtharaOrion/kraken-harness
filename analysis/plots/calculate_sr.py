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

import pandas as pd

# -----------------------------------------------------------------------------
# Inputs
# -----------------------------------------------------------------------------
eval_reports = [
    ("OH GPT-5 Mini", "eval_reports/eval_report_gpt-5-mini_maxiter_100_N_v0.51.1-no-hint-run_1.csv"),
    ("OH Claude 3.7 Sonnet", "eval_reports/eval_report_us.anthropic.claude-3-7-sonnet-20250219-v1_0_maxiter_100_N_v0.51.1-no-hint-run_1.csv"),
    ("OH Gemini 2.5 Flash", "eval_reports/eval_report_gemini-2.5-flash_maxiter_100_N_v0.51.1-no-hint-run_1.csv"),
]

def compute_statistics(df):
    # Compute harmonig mean over human_speedup_ratio without packages
    # Compute harmonic mean of positive human_speedup_ratio values (no scipy)
    ratios = df["human_speedup_ratio"].astype(float)
    agg_speedup_ratio = len(ratios) / (1.0 / ratios).sum()

    base_speedup_ratios = df["pred_speedup_ratio"].astype(float)
    agg_base_speedup = len(base_speedup_ratios) / (1.0 / base_speedup_ratios).sum()

    return agg_speedup_ratio, agg_base_speedup

for name, path in eval_reports:
    print(f"{name}: {path}")
    
    df = pd.read_csv(path)
    agg_speedup_ratio, agg_base_speedup = compute_statistics(df)
    print(f"  Harmonic mean of human_speedup_ratio: {agg_speedup_ratio}")
    print(f"  Harmonic mean of pred_speedup_ratio: {agg_base_speedup}")
