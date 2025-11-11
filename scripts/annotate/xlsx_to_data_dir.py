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

import os
import shutil
from pathlib import Path

import pandas as pd


def process_xlsx(xlsx_path):
    # Read the Excel file
    df = pd.read_excel(xlsx_path)

    # Ensure required columns exist
    required_columns = ["instance_id", "cleaned workload"]
    if not all(col in df.columns for col in required_columns):
        raise ValueError(f"Excel file must contain columns: {required_columns}")

    # Process each row
    for _, row in df.iterrows():
        instance_id = str(row["instance_id"])
        workload_content = str(row["cleaned workload"])

        # Create directory path
        dir_path = Path(f"data/{instance_id}")

        # Create directory if it doesn't exist
        dir_path.mkdir(parents=True, exist_ok=True)

        # Write workload.py file
        workload_file = dir_path / "workload.py"
        if workload_file.exists():
            os.remove(workload_file)

        if workload_content == "nan":
            print(f"Skipping {instance_id} because workload is empty")
            # remove the directory
            shutil.rmtree(dir_path)
            continue

        with open(workload_file, "w") as f:
            f.write(workload_content)

        print(f"Created workload.py in {dir_path}")


# first create "data/" directory if it doesn't exist
if not os.path.exists("data/"):
    os.makedirs("data/")

# next run "find logs/run_evaluation/old_debugging_coverage/debugging_coverage_sympy/gold/ -name "covering_tests.txt" -exec sh -c 'cp -r "$(dirname {})" ./data/' \;"
# which will copy the directories to the data/ directory with all the PRs that passed coverage.
# python scripts/annotate/xlsx_to_data_dir.py scripts/annotate/annotate_images_sympy.xlsx

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python xlsx_to_data_dir.py <path_to_xlsx_file>")
        sys.exit(1)

    xlsx_path = sys.argv[1]
    process_xlsx(xlsx_path)
