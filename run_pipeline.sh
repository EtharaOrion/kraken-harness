#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_pipeline.sh — End-to-end SWE-fficiency pipeline
#
# Runs ALL stages from GitHub PR scraping → perf filter → versioning →
# auto-detect specs → workload generation → Docker build → evaluation → report
#
# Usage:
#   ./run_pipeline.sh [OPTIONS]
#
# Options:
#   --repo OWNER/NAME       Target repo (default: psf/requests)
#   --run-id NAME           Run identifier (default: auto-generated timestamp)
#   --cutoff-date YYYYMMDD  PR cutoff date (default: 20180101)
#   --max-pulls N           Max PRs to scrape (default: unlimited)
#   --max-workers N         Parallel workers for eval (default: 1)
#   --skip-scrape           Skip stages 1-5, use existing enriched JSONL
#   --skip-workload         Skip workload generation
#   --skip-docker-build     Skip Docker build (assume images exist)
#   --dataset PATH          Use existing dataset JSONL (skips scrape+filter+version)
#   --mode MODE             Inference mode: default|openhands (default: default)
#   --dry-run               Show what would be done without executing
#   --help                  Show this help
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Defaults ─────────────────────────────────────────────────────────────────
REPO="psf/requests"
RUN_ID=""
CUTOFF_DATE="20180101"
MAX_PULLS=""
MAX_WORKERS=1
SKIP_SCRAPE=false
SKIP_WORKLOAD=false
SKIP_DOCKER_BUILD=false
DATASET=""
MODE="default"
DRY_RUN=false
TIMEOUT=7200

# ─── Parse args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --repo)         REPO="$2"; shift 2 ;;
        --run-id)       RUN_ID="$2"; shift 2 ;;
        --cutoff-date)  CUTOFF_DATE="$2"; shift 2 ;;
        --max-pulls)    MAX_PULLS="$2"; shift 2 ;;
        --max-workers)  MAX_WORKERS="$2"; shift 2 ;;
        --skip-scrape)  SKIP_SCRAPE=true; shift ;;
        --skip-workload) SKIP_WORKLOAD=true; shift ;;
        --skip-docker-build) SKIP_DOCKER_BUILD=true; shift ;;
        --dataset)      DATASET="$2"; shift 2 ;;
        --mode)         MODE="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --timeout)      TIMEOUT="$2"; shift 2 ;;
        --help)
            sed -n '/^# Usage:/,/^###/p' "$0" | head -n -1
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── Derived values ───────────────────────────────────────────────────────────
REPO_SLUG="${REPO##*/}"  # e.g., "requests" from "psf/requests"
[[ -z "$RUN_ID" ]] && RUN_ID="${REPO_SLUG}_$(date +%Y%m%d_%H%M%S)"

ARTIFACTS_DIR="$SCRIPT_DIR/artifacts"
PRS_DIR="$ARTIFACTS_DIR/pull_requests"
TASKS_DIR="$ARTIFACTS_DIR/tasks"
FILTERED_DIR="$ARTIFACTS_DIR/perf_filtered"
VERSIONED_DIR="$ARTIFACTS_DIR/versioned"
ENRICHED_DIR="$ARTIFACTS_DIR/enriched"
WORKLOAD_DIR="$SCRIPT_DIR/logs/workload_generation/$RUN_ID"
EVAL_DIR="$SCRIPT_DIR/logs/run_evaluation/$RUN_ID"
REPORT_DIR="$SCRIPT_DIR/eval_reports"

