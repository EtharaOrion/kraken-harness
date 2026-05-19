#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_pipeline_dataset_cpp.sh — Phase 2 (C++): enriched → final dataset + images.
#
# Stages: coverage (Phase-1 stub), flaky_filter (Phase-1 stub), workload.
# Then (flag-gated): build multiarch C++ Docker images and push to ECR, so the
# eval/inference phase can pull pre-built images instead of rebuilding.
#
# Credentials: Docker daemon (image build), Bedrock creds (workload generation).
# Input:  --dataset <enriched jsonl>   (output of run_pipeline_scrape_cpp.sh)
# Output: artifacts_cpp/final/<slug>-cpp-dataset.jsonl
#         → feed into run_pipeline_eval_cpp.sh
#
# Usage:
#   ./run_pipeline_dataset_cpp.sh --dataset PATH [OPTIONS]
#
# Options:
#   --dataset PATH          REQUIRED. Enriched dataset JSONL from scrape phase.
#   --run-id NAME           Run identifier (default: auto)
#   --max-workers N         Parallel workers (default: 1)
#   --skip-workload         Skip LLM workload generation
#   --flaky-runs N          Flaky-detection runs (default: 10; Phase-1 stub)
#   --timeout N             Per-instance timeout in seconds (default: 1800)
#   --multiarch             Build amd64+arm64 C++ Docker images and push to ECR.
#                           Requires the ECR_REGISTRY env var to be set.
#   --dry-run               Show what would be done
#   --start-from STAGE      Resume from this stage
#   --stop-after STAGE      Stop after this stage
#   --stages LIST           Comma-separated stages to run
#   --help                  Show this help
#
# Stages (execution order): coverage, flaky_filter, workload
# ECR push: gated on --multiarch + ECR_REGISTRY env var (see stage_build_images).
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/pipeline_lib_cpp.sh"

# ─── Defaults ────────────────────────────────────────────────────────────────
DATASET=""
RUN_ID=""
MAX_WORKERS=1
SKIP_WORKLOAD=false
FLAKY_RUNS=10
TIMEOUT=1800
MULTIARCH=false
DRY_RUN=false
START_FROM=""
STOP_AFTER=""
STAGES=""

# ─── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --dataset)       DATASET="$2"; shift 2 ;;
        --run-id)        RUN_ID="$2"; shift 2 ;;
        --max-workers)   MAX_WORKERS="$2"; shift 2 ;;
        --skip-workload) SKIP_WORKLOAD=true; shift ;;
        --flaky-runs)    FLAKY_RUNS="$2"; shift 2 ;;
        --timeout)       TIMEOUT="$2"; shift 2 ;;
        --multiarch)     MULTIARCH=true; shift ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --start-from)    START_FROM="$2"; shift 2 ;;
        --stop-after)    STOP_AFTER="$2"; shift 2 ;;
        --stages)        STAGES="$2"; shift 2 ;;
        --help)
            # Use sed '$d' instead of GNU 'head -n -1' for macOS BSD compatibility.
            sed -n '/^# Usage:/,/^###/p' "$0" | sed '$d'
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$DATASET" ]]; then
    echo "ERROR: --dataset is required (the enriched JSONL from run_pipeline_scrape_cpp.sh)."
    exit 1
fi
if [[ ! -f "$DATASET" ]]; then
    echo "ERROR: --dataset file not found: $DATASET"
    exit 1
fi

# ─── Derived values ──────────────────────────────────────────────────────────
REPO_SLUG="$(basename "${DATASET%.jsonl}")"
REPO="$REPO_SLUG"
[[ -z "$RUN_ID" ]] && RUN_ID="cpp_${REPO_SLUG}_$(date +%Y%m%d_%H%M%S)"

ARTIFACTS_DIR="$SCRIPT_DIR/artifacts_cpp"
ENRICHED_DIR="$ARTIFACTS_DIR/enriched"
FINAL_DIR="$ARTIFACTS_DIR/final"
WORKLOAD_DIR="$SCRIPT_DIR/logs/workload_generation_cpp/$RUN_ID"
EVAL_DIR="$SCRIPT_DIR/logs/run_evaluation_cpp/$RUN_ID"
REPORT_DIR=""

