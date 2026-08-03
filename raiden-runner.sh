#!/usr/bin/env bash
# raiden-runner.sh — parallel generate → harbor run → push pipeline
#
# Usage:
#   ./raiden-runner.sh [FLAGS] SUBSET [SUBSET...]
#
# Examples:
#   ./raiden-runner.sh mb cp ls
#   ./raiden-runner.sh mb,cp ls,mv,sync
#   ./raiden-runner.sh --agent openhands --parallel 4 mb cp,ls mb,cp,ls
#   ./raiden-runner.sh --resume mb cp ls          # skip already-completed subsets
#   ./raiden-runner.sh --dry-run mb,cp,ls

set -euo pipefail

readonly VALID_S3_COMMANDS="mb cp ls mv rm rb sync"
readonly HARBOR_TIMEOUT_SEC=3600

# ─── Defaults ──────────────────────────────────────────────────────────────────

REPO="aws/aws-cli"
REF="bb8fa8c1fec3523fa4cd8538071215f90c8ff97f"
PIPELINE="code_instruct"
AGENT="openhands-sdk"
MODEL="${R2E_LLM:-}"
HARBOR_ENV="docker"
BASE_OUT="./datasets/raiden"
TRAJ_BASE="/tmp/raiden-trajectories"
LOG_DIR="./logs/raiden-runner"
DATASET_REPO="https://github.com/Ethara-Ai/raiden-dataset.git"
DATASET_DIR="./.raiden-dataset"
# Top-level partition inside the dataset repo. Each model/eval run lands in its own
# sample_N folder so multiple runs coexist: $SAMPLE_DIR/dataset/<task> + $SAMPLE_DIR/trajectory/<task>.
SAMPLE_DIR="sample_1"
UV_EXTRA="bedrock"
ENV_FILE=".env"
# GOOGLE_APPLICATION_CREDENTIALS must be a file path, not inline JSON (google.auth
# opens it as a file); SA file is bind-mounted to this in-container path.
SA_CONTAINER_PATH="/tmp/raiden-sa.json"
# openhands-sdk agent config (matched to the ideal reference trajectory).
# max_iterations caps the agent's tool-call loop; reasoning_effort controls whether
# gemini-3.1-pro-preview's thinking mode is active (none = off, saves tokens).
MAX_ITERATIONS=1000
REASONING_EFFORT="high"
AGENT_SETUP_TIMEOUT_MULTIPLIER="5.0"
DRY_RUN=false
RESUME=false
PARALLEL=0
LIMIT=8
MAX_LLM_TOKENS=16000
MAX_LLM_SPEND_USD=50
CLI_APP_WORKFLOW_TESTS=3
CLI_APP_REFERENCE_GROUNDING=true
CLI_APP_MIN_GROUNDED_TESTS=3
CLI_APP_MAX_INTENTS=3
CLI_APP_DOCKER_GAUNTLET=true
CLI_APP_DOCKER_TIMEOUT_SEC=300

EXTRA_PIPELINE_OPTS=()
EXTRA_HARBOR_ARGS=()

# ─── Colors / helpers ─────────────────────────────────────────────────────────

_RED='\033[0;31m' _GREEN='\033[0;32m' _YELLOW='\033[0;33m'
_CYAN='\033[0;36m' _BOLD='\033[1m' _RESET='\033[0m'

_ts() { date '+%H:%M:%S'; }
log_info()    { printf "[%s] ${_CYAN}ⓘ %s${_RESET}\n" "$(_ts)" "$*"; }
log_ok()      { printf "[%s] ${_GREEN}✓ %s${_RESET}\n" "$(_ts)" "$*"; }
log_warn()    { printf "[%s] ${_YELLOW}⚠ %s${_RESET}\n" "$(_ts)" "$*"; }
log_error()   { printf "[%s] ${_RED}✗ %s${_RESET}\n" "$(_ts)" "$*" >&2; }
log_section() { printf "\n${_BOLD}── %s ──${_RESET}\n" "$*"; }

