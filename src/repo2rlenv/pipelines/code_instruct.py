"""OSS-Instruct-style coding tasks, anchored to a target repo + verified by execution.

For each emitted task:

  1. Sample a seed snippet from the target repo (Python file, 30-200 LOC)
  2. Ask the LLM for [Problem Description], [Test], [Solution] in one call
  3. Verify in the bootstrap container:
     - With ONLY the test file in place: `pytest <test_file>` must FAIL
       (otherwise the test doesn't actually exercise the oracle — trivial)
     - With BOTH the test and oracle: `pytest <test_file>` must PASS
       (otherwise the LLM's oracle is wrong)
  4. Emit Harbor task whose gold patch adds `task_module.py` (the oracle)
     and `test_<task_id>.py` (the verifier) at the repo root

Different from Magicoder's OSS-Instruct:
  - Seeds come from one specific repo (verified-solvable in THAT env)
  - Each task has an executable pytest verifier (not just text)
  - The oracle has to actually pass the test in the repo's Docker env

----------------------------------------------------------------------------
Acknowledgment
----------------------------------------------------------------------------
Inspired by:

  Magicoder: Empowering Code Generation with OSS-Instruct
  (Wei et al., ICML '24, arXiv:2312.02120)
  https://github.com/ise-uiuc/magicoder        (MIT)

The seed-snippet → LLM-instruction recipe is adapted from their
`data_synthesis/` pipeline. Section parsing and decontamination
heuristics follow their patterns but are reimplemented against
the Python stdlib (see _oss_instruct.py).

Released under Apache-2.0 along with the rest of Repo2RLEnv.
----------------------------------------------------------------------------
"""

from __future__ import annotations

import base64
import hashlib
import logging
import random
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

import repo2rlenv
from repo2rlenv.auth import resolve_github_token
from repo2rlenv.bootstrap.runner import _shallow_clone_at_ref
from repo2rlenv.bootstrap.spec import BootstrapResult, LanguageHint
from repo2rlenv.emitter.harbor import HarborTask, write_harbor_task
from repo2rlenv.llm import complete
from repo2rlenv.pipelines._code_instruct_backends import get_backend
from repo2rlenv.pipelines._code_instruct_backends.base import LanguageBackend, SandboxDelivery
from repo2rlenv.pipelines._code_instruct_backends.python import (
    _all_tests_passed,
    _build_task_module_router,
    _make_solution_diff,
)

__all__ = [
    "CodeInstructPipeline",
    "_all_tests_passed",
    "_build_task_module_router",
    "_make_solution_diff",
    "build_code_instruct_dockerfile",
]
from repo2rlenv.pipelines._oss_instruct import (
    ParsedTask,
    Seed,
    has_benchmark_overlap,
    list_source_files,
    parse_task_response,
    sample_seed,
    solution_leaks_into_problem,
)
from repo2rlenv.pipelines.base import PipelineResult
from repo2rlenv.pipelines.mutation_bugs import build_mutation_eval_script
from repo2rlenv.spec.input import GenerationInput, PipelineName
from repo2rlenv.spec.options import CodeInstructOptions

_DEBUG_LOG_DIR = Path(tempfile.gettempdir()) / "repo2rlenv_code_instruct_debug"

