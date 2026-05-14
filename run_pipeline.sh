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
#   --repos-file PATH       File with repos, one per line (output of discover_repos.py)
#   --run-id NAME           Run identifier (default: auto-generated timestamp)
#   --cutoff-date YYYYMMDD  PR cutoff date (default: 20180101)
#   --max-pulls N           Max PRs to scrape (default: unlimited)
#   --max-workers N         Parallel workers for eval (default: 1)
#   --skip-scrape           Skip stages 1-6, use existing enriched JSONL
#   --skip-workload         Skip workload generation
#   --filter-early          Apply perf filter at Stage I (reduces volume ~95%)
#   --dataset PATH          Use existing dataset JSONL (skips scrape+filter+version)
#   --mode MODE             Inference mode: default|openhands (default: default)
#   --dry-run               Show what would be done without executing
#   --use-helicone          Route LLM calls through Helicone proxy
#   --multiarch             Build base+env Docker images for amd64+arm64 via buildx
#   --timeout N             Eval timeout in seconds (default: 1800)
#   --start-from STAGE      Start from this stage, skip all prior stages
#   --stop-after STAGE      Stop after this stage, skip all later stages
#   --stages LIST           Comma-separated list of stages to run (e.g., eval,report)
#   --help                  Show this help
#
# Stages (in execution order):
#   scrape, perf_filter, versioning, detect_specs, coverage, flaky_filter,
#   workload, eval, significance_filter, pred_eval, report, inference
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Defaults ─────────────────────────────────────────────────────────────────
REPO="psf/requests"
REPOS_FILE=""
FILTER_EARLY=false
RUN_ID=""
CUTOFF_DATE="20180101"
MAX_PULLS=""
MAX_WORKERS=1
SKIP_SCRAPE=false
SKIP_WORKLOAD=false
DATASET=""
MODE="default"
DRY_RUN=false
USE_HELICONE=false
MULTIARCH=false
TIMEOUT=1800
START_FROM=""
STOP_AFTER=""
STAGES=""
FLAKY_RUNS=10

# ─── Parse args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --repo)         REPO="$2"; shift 2 ;;
        --repos-file)   REPOS_FILE="$2"; shift 2 ;;
        --run-id)       RUN_ID="$2"; shift 2 ;;
        --cutoff-date)  CUTOFF_DATE="$2"; shift 2 ;;
        --max-pulls)    MAX_PULLS="$2"; shift 2 ;;
        --max-workers)  MAX_WORKERS="$2"; shift 2 ;;
        --skip-scrape)  SKIP_SCRAPE=true; shift ;;
        --skip-workload) SKIP_WORKLOAD=true; shift ;;
        --dataset)      DATASET="$2"; shift 2 ;;
        --mode)         MODE="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --use-helicone) USE_HELICONE=true; shift ;;
        --multiarch)    MULTIARCH=true; shift ;;
        --timeout)      TIMEOUT="$2"; shift 2 ;;
        --start-from)   START_FROM="$2"; shift 2 ;;
        --stop-after)   STOP_AFTER="$2"; shift 2 ;;
        --stages)       STAGES="$2"; shift 2 ;;
        --filter-early) FILTER_EARLY=true; shift ;;
        --flaky-runs)   FLAKY_RUNS="$2"; shift 2 ;;
        --help)
            sed -n '/^# Usage:/,/^###/p' "$0" | head -n -1
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── Derived values ───────────────────────────────────────────────────────────
if [[ -n "$REPOS_FILE" ]]; then
    # Multi-repo mode: use generic slug
    REPO_SLUG="multi"
    REPO_OWNER="multi"
    [[ -z "$RUN_ID" ]] && RUN_ID="multi_$(date +%Y%m%d_%H%M%S)"
else
    REPO_SLUG="${REPO##*/}"
    REPO_OWNER="${REPO%%/*}"
    [[ -z "$RUN_ID" ]] && RUN_ID="${REPO_SLUG}_$(date +%Y%m%d_%H%M%S)"
fi

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

    if should_run_stage "eval" || should_run_stage "pred_eval" || should_run_stage "inference"; then
        if ! docker info >/dev/null 2>&1; then
            echo "ERROR: Docker daemon not running. Start Docker Desktop first."
            exit 1
        fi
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

# Per-stage hard timeout (default 8h). Override via SWEFF_STAGE_TIMEOUT env.
# Stages run on a single host; a hang here blocks the whole 10k pipeline,
# so we wrap every python subprocess with `timeout` when available.
STAGE_TIMEOUT="${SWEFF_STAGE_TIMEOUT:-28800}"
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
if [[ -z "$TIMEOUT_BIN" ]]; then
    echo "WARNING: 'timeout' not found on PATH; stage hangs will NOT be bounded." >&2
