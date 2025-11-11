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

import datasets

ds = datasets.load_dataset("swefficiency/swefficiency", split="test")
instance_ids = set(d["instance_id"] for d in ds)

OUTPUT_DIR = Path("predictions/converted")

# model_name = "gemini25flash"
# model_name = "gpt5mini"
# model_name = "claude37sonnet"

for model_name in [
    # "gemini25flash",
    # "gemini25pro",
    # "gpt5mini",
    # "claude37sonnet",
    # "kimi_k2_0905",
    # "qwen3_coder_plus_20250923",
    # "claude45sonnet",
    # "gpt5",
    # "glm46",
    # "claude41opus",
    # "minimax_m2"
    # "claude45opus",
    # "gpt52",
    # "gpt51",
    # "gpt52",
    "gemini3flash",
    "gemini3pro",
]:
    INPUT_FILE = f"predictions/openhands/{model_name}_raw.jsonl"
    OUTPUT_FILE = OUTPUT_DIR / f"oh_{model_name}.jsonl"

    print(f"Converting {INPUT_FILE} to {OUTPUT_FILE}...")

    # Read in JSONL file and convert to list of dict.
    import json

    def read_jsonl(file_path):
        data = []
        with open(file_path, "r") as f:
            for line in f:
                data.append(json.loads(line))
        return data

    raw_predictions = read_jsonl(INPUT_FILE)

    predictions = []
    for item in raw_predictions:
        if not item["metadata"]:
            print(item)
            continue

        if item["instance_id"] not in instance_ids:
            print(
                f"Warning: instance_id {item['instance_id']} not in dataset, skipping."
            )
            continue

        model_patch = item["test_result"].get("git_patch", "")
        if not model_patch:
            print(f"Warning: instance_id {item['instance_id']} has no git_patch.")
            print(item["test_result"])

        eval_entry = {
            "instance_id": item["instance_id"],
            "model_patch": item["test_result"].get("git_patch", ""),
            "model_name_or_path": item["metadata"]["eval_output_dir"].split("/")[-1],
        }
        predictions.append(eval_entry)

    # Write out to JSONL file.
    def write_jsonl(data, file_path):
        with open(file_path, "w") as f:
            for entry in data:
                f.write(json.dumps(entry) + "\n")

    write_jsonl(predictions, OUTPUT_FILE)
