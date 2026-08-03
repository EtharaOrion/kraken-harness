"""Go language backend for the code_instruct pipeline.

Whitebox contract: both the LLM-emitted test file and the LLM-emitted
solution file declare `package task_module`, so the test can call
solution symbols directly without an import. The test module lives at
`/task_module/` — a sibling of `/workspace/` — to keep Go's upward
`go.mod` search from picking up the target repo's module (D1).

At Stage A the sandbox runs the tests without the solution present; a
Go build failure that names an undefined identifier is the semantic
equivalent of "the test detected that the solution is missing", so
`stage_a_verdict` remaps such `build_fail` outcomes to `test_fail`
(Oracle D6). Stage B keeps the standard mapping.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from repo2rlenv.bootstrap.spec import LanguageHint

from . import register_backend
from .base import SandboxDelivery

if TYPE_CHECKING:
    from repo2rlenv.bootstrap.docker import DockerSandbox
    from repo2rlenv.pipelines._oss_instruct import Seed


ROUTER_SOURCE_PATH = Path(__file__).parent / "router.go"

TASK_MODULE_DIR = "/task_module"
TASK_MODULE_FILE = f"{TASK_MODULE_DIR}/task_module.go"
TASK_MODULE_TEST_FILE = f"{TASK_MODULE_DIR}/task_module_test.go"
ROUTER_BINARY_PATH = f"{TASK_MODULE_DIR}/task-router"
ROUTER_SOURCE_IN_IMAGE = f"{TASK_MODULE_DIR}/router.go"


PROMPT_SYSTEM_GO = """You are a senior Go engineer. You will be given a code snippet from an open-source repository. Your job is to design a new, self-contained programming exercise that is INSPIRED by the snippet but does NOT require any of the repo's APIs.

Produce three sections — exactly in this order, exactly with these section headers:

[Problem Description]
A clear, self-contained problem statement. Describe the function(s) or type(s) to implement and their expected behavior. Include 1-2 input/output examples. Avoid any specific library or framework references. Treat the reader as someone who has not seen the snippet. Keep it under 250 words. Do NOT include the implementation, the solution source, or copies of any line from the [Solution] section — the reader must write the code themselves.

[Test]
A Go test file. It MUST declare `package task_module` at the top. Use only the standard library — the `testing` package for assertions, `strings`, `errors`, `sort`, etc. as needed. Write 2-4 test functions covering normal cases AND edge cases; each function MUST have the signature `func TestXxx(t *testing.T)`. Do NOT define `TestMain`. Do NOT add `//go:build` tags. Do NOT `import "task_module"` — the test file is already IN `package task_module` and calls solution symbols directly.

[Solution]
The Go source for `task_module.go` — the implementation the tests will exercise. It MUST declare `package task_module` at the top. Standard library only, no cgo (`import "C"`), no external imports. Provide a complete, runnable Go file with all identifiers referenced by the test defined at the top level.

Output only those three sections in that order. No preamble, no closing notes."""


PROMPT_USER_TEMPLATE_GO = """Inspiration snippet (from `{path}`, lines {start}-{end}):

```go
{snippet}
```

