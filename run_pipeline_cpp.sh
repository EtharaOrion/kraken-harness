#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_pipeline_cpp.sh — End-to-end SWE-fficiency C++ pipeline
#
# Mirrors run_pipeline.sh (Python) but calls the *_cpp variants for stages that
# are language-sensitive (scrape, versioning, detect_specs, workload, eval,
# report). Shared stages (perf_filter, significance_filter) call the original
# language-agnostic modules.
#
# Phase 1 (this script): vertical slice on fmtlib/fmt and the 5 other Tier-1
# C++ repos. Coverage and flaky_filter are SOFT-SKIPPED (warn + continue) for
# Phase 1 — they require run_validation_cpp.py which is Phase 2. The script
# will not crash if those tools are missing.
#
# Usage:
#   ./run_pipeline_cpp.sh [OPTIONS]
#
# Options:
#   --repo OWNER/NAME       Target repo (default: fmtlib/fmt)
#   --repos-file PATH       File with C++ repos, one per line
#   --run-id NAME           Run identifier (default: auto)
#   --cutoff-date YYYYMMDD  PR cutoff date (default: 20180101)
#   --max-pulls N           Max PRs to scrape
#   --max-workers N         Parallel workers for eval (default: 1)
#   --dataset PATH          Use existing enriched JSONL (skips scrape stages)
#   --dry-run               Show what would be done
#   --multiarch             Build multiarch Docker images
#   --timeout N             Eval timeout in seconds (default: 1800)
#   --start-from STAGE      Resume from this stage
#   --stop-after STAGE      Stop after this stage
#   --stages LIST           Comma-separated stages to run
#   --flaky-runs N          Number of correctness runs (default: 10)
#   --skip-scrape           Skip stages 1-6
#   --skip-workload         Skip workload generation
#   --help                  Show this help
#
# Stages (execution order, per locked decision #1):
#   scrape, perf_filter, versioning, detect_specs, coverage, flaky_filter,
#   workload, eval, significance_filter, pred_eval, report, inference
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Defaults ────────────────────────────────────────────────────────────────
REPO="fmtlib/fmt"
REPOS_FILE=""
RUN_ID=""
CUTOFF_DATE="20180101"
MAX_PULLS=""
MAX_WORKERS=1
SKIP_SCRAPE=false
SKIP_WORKLOAD=false
DATASET=""
MODE="default"
DRY_RUN=false
MULTIARCH=false
TIMEOUT=1800
START_FROM=""
STOP_AFTER=""
STAGES=""
FLAKY_RUNS=10
DISCOVER=false
DISCOVERY_OUTPUT=""
DISCOVERY_MIN_STARS=500
DISCOVERY_MIN_PRS=100
DISCOVERY_MAX_REPOS=500

# ─── Parse args ──────────────────────────────────────────────────────────────
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
        --multiarch)    MULTIARCH=true; shift ;;
        --timeout)      TIMEOUT="$2"; shift 2 ;;
        --start-from)   START_FROM="$2"; shift 2 ;;
        --stop-after)   STOP_AFTER="$2"; shift 2 ;;
        --stages)       STAGES="$2"; shift 2 ;;
        --flaky-runs)   FLAKY_RUNS="$2"; shift 2 ;;
        --discover)     DISCOVER=true; shift ;;
        --discovery-output)    DISCOVERY_OUTPUT="$2"; shift 2 ;;
        --discovery-min-stars) DISCOVERY_MIN_STARS="$2"; shift 2 ;;
        --discovery-min-prs)   DISCOVERY_MIN_PRS="$2"; shift 2 ;;
        --discovery-max-repos) DISCOVERY_MAX_REPOS="$2"; shift 2 ;;
        --help)
            # Use sed '$d' instead of GNU 'head -n -1' for macOS BSD compatibility.
            sed -n '/^# Usage:/,/^###/p' "$0" | sed '$d'
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

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
PRS_DIR="$ARTIFACTS_DIR/pull_requests"
TASKS_DIR="$ARTIFACTS_DIR/tasks"
FILTERED_DIR="$ARTIFACTS_DIR/perf_filtered"
VERSIONED_DIR="$ARTIFACTS_DIR/versioned"
ENRICHED_DIR="$ARTIFACTS_DIR/enriched"
FINAL_DIR="$ARTIFACTS_DIR/final"
WORKLOAD_DIR="$SCRIPT_DIR/logs/workload_generation_cpp/$RUN_ID"
EVAL_DIR="$SCRIPT_DIR/logs/run_evaluation_cpp/$RUN_ID"
REPORT_DIR="$SCRIPT_DIR/eval_reports_cpp"

