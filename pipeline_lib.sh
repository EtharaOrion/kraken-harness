#!/usr/bin/env bash
###############################################################################
# pipeline_lib.sh — Shared helpers for the split SWE-fficiency pipeline.
#
# Sourced by run_pipeline_scrape.sh, run_pipeline_dataset.sh and
# run_pipeline_eval.sh. Not meant to be executed directly.
#
# Consumers must define these globals before calling functions that use them
# (bash resolves globals at call time, not source time):
#   DRY_RUN                          — run_cmd
#   STAGES START_FROM STOP_AFTER     — should_run_stage / validate_stage_name
#   RUN_ID REPO                      — print_summary
#   ARTIFACTS_DIR EVAL_DIR REPORT_DIR (optional) — print_summary
#   PIPELINE_NEEDS_DOCKER PIPELINE_NEEDS_GITHUB (optional) — check_prereqs
###############################################################################

# Guard against double-sourcing.
[[ -n "${_PIPELINE_LIB_SOURCED:-}" ]] && return 0
_PIPELINE_LIB_SOURCED=1

# ─── Raise FD limit ──────────────────────────────────────────────────────────
# Long-running pipelines open many sockets (HTTP) + files concurrently. Default
# macOS/Linux soft limit is often 1024, too low for parallel Docker builds +
# LLM HTTP pools. Raise to SWEFF_MIN_FDS (default 4096); warn if we can't.
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
    echo "  Raise with: ulimit -n $target" >&2
    echo "  On macOS:   sudo launchctl limit maxfiles $target $target" >&2
    return 0
}

# ─── Logging ─────────────────────────────────────────────────────────────────
log() { echo -e "\n══════════════════════════════════════════════════════════"; echo "  $1"; echo "══════════════════════════════════════════════════════════"; }
step() { echo -e "\n── $1 ──"; }

# ─── Per-stage hard timeout ──────────────────────────────────────────────────
# Default 8h. Override via SWEFF_STAGE_TIMEOUT. A hang in any stage blocks the
# whole pipeline, so every python subprocess is wrapped with `timeout`.
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

# ─── JSONL helpers ───────────────────────────────────────────────────────────
count_lines() { wc -l < "$1" | tr -d ' '; }

# Concatenate JSONL files with strict line-count validation. Aborts on mismatch.
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

# ─── Stage ordering + resume gating ──────────────────────────────────────────
# Full canonical stage order across all three phase scripts. Each phase script
# only invokes its own subset, but the global order keeps --start-from /
# --stop-after semantics consistent across phase boundaries.
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

# ─── Validate prerequisites ──────────────────────────────────────────────────
# Phase scripts set PIPELINE_NEEDS_DOCKER / PIPELINE_NEEDS_GITHUB to declare
# which daemons/credentials their stages require.
check_prereqs() {
    local missing=()
    command -v python3 >/dev/null 2>&1 || missing+=("python3")
    command -v git >/dev/null 2>&1    || missing+=("git")
    if [[ "${PIPELINE_NEEDS_DOCKER:-false}" == "true" ]]; then
        command -v docker >/dev/null 2>&1 || missing+=("docker")
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "ERROR: Missing required tools: ${missing[*]}"
        exit 1
    fi

    if [[ "${PIPELINE_NEEDS_DOCKER:-false}" == "true" ]]; then
        if ! docker info >/dev/null 2>&1; then
            echo "ERROR: Docker daemon not running. Start Docker Desktop first."
            exit 1
        fi
    fi

    if [[ "${PIPELINE_NEEDS_GITHUB:-false}" == "true" ]]; then
        if [[ -z "${GITHUB_TOKENS:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
            echo "WARNING: GITHUB_TOKENS or GITHUB_TOKEN not set. Scraping will fail."
        fi
    fi

    python3 -c "import swefficiency" 2>/dev/null || {
        echo "ERROR: swefficiency not installed. Run: pip install -e ."
        exit 1
    }
}

# ─── .env loading ────────────────────────────────────────────────────────────
load_env() {
    local dir="$1"
    if [[ -f "$dir/.env" ]]; then
        # An explicitly-exported GITHUB_TOKENS/GITHUB_TOKEN wins over a stale
        # value in .env: at scale tokens come from tokens.txt, not .env.
        local _keep_tokens="${GITHUB_TOKENS:-}" _keep_token="${GITHUB_TOKEN:-}"
        set -a
        source "$dir/.env"
        set +a
        [[ -n "$_keep_tokens" ]] && export GITHUB_TOKENS="$_keep_tokens"
        [[ -n "$_keep_token" ]] && export GITHUB_TOKEN="$_keep_token"
    fi
}

# ─── Final summary ───────────────────────────────────────────────────────────
print_summary() {
    log "Pipeline Phase Complete!"
    echo ""
    echo "  Run ID:         ${RUN_ID:-N/A}"
    echo "  Repo:           ${REPO:-N/A}"
    echo "  Platform:       $(uname -s)/$(uname -m)"
    echo ""
    [[ -n "${ARTIFACTS_DIR:-}" ]] && echo "  Artifacts:      $ARTIFACTS_DIR"
    [[ -n "${EVAL_DIR:-}" ]]      && echo "  Eval output:    $EVAL_DIR"
    [[ -n "${REPORT_DIR:-}" ]]    && echo "  Reports:        $REPORT_DIR"
    echo ""

    if [[ -n "${REPORT_DIR:-}" && -f "$REPORT_DIR/eval_report_gold_as_pred.json" ]]; then
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
    echo "  Done."
    echo "  ═══════════════════════════════════════"
}