Design a NEW, self-contained programming exercise inspired by the snippet."""


_CODE_FENCE_RE = re.compile(r"^```(?:go|golang)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = _CODE_FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    return text


_PACKAGE_TASK_MODULE_RE = re.compile(r"(?m)^\s*package\s+task_module\b")


_LINE_COMMENT_RE = re.compile(r"^\s*//")
_PACKAGE_LINE_RE = re.compile(r"^\s*package\s+\w+")
_IMPORT_LINE_RE = re.compile(r"^\s*import\b")
_BLOCK_COMMENT_ALL_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _capitalized_call_targets(code: str) -> list[str]:
    without_blocks = _BLOCK_COMMENT_ALL_RE.sub("", code)
    lines = []
    for raw in without_blocks.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("//"):
            continue
        lines.append(raw)
    without_comments = "\n".join(lines)
    without_strings = re.sub(r'"(?:\\.|[^"\\])*"', "", without_comments)
    without_strings = re.sub(r"`[^`]*`", "", without_strings)
    # Strip Go function definitions so we only match CALLS, not declarations:
    # matches both `func Foo(` and `func (r T) Foo(`
    without_defs = re.sub(
        r"\bfunc\s+(?:\([^)]*\)\s+)?([A-Z][A-Za-z0-9_]*)\s*\(",
        "",
        without_strings,
    )
    # (?<![.\w]) rejects qualified calls like `reflect.DeepEqual` and `t.Errorf`
    matches = re.findall(r"(?<![.\w])([A-Z][A-Za-z0-9_]*)\s*\(", without_defs)
    seen: set[str] = set()
    out: list[str] = []
    for name in matches:
        if name in seen:
            continue
        # Test functions can only exist in _test.go files — never a solution symbol
        if name.startswith("Test"):
            continue
        seen.add(name)
        out.append(name)
    return sorted(out)


def _make_solution_diff(*, task_module_code: str) -> str:
    if not task_module_code or not task_module_code.strip():
        raise ValueError("task_module_code is empty; cannot synthesise gold patch")
    lines = task_module_code.splitlines()
    n = len(lines)
    header = (
        "diff --git a/tests/task_module.go b/tests/task_module.go\n"
        "new file mode 100644\n"
        "index 0000000..0000001\n"
        "--- /dev/null\n"
        "+++ b/tests/task_module.go\n"
        f"@@ -0,0 +1,{n} @@\n"
    )
    body = "".join(f"+{ln}\n" for ln in lines)
    if not task_module_code.endswith("\n"):
        body += "\\ No newline at end of file\n"
    return header + body


def _build_router_shim(expected_names: list[str]) -> str:
    filtered = sorted({n for n in expected_names if n.isidentifier()})
    if not filtered:
        return f"test -f {TASK_MODULE_FILE} && exit 0"
    expect_arg = ",".join(filtered)
    return (
        f"test -f {TASK_MODULE_FILE} && exit 0; "
        f"{ROUTER_BINARY_PATH} --expect={expect_arg} --dest={TASK_MODULE_FILE} /workspace"
    )


def _all_tests_passed_from_json(log: str) -> bool:
    saw_pass = False
    for line in log.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = evt.get("Action")
        test = evt.get("Test")
        if action == "fail":
            return False
        if action == "pass" and test:
            saw_pass = True
    return saw_pass


def _has_undefined_reference(log: str) -> bool:
    return bool(re.search(r"undefined:\s*\w+", log))


def _has_panic(log: str) -> bool:
    for line in log.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("Action") == "output":
            out = evt.get("Output", "")
            if out.lstrip().startswith("panic:"):
                return True
    return False


def _standard_go_verdict(
    log: str, exit_code: int
) -> Literal["build_fail", "test_fail", "test_pass", "unknown"]:
    if not log.strip():
        return "unknown"
    if exit_code == 0:
        return "test_pass" if _all_tests_passed_from_json(log) else "unknown"
    if _has_panic(log):
        return "test_fail"
    if "FAIL" in log and _has_undefined_reference(log):
        return "build_fail"
    lowered = log.lower()
    if "build failed" in lowered or "syntax error" in lowered:
        return "build_fail"
    if re.search(r"^--- FAIL:", log, re.MULTILINE):
        return "test_fail"
    for line in log.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("Action") == "fail":
            return "test_fail"
    return "unknown"


@register_backend(LanguageHint.GO)
class GoLanguageBackend:
    language: ClassVar[LanguageHint] = LanguageHint.GO
    default_file_glob: ClassVar[str] = "**/*.go"
    default_exclude_globs: ClassVar[tuple[str, ...]] = (
        "**/*_test.go",
        "**/vendor/**",
        "**/testdata/**",
    )

    def render_prompts(self, seed: Seed, aws_mode: bool = False) -> tuple[str, str]:
        if aws_mode:
            raise ValueError("aws_mode is not supported for Go backend — see D8 in Oracle review")
        user = PROMPT_USER_TEMPLATE_GO.format(
            path=seed.relative_path,
            start=seed.start_line,
            end=seed.end_line,
            snippet=seed.text,
        )
        return PROMPT_SYSTEM_GO, user

    def parse_solution_block(self, text: str) -> str:
        return _strip_code_fence(text)

    def test_references_task_module(self, test_code: str) -> bool:
        return bool(_PACKAGE_TASK_MODULE_RE.search(test_code))

    def extract_task_module_imports(self, test_code: str) -> list[str]:
        return _capitalized_call_targets(test_code)

    def substantive_solution_lines(self, solution_code: str) -> list[str]:
        without_blocks = _BLOCK_COMMENT_ALL_RE.sub("", solution_code)
        out: list[str] = []
        for raw in without_blocks.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if _LINE_COMMENT_RE.match(raw):
                continue
            if _PACKAGE_LINE_RE.match(raw):
                continue
            if _IMPORT_LINE_RE.match(raw):
                continue
            out.append(stripped)
        return out

    def build_sandbox_delivery(
        self,
        *,
        task_module_code: str,
        test_code: str,
        expected_names: list[str],
        test_hash: str,
    ) -> SandboxDelivery:
        del test_code, test_hash
        test_filename = "task_module_test.go"
        invocation = (
            'export PATH="/usr/local/go/bin:$PATH" && '
            "export GOTOOLCHAIN=auto && "
            f"cd {TASK_MODULE_DIR} && "
            "GOPROXY=off CGO_ENABLED=0 "
            "go test -json -count=1 -timeout=30s -vet=off ."
        )
        return SandboxDelivery(
            solution_diff=_make_solution_diff(task_module_code=task_module_code),
            router_shim=_build_router_shim(expected_names),
            test_invocation=invocation,
            cleanup_files=[TASK_MODULE_FILE],
            test_filename=test_filename,
            test_file_relpath=f"tests/{test_filename}",
            test_placement_cmd=f"cp /tests/{test_filename} {TASK_MODULE_DIR}/",
        )

    # Stage A remap: undefined-identifier build errors → test_fail (Oracle D6).
    def stage_a_verdict(
        self, log: str, exit_code: int
    ) -> Literal["build_fail", "test_fail", "test_pass", "unknown"]:
        verdict = _standard_go_verdict(log, exit_code)
        if verdict == "build_fail" and _has_undefined_reference(log):
            return "test_fail"
        return verdict

    def stage_b_verdict(
        self, log: str, exit_code: int
    ) -> Literal["build_fail", "test_fail", "test_pass", "unknown"]:
        return _standard_go_verdict(log, exit_code)

    def sandbox_prep(self, sandbox: DockerSandbox) -> None:
        router_src = ROUTER_SOURCE_PATH.read_text(encoding="utf-8")
        encoded = base64.b64encode(router_src.encode("utf-8")).decode("ascii")
        r = sandbox.exec(
            'export PATH="/usr/local/go/bin:$PATH" && '
            "export GOTOOLCHAIN=auto && "
            f"set -e && mkdir -p {TASK_MODULE_DIR} && cd {TASK_MODULE_DIR} && "
            "(test -f go.mod || go mod init task_module >/dev/null 2>&1) && "
            f"echo '{encoded}' | base64 -d > {ROUTER_SOURCE_IN_IMAGE} && "
            "go build -o task-router router.go && "
            f"test -x {ROUTER_BINARY_PATH}",
            timeout=180,
        )
        if not r.ok:
            raise RuntimeError(f"router binary build failed (exit={r.exit_code}): {r.truncated()}")

    def dockerfile_extra_layers(self) -> str:
        router_src = ROUTER_SOURCE_PATH.read_text(encoding="utf-8")
        heredoc_marker = "R2E_ROUTER_EOF"
        return (
            'RUN command -v go >/dev/null 2>&1 || (echo "Go not found in bootstrap '
            'image — this backend requires a Go-capable base image" && exit 1)\n'
            f"RUN mkdir -p {TASK_MODULE_DIR}\n"
            f"RUN cat <<'{heredoc_marker}' > {ROUTER_SOURCE_IN_IMAGE}\n"
            f"{router_src}\n"
            f"{heredoc_marker}\n"
            f"RUN cd {TASK_MODULE_DIR} && go build -o task-router router.go\n"
        )
