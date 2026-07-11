# DynamoDB pilot — runbook (3-task slice)

The `code_instruct` `cli_app` pipeline can generate DynamoDB tasks (backend =
DynamoDB Local, extractor = botocore service model, no-boto raw-HTTP tests).
The code is complete and unit-tested; these scripts run the remaining
*runtime* steps, which need Docker + an LLM key.

## 1. Go/no-go spike (no LLM cost)
```bash
scripts/dynamodb/spike.sh
```
Validates: (#1) the aws-cli@v2 clone vendors `botocore/data/dynamodb/service-2.json`;
(#2) DynamoDB Local boots and the shipped `_ddb_http` client round-trips (confirming
the dummy-SigV4 header is accepted); (#3) real `aws dynamodb` honours
`AWS_ENDPOINT_URL_DYNAMODB`; (#4) cold-start < 10 s. It also prints the
`amazon/dynamodb-local` **digest** to pin into `PINNED_DDB_LOCAL_IMAGE`.

If gate #1 fails (the branch doesn't vendor botocore data), pip-install the
matching `botocore` and re-run with `SERVICE_MODEL_OVERRIDE=<path>/service-2.json`.

## 2. Generate the slice (spends LLM budget)
```bash
export LLM=anthropic/claude-opus-4-8        # provider/model
export ANTHROPIC_API_KEY=...                # (or the creds for your chosen model)
scripts/dynamodb/generate_slice.sh
```
Emits 3 tasks under `./datasets/ddb-slice`. Grounding is ON by default
(`GROUNDING=off` for a Docker-free smoke).

## 3. Verify each task (per-task DoD)
Per `samples/README.md`:
```bash
docker build -t raiden-ddb datasets/ddb-slice/<uuid>/environment/
docker run --rm -v "$PWD/datasets/ddb-slice/<uuid>:/task:ro" raiden-ddb bash -c '
  bash /task/solution/solve.sh && bash /task/tests/test.sh && cat /logs/verifier/reward.txt'
```
Expect `1.0` with the gold patch, `0.0` with an empty `submission/main.py`, and
real-`aws dynamodb` ≥ 0.95 from the grounding leg.

## Prerequisites checklist
- Docker daemon running (engine, base-image build, grounding gauntlet).
- `uv` + this harness installed.
- An LLM provider + key for `--llm` (Opus tier assumed by the cost anchor).
- Network at *generation* time to clone `aws/aws-cli@v2` and pull
  `amazon/dynamodb-local` (shipped tasks run offline).
- `PINNED_DDB_LOCAL_IMAGE` pinned to a digest (from the spike output) before any
  delivery build, plus the DynamoDB-Local licensing sign-off (deferred item).
