#!/usr/bin/env bash
#
# 10-july-v7 DDB batch: generate the single "hardest" DDB task using the
# same v4-style thorough pipeline knobs. Only t1 (mega 8-verb subset) is
# emitted by default; the remaining v4 subsets are kept in SUBSETS for
# parity so START_AT/END_AT can extend the batch later without editing.
#
# Env (required):
#   LLM_CONFIG           path to proxy yaml (scripts/dynamodb/llm-proxy.yaml)
#   CLAUDE_PROXY_TOKEN   any non-empty value (proxy reads OAuth from Keychain)
# Env (optional):
#   OUT_ROOT             parent dir (default: ./datasets/v7)
#   GROUNDING            "on" (default) or "off"
#   START_AT             1..10 to resume mid-batch after a failure
#   END_AT               default 1 (only the hardest mega subset)

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HARNESS_DIR"

: "${LLM_CONFIG:?set LLM_CONFIG=scripts/dynamodb/llm-proxy.yaml}"
: "${CLAUDE_PROXY_TOKEN:?set CLAUDE_PROXY_TOKEN=dummy (proxy reads OAuth from Keychain)}"
[ -f "$LLM_CONFIG" ] || { echo "LLM_CONFIG not found: $LLM_CONFIG"; exit 1; }

OUT_ROOT="${OUT_ROOT:-./datasets/v7}"
GROUNDING="${GROUNDING:-on}"
START_AT="${START_AT:-1}"
END_AT="${END_AT:-1}"

if ! curl -sf http://localhost:8765/health > /dev/null; then
  echo "proxy at localhost:8765 not responding - start it with:"
  echo "  uv run proxy/claude_oauth_proxy.py --port 8765"
  exit 1
fi

if ! docker info > /dev/null 2>&1; then
  echo "docker daemon not running"
  exit 1
fi

SUBSETS=(
  "create-table,delete-item,delete-table,get-item,list-tables,put-item,query,update-item"
  "create-table,delete-table"
  "delete-item,get-item,put-item"
  "create-table,put-item,query"
  "create-table,delete-item,put-item,update-item"
  "create-table,delete-item,delete-table,get-item,put-item"
  "create-table,delete-item,get-item,put-item,query,update-item"
  "create-table,delete-item,delete-table,get-item,put-item,query,update-item"
  "create-table,delete-table,list-tables"
  "list-tables,query"
)

opts=(
  --repo aws/aws-cli --ref v2 --pipeline code_instruct
  --pipeline-opt mode=cli_app
  --pipeline-opt cli_app_command_prefix=dynamodb
  --pipeline-opt cli_app_backend=dynamodb_local
  --pipeline-opt cli_app_extract_mode=botocore_model
  --pipeline-opt cli_app_oracle=golden
  --pipeline-opt cli_app_workflow_tests=25
  --pipeline-opt cli_app_max_intents=100
  --pipeline-opt cli_app_min_grounded_tests=25
  --pipeline-opt cli_app_min_tests_final=50
  --pipeline-opt cli_app_min_happy_path=15
  --pipeline-opt cli_app_min_error_nonexistent=4
  --pipeline-opt cli_app_min_error_invalid_args=8
  --pipeline-opt cli_app_min_workflow=10
  --pipeline-opt max_llm_tokens=65000
  --pipeline-opt cli_app_docker_timeout_sec=1200
  --pipeline-opt cli_app_translate_workers=6
)
if [ "$GROUNDING" = "on" ]; then
  opts+=( --pipeline-opt cli_app_docker_gauntlet=true --pipeline-opt cli_app_reference_grounding=true )
else
  opts+=( --pipeline-opt cli_app_docker_gauntlet=false --pipeline-opt cli_app_reference_grounding=false )
fi

mkdir -p "$OUT_ROOT"

for i in "${!SUBSETS[@]}"; do
  n=$((i + 1))
  if [ "$n" -lt "$START_AT" ]; then continue; fi
  if [ "$n" -gt "$END_AT" ]; then continue; fi
  subset="${SUBSETS[$i]}"
  out="$OUT_ROOT/ddb-v7-t${n}"
  echo
  echo "===================================================================="
  echo "[10-july-v7] task ${n}/${#SUBSETS[@]} -> $out"
  echo "  subset: $subset"
  echo "  oracle: golden (real aws-cli slice + LLM reference)"
  echo "===================================================================="
  mkdir -p "$out"
  uv run repo2rlenv generate "${opts[@]}" \
    --pipeline-opt "cli_app_subsets=[\"${subset}\"]" \
    --config "$LLM_CONFIG" \
    --out "$out" 2>&1 | tee "$out/generate.log"
done

echo
echo "[10-july-v7] batch complete. Task dirs under: $OUT_ROOT/ddb-v7-t{${START_AT}..${END_AT}}/"