# ─── Load .env ────────────────────────────────────────────────────────────────
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# ─── Validate prerequisites ──────────────────────────────────────────────────
check_prereqs() {
    local missing=()
    command -v python >/dev/null 2>&1 || missing+=("python")
    command -v docker >/dev/null 2>&1 || missing+=("docker")
    command -v git >/dev/null 2>&1    || missing+=("git")

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "ERROR: Missing required tools: ${missing[*]}"
        exit 1
    fi

    if ! docker info >/dev/null 2>&1; then
        echo "ERROR: Docker daemon not running. Start Docker Desktop first."
        exit 1
    fi

    if [[ -z "${GITHUB_TOKENS:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
        echo "ERROR: GITHUB_TOKENS or GITHUB_TOKEN not set. Add to .env or export."
        exit 1
    fi

    python -c "import swefficiency" 2>/dev/null || {
        echo "ERROR: swefficiency not installed. Run: pip install -e ."
        exit 1
    }
}

# ─── Helpers ──────────────────────────────────────────────────────────────────
log() { echo -e "\n══════════════════════════════════════════════════════════"; echo "  $1"; echo "══════════════════════════════════════════════════════════"; }
step() { echo -e "\n── $1 ──"; }
run_cmd() {
    if $DRY_RUN; then
        echo "[DRY-RUN] $*"
    else
        "$@"
    fi
}

count_lines() { wc -l < "$1" | tr -d ' '; }

ensure_dir() { mkdir -p "$1"; }

# Find the first matching JSONL file in a dir matching a pattern
find_jsonl() {
    local dir="$1" pattern="$2"
    find "$dir" -name "$pattern" -type f 2>/dev/null | head -1
}

###############################################################################
# STAGE 1-3: Scrape PRs + Build Dataset
###############################################################################
stage_scrape() {
    log "STAGE 1-3: Scraping PRs from $REPO"

    ensure_dir "$PRS_DIR" "$TASKS_DIR"

    local pulls_args=(
        --repos "$REPO"
        --path_prs "$PRS_DIR"
        --path_tasks "$TASKS_DIR"
    )
    [[ -n "$CUTOFF_DATE" ]] && pulls_args+=(--cutoff_date "$CUTOFF_DATE")
    [[ -n "$MAX_PULLS" ]] && pulls_args+=(--max_pulls "$MAX_PULLS")

    step "Scraping PRs and building task instances..."
    run_cmd python -m swefficiency.collect.get_tasks_pipeline "${pulls_args[@]}"

    TASKS_FILE=$(find_jsonl "$TASKS_DIR" "${REPO_SLUG}*task-instances*.jsonl")
    if [[ -z "$TASKS_FILE" ]]; then
        echo "ERROR: No task instances file found in $TASKS_DIR"
        exit 1
    fi
    local n=$(count_lines "$TASKS_FILE")
    echo "  → Found $n task instances in $TASKS_FILE"
}

###############################################################################
# STAGE 4: Performance Filter
###############################################################################
stage_perf_filter() {
    log "STAGE 4: Performance filtering"

    ensure_dir "$FILTERED_DIR"

    PRS_FILE=$(find_jsonl "$PRS_DIR" "${REPO_SLUG}*prs*.jsonl")
    if [[ -z "$PRS_FILE" ]]; then
        echo "ERROR: No PRs file found in $PRS_DIR"
        exit 1
    fi

    step "Filtering for performance-related PRs..."
    run_cmd python -m swefficiency.perf_filter.attributes.filter \
        --prs_path "$PRS_FILE" \
        --instances_path "$TASKS_FILE" \
        --output_dir "$FILTERED_DIR"

    FILTERED_FILE=$(find_jsonl "$FILTERED_DIR" "${REPO_SLUG}*attribute*.jsonl")
    if [[ -z "$FILTERED_FILE" ]]; then
        echo "WARNING: No filtered instances found. Trying to use unfiltered tasks..."
        FILTERED_FILE="$TASKS_FILE"
    fi
    local n=$(count_lines "$FILTERED_FILE")
    echo "  → $n instances after perf filter"

    if [[ "$n" -eq 0 ]]; then
        echo "ERROR: 0 instances after perf filter. Try a different repo or relax --cutoff-date."
        exit 1
    fi
}

###############################################################################
# STAGE 5: Versioning
###############################################################################
stage_versioning() {
    log "STAGE 5: Versioning"

    ensure_dir "$VERSIONED_DIR"

    step "Detecting versions for each instance..."
    run_cmd python -m swefficiency.versioning.get_versions \
        --instances_path "$FILTERED_FILE" \
        --retrieval_method github \
        --num_workers 4 \
        --output_dir "$VERSIONED_DIR"

    VERSIONED_FILE=$(find_jsonl "$VERSIONED_DIR" "*.jsonl")
    if [[ -z "$VERSIONED_FILE" ]]; then
        echo "WARNING: No versioned file found. Using filtered file as-is."
        VERSIONED_FILE="$FILTERED_FILE"
    fi
    local n=$(count_lines "$VERSIONED_FILE")
    echo "  → $n instances after versioning"
}

###############################################################################
# STAGE 6: Auto-detect Repo Specs
###############################################################################
stage_detect_specs() {
    log "STAGE 6: Auto-detecting repo specs"

    ensure_dir "$ENRICHED_DIR"

    ENRICHED_FILE="$ENRICHED_DIR/${REPO_SLUG}_enriched.jsonl"

    step "Running spec detection (Python version, install cmd, test cmd, deps)..."
    run_cmd python scripts/detect_repo_specs.py \
        --input "$VERSIONED_FILE" \
        --output "$ENRICHED_FILE" \
        --workers 4 \
        --verbose

    if [[ -f "$ENRICHED_FILE" ]]; then
        local n=$(count_lines "$ENRICHED_FILE")
        echo "  → $n enriched instances in $ENRICHED_FILE"
    else
        echo "WARNING: Enriched file not created. Using versioned file."
        ENRICHED_FILE="$VERSIONED_FILE"
    fi
}

###############################################################################
# STAGE 7: Workload Generation (LLM-based)
###############################################################################
stage_workload() {
    log "STAGE 7: Generating performance workloads via LLM"

    if [[ -z "${AWS_BEARER_TOKEN_BEDROCK:-}" ]]; then
        echo "ERROR: AWS_BEARER_TOKEN_BEDROCK not set. Required for workload generation."
        exit 1
    fi

    step "Generating workloads with Bedrock..."
    run_cmd python -m swefficiency.workload.run_synthetic_generation \
        --dataset_name "$ENRICHED_FILE" \
        --run_id "$RUN_ID" \
        --max_workers 1

    WORKLOAD_OUTPUT="$WORKLOAD_DIR/workload_generation.json"
    if [[ ! -f "$WORKLOAD_OUTPUT" ]]; then
        WORKLOAD_OUTPUT=$(find "$WORKLOAD_DIR" -name "*.json" -type f 2>/dev/null | head -1)
    fi

    if [[ -z "$WORKLOAD_OUTPUT" || ! -f "$WORKLOAD_OUTPUT" ]]; then
        echo "WARNING: No workload output found. Continuing without workloads."
        FINAL_DATASET="$ENRICHED_FILE"
        return
    fi

    step "Merging workloads into dataset..."
    FINAL_DATASET="$ENRICHED_DIR/${REPO_SLUG}_with_workloads.jsonl"
    python3 -c "
import json, sys

enriched = {}
with open('$ENRICHED_FILE') as f:
    for line in f:
        inst = json.loads(line)
        enriched[inst['instance_id']] = inst

workloads = {}
with open('$WORKLOAD_OUTPUT') as f:
    data = json.load(f) if '$WORKLOAD_OUTPUT'.endswith('.json') else [json.loads(l) for l in f]
    if isinstance(data, dict):
        data = [data]
    for item in data:
        iid = item.get('instance_id', '')
        wl = item.get('workload', item.get('generated_workload', ''))
        if iid and wl:
            workloads[iid] = wl

merged = 0
with open('$FINAL_DATASET', 'w') as out:
    for iid, inst in enriched.items():
        if iid in workloads:
            inst['workload'] = workloads[iid]
            merged += 1
        out.write(json.dumps(inst) + '\n')

print(f'  → Merged {merged} workloads into {len(enriched)} instances')
print(f'  → Output: $FINAL_DATASET')
"
}

###############################################################################
# STAGE 8: Docker Build + Evaluation (Gold baseline)
###############################################################################
stage_eval() {
    log "STAGE 8: Docker Build + Evaluation"

    local dataset_to_use="${FINAL_DATASET:-$ENRICHED_FILE}"
    if [[ -n "$DATASET" ]]; then
        dataset_to_use="$DATASET"
    fi

    local n=$(count_lines "$dataset_to_use")
    echo "  Using dataset: $dataset_to_use ($n instances)"

    if ! $SKIP_DOCKER_BUILD; then
        step "Building Docker images + running gold evaluation..."
        run_cmd python swefficiency/harness/run_validation.py \
            --dataset_name "$dataset_to_use" \
            --run_id "${RUN_ID}" \
            --max_workers "$MAX_WORKERS" \
            --max_build_workers "$MAX_WORKERS" \
            --timeout "$TIMEOUT" \
            --use_dockerhub_images false \
            --run_perf true \
            --run_correctness true \
            --process_isolation true \
            --empty_patch false \
            --cache_level env
    else
        step "Skipping Docker build (--skip-docker-build). Assume images exist."
        step "Running evaluation with pre-built images..."
        run_cmd python swefficiency/harness/run_validation.py \
            --dataset_name "$dataset_to_use" \
            --run_id "${RUN_ID}" \
            --max_workers "$MAX_WORKERS" \
            --timeout "$TIMEOUT" \
            --use_dockerhub_images true \
            --run_perf true \
            --run_correctness true \
            --process_isolation true \
            --empty_patch false
    fi

    GOLD_DIR="$EVAL_DIR/gold"
    if [[ ! -d "$GOLD_DIR" ]]; then
        GOLD_DIR=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)
    fi

    if [[ -n "$GOLD_DIR" && -d "$GOLD_DIR" ]]; then
        local eval_count=$(find "$GOLD_DIR" -name "perf_summary.txt" 2>/dev/null | wc -l | tr -d ' ')
        echo "  → Gold evaluation complete: $eval_count instances with perf data"
    else
        echo "WARNING: No evaluation output directory found at $EVAL_DIR"
    fi
}

###############################################################################
# STAGE 9: Inference (Agent Trajectory) — Optional
###############################################################################
stage_inference() {
    if [[ "$MODE" == "openhands" ]]; then
        log "STAGE 9: Running OpenHands Agent Inference"

        local llm_config="$SCRIPT_DIR/scripts/inference/llm_configs/bedrock.json"
        if [[ ! -f "$llm_config" ]]; then
            echo "ERROR: LLM config not found at $llm_config"
            exit 1
        fi

        local dataset_to_use="${FINAL_DATASET:-$ENRICHED_FILE}"
        [[ -n "$DATASET" ]] && dataset_to_use="$DATASET"

        step "Running inference with OpenHands agent..."
        run_cmd python scripts/inference/custom.py \
            --mode openhands \
            --run-id "${RUN_ID}_inference" \
            --llm-config "$llm_config" \
            --dataset "$dataset_to_use" \
            --num-workers 1 \
            --max-iterations 100 \
            --max-fake-responses 5 \
            --mem-limit 12g \
            --disable-cpu-pinning

        local inf_dir="$SCRIPT_DIR/logs/run_inference/${RUN_ID}_inference"
        if [[ -d "$inf_dir" ]]; then
            local patch_count=$(find "$inf_dir" -name "patch.diff" 2>/dev/null | wc -l | tr -d ' ')
            echo "  → Inference complete: $patch_count patches generated"

            step "Converting patches to predictions JSONL..."
            local pred_file="$inf_dir/predictions.jsonl"
            python3 -c "
import json, os, pathlib

inf_dir = pathlib.Path('$inf_dir')
predictions = []
for patch_file in sorted(inf_dir.rglob('patch.diff')):
    instance_id = patch_file.parent.name
    patch_text = patch_file.read_text()
    if patch_text.strip():
        predictions.append({
            'instance_id': instance_id,
            'model_patch': patch_text,
            'model_name_or_path': 'openhands-bedrock'
        })

with open('$pred_file', 'w') as f:
    for p in predictions:
        f.write(json.dumps(p) + '\n')

print(f'  → {len(predictions)} non-empty predictions written to $pred_file')
"
        fi
    else
        step "Skipping inference (mode=$MODE). Use --mode openhands for agent trajectories."
    fi
}

###############################################################################
# STAGE 10: Report Generation
###############################################################################
stage_report() {
    log "STAGE 10: Report Generation"

    ensure_dir "$REPORT_DIR"

    GOLD_DIR="$EVAL_DIR/gold"
    if [[ ! -d "$GOLD_DIR" ]]; then
        GOLD_DIR=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)
    fi

    if [[ -z "$GOLD_DIR" || ! -d "$GOLD_DIR" ]]; then
        echo "WARNING: No gold eval directory found. Skipping report."
        return
    fi

    if [[ "$MODE" == "openhands" ]]; then
        local pred_dir="$EVAL_DIR/openhands-bedrock"
        local pred_file="$SCRIPT_DIR/logs/run_inference/${RUN_ID}_inference/predictions.jsonl"

        if [[ -f "$pred_file" ]]; then
            step "Evaluating agent predictions..."
            run_cmd python swefficiency/harness/run_validation.py \
                --dataset_name "${FINAL_DATASET:-$ENRICHED_FILE}" \
                --run_id "${RUN_ID}" \
                --model_predictions "$pred_file" \
                --max_workers "$MAX_WORKERS" \
                --timeout "$TIMEOUT" \
                --use_dockerhub_images false \
                --run_perf true \
                --run_correctness true \
                --process_isolation true

            pred_dir=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d -name "openhands*" 2>/dev/null | head -1)
            if [[ -n "$pred_dir" ]]; then
                step "Generating comparison report..."
                run_cmd swefficiency report \
                    --gold_run "$GOLD_DIR" \
                    --pred_run "$pred_dir" \
                    --report_output "$REPORT_DIR"
            fi
        else
            echo "  No predictions file found. Generating gold-only report..."
        fi
    fi

    echo ""
    echo "  ═══════════════════════════════════════"
    echo "  Pipeline complete!"
    echo "  ═══════════════════════════════════════"
    echo ""
    echo "  Run ID:      $RUN_ID"
    echo "  Repo:        $REPO"
    echo "  Artifacts:   $ARTIFACTS_DIR"
    echo "  Eval output: $EVAL_DIR"
    echo "  Reports:     $REPORT_DIR"
    echo ""
}

