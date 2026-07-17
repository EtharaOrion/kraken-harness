"""Generic sidecar service card: the plug-and-play path for model-derived ``aws <service>``.

Additive by design. The ``dynamodb_local`` and ``minio`` paths in ``_cli_app_synthesis``
are untouched: this module supplies, for any *new* AWS service, the same artifacts the
DynamoDB profile hand-rolls -- a compose-sidecar conftest (raw-HTTP stdlib client, zero
boto3/botocore/moto/minio fingerprint), a sidecar Dockerfile, a docker-compose overlay,
and the LLM prompt set -- but parameterised by a :class:`SidecarSpec` instead of hardcoded
DynamoDB. Registering a new service is one :class:`SidecarSpec` + one ``register_profile``
call; the synthesis engine core is not edited.

Dependency direction: leaf-adjacent. It imports the network blocklist from
``emitter.harbor`` and the :class:`ServiceProfile` registry card from the leaf
``_cli_app_profiles`` -- never ``_cli_app_synthesis`` -- so the engine imports this at
registration time without a cycle.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass

from repo2rlenv.emitter.harbor import BLOCKED_HOSTS, BLOCKED_SUFFIXES
from repo2rlenv.pipelines._cli_app_profiles import ServiceProfile

# OpenHands agent SDK pins baked into every generic sidecar task env so it is
# OpenHands/Harbor-runnable, matching the DynamoDB/S3 baseline builder. MUST stay
# equal to the same-named pins in _cli_app_synthesis (the DDB/minio builder).
PINNED_OPENHANDS_VERSION = "v1.12.0"
PINNED_FASTAPI_VERSION = "0.138.2"
PINNED_GCP_AIPLATFORM_VERSION = "1.158.0"


@dataclass(frozen=True)
class SidecarSpec:
    """Per-service inputs the generic builders + prompts specialise on.

    A model-derived backend runs its fake AWS service as a compose *sidecar* next to
    ``main`` (the ``amazon/dynamodb-local`` pattern), reached over the docker network at
    ``http://{sidecar_service}:{sidecar_port}``. ``validate()`` runs at registration so a
    malformed card fails loudly rather than shipping a broken task.
    """

    backend_key: str
    service: str
    simulation_backend: str
    target_prefix: str
    json_version: str
    endpoint_env: str
    signing_service: str
    fixture_name: str
    sidecar_service: str
    sidecar_image: str
    sidecar_port: int
    ready_action: str
    reset_py: str
    wire_rules: str
    oracle_rules: str
    base_image: str
    pinned_deps: tuple[str, ...]
    default_target_ops: tuple[str, ...] = ()
    sidecar_command: tuple[str, ...] = ()
    sidecar_entrypoint: tuple[str, ...] = ()
    sidecar_env: tuple[str, ...] = ()
    sidecar_healthcheck: str | None = None

    def sidecar_endpoint(self) -> str:
        return f"http://{self.sidecar_service}:{self.sidecar_port}"

    def validate(self) -> None:
        """Fail-fast structural check; raises ValueError naming the offending field."""
        required = {
            "backend_key": self.backend_key,
            "service": self.service,
            "simulation_backend": self.simulation_backend,
            "target_prefix": self.target_prefix,
            "endpoint_env": self.endpoint_env,
            "signing_service": self.signing_service,
            "fixture_name": self.fixture_name,
            "sidecar_service": self.sidecar_service,
            "sidecar_image": self.sidecar_image,
            "ready_action": self.ready_action,
            "wire_rules": self.wire_rules,
            "oracle_rules": self.oracle_rules,
            "base_image": self.base_image,
        }
        for field_name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"SidecarSpec({self.backend_key!r}): {field_name!r} must be a non-empty string"
                )
        if self.json_version not in ("1.0", "1.1"):
            raise ValueError(
                f"SidecarSpec({self.backend_key!r}): json_version must be '1.0' or '1.1', "
                f"got {self.json_version!r}"
            )
        if not isinstance(self.sidecar_port, int) or not (0 < self.sidecar_port < 65536):
            raise ValueError(
                f"SidecarSpec({self.backend_key!r}): sidecar_port must be 1..65535, "
                f"got {self.sidecar_port!r}"
            )
        if not self.pinned_deps:
            raise ValueError(f"SidecarSpec({self.backend_key!r}): pinned_deps must be non-empty")
        try:
            ast.parse(self.reset_py)
        except SyntaxError as exc:
            raise ValueError(
                f"SidecarSpec({self.backend_key!r}): reset_py is not valid Python ({exc})"
            ) from exc


# --------------------------------------------------------------------------- #
# Verifier Dockerfile (sidecar model — the fake backend is NOT baked in)
# --------------------------------------------------------------------------- #
def build_dockerfile_generic(
    spec: SidecarSpec,
    *,
    base_image: str | None = None,
    bake_tests: bool = False,
    golden: bool = False,
    golden_deps: tuple[str, ...] | None = None,
) -> str:
    """``main`` image for a generic backend: FROM the service base + the OpenHands agent SDK
    venv + the submission scaffold + git baseline, matching the DynamoDB/S3 baseline builder.
    The backend is reached at ``AWS_ENDPOINT_URL=http://{sidecar_service}:{sidecar_port}`` (a
    compose sidecar, see :func:`build_sidecar_compose_generic`); nothing AWS-SDK is installed
    (raw-HTTP client), so the image carries zero boto3/botocore/moto fingerprint. The service
    base image already ships the aws-cli runtime deps + pytest, so ``golden``/``golden_deps``
    are accepted for signature compatibility but no longer add a pip dependency layer.
    """
    resolved_base = base_image or spec.base_image
    copy_tests = "COPY tests/ /workspace/tests/\n" if bake_tests else ""
    return (
        "# syntax=docker/dockerfile:1\n"
        f"# Task environment for aws {spec.service} ({spec.backend_key} backend, compose sidecar).\n"
        f"ARG BASE_IMAGE={resolved_base}\n"
        "FROM ${BASE_IMAGE}\n"
        "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \\\n"
        "    PYTHONHASHSEED=0 TZ=UTC LC_ALL=C.UTF-8 \\\n"
        "    AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy \\\n"
        "    AWS_DEFAULT_REGION=us-east-1 \\\n"
        f"    {spec.endpoint_env}={spec.sidecar_endpoint()} \\\n"
        f"    AWS_ENDPOINT_URL={spec.sidecar_endpoint()}\n"
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
        "RUN mkdir -p /workspace/submission && touch /workspace/submission/.gitkeep\n"
        "ENV PATH=/workspace/submission:$PATH\n"
        "RUN git config --global --add safe.directory /workspace && \\\n"
        "    git init -q /workspace && \\\n"
        "    git -C /workspace config user.email raiden@local && \\\n"
        "    git -C /workspace config user.name raiden && \\\n"
        "    git -C /workspace add -A && \\\n"
        "    git -C /workspace commit -q --allow-empty -m 'raiden: baseline'\n"
    )


# --------------------------------------------------------------------------- #
# Verifier conftest (connects to the sidecar; raw-HTTP client; no SDK)
# --------------------------------------------------------------------------- #
def build_conftest_generic(spec: SidecarSpec, *, golden: bool = False) -> str:
    """Network-isolated conftest that talks to the backend compose sidecar over the docker
    network + a raw-HTTP JSON state client (no SDK) + a ``cli`` fixture running the
    candidate. Generalises ``_build_conftest_ddb`` by the :class:`SidecarSpec`.

    ``golden`` switches the ``cli`` fixture from ``[sys.executable, submission/main.py]``
    (the LLM oracle layout) to ``[submission/aws]`` (the sliced-aws-cli shim), mirroring the
    DynamoDB conftest so the reference-grounding gauntlet executes the submission.
    """
    suffixes_literal = ", ".join(repr(s) for s in BLOCKED_SUFFIXES)
    cli_prefix = (
        '"/workspace/submission/aws"'
        if golden
        else 'sys.executable, "/workspace/submission/main.py"'
    )
    cli_check_path = "/workspace/submission/aws" if golden else "/workspace/submission/main.py"
    template = r'''"""Test fixtures for the aws __SERVICE__ CLI task (__BACKEND__ backend, compose sidecar).

