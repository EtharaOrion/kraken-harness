#!/usr/bin/env bash

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

# Wrapper to launch the inference harness with the Cursor CLI spec.
# Usage: scripts/inference/run_cursor_cli.sh <run_id> [extra args]
# Set DEBUG=1 to enable verbose tracing.

set -euo pipefail

STREAM_ARGS=()
if [[ "${DEBUG:-0}" == "1" ]]; then
  set -x
  STREAM_ARGS+=(--stream-logs)
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <run_id> [extra args]" >&2
  exit 1
fi

RUN_ID="$1"
shift

python scripts/inference/custom.py \
  --run-id "$RUN_ID" \
  --spec scripts/inference/specs/cursor_cli.yaml \
  --num-workers 8 \
  "${STREAM_ARGS[@]}" \
  "$@"
