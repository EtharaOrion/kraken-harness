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


EVAL_DIR="logs/run_evaluation"

# GOLD_RUN_NAME="$EVAL_DIR/ground_truth5/gold"
GOLD_RUN_NAME="$EVAL_DIR/ground_truth_perf_isolation6/gold"

EVAL_DIRS=(
    "$EVAL_DIR/ground_truth_perf_isolation4"
    "$EVAL_DIR/ground_truth_perf_isolation6"
    "$EVAL_DIR/ground_truth_perf_isolation7"
)

MODEL_NAMES=(
    "gold"
    "us.anthropic.claude-3-7-sonnet-20250219-v1_0_maxiter_100_N_v0.51.1-no-hint-run_1"
    "gpt-5-mini_maxiter_100_N_v0.51.1-no-hint-run_1"
    "gemini-2.5-flash_maxiter_100_N_v0.51.1-no-hint-run_1"
)

for MODEL_NAME in "${MODEL_NAMES[@]}"; do
    echo "Evaluating model: $MODEL_NAME"

    for EVAL_DIR in "${EVAL_DIRS[@]}"; do
        MODEL_PATH="$EVAL_DIR/$MODEL_NAME"
        echo "  Using evaluation directory: $EVAL_DIR"

        python scripts/eval/get_report.py \
            --gold_run "$GOLD_RUN_NAME" \
            --pred_run "$MODEL_PATH" \
            --num_workers 4 \
            --output_dir "eval_reports"
    done

done
