"""Protocol + SandboxDelivery dataclass for per-language code_instruct backends.

This module defines the *contract* between the language-agnostic
`code_instruct` pipeline and per-language adapters. It intentionally holds
NO logic — implementations live in sibling modules (`python.py`, `go.py`, ...)
and register themselves via `_code_instruct_backends.register_backend`.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol

from repo2rlenv.bootstrap.spec import LanguageHint

if TYPE_CHECKING:
    from repo2rlenv.bootstrap.docker import DockerSandbox
    from repo2rlenv.pipelines._oss_instruct import Seed


@dataclass(frozen=True)
class SandboxDelivery:
    """Everything the sandbox needs for one Stage A/B verification cycle.

    Invariants MUST hold across fields:
      - `router_shim` produces a file at a path that `test_invocation` will
        exercise AND `cleanup_files` removes (so Stage A vs Stage B stays clean).
      - `test_file_relpath` is where in the repo the test file lives (relative
        to repo root); router_shim / test_invocation reference the same path.
      - `solution_diff` is the unified-diff patch applied at Stage B; Stage A
        runs without it. Both stages exercise `test_invocation`.
      - `cleanup_files` MUST list every path the shim/tests wrote so a fresh
        Stage A/B cycle starts from a clean tree.
    """

    solution_diff: str
    router_shim: str
    test_invocation: str
    cleanup_files: list[str]
    test_filename: str
    test_file_relpath: str
    test_placement_cmd: str


class LanguageBackend(Protocol):
    """Per-language adapter for the code_instruct pipeline.

    IMPLEMENTORS MUST maintain these co-varying invariants:
      - The code-fence language in `render_prompts` output MUST match the fence
        that `parse_solution_block` accepts (e.g. ```python vs ```go). The
        `render_prompts(seed, aws_mode=...)` `aws_mode` kwarg is optional and
        defaults to False; backends without AWS support should ignore it.
      - The file path `build_sandbox_delivery`'s `router_shim` writes to MUST
        equal the path `test_invocation` runs in AND `cleanup_files` removes.
      - `test_references_task_module` MUST agree with `render_prompts`'s
        instructions to the LLM about how to import / reference the task
        module (import name, package path, etc).
      - `extract_task_module_imports` MUST return the *same* names/paths that
        `test_references_task_module` looks for — one is a boolean gate, the
        other is the list of resolved references; they share a definition.
      - `substantive_solution_lines` filters out non-code lines (blanks,
        comments, docstrings) so downstream heuristics compare like-for-like
        across languages.
      - `stage_a_verdict` / `stage_b_verdict` MUST return one of the four
        Literal tags — the pipeline routes on these exact strings.
      - `stage_a_verdict` MAY remap language-specific build errors caused by
        the missing solution (e.g. Go's `undefined: <symbol>` at compile
        time) to `test_fail` when that is the semantic equivalent of "the
        test detected that the solution is missing". Reserve `build_fail`
        at Stage A for genuine breakage of the test file itself.

    Class attributes:
      - `language`: the LanguageHint this backend serves.
      - `default_file_glob`: default seed-source glob (e.g. "**/*.py").
      - `default_exclude_globs`: default seed-source exclusions.
    """

    language: ClassVar[LanguageHint]
    default_file_glob: ClassVar[str]
    default_exclude_globs: ClassVar[tuple[str, ...]]

    def render_prompts(self, seed: "Seed", aws_mode: bool = False) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) for the OSS-Instruct call.

        When `aws_mode` is True, the system prompt instructs the LLM to
        exercise AWS via `aws` CLI v2 or `boto3` against a sandbox-provided
        moto endpoint. `aws_mode` is passed through by the pipeline from
        `CodeInstructOptions.aws_mode` — backends that do not support AWS
        should ignore the flag (or raise if the mode is unsupported).
        """
        ...

    def parse_solution_block(self, text: str) -> str:
        """Extract the solution code block from the LLM response text.

        Returns the extracted block, or the stripped input if no fence is
        found (backends MAY choose to raise on malformed input; the
        default extraction is lenient).
        """
        ...

    def test_references_task_module(self, test_code: str) -> bool:
        """True if the generated test code references the task module.

        Language-specific: Python looks for `from task_module import ...` or
        `import task_module`; Go looks for the package import path.
        """
        ...

    def extract_task_module_imports(self, test_code: str) -> list[str]:
        """Return the concrete symbols/paths the test imports from the task."""
        ...

    def substantive_solution_lines(self, solution_code: str) -> list[str]:
        """Return solution lines that carry semantic weight (drop blanks/comments)."""
        ...

    def build_sandbox_delivery(
        self,
        *,
        task_module_code: str,
        test_code: str,
        expected_names: list[str],
        test_hash: str,
    ) -> SandboxDelivery:
        """Bundle the artifacts the sandbox needs for one Stage A/B cycle.

        See `SandboxDelivery` docstring for the invariants that MUST hold
        across the returned fields.
        """
        ...

    def stage_a_verdict(
        self, log: str, exit_code: int
    ) -> Literal["build_fail", "test_fail", "test_pass", "unknown"]:
        """Classify Stage A (pre-patch) test-run outcome."""
        ...

    def stage_b_verdict(
        self, log: str, exit_code: int
    ) -> Literal["build_fail", "test_fail", "test_pass", "unknown"]:
        """Classify Stage B (post-patch) test-run outcome."""
        ...

    def sandbox_prep(self, sandbox: "DockerSandbox") -> None:
        """One-time prep inside the sandbox (install runners, seed files, ...)."""
        ...

    def dockerfile_extra_layers(self) -> str:
        """Extra Dockerfile lines to append into the per-task image build."""
        ...
