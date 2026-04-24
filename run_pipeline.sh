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
#   --skip-scrape           Skip stages 1-6, use existing enriched JSONL
#   --skip-workload         Skip workload generation
#   --dataset PATH          Use existing dataset JSONL (skips scrape+filter+version)
#   --mode MODE             Inference mode: default|openhands (default: default)
#   --dry-run               Show what would be done without executing
#   --timeout N             Eval timeout in seconds (default: 1800)
#   --start-from STAGE      Start from this stage, skip all prior stages
#   --stop-after STAGE      Stop after this stage, skip all later stages
#   --stages LIST           Comma-separated list of stages to run (e.g., eval,report)
#   --help                  Show this help
#
# Stages (in execution order):
#   scrape, perf_filter, versioning, detect_specs, workload,
#   eval, pred_eval, report, inference
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
DATASET=""
MODE="default"
DRY_RUN=false
TIMEOUT=1800
START_FROM=""
STOP_AFTER=""
STAGES=""

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
        --dataset)      DATASET="$2"; shift 2 ;;
        --mode)         MODE="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --timeout)      TIMEOUT="$2"; shift 2 ;;
        --start-from)   START_FROM="$2"; shift 2 ;;
        --stop-after)   STOP_AFTER="$2"; shift 2 ;;
        --stages)       STAGES="$2"; shift 2 ;;
        --help)
            sed -n '/^# Usage:/,/^###/p' "$0" | head -n -1
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── Derived values ───────────────────────────────────────────────────────────
REPO_SLUG="${REPO##*/}"
REPO_OWNER="${REPO%%/*}"
[[ -z "$RUN_ID" ]] && RUN_ID="${REPO_SLUG}_$(date +%Y%m%d_%H%M%S)"

ARTIFACTS_DIR="$SCRIPT_DIR/artifacts"
PRS_DIR="$ARTIFACTS_DIR/pull_requests"
TASKS_DIR="$ARTIFACTS_DIR/tasks"
FILTERED_DIR="$ARTIFACTS_DIR/perf_filtered"
VERSIONED_DIR="$ARTIFACTS_DIR/versioned"
ENRICHED_DIR="$ARTIFACTS_DIR/enriched"
FINAL_DIR="$ARTIFACTS_DIR/final"
WORKLOAD_DIR="$SCRIPT_DIR/logs/workload_generation/$RUN_ID"
EVAL_DIR="$SCRIPT_DIR/logs/run_evaluation/$RUN_ID"
REPORT_DIR="$SCRIPT_DIR/eval_reports"

TASKS_FILE=""
FILTERED_FILE=""
VERSIONED_FILE=""
ENRICHED_FILE=""
FINAL_DATASET=""

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
        echo "WARNING: GITHUB_TOKENS or GITHUB_TOKEN not set. Scraping will fail."
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

ensure_dir() { mkdir -p "$@"; }

find_jsonl() {
    local dir="$1" pattern="$2"
    find "$dir" -name "$pattern" -type f 2>/dev/null | head -1
}

ORDERED_STAGES=(scrape perf_filter versioning detect_specs workload eval pred_eval report inference)

validate_stage_name() {
    local name="$1"
    for s in "${ORDERED_STAGES[@]}"; do
        [[ "$s" == "$name" ]] && return 0
    done
    echo "ERROR: Unknown stage '$name'. Valid stages: ${ORDERED_STAGES[*]}"
    exit 1
}

should_run_stage() {
    local stage="$1" _s

    if [[ -n "$STAGES" ]]; then
        IFS=',' read -ra _sel <<< "$STAGES"
        for _s in "${_sel[@]}"; do
            [[ "$_s" == "$stage" ]] && return 0
        done
        return 1
    fi

    if [[ -n "$START_FROM" || -n "$STOP_AFTER" ]]; then
        local in_range=false started=true
        [[ -n "$START_FROM" ]] && started=false
        for _s in "${ORDERED_STAGES[@]}"; do
            [[ -n "$START_FROM" && "$_s" == "$START_FROM" ]] && started=true
            if $started; then
                [[ "$_s" == "$stage" ]] && in_range=true
            fi
            [[ -n "$STOP_AFTER" && "$_s" == "$STOP_AFTER" ]] && { $started && break; }
        done
        $in_range && return 0 || return 1
    fi

    return 0
}