_AWS_CONFTEST_BODY = (
    "import os\n"
    "import socket\n"
    "import sys\n"
    "import urllib.request\n"
    "import pytest\n"
    "\n"
    "_R2E_ORIG_CONNECT = socket.socket.connect\n"
    "\n"
    "\n"
    "def _r2e_is_loopback(host):\n"
    "    if isinstance(host, bytes):\n"
    '        host = host.decode("utf-8", "ignore")\n'
    "    return isinstance(host, str) and (\n"
    '        host == "localhost" or host == "::1" or host.startswith("127.")\n'
    "    )\n"
    "\n"
    "\n"
    "def _r2e_guarded_connect(self, address):\n"
    "    if self.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and address:\n"
    "        if not _r2e_is_loopback(address[0]):\n"
    "            raise RuntimeError(\n"
    '                f"r2e:network-isolation: connect to {address[0]!r} blocked; only loopback (moto) is allowed"\n'
    "            )\n"
    "    return _R2E_ORIG_CONNECT(self, address)\n"
    "\n"
    "\n"
    "socket.socket.connect = _r2e_guarded_connect\n"
    "\n"
    "\n"
    "@pytest.fixture(autouse=True)\n"
    "def _reset_moto():\n"
    '    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://127.0.0.1:5000")\n'
    "    try:\n"
    '        req = urllib.request.Request(f"{endpoint}/moto-api/reset", method="POST")\n'
    "        urllib.request.urlopen(req, timeout=5).read()\n"
    "    except Exception as exc:\n"
    '        print(f"r2e:moto-reset-failed: {exc}", file=sys.stderr)\n'
    "    yield\n"
)
_AWS_CONFTEST_B64 = base64.b64encode(_AWS_CONFTEST_BODY.encode("utf-8")).decode("ascii")

_AWS_CLI_VERSION = "2.28.23"
_MOTO_UNAVAILABLE_SENTINEL = "R2E_MOTO_SERVER_UNAVAILABLE"


def _references_aws(test_code: str, solution_code: str) -> bool:
    """Guard against aws_mode tasks whose synthesized code never touches AWS."""
    import re as _re

    blob = test_code + "\n" + solution_code
    if "boto3" in blob:
        return True
    return bool(_re.search(r"""['"]aws[ '"]""", blob))


def _aws_verify_preamble() -> str:
    """Idempotent moto bring-up; sentinel is the LAST stderr line so it survives log truncation."""
    return (
        'MOTO_PORT="${MOTO_PORT:-5000}"\n'
        'MOTO_CMD="moto_server -H 127.0.0.1 -p ${MOTO_PORT}"\n'
        'if ! pgrep -f "moto_server -H 127.0.0.1 -p ${MOTO_PORT}" >/dev/null 2>&1; then\n'
        "  $MOTO_CMD > /tmp/moto.log 2>&1 &\n"
        "  for i in $(seq 1 20); do\n"
        '    (echo > /dev/tcp/127.0.0.1/"$MOTO_PORT") >/dev/null 2>&1 && break\n'
        "    sleep 0.5\n"
        "  done\n"
        "fi\n"
        'if ! (echo > /dev/tcp/127.0.0.1/"$MOTO_PORT") >/dev/null 2>&1; then\n'
        "  cat /tmp/moto.log >&2 2>/dev/null || true\n"
        f"  echo '{_MOTO_UNAVAILABLE_SENTINEL}' >&2\n"
        "  exit 99\n"
        "fi\n"
        'curl -sX POST "http://127.0.0.1:${MOTO_PORT}/moto-api/reset" >/dev/null 2>&1 || true\n'
        'export AWS_ENDPOINT_URL="http://127.0.0.1:${MOTO_PORT}"\n'
        "export AWS_ACCESS_KEY_ID=testing\n"
        "export AWS_SECRET_ACCESS_KEY=testing\n"
        "export AWS_DEFAULT_REGION=us-east-1\n"
        "export AWS_SESSION_TOKEN=testing\n"
        "export AWS_EC2_METADATA_DISABLED=true\n"
    )


def _dump_failure_log(
    test_filename: str,
    reason: str,
    *,
    pre_log: str,
    post_log: str | None,
) -> None:
    """Persist Stage A/B pytest output — otherwise post_log is truncated to 4000 chars and discarded on skip."""
    try:
        _DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
        target = _DEBUG_LOG_DIR / f"{test_filename}.log"
        body = [
            f"reason: {reason}",
            f"timestamp: {datetime.now(UTC).isoformat()}",
            "",
            "===== STAGE A (test only, no oracle) =====",
            pre_log,
        ]
        if post_log is not None:
            body.extend(["", "===== STAGE B (test + oracle) =====", post_log])
        target.write_text("\n".join(body) + "\n", encoding="utf-8")
        logger.warning("code_instruct: failure log -> %s", target)
    except OSError as exc:
        logger.warning("code_instruct: could not write failure log (%s)", exc)


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _VerifyOutcome:
    accepted: bool = False
    reason: str = ""
    pre_log: str = ""
    post_log: str = ""


