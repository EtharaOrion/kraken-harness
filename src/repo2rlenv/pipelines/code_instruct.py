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

import repo2rlenv
from repo2rlenv.auth import resolve_github_token
from repo2rlenv.bootstrap.runner import _shallow_clone_at_ref
from repo2rlenv.bootstrap.spec import BootstrapResult, LanguageHint
from repo2rlenv.emitter.harbor import HarborTask, write_harbor_task
from repo2rlenv.llm import complete
from repo2rlenv.pipelines._oss_instruct import (
    PROMPT_SYSTEM,
    PROMPT_USER_TEMPLATE,
    ParsedTask,
    Seed,
    extract_task_module_imports,
    has_benchmark_overlap,
    list_source_files,
    parse_task_response,
    references_task_module,
    sample_seed,
)
from repo2rlenv.pipelines.base import PipelineResult
from repo2rlenv.pipelines.mutation_bugs import build_mutation_eval_script
from repo2rlenv.spec.input import GenerationInput, PipelineName
from repo2rlenv.spec.options import CodeInstructOptions

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _VerifyOutcome:
    accepted: bool = False
    reason: str = ""
    pre_log: str = ""
    post_log: str = ""


def _make_solution_diff(*, task_module_code: str) -> str:
    """Gold patch creating only `task_module.py` at the repo root.

    The synthesized grading test is NOT bundled here: Harbor stages
    solution/ inside the container only for the OracleAgent, so anything
    placed in this patch is invisible to every non-oracle agent. The test
    file is shipped under tests/ via HarborTask.aux_files instead, and
    test.sh copies it into /workspace before pytest runs.

    Raises ValueError on empty/whitespace input — a 0-line hunk produces
    `@@ -0,0 +1,0 @@` which `git apply` rejects as corrupt.
    """
    if not task_module_code or not task_module_code.strip():
        raise ValueError("task_module_code is empty; cannot synthesise gold patch")
    lines = task_module_code.splitlines()
    n = len(lines)
    header = (
        "diff --git a/task_module.py b/task_module.py\n"
        "new file mode 100644\n"
        "index 0000000..0000001\n"
        "--- /dev/null\n"
        "+++ b/task_module.py\n"
        f"@@ -0,0 +1,{n} @@\n"
    )
    body = "".join(f"+{ln}\n" for ln in lines)
    if not task_module_code.endswith("\n"):
        body += "\\ No newline at end of file\n"
    return header + body


_TASK_MODULE_ROUTER_PY = r"""
import ast
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(os.environ.get("R2E_ROUTER_ROOT", "/workspace"))
TARGET = ROOT / "task_module.py"
if TARGET.exists():
    sys.exit(0)

NAMES = __NAMES__
try:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard", "--modified"],
        capture_output=True, text=True, check=False, timeout=15,
    )
    rel_paths = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip().endswith(".py")]
except Exception:
    rel_paths = []

for rel in rel_paths:
    p = ROOT / rel
    if not p.is_file():
        continue
    if p.name in ("task_module.py", "conftest.py"):
        continue
    if p.name.startswith("test_") or p.name.endswith("_test.py"):
        continue
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        continue
    # Top-level defs only: `from <mod> import *` does not expose nested names,
    # so a nested method named `render_frames` is NOT a valid routing target.
    defs = {n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    matched = sorted(set(NAMES) & defs)
    if matched:
        mod = pathlib.Path(rel).with_suffix("").as_posix().replace("/", ".")
        TARGET.write_text("from " + mod + " import *\n")
        sys.stderr.write("[task_module_router] -> " + mod + " (matched=" + repr(matched) + ")\n")
        break

sys.exit(0)
""".strip()


