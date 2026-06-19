"""Helpers for the `code_instruct` pipeline: sampling, parsing, decontam.

Magicoder OSS-Instruct is a recipe (prompt template + sampling + parsing),
not a reusable library. This module is the recipe.

Acknowledgment
--------------
Algorithms inspired by Magicoder
(`references/magicoder/src/magicoder/generate_data.py:79-102` and
`magicoder/decontamination/find_substrings.py`). No code copied; we
reimplement against Python stdlib only.
"""

from __future__ import annotations

import fnmatch
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed sampling
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Seed:
    """One sampled snippet from the target repo."""

    relative_path: str  # POSIX-style, e.g. "src/foo/bar.py"
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed, inclusive
    text: str  # the snippet itself (no line numbers)


def is_excluded(relative_path: str, exclude_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative_path, pat) for pat in exclude_globs)


def list_source_files(clone_dir: Path, *, file_glob: str, exclude_glob: list[str]) -> list[Path]:
    """Walk the repo tree matching `file_glob` minus `exclude_glob`."""
    out: list[Path] = []
    for p in clone_dir.glob(file_glob):
        if not p.is_file():
            continue
        rel = str(p.relative_to(clone_dir))
        if is_excluded(rel, exclude_glob):
            continue
        out.append(p)
    return out


def sample_seed(
    files: list[Path],
    clone_dir: Path,
    *,
    rng: random.Random,
    min_loc: int,
    max_loc: int,
    max_attempts: int = 20,
) -> Seed | None:
    """Pick a random file, pick a random window of `[min_loc..max_loc]` lines.

    Skips files that are too short. Skips windows that are dominated by
    blank lines, imports, docstrings, or comments (those snippets give
    the LLM nothing to work with). Returns None after `max_attempts`.
    """
    if not files:
        return None
    for _ in range(max_attempts):
        f = rng.choice(files)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        if len(lines) < min_loc:
            continue
        window = rng.randint(min_loc, min(max_loc, len(lines)))
        start = rng.randint(0, max(0, len(lines) - window))
        end = start + window
        chunk_lines = lines[start:end]
        chunk = "\n".join(chunk_lines)
        if _looks_substantive(chunk_lines):
            return Seed(
                relative_path=str(f.relative_to(clone_dir)),
                start_line=start + 1,
                end_line=end,
                text=chunk,
            )
    return None


_COMMENT_OR_IMPORT_RE = re.compile(r"^\s*(?:#|from\s|import\s)")


def _looks_substantive(chunk_lines: list[str]) -> bool:
    """Reject snippets that are 80%+ comments / imports / blanks."""
    if not chunk_lines:
        return False
    boring = 0
    for ln in chunk_lines:
        s = ln.strip()
        if not s or _COMMENT_OR_IMPORT_RE.match(s):
            boring += 1
    return (boring / len(chunk_lines)) < 0.8


# ---------------------------------------------------------------------------
# Decontamination — substring match against well-known eval benchmarks
# ---------------------------------------------------------------------------


# A minimal seed set. The real Magicoder corpus is huge (~10K+ substrings);
# we cover the most common contamination vectors. Extend per-need.
DEFAULT_BENCHMARK_PHRASES: tuple[str, ...] = (
    # HumanEval-style canonical phrasings (both definition and bare-name forms)
    "from typing import list",
    "def has_close_elements",
    "has_close_elements",
    "def separate_paren_groups",
    "separate_paren_groups",
    "def truncate_number",
    "truncate_number",
    # MBPP common phrasings
    "write a python function to",
    "write a function to find the",
    # APPS competitive phrasings
    "the first line of input contains an integer",
    "given a non-empty array of integers",
    # GSM8K (math word problems)
    "natalia sold clips to",
    "if a car travels",
    # DS-1000 — NOTE: bare `import numpy as np` / `import pandas as pd` are
    # NOT included here; they're language idioms, not contamination signals,
    # and matching them rejects every legitimate data-stack task. If you want
    # real DS-1000 coverage, vendor the full substring corpus.
)


def has_benchmark_overlap(text: str, phrases: tuple[str, ...] = DEFAULT_BENCHMARK_PHRASES) -> bool:
    """True if any known benchmark phrase appears as a substring (case-insensitive)."""
    lower = text.lower()
    return any(p.lower() in lower for p in phrases)


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


_TRIVIAL_SOLUTION_LINES = frozenset(
    {"pass", "return", "...", "else:", "try:", "finally:", "break", "continue", "raise"}
)
_MIN_LEAK_LINE_LEN = 8