die() { log_error "$@"; exit 1; }

# ─── Signal handling ──────────────────────────────────────────────────────────
# Ctrl+C / SIGTERM must kill all background jobs so Docker + LLM calls stop

CHILD_PIDS=()

cleanup() {
  local sig="${1:-TERM}"
  log_warn "Caught SIG$sig — killing all background jobs..."
  for pid in "${CHILD_PIDS[@]+"${CHILD_PIDS[@]}"}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  rmdir "$GIT_LOCK_DIR" 2>/dev/null || true
  log_error "Aborted. Partial results in $LOG_DIR"
  exit 130
}

trap 'cleanup INT'  INT
trap 'cleanup TERM' TERM

# ─── Usage ─────────────────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
Usage: raiden-runner.sh [FLAGS] SUBSET [SUBSET...]

Flags:
  --repo REPO                  Target repo              (default: aws/aws-cli)
  --ref REF                    Git ref                  (default: bb8fa8c...)
  --pipeline NAME              Pipeline                 (default: code_instruct)
  --agent AGENT                Harbor agent             (default: openhands-sdk)
  --model MODEL                LLM model (or $R2E_LLM) (default: env R2E_LLM)
  --harbor-env ENV             Harbor environment       (default: docker)
  --out DIR                    Base output directory     (default: ./datasets/raiden)
  --traj-dir DIR               Trajectory output base   (default: /tmp/raiden-trajectories)
  --log-dir DIR                Log directory             (default: ./logs/raiden-runner)
  --dataset-repo URL           Push target repo          (default: Ethara-Ai/raiden-dataset)
  --dataset-dir DIR            Local dataset clone       (default: ./.raiden-dataset)
  --sample-dir DIR             Sample partition in repo  (default: sample_1)
  --parallel N                 Max parallel jobs (0=auto)(default: 0)
  --limit N                    Tasks per subset          (default: 8)
  --uv-extra EXTRA             UV extra for harbor       (default: bedrock)
  --env-file FILE              Source env vars from      (default: .env)
  --pipeline-opt KEY=VAL       Extra pipeline option     (repeatable)
  --harbor-arg ARG             Extra harbor run arg      (repeatable)
  --max-llm-tokens N           Max LLM tokens            (default: 16000)
  --max-llm-spend N            Max LLM spend USD         (default: 50)
  --max-iterations N           Agent max iterations      (default: 1000)
  --reasoning-effort LEVEL     LLM reasoning effort      (default: none)
  --resume                     Skip subsets already marked complete
  --dry-run                    Preview without executing
  -h, --help                   Show this help

Subsets:
  Space-separated S3 command combos. Examples: mb  cp,ls  mb,cp,ls,mv
  Valid commands: mb cp ls mv rm rb sync
EOF
  exit 0
}

# ─── Parse args ────────────────────────────────────────────────────────────────

SUBSETS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)           REPO="$2";           shift 2 ;;
    --ref)            REF="$2";            shift 2 ;;
    --pipeline)       PIPELINE="$2";       shift 2 ;;
    --agent)          AGENT="$2";          shift 2 ;;
    --model)          MODEL="$2";          shift 2 ;;
    --harbor-env)     HARBOR_ENV="$2";     shift 2 ;;
    --out)            BASE_OUT="$2";       shift 2 ;;
    --traj-dir)       TRAJ_BASE="$2";      shift 2 ;;
    --log-dir)        LOG_DIR="$2";        shift 2 ;;
    --dataset-repo)   DATASET_REPO="$2";   shift 2 ;;
    --dataset-dir)    DATASET_DIR="$2";    shift 2 ;;
    --sample-dir)     SAMPLE_DIR="$2";     shift 2 ;;
    --parallel)       PARALLEL="$2";       shift 2 ;;
    --limit)          LIMIT="$2";          shift 2 ;;
    --uv-extra)       UV_EXTRA="$2";       shift 2 ;;
    --env-file)       ENV_FILE="$2";       shift 2 ;;
    --pipeline-opt)   EXTRA_PIPELINE_OPTS+=("$2"); shift 2 ;;
    --harbor-arg)     EXTRA_HARBOR_ARGS+=("$2");   shift 2 ;;
    --max-llm-tokens) MAX_LLM_TOKENS="$2"; shift 2 ;;
    --max-llm-spend)  MAX_LLM_SPEND_USD="$2"; shift 2 ;;
    --max-iterations) MAX_ITERATIONS="$2"; shift 2 ;;
    --reasoning-effort) REASONING_EFFORT="$2"; shift 2 ;;
    --resume)         RESUME=true;         shift ;;
    --dry-run)        DRY_RUN=true;        shift ;;
    -h|--help)        usage ;;
    -*)               die "Unknown flag: $1" ;;
    *)                SUBSETS+=("$1");      shift ;;
  esac
