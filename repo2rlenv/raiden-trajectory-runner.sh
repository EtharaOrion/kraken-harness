#!/usr/bin/env bash
# raiden-trajectory-runner.sh
#
# Runs harbor trajectories over a set of PRE-EXISTING Harbor task directories
# (no generation step), for one or more models, and pushes results into the
# Ethara-Ai/raiden-dataset repo under a sample partition.
#
# Layout written to the dataset repo:
#   <sample>/dataset/<uuid>/                     (shared task inputs, model-agnostic)
#   <sample>/trajectory/<uuid>/<model-slug>/<date>/...   (per-model trajectory output)
#
# Each model loops over every task. The dataset copy is shared, so it is only
# written once per uuid; the per-model trajectory is nested under the model slug
# so multiple models coexist for the same task without collision.

set -uo pipefail

# ─── Config ───────────────────────────────────────────────────────────────────

DATASET_SRC="/Users/apple/Sources/harness/opus_datasets/dataset"
DATASET_REPO="https://github.com/Ethara-Ai/raiden-dataset.git"
DATASET_DIR="./.raiden-dataset"
SAMPLE_DIR="sample_2"

AGENT="openhands-sdk"
HARBOR_ENV="docker"
TRAJ_BASE="/tmp/raiden-traj-multi"
LOG_DIR="./logs/raiden-trajectory"
UV_EXTRA="bedrock"
ENV_FILE=".env"

# Service-account JSON is bind-mounted to this in-container path for Vertex runs.
SA_CONTAINER_PATH="/tmp/raiden-sa.json"

# openhands-sdk agent config (matched to the sample_1 reference trajectory).
MAX_ITERATIONS=1000
REASONING_EFFORT="high"
AGENT_SETUP_TIMEOUT_MULTIPLIER="5.0"
HARBOR_TIMEOUT_SEC=28800

DRY_RUN=false

# Model specs: each entry is "slug|litellm_model_id|auth_kind".
# auth_kind values are handled in build_model_args (vertex_api_key, openai).
MODELS=(
  "opus-4.8|vertex_ai/claude-opus-4-8|vertex_api_key"
  "opus-4.7|vertex_ai/claude-opus-4-7|vertex_api_key"
  "gpt-5.5|openai/gpt-5.5|openai"
)

# ─── Colors / helpers ──────────────────────────────────────────────────────────

_RED='\033[0;31m' _GREEN='\033[0;32m' _YELLOW='\033[0;33m'
_CYAN='\033[0;36m' _BOLD='\033[1m' _RESET='\033[0m'

_ts() { date '+%H:%M:%S'; }
log_info()    { printf "[%s] ${_CYAN}ⓘ %s${_RESET}\n" "$(_ts)" "$*"; }
log_ok()      { printf "[%s] ${_GREEN}✓ %s${_RESET}\n" "$(_ts)" "$*"; }
log_warn()    { printf "[%s] ${_YELLOW}⚠ %s${_RESET}\n" "$(_ts)" "$*"; }
log_error()   { printf "[%s] ${_RED}✗ %s${_RESET}\n" "$(_ts)" "$*" >&2; }
log_section() { printf "\n${_BOLD}── %s ──${_RESET}\n" "$*"; }

die() { log_error "$@"; exit 1; }

# ─── Usage ───────────────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
Usage: raiden-trajectory-runner.sh [FLAGS]

Runs harbor trajectories over existing task dirs for opus-4.8 + gpt-5.5,
pushing to sample_2 of Ethara-Ai/raiden-dataset.

Flags:
  --dataset-src DIR     Source of existing task dirs (default: opus_datasets/dataset)
  --dataset-repo URL    Push target repo            (default: Ethara-Ai/raiden-dataset)
  --dataset-dir DIR     Local dataset clone         (default: ./.raiden-dataset)
  --sample-dir DIR      Sample partition in repo     (default: sample_2)
  --model SLUG          Run only this model slug (repeatable; default: all)
  --env-file FILE       Source env vars from         (default: .env)
  --dry-run             Preview commands without executing
  -h, --help            Show this help

Running models in PARALLEL (one process per model):
  ./raiden-trajectory-runner.sh --model opus-4.8 &
  ./raiden-trajectory-runner.sh --model gpt-5.5  &
  wait
  With a single --model and no explicit --dataset-dir, each instance gets its
  own clone dir (./.raiden-dataset-<slug>) automatically, so the two processes
  push to the shared repo concurrently without clobbering each other.
