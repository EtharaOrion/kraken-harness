#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_pipeline_eval.sh — Phase 3: Final dataset → evaluation, reports, traces.
#
# Stages: eval, significance_filter, pred_eval, report, inference.
# Credentials: Docker daemon; LLM creds for --mode openhands inference.
# Input:  --dataset <final jsonl>   (output of run_pipeline_dataset.sh)
#
# If ECR_REGISTRY is set in the environment, the harness automatically pulls
# pre-built images from ECR (via SWEFF_ECR_PULL_FIRST, default on) instead of
# rebuilding — this is what run_pipeline_dataset.sh --multiarch prepares.
#
# Usage:
#   ./run_pipeline_eval.sh --dataset PATH [OPTIONS]
#
# Options:
#   --dataset PATH          REQUIRED. Final dataset JSONL from the dataset phase.
#   --run-id NAME           Run identifier (default: auto-generated timestamp)
#   --max-workers N         Parallel workers (default: 1)
#   --mode MODE             Inference mode: default|openhands (default: default)
#   --timeout N             Per-instance eval timeout in seconds (default: 1800)
#   --multiarch             Pass through to the harness for multiarch image use
#   --use-helicone          Route LLM calls through Helicone proxy
#   --dry-run               Show what would be done without executing
#   --start-from STAGE      Start from this stage, skip all prior stages
#   --stop-after STAGE      Stop after this stage, skip all later stages
#   --stages LIST           Comma-separated list of stages to run
#   --help                  Show this help
#
# Stages (in execution order):
#   eval, significance_filter, pred_eval, report, inference
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/pipeline_lib.sh"

# ─── Defaults ─────────────────────────────────────────────────────────────────
DATASET=""
RUN_ID=""
MAX_WORKERS=1
MODE="default"
TIMEOUT=1800
MULTIARCH=false
USE_HELICONE=false
DRY_RUN=false
START_FROM=""
STOP_AFTER=""
STAGES=""

# ─── Parse args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --dataset)      DATASET="$2"; shift 2 ;;
        --run-id)       RUN_ID="$2"; shift 2 ;;
        --max-workers)  MAX_WORKERS="$2"; shift 2 ;;
        --mode)         MODE="$2"; shift 2 ;;
        --timeout)      TIMEOUT="$2"; shift 2 ;;
        --multiarch)    MULTIARCH=true; shift ;;
        --use-helicone) USE_HELICONE=true; shift ;;
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
    echo "ERROR: --dataset is required (the final JSONL from run_pipeline_dataset.sh)."
    exit 1
fi
if [[ ! -f "$DATASET" ]]; then
    echo "ERROR: --dataset file not found: $DATASET"
    exit 1
fi

# ─── Derived values ───────────────────────────────────────────────────────────
REPO_SLUG="$(basename "${DATASET%.jsonl}")"
REPO="$REPO_SLUG"
[[ -z "$RUN_ID" ]] && RUN_ID="${REPO_SLUG}_$(date +%Y%m%d_%H%M%S)"

ARTIFACTS_DIR="$SCRIPT_DIR/artifacts"
FINAL_DIR="$ARTIFACTS_DIR/final"
EVAL_DIR="$SCRIPT_DIR/logs/run_evaluation/$RUN_ID"
REPORT_DIR="$SCRIPT_DIR/eval_reports"

# All eval stages resolve their dataset to $DATASET; ENRICHED_FILE/FINAL_DATASET
# are kept defined so the shared `${VAR:-...}` expansions stay safe under set -u.
ENRICHED_FILE="$DATASET"
FINAL_DATASET="$DATASET"
GOLD_DIR=""
PRED_DIR=""
SIGNIFICANT_DATASET=""

load_env "$SCRIPT_DIR"

# ─── Validate resume stage names ──────────────────────────────────────────────
[[ -n "$START_FROM" ]] && validate_stage_name "$START_FROM"
[[ -n "$STOP_AFTER" ]] && validate_stage_name "$STOP_AFTER"
if [[ -n "$STAGES" ]]; then
    IFS=',' read -ra _validate <<< "$STAGES"
    for _s in "${_validate[@]}"; do validate_stage_name "$_s"; done
    unset _validate _s