def substantive_solution_lines(solution_code: str) -> list[str]:
    """Whitespace-normalized implementation-body lines from the oracle solution.

    Excludes signatures, imports, comments, docstrings, blanks, and trivial
    one-keyword lines. What remains is the implementation body — the part that,
    if reproduced in the problem statement, hands the agent the answer. AST is
    used only to locate docstring line ranges. Returns [] on syntax errors.
    """
    import ast

    try:
        tree = ast.parse(solution_code)
    except SyntaxError:
        return []

    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ) and ast.get_docstring(node, clean=False):
            first = node.body[0]
            start = getattr(first, "lineno", None)
            end = getattr(first, "end_lineno", start)
            if start is not None:
                docstring_lines.update(range(start, (end or start) + 1))

    out: list[str] = []
    for lineno, raw in enumerate(solution_code.splitlines(), start=1):
        if lineno in docstring_lines:
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _COMMENT_OR_IMPORT_RE.match(stripped):
            continue
        if stripped.startswith(("def ", "class ", "async def ")):
            continue
        if stripped in _TRIVIAL_SOLUTION_LINES:
            continue
        norm = _normalize_ws(stripped)
        if len(norm) < _MIN_LEAK_LINE_LEN:
            continue
        out.append(norm)
    return out


def solution_leaks_into_problem(
    problem: str, solution_code: str, *, min_leaked_lines: int = 3
) -> bool:
    """True if the oracle implementation bleeds into the agent-visible problem.

    The problem statement is the ONLY artifact the solving agent sees at solve
    time (Harbor withholds the test and oracle until the post-agent verifier),
    so solution->problem is the one real contamination vector here. Counts the
    distinct substantive solution lines that appear verbatim in the problem;
    `>= min_leaked_lines` flags a leak. Returns False on solution syntax errors.
    """
    lines = substantive_solution_lines(solution_code)
    if not lines:
        return False

    problem_norm = _normalize_ws(problem).lower()
    seen: set[str] = set()
    for line in lines:
        key = line.lower()
        if key in seen:
            continue
        if key in problem_norm:
            seen.add(key)
            if len(seen) >= min_leaked_lines:
                return True

    # A 1-2 line solution fully reproduced in the problem is a total leak even
    # though it cannot reach min_leaked_lines distinct matches.
    return len(lines) <= 2 and len(seen) == len(lines)


# ---------------------------------------------------------------------------
# Prompting + parsing
# ---------------------------------------------------------------------------


PROMPT_SYSTEM = """You are a senior Python engineer. You will be given a code snippet from an open-source repository. Your job is to design a new, self-contained programming exercise that is INSPIRED by the snippet but does NOT require any of the repo's APIs.

Produce three sections — exactly in this order, exactly with these section headers:

[Problem Description]
A clear, self-contained problem statement. Describe the function to implement and its expected behavior. Include 1-2 input/output examples. Avoid any specific library or framework references. Treat the reader as someone who has not seen the snippet. Keep it under 200 words. Do NOT include the implementation, the solution source, or copies of any line from the [Solution] section — the reader must write the code themselves.

[Test]
A pytest test file. It MUST import from the module `task_module` (literal name, do not change it). Write 2-4 assertions covering normal cases AND edge cases. Use plain `def test_...(): assert ...` — no fixtures.

[Solution]
The Python source for `task_module.py` — the implementation the test will exercise. Provide a complete, runnable Python file. Do NOT import any third-party libraries; only Python stdlib is allowed.

Output only those three sections in that order. No preamble, no closing notes."""


PROMPT_SYSTEM_AWS = """You are a senior Python engineer. You will be given a code snippet from an open-source repository. Your job is to design a new, self-contained programming exercise that exercises AWS via the AWS CLI v2 (`aws s3 ...`, `aws dynamodb ...`, etc.) or boto3, INSPIRED by the snippet but not requiring the repo's APIs.

Runtime guarantees provided by the sandbox (do NOT restate them in your output):
- `aws` (AWS CLI v2) is on PATH.
- `boto3` is installed.
- A `moto_server` is already running on http://127.0.0.1:5000 BEFORE pytest starts.
- These env vars are already exported: AWS_ENDPOINT_URL=http://127.0.0.1:5000, AWS_ACCESS_KEY_ID=testing, AWS_SECRET_ACCESS_KEY=testing, AWS_DEFAULT_REGION=us-east-1.
- The test MUST NOT hardcode endpoint URLs or credentials. The env handles routing.
- Each test FUNCTION starts with freshly-reset moto state — an autouse `conftest.py` fixture wipes all AWS resources before every test. Tests are isolated from each other; do NOT rely on or assume resources created by sibling tests still exist.
- When an AWS resource is created asynchronously (e.g. Kinesis `create_stream`, DynamoDB `create_table`), call the matching waiter — `client.get_waiter("stream_exists").wait(StreamName=...)`, `client.get_waiter("table_exists").wait(TableName=...)`, etc. — before invoking the function under test. Otherwise the resource may still be in the CREATING state and operations against it will fail.

Produce three sections — exactly in this order, exactly with these section headers:

[Problem Description]
A clear, self-contained problem statement. Describe a function or CLI workflow that operates on AWS resources (S3 buckets/objects, DynamoDB tables, etc.). Include 1-2 worked examples. Keep it under 200 words. Do NOT include the implementation, the solution source, or copies of any line from the [Solution] section — the reader must write the code themselves.

[Test]
A pytest test file. It MUST import from the module `task_module` (literal name). Write 2-4 assertions covering normal cases AND edge cases. Use plain `def test_...(): assert ...` — no fixtures. The test SHOULD set up any required AWS state (e.g., `boto3.client('s3').create_bucket(Bucket=...)`) before invoking the function under test. Use only the env-provided endpoint routing — do NOT pass `endpoint_url=` explicitly. For S3 buckets in us-east-1, do NOT pass `CreateBucketConfiguration` (real S3 rejects LocationConstraint for us-east-1; moto matches that behavior).

[Solution]
The Python source for `task_module.py` — the implementation the test will exercise. Provide a complete, runnable Python file. Allowed imports: Python stdlib + `boto3`. May call `aws` via `subprocess.run(...)`. Do NOT pass `endpoint_url=` to boto3 clients; rely on AWS_ENDPOINT_URL from the environment.

Output only those three sections in that order. No preamble, no closing notes."""