TASKS_FILE=""
FILTERED_FILE=""
VERSIONED_FILE=""
ENRICHED_FILE=""
FINAL_DATASET=""
COVERAGE_FILTERED=""
FLAKY_FILTERED=""

# ─── Load .env ───────────────────────────────────────────────────────────────
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# ─── Raise FD limit ──────────────────────────────────────────────────────────
raise_fd_limit() {
    local target="${SWEFF_MIN_FDS:-4096}"
    local current
    current=$(ulimit -n 2>/dev/null || echo 0)
    # macOS reports 'unlimited' for very high soft limits; normalize to a huge
    # int so the >= comparison below evaluates correctly under `set -u`.
    if [[ "$current" == "unlimited" ]]; then
        current=9999999
    fi
    [[ "$current" =~ ^[0-9]+$ ]] || current=0
    if [[ "$current" -ge "$target" ]]; then
        echo "FD limit: $current (>= $target, ok)"
        return 0
    fi
    if ulimit -n "$target" 2>/dev/null; then
        echo "FD limit: raised from $current to $(ulimit -n)"
        return 0
    fi
    local hard
    hard=$(ulimit -Hn 2>/dev/null || echo 0)
    if [[ "$hard" == "unlimited" ]]; then
        hard=9999999
    fi
    [[ "$hard" =~ ^[0-9]+$ ]] || hard=0
    if [[ "$hard" -gt "$current" ]] && ulimit -n "$hard" 2>/dev/null; then
        echo "FD limit: raised from $current to $hard (capped by hard limit)"
        return 0
    fi
    echo "WARNING: FD limit is $current (< $target). Long runs may exhaust FDs." >&2
    return 0
}

# ─── Helpers ─────────────────────────────────────────────────────────────────
log()  { echo -e "\n══════════════════════════════════════════════════════════"; echo "  $1"; echo "══════════════════════════════════════════════════════════"; }
step() { echo -e "\n── $1 ──"; }

STAGE_TIMEOUT="${SWEFF_STAGE_TIMEOUT:-28800}"
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
if [[ -z "$TIMEOUT_BIN" ]]; then
    echo "WARNING: 'timeout' not found; stages will NOT be bounded." >&2
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
        echo "ERROR: safe_concat_jsonl line-count mismatch: $expected vs $actual in $out" >&2
        return 1
    fi
    echo "  merged $actual lines from ${#sources[@]} file(s) into $out"
}

ensure_dir() { mkdir -p "$@"; }

find_jsonl() {
    local dir="$1" pattern="$2"
    find "$dir" -name "$pattern" -type f 2>/dev/null | head -1
}

# ─── Stage gating ────────────────────────────────────────────────────────────
ORDERED_STAGES_CPP=(discover scrape perf_filter versioning detect_specs coverage flaky_filter workload eval significance_filter pred_eval report inference)