[[ -n "$START_FROM" ]] && validate_stage_name "$START_FROM"
[[ -n "$STOP_AFTER" ]] && validate_stage_name "$STOP_AFTER"
if [[ -n "$STAGES" ]]; then
    IFS=',' read -ra _validate <<< "$STAGES"
    for _s in "${_validate[@]}"; do validate_stage_name "$_s"; done
    unset _validate _s
fi

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
    echo "  → Found $(count_lines "$TASKS_FILE") task instances"
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
        echo "WARNING: No filtered instances found. Using unfiltered tasks..."
        FILTERED_FILE="$TASKS_FILE"
    fi
    local n
    n=$(count_lines "$FILTERED_FILE")
    echo "  → $n instances after perf filter"

    if [[ "$n" -eq 0 ]]; then
        echo "ERROR: 0 instances after perf filter. Try a different repo."
        exit 1
    fi
}

###############################################################################
# STAGE 5: Versioning
###############################################################################
stage_versioning() {
    log "STAGE 5: Versioning"
    ensure_dir "$VERSIONED_DIR"

    step "Detecting versions..."
    run_cmd python -m swefficiency.versioning.get_versions \
        --instances_path "$FILTERED_FILE" \
        --retrieval_method github \
        --num_workers 4 \
        --output_dir "$VERSIONED_DIR"

    # get_versions outputs a JSON array file, not JSONL — convert it
    local json_file
    json_file=$(find "$VERSIONED_DIR" -name "*.json" -type f 2>/dev/null | head -1)
    VERSIONED_FILE="$VERSIONED_DIR/${REPO_SLUG}-versioned.jsonl"

    if [[ -n "$json_file" && -f "$json_file" ]]; then
        python3 -c "
import json
with open('$json_file') as f:
    data = json.load(f)
if isinstance(data, list):
    with open('$VERSIONED_FILE', 'w') as out:
        for item in data:
            if item.get('version'):
                out.write(json.dumps(item) + '\n')
    print(f'  → Converted {len([d for d in data if d.get(\"version\")])} versioned instances')
else:
    print('  WARNING: Unexpected JSON format')
"
    fi

    if [[ ! -f "$VERSIONED_FILE" ]] || [[ $(count_lines "$VERSIONED_FILE") -eq 0 ]]; then
        echo "WARNING: No versioned instances. Using filtered file."
        VERSIONED_FILE="$FILTERED_FILE"
    else
        echo "  → $(count_lines "$VERSIONED_FILE") versioned instances"
    fi
}

