#!/usr/bin/env bash
#
# run_cpp_recovery.sh - Regenerate the C++ discovery list (lost when the
# scrape script's STAGE 0 overwrote it) and scrape it with the fixed
# run_pipeline_scrape_cpp.sh (which now skips STAGE 0 when --repos-file is set).
#
#     nohup ./run_cpp_recovery.sh > cpp_recovery.log 2>&1 &
#
set -uo pipefail
cd "$(dirname "$0")"

TOKENS_FILE="${TOKENS_FILE:-tokens.txt}"
GITHUB_TOKENS="$(grep -v '^[[:space:]]*$' "$TOKENS_FILE" | paste -sd, -)"
export GITHUB_TOKENS
export GITHUB_TOKEN="${GITHUB_TOKENS%%,*}"
export SWEFF_CHUNK_TIMEOUT_S="${SWEFF_CHUNK_TIMEOUT_S:-3888000}"
echo "[$(date)] Loaded $(echo "$GITHUB_TOKENS" | tr ',' '\n' | grep -c .) token(s)."

echo "[$(date)] C++ discovery (regenerating discovered_cpp_repos.txt)..."
python3 -m swefficiency.collect.discover_repos_cpp \
    --output artifacts_cpp/discovered_cpp_repos.txt \
    --format ranked \
    --min-stars "${CPP_MIN_STARS:-100}" \
    --max-repos "${CPP_REPOS:-2500}" \
    || echo "[$(date)] WARN: C++ discovery exited non-zero (partial output kept)"

if [[ -s artifacts_cpp/discovered_cpp_repos.txt ]]; then
    n=$(grep -cv '^[[:space:]]*#\|^[[:space:]]*$' artifacts_cpp/discovered_cpp_repos.txt)
    echo "[$(date)] C++ discovery produced ${n} repos. Starting scrape..."
    bash ./run_pipeline_scrape_cpp.sh --repos-file artifacts_cpp/discovered_cpp_repos.txt \
        || echo "[$(date)] WARN: C++ scrape exited non-zero (see artifacts_cpp/dlq)"
else
    echo "[$(date)] ERROR: no discovered_cpp_repos.txt produced; skipping scrape." >&2
    exit 1
fi
echo "[$(date)] C++ recovery DONE."