validate_stage_name() {
    local name="$1"
    for s in "${ORDERED_STAGES_CPP[@]}"; do
        [[ "$s" == "$name" ]] && return 0
    done
    echo "ERROR: Unknown stage '$name'. Valid: ${ORDERED_STAGES_CPP[*]}"
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
        for _s in "${ORDERED_STAGES_CPP[@]}"; do
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

# ─── Prereqs (C++-aware) ─────────────────────────────────────────────────────
check_prereqs() {
    local missing=()
    command -v python3 >/dev/null 2>&1 || missing+=("python3")
    command -v docker  >/dev/null 2>&1 || missing+=("docker")
    command -v git     >/dev/null 2>&1 || missing+=("git")

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "ERROR: Missing required tools: ${missing[*]}"
        exit 1
    fi

    if should_run_stage "eval" || should_run_stage "pred_eval"; then
        if ! docker info >/dev/null 2>&1; then
            echo "ERROR: Docker daemon not running."
            exit 1
        fi
    fi

    if [[ -z "${GITHUB_TOKENS:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
        echo "WARNING: GITHUB_TOKENS/GITHUB_TOKEN not set. Scraping will fail."
    fi

    python3 -c "import swefficiency" 2>/dev/null || {
        echo "ERROR: swefficiency not installed. Run: pip install -e ."
        exit 1
    }

    # Soft check: C++ build prereqs (do not fail — base Docker image carries them)
    local cpp_missing=()
    for tool in g++ cmake ninja ccache gcov lcov gcovr; do
        command -v "$tool" >/dev/null 2>&1 || cpp_missing+=("$tool")
    done
    if [[ ${#cpp_missing[@]} -gt 0 ]]; then
        echo "INFO: Host missing C++ tools (${cpp_missing[*]}); Docker base image will provide them."
    fi
}

###############################################################################
# STAGE 0: Discover C++ repos from GitHub (license-filtered, no hardcoded set)
###############################################################################
stage_discover() {
    log "STAGE 0: Discovering open-source C++ repos from GitHub"

    if [[ -z "${GITHUB_TOKEN:-}${GITHUB_TOKENS:-}" ]]; then
        echo "ERROR: discover stage needs GITHUB_TOKEN or GITHUB_TOKENS."
        exit 1
    fi

    ensure_dir "$ARTIFACTS_DIR"
    if [[ -z "$DISCOVERY_OUTPUT" ]]; then
        DISCOVERY_OUTPUT="$ARTIFACTS_DIR/discovered_cpp_repos.txt"
    fi

    step "Searching GitHub for C++ repos with allowed licenses..."
    echo "  Licenses:  MIT, MIT-0, Apache-2.0, BSD-3-Clause, BSD-2-Clause, ISC"
    echo "  Filters:   stars >= $DISCOVERY_MIN_STARS, PRs >= $DISCOVERY_MIN_PRS, max=$DISCOVERY_MAX_REPOS"
    echo "  Output:    $DISCOVERY_OUTPUT"

    run_cmd python3 -m swefficiency.collect.discover_repos_cpp \
        --output "$DISCOVERY_OUTPUT" \
        --format simple \
        --min-stars "$DISCOVERY_MIN_STARS" \
        --min-prs "$DISCOVERY_MIN_PRS" \
        --max-repos "$DISCOVERY_MAX_REPOS"

    if [[ ! -f "$DISCOVERY_OUTPUT" ]]; then
        echo "ERROR: discover_repos_cpp produced no output at $DISCOVERY_OUTPUT"
        exit 1
    fi

    # Use awk to count non-comment, non-blank lines without shell-quoting hazards.
    local n
    n=$(awk 'NF && !/^#/' "$DISCOVERY_OUTPUT" | wc -l | tr -d ' ')
    echo "  -> discovered $n repos"

    # Auto-wire downstream stages to use this repos file.
    REPOS_FILE="$DISCOVERY_OUTPUT"
    REPO_SLUG="multi"
    REPO_OWNER="multi"
    echo "  -> REPOS_FILE auto-set to discovered list for subsequent stages"
}

###############################################################################
# STAGE 1-3: Scrape + Build Dataset (C++)
###############################################################################
stage_scrape() {
    if [[ -n "$REPOS_FILE" ]]; then
        log "STAGE 1-3: Scraping PRs (cpp) from $REPOS_FILE"
    else
        log "STAGE 1-3: Scraping PRs (cpp) from $REPO"
    fi
    ensure_dir "$PRS_DIR" "$TASKS_DIR"

    local pulls_args=(
        --path_prs "$PRS_DIR"
        --path_tasks "$TASKS_DIR"
    )
    if [[ -n "$REPOS_FILE" ]]; then
        pulls_args+=(--repos-file "$REPOS_FILE")
    else
        pulls_args+=(--repos "$REPO")
    fi
    [[ -n "$CUTOFF_DATE" ]] && pulls_args+=(--cutoff_date "$CUTOFF_DATE")
    [[ -n "$MAX_PULLS"   ]] && pulls_args+=(--max_pulls   "$MAX_PULLS")

    step "Scraping with get_tasks_pipeline_cpp..."
    run_cmd python3 -m swefficiency.collect.get_tasks_pipeline_cpp "${pulls_args[@]}"

    TASKS_FILE=$(find_jsonl "$TASKS_DIR" "*task-instances*.jsonl")
    if [[ -z "$TASKS_FILE" ]]; then
        echo "ERROR: No task instances file found in $TASKS_DIR"
        exit 1
    fi
    echo "  → $(count_lines "$TASKS_FILE") task instances"
}

###############################################################################
# STAGE 4: Performance Filter (shared with Python — language-agnostic)
###############################################################################
stage_perf_filter() {
    log "STAGE 4: Performance filtering (shared module)"
    ensure_dir "$FILTERED_DIR"

    local prs_pattern
    if [[ "$REPO_SLUG" == "multi" ]]; then
        prs_pattern="*prs*.jsonl"
    else
        prs_pattern="${REPO_SLUG}*prs*.jsonl"
    fi
    PRS_FILE=$(find_jsonl "$PRS_DIR" "$prs_pattern")
    if [[ -z "$PRS_FILE" ]]; then
        echo "ERROR: No PRs file in $PRS_DIR"
        exit 1
    fi

    if [[ "$REPO_SLUG" == "multi" ]]; then
        local merged_tasks="$TASKS_DIR/_all_task_instances.jsonl"
        local task_files=( "$TASKS_DIR"/*task-instances*.jsonl )
        [[ ! -e "${task_files[0]}" ]] && { echo "ERROR: no task-instances files"; exit 1; }
        safe_concat_jsonl "$merged_tasks" "${task_files[@]}" || exit 1
        TASKS_FILE="$merged_tasks"

        local all_prs="$PRS_DIR/_all_prs.jsonl"
        local pr_files=( "$PRS_DIR"/*prs*.jsonl )
        [[ ! -e "${pr_files[0]}" ]] && { echo "ERROR: no prs files"; exit 1; }
        safe_concat_jsonl "$all_prs" "${pr_files[@]}" || exit 1
        run_cmd python3 -m swefficiency.perf_filter.attributes.filter \
            --prs_path "$all_prs" \
            --instances_path "$TASKS_FILE" \
            --output_dir "$FILTERED_DIR"
    else
        run_cmd python3 -m swefficiency.perf_filter.attributes.filter \
            --prs_path "$PRS_FILE" \
            --instances_path "$TASKS_FILE" \
            --output_dir "$FILTERED_DIR"
    fi

    FILTERED_FILE=$(find_jsonl "$FILTERED_DIR" "*attribute*.jsonl")
    if [[ -z "$FILTERED_FILE" ]]; then
        echo "WARNING: No filtered instances. Using unfiltered."
        FILTERED_FILE="$TASKS_FILE"
    fi
    local n
    n=$(count_lines "$FILTERED_FILE")
    echo "  → $n instances after perf filter"
    [[ "$n" -eq 0 ]] && { echo "ERROR: 0 instances after perf filter."; exit 1; }
}

###############################################################################
# STAGE 5: Versioning (C++)
###############################################################################
stage_versioning() {
    log "STAGE 5: Versioning (cpp)"
    ensure_dir "$VERSIONED_DIR"

    step "Detecting versions via get_versions_cpp..."
    run_cmd python3 -m swefficiency.versioning.get_versions_cpp \
        --instances_path "$FILTERED_FILE" \
        --retrieval_method github \
        --num_workers 4 \
        --output_dir "$VERSIONED_DIR"

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
    print(f'  → {len([d for d in data if d.get(\"version\")])} versioned instances')
else:
    print('  WARNING: unexpected JSON shape')
"
    fi

    if [[ ! -f "$VERSIONED_FILE" ]] || [[ $(count_lines "$VERSIONED_FILE") -eq 0 ]]; then
        echo "WARNING: No versioned instances. Falling back to filtered file."
        VERSIONED_FILE="$FILTERED_FILE"
    else
        echo "  → $(count_lines "$VERSIONED_FILE") versioned instances"
    fi
}

###############################################################################
# STAGE 6: Auto-detect Repo Specs (C++)
###############################################################################
stage_detect_specs() {
    log "STAGE 6: Auto-detecting cpp repo specs"
    ensure_dir "$ENRICHED_DIR"
    ENRICHED_FILE="$ENRICHED_DIR/${REPO_SLUG}_enriched.jsonl"

    step "Detecting build system, cmake version, system pkgs, deps..."
    run_cmd python3 scripts/detect_repo_specs_cpp.py \
        --input "$VERSIONED_FILE" \
        --output "$ENRICHED_FILE" \
        --workers 4 \
        --verbose

    if [[ -f "$ENRICHED_FILE" ]]; then
        echo "  → $(count_lines "$ENRICHED_FILE") enriched instances"
    else
        echo "WARNING: enrichment failed; using versioned file."
        ENRICHED_FILE="$VERSIONED_FILE"
    fi
}

###############################################################################
# STAGE 4.5: Coverage Detection — Phase 1 stub
#   Locked decision #7: coverage MAY stub for Phase 1; eval MUST grade.
###############################################################################
stage_coverage() {
    log "STAGE 4.5: Coverage Detection (cpp) — Phase 1 stub"
    echo "  Coverage requires run_validation_cpp.py (Phase 2). Skipping."
    echo "  Dataset passes through unchanged."
    return 0
}

###############################################################################
# STAGE 4.6: Flaky Test Detection — Phase 1 stub
#   Locked decision #7: coverage and flaky MAY stub for Phase 1.
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
# STAGE 8: Docker Build + Gold Evaluation (C++)
###############################################################################
stage_eval() {
    log "STAGE 8: Build cpp images + Gold Evaluation"

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    [[ -n "$DATASET" ]] && dataset_to_use="$DATASET"

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

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    [[ -n "$DATASET" ]] && dataset_to_use="$DATASET"

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

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    [[ -n "$DATASET" ]] && dataset_to_use="$DATASET"

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

    local dataset_to_use="${FINAL_DATASET:-${ENRICHED_FILE:-$DATASET}}"
    [[ -n "$DATASET" ]] && dataset_to_use="$DATASET"

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
# Summary
###############################################################################
print_summary() {
    log "C++ Pipeline Complete!"
    echo ""
    echo "  Run ID:        $RUN_ID"
    echo "  Repo:          $REPO"
    echo "  Platform:      $(uname -s)/$(uname -m)"
    echo "  Artifacts:     $ARTIFACTS_DIR"
    echo "  Eval output:   $EVAL_DIR"
    echo "  Reports:       $REPORT_DIR"
    echo ""
}

###############################################################################
# MAIN
###############################################################################
main() {
    if [[ -n "$REPOS_FILE" ]]; then
        log "SWE-fficiency C++ Pipeline — multi-repo (from $REPOS_FILE)"
    else
        log "SWE-fficiency C++ Pipeline — $REPO"
    fi
    echo "  Run ID:      $RUN_ID"
    echo "  Max workers: $MAX_WORKERS"
    echo "  Platform:    $(uname -s)/$(uname -m)"
    [[ -n "$START_FROM" ]] && echo "  Start from:  $START_FROM"
    [[ -n "$STOP_AFTER" ]] && echo "  Stop after:  $STOP_AFTER"
    [[ -n "$STAGES"     ]] && echo "  Stages:      $STAGES"

    raise_fd_limit
    check_prereqs

    # ── --discover convenience: opt-in shortcut to run STAGE 0 first ──
    if $DISCOVER && [[ -z "$STAGES" && -z "$START_FROM" ]]; then
        START_FROM="discover"
    fi

    # ── Auto-discover intermediate files for resume ──
    if [[ -n "$DATASET" ]]; then
        echo "  Using provided dataset: $DATASET"
        ENRICHED_FILE="$DATASET"
        FINAL_DATASET="$DATASET"
    elif should_run_stage "scrape" && ! $SKIP_SCRAPE; then
        : # set by stage_scrape
    else
        if $SKIP_SCRAPE; then
            echo "  Skipping scrape stages (--skip-scrape)."
        fi
        ENRICHED_FILE=$(find_jsonl "$ENRICHED_DIR" "${REPO_SLUG}*.jsonl")
        FINAL_DATASET=$(find_jsonl "$FINAL_DIR" "${REPO_SLUG}*dataset*.jsonl")
        [[ -z "$ENRICHED_FILE" && -z "$FINAL_DATASET" ]] && { echo "ERROR: no dataset found. Use --dataset."; exit 1; }
        [[ -z "$FINAL_DATASET" ]] && FINAL_DATASET="$ENRICHED_FILE"
    fi

    # ── Stage-gated execution ──
    should_run_stage "discover" && [[ -z "$DATASET" ]] && stage_discover
    should_run_stage "scrape" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_scrape
    should_run_stage "perf_filter" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_perf_filter
    should_run_stage "versioning" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_versioning
    should_run_stage "detect_specs" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_detect_specs
    should_run_stage "coverage" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_coverage
    should_run_stage "flaky_filter" && ! $SKIP_SCRAPE && [[ -z "$DATASET" ]] && stage_flaky_filter

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
