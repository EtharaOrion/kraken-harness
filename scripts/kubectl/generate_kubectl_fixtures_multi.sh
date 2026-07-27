#!/usr/bin/env bash
#
# kubectl (kwok backend) MULTI-TASK batch: 10 varied multi-verb subsets with
# per-task fixture cap (default 80, target range 50-100). Same fixture short-
# circuit as generate_kubectl_fixtures.sh but ships smaller tasks so each one
# stays within the 50-100 test bracket.
#
# Env (required):
#   LLM_CONFIG           path to proxy yaml (scripts/kubectl/llm-proxy.yaml)
#   CLAUDE_PROXY_TOKEN   any non-empty value (proxy reads OAuth from Keychain)
# Env (optional):
#   OUT_ROOT             parent dir (default: ./datasets/kubectl-multi-v1)
#   START_AT             1..N to resume mid-batch after a failure
#   END_AT               default 10 (whole batch)
#   MAX_TESTS            per-task fixture cap (default 80)
#   YAML_BUNDLE          override path to kubectl Cobra YAML bundle
#   FIXTURE_DIR          override path to kubectl fixture dir

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HARNESS_DIR"

: "${LLM_CONFIG:?set LLM_CONFIG=scripts/kubectl/llm-proxy.yaml}"
: "${CLAUDE_PROXY_TOKEN:?set CLAUDE_PROXY_TOKEN=dummy (proxy reads OAuth from Keychain)}"
[ -f "$LLM_CONFIG" ] || { echo "LLM_CONFIG not found: $LLM_CONFIG"; exit 1; }

OUT_ROOT="${OUT_ROOT:-./datasets/kubectl-multi-v1}"
START_AT="${START_AT:-1}"
END_AT="${END_AT:-10}"
MAX_TESTS="${MAX_TESTS:-80}"
YAML_BUNDLE="${YAML_BUNDLE:-$HARNESS_DIR/tests/fixtures/kubectl_spec_v1_31_minimal.yaml}"
FIXTURE_DIR="${FIXTURE_DIR:-$HARNESS_DIR/tests/fixtures/kubectl_testcases}"

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
[ -d "$FIXTURE_DIR" ] || { echo "FIXTURE_DIR not found: $FIXTURE_DIR"; exit 1; }
[ -f "$FIXTURE_DIR/conftest.py" ] || { echo "FIXTURE_DIR missing conftest.py: $FIXTURE_DIR"; exit 1; }

# 10 subsets that mix verbs and kinds across the 8 fixture-covered verbs
# (apply, create, delete, describe, get, label, patch, scale). Combinations
# vary in width (1-8 verbs) and functional theme (read-only, lifecycle,
# mutate-in-place, scale, full CRUD).
SUBSETS=(
  "get,describe,delete"
  "apply,get,delete"
  "create,get,describe,delete"
  "apply,create,delete"
  "label,patch,get"
  "scale,get,describe"
  "apply,label,patch,delete"
  "create,scale,delete"
  "apply,get,describe,label,delete"
  "apply,create,get,describe,patch,label,scale,delete"
)

opts=(
  --repo kubernetes/kubectl --ref v0.32.0 --pipeline code_instruct
  --pipeline-opt mode=cli_app
  --pipeline-opt cli_app_command_prefix=kubectl
  --pipeline-opt cli_app_backend=kwok
  --pipeline-opt "cli_app_kubectl_yaml_bundle_path=$YAML_BUNDLE"
  --pipeline-opt "cli_app_kubectl_fixture_dir=$FIXTURE_DIR"
  --pipeline-opt "cli_app_kubectl_fixture_max_tests=$MAX_TESTS"
  --pipeline-opt cli_app_oracle=llm
  --pipeline-opt cli_app_auto_subsets=false
  --pipeline-opt cli_app_max_intents=100
  --pipeline-opt max_llm_tokens=65000
  --pipeline-opt cli_app_docker_timeout_sec=1200
  --pipeline-opt cli_app_translate_workers=6
  --pipeline-opt cli_app_docker_gauntlet=false
  --pipeline-opt cli_app_reference_grounding=false
)

mkdir -p "$OUT_ROOT"

for i in "${!SUBSETS[@]}"; do
  n=$((i + 1))
  if [ "$n" -lt "$START_AT" ]; then continue; fi
  if [ "$n" -gt "$END_AT" ]; then continue; fi
  subset="${SUBSETS[$i]}"
  out="$OUT_ROOT/kubectl-fx-multi-t${n}"
  echo
  echo "===================================================================="
  echo "[kubectl-multi-v1] task ${n}/${#SUBSETS[@]} -> $out"
  echo "  subset: $subset"
  echo "  max_tests: $MAX_TESTS  (fixture cap; stratified sample by verb+tag)"
  echo "  backend: kwok  (tests = fixtures; golden = slicer; reference = LLM)"
  echo "===================================================================="
  mkdir -p "$out"
  uv run repo2rlenv generate "${opts[@]}" \
    --pipeline-opt "cli_app_subsets=[\"${subset}\"]" \
    --config "$LLM_CONFIG" \
    --out "$out" 2>&1 | tee "$out/generate.log"
done

echo
echo "[kubectl-multi-v1] batch complete. Task dirs: $OUT_ROOT/kubectl-fx-multi-t{${START_AT}..${END_AT}}/"