###############################################################################
# MAIN
###############################################################################
main() {
    log "SWE-fficiency Pipeline — $REPO"
    echo "  Run ID:      $RUN_ID"
    echo "  Mode:        $MODE"
    echo "  Max workers: $MAX_WORKERS"
    echo "  Cutoff date: $CUTOFF_DATE"
    echo "  Platform:    $(uname -s)/$(uname -m)"

    check_prereqs

    if [[ -n "$DATASET" ]]; then
        echo "  Using provided dataset: $DATASET"
        ENRICHED_FILE="$DATASET"
        FINAL_DATASET="$DATASET"
    elif ! $SKIP_SCRAPE; then
        stage_scrape
        stage_perf_filter
        stage_versioning
        stage_detect_specs
    else
        echo "  Skipping scrape stages (--skip-scrape)."
        if [[ -z "${ENRICHED_FILE:-}" ]]; then
            ENRICHED_FILE=$(find_jsonl "$ENRICHED_DIR" "${REPO_SLUG}*.jsonl")
            [[ -z "$ENRICHED_FILE" ]] && ENRICHED_FILE=$(find_jsonl "$VERSIONED_DIR" "*.jsonl")
            [[ -z "$ENRICHED_FILE" ]] && { echo "ERROR: No dataset found. Run without --skip-scrape first."; exit 1; }
        fi
        FINAL_DATASET="$ENRICHED_FILE"
    fi

    if ! $SKIP_WORKLOAD && [[ -z "$DATASET" ]]; then
        stage_workload
    else
        FINAL_DATASET="${ENRICHED_FILE:-$DATASET}"
    fi

    stage_eval
    stage_inference
    stage_report
}

main
