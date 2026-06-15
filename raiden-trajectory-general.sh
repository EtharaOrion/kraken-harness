#!/usr/bin/env bash
# raiden-trajectory-general.sh
#
# General-purpose trajectory runner for ANY model across the three providers
# (OpenAI / Gemini / Claude). One model per invocation, passed as a flag. The
# provider and its auth are auto-detected from the model name, so the caller
# only supplies --model and (optionally) --sample-dir.
#
# Two modes (--mode):
#   trajectory  Consume PRE-EXISTING Harbor task dirs (--dataset-src) and run
#               the agent over each, then push. (default)
#   scratch     GENERATE the task dataset first (repo2rlenv generate) from a
#               repo, then run the agent over the freshly generated tasks and
#               push. Mirrors the generate→run→push flow of raiden-runner.sh.
#
# Layout written to the dataset repo (same as raiden-trajectory-runner.sh):
#   <sample>/dataset/<uuid>/                              shared task inputs
#   <sample>/trajectory/<uuid>/<model-slug>/<date>/...    per-model trajectory
#
# Provider auto-detection (from the model name, bare or already-prefixed):
#   gpt-* / o1* / o3* / openai/*           -> OpenAI       (LLM_API_KEY=$OPENAI_API_KEY)
#   gemini* / vertex_ai/gemini*            -> Vertex (SA)  (LLM_API_KEY=$VERTEXAI_API_KEY + SA mount)
#   claude* / opus* / sonnet* / haiku* /   -> Vertex (SA)  (LLM_API_KEY=$VERTEXAI_API_KEY + SA mount)
#     vertex_ai/claude*
# A bare name is normalised to a litellm id (openai/<name> or vertex_ai/<name>).
# The model slug (folder name) is auto-derived by stripping the provider prefix.

set -uo pipefail

# ─── Config ───────────────────────────────────────────────────────────────────

MODE="trajectory"                       # trajectory | scratch

# Common
DATASET_REPO="https://github.com/Ethara-Ai/raiden-dataset.git"
DATASET_DIR="./.raiden-dataset"
SAMPLE_DIR="sample_1"
AGENT="openhands-sdk"
HARBOR_ENV="docker"
TRAJ_BASE="/tmp/raiden-traj-general"
LOG_DIR="./logs/raiden-trajectory-general"
UV_EXTRA="bedrock"
ENV_FILE=".env"

MODEL=""                                # required: any gpt/gemini/claude model
MODEL_SLUG=""                           # optional override; else auto-derived

# Service-account JSON is bind-mounted to this in-container path for Vertex runs.
SA_CONTAINER_PATH="/tmp/raiden-sa.json"

# openhands-sdk agent config (matched to the sample_1 reference trajectory).
MAX_ITERATIONS=1000
REASONING_EFFORT="high"
AGENT_SETUP_TIMEOUT_MULTIPLIER="5.0"
HARBOR_TIMEOUT_SEC=28800

# ─── trajectory-mode config ────────────────────────────────────────────────────
DATASET_SRC="/Users/apple/Sources/harness/opus_datasets/dataset"

# ─── scratch-mode config (repo2rlenv generate) ─────────────────────────────────
# Mirrors raiden-runner.sh defaults; the generated tasks are then run + pushed.
GEN_REPO="aws/aws-cli"
GEN_REF="bb8fa8c1fec3523fa4cd8538071215f90c8ff97f"
GEN_PIPELINE="code_instruct"
GEN_OUT="./datasets/raiden-general"
GEN_LIMIT=8
GEN_SUBSETS=()                          # e.g. (mb cp,ls mb,cp,ls); required in scratch mode
GEN_MAX_LLM_TOKENS=16000
GEN_MAX_LLM_SPEND_USD=50
GEN_CLI_APP_WORKFLOW_TESTS=3
GEN_CLI_APP_REFERENCE_GROUNDING=true
GEN_CLI_APP_MIN_GROUNDED_TESTS=3
GEN_CLI_APP_MAX_INTENTS=3
GEN_CLI_APP_DOCKER_GAUNTLET=true
GEN_CLI_APP_DOCKER_TIMEOUT_SEC=300
readonly VALID_S3_COMMANDS="mb cp ls mv rm rb sync"