def build_code_instruct_dockerfile(bootstrap_image: str, *, aws_mode: bool = False) -> str:
    """Per-task Dockerfile: FROM bootstrap + defensive git install. HEAD state.

    Unlike pr_runtime / mutation_bugs, code_instruct adds NEW files at
    test time. The grading test ships as a plain file under tests/ (via
    HarborTask.aux_files) and test.sh copies it into /workspace before
    pytest runs, so every agent (not just oracle) can be graded. The
    gold solution/patch.diff carries only `task_module.py`.

    When ``aws_mode`` is true, additional layers install moto[all,server],
    boto3, and AWS CLI v2. v1 is rejected explicitly (it silently ignores
    ``AWS_ENDPOINT_URL`` and would leak traffic to real AWS).
    """
    base = (
        f"# Auto-generated by Repo2RLEnv code_instruct\n"
        f"FROM {bootstrap_image}\n"
        f'ARG HTTP_PROXY=""\n'
        f'ARG HTTPS_PROXY=""\n'
        f'ARG NO_PROXY="localhost,127.0.0.1,::1"\n'
        f'ARG CA_CERT_PATH="/etc/ssl/certs/ca-certificates.crt"\n'
        f"ENV HTTP_PROXY=${{HTTP_PROXY}} \\\n"
        f"    HTTPS_PROXY=${{HTTPS_PROXY}} \\\n"
        f"    NO_PROXY=${{NO_PROXY}} \\\n"
        f"    http_proxy=${{HTTP_PROXY}} \\\n"
        f"    https_proxy=${{HTTPS_PROXY}} \\\n"
        f"    no_proxy=${{NO_PROXY}} \\\n"
        f"    SSL_CERT_FILE=${{CA_CERT_PATH}} \\\n"
        f"    REQUESTS_CA_BUNDLE=${{CA_CERT_PATH}} \\\n"
        f"    CURL_CA_BUNDLE=${{CA_CERT_PATH}}\n"
        f"WORKDIR /workspace\n"
        f"RUN command -v git >/dev/null 2>&1 || \\\n"
        f"    (apt-get update && apt-get install -y --no-install-recommends git \\\n"
        f"     && rm -rf /var/lib/apt/lists/*) || \\\n"
        f"    apk add --no-cache git || true\n"
        f"RUN git config --global --add safe.directory /workspace\n"
    )
    if not aws_mode:
        return base
    return base + (
        "# AWS mode: moto + boto3 + aws-cli v2\n"
        "RUN (apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \\\n"
        "     && rm -rf /var/lib/apt/lists/*) || \\\n"
        "    apk add --no-cache curl unzip ca-certificates || true\n"
        "RUN pip install --no-cache-dir 'moto[all,server]>=5.0' 'boto3>=1.34' pytest\n"
        "RUN set -e; \\\n"
        '    arch="$(uname -m)"; \\\n'
        '    case "$arch" in \\\n'
        "      x86_64|amd64) cli_arch=x86_64 ;; \\\n"
        "      aarch64|arm64) cli_arch=aarch64 ;; \\\n"
        '      *) echo "aws_mode: unsupported arch $arch" >&2; exit 1 ;; \\\n'
        "    esac; \\\n"
        f'    url="https://awscli.amazonaws.com/awscli-exe-linux-${{cli_arch}}-{_AWS_CLI_VERSION}.zip"; \\\n'
        '    curl -sSL "$url" -o /tmp/awscli.zip; \\\n'
        "    unzip -q /tmp/awscli.zip -d /tmp; \\\n"
        "    /tmp/aws/install; \\\n"
        "    rm -rf /tmp/awscli.zip /tmp/aws\n"
        "RUN aws --version\n"
    )


