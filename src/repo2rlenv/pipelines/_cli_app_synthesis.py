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
import hashlib
import logging
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from repo2rlenv.auth import resolve_github_token
from repo2rlenv.bootstrap.runner import _shallow_clone_at_ref
from repo2rlenv.emitter.harbor import BLOCKED_SUFFIXES, HarborTask, write_harbor_task
from repo2rlenv.llm import complete
from repo2rlenv.pipelines._cli_app_extract import (
    CliSpec,
    CommandSpec,
    TestIntent,
    extract_cli_spec,
    extract_test_intents,
)
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
PROMPT_TEMPLATE_VERSION = "v1.1.0-primed"


# Pinned versions for the verification + runtime container. Used both at
# gauntlet time and in the emitted Harbor task's Dockerfile.
PINNED_DEPS = (
    "boto3==1.34.150",
    "botocore==1.34.150",
    "moto[s3,server]==5.0.16",
    "pytest==8.3.3",
    "freezegun==1.5.1",
    "werkzeug==3.0.4",
    "flask==3.0.3",
)
PINNED_PYTHON = "3.12-slim"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


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


# --- Subset (multi-command) oracle prompts ---

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


# --- Cross-command workflow-test prompts (subset tasks) ---

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


def _run_subset_mode(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    subsets: list[str],
    tests_dir_path: Path,
    out_dir: Path,
    owner_name: str,
    skip_reasons: dict[str, int],
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
                extract_test_intents(
                    tests_dir_path,
                    spec,
                    command_filter=c.name,
                    max_intents=options.cli_app_max_intents,
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
) -> tuple[int, int]:
    """Process per-command (or per-intent) mode. Returns (candidates_seen, emitted)."""
    candidates_seen = 0
    emitted = 0

    for cmd_spec in target_commands:
        if emitted >= options.limit:
            logger.info("cli_app: limit=%d reached", options.limit)
            break
        intents = extract_test_intents(
            tests_dir_path,
            spec,
            command_filter=cmd_spec.name,
            max_intents=options.cli_app_max_intents,
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
            )
            if task_path is not None:
                emitted += 1
                logger.info("cli_app: emitted %s", task_path.name)
                pipeline._emit_progress(task_path.name, "emit")

    return candidates_seen, emitted


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


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

    token = resolve_github_token(pipeline.input.repo, pipeline.input.auth)
    owner, name = pipeline.input.repo.owner_name
    owner_name = f"{owner}/{name}"
    skip_reasons: dict[str, int] = {}

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
        if options.cli_app_subsets:
            candidates_seen, emitted = _run_subset_mode(
                pipeline=pipeline,
                options=options,
                spec=spec,
                subsets=options.cli_app_subsets,
                tests_dir_path=tests_dir_path,
                out_dir=out_dir,
                owner_name=owner_name,
                skip_reasons=skip_reasons,
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
        (ctx_path / "Dockerfile").write_text(_build_dockerfile(bake_tests=True))
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
) -> str:
    """Derive task_id from spec sha + command + prompt version (+ intent_idx)."""
    h = hashlib.sha256()
    h.update(spec.spec_sha256.encode())
    h.update(b"\0")
    h.update(cmd_slug.encode())
    h.update(b"\0")
    h.update(PROMPT_TEMPLATE_VERSION.encode())
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


def _apply_static_gauntlet(test_files: dict[str, str]) -> dict[str, str]:
    """Gauntlet G1-G2 (cheap, no Docker). Returns survivors; raises if none survive."""
    survivors: dict[str, str] = {}
    for fname, code in test_files.items():
        ok, reason = _gauntlet_static(code)
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
) -> tuple[dict, dict[str, str]]:
    """Filter tests via real-aws + oracle reference. Returns (result, filtered_test_files)."""
    tests_aux = {"tests/conftest.py": conftest, "tests/__init__.py": ""}
    for fname, code in test_files.items():
        tests_aux[f"tests/{fname}"] = code
    reference_grounding = _run_reference_grounding(
        dockerfile_content=dockerfile,
        tests_aux=tests_aux,
        test_script=test_script,
        oracle_code=oracle_code,
        timeout_sec=options.cli_app_docker_timeout_sec,
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
    return reference_grounding, test_files


def _run_g3g4_gauntlet_gate(
    *,
    options: CodeInstructOptions,
    dockerfile: str,
    aux_files: dict[str, str],
    test_script: str,
    oracle_code: str,
) -> dict:
    """Gauntlet G3 (empty-stub-fails) + G4 (oracle-passes). Raises on non-discriminative."""
    gauntlet_g34 = _run_docker_gauntlet_g3g4(
        dockerfile_content=dockerfile,
        aux_files=aux_files,
        test_script=test_script,
        oracle_code=oracle_code,
        empty_max=options.cli_app_docker_empty_pass_max,
        oracle_min=options.cli_app_docker_oracle_pass_min,
        timeout_sec=options.cli_app_docker_timeout_sec,
    )
    if not gauntlet_g34.get("skipped"):
        if not gauntlet_g34["g3_pass"]:
            raise _TaskRejected(
                f"gauntlet_g3_non_discriminative_{gauntlet_g34['g3_empty_pass_rate']:.2f}"
            )
        if not gauntlet_g34["g4_pass"]:
            raise _TaskRejected(
                f"gauntlet_g4_oracle_failing_{gauntlet_g34['g4_oracle_pass_rate']:.2f}"
            )
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
    content_hash: str,
    reference_grounding: dict | None,
    gauntlet_g34: dict | None,
    llm_cost_before: float,
) -> dict:
    """Assemble the repo2env metadata block for one cli_app task."""
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
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "translation_model": _translation_model_id(pipeline, options),
            "oracle_model": pipeline._llm.qualified_name,
            "intents_extracted": len(intents),
            "tests_translated": len(translated),
            "tests_in_task": len(test_files),
            "simulation_backend": "moto",
            "python_version": "3.11",
            "entry_point": "submission/main.py",
            "pinned_deps": list(PINNED_DEPS),
            "runtime_cpus": 1.0,
            "runtime_memory_mb": 1024,
            "runtime_network": "none",
            "runtime_timeout_sec": 300,
            "llm_cost_usd": round(pipeline._llm_cost_usd - llm_cost_before, 6),
            "run_llm_cost_usd": round(pipeline._llm_cost_usd, 6),
            "llm_cost_method": "litellm_native",
            "behaviour_tags": sorted({i.behaviour_tag for i in intents}),
            "behaviour_tag_counts": _count_behaviour_tags(intents),
        },
    }
    if is_subset:
        repo2env["code_instruct"]["commands"] = sorted(cmd_names)
        repo2env["code_instruct"]["subset"] = True
        # count workflow tests that actually shipped (post static gauntlet)
        repo2env["code_instruct"]["workflow_tests"] = sum(
            1 for f in test_files if "_workflow_" in f
        )
    if reference_grounding is not None and not reference_grounding.get("skipped"):
        repo2env["code_instruct"]["reference_grounding"] = {
            "reference": "aws-cli",
            "awscli_version": PINNED_AWSCLI,
            "n_reference_pass": reference_grounding["n_reference"],
            "n_oracle_pass": reference_grounding["n_oracle"],
            "n_empty_stub_pass": reference_grounding["n_empty"],
            "tests_shipped": len(test_files),
            "discriminative": True,
            "oracle_solves_all_shipped": True,
        }
    if gauntlet_g34 is not None and not gauntlet_g34.get("skipped"):
        repo2env["code_instruct"]["docker_gauntlet"] = {
            "g3_empty_pass_rate": round(gauntlet_g34["g3_empty_pass_rate"], 4),
            "g3_empty_passed": gauntlet_g34["g3_empty_passed"],
            "g3_empty_total": gauntlet_g34["g3_empty_total"],
            "g4_oracle_pass_rate": round(gauntlet_g34["g4_oracle_pass_rate"], 4),
            "g4_oracle_passed": gauntlet_g34["g4_oracle_passed"],
            "g4_oracle_total": gauntlet_g34["g4_oracle_total"],
            "discriminative": True,
            "image_tag": gauntlet_g34.get("image_tag", ""),
        }
    return repo2env