DRY_RUN=false
NO_PUSH=false
DATASET_DIR_EXPLICIT=false

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
Usage: raiden-trajectory-general.sh --model MODEL [FLAGS]

Runs harbor trajectories for ANY single model (provider + auth auto-detected
from the model name) and pushes results into a sample partition of the dataset
repo. Supports running over pre-existing task dirs (trajectory mode) or
generating the dataset first (scratch mode).

Required:
  --model MODEL          Any model name. Provider is auto-detected:
                           gpt-* / o1* / o3* / openai/*  -> OpenAI
                           gemini* / vertex_ai/gemini*   -> Vertex (Gemini, SA)
                           claude*/opus*/sonnet*/haiku*  -> Vertex (Claude, SA)
                         Bare names are normalised (gpt-5.5 -> openai/gpt-5.5,
                         claude-opus-4-8 -> vertex_ai/claude-opus-4-8).

Common flags:
  --mode MODE            trajectory (run existing) | scratch (generate first)
                         (default: trajectory)
  --sample-dir DIR       Sample partition in repo      (default: sample_1)
  --slug SLUG            Override the model folder slug (default: auto from name)
  --dataset-repo URL     Push target repo              (default: Ethara-Ai/raiden-dataset)
  --dataset-dir DIR      Local dataset clone           (default: ./.raiden-dataset-<slug>)
  --agent AGENT          Harbor agent                  (default: openhands-sdk)
  --harbor-env ENV       Harbor environment            (default: docker)
  --max-iterations N     Agent max iterations          (default: 1000)
  --reasoning-effort L   LLM reasoning effort          (default: none)
  --uv-extra EXTRA       UV extra for harbor           (default: bedrock)
  --env-file FILE        Source env vars from          (default: .env)
  --no-push              Run harbor + write trajectory locally, skip git push
  --dry-run              Preview commands, no execution
  -h, --help             Show this help

trajectory-mode flags:
  --dataset-src DIR      Source of existing task dirs
                         (default: opus_datasets/dataset)

scratch-mode flags (repo2rlenv generate):
  --gen-repo REPO        Target repo to generate from  (default: aws/aws-cli)
  --gen-ref REF          Git ref                       (default: bb8fa8c...)
  --gen-pipeline NAME    Pipeline                      (default: code_instruct)
  --gen-out DIR          Generation output dir         (default: ./datasets/raiden-general)
  --gen-limit N          Tasks per subset              (default: 8)
  --gen-subset SUBSET    S3 command combo (repeatable; REQUIRED in scratch mode)
                         e.g. --gen-subset mb --gen-subset cp,ls
  --gen-max-llm-tokens N Generation max LLM tokens     (default: 16000)
  --gen-max-llm-spend N  Generation max LLM spend USD  (default: 50)

Examples:
  # Run an existing dataset with Claude opus-4.8 into sample_4:
  ./raiden-trajectory-general.sh --model claude-opus-4-8 --sample-dir sample_4

  # Run an existing dataset with GPT into sample_5:
  ./raiden-trajectory-general.sh --model gpt-5.5 --sample-dir sample_5

  # Run an existing dataset with Gemini into sample_6:
  ./raiden-trajectory-general.sh --model gemini-3.1-pro-preview --sample-dir sample_6

  # Generate from scratch (aws-cli s3 subsets) then run with Claude:
  ./raiden-trajectory-general.sh --mode scratch --model claude-opus-4-8 \
      --sample-dir sample_7 --gen-subset mb --gen-subset cp,ls

Running multiple models in PARALLEL (one process each):
  ./raiden-trajectory-general.sh --model claude-opus-4-8 --sample-dir s &
  ./raiden-trajectory-general.sh --model gpt-5.5         --sample-dir s &
  wait
  Each invocation auto-derives its own clone dir (./.raiden-dataset-<slug>) when
  --dataset-dir is not pinned, so concurrent pushes to the shared repo are safe.
EOF
  exit 0
}

