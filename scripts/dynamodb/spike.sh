#!/usr/bin/env bash
#
# DynamoDB enablement go/no-go spike (plan §1). Validates the four runtime
# assumptions the DynamoDB pipeline rests on BEFORE spending any LLM budget on
# the 3-task slice. Prints a PASS/FAIL summary and exits non-zero if any hard
# gate fails.
#
# Gates:
#   #1 extractor    — the aws-cli v2 clone vendors botocore/data/dynamodb/service-2.json
#   #2 engine+auth  — DynamoDB Local boots and the SHIPPED _ddb_http client round-trips
#   #3 grounding    — real `aws dynamodb` honours AWS_ENDPOINT_URL_DYNAMODB (soft: skips if no aws)
#   #4 cold-start   — engine answers ListTables within the DoD budget (< 10s)
#
# Requirements: docker (running), git, uv. Optional: aws-cli v2 (for gate #3 on host).
# Usage: scripts/dynamodb/spike.sh
set -uo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DDB_IMAGE="${DDB_IMAGE:-amazon/dynamodb-local:2.5.4}"
AWSCLI_REF="${AWSCLI_REF:-v2}"
# Pick a free host port (8000 is often taken); container still listens on 8000.
PORT="${PORT:-$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()' 2>/dev/null || echo 8123)}"
ENDPOINT="http://127.0.0.1:${PORT}"
WORK="$(mktemp -d)"
CID=""
fail=0

log()  { printf '\033[1m[spike]\033[0m %s\n' "$*"; }
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=1; }

cleanup() {
  [ -n "$CID" ] && docker rm -f "$CID" >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

command -v docker >/dev/null || { echo "docker not found"; exit 2; }
docker info >/dev/null 2>&1   || { echo "docker daemon not running"; exit 2; }

# --------------------------------------------------------------------------
log "Gate #1 — service model present in aws-cli @ ${AWSCLI_REF} clone"
# --------------------------------------------------------------------------
if [ -n "${SERVICE_MODEL_OVERRIDE:-}" ]; then
  if [ -f "$SERVICE_MODEL_OVERRIDE" ]; then
    pass "override provided: $SERVICE_MODEL_OVERRIDE"
  else
    bad "SERVICE_MODEL_OVERRIDE set but not a file: $SERVICE_MODEL_OVERRIDE"
  fi
else
  git clone --depth 1 --branch "$AWSCLI_REF" https://github.com/aws/aws-cli "$WORK/aws-cli" >/dev/null 2>&1 \
    || bad "could not shallow-clone aws/aws-cli @ ${AWSCLI_REF}"
  MODEL="$(find "$WORK/aws-cli" -path '*botocore/data/dynamodb/*/service-2.json' 2>/dev/null | head -1)"
  if [ -n "$MODEL" ]; then
    OPS="$(grep -o '"CreateTable"\|"PutItem"\|"GetItem"\|"Query"' "$MODEL" | sort -u | wc -l | tr -d ' ')"
    pass "found $(echo "$MODEL" | sed "s|$WORK/aws-cli/||") (target ops present: ${OPS}/4)"
    [ "$OPS" = "4" ] || warn "not all 4 sampled ops found — inspect the model shape"
  else
    bad "no botocore/data/dynamodb/*/service-2.json in the clone."
    warn "the v2 branch may not vendor botocore data; use SERVICE_MODEL_OVERRIDE=<path> "
    warn "(e.g. from a pip-installed botocore) and pass cli_app_service_model_override to generate."
  fi
fi

# --------------------------------------------------------------------------
log "Gate #4/#2 — boot DynamoDB Local (${DDB_IMAGE}) and time readiness"
# --------------------------------------------------------------------------
DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "$DDB_IMAGE" 2>/dev/null || true)"
[ -z "$DIGEST" ] && docker pull "$DDB_IMAGE" >/dev/null 2>&1 && \
  DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "$DDB_IMAGE" 2>/dev/null || true)"