def _build_one_task(
    *,
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    cmd_specs: list[CommandSpec],
    intents: list[TestIntent],
    out_dir: Path,
    intent_idx: int | None = None,
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
    # Canonical, order-independent slugs. Single-command keeps the bare command
    # name so existing task_ids / cache keys / filenames are unchanged.
    cmd_slug = cmd_names[0] if not is_subset else "+".join(sorted(cmd_names))
    id_slug = cmd_names[0] if not is_subset else "_".join(sorted(cmd_names))

    # Snapshot pipeline-wide cost before this task's LLM work so the per-task
    # record reflects ONLY this task's delta, not the cumulative run total.
    _llm_cost_before = pipeline._llm_cost_usd

    # ----- LLM: translate each intent into a black-box test -----
    translated: list[str] = []
    for intent in intents:
        test_code = _translate_intent(pipeline, options, spec, intent)
        if test_code is None:
            continue
        translated.append(test_code)
    if not translated:
        raise _TaskRejected("no_translatable_intents")

    # ----- LLM: synthesise oracle (cached per command-or-subset) -----
    cache_key = f"{spec.spec_sha256}|{cmd_slug}"
    if cache_key in _ORACLE_CACHE:
        oracle_code = _ORACLE_CACHE[cache_key]
    else:
        oracle_code = _synthesise_oracle(pipeline, options, spec, cmd_specs, intents)
        if oracle_code is not None:
            _ORACLE_CACHE[cache_key] = oracle_code
    if oracle_code is None:
        raise _TaskRejected("oracle_synthesis_failed")

    # ----- Build supporting files -----
    conftest = _build_conftest()
    test_files = {
        f"test_{spec.command_prefix}_{id_slug}_{i:02d}.py": code
        for i, code in enumerate(translated)
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
    dockerfile = _build_dockerfile(bake_tests=options.cli_app_ecr_push)
    test_script = _build_test_script()

    # ----- Gauntlet G1-G2 (cheap, no Docker) -----
    if not options.cli_app_skip_gauntlet:
        test_files = _apply_static_gauntlet(test_files)

    # ----- Reference grounding (opt-in): keep ONLY tests that BOTH the real
    # aws CLI AND the synthesised oracle pass, and that the empty stub fails.
    # Filters out LLM-hallucinated/brittle tests and guarantees the gold patch
    # solves its own task. The `aws` binary lives only in the gauntlet image,
    # never in the shipped task image (anti-cheat).
    reference_grounding = None
    if options.cli_app_reference_grounding:
        reference_grounding, test_files = _apply_reference_grounding(
            options=options,
            dockerfile=dockerfile,
            conftest=conftest,
            test_files=test_files,
            test_script=test_script,
            oracle_code=oracle_code,
        )

    # ----- Assemble aux_files for Harbor (tests/ subdir) -----
    aux_files: dict[str, str] = {
        "tests/conftest.py": conftest,
        "tests/__init__.py": "",
    }
    for fname, code in test_files.items():
        aux_files[f"tests/{fname}"] = code

    # ----- Multi-file gold patch creates submission/main.py -----
    gold_diff = make_multi_file_diff({"submission/main.py": oracle_code})

    # ----- instruction.md (rendered from spec, NEVER from tests) -----
    if is_subset:
        instruction_md = _build_subset_instruction_md(spec, cmd_specs, intents)
    else:
        instruction_md = _build_instruction_md(spec, cmd_specs[0], intents)
    _assert_no_test_leakage(instruction_md, test_files)

    # ----- task_id derived from spec sha + command + prompt version (+ intent_idx) -----
    task_id = _compute_cliapp_task_id(
        spec=spec,
        cmd_slug=cmd_slug,
        id_slug=id_slug,
        intent_idx=intent_idx,
        intents=intents,
    )

    # ----- Pre-compute content_hash covering spec + tests + oracle + instr -----
    # Overrides harbor.py's default which only covers instruction + diff.
    content_hash = _compute_content_hash(
        spec=spec,
        instruction=instruction_md,
        oracle_diff=gold_diff,
        aux_files=aux_files,
        prompt_version=PROMPT_TEMPLATE_VERSION,
        translation_model=_translation_model_id(pipeline, options),
        oracle_model=pipeline._llm.qualified_name,
    )

    # ----- Gauntlet G3 (empty-stub-fails) + G4 (oracle-passes) — opt-in -----
    # Without this, tests can be non-discriminative (pass on empty stub).
    # Builds image once per Dockerfile (cached), runs pytest twice per task.
    gauntlet_g34 = None
    if not options.cli_app_skip_gauntlet and getattr(options, "cli_app_docker_gauntlet", False):
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
        content_hash=content_hash,
        reference_grounding=reference_grounding,
        gauntlet_g34=gauntlet_g34,
        llm_cost_before=_llm_cost_before,
    )

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
        )
        repo2env["reproducibility"] = {
            "mode": "registry",
            "image_ref": _task_ecr_ref,
            "image_tag": _task_ecr_ref,
            "image_visibility": "private",
        }

    if is_subset:
        description = (
            f"Implement an `aws {spec.command_prefix}` CLI subset "
            f"({', '.join(sorted(cmd_names))}) from scratch"
        )[:120]
        keywords = [spec.name, "code_instruct", "cli_app", "subset", *sorted(cmd_names)]
    else:
        description = (f"Implement `aws {spec.command_prefix} {cmd_names[0]}` from scratch")[:120]
        keywords = [spec.name, "code_instruct", "cli_app", cmd_names[0]]

    task = HarborTask(
        name=task_id,
        org=pipeline.input.output.org,
        description=description,
        instruction=instruction_md,
        oracle_diff=gold_diff,
        repo2env=repo2env,
        difficulty="medium",
        category="feature",
        keywords=keywords,
        environment_dockerfile=dockerfile,
        test_script=test_script,
        aux_files=aux_files,
        task_uuid=str(uuid4()),
    )
    return write_harbor_task(task, out_dir)


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _translate_intent(
    pipeline: CodeInstructPipeline,
    options: CodeInstructOptions,
    spec: CliSpec,
    intent: TestIntent,
) -> str | None:
    """One LLM call per intent. Returns translated test code or None on failure."""
    user = TRANSLATION_USER_TEMPLATE.format(
        raw_source=intent.raw_source[:4000],
        command_prefix=spec.command_prefix,
        command=intent.command,
        cmdline_template=intent.cmdline_template,
        expected_exit=intent.expected_exit,
        expected_state_calls=intent.expected_state_calls,
        behaviour_tag=intent.behaviour_tag,
    )
    try:
        resp = complete(
            pipeline._llm,
            system=TRANSLATION_SYSTEM,
            user=user,
            max_tokens=options.max_llm_tokens,
            temperature=options.llm_temperature,
        )
    except Exception as exc:
        logger.warning("translation failed for %s: %s", intent.test_name, exc)
        return None
    pipeline._llm_cost_usd += resp.cost_usd
    return _strip_code_fence(resp.content)


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
    behaviours = _summarise_behaviours_from_intents(intents)
    behaviours_bulleted = "\n".join(f"- {b}" for b in behaviours)
    if len(cmd_specs) > 1:
        commands_csv = ", ".join(f"`{spec.command_prefix} {c.name}`" for c in cmd_specs)
        system = ORACLE_SUBSET_SYSTEM
        user = ORACLE_SUBSET_USER_TEMPLATE.format(
            command_prefix=spec.command_prefix,
            commands_csv=commands_csv,
            behaviours_bulleted=behaviours_bulleted,
        )
    else:
        system = ORACLE_SYSTEM
        user = ORACLE_USER_TEMPLATE.format(
            command_prefix=spec.command_prefix,
            command=cmd_specs[0].name,
            behaviours_bulleted=behaviours_bulleted,
        )
    cmd_label = "+".join(c.name for c in cmd_specs)
    try:
        resp = complete(
            pipeline._llm,
            system=system,
            user=user,
            max_tokens=options.max_llm_tokens,
            temperature=options.llm_temperature,
        )
    except Exception as exc:
        logger.warning("oracle synthesis failed for command=%s: %s", cmd_label, exc)
        return None
    pipeline._llm_cost_usd += resp.cost_usd
    code = _strip_code_fence(resp.content)
    try:
        compile(code, "<oracle>", "exec")
    except SyntaxError as exc:
        logger.warning("oracle synthesis returned invalid Python: %s", exc)
        return None
    return code