# ─── Parse args ────────────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)             MODE="$2";           shift 2 ;;
    --model)            MODEL="$2";          shift 2 ;;
    --slug)             MODEL_SLUG="$2";     shift 2 ;;
    --sample-dir)       SAMPLE_DIR="$2";     shift 2 ;;
    --dataset-repo)     DATASET_REPO="$2";   shift 2 ;;
    --dataset-dir)      DATASET_DIR="$2"; DATASET_DIR_EXPLICIT=true; shift 2 ;;
    --agent)            AGENT="$2";          shift 2 ;;
    --harbor-env)       HARBOR_ENV="$2";     shift 2 ;;
    --max-iterations)   MAX_ITERATIONS="$2"; shift 2 ;;
    --reasoning-effort) REASONING_EFFORT="$2"; shift 2 ;;
    --uv-extra)         UV_EXTRA="$2";       shift 2 ;;
    --env-file)         ENV_FILE="$2";       shift 2 ;;
    --dataset-src)      DATASET_SRC="$2";    shift 2 ;;
    --gen-repo)         GEN_REPO="$2";       shift 2 ;;
    --gen-ref)          GEN_REF="$2";        shift 2 ;;
    --gen-pipeline)     GEN_PIPELINE="$2";   shift 2 ;;
    --gen-out)          GEN_OUT="$2";        shift 2 ;;
    --gen-limit)        GEN_LIMIT="$2";      shift 2 ;;
    --gen-subset)       GEN_SUBSETS+=("$2"); shift 2 ;;
    --gen-max-llm-tokens) GEN_MAX_LLM_TOKENS="$2"; shift 2 ;;
    --gen-max-llm-spend)  GEN_MAX_LLM_SPEND_USD="$2"; shift 2 ;;
    --no-push)          NO_PUSH=true;        shift ;;
    --dry-run)          DRY_RUN=true;        shift ;;
    -h|--help)          usage ;;
    -*)                 die "Unknown flag: $1" ;;
    *)                  die "Unexpected argument: $1" ;;
  esac
done

[[ -n "$MODEL" ]] || die "No model specified. Pass --model (see --help)."
case "$MODE" in
  trajectory|scratch) ;;
  *) die "Invalid --mode '$MODE'. Use 'trajectory' or 'scratch'." ;;
esac

# ─── Provider auto-detection ────────────────────────────────────────────────────
# Resolves the bare/prefixed --model into:
#   MODEL_ID    full litellm id (openai/<name> or vertex_ai/<name>)
#   AUTH_KIND   openai | vertex   (vertex covers both Gemini and Claude on Vertex)
#   MODEL_SLUG  folder slug (provider prefix stripped), unless overridden
# Detection is case-insensitive and matches on the bare name (prefix stripped).

MODEL_ID=""
AUTH_KIND=""

detect_provider() {
  local raw="$1"
  # Strip any existing provider prefix to get the bare model name.
  local bare="${raw#*/}"
  local lower
  lower=$(printf '%s' "$bare" | tr '[:upper:]' '[:lower:]')

  case "$lower" in
    gpt-*|gpt[0-9]*|o1|o1-*|o3|o3-*|o4|o4-*|chatgpt*|text-*|davinci*)
      MODEL_ID="openai/$bare"
      AUTH_KIND="openai"
      ;;
    gemini*|gemini-*)
      # Per user decision: Gemini routes through Vertex (SA OAuth), not GoogleAI.
      MODEL_ID="vertex_ai/$bare"
      AUTH_KIND="vertex"
      ;;
    claude*|opus*|sonnet*|haiku*)
      MODEL_ID="vertex_ai/$bare"
      AUTH_KIND="vertex"
      ;;
    *)
      # Fall back to the already-prefixed form if the caller passed one.
      case "$raw" in
        openai/*)     MODEL_ID="$raw"; AUTH_KIND="openai" ;;
        vertex_ai/*)  MODEL_ID="$raw"; AUTH_KIND="vertex" ;;
        *) die "Cannot auto-detect provider for model '$raw'. Pass a full litellm id (openai/... or vertex_ai/...) or a recognised name (gpt-*, gemini*, claude*/opus*/sonnet*/haiku*)." ;;
      esac
      ;;
  esac

  # Derive the folder slug from the bare name unless explicitly overridden.
  if [[ -z "$MODEL_SLUG" ]]; then
    MODEL_SLUG=$(printf '%s' "$bare" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g')
  fi
}