fi

run_cmd() {
    if $DRY_RUN; then
        echo "[DRY-RUN] $*"
        return 0
    fi
    if [[ -n "$TIMEOUT_BIN" ]]; then
        "$TIMEOUT_BIN" --kill-after=60 "$STAGE_TIMEOUT" "$@"
        local rc=$?
        if [[ $rc -eq 124 || $rc -eq 137 ]]; then
            echo "ERROR: stage timed out after ${STAGE_TIMEOUT}s: $*" >&2
            return 124
        fi
        return $rc
    else
        "$@"
    fi
}

count_lines() { wc -l < "$1" | tr -d ' '; }

# Concatenate JSONL files with strict line-count validation. Aborts on mismatch.
# Replaces previous 'cat ... 2>/dev/null || true' anti-pattern that silently
# dropped files on any read error.
safe_concat_jsonl() {
    local out="$1"; shift
    local sources=("$@")
    local expected=0 actual=0
    : > "$out"
    for src in "${sources[@]}"; do
        if [[ ! -f "$src" ]]; then
            echo "ERROR: safe_concat_jsonl: missing input $src" >&2
            return 1
        fi
        local n
        n=$(count_lines "$src")
        expected=$((expected + n))
        cat "$src" >> "$out"
    done
    actual=$(count_lines "$out")
    if [[ "$expected" -ne "$actual" ]]; then
        echo "ERROR: safe_concat_jsonl line-count mismatch: expected $expected, got $actual in $out" >&2
        return 1
    fi
    echo "  merged $actual lines from ${#sources[@]} file(s) into $out"
}

ensure_dir() { mkdir -p "$@"; }

find_jsonl() {
    local dir="$1" pattern="$2"
    find "$dir" -name "$pattern" -type f 2>/dev/null | head -1
}