# Prepended to every workflow-test module so each is self-contained after the
# multi-function LLM response is split into one file per test function.
_WF_IMPORT_PREAMBLE = "import boto3\nimport botocore\nimport botocore.exceptions\n\n\n"


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
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen:
            seen.add(shape)
            shapes.append(f"- `{shape}`")
    argv_shapes_bulleted = "\n".join(shapes) if shapes else "- (none observed)"

    n_workflows = max(1, options.cli_app_workflow_tests)
    user = WORKFLOW_USER_TEMPLATE.format(
        command_prefix=spec.command_prefix,
        subset_csv=", ".join(subset_names),
        state_models_joined=state_models_joined,
        argv_shapes_bulleted=argv_shapes_bulleted,
        n_workflows=n_workflows,
    )
    try:
        resp = complete(
            pipeline._llm,
            system=WORKFLOW_SYSTEM,
            user=user,
            max_tokens=options.max_llm_tokens,
            temperature=options.llm_temperature,
        )
    except Exception as exc:
        logger.warning("workflow-test synthesis failed for subset=%s: %s", subset_names, exc)
        return []
    pipeline._llm_cost_usd += resp.cost_usd
    code = _strip_code_fence(resp.content)
    return _split_workflow_functions(
        code, allowed_commands=set(subset_names), prefix=spec.command_prefix
    )


