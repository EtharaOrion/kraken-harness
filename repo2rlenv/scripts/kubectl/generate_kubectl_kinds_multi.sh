#!/usr/bin/env bash
#
# kubectl (kwok backend) KINDS-BASED BATCH: 50 tasks in reverse-order size:
#   Task 1        -> size-14 (all kinds together)
#   Tasks 2-15    -> size-13 (each drops exactly one kind)
#   Tasks 16-50   -> first 35 of the 91 size-12 combinations
#
# For each combination, the verb subset is the UNION of commands the selected
# kinds support (from kubectl_kinds.md). Fixtures selected via the kwok
# fixture short-circuit filter by (verb, kind); missing (verb, kind) pairs
# fall back to LLM synthesis.
#
# Env (required):
#   LLM_CONFIG           path to proxy yaml (scripts/kubectl/llm-proxy.yaml)
#   CLAUDE_PROXY_TOKEN   any non-empty value (proxy reads OAuth from Keychain)
# Env (optional):
#   OUT_ROOT             parent dir (default: ./datasets/kubectl-kinds-v1)
#   START_AT             1..N to resume mid-batch after a failure
#   END_AT               default 50 (whole batch)
#   MAX_TESTS            per-task fixture cap (default 400, must be ≥ kinds×verbs to guarantee combo coverage)
#   YAML_BUNDLE          override path to kubectl Cobra YAML bundle
#   FIXTURE_DIR          override path to kubectl fixture dir

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$HARNESS_DIR"

: "${LLM_CONFIG:?set LLM_CONFIG=scripts/kubectl/llm-proxy.yaml}"
: "${CLAUDE_PROXY_TOKEN:?set CLAUDE_PROXY_TOKEN=dummy (proxy reads OAuth from Keychain)}"
[ -f "$LLM_CONFIG" ] || { echo "LLM_CONFIG not found: $LLM_CONFIG"; exit 1; }

OUT_ROOT="${OUT_ROOT:-./datasets/kubectl-kinds-v1}"
START_AT="${START_AT:-1}"
END_AT="${END_AT:-50}"
MAX_TESTS="${MAX_TESTS:-400}"
YAML_BUNDLE="${YAML_BUNDLE:-$HARNESS_DIR/tests/fixtures/kubectl_spec_v1_31_minimal.yaml}"
FIXTURE_DIR="${FIXTURE_DIR:-$HARNESS_DIR/tests/fixtures/kubectl_testcases}"

if ! curl -sf http://localhost:8765/health > /dev/null 2>&1; then
  if ! curl -sf -X POST http://localhost:8765/v1/messages \
      -H 'content-type: application/json' \
      -H 'x-api-key: dummy' \
      -d '{"model":"claude-opus-4-8","max_tokens":1,"messages":[{"role":"user","content":"ping"}]}' \
      > /dev/null 2>&1; then
    echo "proxy at localhost:8765 not responding - start it with:"
    echo "  uv run proxy/claude_oauth_proxy.py --port 8765"
    exit 1
  fi
fi

if ! docker info > /dev/null 2>&1; then
  echo "docker daemon not running"
  exit 1
fi

[ -f "$YAML_BUNDLE" ] || { echo "YAML_BUNDLE not found: $YAML_BUNDLE"; exit 1; }
[ -d "$FIXTURE_DIR" ] || { echo "FIXTURE_DIR not found: $FIXTURE_DIR"; exit 1; }
[ -f "$FIXTURE_DIR/conftest.py" ] || { echo "FIXTURE_DIR missing conftest.py: $FIXTURE_DIR"; exit 1; }
[ -f "$FIXTURE_DIR/kind_index.json" ] || { echo "FIXTURE_DIR missing kind_index.json: run scripts/kubectl/build_kind_index.py first"; exit 1; }

# Precompute the 50 (task_num, slug, kinds_csv, verbs_csv) tuples via Python.
# Reverse order (largest first): 1 size-14 + 14 size-13 + 35 size-12.
TASKS_TSV="$(mktemp)"
trap 'rm -f "$TASKS_TSV"' EXIT

python3 - > "$TASKS_TSV" <<'PYEOF'
import itertools

