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


REPO_NAME=$1  # e.g., getmoto__moto
INSTANCE_PATH=artifacts/1_attributes/${REPO_NAME}-task-instances_attribute.jsonl
OUTPUT_DIR=artifacts/2_versioning
CONDA_PATH=~/miniforge3/condabin/conda
TESTBED_PATH=~/scratch/testbed

pushd swefficiency/versioning

python get_versions.py \
    --instances_path $INSTANCE_PATH \
    --retrieval_method github \
    --conda_env temp \
    --num_workers 4 \
    --path_conda $CONDA_PATH \
    --output_dir $OUTPUT_DIR \
    --testbed $TESTBED_PATH

popd

OUTPUT_PATH=$OUTPUT_DIR/${REPO_NAME}-task-instances_attribute_versions.json
python3 scripts/filter_empty_version.py $OUTPUT_PATH
