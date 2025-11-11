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


NUM_WORKERS=12
MODELS=(
    # "oh_glm46"
    # "oh_gpt5"                     
    # "oh_kimi_k2_0905"          
    # "oh_gemini25pro"  
    # "oh_claude37sonnet"   
    # "oh_claude41opus"     
    # "oh_claude45opus"     
    # "oh_qwen3_coder_plus_20250923"  
    # "oh_claude45sonnet"
    # "oh_gemini25flash"
    # "oh_gpt5mini"
    # "oh_deepseekv31"
    # "sweagent_gpt5mini"
    # "sweagent_claude37sonnet"
    # "sweagent_gemini25flash"
    # "oh_minimax_m2"
    # "cursor_composer1"
    # "oh_gpt51"
    # "oh_gpt52"
    "oh_gemini3pro"
    "oh_gemini3flash"
)

RUN_NAME="ground_truth_perf_isolation4"

swefficiency eval --num_workers $NUM_WORKERS --run_id $RUN_NAME 
docker rm -f $(docker ps -aq); docker system prune -a -f;

for MODEL in "${MODELS[@]}"; do
    echo "Running evaluation for model: $MODEL"

    swefficiency eval --num_workers $NUM_WORKERS --run_id $RUN_NAME --prediction_path predictions/converted/$MODEL.jsonl $EXTRA_ARGS
    docker rm -f $(docker ps -aq); docker system prune -a -f;

done