def build_aws_eval_script(test_cmds: list[str], *, language: str) -> str:
    del language
    test_block = " && ".join(test_cmds)
    return (
        "#!/bin/bash\n"
        "set -uxo pipefail\n"
        "cd /workspace\n"
        "mkdir -p /logs/verifier\n"
        'MOTO_PORT="${MOTO_PORT:-5000}"\n'
        'moto_server -H 127.0.0.1 -p "$MOTO_PORT" > /logs/verifier/moto.log 2>&1 &\n'
        "MOTO_PID=$!\n"
        "trap 'kill $MOTO_PID 2>/dev/null || true' EXIT\n"
        "for i in $(seq 1 20); do\n"
        '  (echo > /dev/tcp/127.0.0.1/"$MOTO_PORT") >/dev/null 2>&1 && break\n'
        "  sleep 0.5\n"
        "done\n"
        'if ! (echo > /dev/tcp/127.0.0.1/"$MOTO_PORT") >/dev/null 2>&1; then\n'
        "  cat /logs/verifier/moto.log >&2 2>/dev/null || true\n"
        "  echo 'moto_server failed to start; see /logs/verifier/moto.log' >&2\n"
        "  exit 99\n"
        "fi\n"
        'export AWS_ENDPOINT_URL="http://127.0.0.1:${MOTO_PORT}"\n'
        "export AWS_ACCESS_KEY_ID=testing\n"
        "export AWS_SECRET_ACCESS_KEY=testing\n"
        "export AWS_DEFAULT_REGION=us-east-1\n"
        "export AWS_SESSION_TOKEN=testing\n"
        "export AWS_EC2_METADATA_DISABLED=true\n"
        'curl -sX POST "${AWS_ENDPOINT_URL}/moto-api/reset" >/dev/null 2>&1 || true\n'
        f"echo {_AWS_CONFTEST_B64} | base64 -d > /workspace/conftest.py\n"
        f"( {test_block} ) > /logs/verifier/test_output.log 2>&1\n"
        "TEST_EXIT_CODE=$?\n"
        '[ "$TEST_EXIT_CODE" -eq 0 ] && echo "1.0" > /logs/verifier/reward.txt '
        '|| echo "0.0" > /logs/verifier/reward.txt\n'
        "exit $TEST_EXIT_CODE\n"
    )