# stage_workload consumes ENRICHED_FILE; coverage/flaky are Phase-1 stubs that
# pass the dataset through unchanged.
ENRICHED_FILE="$DATASET"
FINAL_DATASET=""

load_env "$SCRIPT_DIR"

# ─── Validate resume stage names ─────────────────────────────────────────────
[[ -n "$START_FROM" ]] && validate_stage_name "$START_FROM"
[[ -n "$STOP_AFTER" ]] && validate_stage_name "$STOP_AFTER"
if [[ -n "$STAGES" ]]; then
    IFS=',' read -ra _validate <<< "$STAGES"
    for _s in "${_validate[@]}"; do validate_stage_name "$_s"; done
    unset _validate _s
fi

###############################################################################
# STAGE 4.5: Coverage Detection — Phase 1 stub
#   coverage MAY stub for Phase 1; it requires run_validation_cpp.py (Phase 2).
###############################################################################
stage_coverage() {
    log "STAGE 4.5: Coverage Detection (cpp) — Phase 1 stub"
    echo "  Coverage requires run_validation_cpp.py (Phase 2). Skipping."
    echo "  Dataset passes through unchanged."
    return 0
}

###############################################################################
# STAGE 4.6: Flaky Test Detection — Phase 1 stub
###############################################################################
stage_flaky_filter() {
    log "STAGE 4.6: Flaky Test Detection (cpp) — Phase 1 stub"
    echo "  Flaky filter requires N=$FLAKY_RUNS correctness runs via run_validation_cpp.py (Phase 2)."
    echo "  Dataset passes through unchanged."
    return 0
}