###############################################################################
# STAGE 6: Auto-detect Repo Specs
###############################################################################
stage_detect_specs() {
    log "STAGE 6: Auto-detecting repo specs"
    ensure_dir "$ENRICHED_DIR"

    ENRICHED_FILE="$ENRICHED_DIR/${REPO_SLUG}_enriched.jsonl"

    step "Detecting Python version, install cmd, test cmd, deps..."
    run_cmd python scripts/detect_repo_specs.py \
        --input "$VERSIONED_FILE" \
        --output "$ENRICHED_FILE" \
        --workers 4 \
        --verbose

    if [[ -f "$ENRICHED_FILE" ]]; then
        echo "  → $(count_lines "$ENRICHED_FILE") enriched instances"
    else
        echo "WARNING: Enrichment failed. Using versioned file."
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

    # Find workload output
    local wl_output
    wl_output=$(find "logs/workload_generation/$RUN_ID" -name "workload_generation.json" -type f 2>/dev/null | head -1)
    if [[ -z "$wl_output" ]]; then
        wl_output=$(find "logs/workload_generation/$RUN_ID" -name "*.json" -type f 2>/dev/null | head -1)
    fi

    ensure_dir "$FINAL_DIR"
    FINAL_DATASET="$FINAL_DIR/${REPO_SLUG}-dataset.jsonl"

    step "Merging workloads into dataset..."
    _ENRICHED="$ENRICHED_FILE" _WL_OUTPUT="${wl_output:-}" _FINAL="$FINAL_DATASET" python3 << 'PYEOF'
import json, sys, os, pathlib

enriched_path = os.environ.get("_ENRICHED", "")
wl_path = os.environ.get("_WL_OUTPUT", "")
out_path = os.environ.get("_FINAL", "")

enriched = {}
with open(enriched_path) as f:
    for line in f:
        if line.strip():
            inst = json.loads(line)
            enriched[inst['instance_id']] = inst

workloads = {}
if wl_path and os.path.exists(wl_path):
    with open(wl_path) as f:
        content = f.read().strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = [json.loads(line) for line in content.splitlines() if line.strip()]
    for item in data:
        iid = item.get('instance_id', '')
        wl = item.get('workload', item.get('generated_workload', ''))
        if not wl:
            wl_file = item.get('workload_file', '')
            if wl_file and os.path.exists(wl_file):
                wl = pathlib.Path(wl_file).read_text()
        if iid and wl:
            workloads[iid] = wl

merged = 0
with open(out_path, 'w') as out:
    for iid, inst in enriched.items():
        if iid in workloads:
            inst['workload'] = workloads[iid]
            merged += 1
        # Ensure required fields exist
        inst.setdefault('PASS_TO_PASS', [])
        inst.setdefault('FAIL_TO_PASS', [])
        inst.setdefault('covering_tests', [])
        inst.setdefault('test_patch', '')
        inst.setdefault('environment_setup_commit', inst.get('base_commit', ''))
        inst.setdefault('speedup', '')
        inst.setdefault('notes', '')
        inst.setdefault('single_thread_tests', [])
        out.write(json.dumps(inst) + '\n')

print(f"  → Merged {merged}/{len(enriched)} workloads → {out_path}")
PYEOF
}

###############################################################################
# STAGE 8: Docker Build + Gold Evaluation (perf-only)
###############################################################################
stage_eval() {
    log "STAGE 8: Docker Build + Gold Evaluation (perf-only)"

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    if [[ -n "$DATASET" ]]; then
        dataset_to_use="$DATASET"
    fi

    echo "  Dataset:  $dataset_to_use ($(count_lines "$dataset_to_use") instances)"
    echo "  Workers:  $MAX_WORKERS"
    echo "  Timeout:  ${TIMEOUT}s"

    step "Running gold evaluation (perf-only, no correctness)..."
    run_cmd python swefficiency/harness/run_validation.py \
        --dataset_name "$dataset_to_use" \
        --run_id "$RUN_ID" \
        --max_workers "$MAX_WORKERS" \
        --max_build_workers "$MAX_WORKERS" \
        --timeout "$TIMEOUT" \
        --use_ecr_images false \
        --run_perf true \
        --run_correctness true \
        --run_coverage false \
        --process_isolation true \
        --force_rerun true

    GOLD_DIR="$EVAL_DIR/gold"
    if [[ ! -d "$GOLD_DIR" ]]; then
        GOLD_DIR=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1 || true)
    fi

    if [[ -n "$GOLD_DIR" && -d "$GOLD_DIR" ]]; then
        local eval_count
        eval_count=$(find "$GOLD_DIR" -name "perf_summary.txt" 2>/dev/null | wc -l | tr -d ' ')
        echo "  → Gold eval done: $eval_count instances with perf data"

        step "Printing perf summaries..."
        find "$GOLD_DIR" -name "perf_summary.txt" -exec sh -c 'echo "  $(basename $(dirname {})):"; cat "{}"; echo ""' \;
    else
        if $DRY_RUN; then
            echo "  [DRY-RUN] Gold eval output would be at $EVAL_DIR"
        else
            echo "ERROR: No gold eval output. Check logs."
            exit 1
        fi
    fi
}

