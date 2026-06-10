"""LLM prompts + pinned versions for the cli_app synthesis pipeline.

Pure data module. Imported by _cli_app_synthesis and _cli_app_llm.
"""

from __future__ import annotations

PROMPT_TEMPLATE_VERSION = "v1.1.0-primed"


PINNED_DEPS = (
    "boto3==1.34.150",
    "botocore==1.34.150",
    "moto[s3,server]==5.0.16",
    "pytest==8.3.3",
    "freezegun==1.5.1",
    "werkzeug==3.0.4",
    "flask==3.0.3",
)
PINNED_PYTHON = "3.11-slim"


TRANSLATION_SYSTEM = """You translate aws-cli white-box tests into black-box pytest tests.

The reference test exercises an aws-cli command via the in-process driver and \
asserts on boto3 operations. Treat it as a STYLE and INTENT reference only — \
write a clean black-box pytest function from scratch that produces the same \
observable behaviour. Your output must:

1. Use @mock_aws decorator (function scope, from `moto`)
2. Invoke the candidate CLI as a subprocess via the `cli` fixture (defined \
in conftest.py) which returns a `subprocess.CompletedProcess` (stdout/stderr/returncode)
3. Assert on returncode AND on observable side effects (S3 state via the \
`s3_client` fixture, or stdout content)
4. Have AT LEAST one non-trivial STATE assertion: either query s3_client for
   bucket/object existence/contents, OR assert on a specific stderr/stdout
   substring tied to the command's documented output format. A bare
   `assert result.returncode == 0` with no state check is REJECTED — such
   tests pass against an empty stub that just exits 0 (non-discriminative).
5. For happy_path tests: set up the prereq state explicitly inside the test
   (e.g. `s3_client.create_bucket(Bucket='x')` before testing `rb`).
   The test must be runnable in isolation — do NOT assume other tests ran.

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
- Expected boto3 operations: {expected_state_calls}
- Behaviour tag: {behaviour_tag}

Translate this into a black-box pytest test. The agent's CLI is at \
/workspace/submission/main.py. Use `cli(*argv)` to invoke it (returns \
CompletedProcess). Use `s3_client` (a boto3 S3 client pointing at moto) to \
verify state."""


ORACLE_SYSTEM = """You write a reference Python implementation of a single aws-cli S3 command.

Constraints:
- Single file: `submission/main.py`
- Use argparse for argument parsing
- Use boto3 with the default endpoint (moto intercepts via AWS_ENDPOINT_URL_S3 env var)
- Do NOT import `awscli` or shell out to the `aws` binary
- Exit 0 on success, non-zero on failure
- Match real aws-cli output format on stdout (e.g. `make_bucket: <name>` for mb, \
`delete: s3://<bucket>/<key>` for rm, etc.)
- Print errors to stderr, suppress noisy boto3 tracebacks (use `botocore.exceptions.ClientError`)

The CLI is invoked as: `python submission/main.py <prefix> <command> [args...]`

Return ONLY the Python source for `submission/main.py` (no preamble, no surrounding markdown fences)."""


ORACLE_USER_TEMPLATE = """Implement `aws {command_prefix} {command}` covering these behaviours:

{behaviours_bulleted}

The implementation should be self-contained and dispatch on argv[1] / argv[2] \
so a single `main.py` can handle multiple commands when extended later. For now, \
focus on the `{command}` subcommand."""


ORACLE_SUBSET_SYSTEM = """You write a reference Python implementation of a SUBSET of \
aws-cli S3 commands as ONE file.

Constraints:
- Single file: `submission/main.py`
- Parse argv and dispatch on the subcommand (argv[2]) so one program handles \
every requested subcommand
- Use boto3 with the default endpoint (moto intercepts via AWS_ENDPOINT_URL_S3 env var)
- Do NOT import `awscli` or shell out to the `aws` binary
- Exit 0 on success, non-zero on failure
- Match real aws-cli output format on stdout (e.g. `make_bucket: <name>` for mb, \
`delete: s3://<bucket>/<key>` for rm, `upload: <src> to <dst>` for cp, etc.)
- Print errors to stderr, suppress noisy boto3 tracebacks (use `botocore.exceptions.ClientError`)
- Keep S3 state consistent across subcommands so a sequence like upload -> list -> \
download -> remove behaves correctly end-to-end

The CLI is invoked as: `python submission/main.py <prefix> <command> [args...]`

Return ONLY the Python source for `submission/main.py` (no preamble, no surrounding markdown fences)."""


ORACLE_SUBSET_USER_TEMPLATE = """Implement a single `aws {command_prefix}` CLI supporting \
ALL of these subcommands: {commands_csv}.

It must cover these behaviours (collected across the subcommands):

{behaviours_bulleted}

Dispatch on argv[1] (prefix) / argv[2] (subcommand) so one `main.py` handles every \
listed subcommand, and keep S3 state consistent across them so cross-command workflows \
(upload -> list -> download -> move -> remove -> remove-bucket) behave correctly."""


WORKFLOW_SYSTEM = """You write black-box pytest tests that exercise CROSS-COMMAND \
behaviour of a from-scratch `aws s3`-style CLI.

The CLI is a single file at /workspace/submission/main.py, invoked as a subprocess via \
the `cli` fixture: `cli(*argv) -> subprocess.CompletedProcess` (with .returncode, \
.stdout, .stderr). A boto3 client `s3_client` (pointing at the SAME sandboxed S3) and \
pytest's `tmp_path` are also available as fixtures.

Rules:
1. Use ONLY the fixtures `cli`, `s3_client`, `tmp_path` as test-function arguments. Do \
NOT use any decorator. You may use the standard library plus `boto3`/`botocore` \
(assume both are importable).
2. Create ALL prerequisite state inside the test (buckets via the CLI or \
`s3_client.create_bucket`, local files via `tmp_path`). Tests must run in isolation and \
in any order.
3. After EVERY `cli(...)` step meant to succeed, assert `result.returncode == 0`. For \
steps meant to fail, assert `result.returncode != 0` AND a stderr substring.
4. Assert cross-command invariants on `s3_client` STATE, not on stdout wording: object \
presence via `list_objects_v2`/`head_object`; byte-identical content via \
`get_object()['Body'].read()`; deletion by expecting a `botocore.exceptions.ClientError` \
(error code '404' or 'NoSuchKey') from `head_object`; bucket presence/absence via \
`list_buckets`.
5. Each test MUST chain at least TWO different subcommands and include at least one \
assertion that depends on a PRIOR command's effect.
6. Assert only on order-insensitive state (sets of keys, object bytes, bucket existence, \
exit codes) — never on listing order, ETags, or timestamps.
7. Name each function `test_workflow_<chain>`. Return ONLY the test function source(s) \
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
