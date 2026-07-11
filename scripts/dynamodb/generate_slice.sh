#!/usr/bin/env bash
#
# Generate the DynamoDB 3-task fidelity slice (plan §4) through the full
# pipeline with the grounding gate ON. Run scripts/dynamodb/spike.sh FIRST —
# this script assumes the four go/no-go gates already pass.
#
# Emits 3 tasks:
#   1. create-table                       (single-command  -> per-command mode)
#   2. put-item,get-item                   (two-command     -> subset mode)
#   3. create-table,put-item,query         (three-command   -> subset mode)
#
# NB: the single-command task MUST use cli_app_command (subset mode silently
# skips any group with < 2 commands).
#
# LLM (choose ONE):
#   LLM_CONFIG     path to a --config yaml with an `llm:` block (proxy setups; see
#                  llm-proxy.example.yaml + proxy_check.sh). Preferred for the proxy.
#   LLM            provider/model, e.g. anthropic/claude-opus-4-8 (direct API; needs the key env)
# Optional env:
#   DDB_BASE_IMAGE            override the app Dockerfile BASE_IMAGE (default: pipeline PINNED_BASE_IMAGE)
#   SERVICE_MODEL_OVERRIDE    abs path to service-2.json if the clone doesn't vendor botocore data
#   OUT                       output dir (default ./datasets/ddb-slice)
#   GROUNDING                 "on" (default) or "off" (smoke without Docker gauntlet)
set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HARNESS_DIR"

OUT="${OUT:-./datasets/ddb-slice}"
GROUNDING="${GROUNDING:-on}"

# Proxy config file takes precedence; otherwise a direct provider/model.
llm_args=()
if [ -n "${LLM_CONFIG:-}" ]; then
  [ -f "$LLM_CONFIG" ] || { echo "LLM_CONFIG not found: $LLM_CONFIG"; exit 1; }
  llm_args=(--config "$LLM_CONFIG")
elif [ -n "${LLM:-}" ]; then
  llm_args=(--llm "$LLM")
else
  echo "set LLM_CONFIG=<proxy yaml> (preferred) or LLM=provider/model" >&2; exit 1
fi

opts=(
  --repo aws/aws-cli --ref v2 --pipeline code_instruct
  --pipeline-opt mode=cli_app
  --pipeline-opt cli_app_command_prefix=dynamodb
  --pipeline-opt cli_app_backend=dynamodb_local
  --pipeline-opt cli_app_extract_mode=botocore_model
  --pipeline-opt cli_app_workflow_tests=3
  --pipeline-opt cli_app_max_intents=8
  --pipeline-opt cli_app_min_grounded_tests=3
)
if [ "$GROUNDING" = "on" ]; then
  opts+=( --pipeline-opt cli_app_docker_gauntlet=true --pipeline-opt cli_app_reference_grounding=true )
else
  opts+=( --pipeline-opt cli_app_docker_gauntlet=false --pipeline-opt cli_app_reference_grounding=false )
fi
[ -n "${DDB_BASE_IMAGE:-}" ]         && opts+=( --pipeline-opt "cli_app_base_image=${DDB_BASE_IMAGE}" )
[ -n "${SERVICE_MODEL_OVERRIDE:-}" ] && opts+=( --pipeline-opt "cli_app_service_model_override=${SERVICE_MODEL_OVERRIDE}" )

echo "[slice] task 1/3 — create-table (per-command mode)"
uv run repo2rlenv generate "${opts[@]}" \
  --pipeline-opt cli_app_command=create-table \
  "${llm_args[@]}" --out "$OUT"

echo "[slice] tasks 2-3/3 — put-item,get-item and create-table,put-item,query (subset mode)"
uv run repo2rlenv generate "${opts[@]}" \
  --pipeline-opt 'cli_app_subsets=["put-item,get-item","create-table,put-item,query"]' \
  "${llm_args[@]}" --out "$OUT"

echo
echo "[slice] done. Emitted task dirs under: $OUT"
echo "[slice] per-task DoD (verify each): oracle=1.0000, nop=0.0000, real-aws>=0.95,"
echo "        tests_shipped == pytest --collect-only, no forbidden flags, no boto imports."
