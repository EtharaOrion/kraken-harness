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
    "oh_claude37sonnet"
    "oh_gemini25flash"
    "oh_gpt5mini"
    "oh_deepseekv31"
    "oh_kimi_k2_0905"
    "oh_gemini25pro"
    "oh_qwen3_coder_plus_20250923"
    # "sweagent_gpt5mini"
    # "sweagent_claude37sonnet"
    # "sweagent_gemini25flash"
)


for MODEL in "${MODELS[@]}"; do
    echo "Running evaluation for model: $MODEL"

    scripts/eval/run_profiler_only.sh profile_runs 12 predictions/converted/$MODEL.jsonl;
    docker rm -f $(docker ps -aq); docker system prune -a -f;

done