EOF
  exit 0
}

# ─── Parse args ────────────────────────────────────────────────────────────────

MODEL_FILTER=()
DATASET_DIR_EXPLICIT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dataset-src)  DATASET_SRC="$2";  shift 2 ;;
    --dataset-repo) DATASET_REPO="$2"; shift 2 ;;
    --dataset-dir)  DATASET_DIR="$2"; DATASET_DIR_EXPLICIT=true; shift 2 ;;
    --sample-dir)   SAMPLE_DIR="$2";   shift 2 ;;
    --model)        MODEL_FILTER+=("$2"); shift 2 ;;
    --env-file)     ENV_FILE="$2";     shift 2 ;;
    --dry-run)      DRY_RUN=true;      shift ;;
    -h|--help)      usage ;;
    -*)             die "Unknown flag: $1" ;;
    *)              die "Unexpected argument: $1" ;;
  esac
done

# Parallel-safety: each instance needs its OWN clone dir or two processes will
# corrupt each other's working tree (the push retry loop only makes the git side
# race-safe, not the shared cp/add). When a single --model is selected (the
# per-model parallel pattern) and the user didn't pin --dataset-dir, derive a
# per-model clone dir automatically so `--model A &` and `--model B &` are safe.
if ! $DATASET_DIR_EXPLICIT && [[ ${#MODEL_FILTER[@]} -eq 1 ]]; then
  DATASET_DIR="${DATASET_DIR}-${MODEL_FILTER[0]}"
fi

# ─── Signal handling ──────────────────────────────────────────────────────────

CHILD_PIDS=()
cleanup() {
  log_warn "Caught signal — killing background jobs..."
  for pid in "${CHILD_PIDS[@]+"${CHILD_PIDS[@]}"}"; do
    kill -0 "$pid" 2>/dev/null && kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit 130
}
trap 'cleanup' INT TERM

# ─── Load env ──────────────────────────────────────────────────────────────────

if [[ -f "$ENV_FILE" ]]; then
  log_info "Sourcing env from $ENV_FILE"
  set -a; source "$ENV_FILE"; set +a
fi

[[ -d "$DATASET_SRC" ]] || die "Dataset source not found: $DATASET_SRC"

# ─── Build per-model harbor flag arrays ─────────────────────────────────────────
# Echoes the extra harbor args for a model on stdout, one arg per line, so the
# caller can read them into an array. Validates required credentials up front.

build_model_args() {
  local model_id="$1" auth_kind="$2"
  local -a args=(
    --ak "max_iterations=$MAX_ITERATIONS"
    --agent-setup-timeout-multiplier "$AGENT_SETUP_TIMEOUT_MULTIPLIER"
    --ae "LLM_REASONING_EFFORT=$REASONING_EFFORT"
    --ae "LITELLM_DROP_PARAMS=1"
  )

  case "$auth_kind" in
    vertex_api_key)
      [[ -n "${VERTEXAI_API_KEY:-}" ]] || die "$model_id needs VERTEXAI_API_KEY"
      [[ -n "${VERTEXAI_PROJECT:-}" ]] || die "$model_id needs VERTEXAI_PROJECT"
      [[ -n "${VERTEXAI_LOCATION:-}" ]] || die "$model_id needs VERTEXAI_LOCATION"
      local sa_host="${GOOGLE_APPLICATION_CREDENTIALS:-}"
      [[ -n "$sa_host" && -f "$sa_host" ]] || die "$model_id needs a valid GOOGLE_APPLICATION_CREDENTIALS file"
      local mounts
      mounts=$(printf '[{"type":"bind","source":"%s","target":"%s","read_only":true}]' \
        "$sa_host" "$SA_CONTAINER_PATH")
      args+=(
        --mounts-json "$mounts"
        --ae "LLM_API_KEY=$VERTEXAI_API_KEY"
        --ae "GOOGLE_APPLICATION_CREDENTIALS=$SA_CONTAINER_PATH"
        --ae "VERTEXAI_PROJECT=$VERTEXAI_PROJECT"
        --ae "VERTEXAI_LOCATION=$VERTEXAI_LOCATION"
      )
      ;;
    openai)
      [[ -n "${OPENAI_API_KEY:-}" ]] || die "$model_id needs OPENAI_API_KEY"
      args+=(--ae "LLM_API_KEY=$OPENAI_API_KEY")
      ;;
    *)
      die "Unknown auth_kind: $auth_kind"
      ;;
  esac

  printf '%s\n' "${args[@]}"
}