def _build_task_module_router(expected_names: list[str]) -> str:
    """Return a SINGLE shell command that synthesises `task_module.py` at runtime.

    Baked into `tests/test.sh` between the test-file copy and the pytest
    invocation. Reads agent-added files via `git ls-files --others
    --exclude-standard --modified` so it never picks up the repo's own
    pre-existing code (the bootstrap image clones the target repo into
    /workspace; aws-cli for example has thousands of .py files). Always
    exits 0 — if no agent file defines any expected name, pytest will
    fail naturally with ModuleNotFoundError and the agent earns reward 0.

    Single-line output (no embedded newlines) so it composes safely with
    `build_mutation_eval_script`'s ` && ` joiner.
    """
    import base64

    names = sorted({n for n in expected_names if n.isidentifier()})
    py = _TASK_MODULE_ROUTER_PY.replace("__NAMES__", repr(names))
    enc = base64.b64encode(py.encode("utf-8")).decode("ascii")
    return f"echo {enc} | base64 -d | python3 -"


def build_code_instruct_dockerfile(bootstrap_image: str) -> str:
    """Per-task Dockerfile: FROM bootstrap + defensive git install. HEAD state.

    Unlike pr_runtime / mutation_bugs, code_instruct adds NEW files at
    test time. The grading test ships as a plain file under tests/ (via
    HarborTask.aux_files) and test.sh copies it into /workspace before
    pytest runs, so every agent (not just oracle) can be graded. The
    gold solution/patch.diff carries only `task_module.py`.
    """
    return (
        f"# Auto-generated by Repo2RLEnv code_instruct\n"
        f"FROM {bootstrap_image}\n"
        f"WORKDIR /workspace\n"
        f"RUN command -v git >/dev/null 2>&1 || \\\n"
        f"    (apt-get update && apt-get install -y --no-install-recommends git \\\n"
        f"     && rm -rf /var/lib/apt/lists/*) || \\\n"
        f"    apk add --no-cache git || true\n"
        f"RUN git config --global --add safe.directory /workspace\n"
    )


