#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_pipeline_eval_cpp.sh — Phase 3 of the split SWE-fficiency C++ pipeline.
#
# Stages: eval, significance_filter, pred_eval, report, inference.
# Entry point is a finished C++ dataset JSONL (output of run_pipeline_dataset_cpp.sh).
# Requires the Docker daemon. Shared helpers come from pipeline_lib_cpp.sh.
#
# Usage:
#   ./run_pipeline_eval_cpp.sh --dataset PATH [OPTIONS]
#
# Options:
#   --dataset PATH          Finished C++ dataset JSONL (required)
#   --repo OWNER/NAME       Repo slug source (default: fmtlib/fmt)
#   --repos-file PATH       Multi-repo marker — sets slug to "multi"
#   --run-id NAME           Run identifier (default: auto)
#   --max-workers N         Parallel eval workers (default: 1)
#   --timeout N             Per-instance eval timeout in seconds (default: 1800)
#   --multiarch             Build multiarch Docker images during eval
#   --mode MODE             Inference mode (default: default)
#   --dry-run               Show what would be done
#   --start-from STAGE      Resume from this stage
#   --stop-after STAGE      Stop after this stage
#   --stages LIST           Comma-separated stages to run
#   --help                  Show this help
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source "$SCRIPT_DIR/pipeline_lib_cpp.sh"

# ─── Defaults ────────────────────────────────────────────────────────────────
REPO="fmtlib/fmt"
REPOS_FILE=""
RUN_ID=""
DATASET=""
MAX_WORKERS=1
TIMEOUT=1800
MULTIARCH=false
MODE="default"
DRY_RUN=false
START_FROM=""
STOP_AFTER=""
STAGES=""

# ─── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --dataset)      DATASET="$2"; shift 2 ;;
        --repo)         REPO="$2"; shift 2 ;;
        --repos-file)   REPOS_FILE="$2"; shift 2 ;;
        --run-id)       RUN_ID="$2"; shift 2 ;;
        --max-workers)  MAX_WORKERS="$2"; shift 2 ;;
        --timeout)      TIMEOUT="$2"; shift 2 ;;
        --multiarch)    MULTIARCH=true; shift ;;
        --mode)         MODE="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --start-from)   START_FROM="$2"; shift 2 ;;
        --stop-after)   STOP_AFTER="$2"; shift 2 ;;
        --stages)       STAGES="$2"; shift 2 ;;
        --help)
            sed -n '/^# Usage:/,/^###/p' "$0" | sed '$d'
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$DATASET" ]]; then
    echo "ERROR: --dataset is required for the eval phase."
    echo "       Pass the finished dataset JSONL from run_pipeline_dataset_cpp.sh."
    exit 1
fi
if [[ ! -f "$DATASET" ]]; then
    echo "ERROR: dataset not found: $DATASET"
    exit 1
fi

# ─── Derived values ──────────────────────────────────────────────────────────
if [[ -n "$REPOS_FILE" ]]; then
    REPO_SLUG="multi"
    REPO_OWNER="multi"
    [[ -z "$RUN_ID" ]] && RUN_ID="cpp_multi_$(date +%Y%m%d_%H%M%S)"
else
    REPO_SLUG="${REPO##*/}"
    REPO_OWNER="${REPO%%/*}"
    [[ -z "$RUN_ID" ]] && RUN_ID="cpp_${REPO_SLUG}_$(date +%Y%m%d_%H%M%S)"
fi

ARTIFACTS_DIR="$SCRIPT_DIR/artifacts_cpp"
ENRICHED_DIR="$ARTIFACTS_DIR/enriched"
FINAL_DIR="$ARTIFACTS_DIR/final"
EVAL_DIR="$SCRIPT_DIR/logs/run_evaluation_cpp/$RUN_ID"
REPORT_DIR="$SCRIPT_DIR/eval_reports_cpp"

ENRICHED_FILE="$DATASET"
FINAL_DATASET="$DATASET"
GOLD_DIR=""

# ─── Load .env ───────────────────────────────────────────────────────────────
load_env "$SCRIPT_DIR"

# ─── Declare prereqs: eval phase needs Docker, not GitHub ────────────────────
PIPELINE_NEEDS_DOCKER=true
PIPELINE_NEEDS_GITHUB=false