def _split_workflow_functions(code: str, *, allowed_commands: set[str], prefix: str) -> list[str]:
    """Split a multi-function workflow blob into one self-contained module per
    `test_*` function. Functions whose `cli(...)` calls reference a subcommand
    outside the subset are dropped (the combined oracle won't implement it).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
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
    header = _WF_IMPORT_PREAMBLE
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


def _gauntlet_static(test_code: str) -> tuple[bool, str]:
    """G1 (compile) + G2 (AST structural). Returns (ok, reason_if_not)."""
    # G1
    try:
        tree = ast.parse(test_code)
    except SyntaxError as exc:
        return False, f"G1_compile: {exc}"
    # G2: must define at least one `def test_*` function with a body
    found_test = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            found_test = True
            # Must contain at least one Assert OR call to assert via subprocess
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
    return True, ""


# ---------------------------------------------------------------------------
# Artefact builders (Dockerfile, conftest, test.sh, instruction.md)
# ---------------------------------------------------------------------------


def _build_dockerfile(*, bake_tests: bool = False) -> str:
    """Pinned python-slim + pinned deps + determinism env + git init; bake_tests COPYs tests/ for ECR per-task variance."""
    deps_line = " ".join(f'"{d}"' for d in PINNED_DEPS)
    copy_tests = "COPY tests/ /workspace/tests/\n" if bake_tests else ""
    return (
        "# Auto-generated by Repo2RLEnv code_instruct cli_app mode\n"
        f"FROM python:{PINNED_PYTHON}\n"
        'ARG HTTP_PROXY=""\n'
        'ARG HTTPS_PROXY=""\n'
        'ARG NO_PROXY="localhost,127.0.0.1,::1"\n'
        'ARG CA_CERT_PATH="/etc/ssl/certs/ca-certificates.crt"\n'
        "ENV HTTP_PROXY=${HTTP_PROXY} \\\n"
        "    HTTPS_PROXY=${HTTPS_PROXY} \\\n"
        "    NO_PROXY=${NO_PROXY} \\\n"
        "    http_proxy=${HTTP_PROXY} \\\n"
        "    https_proxy=${HTTPS_PROXY} \\\n"
        "    no_proxy=${NO_PROXY} \\\n"
        "    SSL_CERT_FILE=${CA_CERT_PATH} \\\n"
        "    REQUESTS_CA_BUNDLE=${CA_CERT_PATH} \\\n"
        "    CURL_CA_BUNDLE=${CA_CERT_PATH} \\\n"
        "    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \\\n"
        "    PYTHONHASHSEED=0 TZ=UTC LC_ALL=C.UTF-8 \\\n"
        "    AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing \\\n"
        "    AWS_DEFAULT_REGION=us-east-1\n"
        "WORKDIR /workspace\n"
        "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
        "      git ca-certificates && rm -rf /var/lib/apt/lists/*\n"
        "RUN pip install --no-cache-dir --upgrade pip\n"
        f"RUN pip install --no-cache-dir {deps_line}\n"
        f"{copy_tests}"
        # NOTE: don't pre-create submission/main.py — the gold patch is a
        # `new file` diff which `git apply` rejects with "already exists" if
        # the file is present. Just make the dir + an empty .gitkeep so git
        # has something to commit as a baseline.
        "RUN mkdir -p /workspace/submission && touch /workspace/submission/.gitkeep\n"
        "RUN git init -q /workspace && \\\n"
        "    git -C /workspace config user.email r2e@local && \\\n"
        "    git -C /workspace config user.name r2e && \\\n"
        "    git -C /workspace add -A && \\\n"
        "    git -C /workspace commit -q --allow-empty -m 'r2e: baseline'\n"
    )


def _build_conftest() -> str:
    """ThreadedMotoServer per-test fixture + cli subprocess wrapper + s3_client.

    The verifier-phase socket guard reuses ``BLOCKED_SUFFIXES`` from
    ``emitter/harbor`` as its single source of truth so the Docker-layer
    disallow-list and the Python-layer guard cannot drift. Public IP
    literals are rejected outright (closing the IP-bypass route a pure
    suffix blocklist leaves open).
    """
    suffixes_literal = ", ".join(repr(s) for s in BLOCKED_SUFFIXES)
    template = '''"""Auto-generated by Repo2RLEnv code_instruct cli_app mode.