###############################################################################
# STAGE 8.5: Create Gold-as-Predictions + Run Prediction Eval
###############################################################################
stage_pred_eval() {
    log "STAGE 8.5: Prediction Evaluation (gold patches as predictions)"

    if $DRY_RUN; then
        echo "  [DRY-RUN] Would create gold-as-prediction JSONL and run prediction eval"
        return
    fi

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    [[ -n "$DATASET" ]] && dataset_to_use="$DATASET"

    ensure_dir "$FINAL_DIR"
    local pred_file="$FINAL_DIR/${REPO_SLUG}-gold-predictions.jsonl"

    step "Creating gold-as-prediction JSONL..."
    python3 -c "
import json
with open('$dataset_to_use') as f:
    instances = [json.loads(line) for line in f if line.strip()]
with open('$pred_file', 'w') as out:
    for inst in instances:
        out.write(json.dumps({
            'instance_id': inst['instance_id'],
            'model_patch': inst.get('patch', ''),
            'model_name_or_path': 'gold_as_pred'
        }) + '\n')
print(f'  → Created {len(instances)} predictions')
"

    step "Running prediction eval..."
    run_cmd python swefficiency/harness/run_validation.py \
        --dataset_name "$dataset_to_use" \
        --run_id "$RUN_ID" \
        --max_workers "$MAX_WORKERS" \
        --max_build_workers "$MAX_WORKERS" \
        --timeout "$TIMEOUT" \
        --use_ecr_images false \
        --run_perf true \
        --run_correctness true \
        --run_coverage false \
        --process_isolation true \
        --force_rerun true \
        --model_predictions "$pred_file"

    PRED_DIR="$EVAL_DIR/gold_as_pred"
    if [[ -d "$PRED_DIR" ]]; then
        local pred_count
        pred_count=$(find "$PRED_DIR" -name "perf_summary.txt" 2>/dev/null | wc -l | tr -d ' ')
        echo "  → Prediction eval done: $pred_count instances"
    fi
}

###############################################################################
# STAGE 9: Report Generation
###############################################################################
stage_report() {
    log "STAGE 9: Report Generation"

    if $DRY_RUN; then
        echo "  [DRY-RUN] Would generate comparison report"
        return
    fi

    ensure_dir "$REPORT_DIR"

    GOLD_DIR="$EVAL_DIR/gold"
    if [[ ! -d "$GOLD_DIR" ]]; then
        GOLD_DIR=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d -name "gold" 2>/dev/null | head -1)
    fi
    PRED_DIR="$EVAL_DIR/gold_as_pred"

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    [[ -n "$DATASET" ]] && dataset_to_use="$DATASET"

    if [[ -d "$GOLD_DIR" && -d "$PRED_DIR" ]]; then
        step "Generating comparison report..."
        run_cmd python -m swefficiency.cli report \
            --gold_run "$GOLD_DIR" \
            --pred_run "$PRED_DIR" \
            --report_output "$REPORT_DIR" \
            --num_workers 1 \
            --dataset "$dataset_to_use"

        echo ""
        echo "  Reports:"
        ls -la "$REPORT_DIR"/eval_report_gold_as_pred.* 2>/dev/null || echo "  (no report files found)"
        echo ""
        if [[ -f "$REPORT_DIR/eval_report_gold_as_pred.json" ]]; then
            step "Report Summary:"
            cat "$REPORT_DIR/eval_report_gold_as_pred.json"
        fi
    else
        echo "  Skipping report: gold=$GOLD_DIR pred=$PRED_DIR"
    fi
}

###############################################################################
# STAGE 10: Inference (Agent Trajectory) — Optional
###############################################################################
stage_inference() {
    if [[ "$MODE" != "openhands" ]]; then
        step "Skipping inference (mode=$MODE). Use --mode openhands for agent trajectories."
        return
    fi

    log "STAGE 10: Running OpenHands Agent Inference"

    local llm_config="$SCRIPT_DIR/scripts/inference/llm_configs/bedrock.json"
    if [[ ! -f "$llm_config" ]]; then
        echo "ERROR: LLM config not found at $llm_config"
        exit 1
    fi

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
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
        local patch_count
        patch_count=$(find "$inf_dir" -name "patch.diff" 2>/dev/null | wc -l | tr -d ' ')
        echo "  → $patch_count patches generated"
    fi
}