done

[[ ${#SUBSETS[@]} -eq 0 ]] && die "No subsets specified. Run with --help for usage."

# ─── Load env file ─────────────────────────────────────────────────────────────

if [[ -f "$ENV_FILE" ]]; then
  log_info "Sourcing env from $ENV_FILE"
  set -a; source "$ENV_FILE"; set +a
fi

[[ -z "$MODEL" ]] && MODEL="${R2E_LLM:-}"
[[ -z "$MODEL" ]] && die "No model specified. Set --model or R2E_LLM env var."

# ─── Vertex AI credential forwarding ────────────────────────────────────────────

VERTEX_CRED_ARGS=()

build_vertex_cred_args() {
  [[ "$MODEL" == vertex_ai/* ]] || return 0

  local sa_host="${GOOGLE_APPLICATION_CREDENTIALS:-}"
  [[ -n "$sa_host" ]] || die "$MODEL needs GOOGLE_APPLICATION_CREDENTIALS (service-account JSON path)."
  [[ -f "$sa_host" ]] || die "Service-account file not found: $sa_host"
  [[ -n "${VERTEXAI_PROJECT:-}" ]] || die "$MODEL needs VERTEXAI_PROJECT."
  [[ -n "${VERTEXAI_LOCATION:-}" ]] || die "$MODEL needs VERTEXAI_LOCATION."

  local mounts
  mounts=$(printf '[{"type":"bind","source":"%s","target":"%s","read_only":true}]' \
    "$sa_host" "$SA_CONTAINER_PATH")

  VERTEX_CRED_ARGS=(
    --mounts-json "$mounts"
    --ae "GOOGLE_APPLICATION_CREDENTIALS=$SA_CONTAINER_PATH"
    --ae "VERTEXAI_PROJECT=$VERTEXAI_PROJECT"
    --ae "VERTEXAI_LOCATION=$VERTEXAI_LOCATION"
  )
  log_info "Vertex AI creds will be forwarded to the agent container (SA mounted at $SA_CONTAINER_PATH)"
}

build_vertex_cred_args

# ─── openhands-sdk agent flags ────────────────────────────────────────────────

AGENT_ARGS=()

build_agent_args() {
  [[ "$AGENT" == "openhands-sdk" ]] || return 0

  AGENT_ARGS+=(
    --ak "max_iterations=$MAX_ITERATIONS"
    --agent-setup-timeout-multiplier "$AGENT_SETUP_TIMEOUT_MULTIPLIER"
    --ae "LLM_REASONING_EFFORT=$REASONING_EFFORT"
    --ae "LITELLM_DROP_PARAMS=1"
  )

  if [[ "$MODEL" == vertex_ai/* ]]; then
    AGENT_ARGS+=(--ae "LLM_API_KEY=unused")
  else
    local api_key="${LLM_API_KEY:-${OPENAI_API_KEY:-${ANTHROPIC_API_KEY:-}}}"
    [[ -n "$api_key" ]] || die "openhands-sdk needs LLM_API_KEY for non-vertex models. Set LLM_API_KEY."
    AGENT_ARGS+=(--ae "LLM_API_KEY=$api_key")
  fi

  log_info "openhands-sdk: max_iterations=$MAX_ITERATIONS, reasoning=$REASONING_EFFORT, setup_timeout=${AGENT_SETUP_TIMEOUT_MULTIPLIER}x"
}

build_agent_args

# ─── Validate subsets ──────────────────────────────────────────────────────────

validate_subsets() {
  for subset in "${SUBSETS[@]}"; do
    IFS=',' read -ra cmds <<< "$subset"
    for cmd in "${cmds[@]}"; do
      if ! echo "$VALID_S3_COMMANDS" | grep -qw "$cmd"; then
        die "Invalid S3 command '$cmd' in subset '$subset'. Valid: $VALID_S3_COMMANDS"
      fi
    done
  done
}

validate_subsets

# ─── Auto-detect parallelism ──────────────────────────────────────────────────

auto_detect_parallel() {
  local cpus mem_gb

  if command -v nproc &>/dev/null; then
    cpus=$(nproc)
  elif [[ "$(uname)" == "Darwin" ]]; then
    cpus=$(sysctl -n hw.ncpu 2>/dev/null || echo 4)
  else
    cpus=4
  fi

  if [[ "$(uname)" == "Darwin" ]]; then
    mem_gb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8589934592) / 1073741824 ))
  elif [[ -f /proc/meminfo ]]; then
    mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1048576}' /proc/meminfo)
  else
    mem_gb=8
  fi

  # ~4 GB RAM + 2 CPU cores per harbor run
  local max_by_cpu=$(( cpus / 2 ))
  local max_by_mem=$(( mem_gb / 4 ))
  local result=$(( max_by_cpu < max_by_mem ? max_by_cpu : max_by_mem ))
  [[ $result -lt 1 ]] && result=1
  [[ $result -gt ${#SUBSETS[@]} ]] && result=${#SUBSETS[@]}

  echo "$result"
}

if [[ "$PARALLEL" -eq 0 ]]; then
  PARALLEL=$(auto_detect_parallel)
fi

# ─── State tracking (resume support) ──────────────────────────────────────────

STATE_DIR=""

init_state_dir() {
  STATE_DIR="$LOG_DIR/.state"
  mkdir -p "$STATE_DIR"
}

mark_subset_status() {
  local subset_slug="$1" status="$2"
  echo "$status" > "$STATE_DIR/$subset_slug"
}

get_subset_status() {
  local subset_slug="$1"
  [[ -f "$STATE_DIR/$subset_slug" ]] && cat "$STATE_DIR/$subset_slug" || echo "pending"
}

# ─── Git push lock (PID-based with stale detection) ──────────────────────────

GIT_LOCK_DIR=""

init_lock_dir() {
  GIT_LOCK_DIR="$DATASET_DIR/.raiden-push-lock"
}

git_push_locked() {
  local retries=0
  while ! mkdir "$GIT_LOCK_DIR" 2>/dev/null; do
    # Stale lock detection: check if holder PID is still alive
    if [[ -f "$GIT_LOCK_DIR/pid" ]]; then
      local holder_pid
      holder_pid=$(<"$GIT_LOCK_DIR/pid")
      if ! kill -0 "$holder_pid" 2>/dev/null; then
        log_warn "Stale lock from dead PID $holder_pid — breaking"
        rm -rf "$GIT_LOCK_DIR"
        continue
      fi
    fi
    retries=$((retries + 1))
    if [[ $retries -gt 120 ]]; then
      log_error "Git push lock timeout after 120s"
      return 1
    fi
    sleep 1
  done
  echo $$ > "$GIT_LOCK_DIR/pid"

  local rc=0
  _do_git_push "$@" || rc=$?

  rm -rf "$GIT_LOCK_DIR" 2>/dev/null || true
  return $rc
}

_do_git_push() {
  local task_dir="$1" traj_dir="$2"
  local task_name
  task_name=$(basename "$task_dir")

  local data_dest="$DATASET_DIR/$SAMPLE_DIR/dataset/$task_name"
  local traj_dest="$DATASET_DIR/$SAMPLE_DIR/trajectory/$task_name"

  # Sync with remote before touching anything
  git -C "$DATASET_DIR" fetch --quiet origin 2>/dev/null || true
  git -C "$DATASET_DIR" reset --quiet --hard origin/main 2>/dev/null \
    || git -C "$DATASET_DIR" reset --quiet --hard origin/master 2>/dev/null \
    || true

  mkdir -p "$data_dest"
  cp -a "$task_dir/." "$data_dest/"

  if [[ -d "$traj_dir" ]] && [[ -n "$(ls -A "$traj_dir" 2>/dev/null)" ]]; then
    mkdir -p "$traj_dest"
    cp -a "$traj_dir/." "$traj_dest/"
  fi

  git -C "$DATASET_DIR" add "$SAMPLE_DIR/dataset/$task_name" "$SAMPLE_DIR/trajectory/$task_name" 2>/dev/null || true
  if git -C "$DATASET_DIR" diff --cached --quiet 2>/dev/null; then
    return 0
  fi

  git -C "$DATASET_DIR" commit -q -m "add: $task_name (dataset + trajectory)"

  # Resolve the current local branch so the first push to an empty remote
  # can set upstream explicitly (a fresh repo has no origin/main to track).
  local branch
  branch=$(git -C "$DATASET_DIR" symbolic-ref --short HEAD 2>/dev/null || echo main)

  local push_retries=0
  while ! git -C "$DATASET_DIR" push --quiet -u origin "$branch" 2>/dev/null; do
    push_retries=$((push_retries + 1))
    if [[ $push_retries -gt 5 ]]; then
      log_error "Push failed after 5 retries for $task_name"
      return 1
    fi
    # Only rebase if the remote branch actually exists; on an empty remote
    # there is nothing to rebase onto, so skip straight to retry.
    if git -C "$DATASET_DIR" ls-remote --exit-code --heads origin "$branch" &>/dev/null; then
      git -C "$DATASET_DIR" pull --rebase --quiet origin "$branch" 2>/dev/null || {
        log_error "Rebase conflict for $task_name — cannot auto-resolve"
        git -C "$DATASET_DIR" rebase --abort 2>/dev/null || true
        return 1
      }
    fi
    sleep $((push_retries * 2))
  done
}

# ─── Clone / prepare dataset repo ─────────────────────────────────────────────

prepare_dataset_repo() {
  if [[ -d "$DATASET_DIR/.git" ]]; then
    log_info "Dataset repo exists at $DATASET_DIR, pulling latest..."
    git -C "$DATASET_DIR" pull --ff-only --quiet || true
  else
    log_info "Cloning dataset repo → $DATASET_DIR"
    git clone --quiet "$DATASET_REPO" "$DATASET_DIR"
  fi
  mkdir -p "$DATASET_DIR/$SAMPLE_DIR/dataset" "$DATASET_DIR/$SAMPLE_DIR/trajectory"
}

# ─── Verify a harbor run actually succeeded ──────────────────────────────────
# `harbor run` exits 0 even when a trial errors internally, so the process exit
# code is not a reliable success signal. The authoritative result is the top-level
# result.json (<task_traj>/<timestamp>/result.json) whose stats.n_errored_trials is
# >0 on failure. Treat success as: a result.json exists AND n_errored_trials==0.
harbor_trial_succeeded() {
  local task_traj="$1"
  local result_json
  result_json=$(ls -t "$task_traj"/*/result.json 2>/dev/null | head -1)
  if [[ -z "$result_json" || ! -f "$result_json" ]]; then
    return 1
  fi
  python3 - "$result_json" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except Exception:
    sys.exit(1)
errored = data.get("stats", {}).get("n_errored_trials")
sys.exit(0 if errored == 0 else 1)
PY
}

# ─── Run one subset ──────────────────────────────────────────────────────────
# All stdout/stderr goes to log file. Only structured status lines to console.

run_subset() {
  local subset="$1"
  local subset_slug="${subset//,/_}"
  local subset_out="$BASE_OUT/$subset_slug"
  local subset_traj="$TRAJ_BASE/$subset_slug"
  local subset_log="$LOG_DIR/$subset_slug"
  local log_file="$subset_log/full.log"

  mkdir -p "$subset_out" "$subset_traj" "$subset_log"
  mark_subset_status "$subset_slug" "running"

  exec 3>&1 4>&2
  exec > "$log_file" 2>&1

  log_ok "[$subset_slug] Starting generate" >&3

  local gen_cmd=(
    uv run repo2rlenv generate
    --repo "$REPO"
    --ref "$REF"
    --pipeline "$PIPELINE"
    --pipeline-opt "mode=cli_app"
    --pipeline-opt "cli_app_command_prefix=s3"
    --pipeline-opt "cli_app_subsets=[\"$subset\"]"
    --pipeline-opt "limit=$LIMIT"
    --pipeline-opt "cli_app_workflow_tests=$CLI_APP_WORKFLOW_TESTS"
    --pipeline-opt "cli_app_reference_grounding=$CLI_APP_REFERENCE_GROUNDING"
    --pipeline-opt "cli_app_min_grounded_tests=$CLI_APP_MIN_GROUNDED_TESTS"
    --pipeline-opt "cli_app_max_intents=$CLI_APP_MAX_INTENTS"
    --pipeline-opt "max_llm_tokens=$MAX_LLM_TOKENS"
    --pipeline-opt "max_llm_spend_usd=$MAX_LLM_SPEND_USD"
    --pipeline-opt "cli_app_docker_gauntlet=$CLI_APP_DOCKER_GAUNTLET"
    --pipeline-opt "cli_app_docker_timeout_sec=$CLI_APP_DOCKER_TIMEOUT_SEC"
    --llm "$MODEL"
    --out "$subset_out"
  )
  for opt in "${EXTRA_PIPELINE_OPTS[@]+"${EXTRA_PIPELINE_OPTS[@]}"}"; do
    gen_cmd+=(--pipeline-opt "$opt")
  done

  if ! "${gen_cmd[@]}"; then
    log_error "[$subset_slug] Generate failed. See $log_file" >&4
    mark_subset_status "$subset_slug" "failed:generate"
    exec 1>&3 2>&4 3>&- 4>&-
    return 1
  fi
  log_ok "[$subset_slug] Generate complete" >&3

  local task_count=0 task_ok=0 task_fail=0

  for task_dir in "$subset_out"/*/; do
    [[ -f "${task_dir}task.toml" ]] || continue
    task_count=$((task_count + 1))

    local task_name
    task_name=$(basename "$task_dir")
    local task_traj="$subset_traj/$task_name"
    mkdir -p "$task_traj"

    log_info "[$subset_slug] Harbor run: $task_name" >&3

    local harbor_cmd=(
      uv run --extra "$UV_EXTRA"
      harbor run
      -p "$task_dir"
      -a "$AGENT"
      -m "$MODEL"
      -e "$HARBOR_ENV"
      -o "$task_traj"
    )
    if [[ ${#AGENT_ARGS[@]} -gt 0 ]]; then
      harbor_cmd+=("${AGENT_ARGS[@]}")
    fi
    if [[ -n "${VERTEX_CRED_ARGS[*]+x}" && ${#VERTEX_CRED_ARGS[@]} -gt 0 ]]; then
      harbor_cmd+=("${VERTEX_CRED_ARGS[@]}")
    fi
    for arg in "${EXTRA_HARBOR_ARGS[@]+"${EXTRA_HARBOR_ARGS[@]}"}"; do
      harbor_cmd+=("$arg")
    done

    local harbor_rc=0
    if command -v timeout &>/dev/null; then
      timeout "$HARBOR_TIMEOUT_SEC" "${harbor_cmd[@]}" || harbor_rc=$?
    else
      "${harbor_cmd[@]}" || harbor_rc=$?
    fi

    if [[ $harbor_rc -eq 124 ]]; then
      log_error "[$subset_slug] Harbor TIMEOUT after ${HARBOR_TIMEOUT_SEC}s: $task_name" >&4
      task_fail=$((task_fail + 1))
      continue
    elif [[ $harbor_rc -ne 0 ]]; then
      log_error "[$subset_slug] Harbor failed (exit $harbor_rc): $task_name. See $log_file" >&4
      task_fail=$((task_fail + 1))
      continue
    fi

    if ! harbor_trial_succeeded "$task_traj"; then
      log_error "[$subset_slug] Harbor trial ERRORED (harbor exit 0 but result.json shows errors): $task_name. See $log_file" >&4
      task_fail=$((task_fail + 1))
      continue
    fi

    log_ok "[$subset_slug] Harbor done: $task_name" >&3

    if git_push_locked "$task_dir" "$task_traj"; then
      log_ok "[$subset_slug] Pushed: $task_name" >&3
    else
      log_warn "[$subset_slug] Push failed for $task_name (non-fatal)" >&3
    fi

    task_ok=$((task_ok + 1))
  done

  exec 1>&3 2>&4 3>&- 4>&-

  if [[ $task_count -eq 0 ]]; then
    log_warn "[$subset_slug] No tasks generated"
    mark_subset_status "$subset_slug" "failed:no_tasks"
    return 1
  fi

  local status="complete"
  [[ $task_fail -gt 0 ]] && status="partial"
  mark_subset_status "$subset_slug" "$status:${task_ok}ok_${task_fail}fail_of_${task_count}"

  log_info "[$subset_slug] Done: $task_ok/$task_count succeeded"
  return 0
}

run_subset_dry() {
  local subset="$1"
  local subset_slug="${subset//,/_}"
  log_info "[DRY RUN] $subset_slug"
  log_info "  generate: uv run repo2rlenv generate --repo $REPO --ref ${REF:0:8}... --pipeline $PIPELINE --pipeline-opt 'cli_app_subsets=[\"$subset\"]' --llm \$MODEL --out $BASE_OUT/$subset_slug"
  log_info "  harbor:   uv run --extra $UV_EXTRA harbor run -a $AGENT -m \$MODEL -e $HARBOR_ENV (per task, timeout ${HARBOR_TIMEOUT_SEC}s)"
  if [[ "$AGENT" == "openhands-sdk" ]]; then
    log_info "  sdk:      --ak max_iterations=$MAX_ITERATIONS --ae LLM_REASONING_EFFORT=$REASONING_EFFORT --agent-setup-timeout-multiplier $AGENT_SETUP_TIMEOUT_MULTIPLIER"
  fi
  if [[ -n "${VERTEX_CRED_ARGS[*]+x}" && ${#VERTEX_CRED_ARGS[@]} -gt 0 ]]; then
    log_info "  creds:    forwarding Vertex AI SA (--mounts-json bind $SA_CONTAINER_PATH + --ae GOOGLE_APPLICATION_CREDENTIALS/VERTEXAI_PROJECT/VERTEXAI_LOCATION)"
  fi
  log_info "  push:     git push to $DATASET_REPO"
}

# ─── Summary report ───────────────────────────────────────────────────────────

write_summary() {
  local report_file="$LOG_DIR/summary.json"
  local entries=()
  for subset in "${SUBSETS[@]}"; do
    local slug="${subset//,/_}"
    local status
    status=$(get_subset_status "$slug")
    entries+=("    {\"subset\": \"$subset\", \"status\": \"$status\"}")
  done

  local joined
  joined=$(IFS=$'\n'; echo "${entries[*]}" | paste -sd ',' -)

  cat > "$report_file" <<EOF
{
  "timestamp": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "repo": "$REPO",
  "ref": "$REF",
  "agent": "$AGENT",
  "pipeline": "$PIPELINE",
  "parallel": $PARALLEL,
  "subsets": [
$joined
  ]
}
EOF
  log_info "Report: $report_file"
}

# ─── Main ──────────────────────────────────────────────────────────────────────

main() {
  log_section "Raiden Runner"
  log_info "Subsets:   ${SUBSETS[*]} (${#SUBSETS[@]} total)"
  log_info "Parallel:  $PARALLEL"
  log_info "Agent:     $AGENT"
  log_info "Model:     $MODEL"
  log_info "Pipeline:  $PIPELINE"
  log_info "Repo:      $REPO@${REF:0:8}"
  log_info "Output:    $BASE_OUT"
  log_info "Logs:      $LOG_DIR"
  log_info "Dataset:   $DATASET_REPO"
  $RESUME && log_info "Mode:      RESUME (skipping completed subsets)"

  mkdir -p "$BASE_OUT" "$TRAJ_BASE" "$LOG_DIR"
  init_state_dir
  init_lock_dir

  if $DRY_RUN; then
    for subset in "${SUBSETS[@]}"; do
      run_subset_dry "$subset"
    done
    return 0
  fi

  prepare_dataset_repo

  local pids=()
  local pid_to_subset=()
  local running=0
  local total=${#SUBSETS[@]}
  local completed=0
  local succeeded=0
  local failed=0
  local skipped=0

  log_section "Launching $total subsets (max $PARALLEL parallel)"

  for subset in "${SUBSETS[@]}"; do
    local slug="${subset//,/_}"

    if $RESUME; then
      local prev_status
      prev_status=$(get_subset_status "$slug")
      if [[ "$prev_status" == complete:* ]]; then
        log_info "Skipping $subset (already complete: $prev_status)"
        skipped=$((skipped + 1))
        completed=$((completed + 1))
        succeeded=$((succeeded + 1))
        continue
      fi
    fi

    while [[ $running -ge $PARALLEL ]]; do
      local reaped=false
      for i in "${!pids[@]}"; do
        if ! kill -0 "${pids[$i]}" 2>/dev/null; then
          wait "${pids[$i]}" 2>/dev/null && succeeded=$((succeeded + 1)) || failed=$((failed + 1))
          completed=$((completed + 1))
          log_info "Progress: $completed/$total (${pid_to_subset[$i]} done)"
          unset 'pids[i]' 'pid_to_subset[i]'
          running=$((running - 1))
          reaped=true
          break
        fi
      done
      if ! $reaped; then
        sleep 2
      fi
      pids=("${pids[@]+"${pids[@]}"}")
      pid_to_subset=("${pid_to_subset[@]+"${pid_to_subset[@]}"}")
    done

    log_info "Starting subset: $subset"
    run_subset "$subset" &
    local child_pid=$!
    pids+=("$child_pid")
    pid_to_subset+=("$subset")
    CHILD_PIDS+=("$child_pid")
    running=$((running + 1))
  done

  for i in "${!pids[@]}"; do
    wait "${pids[$i]}" 2>/dev/null && succeeded=$((succeeded + 1)) || failed=$((failed + 1))
    completed=$((completed + 1))
    log_info "Progress: $completed/$total (${pid_to_subset[$i]} done)"
  done

  rm -rf "$GIT_LOCK_DIR" 2>/dev/null || true

  write_summary

  log_section "FINAL SUMMARY"
  log_info "Total:     $total subsets"
  log_ok   "Succeeded: $succeeded"
  [[ $skipped -gt 0 ]] && log_info "Skipped:   $skipped (resumed)"
  [[ $failed  -gt 0 ]] && log_error "Failed:    $failed"
  log_info "Logs:      $LOG_DIR"
  log_info "Datasets:  $BASE_OUT"
  log_info "Pushed to: $DATASET_REPO"

  [[ $failed -gt 0 ]] && exit 1
  exit 0
}

main