Per-test moto S3 server + subprocess fixtures. The agent's submission
runs as a subprocess; @mock_aws's in-process patching doesn't reach
subprocesses, so we boot a real ThreadedMotoServer on a random port and
point boto3 (in both the test and the subprocess) at it via AWS_ENDPOINT_URL_S3.
"""

import ipaddress
import os
import socket as _socket
import subprocess
import sys

_R2E_ORIG_CONNECT = _socket.socket.connect
_R2E_BLOCKED_SUFFIXES = (__BLOCKED_SUFFIXES__,)


def _r2e_guarded_connect(self, address):
    if self.family in (_socket.AF_INET, _socket.AF_INET6) and isinstance(address, tuple):
        host = address[0]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            for suffix in _R2E_BLOCKED_SUFFIXES:
                if host.lower() == suffix or host.lower().endswith("." + suffix):
                    raise RuntimeError(f"r2e:network-isolation: connect to {host!r} blocked")
        else:
            if not (ip.is_loopback or ip.is_private or ip.is_link_local):
                raise RuntimeError(
                    f"r2e:network-isolation: connect to public IP {host!r} blocked"
                )
    return _R2E_ORIG_CONNECT(self, address)


_socket.socket.connect = _r2e_guarded_connect
def _r2e_guarded_connect_ex(self, addr):
    import errno as _errno
    try:
        _r2e_guarded_connect(self, addr)
        return 0
    except RuntimeError:
        return _errno.EACCES
    except OSError as exc:
        return exc.errno
_socket.socket.connect_ex = _r2e_guarded_connect_ex

import boto3
import pytest
from moto.server import ThreadedMotoServer


@pytest.fixture
def moto_server():
    server = ThreadedMotoServer(port=0)
    server.start()
    port = server._server.socket.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    yield endpoint
    server.stop()


@pytest.fixture
def s3_client(moto_server):
    return boto3.client(
        "s3",
        endpoint_url=moto_server,
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture
def cli(moto_server):
    """Invoke /workspace/submission/main.py as a subprocess.

    Returns a callable: cli(*argv) -> subprocess.CompletedProcess
    """

    def _run(*args, env_overrides=None, timeout=60):
        env = os.environ.copy()
        env["AWS_ENDPOINT_URL_S3"] = moto_server
        env["AWS_ENDPOINT_URL"] = moto_server
        env["AWS_ACCESS_KEY_ID"] = "testing"
        env["AWS_SECRET_ACCESS_KEY"] = "testing"
        env["AWS_DEFAULT_REGION"] = "us-east-1"
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, "/workspace/submission/main.py", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return _run
'''
    return template.replace("__BLOCKED_SUFFIXES__", suffixes_literal)


def _build_test_script() -> str:
    """test.sh runs pytest on the tests dir (sibling of $0), writes pass-rate to reward.txt.

    Harbor mounts the task's tests/ dir into the container at /tests (sibling
    of where test.sh ends up). Using `$(dirname $0)` makes the script work
    regardless of mount path.
    """
    return """#!/bin/bash
