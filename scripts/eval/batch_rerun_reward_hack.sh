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



# scripts/eval/run_eval.sh ground_truth6 12;
# docker rm -f $(docker ps -aq); docker system prune -a -f;

# scripts/eval/run_eval.sh ground_truth5 12 predictions/converted/sweagent_gpt5mini.jsonl; 
# docker rm -f $(docker ps -aq); docker system prune -a -f;

scripts/eval/run_eval.sh ground_truth5 12 predictions/converted/sweagent_claude37sonnet.jsonl rerun_sweagent_claude37sonnet.txt
docker rm -f $(docker ps -aq); docker system prune -a -f;

scripts/eval/run_eval.sh ground_truth5 12 predictions/converted/sweagent_gpt5mini.jsonl rerun_sweagent_gpt5mini.txt
docker rm -f $(docker ps -aq); docker system prune -a -f;

scripts/eval/run_eval.sh ground_truth5 12 predictions/converted/sweagent_gemini25flash.jsonl rerun_sweagent_gemini25flash.txt
docker rm -f $(docker ps -aq); docker system prune -a -f;

scripts/eval/run_eval.sh ground_truth5 12 predictions/converted/sweagent_gemini25flash.jsonl rerun_oh_gemini25flash.txt
docker rm -f $(docker ps -aq); docker system prune -a -f;

scripts/eval/run_eval.sh ground_truth5 12 predictions/converted/oh_gpt5mini.jsonl rerun_oh_gpt5mini.txt
docker rm -f $(docker ps -aq); docker system prune -a -f;

scripts/eval/run_eval.sh ground_truth5 12 predictions/converted/oh_claude37sonnet.jsonl rerun_oh_claude37sonnet.txt
docker rm -f $(docker ps -aq); docker system prune -a -f;