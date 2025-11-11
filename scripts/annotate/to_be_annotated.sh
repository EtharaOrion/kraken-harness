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

# REPO_NAMES=("scipy" "sympy" "astropy" "spaCy")
REPO_NAMES=("sympy")

# Need to run covering tests first for.
# TODO: modin, scikit-image, networkx, pytensor, scrapy, statsmodels


for REPO_NAME in "${REPO_NAMES[@]}"; do
    ARTIFACTS_DIR=artifacts

    TASKS_FILE=${ARTIFACTS_DIR}/2_versioning/${REPO_NAME}-task-instances_attribute_versions.non-empty.jsonl
    PR_FILE=${ARTIFACTS_DIR}/pull_requests/${REPO_NAME}-prs.jsonl

    python scripts/annotate/upload_annotate_docker_and_get_csv_real.py \
        --tasks_file $TASKS_FILE \
        --pr_file $PR_FILE \
        --coverage_run_dir logs/run_evaluation/debugging_coverage_$REPO_NAME/gold/ \
        --max_build_workers 8 \
        --run_id $REPO_NAME
done
