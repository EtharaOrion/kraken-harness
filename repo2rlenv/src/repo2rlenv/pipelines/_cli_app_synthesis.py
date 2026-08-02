"""LLM-driven translation + gauntlet + Harbor emission for cli_app mode.

Flow (called from code_instruct.run() when options.mode == "cli_app"):

  1. clone the target repo (uses bootstrap.runner._shallow_clone_at_ref)
  2. auto-detect entry_point + tests_dir (no LLM in MVP)
  3. extract CliSpec + TestIntents (deterministic AST walk)
  4. per intent: LLM-translate intent -> black-box pytest test
  5. per command: LLM-synthesise oracle (submission/main.py)
  6. gauntlet (G1-G4 in MVP; G5/G6 determinism flagged off by default)
       G1 compile()
       G2 AST structural (must use subprocess.run + assertion)
       G3 empty stub fails the test
       G4 LLM oracle passes the test
  7. build Dockerfile + conftest.py + test.sh + instruction.md
  8. write Harbor task via existing write_harbor_task()

This module is INTENTIONALLY MVP for the v3 smoke. Things deliberately
left out for the first task:
  - persistent cache at ~/.cache/repo2rlenv/cli_app_*
  - determinism gates G5/G6
  - semantic dedup
  - suite-level Docker verify
  - LLM fallback for auto-detection
  - per_behaviour / multi granularity (default = per_command for smoke)

All can be added without touching the architecture (this module owns them).
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from repo2rlenv.auth import resolve_github_token
from repo2rlenv.bootstrap.runner import _shallow_clone_at_ref
from repo2rlenv.emitter.harbor import (
    BLOCKED_HOSTS_DDB,
    BLOCKED_SUFFIXES,
    BLOCKED_SUFFIXES_DDB,
    HarborTask,
    _build_disallow_compose,
    write_harbor_task,
)
from repo2rlenv.llm import complete
from repo2rlenv.pipelines._cli_app_antihack import scan_oracle_for_reward_hacking
from repo2rlenv.pipelines._cli_app_extract import (
    _DDB_TARGET_OPS_DEFAULT,
    CliSpec,
    CommandSpec,
    TestIntent,
    _canonical_spec_hash,
    extract_cli_spec,
    extract_cli_spec_from_model,
    extract_test_intents,
    select_lifecycle_scope,
    synthesize_intents_from_model,
)
from repo2rlenv.pipelines._cli_app_generic import (
    SidecarSpec,
    make_generic_profile,
    resolve_sidecar,
)
from repo2rlenv.pipelines._cli_app_profiles import (
    ServiceProfile,
    register_profile,
    registered_backends,
    resolve_profile,
)
from repo2rlenv.pipelines._cli_app_slice import SliceError, build_slice_gold
from repo2rlenv.pipelines._cli_app_subsets import sample_subsets
from repo2rlenv.pipelines._oss_instruct import make_multi_file_diff
from repo2rlenv.pipelines.base import PipelineResult
from repo2rlenv.registry.buildx import (
    build_and_push_multiarch,
    manifest_exists,
)
from repo2rlenv.registry.ecr import (
    ensure_docker_login_ecr,
    ensure_ecr_repository,
    parse_ecr_region,
)

if TYPE_CHECKING:
    from repo2rlenv.pipelines.code_instruct import CodeInstructPipeline
    from repo2rlenv.spec.options import CodeInstructOptions

logger = logging.getLogger(__name__)


# Bump on prompt changes; baked into content_hash so consumers can detect
# "tasks before/after this version are not directly comparable".
PROMPT_TEMPLATE_VERSION = "v2.0.0-minio"
# DynamoDB-backend prompt-template version. Backend-scoped so switching a task
# to the DynamoDB Local backend never perturbs an S3/MinIO task's task_id or
# content_hash (both fold in the template version).
PROMPT_TEMPLATE_VERSION_DDB = "v2.0.0-ddb"


def _prompt_template_version(options: CodeInstructOptions) -> str:
    """Return the prompt-template version for this task's backend.

    MinIO tasks keep the exact ``PROMPT_TEMPLATE_VERSION`` literal so their
    task_id/content_hash stay byte-identical after DynamoDB support lands.
    """
    backend = getattr(options, "cli_app_backend", "minio")
    if backend == "kwok":
        from repo2rlenv.pipelines._cli_app_backends import get_backend

        return get_backend("kwok").prompt_template_version
    if backend == "dynamodb_local":
        return PROMPT_TEMPLATE_VERSION_DDB
    return PROMPT_TEMPLATE_VERSION


# Pinned versions for the verification + runtime container. Used both at
# gauntlet time and in the emitted Harbor task's Dockerfile.
PINNED_DEPS = (
    "pytest==8.3.3",
    "minio==7.2.20",
)
# DynamoDB backend runtime deps. The test-side DynamoDB client is stdlib-only
# (urllib) — there is no independent no-boto SDK to pin, so `minio` is dropped.
PINNED_DEPS_DDB = ("pytest==8.3.3",)

# Grader-side deps installed alongside the vendored golden slice. Botocore +
# s3transfer are NOT here — the slice vendors them under submission/. urllib3
# range is pinned to satisfy awscrt's compat constraint.
GOLDEN_TEST_HARNESS_DEPS_MINIO: tuple[str, ...] = (
    "pytest==8.3.3",
    "freezegun==1.5.1",
    "minio==7.2.20",
)
GOLDEN_TEST_HARNESS_DEPS_DDB: tuple[str, ...] = (
    "pytest==8.3.3",
    "freezegun==1.5.1",
)

# DynamoDB Local sidecar image (public Docker Hub). Emitted as a service in
# the task's docker-compose.yaml so the task container talks to it via
# AWS_ENDPOINT_URL=http://ddb:8000. Digest-pinned for hermetic pulls.
PINNED_DDB_LOCAL_IMAGE = "amazon/dynamodb-local:2.5.4"
PINNED_DDB_LOCAL_DIGEST = "sha256:cf8cebd061f988628c02daff10fdb950a54478feff9c52f6ddf84710fe3c3906"

# Two-stage image: the app layer builds ON TOP of the baked polyglot base
# (raiden-base — C/C++/Go/Rust/Node/Ruby/Java/Python toolchains + curl + the
# aws-cli v2 binary). Override per-build via the Dockerfile's BASE_IMAGE ARG or
# CodeInstructOptions.cli_app_base_image. Pinned by digest for reproducibility.
PINNED_BASE_IMAGE = (
    "426628337772.dkr.ecr.ap-south-1.amazonaws.com/aws_cli_s3@sha256:"
    "6fbab75a878b49c1be2f7ee3f754f563b977adcbd7b6bf2eb7462d424efbef29"
)

# DynamoDB-backend base: polyglot task_env image (Python/Go/Node/JDK21/Ruby/
# PHP/Rust) with awscrt + boto3 deps + pytest baked in. Service-agnostic —
# DynamoDB Local runs as a compose sidecar (see environment/docker-compose.yaml).
PINNED_DDB_BASE_IMAGE = (
    "426628337772.dkr.ecr.ap-south-1.amazonaws.com/aws_cli_dynamodb@sha256:"
    "9ca8d49449e64b5226138ff660ba8c9bbc52c0c8490b9b0fd01f7a95d5d107f2"
)

# DDB Local baked into the GAUNTLET reference-grounding image ONLY.
# The gauntlet runs docker with --network=none, so it cannot reach the compose
# sidecar the shipped emitted tasks talk to. Instead we bake DDB Local into the
# gauntlet image itself and start it via a wrapper script BEFORE test.sh runs,
# reachable at loopback http://127.0.0.1:8000. Shipped emitted tasks continue to
# use the compose sidecar - only the pipeline's ref-grounding gauntlet is patched.
_DDB_GAUNTLET_LAYERS = f"""
# --- DDB Local baked into the gauntlet (loopback endpoint, not the sidecar) ---
COPY --from={PINNED_DDB_LOCAL_IMAGE}@{PINNED_DDB_LOCAL_DIGEST} /home/dynamodblocal/DynamoDBLocal.jar /opt/ddb/DynamoDBLocal.jar
COPY --from={PINNED_DDB_LOCAL_IMAGE}@{PINNED_DDB_LOCAL_DIGEST} /home/dynamodblocal/DynamoDBLocal_lib /opt/ddb/DynamoDBLocal_lib
ENV AWS_ENDPOINT_URL_DYNAMODB=http://127.0.0.1:8000 \\
    AWS_ENDPOINT_URL=http://127.0.0.1:8000
RUN printf '#!/bin/bash\\nset -e\\ncd /opt/ddb\\nnohup java -jar DynamoDBLocal.jar -inMemory -sharedDb -port 8000 > /tmp/ddb.log 2>&1 &\\nfor i in $(seq 1 60); do if bash -c "</dev/tcp/127.0.0.1/8000" 2>/dev/null; then break; fi; sleep 0.1; done\\nexec "$@"\\n' > /usr/local/bin/ddb-wrap && chmod +x /usr/local/bin/ddb-wrap
"""
_DDB_GAUNTLET_WRAPPER = "/usr/local/bin/ddb-wrap"

# MinIO server binary baked into the app layer (arch-aware download, SHA256-pinned
# per arch — the app supports amd64 + arm64). Hashes are the official
# dl.min.io minio.<VERSION>.sha256sum values for this release.
PINNED_MINIO_VERSION = "RELEASE.2025-09-07T16-13-09Z"
PINNED_MINIO_SHA256_AMD64 = "7c5bd8512c6e966455b1d198209358b2d191c77a83ab377c4073281065fb855f"
PINNED_MINIO_SHA256_ARM64 = "5c83cd2cf151717ba0243f73e1c7802ff36e272b67144bdd7f1f7d684fd6f03d"

# OpenHands agent-runtime SDK baked into an isolated venv (harness parity).
PINNED_OPENHANDS_VERSION = "v1.12.0"
PINNED_FASTAPI_VERSION = "0.138.2"
PINNED_GCP_AIPLATFORM_VERSION = "1.158.0"

# aws-cli v2 S3-command dependency closure, pinned to aws-cli/pyproject.toml.
# Installed in the MAIN env so the base image's aws-cli is runnable. There is no
# real conflict with the MinIO SDK (minio declares urllib3 unbounded and runs on
# 1.26.x). urllib3 is pinned down FIRST (clean RECORD-based downgrade of the
# minio-pulled 2.x), then the rest with --ignore-installed so debian-shipped,
# RECORD-less packages are shadowed rather than failing to uninstall.
AWSCLI_DEP_CLOSURE = (
    "colorama>=0.2.5,<0.4.7",
    "docutils>=0.10,<0.20",
    "ruamel.yaml>=0.15.0,<=0.17.21",
    "ruamel.yaml.clib>=0.2.0,<=0.2.12",
    "prompt-toolkit>=3.0.24,<3.0.52",
    "distro>=1.5.0,<1.9.0",
    "awscrt==0.27.6",
    "python-dateutil>=2.1,<=2.9.0",
    "jmespath>=0.7.1,<1.1.0",
)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


TRANSLATION_SYSTEM = """You translate aws-cli white-box tests into black-box pytest tests.

The reference test exercises an aws-cli command via the in-process driver and \
asserts on boto3 operations. Treat it as a STYLE and INTENT reference only — \
write a clean black-box pytest function from scratch that produces the same \
observable behaviour. The S3 backend in this environment is a local MinIO \
server (already running, wired into the `cli` and `s3_client` fixtures via \
conftest.py). Your output must:

1. Do NOT import or reference ANY of the following — these are fatal errors:
   - `boto3` (any form: `import boto3`, `from boto3`, `boto3.client(...)`, \
`boto3.resource(...)`)
   - `botocore` (any form: `import botocore`, `botocore.session`, \
`botocore.exceptions`, `from botocore...`)
   - `moto` (any form, including `@mock_aws`, `from moto`, `ThreadedMotoServer`)
2. Do NOT use boto3 dict-idiom on `s3_client`. The `s3_client` fixture is a \
`minio.Minio` instance, NOT a boto3 client. The following are FORBIDDEN \
because they will raise `TypeError`:
   - `s3_client.create_bucket(Bucket="foo")`           — use `s3_client.make_bucket("foo")`
   - `s3_client.put_object(Bucket="b", Key="k", Body=b"v")` — use \
`s3_client.put_object("b", "k", BytesIO(b"v"), length=1)`
   - `s3_client.list_buckets()["Buckets"]`             — use `list(s3_client.list_buckets())` \
(returns `Bucket` objects with `.name` and `.creation_date`)
   - `s3_client.get_object(Bucket="b", Key="k")["Body"].read()` — use \
`s3_client.get_object("b", "k").read()`
   - `s3_client.head_object(Bucket="b", Key="k")`      — use `s3_client.stat_object("b", "k")` \
(returns `Object` with `.size`, `.etag`, `.last_modified`)
   - `s3_client.delete_object(Bucket="b", Key="k")`    — use `s3_client.remove_object("b", "k")`
   - `s3_client.list_objects_v2(Bucket="b")["Contents"]` — use \
`list(s3_client.list_objects("b", recursive=True))` (returns `Object` items \
with `.object_name`, `.size`)
3. Catch `minio.error.S3Error` for S3 errors (NOT `botocore.exceptions.ClientError`). \
The error has `.code` (e.g. `'NoSuchBucket'`, `'NoSuchKey'`) and `.message`.
4. Invoke the candidate CLI as a subprocess via the `cli` fixture (returns \
`subprocess.CompletedProcess`).
5. Assert on returncode AND on observable side effects (S3 state via the \
`s3_client` Minio instance, or stdout content).
6. Have AT LEAST one non-trivial STATE assertion: query `s3_client` for \
bucket/object existence/contents via SDK methods (`bucket_exists`, \
`stat_object`, `get_object`), OR assert on a specific stderr/stdout substring \
tied to the command's documented output format. A bare \
`assert result.returncode == 0` with no state check is REJECTED — such tests \
pass against an empty stub that just exits 0 (non-discriminative).
7. For happy_path tests: set up the prereq state explicitly inside the test \
(e.g. `s3_client.make_bucket('x')` before testing `rb`). The test must be \
runnable in isolation — do NOT assume other tests ran.
8. Upstream aws-cli alignment (these tests must ALSO pass against real \
aws-cli v2.28+, not just the oracle):
   - Exit codes: NEVER assert `result.returncode == 255` or `== 2` or `== 252`. \
Real aws-cli returns `252` for argparse-style usage errors, `255` for \
internal/network errors, `1` for application errors. For error cases use \
`assert result.returncode != 0` only. The `Expected exit code` field in the \
translation prompt is a CATEGORY hint (0 = success, non-zero = error), not a \
value to assert on when non-zero.
   - Stdout: assert with substring-anywhere semantics (`pattern in result.stdout` \
or `re.search(pattern, result.stdout)`). NEVER `result.stdout.splitlines()[0] == \
pattern` — real aws-cli prints progress lines (`Completed N Bytes(s)...`) BEFORE \
the success line for `cp`/`mv`/`sync`. If you need progress-free output, pass \
`--no-progress`.
   - Error messages: assert on error CATEGORY, not verbatim phrasing. Match a \
stable keyword like `NoSuchBucket`, `NoSuchKey`, `does not exist`, \
`InvalidBucketName`, `AccessDenied`, `usage:` — NOT a full sentence copied \
from the reference test. Two correct implementations may word the same error \
differently.
   - Bucket-name validation: do NOT assert client-side rejection for malformed \
bucket names (e.g. uppercase, `_`, too-short). Real aws-cli defers name \
validation to the server; MinIO does the same. Any bucket-name test must \
exercise the server round-trip and assert on the server response.
   - Fabricated flags: never assert a flag that isn't in the reference test's \
observed argv. In particular, `aws s3 mb` has NO `--tags` flag — do NOT write \
a test that passes `--tags` to `mb`.

If you find yourself wanting to import `boto3` or write `s3_client.X(Bucket=...)`, \
STOP — translate to the Minio SDK equivalent from the mapping above. Boto3 \
imports or dict-idiom in this file is a fatal error.

DO NOT COPY any of the following from the reference test — these are \
white-box harness leakage and will break the black-box contract:
- `self.run_cmd`, `self.assert_params_for_cmd`, `self.operations_called`, \
`self.parsed_responses`, `self.last_kwargs`
- `self.prefix`, `self.files`, `FileCreator`, `BaseAWSCommandParamsTest`, \
`BaseS3TransferCommandTest`
- Imports from `awscli.*` or `awscli.testutils`
- `unittest.TestCase` base class, `setUp` / `tearDown` methods
- Helper invocations such as `self.put_object_request`, `self.head_object_response`
- base64-encoded operation parameter payloads

Output constraints:
- Function name: `test_<command>_<descriptive>` matching the intent
- No fixtures other than `cli`, `s3_client`, `tmp_path` (all provided by conftest)
- Plain `def test_...(...)` with positional fixture args
- If you need to construct request bodies, import `BytesIO` from `io`. The \
`BytesIO` is already imported at module level by the conftest preamble — \
you can import it again in the test for clarity.
- For error-tag intents: assert `result.returncode != 0` AND on a stderr
  substring identifying the error category
- Return ONLY the test function source (no preamble, no surrounding markdown fences)"""


TRANSLATION_USER_TEMPLATE = """Reference white-box test (style + intent only — do NOT copy harness):
```python
{raw_source}
```

Extracted intent:
- Command: aws {command_prefix} {command}
- argv after program name: {cmdline_template}
- Expected exit code: {expected_exit}
- Expected aws-cli observable operations: {expected_state_calls}
- Behaviour tag: {behaviour_tag}

Translate this into a black-box pytest test. The agent's CLI is at \
/workspace/submission/main.py. Use `cli(*argv)` to invoke it (returns \
CompletedProcess). Use `s3_client` (a `minio.Minio` SDK client wired to the \
local MinIO server) to verify state — call methods like `make_bucket`, \
`put_object`, `stat_object`, `list_objects` per the mapping in the system \
prompt. The `expected_state_calls` field above describes the OBSERVABLE \
side-effects in aws-cli terms; translate them into the equivalent Minio SDK \
queries when asserting state."""


ORACLE_SYSTEM = """You write a reference Python implementation of a single aws-cli S3 command.

The S3 backend is a local MinIO server, already running and reachable. Configure your client from env:

  client = Minio(
      os.environ["MINIO_ENDPOINT"],
      access_key=os.environ["MINIO_ACCESS_KEY"],
      secret_key=os.environ["MINIO_SECRET_KEY"],
      secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
  )

Constraints:
- Single file: `submission/main.py`
- Use argparse for argument parsing
- Use the `minio` Python SDK
- Do NOT import boto3, botocore, or moto in any form (including `@mock_aws`)
- Do NOT import `awscli` or shell out to the `aws` binary
- Exit codes: `0` on success, `1` on application error, `252` for argparse-style \
usage errors (invalid flag, missing required arg), `255` for internal errors. \
Prefer argparse's default `SystemExit(2)` or an explicit `sys.exit(252)` for \
usage errors — either `252` or `255` is acceptable to the tests.
- Catch `minio.error.S3Error`; the error has `.code` (e.g. 'NoSuchBucket', 'NoSuchKey') and `.message`
- Match real aws-cli stdout for the success line (e.g. `make_bucket: <name>` for mb, \
`delete: s3://<bucket>/<key>` for rm). You MAY additionally emit progress lines \
before the success line (e.g. `Completed 1024 Bytes(s) with 1 file(s) remaining`), \
or accept a `--no-progress` flag to suppress them — matching real aws-cli's \
optional progress output.
- For `s3 ls` output use `f"{last_modified}  {size:>10}  {key}"` per line
- The MinIO SDK returns typed objects (Bucket/Object with `.name`, `.object_name`, `.size`, `.last_modified`), not dicts
- Do NOT validate bucket names client-side; let the server return `InvalidBucketName`. \
Real aws-cli defers name-format validation to the S3 service.
- Do NOT fabricate flags that don't exist upstream. In particular, `aws s3 mb` \
has NO `--tags` flag — do NOT implement one.

The CLI is invoked as: `python submission/main.py <prefix> <command> [args...]`

Return ONLY the Python source for `submission/main.py` (no preamble, no surrounding markdown fences)."""


ORACLE_USER_TEMPLATE = """Implement `aws {command_prefix} {command}` covering these behaviours:

{behaviours_bulleted}

The implementation should be self-contained and dispatch on argv[1] / argv[2] \
so a single `main.py` can handle multiple commands when extended later. For now, \
focus on the `{command}` subcommand."""


# --- Subset (multi-command) oracle prompts ---

ORACLE_SUBSET_SYSTEM = """You write a reference Python implementation of a SUBSET of \
aws-cli S3 commands as ONE file.

The S3 backend is a local MinIO server, already running and reachable. Configure your client from env:

  client = Minio(
      os.environ["MINIO_ENDPOINT"],
      access_key=os.environ["MINIO_ACCESS_KEY"],
      secret_key=os.environ["MINIO_SECRET_KEY"],
      secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
  )

Constraints:
- Single file: `submission/main.py`
- Parse argv and dispatch on the subcommand (argv[2]) so one program handles \
every requested subcommand
- Use the `minio` Python SDK
- Do NOT import boto3, botocore, or moto in any form (including `@mock_aws`)
- Do NOT import `awscli` or shell out to the `aws` binary
- Exit codes: `0` on success, `1` on application error, `252` for argparse-style \
usage errors (invalid flag, missing required arg), `255` for internal errors. \
Either `252` or `255` is acceptable to the tests for usage errors.
- Catch `minio.error.S3Error`; the error has `.code` (e.g. 'NoSuchBucket', 'NoSuchKey') and `.message`
- Match real aws-cli stdout for the success line (e.g. `make_bucket: <name>` for \
mb, `delete: s3://<bucket>/<key>` for rm, `upload: <src> to <dst>` for cp). You \
MAY additionally emit progress lines before the success line, or accept \
`--no-progress` to suppress them — matching real aws-cli.
- For `s3 ls` output use `f"{last_modified}  {size:>10}  {key}"` per line
- The MinIO SDK returns typed objects (Bucket/Object with `.name`, `.object_name`, `.size`, `.last_modified`), not dicts
- Keep S3 state consistent across subcommands so a sequence like upload -> list -> \
download -> remove behaves correctly end-to-end
- Do NOT validate bucket names client-side; let the server return `InvalidBucketName`. \
Real aws-cli defers name-format validation to the S3 service.
- Do NOT fabricate flags that don't exist upstream. In particular, `aws s3 mb` \
has NO `--tags` flag — do NOT implement one for any subcommand.

The CLI is invoked as: `python submission/main.py <prefix> <command> [args...]`

Return ONLY the Python source for `submission/main.py` (no preamble, no surrounding markdown fences)."""


ORACLE_SUBSET_USER_TEMPLATE = """Implement a single `aws {command_prefix}` CLI supporting \
ALL of these subcommands: {commands_csv}.

It must cover these behaviours (collected across the subcommands):

{behaviours_bulleted}

Dispatch on argv[1] (prefix) / argv[2] (subcommand) so one `main.py` handles every \
listed subcommand, and keep S3 state consistent across them so cross-command workflows \
(upload -> list -> download -> move -> remove -> remove-bucket) behave correctly."""


# --- Cross-command workflow-test prompts (subset tasks) ---

WORKFLOW_SYSTEM = """You write black-box pytest tests that exercise CROSS-COMMAND \
behaviour of a from-scratch `aws s3`-style CLI.

The CLI is a single file at /workspace/submission/main.py, invoked as a subprocess via \
the `cli` fixture: `cli(*argv) -> subprocess.CompletedProcess` (with .returncode, \
.stdout, .stderr). A `minio.Minio` client `s3_client` (pointing at the SAME sandboxed \
MinIO server) and pytest's `tmp_path` are also available as fixtures.

Rules:
1. Use ONLY the fixtures `cli`, `s3_client`, `tmp_path` as test-function arguments. Do \
NOT use any decorator. You may use the standard library plus the `minio` SDK \
(`from minio import Minio`, `from minio.error import S3Error`, `from io import BytesIO`).
2. Do NOT import or reference boto3, botocore, or moto in any form. Do NOT use boto3 \
dict-idiom on `s3_client` (no `Bucket=`, `Key=`, `Body=`, `["Buckets"]`, `["Body"]`, \
`["Contents"]`, etc.). Use Minio SDK call signatures only.
3. Create ALL prerequisite state inside the test (buckets via the CLI or \
`s3_client.make_bucket("name")`, objects via \
`s3_client.put_object("bucket", "key", BytesIO(b"data"), length=len(b"data"))`, \
local files via `tmp_path`). Tests must run in isolation and in any order.
4. After EVERY `cli(...)` step meant to succeed, assert `result.returncode == 0`. For \
steps meant to fail, assert `result.returncode != 0` AND a stderr CATEGORY \
keyword (e.g. `NoSuchBucket`, `NoSuchKey`, `does not exist`, `InvalidBucketName`, \
`AccessDenied`, `usage:`). NEVER assert `returncode == 255` or `== 2` or `== 252` \
— real aws-cli returns `252` for usage errors and `255` for internal errors, \
and either may occur.
5. Assert cross-command invariants on `s3_client` STATE, not on stdout wording:
   - Object presence: iterate `s3_client.list_objects(bucket, recursive=True)` and check \
`obj.object_name`; OR call `s3_client.stat_object(bucket, key)` (raises `S3Error` with \
`.code == 'NoSuchKey'` when absent).
   - Byte-identical content: `s3_client.get_object(bucket, key).read()`.
   - Deletion: assert `S3Error` with `.code == 'NoSuchKey'` from `stat_object`.
   - Bucket presence/absence: iterate `s3_client.list_buckets()` and check `bucket.name` \
or `s3_client.bucket_exists("name")`.
   - When you DO assert on stdout, use substring-anywhere semantics \
(`pattern in result.stdout`) — NEVER `result.stdout.splitlines()[0]`. Real \
aws-cli emits progress lines BEFORE the success line for `cp`/`mv`/`sync`.
6. Each test MUST chain at least TWO different subcommands and include at least one \
assertion that depends on a PRIOR command's effect.
7. Assert only on order-insensitive state (sets of keys, object bytes, bucket existence, \
exit codes) — never on listing order, ETags, or timestamps.
8. Do NOT fabricate flags that don't exist upstream. In particular, `aws s3 mb` \
has NO `--tags` flag — never generate a workflow step that passes `--tags` to \
`mb`. Do NOT assert client-side rejection for malformed bucket names — real \
aws-cli defers name validation to the server.
9. Name each function `test_workflow_<chain>`. Return ONLY the test function source(s) \
(one or more `def test_...`), no preamble, no surrounding markdown fences."""


WORKFLOW_USER_TEMPLATE = """Write {n_workflows} cross-command workflow test function(s) \
for an `aws {command_prefix}` CLI covering ONLY this compatible subset of subcommands: \
{subset_csv}.

Documented per-command and cross-command invariants (the contract you must verify):
{state_models_joined}

Representative argv shapes observed for these commands:
{argv_shapes_bulleted}

Each test must chain at least two different subcommands from {subset_csv} and assert on \
`s3_client` state produced by an earlier command. Cover, where the subset allows: a \
create -> write -> read-back -> delete lifecycle; the cp round-trip identity (upload \
then download is byte-identical); and at least one NEGATIVE chain (e.g. removing a \
non-empty bucket must fail and leave it intact). Use ONLY subcommands from {subset_csv}."""


# ---------------------------------------------------------------------------
# DynamoDB backend prompt variants (raw-HTTP DynamoDB Local, no boto)
# ---------------------------------------------------------------------------


TRANSLATION_SYSTEM_DDB = """You write black-box pytest tests for a from-scratch `aws dynamodb` CLI.

CRITICAL SYNTAX + DISCRIMINATION RULES (violations are REJECTED by the gauntlet):
- ASCII-ONLY Python code. Use hyphen-minus (-), straight quotes ('), (") only. NEVER use em-dash (—, U+2014), en-dash (–), curly quotes (‘’“”), or any non-ASCII punctuation in code, strings, docstrings, or comments. A single em-dash produces SyntaxError.
- COMPLETE code. Return the ENTIRE test function. Every opening string quote, bracket, and paren MUST be closed. Do NOT truncate mid-expression or mid-line.
- For ERROR-case tests: MANDATORY assertion pattern is `assert result.returncode != 0` AND `assert "<ErrorCode>" in result.stderr` where <ErrorCode> is one of `ResourceNotFoundException`, `ResourceInUseException`, `ConditionalCheckFailedException`, `ValidationException`. A bare `assert result.returncode != 0` alone is REJECTED as non-discriminative - the empty stub also exits non-zero.
- For SUCCESS-case tests: `cli(...)` MUST CAUSE the observable state change, then `ddb_client` VERIFIES it AFTER. Pattern: [1] invoke `result = cli(...)`, [2] `assert result.returncode == 0`, [3] assert on state via `ddb_client.<method>(...)` where the state is what cli JUST created/modified. Do NOT set up the asserted state via `ddb_client` BEFORE cli - that makes the test pass against an empty stub (non-discriminative, REJECTED).
  GOOD (cli causes, ddb_client verifies):
    result = cli("dynamodb", "create-table", "--table-name", "Tbl1", "--attribute-definitions", '[{"AttributeName":"pk","AttributeType":"S"}]', "--key-schema", '[{"AttributeName":"pk","KeyType":"HASH"}]', "--provisioned-throughput", '{"ReadCapacityUnits":5,"WriteCapacityUnits":5}')
    assert result.returncode == 0
    assert "Tbl1" in ddb_client.list_tables()["TableNames"]
  BAD (rejected as non-discriminative):
    ddb_client.create_table(TableName="Tbl1", ...)
    cli("dynamodb", "list-tables")
    assert "Tbl1" in ddb_client.list_tables()["TableNames"]

The input is a behavioural SPECIFICATION (operation docs + parameters + modeled \
errors) synthesised from the DynamoDB service model  -  treat it as INTENT only and \
write a clean black-box pytest function from scratch. The DynamoDB backend in this \
environment is a local DynamoDB Local server (already running, wired into the `cli` \
and `ddb_client` fixtures via conftest.py). Your output must:

1. Do NOT import or reference ANY of the following  -  these are fatal errors:
   - `boto3` (any form), `botocore` (any form), `moto` (any form, including \
`@mock_aws`, `ThreadedMotoServer`).
2. Use the `ddb_client` fixture  -  a stdlib raw-HTTP DynamoDB client (NOT boto3). \
Available methods: `create_table`, `delete_table`, `list_tables`, `put_item`, \
`get_item`, `update_item`, `delete_item`, `query`, `reset_all_tables`. Item/Key \
arguments are DynamoDB AttributeValue maps, e.g. `{"pk": {"S": "abc"}, "n": {"N": "5"}}`. \
Helper functions `to_item(dict)`, `from_item(dict)`, `to_av(value)`, `from_av(av)` \
convert between native Python and AttributeValue form  -  import them from `_ddb_http`. \
Return shapes  -  use these EXACT accessors, methods return raw DynamoDB dicts:
   - `list_tables()` -> `{"TableNames": [str, ...]}`. Check membership with \
`name in ddb_client.list_tables()["TableNames"]`  -  NEVER \
`name in ddb_client.list_tables()` (that checks dict keys and is always False).
   - `get_item(TableName, Key)` -> `{"Item": {..AV..}}` when present, or a dict \
WITHOUT an `"Item"` key when absent. Guard with `resp.get("Item")`. \
IMPORTANT: `get_item` RAISES `DDBHTTPError(ResourceNotFoundException)` if the \
table itself does not exist  -  do NOT call it against a table you know is \
absent. To assert a table is absent, use \
`assert name not in ddb_client.list_tables()["TableNames"]` instead.
   - `query(...)` -> `{"Items": [...], "Count": int, "ScannedCount": int, ...}`.
   - `create_table / put_item / update_item / delete_item / delete_table` -> server \
response dict; verify effects with a follow-up read, do not assert on payload shape.
3. Numbers travel as JSON STRINGS on the wire: `{"N": "5"}`, never `{"N": 5}`.
4. Invoke the candidate CLI as a subprocess via the `cli` fixture (returns \
`subprocess.CompletedProcess`); it runs `python /workspace/submission/main.py \
dynamodb <command> ...`. When passing structured parameters, ALWAYS use JSON \
syntax (a JSON string as a single argv token), NEVER aws-cli shorthand. Real \
aws-cli's DynamoDB parameter validator rejects shorthand like \
`AttributeName=pk,AttributeType=S` with `Invalid JSON` (exit 252), so shorthand \
tests fail against the reference `aws` shim. Structured flags:
   - `--attribute-definitions '[{"AttributeName":"pk","AttributeType":"S"}]'`
   - `--key-schema '[{"AttributeName":"pk","KeyType":"HASH"}]'`
   - `--provisioned-throughput '{"ReadCapacityUnits":5,"WriteCapacityUnits":5}'`
   - `--item '{"pk":{"S":"abc"},"n":{"N":"5"}}'`
   - `--key '{"pk":{"S":"abc"}}'`
   - `--expression-attribute-names '{"#s":"status"}'`
   - `--expression-attribute-values '{":v":{"S":"active"}}'`
   - `--attribute-updates`, `--expected`, `--global-secondary-indexes`, \
`--local-secondary-indexes`, `--stream-specification`  -  same rule, JSON only.
5. Assert on returncode AND on observable side effects (DynamoDB state via \
`ddb_client`, or stdout JSON content). Have AT LEAST one non-trivial STATE \
assertion (e.g. `ddb_client.get_item(...)`, `ddb_client.list_tables()`, \
`ddb_client.query(...)`). A bare `assert result.returncode == 0` is REJECTED  -  \
it passes against an empty stub.
6. Set up all prerequisite state inside the test (create the table + seed items \
via `ddb_client` before exercising a read/update/delete). Tests must run in \
isolation and any order; the autouse fixture drops all tables between tests.
7. Upstream aws-cli alignment (these tests must ALSO pass against real \
aws-cli v2.28+):
   - Exit codes: for error cases assert `result.returncode != 0` ONLY. NEVER \
assert `== 255`, `== 254`, `== 252`, or `== 2`. Real aws-cli returns `252` for \
argparse usage errors, `254` for service-modeled errors, `255` for internal errors.
   - stdout: parse structured output with `json.loads`; assert on semantic \
content (keys/values), NEVER on preamble text, key order, or whitespace.
   - Error messages: assert the error-CODE substring in stderr  -  one of \
`ResourceNotFoundException`, `ResourceInUseException`, \
`ConditionalCheckFailedException`, `ValidationException`  -  NOT a verbatim sentence.
   - Table-name validation: do NOT assert client-side rejection of malformed \
names; DynamoDB defers to the server, so exercise the round-trip and accept \
either a non-zero exit or a `ValidationException`/`ResourceNotFoundException`.
   - Fabricated flags: never pass a flag not present in the spec's parameter list.

Output constraints:
- Function name: `test_<command>_<descriptive>` matching the intent.
- No fixtures other than `cli`, `ddb_client`, `tmp_path` (all provided by conftest).
- Plain `def test_...(...)` with positional fixture args; no decorators.
- For error intents: assert `result.returncode != 0` AND on an error-code stderr substring.
- Return ONLY the test function source (no preamble, no markdown fences)."""


TRANSLATION_USER_TEMPLATE_DDB = """Behavioural specification (intent only  -  write a black-box test):
```
{raw_source}
```

Extracted intent:
- Command: aws {command_prefix} {command}
- argv after program name: {cmdline_template}
- Expected exit code: {expected_exit}
- Expected observable operations: {expected_state_calls}
- Behaviour tag: {behaviour_tag}

Translate this into a black-box pytest test. The agent's CLI is invoked via \
`cli(*argv)` (returns CompletedProcess). Use `ddb_client` (a raw-HTTP DynamoDB \
client wired to the local DynamoDB Local server) to set up prerequisites and to \
verify state  -  call methods like `create_table`, `put_item`, `get_item`, `query`, \
`list_tables`. The `expected_state_calls` field names the OBSERVABLE DynamoDB \
operation the command must perform; verify its effect via the equivalent \
`ddb_client` read."""


ORACLE_SYSTEM_DDB = """You write a reference Python implementation of a single aws-cli DynamoDB command.

CRITICAL SYNTAX RULES (violations are REJECTED):
- ASCII-ONLY Python code. Use hyphen-minus (-), straight quotes ('), (") only. NEVER use em-dash (—, U+2014), en-dash (–), curly quotes, or any non-ASCII punctuation in code, strings, docstrings, or comments. A single em-dash produces SyntaxError.
- COMPLETE code. Return the ENTIRE main.py source. Every opening string quote, bracket, and paren MUST be closed. Do NOT truncate mid-expression or mid-line.

The DynamoDB backend is a local DynamoDB Local server, already running and reachable. \
Discover the endpoint from the environment:

  endpoint = os.environ.get("AWS_ENDPOINT_URL_DYNAMODB") or os.environ["AWS_ENDPOINT_URL"]

Speak the DynamoDB JSON wire protocol directly over the standard library:

  - POST to the endpoint with headers:
      Content-Type: application/x-amz-json-1.0
      X-Amz-Target: DynamoDB_20120810.<Operation>   (e.g. DynamoDB_20120810.PutItem)
      Authorization: <any well-formed-but-dummy SigV4 string  -  DynamoDB Local ignores it>
  - Body is the operation's JSON request (TableName, Item, Key, KeySchema, ...).

Constraints:
- Single file: `submission/main.py`; use argparse; dispatch on argv (prefix, command).
- Use ONLY the Python standard library (`urllib.request`, `json`, `base64`, `argparse`, \
`os`, `sys`). Do NOT import boto3, botocore, moto, requests, or any AWS SDK. Do NOT \
import `awscli` or shell out to the `aws` binary.
- AttributeValues: marshal Python values to `{"S":..}` / `{"N":"5"}` (numbers as \
JSON STRINGS) / `{"B":<base64>}` / `{"BOOL":..}` / `{"NULL":true}` / `{"M":..}` / \
`{"L":..}` / `{"SS"|"NS"|"BS":..}`.
- Exit codes: `0` on success; for a client-side/usage error prefer argparse's \
`SystemExit(2)` or `sys.exit(252)`; for a service-modeled error (the server returns \
an `__type` like `...#ResourceNotFoundException`) exit non-zero (254 is idiomatic) \
and print the error code to stderr.
- Parse the server's error `__type` (`com.amazonaws...#ResourceNotFoundException`) and \
surface the trailing code (`ResourceNotFoundException`) in the stderr message.
- On success, print the operation's JSON response to stdout (json.dumps). Do not print \
progress preambles.
- Do NOT validate table names client-side; let the server return `ValidationException` \
/ `ResourceNotFoundException`.
- Do NOT fabricate flags that don't exist upstream.

The CLI is invoked as: `python submission/main.py <prefix> <command> [args...]`

Return ONLY the Python source for `submission/main.py` (no preamble, no markdown fences)."""


ORACLE_USER_TEMPLATE_DDB = """Implement `aws {command_prefix} {command}` covering these behaviours:

{behaviours_bulleted}

The command accepts these CLI flags (from the upstream botocore service model):
{flags_bulleted}

You MUST accept and marshal EVERY flag listed above into the corresponding DynamoDB \
request field (kebab-case flag -> PascalCase field: `--table-name` -> `TableName`, \
`--provisioned-throughput` -> `ProvisionedThroughput`, `--billing-mode` -> `BillingMode`, \
etc.). Do NOT hardcode any request field that has a corresponding flag; the caller \
supplies its value at invocation. Reject any flag NOT in the list above with a usage error.

Dispatch on argv[1] (prefix) / argv[2] (subcommand) so a single `main.py` can handle \
multiple commands when extended later. For now, focus on the `{command}` subcommand."""


ORACLE_SUBSET_SYSTEM_DDB = """You write a reference Python implementation of a SUBSET of \
aws-cli DynamoDB commands as ONE file.

CRITICAL SYNTAX RULES (violations are REJECTED):
- ASCII-ONLY Python code. Use hyphen-minus (-), straight quotes ('), (") only. NEVER use em-dash (—, U+2014), en-dash (–), curly quotes, or any non-ASCII punctuation in code, strings, docstrings, or comments. A single em-dash produces SyntaxError.
- COMPLETE code. Return the ENTIRE main.py source. Every opening string quote, bracket, and paren MUST be closed. Do NOT truncate mid-expression or mid-line.

The DynamoDB backend is a local DynamoDB Local server, already running and reachable. \
Discover the endpoint from the environment:

  endpoint = os.environ.get("AWS_ENDPOINT_URL_DYNAMODB") or os.environ["AWS_ENDPOINT_URL"]

Speak the DynamoDB JSON wire protocol directly over the standard library (POST with \
`Content-Type: application/x-amz-json-1.0` and `X-Amz-Target: DynamoDB_20120810.<Op>`, \
plus a dummy SigV4 `Authorization` header that DynamoDB Local ignores).

Constraints:
- Single file: `submission/main.py`; parse argv and dispatch on the subcommand (argv[2]) \
so one program handles every requested subcommand.
- Use ONLY the Python standard library. Do NOT import boto3, botocore, moto, requests, \
any AWS SDK, or `awscli`; do NOT shell out to the `aws` binary.
- AttributeValues marshalled as `{"S":..}` / `{"N":"5"}` (numbers as JSON STRINGS) / \
`{"B":<base64>}` / `{"BOOL":..}` / `{"NULL":true}` / `{"M":..}` / `{"L":..}` / \
`{"SS"|"NS"|"BS":..}`.
- Keep DynamoDB state consistent across subcommands so a sequence like create-table -> \
put-item -> get-item -> query -> delete-item behaves correctly end-to-end.
- Exit codes: `0` success; `252` (or argparse `SystemExit(2)`) for usage errors; non-zero \
(254 idiomatic) for service-modeled errors, with the error code surfaced on stderr.
- Do NOT validate table names client-side; let the server reject them. Do NOT fabricate \
flags that don't exist upstream.

The CLI is invoked as: `python submission/main.py <prefix> <command> [args...]`

Return ONLY the Python source for `submission/main.py` (no preamble, no markdown fences)."""


ORACLE_SUBSET_USER_TEMPLATE_DDB = """Implement a single `aws {command_prefix}` CLI supporting \
ALL of these subcommands: {commands_csv}.

It must cover these behaviours (collected across the subcommands):

{behaviours_bulleted}

Each subcommand accepts EXACTLY these CLI flags (from the upstream botocore service \
model). You MUST accept and marshal EVERY flag listed for a subcommand into the \
corresponding DynamoDB request field (kebab-case flag -> PascalCase field: \
`--table-name` -> `TableName`, `--provisioned-throughput` -> `ProvisionedThroughput`, \
`--billing-mode` -> `BillingMode`, `--attribute-updates` -> `AttributeUpdates`, etc.). \
Do NOT hardcode any request field that has a corresponding flag; the caller supplies \
its value at invocation. Reject any flag NOT listed for its subcommand with a usage error:

{flags_per_command}

Dispatch on argv[1] (prefix) / argv[2] (subcommand) so one `main.py` handles every listed \
subcommand, and keep DynamoDB state consistent across them so cross-command workflows \
(create-table -> put-item -> get-item -> query -> update-item -> delete-item) behave \
correctly."""


WORKFLOW_SYSTEM_DDB = """You write black-box pytest tests that exercise CROSS-COMMAND \
behaviour of a from-scratch `aws dynamodb`-style CLI.

CRITICAL SYNTAX + DISCRIMINATION RULES (violations are REJECTED by the gauntlet):
- ASCII-ONLY Python code. Use hyphen-minus (-), straight quotes ('), (") only. NEVER use em-dash (—, U+2014), en-dash (–), curly quotes (‘’“”), or any non-ASCII punctuation in code, strings, docstrings, or comments. A single em-dash produces SyntaxError.
- COMPLETE code. Return the ENTIRE test function. Every opening string quote, bracket, and paren MUST be closed. Do NOT truncate mid-expression or mid-line.
- For ERROR-case tests: MANDATORY assertion pattern is `assert result.returncode != 0` AND `assert "<ErrorCode>" in result.stderr` where <ErrorCode> is one of `ResourceNotFoundException`, `ResourceInUseException`, `ConditionalCheckFailedException`, `ValidationException`. A bare `assert result.returncode != 0` alone is REJECTED as non-discriminative - the empty stub also exits non-zero.
- For SUCCESS-case tests: `cli(...)` MUST CAUSE the observable state change, then `ddb_client` VERIFIES it AFTER. Pattern: [1] invoke `result = cli(...)`, [2] `assert result.returncode == 0`, [3] assert on state via `ddb_client.<method>(...)` where the state is what cli JUST created/modified. Do NOT set up the asserted state via `ddb_client` BEFORE cli - that makes the test pass against an empty stub (non-discriminative, REJECTED).
  GOOD (cli causes, ddb_client verifies):
    result = cli("dynamodb", "create-table", "--table-name", "Tbl1", "--attribute-definitions", '[{"AttributeName":"pk","AttributeType":"S"}]', "--key-schema", '[{"AttributeName":"pk","KeyType":"HASH"}]', "--provisioned-throughput", '{"ReadCapacityUnits":5,"WriteCapacityUnits":5}')
    assert result.returncode == 0
    assert "Tbl1" in ddb_client.list_tables()["TableNames"]
  BAD (rejected as non-discriminative):
    ddb_client.create_table(TableName="Tbl1", ...)
    cli("dynamodb", "list-tables")
    assert "Tbl1" in ddb_client.list_tables()["TableNames"]

The CLI is a single file at /workspace/submission/main.py, invoked as a subprocess via \
the `cli` fixture: `cli(*argv) -> subprocess.CompletedProcess`. A raw-HTTP DynamoDB \
client `ddb_client` (pointing at the SAME sandboxed DynamoDB Local server) and pytest's \
`tmp_path` are also available as fixtures.

Rules:
1. Use ONLY the fixtures `cli`, `ddb_client`, `tmp_path` as test-function arguments; no \
decorators. You may use the standard library and import the marshaling helpers \
(`from _ddb_http import to_item, from_item, to_av, from_av`).
2. Do NOT import or reference boto3, botocore, or moto in any form.
3. Create ALL prerequisite state inside the test (tables + items via the CLI or via \
`ddb_client.create_table(...)` / `ddb_client.put_item(...)`). Tests must run in isolation \
and any order. Every symbol you reference MUST be defined in this file or imported from \
`_ddb_http` (`to_item, from_item, to_av, from_av`). Do NOT call helpers like \
`_make_table`, `_setup`, `_create_table`, `make_table`, etc.  -  they do NOT exist and \
will fail with `NameError`. Inline the `create_table` call every time.
4. After EVERY `cli(...)` step meant to succeed, assert `result.returncode == 0`. For \
steps meant to fail, assert `result.returncode != 0` AND an error-code stderr keyword \
(`ResourceNotFoundException`, `ResourceInUseException`, `ConditionalCheckFailedException`, \
`ValidationException`). NEVER assert `returncode == 255` / `== 254` / `== 252` / `== 2`.
5. Assert cross-command invariants on `ddb_client` STATE, not on stdout wording:
   - Item presence/content: `ddb_client.get_item(TableName=t, Key={...})` returns `{"Item": ..}` \
(absent when the key does not exist); `from_item(resp["Item"])` gives native Python.
   - Table presence/absence: `ddb_client.list_tables()["TableNames"]`.
   - Query results: `ddb_client.query(...)["Items"]`  -  compare as an order-insensitive set/multiset.
   - Numbers are JSON strings (`{"N": "5"}`).
6. Each test MUST chain at least TWO different subcommands and include at least one \
assertion that depends on a PRIOR command's effect.
7. Assert only on order-insensitive state (item bytes, key sets, table existence, exit \
codes)  -  never on listing order or timestamps.
8. Do NOT fabricate flags that don't exist upstream. Do NOT assert client-side rejection \
of malformed table names  -  DynamoDB defers name validation to the server.
9. When passing structured parameters to `cli(...)`, ALWAYS use JSON syntax (a JSON \
string as a single argv token), NEVER aws-cli shorthand. Real aws-cli's DynamoDB \
parameter validator rejects shorthand like `AttributeName=pk,AttributeType=S` with \
`Invalid JSON` (exit 252), so shorthand tests fail against the reference `aws` shim. \
Structured flags:
   - `--attribute-definitions '[{"AttributeName":"pk","AttributeType":"S"}]'`
   - `--key-schema '[{"AttributeName":"pk","KeyType":"HASH"}]'`
   - `--provisioned-throughput '{"ReadCapacityUnits":5,"WriteCapacityUnits":5}'`
   - `--item '{"pk":{"S":"abc"},"n":{"N":"5"}}'`
   - `--key '{"pk":{"S":"abc"}}'`
   - `--expression-attribute-names '{"#s":"status"}'`
   - `--expression-attribute-values '{":v":{"S":"active"}}'`
   - `--attribute-updates`, `--expected`, `--global-secondary-indexes`, \
`--local-secondary-indexes`, `--stream-specification`  -  same rule, JSON only.
10. Name each function `test_workflow_<chain>`. Return ONLY the test function source(s), \
no preamble, no markdown fences."""


WORKFLOW_USER_TEMPLATE_DDB = """Write {n_workflows} cross-command workflow test function(s) \
for an `aws {command_prefix}` CLI covering ONLY this compatible subset of subcommands: \
{subset_csv}.

Documented per-command and cross-command invariants (the contract you must verify):
{state_models_joined}

Representative argv shapes observed for these commands:
{argv_shapes_bulleted}

Each test must chain at least two different subcommands from {subset_csv} and assert on \
`ddb_client` state produced by an earlier command. Cover, where the subset allows: a \
create-table -> put-item -> get-item read-back lifecycle; a put-item then update-item \
then get-item mutation; a query after seeding multiple items; and at least one NEGATIVE \
chain (e.g. get-item / put-item against a missing table must fail with \
`ResourceNotFoundException`). Use ONLY subcommands from {subset_csv}."""


# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------


class _TaskRejected(Exception):
    """Raised internally to short-circuit a task build with a logged reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _try_emit_task(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    cmd_specs: list[CommandSpec],
    intents: list[TestIntent],
    out_dir: Path,
    intent_idx: int | None,
    label: str,
    skip_reasons: dict[str, int],
    source_root: Path | None = None,
    model: dict | None = None,
) -> Path | None:
    """Attempt to build and emit one task. Returns task_path on success, None on skip."""
    try:
        return _build_one_task(
            pipeline=pipeline,
            options=options,
            spec=spec,
            cmd_specs=cmd_specs,
            intents=intents,
            out_dir=out_dir,
            intent_idx=intent_idx,
            source_root=source_root,
            model=model,
        )
    except _TaskRejected as exc:
        skip_reasons[exc.reason] = skip_reasons.get(exc.reason, 0) + 1
        pipeline._emit_progress(label, "skip", exc.reason)
        return None
    except Exception as exc:
        logger.exception("cli_app: task synthesis failed for %s: %s", label, exc)
        skip_reasons["synthesis_error"] = skip_reasons.get("synthesis_error", 0) + 1
        pipeline._emit_progress(label, "skip", f"synthesis_error: {exc}")
        return None


def _resolve_target_ops(options: CodeInstructOptions) -> tuple[str, ...]:
    """CamelCase operation names to lift in botocore_model mode."""
    if options.cli_app_target_operations:
        return tuple(options.cli_app_target_operations)
    profile = resolve_profile(options.cli_app_backend)
    if profile is not None and profile.default_target_ops:
        return profile.default_target_ops
    return _DDB_TARGET_OPS_DEFAULT


def _extract_intents_for(
    command: str,
    *,
    spec: CliSpec,
    tests_dir_path: Path,
    options: CodeInstructOptions,
    model: dict | None,
) -> list[TestIntent]:
    """Extract intents for one command, dispatching on the extraction mode.

    ``model`` (a parsed service-2.json) is required for botocore_model mode;
    tests mode falls back to the aws-cli white-box test corpus (S3 path).
    ``cli_app_backend='kwok'`` routes to the kubectl_cobra_yaml source instead.
    """
    if options.cli_app_backend == "kwok":
        from repo2rlenv.pipelines._cli_app_backends.source.base import get_source

        return get_source("kubectl_cobra_yaml").extract_intents(
            spec,
            command,
            max_intents=options.cli_app_max_intents,
        )
    if options.cli_app_extract_mode == "botocore_model" and model is not None:
        return synthesize_intents_from_model(
            model,
            command,
            spec.command_prefix,
            target_operations=_resolve_target_ops(options),
            max_intents=options.cli_app_max_intents,
            combinations=_is_generic_backend(options) and options.cli_app_combinations,
            max_optional_combos=options.cli_app_max_optional_combos,
            mutually_exclusive=_parse_mutually_exclusive(options),
        )
    return extract_test_intents(
        tests_dir_path,
        spec,
        command_filter=command,
        max_intents=options.cli_app_max_intents,
    )


def _run_subset_mode(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    subsets: list[str],
    tests_dir_path: Path,
    out_dir: Path,
    owner_name: str,
    skip_reasons: dict[str, int],
    model: dict | None = None,
    source_root: Path | None = None,
) -> tuple[int, int]:
    """Process subset specs. Returns (candidates_seen, emitted)."""
    candidates_seen = 0
    emitted = 0
    by_name = {c.name: c for c in spec.commands}

    for raw in subsets:
        if emitted >= options.limit:
            logger.info("cli_app: limit=%d reached", options.limit)
            break
        # dedupe while preserving order (a repeated command would bloat the
        # slug/keywords and double the translation cost)
        names = list(dict.fromkeys(n.strip() for n in raw.split(",") if n.strip()))
        missing = [n for n in names if n not in by_name]
        if missing:
            logger.warning(
                "cli_app: subset %r references unknown commands %s (available: %s)",
                raw,
                missing,
                sorted(by_name),
            )
        group = [by_name[n] for n in names if n in by_name]
        candidates_seen += 1
        slug = "+".join(sorted(c.name for c in group))
        label = f"{owner_name}:{slug or raw}"
        if len(group) < 2:
            skip_reasons["subset_too_small"] = skip_reasons.get("subset_too_small", 0) + 1
            pipeline._emit_progress(label, "skip", "subset_too_small")
            continue
        intents: list[TestIntent] = []
        for c in group:
            intents.extend(
                _extract_intents_for(
                    c.name,
                    spec=spec,
                    tests_dir_path=tests_dir_path,
                    options=options,
                    model=model,
                )
            )
        logger.info(
            "cli_app: subset %s -> %d intents across %d commands",
            slug,
            len(intents),
            len(group),
        )
        if not intents:
            skip_reasons["no_intents_extracted"] = skip_reasons.get("no_intents_extracted", 0) + 1
            pipeline._emit_progress(label, "skip", "no_intents_extracted")
            continue
        task_path = _try_emit_task(
            pipeline=pipeline,
            options=options,
            spec=spec,
            cmd_specs=group,
            intents=intents,
            out_dir=out_dir,
            intent_idx=None,
            label=label,
            skip_reasons=skip_reasons,
            source_root=source_root,
            model=model,
        )
        if task_path is not None:
            emitted += 1
            logger.info("cli_app: emitted %s", task_path.name)
            pipeline._emit_progress(task_path.name, "emit")

    return candidates_seen, emitted


def _run_per_command_mode(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    target_commands: list[CommandSpec],
    tests_dir_path: Path,
    out_dir: Path,
    owner_name: str,
    skip_reasons: dict[str, int],
    model: dict | None = None,
    source_root: Path | None = None,
) -> tuple[int, int]:
    """Process per-command (or per-intent) mode. Returns (candidates_seen, emitted)."""
    candidates_seen = 0
    emitted = 0

    for cmd_spec in target_commands:
        if emitted >= options.limit:
            logger.info("cli_app: limit=%d reached", options.limit)
            break
        intents = _extract_intents_for(
            cmd_spec.name,
            spec=spec,
            tests_dir_path=tests_dir_path,
            options=options,
            model=model,
        )
        logger.info("cli_app: extracted %d intents for command=%s", len(intents), cmd_spec.name)
        if not intents:
            candidates_seen += 1
            skip_reasons["no_intents_extracted"] = skip_reasons.get("no_intents_extracted", 0) + 1
            pipeline._emit_progress(f"{owner_name}:{cmd_spec.name}", "skip", "no_intents_extracted")
            continue

        # per-intent: each intent becomes a separate task (shared oracle via cache);
        # per-command: all intents bundled into one task
        slices: list[tuple[int | None, list[TestIntent]]] = (
            [(i, [intent]) for i, intent in enumerate(intents)]
            if options.cli_app_per_intent
            else [(None, intents)]
        )
        for intent_idx, intent_slice in slices:
            if emitted >= options.limit:
                break
            candidates_seen += 1
            label = (
                f"{owner_name}:{cmd_spec.name}#i{intent_idx:02d}"
                if intent_idx is not None
                else f"{owner_name}:{cmd_spec.name}"
            )
            task_path = _try_emit_task(
                pipeline=pipeline,
                options=options,
                spec=spec,
                cmd_specs=[cmd_spec],
                intents=intent_slice,
                out_dir=out_dir,
                intent_idx=intent_idx,
                label=label,
                skip_reasons=skip_reasons,
                source_root=source_root,
                model=model,
            )
            if task_path is not None:
                emitted += 1
                logger.info("cli_app: emitted %s", task_path.name)
                pipeline._emit_progress(task_path.name, "emit")

    return candidates_seen, emitted


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _is_generic_backend(options: CodeInstructOptions) -> bool:
    """True for a generic model-sidecar service (``build_compose_overlay`` set), False for
    the byte-locked ``dynamodb_local`` / ``minio`` baselines. Every plug-and-play
    auto-feature (auto-scope, auto-subsets, coverage matrix, anti-hack) gates on this so
    the finalized DDB / S3 output stays byte-identical."""
    profile = resolve_profile(options.cli_app_backend)
    return profile is not None and profile.build_compose_overlay is not None


def _parse_mutually_exclusive(options: CodeInstructOptions) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(f.strip() for f in entry.split(",") if f.strip())
        for entry in (options.cli_app_mutually_exclusive or [])
    )


def _effective_antihack_mode(options: CodeInstructOptions) -> str:
    """Resolve the anti-hack scan mode: 'reject' | 'log' | 'off'.

    Explicit off/log/reject wins. None auto-selects 'reject' for generic sidecar
    backends and 'log' for the byte-locked dynamodb_local / minio, so those paths are
    scanned for telemetry but never rejected (their output stays byte-identical).
    """
    mode = options.cli_app_antihack_scan
    if mode is not None:
        return mode
    return "reject" if _is_generic_backend(options) else "log"


def _apply_auto_scope(spec: CliSpec, options: CodeInstructOptions) -> CliSpec:
    """Narrow a broad generic-service surface to a coherent lifecycle subset.

    Applies ONLY to a generic sidecar profile (``build_compose_overlay`` set) that did
    NOT curate its own ``default_target_ops`` and exposes more commands than
    ``cli_app_scope_max_commands``. The byte-locked ``dynamodb_local`` / ``minio``
    backends, and any profile that curated its ops, are returned unchanged so existing
    output stays byte-identical. Explicit user scoping (``cli_app_command`` /
    ``cli_app_target_operations`` / ``cli_app_subsets``) always wins. Recomputes
    ``spec_sha256`` so content-addressing reflects the scoped command set.
    """
    if options.cli_app_command or options.cli_app_target_operations or options.cli_app_subsets:
        return spec
    profile = resolve_profile(options.cli_app_backend)
    if profile is None or profile.build_compose_overlay is None or profile.default_target_ops:
        return spec
    cap = options.cli_app_scope_max_commands
    names = [c.name for c in spec.commands]
    if cap <= 0 or len(names) <= cap:
        return spec
    scope = select_lifecycle_scope(names, max_commands=cap) or sorted(names)[:cap]
    keep = set(scope)
    spec.commands = [c for c in spec.commands if c.name in keep]
    spec.spec_sha256 = _canonical_spec_hash(spec)
    logger.warning(
        "cli_app: %s exposes %d commands (> scope cap %d); auto-scoped to %s. "
        "Override with cli_app_target_operations.",
        spec.command_prefix,
        len(names),
        cap,
        sorted(keep),
    )
    return spec


def run_cli_app_pipeline(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    out_dir: Path,
) -> PipelineResult:
    """Top-level entry point called from CodeInstructPipeline.run()."""
    out_dir.mkdir(parents=True, exist_ok=True)

    if not options.cli_app_command_prefix:
        raise ValueError(
            "cli_app mode requires --pipeline-opt cli_app_command_prefix=<prefix> "
            "(e.g. 's3' for `aws s3 *`)"
        )

    if resolve_profile(options.cli_app_backend) is None:
        raise ValueError(
            f"cli_app_backend={options.cli_app_backend!r} is not a registered ServiceProfile; "
            f"registered backends: {list(registered_backends())}"
        )

    token = resolve_github_token(pipeline.input.repo, pipeline.input.auth)
    owner, name = pipeline.input.repo.owner_name
    owner_name = f"{owner}/{name}"
    skip_reasons: dict[str, int] = {}

    if owner_name.lower() == "aws/aws-cli" and pipeline.input.repo.ref not in (
        "v2",
        "2.28.23",
    ):
        raise ValueError(
            f"cli_app mode for aws/aws-cli requires --ref v2 or 2.28.23 (got {pipeline.input.repo.ref!r}); "
            f"the gauntlet's reference oracle is aws-cli v{PINNED_AWSCLI_VERSION}, so the "
            "source tests must come from a compatible branch/tag."
        )

    with tempfile.TemporaryDirectory(prefix="r2e-cli-app-") as tmp:
        clone_dir = Path(tmp) / "repo"
        logger.info("cli_app: cloning %s at %s", owner_name, pipeline.input.repo.ref)
        try:
            _shallow_clone_at_ref(
                pipeline.input.repo.url, pipeline.input.repo.ref, token, clone_dir, depth=1
            )
        except Exception as exc:
            raise RuntimeError(f"failed to clone {pipeline.input.repo.url}: {exc}") from exc

        git_sha = _resolve_git_sha(clone_dir)

        model: dict | None = None
        if options.cli_app_backend == "kwok":
            from repo2rlenv.pipelines._cli_app_backends.source.base import get_source

            _yaml_override = getattr(options, "cli_app_kubectl_yaml_bundle_path", None)
            _yaml_kwargs = {"yaml_bundle_path": _yaml_override} if _yaml_override else {}
            spec = get_source("kubectl_cobra_yaml").extract_spec(
                clone_dir,
                options.cli_app_command_prefix,
                repo=owner_name,
                git_sha=git_sha,
                **_yaml_kwargs,
            )
        elif options.cli_app_extract_mode == "botocore_model":
            spec, model = extract_cli_spec_from_model(
                clone_dir,
                options.cli_app_command_prefix,
                repo=owner_name,
                git_sha=git_sha,
                target_operations=_resolve_target_ops(options),
                model_path_override=options.cli_app_service_model_override,
            )
        else:
            spec = extract_cli_spec(
                clone_dir,
                options.cli_app_command_prefix,
                repo=owner_name,
                git_sha=git_sha,
                entry_point_override=options.cli_app_entry_point_override,
                tests_dir_override=options.cli_app_tests_dir_override,
            )
        logger.info(
            "cli_app: discovered %d commands under prefix=%s (entry_point=%s, tests_dir=%s)",
            len(spec.commands),
            spec.command_prefix,
            spec.entry_point,
            spec.tests_dir,
        )

        spec = _apply_auto_scope(spec, options)

        target_commands: list[CommandSpec] = (
            [c for c in spec.commands if c.name == options.cli_app_command]
            if options.cli_app_command
            else list(spec.commands)
        )
        if not target_commands:
            raise RuntimeError(
                f"cli_app: no commands matched cli_app_command={options.cli_app_command!r}. "
                f"Available: {[c.name for c in spec.commands]}"
            )

        tests_dir_path = clone_dir / spec.tests_dir
        subsets = options.cli_app_subsets
        if not subsets and options.cli_app_auto_subsets and _is_generic_backend(options):
            subsets = sample_subsets(
                target_commands,
                min_size=options.cli_app_subset_min_commands,
                max_size=options.cli_app_subset_max_commands,
                max_subsets=options.cli_app_max_subsets,
                tiers=options.cli_app_subset_tiers,
            )
            if not subsets:
                # Surface smaller than the >=6-command window: fall back to the default
                # sizing so small generic services still emit multi-command tasks.
                subsets = sample_subsets(
                    target_commands,
                    max_subsets=options.cli_app_max_subsets,
                    tiers=options.cli_app_subset_tiers,
                )
        if subsets:
            candidates_seen, emitted = _run_subset_mode(
                pipeline=pipeline,
                options=options,
                spec=spec,
                subsets=subsets,
                tests_dir_path=tests_dir_path,
                out_dir=out_dir,
                owner_name=owner_name,
                skip_reasons=skip_reasons,
                model=model,
                source_root=clone_dir,
            )
        else:
            candidates_seen, emitted = _run_per_command_mode(
                pipeline=pipeline,
                options=options,
                spec=spec,
                target_commands=target_commands,
                tests_dir_path=tests_dir_path,
                out_dir=out_dir,
                owner_name=owner_name,
                skip_reasons=skip_reasons,
                model=model,
                source_root=clone_dir,
            )

    return PipelineResult(
        candidates=candidates_seen,
        emitted=emitted,
        skipped=sum(skip_reasons.values()),
        out_dir=out_dir,
        skip_reasons=skip_reasons,
    )


_ORACLE_CACHE: dict[str, str] = {}


def _resolve_platforms(options: CodeInstructOptions) -> list[str]:
    if options.cli_app_platforms:
        return list(options.cli_app_platforms)
    return ["linux/amd64", "linux/arm64"]


def _resolve_ecr_profile(options: CodeInstructOptions) -> str | None:
    if options.cli_app_ecr_profile:
        return options.cli_app_ecr_profile
    return os.environ.get("R2E_ECR_PROFILE")


def _safe_repo_segment(s: str) -> str:
    safe = re.sub(r"[^a-z0-9._/-]", "-", s.lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "x"


def _build_and_push_task_image(
    *,
    registry: str,
    profile: str | None,
    platforms: list[str],
    owner_name: str,
    task_slug: str,
    uid: str,
    aux_files: dict[str, str],
    test_script: str,
    dockerfile: str,
) -> str:
    repo_segment = f"{_safe_repo_segment(owner_name)}__{_safe_repo_segment(task_slug)}"
    image_ref = f"{registry}/{repo_segment}:{uid}"
    if manifest_exists(image_ref):
        logger.info("cli_app: ECR image already exists, skipping build: %s", image_ref)
        return image_ref
    region = parse_ecr_region(registry)
    if region is None:
        raise _TaskRejected(f"cli_app_ecr_unsupported_registry_{registry}")
    ensure_ecr_repository(image_ref, profile=profile)
    ensure_docker_login_ecr(registry, region, profile=profile)
    with tempfile.TemporaryDirectory() as ctx:
        ctx_path = Path(ctx)
        (ctx_path / "Dockerfile").write_text(dockerfile)
        for rel, content in aux_files.items():
            target = ctx_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        tests_dir = ctx_path / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test.sh").write_text(test_script)
        logger.info("cli_app: pushing multi-arch image to ECR: %s", image_ref)
        build_and_push_multiarch(context_dir=ctx_path, image_ref=image_ref, platforms=platforms)
    return image_ref


def _compute_cliapp_task_id(
    *,
    spec: CliSpec,
    cmd_slug: str,
    id_slug: str,
    intent_idx: int | None,
    intents: list[TestIntent],
    prompt_version: str = PROMPT_TEMPLATE_VERSION,
) -> str:
    """Derive task_id from spec sha + command + prompt version (+ intent_idx).

    ``prompt_version`` is backend-scoped by the caller; MinIO tasks pass the
    default ``PROMPT_TEMPLATE_VERSION`` so their task_id stays byte-identical.
    """
    h = hashlib.sha256()
    h.update(spec.spec_sha256.encode())
    h.update(b"\0")
    h.update(cmd_slug.encode())
    h.update(b"\0")
    h.update(prompt_version.encode())
    if intent_idx is not None:
        h.update(b"\0")
        h.update(f"i{intent_idx:02d}".encode())
        if intents:
            h.update(b"\0")
            h.update(intents[0].test_name.encode())
        idx_suffix = f"-i{intent_idx:02d}"
    else:
        idx_suffix = ""
    return f"{spec.name}-cliapp-{id_slug}{idx_suffix}-{h.hexdigest()[:10]}"


def _apply_static_gauntlet(
    test_files: dict[str, str],
    *,
    behaviour_tags: dict[str, str] | None = None,
    forbid_skips: bool = False,
    backend_name: str | None = None,
    source_name: str | None = None,
) -> dict[str, str]:
    """Gauntlet G1-G2 (cheap, no Docker). Returns survivors; raises if none survive."""
    survivors: dict[str, str] = {}
    for fname, code in test_files.items():
        tag = behaviour_tags.get(fname) if behaviour_tags else None
        ok, reason = _gauntlet_static(
            code,
            expected_behaviour_tag=tag,
            forbid_skips=forbid_skips,
            backend_name=backend_name,
            source_name=source_name,
        )
        if ok:
            survivors[fname] = code
        else:
            logger.info("gauntlet reject %s: %s", fname, reason)
    if not survivors:
        raise _TaskRejected("all_tests_failed_static_gauntlet")
    return survivors


def _apply_reference_grounding(
    *,
    options: CodeInstructOptions,
    dockerfile: str,
    conftest: str,
    test_files: dict[str, str],
    test_script: str,
    oracle_code: str,
    extra_tests_aux: dict[str, str] | None = None,
    pipeline: CodeInstructPipeline | None = None,
    profile: ServiceProfile | None = None,
) -> tuple[dict, dict[str, str], str]:
    """Filter tests via real-aws + oracle reference. Returns (result, filtered_test_files,
    effective_oracle_code). Ships tests that both the real CLI and the LLM oracle pass
    (minus the empty stub) so Harbor's oracle-reference scoring is 1.0 by construction.

    ``extra_tests_aux`` carries backend helper modules (e.g. tests/_ddb_http.py)
    that the conftest imports; without them the grounding bundle can't collect.
    """
    tests_aux = {"tests/conftest.py": conftest, "tests/__init__.py": ""}
    if extra_tests_aux:
        tests_aux.update(extra_tests_aux)
    for fname, code in test_files.items():
        tests_aux[f"tests/{fname}"] = code

    reference_grounding = _run_reference_grounding(
        dockerfile_content=dockerfile,
        tests_aux=tests_aux,
        test_script=test_script,
        oracle_code=oracle_code,
        timeout_sec=options.cli_app_docker_timeout_sec,
        backend=options.cli_app_backend,
    )
    if reference_grounding.get("skipped"):
        raise _TaskRejected("reference_grounding_unavailable")

    grounded = reference_grounding["grounded_files"]
    logger.info(
        "reference grounding: %d ref-pass & %d oracle-pass -> %d grounded "
        "(empty-stub passed %d of all)",
        reference_grounding["n_reference"],
        reference_grounding["n_oracle"],
        len(grounded),
        reference_grounding["n_empty"],
    )
    if len(grounded) < options.cli_app_min_grounded_tests:
        raise _TaskRejected(f"reference_grounding_insufficient_tests_{len(grounded)}")
    test_files = {f: c for f, c in test_files.items() if f in grounded}
    return reference_grounding, test_files, oracle_code


def _run_g3g4_gauntlet_gate(
    *,
    options: CodeInstructOptions,
    dockerfile: str,
    aux_files: dict[str, str],
    test_script: str,
    oracle_code: str,
    task_id: str = "",
    oracle_go_files: dict[str, str] | None = None,
) -> dict:
    """Gauntlet G3 (empty-stub-fails) + G4 (oracle-passes). Raises on non-discriminative.

    ``task_id`` is logged with each kwok verdict so failed runs can be traced
    back to their originating task. ``oracle_go_files`` and ``command_prefix``
    forward kwok-specific artefacts through the docker gauntlet runner.
    """
    runner_kwargs: dict = dict(
        dockerfile_content=dockerfile,
        aux_files=aux_files,
        test_script=test_script,
        oracle_code=oracle_code,
        empty_max=options.cli_app_docker_empty_pass_max,
        oracle_min=options.cli_app_docker_oracle_pass_min,
        timeout_sec=options.cli_app_docker_timeout_sec,
        backend=options.cli_app_backend,
    )
    try:
        gauntlet_g34 = _run_docker_gauntlet_g3g4(
            **runner_kwargs,
            oracle_go_files=oracle_go_files,
            command_prefix=options.cli_app_command_prefix or "",
        )
    except TypeError:
        gauntlet_g34 = _run_docker_gauntlet_g3g4(**runner_kwargs)
    if gauntlet_g34.get("skipped"):
        return gauntlet_g34
    is_kwok = options.cli_app_backend == "kwok"
    empty_rate = gauntlet_g34["g3_empty_pass_rate"]
    oracle_rate = gauntlet_g34["g4_oracle_pass_rate"]
    if is_kwok:
        if gauntlet_g34["g3_empty_total"] == 0 and gauntlet_g34["g4_oracle_total"] == 0:
            reason = "docker_gauntlet_kwok_startup_failed"
            logger.info(
                "gauntlet kwok task %s: empty_reward=%.2f, oracle_reward=%.2f, verdict=reject:%s",
                task_id or "<unknown>",
                empty_rate,
                oracle_rate,
                reason,
            )
            raise _TaskRejected(reason)
        if not gauntlet_g34["g3_pass"]:
            reason = f"docker_gauntlet_kwok_empty_pass_too_high_{empty_rate:.2f}"
            logger.info(
                "gauntlet kwok task %s: empty_reward=%.2f, oracle_reward=%.2f, verdict=reject:%s",
                task_id or "<unknown>",
                empty_rate,
                oracle_rate,
                reason,
            )
            raise _TaskRejected(reason)
        if not gauntlet_g34["g4_pass"]:
            reason = f"docker_gauntlet_kwok_oracle_pass_too_low_{oracle_rate:.2f}"
            logger.info(
                "gauntlet kwok task %s: empty_reward=%.2f, oracle_reward=%.2f, verdict=reject:%s",
                task_id or "<unknown>",
                empty_rate,
                oracle_rate,
                reason,
            )
            raise _TaskRejected(reason)
        logger.info(
            "gauntlet kwok task %s: empty_reward=%.2f, oracle_reward=%.2f, verdict=accept",
            task_id or "<unknown>",
            empty_rate,
            oracle_rate,
        )
        return gauntlet_g34
    if not gauntlet_g34["g3_pass"]:
        raise _TaskRejected(f"gauntlet_g3_non_discriminative_{empty_rate:.2f}")
    if not gauntlet_g34["g4_pass"]:
        raise _TaskRejected(f"gauntlet_g4_oracle_failing_{oracle_rate:.2f}")
    return gauntlet_g34


def _build_cliapp_repo2env(
    *,
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    cmd_slug: str,
    cmd_names: list[str],
    is_subset: bool,
    intents: list[TestIntent],
    translated: list[str],
    test_files: dict[str, str],
    test_file_tags: dict[str, str],
    content_hash: str,
    reference_grounding: dict | None,
    gauntlet_g34: dict | None,
    llm_cost_before: float,
) -> dict:
    """Assemble the repo2env metadata block for one cli_app task."""
    profile = resolve_profile(options.cli_app_backend)
    # Integrity: True only when a gate (G3/G4 gauntlet or reference grounding with
    # empty-stub=0) actually confirmed it — never hardcoded (hardcoding let
    # non-discriminative / un-gated tasks self-certify).
    _disc_confirmed = False
    if gauntlet_g34 is not None and not gauntlet_g34.get("skipped"):
        _disc_confirmed = bool(gauntlet_g34.get("g3_pass") and gauntlet_g34.get("g4_pass"))
    elif reference_grounding is not None and not reference_grounding.get("skipped"):
        _disc_confirmed = reference_grounding.get("n_empty", 1) == 0
    repo2env: dict[str, Any] = {
        "pipeline": "code_instruct",
        "pipeline_version": "0.6.0-cliapp-v1",
        "repo": spec.repo,
        "ref": spec.git_sha,
        "reference": f"https://github.com/{spec.repo}/tree/{spec.git_sha}/{spec.tests_dir}",
        "source_access": pipeline.input.repo.access,
        "built_at": datetime.now(UTC).isoformat(),
        "synthesis_llm": pipeline._llm.qualified_name,
        "reward_kinds": ["test_execution"],
        "content_hash": content_hash,
        "code_instruct": {
            "mode": "cli_app",
            "command_prefix": spec.command_prefix,
            "command": cmd_slug,
            "cli_spec_sha256": spec.spec_sha256,
            "prompt_template_version": _prompt_template_version(options),
            "translation_model": _translation_model_id(pipeline, options),
            "oracle_model": pipeline._llm.qualified_name,
            "intents_extracted": len(intents),
            "tests_translated": len(translated),
            "tests_in_task": len(test_files),
            "simulation_backend": profile.simulation_backend,
            "python_version": "3.12",
            "entry_point": "submission/main.py",
            "pinned_deps": list(profile.pinned_deps),
            "runtime_cpus": 1.0,
            "runtime_memory_mb": 1024,
            "runtime_network": "none",
            "runtime_timeout_sec": 300,
            "llm_cost_usd": round(pipeline._llm_cost_usd - llm_cost_before, 6),
            "run_llm_cost_usd": round(pipeline._llm_cost_usd, 6),
            "llm_cost_method": "litellm_native",
            "behaviour_tags": sorted({_bucket_of(f, test_file_tags.get(f)) for f in test_files}),
            "behaviour_tag_counts": _shipped_bucket_counts(test_files, test_file_tags),
            "tests_shipped": len(test_files),
            "discriminative": _disc_confirmed,
        },
    }
    if is_subset:
        repo2env["code_instruct"]["commands"] = sorted(cmd_names)
        repo2env["code_instruct"]["subset"] = True
    if reference_grounding is not None and not reference_grounding.get("skipped"):
        repo2env["code_instruct"]["reference_grounding"] = {
            "reference": profile.reference_label,
            profile.reference_version_key: (
                profile.reference_version_value or PINNED_AWSCLI_VERSION
            ),
            "n_reference_pass": reference_grounding["n_reference"],
            "n_oracle_pass": reference_grounding["n_oracle"],
            "n_empty_stub_pass": reference_grounding["n_empty"],
            "sim_completeness": round(
                reference_grounding["n_reference"] / max(1, len(translated)), 4
            ),
            "tests_shipped": len(test_files),
            "discriminative": reference_grounding.get("n_empty", 1) == 0,
            "oracle_solves_all_shipped": set(test_files)
            <= (reference_grounding.get("oracle_pass") or set()),
        }
    if gauntlet_g34 is not None and not gauntlet_g34.get("skipped"):
        repo2env["code_instruct"]["docker_gauntlet"] = {
            "g3_empty_pass_rate": round(gauntlet_g34["g3_empty_pass_rate"], 4),
            "g3_empty_passed": gauntlet_g34["g3_empty_passed"],
            "g3_empty_total": gauntlet_g34["g3_empty_total"],
            "g4_oracle_pass_rate": round(gauntlet_g34["g4_oracle_pass_rate"], 4),
            "g4_oracle_passed": gauntlet_g34["g4_oracle_passed"],
            "g4_oracle_total": gauntlet_g34["g4_oracle_total"],
            "discriminative": bool(gauntlet_g34.get("g3_pass") and gauntlet_g34.get("g4_pass")),
            "image_tag": gauntlet_g34.get("image_tag", ""),
        }
    return repo2env


def _effective_grounded_floor(options: CodeInstructOptions) -> int:
    """Per-task grounded-test floor: a per-service override wins over the global
    cli_app_min_grounded_final (0 = no floor, top-up disabled)."""
    override = options.cli_app_min_grounded_final_overrides.get(options.cli_app_backend)
    return override if override is not None else options.cli_app_min_grounded_final


def _topup_budget_ok(
    pipeline: CodeInstructPipeline, options: CodeInstructOptions, cost0: float, t0: float
) -> bool:
    over_cost = (
        options.cli_app_topup_max_cost_usd is not None
        and pipeline._llm_cost_usd - cost0 >= options.cli_app_topup_max_cost_usd
    )
    over_wall = (
        options.cli_app_topup_max_wall_sec is not None
        and time.monotonic() - t0 >= options.cli_app_topup_max_wall_sec
    )
    return not (over_cost or over_wall)


def _topup_more_intents(
    model: dict,
    cmd_specs: list[CommandSpec],
    options: CodeInstructOptions,
    seen_shas: set[str],
    attempt: int,
    deficit: int,
) -> list[TestIntent]:
    """Fresh variant intents (escalating happy-path variant count) for the subset's commands,
    excluding any already-seen intent by source_method_sha256. Deterministic and bounded."""
    ops = _resolve_target_ops(options)
    mut = _parse_mutually_exclusive(options)
    variants = 8 * (attempt + 2)
    fresh: list[TestIntent] = []
    for c in cmd_specs:
        cand = synthesize_intents_from_model(
            model,
            c.name,
            options.cli_app_command_prefix,
            target_operations=ops,
            max_intents=None,
            combinations=_is_generic_backend(options) and options.cli_app_combinations,
            max_optional_combos=options.cli_app_max_optional_combos,
            mutually_exclusive=mut,
            happy_variants=variants,
        )
        fresh.extend(it for it in cand if it.source_method_sha256 not in seen_shas)
    fresh.sort(key=lambda it: it.source_method_sha256)
    return fresh[: max(12, deficit * 3)]


def _load_kubectl_fixtures(
    fixture_dir_path: str,
    cmd_names: list[str],
    *,
    max_tests: int | None = None,
    kinds: list[str] | None = None,
) -> tuple[dict[str, str], str, set[str], set[tuple[str, str]]] | None:
    import hashlib as _h
    import json as _json
    import re as _re
    from pathlib import Path as _Path

    fixture_dir = _Path(fixture_dir_path)
    if not fixture_dir.is_dir():
        return None
    conftest_path = fixture_dir / "conftest.py"
    if not conftest_path.is_file():
        return None
    kind_filter: set[str] | None = set(kinds) if kinds else None
    kind_index: dict[str, dict] = {}
    if kind_filter is not None:
        index_path = fixture_dir / "kind_index.json"
        if index_path.is_file():
            try:
                kind_index = _json.loads(index_path.read_text(encoding="utf-8"))
            except Exception:
                kind_index = {}
    subset = set(cmd_names)
    _cli_verb_re = _re.compile(r"""cli\(\s*["']([a-z][a-z0-9-]*)["']""")
    _bin_verb_re = _re.compile(r"""kubectl_bin\(\s*\[\s*["']([a-z][a-z0-9-]*)["']""")
    tests: dict[str, str] = {}
    covered_verbs: set[str] = set()
    covered_pairs: set[tuple[str, str]] = set()
    workflow_dropped = 0
    kind_dropped = 0
    for f in sorted(fixture_dir.glob("test_kubectl_*.py")):
        parts = f.stem.split("_")
        if len(parts) < 3:
            continue
        verb = parts[2]
        file_kinds: list[str] = []
        if kind_filter is not None:
            entry = kind_index.get(f.name)
            file_kinds = entry.get("kinds", []) if isinstance(entry, dict) else []
            if file_kinds and not (set(file_kinds) & kind_filter):
                kind_dropped += 1
                continue
        if verb == "workflow":
            body = f.read_text(encoding="utf-8")
            used_verbs = set(_cli_verb_re.findall(body)) | set(_bin_verb_re.findall(body))
            if used_verbs and used_verbs.issubset(subset):
                tests[f.name] = body
                _kinds_for_pairs = [k for k in file_kinds if kind_filter is None or k in kind_filter] or ["_"]
                for k in _kinds_for_pairs:
                    for v in used_verbs:
                        covered_pairs.add((v, k))
            else:
                workflow_dropped += 1
            continue
        if verb in cmd_names:
            tests[f.name] = f.read_text(encoding="utf-8")
            covered_verbs.add(verb)
            _kinds_for_pairs = [k for k in file_kinds if kind_filter is None or k in kind_filter] or ["_"]
            for k in _kinds_for_pairs:
                covered_pairs.add((verb, k))
    if not covered_verbs:
        return None
    if max_tests is not None and len(tests) > max_tests:
        _total_in = len(tests)
        _seed = ",".join(sorted(cmd_names))
        # Kind\u00d7verb combo-coverage floor: for each (verb, kind) where kind is
        # in the task's declared kind_filter, seed one deterministically-picked
        # test. This is protected from the downsample trim so no combo is
        # silently dropped when the task requests all-kinds coverage.
        _combo_floor: set[str] = set()
        if kind_filter is not None:
            _by_combo: dict[tuple[str, str], list[str]] = {}
            for _fname in tests:
                _entry = kind_index.get(_fname) if isinstance(kind_index, dict) else None
                _fk = _entry.get("kinds", []) if isinstance(_entry, dict) else []
                _fparts = _fname[:-3].split("_") if _fname.endswith(".py") else _fname.split("_")
                _fverb = _fparts[2] if len(_fparts) > 2 else "unknown"
                for _k in _fk:
                    if _k in kind_filter:
                        _by_combo.setdefault((_fverb, _k), []).append(_fname)
            for _combo, _names in _by_combo.items():
                _pick = sorted(_names, key=lambda n: _h.sha256(f"{_seed}:{n}".encode()).hexdigest())[0]
                _combo_floor.add(_pick)
        _buckets: dict[tuple[str, str], list[str]] = {}
        for _fname in tests:
            _fparts = _fname[:-3].split("_") if _fname.endswith(".py") else _fname.split("_")
            _fverb = _fparts[2] if len(_fparts) > 2 else "unknown"
            _ftag = _fparts[3] if len(_fparts) > 3 else "unknown"
            _buckets.setdefault((_fverb, _ftag), []).append(_fname)
        _selected: set[str] = set(_combo_floor)
        for _names in _buckets.values():
            _target = max(1, round(len(_names) / _total_in * max_tests))
            _scored = sorted(_names, key=lambda n: _h.sha256(f"{_seed}:{n}".encode()).hexdigest())
            _selected.update(_scored[:_target])
        if len(_selected) > max_tests:
            _trimmable = _selected - _combo_floor
            _scored_all = sorted(
                _trimmable, key=lambda n: _h.sha256(f"{_seed}:{n}".encode()).hexdigest()
            )
            _budget = max(0, max_tests - len(_combo_floor))
            _selected = _combo_floor | set(_scored_all[:_budget])
        tests = {n: c for n, c in tests.items() if n in _selected}
        if _combo_floor:
            logger.info(
                "cli_app: kwok fixture combo-coverage: seeded %d tests for %d kind\u00d7verb pairs",
                len(_combo_floor),
                len(_combo_floor),
            )
        logger.info(
            "cli_app: kwok fixture cap: sampled %d tests from %d (max_tests=%d)",
            len(tests),
            _total_in,
            max_tests,
        )
    if kind_filter is not None:
        logger.info(
            "cli_app: kwok fixture kind filter: dropped %d out-of-kind files (kinds=%s)",
            kind_dropped,
            sorted(kind_filter),
        )
    logger.info(
        "cli_app: kwok fixture workflow filter: kept %d, dropped %d (out-of-subset verbs)",
        sum(1 for name in tests if "_workflow_" in name),
        workflow_dropped,
    )
    return tests, conftest_path.read_text(encoding="utf-8"), covered_verbs, covered_pairs


def _build_one_task(
    *,
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    cmd_specs: list[CommandSpec],
    intents: list[TestIntent],
    out_dir: Path,
    intent_idx: int | None = None,
    source_root: Path | None = None,
    model: dict | None = None,
) -> Path:
    """Synthesise + verify + emit ONE Harbor task for one command, or for a
    compatible subset of commands.

    `cmd_specs` holds a single CommandSpec for the original single-command task
    (output stays byte-identical) or several for a subset task. Subset tasks
    additionally synthesise cross-command workflow tests and a multi-command
    oracle + instruction.
    """
    is_subset = len(cmd_specs) > 1
    cmd_names = [c.name for c in cmd_specs]
    profile = resolve_profile(options.cli_app_backend)
    # Canonical, order-independent slugs. Single-command keeps the bare command
    # name so existing task_ids / cache keys / filenames are unchanged.
    cmd_slug = cmd_names[0] if not is_subset else "+".join(sorted(cmd_names))
    id_slug = cmd_names[0] if not is_subset else "_".join(sorted(cmd_names))

    # Snapshot pipeline-wide cost before this task's LLM work so the per-task
    # record reflects ONLY this task's delta, not the cumulative run total.
    _llm_cost_before = pipeline._llm_cost_usd

    # ----- LLM: translate each intent into a black-box test (parallelisable) -----
    translated: list[str] = []
    translated_intents: list[TestIntent] = []
    max_workers = max(1, options.cli_app_translate_workers)
    if max_workers == 1:
        per_intent_codes = [
            _translate_intent(pipeline, options, spec, intent) for intent in intents
        ]
    else:
        logger.info(
            "cli_app: translating %d intents with %d parallel LLM workers",
            len(intents),
            max_workers,
        )
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            per_intent_codes = list(
                ex.map(lambda i: _translate_intent(pipeline, options, spec, i), intents)
            )
    for intent, test_code in zip(intents, per_intent_codes, strict=True):
        if test_code is None:
            continue
        translated.append(test_code)
        translated_intents.append(intent)
    if not translated:
        raise _TaskRejected("no_translatable_intents")

    # ----- Oracle: either LLM-synthesised main.py OR real-aws-cli golden slice -----
    # In `golden` mode we ALSO synthesise the LLM oracle so it can ship as
    # `solution/reference.diff` alongside `solution/golden.diff`. LLM oracle
    # failure rejects the task — a golden-mode task without a reference is
    # incomplete by contract.
    golden = options.cli_app_oracle in ("golden", "both")
    golden_gold_diff: str | None = None
    golden_image_deps: tuple[str, ...] | None = None
    golden_files: dict[str, str] | None = None
    golden_prov: dict[str, str] | None = None
    if golden:
        if source_root is None:
            # Fail closed: no cloned source => no real golden slice. Never silently
            # ship the LLM oracle AS the golden (that produced golden.diff==reference.diff
            # tasks with no ground truth). Offline callers must set cli_app_oracle="llm".
            raise _TaskRejected("golden_slice_unavailable_no_source_root")
        else:
            service = profile.service
            slice_commands = cmd_names
            try:
                golden_files, golden_gold_diff, golden_prov, slice_externals = build_slice_gold(
                    source_root, commands=slice_commands, service=service
                )
            except SliceError as exc:
                raise _TaskRejected(f"golden_slice_failed_{type(exc).__name__}") from exc
            harness_deps = (
                GOLDEN_TEST_HARNESS_DEPS_DDB
                if options.cli_app_backend == "dynamodb_local" or _is_generic_backend(options)
                else GOLDEN_TEST_HARNESS_DEPS_MINIO
            )
            golden_image_deps = (*slice_externals, *harness_deps)

    cache_key = f"{spec.spec_sha256}|{cmd_slug}"
    if cache_key in _ORACLE_CACHE:
        oracle_code = _ORACLE_CACHE[cache_key]
    else:
        oracle_code = _synthesise_oracle(pipeline, options, spec, cmd_specs, intents)
        if oracle_code is not None:
            _ORACLE_CACHE[cache_key] = oracle_code
    if oracle_code is None:
        raise _TaskRejected(
            "reference_oracle_synthesis_failed" if golden else "oracle_synthesis_failed"
        )

    _antihack_mode = _effective_antihack_mode(options)
    if _antihack_mode != "off":
        _hack_findings = scan_oracle_for_reward_hacking(oracle_code)
        if _hack_findings:
            if _antihack_mode == "reject":
                raise _TaskRejected("oracle_reward_hacking_" + "+".join(_hack_findings))
            logger.warning(
                "cli_app: anti-hack scan (log-only, backend=%s) findings on %s oracle: %s",
                options.cli_app_backend,
                cmd_slug,
                _hack_findings,
            )

    # ----- Build supporting files -----
    conftest = profile.build_conftest(golden=golden)
    # Backend helper modules shipped alongside the tests (imported by conftest).
    # For DynamoDB the stdlib raw-HTTP client must be present in EVERY test bundle
    # (grounding, G3/G4, and the emitted task) or the conftest import fails.
    extra_tests_aux: dict[str, str] = {}
    if profile is not None and profile.client_module_src:
        extra_tests_aux[profile.client_module_path] = profile.client_module_src

    def _test_filename(intent: TestIntent, i: int) -> str:
        cmd_slug_i = (getattr(intent, "command", None) or "unknown").replace("_", "-")
        tag_slug = (intent.behaviour_tag or "unknown").replace("_", "-")
        return f"test_{spec.command_prefix}_{cmd_slug_i}_{tag_slug}_{i:02d}.py"

    test_files = {
        _test_filename(translated_intents[i], i): code for i, code in enumerate(translated)
    }
    test_file_tags = {
        _test_filename(translated_intents[i], i): translated_intents[i].behaviour_tag
        for i in range(len(translated))
    }
    # ----- Cross-command workflow tests (subset tasks only) -----
    if is_subset and options.cli_app_workflow_tests > 0:
        workflow_tests = _synthesise_workflow_tests(pipeline, options, spec, cmd_specs, intents)
        for j, code in enumerate(workflow_tests):
            test_files[f"test_{spec.command_prefix}_workflow_{j:02d}.py"] = code
    _ecr_registry: str | None = None
    _ecr_profile: str | None = None
    _ecr_platforms: list[str] = []
    if options.cli_app_ecr_push:
        if not options.cli_app_ecr_registry:
            raise _TaskRejected("cli_app_ecr_push_requires_registry")
        _ecr_registry = options.cli_app_ecr_registry
        _ecr_profile = _resolve_ecr_profile(options)
        _ecr_platforms = _resolve_platforms(options)
    base_image = options.cli_app_base_image or profile.base_image
    dockerfile = profile.build_dockerfile(
        base_image=base_image,
        bake_tests=options.cli_app_ecr_push,
        golden=golden,
        golden_deps=golden_image_deps,
    )
    test_script = _build_test_script()

    _fixture_dir = getattr(options, "cli_app_kubectl_fixture_dir", None)
    _using_fixtures = False
    _fixture_test_files: dict[str, str] = {}
    _fixture_test_tags: dict[str, str] = {}
    if options.cli_app_backend == "kwok" and _fixture_dir:
        _fx = _load_kubectl_fixtures(
            _fixture_dir,
            list(cmd_names),
            max_tests=getattr(options, "cli_app_kubectl_fixture_max_tests", None),
            kinds=getattr(options, "cli_app_kubectl_kinds", None),
        )
        if _fx is not None:
            _fixture_test_files, conftest, _covered_verbs, _covered_pairs = _fx
            _uncovered_verbs = [v for v in cmd_names if v not in _covered_verbs]
            _fixture_test_tags = {
                f: (
                    "workflow"
                    if "_workflow_" in f
                    else "error-nonexistent"
                    if "error-nonexistent" in f
                    else "error-invalid-args"
                    if "error-invalid-args" in f
                    else "happy-path"
                )
                for f in _fixture_test_files
            }
            _has_fixture_workflow = any("_workflow_" in f for f in _fixture_test_files)

            def _llm_keep(fname: str) -> bool:
                if "_workflow_" in fname:
                    return not _has_fixture_workflow
                return any(f"_{v}_" in fname for v in _uncovered_verbs)

            test_files = {f: c for f, c in test_files.items() if _llm_keep(f)}
            test_file_tags = {f: t for f, t in test_file_tags.items() if f in test_files}
            _using_fixtures = True
            logger.info(
                "cli_app: kwok fixture hybrid for %s: %d fixture tests (verbs: %s), "
                "%d LLM tests (uncovered verbs: %s)",
                cmd_slug,
                len(_fixture_test_files),
                sorted(_covered_verbs),
                len(test_files),
                sorted(_uncovered_verbs),
            )

    if not options.cli_app_skip_gauntlet and test_files:
        test_files = _apply_static_gauntlet(
            test_files,
            behaviour_tags=test_file_tags,
            forbid_skips=options.cli_app_forbid_skips,
            backend_name=options.cli_app_backend,
        )
        if _using_fixtures:
            test_file_tags = {f: t for f, t in test_file_tags.items() if f in test_files}

    # ----- Reference grounding (opt-in): keep ONLY tests that BOTH the real
    # aws CLI AND the synthesised oracle pass, and that the empty stub fails.
    # Filters out LLM-hallucinated/brittle tests and guarantees the gold patch
    # solves its own task. The `aws` binary lives only in the gauntlet image,
    # never in the shipped task image (anti-cheat).
    reference_grounding = None
    if options.cli_app_reference_grounding and not _using_fixtures:
        grounding_conftest = profile.build_conftest(golden=False) if golden else conftest
        reference_grounding, test_files, oracle_code = _apply_reference_grounding(
            options=options,
            dockerfile=dockerfile,
            conftest=grounding_conftest,
            test_files=test_files,
            test_script=test_script,
            oracle_code=oracle_code,
            extra_tests_aux=extra_tests_aux,
            pipeline=pipeline,
            profile=profile,
        )
        floor = _effective_grounded_floor(options)
        if floor and model is not None and _is_generic_backend(options):
            seen_shas = {ti.source_method_sha256 for ti in translated_intents}
            cost0 = pipeline._llm_cost_usd
            t0 = time.monotonic()
            attempt = 0
            while (
                len(test_files) < floor
                and attempt < options.cli_app_topup_max_attempts
                and _topup_budget_ok(pipeline, options, cost0, t0)
            ):
                fresh = _topup_more_intents(
                    model, cmd_specs, options, seen_shas, attempt, floor - len(test_files)
                )
                attempt += 1
                if not fresh:
                    break
                new_tf: dict[str, str] = {}
                new_tags: dict[str, str] = {}
                for it in fresh:
                    seen_shas.add(it.source_method_sha256)
                    code = _translate_intent(pipeline, options, spec, it)
                    if code is None:
                        continue
                    if not options.cli_app_skip_gauntlet:
                        ok, _reason = _gauntlet_static(
                            code,
                            expected_behaviour_tag=it.behaviour_tag,
                            forbid_skips=options.cli_app_forbid_skips,
                            backend_name=options.cli_app_backend,
                        )
                        if not ok:
                            continue
                    translated.append(code)
                    translated_intents.append(it)
                    fname = _test_filename(it, len(translated_intents) - 1)
                    new_tf[fname] = code
                    new_tags[fname] = it.behaviour_tag
                if not new_tf:
                    continue
                test_file_tags.update(new_tags)
                reference_grounding, test_files, oracle_code = _apply_reference_grounding(
                    options=options,
                    dockerfile=dockerfile,
                    conftest=grounding_conftest,
                    test_files={**test_files, **new_tf},
                    test_script=test_script,
                    oracle_code=oracle_code,
                    extra_tests_aux=extra_tests_aux,
                    pipeline=pipeline,
                    profile=profile,
                )
                logger.info(
                    "cli_app top-up attempt %d: grounded=%d / floor=%d",
                    attempt,
                    len(test_files),
                    floor,
                )
            if len(test_files) < floor:
                raise _TaskRejected(f"topup_exhausted_grounded_{len(test_files)}_of_{floor}")
    elif options.cli_app_reference_grounding and _using_fixtures:
        # Filter shipped tests to (reference_pass ∩ oracle_pass) - empty_pass so
        # Harbor's downstream oracle-reference scoring is 1.0 by construction.
        grounding_conftest = profile.build_conftest(golden=False) if golden else conftest
        _combined_fx = {**_fixture_test_files, **test_files}
        _tests_aux_fx: dict[str, str] = {
            "tests/conftest.py": grounding_conftest,
            "tests/__init__.py": "",
        }
        if extra_tests_aux:
            _tests_aux_fx.update(extra_tests_aux)
        for _fname, _code in _combined_fx.items():
            _tests_aux_fx[f"tests/{_fname}"] = _code
        reference_grounding = _run_reference_grounding(
            dockerfile_content=dockerfile,
            tests_aux=_tests_aux_fx,
            test_script=test_script,
            oracle_code=oracle_code,
            timeout_sec=options.cli_app_docker_timeout_sec,
            backend=options.cli_app_backend,
        )
        if reference_grounding.get("skipped"):
            logger.warning(
                "fixture-mode grounding unavailable (%s); shipping unfiltered",
                reference_grounding.get("reason", "unknown"),
            )
        else:
            _grounded = reference_grounding["grounded_files"]
            _fixture_test_files = {
                f: c for f, c in _fixture_test_files.items() if f in _grounded
            }
            test_files = {f: c for f, c in test_files.items() if f in _grounded}
            logger.info(
                "fixture-mode grounding: %d ref-pass & %d oracle-pass -> %d grounded (shipping %d)",
                len(reference_grounding["reference_pass"]),
                len(reference_grounding["oracle_pass"]),
                len(_grounded),
                len(_fixture_test_files) + len(test_files),
            )

    # ----- G4 alignment: the shipped (grounded) tests are the single source of
    # truth for which commands the task covers. If grounding/top-up dropped a
    # command entirely, remove it from the command set so instruction.md, keywords,
    # description and repo2env (all derived below) never over-claim coverage. -----
    if _is_generic_backend(options) and options.cli_app_reference_grounding:
        _fname_cmd = {_test_filename(ti, i): ti.command for i, ti in enumerate(translated_intents)}
        shipped_cmds: set[str] = {_fname_cmd[f] for f in test_files if f in _fname_cmd}
        for f, code in test_files.items():
            if "_workflow_" not in f:
                continue
            try:
                for node in ast.walk(ast.parse(code)):
                    if isinstance(node, ast.FunctionDef):
                        shipped_cmds |= _commands_used_in_cli_calls(node, spec.command_prefix)
            except SyntaxError:
                pass
        aligned = [c for c in cmd_names if c in shipped_cmds]
        if aligned and len(aligned) < len(cmd_names):
            cmd_names = aligned
            cmd_specs = [c for c in cmd_specs if c.name in shipped_cmds]
            is_subset = len(cmd_specs) > 1
            cmd_slug = cmd_names[0] if not is_subset else "+".join(sorted(cmd_names))
            id_slug = cmd_names[0] if not is_subset else "_".join(sorted(cmd_names))
            logger.info("cli_app G4 alignment: shipped commands narrowed to %s", sorted(cmd_names))

    if _using_fixtures:
        test_files = {**_fixture_test_files, **test_files}
        test_file_tags = {**_fixture_test_tags, **test_file_tags}

    aux_files: dict[str, str] = {
        "tests/conftest.py": conftest,
        "tests/__init__.py": "",
    }
    aux_files.update(extra_tests_aux)
    for fname, code in test_files.items():
        aux_files[f"tests/{fname}"] = code
    # DynamoDB tasks ship a compose overlay that also blackholes the DynamoDB
    # service endpoint (defense in depth). The emitter's aux loop runs last, so
    # this overrides the default S3 disallow-list. MinIO tasks keep the default.
    if options.cli_app_backend == "dynamodb_local":
        aux_files["environment/docker-compose.yaml"] = _build_disallow_compose(
            BLOCKED_HOSTS_DDB, ddb_sidecar=True
        )
    elif options.cli_app_backend == "kwok":
        from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
            _KWOK_BLOCKED_HOSTS_EXPANDED,
        )

        aux_files["environment/docker-compose.yaml"] = _build_disallow_compose(
            _KWOK_BLOCKED_HOSTS_EXPANDED
        )
    elif profile.build_compose_overlay is not None:
        aux_files["environment/docker-compose.yaml"] = profile.build_compose_overlay()

    reference_diff_file = make_multi_file_diff({"submission/main.py": oracle_code})
    if golden:
        gold_diff = golden_gold_diff
        reference_diff = reference_diff_file
    else:
        gold_diff = reference_diff_file
        reference_diff = reference_diff_file

    # Kwok golden must come from the AST slicer, not the LLM. reference_diff
    # keeps the LLM output so both signals ship in the task.
    if options.cli_app_backend == "kwok":
        from types import SimpleNamespace

        from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
            KwokSimulationBackend,
        )

        _kwok_slice_spec = SimpleNamespace(commands=list(cmd_names))
        _sliced_diff = KwokSimulationBackend.emit_golden_diff(_kwok_slice_spec)
        if _sliced_diff is not None:
            gold_diff = _sliced_diff
        else:
            logger.warning(
                "cli_app: kwok golden slicer returned None for %s; "
                "falling back to LLM oracle diff (slicer requires docker + network)",
                cmd_slug,
            )

    # ----- instruction.md (rendered from spec, NEVER from tests) -----
    if options.cli_app_backend == "kwok":
        spec.declared_kinds = sorted(options.cli_app_kubectl_kinds or [])
    if is_subset:
        instruction_md = profile.build_instruction_subset(spec, cmd_specs, intents)
    else:
        instruction_md = profile.build_instruction_single(spec, cmd_specs[0], intents)
    _assert_no_test_leakage(instruction_md, test_files)

    # ----- task_id derived from spec sha + command + prompt version (+ intent_idx) -----
    task_id = _compute_cliapp_task_id(
        spec=spec,
        cmd_slug=cmd_slug,
        id_slug=id_slug,
        intent_idx=intent_idx,
        intents=intents,
        prompt_version=_prompt_template_version(options),
    )

    # ----- Pre-compute content_hash covering spec + tests + oracle + instr -----
    # Overrides harbor.py's default which only covers instruction + diff.
    content_hash = _compute_content_hash(
        spec=spec,
        instruction=instruction_md,
        oracle_diff=gold_diff,
        reference_diff=reference_diff,
        aux_files=aux_files,
        prompt_version=_prompt_template_version(options),
        translation_model=_translation_model_id(pipeline, options),
        oracle_model=pipeline._llm.qualified_name,
    )

    # ----- Gauntlet G3 (empty-stub-fails) + G4 (oracle-passes) — opt-in -----
    # Without this, tests can be non-discriminative (pass on empty stub).
    # Builds image once per Dockerfile (cached), runs pytest twice per task.
    # Fixture-mode (e.g. kubectl kwok) ships human-authored tests written
    # against the real CLI; those are ground-truth so the discriminativeness
    # gate on the LLM oracle does not apply. Harbor's oracle-golden run is the
    # correctness gate for fixture-mode tasks.
    gauntlet_g34 = None
    golden_cert = None
    _fixture_mode = bool(getattr(options, "cli_app_kubectl_fixture_dir", None))
    if (
        not options.cli_app_skip_gauntlet
        and not _fixture_mode
        and getattr(options, "cli_app_docker_gauntlet", False)
    ):
        if golden:
            golden_cert = _certify_golden(
                dockerfile=dockerfile,
                conftest=conftest,
                test_files=test_files,
                test_script=test_script,
                gold_files=golden_files or {},
                extra_tests_aux=extra_tests_aux,
                timeout_sec=options.cli_app_docker_timeout_sec,
                backend=options.cli_app_backend,
            )
            if not golden_cert.get("skipped") and golden_cert.get("pass_rate", 0.0) < 1.0:
                raise _TaskRejected(
                    f"golden_cert_failed_{golden_cert.get('passed', 0)}_of_{golden_cert.get('total', 0)}"
                )
        else:
            gauntlet_g34 = _run_g3g4_gauntlet_gate(
                options=options,
                dockerfile=dockerfile,
                aux_files=aux_files,
                test_script=test_script,
                oracle_code=oracle_code,
            )

    # ----- repo2env metadata -----
    repo2env = _build_cliapp_repo2env(
        pipeline=pipeline,
        options=options,
        spec=spec,
        cmd_slug=cmd_slug,
        cmd_names=cmd_names,
        is_subset=is_subset,
        intents=intents,
        translated=translated,
        test_files=test_files,
        test_file_tags=test_file_tags,
        content_hash=content_hash,
        reference_grounding=reference_grounding,
        gauntlet_g34=gauntlet_g34,
        llm_cost_before=_llm_cost_before,
    )
    if golden and golden_files is not None:
        _prov_items = sorted((golden_prov or {}).items())
        repo2env["code_instruct"]["golden"] = {
            "awscli_version": PINNED_AWSCLI_VERSION,
            "entry_point": "submission/aws",
            "n_slice_files": len(golden_files),
            "n_verbatim_files": len(golden_prov or {}),
            "provenance_sha256": hashlib.sha256(
                "\n".join(f"{k}:{v}" for k, v in _prov_items).encode()
            ).hexdigest(),
            "certified_pass_rate": (
                golden_cert.get("pass_rate")
                if golden_cert and not golden_cert.get("skipped")
                else None
            ),
            "oracle_solves_all_shipped": bool(
                golden_cert
                and not golden_cert.get("skipped")
                and golden_cert.get("pass_rate", 0.0) >= 1.0
            ),
        }

    _task_ecr_ref: str | None = None
    if options.cli_app_ecr_push and _ecr_registry is not None:
        _uid = content_hash.split(":", 1)[-1][:12]
        _task_ecr_ref = _build_and_push_task_image(
            registry=_ecr_registry,
            profile=_ecr_profile,
            platforms=_ecr_platforms,
            owner_name=spec.name,
            task_slug=id_slug,
            uid=_uid,
            aux_files=aux_files,
            test_script=test_script,
            dockerfile=dockerfile,
        )
        repo2env["reproducibility"] = {
            "mode": "registry",
            "image_ref": _task_ecr_ref,
            "image_tag": _task_ecr_ref,
            "image_visibility": "private",
        }

    _enforce_final_test_quotas(options, test_files, test_file_tags)

    is_kwok = options.cli_app_backend == "kwok"
    cli_label = spec.command_prefix if is_kwok else f"aws {spec.command_prefix}"
    article = "a" if is_kwok else "an"
    _kinds = sorted(getattr(options, "cli_app_kubectl_kinds", None) or []) if is_kwok else []
    if is_subset:
        if is_kwok and _kinds:
            description = (
                f"Implement {article} `{cli_label}` CLI supporting {len(_kinds)} "
                f"Kubernetes kinds ({', '.join(_kinds)}) with the "
                f"{', '.join(sorted(cmd_names))} verbs, from scratch"
            )
        else:
            description = (
                f"Implement {article} `{cli_label}` CLI subset "
                f"({', '.join(sorted(cmd_names))}) from scratch"
            )
        keywords = [spec.name, "code_instruct", "cli_app", "subset", *sorted(cmd_names)]
    else:
        description = f"Implement `{cli_label} {cmd_names[0]}` from scratch"
        keywords = [spec.name, "code_instruct", "cli_app", cmd_names[0]]

    task = HarborTask(
        name=task_id,
        org=pipeline.input.output.org,
        description=description,
        instruction=instruction_md,
        oracle_diff=gold_diff,
        reference_diff=reference_diff,
        repo2env=repo2env,
        difficulty="medium",
        category="feature",
        keywords=keywords,
        environment_dockerfile=dockerfile,
        test_script=test_script,
        aux_files=aux_files,
        task_uuid=str(uuid4()),
    )
    return write_harbor_task(task, out_dir, emit_samples_format=True)


# ---------------------------------------------------------------------------
# Final-count quota gate
# ---------------------------------------------------------------------------


def _bucket_of(filename: str, tag: str | None) -> str:
    if "_workflow_" in filename:
        return "workflow"
    if tag == "happy_path":
        return "happy_path"
    if tag == "error_nonexistent":
        return "error_nonexistent"
    if tag == "error_invalid_args":
        return "error_invalid_args"
    if tag == "edge":
        return "edge"
    if tag == "error":
        return "error_generic"
    return tag or "unknown"


def _shipped_bucket_counts(
    test_files: dict[str, str], test_file_tags: dict[str, str]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fname in test_files:
        b = _bucket_of(fname, test_file_tags.get(fname))
        counts[b] = counts.get(b, 0) + 1
    return counts


def _enforce_final_test_quotas(
    options: CodeInstructOptions,
    test_files: dict[str, str],
    test_file_tags: dict[str, str],
) -> None:
    total_min = options.cli_app_min_tests_final
    if total_min and len(test_files) < total_min:
        raise _TaskRejected(f"final_tests_below_min_{len(test_files)}_of_{total_min}")
    quotas = {
        "happy_path": options.cli_app_min_happy_path,
        "error_nonexistent": options.cli_app_min_error_nonexistent,
        "error_invalid_args": options.cli_app_min_error_invalid_args,
        "workflow": options.cli_app_min_workflow,
        "edge": options.cli_app_min_edge,
    }
    if not any(quotas.values()):
        return
    counts: dict[str, int] = {}
    for fname in test_files:
        b = _bucket_of(fname, test_file_tags.get(fname))
        counts[b] = counts.get(b, 0) + 1
    for bucket, need in quotas.items():
        if need and counts.get(bucket, 0) < need:
            raise _TaskRejected(f"bucket_{bucket}_below_min_{counts.get(bucket, 0)}_of_{need}")


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

# Guards concurrent updates to pipeline._llm_cost_usd when _translate_intent
# runs under a ThreadPoolExecutor (cli_app_translate_workers > 1).
_TRANSLATE_COST_LOCK = threading.Lock()


def _translate_intent(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    intent: TestIntent,
) -> str | None:
    """One LLM call per intent. Returns translated test code or None on failure."""
    is_ddb = options.cli_app_backend == "dynamodb_local"
    profile = resolve_profile(options.cli_app_backend)
    template = profile.translation_user
    system = profile.translation_system
    fmt_kwargs: dict[str, object] = dict(
        raw_source=intent.raw_source[:4000],
        command_prefix=spec.command_prefix,
        command=intent.command,
        cmdline_template=intent.cmdline_template,
        expected_exit=intent.expected_exit,
        expected_state_calls=intent.expected_state_calls,
        behaviour_tag=intent.behaviour_tag,
        kind=intent.kind or spec.command_prefix,
    )
    if "{real_output_samples}" in template:
        real_section = ""
        if options.cli_app_backend == "kwok":
            from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
                format_real_output_section,
            )

            samples = getattr(pipeline, "_kubectl_samples", None) or {}
            real_section = format_real_output_section(
                intent.command,
                samples,
                command_prefix=spec.command_prefix,
            )
        fmt_kwargs["real_output_samples"] = real_section
    user = template.format(**fmt_kwargs)
    try:
        resp = complete(
            pipeline._llm,
            system=system,
            user=user,
            max_tokens=options.max_llm_tokens,
            temperature=options.llm_temperature,
        )
    except Exception as exc:
        logger.warning("translation failed for %s: %s", intent.test_name, exc)
        return None
    with _TRANSLATE_COST_LOCK:
        pipeline._llm_cost_usd += resp.cost_usd
    code = _sanitise_mock_aws(_strip_code_fence(resp.content))
    if is_ddb:
        code = _WF_IMPORT_PREAMBLE_DDB + code
    return code


def _sanitise_mock_aws(code: str) -> str:
    out_lines: list[str] = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped == "@mock_aws" or stripped.startswith("@mock_aws("):
            continue
        if stripped in {
            "from moto import mock_aws",
            "from moto import mock_aws  # noqa",
            "import moto",
        }:
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _oracle_incompleteness_reason(
    tree: ast.Module,
    code: str,
    cmd_specs: list[CommandSpec],
    finish_reason: str | None,
) -> str | None:
    if finish_reason == "length":
        return "response truncated (finish_reason=length)"
    has_dispatcher = any(
        isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body
    )
    if not has_dispatcher:
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test_src = ast.unparse(node.test)
                if "__name__" in test_src and "__main__" in test_src:
                    has_dispatcher = True
                    break
    if not has_dispatcher:
        return "missing __main__ / def main() dispatcher"
    fn_name_tokens = {n.name.lower() for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    str_consts = {
        n.value.lower()
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    missing: list[str] = []
    for c in cmd_specs:
        verb = c.name.lower()
        covered = verb in str_consts or any(verb in fn for fn in fn_name_tokens)
        if not covered:
            missing.append(c.name)
    if missing:
        return f"no dispatch entry for verb(s): {', '.join(missing)}"
    return None


def _synthesise_oracle(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    cmd_specs: list[CommandSpec],
    intents: list[TestIntent],
) -> str | None:
    """One LLM call per command-or-subset. Returns oracle source or None.

    For a single command the prompt is byte-identical to the original. For a
    subset, a multi-command oracle prompt asks for one `main.py` implementing
    every subcommand, dispatched on argv.
    """
    profile = resolve_profile(options.cli_app_backend)
    behaviours = _summarise_behaviours_from_intents(intents)
    behaviours_bulleted = "\n".join(f"- {b}" for b in behaviours)
    if len(cmd_specs) > 1:
        commands_csv = ", ".join(f"`{spec.command_prefix} {c.name}`" for c in cmd_specs)
        system = profile.oracle_subset_system
        template = profile.oracle_subset_user
        flags_per_command = "\n".join(
            f"- `{spec.command_prefix} {c.name}`: {', '.join(c.flags) if c.flags else '(no flags)'}"
            for c in cmd_specs
        )
        user = template.format(
            command_prefix=spec.command_prefix,
            commands_csv=commands_csv,
            behaviours_bulleted=behaviours_bulleted,
            flags_per_command=flags_per_command,
        )
    else:
        system = profile.oracle_system
        template = profile.oracle_user
        flags_bulleted = (
            "\n".join(f"- `{f}`" for f in cmd_specs[0].flags)
            if cmd_specs[0].flags
            else "- (no flags)"
        )
        user = template.format(
            command_prefix=spec.command_prefix,
            command=cmd_specs[0].name,
            behaviours_bulleted=behaviours_bulleted,
            flags_bulleted=flags_bulleted,
        )
    cmd_label = "+".join(c.name for c in cmd_specs)
    attempts = max(1, options.cli_app_oracle_max_attempts)
    last_reason = "no attempt made"
    for attempt in range(1, attempts + 1):
        try:
            resp = complete(
                pipeline._llm,
                system=system,
                user=user,
                max_tokens=options.cli_app_oracle_max_tokens,
                temperature=options.llm_temperature,
            )
        except Exception as exc:
            last_reason = f"provider error: {exc}"
            logger.warning(
                "oracle synthesis attempt %d/%d failed for command=%s: %s",
                attempt,
                attempts,
                cmd_label,
                exc,
            )
            continue
        pipeline._llm_cost_usd += resp.cost_usd
        code = _strip_code_fence(resp.content)
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            last_reason = f"invalid Python: {exc}"
            logger.warning(
                "oracle synthesis attempt %d/%d returned invalid Python for command=%s: %s",
                attempt,
                attempts,
                cmd_label,
                exc,
            )
            continue
        incomplete = _oracle_incompleteness_reason(tree, code, cmd_specs, resp.finish_reason)
        if incomplete is not None:
            last_reason = incomplete
            logger.warning(
                "oracle synthesis attempt %d/%d returned incomplete code for command=%s: %s",
                attempt,
                attempts,
                cmd_label,
                incomplete,
            )
            continue
        if attempt > 1:
            logger.info(
                "oracle synthesis succeeded for command=%s on attempt %d/%d",
                cmd_label,
                attempt,
                attempts,
            )
        return code
    logger.warning(
        "oracle synthesis exhausted %d attempts for command=%s (last: %s)",
        attempts,
        cmd_label,
        last_reason,
    )
    return None


# Prepended to every workflow-test module so each is self-contained after the
# multi-function LLM response is split into one file per test function.
_WF_IMPORT_PREAMBLE = (
    "from minio import Minio\nfrom minio.error import S3Error\nfrom io import BytesIO\n\n\n"
)
# DynamoDB variant: workflow tests reach state via the raw-HTTP marshaling helpers.
_WF_IMPORT_PREAMBLE_DDB = "from _ddb_http import to_item, from_item, to_av, from_av\n\n\n"


def _synthesise_workflow_tests(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    cmd_specs: list[CommandSpec],
    intents: list[TestIntent],
) -> list[str]:
    """One LLM call per subset -> cross-command workflow pytest modules.

    Each returned string is a standalone module (import preamble + one
    `def test_workflow_*`). Returns [] on failure so the per-command tests still
    ship. Tests chain `cli(*argv)` calls and assert on `s3_client` state across
    commands. Built from the hand-authored _COMMAND_STATE_MODEL + intents, never
    from raw test code.
    """
    subset_names = sorted(c.name for c in cmd_specs)
    state_blocks: list[str] = []
    for name in subset_names:
        sm = _COMMAND_STATE_MODEL.get((spec.command_prefix, name))
        if sm:
            state_blocks.append(f"{spec.command_prefix} {name}:\n{sm}")
    state_models_joined = "\n\n".join(state_blocks) if state_blocks else "(none)"

    shapes: list[str] = []
    seen: set[str] = set()
    for intent in intents:
        if intent.behaviour_tag != "happy_path":
            continue
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen:
            seen.add(shape)
            shapes.append(f"- `{shape}`")
    argv_shapes_bulleted = "\n".join(shapes) if shapes else "- (none observed)"

    profile = resolve_profile(options.cli_app_backend)
    n_workflows = max(1, options.cli_app_workflow_tests)
    template = profile.workflow_user
    system = profile.workflow_system
    user = template.format(
        command_prefix=spec.command_prefix,
        subset_csv=", ".join(subset_names),
        state_models_joined=state_models_joined,
        argv_shapes_bulleted=argv_shapes_bulleted,
        n_workflows=n_workflows,
    )
    # Outer loop retries when the split yields fewer than the bucket target;
    # inner loop doubles max_tokens on `finish_reason=length`. Both matter:
    # the failure modes (parse-drop vs truncation) are distinct and neither
    # retry subsumes the other. Target aims above cli_app_min_workflow so the
    # downstream gauntlet has headroom to drop broken tests without pushing
    # the bucket below its floor.
    min_workflow = options.cli_app_min_workflow
    target = max(min_workflow + 3, int(min_workflow * 1.5)) if min_workflow else 1
    max_parse_attempts = 3
    best_results: list[str] = []
    for parse_attempt in range(1, max_parse_attempts + 1):
        max_tokens = options.max_llm_tokens
        resp = None
        for attempt in range(1, 4):
            try:
                resp = complete(
                    pipeline._llm,
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    temperature=options.llm_temperature,
                )
            except Exception as exc:
                logger.warning(
                    "workflow-test synthesis failed for subset=%s: %s", subset_names, exc
                )
                return best_results
            pipeline._llm_cost_usd += resp.cost_usd
            if resp.finish_reason != "length":
                break
            if attempt < 3:
                logger.warning(
                    "workflow-test synthesis truncated (finish_reason=length) for subset=%s at "
                    "max_tokens=%d; retrying with %d",
                    subset_names,
                    max_tokens,
                    max_tokens * 2,
                )
                max_tokens *= 2
            else:
                logger.warning(
                    "workflow-test synthesis still truncated after %d attempts for subset=%s; "
                    "safety net in _split_workflow_functions will drop broken tests",
                    attempt,
                    subset_names,
                )
        code = _strip_code_fence(resp.content)
        results = _split_workflow_functions(
            code,
            allowed_commands=set(subset_names),
            prefix=spec.command_prefix,
            preamble=profile.wf_preamble,
        )
        if len(results) > len(best_results):
            best_results = results
        if len(results) >= target:
            return results
        if parse_attempt < max_parse_attempts:
            logger.warning(
                "workflow-test synthesis yielded %d usable tests for subset=%s "
                "(need %d for gauntlet headroom; parse attempt %d/%d); retrying",
                len(results),
                subset_names,
                target,
                parse_attempt,
                max_parse_attempts,
            )
    return best_results


def _split_workflow_functions(
    code: str,
    *,
    allowed_commands: set[str],
    prefix: str,
    preamble: str = _WF_IMPORT_PREAMBLE,
) -> list[str]:
    """Split a multi-function workflow blob into one self-contained module per
    `test_*` function. Functions whose `cli(...)` calls reference a subcommand
    outside the subset are dropped (the combined oracle won't implement it).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        try:
            import os as _os
            import tempfile as _tempfile

            dump_dir = _os.environ.get("R2E_WORKFLOW_DUMP_DIR") or _tempfile.gettempdir()
            _os.makedirs(dump_dir, exist_ok=True)
            fd, path = _tempfile.mkstemp(prefix="workflow-fail-", suffix=".py", dir=dump_dir)
            with _os.fdopen(fd, "w") as _f:
                _f.write(code)
            lines = code.splitlines()
            lo = max(0, (exc.lineno or 1) - 4)
            hi = min(len(lines), (exc.lineno or 1) + 3)
            snippet = "\n".join(f"{i + 1:4d}: {lines[i]}" for i in range(lo, hi))
            logger.warning(
                "workflow-test synthesis returned invalid Python: %s (dumped to %s)\n%s",
                exc,
                path,
                snippet,
            )
        except OSError:
            logger.warning("workflow-test synthesis returned invalid Python: %s", exc)
        return []
    # Preserve the LLM's module-level imports (e.g. `import uuid`, `import os`)
    # so each split-out function module is self-contained — otherwise a
    # function that uses a module-level import NameErrors after splitting.
    module_imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom):
            seg = ast.get_source_segment(code, node)
            if seg:
                module_imports.append(seg)
    header = preamble
    if module_imports:
        header += "\n".join(module_imports) + "\n\n\n"
    out: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        stray = _commands_used_in_cli_calls(node, prefix) - allowed_commands
        if stray:
            logger.info(
                "workflow test %s references out-of-subset commands %s; dropping",
                node.name,
                sorted(stray),
            )
            continue
        src = ast.get_source_segment(code, node)
        if not src:
            continue
        # LLM truncation signature: `assert ...` cut to `ass` parses as a bare
        # Name expression, which ast.parse happily accepts but is never valid
        # test code. Drop it so we don't ship broken tests.
        if (
            node.body
            and isinstance(node.body[-1], ast.Expr)
            and isinstance(node.body[-1].value, ast.Name)
        ):
            logger.warning(
                "workflow test %s ends with bare name '%s' (LLM truncation signature); dropping",
                node.name,
                node.body[-1].value.id,
            )
            continue
        out.append(header + src.strip() + "\n")
    return out


def _commands_used_in_cli_calls(fn: ast.FunctionDef, prefix: str) -> set[str]:
    """Best-effort: subcommand tokens passed to `cli(...)` calls in the function.

    Recognises `cli("s3", "mb", ...)` -> {"mb"}: the token after the command
    prefix. If the leading literal is not the prefix (the model omitted it,
    e.g. `cli("mb", ...)`), the first literal is taken as the subcommand.
    Non-literal args are ignored, so the check is lenient (only drops a test
    when it clearly invokes a foreign subcommand).
    """
    used: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "cli":
            literals = [
                a.value
                for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            if not literals:
                continue
            toks = literals[1:] if literals[0] == prefix else literals
            if toks:
                used.add(toks[0])
    return used


# ---------------------------------------------------------------------------
# Gauntlet (static gates G1-G2 in MVP; G3+ require Docker, not enabled yet)
# ---------------------------------------------------------------------------


def _test_uses_pytest_skip_or_xfail(tree: ast.AST) -> bool:
    """AST-detect a pytest skip/xfail marker or call so the zero-skip gate cannot be
    fooled by a string/comment mention (matches only pytest.* / pytest.mark.* roots)."""
    markers = {"skip", "skipif", "xfail"}

    def _pytest_rooted(node: ast.expr) -> bool:
        cur: ast.expr = node
        while isinstance(cur, ast.Attribute):
            cur = cur.value
        return isinstance(cur, ast.Name) and cur.id in ("pytest", "mark")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                d = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(d, ast.Attribute) and d.attr in markers and _pytest_rooted(d):
                    return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("skip", "xfail", "importorskip")
            and _pytest_rooted(node.func)
        ):
            return True
    return False


def _gauntlet_static(
    test_code: str,
    *,
    expected_behaviour_tag: str | None = None,
    forbid_skips: bool = False,
    source_name: str | None = None,
    backend_name: str | None = None,
) -> tuple[bool, str]:
    """G1 (compile) + G2 (structural) + G2b (returncode polarity vs tag).

    ``backend_name='kwok'`` swaps the client-state regex to k8s_client/kubectl_bin
    and accepts pinned ``returncode == 1`` (kubectl's error signal) in addition
    to the {252, 254, 255} pinned exits AWS backends accept.
    """
    is_kwok = backend_name == "kwok"
    # G1
    try:
        tree = ast.parse(test_code)
    except SyntaxError as exc:
        return False, f"G1_compile: {exc}"
    if forbid_skips and _test_uses_pytest_skip_or_xfail(tree):
        return False, "G2e_noskip: test uses a pytest skip/xfail marker (zero-skip guarantee)"
    # G2: must define at least one `def test_*` function with a body
    found_test = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            found_test = True
            has_assert = any(isinstance(s, ast.Assert) for s in ast.walk(node))
            uses_cli_or_subprocess = bool(
                re.search(r"\bcli\s*\(", test_code) or "subprocess.run" in test_code
            )
            if not has_assert:
                return False, "G2_structural: no assert statement"
            if not uses_cli_or_subprocess:
                return False, "G2_structural: doesn't invoke the CLI"
            break
    if not found_test:
        return False, "G2_structural: no test_* function defined"
    if expected_behaviour_tag and expected_behaviour_tag.startswith("error"):
        asserts_failure = bool(
            re.search(r"returncode\s*!=\s*0", test_code)
            or re.search(r"returncode\s*(?:in|not in)\s*[\(\[\{]", test_code)
            or re.search(r"returncode\s*(?:>|>=)\s*[1-9]", test_code)
            or re.search(r"assert\s+.*\.returncode\s*(?!==\s*0)", test_code)
        )
        if not asserts_failure:
            return False, "G2b_polarity: error-tagged test does not assert returncode != 0"
        # `returncode != 0` is trivially satisfied by a missing submission AND by a
        # token-stub that prints a fixed blob of error words. Require a SPECIFIC signal:
        # a stderr assertion on a service error code (NOT a generic "error"/"failed"
        # word a stub can farm), a stderr ==/startswith/endswith, or a pinned exit code.
        _generic_err = {"error", "errors", "exception", "failed", "failure", "invalid", "usage"}
        _stderr_tokens = re.findall(
            r"""["']([^"']+)["']\s+in\s+(?:[A-Za-z_]\w*\.)?stderr\b""", test_code
        )
        has_specific_stderr = any(
            t.strip().lower() not in _generic_err and len(t.strip()) >= 4 for t in _stderr_tokens
        )
        has_stderr_cmp = bool(re.search(r"\.stderr\s*(?:==|\.startswith|\.endswith)", test_code))
        _exit_pattern = (
            r"returncode\s*==\s*(?:1|252|254|255)\b"
            if is_kwok
            else r"returncode\s*==\s*(?:252|254|255)\b"
        )
        has_pinned_exit = bool(re.search(_exit_pattern, test_code))
        if not (has_specific_stderr or has_stderr_cmp or has_pinned_exit):
            return (
                False,
                "G2c_signal: error test lacks a SPECIFIC failure signal (a service error "
                "code in stderr, not a generic 'error'/'failed' word; or exit in "
                "{252,254,255}) - a token-stub farms generic words",
            )
    elif expected_behaviour_tag == "happy_path":
        asserts_success = bool(re.search(r"returncode\s*==\s*0", test_code))
        if not asserts_success:
            return False, "G2b_polarity: happy_path-tagged test does not assert returncode == 0"
        # `returncode == 0` is trivially satisfied by an empty submission
        # (empty main.py is valid Python and exits 0). Require the test to
        # verify state via the CLIENT fixture after cli() runs, so the assertion
        # depends on cli's observable effect and not just the exit code.
        if is_kwok:
            _state_regex = r"\b(?:k8s_client|kubectl_bin)\s*\.\s*[a-z_]+\s*\("
            _state_reason = (
                "G2d_state: happy_path-tagged test lacks a client-side state assertion "
                "(k8s_client./kubectl_bin. call); `returncode == 0` alone is "
                "nop-discriminative - an empty submission also exits 0"
            )
        else:
            _state_regex = r"\b(?:ddb_client|s3_client|minio_client)\s*\.\s*[a-z_]+\s*\("
            _state_reason = (
                "G2d_state: happy_path-tagged test lacks a client-side state assertion "
                "(ddb_client./s3_client./minio_client. call); `returncode == 0` alone is "
                "nop-discriminative - an empty main.py also exits 0"
            )
        has_state_check = bool(
            re.search(_state_regex, test_code) or re.search(r"\.\s*rpc\s*\(", test_code)
        )
        if not has_state_check:
            return False, _state_reason
    return True, ""


# ---------------------------------------------------------------------------
# Artefact builders (Dockerfile, conftest, test.sh, instruction.md)
# ---------------------------------------------------------------------------


def _build_dockerfile(
    *,
    base_image: str | None = None,
    bake_tests: bool = False,
    backend: str = "minio",
    golden: bool = False,
    golden_deps: tuple[str, ...] | None = None,
) -> str:
    """App layer on the baked polyglot base: MinIO server binary, test deps, the
    OpenHands SDK venv, aws-cli dep closure, submission scaffold + git baseline.
    bake_tests COPYs tests/ into the image for per-task ECR variance.

    backend="dynamodb_local" swaps to the DDB task_env base (JRE + DDB Local
    baked in) as a thin single-stage overlay; MinIO body below is returned for
    "minio".

    golden=True installs ``golden_deps`` (slice externals + grader harness) in
    place of ``PINNED_DEPS`` and SKIPS the ``AWSCLI_DEP_CLOSURE`` install —
    botocore and s3transfer are vendored under ``submission/`` by the slice.

    backend="kwok" routes to KwokSimulationBackend's dockerfile methods.
    """
    if backend == "kwok":
        from repo2rlenv.pipelines._cli_app_backends import get_backend

        kwok = get_backend("kwok")
        if golden:
            return kwok.dockerfile_golden_layer(golden_deps or ())
        return kwok.dockerfile_base(base_image)
    if backend == "dynamodb_local":
        # DDB defaults to the materialized DDB task_env image, not the S3 base.
        return _build_dockerfile_ddb(
            base_image=base_image or PINNED_DDB_BASE_IMAGE,
            bake_tests=bake_tests,
            golden=golden,
            golden_deps=golden_deps,
        )
    if base_image is None:
        base_image = PINNED_BASE_IMAGE
    active_deps = golden_deps if golden and golden_deps else PINNED_DEPS
    deps_line = " ".join(f'"{d}"' for d in active_deps)
    closure_line = " \\\n        ".join(f'"{d}"' for d in AWSCLI_DEP_CLOSURE)
    copy_tests = "COPY tests/ /workspace/tests/\n" if bake_tests else ""
    if golden:
        awscli_closure_block = ""
    else:
        awscli_closure_block = (
            'RUN pip install --no-cache-dir "urllib3>=1.25.4,<1.27" && \\\n'
            "    pip install --no-cache-dir --ignore-installed \\\n"
            f"        {closure_line}\n"
        )
    return (
        "# syntax=docker/dockerfile:1\n"
        "# Task environment for the aws CLI (S3/MinIO backend).\n"
        f"ARG BASE_IMAGE={base_image}\n"
        "FROM ${BASE_IMAGE}\n"
        "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \\\n"
        "    PYTHONHASHSEED=0 TZ=UTC LC_ALL=C.UTF-8 \\\n"
        "    AWS_ACCESS_KEY_ID=minioadmin AWS_SECRET_ACCESS_KEY=minioadmin \\\n"
        "    AWS_DEFAULT_REGION=us-east-1 \\\n"
        "    MINIO_UPDATE=off\n"
        "WORKDIR /workspace\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
        "      git ca-certificates && rm -rf /var/lib/apt/lists/*\n"
        f"ARG MINIO_VERSION={PINNED_MINIO_VERSION}\n"
        'RUN m="$(dpkg --print-architecture)"; \\\n'
        '    case "$m" in \\\n'
        f'      arm64) a=arm64; sha="{PINNED_MINIO_SHA256_ARM64}";; \\\n'
        f'      amd64) a=amd64; sha="{PINNED_MINIO_SHA256_AMD64}";; \\\n'
        '      *) echo "unsupported arch: $m" >&2; exit 1;; \\\n'
        "    esac; \\\n"
        '    curl -fsSL "https://dl.min.io/server/minio/release/linux-${a}/archive/minio.${MINIO_VERSION}" '
        "-o /usr/local/bin/minio && \\\n"
        '    echo "${sha}  /usr/local/bin/minio" | sha256sum -c - && \\\n'
        "    chmod +x /usr/local/bin/minio && minio --version\n"
        "RUN pip install --no-cache-dir --upgrade pip\n"
        f"RUN pip install --no-cache-dir {deps_line}\n"
        "RUN python3 -m venv /opt/openhands-sdk-venv && \\\n"
        "    /opt/openhands-sdk-venv/bin/pip install --no-cache-dir --upgrade pip && \\\n"
        "    /opt/openhands-sdk-venv/bin/pip install --no-cache-dir \\\n"
        '        "openhands-sdk @ https://github.com/Ethara-Ai/software-agent-sdk/archive/refs/tags/'
        f'{PINNED_OPENHANDS_VERSION}.tar.gz#subdirectory=openhands-sdk" \\\n'
        '        "openhands-tools @ https://github.com/Ethara-Ai/software-agent-sdk/archive/refs/tags/'
        f'{PINNED_OPENHANDS_VERSION}.tar.gz#subdirectory=openhands-tools" \\\n'
        f'        "fastapi=={PINNED_FASTAPI_VERSION}" "google-cloud-aiplatform=={PINNED_GCP_AIPLATFORM_VERSION}"\n'
        f"{awscli_closure_block}"
        f"{copy_tests}"
        # Don't pre-create submission/main.py — the gold patch is a `new file`
        # diff that `git apply` rejects as "already exists" if the file is present.
        "RUN mkdir -p /workspace/submission && touch /workspace/submission/.gitkeep\n"
        # The submission's `aws` executable lives here and shadows any base-image
        # aws-cli so tests exercise the submission, not the real binary.
        "ENV PATH=/workspace/submission:$PATH\n"
        "RUN git config --global --add safe.directory /workspace && \\\n"
        "    git init -q /workspace && \\\n"
        "    git -C /workspace config user.email raiden@local && \\\n"
        "    git -C /workspace config user.name raiden && \\\n"
        "    git -C /workspace add -A && \\\n"
        "    git -C /workspace commit -q --allow-empty -m 'raiden: baseline'\n"
    )


def _build_dockerfile_ddb(
    *,
    base_image: str = PINNED_DDB_BASE_IMAGE,
    bake_tests: bool = False,
    golden: bool = False,
    golden_deps: tuple[str, ...] | None = None,
) -> str:
    """DynamoDB-Local variant of the app Dockerfile.

    Single-stage overlay on the polyglot DDB task_env base image (Python/Go/
    Node/JDK21/Ruby/PHP/Rust + awscrt + boto3 deps + pytest baked in). DynamoDB
    Local runs as a compose sidecar reachable at ``http://ddb:8000`` (wired via
    AWS_ENDPOINT_URL below — the ``ddb`` hostname matches the compose service
    name emitted in environment/docker-compose.yaml). The task Dockerfile only
    layers determinism ENV, the openhands-sdk venv, the submission scaffold,
    and the git baseline; all runtime pip deps live in the base image.
    The real ``aws`` binary is NOT added here (anti-cheat) — it lives only in
    the derived reference-grounding image.
    """
    copy_tests = "COPY tests/ /workspace/tests/\n" if bake_tests else ""
    return (
        "# syntax=docker/dockerfile:1\n"
        f"ARG BASE_IMAGE={base_image}\n"
        "FROM ${BASE_IMAGE}\n"
        "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \\\n"
        "    PYTHONHASHSEED=0 TZ=UTC LC_ALL=C.UTF-8 \\\n"
        "    AWS_ACCESS_KEY_ID=raidentest AWS_SECRET_ACCESS_KEY=raidentest \\\n"
        "    AWS_DEFAULT_REGION=us-east-1 \\\n"
        "    AWS_ENDPOINT_URL=http://ddb:8000\n"
        "WORKDIR /workspace\n"
        "RUN python3 -m venv /opt/openhands-sdk-venv && \\\n"
        "    /opt/openhands-sdk-venv/bin/pip install --no-cache-dir --upgrade pip && \\\n"
        "    /opt/openhands-sdk-venv/bin/pip install --no-cache-dir \\\n"
        '        "openhands-sdk @ https://github.com/Ethara-Ai/software-agent-sdk/archive/refs/tags/'
        f'{PINNED_OPENHANDS_VERSION}.tar.gz#subdirectory=openhands-sdk" \\\n'
        '        "openhands-tools @ https://github.com/Ethara-Ai/software-agent-sdk/archive/refs/tags/'
        f'{PINNED_OPENHANDS_VERSION}.tar.gz#subdirectory=openhands-tools" \\\n'
        f'        "fastapi=={PINNED_FASTAPI_VERSION}" "google-cloud-aiplatform=={PINNED_GCP_AIPLATFORM_VERSION}"\n'
        f"{copy_tests}"
        # Don't pre-create submission/main.py — the gold patch is a `new file`
        # diff that `git apply` rejects as "already exists" if the file is present.
        "RUN mkdir -p /workspace/submission && touch /workspace/submission/.gitkeep\n"
        "ENV PATH=/workspace/submission:$PATH\n"
        "RUN git config --global --add safe.directory /workspace && \\\n"
        "    git init -q /workspace && \\\n"
        "    git -C /workspace config user.email raiden@local && \\\n"
        "    git -C /workspace config user.name raiden && \\\n"
        "    git -C /workspace add -A && \\\n"
        "    git -C /workspace commit -q --allow-empty -m 'raiden: baseline'\n"
    )


def _build_conftest(*, backend: str = "minio", golden: bool = False) -> str:
    """Network-isolated conftest with S3 server + cli subprocess wrapper.

    The verifier-phase socket guard reuses ``BLOCKED_SUFFIXES`` from
    ``emitter/harbor`` as its single source of truth so the Docker-layer
    disallow-list and the Python-layer guard cannot drift. Public IP
    literals are rejected outright (closing the IP-bypass route a pure
    suffix blocklist leaves open).

    backend="dynamodb_local" returns the DynamoDB Local conftest instead; the
    MinIO body below is byte-identical for "minio".

    golden=True switches the ``cli`` fixture's subprocess invocation from
    ``[sys.executable, "/workspace/submission/main.py", ...]`` (the LLM oracle
    layout) to ``["/workspace/submission/aws", ...]`` (the sliced-aws-cli shim
    the golden slice ships). The rest of the conftest is identical.
    """
    if backend == "kwok":
        from repo2rlenv.pipelines._cli_app_backends import get_backend

        return get_backend("kwok").build_conftest(golden=golden)
    if backend == "dynamodb_local":
        return _build_conftest_ddb(golden=golden)
    suffixes_literal = ", ".join(repr(s) for s in BLOCKED_SUFFIXES)
    cli_prefix = (
        '"/workspace/submission/aws"'
        if golden
        else 'sys.executable, "/workspace/submission/main.py"'
    )
    template = '''"""Test fixtures for the aws CLI task (MinIO/S3 backend).

Module-scoped MinIO subprocess + iterate-and-delete reset between tests.
The agent's submission runs as a subprocess; we boot MinIO on a random
loopback port and pass MINIO_* env vars (plus defensive AWS_* env) so
both the test and the subprocess reach the same server.
"""

import ipaddress
import os
import socket as _socket
import subprocess
import sys
import time as _time
import http.client as _http

_ORIG_CONNECT = _socket.socket.connect
_BLOCKED_SUFFIXES = (__BLOCKED_SUFFIXES__,)


def _guarded_connect(self, address):
    if self.family in (_socket.AF_INET, _socket.AF_INET6) and isinstance(address, tuple):
        host = address[0]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            for suffix in _BLOCKED_SUFFIXES:
                if host.lower() == suffix or host.lower().endswith("." + suffix):
                    raise RuntimeError(f"network-isolation: connect to {host!r} blocked")
        else:
            if not (ip.is_loopback or ip.is_private):
                raise RuntimeError(
                    f"network-isolation: connect to public IP {host!r} blocked"
                )
    return _ORIG_CONNECT(self, address)


_socket.socket.connect = _guarded_connect
def _guarded_connect_ex(self, addr):
    import errno as _errno
    try:
        _guarded_connect(self, addr)
        return 0
    except RuntimeError:
        return _errno.EACCES
    except OSError as exc:
        return exc.errno
_socket.socket.connect_ex = _guarded_connect_ex

import pytest
from io import BytesIO
from minio import Minio
from minio.error import S3Error


def _grab_free_port(retries=3):
    """Retry on bind-time races; rare but observed on busy CI."""
    last_err = None
    for _ in range(retries):
        try:
            sock = _socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            return port
        except OSError as e:
            last_err = e
            _time.sleep(0.05)
    raise RuntimeError(f"could not bind ephemeral port: {last_err}")


@pytest.fixture(scope="module")
def minio_server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("minio-data")
    port = _grab_free_port()
    endpoint = f"127.0.0.1:{port}"

    proc = subprocess.Popen(
        ["minio", "server", str(data_dir),
         "--address", f":{port}",
         "--console-address", ":0"],
        env={
            **os.environ,
            "MINIO_ROOT_USER": "minioadmin",
            "MINIO_ROOT_PASSWORD": "minioadmin",
            "MINIO_UPDATE": "off",
            "MINIO_BROWSER": "off",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(50):
        try:
            conn = _http.HTTPConnection(endpoint, timeout=0.2)
            conn.request("GET", "/minio/health/live")
            if conn.getresponse().status == 200:
                break
        except OSError:
            pass
        _time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("minio failed to start within 5s")

    try:
        yield endpoint
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def s3_client(minio_server):
    return Minio(
        minio_server,
        access_key="minioadmin",
        secret_key="minioadmin",
        secure=False,
    )


@pytest.fixture(autouse=True)
def _reset_minio(s3_client):
    try:
        buckets = list(s3_client.list_buckets())
        for bucket in buckets:
            for obj in s3_client.list_objects(bucket.name, recursive=True):
                s3_client.remove_object(bucket.name, obj.object_name)
            s3_client.remove_bucket(bucket.name)
    except S3Error:
        pass
    yield


@pytest.fixture
def cli(minio_server):
    def _run(*args, env_overrides=None, timeout=60):
        env = os.environ.copy()
        env["MINIO_ENDPOINT"] = minio_server
        env["MINIO_ACCESS_KEY"] = "minioadmin"
        env["MINIO_SECRET_KEY"] = "minioadmin"
        env["MINIO_SECURE"] = "false"
        env["AWS_ENDPOINT_URL_S3"] = f"http://{minio_server}"
        env["AWS_ENDPOINT_URL"] = f"http://{minio_server}"
        env["AWS_ACCESS_KEY_ID"] = "minioadmin"
        env["AWS_SECRET_ACCESS_KEY"] = "minioadmin"
        env["AWS_DEFAULT_REGION"] = "us-east-1"
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [__CLI_PREFIX__, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return _run
'''
    return template.replace("__BLOCKED_SUFFIXES__", suffixes_literal).replace(
        "__CLI_PREFIX__", cli_prefix
    )


# Shipped verbatim as tests/_ddb_http.py. A stdlib-only (urllib) DynamoDB client
# that speaks the DynamoDB JSON wire protocol. There is no independent no-boto
# SDK equivalent to MinIO's `minio` package, so the verifier talks to DynamoDB
# Local over raw HTTP. Returns boto-shaped dicts so test assertions read
# naturally. The submission never imports it (it lives only under tests/).
_DDB_HTTP_HELPER = '''"""Stdlib-only raw-HTTP DynamoDB client for the verifier (DynamoDB JSON, v20120810).

No boto3 / botocore / moto — we speak the wire protocol directly over urllib.
Numbers travel as JSON strings ({"N": "5"}); helpers marshal to/from native Python.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

_TARGET_PREFIX = "DynamoDB_20120810"

# DynamoDB Local does not verify the SigV4 signature but wants a well-formed
# Authorization header; the signature value is ignored.
_AUTH = (
    "AWS4-HMAC-SHA256 "
    "Credential=dummy/20120810/us-east-1/dynamodb/aws4_request, "
    "SignedHeaders=content-type;host;x-amz-target, "
    "Signature=0000000000000000000000000000000000000000000000000000000000000000"
)


class DDBHTTPError(Exception):
    """boto-shaped: .response['Error']['Code'] carries the DynamoDB error code."""

    def __init__(self, code, message, status, operation=""):
        super().__init__(
            "An error occurred (%s) when calling the %s operation: %s"
            % (code, operation, message)
        )
        self.response = {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        self.operation_name = operation


ClientError = DDBHTTPError


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


def _pynum(s):
    try:
        return int(s)
    except ValueError:
        return float(s)


def to_av(v):
    """Marshal a native Python value into a DynamoDB AttributeValue."""
    if v is None:
        return {"NULL": True}
    if isinstance(v, bool):
        return {"BOOL": v}
    if isinstance(v, (int, float)):
        return {"N": _num(v)}
    if isinstance(v, str):
        return {"S": v}
    if isinstance(v, (bytes, bytearray)):
        return {"B": base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, dict):
        return {"M": {k: to_av(x) for k, x in v.items()}}
    if isinstance(v, (list, tuple)):
        return {"L": [to_av(x) for x in v]}
    if isinstance(v, set):
        elems = list(v)
        if elems and all(isinstance(x, str) for x in elems):
            return {"SS": elems}
        if elems and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in elems):
            return {"NS": [_num(x) for x in elems]}
        if elems and all(isinstance(x, (bytes, bytearray)) for x in elems):
            return {"BS": [base64.b64encode(bytes(x)).decode("ascii") for x in elems]}
    raise TypeError("cannot marshal %r to a DynamoDB AttributeValue" % (type(v),))


def from_av(av):
    """Unmarshal a DynamoDB AttributeValue into a native Python value."""
    (tag, val), = av.items()
    if tag == "NULL":
        return None
    if tag == "BOOL":
        return val
    if tag == "N":
        return _pynum(val)
    if tag == "S":
        return val
    if tag == "B":
        return base64.b64decode(val)
    if tag == "M":
        return {k: from_av(x) for k, x in val.items()}
    if tag == "L":
        return [from_av(x) for x in val]
    if tag == "SS":
        return set(val)
    if tag == "NS":
        return {_pynum(x) for x in val}
    if tag == "BS":
        return {base64.b64decode(x) for x in val}
    raise ValueError("unknown AttributeValue tag %r" % (tag,))


def to_item(d):
    return {k: to_av(v) for k, v in d.items()}


def from_item(d):
    return {k: from_av(v) for k, v in (d or {}).items()}


class DDBClient:
    def __init__(self, endpoint_url=None, region_name="us-east-1"):
        endpoint_url = (
            endpoint_url
            or os.environ.get("AWS_ENDPOINT_URL_DYNAMODB")
            or os.environ.get("AWS_ENDPOINT_URL")
        )
        p = urlparse(endpoint_url)
        self.endpoint = ("%s://%s" % (p.scheme, p.netloc)) if p.scheme else ("http://%s" % endpoint_url)
        self.region = region_name

    def _request(self, operation, payload, timeout=5.0):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-amz-json-1.0",
                "X-Amz-Target": "%s.%s" % (_TARGET_PREFIX, operation),
                "X-Amz-Date": "20120810T000000Z",
                "Authorization": _AUTH,
                "Host": urlparse(self.endpoint).netloc,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                doc = json.loads(raw)
            except Exception:
                doc = {}
            raw_type = doc.get("__type", "") or ""
            code = raw_type.split("#")[-1] if "#" in raw_type else (raw_type or "UnknownError")
            message = doc.get("message") or doc.get("Message") or ""
            raise DDBHTTPError(code, message, e.code, operation) from None

    def list_tables(self):
        return self._request("ListTables", {})

    def create_table(self, TableName, KeySchema, AttributeDefinitions,
                     BillingMode="PAY_PER_REQUEST", **extra):
        payload = {
            "TableName": TableName,
            "KeySchema": KeySchema,
            "AttributeDefinitions": AttributeDefinitions,
            "BillingMode": BillingMode,
        }
        payload.update(extra)
        return self._request("CreateTable", payload)

    def delete_table(self, TableName):
        return self._request("DeleteTable", {"TableName": TableName})

    def put_item(self, TableName, Item, **extra):
        payload = {"TableName": TableName, "Item": Item}
        payload.update(extra)
        return self._request("PutItem", payload)

    def get_item(self, TableName, Key, ConsistentRead=True, **extra):
        payload = {"TableName": TableName, "Key": Key, "ConsistentRead": ConsistentRead}
        payload.update(extra)
        return self._request("GetItem", payload)

    def update_item(self, TableName, Key, **extra):
        payload = {"TableName": TableName, "Key": Key}
        payload.update(extra)
        return self._request("UpdateItem", payload)

    def delete_item(self, TableName, Key, **extra):
        payload = {"TableName": TableName, "Key": Key}
        payload.update(extra)
        return self._request("DeleteItem", payload)

    def query(self, TableName, ConsistentRead=True, **extra):
        payload = {"TableName": TableName, "ConsistentRead": ConsistentRead}
        payload.update(extra)
        return self._request("Query", payload)

    def reset_all_tables(self):
        for name in self.list_tables().get("TableNames", []):
            try:
                self.delete_table(name)
            except DDBHTTPError as exc:
                if exc.response.get("Error", {}).get("Code", "") != "ResourceNotFoundException":
                    raise
'''


def _build_conftest_ddb(*, golden: bool = False) -> str:
    """Session-scoped DynamoDB Local sidecar client + drop-all-tables reset.

    The test container reaches DDB Local via ``AWS_ENDPOINT_URL_DYNAMODB``
    (or ``AWS_ENDPOINT_URL``) supplied by docker-compose — the ``ddb`` service
    at ``http://ddb:8000``. Compose's healthcheck gates ``main`` behind
    ``ddb: service_healthy`` so the engine is reachable by the time pytest
    starts; we still poll defensively for ad-hoc invocations that bypass
    healthchecks.

    golden=True switches the ``cli`` fixture's subprocess invocation from
    ``[sys.executable, "/workspace/submission/main.py", ...]`` (the LLM
    oracle layout) to ``["/workspace/submission/aws", ...]`` (the sliced-
    aws-cli shim the golden slice ships). Mirrors the S3 conftest so the
    reference-grounding gauntlet actually executes the submission instead
    of bypassing it to the real ``aws`` binary on PATH.
    """
    suffixes_literal = ", ".join(repr(s) for s in BLOCKED_SUFFIXES_DDB)
    cli_prefix = (
        '"/workspace/submission/aws"'
        if golden
        else 'sys.executable, "/workspace/submission/main.py"'
    )
    cli_check_path = "/workspace/submission/aws" if golden else "/workspace/submission/main.py"
    template = '''"""Session-scoped DynamoDB Local (compose sidecar) client + drop-all-tables reset
between tests. The engine is reached via AWS_ENDPOINT_URL_DYNAMODB, wired by
docker-compose to the ``ddb`` service at http://ddb:8000. The agent's submission
runs as a subprocess and inherits the same endpoint env.
"""

import ipaddress
import os
import socket as _socket
import subprocess
import sys
import time as _time

_ORIG_CONNECT = _socket.socket.connect
_BLOCKED_SUFFIXES = (__BLOCKED_SUFFIXES__,)


def _guarded_connect(self, address):
    if self.family in (_socket.AF_INET, _socket.AF_INET6) and isinstance(address, tuple):
        host = address[0]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            for suffix in _BLOCKED_SUFFIXES:
                if host.lower() == suffix or host.lower().endswith("." + suffix):
                    raise RuntimeError(f"network-isolation: connect to {host!r} blocked")
        else:
            if not (ip.is_loopback or ip.is_private):
                raise RuntimeError(
                    f"network-isolation: connect to public IP {host!r} blocked"
                )
    return _ORIG_CONNECT(self, address)


_socket.socket.connect = _guarded_connect
def _guarded_connect_ex(self, addr):
    import errno as _errno
    try:
        _guarded_connect(self, addr)
        return 0
    except RuntimeError:
        return _errno.EACCES
    except OSError as exc:
        return exc.errno
_socket.socket.connect_ex = _guarded_connect_ex

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from _ddb_http import DDBClient, DDBHTTPError  # noqa: E402


def pytest_configure(config):
    if not os.path.exists("__CLI_CHECK_PATH__"):
        pytest.exit(
            "Anti-NOP guard FAILED: submission entrypoint __CLI_CHECK_PATH__ "
            "not found (no submission to evaluate). Reward=0.",
            returncode=1,
        )


@pytest.fixture(scope="session")
def _ddb_server():
    endpoint = (
        os.environ.get("AWS_ENDPOINT_URL_DYNAMODB")
        or os.environ.get("AWS_ENDPOINT_URL")
        or "http://ddb:8000"
    )
    client = DDBClient(endpoint_url=endpoint)
    # Defensive poll (~30s). Compose healthcheck normally gates us behind
    # `ddb: service_healthy`, but ad-hoc invocations may bypass that.
    for _ in range(300):
        try:
            client.list_tables()
            return endpoint
        except DDBHTTPError:
            return endpoint
        except OSError:
            _time.sleep(0.1)
    raise RuntimeError(f"dynamodb sidecar at {endpoint} not reachable within 30s")


@pytest.fixture
def ddb_client(_ddb_server):
    return DDBClient(endpoint_url=_ddb_server)


@pytest.fixture(autouse=True)
def _reset_ddb(ddb_client):
    ddb_client.reset_all_tables()
    yield
    ddb_client.reset_all_tables()


@pytest.fixture
def cli(_ddb_server):
    def _run(*args, env_overrides=None, timeout=60):
        env = os.environ.copy()
        env["AWS_ENDPOINT_URL_DYNAMODB"] = _ddb_server
        env["AWS_ENDPOINT_URL"] = _ddb_server
        env.setdefault("AWS_ACCESS_KEY_ID", "raidentest")
        env.setdefault("AWS_SECRET_ACCESS_KEY", "raidentest")
        env.setdefault("AWS_DEFAULT_REGION", "us-east-1")
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [__CLI_PREFIX__, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return _run
'''
    return (
        template.replace("__BLOCKED_SUFFIXES__", suffixes_literal)
        .replace("__CLI_PREFIX__", cli_prefix)
        .replace("__CLI_CHECK_PATH__", cli_check_path)
    )


def _build_test_script() -> str:
    """JUnit-XML reward parser (v2) with tests_shipped collection-drift guard.

    The v1 grep-based pass/fail counter is fragile against pytest output-format
    changes and cannot detect test-collection drift. v2 parses JUnit XML for
    exact counts and, when task.toml declares ``tests_shipped``, forces
    reward=0 if pytest collected fewer tests than were shipped (catches
    silent conftest failures or filename-based deselection).
    """
    return r"""#!/bin/bash

set -uxo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_TOML="$SCRIPT_DIR/../task.toml"
mkdir -p /workspace/submission
cd /workspace
mkdir -p /logs/verifier

export PYTHONPATH="/opt/test-libs${PYTHONPATH:+:}${PYTHONPATH:-}"

python -m pytest "$SCRIPT_DIR" -v --tb=short -p no:randomly \
    --junit-xml=/logs/verifier/results.xml \
    > /logs/verifier/pytest_output.log 2>&1
cat /logs/verifier/pytest_output.log

TASK_TOML="$TASK_TOML" python3 << 'PY' > /logs/verifier/reward.txt
import os, re, sys, xml.etree.ElementTree as ET
from pathlib import Path

XML = "/logs/verifier/results.xml"
TOML = os.environ.get("TASK_TOML", "")

expected = None
if TOML and Path(TOML).exists():
    for line in Path(TOML).read_text().splitlines():
        m = re.match(r"\s*tests_shipped\s*=\s*(\d+)", line)
        if m:
            expected = int(m.group(1))
            break

try:
    root = ET.parse(XML).getroot()
except Exception as e:
    sys.stderr.write(f"reward parser v2: could not parse {XML}: {e}\n")
    print("0.0")
    sys.exit(0)

suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
tests = failures = errors = skipped = 0
for s in suites:
    tests    += int(s.get("tests",    0) or 0)
    failures += int(s.get("failures", 0) or 0)
    errors   += int(s.get("errors",   0) or 0)
    skipped  += int(s.get("skipped",  0) or 0)
passed = tests - failures - errors - skipped

if expected is not None and tests < expected:
    sys.stderr.write(
        f"reward parser v2: COLLECTION DRIFT - task.toml.tests_shipped={expected} "
        f"but JUnit reports tests={tests}. Reward=0.\n"
    )
    print("0.0")
    sys.exit(0)

total = passed + failures + errors
print(round(passed / total, 4) if total else 0.0)
PY

REWARD=$(cat /logs/verifier/reward.txt)
echo "reward=$REWARD parser=v2"
exit 0
"""


# Per-command state model. Hardcoded because it's NOT inferable from the
# AST-extracted intents — it's the cross-command behaviour contract the
# client doc explicitly asks for ("after cp uploads a file, ls must show it,
# cp back must retrieve identical content"). Extend when new commands ship.
_COMMAND_STATE_MODEL: dict[tuple[str, str], str] = {
    ("s3", "mb"): (
        "- After successful creation, the bucket appears in the output of `list-buckets`.\n"
        "- Creating a bucket the caller already owns: SUCCEEDS (exit 0, idempotent).\n"
        "- Creating a bucket owned by another account: FAILS with stderr containing\n"
        "  `BucketAlreadyExists` or `BucketAlreadyOwnedByYou`.\n"
        "- `--region <r>` MUST be applied as `LocationConstraint` (except `us-east-1`,\n"
        "  which omits the constraint)."
    ),
    ("s3", "rb"): (
        "- After successful removal, the bucket no longer appears in `list-buckets`.\n"
        "- Removing a non-existent bucket: FAILS (exit 1, stderr contains `NoSuchBucket`).\n"
        "- Removing a non-empty bucket without `--force`: FAILS (exit 1, stderr mentions\n"
        "  the bucket is not empty).\n"
        "- With `--force`: deletes all objects first, then the bucket."
    ),
    ("s3", "cp"): (
        "- Local-to-S3 (`<local> s3://...`): uploads via `PutObject`. After success, the\n"
        "  object is retrievable via `GetObject` and listed by `ListObjectsV2`.\n"
        "- S3-to-local (`s3://... <local>`): downloads via `GetObject`. Local file is\n"
        "  byte-identical to the source object.\n"
        "- S3-to-S3 (`s3://A s3://B`): copies via `CopyObject`. Both copies exist\n"
        "  independently after the operation.\n"
        "- **Round-trip invariant**: `cp local.txt s3://b/k` then `cp s3://b/k local2.txt`\n"
        "  MUST produce `local2.txt` byte-identical to `local.txt`.\n"
        "- Encryption flags (`--sse`, `--sse-kms-key-id`) MUST be passed through as\n"
        "  `ServerSideEncryption` and `SSEKMSKeyId` on the underlying `PutObject` call."
    ),
    ("s3", "ls"): (
        "- `ls` with no path: lists all buckets (one per line, with creation date).\n"
        "- `ls s3://<bucket>/`: lists objects (and common prefixes) under that bucket.\n"
        "- `ls s3://<bucket>/<prefix>`: lists matching keys under the prefix.\n"
        "- `--recursive`: walks all sub-prefixes; output is flat (no `PRE` directory entries).\n"
        "- `--page-size <n>`: passed to `ListObjectsV2` as `MaxKeys`.\n"
        "- Empty bucket: succeeds (exit 0, empty output).\n"
        "- Non-existent bucket: FAILS (exit 1, stderr contains `NoSuchBucket`)."
    ),
    ("s3", "mv"): (
        "- Equivalent to `cp` followed by `rm` of the source on success.\n"
        "- Source and destination of the same S3 URI: FAILS (cannot move object onto itself).\n"
        "- After successful local-to-S3 move: local file removed, S3 object exists.\n"
        "- After successful S3-to-S3 move: source S3 key removed, destination S3 key exists.\n"
        "- After successful S3-to-local move: S3 key removed, local file created."
    ),
    ("s3", "rm"): (
        "- After successful removal, the object is no longer retrievable via `GetObject`\n"
        "  and no longer appears in `ListObjectsV2`.\n"
        "- `rm s3://b/k` removes a single object via `DeleteObject`.\n"
        "- `rm s3://b/prefix --recursive` removes all matching objects via `DeleteObjects`.\n"
        "- Removing a non-existent object: SUCCEEDS silently (idempotent, like real aws-cli).\n"
        "- `--request-payer requester` MUST be reflected as an `x-amz-request-payer` "
        "header on the underlying S3 request."
    ),
    ("s3", "sync"): (
        "- Syncs source → destination, transferring only files that are newer or absent.\n"
        "- Local-to-S3: uploads files that don't exist in S3 or whose local mtime is newer.\n"
        "- S3-to-local: downloads objects that don't exist locally or whose S3 LastModified is newer.\n"
        "- After sync, the destination's file/object set MUST be a superset of the source's.\n"
        "- Sync does NOT delete by default; `--delete` (if supported) removes destination items\n"
        "  not present at source.\n"
        "- Non-existent source directory (local): FAILS (non-zero exit, typically 252 "
        "or 255; stderr contains `does not exist`)."
    ),
    ("s3", "presign"): (
        "- Outputs a time-limited presigned URL on stdout for `GET <s3://bucket/key>`.\n"
        "- `--expires-in <seconds>` controls TTL (default 3600).\n"
        "- URL format: `https://<bucket>.s3.amazonaws.com/<key>?<query-params>`\n"
        "  with `X-Amz-Algorithm`, `X-Amz-Credential`, `X-Amz-Date`, `X-Amz-Expires`,\n"
        "  `X-Amz-Signature` query parameters."
    ),
    ("s3", "website"): (
        "- Configures static-website hosting on a bucket via `PutBucketWebsite`.\n"
        "- `--index-document <name>` sets the index suffix (default `index.html`).\n"
        "- `--error-document <name>` sets the error key.\n"
        "- Removing website config (`website s3://bucket` with no flags or `--delete`)\n"
        "  calls `DeleteBucketWebsite`."
    ),
    # --- DynamoDB (pilot: PAY_PER_REQUEST only; assert on codes, never wording) ---
    ("dynamodb", "create-table"): (
        "- After successful creation the table appears in `list-tables`.\n"
        "- Re-creating an existing table name FAILS with `ResourceInUseException`.\n"
        "- `--billing-mode PAY_PER_REQUEST` is used; do NOT rely on provisioned-throughput\n"
        "  behaviour (it is ignored by the sandbox).\n"
        "- `--key-schema` + `--attribute-definitions` must agree; a key attribute missing\n"
        "  from the definitions FAILS with `ValidationException`."
    ),
    ("dynamodb", "delete-table"): (
        "- After success the table no longer appears in `list-tables`.\n"
        "- Deleting a non-existent table FAILS with `ResourceNotFoundException`."
    ),
    ("dynamodb", "list-tables"): (
        "- Returns the set of existing table names on stdout as JSON.\n"
        "- With no tables, succeeds (exit 0) with an empty `TableNames` list.\n"
        "- Assert membership as a set — never rely on ordering."
    ),
    ("dynamodb", "put-item"): (
        "- Writes an item; afterward `get-item` on the same key returns it.\n"
        "- `--condition-expression attribute_not_exists(pk)` on an existing key FAILS\n"
        "  with `ConditionalCheckFailedException` and leaves the stored item unchanged.\n"
        '- Numbers are JSON strings (`{"N": "5"}`).\n'
        "- Writing to a missing table FAILS with `ResourceNotFoundException`."
    ),
    ("dynamodb", "get-item"): (
        '- Returns `{"Item": ...}` for an existing key; when the key is absent the\n'
        "  response has NO `Item` member (exit 0).\n"
        "- Reading from a missing table FAILS with `ResourceNotFoundException`.\n"
        "- Reads are strongly consistent."
    ),
    ("dynamodb", "update-item"): (
        "- Applies an `UpdateExpression` (e.g. `SET #s = :v`) with\n"
        "  `--expression-attribute-names` / `--expression-attribute-values`; afterward\n"
        "  `get-item` reflects the change.\n"
        "- A reserved word used unescaped in the expression FAILS with `ValidationException`\n"
        "  (use `--expression-attribute-names` to alias reserved words like `Status`).\n"
        "- A failing `--condition-expression` FAILS with `ConditionalCheckFailedException`\n"
        "  and does NOT mutate the item."
    ),
    ("dynamodb", "delete-item"): (
        "- After success `get-item` on the key returns no `Item`.\n"
        "- Deleting a non-existent key SUCCEEDS silently (idempotent).\n"
        "- A failing `--condition-expression` FAILS with `ConditionalCheckFailedException`."
    ),
    ("dynamodb", "query"): (
        "- Returns items whose partition key matches the `--key-condition-expression`\n"
        "  (e.g. `pk = :v`), as `Items` on stdout.\n"
        "- Assert result membership as an order-insensitive set unless a sort-key range\n"
        "  is specified.\n"
        "- Querying on a non-key attribute in the key condition FAILS with `ValidationException`."
    ),
}

# Friendly English for S3 API operation names — used to render "Expected
# observable side effects" without leaking test internals.
_OP_TO_ENGLISH: dict[str, str] = {
    "PutObject": "upload an object to S3",
    "GetObject": "download an object from S3",
    "DeleteObject": "delete one object from S3",
    "DeleteObjects": "delete multiple objects from S3",
    "CopyObject": "copy an object between S3 locations",
    "ListObjectsV2": "list objects under a prefix",
    "ListBuckets": "list all buckets visible to the caller",
    "CreateBucket": "create a bucket",
    "DeleteBucket": "delete a bucket",
    "HeadBucket": "check bucket existence/permission",
    "HeadObject": "fetch object metadata",
    "PutBucketWebsite": "configure static-website settings on a bucket",
    "DeleteBucketWebsite": "remove static-website settings from a bucket",
    "GetBucketLocation": "resolve a bucket's region",
    "PutBucketAcl": "set a bucket's ACL",
    "UploadPart": "upload one chunk of a multipart upload",
    "CreateMultipartUpload": "begin a multipart upload",
    "CompleteMultipartUpload": "finalise a multipart upload",
    # DynamoDB
    "CreateTable": "create a table",
    "DeleteTable": "delete a table",
    "ListTables": "list table names",
    "PutItem": "write an item",
    "GetItem": "read an item by key",
    "UpdateItem": "update attributes of an item",
    "DeleteItem": "delete an item by key",
    "Query": "query items by partition key",
}


def _build_instruction_md(
    spec: CliSpec,
    cmd_spec: CommandSpec,
    intents: list[TestIntent],
    *,
    backend: str = "minio",
) -> str:
    """Render the agent-facing instruction.md.

    Matches the client doc's deliverable shape (Pilot RL Environment Creation,
    "Feature Specification"): app description + per-command interface + I/O +
    error behaviour + cross-command state expectations + examples.

    Built ONLY from CliSpec + extracted intents — never reads raw_source or
    test bodies. `_assert_no_test_leakage` is the safety net. backend
    ="dynamodb_local" renders the DynamoDB variant; the MinIO body below is
    byte-identical for "minio".
    """
    if backend == "dynamodb_local":
        return _build_instruction_md_ddb(spec, cmd_spec, intents)
    if backend == "kwok":
        return _build_instruction_md_kwok(spec, cmd_spec, intents)
    by_tag = _group_by_tag(intents)
    flags = _extract_flags_from_intents(intents)
    cmd_label = f"{spec.command_prefix} {cmd_spec.name}"
    state_model = _COMMAND_STATE_MODEL.get((spec.command_prefix, cmd_spec.name))

    parts: list[str] = []

    # 1. Title + application overview
    parts.append(f"# Build `aws {cmd_label}` from scratch\n")
    parts.append(
        "## Application overview\n\n"
        f"You are implementing the `aws {cmd_label}` subcommand of the AWS CLI's S3\n"
        "family. The agent is given **no source code**, only this specification.\n"
        "Your implementation will be invoked as a subprocess:\n\n"
        "```bash\n"
        f"python /workspace/submission/main.py {cmd_label} [args...]\n"
        "```\n\n"
        "The harness configures the runtime environment so that the S3 client\n"
        "reaches a sandboxed, isolated S3-compatible endpoint. Read credentials\n"
        "and endpoint from the environment; do not hard-code them in your code.\n"
        "Treat the backend as real AWS S3: your implementation should be\n"
        "correct against the actual S3 API contract.\n"
    )

    # 2. Command spec
    parts.append(f"## Command: `{cmd_label}`\n")

    # 2a. Interface (positional args + flags)
    parts.append("### Interface\n\nObserved argv patterns (after `python submission/main.py`):\n")
    seen_shapes: set[str] = set()
    for intent in intents:
        if _is_internal_mutation_intent(intent):
            continue
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen_shapes:
            seen_shapes.add(shape)
            parts.append(f"- `{shape}`")
    parts.append("")
    if flags:
        parts.append("**Flags observed in the reference test suite:**\n")
        parts.append("| Flag | Example value |")
        parts.append("|---|---|")
        for f, v in sorted(flags.items()):
            parts.append(f"| `{f}` | `{v}` |" if v else f"| `{f}` | _(boolean)_ |")
        parts.append("")

    # 2b. Expected I/O
    success_ops = sorted(
        {op for i in intents if i.expected_exit == 0 for op in i.expected_state_calls}
    )
    parts.append("### Expected I/O\n")
    parts.append("**On success (exit 0):**")
    parts.append(
        "- stdout: aws-cli-style success line — `make_bucket: <name>` for `mb`,"
        " `delete: s3://<b>/<k>` for `rm`, `upload: <src> to <dst>` for `cp` upload, etc.\n"
        "  Real aws-cli may print progress lines (`Completed N Bytes(s)...`) BEFORE\n"
        "  the success line for `cp`/`mv`/`sync`. Tests should match the success line\n"
        "  as a substring ANYWHERE in stdout (`pattern in result.stdout`), NEVER via\n"
        "  `result.stdout.splitlines()[0]`. Your implementation may either emit the\n"
        "  progress lines or accept `--no-progress` to suppress them.\n"
        "- stderr: empty\n"
        "- exit: 0"
    )
    if success_ops:
        bullets = ", ".join(f"`{op}`" for op in success_ops)
        ens = "; ".join(f"{op} = {_OP_TO_ENGLISH.get(op, op)}" for op in success_ops)
        parts.append(
            "- **Observable side effects** — the underlying S3 operations invoked must\n"
            f"  include at least: {bullets}.\n"
            f"  (Plain English: {ens}.)"
        )
    parts.append("")
    parts.append("**On error (exit ≠ 0):**")
    if by_tag.get("error"):
        parts.append("- stdout: empty")
        parts.append(
            "- stderr: human-readable error identifying the CATEGORY (e.g."
            " `NoSuchBucket`, `NoSuchKey`, `does not exist`, `InvalidBucketName`,"
            " `AccessDenied`, `usage:`). Tests assert on the category keyword,"
            " NOT on any specific reference-impl wording."
        )
        parts.append(
            "- exit: `1` (application error) or `252` / `255` (argument/usage error)."
            " Real aws-cli returns `252` for argparse-style usage errors and `255`"
            " for internal errors. Tests should assert `returncode != 0` rather than"
            " equality with any specific non-zero code."
        )
        parts.append("- Specific error cases:")
        for intent in by_tag["error"]:
            if _is_internal_mutation_intent(intent):
                continue
            shape = _argv_shape(intent.cmdline_template) or "<argv>"
            parts.append(f"  - `{shape}` → exit `{intent.expected_exit}`")
    else:
        parts.append("- No error cases specified for this slice.")
    parts.append("")

    # 3. Cross-command state expectations
    parts.append("### State expectations (cross-command observable)\n")
    if state_model:
        parts.append(state_model + "\n")
    else:
        parts.append(
            "_(no built-in state model for this command — follow the principle of\n"
            "least surprise: after a successful operation, its effects MUST be\n"
            "observable via the documented S3 read operations.)_\n"
        )

    # 4. Examples (derived from intent cmdlines, NOT from test code)
    examples = _render_examples(intents, cmd_label)
    if examples:
        parts.append("### Examples\n")
        parts.append("```bash")
        parts.extend(examples)
        parts.append("```\n")

    # 5. Implementation constraints
    parts.append(
        "## Implementation constraints\n\n"
        "- Use the S3 client library that is pre-installed in the environment;\n"
        "  do not add new package dependencies. Do NOT import `awscli` or shell\n"
        "  out to the real `aws` binary.\n"
        "- Read endpoint and credentials from environment variables provided\n"
        "  by the runtime; do not hard-code them.\n"
        "- Success messages go to **stdout**; errors go to **stderr**. Do not mix them.\n"
        "- Exit code: `0` on success, `1` on application error, `252` or `255` on\n"
        "  argument/usage errors. Real aws-cli returns `252` for argparse-style\n"
        "  usage errors and `255` for internal errors — either is acceptable.\n"
        "- Catch S3 errors and print a concise, user-facing error string\n"
        "  (do NOT print raw Python tracebacks).\n"
        "- Do NOT fabricate flags that don't exist upstream. For example,\n"
        "  `aws s3 mb` has NO `--tags` flag — do NOT implement one.\n"
        "- Do NOT validate bucket names client-side; the server rejects malformed\n"
        "  names with `InvalidBucketName`.\n"
        "- Implementation lives at `/workspace/submission/main.py` — a single file.\n"
    )

    # (No "## Reference" block emitted: pointing the agent at the source
    # tests is a reward-hacking vector — it can fetch the test file at the
    # pinned SHA and hard-code submission/main.py to satisfy assertions
    # without actually implementing the CLI. Provenance lives in task.toml
    # under [metadata.repo2env] for the trainer, NOT in instruction.md.)

    return "\n".join(parts) + "\n"


def _build_instruction_md_ddb(
    spec: CliSpec, cmd_spec: CommandSpec, intents: list[TestIntent]
) -> str:
    by_tag = _group_by_tag(intents)
    flags = _extract_flags_from_intents(intents)
    cmd_label = f"{spec.command_prefix} {cmd_spec.name}"
    state_model = _COMMAND_STATE_MODEL.get((spec.command_prefix, cmd_spec.name))

    parts: list[str] = []
    parts.append(f"# Build `aws {cmd_label}` CLI\n")
    parts.append(
        "## Application overview\n\n"
        f"You will implement the `aws {cmd_label}` subcommand of the AWS CLI's\n"
        "DynamoDB family.\n\n"
        "Your code is invoked as a subprocess:\n\n"
        "```bash\n"
        f"aws {cmd_label} [args...]\n"
        "```\n\n"
        "After any successful operation, its effect must be observable via the\n"
        "documented DynamoDB read operations. Treat the backend as real AWS\n"
        "DynamoDB and keep state consistent with the DynamoDB API contract.\n"
    )

    parts.append(f"## Command: `{cmd_label}`\n")

    parts.append("Argv shapes observed:\n")
    seen_shapes: set[str] = set()
    for intent in intents:
        if _is_internal_mutation_intent(intent):
            continue
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen_shapes:
            seen_shapes.add(shape)
            parts.append(f"- `{shape}`")
    parts.append("")

    if flags:
        parts.append("Flags: " + ", ".join(f"`{f}`" for f in sorted(flags)) + "\n")

    success_ops = sorted(
        {op for i in intents if i.expected_exit == 0 for op in i.expected_state_calls}
    )
    parts.append("Behavior:\n")
    parts.append(
        "- On success: the operation's DynamoDB JSON response document is written\n"
        "  to stdout (parseable with `json.loads`); stderr is empty; exit code is\n"
        "  `0`. Assertions are on JSON semantic content, never on key order,\n"
        "  whitespace, or any textual preamble."
    )
    if success_ops:
        bullets = ", ".join(f"`{op}`" for op in success_ops)
        ens = "; ".join(f"{op} = {_OP_TO_ENGLISH.get(op, op)}" for op in success_ops)
        parts.append(
            "- Observable side effects — the underlying DynamoDB operations invoked\n"
            f"  must include at least: {bullets}.\n"
            f"  (In plain English: {ens}.)"
        )
    if by_tag.get("error"):
        parts.append(
            "- On error: stdout is empty; stderr identifies the error CATEGORY —\n"
            "  one of `ResourceNotFoundException`, `ResourceInUseException`,\n"
            "  `ConditionalCheckFailedException`, `ValidationException`. Tests match\n"
            "  on the error-code keyword, never on verbatim wording. Exit is\n"
            "  non-zero; tests require `returncode != 0`, never equality with any\n"
            "  specific non-zero code."
        )
        parts.append("- Specific error cases:")
        shape_key_to_categories: dict[tuple[str, int], list[str]] = {}
        shape_key_order: list[tuple[str, int]] = []
        for intent in by_tag["error"]:
            if _is_internal_mutation_intent(intent):
                continue
            shape = _argv_shape(intent.cmdline_template) or "<argv>"
            key = (shape, intent.expected_exit)
            if key not in shape_key_to_categories:
                shape_key_to_categories[key] = []
                shape_key_order.append(key)
            if intent.error_category:
                shape_key_to_categories[key].append(intent.error_category)
        for shape, exit_code in shape_key_order:
            cats = shape_key_to_categories[(shape, exit_code)]
            if cats:
                unique_cats = sorted(set(cats))
                cat_txt = ", ".join(f"`{c}`" for c in unique_cats)
                parts.append(f"  - `{shape}` → any of: {cat_txt}")
            else:
                parts.append(f"  - `{shape}` → non-zero exit")
    parts.append("")

    if state_model:
        parts.append("## State expectations\n")
        parts.append(state_model + "\n")

    parts.append(
        "## Data model notes\n\n"
        '- Item and key values use DynamoDB AttributeValue form: `{"S": ...}` (string),\n'
        '  `{"N": "5"}` (number  -  **numbers are JSON strings**), `{"B": <base64>}`,\n'
        '  `{"BOOL": ...}`, `{"NULL": true}`, `{"M": ...}`, `{"L": ...}`,\n'
        '  `{"SS"|"NS"|"BS": ...}`.\n'
        "- Tables in this pilot use on-demand capacity (`PAY_PER_REQUEST`).\n"
    )

    examples = _render_examples(intents, cmd_label, invocation="aws")
    if examples:
        parts.append("## Examples\n")
        parts.append("```bash")
        parts.extend(examples)
        parts.append("```\n")

    parts.append(
        "## Implementation constraints\n\n"
        "- Your submission may be written in any language available in the image.\n"
        "  Use only what the image already provides; no additional packages may be\n"
        "  fetched.\n"
        "- Do not import `awscli` or shell out to the real `aws` binary.\n"
        "- AWS credentials and endpoint are set in the environment; do not override\n"
        "  the service address, region, or credentials in code.\n"
        "- Success output (JSON) goes to **stdout**; errors go to **stderr**. Do not\n"
        "  mix them.\n"
        "- Do not surface raw library tracebacks; print a brief user-facing error\n"
        "  string instead.\n"
        "- Do not fabricate flags that do not exist upstream. Do not validate table\n"
        "  names client-side; the service rejects malformed input with\n"
        "  `ValidationException`.\n"
        "- Your submission must be an executable named `aws` on `$PATH`. It may be\n"
        "  written in any language. The image provides `/workspace/submission/` first\n"
        "  on `$PATH` as a convenient writable install location, but any directory on\n"
        "  `$PATH` is acceptable. Helper files may live alongside it.\n"
    )

    parts.append(
        "## Output contract\n\n"
        "A correct implementation produces output in the *shape* described below,\n"
        "names the *class* of any error reported, uses the documented exit-code\n"
        "set, and never surfaces a runtime stack trace. Specific verbs and the\n"
        "exact wording of any message are deliberately not enumerated here: derive\n"
        "them from the underlying DynamoDB service semantics and standard\n"
        "`aws dynamodb` conventions.\n"
    )

    parts.append(
        "### stdout (success path)\n\n"
        "- A successful command writes the operation's DynamoDB JSON response\n"
        "  document to stdout (parseable with `json.loads`).\n"
        "- Assertions are on JSON semantic content, never on key order, whitespace,\n"
        "  or any textual preamble.\n"
        "- stderr is empty on success.\n"
    )

    parts.append(
        "### stderr (failure path)\n\n"
        "- stdout is empty on failure.\n"
        "- A human-readable error line is written to stderr that identifies the\n"
        "  failure *class*. Any of the following shapes is acceptable:\n"
        "  - the underlying AWS service error envelope:\n"
        "    `An error occurred (<ErrorCode>) when calling the <Operation> operation: <message>`\n"
        "  - a bare `<ErrorCode>: <message>` line naming the DynamoDB error code\n"
        "    (for example, `ResourceNotFoundException`, `ResourceInUseException`,\n"
        "    `ConditionalCheckFailedException`, `ValidationException`)\n"
        "  - a client-side usage-error line whose prefix names the failure class\n"
        "    (for example, `usage: ...`, `Parameter validation failed: ...`,\n"
        "    `Unknown options: ...`)\n"
        "- Tests match the failure *class* against one of these shapes — not\n"
        "  verbatim wording — so any spec-compliant phrasing is accepted.\n"
        "- No runtime stack trace is emitted under any condition.\n"
    )

    parts.append(
        "### Exit codes\n\n"
        "The exit code on termination is one of `{0, 1, 252, 254, 255}`:\n\n"
        "- `0` — success\n"
        "- `1` — application error (a DynamoDB operation was attempted and failed)\n"
        "- `252` — parameter/usage error (unknown flag, missing/extra argument,\n"
        "  malformed value)\n"
        "- `254` — service-modeled error (the service returned a modeled exception\n"
        "  such as `ResourceNotFoundException`)\n"
        "- `255` — other or general error\n\n"
        "Tests only check `returncode != 0` on failure; any non-zero code in this set\n"
        "is acceptable.\n"
    )
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Subset (multi-command) instruction.md
# ---------------------------------------------------------------------------


# Cross-command observable contracts, keyed by the command whose effect another
# command must observe. Used to render the "Cross-command behaviour" section so
# the agent knows state must stay consistent across subcommands.
_CROSS_COMMAND_INVARIANTS_BY_CMD: dict[str, str] = {
    "mb": "After `mb s3://bucket`, the bucket appears in `ls` (no path).",
    "rb": (
        "After `rb s3://bucket`, the bucket disappears from `ls`; `rb` on a "
        "non-empty bucket fails unless `--force` is given."
    ),
    "cp": (
        "After `cp <local> s3://bucket/key`, the object is listed by "
        "`ls s3://bucket/` and retrievable; `cp s3://bucket/key <local2>` yields "
        "bytes identical to the original (round-trip identity)."
    ),
    "mv": (
        "After `mv A B`, the source no longer exists and the destination does "
        "(mv behaves like a copy followed by removal of the source)."
    ),
    "rm": "After `rm s3://bucket/key`, the object is no longer listed or retrievable.",
    "ls": "`ls` reflects exactly the cumulative effect of the prior commands at every step.",
    "sync": (
        "A second `sync` over an unchanged source/destination transfers nothing "
        "(idempotent); the destination set is a superset of the source."
    ),
}


def _cross_command_invariants(prefix: str, names: list[str]) -> str:
    """Render the cross-command behaviour bullets for a subset."""
    bullets: list[str] = []
    for n in names:
        inv = _CROSS_COMMAND_INVARIANTS_BY_CMD.get(n)
        if inv:
            bullets.append(f"- {inv}")
    if {"cp", "rb"} <= set(names) or {"sync", "rb"} <= set(names):
        bullets.append(
            "- A bucket populated by `cp`/`sync` cannot be removed by a plain `rb` "
            "until its objects are removed (e.g. via `rm`)."
        )
    if not bullets:
        bullets.append(
            "- After any successful operation, its effect MUST be observable via the "
            "documented read operations of the other commands."
        )
    return "\n".join(bullets) + "\n"


_INTERNAL_MUTATION_KINDS: frozenset[str] = frozenset(
    {"unknown_flag", "empty_value", "malformed_json", "duplicate_flag", "too_long_value"}
)


def _is_internal_mutation_intent(intent: TestIntent) -> bool:
    tn = intent.test_name or ""
    if not tn.startswith("model_"):
        return False
    for k in _INTERNAL_MUTATION_KINDS:
        if tn.endswith("_" + k):
            return True
    return "_missing_" in tn


def _command_section_parts(
    spec: CliSpec, cmd_spec: CommandSpec, intents: list[TestIntent]
) -> list[str]:
    """Compact per-command spec section for a subset instruction.md."""
    prefix = spec.command_prefix
    cmd_label = f"{prefix} {cmd_spec.name}"
    parts: list[str] = [f"### Command: `{cmd_label}`\n"]

    shapes: list[str] = []
    seen: set[str] = set()
    for intent in intents:
        if _is_internal_mutation_intent(intent):
            continue
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen:
            seen.add(shape)
            shapes.append(f"- `{shape}`")
    if shapes:
        parts.append("Observed argv patterns:\n")
        parts.extend(shapes)
        parts.append("")

    non_mutation_intents = [i for i in intents if not _is_internal_mutation_intent(i)]
    observed_flags = set(_extract_flags_from_intents(non_mutation_intents))
    documented_flags = set(cmd_spec.flags or [])
    if documented_flags:
        parts.append(
            "Documented flags: " + ", ".join(f"`{f}`" for f in sorted(documented_flags)) + "\n"
        )
    flags_union = observed_flags | documented_flags
    if flags_union:
        parts.append("Flags observed: " + ", ".join(f"`{f}`" for f in sorted(flags_union)) + "\n")

    state_model = _COMMAND_STATE_MODEL.get((prefix, cmd_spec.name))
    if state_model:
        parts.append("Behaviour & state expectations:\n")
        parts.append(state_model + "\n")

    by_tag = _group_by_tag(intents)
    error_intents: list[TestIntent] = []
    for tag in ("error", "error_nonexistent", "error_invalid_args"):
        error_intents.extend(by_tag.get(tag, []))
    if error_intents:
        parts.append("Error cases:")
        seen_errors: set[tuple[str, int]] = set()
        for intent in error_intents:
            shape = _argv_shape(intent.cmdline_template) or "<argv>"
            key = (shape, intent.expected_exit)
            if key in seen_errors:
                continue
            seen_errors.add(key)
            parts.append(f"- `{shape}` -> exit `{intent.expected_exit}`")
        parts.append("")
    return parts


def _build_subset_instruction_md(
    spec: CliSpec,
    cmd_specs: list[CommandSpec],
    intents: list[TestIntent],
    *,
    backend: str = "minio",
) -> str:
    """Agent-facing instruction.md for a multi-command subset task.

    Overview + one section per subcommand (interface + I/O + state) + a
    cross-command behaviour section. Built ONLY from CliSpec + intents + the
    hand-authored _COMMAND_STATE_MODEL — never from test code. `_assert_no_test_leakage`
    is the safety net. backend="dynamodb_local" renders the DynamoDB variant.
    """
    if backend == "dynamodb_local":
        return _build_subset_instruction_md_ddb(spec, cmd_specs, intents)
    if backend == "kwok":
        return _build_subset_instruction_md_kwok(spec, cmd_specs, intents)
    prefix = spec.command_prefix
    names = sorted(c.name for c in cmd_specs)
    label_list = ", ".join(f"`{prefix} {n}`" for n in names)
    parts: list[str] = []

    parts.append(f"# Build an `aws {prefix}` CLI (subset: {', '.join(names)})\n")
    parts.append(
        "## Application overview\n\n"
        f"You are implementing a subset of the AWS CLI's `{prefix}` command family:\n"
        f"{label_list}. The agent is given **no source code**, only this specification.\n"
        "Your implementation is a single file, invoked as a subprocess:\n\n"
        "```bash\n"
        f"python /workspace/submission/main.py {prefix} <command> [args...]\n"
        "```\n\n"
        "Dispatch on the `<command>` token so one program handles every subcommand\n"
        "above. The harness configures the runtime so that the S3 client reaches\n"
        "a sandboxed, isolated S3-compatible service. Read endpoint and\n"
        "credentials from the environment; do not hard-code them. Treat the\n"
        "backend as real AWS S3, and keep state consistent across commands so\n"
        "a sequence like upload, list, download, remove behaves correctly\n"
        "end-to-end.\n"
    )

    parts.append("## Commands\n")
    by_cmd: dict[str, list[TestIntent]] = {}
    for i in intents:
        by_cmd.setdefault(i.command, []).append(i)
    for c in sorted(cmd_specs, key=lambda c: c.name):
        parts.extend(_command_section_parts(spec, c, by_cmd.get(c.name, [])))

    parts.append("## Cross-command behaviour (state must stay consistent)\n")
    parts.append(_cross_command_invariants(prefix, names))

    parts.append(
        "## Implementation constraints\n\n"
        "- Use the S3 client library that is pre-installed in the environment;\n"
        "  do not add new package dependencies. Do NOT import `awscli` or shell\n"
        "  out to the real `aws` binary.\n"
        "- Read endpoint and credentials from environment variables provided\n"
        "  by the runtime; do not hard-code them.\n"
        "- Success messages go to **stdout**; errors go to **stderr**. Do not mix them.\n"
        "- Exit code: `0` on success, `1` on application error, `252` or `255` on\n"
        "  argument/usage errors. Real aws-cli returns `252` for argparse-style\n"
        "  usage errors and `255` for internal errors — either is acceptable.\n"
        "- Catch S3 errors and print a concise, user-facing error string\n"
        "  (do NOT print raw Python tracebacks).\n"
        "- Do NOT fabricate flags that don't exist upstream. For example,\n"
        "  `aws s3 mb` has NO `--tags` flag — do NOT implement one for any subcommand.\n"
        "- Do NOT validate bucket names client-side; the server rejects malformed\n"
        "  names with `InvalidBucketName`.\n"
        "- Everything lives in `/workspace/submission/main.py` — a single file that\n"
        "  dispatches on the subcommand.\n"
    )
    return "\n".join(parts) + "\n"


_CROSS_COMMAND_INVARIANTS_BY_CMD_DDB: dict[str, str] = {
    "create-table": "After `create-table`, the table appears in `list-tables`.",
    "delete-table": "After `delete-table`, the table disappears from `list-tables`.",
    "put-item": "After `put-item`, `get-item` on the same key returns the written item.",
    "get-item": "`get-item` reflects exactly the cumulative effect of prior writes/updates.",
    "update-item": "After `update-item`, `get-item` reflects the mutated attributes.",
    "delete-item": "After `delete-item`, `get-item` on the key returns no `Item`.",
    "query": "`query` returns exactly the items previously written under the partition key.",
}


def _cross_command_invariants_ddb(names: list[str]) -> str:
    bullets: list[str] = []
    for n in names:
        inv = _CROSS_COMMAND_INVARIANTS_BY_CMD_DDB.get(n)
        if inv:
            bullets.append(f"- {inv}")
    if {"put-item", "get-item"} <= set(names) or {"get-item", "delete-item"} <= set(names):
        bullets.append(
            "- Reads are strongly consistent: a write's effect is visible to the very "
            "next read of the same key."
        )
    if not bullets:
        bullets.append(
            "- After any successful operation, its effect MUST be observable via the "
            "documented read operations of the other commands."
        )
    return "\n".join(bullets) + "\n"


def _build_subset_instruction_md_ddb(
    spec: CliSpec, cmd_specs: list[CommandSpec], intents: list[TestIntent]
) -> str:
    prefix = spec.command_prefix
    names = sorted(c.name for c in cmd_specs)
    label_list = ", ".join(f"`{prefix} {n}`" for n in names)
    parts: list[str] = []

    parts.append(f"# Build an `aws {prefix}` CLI\n")
    parts.append(
        "## Application overview\n\n"
        f"You will implement the following `aws {prefix}` commands:\n"
        f"{label_list}.\n\n"
        "Your code is invoked as a subprocess:\n\n"
        "```bash\n"
        f"aws {prefix} <command> [args...]\n"
        "```\n\n"
        "Dispatch on the `<command>` token so one program handles every subcommand\n"
        "above. State must remain consistent across commands so a sequence such as\n"
        "create-table, put-item, get-item, query behaves correctly end-to-end.\n"
    )

    parts.append("## Commands\n")
    by_cmd: dict[str, list[TestIntent]] = {}
    for i in intents:
        by_cmd.setdefault(i.command, []).append(i)
    for c in sorted(cmd_specs, key=lambda c: c.name):
        parts.extend(_command_section_parts(spec, c, by_cmd.get(c.name, [])))

    parts.append("## Cross-command behavior\n")
    parts.append("State must remain consistent across the command set:\n")
    parts.append(_cross_command_invariants_ddb(names))

    parts.append(
        "## Data model notes\n\n"
        "- Item and key values use DynamoDB AttributeValue form; **numbers are JSON\n"
        '  strings** (`{"N": "5"}`).\n'
        "- Tables use on-demand capacity (`PAY_PER_REQUEST`).\n"
    )

    parts.append(
        "## Implementation constraints\n\n"
        "- Your submission may be written in any language available in the image.\n"
        "  Use only what the image already provides; no additional packages may be\n"
        "  fetched.\n"
        "- Do not import `awscli` or shell out to the real `aws` binary.\n"
        "- AWS credentials and endpoint are set in the environment; do not override\n"
        "  the service address, region, or credentials in code.\n"
        "- Success output (JSON) goes to **stdout**; errors go to **stderr**. Do not\n"
        "  mix them.\n"
        "- Do not surface raw library tracebacks; print a brief user-facing error\n"
        "  string instead.\n"
        "- Do not fabricate flags that do not exist upstream. Do not validate table\n"
        "  names client-side; the service rejects malformed input with\n"
        "  `ValidationException`.\n"
        "- Your submission must be an executable named `aws` on `$PATH`. It may be\n"
        "  written in any language. The image provides `/workspace/submission/` first\n"
        "  on `$PATH` as a convenient writable install location, but any directory on\n"
        "  `$PATH` is acceptable. Helper files may live alongside it.\n"
    )

    parts.append(
        "## Output contract\n\n"
        "A correct implementation produces output in the *shape* described below,\n"
        "names the *class* of any error reported, uses the documented exit-code\n"
        "set, and never surfaces a runtime stack trace. Specific verbs and the\n"
        "exact wording of any message are deliberately not enumerated here: derive\n"
        "them from the underlying DynamoDB service semantics and standard\n"
        f"`aws {prefix}` conventions.\n"
    )

    parts.append(
        "### stdout (success path)\n\n"
        "- A successful command writes the operation's DynamoDB JSON response\n"
        "  document to stdout (parseable with `json.loads`).\n"
        "- Assertions are on JSON semantic content, never on key order, whitespace,\n"
        "  or any textual preamble.\n"
        "- stderr is empty on success.\n"
    )

    parts.append(
        "### stderr (failure path)\n\n"
        "- stdout is empty on failure.\n"
        "- A human-readable error line is written to stderr that identifies the\n"
        "  failure *class*. Any of the following shapes is acceptable:\n"
        "  - the underlying AWS service error envelope:\n"
        "    `An error occurred (<ErrorCode>) when calling the <Operation> operation: <message>`\n"
        "  - a bare `<ErrorCode>: <message>` line naming the DynamoDB error code\n"
        "    (for example, `ResourceNotFoundException`, `ResourceInUseException`,\n"
        "    `ConditionalCheckFailedException`, `ValidationException`)\n"
        "  - a client-side usage-error line whose prefix names the failure class\n"
        "    (for example, `usage: ...`, `Parameter validation failed: ...`,\n"
        "    `Unknown options: ...`)\n"
        "- Tests match the failure *class* against one of these shapes — not\n"
        "  verbatim wording — so any spec-compliant phrasing is accepted.\n"
        "- No runtime stack trace is emitted under any condition.\n"
    )

    parts.append(
        "### Exit codes\n\n"
        "The exit code on termination is one of `{0, 1, 252, 254, 255}`:\n\n"
        "- `0` — success\n"
        "- `1` — application error (a DynamoDB operation was attempted and failed)\n"
        "- `252` — parameter/usage error (unknown flag, missing/extra argument,\n"
        "  malformed value)\n"
        "- `254` — service-modeled error (the service returned a modeled exception\n"
        "  such as `ResourceNotFoundException`)\n"
        "- `255` — other or general error\n\n"
        "Tests only check `returncode != 0` on failure; any non-zero code in this set\n"
        "is acceptable.\n"
    )
    return "\n".join(parts) + "\n"


def _build_instruction_md_generic(
    spec: CliSpec,
    cmd_spec: CommandSpec,
    intents: list[TestIntent],
    *,
    sidecar: SidecarSpec,
) -> str:
    """Model-backend (sidecar) instruction.md, generalised by SidecarSpec.

    Mirrors the leakage-clean shape of ``_build_instruction_md_ddb`` (JSON stdout,
    error categories, exit-code set, aws-on-PATH) but parameterised by
    ``sidecar.service``. Wire/endpoint detail (X-Amz-Target, JSON version, the
    sidecar endpoint) is deliberately kept OUT of instruction.md and lives only in
    the prompt set, so ``_assert_no_test_leakage`` stays satisfied for any service.
    """
    service = sidecar.service
    by_tag = _group_by_tag(intents)
    flags = _extract_flags_from_intents(intents)
    cmd_label = f"{spec.command_prefix} {cmd_spec.name}"
    state_model = _COMMAND_STATE_MODEL.get((spec.command_prefix, cmd_spec.name))

    parts: list[str] = []
    parts.append(f"# Build `aws {cmd_label}` CLI\n")
    parts.append(
        "## Application overview\n\n"
        f"You will implement the `aws {cmd_label}` subcommand of the AWS CLI's\n"
        f"{service} family.\n\n"
        "Your code is invoked as a subprocess:\n\n"
        "```bash\n"
        f"aws {cmd_label} [args...]\n"
        "```\n\n"
        "After any successful operation, its effect must be observable via the\n"
        f"documented {service} read operations. Treat the backend as real AWS\n"
        f"{service} and keep state consistent with the {service} API contract.\n"
    )

    parts.append(f"## Command: `{cmd_label}`\n")

    parts.append("Argv shapes observed:\n")
    seen_shapes: set[str] = set()
    for intent in intents:
        if _is_internal_mutation_intent(intent):
            continue
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen_shapes:
            seen_shapes.add(shape)
            parts.append(f"- `{shape}`")
    parts.append("")

    if flags:
        parts.append("Flags: " + ", ".join(f"`{f}`" for f in sorted(flags)) + "\n")

    success_ops = sorted(
        {op for i in intents if i.expected_exit == 0 for op in i.expected_state_calls}
    )
    parts.append("Behavior:\n")
    parts.append(
        "- On success: the operation's JSON response document is written to stdout\n"
        "  (parseable with `json.loads`); stderr is empty; exit code is `0`.\n"
        "  Assertions are on JSON semantic content, never on key order, whitespace,\n"
        "  or any textual preamble."
    )
    if success_ops:
        bullets = ", ".join(f"`{op}`" for op in success_ops)
        parts.append(
            f"- Observable side effects — the underlying {service} operations invoked\n"
            f"  must include at least: {bullets}."
        )
    if by_tag.get("error"):
        parts.append(
            "- On error: stdout is empty; stderr identifies the error CATEGORY (the\n"
            "  service's exception name, e.g. a `...Exception` / `...NotFound` /\n"
            "  `...InUse` class). Tests match on the error-code keyword, never on\n"
            "  verbatim wording. Exit is non-zero; tests require `returncode != 0`,\n"
            "  never equality with any specific non-zero code."
        )
        parts.append("- Specific error cases:")
        shape_key_to_categories: dict[tuple[str, int], list[str]] = {}
        shape_key_order: list[tuple[str, int]] = []
        for intent in by_tag["error"]:
            if _is_internal_mutation_intent(intent):
                continue
            shape = _argv_shape(intent.cmdline_template) or "<argv>"
            key = (shape, intent.expected_exit)
            if key not in shape_key_to_categories:
                shape_key_to_categories[key] = []
                shape_key_order.append(key)
            if intent.error_category:
                shape_key_to_categories[key].append(intent.error_category)
        for shape, exit_code in shape_key_order:
            cats = shape_key_to_categories[(shape, exit_code)]
            if cats:
                unique_cats = sorted(set(cats))
                cat_txt = ", ".join(f"`{c}`" for c in unique_cats)
                parts.append(f"  - `{shape}` → any of: {cat_txt}")
            else:
                parts.append(f"  - `{shape}` → non-zero exit")
    parts.append("")

    if state_model:
        parts.append("## State expectations\n")
        parts.append(state_model + "\n")

    examples = _render_examples(intents, cmd_label, invocation="aws")
    if examples:
        parts.append("## Examples\n")
        parts.append("```bash")
        parts.extend(examples)
        parts.append("```\n")

    parts.append(
        "## Implementation constraints\n\n"
        "- Your submission may be written in any language available in the image.\n"
        "  Use only what the image already provides; no additional packages may be\n"
        "  fetched.\n"
        "- Do not import `awscli` or shell out to the real `aws` binary.\n"
        "- AWS credentials and endpoint are set in the environment; do not override\n"
        "  the service address, region, or credentials in code.\n"
        "- Success output (JSON) goes to **stdout**; errors go to **stderr**. Do not\n"
        "  mix them.\n"
        "- Do not surface raw library tracebacks; print a brief user-facing error\n"
        "  string instead.\n"
        "- Do not fabricate flags that do not exist upstream. Do not validate input\n"
        "  client-side; the service rejects malformed input with a validation error.\n"
        "- Your submission must be an executable named `aws` on `$PATH`. It may be\n"
        "  written in any language. The image provides `/workspace/submission/` first\n"
        "  on `$PATH` as a convenient writable install location, but any directory on\n"
        "  `$PATH` is acceptable. Helper files may live alongside it.\n"
    )

    parts.append(
        "## Output contract\n\n"
        "A correct implementation produces output in the *shape* described below,\n"
        "names the *class* of any error reported, uses the documented exit-code\n"
        "set, and never surfaces a runtime stack trace. Specific verbs and the\n"
        "exact wording of any message are deliberately not enumerated here: derive\n"
        f"them from the underlying {service} service semantics and standard\n"
        f"`aws {spec.command_prefix}` conventions.\n"
    )

    parts.append(
        "### stdout (success path)\n\n"
        "- A successful command writes the operation's JSON response document to\n"
        "  stdout (parseable with `json.loads`).\n"
        "- Assertions are on JSON semantic content, never on key order, whitespace,\n"
        "  or any textual preamble.\n"
        "- stderr is empty on success.\n"
    )

    parts.append(
        "### stderr (failure path)\n\n"
        "- stdout is empty on failure.\n"
        "- A human-readable error line is written to stderr that identifies the\n"
        "  failure *class*. Any of the following shapes is acceptable:\n"
        "  - the underlying AWS service error envelope:\n"
        "    `An error occurred (<ErrorCode>) when calling the <Operation> operation: <message>`\n"
        "  - a bare `<ErrorCode>: <message>` line naming the service error code\n"
        "  - a client-side usage-error line whose prefix names the failure class\n"
        "    (for example, `usage: ...`, `Parameter validation failed: ...`,\n"
        "    `Unknown options: ...`)\n"
        "- Tests match the failure *class* against one of these shapes — not\n"
        "  verbatim wording — so any spec-compliant phrasing is accepted.\n"
        "- No runtime stack trace is emitted under any condition.\n"
    )

    parts.append(
        "### Exit codes\n\n"
        "The exit code on termination is one of `{0, 1, 252, 254, 255}`:\n\n"
        "- `0` — success\n"
        "- `1` — application error (an operation was attempted and failed)\n"
        "- `252` — parameter/usage error (unknown flag, missing/extra argument,\n"
        "  malformed value)\n"
        "- `254` — service-modeled error (the service returned a modeled exception)\n"
        "- `255` — other or general error\n\n"
        "Tests only check `returncode != 0` on failure; any non-zero code in this set\n"
        "is acceptable.\n"
    )
    return "\n".join(parts) + "\n"


def _build_subset_instruction_md_generic(
    spec: CliSpec,
    cmd_specs: list[CommandSpec],
    intents: list[TestIntent],
    *,
    sidecar: SidecarSpec,
) -> str:
    service = sidecar.service
    prefix = spec.command_prefix
    names = sorted(c.name for c in cmd_specs)
    label_list = ", ".join(f"`{prefix} {n}`" for n in names)
    parts: list[str] = []

    parts.append(f"# Build an `aws {prefix}` CLI\n")
    parts.append(
        "## Application overview\n\n"
        f"You will implement the following `aws {prefix}` commands:\n"
        f"{label_list}.\n\n"
        "Your code is invoked as a subprocess:\n\n"
        "```bash\n"
        f"aws {prefix} <command> [args...]\n"
        "```\n\n"
        "Dispatch on the `<command>` token so one program handles every subcommand\n"
        f"above. State must remain consistent across commands so a sequence of\n"
        f"{service} operations behaves correctly end-to-end.\n"
    )

    parts.append("## Commands\n")
    by_cmd: dict[str, list[TestIntent]] = {}
    for i in intents:
        by_cmd.setdefault(i.command, []).append(i)
    for c in sorted(cmd_specs, key=lambda c: c.name):
        parts.extend(_command_section_parts(spec, c, by_cmd.get(c.name, [])))

    parts.append("## Cross-command behavior\n")
    parts.append("State must remain consistent across the command set:\n")
    parts.append(
        "- After any successful operation, its effect MUST be observable via the\n"
        "  documented read operations of the other commands.\n"
    )

    parts.append(
        "## Implementation constraints\n\n"
        "- Your submission may be written in any language available in the image.\n"
        "  Use only what the image already provides; no additional packages may be\n"
        "  fetched.\n"
        "- Do not import `awscli` or shell out to the real `aws` binary.\n"
        "- AWS credentials and endpoint are set in the environment; do not override\n"
        "  the service address, region, or credentials in code.\n"
        "- Success output (JSON) goes to **stdout**; errors go to **stderr**. Do not\n"
        "  mix them.\n"
        "- Do not surface raw library tracebacks; print a brief user-facing error\n"
        "  string instead.\n"
        "- Do not fabricate flags that do not exist upstream. Do not validate input\n"
        "  client-side; the service rejects malformed input with a validation error.\n"
        "- Your submission must be an executable named `aws` on `$PATH`. It may be\n"
        "  written in any language. The image provides `/workspace/submission/` first\n"
        "  on `$PATH` as a convenient writable install location, but any directory on\n"
        "  `$PATH` is acceptable. Helper files may live alongside it.\n"
    )

    parts.append(
        "## Output contract\n\n"
        "A correct implementation produces output in the *shape* described below,\n"
        "names the *class* of any error reported, uses the documented exit-code\n"
        "set, and never surfaces a runtime stack trace. Specific verbs and the\n"
        "exact wording of any message are deliberately not enumerated here: derive\n"
        f"them from the underlying {service} service semantics and standard\n"
        f"`aws {prefix}` conventions.\n"
    )
    parts.append(
        "### stdout (success path)\n\n"
        "- A successful command writes the operation's JSON response document to\n"
        "  stdout (parseable with `json.loads`).\n"
        "- Assertions are on JSON semantic content, never on key order, whitespace,\n"
        "  or any textual preamble.\n"
        "- stderr is empty on success.\n"
    )
    parts.append(
        "### stderr (failure path)\n\n"
        "- stdout is empty on failure.\n"
        "- A human-readable error line is written to stderr that identifies the\n"
        "  failure *class*. Any of the following shapes is acceptable:\n"
        "  - the underlying AWS service error envelope:\n"
        "    `An error occurred (<ErrorCode>) when calling the <Operation> operation: <message>`\n"
        "  - a bare `<ErrorCode>: <message>` line naming the service error code\n"
        "  - a client-side usage-error line whose prefix names the failure class\n"
        "    (for example, `usage: ...`, `Parameter validation failed: ...`,\n"
        "    `Unknown options: ...`)\n"
        "- Tests match the failure *class* against one of these shapes — not\n"
        "  verbatim wording — so any spec-compliant phrasing is accepted.\n"
        "- No runtime stack trace is emitted under any condition.\n"
    )
    parts.append(
        "### Exit codes\n\n"
        "The exit code on termination is one of `{0, 1, 252, 254, 255}`:\n\n"
        "- `0` — success\n"
        "- `1` — application error (an operation was attempted and failed)\n"
        "- `252` — parameter/usage error (unknown flag, missing/extra argument,\n"
        "  malformed value)\n"
        "- `254` — service-modeled error (the service returned a modeled exception)\n"
        "- `255` — other or general error\n\n"
        "Tests only check `returncode != 0` on failure; any non-zero code in this set\n"
        "is acceptable.\n"
    )
    return "\n".join(parts) + "\n"


def _group_by_tag(intents: list[TestIntent]) -> dict[str, list[TestIntent]]:
    out: dict[str, list[TestIntent]] = {}
    for i in intents:
        out.setdefault(i.behaviour_tag, []).append(i)
    return out


def _extract_flags_from_intents(intents: list[TestIntent]) -> dict[str, str | None]:
    """Discover `--flag value` pairs in observed cmdlines. Returns flag -> example."""
    flags: dict[str, str | None] = {}
    for intent in intents:
        toks = intent.cmdline_template
        for i, tok in enumerate(toks):
            if tok.startswith("--") and len(tok) > 2:
                # Strip any `=value` form for the key
                key = tok.split("=", 1)[0]
                if "=" in tok:
                    flags.setdefault(key, tok.split("=", 1)[1])
                    continue
                # Look ahead for a non-flag value
                nxt = toks[i + 1] if i + 1 < len(toks) else ""
                if nxt and not nxt.startswith("--") and not nxt.startswith("<arg>"):
                    flags.setdefault(key, nxt)
                else:
                    flags.setdefault(key, None)
    return flags


def _argv_shape(tokens: list[str]) -> str:
    """Human-readable argv shape with positional placeholders abstracted.

    Examples:
        ['s3', 'cp', '<arg>', 's3://bucket/key'] -> 's3 cp <local-path> s3://bucket/key'
        ['s3', 'mb', 's3://bucket', '--region', 'us-west-2']
            -> 's3 mb s3://bucket --region us-west-2'
    """
    # Display cap: too_long_value intents emit e.g. `"x" * 512` payloads that
    # dump as an unreadable wall of characters into instruction.md. Only the
    # rendered *shape* is truncated; the raw token is preserved in the intent
    # for the test invocation.
    out: list[str] = []
    for tok in tokens:
        if tok == "<arg>":
            # Best-effort label based on neighbours: a bare <arg> in the
            # middle of s3 cp/mv/sync is almost always a local path.
            out.append("<local-path>")
        elif len(tok) > 40:
            out.append(f"<oversized-value:{len(tok)}-chars>")
        else:
            out.append(tok)
    return " ".join(out)


def _humanise_test_name(name: str) -> str:
    """Turn `test_nonzero_exit_if_invalid_path_provided` into a short phrase."""
    s = name[len("test_") :] if name.startswith("test_") else name
    return s.replace("_", " ")


def _render_examples(
    intents: list[TestIntent],
    cmd_label: str,
    *,
    invocation: str = "python /workspace/submission/main.py",
) -> list[str]:
    """Render up to 4 representative invocations as bash one-liners.

    Pulls from intent.cmdline_template (NOT from test body). Diversity-first:
    one happy_path, one error, one workflow, one edge — caps total at 4.
    `invocation` is the command prefix; defaults to the MinIO/S3 python entry.
    """
    chosen: list[TestIntent] = []
    seen_shapes: set[str] = set()
    priority = [
        "happy_path",
        "error_nonexistent",
        "error_invalid_args",
        "error",
        "workflow",
        "edge",
    ]
    by_tag = _group_by_tag(intents)
    for tag in priority:
        for intent in by_tag.get(tag, []):
            if _is_internal_mutation_intent(intent):
                continue
            shape = _argv_shape(intent.cmdline_template)
            if shape and shape not in seen_shapes:
                seen_shapes.add(shape)
                chosen.append(intent)
                break
        if len(chosen) >= 4:
            break
    if not chosen:
        return []
    lines: list[str] = []
    for intent in chosen:
        argv = _argv_shape(intent.cmdline_template)
        # Neutral label — do NOT humanise test_name (it would leak the source
        # test slug, e.g. `nonzero exit if invalid path provided`).
        comment = f"# exit {intent.expected_exit}"
        lines.append(comment)
        lines.append(f"{invocation} {argv}")
        lines.append("")
    return lines


def _assert_no_test_leakage(instruction_md: str, test_files: dict[str, str]) -> None:
    """Static check: no test-code OR test-infrastructure leakage into instruction.md.

    The agent must believe it is implementing against real S3. Mentions of
    `moto`, `mock_aws`, `pytest`, etc. would let the agent (1) reason about
    backend limitations, (2) try to bypass tests by probing for mock state.
    """
    code_suspects = ("def test_", "assert ", "@mock_aws", "@pytest.fixture", "subprocess.run")
    for s in code_suspects:
        if s in instruction_md:
            raise RuntimeError(f"test-code leakage into instruction.md: {s!r}")
        # Test-infrastructure leakage — case-insensitive token check.
        infra_suspects = (
            "moto",
            "mock_aws",
            "minio",
            "pytest",
            "conftest",
            "ThreadedMotoServer",
            # DynamoDB-backend mock tokens — must never leak the local engine:
            "dynamodb-local",
            "dynamodblocal",
            "dynamodb local",
            "dynamodb_local",
            "_ddb_http",
            "-inmemory",
            "x-amz-target",
            "sqlite4java",
            "AWS_ENDPOINT_URL",
            "AWS_ENDPOINT",
            "endpoint_url",
            # Reward-hacking surface — must NEVER point agent at source tests:
            "github.com",
            "tests/functional",
            "_command.py",
            "git ref",
            "git_sha",
            "reference url",
            "behaviour drawn from",
        )
    lower = instruction_md.lower()
    for s in infra_suspects:
        if s.lower() in lower:
            raise RuntimeError(f"test-infrastructure leakage into instruction.md: {s!r}")
    # Git SHA fingerprint: 12-40 char lowercase hex. Catches future templates
    # that quote a commit ref without using one of the labelled phrases above.
    import re as _re

    if _re.search(r"\b[0-9a-f]{12,40}\b", instruction_md):
        raise RuntimeError("test-infrastructure leakage: git-SHA-shaped token in instruction.md")


# ---------------------------------------------------------------------------
# Hashing + helpers
# ---------------------------------------------------------------------------


def _compute_content_hash(
    *,
    spec: CliSpec,
    instruction: str,
    oracle_diff: str,
    aux_files: dict[str, str],
    prompt_version: str,
    translation_model: str,
    oracle_model: str,
    reference_diff: str | None = None,
) -> str:
    """Content hash covering EVERYTHING that affects task semantics.

    Overrides harbor.py's default (which only hashes instruction +
    oracle_diff). For cli_app mode, aux_files are the test bank, so they
    must be part of the hash.
    """
    h = hashlib.sha256()

    def _h(label: str, value: str) -> None:
        h.update(label.encode())
        h.update(b"\0")
        h.update(value.encode())
        h.update(b"\0")

    _h("spec_sha256", spec.spec_sha256)
    _h("prompt_version", prompt_version)
    _h("translation_model", translation_model)
    _h("oracle_model", oracle_model)
    _h("instruction", instruction)
    _h("oracle_diff", oracle_diff)
    if reference_diff is not None:
        _h("reference_diff", reference_diff)
    for path in sorted(aux_files):
        _h(f"aux:{path}", aux_files[path])
    return f"sha256:{h.hexdigest()}"


_FENCE_LINE_RE = re.compile(r"^\s*```[a-zA-Z0-9_+.-]*\s*$")


def _strip_trailing_bare_names(code: str) -> str:
    """Drop trailing module-level bare-Name/Attribute expressions (LLM stop-sentinel leaks
    like `endTurn`, `endTool`). ast.parse() accepts them as valid syntax so compile() will
    not catch them, but they NameError at pytest collect time and cascade-fail the whole
    reference_grounding batch (one poisoned file → 0 tests collected). Loops so the
    stripper handles multiple trailing sentinels."""
    while True:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code
        if not tree.body:
            return code
        tail = tree.body[-1]
        if not isinstance(tail, ast.Expr):
            return code
        val = tail.value
        if not isinstance(val, ast.Name | ast.Attribute):
            return code
        end_lineno = getattr(tail, "end_lineno", tail.lineno) or tail.lineno
        lines = code.splitlines()
        del lines[tail.lineno - 1 : end_lineno]
        code = "\n".join(lines).rstrip() + "\n"


def _strip_code_fence(text: str) -> str:
    """Extract Python from an LLM response; handles raw, single-fenced, and multi-block responses."""
    s = text.strip()
    lines = s.splitlines()
    fence_indices = [i for i, ln in enumerate(lines) if _FENCE_LINE_RE.match(ln)]
    if not fence_indices:
        return _strip_trailing_bare_names(s + "\n")
    extracted: list[str] = []
    in_block = False
    for ln in lines:
        if _FENCE_LINE_RE.match(ln):
            in_block = not in_block
            continue
        if in_block:
            extracted.append(ln)
    if not extracted:
        extracted = [ln for ln in lines if not _FENCE_LINE_RE.match(ln)]
    return _strip_trailing_bare_names("\n".join(extracted).strip() + "\n")


def _translation_model_id(pipeline: CodeInstructPipeline, options: CodeInstructOptions) -> str:
    if options.cli_app_translation_model:
        return options.cli_app_translation_model
    return pipeline._llm.qualified_name


def _resolve_git_sha(clone_dir: Path) -> str:
    """Capture the resolved git SHA after shallow clone (for provenance)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Docker gauntlet G3 (empty stub) + G4 (oracle) — opt-in verification
#
# G3: build the image, run tests with the empty stub baked into the Dockerfile.
#     Tests that pass against the empty stub are non-discriminative — discard
#     the whole task (reward signal would be noise during RL training).
# G4: same image, mount the oracle as /workspace/submission/main.py, run tests.
#     If the oracle can't satisfy its own tests, the LLM's intent translation
#     and/or oracle synthesis is broken — discard.
#
# Image build is cached by sha256(dockerfile_content) so all per_intent tasks
# for the same command reuse one build.
# ---------------------------------------------------------------------------

_DOCKER_IMAGE_CACHE: dict[str, str] = {}
_TEST_SH_SUMMARY_RE = re.compile(r"passed=(\d+)\s+failed=(\d+)\s+errors=(\d+)\s+reward=([\d.]+)")
_TEST_SH_V2_REWARD_RE = re.compile(r"reward=([\d.]+)\s+parser=v2")
_PYTEST_TOTALS_RE = re.compile(
    r"=+\s*(?:(\d+)\s+passed)?"
    r"(?:[^\n=]*?(\d+)\s+failed)?"
    r"(?:[^\n=]*?(\d+)\s+error)?"
    r"[^\n]*?in\s+[\d.]+s"
)


def _summarise_behaviours_from_intents(intents: list[TestIntent]) -> list[str]:
    """Render one human-readable bullet per intent for the ORACLE prompt.

    Format: `<cmdline>` should succeed/error (exit N) and call: Op1, Op2.
    The oracle LLM uses this to know exactly which behaviours to satisfy.
    Test code is NEVER included — only the structured intent (argv, exit, ops).
    Safe to leak into oracle prompt because oracle is the answer key, not the
    agent-visible task spec (which lives in instruction.md).
    """
    out: list[str] = []
    for intent in intents:
        cmdline_str = " ".join(intent.cmdline_template) if intent.cmdline_template else "<unknown>"
        if intent.expected_exit == 0:
            exit_str = "should succeed (exit 0)"
        else:
            exit_str = f"should error (exit {intent.expected_exit})"
        suffix = ""
        if intent.expected_state_calls:
            suffix = f" and call: {', '.join(intent.expected_state_calls)}"
        out.append(f"`{cmdline_str}` {exit_str}{suffix}")
    return out


def _count_behaviour_tags(intents: list[TestIntent]) -> dict[str, int]:
    """Distribution of behaviour_tag across the intents in this task."""
    counts: dict[str, int] = {}
    for i in intents:
        counts[i.behaviour_tag] = counts.get(i.behaviour_tag, 0) + 1
    return counts


def _parse_test_sh_summary(text: str) -> dict:
    m2 = _TEST_SH_V2_REWARD_RE.search(text)
    if m2:
        r = float(m2.group(1))
        p = f = e = 0
        for pm in _PYTEST_TOTALS_RE.finditer(text):
            p += int(pm.group(1) or 0)
            f += int(pm.group(2) or 0)
            e += int(pm.group(3) or 0)
        return {"passed": p, "total": p + f + e, "pass_rate": r, "summary": text[-500:]}
    m = _TEST_SH_SUMMARY_RE.search(text)
    if not m:
        return {"passed": 0, "total": 0, "pass_rate": 0.0, "summary": text[-500:]}
    p, f, e = int(m.group(1)), int(m.group(2)), int(m.group(3))
    r = float(m.group(4))
    return {"passed": p, "total": p + f + e, "pass_rate": r, "summary": text[-500:]}


def _build_or_reuse_docker_image(dockerfile_content: str, ctx_dir: Path) -> str | None:
    """Build the gauntlet image, or reuse cached. Returns None if docker missing."""
    sha = hashlib.sha256(dockerfile_content.encode()).hexdigest()[:16]
    if sha in _DOCKER_IMAGE_CACHE:
        return _DOCKER_IMAGE_CACHE[sha]
    tag = f"r2e-cliapp-gauntlet:{sha}"
    try:
        subprocess.run(["docker", "version"], check=True, capture_output=True, timeout=10)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("docker not available; skipping G3+G4 gauntlet")
        return None
    logger.info("docker build %s (one-time per Dockerfile content)", tag)
    try:
        subprocess.run(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "-q",
                "-t",
                tag,
                str(ctx_dir),
            ],
            check=True,
            capture_output=True,
            timeout=900,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"")[-500:].decode("utf-8", errors="replace")
        logger.error("docker build failed: %s", err)
        return None
    _DOCKER_IMAGE_CACHE[sha] = tag
    return tag


# A generic sidecar backend (kinesalite/local-kms/elasticmq/cognito) runs its fake
# service as a SEPARATE container, so the network-isolated gate containers cannot reach
# it the way DDB reaches its baked-in loopback JVM. Instead we start the sidecar on a
# throwaway docker network and have each gate container join that network with
# AWS_ENDPOINT_URL pointed at it. Internet isolation is still enforced by the conftest's
# socket guard (public IPs rejected) -- only the private sidecar host is reachable.
def _wait_sidecar_ready(
    network: str, host: str, port: int, probe_image: str, timeout_sec: int
) -> bool:
    """Poll (from a throwaway container on the net) until the sidecar TCP port opens."""
    probe = (
        "import socket,time,sys\n"
        f"for _ in range({max(1, timeout_sec)} * 2):\n"
        "    s = socket.socket(); s.settimeout(1)\n"
        "    try:\n"
        f"        s.connect(('{host}', {port})); s.close(); sys.exit(0)\n"
        "    except Exception:\n"
        "        time.sleep(0.5)\n"
        "sys.exit(1)\n"
    )
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--network", network, probe_image, "python3", "-c", probe],
            capture_output=True,
            timeout=timeout_sec + 15,
        )
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


@contextlib.contextmanager
def _sidecar_up(spec: SidecarSpec, *, probe_image: str, timeout_sec: int = 40):
    """Start ``spec``'s backend as a sidecar on a throwaway docker network, yielding
    ``(network, endpoint_url)`` for gate containers to join. Always tears down the
    container + network, even on failure."""
    net = f"r2e-side-{uuid4().hex[:10]}"
    cname = f"{spec.sidecar_service}-{uuid4().hex[:8]}"
    endpoint = spec.sidecar_endpoint()
    subprocess.run(["docker", "network", "create", net], check=True, capture_output=True)
    try:
        run_cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            cname,
            "--network",
            net,
            "--network-alias",
            spec.sidecar_service,
        ]
        for kv in spec.sidecar_env:
            run_cmd += ["-e", kv]
        if spec.sidecar_entrypoint:
            run_cmd += ["--entrypoint", spec.sidecar_entrypoint[0]]
        run_cmd += [spec.sidecar_image, *spec.sidecar_command]
        subprocess.run(run_cmd, check=True, capture_output=True)
        if not _wait_sidecar_ready(
            net, spec.sidecar_service, spec.sidecar_port, probe_image, timeout_sec
        ):
            logger.warning(
                "sidecar %s not ready within %ds; proceeding (conftest re-polls)",
                spec.sidecar_service,
                timeout_sec,
            )
        yield net, endpoint
    finally:
        subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)


def _sidecar_docker_args(
    sidecar: tuple[str, str] | None, *, backend: str = "minio"
) -> list[str]:
    """Network + endpoint args for a gate container: isolated (``--network=none``) by
    default, or joined to a running sidecar network with AWS_ENDPOINT_URL set.

    kwok backend needs a default-route network so kube-apiserver's bind-address
    auto-discovery finds an interface; the conftest's socket guard still blocks
    public IPs so this stays isolated at the process level.
    """
    if sidecar is None:
        if backend == "kwok":
            return []
        return ["--network=none"]
    net, endpoint = sidecar
    return ["--network", net, "-e", f"AWS_ENDPOINT_URL={endpoint}"]


def _docker_run_test_sh(
    image_tag: str,
    bundle_dir: Path,
    timeout_sec: int,
    oracle_override_path: Path | None = None,
    *,
    wrapper: str | None = None,
    sidecar: tuple[str, str] | None = None,
    backend: str = "minio",
) -> dict:
    """Run /workspace/tests/test.sh in the container. Returns parsed summary."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "--cpus=1.0",
        "--memory=1g",
        *_sidecar_docker_args(sidecar, backend=backend),
        "-v",
        f"{bundle_dir / 'tests'}:/workspace/tests:ro",
    ]
    if oracle_override_path is not None:
        cmd.extend(
            [
                "-v",
                f"{oracle_override_path}:/workspace/submission/main.py:ro",
            ]
        )
    cmd.append(image_tag)
    if wrapper is not None:
        cmd.append(wrapper)
    cmd.extend(["bash", "/workspace/tests/test.sh"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        out = (result.stdout + "\n" + result.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return {"passed": 0, "total": 0, "pass_rate": 0.0, "summary": "TIMEOUT"}
    return _parse_test_sh_summary(out)


def _certify_golden(
    *,
    dockerfile: str,
    conftest: str,
    test_files: dict[str, str],
    test_script: str,
    gold_files: dict[str, str],
    extra_tests_aux: dict[str, str] | None = None,
    timeout_sec: int,
    backend: str = "minio",
) -> dict:
    """Run the shipped tests against the SLICED GOLDEN (submission/aws) in Docker and
    return the pass summary. A golden that fails any shipped test means an incomplete
    slice, so the caller rejects the task. Mounts the whole golden submission tree over
    /workspace/submission (multi-file, unlike the single-main.py oracle override)."""
    # Network-isolated cert can't reach the ddb:8000 sidecar; bake+start DDB on
    # loopback via ddb-wrap, same as the gauntlet / ref-grounding paths.
    cert_dockerfile = dockerfile
    wrapper: str | None = None
    if backend == "dynamodb_local":
        cert_dockerfile = dockerfile + _DDB_GAUNTLET_LAYERS + _AWSCLI_INSTALL_LAYERS
        wrapper = _DDB_GAUNTLET_WRAPPER
    with tempfile.TemporaryDirectory(prefix="r2e-goldcert-ctx-") as ctx_str:
        ctx = Path(ctx_str)
        (ctx / "Dockerfile").write_text(cert_dockerfile)
        image = _build_or_reuse_docker_image(cert_dockerfile, ctx)
    if image is None:
        return {"skipped": True, "reason": "docker_unavailable"}

    sidecar_spec = resolve_sidecar(backend)
    sidecar_ctx = (
        _sidecar_up(sidecar_spec, probe_image=image)
        if sidecar_spec is not None
        else contextlib.nullcontext(None)
    )
    with (
        tempfile.TemporaryDirectory(prefix="r2e-goldcert-bundle-") as b_str,
        sidecar_ctx as sidecar,
    ):
        bundle = Path(b_str)
        tests_dir = bundle / "tests"
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text(conftest)
        (tests_dir / "__init__.py").write_text("")
        for rel, content in (extra_tests_aux or {}).items():
            if rel.startswith("tests/"):
                tgt = bundle / rel
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_text(content)
        for fname, code in test_files.items():
            (tests_dir / fname).write_text(code)
        (tests_dir / "test.sh").write_text(test_script)
        (tests_dir / "test.sh").chmod(0o755)
        for rel, content in gold_files.items():
            tgt = bundle / rel
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text(content)
        aws_shim = bundle / "submission" / "aws"
        if aws_shim.is_file():
            aws_shim.chmod(0o755)
        cmd = [
            "docker",
            "run",
            "--rm",
            "--cpus=1.0",
            "--memory=1g",
            *_sidecar_docker_args(sidecar, backend=backend),
            "-v",
            f"{tests_dir}:/workspace/tests:ro",
            "-v",
            f"{bundle / 'submission'}:/workspace/submission:ro",
            image,
        ]
        if wrapper is not None:
            cmd.append(wrapper)
        cmd.extend(["bash", "/workspace/tests/test.sh"])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            full = result.stdout + "\n" + result.stderr
        except subprocess.TimeoutExpired:
            return {
                "skipped": False,
                "passed": 0,
                "total": 0,
                "pass_rate": 0.0,
                "summary": "TIMEOUT",
            }
        parsed = _parse_test_sh_summary(full[-4000:])
        if parsed.get("pass_rate", 0.0) < 1.0:
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            dbg = Path(tempfile.gettempdir()) / f"r2e-goldcert-debug-{ts}"
            dbg.mkdir(parents=True, exist_ok=True)
            (dbg / "output.log").write_text(full)
            with contextlib.suppress(Exception):
                shutil.copytree(bundle / "tests", dbg / "tests")
            logger.warning(
                "golden cert failed (%d/%d passed); debug saved to %s",
                parsed.get("passed", 0),
                parsed.get("total", 0),
                dbg,
            )
        return {"skipped": False, **parsed}


def _run_docker_gauntlet_g3g4(
    *,
    dockerfile_content: str,
    aux_files: dict[str, str],
    test_script: str,
    oracle_code: str,
    empty_max: float,
    oracle_min: float,
    timeout_sec: int,
    backend: str = "minio",
) -> dict:
    """G3 (empty stub fails) + G4 (oracle passes). Returns metrics + verdicts.

    Returns {'skipped': True, ...} if docker unavailable. Otherwise returns
    {g3_empty_pass_rate, g3_pass, g4_oracle_pass_rate, g4_pass, ...}.
    """
    gauntlet_dockerfile = dockerfile_content
    wrapper: str | None = None
    if backend == "dynamodb_local":
        gauntlet_dockerfile = dockerfile_content + _DDB_GAUNTLET_LAYERS + _AWSCLI_INSTALL_LAYERS
        wrapper = _DDB_GAUNTLET_WRAPPER
    with tempfile.TemporaryDirectory(prefix="r2e-gauntlet-ctx-") as ctx_str:
        ctx = Path(ctx_str)
        (ctx / "Dockerfile").write_text(gauntlet_dockerfile)
        image = _build_or_reuse_docker_image(gauntlet_dockerfile, ctx)
    if image is None:
        return {"skipped": True, "reason": "docker_unavailable"}

    sidecar_spec = resolve_sidecar(backend)
    sidecar_ctx = (
        _sidecar_up(sidecar_spec, probe_image=image)
        if sidecar_spec is not None
        else contextlib.nullcontext(None)
    )
    with (
        tempfile.TemporaryDirectory(prefix="r2e-gauntlet-bundle-") as b_str,
        sidecar_ctx as sidecar,
    ):
        bundle = Path(b_str)
        (bundle / "tests").mkdir()
        for rel, content in aux_files.items():
            if rel.startswith("tests/"):
                tgt = bundle / rel
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_text(content)
        (bundle / "tests" / "test.sh").write_text(test_script)
        (bundle / "tests" / "test.sh").chmod(0o755)

        # G3: empty stub (image bakes empty stub at /workspace/submission/main.py)
        g3 = _docker_run_test_sh(
            image,
            bundle,
            timeout_sec,
            oracle_override_path=None,
            wrapper=wrapper,
            sidecar=sidecar,
            backend=backend,
        )
        logger.info(
            "G3 empty stub: %d/%d passed (rate=%.2f, max=%.2f)",
            g3["passed"],
            g3["total"],
            g3["pass_rate"],
            empty_max,
        )

        # G4: oracle override
        oracle_path = bundle / "main.py"
        oracle_path.write_text(oracle_code)
        g4 = _docker_run_test_sh(
            image,
            bundle,
            timeout_sec,
            oracle_override_path=oracle_path,
            wrapper=wrapper,
            sidecar=sidecar,
            backend=backend,
        )
        logger.info(
            "G4 oracle: %d/%d passed (rate=%.2f, min=%.2f)",
            g4["passed"],
            g4["total"],
            g4["pass_rate"],
            oracle_min,
        )

    return {
        "skipped": False,
        "image_tag": image,
        "g3_empty_pass_rate": g3["pass_rate"],
        "g3_empty_passed": g3["passed"],
        "g3_empty_total": g3["total"],
        "g3_pass": g3["pass_rate"] <= empty_max,
        "g4_oracle_pass_rate": g4["pass_rate"],
        "g4_oracle_passed": g4["passed"],
        "g4_oracle_total": g4["total"],
        "g4_pass": g4["pass_rate"] >= oracle_min,
    }


# ---------------------------------------------------------------------------
# Reference grounding — real aws-cli as the ground-truth oracle
#
# The synthesised tests (translated from aws-cli's own functional tests) and
# the synthesised oracle are generated independently, so they disagree on ~15-
# 25% of assertions (error wording, output format, edge cases). Reference
# grounding resolves this: it runs the test bank against (a) the REAL `aws`
# binary, (b) the empty stub, and (c) the synthesised oracle, then ships only
# the tests that the real aws CLI AND the oracle both pass and the empty stub
# fails. Result: every shipped test matches real S3-CLI behaviour AND is solved
# by the gold patch, while staying discriminative.
#
# `aws` is installed ONLY in the gauntlet image (a derived layer on top of the
# task Dockerfile), never in the shipped task image — the agent must still build
# the CLI from scratch.
# ---------------------------------------------------------------------------

# v2 has no PyPI package; this is the binary version pulled from awscli.amazonaws.com.
# Source repo must be cloned at `--ref v2` for the test corpus to match.
PINNED_AWSCLI_VERSION = "2.28.23"

# aws-cli v2 install layer for GAUNTLET images ONLY. Both ref-grounding AND
# G3/G4 pertest need real `aws` on PATH: ref-grounding invokes it via the
# reference shim, G3/G4 invokes it via the LLM oracle main.py + conftest's
# `shutil.which("aws")` presence check. S3 backend gets `aws` from the base
# image; DDB backend does not, so it must be baked here too.
_AWSCLI_INSTALL_LAYERS = f"""
# --- aws-cli v2 baked into internal gauntlet images (not the shipped image) ---
# aws-cli v2 has no PyPI package; install from the official binary zip.
RUN (apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \\
     && rm -rf /var/lib/apt/lists/*) || \\
    apk add --no-cache curl unzip ca-certificates || true
RUN set -e; \\
    arch="$(uname -m)"; \\
    case "$arch" in \\
      x86_64|amd64) cli_arch=x86_64 ;; \\
      aarch64|arm64) cli_arch=aarch64 ;; \\
      *) echo "cli_app gauntlet: unsupported arch $arch" >&2; exit 1 ;; \\
    esac; \\
    url="https://awscli.amazonaws.com/awscli-exe-linux-${{cli_arch}}-{PINNED_AWSCLI_VERSION}.zip"; \\
    curl -sSL "$url" -o /tmp/awscli.zip; \\
    unzip -q /tmp/awscli.zip -d /tmp; \\
    /tmp/aws/install; \\
    rm -rf /tmp/awscli.zip /tmp/aws
RUN aws --version
"""

# Mounted as /workspace/submission/main.py during the reference run: forwards
# argv to the real `aws` binary, so `cli("s3","mb",...)` runs `aws s3 mb ...`
# against the same S3 server the test fixtures point at (via
# AWS_ENDPOINT_URL_S3 set in the cli fixture — works for moto and MinIO alike,
# since aws-cli v2.13+ honours AWS_ENDPOINT_URL_S3).
_REFERENCE_SHIM = (
    "import subprocess\n"
    "import sys\n"
    "raise SystemExit(subprocess.run(['aws', *sys.argv[1:]]).returncode)\n"
)

_REFERENCE_SHIM_KWOK = (
    "import subprocess\n"
    "import sys\n"
    "raise SystemExit(subprocess.run(['kubectl', *sys.argv[1:]]).returncode)\n"
)

_PERTEST_PASS_RE = re.compile(r"^(tests/\S+\.py)::\S+\s+PASSED", re.M)


def _docker_run_pertest(
    image_tag: str,
    bundle_dir: Path,
    timeout_sec: int,
    override_path: Path | None = None,
    *,
    wrapper: str | None = None,
    sidecar: tuple[str, str] | None = None,
    backend: str = "minio",
) -> tuple[set[str], str]:
    """Run the test bank in the container; return (passed test-file names, full output).

    Callers may save the full output when grounding produces zero passes to see why.
    """
    cmd = [
        "docker",
        "run",
        "--rm",
        "--cpus=1.0",
        "--memory=1g",
        *_sidecar_docker_args(sidecar, backend=backend),
        "-v",
        f"{bundle_dir / 'tests'}:/workspace/tests:ro",
    ]
    if override_path is not None:
        cmd.extend(["-v", f"{override_path}:/workspace/submission/main.py:ro"])
    cmd.append(image_tag)
    if wrapper is not None:
        cmd.append(wrapper)
    cmd.extend(["bash", "/workspace/tests/test.sh"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired as exc:
        logger.warning(
            "docker per-test run timed out after %ss (override=%s, wrapper=%s); "
            "partial stdout=%d bytes lost",
            timeout_sec,
            override_path.name if override_path else "none",
            wrapper or "none",
            len(exc.stdout or b"") if exc.stdout else 0,
        )
        partial_out = exc.stdout or ""
        partial_err = exc.stderr or ""
        if isinstance(partial_out, bytes):
            partial_out = partial_out.decode("utf-8", "replace")
        if isinstance(partial_err, bytes):
            partial_err = partial_err.decode("utf-8", "replace")
        return set(), partial_out + "\n[TIMEOUT]\n" + partial_err
    out = result.stdout + "\n" + result.stderr
    return {Path(m.group(1)).name for m in _PERTEST_PASS_RE.finditer(out)}, out


def _run_reference_grounding(
    *,
    dockerfile_content: str,
    tests_aux: dict[str, str],
    test_script: str,
    oracle_code: str,
    timeout_sec: int,
    backend: str = "minio",
) -> dict:
    """Ground the test bank against the real aws CLI + oracle + empty stub.

    Returns {'skipped': True, ...} if docker unavailable. Otherwise returns the
    grounded file set = (reference-pass ∩ oracle-pass) − empty-pass, plus counts.
    """
    base_dockerfile = dockerfile_content
    wrapper: str | None = None
    if backend == "dynamodb_local":
        base_dockerfile = dockerfile_content + _DDB_GAUNTLET_LAYERS
        wrapper = _DDB_GAUNTLET_WRAPPER
    ref_dockerfile = base_dockerfile + (_AWSCLI_INSTALL_LAYERS if backend != "kwok" else "")
    with tempfile.TemporaryDirectory(prefix="r2e-refground-ctx-") as ctx_str:
        ctx = Path(ctx_str)
        (ctx / "Dockerfile").write_text(ref_dockerfile)
        image = _build_or_reuse_docker_image(ref_dockerfile, ctx)
    if image is None:
        return {"skipped": True, "reason": "docker_unavailable"}

    sidecar_spec = resolve_sidecar(backend)
    sidecar_ctx = (
        _sidecar_up(sidecar_spec, probe_image=image)
        if sidecar_spec is not None
        else contextlib.nullcontext(None)
    )
    with (
        tempfile.TemporaryDirectory(prefix="r2e-refground-bundle-") as b_str,
        sidecar_ctx as sidecar,
    ):
        bundle = Path(b_str)
        (bundle / "tests").mkdir()
        for rel, content in tests_aux.items():
            if rel.startswith("tests/"):
                tgt = bundle / rel
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_text(content)
        (bundle / "tests" / "test.sh").write_text(test_script)
        (bundle / "tests" / "test.sh").chmod(0o755)

        ref_path = bundle / "reference_main.py"
        ref_path.write_text(_REFERENCE_SHIM_KWOK if backend == "kwok" else _REFERENCE_SHIM)
        reference_pass, ref_out = _docker_run_pertest(
            image, bundle, timeout_sec, ref_path, wrapper=wrapper, sidecar=sidecar, backend=backend
        )

        empty_pass, empty_out = _docker_run_pertest(
            image, bundle, timeout_sec, None, wrapper=wrapper, sidecar=sidecar, backend=backend
        )

        oracle_path = bundle / "oracle_main.py"
        oracle_path.write_text(oracle_code)
        oracle_pass, oracle_out = _docker_run_pertest(
            image, bundle, timeout_sec, oracle_path, wrapper=wrapper, sidecar=sidecar, backend=backend
        )

        grounded = (reference_pass & oracle_pass) - empty_pass
        if not grounded:
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            debug_dir = Path(tempfile.gettempdir()) / f"r2e-grounding-debug-{ts}"
            debug_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundle / "tests", debug_dir / "tests")
            shutil.copy(ref_path, debug_dir / "reference_main.py")
            shutil.copy(oracle_path, debug_dir / "oracle_main.py")
            (debug_dir / "reference_output.log").write_text(ref_out)
            (debug_dir / "empty_output.log").write_text(empty_out)
            (debug_dir / "oracle_output.log").write_text(oracle_out)
            (debug_dir / "summary.txt").write_text(
                f"image={image}\nbackend={backend}\ntimeout_sec={timeout_sec}\n"
                f"reference_pass={sorted(reference_pass)}\n"
                f"empty_pass={sorted(empty_pass)}\n"
                f"oracle_pass={sorted(oracle_pass)}\n"
            )
            logger.warning(
                "grounding produced 0 grounded tests; debug bundle saved to %s",
                debug_dir,
            )
    return {
        "skipped": False,
        "image_tag": image,
        "grounded_files": grounded,
        "reference_pass": reference_pass,
        "oracle_pass": oracle_pass,
        "empty_pass": empty_pass,
        "oracle_out": oracle_out,
        "n_reference": len(reference_pass),
        "n_oracle": len(oracle_pass),
        "n_empty": len(empty_pass),
        "n_grounded": len(grounded),
    }


# ---------------------------------------------------------------------------
# Service-profile registry (plug-and-play). DynamoDB and S3/MinIO are the first
# two registered profiles; the engine dispatches on the resolved profile instead
# of hardcoded ``is_ddb`` branches. Adding a service = registering a profile.
# ---------------------------------------------------------------------------
register_profile(
    ServiceProfile(
        backend_key="dynamodb_local",
        service="dynamodb",
        simulation_backend="dynamodb_local",
        extract_mode="botocore_model",
        target_prefix="DynamoDB_20120810",
        json_version="1.0",
        default_target_ops=_DDB_TARGET_OPS_DEFAULT,
        client_module_path="tests/_ddb_http.py",
        client_module_src=_DDB_HTTP_HELPER,
        translation_system=TRANSLATION_SYSTEM_DDB,
        translation_user=TRANSLATION_USER_TEMPLATE_DDB,
        oracle_system=ORACLE_SYSTEM_DDB,
        oracle_user=ORACLE_USER_TEMPLATE_DDB,
        oracle_subset_system=ORACLE_SUBSET_SYSTEM_DDB,
        oracle_subset_user=ORACLE_SUBSET_USER_TEMPLATE_DDB,
        workflow_system=WORKFLOW_SYSTEM_DDB,
        workflow_user=WORKFLOW_USER_TEMPLATE_DDB,
        wf_preamble=_WF_IMPORT_PREAMBLE_DDB,
        build_conftest=lambda golden=False: _build_conftest(
            backend="dynamodb_local", golden=golden
        ),
        build_dockerfile=lambda **kw: _build_dockerfile(backend="dynamodb_local", **kw),
        base_image=PINNED_DDB_BASE_IMAGE,
        pinned_deps=PINNED_DEPS_DDB,
        build_instruction_single=lambda spec, cmd_spec, intents: _build_instruction_md(
            spec, cmd_spec, intents, backend="dynamodb_local"
        ),
        build_instruction_subset=lambda spec, cmd_specs, intents: _build_subset_instruction_md(
            spec, cmd_specs, intents, backend="dynamodb_local"
        ),
    )
)
register_profile(
    ServiceProfile(
        backend_key="minio",
        service="s3",
        simulation_backend="minio",
        extract_mode="tests",
        translation_system=TRANSLATION_SYSTEM,
        translation_user=TRANSLATION_USER_TEMPLATE,
        oracle_system=ORACLE_SYSTEM,
        oracle_user=ORACLE_USER_TEMPLATE,
        oracle_subset_system=ORACLE_SUBSET_SYSTEM,
        oracle_subset_user=ORACLE_SUBSET_USER_TEMPLATE,
        workflow_system=WORKFLOW_SYSTEM,
        workflow_user=WORKFLOW_USER_TEMPLATE,
        wf_preamble=_WF_IMPORT_PREAMBLE,
        build_conftest=lambda golden=False: _build_conftest(backend="minio", golden=golden),
        build_dockerfile=lambda **kw: _build_dockerfile(backend="minio", **kw),
        base_image=PINNED_BASE_IMAGE,
        pinned_deps=PINNED_DEPS,
        build_instruction_single=lambda spec, cmd_spec, intents: _build_instruction_md(
            spec, cmd_spec, intents, backend="minio"
        ),
        build_instruction_subset=lambda spec, cmd_specs, intents: _build_subset_instruction_md(
            spec, cmd_specs, intents, backend="minio"
        ),
    )
)


# ---------------------------------------------------------------------------
# Kinesis (kinesalite) — proof that adding a service is ONE registered profile
# and no engine edits: the whole card routes through the generic
# _cli_app_generic path. Sidecar + service-base images are digest-pinned;
# pinned_deps reuse AWSCLI_DEP_CLOSURE so they never drift from the S3/DDB set.
# ---------------------------------------------------------------------------
KINESALITE_IMAGE = (
    "instructure/kinesalite@sha256:34400d82f28fa91b940a7c4afaf3a8ecdf47a0dd15625ebaa077d0ab28343581"
)
KINESALITE_BASE_IMAGE = (
    "426628337772.dkr.ecr.ap-south-1.amazonaws.com/aws_cli_kinesis@sha256:"
    "41e76338d734597ae1df0e397628497aebd379e5d57de644f7454f1ecaca0fad"
)

_KINESALITE_SPEC = SidecarSpec(
    backend_key="kinesalite",
    service="kinesis",
    simulation_backend="kinesalite",
    target_prefix="Kinesis_20131202",
    json_version="1.1",
    endpoint_env="AWS_ENDPOINT_URL_KINESIS",
    signing_service="kinesis",
    fixture_name="kinesis",
    sidecar_service="kinesis",
    sidecar_image=KINESALITE_IMAGE,
    sidecar_port=4567,
    sidecar_entrypoint=("",),
    sidecar_command=(
        "node",
        "/usr/src/app/node_modules/kinesalite/cli.js",
        "--path",
        "/var/lib/kinesalite",
        "--port",
        "4567",
    ),
    sidecar_healthcheck="curl -s -o /dev/null http://127.0.0.1:4567/ || exit 1",
    ready_action="ListStreams",
    reset_py=(
        "try:\n"
        "    for _s in _c.rpc('ListStreams', {}).get('StreamNames', []):\n"
        "        _c.rpc('DeleteStream', {'StreamName': _s})\n"
        "    for _ in range(50):\n"
        "        if not _c.rpc('ListStreams', {}).get('StreamNames', []):\n"
        "            break\n"
        "        _time.sleep(0.1)\n"
        "except Exception:\n"
        "    pass"
    ),
    wire_rules=(
        "Kinesis wire protocol is JSON 1.1 (X-Amz-Target: Kinesis_20131202.<Op>). "
        "CreateStream {StreamName, ShardCount} creates a stream; it is not immediately "
        "ACTIVE — DescribeStream returns StreamDescription with StreamName, StreamARN, "
        "StreamStatus (CREATING then ACTIVE) and Shards[]. ListStreams returns "
        "{StreamNames:[...]}. DeleteStream {StreamName}. PutRecord {StreamName, "
        "Data(base64 string), PartitionKey} -> {ShardId, SequenceNumber}. Assert on "
        "StreamDescription fields via DescribeStream (StreamName/shard count), not on "
        "stdout wording. Data blobs are base64 strings in the JSON body and stdout. "
        "CRITICAL backend timing facts (assert accordingly or the real aws CLI fails): "
        "(1) After CreateStream the stream is 'CREATING' and stays CREATING on this "
        "backend — NEVER assert StreamStatus=='ACTIVE'; assert StreamStatus in "
        "('CREATING','ACTIVE') or just assert StreamName. (2) While CREATING, "
        "DescribeStream returns Shards==[] regardless of ShardCount — NEVER assert on "
        "len(Shards) or shard contents for a fresh stream; assert on StreamName only. "
        "(3) DeleteStream is ASYNC and this backend does NOT faithfully emulate the "
        "transitional 'DELETING' state: after delete, DescribeStream may return "
        "StreamStatus in ('DELETING','ACTIVE') OR the stream may already be gone. NEVER "
        "assert a specific post-delete StreamStatus (StreamStatus=='DELETING' is a known "
        "failure on this backend); assert ONLY that delete returncode==0, and tolerate the "
        "stream being either still-present or absent afterward."
    ),
    oracle_rules=(
        "Map CLI flags to Kinesis API params in PascalCase: --stream-name->StreamName, "
        "--shard-count->ShardCount (int), --partition-key->PartitionKey, --limit->Limit "
        "(int), --exclusive-start-shard-id->ExclusiveStartShardId. --data is a blob: "
        "aws-cli v2 cli_binary_format=base64 is the default, so a bare `--data <val>` "
        "value is ALREADY base64 — put it into the JSON Data field verbatim (do NOT "
        "re-encode). DescribeStream returns {StreamDescription:{...}} — print the "
        "response as JSON. On a missing stream the service returns "
        "ResourceNotFoundException; on a duplicate CreateStream, ResourceInUseException "
        "— write the error response body (with __type) to stderr."
    ),
    base_image=KINESALITE_BASE_IMAGE,
    pinned_deps=("pytest==8.3.3", "urllib3>=1.25.4,<1.27", *AWSCLI_DEP_CLOSURE),
    default_target_ops=(
        "CreateStream",
        "DescribeStream",
        "ListStreams",
        "DeleteStream",
        "PutRecord",
    ),
)
register_profile(
    make_generic_profile(
        _KINESALITE_SPEC,
        build_instruction_single=lambda spec, cmd_spec, intents: _build_instruction_md_generic(
            spec, cmd_spec, intents, sidecar=_KINESALITE_SPEC
        ),
        build_instruction_subset=lambda spec, cmd_specs, intents: (
            _build_subset_instruction_md_generic(spec, cmd_specs, intents, sidecar=_KINESALITE_SPEC)
        ),
    )
)


# ---------------------------------------------------------------------------
# KMS (local-kms) — generic sidecar profile. AWS JSON 1.1 wire protocol
# (X-Amz-Target: TrentService.<Op>); nsmithuk/local-kms is a small Go emulator
# that listens on :8080. Sidecar + service-base images are digest-pinned.
# ---------------------------------------------------------------------------
LOCAL_KMS_IMAGE = (
    "nsmithuk/local-kms@sha256:e070866476b20973a9e23a9b636204b7a222e4169a6e03198d27b80d47ed28e3"
)
LOCAL_KMS_BASE_IMAGE = (
    "426628337772.dkr.ecr.ap-south-1.amazonaws.com/aws_cli_kms@sha256:"
    "017f6a2fa8f9e04413a40bf30b2b5f0ac48808462e537d01f576227144dd695f"
)

_LOCAL_KMS_SPEC = SidecarSpec(
    backend_key="local_kms",
    service="kms",
    simulation_backend="local_kms",
    target_prefix="TrentService",
    json_version="1.1",
    endpoint_env="AWS_ENDPOINT_URL_KMS",
    signing_service="kms",
    fixture_name="kms",
    sidecar_service="kms",
    sidecar_image=LOCAL_KMS_IMAGE,
    sidecar_port=8080,
    sidecar_entrypoint=("",),
    sidecar_command=("local-kms",),
    sidecar_healthcheck="nc -z 127.0.0.1 8080 || exit 1",
    ready_action="ListKeys",
    reset_py=(
        "try:\n"
        "    for _a in _c.rpc('ListAliases', {}).get('Aliases', []):\n"
        "        _n = _a.get('AliasName', '')\n"
        "        if _n.startswith('alias/') and not _n.startswith('alias/aws/'):\n"
        "            try:\n"
        "                _c.rpc('DeleteAlias', {'AliasName': _n})\n"
        "            except Exception:\n"
        "                pass\n"
        "except Exception:\n"
        "    pass"
    ),
    wire_rules=(
        "KMS wire protocol is AWS JSON 1.1 (X-Amz-Target: TrentService.<Op>). "
        "CreateKey {Description?, KeyUsage?, KeySpec?} -> {KeyMetadata:{KeyId, Arn, "
        "KeyState, Enabled, KeyUsage, ...}}. DescribeKey {KeyId} accepts a raw key id, a "
        "key ARN, or 'alias/<name>' and returns {KeyMetadata:{...}}. ListKeys -> "
        "{Keys:[{KeyId, KeyArn}], Truncated}. CreateAlias {AliasName:'alias/<name>', "
        "TargetKeyId}. ListAliases -> {Aliases:[{AliasName, AliasArn, TargetKeyId?}]}. "
        "Encrypt {KeyId, Plaintext(base64 string)} -> {CiphertextBlob(base64 string), "
        "KeyId}. Decrypt {CiphertextBlob(base64 string)} -> {Plaintext(base64 string), "
        "KeyId}. GenerateDataKey {KeyId, KeySpec|NumberOfBytes} -> {CiphertextBlob, "
        "Plaintext, KeyId}. Assert on returned KeyMetadata/aliases via DescribeKey/"
        "ListKeys and on the Encrypt->Decrypt ROUND TRIP (decrypted Plaintext equals the "
        "input), never on stdout wording or on the exact ciphertext bytes (nondeterministic). "
        "CRITICAL backend facts (assert accordingly or the real aws CLI fails): "
        "(1) KeyId is a fresh UUID per CreateKey — never hard-code or assert a specific "
        "id; capture it from the CreateKey response. "
        "(2) KMS keys CANNOT be deleted immediately: ScheduleKeyDeletion sets "
        "KeyState=='PendingDeletion' with a PendingWindowInDays (min 7) and returns exit "
        "0 — afterwards DescribeKey STILL returns the key (KeyState=='PendingDeletion'), "
        "it does NOT become NotFound. Never assert describe fails after scheduling "
        "deletion; assert KeyState. "
        "(3) A disabled key (DisableKey) still Describes fine (Enabled==false) but Encrypt "
        "with it returns DisabledException; EnableKey restores it. "
        "(4) alias names are namespaced 'alias/<name>'; a duplicate CreateAlias returns "
        "AlreadyExistsException; describing/encrypting a missing key or alias returns "
        "NotFoundException."
    ),
    oracle_rules=(
        "Map CLI flags to KMS API params in PascalCase: --key-id->KeyId, "
        "--description->Description, --key-usage->KeyUsage, --key-spec->KeySpec (also "
        "accept --customer-master-key-spec->KeySpec), --alias-name->AliasName, "
        "--target-key-id->TargetKeyId, --number-of-bytes->NumberOfBytes (int), "
        "--pending-window-in-days->PendingWindowInDays (int). --plaintext and "
        "--ciphertext-blob are BLOB args: aws-cli v2 defaults cli_binary_format=base64, so "
        "a bare `--plaintext <val>` / `--ciphertext-blob <val>` value is ALREADY base64 — "
        "put it into the JSON Plaintext/CiphertextBlob field verbatim (do NOT re-encode), "
        "and pass the base64 strings the service returns straight back. On a missing "
        "key/alias the service returns NotFoundException; on a disabled key, "
        "DisabledException; on a duplicate alias, AlreadyExistsException — write the error "
        "response body (with __type) to stderr."
    ),
    base_image=LOCAL_KMS_BASE_IMAGE,
    pinned_deps=("pytest==8.3.3", "urllib3>=1.25.4,<1.27", *AWSCLI_DEP_CLOSURE),
    default_target_ops=(
        "CreateKey",
        "DescribeKey",
        "ListKeys",
        "Encrypt",
        "Decrypt",
        "GenerateDataKey",
        "CreateAlias",
        "ListAliases",
        "ScheduleKeyDeletion",
        "EnableKey",
        "DisableKey",
    ),
)
register_profile(
    make_generic_profile(
        _LOCAL_KMS_SPEC,
        build_instruction_single=lambda spec, cmd_spec, intents: _build_instruction_md_generic(
            spec, cmd_spec, intents, sidecar=_LOCAL_KMS_SPEC
        ),
        build_instruction_subset=lambda spec, cmd_specs, intents: (
            _build_subset_instruction_md_generic(spec, cmd_specs, intents, sidecar=_LOCAL_KMS_SPEC)
        ),
    )
)


# ---------------------------------------------------------------------------
# SQS (ElasticMQ) — generic sidecar profile. Modern SQS speaks AWS JSON 1.0
# (X-Amz-Target: AmazonSQS.<Op>); softwaremill/elasticmq serves it on :9324.
# Sidecar + service-base images are digest-pinned.
# ---------------------------------------------------------------------------
ELASTICMQ_IMAGE = (
    "softwaremill/elasticmq@sha256:f1de391a9b8c18fd3f2ce37b4f7d1b8989857e8a8e18bb01284fff899e69da82"
)
ELASTICMQ_BASE_IMAGE = (
    "426628337772.dkr.ecr.ap-south-1.amazonaws.com/aws_cli_sqs@sha256:"
    "5e7d4b7410034dbb0f94e14aa2a3d77a9890daaf01c4bf8409158725f8939ec2"
)

_ELASTICMQ_SPEC = SidecarSpec(
    backend_key="elasticmq",
    service="sqs",
    simulation_backend="elasticmq",
    target_prefix="AmazonSQS",
    json_version="1.0",
    endpoint_env="AWS_ENDPOINT_URL_SQS",
    signing_service="sqs",
    fixture_name="sqs",
    sidecar_service="sqs",
    sidecar_image=ELASTICMQ_IMAGE,
    sidecar_port=9324,
    sidecar_entrypoint=("",),
    sidecar_command=(
        "java",
        "-Dconfig.file=/opt/elasticmq.conf",
        "-jar",
        "/opt/elasticmq/elasticmq-server.jar",
    ),
    sidecar_healthcheck="curl -s -o /dev/null http://127.0.0.1:9324/ || exit 1",
    ready_action="ListQueues",
    reset_py=(
        "try:\n"
        "    for _u in _c.rpc('ListQueues', {}).get('QueueUrls', []):\n"
        "        try:\n"
        "            _c.rpc('DeleteQueue', {'QueueUrl': _u})\n"
        "        except Exception:\n"
        "            pass\n"
        "except Exception:\n"
        "    pass"
    ),
    wire_rules=(
        "SQS wire protocol is AWS JSON 1.0 (X-Amz-Target: AmazonSQS.<Op>). CreateQueue "
        "{QueueName, Attributes?} -> {QueueUrl}. GetQueueUrl {QueueName} -> {QueueUrl}. "
        "ListQueues {QueueNamePrefix?} -> {QueueUrls:[...]}. SendMessage {QueueUrl, "
        "MessageBody} -> {MessageId, MD5OfMessageBody}. ReceiveMessage {QueueUrl, "
        "MaxNumberOfMessages?, WaitTimeSeconds?} -> {Messages:[{MessageId, ReceiptHandle, "
        "Body, MD5OfBody}]} (Messages omitted/empty when the queue is empty). "
        "DeleteMessage {QueueUrl, ReceiptHandle}. GetQueueAttributes {QueueUrl, "
        "AttributeNames:['All'|...]} -> {Attributes:{...string values...}}. DeleteQueue "
        "{QueueUrl}. Assert on the message Body/MD5 round trip and on queue presence via "
        "ListQueues/GetQueueUrl, never on stdout wording. "
        "CRITICAL ElasticMQ backend facts (assert accordingly or the real aws CLI fails): "
        "(1) Send EVERY request to the endpoint (AWS_ENDPOINT_URL_SQS); the server routes "
        "by the QueueUrl's trailing '/<account>/<QueueName>' path, so the HOST in a "
        "returned QueueUrl is irrelevant. ElasticMQ returns QueueUrls with host "
        "'localhost:9324' by default — NEVER assert the QueueUrl host/scheme; assert only "
        "that it ENDS WITH the queue name (…/<QueueName>). Pass the returned QueueUrl "
        "verbatim in the body of later calls. "
        "(2) A just-sent message may not appear on the first ReceiveMessage and a received "
        "message is invisible until its visibility timeout — for a deterministic check "
        "assert ApproximateNumberOfMessages via GetQueueAttributes after SendMessage, or "
        "assert the SendMessage returncode==0 and MessageId present and tolerate an empty "
        "first read. "
        "(3) A FIFO queue REQUIRES a name ending in '.fifo' plus Attributes "
        "{'FifoQueue':'true'}, and SendMessage then needs MessageGroupId. "
        "(4) Operating on a missing queue returns "
        "AWS.SimpleQueueService.NonExistentQueue; recreating an existing name with "
        "different attributes returns QueueNameExists."
    ),
    oracle_rules=(
        "Map CLI flags to SQS API params in PascalCase: --queue-name->QueueName, "
        "--queue-url->QueueUrl, --message-body->MessageBody, --attributes->Attributes "
        "(JSON map), --attribute-names->AttributeNames (list, e.g. ['All']), "
        "--max-number-of-messages->MaxNumberOfMessages (int), "
        "--visibility-timeout->VisibilityTimeout (int), --wait-time-seconds->"
        "WaitTimeSeconds (int), --receipt-handle->ReceiptHandle, --delay-seconds->"
        "DelaySeconds (int), --message-group-id->MessageGroupId. Send every request to "
        "the endpoint host and pass QueueUrl values through verbatim (do not rewrite their "
        "host). On a missing queue the service returns "
        "AWS.SimpleQueueService.NonExistentQueue — write the error response body (with "
        "__type) to stderr."
    ),
    base_image=ELASTICMQ_BASE_IMAGE,
    pinned_deps=("pytest==8.3.3", "urllib3>=1.25.4,<1.27", *AWSCLI_DEP_CLOSURE),
    default_target_ops=(
        "CreateQueue",
        "ListQueues",
        "GetQueueUrl",
        "GetQueueAttributes",
        "SendMessage",
        "ReceiveMessage",
        "DeleteMessage",
        "DeleteQueue",
    ),
)
register_profile(
    make_generic_profile(
        _ELASTICMQ_SPEC,
        build_instruction_single=lambda spec, cmd_spec, intents: _build_instruction_md_generic(
            spec, cmd_spec, intents, sidecar=_ELASTICMQ_SPEC
        ),
        build_instruction_subset=lambda spec, cmd_specs, intents: (
            _build_subset_instruction_md_generic(spec, cmd_specs, intents, sidecar=_ELASTICMQ_SPEC)
        ),
    )
)


# ---------------------------------------------------------------------------
# Cognito Identity Provider (cognito-local) — generic sidecar profile. AWS
# JSON 1.1 wire protocol (X-Amz-Target: AWSCognitoIdentityProviderService.<Op>);
# jagregory/cognito-local serves it on :9229. CLI prefix is `cognito-idp`.
# Sidecar + service-base images are digest-pinned.
# ---------------------------------------------------------------------------
COGNITO_LOCAL_IMAGE = "jagregory/cognito-local@sha256:a5ad30d01da5016a38535a717f6e1642d1b37f886a7b17e90b67f6e5ad134831"
COGNITO_LOCAL_BASE_IMAGE = (
    "426628337772.dkr.ecr.ap-south-1.amazonaws.com/aws_cli_cognito@sha256:"
    "b24fac06ef0ec589f4320bf5b1f02d1996fa527c74e57f56ac4c4f1826d6f6d0"
)

_COGNITO_LOCAL_SPEC = SidecarSpec(
    backend_key="cognito_local",
    service="cognito-idp",
    simulation_backend="cognito_local",
    target_prefix="AWSCognitoIdentityProviderService",
    json_version="1.1",
    endpoint_env="AWS_ENDPOINT_URL_COGNITO_IDENTITY_PROVIDER",
    signing_service="cognito-idp",
    fixture_name="cognito",
    sidecar_service="cognito",
    sidecar_image=COGNITO_LOCAL_IMAGE,
    sidecar_port=9229,
    sidecar_entrypoint=("",),
    sidecar_command=("node", "/app/start.js"),
    sidecar_healthcheck="nc -z 127.0.0.1 9229 || exit 1",
    ready_action="ListUserPools",
    reset_py=(
        "try:\n"
        "    for _p in _c.rpc('ListUserPools', {'MaxResults': 60}).get('UserPools', []):\n"
        "        try:\n"
        "            _c.rpc('DeleteUserPool', {'UserPoolId': _p['Id']})\n"
        "        except Exception:\n"
        "            pass\n"
        "except Exception:\n"
        "    pass"
    ),
    wire_rules=(
        "Cognito IdP wire protocol is AWS JSON 1.1 (X-Amz-Target: "
        "AWSCognitoIdentityProviderService.<Op>). CreateUserPool {PoolName} -> "
        "{UserPool:{Id, Name, ...}}. ListUserPools {MaxResults(int, REQUIRED)} -> "
        "{UserPools:[{Id, Name}]}. DescribeUserPool {UserPoolId} -> {UserPool:{...}}. "
        "CreateUserPoolClient {UserPoolId, ClientName} -> {UserPoolClient:{ClientId, "
        "ClientName, UserPoolId}}. AdminCreateUser {UserPoolId, Username, UserAttributes?} "
        "-> {User:{Username, Attributes, UserStatus, Enabled}}. AdminGetUser {UserPoolId, "
        "Username} -> {Username, UserAttributes, UserStatus}. ListUsers {UserPoolId} -> "
        "{Users:[{Username, Attributes, ...}]}. Assert on Name/Username/ClientName and "
        "cross-op state (create pool -> describe/list it; create user -> admin-get it), "
        "never on stdout wording. "
        "CRITICAL backend facts (assert accordingly or the real aws CLI fails): "
        "(1) UserPoolId is generated ('<region>_<random>', e.g. 'local_xxxxxxxxx') and "
        "ClientId is generated per create — never hard-code them; capture from the create "
        "response and reuse. "
        "(2) ListUserPools REQUIRES MaxResults; calling it without MaxResults is an error. "
        "(3) AdminGetUser/AdminCreateUser/CreateUserPoolClient need an existing "
        "UserPoolId, else ResourceNotFoundException; a brand-new pool has no users. "
        "(4) A duplicate AdminCreateUser (same Username) returns UsernameExistsException; "
        "referencing a missing pool/user/client returns ResourceNotFoundException; a "
        "malformed parameter returns InvalidParameterException."
    ),
    oracle_rules=(
        "Map CLI flags to Cognito IdP API params in PascalCase: --pool-name->PoolName, "
        "--user-pool-id->UserPoolId, --client-name->ClientName, --client-id->ClientId, "
        "--username->Username, --user-attributes->UserAttributes (list of "
        "{'Name':..,'Value':..}; CLI shorthand 'Name=..,Value=..' also appears), "
        "--max-results->MaxResults (int), --group-name->GroupName, "
        "--temporary-password->TemporaryPassword. ListUserPools MUST send MaxResults "
        "(default to 60 when the flag is absent). On a missing pool/user the service "
        "returns ResourceNotFoundException; on a duplicate user, UsernameExistsException; "
        "on bad input, InvalidParameterException — write the error response body (with "
        "__type) to stderr."
    ),
    base_image=COGNITO_LOCAL_BASE_IMAGE,
    pinned_deps=("pytest==8.3.3", "urllib3>=1.25.4,<1.27", *AWSCLI_DEP_CLOSURE),
    default_target_ops=(
        "CreateUserPool",
        "ListUserPools",
        "DescribeUserPool",
        "CreateUserPoolClient",
        "AdminCreateUser",
        "AdminGetUser",
        "ListUsers",
        "DeleteUserPool",
    ),
)
register_profile(
    make_generic_profile(
        _COGNITO_LOCAL_SPEC,
        build_instruction_single=lambda spec, cmd_spec, intents: _build_instruction_md_generic(
            spec, cmd_spec, intents, sidecar=_COGNITO_LOCAL_SPEC
        ),
        build_instruction_subset=lambda spec, cmd_specs, intents: (
            _build_subset_instruction_md_generic(
                spec, cmd_specs, intents, sidecar=_COGNITO_LOCAL_SPEC
            )
        ),
    )
)


# ---------------------------------------------------------------------------
# Kwok validation gate — in-pipeline dynamic gate that runs the emitted task
# image + shipped test.sh against a golden shim (expect reward >= min) and
# an empty stub (expect reward <= max), with optional golden-vendored and
# reference-compiled legs. Ported from Kubectl integration.
# ---------------------------------------------------------------------------

_KWOK_EMPTY_STUB: dict[str, str] = {"submission/kubectl": "#!/bin/bash\nexit 0\n"}


@dataclass(slots=True)
class _ValidationGateResult:
    passed: bool
    golden_reward: float
    empty_reward: float
    reason: str
    golden_summary: str = ""
    empty_summary: str = ""
    skipped: bool = False
    golden_vendored_reward: float = 0.0
    reference_reward: float = 0.0
    golden_vendored_summary: str = ""
    reference_summary: str = ""


def _validation_gate_run_container(
    image_tag: str,
    bundle_dir: Path,
    timeout_sec: int,
    mounts: list[tuple[Path, str]],
    *,
    network_mode: str = "none",
    pre_test_script: str | None = None,
) -> dict:
    cmd = [
        "docker",
        "run",
        "--platform",
        "linux/amd64",
        "--rm",
        "--cpus=1.0",
        "--memory=1g",
        f"--network={network_mode}",
        "-v",
        f"{bundle_dir / 'tests'}:/workspace/tests:ro",
    ]
    for local, target in mounts:
        cmd.extend(["-v", f"{local}:{target}:ro"])
    if pre_test_script is not None:
        cmd.extend(
            [
                image_tag,
                "bash",
                "-c",
                f"set -eo pipefail; {pre_test_script} && bash /workspace/tests/test.sh",
            ]
        )
    else:
        cmd.extend([image_tag, "bash", "/workspace/tests/test.sh"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        out = (result.stdout + "\n" + result.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return {"passed": 0, "total": 0, "pass_rate": 0.0, "summary": "TIMEOUT"}
    summary = _parse_test_sh_summary(out)
    if pre_test_script is not None and result.returncode != 0 and summary.get("total", 0) == 0:
        summary = {"passed": 0, "total": 0, "pass_rate": 0.0, "summary": "BUILD_FAILED"}
    return summary


def _materialise_mounts(root: Path, files: dict[str, str]) -> list[tuple[Path, str]]:
    mounts: list[tuple[Path, str]] = []
    for rel, content in files.items():
        local = root / rel.replace("/", "__")
        local.write_text(content)
        local.chmod(0o755)
        mounts.append((local, f"/workspace/{rel}"))
    return mounts


_GOLDEN_VENDORED_PRE_TEST = (
    "cd /workspace && git apply --whitespace=nowarn /work/golden.diff && "
    "cd /workspace/submission/kubectl-src && "
    "GOFLAGS=-mod=vendor go build -o /workspace/submission/kubectl ./cmd/kubectl"
)

_REFERENCE_PRE_TEST = (
    "cd /workspace && git apply --whitespace=nowarn /work/reference.diff && "
    "cd /workspace/submission && go build -o kubectl ."
)


def _run_validation_gate(
    *,
    dockerfile_content: str,
    aux_files: dict[str, str],
    test_script: str,
    golden_shim: dict[str, str],
    empty_stub: dict[str, str],
    min_golden_reward: float,
    max_empty_reward: float,
    timeout_sec: int,
    backend: str = "minio",
    golden_vendored_diff: str | None = None,
    reference_diff: str | None = None,
    min_reference_reward: float = 0.5,
    compile_timeout_sec: int | None = None,
) -> _ValidationGateResult:
    with tempfile.TemporaryDirectory(prefix="r2e-valgate-ctx-") as ctx_str:
        ctx = Path(ctx_str)
        (ctx / "Dockerfile").write_text(dockerfile_content)
        image = _build_or_reuse_docker_image(dockerfile_content, ctx)
    if image is None:
        return _ValidationGateResult(
            passed=False,
            golden_reward=0.0,
            empty_reward=0.0,
            reason="validation_gate_docker_unavailable",
            skipped=True,
        )

    with tempfile.TemporaryDirectory(prefix="r2e-valgate-bundle-") as b_str:
        bundle = Path(b_str)
        (bundle / "tests").mkdir()
        for rel, content in aux_files.items():
            if rel.startswith("tests/"):
                tgt = bundle / rel
                tgt.parent.mkdir(parents=True, exist_ok=True)
                tgt.write_text(content)
        (bundle / "tests" / "test.sh").write_text(test_script)
        (bundle / "tests" / "test.sh").chmod(0o755)

        golden_dir = bundle / "_golden"
        golden_dir.mkdir()
        golden_mounts = _materialise_mounts(golden_dir, golden_shim)

        empty_dir = bundle / "_empty"
        empty_dir.mkdir()
        empty_mounts = _materialise_mounts(empty_dir, empty_stub)

        network_mode = "bridge" if backend == "kwok" else "none"
        compile_to = compile_timeout_sec if compile_timeout_sec is not None else timeout_sec
        golden_summary = _validation_gate_run_container(
            image, bundle, timeout_sec, golden_mounts, network_mode=network_mode
        )
        empty_summary = _validation_gate_run_container(
            image, bundle, timeout_sec, empty_mounts, network_mode=network_mode
        )

        golden_vendored_summary: dict = {}
        if golden_vendored_diff is not None:
            gv_dir = bundle / "_golden_vendored"
            gv_dir.mkdir()
            gv_diff_path = gv_dir / "golden.diff"
            gv_diff_path.write_text(golden_vendored_diff)
            gv_diff_path.chmod(0o644)
            golden_vendored_summary = _validation_gate_run_container(
                image,
                bundle,
                compile_to,
                [(gv_diff_path, "/work/golden.diff")],
                network_mode=network_mode,
                pre_test_script=_GOLDEN_VENDORED_PRE_TEST,
            )

        reference_summary: dict = {}
        if reference_diff is not None:
            ref_dir = bundle / "_reference"
            ref_dir.mkdir()
            ref_diff_path = ref_dir / "reference.diff"
            ref_diff_path.write_text(reference_diff)
            ref_diff_path.chmod(0o644)
            reference_summary = _validation_gate_run_container(
                image,
                bundle,
                compile_to,
                [(ref_diff_path, "/work/reference.diff")],
                network_mode=network_mode,
                pre_test_script=_REFERENCE_PRE_TEST,
            )

    golden_reward = float(golden_summary.get("pass_rate", 0.0))
    empty_reward = float(empty_summary.get("pass_rate", 0.0))
    golden_vendored_reward = float(golden_vendored_summary.get("pass_rate", 0.0))
    reference_reward = float(reference_summary.get("pass_rate", 0.0))
    g_out = golden_summary.get("summary", "")
    e_out = empty_summary.get("summary", "")
    gv_out = golden_vendored_summary.get("summary", "")
    ref_out = reference_summary.get("summary", "")

    def _fail(reason: str) -> _ValidationGateResult:
        return _ValidationGateResult(
            passed=False,
            golden_reward=golden_reward,
            empty_reward=empty_reward,
            golden_vendored_reward=golden_vendored_reward,
            reference_reward=reference_reward,
            reason=reason,
            golden_summary=g_out,
            empty_summary=e_out,
            golden_vendored_summary=gv_out,
            reference_summary=ref_out,
        )

    if g_out == "TIMEOUT":
        return _fail("validation_gate_timeout_golden")
    if e_out == "TIMEOUT":
        return _fail("validation_gate_timeout_empty")
    if golden_vendored_diff is not None and gv_out == "TIMEOUT":
        return _fail("validation_gate_timeout_golden_vendored")
    if reference_diff is not None and ref_out == "TIMEOUT":
        return _fail("validation_gate_timeout_reference")

    if golden_vendored_diff is not None and gv_out == "BUILD_FAILED":
        return _fail("validation_gate_golden_vendored_build_failed")
    if reference_diff is not None and ref_out == "BUILD_FAILED":
        return _fail("validation_gate_reference_build_failed")

    if golden_reward < min_golden_reward:
        return _fail(f"all_tests_failed_validation_gate_golden_{golden_reward:.2f}")
    if empty_reward > max_empty_reward:
        return _fail(f"all_tests_failed_validation_gate_empty_{empty_reward:.2f}")
    if golden_vendored_diff is not None and golden_vendored_reward < min_golden_reward:
        return _fail(
            f"all_tests_failed_validation_gate_golden_vendored_{golden_vendored_reward:.2f}"
        )
    if reference_diff is not None and reference_reward < min_reference_reward:
        return _fail(f"all_tests_failed_validation_gate_reference_{reference_reward:.2f}")

    return _ValidationGateResult(
        passed=True,
        golden_reward=golden_reward,
        empty_reward=empty_reward,
        golden_vendored_reward=golden_vendored_reward,
        reference_reward=reference_reward,
        reason="ok",
        golden_summary=g_out,
        empty_summary=e_out,
        golden_vendored_summary=gv_out,
        reference_summary=ref_out,
    )


def validate_backend_pairing(sim_name: str, source_name: str) -> None:
    """Raise ValueError if the (sim, source) pairing violates either side's compatibility.

    Both sides must handshake: the sim's compatible_sources must contain source_name
    AND the source's compatible_sims must contain sim_name. Called at pipeline
    startup to short-circuit obvious mismatches like ``aws_tests + kwok`` before
    the extractor runs.
    """
    from repo2rlenv.pipelines._cli_app_backends import get_backend
    from repo2rlenv.pipelines._cli_app_backends.source.base import get_source

    sim = get_backend(sim_name)
    src = get_source(source_name)
    if source_name not in sim.compatible_sources:
        raise ValueError(
            f"cli_app: source {source_name!r} is not compatible with sim {sim_name!r}; "
            f"sim advertises compatible_sources={sorted(sim.compatible_sources)}"
        )
    if sim_name not in src.compatible_sims:
        raise ValueError(
            f"cli_app: sim {sim_name!r} is not compatible with source {source_name!r}; "
            f"source advertises compatible_sims={sorted(src.compatible_sims)}"
        )


def _build_kwok_task_spec(cmd_specs, translated_intents, command_prefix: str = ""):
    """Build a duck-typed task_spec for KwokSimulationBackend.emit_reference_client.

    The pruner reads `.commands` (verbs) to filter client methods, `.kinds`
    (resource kinds) to trim the KINDS catalog, and `.command_prefix` to
    generate a golden shim that strips the synthesis-time prefix arg before
    exec'ing real kubectl.
    """
    verbs = sorted({c.name for c in cmd_specs})
    kinds: set[str] = set()
    for intent in translated_intents or ():
        template = getattr(intent, "cmdline_template", None)
        if template and len(template) >= 3 and template[0] == "kubectl":
            kinds.add(template[2])
    return SimpleNamespace(
        commands=verbs,
        kinds=sorted(kinds),
        command_prefix=command_prefix or "",
    )


_KWOK_SUBSET_IMAGE_CACHE: dict[str, str] = {}


def _kwok_subset_hash(
    cmd_names: list[str],
    kubectl_version: str,
    kwok_base_image: str,
) -> str:
    payload = "|".join(
        [
            ",".join(sorted(cmd_names)),
            kubectl_version,
            kwok_base_image,
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def _git_short_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not sha:
        return "unknown"
    return sha[:8]


def _preflight_ecr_env(profile: str | None) -> None:
    if profile or os.environ.get("AWS_PROFILE"):
        return
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        raise RuntimeError(
            "ECR push enabled but AWS_ACCESS_KEY_ID missing "
            "(and no AWS_PROFILE / cli_app_ecr_profile set). "
            "Export AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + AWS_REGION, "
            "or set cli_app_ecr_profile to a configured named profile."
        )


def _get_manifest_digest(image_ref: str, *, timeout: int = 60) -> str:
    proc = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", "--raw", image_ref],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip() if proc.stderr else ""
        raise RuntimeError(f"docker buildx imagetools inspect --raw {image_ref} failed: {stderr}")
    return "sha256:" + hashlib.sha256(proc.stdout).hexdigest()


def _build_and_push_kwok_subset_image(
    *,
    registry: str,
    profile: str | None,
    platforms: list[str],
    cmd_names: list[str],
    kubectl_version: str,
    kwok_base_image: str,
    dockerfile: str,
    git_sha: str | None = None,
) -> str:
    sha8 = _kwok_subset_hash(cmd_names, kubectl_version, kwok_base_image)
    cached = _KWOK_SUBSET_IMAGE_CACHE.get(sha8)
    if cached is not None:
        logger.info("cli_app: kwok subset image cache hit sha=%s ref=%s", sha8, cached)
        return cached
    if git_sha is None:
        git_sha = _git_short_sha()
    repo_segment = f"r2e-kubectl-{sha8}"
    tag_ref = f"{registry}/{repo_segment}:v{git_sha}"
    region = parse_ecr_region(registry)
    if region is None:
        raise _TaskRejected(f"cli_app_ecr_unsupported_registry_{registry}")
    ensure_ecr_repository(tag_ref, profile=profile)
    ensure_docker_login_ecr(registry, region, profile=profile)
    if not manifest_exists(tag_ref):
        with tempfile.TemporaryDirectory() as ctx:
            ctx_path = Path(ctx)
            (ctx_path / "Dockerfile").write_text(dockerfile)
            logger.info(
                "cli_app: pushing shared kwok subset image sha=%s git=%s ref=%s",
                sha8,
                git_sha,
                tag_ref,
            )
            build_and_push_multiarch(context_dir=ctx_path, image_ref=tag_ref, platforms=platforms)
    else:
        logger.info(
            "cli_app: kwok subset image already exists on registry sha=%s ref=%s",
            sha8,
            tag_ref,
        )
    digest = _get_manifest_digest(tag_ref)
    sha_pinned_ref = f"{registry}/{repo_segment}@{digest}"
    _KWOK_SUBSET_IMAGE_CACHE[sha8] = sha_pinned_ref
    return sha_pinned_ref


_KUBECTL_VERB_BEHAVIOR: dict[str, list[str]] = {
    "get": [
        "Reads one or more resources from the apiserver via the corresponding "
        "`list_<kind>` / `read_<kind>` call and writes a human-readable table to stdout "
        "(`NAME  READY  STATUS  RESTARTS  AGE` for pods; analogous columns per kind).",
        "`-o json` / `-o yaml` MUST emit a machine-parseable object; keys are stable "
        "but ordering is not asserted.",
        "`--namespace <ns>` (or `-n`) restricts the list to that namespace. Without "
        "it, the default namespace is used; `--all-namespaces` widens the scope.",
        "Getting a resource that does not exist FAILS with exit `1` and stderr "
        "containing `NotFound` (or lowercase `not found`).",
        "Getting from a namespace that does not exist FAILS with exit `1` and stderr "
        "containing `NotFound`.",
        "`get` never mutates cluster state; a second `get` over an unchanged cluster "
        "MUST return the same set of names (order-independent).",
    ],
    "apply": [
        "Applies a manifest (`-f <file>`) declaratively: creates the resource if "
        "absent, patches it toward the manifest if present (idempotent).",
        "After success, `kubectl get` on the same name/namespace MUST list the "
        "resource; a re-apply of the SAME manifest is a no-op with respect to spec.",
        "Success stdout is real-kubectl shape: `<kind>/<name> created` on first apply, "
        "`<kind>/<name> configured` or `<kind>/<name> unchanged` on re-apply.",
        "Missing manifest file, malformed YAML, or a manifest that fails apiserver "
        "validation FAILS with exit `1` (stderr contains `Invalid`) or exit `2` "
        "(stderr contains `invalid` for argparse-style flag errors).",
        "`kubectl apply` has NO `--wait-for` flag upstream; only `--wait` exists. Do "
        "NOT invent flags outside the observed argv shapes.",
        "State invariant: after `apply -f pod.yaml`, `read_namespaced_pod` returns the "
        "pod with `.metadata.name` matching the manifest's `metadata.name`.",
    ],
    "delete": [
        "Removes one or more resources from the apiserver via `delete_<kind>` and "
        "prints `<kind>/<name> deleted` on stdout, once per removed object.",
        "After success, the resource MUST NOT appear in the corresponding "
        "`list_<kind>` result; a follow-up `read_<kind>` raises `ApiException` with "
        "`.status == 404`.",
        "Deleting a non-existent resource FAILS with exit `1` and stderr containing "
        "`NotFound` (or lowercase `not found`).",
        "Bulk shapes such as `--all` (all objects in ns) or `--all-namespaces` remove "
        "the corresponding set atomically per kind.",
        "`--namespace <ns>` (or `-n`) selects the namespace; without it the default "
        "namespace is used.",
        "A missing positional name AND missing `--all` MUST fail with exit `2` and "
        "stderr containing `invalid` / `resource(s) were provided`.",
    ],
    "create": [
        "Creates a resource from a manifest (`-f <file>`) or from typed sub-forms "
        "such as `create namespace <name>` / `create configmap <name>`.",
        "After success, the resource MUST appear in the corresponding "
        "`list_<kind>` result; `read_<kind>` returns the created object.",
        "Success stdout is real-kubectl shape: `<kind>/<name> created`.",
        "Creating a resource that already exists FAILS with exit `1` and stderr "
        "containing `AlreadyExists`.",
        "`create` is NOT idempotent (unlike `apply`) — a second `create` of the same "
        "name errors out with `AlreadyExists`.",
        "Missing or unparseable `-f` payload FAILS with exit `1` (stderr `Invalid`) "
        "or exit `2` (stderr `invalid` for missing-arg errors).",
    ],
    "describe": [
        "Prints a multi-section, human-readable view of one or more resources on "
        "stdout: `Name`, `Namespace`, `Labels`, `Annotations`, `Status`, `Events` "
        "sections at minimum for pods; analogous sections per kind.",
        "Reads via `read_<kind>` (single object) or `list_<kind>` (bulk) and formats "
        "the result; NEVER mutates state.",
        "Describing a resource that does not exist FAILS with exit `1` and stderr "
        "containing `NotFound`.",
        "Section output is stable enough to substring-match on section headers "
        "(`Name:`, `Namespace:`, `Status:`) but tests should NOT pin on exact "
        "whitespace or full-line format.",
        "`--namespace <ns>` restricts the lookup; without it the default namespace is used.",
    ],
    "patch": [
        "Applies a strategic-merge or JSON patch (`--patch <body>` or `-p <body>`) to "
        "an existing resource via `patch_<kind>`; only the fields named in the patch "
        "are changed, others are preserved.",
        "After success, `read_<kind>` MUST return the object with the patched fields "
        "reflecting the patch body; unmodified fields keep their prior value.",
        "Success stdout is real-kubectl shape: `<kind>/<name> patched`.",
        "Patching a non-existent resource FAILS with exit `1` and stderr containing `NotFound`.",
        "A malformed patch body (invalid JSON, unknown field, illegal value) FAILS "
        "with exit `1` and stderr containing `Invalid`.",
        "`--type strategic|merge|json` selects the patch semantics; the default is "
        "`strategic` for built-in kinds.",
    ],
    "scale": [
        "Sets the replica count of a scalable workload (Deployment, StatefulSet, "
        "ReplicaSet) via `patch_<kind>_scale` or an equivalent PATCH to `/scale`.",
        "After `scale deployment <name> --replicas=N`, `read_namespaced_deployment` "
        "MUST return `.spec.replicas == N`.",
        "Success stdout is real-kubectl shape: `deployment.apps/<name> scaled`.",
        "`--replicas <n>` is REQUIRED; a missing value FAILS with exit `2` and "
        "stderr containing `invalid` / `required`.",
        "Scaling a non-existent workload FAILS with exit `1` and stderr containing `NotFound`.",
        "Scaling to `0` is legal and MUST succeed; the deployment's spec-replica "
        "count reads back as `0`.",
    ],
    "label": [
        "Adds, updates, or removes labels on an existing resource via a PATCH to "
        "`.metadata.labels`.",
        "`kubectl label <kind>/<name> key=value` sets the label; `kubectl label "
        "<kind>/<name> key-` (trailing hyphen) removes it.",
        "After success, `read_<kind>` MUST return the object with the mutated "
        "`.metadata.labels` map reflecting the change.",
        "Success stdout is real-kubectl shape: `<kind>/<name> labeled`.",
        "Setting a label that already exists WITHOUT `--overwrite` FAILS with exit "
        "`1` and stderr containing `already has a value` / `Invalid`.",
        "Labeling a non-existent resource FAILS with exit `1` and stderr containing `NotFound`.",
    ],
    "annotate": [
        "Adds, updates, or removes annotations on an existing resource via a PATCH "
        "to `.metadata.annotations`; same shape as `label` but for annotations.",
        "After success, `read_<kind>` MUST return the object with the mutated "
        "`.metadata.annotations` map reflecting the change.",
        "Success stdout is real-kubectl shape: `<kind>/<name> annotated`.",
        "Setting an annotation that already exists WITHOUT `--overwrite` FAILS with "
        "exit `1` and stderr containing `already has a value` / `Invalid`.",
        "Annotating a non-existent resource FAILS with exit `1` and stderr containing `NotFound`.",
    ],
    "edit": [
        "Reads the current object via `read_<kind>`, hands the caller-supplied edit "
        "(via `--filename` or in-place buffer) and re-applies via `patch_<kind>`.",
        "After success, the mutated fields MUST be observable via `read_<kind>`.",
        "Editing a non-existent resource FAILS with exit `1` and stderr containing `NotFound`.",
    ],
    "replace": [
        "Replaces an existing resource by re-applying a full manifest via "
        "`replace_<kind>`; unlike `apply`, it requires the object to already exist.",
        "After success, `read_<kind>` returns the manifest-supplied object; every "
        "field NOT in the manifest is either reset to its zero value or dropped.",
        "Replacing a non-existent resource FAILS with exit `1` and stderr containing "
        "`NotFound`. Use `--force` to fall back to delete+create.",
        "Malformed YAML or a manifest that fails apiserver validation FAILS with "
        "exit `1` and stderr containing `Invalid`.",
    ],
    "rollout": [
        "Manages the rollout state of a workload: `rollout status <kind>/<name>` "
        "polls the workload's `.status` until the rollout completes; "
        "`rollout restart` triggers a rolling restart via a PATCH; "
        "`rollout undo` reverts to the previous ReplicaSet.",
        "`rollout status` prints progress lines followed by "
        '`deployment "<name>" successfully rolled out` on completion.',
        "Rollout on a non-existent workload FAILS with exit `1` and stderr containing `NotFound`.",
        "State invariant: after `rollout restart`, the target's "
        "`.spec.template.metadata.annotations` gains a `kubectl.kubernetes.io/"
        "restartedAt` timestamp observable via `read_namespaced_deployment`.",
    ],
    "expose": [
        "Creates a Service targeting an existing workload via `create_namespaced_service`.",
        "After success, `read_namespaced_service` MUST return the created Service "
        "with `.spec.selector` matching the workload's labels.",
        "Exposing a non-existent workload FAILS with exit `1` and stderr containing `NotFound`.",
        "Missing `--port` FAILS with exit `2` and stderr containing `required` / `invalid`.",
    ],
    "autoscale": [
        "Creates a HorizontalPodAutoscaler targeting an existing workload via "
        "`create_namespaced_horizontal_pod_autoscaler`.",
        "After success, `read_namespaced_horizontal_pod_autoscaler` MUST return the "
        "HPA with `.spec.min_replicas` / `.spec.max_replicas` matching the flags.",
        "Autoscaling a non-existent workload FAILS with exit `1` and stderr containing `NotFound`.",
    ],
}


# Fallback bullets when a verb is not in the map above — used defensively so
# rendering never yields an empty section for unknown or unusual verbs.
_KUBECTL_VERB_BEHAVIOR_FALLBACK: list[str] = [
    "Invokes the corresponding apiserver operation for this verb; the resulting "
    "state MUST be observable via the documented read APIs of the other verbs.",
    "On success: exit `0`, real-kubectl-shaped stdout line (`<kind>/<name> "
    "<verb-past-tense>`), stderr empty.",
    "On failure: exit `1` for API errors (stderr contains a stable category "
    "keyword — `NotFound`, `AlreadyExists`, `Invalid`, `Forbidden`, `Conflict`, "
    "`Timeout`) or exit `2` for argparse-style usage errors (stderr contains "
    "`invalid`).",
]


def _kwok_verb_behavior_bullets(verb: str) -> list[str]:
    """Return the 4-8 raiden-style behavior bullets for a kubectl verb."""
    return _KUBECTL_VERB_BEHAVIOR.get(verb.lower(), _KUBECTL_VERB_BEHAVIOR_FALLBACK)


_KWOK_IMPLEMENTATION_CONSTRAINTS = (
    "## Implementation constraints\n\n"
    "- Your submission may be written in any language available in the image.\n"
    "  Use only what the image already provides; no additional packages may be\n"
    "  fetched.\n"
    "- Do NOT shell out to the real `kubectl` binary from inside your program.\n"
    "- The kwok cluster exposes a standard Kubernetes REST API on the endpoint\n"
    "  configured in `$KUBECONFIG`. Use any client library idiomatic for your\n"
    "  language, or speak the Kubernetes REST API directly.\n"
    "- Read `KUBECONFIG` from the environment; the runtime configures it to point\n"
    "  at a sandboxed kwok cluster. Do NOT override the apiserver endpoint,\n"
    "  credentials, or context in code.\n"
    "- Success messages go to **stdout**; errors go to **stderr**. Do NOT mix them.\n"
    "- Exit codes are STRICT and must match real kubectl semantics. The\n"
    "  test-enforced set is `{0, 1, 2}`; signal codes `{130, 137, 143}`\n"
    "  are runtime-inherited and MUST NOT be produced deliberately:\n"
    "  - `0` on success.\n"
    "  - `1` on any apiserver-shaped API error (404 `NotFound`,\n"
    "    409 `Conflict`, 409 `AlreadyExists`, 422 `Invalid`,\n"
    "    401 `Unauthorized`, 403 `Forbidden`, 405 `MethodNotAllowed`,\n"
    "    410 `Gone`, 413 `RequestEntityTooLarge`, 415\n"
    "    `UnsupportedMediaType`, 429 `TooManyRequests`, 500\n"
    "    `InternalError`, 503 `ServiceUnavailable`, `Timeout`,\n"
    "    `ServerTimeout`), on TCP-level cluster-unreachable failures\n"
    "    (DNS, connection refused, TLS mismatch, read timeout), and on\n"
    "    kubeconfig / configuration errors (unreadable `KUBECONFIG`,\n"
    "    missing current-context, unresolvable cluster server URL).\n"
    "  - `2` on cobra / argparse usage errors: unknown flag, missing\n"
    "    required positional, extra positional, malformed flag value,\n"
    "    invalid subcommand, mutually-exclusive flag combination,\n"
    "    invalid `-o` / `--output` format selector, invalid\n"
    "    `--replicas` / `--port` numeric value, invalid `--patch-type`\n"
    "    selector, missing required `--all` when no name is given,\n"
    "    invalid label syntax that fails client-side parsing.\n"
    "  - `130` on `SIGINT` (`Ctrl+C`); `137` on `SIGKILL` (typically\n"
    "    OOM); `143` on `SIGTERM`. Runtime-inherited only.\n"
    "  Tests enforce the SPECIFIC code — `returncode == 1` for\n"
    "  apiserver / configuration errors and `returncode == 2` for\n"
    "  usage errors. Returning the wrong non-zero code will fail\n"
    "  verification.\n"
    "- Do NOT surface raw runtime tracebacks or internal error dumps; print a\n"
    "  brief user-facing error string that names the failure class instead\n"
    "  (for example, `NotFound (404)` or `Invalid: ...`).\n"
    "- Do NOT fabricate flags that don't exist upstream. In particular,\n"
    "  `kubectl apply` has NO `--wait-for` flag (only `--wait`).\n"
    "- Do NOT validate resource names client-side; the apiserver rejects\n"
    "  DNS-1123-invalid names with `Invalid`. Defer to the server.\n"
    "- Do NOT implement or delegate to the unsupported verbs `logs`, `exec`,\n"
    "  `port-forward`, `attach`, `top`, `cp` — kwok returns synthetic data for\n"
    "  these and no test will exercise them.\n"
    "- Your submission must be an executable at `/workspace/submission/kubectl`\n"
    "  (any language — shebang script or compiled binary). The image provides\n"
    "  `/workspace/submission/` first on `$PATH`, so the executable shadows the\n"
    "  real `/usr/local/bin/kubectl` for the test harness.\n"
)


_KWOK_OUTPUT_CONTRACT = (
    "## Output contract\n\n"
    "A correct implementation produces output in the *shape* described below,\n"
    "names the *class* of any error reported, uses the documented exit-code set,\n"
    "and never surfaces a runtime stack trace. Specific verbs, error codes, and\n"
    "the exact wording of any message are deliberately not enumerated here:\n"
    "derive them from the underlying Kubernetes API semantics and standard\n"
    "`kubectl` conventions.\n\n"
    "### stdout (success path)\n\n"
    "- A successful mutation writes one line per affected resource. `create`,\n"
    "  `apply`, `patch`, `scale`, `label`, `annotate`, `rollout` use the shape\n"
    "  `<kind>/<name> <verb-past-tense>` (for example, `pod/foo created`,\n"
    "  `deployment.apps/bar scaled`). `delete` uses a DIFFERENT shape:\n"
    '  `<kind> "<name>" deleted` (for example, `namespace "baz" deleted`,\n'
    '  `pod "foo" deleted`). The `<kind>` fragment may be short (`pod`) or\n'
    "  qualified (`deployment.apps`); both are acceptable to the tests.\n"
    "- `kubectl get` (default output) writes a human-readable table with a header\n"
    "  row and one line per resource. `-o json` / `-o yaml` write a\n"
    "  machine-parseable document.\n"
    "- `kubectl describe` writes a multi-section report (section headers end\n"
    "  with `:` — `Name:`, `Namespace:`, `Labels:`, `Annotations:`, `Status:`,\n"
    "  `Events:`).\n"
    "- Implementations MAY emit informational progress lines BEFORE the success\n"
    '  line (for example, `Waiting for deployment "foo" rollout to finish...`).\n'
    "  Conformance is checked by looking for the success line anywhere in stdout,\n"
    "  not as the first line.\n"
    "- stderr is empty on success.\n\n"
    "### stderr (failure path)\n\n"
    "- stdout is empty on failure.\n"
    "- A human-readable error line is written to stderr that identifies the\n"
    "  failure *class*. Any of the following shapes is acceptable:\n"
    "  - the underlying apiserver error envelope surfaced as\n"
    "    `<reason> (<status>)` (for example, `NotFound (404)`,\n"
    "    `AlreadyExists (409)`, `Invalid (422)`)\n"
    "  - a bare `<reason>: <message>` line naming the apiserver error reason\n"
    "    (`NotFound`, `AlreadyExists`, `Invalid`, `Forbidden`, `Conflict`,\n"
    "    `Timeout`)\n"
    "  - a client-side usage-error line whose prefix names the failure class\n"
    "    (for example, `Error: unknown flag: --nope`, `error: resource(s) were\n"
    '    not provided`, `invalid argument "..."`)\n'
    "- Tests match the failure *class* against one of these shapes — not\n"
    "  verbatim wording — so any spec-compliant phrasing is accepted.\n"
    "- No runtime stack trace is emitted under any condition.\n\n"
    "### Exit codes\n\n"
    "The test-enforced exit-code set is `{0, 1, 2}`; process signals may\n"
    "surface as `{130, 137, 143}` and MUST NOT be produced deliberately:\n\n"
    "- `0` — success.\n"
    "- `1` — apiserver / API error surfaced from an `ApiException` or the\n"
    "  underlying REST client. All of the following apiserver reasons map\n"
    "  to exit `1`: `NotFound`, `AlreadyExists`, `Invalid`, `Forbidden`,\n"
    "  `Unauthorized`, `Conflict`, `Timeout`, `ServerTimeout`,\n"
    "  `TooManyRequests`, `InternalError`, `ServiceUnavailable`,\n"
    "  `MethodNotAllowed`, `UnsupportedMediaType`, `Gone`,\n"
    "  `RequestEntityTooLarge`. TCP-level cluster-unreachable failures\n"
    "  (DNS, connection refused, TLS mismatch, read timeout) also exit\n"
    "  `1`. Kubeconfig / configuration errors (unreadable `KUBECONFIG`,\n"
    "  missing current-context, unresolvable cluster server URL) also\n"
    "  exit `1`.\n"
    "- `2` — cobra / argparse usage error: unknown flag, missing or extra\n"
    "  positional argument, malformed flag value, invalid subcommand,\n"
    "  mutually-exclusive flag combination, invalid `-o` / `--output`\n"
    "  format selector, invalid `--replicas` / `--port` numeric value,\n"
    "  invalid `--patch-type` selector, missing required `--all` when no\n"
    "  name is given, invalid label syntax that fails client-side parsing.\n"
    "- `130` — process interrupted by `SIGINT` (`Ctrl+C`); inherited from\n"
    "  the runtime, do NOT emit deliberately.\n"
    "- `137` — process killed by `SIGKILL` (typically OOM); inherited from\n"
    "  the runtime, do NOT emit deliberately.\n"
    "- `143` — process terminated by `SIGTERM`; inherited from the runtime,\n"
    "  do NOT emit deliberately.\n\n"
    "Tests must produce the SPECIFIC exit code for each modeled error class —\n"
    "`returncode == 1` for apiserver / configuration errors and\n"
    "`returncode == 2` for usage errors. Returning the wrong non-zero code\n"
    "fails verification.\n"
)


def _build_instruction_md_kwok(
    spec: CliSpec, cmd_spec: CommandSpec, intents: list[TestIntent]
) -> str:
    """Render the kwok/kubectl agent-facing instruction.md at raiden parity.

    Structure mirrors ``_build_instruction_md`` (the AWS variant) but authors
    every prose block in kubectl terms: verbs (`get`, `apply`, `delete`, ...)
    over resources (pods, deployments, ...), the kubernetes-python-client
    surface, and the apiserver-shaped error envelope. Built ONLY from CliSpec
    + extracted intents + the hand-authored ``_KUBECTL_VERB_BEHAVIOR`` map —
    never reads test bodies. ``_assert_no_test_leakage`` is the safety net.
    """
    from repo2rlenv.pipelines._cli_app_backends import get_backend
    from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import _REAL_KUBECTL_FLAGS

    kwok = get_backend("kwok")
    flags = _extract_flags_from_intents(intents)
    verb = cmd_spec.name
    kinds = list(spec.declared_kinds or [])
    kinds_csv = ", ".join(kinds) if kinds else ""
    kinds_phrase = (
        f"the {len(kinds)} Kubernetes kinds under test ({kinds_csv})"
        if kinds
        else "the resource kinds under test"
    )

    parts: list[str] = []

    if kinds:
        parts.append(
            f"# Build `kubectl {verb}` from scratch "
            f"(covering {len(kinds)} kinds: {kinds_csv})\n"
        )
    else:
        parts.append(f"# Build `kubectl {verb}` from scratch\n")
    parts.append(
        "## Application overview\n\n"
        f"You are implementing the real kubectl `{verb}` verb. Real kubectl is\n"
        "**verb-first** — the invocation shape is `kubectl VERB [TYPE] [NAME] [flags]`.\n"
        "There is no `kubectl <resource> <verb>` subcommand form; `kubectl pods apply` DOES NOT\n"
        f"EXIST. This task's tests exercise {kinds_phrase}, entering the CLI\n"
        "either via the manifest's `kind:` field (for `apply`/`create -f`) or as\n"
        "the TYPE positional after the verb (for\n"
        "`get`/`delete`/`describe`/`patch`/`scale`/`label`).\n\n"
        "The agent is given **no source code**, only this specification. Your\n"
        "implementation is an executable at `/workspace/submission/kubectl`,\n"
        "invoked as a subprocess:\n\n"
        "```bash\n"
        f"/workspace/submission/kubectl {verb} [TYPE] [NAME] [flags...]\n"
        "```\n\n"
        "Any executable format works — shebang script or compiled binary. The\n"
        "runtime image ships toolchains for a range of general-purpose\n"
        "languages; use whichever you prefer, with any client library idiomatic\n"
        "for that language.\n\n"
        "Make sure the file is executable (`chmod +x`). The runtime configures\n"
        "`KUBECONFIG` in the environment to point at a sandboxed kwok cluster\n"
        "(lightweight apiserver + etcd-backed storage simulating Kubernetes\n"
        "control-plane semantics faithfully). Read `KUBECONFIG` from the\n"
        "environment; do NOT hard-code endpoints. Treat the backend as real\n"
        "Kubernetes, and keep state consistent across verbs so a sequence like\n"
        "create -> get -> patch -> scale -> delete behaves correctly end-to-end.\n"
    )

    if kinds:
        parts.append(f"## Verb: `kubectl {verb}` (across {len(kinds)} kinds: {kinds_csv})\n")
    else:
        parts.append(f"## Verb: `kubectl {verb}`\n")

    parts.append("### Interface\n\nObserved argv patterns (after invoking `submission/kubectl`):\n")
    seen_shapes: set[str] = set()
    for intent in intents:
        if _is_internal_mutation_intent(intent):
            continue
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen_shapes:
            seen_shapes.add(shape)
            parts.append(f"- `{shape}`")
    parts.append("")

    real_flags = _REAL_KUBECTL_FLAGS.get(verb, ())
    if flags or real_flags:
        parts.append("### Flags\n")
        parts.append(
            "Real kubectl v1.31 flags for this verb (support all of them; the "
            "reference test suite exercises a subset):\n"
        )
        parts.append("| Flag | Example value |")
        parts.append("|---|---|")
        seen_keys: set[str] = set()
        for f, v in sorted(flags.items()):
            seen_keys.add(f)
            parts.append(f"| `{f}` | `{v}` |" if v else f"| `{f}` | _(boolean)_ |")
        for real in real_flags:
            key = real.split("/", 1)[0].split("=", 1)[0].strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            parts.append(f"| `{real}` | _(v1.31)_ |")
        parts.append("")

    parts.append("### Behavior\n")
    for bullet in _kwok_verb_behavior_bullets(cmd_spec.name):
        parts.append(f"- {bullet}")
    parts.append("")

    parts.append("### State expectations (kwok cluster is real apiserver state)\n")
    parts.append(kwok.cross_command_invariants([cmd_spec.name]))

    examples = _render_examples(intents, verb, invocation="/workspace/submission/kubectl")
    if examples:
        parts.append("### Examples\n")
        parts.append("```bash")
        parts.extend(examples)
        parts.append("```\n")

    parts.append(_KWOK_IMPLEMENTATION_CONSTRAINTS)
    parts.append(_KWOK_OUTPUT_CONTRACT)

    return "\n".join(parts) + "\n"


def _build_subset_instruction_md_kwok(
    spec: CliSpec, cmd_specs: list[CommandSpec], intents: list[TestIntent]
) -> str:
    """Render the kwok/kubectl multi-verb subset instruction.md at raiden parity.

    One `## Command: kubectl <prefix> <verb>` section per verb (Interface +
    Flags + Behavior), followed by cross-command state invariants and the
    shared implementation + output contract. Mirrors the shape of
    ``_build_subset_instruction_md`` (the AWS variant).
    """
    from repo2rlenv.pipelines._cli_app_backends import get_backend

    kwok = get_backend("kwok")
    kinds = list(spec.declared_kinds or [])
    names = sorted(c.name for c in cmd_specs)
    label_list = ", ".join(f"`kubectl {n}`" for n in names)
    kinds_csv = ", ".join(kinds) if kinds else ""
    kinds_phrase = (
        f"the {len(kinds)} Kubernetes kinds under test ({kinds_csv})"
        if kinds
        else "the resource kinds under test"
    )

    parts: list[str] = []

    if kinds:
        parts.append(
            f"# Build a `kubectl` CLI (verbs: {', '.join(names)}; "
            f"covering {len(kinds)} kinds: {kinds_csv})\n"
        )
    else:
        parts.append(f"# Build a `kubectl` CLI (verbs: {', '.join(names)})\n")
    parts.append(
        "## Application overview\n\n"
        "You are implementing a subset of real kubectl verbs:\n"
        f"{label_list}. Real kubectl is **verb-first** — the invocation shape is\n"
        "`kubectl VERB [TYPE] [NAME] [flags]`. There is no\n"
        "`kubectl <resource> <verb>` subcommand form; `kubectl pods apply` DOES NOT\n"
        f"EXIST. Your implementation must support every declared verb on every\n"
        f"declared kind: this task exercises {kinds_phrase}, entering the CLI\n"
        "either via the manifest's `kind:` field (for `apply`/`create -f`) or as\n"
        "the TYPE positional after the verb (for\n"
        "`get`/`delete`/`describe`/`patch`/`scale`/`label`).\n\n"
        "The agent is given **no source code**, only this specification. Your\n"
        "implementation is an executable at `/workspace/submission/kubectl`,\n"
        "invoked as a subprocess:\n\n"
        "```bash\n"
        "/workspace/submission/kubectl <verb> [TYPE] [NAME] [flags...]\n"
        "```\n\n"
        "Dispatch on argv[1] (the verb: `apply`, `get`, `delete`, `describe`,\n"
        "`patch`, `scale`, `label`, `create`) so one program handles every verb\n"
        "above.\n\n"
        "Any executable format works — shebang script or compiled binary. The\n"
        "runtime image ships toolchains for a range of general-purpose\n"
        "languages; use whichever you prefer, with any client library idiomatic\n"
        "for that language.\n\n"
        "Make sure the file is executable (`chmod +x`). The runtime configures\n"
        "`KUBECONFIG` in the environment to point at a sandboxed kwok cluster\n"
        "(lightweight apiserver + etcd-backed storage simulating Kubernetes\n"
        "control-plane semantics faithfully). Read `KUBECONFIG` from the\n"
        "environment; do NOT hard-code endpoints. Treat the backend as real\n"
        "Kubernetes, and keep state consistent across verbs so a sequence like\n"
        "create -> get -> patch -> scale -> delete behaves correctly end-to-end.\n"
    )

    parts.append("## Verbs\n")
    by_cmd: dict[str, list[TestIntent]] = {}
    for i in intents:
        by_cmd.setdefault(i.command, []).append(i)
    for c in sorted(cmd_specs, key=lambda c: c.name):
        parts.extend(_kwok_command_section_parts(spec, c, by_cmd.get(c.name, [])))

    parts.append("## Cross-command behaviour (state must stay consistent)\n")
    parts.append(kwok.cross_command_invariants(names))
    parts.append(
        "State must remain consistent across the verb set:\n\n"
        "- The kwok apiserver persists every mutation to etcd via kine, so the\n"
        "  effect of any successful mutation MUST be immediately observable via\n"
        "  the corresponding read verb (`get`, `describe`) or client method\n"
        "  (`read_<kind>`, `list_<kind>`).\n"
        "- After `create <kind> <name>` (or `apply -f manifest.yaml`), a follow-up\n"
        "  `get <kind> <name>` returns the resource; `read_<kind>` on the same\n"
        "  name succeeds. `apply` is idempotent — re-applying the same manifest\n"
        "  is a no-op with respect to spec fields.\n"
        "- After `delete <kind> <name>`, the resource disappears from\n"
        "  `list_<kind>` and `read_<kind>` raises `ApiException` with\n"
        "  `.status == 404`. Deleting the same name a second time FAILS with\n"
        "  `NotFound` (unlike some AWS delete APIs, kubectl delete is NOT\n"
        "  idempotent by default).\n"
        "- After `patch <kind>/<name>` or `label <kind>/<name>`, `read_<kind>`\n"
        "  reflects the mutated fields; unmodified fields keep their prior value\n"
        "  (strategic-merge semantics for built-in kinds).\n"
        "- After `scale <workload>/<name> --replicas=N`, "
        "`read_<workload>(name)` returns\n"
        "  `.spec.replicas == N`.\n"
        "- Read verbs (`get`, `describe`) never mutate state; two consecutive\n"
        "  reads over an unchanged cluster return the same set of names\n"
        "  (order-independent).\n"
    )

    parts.append(_KWOK_IMPLEMENTATION_CONSTRAINTS)
    parts.append(_KWOK_OUTPUT_CONTRACT)

    return "\n".join(parts) + "\n"


def _kwok_command_section_parts(
    spec: CliSpec, cmd_spec: CommandSpec, intents: list[TestIntent]
) -> list[str]:
    """Compact per-verb spec section for a kwok subset instruction.md.

    Emits `### Command: kubectl <prefix> <verb>` with Interface + Flags +
    Behavior sub-sections, mirroring the aws `_command_section_parts` shape
    but scoped to kubectl semantics.
    """
    verb = cmd_spec.name
    kinds = list(spec.declared_kinds or [])
    if kinds:
        header = f"### Verb: `kubectl {verb}` (across {len(kinds)} kinds: {', '.join(kinds)})\n"
    else:
        header = f"### Verb: `kubectl {verb}`\n"
    parts: list[str] = [header]

    shapes: list[str] = []
    seen: set[str] = set()
    for intent in intents:
        if _is_internal_mutation_intent(intent):
            continue
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen:
            seen.add(shape)
            shapes.append(f"- `{shape}`")
    if shapes:
        parts.append("**Interface — observed argv patterns:**\n")
        parts.extend(shapes)
        parts.append("")

    from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import _REAL_KUBECTL_FLAGS

    non_mutation_intents = [i for i in intents if not _is_internal_mutation_intent(i)]
    observed_flags = _extract_flags_from_intents(non_mutation_intents)
    documented_flags = set(cmd_spec.flags or [])
    flags_union = set(observed_flags.keys()) | documented_flags
    real_flags = _REAL_KUBECTL_FLAGS.get(verb, ())
    if flags_union or real_flags:
        parts.append("**Flags (real kubectl v1.31 — support all):**\n")
        parts.append("| Flag | Example value |")
        parts.append("|---|---|")
        seen_keys: set[str] = set()
        for f in sorted(flags_union):
            seen_keys.add(f)
            v = observed_flags.get(f)
            parts.append(f"| `{f}` | `{v}` |" if v else f"| `{f}` | _(boolean)_ |")
        for real in real_flags:
            key = real.split("/", 1)[0].split("=", 1)[0].strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            parts.append(f"| `{real}` | _(v1.31)_ |")
        parts.append("")

    parts.append("**Behavior:**\n")
    for bullet in _kwok_verb_behavior_bullets(cmd_spec.name):
        parts.append(f"- {bullet}")
    parts.append("")

    by_tag = _group_by_tag(intents)
    error_intents: list[TestIntent] = []
    for tag in ("error", "error_nonexistent", "error_invalid_args"):
        error_intents.extend(by_tag.get(tag, []))
    if error_intents:
        parts.append("**Error cases observed:**\n")
        seen_errors: set[tuple[str, int]] = set()
        for intent in error_intents:
            if _is_internal_mutation_intent(intent):
                continue
            shape = _argv_shape(intent.cmdline_template) or "<argv>"
            key = (shape, intent.expected_exit)
            if key in seen_errors:
                continue
            seen_errors.add(key)
            parts.append(f"- `{shape}` -> exit `{intent.expected_exit}`")
        parts.append("")

    return parts


def _resolve_source_name(options: CodeInstructOptions) -> str:
    if getattr(options, "cli_app_backend", "minio") == "kwok":
        return "kubectl_cobra_yaml"
    if options.cli_app_extract_mode == "botocore_model":
        return "aws_botocore"
    return "aws_tests"


def _kwok_profile_build_dockerfile(**kwargs) -> str:
    from repo2rlenv.pipelines._cli_app_backends import get_backend

    base_image = kwargs.get("base_image")
    golden = kwargs.get("golden", False)
    golden_deps = kwargs.get("golden_deps") or ()
    kwok = get_backend("kwok")
    if golden:
        return kwok.dockerfile_golden_layer(tuple(golden_deps))
    return kwok.dockerfile_base(base_image)


def _kwok_profile_build_conftest(**kwargs) -> str:
    from repo2rlenv.pipelines._cli_app_backends import get_backend

    return get_backend("kwok").build_conftest(golden=kwargs.get("golden", False))


def _register_kwok_profile() -> None:
    from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import KwokSimulationBackend

    register_profile(
        ServiceProfile(
            backend_key="kwok",
            service="kubectl",
            simulation_backend="kwok",
            extract_mode="tests",
            base_image=KwokSimulationBackend.pinned_base_image,
            pinned_deps=KwokSimulationBackend.pinned_deps,
            translation_system=KwokSimulationBackend.prompts.translation_system,
            translation_user=KwokSimulationBackend.prompts.translation_user_template,
            oracle_system=KwokSimulationBackend.prompts.oracle_single_system,
            oracle_user=KwokSimulationBackend.prompts.oracle_single_user_template,
            oracle_subset_system=KwokSimulationBackend.prompts.oracle_subset_system,
            oracle_subset_user=KwokSimulationBackend.prompts.oracle_subset_user_template,
            workflow_system=KwokSimulationBackend.prompts.workflow_system,
            workflow_user=KwokSimulationBackend.prompts.workflow_user_template,
            build_conftest=_kwok_profile_build_conftest,
            build_dockerfile=_kwok_profile_build_dockerfile,
            build_instruction_single=_build_instruction_md_kwok,
            build_instruction_subset=_build_subset_instruction_md_kwok,
            reference_label="kubectl-reference-shim",
            reference_version_key="kubectl_version",
            reference_version_value="1.31.0",
        )
    )


_register_kwok_profile()
