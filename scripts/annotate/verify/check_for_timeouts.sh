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

# /bin/bash
root=logs/run_evaluation

find "$root" -type f -name 'coverage_output.txt' -printf '%h\0' |
  sort -zu |
  while IFS= read -r -d '' dir; do
    if [ ! -e "$dir/covering_tests.txt" ]; then
      printf '%s\n' "$dir/coverage_output.txt"
    fi
  done > investigate.txt

# Iterate through each line in investigate.txt, read the file, and check for "timed out"
while IFS= read -r file; do
  if grep -q "Timeout" "$file"; then
    echo "Timeout found in: $file"
    # You can add additional actions here, like sending an alert or logging
  fi
done < investigate.txt

# This should print nothing if there are no timeouts.