KINDS = [
    ("Pod",                   "get,describe,delete,apply,patch,label"),
    ("Service",               "get,describe,delete,create,apply,patch,label"),
    ("Deployment",            "get,describe,delete,create,apply,patch,scale,label"),
    ("ReplicaSet",            "get,describe,delete,apply,patch,scale,label"),
    ("StatefulSet",           "get,describe,delete,apply,patch,scale,label"),
    ("DaemonSet",             "get,describe,delete,apply,patch,label"),
    ("Job",                   "get,describe,delete,create,apply,patch,label"),
    ("CronJob",               "get,describe,delete,create,apply,patch,label"),
    ("ConfigMap",             "get,describe,delete,create,apply,patch,label"),
    ("Secret",                "get,describe,delete,create,apply,patch,label"),
    ("Namespace",             "get,describe,delete,create,apply,patch,label"),
    ("Ingress",               "get,describe,delete,create,apply,patch,label"),
    ("PersistentVolumeClaim", "get,describe,delete,apply,patch,label"),
    ("ServiceAccount",        "get,describe,delete,create,apply,patch,label"),
]
all_kinds = [k for k, _ in KINDS]
kind_verbs = {k: v.split(",") for k, v in KINDS}

def verbs_for(kinds):
    s = set()
    for k in kinds:
        s.update(kind_verbs[k])
    return sorted(s)

def short(name):
    # short abbrevs for slug
    return {
        "Pod":"pod", "Service":"svc", "Deployment":"dep", "ReplicaSet":"rs",
        "StatefulSet":"sts", "DaemonSet":"ds", "Job":"job", "CronJob":"cj",
        "ConfigMap":"cm", "Secret":"sec", "Namespace":"ns", "Ingress":"ing",
        "PersistentVolumeClaim":"pvc", "ServiceAccount":"sa",
    }[name]

tasks = []
# size 14 (1 task)
tasks.append(("all14", all_kinds))
# size 13 (14 tasks): drop each kind once
for i in range(14):
    remaining = [all_kinds[j] for j in range(14) if j != i]
    slug = f"no-{short(all_kinds[i])}"
    tasks.append((slug, remaining))
# size 12 (35 tasks): first 35 of 91 lexicographic combinations
size12 = list(itertools.combinations(range(14), 12))
for combo in size12[:35]:
    kinds = [all_kinds[j] for j in combo]
    dropped = sorted(set(range(14)) - set(combo))
    slug = "no-" + "-".join(short(all_kinds[j]) for j in dropped)
    tasks.append((slug, kinds))

for i, (slug, kinds) in enumerate(tasks, 1):
    print(f"{i}\t{slug}\t{','.join(kinds)}\t{','.join(verbs_for(kinds))}")
PYEOF

TOTAL="$(wc -l < "$TASKS_TSV" | tr -d ' ')"
echo "[kubectl-kinds-v1] precomputed $TOTAL tasks (expected 50)"

mkdir -p "$OUT_ROOT"

while IFS=$'\t' read -r n slug kinds_csv verbs_csv; do
  if [ "$n" -lt "$START_AT" ]; then continue; fi
  if [ "$n" -gt "$END_AT" ]; then continue; fi
  size="$(echo "$kinds_csv" | tr ',' '\n' | wc -l | tr -d ' ')"
  out="$OUT_ROOT/task-${size}-${slug}"
  echo
  echo "===================================================================="
  echo "[kubectl-kinds-v1] task ${n}/${TOTAL} -> $out"
  echo "  size:  ${size}"
  echo "  kinds: ${kinds_csv}"
  echo "  verbs: ${verbs_csv}"
  echo "  max_tests: $MAX_TESTS"
  echo "===================================================================="
  mkdir -p "$out"
  uv run repo2rlenv generate \
    --repo kubernetes/kubectl --ref v0.32.0 --pipeline code_instruct \
    --pipeline-opt mode=cli_app \
    --pipeline-opt cli_app_command_prefix=kubectl \
    --pipeline-opt cli_app_backend=kwok \
    --pipeline-opt "cli_app_kubectl_yaml_bundle_path=$YAML_BUNDLE" \
    --pipeline-opt "cli_app_kubectl_fixture_dir=$FIXTURE_DIR" \
    --pipeline-opt "cli_app_kubectl_fixture_max_tests=$MAX_TESTS" \
    --pipeline-opt "cli_app_kubectl_kinds=[$(echo "$kinds_csv" | sed 's/,/","/g;s/^/"/;s/$/"/')]" \
    --pipeline-opt "cli_app_subsets=[\"${verbs_csv}\"]" \
    --pipeline-opt cli_app_oracle=llm \
    --pipeline-opt cli_app_auto_subsets=false \
    --pipeline-opt cli_app_max_intents=100 \
    --pipeline-opt max_llm_tokens=65000 \
    --pipeline-opt cli_app_docker_timeout_sec=3600 \
    --pipeline-opt cli_app_translate_workers=3 \
    --pipeline-opt cli_app_docker_gauntlet=false \
    --pipeline-opt cli_app_reference_grounding=true \
    --config "$LLM_CONFIG" \
    --out "$out" 2>&1 | tee "$out/generate.log"
done < "$TASKS_TSV"

echo
echo "[kubectl-kinds-v1] batch complete. Task dirs under: $OUT_ROOT/task-*/"