###############################################################################
# STAGE 7: Workload Generation (LLM, C++)
###############################################################################
stage_workload() {
    log "STAGE 7: Generating cpp workloads via LLM"

    if [[ -z "${AWS_BEARER_TOKEN_BEDROCK:-}" && -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
        echo "ERROR: No Bedrock credentials. Set AWS_BEARER_TOKEN_BEDROCK or AWS_ACCESS_KEY_ID."
        exit 1
    fi

    # Compile-validation is critical for shipping non-broken workloads;
    # default to ON for pipeline runs so DLQ at workload_uncompilable_cpp.jsonl
    # is actually reachable. Honour any user override.
    export SWEFF_VALIDATE_CPP_WORKLOAD="${SWEFF_VALIDATE_CPP_WORKLOAD:-1}"

    step "Generating Google Benchmark workloads..."
    run_cmd python3 -m swefficiency.workload.run_synthetic_generation_cpp \
        --dataset_name "$ENRICHED_FILE" \
        --run_id "$RUN_ID" \
        --max_workers "$MAX_WORKERS"

    local wl_output
    wl_output=$(find "logs/workload_generation_cpp/$RUN_ID" -name "workload_generation_cpp.json" -type f 2>/dev/null | head -1)
    if [[ -z "$wl_output" ]]; then
        wl_output=$(find "logs/workload_generation_cpp/$RUN_ID" -name "*.json" -type f 2>/dev/null | head -1)
    fi

    ensure_dir "$FINAL_DIR"
    FINAL_DATASET="$FINAL_DIR/${REPO_SLUG}-cpp-dataset.jsonl"

    step "Merging workloads into dataset..."
    _ENRICHED="$ENRICHED_FILE" _WL_OUTPUT="${wl_output:-}" _FINAL="$FINAL_DATASET" python3 << 'PYEOF'
import json, os, pathlib

enriched_path = os.environ["_ENRICHED"]
wl_path = os.environ.get("_WL_OUTPUT", "")
out_path = os.environ["_FINAL"]

enriched = {}
with open(enriched_path) as f:
    for line in f:
        if line.strip():
            inst = json.loads(line)
            enriched[inst["instance_id"]] = inst

workloads = {}
if wl_path and os.path.exists(wl_path):
    content = open(wl_path).read().strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            data = [data]
    except json.JSONDecodeError:
        data = [json.loads(line) for line in content.splitlines() if line.strip()]
    for item in data:
        iid = item.get("instance_id", "")
        wl = item.get("workload", item.get("generated_workload", ""))
        if not wl:
            wl_file = item.get("workload_file", "")
            if wl_file and os.path.exists(wl_file):
                wl = pathlib.Path(wl_file).read_text()
        if iid and wl:
            workloads[iid] = wl

merged = 0
with open(out_path, "w") as out:
    for iid, inst in enriched.items():
        if iid in workloads:
            inst["workload"] = workloads[iid]
            merged += 1
        inst.setdefault("PASS_TO_PASS", [])
        inst.setdefault("FAIL_TO_PASS", [])
        inst.setdefault("covering_tests", [])
        inst.setdefault("test_patch", "")
        inst.setdefault("environment_setup_commit", inst.get("base_commit", ""))
        inst.setdefault("language", "cpp")
        out.write(json.dumps(inst) + "\n")
print(f"  → Merged {merged}/{len(enriched)} workloads → {out_path}")
PYEOF
}

###############################################################################
# Multiarch C++ Docker build + ECR push (flag-gated)
# Runs only when --multiarch is passed. Builds the base→env→instance cpp image
# chain for amd64+arm64 via buildx and pushes the manifest list to the registry
# named by the ECR_REGISTRY env var, preparing pre-built images for eval.
###############################################################################
stage_build_images() {
    if ! $MULTIARCH; then
        step "Skipping multiarch image build (pass --multiarch to enable)."
        return 0
    fi

    log "Multiarch C++ Docker Build + ECR Push"

    local dataset_to_use="${FINAL_DATASET:-$ENRICHED_FILE}"
    if [[ -z "$dataset_to_use" || ! -f "$dataset_to_use" ]]; then
        echo "ERROR: No dataset available for image build (looked for FINAL_DATASET/ENRICHED_FILE)."
        exit 1
    fi

    # ECR push is env-driven: ECR_REGISTRY names the target registry. The
    # underlying build_and_validate_images_cpp.py needs --registry when
    # --build-multiarch is set (an unqualified push targets docker.io and 401s).
    local registry="${ECR_REGISTRY:-}"
    if [[ -z "$registry" ]]; then
        echo "ERROR: --multiarch requires the ECR_REGISTRY env var to be set."
        echo "  Set ECR_REGISTRY=<account>.dkr.ecr.<region>.amazonaws.com"
        echo "  (the multiarch manifest is pushed to <ECR_REGISTRY>/swefficiency-images-cpp:<id>)."
        exit 1
    fi

    echo "  Dataset:  $dataset_to_use ($(count_lines "$dataset_to_use") instances)"
    echo "  Registry: $registry"
    echo "  Workers:  $MAX_WORKERS"

    step "Building amd64+arm64 cpp images and pushing to ECR..."
    run_cmd python3 scripts/build_and_validate_images_cpp.py \
        --dataset "$dataset_to_use" \
        --max-workers "$MAX_WORKERS" \
        --build-multiarch \
        --registry "$registry"
}

###############################################################################
# MAIN
###############################################################################
main() {
    log "SWE-fficiency C++ Pipeline [DATASET] — $REPO_SLUG"
    echo "  Run ID:      $RUN_ID"
    echo "  Dataset:     $DATASET"
    echo "  Max workers: $MAX_WORKERS"
    echo "  Multiarch:   $MULTIARCH"
    echo "  Platform:    $(uname -s)/$(uname -m)"
    [[ -n "$START_FROM" ]] && echo "  Start from:  $START_FROM"
    [[ -n "$STOP_AFTER" ]] && echo "  Stop after:  $STOP_AFTER"
    [[ -n "$STAGES"     ]] && echo "  Stages:      $STAGES"

    raise_fd_limit
    PIPELINE_NEEDS_DOCKER=true
    PIPELINE_NEEDS_GITHUB=false
    check_prereqs

    # ── Stage-gated execution ──
    should_run_stage "coverage"     && stage_coverage
    should_run_stage "flaky_filter" && stage_flaky_filter

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
        echo "  → Next: ./run_pipeline_eval_cpp.sh --dataset \"$FINAL_DATASET\" [--run-id $RUN_ID ...]"
    fi
    print_summary
}

main