class CodeInstructPipeline:
    """Repo-anchored OSS-Instruct with executable verifiers."""

    name: ClassVar[PipelineName] = PipelineName.CODE_INSTRUCT
    requires_bootstrap: ClassVar[bool] = True
    experimental: ClassVar[bool] = True
    supported_languages: ClassVar[frozenset[LanguageHint] | None] = frozenset(
        {LanguageHint.PYTHON, LanguageHint.GO}
    )

    def __init__(
        self,
        input: GenerationInput,
        options: CodeInstructOptions,
        bootstrap: BootstrapResult | None = None,
    ):
        # cli_app mode reads from clone + LLM and does NOT need a bootstrap
        # image (we build our own task image via the optional Docker gauntlet).
        _cli_app = getattr(options, "mode", "snippet") == "cli_app"
        if bootstrap is None and not _cli_app:
            raise RuntimeError(
                "code_instruct requires a BootstrapResult (set requires_bootstrap=True "
                "and let cmd_generate trigger it, or pass one explicitly)"
            )
        if input.llm is None:
            raise ValueError("code_instruct requires --llm (provider/model)")
        self._llm = input.llm
        self.input = input
        self.options = options
        self.bootstrap = bootstrap
        self._progress_cb = None
        self._llm_cost_usd = 0.0
        self._backend: LanguageBackend | None = (
            get_backend(bootstrap.language) if bootstrap is not None else None
        )
        if self._backend is not None:
            _defaults = CodeInstructOptions()
            if options.file_glob == _defaults.file_glob:
                options.file_glob = self._backend.default_file_glob
            if options.exclude_glob == _defaults.exclude_glob:
                options.exclude_glob = list(self._backend.default_exclude_globs)

    def set_progress_callback(self, cb) -> None:
        self._progress_cb = cb

    def _emit_progress(self, name: str, outcome: str, reason: str = "") -> None:
        if self._progress_cb is not None:
            try:
                self._progress_cb(name=name, outcome=outcome, reason=reason)
            except Exception as exc:
                logger.debug("progress callback failed: %s", exc)

    # ----- run loop -----------------------------------------------------------

    def run(self, out_dir: Path) -> PipelineResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        # cli_app mode dispatches to a sibling module — snippet code below
        # is byte-identical for mode="snippet" (the default).
        if getattr(self.options, "mode", "snippet") == "cli_app":
            from repo2rlenv.pipelines._cli_app_synthesis import run_cli_app_pipeline

            return run_cli_app_pipeline(self, self.options, out_dir)
        token = resolve_github_token(self.input.repo, self.input.auth)
        if self.input.repo.access == "private" and not token:
            raise RuntimeError(
                "private repo specified but no GitHub token resolved. "
                "Run `gh auth login` or set GITHUB_TOKEN."
            )

        owner, name = self.input.repo.owner_name
        owner_name = f"{owner}/{name}"
        rng = random.Random(self.options.seed) if self.options.seed is not None else random.Random()

        skip_reasons: dict[str, int] = {}
        emitted = 0
        candidates_seen = 0
        sandbox = None

        with tempfile.TemporaryDirectory(prefix="r2e-code-instruct-") as tmp:
            clone_dir = Path(tmp) / "repo"
            try:
                _shallow_clone_at_ref(
                    self.input.repo.url, self.input.repo.ref, token, clone_dir, depth=1
                )
            except Exception as exc:
                raise RuntimeError(f"failed to clone {self.input.repo.url}: {exc}") from exc

            source_files = list_source_files(
                clone_dir,
                file_glob=self.options.file_glob,
                exclude_glob=self.options.exclude_glob,
            )
            logger.info("code_instruct: %d candidate source files", len(source_files))

            try:
                if not self.options.skip_validation:
                    sandbox = self._start_sandbox()

                while emitted < self.options.limit:
                    if candidates_seen >= self.options.limit * 5:
                        # Avoid spinning forever on a repo that resists synthesis
                        logger.info(
                            "code_instruct: candidate budget exhausted (seen=%d, emitted=%d)",
                            candidates_seen,
                            emitted,
                        )
                        break
                    if (
                        self.options.max_llm_spend_usd is not None
                        and self._llm_cost_usd >= self.options.max_llm_spend_usd
                    ):
                        logger.warning(
                            "code_instruct: LLM spend cap reached "
                            "($%.4f >= $%.4f); halting (emitted=%d)",
                            self._llm_cost_usd,
                            self.options.max_llm_spend_usd,
                            emitted,
                        )
                        skip_reasons["llm_budget_exceeded"] = (
                            skip_reasons.get("llm_budget_exceeded", 0) + 1
                        )
                        break
                    candidates_seen += 1
                    seed = sample_seed(
                        source_files,
                        clone_dir,
                        rng=rng,
                        min_loc=self.options.seed_min_loc,
                        max_loc=self.options.seed_max_loc,
                    )
                    if seed is None:
                        skip_reasons["no_seed"] = skip_reasons.get("no_seed", 0) + 1
                        continue
                    label = f"{owner_name}:{seed.relative_path}#{seed.start_line}-{seed.end_line}"

                    parsed = self._llm_synthesize(seed)
                    if parsed is None:
                        skip_reasons["llm_parse_failed"] = (
                            skip_reasons.get("llm_parse_failed", 0) + 1
                        )
                        self._emit_progress(label, "skip", "llm_parse_failed")
                        continue

                    # Decontamination
                    if not self.options.skip_decontamination:
                        joined = parsed.problem + "\n" + parsed.solution_code
                        if has_benchmark_overlap(joined):
                            skip_reasons["benchmark_overlap"] = (
                                skip_reasons.get("benchmark_overlap", 0) + 1
                            )
                            self._emit_progress(label, "skip", "benchmark_overlap")
                            continue
                        if solution_leaks_into_problem(parsed.problem, parsed.solution_code):
                            skip_reasons["solution_leaks_into_problem"] = (
                                skip_reasons.get("solution_leaks_into_problem", 0) + 1
                            )
                            self._emit_progress(label, "skip", "solution_leaks_into_problem")
                            continue

                    assert self._backend is not None
                    # Syntactic: test must reference task_module
                    if not self._backend.test_references_task_module(parsed.test_code):
                        skip_reasons["test_does_not_use_task_module"] = (
                            skip_reasons.get("test_does_not_use_task_module", 0) + 1
                        )
                        self._emit_progress(label, "skip", "test_does_not_use_task_module")
                        continue

                    # Runtime delivery requires `from task_module import <name>` form:
                    # the router shim matches by name against agent-modified files. A
                    # bare `import task_module` test yields no names → router cannot
                    # synthesize task_module.py → silent reward 0 for every agent.
                    expected_names = self._backend.extract_task_module_imports(parsed.test_code)
                    if not expected_names:
                        skip_reasons["test_uses_bare_module_import"] = (
                            skip_reasons.get("test_uses_bare_module_import", 0) + 1
                        )
                        self._emit_progress(label, "skip", "test_uses_bare_module_import")
                        continue

                    # aws_mode: skip synthesized tasks that don't actually use AWS
                    if self.options.aws_mode and not _references_aws(
                        parsed.test_code, parsed.solution_code
                    ):
                        skip_reasons["aws_mode_test_does_not_use_aws"] = (
                            skip_reasons.get("aws_mode_test_does_not_use_aws", 0) + 1
                        )
                        self._emit_progress(label, "skip", "aws_mode_test_does_not_use_aws")
                        continue

                    # Sandbox verification
                    content_hash = self._compute_content_hash(seed, parsed)
                    delivery = self._backend.build_sandbox_delivery(
                        task_module_code=parsed.solution_code,
                        test_code=parsed.test_code,
                        expected_names=expected_names,
                        test_hash=content_hash[:10],
                    )
                    if not self.options.skip_validation:
                        outcome = self._verify_task(sandbox, parsed, delivery=delivery)
                        if not outcome.accepted:
                            skip_reasons[outcome.reason] = skip_reasons.get(outcome.reason, 0) + 1
                            self._emit_progress(label, "skip", outcome.reason)
                            continue

                    # Emit
                    task = self._build_task(
                        seed,
                        parsed,
                        delivery=delivery,
                        content_hash=content_hash,
                    )
                    write_harbor_task(task, out_dir)
                    emitted += 1
                    logger.info("emitted task %s (seed=%s)", task.name, seed.relative_path)
                    self._emit_progress(task.name, "emit")
            finally:
                if sandbox is not None:
                    sandbox.cleanup()
                shutil.rmtree(clone_dir, ignore_errors=True)

        return PipelineResult(
            candidates=candidates_seen,
            emitted=emitted,
            skipped=sum(skip_reasons.values()),
            out_dir=out_dir,
            skip_reasons=skip_reasons,
        )

    # ----- LLM ---------------------------------------------------------------

    def _llm_synthesize(self, seed: Seed) -> ParsedTask | None:
        assert self._backend is not None
        system, user = self._backend.render_prompts(seed, aws_mode=self.options.aws_mode)
        try:
            resp = complete(
                self._llm,
                system=system,
                user=user,
                max_tokens=self.options.max_llm_tokens,
                temperature=self.options.llm_temperature,
            )
        except Exception as exc:
            logger.warning("code_instruct LLM call failed: %s", exc)
            return None
        self._llm_cost_usd += resp.cost_usd
        parsed = parse_task_response(resp.content)
        if parsed is None:
            return None
        parsed.test_code = self._backend.parse_solution_block(parsed.test_code)
        parsed.solution_code = self._backend.parse_solution_block(parsed.solution_code)
        return parsed

    # ----- sandbox -----------------------------------------------------------

    def _start_sandbox(self):
        assert self.bootstrap is not None
        assert self._backend is not None
        from repo2rlenv.bootstrap.docker import DockerSandbox

        marker = Path(tempfile.mkdtemp(prefix="r2e-code-instruct-"))
        (marker / ".keep").write_text("")
        sandbox = DockerSandbox.start(
            base_image=self.bootstrap.image_tag,
            repo_dir=marker,
            platform=self.input.bootstrap.platform,
        )
        self._backend.sandbox_prep(sandbox)
        if self.options.aws_mode:
            logger.info("code_instruct: installing moto+boto3 into verification sandbox")
            install = sandbox.exec(
                "pip install --no-cache-dir 'moto[all,server]>=5.0' 'boto3>=1.34' pytest",
                timeout=600,
            )
            if not install.ok:
                output = install.truncated(max_chars=2000)
                sandbox.cleanup()
                raise RuntimeError(
                    "failed to install moto/boto3 into verification sandbox; "
                    "aws_mode candidates cannot be verified.\n" + output
                )
        return sandbox

    def _verify_task(
        self,
        sandbox,
        parsed: ParsedTask,
        *,
        delivery: SandboxDelivery,
    ) -> _VerifyOutcome:
        """Two-stage verification — Stage B exercises the runtime router path.

        Stage A: write only the test file, run test → must NOT pass.
        Stage B: write solution under a non-canonical name, run the SAME
                 router shim that ships in the emitted task, then run the
                 test → must pass. Catches router/name-extraction bugs at
                 synthesis time instead of in production.
        """
        assert self._backend is not None
        enc_test = base64.b64encode(parsed.test_code.encode("utf-8")).decode("ascii")
        enc_solution = base64.b64encode(parsed.solution_code.encode("utf-8")).decode("ascii")
        conftest_write = (
            f"echo {_AWS_CONFTEST_B64} | base64 -d > /workspace/conftest.py\n"
            if self.options.aws_mode
            else ""
        )
        moto_preamble = _aws_verify_preamble() if self.options.aws_mode else ""
        cleanup_line = "rm -f " + " ".join(delivery.cleanup_files) + " || true\n"

        # Stage A — test only, no oracle
        script_a = (
            "set -uxo pipefail\n"
            "cd /workspace\n"
            + moto_preamble
            + "git config --global --add safe.directory /workspace\n"
            "git reset --hard HEAD\n"
            "git clean -fdx -e .venv -e venv -e __pycache__ || true\n"
            + cleanup_line
            + conftest_write
            + f"echo {enc_test} | base64 -d > {delivery.test_filename}\n"
            ": 'START_TEST_OUTPUT'\n"
            f"{delivery.test_invocation} || true\n"
            ": 'END_TEST_OUTPUT'\n"
        )
        a = sandbox.exec(script_a, timeout=self.options.validation_timeout_sec)
        pre_log = a.truncated(max_chars=4000)
        if self.options.aws_mode and "R2E_MOTO_SERVER_UNAVAILABLE" in pre_log:
            _dump_failure_log(
                delivery.test_filename,
                "moto_server_unavailable",
                pre_log=pre_log,
                post_log=None,
            )
            return _VerifyOutcome(accepted=False, reason="moto_server_unavailable", pre_log=pre_log)
        pre_verdict = self._backend.stage_a_verdict(pre_log, a.exit_code)
        if self.options.require_test_fails_without_oracle and pre_verdict == "test_pass":
            _dump_failure_log(
                delivery.test_filename,
                "test_passes_without_oracle",
                pre_log=pre_log,
                post_log=None,
            )
            return _VerifyOutcome(
                accepted=False, reason="test_passes_without_oracle", pre_log=pre_log
            )

        # Stage B — write solution under a non-canonical name and let the
        # router shim synthesise the task module. This is the EXACT path the
        # emitted task takes at runtime.
        script_b = (
            "set -uxo pipefail\n"
            "cd /workspace\n"
            + moto_preamble
            + conftest_write
            + f"echo {enc_solution} | base64 -d > r2e_solution\n"
            + f"{delivery.router_shim}\n"
            ": 'START_TEST_OUTPUT'\n"
            f"{delivery.test_invocation}\n"
            ": 'END_TEST_OUTPUT'\n" + cleanup_line
        )
        b = sandbox.exec(script_b, timeout=self.options.validation_timeout_sec)
        post_log = b.truncated(max_chars=4000)
        if self.options.aws_mode and "R2E_MOTO_SERVER_UNAVAILABLE" in post_log:
            _dump_failure_log(
                delivery.test_filename,
                "moto_server_unavailable",
                pre_log=pre_log,
                post_log=post_log,
            )
            return _VerifyOutcome(
                accepted=False,
                reason="moto_server_unavailable",
                pre_log=pre_log,
                post_log=post_log,
            )
        post_verdict = self._backend.stage_b_verdict(post_log, b.exit_code)
        if self.options.require_test_passes_with_oracle and post_verdict != "test_pass":
            _dump_failure_log(
                delivery.test_filename,
                "oracle_does_not_satisfy_test",
                pre_log=pre_log,
                post_log=post_log,
            )
            return _VerifyOutcome(
                accepted=False,
                reason="oracle_does_not_satisfy_test",
                pre_log=pre_log,
                post_log=post_log,
            )

        return _VerifyOutcome(accepted=True, pre_log=pre_log, post_log=post_log)

    # ----- task builder -------------------------------------------------------

    def _compute_content_hash(self, seed: Seed, parsed: ParsedTask) -> str:
        h = hashlib.sha256()
        h.update(seed.relative_path.encode())
        h.update(b"\0")
        h.update(str(seed.start_line).encode())
        h.update(b"\0")
        h.update(parsed.problem.encode())
        return h.hexdigest()

    def _build_task(
        self,
        seed: Seed,
        parsed: ParsedTask,
        *,
        delivery: SandboxDelivery,
        content_hash: str,
    ) -> HarborTask:
        assert self.bootstrap is not None
        assert self._backend is not None
        owner, name = self.input.repo.owner_name
        task_id = f"{owner}__{name}-cinst-{content_hash[:8]}"

        gold_diff = delivery.solution_diff

        # The verifier runs the synthesized test file specifically (NOT the
        # bootstrap's recorded test_cmds — those are for the original suite).
        # Harbor mounts tests/ at /tests for every agent (oracle or not);
        # the router shim (between placement and test invocation) synthesises
        # the task module at runtime from whatever file the agent created,
        # so the agent isn't forced to use the canonical filename.
        eval_builder = (
            build_aws_eval_script if self.options.aws_mode else build_mutation_eval_script
        )
        eval_script = eval_builder(
            [
                delivery.test_placement_cmd,
                delivery.router_shim,
                delivery.test_invocation,
            ],
            language=self.bootstrap.language.value,
        )
        image_ref = (
            self.bootstrap.image_digest
            if self.bootstrap.pushed_to_registry
            else self.bootstrap.image_tag
        )
        dockerfile = build_code_instruct_dockerfile(image_ref, aws_mode=self.options.aws_mode)
        extra_layers = self._backend.dockerfile_extra_layers()
        if extra_layers:
            dockerfile = dockerfile.rstrip() + "\n" + extra_layers

        repo2env = {
            "pipeline": "code_instruct",
            "pipeline_version": repo2rlenv.__version__,
            "repo": f"{owner}/{name}",
            "ref": self.input.repo.ref,
            "reference": (
                f"https://github.com/{owner}/{name}/blob/{self.input.repo.ref}/"
                f"{seed.relative_path}#L{seed.start_line}-L{seed.end_line}"
            ),
            "source_access": self.input.repo.access,
            "built_at": datetime.now(UTC).isoformat(),
            "synthesis_llm": self._llm.qualified_name,
            "reward_kinds": ["test_execution"],
            "language": self.bootstrap.language.value,
            "code_instruct": {
                "seed_path": seed.relative_path,
                "seed_start_line": seed.start_line,
                "seed_end_line": seed.end_line,
                "test_filename": delivery.test_filename,
                "bootstrap_image": self.bootstrap.image_digest,
                "llm_cost_usd": round(self._llm_cost_usd, 6),
            },
        }

        return HarborTask(
            name=task_id,
            org=self.input.output.org,
            description=parsed.problem.split("\n", 1)[0],
            instruction=parsed.problem,
            oracle_diff=gold_diff,
            repo2env=repo2env,
            difficulty="medium",
            category="feature",
            keywords=[name, "code_instruct"],
            environment_dockerfile=dockerfile,
            test_script=eval_script,
            aux_files={delivery.test_file_relpath: parsed.test_code},
            task_uuid=str(uuid4()),
        )
