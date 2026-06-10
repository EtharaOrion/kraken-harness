"""Deterministic auto-detection + AST extraction for cli_app mode.

No LLM calls in the main path. Walks the cloned repo with stdlib `ast`
to derive:

  - CliSpec   — what commands exist under the prefix (auto-detected from
                argparse subparsers under the prefix)
  - TestIntent — per-test structured intent inferred from white-box test
                source (cmdline string, expected exit code, expected boto3
                operation names from `self.operations_called[i][0].name`)

The extraction is "best effort": tests with patterns we can't infer
deterministically are dropped (logged), to be either retried via LLM in
a later pass or excluded entirely. For the v1 MVP we drop them.

Acknowledgment
--------------
Tested against aws-cli's `tests/functional/s3/` BaseAWSCommandParamsTest
suite. The CLI spec extractor reads any module that declares a parser
via standard argparse `add_subparsers()` patterns; the test extractor is
specialised to BaseAWSCommandParamsTest's `prefix = '... '` + `self.run_cmd`
+ `self.parsed_responses` + `self.operations_called` idiom.

Released under Apache-2.0.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CommandSpec:
    name: str  # e.g. "mb"
    synopsis: str = ""  # one-line help text if present
    args: list[str] = field(default_factory=list)  # positional arg names
    flags: list[str] = field(default_factory=list)  # flag names (--region, ...)
    behaviours: list[str] = field(default_factory=list)  # human-derived from intents


@dataclass(slots=True)
class CliSpec:
    name: str  # e.g. "aws_cli_s3"
    command_prefix: str  # e.g. "s3"
    repo: str  # e.g. "aws/aws-cli"
    git_sha: str  # resolved git ref
    entry_point: str  # relative to clone root
    tests_dir: str  # relative to clone root
    commands: list[CommandSpec] = field(default_factory=list)
    spec_sha256: str = ""  # canonical hash of (name, prefix, commands)


@dataclass(slots=True)
class TestIntent:
    source_file: str
    test_name: str
    source_method_sha256: str
    command: str  # which subcommand (mb/rb/cp/ls/...)
    cmdline_template: list[str]  # argv tokens after the program name
    expected_exit: int = 0
    expected_state_calls: list[str] = field(default_factory=list)
    expected_stdout_pattern: str | None = None
    behaviour_tag: Literal["happy_path", "error", "edge", "workflow"] = "happy_path"
    raw_source: str = ""  # original method source (for LLM context)


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------


_DEFAULT_EXCLUDE_DIRS = (
    ".git/**",
    ".venv/**",
    "venv/**",
    "node_modules/**",
    "build/**",
    "dist/**",
    "**/__pycache__/**",
)


def _walk_python_files(
    clone_dir: Path, exclude: tuple[str, ...] = _DEFAULT_EXCLUDE_DIRS
) -> list[Path]:
    out: list[Path] = []
    for p in clone_dir.rglob("*.py"):
        rel = str(p.relative_to(clone_dir))
        if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
            continue
        out.append(p)
    return out


def auto_detect_entry_point(
    clone_dir: Path,
    command_prefix: str,
    *,
    override: str | None = None,
) -> Path:
    """Find the Python file that registers `command_prefix` subcommands.

    Strategy:
      1. If `override` set, return clone_dir / override.
      2. Heuristic: file whose path contains the prefix as a path component
         AND contains `add_subparsers` OR `BasicCommand` (aws-cli idiom).
      3. Fallback: any file with `add_subparsers` whose docstring or
         module-level constants mention the prefix.

    For aws-cli + prefix=s3, this resolves to
    `awscli/customizations/s3/subcommands.py`.
    """
    if override:
        p = clone_dir / override
        if not p.is_file():
            raise FileNotFoundError(f"cli_app_entry_point_override not found: {override}")
        return p

    candidates: list[Path] = []
    for p in _walk_python_files(clone_dir):
        rel_parts = p.relative_to(clone_dir).parts
        if command_prefix in rel_parts:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "add_subparsers" in text or "BasicCommand" in text or "subparsers" in text:
                candidates.append(p)

    # aws-cli specifically: prefer `subcommands.py` if multiple matches
    preferred = [c for c in candidates if c.name == "subcommands.py"]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]

    raise RuntimeError(
        f"could not auto-detect entry point for command_prefix={command_prefix!r}. "
        f"Pass --pipeline-opt cli_app_entry_point_override=<path-from-repo-root> to override."
    )


def auto_detect_tests_dir(
    clone_dir: Path,
    command_prefix: str,
    *,
    override: str | None = None,
) -> Path:
    """Find the directory containing tests for the given command prefix.

    Strategy:
      1. If `override` set, return clone_dir / override.
      2. Walk for dirs containing `test_*_command.py` AND `__init__.py`.
      3. Filter to those whose path contains the prefix.

    For aws-cli + prefix=s3, this resolves to `tests/functional/s3/`.
    """
    if override:
        p = clone_dir / override
        if not p.is_dir():
            raise FileNotFoundError(f"cli_app_tests_dir_override not found: {override}")
        return p

    candidates: list[Path] = []
    for p in clone_dir.rglob("test_*_command.py"):
        rel_parts = p.relative_to(clone_dir).parts
        if command_prefix in rel_parts:
            candidates.append(p.parent)

    # Prefer functional/ over integration/ over unit/
    for tier in ("functional", "integration", "unit"):
        for c in candidates:
            if tier in c.parts:
                return c
    if candidates:
        return candidates[0]

    raise RuntimeError(
        f"could not auto-detect tests dir for command_prefix={command_prefix!r}. "
        f"Pass --pipeline-opt cli_app_tests_dir_override=<path-from-repo-root> to override."
    )


# ---------------------------------------------------------------------------
# CliSpec extraction
# ---------------------------------------------------------------------------


def extract_cli_spec(
    clone_dir: Path,
    command_prefix: str,
    *,
    repo: str,
    git_sha: str,
    entry_point_override: str | None = None,
    tests_dir_override: str | None = None,
) -> CliSpec:
    """Build CliSpec by walking the test directory for test_*_command.py files.

    For aws-cli we derive commands from the TEST FILE NAMES rather than
    parsing argparse, because aws-cli's command registration is split
    across many files via plugin loaders. Each `test_<cmd>_command.py`
    file is one CLI command.
    """
    entry_point = auto_detect_entry_point(clone_dir, command_prefix, override=entry_point_override)
    tests_dir = auto_detect_tests_dir(clone_dir, command_prefix, override=tests_dir_override)

    commands: list[CommandSpec] = []
    for test_file in sorted(tests_dir.glob("test_*_command.py")):
        # test_mb_command.py -> "mb"
        m = re.match(r"test_(\w+)_command\.py$", test_file.name)
        if not m:
            continue
        cmd_name = m.group(1)
        commands.append(CommandSpec(name=cmd_name))

    spec = CliSpec(
        name=f"aws_cli_{command_prefix}",
        command_prefix=command_prefix,
        repo=repo,
        git_sha=git_sha,
        entry_point=str(entry_point.relative_to(clone_dir)),
        tests_dir=str(tests_dir.relative_to(clone_dir)),
        commands=commands,
    )
    spec.spec_sha256 = _canonical_spec_hash(spec)
    return spec


def _canonical_spec_hash(spec: CliSpec) -> str:
    """sha256 over a canonical JSON-ish repr of the spec (deterministic)."""
    parts = [
        spec.name,
        spec.command_prefix,
        spec.repo,
        spec.git_sha,
        spec.entry_point,
        spec.tests_dir,
    ]
    for cmd in sorted(spec.commands, key=lambda c: c.name):
        parts.append(cmd.name)
        parts.extend(sorted(cmd.args))
        parts.extend(sorted(cmd.flags))
    h = hashlib.sha256()
    h.update("\0".join(parts).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# TestIntent extraction (aws-cli BaseAWSCommandParamsTest pattern)
# ---------------------------------------------------------------------------


def extract_test_intents(
    tests_dir: Path,
    spec: CliSpec,
    *,
    command_filter: str | None = None,
    max_intents: int | None = None,
) -> list[TestIntent]:
    """Walk test files, parse to AST, extract structured intent per method.

    For each test method in a class derived from BaseAWSCommandParamsTest:
      - Find `cmdline = self.prefix + '...'` assembly
      - Find `self.run_cmd(...)` call with optional `expected_rc=`
      - Find `self.operations_called[N][0].name` assertions
      - Find `self.parsed_responses = [...]` fixture setup

    Returns one TestIntent per successfully-extracted method. Methods with
    irreducible patterns are silently dropped.
    """
    out: list[TestIntent] = []
    cmd_to_file = {cmd.name: f"test_{cmd.name}_command.py" for cmd in spec.commands}

    for cmd_name, file_name in sorted(cmd_to_file.items()):
        if command_filter and cmd_name != command_filter:
            continue
        test_file = tests_dir / file_name
        if not test_file.is_file():
            continue
        try:
            source = test_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            logger.warning("AST parse failed for %s: %s", file_name, exc)
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Some test classes (e.g. TestLSCommand) don't declare `prefix`;
            # tests inline the full command literal in run_cmd. Default to "".
            prefix_value = _extract_class_prefix(node) or ""
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                if not item.name.startswith("test_"):
                    continue
                intent = _extract_intent_from_method(
                    method=item,
                    prefix_value=prefix_value,
                    command=cmd_name,
                    source_file=file_name,
                    full_source=source,
                )
                if intent is not None:
                    out.append(intent)

    # Behaviour-diversity ordering: interleave error/edge/workflow intents
    # ahead of happy_path so a small max_intents slice still covers the
    # important behaviours. Without this, happy_path tests (file order)
    # would consume the budget and edge/error coverage falls to zero.
    out = _interleave_by_behaviour(out)
    if max_intents:
        out = out[:max_intents]
    return out


def _interleave_by_behaviour(intents: list[TestIntent]) -> list[TestIntent]:
    """Round-robin intents by behaviour_tag for diversity in small slices.

    Tags drained in priority order (error first, then edge, workflow,
    happy_path) so when max_intents is small the slice still surfaces
    the rare-but-important cases. Within a tag, original order preserved.
    """
    buckets: dict[str, list[TestIntent]] = {}
    for i in intents:
        buckets.setdefault(i.behaviour_tag, []).append(i)
    priority = ["error", "edge", "workflow", "happy_path"]
    ordered: list[TestIntent] = []
    while any(buckets.get(t) for t in priority):
        for tag in priority:
            if buckets.get(tag):
                ordered.append(buckets[tag].pop(0))
    return ordered


def _extract_class_prefix(class_node: ast.ClassDef) -> str | None:
    """Look for `prefix = 's3 mb '` at class body. Returns the prefix string or None."""
    for item in class_node.body:
        if (
            isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and item.targets[0].id == "prefix"
            and isinstance(item.value, ast.Constant)
            and isinstance(item.value.value, str)
        ):
            return item.value.value
    return None


def _extract_intent_from_method(
    *,
    method: ast.FunctionDef,
    prefix_value: str,
    command: str,
    source_file: str,
    full_source: str,
) -> TestIntent | None:
    """Best-effort intent extraction. Returns None on irreducible patterns."""
    cmdline: list[str] | None = None
    expected_exit = 0
    expected_state_calls: list[str] = []
    expected_stdout_pattern: str | None = None

    for stmt in ast.walk(method):
        # cmdline = self.prefix + '<rest>'  OR  cmdline = self.prefix + 's3://...'
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id in ("cmdline", "command")
        ):
            literal_tail = _extract_string_concat_tail(stmt.value)
            if literal_tail is not None:
                full = prefix_value + literal_tail
                cmdline = full.strip().split()

        # self.run_cmd(cmdline, expected_rc=N)
        if (
            isinstance(stmt, ast.Call)
            and isinstance(stmt.func, ast.Attribute)
            and stmt.func.attr in ("run_cmd", "assert_params_for_cmd")
        ):
            # If cmdline wasn't extracted yet, try positional argument
            if cmdline is None and stmt.args:
                first = stmt.args[0]
                literal = _extract_string_concat_tail(first)
                if literal is not None:
                    full = prefix_value + literal
                    cmdline = full.strip().split()
            for kw in stmt.keywords:
                if (
                    kw.arg == "expected_rc"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, int)
                ):
                    expected_exit = kw.value.value

        # self.operations_called[N][0].name -> capture via assertEqual
        if (
            isinstance(stmt, ast.Call)
            and isinstance(stmt.func, ast.Attribute)
            and stmt.func.attr in ("assertEqual", "assertEquals")
            and len(stmt.args) >= 2
        ):
            for arg in stmt.args:
                op_name = _maybe_extract_operation_name(arg)
                if op_name and op_name not in expected_state_calls:
                    expected_state_calls.append(op_name)

    # Fallback A: presign-style wrapper calls (`helper(self.prefix + 'literal')`)
    # — scan ALL BinOp(Add) inside the method body for a self.prefix
    # concatenation tail, even when wrapped in non-canonical calls.
    if cmdline is None or not cmdline:
        for stmt in ast.walk(method):
            if isinstance(stmt, ast.BinOp):
                literal_tail = _extract_string_concat_tail(stmt)
                if literal_tail and (
                    literal_tail.startswith("s3://")
                    or literal_tail.startswith("--")
                    or " " in literal_tail
                ):
                    full = prefix_value + literal_tail
                    cmdline = full.strip().split()
                    break

    # Fallback B: regex on raw method source for any literal that includes
    # the command name as a token (e.g. ls's direct `run_cmd('s3 ls ...')`).
    if cmdline is None or not cmdline:
        method_source = ast.get_source_segment(full_source, method) or ""
        m = re.search(
            r"['\"]\s*((?:[a-z0-9_]+\s+){0,3}" + re.escape(command) + r"\b[^'\"]*)['\"]",
            method_source,
        )
        if m:
            cmdline = m.group(1).strip().split()

    # Last-resort placeholder so the method isn't silently dropped. The LLM
    # gets the full raw_source and translates from that — cmdline_template
    # is only a hint.
    if cmdline is None or not cmdline:
        cmdline = [command]

    behaviour_tag = _infer_behaviour_tag(method.name, expected_exit)

    h = hashlib.sha256()
    h.update(source_file.encode())
    h.update(b"\0")
    h.update(method.name.encode())
    h.update(b"\0")
    h.update(str(method.lineno).encode())
    source_method_sha = h.hexdigest()

    method_source = ast.get_source_segment(full_source, method) or ""

    return TestIntent(
        source_file=source_file,
        test_name=method.name,
        source_method_sha256=source_method_sha,
        command=command,
        cmdline_template=cmdline,
        expected_exit=expected_exit,
        expected_state_calls=expected_state_calls,
        expected_stdout_pattern=expected_stdout_pattern,
        behaviour_tag=behaviour_tag,
        raw_source=method_source,
    )


def _extract_string_concat_tail(node: ast.expr) -> str | None:
    """Given an expression like `self.prefix + 's3://bucket'` or
    `'%s ...' % (self.prefix, ...)`, return the literal tail. Returns None
    for non-trivial expressions (variables, function calls, etc.).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # self.prefix + 'literal'
        right = node.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            return right.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        # '%s ... %s' % (self.prefix, args)
        #   -> use the template as the tail, dropping the leading "%s "
        #   placeholder that's filled by self.prefix. Remaining %s become
        #   placeholders the LLM resolves from raw_source context.
        left = node.left
        if isinstance(left, ast.Constant) and isinstance(left.value, str):
            template = left.value
            if template.startswith("%s "):
                template = template[3:]
            # Replace remaining %s placeholders with readable <arg> tokens
            # so the agent's instruction.md doesn't leak raw format syntax.
            template = template.replace("%s", "<arg>")
            return template
    return None


def _maybe_extract_operation_name(node: ast.expr) -> str | None:
    """Detect patterns like `self.operations_called[0][0].name == 'CreateBucket'`.

    We look for string literals that look like AWS operation names
    (CamelCase ASCII, length 3-40), or attribute access on operations_called.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        v = node.value
        if _looks_like_op_name(v):
            return v
    return None


_OP_NAME_RE = re.compile(r"^[A-Z][a-zA-Z0-9]{2,39}$")


def _looks_like_op_name(s: str) -> bool:
    return bool(_OP_NAME_RE.match(s))


def _infer_behaviour_tag(
    method_name: str, expected_exit: int
) -> Literal["happy_path", "error", "edge", "workflow"]:
    name = method_name.lower()
    if expected_exit != 0 or "error" in name or "fail" in name or "invalid" in name:
        return "error"
    if "edge" in name or "empty" in name or "missing" in name or "nonexistent" in name:
        return "edge"
    if "_then_" in name or "_and_" in name or "workflow" in name:
        return "workflow"
    return "happy_path"