# ─── Verify a harbor run actually succeeded ──────────────────────────────────
# harbor exits 0 even when a trial errors; the authoritative signal is the
# top-level result.json with stats.n_errored_trials == 0.

harbor_trial_succeeded() {
  local task_traj="$1" result_json
  result_json=$(ls -t "$task_traj"/*/result.json 2>/dev/null | head -1)
  [[ -n "$result_json" && -f "$result_json" ]] || return 1
  python3 - "$result_json" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
sys.exit(0 if data.get("stats", {}).get("n_errored_trials") == 0 else 1)
PY
}

# ─── Clone / prepare dataset repo ─────────────────────────────────────────────

prepare_dataset_repo() {
  if [[ -d "$DATASET_DIR/.git" ]]; then
    log_info "Dataset repo exists at $DATASET_DIR, syncing..."
    git -C "$DATASET_DIR" fetch --quiet origin 2>/dev/null || true
    git -C "$DATASET_DIR" reset --quiet --hard origin/main 2>/dev/null || true
  else
    log_info "Cloning dataset repo → $DATASET_DIR"
    git clone --quiet "$DATASET_REPO" "$DATASET_DIR" || die "Clone failed: $DATASET_REPO"
  fi
  mkdir -p "$DATASET_DIR/$SAMPLE_DIR/dataset" "$DATASET_DIR/$SAMPLE_DIR/trajectory"
}

# ─── Push one (task, model) result into the dataset repo ──────────────────────

#
# Safe under PARALLEL instances (one clone dir per instance). The entire
# fetch→reset→copy→commit→push is INSIDE the retry loop: every attempt rebuilds
# the commit from the source files on top of the latest origin/main, so we never
# rebase and can never hit a lost-update race. `reset --hard` is safe here because
# no local commit ever survives between attempts — we always re-copy from source.
push_result() {
  local task_dir="$1" traj_dir="$2" model_slug="$3"
  local task_name
  task_name=$(basename "$task_dir")

  # Guard: never push an empty trajectory (caller already verified the run, but
  # be defensive). This is checked once up front; source files don't change.
  [[ -n "$(ls -A "$traj_dir" 2>/dev/null)" ]] || { log_warn "Empty trajectory for $task_name/$model_slug — skipping push"; return 1; }

  local data_dest="$DATASET_DIR/$SAMPLE_DIR/dataset/$task_name"
  local traj_dest="$DATASET_DIR/$SAMPLE_DIR/trajectory/$task_name/$model_slug"

  local max_attempts=7
  local attempt=0
  while :; do
    attempt=$((attempt + 1))
    if [[ $attempt -gt $max_attempts ]]; then
      log_error "Push failed after $max_attempts attempts for $task_name/$model_slug"
      return 1
    fi
    # Jittered backoff on retries to de-synchronise contending instances.
    [[ $attempt -gt 1 ]] && sleep $(( (attempt - 1) * 2 + (RANDOM % 3) ))

    # 1. Sync to the latest remote HEAD.
    if ! git -C "$DATASET_DIR" fetch --quiet origin main 2>/dev/null; then
      log_warn "[$model_slug] fetch failed (attempt $attempt) for $task_name"
      continue
    fi
    git -C "$DATASET_DIR" reset --quiet --hard origin/main 2>/dev/null || true

    # 2. (Re)apply our content. Idempotent: dataset/ is byte-identical across
    #    models, so re-copying another instance's already-pushed dataset is a no-op
    #    to git. trajectory/<slug>/ is disjoint per model.
    mkdir -p "$data_dest"
    cp -a "$task_dir/." "$data_dest/"
    mkdir -p "$traj_dest"
    cp -a "$traj_dir/." "$traj_dest/"

    # 3. Stage ONLY our paths — the shared dataset and THIS model's trajectory.
    #    Narrow scope avoids touching sibling models' trajectories.
    git -C "$DATASET_DIR" add \
      "$SAMPLE_DIR/dataset/$task_name" \
      "$SAMPLE_DIR/trajectory/$task_name/$model_slug" 2>/dev/null || true

    # 4. Nothing staged → content already on origin/main. Done.
    if git -C "$DATASET_DIR" diff --cached --quiet 2>/dev/null; then
      return 0
    fi

    git -C "$DATASET_DIR" commit -q -m "add: $task_name trajectory ($model_slug)"

    # 5. Push. On rejection (someone advanced main), loop: fetch+reset rebuilds
    #    the commit on the new HEAD. No rebase, no conflict.
    if git -C "$DATASET_DIR" push --quiet origin main 2>/dev/null; then
      return 0
    fi
    log_warn "[$model_slug] push rejected (attempt $attempt) for $task_name, retrying..."
  done
}

# ─── Run all tasks for one model ──────────────────────────────────────────────

run_model() {
  local model_slug="$1" model_id="$2" auth_kind="$3"

  local -a model_args=()
  while IFS= read -r line; do model_args+=("$line"); done < <(build_model_args "$model_id" "$auth_kind")

  log_section "Model: $model_slug ($model_id)"

  local total=0 ok=0 fail=0
  for task_dir in "$DATASET_SRC"/*/; do
    [[ -f "${task_dir}task.toml" ]] || continue
    task_dir="${task_dir%/}"
    local task_name
    task_name=$(basename "$task_dir")
    total=$((total + 1))

    local date_stamp
    date_stamp=$(date '+%Y-%m-%d__%H-%M-%S')
    local task_traj="$TRAJ_BASE/$model_slug/$task_name/$date_stamp"
    mkdir -p "$task_traj"

    local harbor_cmd=(
      uv run --extra "$UV_EXTRA"
      harbor run
      -p "$task_dir"
      -a "$AGENT"
      -m "$model_id"
      -e "$HARBOR_ENV"
      -o "$task_traj"
      "${model_args[@]}"
    )

    if $DRY_RUN; then
      log_info "[DRY] $model_slug / $task_name"
      printf '        %s\n' "${harbor_cmd[*]}"
      log_info "        push -> $SAMPLE_DIR/trajectory/$task_name/$model_slug/$date_stamp"
      ok=$((ok + 1))
      continue
    fi

    log_info "[$model_slug] Harbor run: $task_name"
    local rc=0
    if command -v timeout &>/dev/null; then
      timeout "$HARBOR_TIMEOUT_SEC" "${harbor_cmd[@]}" || rc=$?
    else
      "${harbor_cmd[@]}" || rc=$?
    fi

    if [[ $rc -eq 124 ]]; then
      log_error "[$model_slug] TIMEOUT after ${HARBOR_TIMEOUT_SEC}s: $task_name"
      fail=$((fail + 1)); continue
    elif [[ $rc -ne 0 ]]; then
      log_error "[$model_slug] Harbor failed (exit $rc): $task_name"
      fail=$((fail + 1)); continue
    fi

    if ! harbor_trial_succeeded "$task_traj"; then
      log_warn "[$model_slug] Trial errored (harbor exit 0 but result.json shows errors): $task_name"
    fi

    if push_result "$task_dir" "$task_traj" "$model_slug"; then
      log_ok "[$model_slug] Pushed: $task_name"
      ok=$((ok + 1))
    else
      log_warn "[$model_slug] Push failed (non-fatal): $task_name"
      fail=$((fail + 1))
    fi
  done

  log_info "[$model_slug] Done: $ok/$total succeeded ($fail failed)"
}

# ─── Main ──────────────────────────────────────────────────────────────────────

model_selected() {
  local slug="$1"
  [[ ${#MODEL_FILTER[@]} -eq 0 ]] && return 0
  for m in "${MODEL_FILTER[@]}"; do [[ "$m" == "$slug" ]] && return 0; done
  return 1
}

main() {
  log_section "Raiden Trajectory Runner (existing datasets)"
  log_info "Source:   $DATASET_SRC"
  log_info "Repo:     $DATASET_REPO"
  log_info "Sample:   $SAMPLE_DIR"
  log_info "Agent:    $AGENT"
  log_info "Models:   ${MODELS[*]}"
  $DRY_RUN && log_warn "DRY RUN — no harbor execution, no pushes"

  mkdir -p "$TRAJ_BASE" "$LOG_DIR"

  if ! $DRY_RUN; then
    prepare_dataset_repo
  fi

  for spec in "${MODELS[@]}"; do
    IFS='|' read -r slug model_id auth_kind <<< "$spec"
    if ! model_selected "$slug"; then
      log_info "Skipping $slug (not in --model filter)"
      continue
    fi
    run_model "$slug" "$model_id" "$auth_kind"
  done

  log_section "ALL MODELS COMPLETE"
}

main