PROMPT_USER_TEMPLATE = """Inspiration snippet (from `{path}`, lines {start}-{end}):

```python
{snippet}
```

Design a NEW, self-contained programming exercise inspired by the snippet."""


@dataclass(slots=True)
class ParsedTask:
    problem: str
    test_code: str
    solution_code: str


def parse_task_response(text: str) -> ParsedTask | None:
    """Extract the three sections from the LLM's response.

    Tolerant: section markers are matched case-insensitively. Returns
    None if any section is missing or empty.
    """
    problem = _extract_section(text, "Problem Description")
    test = _extract_section(text, "Test")
    solution = _extract_section(text, "Solution")
    if not (problem and test and solution):
        return None
    return ParsedTask(
        problem=problem.strip(),
        test_code=_strip_code_fence(test),
        solution_code=_strip_code_fence(solution),
    )


_SECTION_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _section_re(name: str) -> re.Pattern[str]:
    if name not in _SECTION_RE_CACHE:
        # Match `[Section Name]` markers, with optional leading/trailing whitespace
        pattern = rf"(?im)^\s*\[\s*{re.escape(name)}\s*\]\s*$"
        _SECTION_RE_CACHE[name] = re.compile(pattern)
    return _SECTION_RE_CACHE[name]


def _extract_section(text: str, name: str) -> str:
    """Return the text between `[<name>]` and the next `[...]` marker (or EOF)."""
    pattern = _section_re(name)
    m = pattern.search(text)
    if not m:
        return ""
    start = m.end()
    # Find the next section marker after this one
    next_marker = re.search(r"(?im)^\s*\[\s*[A-Za-z][A-Za-z ]+\s*\]\s*$", text[start:])
    end = start + next_marker.start() if next_marker else len(text)
    return text[start:end].strip()


_CODE_FENCE_RE = re.compile(r"^```(?:python|py)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Strip a single surrounding ``` code fence if present."""
    text = text.strip()
    m = _CODE_FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    return text


# ---------------------------------------------------------------------------
# Test syntactic validation
# ---------------------------------------------------------------------------


def references_task_module(test_code: str) -> bool:
    """True iff the test code imports `task_module` (our convention).

    Uses AST so that the string `from task_module import …` appearing inside
    a docstring, comment, or `pytest.skip("…")` argument does NOT count as
    an import. Returns False on syntax errors (those tasks would be rejected
    downstream anyway).
    """
    import ast

    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "task_module":
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "task_module":
                    return True
    return False


def extract_task_module_imports(test_code: str) -> list[str]:
    """Return the names imported via `from task_module import ...`, sorted+unique.

    Used by the runtime auto-router shim baked into `tests/test.sh`: at
    verify time the shim scans agent-modified files for any of these names
    and synthesizes `task_module.py` re-exporting from whichever module
    defines them, so the agent isn't forced to use the literal filename
    `task_module.py`.

    Returns the ORIGINAL exported name even when the test aliases it
    (`import compute as c` → "compute"), because the original name is what
    the agent's module must define. Returns [] on syntax errors or when
    no `from task_module import …` appears (bare `import task_module`
    yields no name list, since the test accesses attributes dynamically).
    """
    import ast

    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "task_module":
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.name)
    return sorted(names)


# ---------------------------------------------------------------------------
# Multi-file diff helper (shared between snippet and cli_app modes)
# ---------------------------------------------------------------------------


def make_multi_file_diff(files: dict[str, str]) -> str:
    """Build a `git apply`-compatible diff that creates each file as new.

    All files added at mode 100644, no deletes, no edits. Paths are sorted
    for byte-deterministic output across runs (same input dict -> same diff
    bytes). Handles missing trailing newline per the unified-diff spec.

    Used by code_instruct cli_app mode via _cli_app_synthesis, and available
    for any future multi-file pipeline.
    """
    out: list[str] = []
    for path in sorted(files):
        content = files[path]
        lines = content.splitlines()
        n = len(lines)
        header = (
            f"diff --git a/{path} b/{path}\n"
            f"new file mode 100644\n"
            f"index 0000000..0000001\n"
            f"--- /dev/null\n"
            f"+++ b/{path}\n"
            f"@@ -0,0 +1,{n} @@\n"
        )
        body = "".join(f"+{ln}\n" for ln in lines)
        if content and not content.endswith("\n"):
            body += "\\ No newline at end of file\n"
        out.append(header + body)
    return "".join(out)