ORDERED_STAGES=(scrape perf_filter versioning detect_specs coverage flaky_filter workload eval significance_filter pred_eval report inference)

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
    if [[ -n "$REPOS_FILE" ]]; then
        log "STAGE 1-3: Scraping PRs from repos file: $REPOS_FILE"
    else
        log "STAGE 1-3: Scraping PRs from $REPO"
    fi
    ensure_dir "$PRS_DIR" "$TASKS_DIR"

    local pulls_args=(
        --path_prs "$PRS_DIR"
        --path_tasks "$TASKS_DIR"
    )

    # Support both single --repo and --repos-file
    if [[ -n "$REPOS_FILE" ]]; then
        pulls_args+=(--repos-file "$REPOS_FILE")
    else
        pulls_args+=(--repos "$REPO")
    fi

    [[ -n "$CUTOFF_DATE" ]] && pulls_args+=(--cutoff_date "$CUTOFF_DATE")
    [[ -n "$MAX_PULLS" ]] && pulls_args+=(--max_pulls "$MAX_PULLS")

    step "Scraping PRs and building task instances..."
    run_cmd python -m swefficiency.collect.get_tasks_pipeline "${pulls_args[@]}"

    # Find task instances (may be multiple files for multi-repo)
    TASKS_FILE=$(find_jsonl "$TASKS_DIR" "*task-instances*.jsonl")
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

    # In multi-repo mode, find ALL PR files; in single-repo mode, use slug
    local prs_pattern
    if [[ "$REPO_SLUG" == "multi" ]]; then
        prs_pattern="*prs*.jsonl"
    else
        prs_pattern="${REPO_SLUG}*prs*.jsonl"
    fi

    PRS_FILE=$(find_jsonl "$PRS_DIR" "$prs_pattern")
    if [[ -z "$PRS_FILE" ]]; then
        echo "ERROR: No PRs file found in $PRS_DIR"
        exit 1
    fi

    step "Filtering for performance-related PRs..."
    # For multi-repo, process each PR file against corresponding task file
    if [[ "$REPO_SLUG" == "multi" ]]; then
        # Concatenate all task instance files into one for filtering
        local merged_tasks="$TASKS_DIR/_all_task_instances.jsonl"
        local task_files=( "$TASKS_DIR"/*task-instances*.jsonl )
        if [[ ! -e "${task_files[0]}" ]]; then
            echo "ERROR: no task-instances files in $TASKS_DIR" >&2
            exit 1
        fi
        safe_concat_jsonl "$merged_tasks" "${task_files[@]}" || exit 1
        TASKS_FILE="$merged_tasks"

        # Run filter on each PR file and merge results
        local all_prs_merged="$PRS_DIR/_all_prs.jsonl"
        local pr_files=( "$PRS_DIR"/*prs*.jsonl )
        if [[ ! -e "${pr_files[0]}" ]]; then
            echo "ERROR: no prs files in $PRS_DIR" >&2
            exit 1
        fi
        safe_concat_jsonl "$all_prs_merged" "${pr_files[@]}" || exit 1
        run_cmd python -m swefficiency.perf_filter.attributes.filter \
            --prs_path "$all_prs_merged" \
            --instances_path "$TASKS_FILE" \
            --output_dir "$FILTERED_DIR"
    else
        run_cmd python -m swefficiency.perf_filter.attributes.filter \
            --prs_path "$PRS_FILE" \
            --instances_path "$TASKS_FILE" \
            --output_dir "$FILTERED_DIR"
    fi

    FILTERED_FILE=$(find_jsonl "$FILTERED_DIR" "*attribute*.jsonl")
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
    json_file=$(find "$VERSIONED_DIR" -name "*_versions.json" -type f 2>/dev/null | head -1)
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
# STAGE 4.5: Coverage Detection (Paper Stage III)
###############################################################################
stage_coverage() {
    log "STAGE 4.5: Coverage Detection (Paper Stage III)"

    local dataset_to_use="${ENRICHED_FILE:-${VERSIONED_FILE:-$DATASET}}"
    if [[ -n "$DATASET" ]]; then
        dataset_to_use="$DATASET"
    fi

    echo "  Dataset:  $dataset_to_use ($(count_lines "$dataset_to_use") instances)"
    echo "  Workers:  $MAX_WORKERS"

    local coverage_run_id="${RUN_ID}_coverage"
    local coverage_eval_dir="$SCRIPT_DIR/logs/run_evaluation/${coverage_run_id}"

    step "Running coverage detection (Docker-based)..."
    run_cmd python swefficiency/harness/run_validation.py \
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
    run_cmd python scripts/merge_coverage.py \
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
# STAGE 4.6: Flaky Test Detection (Paper Stage V — test stability)
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
        run_cmd python swefficiency/harness/run_validation.py \
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
    run_cmd python scripts/flaky_test_filter.py \
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
    run_cmd python -m swefficiency.workload.run_synthetic_generation \
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
    run_cmd python scripts/significance_filter.py \
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
    if [[ -n "$REPOS_FILE" ]]; then
        log "SWE-fficiency Pipeline — multi-repo (from $REPOS_FILE)"
    else
        log "SWE-fficiency Pipeline — $REPO"
    fi
    echo "  Run ID:      $RUN_ID"
    echo "  Mode:        $MODE"
    echo "  Max workers: $MAX_WORKERS"
    echo "  Cutoff date: $CUTOFF_DATE"
    echo "  Platform:    $(uname -s)/$(uname -m)"
    [[ -n "$START_FROM" ]] && echo "  Start from:  $START_FROM"
    [[ -n "$STOP_AFTER" ]] && echo "  Stop after:  $STOP_AFTER"
    [[ -n "$STAGES" ]]     && echo "  Stages:      $STAGES"

    check_prereqs

    if $USE_HELICONE; then
        export ENABLE_HELICONE=1
    fi

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

    # ── Initialize intermediate variables for --start-from resume ──
    if ! should_run_stage "coverage"; then
        COVERAGE_FILTERED=$(find_jsonl "$FILTERED_DIR" "${REPO_SLUG}*coverage-filtered*.jsonl")
        [[ -n "$COVERAGE_FILTERED" ]] && ENRICHED_FILE="$COVERAGE_FILTERED"
    fi
    if ! should_run_stage "flaky_filter"; then
        FLAKY_FILTERED=$(find_jsonl "$FILTERED_DIR" "${REPO_SLUG}*flaky-filtered*.jsonl")
        [[ -n "$FLAKY_FILTERED" ]] && ENRICHED_FILE="$FLAKY_FILTERED"
    fi

    # ── Stage-gated execution ──
    should_run_stage "scrape" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_scrape
    should_run_stage "perf_filter" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_perf_filter
    should_run_stage "versioning" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_versioning
    should_run_stage "detect_specs" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_detect_specs
    should_run_stage "coverage" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_coverage
    should_run_stage "flaky_filter" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_flaky_filter

    export _ENRICHED="${ENRICHED_FILE:-}"
    export _FINAL="${FINAL_DATASET:-}"
    export _WL_OUTPUT=""

    if should_run_stage "workload" && ! $SKIP_WORKLOAD && [[ -z "$DATASET" ]]; then
        stage_workload
    else
        FINAL_DATASET="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    fi

    should_run_stage "eval" && stage_eval
    should_run_stage "significance_filter" && stage_significance_filter
    should_run_stage "pred_eval" && stage_pred_eval
    should_run_stage "report" && stage_report
    should_run_stage "inference" && stage_inference
    print_summary
}

main
