#!/usr/bin/env bash
# Runs harbor {oracle-golden, oracle-reference, nop} against every task
# under datasets/kubectl-kinds-v1/. Up to 3 tasks in parallel; each task
# runs its three variants sequentially.
#
# Usage: scripts/kubectl/harbor_score_all.sh [ROOT] [MAX_PARALLEL]
#   ROOT          default: datasets/kubectl-kinds-v1
#   MAX_PARALLEL  default: 3

set -uo pipefail

ROOT="${1:-/Users/anshkataria/Desktop/23-july/Repo2RLEnv/datasets/kubectl-kinds-v1}"
MAX_PARALLEL="${2:-3}"
LOGDIR="$ROOT/_runner_logs"
mkdir -p "$LOGDIR"

process_task() {
    local task_dir="$1"
    local task_name
    task_name=$(basename "$(dirname "$task_dir")")
    local log="$LOGDIR/${task_name}.log"
    local scoring="$task_dir/scoring"
    mkdir -p "$scoring"

    {
        echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) START $task_name ==="
        echo "task_dir: $task_dir"

        for variant in oracle-golden oracle-reference nop; do
            local agent extra
            case "$variant" in
                oracle-golden)    agent=oracle ; extra=(--ae SOLVE_PATCH=golden) ;;
                oracle-reference) agent=oracle ; extra=(--ae SOLVE_PATCH=reference) ;;
                nop)              agent=nop    ; extra=() ;;
            esac
            local out="$scoring/$variant"
            mkdir -p "$out"
            echo ""
            echo "--- $(date -u +%H:%M:%SZ) [$variant] agent=$agent ---"
            if compgen -G "$out/*/result.json" >/dev/null; then
                echo "[$variant] already scored, skipping"
                continue
            fi
            if harbor run -p "$task_dir" -a "$agent" -e docker -o "$out" -n 1 -y -q --verifier-timeout-multiplier=4 "${extra[@]}" 2>&1; then
                echo "[$variant] harbor exit 0"
            else
                echo "[$variant] harbor NON-ZERO EXIT $?"
            fi
        done

        echo ""
        echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) DONE $task_name ==="
    } >>"$log" 2>&1
}
export -f process_task
export LOGDIR

TASK_DIRS=$(find "$ROOT" -mindepth 2 -maxdepth 2 -type d -exec test -f {}/task.toml \; -print | sort)
N_TASKS=$(echo "$TASK_DIRS" | wc -l | tr -d ' ')
echo "[$(date -u +%H:%M:%SZ)] Runner: $N_TASKS tasks, parallelism=$MAX_PARALLEL, logs=$LOGDIR"

echo "$TASK_DIRS" | xargs -n1 -P"$MAX_PARALLEL" -I{} bash -c 'process_task "$@"' _ {}

echo "[$(date -u +%H:%M:%SZ)] Runner: all tasks complete."
