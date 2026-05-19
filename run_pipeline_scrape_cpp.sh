#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_pipeline_scrape_cpp.sh — Phase 1 (C++): discovery + scraping → enriched.
#
# Stages: discover, scrape, perf_filter, versioning, detect_specs.
# Credentials: GITHUB_TOKENS / GITHUB_TOKEN (no Docker, no AWS).
# Output:  artifacts_cpp/enriched/<slug>_enriched.jsonl
#          → feed into run_pipeline_dataset_cpp.sh via --dataset
#
# Usage:
#   ./run_pipeline_scrape_cpp.sh [OPTIONS]
#
# Options:
#   --repo OWNER/NAME       Single target repo (default: fmtlib/fmt)
#   --repos-file PATH       File with C++ repos, one owner/repo per line
#   --repos-json PATH       JSON file: array of strings, array of objects with
#                           a "full_name" key, or {"repos": [...]}
#   --run-id NAME           Run identifier (default: auto)
#   --cutoff-date YYYYMMDD  PR cutoff date (default: 20180101)
#   --max-pulls N           Max PRs to scrape
#   --discover              Run STAGE 0 (GitHub C++ repo discovery) first
#   --discovery-output PATH Output path for discovered repos list
#   --discovery-min-stars N Discovery: minimum stars (default: 500)
#   --discovery-min-prs N   Discovery: minimum merged PRs (default: 100)
#   --discovery-max-repos N Discovery: cap on discovered repos (default: 500)
#   --dry-run               Show what would be done
#   --start-from STAGE      Resume from this stage
#   --stop-after STAGE      Stop after this stage
#   --stages LIST           Comma-separated stages to run
#   --help                  Show this help
#
# Stages (execution order): discover, scrape, perf_filter, versioning, detect_specs
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/pipeline_lib_cpp.sh"

# ─── Defaults ────────────────────────────────────────────────────────────────
REPO="fmtlib/fmt"
REPOS_FILE=""
REPOS_JSON=""
RUN_ID=""
CUTOFF_DATE="20180101"
MAX_PULLS=""
DRY_RUN=false
START_FROM=""
STOP_AFTER=""
STAGES=""
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
        --repos-json)   REPOS_JSON="$2"; shift 2 ;;
        --run-id)       RUN_ID="$2"; shift 2 ;;
        --cutoff-date)  CUTOFF_DATE="$2"; shift 2 ;;
        --max-pulls)    MAX_PULLS="$2"; shift 2 ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --start-from)   START_FROM="$2"; shift 2 ;;
        --stop-after)   STOP_AFTER="$2"; shift 2 ;;
        --stages)       STAGES="$2"; shift 2 ;;
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
if [[ -n "$REPOS_FILE" || -n "$REPOS_JSON" ]]; then
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

TASKS_FILE=""
FILTERED_FILE=""
VERSIONED_FILE=""
ENRICHED_FILE=""

# print_summary references these; the scrape phase has no eval/report output.
EVAL_DIR=""
REPORT_DIR=""

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
# STAGE 0: Discover C++ repos from GitHub (license-filtered, no hardcoded set)
###############################################################################
stage_discover() {
    if [[ -n "$REPOS_FILE" || -n "$REPOS_JSON" ]]; then
        log "STAGE 0: discovery skipped - repos file/json supplied explicitly"
        return 0
    fi
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
    if [[ -n "$REPOS_JSON" ]]; then
        log "STAGE 1-3: Scraping PRs (cpp) from $REPOS_JSON"
    elif [[ -n "$REPOS_FILE" ]]; then
        log "STAGE 1-3: Scraping PRs (cpp) from $REPOS_FILE"
    else
        log "STAGE 1-3: Scraping PRs (cpp) from $REPO"
    fi
    ensure_dir "$PRS_DIR" "$TASKS_DIR"

    local pulls_args=(
        --path_prs "$PRS_DIR"
        --path_tasks "$TASKS_DIR"
    )
    if [[ -n "$REPOS_JSON" ]]; then
        pulls_args+=(--repos-json "$REPOS_JSON")
    elif [[ -n "$REPOS_FILE" ]]; then
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
    # Version is best-effort metadata, never a gate: a repo whose version
    # cannot be parsed must still flow downstream (base_commit, not version,
    # determines the build).
    with open('$VERSIONED_FILE', 'w') as out:
        for item in data:
            out.write(json.dumps(item) + '\n')
    _v = len([d for d in data if d.get('version')])
    print(f'  → {len(data)} instances ({_v} with a detected version)')
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
# MAIN
###############################################################################
main() {
    if [[ -n "$REPOS_JSON" ]]; then
        log "SWE-fficiency C++ Pipeline [SCRAPE] — multi-repo (from $REPOS_JSON)"
    elif [[ -n "$REPOS_FILE" ]]; then
        log "SWE-fficiency C++ Pipeline [SCRAPE] — multi-repo (from $REPOS_FILE)"
    else
        log "SWE-fficiency C++ Pipeline [SCRAPE] — $REPO"
    fi
    echo "  Run ID:      $RUN_ID"
    echo "  Cutoff date: $CUTOFF_DATE"
    echo "  Platform:    $(uname -s)/$(uname -m)"
    [[ -n "$START_FROM" ]] && echo "  Start from:  $START_FROM"
    [[ -n "$STOP_AFTER" ]] && echo "  Stop after:  $STOP_AFTER"
    [[ -n "$STAGES"     ]] && echo "  Stages:      $STAGES"

    raise_fd_limit
    PIPELINE_NEEDS_DOCKER=false
    PIPELINE_NEEDS_GITHUB=true
    check_prereqs

    # ── --discover convenience: opt-in shortcut to run STAGE 0 first ──
    if $DISCOVER && [[ -z "$STAGES" && -z "$START_FROM" ]]; then
        START_FROM="discover"
    fi

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
    should_run_stage "discover"     && stage_discover
    should_run_stage "scrape"       && stage_scrape
    should_run_stage "perf_filter"  && stage_perf_filter
    should_run_stage "versioning"   && stage_versioning
    should_run_stage "detect_specs" && stage_detect_specs

    if [[ -n "$ENRICHED_FILE" ]]; then
        echo ""
        echo "  Enriched dataset: $ENRICHED_FILE"
        echo "  → Next: ./run_pipeline_dataset_cpp.sh --dataset \"$ENRICHED_FILE\" [--run-id $RUN_ID ...]"
    fi
    print_summary
}

main
