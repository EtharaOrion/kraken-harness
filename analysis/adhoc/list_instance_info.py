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

import datasets

ds = datasets.load_dataset("swefficiency/swefficiency", split="test")

instance_id_to_github_url = {}

for d in ds:
    instance_id = d["instance_id"]
    repo = d["repo"]

    pull_number = instance_id.split("-")[-1]

    github_url = f"https://github.com/{repo}/pull/{pull_number}"
    instance_id_to_github_url[instance_id] = github_url

# Save to two column CSV file.
import pandas as pd

df = pd.DataFrame(
    instance_id_to_github_url.items(), columns=["instance_id", "github_url"]
)
df.to_csv("instance_id_to_github_url.csv", index=False)
