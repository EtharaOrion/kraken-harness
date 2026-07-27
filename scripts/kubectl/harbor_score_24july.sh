#!/bin/bash
# Usage: harbor_score_24july.sh [ROOT] [MAX_PARALLEL]

set -uo pipefail

ROOT="${1:-/Users/anshkataria/Desktop/23-july/24-july/kubectl-kinds-v1}"
MAX_PARALLEL="${2:-3}"
LOGDIR="$ROOT/_runner_logs"
mkdir -p "$LOGDIR"

HARBOR="$HOME/.local/bin/harbor"

TASKS=()
while IFS= read -r line; do
    TASKS+=("$line")
done < <(find "$ROOT" -mindepth 2 -maxdepth 2 -type d -exec test -e '{}/task.toml' \; -print | sort)

echo "[$(date -u +%FT%TZ)] Runner: ${#TASKS[@]} tasks, parallelism=$MAX_PARALLEL, logs=$LOGDIR"

run_one() {
    local task_dir="$1"
    local task_name
    task_name=$(basename "$(dirname "$task_dir")")
    local log="$LOGDIR/$task_name.log"

    {
        echo "[$(date -u +%FT%TZ)] START $task_name  ($task_dir)"
        for variant in oracle-golden oracle-reference; do
            local out="$task_dir/scoring/$variant"
            mkdir -p "$out"
            if compgen -G "$out/*/result.json" >/dev/null; then
                echo "[$variant] already scored, skipping"
                continue
            fi
            local ae=()
            case "$variant" in
                oracle-golden)    ae=(--ae "SOLVE_PATCH=golden") ;;
                oracle-reference) ae=(--ae "SOLVE_PATCH=reference") ;;
            esac
            echo "[$(date -u +%FT%TZ)] $variant start"
            "$HARBOR" run -p "$task_dir" -a oracle -e docker -o "$out" -n 1 -y -q "${ae[@]}"
            echo "[$(date -u +%FT%TZ)] $variant exit=$?"
        done
        echo "[$(date -u +%FT%TZ)] DONE  $task_name"
    } >>"$log" 2>&1
}

export -f run_one
export LOGDIR HARBOR

printf '%s\n' "${TASKS[@]}" | xargs -n1 -P"$MAX_PARALLEL" -I{} bash -c 'run_one "$@"' _ {}

echo "[$(date -u +%FT%TZ)] Runner complete"