fi

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
    run_cmd python3 swefficiency/harness/run_validation.py \
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
        --multiarch $MULTIARCH

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
# STAGE 8.5a: Significance Filter (Paper Stage V — μ_pre - μ_post > 2σ_post)
###############################################################################
stage_significance_filter() {
    log "STAGE 8.5a: Statistical Significance Filter (Paper Stage V)"
    if $DRY_RUN; then echo "  [DRY-RUN] would apply 2σ significance filter"; return; fi

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    if [[ -n "$DATASET" ]]; then
        dataset_to_use="$DATASET"
    fi

    GOLD_DIR="$EVAL_DIR/gold"
    if [[ ! -d "$GOLD_DIR" ]]; then
        GOLD_DIR=$(find "$EVAL_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1 || true)
    fi

    if [[ -z "$GOLD_DIR" || ! -d "$GOLD_DIR" ]]; then
        echo "ERROR: No gold eval output for significance filter. Run eval first."
        exit 1
    fi

    ensure_dir "$FINAL_DIR"
    SIGNIFICANT_DATASET="$FINAL_DIR/${REPO_SLUG}-significant.jsonl"

    step "Applying 2σ significance filter..."
    run_cmd python3 scripts/significance_filter.py \
        --dataset "$dataset_to_use" \
        --eval_dir "$GOLD_DIR" \
        --output "$SIGNIFICANT_DATASET" \
        --sigma 2.0

    if [[ -f "$SIGNIFICANT_DATASET" ]]; then
        echo "  → $(count_lines "$SIGNIFICANT_DATASET") statistically significant instances"
        FINAL_DATASET="$SIGNIFICANT_DATASET"
    else
        echo "WARNING: Significance filter failed. Continuing with unfiltered dataset."
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
    run_cmd python3 swefficiency/harness/run_validation.py \
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
        --multiarch $MULTIARCH \
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
        run_cmd python3 -m swefficiency.cli report \
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
    run_cmd python3 scripts/inference/custom.py \
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
# MAIN
###############################################################################
main() {
    log "SWE-fficiency Pipeline [EVAL] — $REPO_SLUG"
    echo "  Run ID:      $RUN_ID"
    echo "  Dataset:     $DATASET"
    echo "  Mode:        $MODE"
    echo "  Max workers: $MAX_WORKERS"
    echo "  Timeout:     ${TIMEOUT}s"
    echo "  Platform:    $(uname -s)/$(uname -m)"
    [[ -n "$START_FROM" ]] && echo "  Start from:  $START_FROM"
    [[ -n "$STOP_AFTER" ]] && echo "  Stop after:  $STOP_AFTER"
    [[ -n "$STAGES" ]]     && echo "  Stages:      $STAGES"

    raise_fd_limit
    PIPELINE_NEEDS_DOCKER=true
    PIPELINE_NEEDS_GITHUB=false
    check_prereqs

    if $USE_HELICONE; then
        export ENABLE_HELICONE=1
    fi

    # ── Resume prerequisite checks ──
    if ! should_run_stage "eval" && { should_run_stage "pred_eval" || should_run_stage "report"; }; then
        GOLD_DIR="$EVAL_DIR/gold"
        [[ ! -d "$GOLD_DIR" ]] && { echo "ERROR: resuming at pred_eval/report but no gold eval at $GOLD_DIR"; exit 1; }
    fi
    if ! should_run_stage "pred_eval" && should_run_stage "report"; then
        PRED_DIR="$EVAL_DIR/gold_as_pred"
        [[ ! -d "$PRED_DIR" ]] && { echo "ERROR: resuming at report but no pred eval at $PRED_DIR"; exit 1; }
    fi

    # ── Stage-gated execution ──
    should_run_stage "eval"                && stage_eval
    should_run_stage "significance_filter" && stage_significance_filter
    should_run_stage "pred_eval"           && stage_pred_eval
    should_run_stage "report"              && stage_report
    should_run_stage "inference"           && stage_inference
    print_summary
}

main
