"""Python language backend for the code_instruct pipeline.

Every method here is a faithful extraction from `code_instruct.py` /
`_oss_instruct.py`; per-method `# extracted from ...` comments cite the
source range. The wiring change (making `code_instruct.py` route through
this backend) lands in a follow-up task; today the pipeline still calls
the original in-line logic — this backend simply mirrors it.
"""

from __future__ import annotations

import base64
import re
from typing import TYPE_CHECKING, ClassVar, Literal

from repo2rlenv.bootstrap.spec import LanguageHint
from repo2rlenv.pipelines._oss_instruct import (
    PROMPT_SYSTEM,
    PROMPT_SYSTEM_AWS,
    PROMPT_USER_TEMPLATE,
    _strip_code_fence,
)
from repo2rlenv.pipelines._oss_instruct import (
    extract_task_module_imports as _extract_task_module_imports,
)
from repo2rlenv.pipelines._oss_instruct import (
    references_task_module as _references_task_module,
)
from repo2rlenv.pipelines._oss_instruct import (
    substantive_solution_lines as _substantive_solution_lines,
)

from . import register_backend
from .base import SandboxDelivery

if TYPE_CHECKING:
    from repo2rlenv.bootstrap.docker import DockerSandbox
    from repo2rlenv.pipelines._oss_instruct import Seed


# extracted from code_instruct.py:229-275
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


# extracted from code_instruct.py:278-297
def _build_task_module_router(expected_names: list[str]) -> str:
    names = sorted({n for n in expected_names if n.isidentifier()})
    py = _TASK_MODULE_ROUTER_PY.replace("__NAMES__", repr(names))
    enc = base64.b64encode(py.encode("utf-8")).decode("ascii")
    return f"echo {enc} | base64 -d | python3 -"


# extracted from code_instruct.py:199-226
def _make_solution_diff(*, task_module_code: str) -> str:
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


# extracted from code_instruct.py:874-891
def _all_tests_passed(log: str) -> bool:
    lower = log.lower()
    if "collected 0 items" in lower:
        return False
    if re.search(r"\b[1-9]\d*\s+failed\b", lower):
        return False
    if re.search(r"\b[1-9]\d*\s+errors?\b", lower):
        return False
    return bool(re.search(r"\b[1-9]\d*\s+passed\b", lower))


def _pytest_verdict(
    log: str, exit_code: int
) -> Literal["build_fail", "test_fail", "test_pass", "unknown"]:
    if "collected 0 items" in log.lower():
        return "unknown"
    if exit_code == 0 and _all_tests_passed(log):
        return "test_pass"
    if exit_code == 1:
        return "test_fail"
    if exit_code >= 2:
        return "build_fail"
    return "unknown"


@register_backend(LanguageHint.PYTHON)
class PythonLanguageBackend:
    language: ClassVar[LanguageHint] = LanguageHint.PYTHON
    default_file_glob: ClassVar[str] = "**/*.py"
    default_exclude_globs: ClassVar[tuple[str, ...]] = (
        "**/tests/**",
        "**/test_*.py",
        "**/*_test.py",
    )

    # extracted from code_instruct.py:615-621 + _oss_instruct.py:244-291
    def render_prompts(self, seed: Seed, aws_mode: bool = False) -> tuple[str, str]:
        system = PROMPT_SYSTEM_AWS if aws_mode else PROMPT_SYSTEM
        user = PROMPT_USER_TEMPLATE.format(
            path=seed.relative_path,
            start=seed.start_line,
            end=seed.end_line,
            snippet=seed.text,
        )
        return system, user

    # extracted from _oss_instruct.py:343-352
    def parse_solution_block(self, text: str) -> str:
        return _strip_code_fence(text)

    # extracted from _oss_instruct.py:360-381
    def test_references_task_module(self, test_code: str) -> bool:
        return _references_task_module(test_code)

    # extracted from _oss_instruct.py:384-411
    def extract_task_module_imports(self, test_code: str) -> list[str]:
        return _extract_task_module_imports(test_code)

    # extracted from _oss_instruct.py:162-205
    def substantive_solution_lines(self, solution_code: str) -> list[str]:
        return _substantive_solution_lines(solution_code)

    # extracted from code_instruct.py:697-704, 738-743, 779-787
    def build_sandbox_delivery(
        self,
        *,
        task_module_code: str,
        test_code: str,
        expected_names: list[str],
        test_hash: str,
    ) -> SandboxDelivery:
        del test_code
        test_filename = f"test_r2e_{test_hash}.py"
        return SandboxDelivery(
            solution_diff=_make_solution_diff(task_module_code=task_module_code),
            router_shim=_build_task_module_router(expected_names),
            test_invocation=f"python -m pytest {test_filename} -v --no-header",
            cleanup_files=["task_module.py", "r2e_solution.py", test_filename],
            test_filename=test_filename,
            test_file_relpath=f"tests/{test_filename}",
            test_placement_cmd=f"cp /tests/{test_filename} /workspace/",
        )

    # extracted from code_instruct.py:874-891 (via _all_tests_passed)
    def stage_a_verdict(
        self, log: str, exit_code: int
    ) -> Literal["build_fail", "test_fail", "test_pass", "unknown"]:
        return _pytest_verdict(log, exit_code)

    # extracted from code_instruct.py:874-891 (via _all_tests_passed)
    def stage_b_verdict(
        self, log: str, exit_code: int
    ) -> Literal["build_fail", "test_fail", "test_pass", "unknown"]:
        return _pytest_verdict(log, exit_code)

    def sandbox_prep(self, sandbox: DockerSandbox) -> None:
        # Bootstrap Dockerfile (code_instruct.py:334) already sets
        # `git config --global --add safe.directory /workspace`; nothing else
        # is Python-specific for snippet mode.
        del sandbox
        return None

    # extracted from code_instruct.py:336-337 (non-aws branch: no extra layers)
    def dockerfile_extra_layers(self) -> str:
        return ""
