#!/usr/bin/env bash
# Score an emitted kubectl task by running its own test harness inside its own
# environment for each candidate patch: golden.diff, reference.diff, and the
# empty submission (NOP). Emits a JSON summary and per-run pytest logs.
#
# Usage:
#   scripts/kubectl/score_task.sh <task_dir>
#
# Requirements:
#   - docker daemon running
#   - DOCKER_DEFAULT_PLATFORM=linux/amd64 (auto-set on arm64 hosts)
#
# Output files (written into <task_dir>/scoring/):
#   golden/pytest.log    reference/pytest.log    empty/pytest.log
#   golden/reward.txt    reference/reward.txt    empty/reward.txt
#   summary.json
set -uo pipefail

TASK_DIR="${1:-}"
if [[ -z "$TASK_DIR" || ! -d "$TASK_DIR" ]]; then
    echo "usage: $0 <task_dir>" >&2
    exit 2
fi
TASK_DIR="$(cd "$TASK_DIR" && pwd)"

if [[ "$(uname -m)" == "arm64" || "$(uname -m)" == "aarch64" ]]; then
    export DOCKER_DEFAULT_PLATFORM=linux/amd64
fi

ENV_DIR="$TASK_DIR/environment"
SOL_DIR="$TASK_DIR/solution"
TEST_DIR="$TASK_DIR/tests"
SCORE_DIR="$TASK_DIR/scoring"
mkdir -p "$SCORE_DIR"

if [[ ! -f "$ENV_DIR/Dockerfile" ]]; then
    echo "score_task: missing $ENV_DIR/Dockerfile" >&2
    exit 3
fi

TAG="r2e-score-$(basename "$TASK_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')"
TAG="${TAG:0:60}"

echo "[score_task] building image $TAG from $ENV_DIR/Dockerfile"
BUILD_LOG="$SCORE_DIR/docker_build.log"
if ! docker build -q -t "$TAG" "$ENV_DIR" >"$BUILD_LOG" 2>&1; then
    echo "[score_task] docker build FAILED (see $BUILD_LOG)" >&2
    tail -40 "$BUILD_LOG" >&2
    exit 4
fi

run_variant() {
    local variant="$1"
    local out="$SCORE_DIR/$variant"
    mkdir -p "$out"
    local logs_host="$out/container_logs"
    mkdir -p "$logs_host"

    local mounts=(
        -v "$TEST_DIR:/workspace/tests:ro"
        -v "$TASK_DIR/task.toml:/workspace/task.toml:ro"
        -v "$logs_host:/logs"
    )
    local pre_cmd=""
    if [[ "$variant" == "golden" ]]; then
        mounts+=(-v "$SOL_DIR:/workspace/solution:ro")
        pre_cmd='bash /workspace/solution/solve.sh SOLVE_PATCH=golden; SOLVE_PATCH=golden bash /workspace/solution/solve.sh || true; '
    elif [[ "$variant" == "reference" ]]; then
        mounts+=(-v "$SOL_DIR:/workspace/solution:ro")
        pre_cmd='SOLVE_PATCH=reference bash /workspace/solution/solve.sh || true; '
    else
        pre_cmd=''
    fi

    echo "[score_task] running variant=$variant"
    docker run --rm --cpus=2.0 --memory=4g \
        -e SOLVE_PATCH="$variant" \
        "${mounts[@]}" \
        "$TAG" \
        bash -c "set -x; mkdir -p /logs/verifier; ${pre_cmd} bash /workspace/tests/test.sh; echo done" \
        >"$out/pytest.log" 2>&1

    if [[ -f "$logs_host/verifier/reward.txt" ]]; then
        cp "$logs_host/verifier/reward.txt" "$out/reward.txt"
    else
        echo "0.0" >"$out/reward.txt"
    fi
    if [[ -f "$logs_host/verifier/results.xml" ]]; then
        cp "$logs_host/verifier/results.xml" "$out/results.xml"
    fi
}

run_variant golden
run_variant reference
run_variant empty

python3 - "$SCORE_DIR" <<'PY'
import json, sys, re
from pathlib import Path
from xml.etree import ElementTree as ET

score_dir = Path(sys.argv[1])
task_dir = score_dir.parent

def parse_reward(path: Path) -> float:
    try:
        txt = path.read_text().strip().splitlines()
        for line in reversed(txt):
            m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*$", line)
            if m:
                return float(m.group(1))
    except Exception:
        pass
    return 0.0

def parse_junit(path: Path) -> dict:
    if not path.exists():
        return {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    t = f = e = s = 0
    for su in suites:
        t += int(su.get("tests", 0) or 0)
        f += int(su.get("failures", 0) or 0)
        e += int(su.get("errors", 0) or 0)
        s += int(su.get("skipped", 0) or 0)
    return {"tests": t, "passed": t - f - e - s, "failed": f, "errors": e, "skipped": s}

variants = ["golden", "reference", "empty"]
result = {"task_dir": str(task_dir), "variants": {}}
for v in variants:
    rd = score_dir / v
    reward = parse_reward(rd / "reward.txt")
    counts = parse_junit(rd / "results.xml")
    result["variants"][v] = {"reward": reward, **counts}

golden = result["variants"]["golden"]["reward"]
reference = result["variants"]["reference"]["reward"]
empty = result["variants"]["empty"]["reward"]
result["pass"] = golden >= 0.95 and reference >= 0.95 and empty <= 0.05
result["thresholds"] = {"golden_min": 0.95, "reference_min": 0.95, "empty_max": 0.05}

out = score_dir / "summary.json"
out.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
PY

echo "[score_task] summary written to $SCORE_DIR/summary.json"
