#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_pipeline_dataset.sh — Phase 2: Enriched dataset → final dataset + images.
#
# Stages: coverage, flaky_filter, workload.
# Then (flag-gated): build multiarch Docker images and push to ECR, so the
# eval/inference phase can pull pre-built images instead of rebuilding.
#
# Credentials: Docker daemon (coverage/flaky/build), AWS_BEARER_TOKEN_BEDROCK
#              (workload generation). No GitHub token needed.
# Input:  --dataset <enriched jsonl>   (output of run_pipeline_scrape.sh)
# Output: artifacts/final/<slug>-dataset.jsonl  → feed into run_pipeline_eval.sh
#
# Usage:
#   ./run_pipeline_dataset.sh --dataset PATH [OPTIONS]
#
# Options:
#   --dataset PATH          REQUIRED. Enriched dataset JSONL from scrape phase.
#   --run-id NAME           Run identifier (default: auto-generated timestamp)
#   --max-workers N         Parallel workers (default: 1)
#   --skip-workload         Skip LLM workload generation
#   --flaky-runs N          Flaky-detection runs (default: 10)
#   --timeout N             Per-instance eval timeout in seconds (default: 1800)
#   --multiarch             Build amd64+arm64 Docker images and push to ECR.
#                           Requires the ECR_REGISTRY env var to be set.
#   --use-helicone          Route LLM calls through Helicone proxy
#   --dry-run               Show what would be done without executing
#   --start-from STAGE      Start from this stage, skip all prior stages
#   --stop-after STAGE      Stop after this stage, skip all later stages
#   --stages LIST           Comma-separated list of stages to run
#   --help                  Show this help
#
# Stages (in execution order): coverage, flaky_filter, workload
# ECR push: gated on --multiarch + ECR_REGISTRY env var (see stage_build_images).
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/pipeline_lib.sh"

# ─── Defaults ─────────────────────────────────────────────────────────────────
DATASET=""
RUN_ID=""
MAX_WORKERS=1
SKIP_WORKLOAD=false
FLAKY_RUNS=10
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
        --dataset)       DATASET="$2"; shift 2 ;;
        --run-id)        RUN_ID="$2"; shift 2 ;;
        --max-workers)   MAX_WORKERS="$2"; shift 2 ;;
        --skip-workload) SKIP_WORKLOAD=true; shift ;;
        --flaky-runs)    FLAKY_RUNS="$2"; shift 2 ;;
        --timeout)       TIMEOUT="$2"; shift 2 ;;
        --multiarch)     MULTIARCH=true; shift ;;
        --use-helicone)  USE_HELICONE=true; shift ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --start-from)    START_FROM="$2"; shift 2 ;;
        --stop-after)    STOP_AFTER="$2"; shift 2 ;;
        --stages)        STAGES="$2"; shift 2 ;;
        --help)
            sed -n '/^# Usage:/,/^###/p' "$0" | sed '$d'
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$DATASET" ]]; then
    echo "ERROR: --dataset is required (the enriched JSONL from run_pipeline_scrape.sh)."
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
FILTERED_DIR="$ARTIFACTS_DIR/perf_filtered"
ENRICHED_DIR="$ARTIFACTS_DIR/enriched"
FINAL_DIR="$ARTIFACTS_DIR/final"
WORKLOAD_DIR="$SCRIPT_DIR/logs/workload_generation/$RUN_ID"
EVAL_DIR="$SCRIPT_DIR/logs/run_evaluation/$RUN_ID"
REPORT_DIR=""

