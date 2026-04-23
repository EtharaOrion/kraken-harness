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


RUN_ID=$1
NUM_WORKERS=$2
PREDICTIONS_PATH=$3
INSTANCES_TO_RUN_PATH=$4  # Optional: comma-separated list of instance IDs to run

# If predictions_path is provided, add to args
ADDITIONAL_ARGS=""
if [ -n "$PREDICTIONS_PATH" ]; then
    ADDITIONAL_ARGS="--model_predictions $PREDICTIONS_PATH"
fi

if [ -n "$INSTANCES_TO_RUN_PATH" ]; then
    # Read the instance IDs (already space-separated) and put full list as is into args.
    INSTANCES_TO_RUN=$(cat $INSTANCES_TO_RUN_PATH)
    ADDITIONAL_ARGS="$ADDITIONAL_ARGS --instance_ids $INSTANCES_TO_RUN --force_rerun true"
fi

python swefficiency/harness/run_validation.py \
    --dataset_name swefficiency/swefficiency \
    --run_id $RUN_ID \
    --cache_level env \
    --max_build_workers 16 \
    --max_workers $NUM_WORKERS \
    --timeout 7_200 \
    --run_perf true \
    --run_correctness true \
    --use_ecr_images true \
    $ADDITIONAL_ARGS
