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

INSTANCE = "pandas-dev__pandas-52341"
INSTANCE = "pandas-dev__pandas-52381"
INSTANCE = "astropy__astropy-7549"
INSTANCE = "pydata__xarray-7374"

PROFILE_RUN_DIR = Path("logs/run_evaluation/profile_runs")
GOLD_PROFILE_DIR = PROFILE_RUN_DIR / "gold"
LLM_PROFILE_DIR = PROFILE_RUN_DIR / "default_sweperf_claude__anthropic--claude-3-7-sonnet-20250219__t-0.00__p-1.00__c-1.00___swefficiency_full_test"

gold_preedit_file = GOLD_PROFILE_DIR / INSTANCE / "preedit" / "workload_preedit_cprofile.prof"
gold_postedit_file = GOLD_PROFILE_DIR / INSTANCE / "postedit" / "workload_postedit_cprofile.prof"

llm_preedit_file = LLM_PROFILE_DIR / INSTANCE / "preedit" / "workload_preedit_cprofile.prof"
llm_postedit_file = LLM_PROFILE_DIR / INSTANCE / "postedit" / "workload_postedit_cprofile.prof"