detect_provider "$MODEL"

# Parallel-safety: derive a per-model clone dir when --dataset-dir is not pinned,
# so two concurrent invocations (different models) never share a working tree.
if ! $DATASET_DIR_EXPLICIT; then
  DATASET_DIR="${DATASET_DIR}-${MODEL_SLUG}"
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

# ─── Build the model's harbor flag array ────────────────────────────────────────
# Echoes the extra harbor args on stdout, one per line, so the caller reads them
# into an array. Validates required credentials up front for the detected auth.

build_model_args() {
  local -a args=(
    --ak "max_iterations=$MAX_ITERATIONS"
    --agent-setup-timeout-multiplier "$AGENT_SETUP_TIMEOUT_MULTIPLIER"
    --ae "LLM_REASONING_EFFORT=$REASONING_EFFORT"
    --ae "LITELLM_DROP_PARAMS=1"
  )

  case "$AUTH_KIND" in
    vertex)
      # Both Gemini and Claude on Vertex authenticate via the service-account
      # OAuth path: litellm reads the mounted SA file + project/location. The
      # LLM_API_KEY=$VERTEXAI_API_KEY is forwarded for parity with the proven
      # runner; on the Vertex partner-model path litellm uses the SA mount.
      [[ -n "${VERTEXAI_PROJECT:-}" ]] || die "$MODEL_ID needs VERTEXAI_PROJECT"
      [[ -n "${VERTEXAI_LOCATION:-}" ]] || die "$MODEL_ID needs VERTEXAI_LOCATION"
      local sa_host="${GOOGLE_APPLICATION_CREDENTIALS:-}"
      [[ -n "$sa_host" && -f "$sa_host" ]] || die "$MODEL_ID needs a valid GOOGLE_APPLICATION_CREDENTIALS file"
      local api_key="${VERTEXAI_API_KEY:-unused}"
      local mounts
      mounts=$(printf '[{"type":"bind","source":"%s","target":"%s","read_only":true}]' \
        "$sa_host" "$SA_CONTAINER_PATH")
      args+=(
        --mounts-json "$mounts"
        --ae "LLM_API_KEY=$api_key"
        --ae "GOOGLE_APPLICATION_CREDENTIALS=$SA_CONTAINER_PATH"
        --ae "VERTEXAI_PROJECT=$VERTEXAI_PROJECT"
        --ae "VERTEXAI_LOCATION=$VERTEXAI_LOCATION"
      )
      ;;
    openai)
      [[ -n "${OPENAI_API_KEY:-}" ]] || die "$MODEL_ID needs OPENAI_API_KEY"
      args+=(--ae "LLM_API_KEY=$OPENAI_API_KEY")
      ;;
    *)
      die "Unknown auth_kind: $AUTH_KIND"
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
    [[ $attempt -gt 1 ]] && sleep $(( (attempt - 1) * 2 + (RANDOM % 3) ))

    if ! git -C "$DATASET_DIR" fetch --quiet origin main 2>/dev/null; then
      log_warn "[$model_slug] fetch failed (attempt $attempt) for $task_name"
      continue
    fi
    git -C "$DATASET_DIR" reset --quiet --hard origin/main 2>/dev/null || true

    mkdir -p "$data_dest"
    cp -a "$task_dir/." "$data_dest/"
    mkdir -p "$traj_dest"
    cp -a "$traj_dir/." "$traj_dest/"

    git -C "$DATASET_DIR" add \
      "$SAMPLE_DIR/dataset/$task_name" \
      "$SAMPLE_DIR/trajectory/$task_name/$model_slug" 2>/dev/null || true

    if git -C "$DATASET_DIR" diff --cached --quiet 2>/dev/null; then
      return 0
    fi

    git -C "$DATASET_DIR" commit -q -m "add: $task_name trajectory ($model_slug)"

    if git -C "$DATASET_DIR" push --quiet origin main 2>/dev/null; then
      return 0
    fi
    log_warn "[$model_slug] push rejected (attempt $attempt) for $task_name, retrying..."
  done
}

