#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_pipeline_scrape.sh — Phase 1: Repo scraping → enriched dataset.
#
# Stages: scrape, perf_filter, versioning, detect_specs.
# Credentials: GITHUB_TOKENS / GITHUB_TOKEN (no Docker, no AWS).
# Output:  artifacts/enriched/<slug>_enriched.jsonl
#          → feed into run_pipeline_dataset.sh via --dataset
#
# Usage:
#   ./run_pipeline_scrape.sh [OPTIONS]
#
# Options:
#   --repo OWNER/NAME       Single target repo (default: psf/requests)
#   --repos-file PATH       File with repos, one owner/repo per line
#   --repos-json PATH       JSON file: array of strings, array of objects with
#                           a "full_name" key, or {"repos": [...]}
#   --run-id NAME           Run identifier (default: auto-generated timestamp)
#   --cutoff-date YYYYMMDD  PR cutoff date (default: 20180101)
#   --max-pulls N           Max PRs to scrape (default: unlimited)
#   --filter-early          Apply perf filter at Stage I
#   --dry-run               Show what would be done without executing
#   --start-from STAGE      Start from this stage, skip all prior stages
#   --stop-after STAGE      Stop after this stage, skip all later stages
#   --stages LIST           Comma-separated list of stages to run
#   --help                  Show this help
#
# Stages (in execution order): scrape, perf_filter, versioning, detect_specs
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/pipeline_lib.sh"

# ─── Defaults ─────────────────────────────────────────────────────────────────
REPO="psf/requests"
REPOS_FILE=""
REPOS_JSON=""
FILTER_EARLY=false
RUN_ID=""
CUTOFF_DATE="20180101"
MAX_PULLS=""
DRY_RUN=false
START_FROM=""
STOP_AFTER=""
STAGES=""

# ─── Parse args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --repo)         REPO="$2"; shift 2 ;;
        --repos-file)   REPOS_FILE="$2"; shift 2 ;;
        --repos-json)   REPOS_JSON="$2"; shift 2 ;;
        --run-id)       RUN_ID="$2"; shift 2 ;;
        --cutoff-date)  CUTOFF_DATE="$2"; shift 2 ;;
        --max-pulls)    MAX_PULLS="$2"; shift 2 ;;
        --filter-early) FILTER_EARLY=true; shift ;;
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

# ─── Derived values ───────────────────────────────────────────────────────────
if [[ -n "$REPOS_FILE" || -n "$REPOS_JSON" ]]; then
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

TASKS_FILE=""
FILTERED_FILE=""
VERSIONED_FILE=""
ENRICHED_FILE=""

# print_summary (in pipeline_lib.sh) references these; the scrape phase has no
# eval/report output, so they stay empty and are skipped in the summary.
EVAL_DIR=""
REPORT_DIR=""

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
# STAGE 1-3: Scrape PRs + Build Dataset
###############################################################################
stage_scrape() {
    if [[ -n "$REPOS_JSON" ]]; then
        log "STAGE 1-3: Scraping PRs from repos JSON: $REPOS_JSON"
    elif [[ -n "$REPOS_FILE" ]]; then
        log "STAGE 1-3: Scraping PRs from repos file: $REPOS_FILE"
    else
        log "STAGE 1-3: Scraping PRs from $REPO"
    fi
    ensure_dir "$PRS_DIR" "$TASKS_DIR"

    local pulls_args=(
        --path_prs "$PRS_DIR"
        --path_tasks "$TASKS_DIR"
    )

    # Repo source: --repos-json, --repos-file, or single --repo
    if [[ -n "$REPOS_JSON" ]]; then
        pulls_args+=(--repos-json "$REPOS_JSON")
    elif [[ -n "$REPOS_FILE" ]]; then
        pulls_args+=(--repos-file "$REPOS_FILE")
    else
        pulls_args+=(--repos "$REPO")
    fi

    [[ -n "$CUTOFF_DATE" ]] && pulls_args+=(--cutoff_date "$CUTOFF_DATE")
    [[ -n "$MAX_PULLS" ]] && pulls_args+=(--max_pulls "$MAX_PULLS")

    step "Scraping PRs and building task instances..."
    run_cmd python3 -m swefficiency.collect.get_tasks_pipeline "${pulls_args[@]}"

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
        run_cmd python3 -m swefficiency.perf_filter.attributes.filter \
            --prs_path "$all_prs_merged" \
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
    run_cmd python3 -m swefficiency.versioning.get_versions \
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
    run_cmd python3 scripts/detect_repo_specs.py \
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
# MAIN
###############################################################################
main() {
    if [[ -n "$REPOS_JSON" ]]; then
        log "SWE-fficiency Pipeline [SCRAPE] — multi-repo (from $REPOS_JSON)"
    elif [[ -n "$REPOS_FILE" ]]; then
        log "SWE-fficiency Pipeline [SCRAPE] — multi-repo (from $REPOS_FILE)"
    else
        log "SWE-fficiency Pipeline [SCRAPE] — $REPO"
    fi
    echo "  Run ID:      $RUN_ID"
    echo "  Cutoff date: $CUTOFF_DATE"
    echo "  Platform:    $(uname -s)/$(uname -m)"
    [[ -n "$START_FROM" ]] && echo "  Start from:  $START_FROM"
    [[ -n "$STOP_AFTER" ]] && echo "  Stop after:  $STOP_AFTER"
    [[ -n "$STAGES" ]]     && echo "  Stages:      $STAGES"

    raise_fd_limit
    PIPELINE_NEEDS_DOCKER=false
    PIPELINE_NEEDS_GITHUB=true
    check_prereqs

    # ── Resume discovery: locate intermediate files from a prior run ──
    if ! should_run_stage "scrape"; then
        TASKS_FILE=$(find_jsonl "$TASKS_DIR" "*task-instances*.jsonl")
    fi
    if ! should_run_stage "perf_filter"; then
        FILTERED_FILE=$(find_jsonl "$FILTERED_DIR" "*attribute*.jsonl")
        [[ -z "$FILTERED_FILE" ]] && FILTERED_FILE="$TASKS_FILE"
    fi
    if ! should_run_stage "versioning"; then
        VERSIONED_FILE=$(find_jsonl "$VERSIONED_DIR" "${REPO_SLUG}*versioned*.jsonl")
        [[ -z "$VERSIONED_FILE" ]] && VERSIONED_FILE="$FILTERED_FILE"
    fi

    # ── Stage-gated execution ──
    should_run_stage "scrape"       && stage_scrape
    should_run_stage "perf_filter"  && stage_perf_filter
    should_run_stage "versioning"   && stage_versioning
    should_run_stage "detect_specs" && stage_detect_specs

    if [[ -n "$ENRICHED_FILE" ]]; then
        echo ""
        echo "  Enriched dataset: $ENRICHED_FILE"
        echo "  → Next: ./run_pipeline_dataset.sh --dataset \"$ENRICHED_FILE\" [--run-id $RUN_ID ...]"
    fi
    print_summary
}

main
