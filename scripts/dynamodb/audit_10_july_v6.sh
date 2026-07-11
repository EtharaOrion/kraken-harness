#!/usr/bin/env bash
#
# 10-july-v6 audit: run harbor oracle + nop against each task under
# raiden/10-july-v6/{uuid}/. Reject any task where oracle reward != 1.0
# or nop reward != 0.0.
#
# Per-task outputs:
#   <task>/audit-logs/oracle_full.log
#   <task>/audit-logs/nop_full.log
#
# Batch outputs at raiden/10-july-v6/:
#   harbor_runs.log      per-task ORACLE + NOP panels, ALL COMPLETE footer
#   audit_verdict.tsv    uuid \t oracle_reward \t nop_reward \t verdict
#
# UUIDs are discovered dynamically (any dir under V6_ROOT that has task.toml).
#
# Env (optional):
#   V6_ROOT        default: /Users/anshkataria/Desktop/7-July/raiden/10-july-v6
#   JOBS_ROOT      default: /tmp/audit-jobs-10-july-v6
#   HARBOR_BIN     default: /Users/anshkataria/Desktop/7-July/raiden/harbor/.venv/bin/harbor
#   START_AT       1..N to resume mid-run

set -euo pipefail

V6_ROOT="${V6_ROOT:-/Users/anshkataria/Desktop/7-July/raiden/10-july-v6}"
JOBS_ROOT="${JOBS_ROOT:-/tmp/audit-jobs-10-july-v6}"
HARBOR_BIN="${HARBOR_BIN:-/Users/anshkataria/Desktop/7-July/raiden/harbor/.venv/bin/harbor}"
START_AT="${START_AT:-1}"

[ -d "$V6_ROOT" ] || { echo "V6_ROOT not found: $V6_ROOT" >&2; exit 1; }
[ -x "$HARBOR_BIN" ] || { echo "harbor CLI not executable: $HARBOR_BIN" >&2; exit 1; }
docker info > /dev/null 2>&1 || { echo "docker daemon not running" >&2; exit 1; }

# Dynamic UUID discovery: any directory directly under V6_ROOT that has task.toml.
UUIDS=()
while IFS= read -r d; do
  uuid="$(basename "$d")"
  if [ -f "$d/task.toml" ]; then
    UUIDS+=("$uuid")
  fi
done < <(find "$V6_ROOT" -mindepth 1 -maxdepth 1 -type d | sort)

TOTAL=${#UUIDS[@]}
[ "$TOTAL" -gt 0 ] || { echo "no task dirs discovered under $V6_ROOT" >&2; exit 1; }

HARBOR_RUNS_LOG="$V6_ROOT/harbor_runs.log"
VERDICT_TSV="$V6_ROOT/audit_verdict.tsv"

if [ "$START_AT" = "1" ]; then
  : > "$HARBOR_RUNS_LOG"
  printf 'uuid\toracle_reward\tnop_reward\tverdict\n' > "$VERDICT_TSV"
fi

mkdir -p "$JOBS_ROOT"

# Extract mean reward from harbor jobs result.json.
# Path: stats.evals.<agent>__adhoc.metrics[0].mean
extract_reward() {
  local result_json="$1"
  local agent="$2"
  python3 - "$result_json" "$agent" <<'PY'
import json, sys
path, agent = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
evals = data.get("stats", {}).get("evals", {})
key = f"{agent}__adhoc"
metrics = evals.get(key, {}).get("metrics", [])
if not metrics:
    print("NA")
else:
    print(f"{metrics[0].get('mean', float('nan')):.4f}")
PY
}

for i in "${!UUIDS[@]}"; do
  n=$((i + 1))
  if [ "$n" -lt "$START_AT" ]; then continue; fi

  uuid="${UUIDS[$i]}"
  task_dir="$V6_ROOT/$uuid"
  audit_dir="$task_dir/audit-logs"
  jobs_dir="$JOBS_ROOT/$uuid"

  mkdir -p "$audit_dir" "$jobs_dir"

  {
    echo "===================================================================="
    echo "TASK $n/$TOTAL: $uuid"
    echo "PATH: $task_dir/"
    echo "START: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "===================================================================="
    echo
  } >> "$HARBOR_RUNS_LOG"

  oracle_log="$audit_dir/oracle_full.log"
  echo "--- ORACLE ---" >> "$HARBOR_RUNS_LOG"
  set +e
  "$HARBOR_BIN" run \
    --path "$task_dir" \
    --agent oracle \
    --jobs-dir "$jobs_dir/oracle" \
    --job-name oracle \
    -k 1 -n 1 -y --no-delete \
    > "$oracle_log" 2>&1
  set -e
  cat "$oracle_log" >> "$HARBOR_RUNS_LOG"

  oracle_result="$jobs_dir/oracle/oracle/result.json"
  if [ -f "$oracle_result" ]; then
    oracle_reward=$(extract_reward "$oracle_result" oracle)
  else
    oracle_reward="NA"
  fi

  nop_log="$audit_dir/nop_full.log"
  echo >> "$HARBOR_RUNS_LOG"
  echo "--- NOP ---" >> "$HARBOR_RUNS_LOG"
  set +e
  "$HARBOR_BIN" run \
    --path "$task_dir" \
    --agent nop \
    --jobs-dir "$jobs_dir/nop" \
    --job-name nop \
    -k 1 -n 1 -y --no-delete \
    > "$nop_log" 2>&1
  set -e
  cat "$nop_log" >> "$HARBOR_RUNS_LOG"

  nop_result="$jobs_dir/nop/nop/result.json"
  if [ -f "$nop_result" ]; then
    nop_reward=$(extract_reward "$nop_result" nop)
  else
    nop_reward="NA"
  fi

  verdict="REJECT"
  if [ "$oracle_reward" = "1.0000" ] && [ "$nop_reward" = "0.0000" ]; then
    verdict="PASS"
  fi

  printf '%s\t%s\t%s\t%s\n' "$uuid" "$oracle_reward" "$nop_reward" "$verdict" >> "$VERDICT_TSV"

  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  {
    echo
    echo "[$ts] done $n/$TOTAL $uuid oracle=$oracle_reward nop=$nop_reward -> $verdict"
    echo
  } >> "$HARBOR_RUNS_LOG"

  echo "[$n/$TOTAL] $uuid oracle=$oracle_reward nop=$nop_reward -> $verdict"
done

echo "ALL COMPLETE" >> "$HARBOR_RUNS_LOG"
echo
echo "harbor_runs.log:    $HARBOR_RUNS_LOG"
echo "audit_verdict.tsv:  $VERDICT_TSV"
echo "jobs root:          $JOBS_ROOT"