class CodeInstructPipeline:
    """Repo-anchored OSS-Instruct with executable verifiers."""

    name: ClassVar[PipelineName] = PipelineName.CODE_INSTRUCT
    requires_bootstrap: ClassVar[bool] = True
    experimental: ClassVar[bool] = True
    supported_languages: ClassVar[frozenset[LanguageHint] | None] = frozenset({LanguageHint.PYTHON})

    def __init__(
        self,
        input: GenerationInput,
        options: CodeInstructOptions,
        bootstrap: BootstrapResult | None = None,
    ):
        if bootstrap is None:
            raise RuntimeError(
                "code_instruct requires a BootstrapResult (set requires_bootstrap=True "
                "and let cmd_generate trigger it, or pass one explicitly)"
            )
        if input.llm is None:
            raise ValueError("code_instruct requires --llm (provider/model)")
        self.input = input
        self.options = options
        self.bootstrap = bootstrap
        self._progress_cb = None
        self._llm_cost_usd = 0.0

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

                    # Syntactic: test must reference task_module
                    if not references_task_module(parsed.test_code):
                        skip_reasons["test_does_not_use_task_module"] = (
                            skip_reasons.get("test_does_not_use_task_module", 0) + 1
                        )
                        self._emit_progress(label, "skip", "test_does_not_use_task_module")
                        continue

                    # Runtime delivery requires `from task_module import <name>` form:
                    # the router shim matches by name against agent-modified files. A
                    # bare `import task_module` test yields no names → router cannot
                    # synthesize task_module.py → silent reward 0 for every agent.
                    expected_names = extract_task_module_imports(parsed.test_code)
                    if not expected_names:
                        skip_reasons["test_uses_bare_module_import"] = (
                            skip_reasons.get("test_uses_bare_module_import", 0) + 1
                        )
                        self._emit_progress(label, "skip", "test_uses_bare_module_import")
                        continue

                    # Sandbox verification
                    test_filename = self._task_test_filename(seed, parsed)
                    if not self.options.skip_validation:
                        outcome = self._verify_task(
                            sandbox,
                            parsed,
                            test_filename=test_filename,
                            expected_names=expected_names,
                        )
                        if not outcome.accepted:
                            skip_reasons[outcome.reason] = skip_reasons.get(outcome.reason, 0) + 1
                            self._emit_progress(label, "skip", outcome.reason)
                            continue

                    # Emit
                    task = self._build_task(
                        seed,
                        parsed,
                        test_filename=test_filename,
                        expected_names=expected_names,
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
        user = PROMPT_USER_TEMPLATE.format(
            path=seed.relative_path,
            start=seed.start_line,
            end=seed.end_line,
            snippet=seed.text,
        )
        try:
            resp = complete(
                self.input.llm,
                system=PROMPT_SYSTEM,
                user=user,
                max_tokens=self.options.max_llm_tokens,
                temperature=self.options.llm_temperature,
            )
        except Exception as exc:
            logger.warning("code_instruct LLM call failed: %s", exc)
            return None
        self._llm_cost_usd += resp.cost_usd
        return parse_task_response(resp.content)

    # ----- sandbox -----------------------------------------------------------

    def _start_sandbox(self):
        from repo2rlenv.bootstrap.docker import DockerSandbox

        marker = Path(tempfile.mkdtemp(prefix="r2e-code-instruct-"))
        (marker / ".keep").write_text("")
        return DockerSandbox.start(
            base_image=self.bootstrap.image_tag,
            repo_dir=marker,
            platform=self.input.bootstrap.platform,
        )

    def _verify_task(
        self,
        sandbox,
        parsed: ParsedTask,
        *,
        test_filename: str,
        expected_names: list[str],
    ) -> _VerifyOutcome:
        """Two-stage verification — Stage B exercises the runtime router path.

        Stage A: write only the test file, run pytest → must NOT pass.
        Stage B: write solution to a NON-`task_module.py` filename, run the
                 SAME router shim that ships in the emitted task, then run
                 pytest → must pass. This catches router/name-extraction
                 bugs at synthesis time instead of in production.
        """
        enc_test = base64.b64encode(parsed.test_code.encode("utf-8")).decode("ascii")
        enc_solution = base64.b64encode(parsed.solution_code.encode("utf-8")).decode("ascii")
        router_cmd = _build_task_module_router(expected_names)

        # Stage A — test only, no oracle
        script_a = (
            "set -uxo pipefail\n"
            "cd /workspace\n"
            "git config --global --add safe.directory /workspace\n"
            "git reset --hard HEAD\n"
            "git clean -fdx -e .venv -e venv -e __pycache__ || true\n"
            "rm -f task_module.py task_module.pyc r2e_solution.py || true\n"
            f"echo {enc_test} | base64 -d > {test_filename}\n"
            ": 'START_TEST_OUTPUT'\n"
            f"python -m pytest {test_filename} -v --no-header || true\n"
            ": 'END_TEST_OUTPUT'\n"
        )
        a = sandbox.exec(script_a, timeout=self.options.validation_timeout_sec)
        pre_log = a.truncated(max_chars=4000)
        # The wrapper uses `|| true` so sandbox.exec succeeds regardless;
        # we parse the pytest summary line to decide pass/fail.
        pre_passed = _all_tests_passed(pre_log)
        if self.options.require_test_fails_without_oracle and pre_passed:
            return _VerifyOutcome(
                accepted=False, reason="test_passes_without_oracle", pre_log=pre_log
            )

        # Stage B — write solution under a non-canonical name and let the
        # router shim synthesise task_module.py. This is the EXACT path the
        # emitted task takes at runtime: a bug in name extraction or in the
        # router's git-ls-files scan surfaces here, not in production.
        script_b = (
            "set -uxo pipefail\n"
            "cd /workspace\n"
            f"echo {enc_solution} | base64 -d > r2e_solution.py\n"
            f"{router_cmd}\n"
            ": 'START_TEST_OUTPUT'\n"
            f"python -m pytest {test_filename} -v --no-header\n"
            ": 'END_TEST_OUTPUT'\n"
            f"rm -f task_module.py r2e_solution.py {test_filename}\n"
        )
        b = sandbox.exec(script_b, timeout=self.options.validation_timeout_sec)
        post_log = b.truncated(max_chars=4000)
        post_passed = b.ok and _all_tests_passed(post_log)
        if self.options.require_test_passes_with_oracle and not post_passed:
            return _VerifyOutcome(
                accepted=False,
                reason="oracle_does_not_satisfy_test",
                pre_log=pre_log,
                post_log=post_log,
            )

        return _VerifyOutcome(accepted=True, pre_log=pre_log, post_log=post_log)

    # ----- task builder -------------------------------------------------------

    def _task_test_filename(self, seed: Seed, parsed: ParsedTask) -> str:
        """Content-derived filename — pytest discovers it by `test_*.py` glob."""
        h = hashlib.sha256()
        h.update(seed.relative_path.encode())
        h.update(b"\0")
        h.update(str(seed.start_line).encode())
        h.update(b"\0")
        h.update(parsed.problem.encode())
        return f"test_r2e_{h.hexdigest()[:10]}.py"

    def _build_task(
        self,
        seed: Seed,
        parsed: ParsedTask,
        *,
        test_filename: str,
        expected_names: list[str],
    ) -> HarborTask:
        owner, name = self.input.repo.owner_name
        h = hashlib.sha256()
        h.update(seed.relative_path.encode())
        h.update(b"\0")
        h.update(str(seed.start_line).encode())
        h.update(b"\0")
        h.update(parsed.problem.encode())
        task_id = f"{owner}__{name}-cinst-{h.hexdigest()[:8]}"

        gold_diff = _make_solution_diff(task_module_code=parsed.solution_code)

        # Harbor mounts tests/ at /tests for every agent (oracle or not);
        # we copy the synthesized test into /workspace so pytest finds it.
        # The router shim (between cp and pytest) synthesises task_module.py
        # at runtime from whatever file the agent created, so the agent
        # isn't forced to use the literal filename `task_module.py`.
        eval_script = build_mutation_eval_script(
            [
                f"cp /tests/{test_filename} /workspace/",
                _build_task_module_router(expected_names),
                f"python -m pytest {test_filename} -v --no-header",
            ],
            language=self.bootstrap.language.value,
        )
        image_ref = (
            self.bootstrap.image_digest
            if self.bootstrap.pushed_to_registry
            else self.bootstrap.image_tag
        )
        dockerfile = build_code_instruct_dockerfile(image_ref)

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
            "synthesis_llm": self.input.llm.qualified_name,
            "reward_kinds": ["test_execution"],
            "code_instruct": {
                "seed_path": seed.relative_path,
                "seed_start_line": seed.start_line,
                "seed_end_line": seed.end_line,
                "test_filename": test_filename,
                "bootstrap_image": self.bootstrap.image_digest,
                "llm_cost_usd": round(self._llm_cost_usd, 6),
            },
        }

        return HarborTask(
            name=task_id,
            org=self.input.output.org,
            description=parsed.problem.split("\n", 1)[0][:120],
            instruction=parsed.problem,
            oracle_diff=gold_diff,
            repo2env=repo2env,
            difficulty="medium",
            category="feature",
            keywords=[name, "code_instruct"],
            environment_dockerfile=dockerfile,
            test_script=eval_script,
            aux_files={f"tests/{test_filename}": parsed.test_code},
        )


def _all_tests_passed(log: str) -> bool:
    """Heuristic: pytest summary line shows `N passed` and zero failed/errored.

    Rejects on any of: collection error, `>=1 failed`, `>=1 error(s)`. The
    `error` token is critical — pytest reports collection/setup failures
    separately from assertion failures, and treating an `errors+passed`
    line as success accepts a broken verifier (regression for review S1).
    """
    import re as _re

    lower = log.lower()
    if "collected 0 items" in lower:
        return False
    if _re.search(r"\b[1-9]\d*\s+failed\b", lower):
        return False
    if _re.search(r"\b[1-9]\d*\s+errors?\b", lower):
        return False
    return bool(_re.search(r"\b[1-9]\d*\s+passed\b", lower))
