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

__version__ = "1.0.0"

from swefficiency.collect.build_dataset import main as build_dataset
from swefficiency.collect.get_tasks_pipeline import main as get_tasks_pipeline
from swefficiency.collect.print_pulls import main as print_pulls
from swefficiency.harness.constants import (
    KEY_INSTANCE_ID,
    KEY_MODEL,
    KEY_PREDICTION,
    MAP_REPO_VERSION_TO_SPECS,
)
from swefficiency.harness.docker_build import (
    build_base_images,
    build_env_images,
    build_image,
    build_instance_image,
    build_instance_images,
    close_logger,
    setup_logger,
)
from swefficiency.harness.docker_utils import (
    cleanup_container,
    copy_to_container,
    exec_run_with_timeout,
    list_images,
    remove_image,
)
from swefficiency.harness.grading import (
    ResolvedStatus,
    TestStatus,
    compute_fail_to_pass,
    compute_pass_to_pass,
    get_eval_report,
    get_logs_eval,
    get_resolution_status,
)
from swefficiency.harness.log_parsers import MAP_REPO_TO_PARSER
from swefficiency.harness.utils import get_environment_yml, get_requirements
from swefficiency.versioning.constants import (
    MAP_REPO_TO_VERSION_PATHS,
    MAP_REPO_TO_VERSION_PATTERNS,
)
from swefficiency.versioning.get_versions import (
    get_version,
    get_versions_from_build,
    get_versions_from_web,
    map_version_to_task_instances,
)
from swefficiency.versioning.utils import split_instances