# ENRICHED_FILE starts as the phase input; coverage/flaky overwrite it as they
# narrow the dataset, and stage_workload consumes whatever the latest value is.
ENRICHED_FILE="$DATASET"
COVERAGE_FILTERED=""
FLAKY_FILTERED=""
FINAL_DATASET=""

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
# STAGE 4.5: Coverage Detection (Paper Stage III)
###############################################################################
stage_coverage() {
    log "STAGE 4.5: Coverage Detection (Paper Stage III)"

    local dataset_to_use="${ENRICHED_FILE:-$DATASET}"
    if [[ -n "$DATASET" ]]; then
        dataset_to_use="$DATASET"
    fi

    echo "  Dataset:  $dataset_to_use ($(count_lines "$dataset_to_use") instances)"
    echo "  Workers:  $MAX_WORKERS"

    local coverage_run_id="${RUN_ID}_coverage"
    local coverage_eval_dir="$SCRIPT_DIR/logs/run_evaluation/${coverage_run_id}"

    step "Running coverage detection (Docker-based)..."
    run_cmd python3 swefficiency/harness/run_validation.py \
        --dataset_name "$dataset_to_use" \
        --run_id "$coverage_run_id" \
        --max_workers "$MAX_WORKERS" \
        --max_build_workers "$MAX_WORKERS" \
        --timeout "$TIMEOUT" \
        --use_ecr_images false \
        --run_perf false \
        --run_correctness false \
        --run_coverage true \
        --allow_test_patch \
        --multiarch $MULTIARCH

    local gold_dir="$coverage_eval_dir/gold"
    if [[ ! -d "$gold_dir" ]]; then
        # Fallback: find subdirectory containing actual eval artifacts (not just any dir)
        gold_dir=$(find "$coverage_eval_dir" -mindepth 2 -maxdepth 2 -name "covering_tests.txt" -exec dirname {} \; 2>/dev/null | head -1 | xargs dirname 2>/dev/null || true)
        # If still nothing, try any subdirectory (last resort)
        if [[ -z "$gold_dir" || ! -d "$gold_dir" ]]; then
            gold_dir=$(find "$coverage_eval_dir" -mindepth 1 -maxdepth 1 -type d -not -name ".*" 2>/dev/null | head -1 || true)
        fi
    fi

    if [[ -z "$gold_dir" || ! -d "$gold_dir" ]]; then
        echo "ERROR: Coverage run produced no output at $coverage_eval_dir"
        exit 1
    fi

    local ct_count
    ct_count=$(find "$gold_dir" -name "covering_tests.txt" 2>/dev/null | wc -l | tr -d ' ')
    echo "  → Coverage found for $ct_count instances"

    ensure_dir "$FILTERED_DIR"
    COVERAGE_FILTERED="$FILTERED_DIR/${REPO_SLUG}-coverage-filtered.jsonl"

    step "Merging coverage into dataset and filtering..."
    run_cmd python3 scripts/merge_coverage.py \
        --dataset "$dataset_to_use" \
        --eval_dir "$gold_dir" \
        --output "$COVERAGE_FILTERED"

    if [[ -f "$COVERAGE_FILTERED" ]]; then
        echo "  → $(count_lines "$COVERAGE_FILTERED") instances with coverage (paper: ~11.2% retention)"
        ENRICHED_FILE="$COVERAGE_FILTERED"
    else
        echo "ERROR: Coverage filtering failed."
        exit 1
    fi
}

