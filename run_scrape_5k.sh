#!/usr/bin/env bash
#
# run_scrape_5k.sh - Discover + scrape ~5000 repos (Python + C++) for the
# SWE-fficiency dataset, producing everything the downstream workload-gen /
# docker-build / final-dataset stages consume.
#
# THIS IS A MULTI-DAY OPERATION. It must be launched detached so it survives
# terminal/session loss:
#
#     nohup ./run_scrape_5k.sh > scrape_5k.log 2>&1 &
#     tail -f scrape_5k.log          # monitor
#
# Token rotation: the 9 PATs in tokens.txt are comma-joined into GITHUB_TOKENS.
# get_tasks_pipeline partitions them into disjoint subsets (3x3); each worker
# process owns a private _TokenRotator that rotates on HTTP 403 and cools a
# rate-limited token until its X-RateLimit-Reset (no more 1-hour hangs).
#
# Resumable: completed_repos.txt ledgers under artifacts/tasks and
# artifacts_cpp/tasks let a re-run skip already-scraped repos with 0 API calls.
#
set -uo pipefail
cd "$(dirname "$0")"

# Idempotent completion guard: a finished run drops .scrape_5k_done. The
# launchd supervisor re-runs this script at every login/reboot, so without
# this guard a completed scrape would pointlessly re-run discovery. Delete
# .scrape_5k_done to force a fresh full run.
if [[ -f .scrape_5k_done ]]; then
    echo "[$(date)] .scrape_5k_done present -- scrape already completed; exiting."
    exit 0
fi

TOKENS_FILE="${TOKENS_FILE:-tokens.txt}"
PY_REPOS="${PY_REPOS:-2500}"
CPP_REPOS="${CPP_REPOS:-2500}"
# Star floor for discovery. At stars>=1000 GitHub has only ~950 qualifying
# Python repos, so reaching ~5k needs a lower floor; --min-prs (200) remains
# the real quality gate. Override via MIN_STARS=... if desired.
MIN_STARS="${MIN_STARS:-100}"

if [[ ! -f "$TOKENS_FILE" ]]; then
    echo "ERROR: token file not found: $TOKENS_FILE" >&2
    exit 1
fi

# Comma-join non-blank token lines. GITHUB_TOKENS is what the pipeline reads;
# GITHUB_TOKEN (single) is a fallback for tools that want one token.
GITHUB_TOKENS="$(grep -v '^[[:space:]]*$' "$TOKENS_FILE" | paste -sd, -)"
export GITHUB_TOKENS
export GITHUB_TOKEN="${GITHUB_TOKENS%%,*}"
N_TOKENS="$(grep -cv '^[[:space:]]*$' "$TOKENS_FILE")"
if [[ -z "$GITHUB_TOKENS" ]]; then
    echo "ERROR: no tokens parsed from $TOKENS_FILE" >&2
    exit 1
fi
echo "[$(date)] Loaded ${N_TOKENS} GitHub token(s)."

# A 5000-repo scrape is millions of API calls -- realistically 1-5 weeks of
# wall-clock. get_tasks_pipeline bounds the whole run with SWEFF_CHUNK_TIMEOUT_S
# (default 14400s = 4h), which would DLQ every still-running chunk as "stuck".
# Raise it to 45 days so a single invocation can finish even the worst case.
# (The run is also resumable via completed_repos.txt if it is ever re-launched.)
export SWEFF_CHUNK_TIMEOUT_S="${SWEFF_CHUNK_TIMEOUT_S:-3888000}"

# The Python pipeline shell scripts invoke `python`; some hosts (this Mac)
# only ship `python3`. Put a `python` -> `python3` shim on PATH if needed so
# the scrape phase runs regardless of host.
if ! command -v python >/dev/null 2>&1; then
    if command -v python3 >/dev/null 2>&1; then
        _SHIM_DIR="$(mktemp -d)"
        ln -sf "$(command -v python3)" "$_SHIM_DIR/python"
        export PATH="$_SHIM_DIR:$PATH"
        echo "[$(date)] python shim -> python3 created at $_SHIM_DIR"
    else
        echo "ERROR: neither python nor python3 found on PATH" >&2
        exit 1
    fi
fi

# --------------------------------------------------------------------------
# Phase 1: discovery (the GitHub-token-required "first part")
# --------------------------------------------------------------------------
echo "[$(date)] Phase 1a: discovering up to ${PY_REPOS} Python repos..."
python3 -m swefficiency.collect.discover_repos \
    --output artifacts/discovered_py_repos.txt \
    --format ranked \
    --min-stars "$MIN_STARS" \
    --max-repos "$PY_REPOS" \
    || echo "[$(date)] WARN: Python discovery exited non-zero (partial output kept)"

echo "[$(date)] Phase 1b: discovering up to ${CPP_REPOS} C++ repos..."
python3 -m swefficiency.collect.discover_repos_cpp \
    --output artifacts_cpp/discovered_cpp_repos.txt \
    --format ranked \
    --min-stars "$MIN_STARS" \
    --max-repos "$CPP_REPOS" \
    || echo "[$(date)] WARN: C++ discovery exited non-zero (partial output kept)"

# --------------------------------------------------------------------------
# Phase 2: scrape (PRs -> perf_filter -> versioning -> detect_specs)
# Produces the enriched task instances the next phase needs.
# --------------------------------------------------------------------------
if [[ -s artifacts/discovered_py_repos.txt ]]; then
    echo "[$(date)] Phase 2a: scraping Python repos..."
    ./run_pipeline_scrape.sh --repos-file artifacts/discovered_py_repos.txt \
        || echo "[$(date)] WARN: Python scrape exited non-zero (see DLQ artifacts/dlq)"
else
    echo "[$(date)] SKIP Python scrape: no discovered_py_repos.txt"
fi

if [[ -s artifacts_cpp/discovered_cpp_repos.txt ]]; then
    echo "[$(date)] Phase 2b: scraping C++ repos..."
    ./run_pipeline_scrape_cpp.sh --repos-file artifacts_cpp/discovered_cpp_repos.txt \
        || echo "[$(date)] WARN: C++ scrape exited non-zero (see DLQ artifacts_cpp/dlq)"
else
    echo "[$(date)] SKIP C++ scrape: no discovered_cpp_repos.txt"
fi

echo "[$(date)] DONE."
echo "  Completed-repo ledgers : artifacts/tasks/completed_repos.txt"
echo "                           artifacts_cpp/tasks/completed_repos.txt"
echo "  Failure triage (DLQ)   : artifacts/dlq/  artifacts_cpp/dlq/"
echo "  Re-run this script to resume; ledgered repos are skipped (0 API calls)."

# Mark completion so the launchd supervisor does not re-run discovery.
touch .scrape_5k_done
echo "[$(date)] wrote .scrape_5k_done sentinel."
