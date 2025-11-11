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
GOLD_RUN_NAME="$EVAL_DIR/ground_truth_perf_isolation4/gold"

MODEL_NAMES=(
    # "$EVAL_DIR/ground_truth_perf_isolation5/gold"
    # "$EVAL_DIR/ground_truth_perf_isolation4/cursor-cli-composer-1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/claude-opus-4-5-20251101_maxiter_100_N_v0.61.0-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/claude-opus-4-1-20250805_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/glm-4.6_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/gpt-5.1_maxiter_100_N_v0.61.0-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/gpt-5.2_maxiter_100_N_v0.61.0-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/gemini-3-pro-preview_maxiter_100_N_v0.61.0-no-hint-run_1"
    "$EVAL_DIR/ground_truth_perf_isolation4/gemini-3-flash-preview_maxiter_100_N_v0.61.0-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/gpt-5_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/claude-sonnet-4-5-20250929_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/gpt-5-mini_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/us.anthropic.claude-3-7-sonnet-20250219-v1_0_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/gemini-2.5-flash_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/gemini-2.5-pro_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/deepseek-reasoner_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/kimi-k2-0905-preview_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation4/qwen3-coder-plus-2025-09-23_maxiter_100_N_v0.51.1-no-hint-run_1"
    # "$EVAL_DIR/ground_truth_perf_isolation3/default_sweperf_claude__anthropic--claude-3-7-sonnet-20250219__t-0.00__p-1.00__c-1.00___swefficiency_full_test"
    # "$EVAL_DIR/ground_truth_perf_isolation3/default_sweperf_gemini__gemini--gemini-2.5-flash__t-0.00__p-1.00__c-1.00___swefficiency_full_test"
    # "$EVAL_DIR/ground_truth_perf_isolation3/default_sweperf_openai__openai--gpt-5-mini__t-1.00__p-1.00__c-1.00___swefficiency_full_test"
)

for MODEL_NAME in "${MODEL_NAMES[@]}"; do
    echo "Evaluating model: $MODEL_NAME"

    FOLDER_NAME=$(basename "$MODEL_NAME")

    # swefficiency report \
    #     --run_id "ground_truth_perf_isolation3" \
    #     --pred_run "$MODEL_NAME" \

    python scripts/eval/get_report.py \
        --gold_run "$GOLD_RUN_NAME" \
        --pred_run "$MODEL_NAME" \
        --num_workers 4 \
        --output_dir "eval_reports"
done
