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

# Example call for getting versions by building the repo locally
python get_versions.py \
    --path_tasks "<path to matplotlib task instances>" \
    --retrieval_method build \
    --conda_env "<name of conda environment to build task instances within>" \
    --num_threads 10 \
    --path_conda "<path to conda installation with `conda_env`>" \
    --testbed "<path to folder>"

# Example call for getting versions from github web interface
python get_versions.py \
    --path_tasks "<path to sphinx task instances>" \
    --retrieval_method github \
    --num_workers 25 \
    --output_dir "<path to folder to save versioned task instances to>"