# ─── Run the agent over one task dir + push ─────────────────────────────────────

run_one_task() {
  local task_dir="$1"; shift
  local -a model_args=("$@")
  task_dir="${task_dir%/}"
  local task_name
  task_name=$(basename "$task_dir")

  local date_stamp
  date_stamp=$(date '+%Y-%m-%d__%H-%M-%S')
  local task_traj="$TRAJ_BASE/$MODEL_SLUG/$task_name/$date_stamp"
  mkdir -p "$task_traj"

  local harbor_cmd=(
    uv run --extra "$UV_EXTRA"
    harbor run
    -p "$task_dir"
    -a "$AGENT"
    -m "$MODEL_ID"
    -e "$HARBOR_ENV"
    -o "$task_traj"
    "${model_args[@]}"
  )

  if $DRY_RUN; then
    log_info "[DRY] $MODEL_SLUG / $task_name"
    printf '        %s\n' "${harbor_cmd[*]}"
    log_info "        push -> $SAMPLE_DIR/trajectory/$task_name/$MODEL_SLUG/$date_stamp"
    return 0
  fi

  log_info "[$MODEL_SLUG] Harbor run: $task_name"
  local rc=0
  if command -v timeout &>/dev/null; then
    timeout "$HARBOR_TIMEOUT_SEC" "${harbor_cmd[@]}" || rc=$?
  else
    "${harbor_cmd[@]}" || rc=$?
  fi

  if [[ $rc -eq 124 ]]; then
    log_error "[$MODEL_SLUG] TIMEOUT after ${HARBOR_TIMEOUT_SEC}s: $task_name"
    return 1
  elif [[ $rc -ne 0 ]]; then
    log_error "[$MODEL_SLUG] Harbor failed (exit $rc): $task_name"
    return 1
  fi

  if ! harbor_trial_succeeded "$task_traj"; then
    log_warn "[$MODEL_SLUG] Trial errored (harbor exit 0 but result.json shows errors): $task_name"
  fi

  if $NO_PUSH; then
    log_ok "[$MODEL_SLUG] Done (no-push): $task_name -> $task_traj"
    return 0
  fi

  if push_result "$task_dir" "$task_traj" "$MODEL_SLUG"; then
    log_ok "[$MODEL_SLUG] Pushed: $task_name"
    return 0
  fi
  log_warn "[$MODEL_SLUG] Push failed (non-fatal): $task_name"
  return 1
}

# ─── scratch mode: generate the dataset, then run over it ──────────────────────
# Generates per subset via repo2rlenv (same invocation shape as raiden-runner.sh),
# collecting every emitted task dir into GEN_OUT, then runs the agent over each.

validate_subsets() {
  for subset in "${GEN_SUBSETS[@]}"; do
    IFS=',' read -ra cmds <<< "$subset"
    for cmd in "${cmds[@]}"; do
      echo "$VALID_S3_COMMANDS" | grep -qw "$cmd" \
        || die "Invalid S3 command '$cmd' in subset '$subset'. Valid: $VALID_S3_COMMANDS"
    done
  done
}

