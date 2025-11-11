#!/bin/bash

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

root=logs/run_evaluation

# Find directories containing 'run_instance.log' but do not contain 'ast_output.txt'
find "$root" -type f -name 'run_instance.log' -printf '%h\0' |
  sort -zu |
  while IFS= read -r -d '' dir; do
    # Check if 'ast_output.txt' does NOT exist in the directory
    if [ ! -e "$dir/ast_output.txt" ]; then
      printf '%s\n' "$dir/run_instance.log"
    fi
  done > investigate_failed.txt
