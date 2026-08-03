#!/usr/bin/env bash
#
# kubectl (kwok backend) batch: mirrors scripts/dynamodb/generate_10_july_v7.sh
# style. Each SUBSETS entry becomes ONE emitted task whose test suite exercises
# that comma-joined verb bundle against a kwok-backed Kubernetes cluster.
#
# Env (required):
#   LLM_CONFIG           path to proxy yaml (scripts/kubectl/llm-proxy.yaml)
#   CLAUDE_PROXY_TOKEN   any non-empty value (proxy reads OAuth from Keychain)
# Env (optional):
#   OUT_ROOT             parent dir (default: ./datasets/kubectl-v1)
#   GROUNDING            "on" (default) or "off"
#   START_AT             1..N to resume mid-batch after a failure
#   END_AT               default 1 (only the hardest subset)
#   YAML_BUNDLE          override path to kubectl Cobra YAML bundle
#                        (default: tests/fixtures/kubectl_spec_v1_31_minimal.yaml)

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HARNESS_DIR"

: "${LLM_CONFIG:?set LLM_CONFIG=scripts/kubectl/llm-proxy.yaml}"
: "${CLAUDE_PROXY_TOKEN:?set CLAUDE_PROXY_TOKEN=dummy (proxy reads OAuth from Keychain)}"
[ -f "$LLM_CONFIG" ] || { echo "LLM_CONFIG not found: $LLM_CONFIG"; exit 1; }

OUT_ROOT="${OUT_ROOT:-./datasets/kubectl-v1}"
GROUNDING="${GROUNDING:-on}"
START_AT="${START_AT:-1}"
END_AT="${END_AT:-1}"
YAML_BUNDLE="${YAML_BUNDLE:-$HARNESS_DIR/tests/fixtures/kubectl_spec_v1_31_minimal.yaml}"

if ! curl -sf http://localhost:8765/health > /dev/null 2>&1; then
  if ! curl -sf -X POST http://localhost:8765/v1/messages \
      -H 'content-type: application/json' \
      -H 'x-api-key: dummy' \
      -d '{"model":"claude-opus-4-8","max_tokens":1,"messages":[{"role":"user","content":"ping"}]}' \
      > /dev/null 2>&1; then
    echo "proxy at localhost:8765 not responding - start it with:"
    echo "  uv run proxy/claude_oauth_proxy.py --port 8765"
    exit 1
  fi
fi

if ! docker info > /dev/null 2>&1; then
  echo "docker daemon not running"
  exit 1
fi

[ -f "$YAML_BUNDLE" ] || { echo "YAML_BUNDLE not found: $YAML_BUNDLE"; exit 1; }

SUBSETS=(
  "get,describe,delete"
  "get,describe"
  "apply,get,delete"
  "create,get,delete"
  "get,delete"
  "apply,get"
  "create,delete"
  "get"
  "describe"
  "delete"
)

opts=(
  --repo kubernetes/kubectl --ref v0.32.0 --pipeline code_instruct
  --pipeline-opt mode=cli_app
  --pipeline-opt cli_app_command_prefix=kubectl
  --pipeline-opt cli_app_backend=kwok
  --pipeline-opt "cli_app_kubectl_yaml_bundle_path=$YAML_BUNDLE"
  --pipeline-opt cli_app_oracle=llm
  --pipeline-opt cli_app_auto_subsets=false
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
  out="$OUT_ROOT/kubectl-v1-t${n}"
  echo
  echo "===================================================================="
  echo "[kubectl-v1] task ${n}/${#SUBSETS[@]} -> $out"
  echo "  subset: $subset"
  echo "  backend: kwok  (golden = kubectl AST slicer; reference = LLM)"
  echo "===================================================================="
  mkdir -p "$out"
  uv run repo2rlenv generate "${opts[@]}" \
    --pipeline-opt "cli_app_subsets=[\"${subset}\"]" \
    --config "$LLM_CONFIG" \
    --out "$out" 2>&1 | tee "$out/generate.log"
done

echo
echo "[kubectl-v1] batch complete. Task dirs under: $OUT_ROOT/kubectl-v1-t{${START_AT}..${END_AT}}/"
