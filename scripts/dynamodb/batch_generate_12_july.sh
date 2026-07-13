#!/usr/bin/env bash
#
# 12-july-50-tasks DDB batch generator. Runs the code_instruct pipeline
# across 50 hard subsets from 50_hard_subsets.tsv at concurrency=PARALLEL.
#
# Env (required):
#   CLAUDE_PROXY_TOKEN   any non-empty value (proxy reads OAuth from Keychain)
# Env (optional):
#   LLM_CONFIG           default: scripts/dynamodb/llm-proxy.yaml
#   OUT_ROOT             default: ./datasets/12-july-50-tasks
#   SUBSETS_TSV          default: scripts/dynamodb/50_hard_subsets.tsv
#   PARALLEL             default: 3
#   TIMEOUT_SEC          per-task hard cap, default 2700 (45 min)
#   START_AT / END_AT    resume window, default 1 / 50
#
# Output layout:
#   $OUT_ROOT/
#     ddb-batch-t01/generate.log + <uuid>/{task.toml, instruction.md, ...}
#     ddb-batch-t02/...
#     batch_manifest.tsv   (nn, subset, start_utc, end_utc, exit, uuid)
#     batch_master.log     (aggregated START/END markers)

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HARNESS_DIR"

SUBSETS_TSV="${SUBSETS_TSV:-scripts/dynamodb/50_hard_subsets.tsv}"
LLM_CONFIG="${LLM_CONFIG:-scripts/dynamodb/llm-proxy.yaml}"
export CLAUDE_PROXY_TOKEN="${CLAUDE_PROXY_TOKEN:-dummy}"
OUT_ROOT="${OUT_ROOT:-./datasets/12-july-50-tasks}"
TIMEOUT_SEC="${TIMEOUT_SEC:-2700}"
PARALLEL="${PARALLEL:-3}"
START_AT="${START_AT:-1}"
END_AT="${END_AT:-50}"

[ -f "$LLM_CONFIG" ] || { echo "LLM_CONFIG not found: $LLM_CONFIG"; exit 1; }
[ -f "$SUBSETS_TSV" ] || { echo "SUBSETS_TSV not found: $SUBSETS_TSV"; exit 1; }

if ! curl -sf http://localhost:8765/health > /dev/null; then
  echo "proxy at localhost:8765 not responding - start it with:"
  echo "  uv run proxy/claude_oauth_proxy.py --port 8765"
  exit 1
fi

if ! docker info > /dev/null 2>&1; then
  echo "docker daemon not running"
  exit 1
fi

if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN="gtimeout"
else
  echo "GNU 'timeout' not found. Install: brew install coreutils, then re-run."
  echo "  (macOS coreutils installs the binary as 'gtimeout' by default; both are accepted.)"
  exit 1
fi

mkdir -p "$OUT_ROOT"
MANIFEST="$OUT_ROOT/batch_manifest.tsv"
MASTER_LOG="$OUT_ROOT/batch_master.log"
if [ ! -f "$MANIFEST" ]; then
  printf 'nn\tsubset\tstart_utc\tend_utc\texit\tuuid\n' > "$MANIFEST"
fi
touch "$MASTER_LOG"

run_one() {
  local nn="$1"
  local subset="$2"
  local out="$OUT_ROOT/ddb-batch-t${nn}"
  local log="$out/generate.log"
  mkdir -p "$out"
  local start_ts; start_ts="$(date -u +%FT%TZ)"
  echo "[$(date -u +%FT%TZ)] START t${nn} subset=${subset}" | tee -a "$MASTER_LOG"

  set +e
  "$TIMEOUT_BIN" "$TIMEOUT_SEC" uv run repo2rlenv generate \
    --repo aws/aws-cli --ref v2 --pipeline code_instruct \
    --pipeline-opt mode=cli_app \
    --pipeline-opt cli_app_command_prefix=dynamodb \
    --pipeline-opt cli_app_backend=dynamodb_local \
    --pipeline-opt cli_app_extract_mode=botocore_model \
    --pipeline-opt cli_app_oracle=golden \
    --pipeline-opt cli_app_workflow_tests=12 \
    --pipeline-opt cli_app_max_intents=50 \
    --pipeline-opt cli_app_min_grounded_tests=12 \
    --pipeline-opt cli_app_min_tests_final=25 \
    --pipeline-opt cli_app_min_happy_path=8 \
    --pipeline-opt cli_app_min_error_nonexistent=2 \
    --pipeline-opt cli_app_min_error_invalid_args=5 \
    --pipeline-opt cli_app_min_workflow=5 \
    --pipeline-opt cli_app_min_edge=2 \
    --pipeline-opt max_llm_tokens=65000 \
    --pipeline-opt cli_app_docker_timeout_sec=1200 \
    --pipeline-opt cli_app_translate_workers=4 \
    --pipeline-opt cli_app_docker_gauntlet=true \
    --pipeline-opt cli_app_reference_grounding=true \
    --pipeline-opt "cli_app_subsets=[\"${subset}\"]" \
    --config "$LLM_CONFIG" \
    --out "$out" > "$log" 2>&1
  local rc=$?
  set -e

  local end_ts; end_ts="$(date -u +%FT%TZ)"
  local uuid=""
  if grep -qE 'cli_app: emitted [0-9a-f-]{36}' "$log" 2>/dev/null; then
    uuid="$(grep -Eo 'cli_app: emitted [0-9a-f-]{36}' "$log" | tail -1 | awk '{print $NF}')"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$nn" "$subset" "$start_ts" "$end_ts" "$rc" "${uuid:-}" >> "$MANIFEST"
  echo "[$(date -u +%FT%TZ)] END t${nn} rc=${rc} uuid=${uuid:-none}" | tee -a "$MASTER_LOG"
}
export -f run_one
export OUT_ROOT MANIFEST MASTER_LOG TIMEOUT_BIN TIMEOUT_SEC LLM_CONFIG HARNESS_DIR CLAUDE_PROXY_TOKEN

echo "[$(date -u +%FT%TZ)] BATCH START PARALLEL=${PARALLEL} range=${START_AT}..${END_AT}" | tee -a "$MASTER_LOG"

# Pipe-delimit NN|subset: BSD xargs -I{} would split TSV on whitespace/tabs.
awk -F$'\t' -v S="$START_AT" -v E="$END_AT" '
  NR==1 { next }
  { n = $1 + 0; if (n >= S && n <= E) print $1 "|" $2 }
' "$SUBSETS_TSV" | \
  xargs -P "$PARALLEL" -I{} bash -c '
    IFS="|" read -r nn subset <<<"$1"
    run_one "$nn" "$subset"
  ' _ "{}"

echo "[$(date -u +%FT%TZ)] BATCH DONE. See $MANIFEST" | tee -a "$MASTER_LOG"