###############################################################################
# STAGE 4.6: Flaky Test Detection (Paper Stage V — test stability)
# NOTE: Paper requires N=10 correctness runs per instance. At scale (10k+),
#   this is ~100k container runs. The harness skips already-built images
#   (resume mode), so subsequent runs reuse Docker images. Scale horizontally
#   with MAX_WORKERS to parallelize.  Reduce FLAKY_RUNS to 3-5 for screening.
###############################################################################
stage_flaky_filter() {
    log "STAGE 4.6: Flaky Test Detection ($FLAKY_RUNS runs, Paper Stage V)"

    local dataset_to_use="${COVERAGE_FILTERED:-${ENRICHED_FILE:-$DATASET}}"
    if [[ -n "$DATASET" ]]; then
        dataset_to_use="$DATASET"
    fi

    echo "  Dataset:  $dataset_to_use ($(count_lines "$dataset_to_use") instances)"
    echo "  Runs:     $FLAKY_RUNS"
    echo "  Workers:  $MAX_WORKERS"

    local flaky_dirs=()

    for i in $(seq 1 "$FLAKY_RUNS"); do
        local run_id="${RUN_ID}_flaky_${i}"
        local flaky_eval_dir="$SCRIPT_DIR/logs/run_evaluation/${run_id}"

        step "Flaky run $i/$FLAKY_RUNS..."
        run_cmd python3 swefficiency/harness/run_validation.py \
            --dataset_name "$dataset_to_use" \
            --run_id "$run_id" \
            --max_workers "$MAX_WORKERS" \
            --max_build_workers "$MAX_WORKERS" \
            --timeout "$TIMEOUT" \
            --use_ecr_images false \
            --run_perf false \
            --run_correctness true \
            --run_coverage false \
            --multiarch $MULTIARCH

        local gold_dir="$flaky_eval_dir/gold"
        if [[ ! -d "$gold_dir" ]]; then
            gold_dir=$(find "$flaky_eval_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1 || true)
        fi
        if [[ -n "$gold_dir" && -d "$gold_dir" ]]; then
            flaky_dirs+=("$gold_dir")
        fi
    done

    if [[ ${#flaky_dirs[@]} -lt 3 ]]; then
        echo "WARNING: Only ${#flaky_dirs[@]} flaky runs succeeded. Skipping flaky filter."
        return
    fi

    ensure_dir "$FILTERED_DIR"
    FLAKY_FILTERED="$FILTERED_DIR/${REPO_SLUG}-flaky-filtered.jsonl"

    step "Filtering flaky tests..."
    run_cmd python3 scripts/flaky_test_filter.py \
        --dataset "$dataset_to_use" \
        --eval_dirs "${flaky_dirs[@]}" \
        --output "$FLAKY_FILTERED" \
        --min_runs 3

    if [[ -f "$FLAKY_FILTERED" ]]; then
        echo "  → $(count_lines "$FLAKY_FILTERED") instances after flaky filter"
        ENRICHED_FILE="$FLAKY_FILTERED"
    else
        echo "WARNING: Flaky filter failed. Continuing with unfiltered dataset."
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
    run_cmd python3 -m swefficiency.workload.run_synthetic_generation \
        --dataset_name "$ENRICHED_FILE" \
        --run_id "$RUN_ID" \
        --max_workers "$MAX_WORKERS"

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
# Multiarch Docker build + ECR push (flag-gated)
# Runs only when --multiarch is passed. Builds the base→env→instance image
# chain for amd64+arm64 via buildx and pushes the manifest list to the registry
# named by the ECR_REGISTRY env var. This prepares pre-built images so the
# eval/inference phase can pull instead of rebuilding.
###############################################################################
stage_build_images() {
    if ! $MULTIARCH; then
        step "Skipping multiarch image build (pass --multiarch to enable)."
        return 0
    fi

    log "Multiarch Docker Build + ECR Push"

    local dataset_to_use="${FINAL_DATASET:-$ENRICHED_FILE}"
    if [[ -z "$dataset_to_use" || ! -f "$dataset_to_use" ]]; then
        echo "ERROR: No dataset available for image build (looked for FINAL_DATASET/ENRICHED_FILE)."
        exit 1
    fi

    # ECR push is env-driven: ECR_REGISTRY names the target registry. The
    # underlying scripts/build_and_validate_images.py requires --registry when
    # --build-multiarch is set (an unqualified push targets docker.io and 401s).
    local registry="${ECR_REGISTRY:-}"
    if [[ -z "$registry" ]]; then
        echo "ERROR: --multiarch requires the ECR_REGISTRY env var to be set."
        echo "  Set ECR_REGISTRY=<account>.dkr.ecr.<region>.amazonaws.com"
        echo "  (the multiarch manifest is pushed to <ECR_REGISTRY>/swefficiency-images:<id>)."
        exit 1
    fi

    echo "  Dataset:  $dataset_to_use ($(count_lines "$dataset_to_use") instances)"
    echo "  Registry: $registry"
    echo "  Workers:  $MAX_WORKERS"

    step "Building amd64+arm64 images and pushing to ECR..."
    run_cmd python3 scripts/build_and_validate_images.py \
        --dataset "$dataset_to_use" \
        --max-workers "$MAX_WORKERS" \
        --build-multiarch \
        --registry "$registry"
}

###############################################################################
# MAIN
###############################################################################
main() {
    log "SWE-fficiency Pipeline [DATASET] — $REPO_SLUG"
    echo "  Run ID:      $RUN_ID"
    echo "  Dataset:     $DATASET"
    echo "  Max workers: $MAX_WORKERS"
    echo "  Multiarch:   $MULTIARCH"
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

    # ── Stage-gated execution ──
    should_run_stage "coverage"     && stage_coverage
    should_run_stage "flaky_filter" && stage_flaky_filter

    export _ENRICHED="${ENRICHED_FILE:-}"
    export _FINAL="${FINAL_DATASET:-}"
    export _WL_OUTPUT=""

    if should_run_stage "workload" && ! $SKIP_WORKLOAD; then
        stage_workload
    else
        FINAL_DATASET="${FINAL_DATASET:-$ENRICHED_FILE}"
    fi

    # Multiarch build + ECR push — gated internally on --multiarch.
    stage_build_images

    if [[ -n "${FINAL_DATASET:-}" ]]; then
        echo ""
        echo "  Final dataset: $FINAL_DATASET"
        echo "  → Next: ./run_pipeline_eval.sh --dataset \"$FINAL_DATASET\" [--run-id $RUN_ID ...]"
    fi
    print_summary
}

main