set -uxo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd /workspace
mkdir -p /logs/verifier

python -m pytest "$SCRIPT_DIR" -v --tb=short -p no:randomly \\
    > /logs/verifier/pytest_output.log 2>&1
TEST_EXIT_CODE=$?
cat /logs/verifier/pytest_output.log

PASSED=$(grep -oE '\\b[0-9]+ passed\\b' /logs/verifier/pytest_output.log \\
    | awk '{sum+=$1} END {print sum+0}')
FAILED=$(grep -oE '\\b[0-9]+ failed\\b' /logs/verifier/pytest_output.log \\
    | awk '{sum+=$1} END {print sum+0}')
ERRORS=$(grep -oE '\\b[0-9]+ error[s]?\\b' /logs/verifier/pytest_output.log \\
    | awk '{sum+=$1} END {print sum+0}')
TOTAL=$((PASSED + FAILED + ERRORS))

if [ "$TOTAL" -gt 0 ]; then
    REWARD=$(python3 -c "print(round($PASSED / $TOTAL, 4))")
else
    REWARD=0.0
fi
echo "$REWARD" > /logs/verifier/reward.txt
echo "passed=$PASSED failed=$FAILED errors=$ERRORS reward=$REWARD"
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
        "- `--request-payer requester` MUST be passed through to the boto3 call."
    ),
    ("s3", "sync"): (
        "- Syncs source → destination, transferring only files that are newer or absent.\n"
        "- Local-to-S3: uploads files that don't exist in S3 or whose local mtime is newer.\n"
        "- S3-to-local: downloads objects that don't exist locally or whose S3 LastModified is newer.\n"
        "- After sync, the destination's file/object set MUST be a superset of the source's.\n"
        "- Sync does NOT delete by default; `--delete` (if supported) removes destination items\n"
        "  not present at source.\n"
        "- Non-existent source directory (local): FAILS (exit 255, stderr `does not exist`)."
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
}

# Friendly English for boto3 operation names — used to render "Expected
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
}


def _build_instruction_md(spec: CliSpec, cmd_spec: CommandSpec, intents: list[TestIntent]) -> str:
    """Render the agent-facing instruction.md.

    Matches the client doc's deliverable shape (Pilot RL Environment Creation,
    "Feature Specification"): app description + per-command interface + I/O +
    error behaviour + cross-command state expectations + examples.

    Built ONLY from CliSpec + extracted intents — never reads raw_source or
    test bodies. `_assert_no_test_leakage` is the safety net.
    """
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
        "The harness configures the runtime environment so that\n"
        "`boto3.client('s3')` connects to a sandboxed, isolated S3 endpoint.\n"
        "Use boto3's defaults — do not override the endpoint, region, or\n"
        "credentials in your code. They will be set by the environment.\n"
        "Treat the S3 backend as real AWS S3: your implementation should be\n"
        "correct against the actual S3 API contract.\n"
    )

    # 2. Command spec
    parts.append(f"## Command: `{cmd_label}`\n")

    # 2a. Interface (positional args + flags)
    parts.append("### Interface\n\nObserved argv patterns (after `python submission/main.py`):\n")
    seen_shapes: set[str] = set()
    for intent in intents:
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
        "- stderr: empty\n"
        "- exit: 0"
    )
    if success_ops:
        bullets = ", ".join(f"`{op}`" for op in success_ops)
        ens = "; ".join(f"{op} = {_OP_TO_ENGLISH.get(op, op)}" for op in success_ops)
        parts.append(
            "- **Observable side effects** — the underlying boto3 calls invoked must\n"
            f"  include at least: {bullets}.\n"
            f"  (Plain English: {ens}.)"
        )
    parts.append("")
    parts.append("**On error (exit ≠ 0):**")
    if by_tag.get("error"):
        parts.append("- stdout: empty")
        parts.append("- stderr: human-readable error message that identifies the cause")
        parts.append("- exit: 1 (application error) or 2 / 255 (argument error)")
        parts.append("- Specific error cases:")
        for intent in by_tag["error"]:
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
        "- **Python 3.11** standard library + `boto3` only.\n"
        "- **Do NOT** import `awscli` or shell out to the real `aws` binary.\n"
        "- Use `boto3.client('s3')` with its defaults. Do not set endpoint, region,\n"
        "  or credentials in code; the runtime environment configures them for you.\n"
        "- Success messages go to **stdout**; errors go to **stderr**. Do not mix them.\n"
        "- Exit code: `0` on success, `1` on application error, `2`/`255` on argument errors\n"
        "  (matching aws-cli's conventions).\n"
        "- Suppress raw `botocore.exceptions.ClientError` tracebacks — print only the\n"
        "  user-facing error string.\n"
        "- Implementation lives at `/workspace/submission/main.py` — a single file.\n"
    )

    # (No "## Reference" block emitted: pointing the agent at the source
    # tests is a reward-hacking vector — it can fetch the test file at the
    # pinned SHA and hard-code submission/main.py to satisfy assertions
    # without actually implementing the CLI. Provenance lives in task.toml
    # under [metadata.repo2env] for the trainer, NOT in instruction.md.)

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
        shape = _argv_shape(intent.cmdline_template)
        if shape and shape not in seen:
            seen.add(shape)
            shapes.append(f"- `{shape}`")
    if shapes:
        parts.append("Observed argv patterns:\n")
        parts.extend(shapes)
        parts.append("")

    flags = _extract_flags_from_intents(intents)
    if flags:
        parts.append("Flags observed: " + ", ".join(f"`{f}`" for f in sorted(flags)) + "\n")

    state_model = _COMMAND_STATE_MODEL.get((prefix, cmd_spec.name))
    if state_model:
        parts.append("Behaviour & state expectations:\n")
        parts.append(state_model + "\n")

    by_tag = _group_by_tag(intents)
    if by_tag.get("error"):
        parts.append("Error cases:")
        for intent in by_tag["error"]:
            shape = _argv_shape(intent.cmdline_template) or "<argv>"
            parts.append(f"- `{shape}` -> exit `{intent.expected_exit}`")
        parts.append("")
    return parts