generate_dataset() {
  validate_subsets
  for subset in "${GEN_SUBSETS[@]}"; do
    local subset_slug="${subset//,/_}"
    local subset_out="$GEN_OUT/$subset_slug"
    mkdir -p "$subset_out"

    local gen_cmd=(
      uv run repo2rlenv generate
      --repo "$GEN_REPO"
      --ref "$GEN_REF"
      --pipeline "$GEN_PIPELINE"
      --pipeline-opt "mode=cli_app"
      --pipeline-opt "cli_app_command_prefix=s3"
      --pipeline-opt "cli_app_subsets=[\"$subset\"]"
      --pipeline-opt "limit=$GEN_LIMIT"
      --pipeline-opt "cli_app_workflow_tests=$GEN_CLI_APP_WORKFLOW_TESTS"
      --pipeline-opt "cli_app_reference_grounding=$GEN_CLI_APP_REFERENCE_GROUNDING"
      --pipeline-opt "cli_app_min_grounded_tests=$GEN_CLI_APP_MIN_GROUNDED_TESTS"
      --pipeline-opt "cli_app_max_intents=$GEN_CLI_APP_MAX_INTENTS"
      --pipeline-opt "max_llm_tokens=$GEN_MAX_LLM_TOKENS"
      --pipeline-opt "max_llm_spend_usd=$GEN_MAX_LLM_SPEND_USD"
      --pipeline-opt "cli_app_docker_gauntlet=$GEN_CLI_APP_DOCKER_GAUNTLET"
      --pipeline-opt "cli_app_docker_timeout_sec=$GEN_CLI_APP_DOCKER_TIMEOUT_SEC"
      --llm "$MODEL_ID"
      --out "$subset_out"
    )

    if $DRY_RUN; then
      log_info "[DRY] generate subset '$subset'"
      printf '        %s\n' "${gen_cmd[*]}"
      continue
    fi

    log_info "[$MODEL_SLUG] Generating subset: $subset"
    if ! "${gen_cmd[@]}"; then
      log_error "[$MODEL_SLUG] Generate failed for subset '$subset'"
      continue
    fi
    log_ok "[$MODEL_SLUG] Generated subset: $subset"
  done
}

# ─── Main ──────────────────────────────────────────────────────────────────────

main() {
  log_section "Raiden Trajectory Runner (general)"
  log_info "Mode:     $MODE"
  log_info "Model:    $MODEL  ->  $MODEL_ID  (auth: $AUTH_KIND, slug: $MODEL_SLUG)"
  log_info "Repo:     $DATASET_REPO"
  log_info "Sample:   $SAMPLE_DIR"
  log_info "Clone:    $DATASET_DIR"
  log_info "Agent:    $AGENT"
  if [[ "$MODE" == "trajectory" ]]; then
    log_info "Source:   $DATASET_SRC"
  else
    log_info "Generate: $GEN_REPO@${GEN_REF:0:8} pipeline=$GEN_PIPELINE subsets=${GEN_SUBSETS[*]:-<none>}"
  fi
  $DRY_RUN && log_warn "DRY RUN — no harbor execution, no pushes"
  $NO_PUSH && log_warn "NO-PUSH — harbor runs, trajectory stays local under $TRAJ_BASE"

  mkdir -p "$TRAJ_BASE" "$LOG_DIR"

  # Build the model's harbor args once (validates creds up front).
  local -a model_args=()
  while IFS= read -r line; do model_args+=("$line"); done < <(build_model_args)

  if ! $DRY_RUN && ! $NO_PUSH; then
    prepare_dataset_repo
  fi

  local total=0 ok=0 fail=0
  local task_root

  if [[ "$MODE" == "scratch" ]]; then
    [[ ${#GEN_SUBSETS[@]} -gt 0 ]] || die "scratch mode requires at least one --gen-subset (e.g. --gen-subset mb)."
    log_section "Generating dataset"
    generate_dataset
    task_root="$GEN_OUT"
  else
    [[ -d "$DATASET_SRC" ]] || die "Dataset source not found: $DATASET_SRC"
    task_root="$DATASET_SRC"
  fi

  log_section "Running trajectories"
  # Walk every task.toml-bearing dir under task_root (one level for trajectory
  # mode; two levels deep for scratch mode where tasks nest under subset dirs).
  local task_dir
  while IFS= read -r task_dir; do
    task_dir=$(dirname "$task_dir")
    total=$((total + 1))
    if run_one_task "$task_dir" "${model_args[@]}"; then
      ok=$((ok + 1))
    else
      fail=$((fail + 1))
    fi
  done < <(find -L "$task_root" -name task.toml -type f 2>/dev/null | sort)

  log_section "COMPLETE"
  log_info "[$MODEL_SLUG] Done: $ok/$total succeeded ($fail failed)"
  [[ $total -eq 0 ]] && log_warn "No tasks found under $task_root"
}

main