###############################################################################
# FINAL SUMMARY
###############################################################################
print_summary() {
    log "Pipeline Complete!"
    echo ""
    echo "  Run ID:         $RUN_ID"
    echo "  Repo:           $REPO"
    echo "  Platform:       $(uname -s)/$(uname -m)"
    echo ""
    echo "  Artifacts:      $ARTIFACTS_DIR"
    echo "  Eval output:    $EVAL_DIR"
    echo "  Reports:        $REPORT_DIR"
    echo ""

    if [[ -f "$REPORT_DIR/eval_report_gold_as_pred.json" ]]; then
        echo "  ── Evaluation Results ──"
        python3 -c "
import json
with open('$REPORT_DIR/eval_report_gold_as_pred.json') as f:
    r = json.load(f)
print(f'  Total instances:     {r[\"total_instances\"]}')
print(f'  Overall score:       {r[\"overall_score\"]}')
print(f'  Human speedup+:     {r[\"proportion_human_speedup_or_better\"]}')
"
    fi

    echo ""
    echo "  ═══════════════════════════════════════"
    echo "  Done. Check eval_reports/ for results."
    echo "  ═══════════════════════════════════════"
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
    [[ -n "$START_FROM" ]] && echo "  Start from:  $START_FROM"
    [[ -n "$STOP_AFTER" ]] && echo "  Stop after:  $STOP_AFTER"
    [[ -n "$STAGES" ]]     && echo "  Stages:      $STAGES"

    check_prereqs

    # ── Auto-discover intermediate files for resume ──
    if [[ -n "$DATASET" ]]; then
        echo "  Using provided dataset: $DATASET"
        ENRICHED_FILE="$DATASET"
        FINAL_DATASET="$DATASET"
    elif should_run_stage "scrape" && ! $SKIP_SCRAPE; then
        : # Will be set by stage_scrape
    else
        if $SKIP_SCRAPE; then
            echo "  Skipping scrape stages (--skip-scrape)."
        fi
        ENRICHED_FILE=$(find_jsonl "$ENRICHED_DIR" "${REPO_SLUG}*.jsonl")
        FINAL_DATASET=$(find_jsonl "$FINAL_DIR" "${REPO_SLUG}*dataset*.jsonl")
        [[ -z "$ENRICHED_FILE" && -z "$FINAL_DATASET" ]] && { echo "ERROR: Skipping scrape but no dataset found. Use --dataset."; exit 1; }
        [[ -z "$FINAL_DATASET" ]] && FINAL_DATASET="$ENRICHED_FILE"
    fi

    if ! should_run_stage "eval" && (should_run_stage "pred_eval" || should_run_stage "report"); then
        GOLD_DIR="$EVAL_DIR/gold"
        [[ ! -d "$GOLD_DIR" ]] && { echo "ERROR: --start-from pred_eval/report but no gold eval at $GOLD_DIR"; exit 1; }
    fi

    if ! should_run_stage "pred_eval" && should_run_stage "report"; then
        PRED_DIR="$EVAL_DIR/gold_as_pred"
        [[ ! -d "$PRED_DIR" ]] && { echo "ERROR: --start-from report but no pred eval at $PRED_DIR"; exit 1; }
    fi

    # ── Stage-gated execution ──
    should_run_stage "scrape" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_scrape
    should_run_stage "perf_filter" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_perf_filter
    should_run_stage "versioning" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_versioning
    should_run_stage "detect_specs" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_detect_specs

    export _ENRICHED="${ENRICHED_FILE:-}"
    export _FINAL="${FINAL_DATASET:-}"
    export _WL_OUTPUT=""

    if should_run_stage "workload" && ! $SKIP_WORKLOAD && [[ -z "$DATASET" ]]; then
        stage_workload
    else
        FINAL_DATASET="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    fi

    should_run_stage "eval" && stage_eval
    should_run_stage "pred_eval" && stage_pred_eval
    should_run_stage "report" && stage_report
    should_run_stage "inference" && stage_inference
    print_summary
}

main