def _build_subset_instruction_md(
    spec: CliSpec, cmd_specs: list[CommandSpec], intents: list[TestIntent]
) -> str:
    """Agent-facing instruction.md for a multi-command subset task.

    Overview + one section per subcommand (interface + I/O + state) + a
    cross-command behaviour section. Built ONLY from CliSpec + intents + the
    hand-authored _COMMAND_STATE_MODEL — never from test code. `_assert_no_test_leakage`
    is the safety net.
    """
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
        "above. The harness configures the runtime so that `boto3.client('s3')`\n"
        "connects to a sandboxed, isolated S3 service. Use boto3's defaults — do not\n"
        "override the service address, region, or credentials in your code; they are\n"
        "set by the environment. Treat the S3 backend as real AWS S3, and keep state\n"
        "consistent across commands so a sequence like upload, list, download, remove\n"
        "behaves correctly end-to-end.\n"
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
        "- **Python 3.11** standard library + `boto3` only.\n"
        "- **Do NOT** import `awscli` or shell out to the real `aws` binary.\n"
        "- Use `boto3.client('s3')` with its defaults. Do not set the service address,\n"
        "  region, or credentials in code; the runtime environment configures them.\n"
        "- Success messages go to **stdout**; errors go to **stderr**. Do not mix them.\n"
        "- Exit code: `0` on success, `1` on application error, `2`/`255` on argument errors\n"
        "  (matching aws-cli's conventions).\n"
        "- Suppress raw `botocore.exceptions.ClientError` tracebacks — print only the\n"
        "  user-facing error string.\n"
        "- Everything lives in `/workspace/submission/main.py` — a single file that\n"
        "  dispatches on the subcommand.\n"
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
    out: list[str] = []
    for tok in tokens:
        if tok == "<arg>":
            # Best-effort label based on neighbours: a bare <arg> in the
            # middle of s3 cp/mv/sync is almost always a local path.
            out.append("<local-path>")
        else:
            out.append(tok)
    return " ".join(out)


def _humanise_test_name(name: str) -> str:
    """Turn `test_nonzero_exit_if_invalid_path_provided` into a short phrase."""
    s = name[len("test_") :] if name.startswith("test_") else name
    return s.replace("_", " ")


def _render_examples(intents: list[TestIntent], cmd_label: str) -> list[str]:
    """Render up to 4 representative invocations as bash one-liners.

    Pulls from intent.cmdline_template (NOT from test body). Diversity-first:
    one happy_path, one error, one workflow, one edge — caps total at 4.
    """
    chosen: list[TestIntent] = []
    seen_shapes: set[str] = set()
    priority = ["happy_path", "error", "workflow", "edge"]
    by_tag = _group_by_tag(intents)
    for tag in priority:
        for intent in by_tag.get(tag, []):
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
        lines.append(f"python /workspace/submission/main.py {argv}")
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
        "pytest",
        "conftest",
        "ThreadedMotoServer",
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
    for path in sorted(aux_files):
        _h(f"aux:{path}", aux_files[path])
    return f"sha256:{h.hexdigest()}"


def _strip_code_fence(text: str) -> str:
    """Strip surrounding markdown code fences if present."""
    s = text.strip()
    if s.startswith("```"):
        # remove first line (```python or ```)
        first_newline = s.find("\n")
        if first_newline > 0:
            s = s[first_newline + 1 :]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip() + "\n"


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
    """Parse `passed=N failed=N errors=N reward=R` line from test.sh stdout."""
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
            ["docker", "build", "-q", "-t", tag, str(ctx_dir)],
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


