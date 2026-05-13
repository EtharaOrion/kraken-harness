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

INSTANCE_ID="pandas-dev__pandas-52054"
THRESHOLD=5

PROFILE_RUN_DIR="logs/run_evaluation/profile_runs"
OUTPUT_DIR="analysis/adhoc/speedup_attribution/flame_graphs"

echo "preedit"
flameprof $PROFILE_RUN_DIR/gold/$INSTANCE_ID/workload_preedit_cprofile.prof --threshold $THRESHOLD > $OUTPUT_DIR/requests_preedit.svg

echo "post gold"
flameprof $PROFILE_RUN_DIR/gold/$INSTANCE_ID/workload_postedit_cprofile.prof --threshold $THRESHOLD > $OUTPUT_DIR/requests_postedit.svg

echo "post LLM"
flameprof $PROFILE_RUN_DIR/default_sweperf_claude__anthropic--claude-3-7-sonnet-20250219__t-0.00__p-1.00__c-1.00___swefficiency_full_test/$INSTANCE_ID/workload_postedit_cprofile.prof --threshold $THRESHOLD > $OUTPUT_DIR/requests_postedit_llm.svg


# Get the logs as well
flameprof $PROFILE_RUN_DIR/gold/$INSTANCE_ID/workload_preedit_cprofile.prof --threshold $THRESHOLD --format log > $OUTPUT_DIR/requests_preedit.log
flameprof $PROFILE_RUN_DIR/gold/$INSTANCE_ID/workload_postedit_cprofile.prof --threshold $THRESHOLD --format log > $OUTPUT_DIR/requests_postedit.log
flameprof $PROFILE_RUN_DIR/default_sweperf_claude__anthropic--claude-3-7-sonnet-20250219__t-0.00__p-1.00__c-1.00___swefficiency_full_test/$INSTANCE_ID/workload_postedit_cprofile.prof --threshold $THRESHOLD --format log > $OUTPUT_DIR/requests_postedit_llm.log
