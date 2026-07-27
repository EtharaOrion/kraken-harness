#!/usr/bin/env bash
#
# kubectl (kwok backend) batch WITH FIXTURE SHORT-CIRCUIT: same shape as
# generate_kubectl.sh, but points cli_app_kubectl_fixture_dir at the
# hand-authored test bank so the pipeline ships those tests verbatim
# (bypasses LLM test synthesis + static gauntlet + reference grounding).
# LLM oracle (reference.diff) and kubectl AST slicer golden (gold.diff)
# still run.
#
# Env (required):
#   LLM_CONFIG           path to proxy yaml (scripts/kubectl/llm-proxy.yaml)
#   CLAUDE_PROXY_TOKEN   any non-empty value (proxy reads OAuth from Keychain)
# Env (optional):
#   OUT_ROOT             parent dir (default: ./datasets/kubectl-fx-v1)
#   START_AT             1..N to resume mid-batch after a failure
#   END_AT               default 1 (only the hardest subset)
#   YAML_BUNDLE          override path to kubectl Cobra YAML bundle
#                        (default: tests/fixtures/kubectl_spec_v1_31_minimal.yaml)
#   FIXTURE_DIR          override path to kubectl fixture dir
#                        (default: tests/fixtures/kubectl_testcases)

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HARNESS_DIR"

: "${LLM_CONFIG:?set LLM_CONFIG=scripts/kubectl/llm-proxy.yaml}"
: "${CLAUDE_PROXY_TOKEN:?set CLAUDE_PROXY_TOKEN=dummy (proxy reads OAuth from Keychain)}"
[ -f "$LLM_CONFIG" ] || { echo "LLM_CONFIG not found: $LLM_CONFIG"; exit 1; }

OUT_ROOT="${OUT_ROOT:-./datasets/kubectl-fx-v1}"
START_AT="${START_AT:-1}"
END_AT="${END_AT:-1}"
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

# Only verbs with fixture coverage: apply, create, delete, describe, get, label, patch, scale.
# NOT covered (would trigger LLM fallback): rollout, expose, autoscale, annotate, edit, replace.
SUBSETS=(
  "get,describe,delete"
  "apply,get,delete"
  "create,get,delete"
  "apply,create,get,delete"
  "get,describe,label,patch"
  "apply,get,label"
  "create,delete,scale"
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
  --pipeline-opt "cli_app_kubectl_fixture_dir=$FIXTURE_DIR"
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
  out="$OUT_ROOT/kubectl-fx-v1-t${n}"
  echo
  echo "===================================================================="
  echo "[kubectl-fx-v1] task ${n}/${#SUBSETS[@]} -> $out"
  echo "  subset: $subset"
  echo "  backend: kwok  (tests = hand-authored fixtures; golden = slicer; reference = LLM)"
  echo "  fixtures: $FIXTURE_DIR"
  echo "===================================================================="
  mkdir -p "$out"
  uv run repo2rlenv generate "${opts[@]}" \
    --pipeline-opt "cli_app_subsets=[\"${subset}\"]" \
    --config "$LLM_CONFIG" \
    --out "$out" 2>&1 | tee "$out/generate.log"
done

echo
echo "[kubectl-fx-v1] batch complete. Task dirs under: $OUT_ROOT/kubectl-fx-v1-t{${START_AT}..${END_AT}}/"