# ─── Validate stage names ────────────────────────────────────────────────────
[[ -n "$START_FROM" ]] && validate_stage_name "$START_FROM"
[[ -n "$STOP_AFTER" ]] && validate_stage_name "$STOP_AFTER"
if [[ -n "$STAGES" ]]; then
    IFS=',' read -ra _validate <<< "$STAGES"
    for _s in "${_validate[@]}"; do validate_stage_name "$_s"; done
    unset _validate _s
fi

###############################################################################
# STAGE 8: Docker Build + Gold Evaluation (C++)
###############################################################################
stage_eval() {
    log "STAGE 8: Build cpp images + Gold Evaluation"

    local dataset_to_use="$DATASET"

    echo "  Dataset:  $dataset_to_use ($(count_lines "$dataset_to_use") instances)"
    echo "  Workers:  $MAX_WORKERS"
    echo "  Timeout:  ${TIMEOUT}s"

    # Stage 8a: Build cpp images.
    step "Building cpp Docker images via build_and_validate_images_cpp..."
    local build_args=(
        --dataset "$dataset_to_use"
        --max-workers "$MAX_WORKERS"
    )
    $MULTIARCH && build_args+=(--build-multiarch)
    run_cmd python3 scripts/build_and_validate_images_cpp.py "${build_args[@]}" || {
        echo "WARNING: image build/validation reported errors; eval may fail for some instances."
    }

    # Stage 8b: Gold evaluation = run with empty prediction (no patch applied).
    # We construct an empty-patch predictions JSONL to drive run_evaluation_cpp.
    ensure_dir "$EVAL_DIR"
    local gold_pred="$EVAL_DIR/_gold_predictions.jsonl"
    python3 -c "
import json
with open('$dataset_to_use') as f, open('$gold_pred', 'w') as out:
    for line in f:
        if not line.strip(): continue
        inst = json.loads(line)
        out.write(json.dumps({
            'instance_id': inst['instance_id'],
            'model_patch': '',
            'model_name_or_path': 'gold'
        }) + '\n')
"

    step "Running gold evaluation..."
    run_cmd python3 -m swefficiency.harness.run_evaluation_cpp \
        --dataset-name "$dataset_to_use" \
        --predictions-path "$gold_pred" \
        --run-id "$RUN_ID" \
        --max-workers "$MAX_WORKERS" \
        --timeout "$TIMEOUT"

    GOLD_DIR="$EVAL_DIR/gold"
    if [[ ! -d "$GOLD_DIR" ]]; then
        GOLD_DIR=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1 || true)
    fi
    if [[ -n "$GOLD_DIR" && -d "$GOLD_DIR" ]]; then
        local n
        n=$(find "$GOLD_DIR" -name "report.json" 2>/dev/null | wc -l | tr -d ' ')
        echo "  → Gold eval: $n instances with report.json"
    else
        $DRY_RUN || { echo "ERROR: No gold eval output."; exit 1; }
    fi
}

###############################################################################
# STAGE 8.5a: Significance Filter (shared — statistical, language-agnostic)
###############################################################################
stage_significance_filter() {
    log "STAGE 8.5a: 2σ Significance Filter (shared module)"
    if $DRY_RUN; then echo "  [DRY-RUN] would apply 2σ significance filter"; return; fi

    local dataset_to_use="$FINAL_DATASET"

    GOLD_DIR="$EVAL_DIR/gold"
    if [[ ! -d "$GOLD_DIR" ]]; then
        GOLD_DIR=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1 || true)
    fi
    if [[ -z "$GOLD_DIR" || ! -d "$GOLD_DIR" ]]; then
        echo "ERROR: No gold eval output for significance filter."
        exit 1
    fi

    ensure_dir "$FINAL_DIR"
    SIGNIFICANT_DATASET="$FINAL_DIR/${REPO_SLUG}-cpp-significant.jsonl"
    step "Applying 2σ significance filter..."
    run_cmd python3 scripts/significance_filter.py \
        --dataset "$dataset_to_use" \
        --eval_dir "$GOLD_DIR" \
        --output "$SIGNIFICANT_DATASET" \
        --sigma 2.0 || echo "WARNING: significance filter failed; continuing."

    if [[ -f "$SIGNIFICANT_DATASET" ]]; then
        echo "  → $(count_lines "$SIGNIFICANT_DATASET") significant instances"
        FINAL_DATASET="$SIGNIFICANT_DATASET"
    fi
}