[ -n "$DIGEST" ] && log "pin this in PINNED_DDB_LOCAL_IMAGE -> ${DIGEST}"

t0=$(date +%s)
CID="$(docker run -d -p "${PORT}:8000" "$DDB_IMAGE" -jar DynamoDBLocal.jar -inMemory -sharedDb -disableTelemetry 2>/dev/null)"
if [ -z "$CID" ]; then
  bad "could not start DynamoDB Local container"
else
  ready=0
  for _ in $(seq 1 100); do
    code="$(curl -s -o /dev/null -w '%{http_code}' \
      -H 'Content-Type: application/x-amz-json-1.0' \
      -H 'X-Amz-Target: DynamoDB_20120810.ListTables' \
      -H 'Authorization: AWS4-HMAC-SHA256 Credential=dummy/20120810/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=00' \
      -d '{}' "$ENDPOINT" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] && { ready=1; break; }
    sleep 0.1
  done
  t1=$(date +%s); cold=$((t1 - t0))
  if [ "$ready" = "1" ]; then
    if [ "$cold" -lt 10 ]; then pass "engine ready in ${cold}s (< 10s DoD)"; else bad "cold-start ${cold}s exceeds 10s DoD"; fi
  else
    bad "engine never answered ListTables (auth header rejected or boot failed)"
  fi
fi

# --------------------------------------------------------------------------
log "Gate #2 — SHIPPED _ddb_http client round-trip against the live engine"
# --------------------------------------------------------------------------
if [ -n "$CID" ]; then
  ( cd "$HARNESS_DIR" && uv run python -c "
from repo2rlenv.pipelines._cli_app_synthesis import _DDB_HTTP_HELPER
ns={}; exec(compile(_DDB_HTTP_HELPER,'_ddb_http','exec'), ns)
C=ns['DDBClient']('${ENDPOINT}')
C.create_table('spike', [{'AttributeName':'pk','KeyType':'HASH'}], [{'AttributeName':'pk','AttributeType':'S'}])
assert 'spike' in C.list_tables()['TableNames']
C.put_item('spike', {'pk':{'S':'a'},'n':{'N':'5'}})
r=C.get_item('spike', {'pk':{'S':'a'}})
assert ns['from_item'](r['Item'])=={'pk':'a','n':5}, r
try:
    C.get_item('missing', {'pk':{'S':'a'}}); raise SystemExit('expected error on missing table')
except ns['DDBHTTPError'] as e:
    assert 'ResourceNotFoundException' in e.response['Error']['Code'], e.response
print('OK')
" ) >/tmp/ddb_client_check 2>&1 && pass "create/put/get round-trip + error taxonomy OK (dummy SigV4 accepted)" \
    || { bad "shipped _ddb_http client failed against the engine"; sed 's/^/    /' /tmp/ddb_client_check; }
fi

# --------------------------------------------------------------------------
log "Gate #3 — real aws dynamodb honours AWS_ENDPOINT_URL_DYNAMODB"
# --------------------------------------------------------------------------
if [ -n "$CID" ] && command -v aws >/dev/null 2>&1; then
  if AWS_ENDPOINT_URL_DYNAMODB="$ENDPOINT" AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \
     AWS_DEFAULT_REGION=us-east-1 aws dynamodb list-tables >/dev/null 2>&1; then
    pass "real aws dynamodb reached the local endpoint ($(aws --version 2>&1 | head -1))"
  else
    bad "real aws dynamodb did NOT honour AWS_ENDPOINT_URL_DYNAMODB (grounding leg at risk)"
  fi
else
  warn "aws-cli not on host — gate #3 is exercised in the grounding image instead; skipping here"
fi

echo
if [ "$fail" = "0" ]; then
  log "RESULT: GO — all hard gates passed. Proceed to scripts/dynamodb/generate_slice.sh"
else
  log "RESULT: NO-GO — fix the FAIL gate(s) above before generating tasks."
fi
exit "$fail"