The __SERVICE__ backend runs as a compose SIDECAR (service "__SIDECAR_SVC__"), reached over
the docker network at __SIDECAR_ENDPOINT__ (also exported as AWS_ENDPOINT_URL). The agent
submission runs as a subprocess; both it and the test reach the same sidecar via
__ENDPOINT_ENV__ (+ dummy AWS_* creds). Grading client is stdlib raw HTTP
(JSON __JSONV__, X-Amz-Target __TARGET__) — no AWS SDK.
"""

import ipaddress
import json as _json
import os
import socket as _socket
import subprocess
import sys
import time as _time
import urllib.request as _ureq
import urllib.error as _uerr

_ORIG_CONNECT = _socket.socket.connect
_BLOCKED_SUFFIXES = (__BLOCKED__,)


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
                raise RuntimeError(f"network-isolation: connect to public IP {host!r} blocked")
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


def pytest_configure(config):
    if not os.path.exists("__CLI_CHECK_PATH__"):
        pytest.exit(
            "Anti-NOP guard FAILED: submission entrypoint __CLI_CHECK_PATH__ "
            "not found (no submission to evaluate). Reward=0.",
            returncode=1,
        )


_AUTH = (
    "AWS4-HMAC-SHA256 Credential=dummy/20260101/us-east-1/__SIGN__/aws4_request, "
    "SignedHeaders=host;x-amz-date, Signature=dummy"
)


class _Client:
    """Minimal stdlib JSON-protocol client (raw HTTP; the local backend ignores SigV4)."""

    def __init__(self, endpoint):
        self.endpoint = endpoint.rstrip("/") + "/"

    def rpc(self, action, payload=None, timeout=10):
        req = _ureq.Request(
            self.endpoint,
            data=_json.dumps(payload or {}).encode(),
            method="POST",
            headers={
                "Content-Type": "application/x-amz-json-__JSONV__",
                "X-Amz-Target": "__TARGET__." + action,
                "X-Amz-Date": "20260101T000000Z",
                "Authorization": _AUTH,
            },
        )
        with _ureq.urlopen(req, timeout=timeout) as r:
            return _json.loads(r.read() or b"{}")


@pytest.fixture(scope="session")
def _server():
    # The __SERVICE__ backend is a compose sidecar; connect over the docker network
    # (no in-process boot). depends_on/healthcheck may not be honored by every runner,
    # so poll defensively until the sidecar accepts requests (~30s).
    endpoint = os.environ.get("__ENDPOINT_ENV__") or os.environ.get("AWS_ENDPOINT_URL") or "__SIDECAR_ENDPOINT__"
    _c = _Client(endpoint)
    for _ in range(150):
        try:
            _c.rpc("__READY__", {})
            break
        except _uerr.HTTPError:
            break  # server answered (up)
        except OSError:
            _time.sleep(0.2)
    else:
        raise RuntimeError("__SERVICE__ sidecar at " + endpoint + " not reachable within 30s")
    yield endpoint


@pytest.fixture
def __FIXTURE__(_server):
    return _Client(_server)


__RESET_FIXTURE__

@pytest.fixture
def cli(_server):
    def _run(*args, env_overrides=None, timeout=60):
        env = os.environ.copy()
        env["__ENDPOINT_ENV__"] = _server
        env["AWS_ENDPOINT_URL"] = _server
        env.setdefault("AWS_ACCESS_KEY_ID", "dummy")
        env.setdefault("AWS_SECRET_ACCESS_KEY", "dummy")
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
    # Emit the autouse reset fixture only when the profile actually resets state.
    # A no-op reset (e.g. a backend where resources are isolated per-test via unique
    # ids) would otherwise ship a dead fixture that builds an unused client every test.
    if spec.reset_py.strip().startswith("pass"):
        reset_fixture = (
            "# No per-test reset needed for "
            + spec.service
            + " ("
            + spec.reset_py.split("#", 1)[-1].strip()
            + ")."
        )
    else:
        reset_block = spec.reset_py.replace("\n", "\n    ")
        reset_fixture = (
            "@pytest.fixture(autouse=True)\n"
            "def _reset_backend(_server):\n"
            "    _c = _Client(_server)\n"
            f"    {reset_block}\n"
            "    yield"
        )
    return (
        template.replace("__RESET_FIXTURE__", reset_fixture)
        .replace("__BLOCKED__", suffixes_literal)
        .replace("__CLI_PREFIX__", cli_prefix)
        .replace("__CLI_CHECK_PATH__", cli_check_path)
        .replace("__SERVICE__", spec.service)
        .replace("__BACKEND__", spec.backend_key)
        .replace("__JSONV__", spec.json_version)
        .replace("__TARGET__", spec.target_prefix)
        .replace("__SIGN__", spec.signing_service)
        .replace("__ENDPOINT_ENV__", spec.endpoint_env)
        .replace("__READY__", spec.ready_action)
        .replace("__FIXTURE__", spec.fixture_name)
        .replace("__SIDECAR_ENDPOINT__", spec.sidecar_endpoint())
        .replace("__SIDECAR_SVC__", spec.sidecar_service)
    )


# --------------------------------------------------------------------------- #
# Sidecar compose overlay (backend as a service, mirrors amazon/dynamodb-local)
# --------------------------------------------------------------------------- #
def build_sidecar_compose_generic(spec: SidecarSpec) -> str:
    """docker-compose overlay: the backend as a SIDECAR service + ``main`` wired to it.

    Shipped via ``aux_files["environment/docker-compose.yaml"]``, which OVERRIDES the
    default blackhole overlay (the emitter's aux loop runs last). Harbor merges this: it
    ADDS the ``{sidecar_service}`` service and AUGMENTS ``main`` (the endpoint env +
    depends_on + the full blocked-hosts blackhole). ``main``'s image comes from Harbor via
    ``[environment].docker_image``, so it is not set here.
    """
    extra_hosts = "\n".join(f'      - "{h}:0.0.0.0"' for h in BLOCKED_HOSTS)
    lines: list[str] = [
        "services:",
        f"  {spec.sidecar_service}:",
        f"    image: {spec.sidecar_image}",
    ]
    if spec.sidecar_entrypoint:
        ep = ", ".join(f'"{e}"' for e in spec.sidecar_entrypoint)
        lines.append(f"    entrypoint: [{ep}]")
    if spec.sidecar_command:
        cmd = ", ".join(f'"{c}"' for c in spec.sidecar_command)
        lines.append(f"    command: [{cmd}]")
    if spec.sidecar_env:
        lines.append("    environment:")
        lines.extend(f"      - {kv}" for kv in spec.sidecar_env)
    if spec.sidecar_healthcheck:
        lines.extend(
            [
                "    healthcheck:",
                f'      test: ["CMD-SHELL", "{spec.sidecar_healthcheck}"]',
                "      interval: 2s",
                "      timeout: 3s",
                "      retries: 40",
                "      start_period: 3s",
            ]
        )
    lines.append("  main:")
    if spec.sidecar_healthcheck:
        lines.extend(
            [
                "    depends_on:",
                f"      {spec.sidecar_service}:",
                "        condition: service_healthy",
            ]
        )
    else:
        lines.append(f"    depends_on: [{spec.sidecar_service}]")
    lines.extend(
        [
            "    environment:",
            "      - AWS_ACCESS_KEY_ID=dummy",
            "      - AWS_SECRET_ACCESS_KEY=dummy",
            "      - AWS_DEFAULT_REGION=us-east-1",
            f"      - {spec.endpoint_env}={spec.sidecar_endpoint()}",
            f"      - AWS_ENDPOINT_URL={spec.sidecar_endpoint()}",
            "      - AWS_PAGER=",
            "      - AWS_EC2_METADATA_DISABLED=true",
            "    extra_hosts:",
        ]
    )
    return "\n".join(lines) + "\n" + extra_hosts + "\n"


# --------------------------------------------------------------------------- #
# Prompt set — generic model-service templates
#
# Mirrors the *_DDB templates in _cli_app_synthesis with the same {command_prefix}/
# {command}/... .format() placeholders, so the synthesis call sites are unchanged.
# Profile-specific tokens use __X__ and are substituted in make_generic_profile() BEFORE
# the caller's .format(); system strings are never formatted so their literal JSON braces
# are safe. NB: __type in the oracle text is an error field name, not a substitution token.
# --------------------------------------------------------------------------- #
_TRANSLATION_SYSTEM_MODEL = """You translate an aws-cli __SERVICE__ test intent into a black-box pytest test.

The environment runs a local __SERVICE__-compatible server, already booted and wired into the
`cli` and `__FIXTURE__` fixtures via conftest.py. Write a clean black-box pytest function from
scratch that verifies the intent's behaviour against real __SERVICE__ state.

Fixtures (use ONLY these as test-function args): `cli`, `__FIXTURE__`, `tmp_path`.
- `cli(*argv)` runs the candidate CLI as a subprocess -> subprocess.CompletedProcess
  (.returncode, .stdout, .stderr). e.g. cli("__SERVICE__", "<command>", "--flag", "value").
- `__FIXTURE__` is a raw-HTTP __SERVICE__ client (NOT boto3). Method:
    __FIXTURE__.rpc(action, payload) -> dict   e.g. __FIXTURE__.rpc("__READY__", {})
  It speaks JSON __JSONV__ with header X-Amz-Target: __TARGET__.<Action>. Use it to SET UP
  prerequisite state and to ASSERT resulting state.

Hard rules:
1. NEVER import or reference boto3, botocore, moto, minio, or awscli in any form — fatal error. stdlib + json only.
2. __WIRE_RULES__
3. Invoke the candidate with `cli(...)`. Assert BOTH result.returncode AND at least one real
   __SERVICE__ STATE assertion via `__FIXTURE__` (a resource present with the right value, etc.).
   A bare `assert result.returncode == 0` with no state check is REJECTED (non-discriminative).
   Some scenarios need MORE THAN ONE `cli(...)` call (e.g. create then read back, or an operation
   whose second attempt must fail) — check each call's returncode and assert on the FINAL state.
4. STATE-STRICT ORDER (a baseline read AFTER the mutating call is a tautology — forbidden):
   establish any prerequisite state FIRST (via `__FIXTURE__.rpc(...)` or a prior `cli(...)`), THEN run
   the command under test, THEN read the RESULTING state back through `__FIXTURE__` and assert the
   command's effect. Tests must run in isolation and in any order.
5. Upstream alignment (must ALSO pass against real `aws __SERVICE__` v2.28.23):
   - Exit codes: for error cases assert `result.returncode != 0` ONLY — NEVER assert == 255/254/252/2.
   - ERROR tests MUST assert an error-CATEGORY substring in `result.stderr` (the service's exception
     name, e.g. a `...Exception`/`...NotFound`/`...Disabled` class) — a bare `returncode != 0` with no
     stderr check is REJECTED (a crash on bad input would score identical to a correct rejection).
     Match the category substring, never verbatim wording.
   - Stdout: parse with json.loads(result.stdout) and assert on structure, never on text/whitespace/key order.
     Some successes print nothing — don't assert stdout for those.
   - No invented flags: use only flags that exist on the real command.
Output: function name test_<command>_<descriptive>; plain def with positional fixture args;
return ONLY the test function source (no preamble, no markdown fences)."""


_TRANSLATION_USER_TEMPLATE_MODEL = """Intent to translate into a black-box pytest test:
- Command: aws {command_prefix} {command}
- argv after program name: {cmdline_template}
- Expected exit category: {expected_exit} (0 = success, non-zero = error)
- Modelled operation(s): {expected_state_calls}
- Behaviour tag: {behaviour_tag}

Context brief (there is no real test to copy):
{raw_source}

Write the black-box pytest test. Invoke the candidate with `cli("{command_prefix}", "{command}", ...)`.
Use `__FIXTURE__.rpc(...)` to seed any prerequisite state and to assert the resulting __SERVICE__ state."""


_ORACLE_SYSTEM_MODEL = """You write a reference Python implementation of a single `aws __SERVICE__` command.

The __SERVICE__ backend is a local server reachable at env var __ENDPOINT_ENV__
(fallback AWS_ENDPOINT_URL). Talk to it over raw HTTP with the JSON __JSONV__ protocol — NO SDK.

Wire protocol: HTTP POST to the endpoint with headers:
  Content-Type: application/x-amz-json-__JSONV__
  X-Amz-Target: __TARGET__.<OperationName>
  Authorization: AWS4-HMAC-SHA256 Credential=dummy/20260101/us-east-1/__SIGN__/aws4_request, SignedHeaders=host;x-amz-date, Signature=dummy
Body is the operation's JSON input. The local backend ignores the signature, so the static dummy
Authorization header is accepted. Use urllib from the standard library.

Constraints:
- Single file: `submission/main.py`.
- NO boto3, botocore, moto, minio, or awscli — and do NOT shell out to `aws`.
- Parse argv: argv[1] = prefix ("__SERVICE__"), argv[2] = command; parse --flags after.
- __ORACLE_RULES__
- Wire semantics: __WIRE_RULES__
- Exit codes: 0 success; 252 usage error (missing/invalid required arg, unknown command); 254 for a
  modelled __SERVICE__ service error (an error response body); 255 for other internal errors.
- On a service error, write the error response body (with the __type / exception name) to stderr so
  callers can match the error category.
- Print successful output as JSON (json.dumps of the response) to stdout. For commands AWS prints
  nothing for, print nothing.

Invoked as: `python submission/main.py __SERVICE__ <command> [args...]`.
Return ONLY the Python source for submission/main.py (no preamble, no markdown fences)."""


_ORACLE_USER_TEMPLATE_MODEL = """Implement `aws {command_prefix} {command}` covering these behaviours:

{behaviours_bulleted}

Dispatch on argv[1] (prefix) / argv[2] (subcommand) so the file can be extended later; for now
focus on the `{command}` subcommand."""


_ORACLE_SUBSET_SYSTEM_MODEL = """You write a reference Python implementation of a SUBSET of `aws __SERVICE__` \
commands as ONE file.

Same wire protocol and constraints as a single-command __SERVICE__ oracle (raw HTTP JSON __JSONV__ to
__ENDPOINT_ENV__, X-Amz-Target __TARGET__.<Op>; NO boto3/botocore/moto/minio/awscli; stdlib urllib
only), with:
- Single file `submission/main.py`; parse argv and dispatch on the subcommand (argv[2]) so one
  program handles every requested subcommand.
- __ORACLE_RULES__
- Wire semantics: __WIRE_RULES__
- Keep __SERVICE__ state consistent across subcommands so a create -> use -> read-back -> delete
  sequence behaves correctly end-to-end.
- Exit codes 0/252/254/255 as for the single-command oracle; JSON output on stdout; error body on
  stderr for service errors.

Invoked as: `python submission/main.py __SERVICE__ <command> [args...]`.
Return ONLY the Python source for submission/main.py (no preamble, no markdown fences)."""


_ORACLE_SUBSET_USER_TEMPLATE_MODEL = """Implement a single `aws {command_prefix}` CLI supporting ALL of \
these subcommands: {commands_csv}.

It must cover these behaviours (collected across the subcommands):

{behaviours_bulleted}

Dispatch on argv[1] (prefix) / argv[2] (subcommand) so one `main.py` handles every listed
subcommand, and keep __SERVICE__ state consistent across them so cross-command workflows behave
correctly end-to-end."""


_WORKFLOW_SYSTEM_MODEL = """You write black-box pytest tests that exercise CROSS-COMMAND behaviour of a \
from-scratch `aws __SERVICE__` CLI.

The CLI is an executable `aws` at /workspace/submission/aws, invoked as a subprocess via the `cli`
fixture: `cli(*argv) -> subprocess.CompletedProcess`. A raw-HTTP __SERVICE__ client `__FIXTURE__`
(same server) and pytest's `tmp_path` are also fixtures.

Rules:
1. Every test function MUST declare the fixtures it uses as parameters — write
   `def test_workflow_<chain>(cli, __FIXTURE__, tmp_path):`. Use ONLY the fixtures `cli`,
   `__FIXTURE__`, `tmp_path`. No decorators. stdlib + json only.
2. NEVER import boto3, botocore, moto, minio, or awscli. `__FIXTURE__` exposes
   __FIXTURE__.rpc(action, payload); use it (not boto3 idiom) for state setup + assertions.
3. Create ALL prerequisite state inside the test (via __FIXTURE__.rpc or via the CLI itself).
   Tests run in isolation and any order.
4. After each `cli(...)` meant to succeed, assert result.returncode == 0. For steps meant to fail,
   assert result.returncode != 0 AND an error-category stderr substring. NEVER assert an exact code.
5. __WIRE_RULES__
6. Each test MUST chain at least TWO different subcommands and include one assertion that depends on a
   PRIOR command's effect. Assert only on order-insensitive state.
7. No invented flags. Name each function test_workflow_<chain>. Return ONLY the test function source(s)
   (one or more def test_...), no preamble, no markdown fences."""


_WORKFLOW_USER_TEMPLATE_MODEL = """Write {n_workflows} cross-command workflow test function(s) for an \
`aws {command_prefix}` CLI covering ONLY this compatible subset of subcommands: {subset_csv}.

Documented per-command and cross-command invariants (the contract you must verify):
{state_models_joined}

Representative argv shapes observed for these commands:
{argv_shapes_bulleted}

Each test must chain at least two different subcommands from {subset_csv} and assert on __SERVICE__
state produced by an earlier command. Across the workflow tests you write, EVERY subcommand in
{subset_csv} must appear in at least one HAPPY (rc==0) step — do not leave any listed command
exercised only on an error path. Include at least one NEGATIVE chain where a later step must fail
(assert rc!=0 AND an error-category stderr substring). Use ONLY subcommands from {subset_csv}."""


_WF_IMPORT_PREAMBLE_MODEL = "import json\n\n\n"


def _specialise(text: str, spec: SidecarSpec) -> str:
    """Substitute the profile-specific ``__X__`` tokens, leaving ``{...}`` .format()
    placeholders intact for the engine's downstream .format() call."""
    return (
        text.replace("__SERVICE__", spec.service)
        .replace("__TARGET__", spec.target_prefix)
        .replace("__JSONV__", spec.json_version)
        .replace("__ENDPOINT_ENV__", spec.endpoint_env)
        .replace("__SIGN__", spec.signing_service)
        .replace("__FIXTURE__", spec.fixture_name)
        .replace("__READY__", spec.ready_action)
        .replace("__WIRE_RULES__", spec.wire_rules)
        .replace("__ORACLE_RULES__", spec.oracle_rules)
    )


_SIDECARS: dict[str, SidecarSpec] = {}


def resolve_sidecar(backend_key: str) -> SidecarSpec | None:
    """The SidecarSpec for a generic sidecar backend, or None for the byte-locked
    dynamodb_local / minio. Drives the reference-grounding + G3/G4 gauntlets, which boot
    this backend on a throwaway docker network so the network-isolated gate containers can
    reach it (the emitted task itself uses a compose sidecar instead)."""
    return _SIDECARS.get(backend_key)


def make_generic_profile(
    spec: SidecarSpec,
    *,
    build_instruction_single: Callable[..., str],
    build_instruction_subset: Callable[..., str],
) -> ServiceProfile:
    """Build the registry :class:`ServiceProfile` for a generic sidecar backend.

    The prompt strings are specialised from the shared model templates; conftest/dockerfile
    are wired to the generic builders (closed over ``spec``); the instruction builders are
    injected by the engine (they reuse engine-internal helpers). ``client_module_src`` is
    None -- the raw-HTTP client is inlined in the conftest, not a shipped module.
    """
    spec.validate()
    _SIDECARS[spec.backend_key] = spec
    return ServiceProfile(
        backend_key=spec.backend_key,
        service=spec.service,
        simulation_backend=spec.simulation_backend,
        extract_mode="botocore_model",
        default_target_ops=spec.default_target_ops,
        target_prefix=spec.target_prefix,
        json_version=spec.json_version,
        translation_system=_specialise(_TRANSLATION_SYSTEM_MODEL, spec),
        translation_user=_specialise(_TRANSLATION_USER_TEMPLATE_MODEL, spec),
        oracle_system=_specialise(_ORACLE_SYSTEM_MODEL, spec),
        oracle_user=_specialise(_ORACLE_USER_TEMPLATE_MODEL, spec),
        oracle_subset_system=_specialise(_ORACLE_SUBSET_SYSTEM_MODEL, spec),
        oracle_subset_user=_specialise(_ORACLE_SUBSET_USER_TEMPLATE_MODEL, spec),
        workflow_system=_specialise(_WORKFLOW_SYSTEM_MODEL, spec),
        workflow_user=_specialise(_WORKFLOW_USER_TEMPLATE_MODEL, spec),
        wf_preamble=_WF_IMPORT_PREAMBLE_MODEL,
        client_module_path=None,
        client_module_src=None,
        build_conftest=lambda golden=False: build_conftest_generic(spec, golden=golden),
        build_dockerfile=lambda **kw: build_dockerfile_generic(spec, **kw),
        build_instruction_single=build_instruction_single,
        build_instruction_subset=build_instruction_subset,
        base_image=spec.base_image,
        pinned_deps=spec.pinned_deps,
        build_compose_overlay=lambda: build_sidecar_compose_generic(spec),
    )