###############################################################################
# STAGE 8.5: Prediction Evaluation (gold-as-pred for cpp)
###############################################################################
stage_pred_eval() {
    log "STAGE 8.5: Prediction Evaluation (cpp, gold-as-pred)"

    if $DRY_RUN; then
        echo "  [DRY-RUN] skipped"
        return
    fi

    local dataset_to_use="$FINAL_DATASET"

    ensure_dir "$FINAL_DIR"
    local pred_file="$FINAL_DIR/${REPO_SLUG}-cpp-gold-predictions.jsonl"

    step "Creating gold-as-prediction JSONL..."
    python3 -c "
import json
with open('$dataset_to_use') as f:
    instances = [json.loads(l) for l in f if l.strip()]
with open('$pred_file', 'w') as out:
    for inst in instances:
        out.write(json.dumps({
            'instance_id': inst['instance_id'],
            'model_patch': inst.get('patch', ''),
            'model_name_or_path': 'gold_as_pred'
        }) + '\n')
print(f'  → {len(instances)} predictions')
"

    step "Running prediction eval..."
    run_cmd python3 -m swefficiency.harness.run_evaluation_cpp \
        --dataset-name "$dataset_to_use" \
        --predictions-path "$pred_file" \
        --run-id "${RUN_ID}_pred" \
        --max-workers "$MAX_WORKERS" \
        --timeout "$TIMEOUT"
}

###############################################################################
# STAGE 9: Report Generation (cpp)
###############################################################################
stage_report() {
    log "STAGE 9: Report Generation (cpp)"
    if $DRY_RUN; then
        echo "  [DRY-RUN] skipped"
        return
    fi
    ensure_dir "$REPORT_DIR"

    GOLD_DIR="$EVAL_DIR/gold"
    [[ ! -d "$GOLD_DIR" ]] && GOLD_DIR=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)
    PRED_DIR="$SCRIPT_DIR/logs/run_evaluation_cpp/${RUN_ID}_pred/gold_as_pred"
    [[ ! -d "$PRED_DIR" ]] && PRED_DIR=$(find "$SCRIPT_DIR/logs/run_evaluation_cpp/${RUN_ID}_pred" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1 || true)

    local dataset_to_use="$FINAL_DATASET"

    if [[ -d "$GOLD_DIR" && -d "$PRED_DIR" ]]; then
        step "Generating cpp comparison report..."
        run_cmd python3 -m swefficiency.report_cpp \
            --gold-run "$GOLD_DIR" \
            --pred-run "$PRED_DIR" \
            --output-dir "$REPORT_DIR" \
            --num-workers 1 \
            --dataset-name "$dataset_to_use"

        echo ""
        echo "  Reports:"
        ls -la "$REPORT_DIR"/eval_report_cpp_*.* 2>/dev/null || echo "  (no report files)"
        if [[ -f "$REPORT_DIR/eval_report_cpp_gold_as_pred.json" ]]; then
            step "Report Summary:"
            cat "$REPORT_DIR/eval_report_cpp_gold_as_pred.json"
        fi
    else
        echo "  Skipping report: gold=$GOLD_DIR pred=$PRED_DIR"
    fi
}

###############################################################################
# STAGE 10: Inference — Phase 2 stub for cpp
###############################################################################
stage_inference() {
    log "STAGE 10: Inference (cpp) — Phase 2 stub"
    echo "  Cpp OpenHands inference deferred to Phase 2."
    return 0
}

###############################################################################
# MAIN
###############################################################################
main() {
    log "SWE-fficiency C++ Pipeline — Phase 3 (eval)"
    echo "  Run ID:      $RUN_ID"
    echo "  Dataset:     $DATASET"
    echo "  Max workers: $MAX_WORKERS"
    echo "  Platform:    $(uname -s)/$(uname -m)"
    [[ -n "$START_FROM" ]] && echo "  Start from:  $START_FROM"
    [[ -n "$STOP_AFTER" ]] && echo "  Stop after:  $STOP_AFTER"
    [[ -n "$STAGES"     ]] && echo "  Stages:      $STAGES"

    raise_fd_limit
    check_prereqs

    should_run_stage "eval" && stage_eval
    should_run_stage "significance_filter" && stage_significance_filter
    should_run_stage "pred_eval" && stage_pred_eval
    should_run_stage "report" && stage_report
    should_run_stage "inference" && stage_inference
    print_summary
}

main