def _docker_run_test_sh(
    image_tag: str,
    bundle_dir: Path,
    timeout_sec: int,
    oracle_override_path: Path | None = None,
) -> dict:
    """Run /workspace/tests/test.sh in the container. Returns parsed summary."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "--cpus=1.0",
        "--memory=1g",
        "--network=none",
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
    cmd.extend([image_tag, "bash", "/workspace/tests/test.sh"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        out = (result.stdout + "\n" + result.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return {"passed": 0, "total": 0, "pass_rate": 0.0, "summary": "TIMEOUT"}
    return _parse_test_sh_summary(out)


def _run_docker_gauntlet_g3g4(
    *,
    dockerfile_content: str,
    aux_files: dict[str, str],
    test_script: str,
    oracle_code: str,
    empty_max: float,
    oracle_min: float,
    timeout_sec: int,
) -> dict:
    """G3 (empty stub fails) + G4 (oracle passes). Returns metrics + verdicts.

    Returns {'skipped': True, ...} if docker unavailable. Otherwise returns
    {g3_empty_pass_rate, g3_pass, g4_oracle_pass_rate, g4_pass, ...}.
    """
    with tempfile.TemporaryDirectory(prefix="r2e-gauntlet-ctx-") as ctx_str:
        ctx = Path(ctx_str)
        (ctx / "Dockerfile").write_text(dockerfile_content)
        image = _build_or_reuse_docker_image(dockerfile_content, ctx)
    if image is None:
        return {"skipped": True, "reason": "docker_unavailable"}

    with tempfile.TemporaryDirectory(prefix="r2e-gauntlet-bundle-") as b_str:
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
        g3 = _docker_run_test_sh(image, bundle, timeout_sec, oracle_override_path=None)
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
        g4 = _docker_run_test_sh(image, bundle, timeout_sec, oracle_override_path=oracle_path)
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

# aws-cli v1 (pip-installable, botocore-based, honours AWS_ENDPOINT_URL → moto).
PINNED_AWSCLI = "awscli==1.45.24"

# Mounted as /workspace/submission/main.py during the reference run: forwards
# argv to the real `aws` binary, so `cli("s3","mb",...)` runs `aws s3 mb ...`
# against the same moto server the test fixtures point at.
_REFERENCE_SHIM = (
    "import subprocess\n"
    "import sys\n"
    "raise SystemExit(subprocess.run(['aws', *sys.argv[1:]]).returncode)\n"
)

_PERTEST_PASS_RE = re.compile(r"^(tests/\S+\.py)::\S+\s+PASSED", re.M)


def _docker_run_pertest(
    image_tag: str,
    bundle_dir: Path,
    timeout_sec: int,
    override_path: Path | None = None,
) -> set[str]:
    """Run the test bank in the container; return the set of test-FILE names
    that PASSED (one test function per file, so file-level == test-level).
    """
    cmd = [
        "docker",
        "run",
        "--rm",
        "--cpus=1.0",
        "--memory=1g",
        "--network=none",
        "-v",
        f"{bundle_dir / 'tests'}:/workspace/tests:ro",
    ]
    if override_path is not None:
        cmd.extend(["-v", f"{override_path}:/workspace/submission/main.py:ro"])
    cmd.extend([image_tag, "bash", "/workspace/tests/test.sh"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return set()
    out = result.stdout + "\n" + result.stderr
    return {Path(m.group(1)).name for m in _PERTEST_PASS_RE.finditer(out)}


def _run_reference_grounding(
    *,
    dockerfile_content: str,
    tests_aux: dict[str, str],
    test_script: str,
    oracle_code: str,
    timeout_sec: int,
) -> dict:
    """Ground the test bank against the real aws CLI + oracle + empty stub.

    Returns {'skipped': True, ...} if docker unavailable. Otherwise returns the
    grounded file set = (reference-pass ∩ oracle-pass) − empty-pass, plus counts.
    """
    ref_dockerfile = (
        dockerfile_content
        + "\n# Reference oracle for gauntlet grounding ONLY (not the shipped image)\n"
        + f"RUN pip install --no-cache-dir {PINNED_AWSCLI}\n"
    )
    with tempfile.TemporaryDirectory(prefix="r2e-refground-ctx-") as ctx_str:
        ctx = Path(ctx_str)
        (ctx / "Dockerfile").write_text(ref_dockerfile)
        image = _build_or_reuse_docker_image(ref_dockerfile, ctx)
    if image is None:
        return {"skipped": True, "reason": "docker_unavailable"}

    with tempfile.TemporaryDirectory(prefix="r2e-refground-bundle-") as b_str:
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
        ref_path.write_text(_REFERENCE_SHIM)
        reference_pass = _docker_run_pertest(image, bundle, timeout_sec, ref_path)

        empty_pass = _docker_run_pertest(image, bundle, timeout_sec, None)

        oracle_path = bundle / "oracle_main.py"
        oracle_path.write_text(oracle_code)
        oracle_pass = _docker_run_pertest(image, bundle, timeout_sec, oracle_path)

    grounded = (reference_pass & oracle_pass) - empty_pass
    return {
        "skipped": False,
        "image_tag": image,
        "grounded_files": grounded,
        "n_reference": len(reference_pass),
        "n_oracle": len(oracle_pass),
        "n_empty": len(empty_pass),
        "n_grounded": len(grounded),
    }
