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
import json
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
    behaviour_tag: Literal[
        "happy_path",
        "error",
        "error_nonexistent",
        "error_invalid_args",
        "edge",
        "workflow",
    ] = "happy_path"
    raw_source: str = ""  # original method source (for LLM context)
    error_category: str | None = None
    kind: str | None = None


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


# CRUD verb vocabulary in lifecycle order (create -> read -> update -> delete) so a
# selected scope reads as a natural workflow. Service-agnostic: scope selection uses
# only command-name structure, never service names.
_CRUD_VERBS: tuple[str, ...] = (
    "create",
    "put",
    "register",
    "add",
    "import",
    "start",
    "describe",
    "get",
    "list",
    "batch-get",
    "query",
    "scan",
    "update",
    "modify",
    "set",
    "enable",
    "disable",
    "tag",
    "untag",
    "delete",
    "remove",
    "deregister",
    "stop",
)
_VERB_RANK: dict[str, int] = {v: i for i, v in enumerate(_CRUD_VERBS)}


def _command_verb_resource(cmd: str) -> tuple[str | None, str]:
    """Split a kebab command into (verb, resource-noun).

    'admin-create-user' -> ('create', 'user'); 'list-user-pools' -> ('list',
    'user-pools'). Verb is the first recognised CRUD token after an optional
    'admin' prefix; two-word verbs (batch-get) match first.
    """
    parts = cmd.split("-")
    idx = 1 if parts[:1] == ["admin"] else 0
    verb: str | None = None
    if idx + 1 < len(parts) and f"{parts[idx]}-{parts[idx + 1]}" in _VERB_RANK:
        verb = f"{parts[idx]}-{parts[idx + 1]}"
        idx += 2
    elif idx < len(parts) and parts[idx] in _VERB_RANK:
        verb = parts[idx]
        idx += 1
    return verb, "-".join(parts[idx:])


def select_lifecycle_scope(command_names: list[str], *, max_commands: int = 7) -> list[str]:
    """Pick a coherent, stateful command subset from a broad surface.

    Service-agnostic: groups commands by resource noun (singular/plural folded so
    `list-user-pools` joins `create-user-pool`), chooses the resource whose commands
    span the most distinct lifecycle stages so the scope forms a natural
    create -> read -> update -> delete workflow that cross-command tests can
    exercise, orders by lifecycle rank, and caps the count. Returns [] when nothing
    can be grouped (the caller falls back to a plain alphabetical cap).
    """
    groups: dict[str, list[tuple[int, str]]] = {}
    for cmd in command_names:
        verb, resource = _command_verb_resource(cmd)
        if verb is None or not resource:
            continue
        key = resource[:-1] if resource.endswith("s") else resource
        groups.setdefault(key, []).append((_VERB_RANK[verb], cmd))
    if not groups:
        return []

    def _score(item: tuple[str, list[tuple[int, str]]]) -> tuple[int, int, int]:
        _resource, cmds = item
        return (len({rank for rank, _ in cmds}), len(cmds), -len(_resource))

    _key, best = max(groups.items(), key=_score)
    ordered = [cmd for _rank, cmd in sorted(set(best))]
    return ordered[:max_commands]


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
    """Round-robin intents by behaviour_tag for diversity in small slices."""
    buckets: dict[str, list[TestIntent]] = {}
    for i in intents:
        buckets.setdefault(i.behaviour_tag, []).append(i)
    priority = [
        "error_nonexistent",
        "error_invalid_args",
        "error",
        "edge",
        "workflow",
        "happy_path",
    ]
    for tag in list(buckets):
        if tag not in priority:
            priority.append(tag)
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


def _try_cmdline_from_assignment(stmt: ast.AST, prefix_value: str) -> list[str] | None:
    if not (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and stmt.targets[0].id in ("cmdline", "command")
    ):
        return None
    literal_tail = _extract_string_concat_tail(stmt.value)
    if literal_tail is None:
        return None
    return (prefix_value + literal_tail).strip().split()


def _try_cmdline_and_rc_from_call(
    stmt: ast.AST, prefix_value: str
) -> tuple[list[str] | None, int | None]:
    if not (
        isinstance(stmt, ast.Call)
        and isinstance(stmt.func, ast.Attribute)
        and stmt.func.attr in ("run_cmd", "assert_params_for_cmd")
    ):
        return None, None

    cmdline: list[str] | None = None
    if stmt.args:
        literal = _extract_string_concat_tail(stmt.args[0])
        if literal is not None:
            cmdline = (prefix_value + literal).strip().split()

    expected_rc: int | None = None
    for kw in stmt.keywords:
        if (
            kw.arg == "expected_rc"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, int)
        ):
            expected_rc = kw.value.value
    return cmdline, expected_rc


def _collect_operation_names(stmt: ast.AST) -> list[str]:
    if not (
        isinstance(stmt, ast.Call)
        and isinstance(stmt.func, ast.Attribute)
        and stmt.func.attr in ("assertEqual", "assertEquals")
        and len(stmt.args) >= 2
    ):
        return []
    names: list[str] = []
    for arg in stmt.args:
        op_name = _maybe_extract_operation_name(arg)
        if op_name:
            names.append(op_name)
    return names


def _resolve_cmdline_with_fallbacks(
    method: ast.FunctionDef,
    prefix_value: str,
    command: str,
    full_source: str,
    primary: list[str] | None,
) -> list[str]:
    if primary:
        return primary

    # Fallback A: presign-style wrapper — scan BinOp(Add) for self.prefix concat
    for stmt in ast.walk(method):
        if isinstance(stmt, ast.BinOp):
            literal_tail = _extract_string_concat_tail(stmt)
            if literal_tail and (
                literal_tail.startswith("s3://")
                or literal_tail.startswith("--")
                or " " in literal_tail
            ):
                return (prefix_value + literal_tail).strip().split()

    # Fallback B: regex on raw source for any literal containing the command name
    method_source = ast.get_source_segment(full_source, method) or ""
    m = re.search(
        r"['\"]\s*((?:[a-z0-9_]+\s+){0,3}" + re.escape(command) + r"\b[^'\"]*)['\"]",
        method_source,
    )
    if m:
        return m.group(1).strip().split()

    return [command]


def _extract_intent_from_method(
    *,
    method: ast.FunctionDef,
    prefix_value: str,
    command: str,
    source_file: str,
    full_source: str,
) -> TestIntent | None:
    cmdline: list[str] | None = None
    expected_exit = 0
    expected_state_calls: list[str] = []
    expected_stdout_pattern: str | None = None

    for stmt in ast.walk(method):
        assigned = _try_cmdline_from_assignment(stmt, prefix_value)
        if assigned is not None:
            cmdline = assigned

        call_cmd, call_rc = _try_cmdline_and_rc_from_call(stmt, prefix_value)
        if cmdline is None and call_cmd is not None:
            cmdline = call_cmd
        if call_rc is not None:
            expected_exit = call_rc

        for op in _collect_operation_names(stmt):
            if op not in expected_state_calls:
                expected_state_calls.append(op)

    cmdline = _resolve_cmdline_with_fallbacks(method, prefix_value, command, full_source, cmdline)

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


# ---------------------------------------------------------------------------
# botocore service-model extraction (for services whose CLI verbs are
# model-generated, e.g. `aws dynamodb`, rather than an awscli customization
# with a `subcommands.py` + `tests/functional/<svc>/test_*_command.py` corpus).
#
# The reader consumes the vendored `botocore/data/<service>/*/service-2.json`
# as STATIC JSON off disk (json.loads) — it NEVER `import botocore`, so shipped
# tasks keep the no-boto/botocore/moto guarantee. It surfaces the target
# operations as CommandSpecs and synthesises TestIntents from the request /
# response / error shapes (there are no white-box test files to lift from).
# ---------------------------------------------------------------------------


# DynamoDB Data-Plane API version (the X-Amz-Target suffix is DynamoDB_20120810).
_DDB_API_VERSION = "2012-08-10"

# The 8 in-scope pilot verbs (DYNAMODB-02-SCOPE §1), as CamelCase operation
# names. Used as the default target set for botocore_model extraction.
_DDB_TARGET_OPS_DEFAULT: tuple[str, ...] = (
    "CreateTable",
    "DeleteTable",
    "ListTables",
    "PutItem",
    "GetItem",
    "UpdateItem",
    "DeleteItem",
    "Query",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_doc(text: str, *, limit: int = 500) -> str:
    """Flatten botocore's HTML documentation into a short plain-text blurb."""
    if not text:
        return ""
    plain = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()
    if len(plain) > limit:
        plain = plain[:limit].rstrip() + " ..."
    return plain


def _camel_to_kebab(name: str) -> str:
    """botocore-style casing: CreateTable -> create-table, SSESpecification ->
    sse-specification. Handles acronym runs correctly."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1-\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s1)
    return s2.lower()


def _op_to_cli_name(op: str) -> str:
    """CreateTable -> create-table (the `aws dynamodb <verb>` name)."""
    return _camel_to_kebab(op)


def _member_to_flag(member: str) -> str:
    """TableName -> --table-name (the aws-cli long option for an input member)."""
    return "--" + _camel_to_kebab(member)


def find_service_model_json(
    clone_dir: Path,
    service: str,
    *,
    override: str | None = None,
) -> Path:
    """Locate `botocore/data/<service>/<api-version>/service-2.json` in the clone.

    Read as a STATIC JSON data file, never via `import botocore`. When several
    API-version directories exist, the lexically greatest (latest) is chosen.
    `override` may point at either the service-2.json directly or a botocore
    data dir to search under.
    """
    if override:
        p = Path(override)
        if p.is_file():
            return p
        if p.is_dir():
            hits = sorted(p.rglob("service-2.json"))
            if hits:
                return hits[-1]
        raise FileNotFoundError(f"cli_app_service_model_override not usable: {override}")

    matches = sorted(clone_dir.rglob(f"botocore/data/{service}/*/service-2.json"))
    if not matches:
        raise RuntimeError(
            f"could not locate botocore service model for service={service!r} under "
            f"{clone_dir} (looked for botocore/data/{service}/*/service-2.json). "
            "Pass --pipeline-opt cli_app_service_model_override=<abs-path-to-service-2.json>."
        )
    # Prefer the greatest API-version directory (…/dynamodb/2012-08-10/service-2.json).
    matches.sort(key=lambda p: p.parent.name)
    return matches[-1]


def _shape_summary(model: dict, shape_name: str) -> str:
    """One-line type description for a shape reference (for the spec blurb)."""
    shape = model.get("shapes", {}).get(shape_name, {})
    stype = shape.get("type", "")
    if stype == "list":
        member = shape.get("member", {}).get("shape", "item")
        return f"list of {member}"
    if stype == "map":
        val = shape.get("value", {}).get("shape", "value")
        return f"map to {val}"
    if stype == "structure":
        return f"structure ({shape_name})"
    return stype or shape_name


def extract_cli_spec_from_model(
    clone_dir: Path,
    command_prefix: str,
    *,
    repo: str,
    git_sha: str,
    target_operations: tuple[str, ...] = _DDB_TARGET_OPS_DEFAULT,
    model_path_override: str | None = None,
) -> tuple[CliSpec, dict]:
    """Build a CliSpec from a botocore service model, filtered to target ops.

    Returns (spec, model) — the parsed service-2.json is returned so intent
    synthesis can walk the request/response/error shapes without re-reading.
    """
    model_path = find_service_model_json(clone_dir, command_prefix, override=model_path_override)
    model = json.loads(model_path.read_text(encoding="utf-8", errors="replace"))
    operations = model.get("operations", {})

    commands: list[CommandSpec] = []
    for op in target_operations:
        op_def = operations.get(op)
        if op_def is None:
            logger.warning(
                "botocore_model: operation %s not found in %s (available: %d ops)",
                op,
                model_path.name,
                len(operations),
            )
            continue
        input_shape = _op_input_shape(model, op_def)
        flags = sorted(_member_to_flag(m) for m in input_shape.get("members", {}))
        commands.append(
            CommandSpec(
                name=_op_to_cli_name(op),
                synopsis=_strip_doc(op_def.get("documentation", ""), limit=200),
                args=[],
                flags=flags,
            )
        )
    if not commands:
        raise RuntimeError(
            f"botocore_model: none of the target operations {list(target_operations)} "
            f"were found in {model_path}"
        )

    spec = CliSpec(
        name=f"aws_cli_{command_prefix}",
        command_prefix=command_prefix,
        repo=repo,
        git_sha=git_sha,
        entry_point=str(_safe_relpath(model_path, clone_dir)),
        tests_dir="",
        commands=commands,
    )
    spec.spec_sha256 = _canonical_spec_hash(spec)
    return spec, model


def _safe_relpath(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return Path(path.name)


def _op_input_shape(model: dict, op_def: dict) -> dict:
    shape_name = (op_def.get("input") or {}).get("shape")
    if not shape_name:
        return {}
    return model.get("shapes", {}).get(shape_name, {})


def _slug(v: object) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(v)).strip("_").lower() or "x"


def _resolved_input_members(model: dict, op_def: dict) -> dict[str, dict]:
    """member name -> resolved shape dict (carries type/enum/min/max)."""
    raw = _op_input_shape(model, op_def).get("members") or {}
    shapes = model.get("shapes", {})
    resolved: dict[str, dict] = {}
    for m, ref in raw.items():
        shape_name = ref.get("shape") if isinstance(ref, dict) else None
        resolved[m] = (shapes.get(shape_name) or {}) if shape_name else {}
    return resolved


def _pairwise_optional_combos(optional: list[str], cap: int) -> list[frozenset[str]]:
    """Bounded strength-2 optional-flag cover in n+1 rows (not 2**n).

    The required-only happy path supplies the all-OFF row; {all-ON} plus each
    {all-but-one} row then makes every optional-flag pair take all four on/off
    combinations. Deterministic; truncated to ``cap``.
    """
    if not optional or cap <= 0:
        return []
    rows: list[frozenset[str]] = [frozenset(optional)]
    rows += [frozenset(o for o in optional if o != drop) for drop in optional]
    seen: set[frozenset[str]] = set()
    out: list[frozenset[str]] = []
    for row in rows:
        if not row or row in seen:
            continue
        seen.add(row)
        out.append(row)
    return out[:cap]


_NUMERIC_SHAPE_TYPES = frozenset({"integer", "long", "double", "float"})

# A length-boundary probe longer than this is skipped. A multi-KB/MB filler (e.g.
# Kinesis's 1 MB Data blob or a large NextToken max) is untestable as a literal CLI
# arg and, aggregated across a subset's intents, blows the oracle LLM prompt past
# its context window. Numeric boundaries are unaffected (they stringify to a few chars).
_MAX_BOUNDARY_FILLER_LEN = 1024


def _boundary_value(shape: dict, n: int) -> str | None:
    """Concrete value hitting count ``n`` for a shape's min/max: the number itself
    for numeric shapes, an n-length filler for length-constrained shapes. None when
    ``n`` is unrepresentable (n < 0) or pathologically long (> _MAX_BOUNDARY_FILLER_LEN)."""
    if shape.get("type", "string") in _NUMERIC_SHAPE_TYPES:
        return str(n)
    if n < 0 or n > _MAX_BOUNDARY_FILLER_LEN:
        return None
    return "x" * n


def _boundary_probes(shape: dict) -> list[tuple[str, int, str, int]]:
    """(kind, count, behaviour_tag, exit) probes for a shape's min/max, if any."""
    probes: list[tuple[str, int, str, int]] = []
    lo, hi = shape.get("min"), shape.get("max")
    if isinstance(lo, int):
        probes.append(("boundary_min", lo, "edge", 0))
        probes.append(("boundary_below_min", lo - 1, "error_invalid_args", 252))
    if isinstance(hi, int):
        probes.append(("boundary_max", hi, "edge", 0))
        probes.append(("boundary_above_max", hi + 1, "error_invalid_args", 252))
    return probes


def _coverage_matrix_intents(
    model: dict,
    op_def: dict,
    *,
    op_name: str,
    command: str,
    command_prefix: str,
    max_optional_combos: int,
    mutually_exclusive: tuple[tuple[str, ...], ...] = (),
) -> list[TestIntent]:
    """Service-model scenario matrix for one command (no LLM, no per-service constants).

    De-duplicated by argv signature: pairwise optional-flag combinations
    (happy_path), one case per enum value (edge), in-range boundary values (edge)
    and out-of-range ones (error_invalid_args), and mutually-exclusive flag
    conflicts (error_invalid_args). Reads only the botocore shape model, so it is
    the automatic substitute for hand-authored edge cases on any AWS service.
    """
    input_shape = _op_input_shape(model, op_def)
    members_dict = input_shape.get("members") or {}
    members = list(members_dict.keys())
    required = [m for m in (input_shape.get("required") or []) if m in members]
    optional = [m for m in members if m not in required]
    resolved = _resolved_input_members(model, op_def)
    op_doc = _strip_doc(op_def.get("documentation", ""))
    member_lines = _render_member_lines(model, members_dict, required)
    errors = [e.get("shape", "") for e in op_def.get("errors", []) if e.get("shape")]

    seen: set[tuple[str, ...]] = set()
    out: list[TestIntent] = []

    def _argv(overrides: dict[str, str] | None = None, extra: list[str] | None = None) -> list[str]:
        ov = overrides or {}
        argv = [command_prefix, command]
        for m in required:
            argv += [_member_to_flag(m), ov.get(m, "<value>")]
        return argv + (extra or [])

    def _emit(kind: str, argv: list[str], tag: str, exit_code: int) -> None:
        sig = tuple(argv)
        if sig in seen:
            return
        seen.add(sig)
        out.append(
            _make_model_intent(
                command=command,
                command_prefix=command_prefix,
                op_name=op_name,
                kind=kind,
                cmdline=argv,
                expected_exit=exit_code,
                behaviour_tag=tag,
                raw_source=_spec_block(
                    op_name,
                    command_prefix,
                    command,
                    op_doc,
                    member_lines,
                    errors,
                    kind="happy" if exit_code == 0 else "invalid_arg",
                    detail=kind,
                ),
                state_calls=[op_name] if exit_code == 0 else [],
            )
        )

    conflict_groups = [set(g) for g in mutually_exclusive]
    for i, combo in enumerate(_pairwise_optional_combos(optional, max_optional_combos)):
        combo_flags = {_member_to_flag(m) for m in combo}
        if any(g <= combo_flags for g in conflict_groups):
            continue
        extra: list[str] = []
        for m in optional:
            if m in combo:
                extra += [_member_to_flag(m), "<value>"]
        _emit(f"opt_combo_{i:02d}", _argv(extra=extra), "happy_path", 0)

    for m, shape in resolved.items():
        for v in shape.get("enum") or []:
            argv = (
                _argv(overrides={m: str(v)})
                if m in required
                else _argv(extra=[_member_to_flag(m), str(v)])
            )
            _emit(f"enum_{_camel_to_kebab(m)}_{_slug(v)}", argv, "edge", 0)

    for m, shape in resolved.items():
        for kind, n, tag, exit_code in _boundary_probes(shape):
            val = _boundary_value(shape, n)
            if val is None:
                continue
            argv = (
                _argv(overrides={m: val})
                if m in required
                else _argv(extra=[_member_to_flag(m), val])
            )
            _emit(f"{kind}_{_camel_to_kebab(m)}", argv, tag, exit_code)

    cmd_flags = {_member_to_flag(m) for m in required + optional}
    required_flags = {_member_to_flag(m) for m in required}
    for group in mutually_exclusive:
        present = [f for f in group if f in cmd_flags]
        if len(present) < 2:
            continue
        argv_extra: list[str] = []
        for f in present:
            if f not in required_flags:
                argv_extra += [f, "<value>"]
        _emit(
            "conflict_" + _slug("_".join(present)),
            _argv(extra=argv_extra),
            "error_invalid_args",
            252,
        )

    return out


def synthesize_intents_from_model(
    model: dict,
    command: str,
    command_prefix: str,
    *,
    target_operations: tuple[str, ...] = _DDB_TARGET_OPS_DEFAULT,
    max_intents: int | None = None,
    combinations: bool = False,
    max_optional_combos: int = 0,
    mutually_exclusive: tuple[tuple[str, ...], ...] = (),
    happy_variants: int | None = None,
) -> list[TestIntent]:
    """Synthesise TestIntents for one CLI command from its model operation.

    Produces a diverse set (happy-path, a missing-required-arg error, and one
    intent per modeled service error) whose `raw_source` is a synthesised
    behavioural spec block (op docs + input-member table + the specific error
    under test) — this seeds the LLM translation prompt in lieu of a white-box
    test. Returns [] if the command has no matching operation.
    """
    op_name = _command_to_op(command, target_operations)
    operations = model.get("operations", {})
    op_def = operations.get(op_name) if op_name else None
    if op_def is None:
        return []

    input_shape = _op_input_shape(model, op_def)
    members = input_shape.get("members", {})
    required = list(input_shape.get("required", []))
    op_doc = _strip_doc(op_def.get("documentation", ""))
    member_lines = _render_member_lines(model, members, required)
    errors = [e.get("shape", "") for e in op_def.get("errors", []) if e.get("shape")]

    happy_cmd = [command_prefix, command]
    for m in required:
        ph = _placeholder_for_shape(model, members.get(m, {}).get("shape", ""))
        happy_cmd.extend([_member_to_flag(m), ph])

    out: list[TestIntent] = []

    for variant_ix in range(
        happy_variants if happy_variants is not None else _HAPPY_PATH_VARIANTS_PER_CMD
    ):
        variant_cmd = [command_prefix, command]
        for m in required:
            ph = _placeholder_for_shape(
                model, members.get(m, {}).get("shape", ""), variant=variant_ix
            )
            variant_cmd.extend([_member_to_flag(m), ph])
        out.append(
            _make_model_intent(
                command=command,
                command_prefix=command_prefix,
                op_name=op_name,
                kind=f"happy_v{variant_ix}",
                cmdline=variant_cmd,
                expected_exit=0,
                behaviour_tag="happy_path",
                raw_source=_spec_block(
                    op_name,
                    command_prefix,
                    command,
                    op_doc,
                    member_lines,
                    errors,
                    kind="happy",
                    detail=f"variant {variant_ix}",
                ),
                state_calls=[op_name],
            )
        )

    for missing in required:
        bad_cmd = [command_prefix, command]
        for m in required:
            if m == missing:
                continue
            ph = _placeholder_for_shape(model, members.get(m, {}).get("shape", ""))
            bad_cmd.extend([_member_to_flag(m), ph])
        out.append(
            _make_model_intent(
                command=command,
                command_prefix=command_prefix,
                op_name=op_name,
                kind=f"missing_{_camel_to_kebab(missing)}",
                cmdline=bad_cmd,
                expected_exit=252,
                behaviour_tag="error_invalid_args",
                raw_source=_spec_block(
                    op_name,
                    command_prefix,
                    command,
                    op_doc,
                    member_lines,
                    errors,
                    kind="missing_required",
                    detail=_member_to_flag(missing),
                ),
                state_calls=[],
            )
        )

    if required:
        for extra_kind in _INVALID_ARGS_EXTRA_KINDS:
            corrupted_cmd = _mutate_cmdline_for_kind(
                model,
                members,
                required,
                command_prefix,
                command,
                kind=extra_kind,
            )
            if corrupted_cmd is None:
                continue
            out.append(
                _make_model_intent(
                    command=command,
                    command_prefix=command_prefix,
                    op_name=op_name,
                    kind=extra_kind,
                    cmdline=corrupted_cmd,
                    expected_exit=252,
                    behaviour_tag="error_invalid_args",
                    raw_source=_spec_block(
                        op_name,
                        command_prefix,
                        command,
                        op_doc,
                        member_lines,
                        errors,
                        kind="invalid_arg",
                        detail=extra_kind,
                    ),
                    state_calls=[],
                )
            )

    if required:
        for err in errors:
            err_tag = _classify_service_error(err)
            out.append(
                _make_model_intent(
                    command=command,
                    command_prefix=command_prefix,
                    op_name=op_name,
                    kind=f"err_{_camel_to_kebab(err)}",
                    cmdline=list(happy_cmd),
                    expected_exit=254,
                    behaviour_tag=err_tag,
                    raw_source=_spec_block(
                        op_name,
                        command_prefix,
                        command,
                        op_doc,
                        member_lines,
                        errors,
                        kind="service_error",
                        detail=err,
                    ),
                    state_calls=[op_name],
                    error_category=err,
                )
            )

    out.extend(
        _edge_intents_for_op(
            op_name=op_name,
            command_prefix=command_prefix,
            command=command,
            op_doc=op_doc,
            member_lines=member_lines,
            errors=errors,
        )
    )

    if combinations:
        out.extend(
            _coverage_matrix_intents(
                model,
                op_def,
                op_name=op_name,
                command=command,
                command_prefix=command_prefix,
                max_optional_combos=max_optional_combos,
                mutually_exclusive=mutually_exclusive,
            )
        )

    out = _interleave_by_behaviour(out)
    if max_intents:
        out = out[:max_intents]
    return out


def _command_to_op(command: str, target_operations: tuple[str, ...]) -> str | None:
    """Reverse `create-table` -> `CreateTable` by matching the target op set."""
    for op in target_operations:
        if _op_to_cli_name(op) == command:
            return op
    return None


def _render_member_lines(model: dict, members: dict, required: list[str]) -> list[str]:
    lines: list[str] = []
    req_set = set(required)
    for name, ref in members.items():
        flag = _member_to_flag(name)
        summary = _shape_summary(model, ref.get("shape", ""))
        doc = _strip_doc(ref.get("documentation", ""), limit=140)
        tag = "required" if name in req_set else "optional"
        suffix = f" — {doc}" if doc else ""
        lines.append(f"- `{flag}` ({name}, {tag}, {summary}){suffix}")
    return lines


def _spec_block(
    op_name: str,
    command_prefix: str,
    command: str,
    op_doc: str,
    member_lines: list[str],
    errors: list[str],
    *,
    kind: str,
    detail: str = "",
) -> str:
    """Render a behavioural spec block (NOT test code) used as translation context."""
    parts = [f"Operation: {op_name}  (aws {command_prefix} {command})"]
    if op_doc:
        parts.append("")
        parts.append(op_doc)
    if member_lines:
        parts.append("")
        parts.append("Parameters:")
        parts.extend(member_lines)
    if errors:
        parts.append("")
        parts.append("Modeled service errors: " + ", ".join(errors))
    parts.append("")
    if kind == "happy":
        parts.append(
            "This intent tests the HAPPY PATH: a valid invocation must succeed "
            "(exit 0) and its effect must be observable via an independent read."
        )
    elif kind == "missing_required":
        parts.append(
            f"This intent tests a PARAMETER ERROR: omitting the required {detail} "
            "option must fail (non-zero exit); assert `returncode != 0`, never an "
            "exact code."
        )
    elif kind == "service_error":
        parts.append(
            f"This intent tests the SERVICE ERROR `{detail}`: the invocation must "
            f"fail with `{detail}` surfaced in stderr (assert the error-code "
            "substring, never verbatim wording)."
        )
    elif kind == "edge":
        parts.append(
            "This intent tests a DDB-SEMANTIC EDGE CASE: "
            + detail
            + " Prefer asserting observable state via an independent read "
            "over inspecting stdout wording."
        )
    return "\n".join(parts)


def _make_model_intent(
    *,
    command: str,
    command_prefix: str,
    op_name: str,
    kind: str,
    cmdline: list[str],
    expected_exit: int,
    behaviour_tag: Literal[
        "happy_path",
        "error",
        "error_nonexistent",
        "error_invalid_args",
        "edge",
        "workflow",
    ],
    raw_source: str,
    state_calls: list[str],
    error_category: str | None = None,
) -> TestIntent:
    h = hashlib.sha256()
    h.update(command_prefix.encode())
    h.update(b"\0")
    h.update(op_name.encode())
    h.update(b"\0")
    h.update(kind.encode())
    return TestIntent(
        source_file=f"{command_prefix}/service-2.json",
        test_name=f"model_{command.replace('-', '_')}_{kind}",
        source_method_sha256=h.hexdigest(),
        command=command,
        cmdline_template=cmdline,
        expected_exit=expected_exit,
        expected_state_calls=state_calls,
        expected_stdout_pattern=None,
        behaviour_tag=behaviour_tag,
        raw_source=raw_source,
        error_category=error_category,
    )


_SHAPE_TYPE_TO_PLACEHOLDER: dict[str, str] = {
    "string": "<string>",
    "integer": "<number>",
    "long": "<number>",
    "double": "<number>",
    "float": "<number>",
    "boolean": "<boolean>",
    "timestamp": "<timestamp>",
    "blob": "<blob>",
    "list": "<json>",
    "map": "<json>",
    "structure": "<json>",
}


def _placeholder_for_shape(model: dict, shape_name: str, *, variant: int = 0) -> str:
    shape = model.get("shapes", {}).get(shape_name, {}) if shape_name else {}
    base = _SHAPE_TYPE_TO_PLACEHOLDER.get(shape.get("type", "string"), "<string>")
    if variant == 0:
        return base
    return base.replace(">", f"_v{variant}>", 1) if base.endswith(">") else f"{base}_v{variant}"


_HAPPY_PATH_VARIANTS_PER_CMD = 8

_INVALID_ARGS_EXTRA_KINDS: tuple[str, ...] = (
    "unknown_flag",
    "empty_value",
    "malformed_json",
    "duplicate_flag",
    "too_long_value",
)

_NONEXISTENT_ERROR_MARKERS: tuple[str, ...] = (
    "NotFound",
    "NotExists",
    "Missing",
    "Unknown",
    "DoesNotExist",
    "NoSuch",
)


def _classify_service_error(err_name: str) -> str:
    for marker in _NONEXISTENT_ERROR_MARKERS:
        if marker.lower() in err_name.lower():
            return "error_nonexistent"
    return "error_invalid_args"


@dataclass(slots=True, frozen=True)
class _EdgeSpec:
    kind: str
    argv_tail: tuple[str, ...]
    expected_exit: int
    description: str
    state_calls: tuple[str, ...] = ()


_TN = "<string>"

_EDGE_CASES_BY_OP: dict[str, tuple[_EdgeSpec, ...]] = {
    "CreateTable": (
        _EdgeSpec(
            kind="edge_composite_key",
            argv_tail=(
                "--table-name",
                _TN,
                "--attribute-definitions",
                "AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=N",
                "--key-schema",
                "AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE",
                "--billing-mode",
                "PAY_PER_REQUEST",
            ),
            expected_exit=0,
            description=(
                "creates a table with a COMPOSITE PRIMARY KEY (HASH partition key "
                "`pk` + RANGE sort key `sk`). The described KeySchema must contain "
                "both entries in HASH,RANGE order."
            ),
            state_calls=("CreateTable", "DescribeTable"),
        ),
        _EdgeSpec(
            kind="edge_provisioned_throughput",
            argv_tail=(
                "--table-name",
                _TN,
                "--attribute-definitions",
                "AttributeName=id,AttributeType=S",
                "--key-schema",
                "AttributeName=id,KeyType=HASH",
                "--billing-mode",
                "PROVISIONED",
                "--provisioned-throughput",
                "ReadCapacityUnits=5,WriteCapacityUnits=5",
            ),
            expected_exit=0,
            description=(
                "creates a table with `BillingMode=PROVISIONED` and explicit "
                "ReadCapacityUnits=5 / WriteCapacityUnits=5. DescribeTable must "
                "surface BillingModeSummary.BillingMode == 'PROVISIONED' and the "
                "declared throughput."
            ),
            state_calls=("CreateTable", "DescribeTable"),
        ),
    ),
    "PutItem": (
        _EdgeSpec(
            kind="edge_multi_type_item",
            argv_tail=(
                "--table-name",
                _TN,
                "--item",
                '{"id":{"S":"k1"},"count":{"N":"42"},"live":{"BOOL":true},"tags":{"L":[{"S":"a"},{"S":"b"}]}}',
            ),
            expected_exit=0,
            description=(
                "puts an item with heterogeneous attribute types (S, N, BOOL, L). "
                "A follow-up GetItem must round-trip every attribute with its "
                "declared type marker intact."
            ),
            state_calls=("PutItem", "GetItem"),
        ),
        _EdgeSpec(
            kind="edge_condition_attribute_not_exists",
            argv_tail=(
                "--table-name",
                _TN,
                "--item",
                '{"id":{"S":"k1"},"v":{"S":"first"}}',
                "--condition-expression",
                "attribute_not_exists(id)",
            ),
            expected_exit=0,
            description=(
                "puts an item guarded by `attribute_not_exists(id)`. On a fresh "
                "table the write MUST succeed. A second PutItem with the same "
                "condition MUST fail with ConditionalCheckFailedException — but "
                "this intent only asserts the first (successful) branch."
            ),
            state_calls=("PutItem", "GetItem"),
        ),
    ),
    "GetItem": (
        _EdgeSpec(
            kind="edge_missing_item_empty_response",
            argv_tail=(
                "--table-name",
                _TN,
                "--key",
                '{"id":{"S":"does-not-exist"}}',
            ),
            expected_exit=0,
            description=(
                "GetItem for a key that was never written returns exit 0 with NO "
                "`Item` key in the response payload (DDB semantics: absence is not "
                "an error). Assert either the absence of `Item` in the parsed "
                "stdout JSON, or an empty dict returned."
            ),
            state_calls=("GetItem",),
        ),
        _EdgeSpec(
            kind="edge_consistent_read",
            argv_tail=(
                "--table-name",
                _TN,
                "--key",
                '{"id":{"S":"k1"}}',
                "--consistent-read",
            ),
            expected_exit=0,
            description=(
                "GetItem with strongly-consistent read (`--consistent-read` sets "
                "ConsistentRead=true). After a preceding PutItem, the value must "
                "be retrievable in the same call."
            ),
            state_calls=("PutItem", "GetItem"),
        ),
    ),
    "DeleteItem": (
        _EdgeSpec(
            kind="edge_missing_item_idempotent",
            argv_tail=(
                "--table-name",
                _TN,
                "--key",
                '{"id":{"S":"never-existed"}}',
            ),
            expected_exit=0,
            description=(
                "DeleteItem on a key that was never written returns exit 0 (DDB "
                "is idempotent for delete). No `Attributes` field is expected in "
                "the response payload."
            ),
            state_calls=("DeleteItem",),
        ),
        _EdgeSpec(
            kind="edge_condition_attribute_exists_fails",
            argv_tail=(
                "--table-name",
                _TN,
                "--key",
                '{"id":{"S":"never-existed"}}',
                "--condition-expression",
                "attribute_exists(id)",
            ),
            expected_exit=254,
            description=(
                "DeleteItem guarded by `attribute_exists(id)` against a missing "
                "key MUST fail with ConditionalCheckFailedException (CLI exit "
                "254). Assert the error code substring in stderr; state must be "
                "unchanged."
            ),
            state_calls=("DeleteItem",),
        ),
    ),
    "UpdateItem": (
        _EdgeSpec(
            kind="edge_set_expression",
            argv_tail=(
                "--table-name",
                _TN,
                "--key",
                '{"id":{"S":"k1"}}',
                "--update-expression",
                "SET v = :v",
                "--expression-attribute-values",
                '{":v":{"S":"updated"}}',
            ),
            expected_exit=0,
            description=(
                "UpdateItem with `SET v = :v` on an existing item overwrites the "
                "attribute. A follow-up GetItem must show v == {'S':'updated'}."
            ),
            state_calls=("PutItem", "UpdateItem", "GetItem"),
        ),
        _EdgeSpec(
            kind="edge_add_increment",
            argv_tail=(
                "--table-name",
                _TN,
                "--key",
                '{"id":{"S":"k1"}}',
                "--update-expression",
                "ADD c :inc",
                "--expression-attribute-values",
                '{":inc":{"N":"1"}}',
            ),
            expected_exit=0,
            description=(
                "UpdateItem with `ADD c :inc` on an item whose `c` starts at 0 "
                "MUST leave `c == {'N':'1'}` (or increment an existing value by "
                "1). GetItem verifies."
            ),
            state_calls=("PutItem", "UpdateItem", "GetItem"),
        ),
    ),
    "Query": (
        _EdgeSpec(
            kind="edge_key_condition_equals",
            argv_tail=(
                "--table-name",
                _TN,
                "--key-condition-expression",
                "id = :pk",
                "--expression-attribute-values",
                '{":pk":{"S":"k1"}}',
            ),
            expected_exit=0,
            description=(
                "Query with `KeyConditionExpression = id = :pk` against a table "
                "seeded with one matching item returns Count=1 and Items[0] "
                "matches. The `--expression-attribute-values` JSON binds :pk."
            ),
            state_calls=("PutItem", "Query"),
        ),
        _EdgeSpec(
            kind="edge_limit_one",
            argv_tail=(
                "--table-name",
                _TN,
                "--key-condition-expression",
                "id = :pk",
                "--expression-attribute-values",
                '{":pk":{"S":"k1"}}',
                "--limit",
                "1",
            ),
            expected_exit=0,
            description=(
                "Query with `--limit 1` against a table with multiple matching "
                "items returns exactly one Item and `Count == 1`. Do NOT assert "
                "LastEvaluatedKey presence (DDB Local sometimes omits it)."
            ),
            state_calls=("PutItem", "Query"),
        ),
    ),
    "ListTables": (
        _EdgeSpec(
            kind="edge_limit_one",
            argv_tail=(
                "--limit",
                "1",
            ),
            expected_exit=0,
            description=(
                "ListTables with `--limit 1` returns at most one entry in "
                "TableNames. When more than one table exists the response MAY "
                "include LastEvaluatedTableName — assert only the length bound."
            ),
            state_calls=("CreateTable", "ListTables"),
        ),
    ),
    "DeleteTable": (
        _EdgeSpec(
            kind="edge_delete_then_describe",
            argv_tail=(
                "--table-name",
                _TN,
            ),
            expected_exit=0,
            description=(
                "DeleteTable succeeds (exit 0). A follow-up DescribeTable on the "
                "same name MUST surface `ResourceNotFoundException`. This intent "
                "asserts the delete succeeded; the follow-up assertion belongs "
                "in the test body."
            ),
            state_calls=("CreateTable", "DeleteTable", "DescribeTable"),
        ),
    ),
}


def _edge_intents_for_op(
    op_name: str,
    command_prefix: str,
    command: str,
    op_doc: str,
    member_lines: list[str],
    errors: list[str],
) -> list[TestIntent]:
    """Hand-authored DDB-semantic edges from _EDGE_CASES_BY_OP; unlike the rest of this module these are NOT derived from the botocore model."""
    specs = _EDGE_CASES_BY_OP.get(op_name, ())
    out: list[TestIntent] = []
    for spec in specs:
        out.append(
            _make_model_intent(
                command=command,
                command_prefix=command_prefix,
                op_name=op_name,
                kind=spec.kind,
                cmdline=[command_prefix, command, *spec.argv_tail],
                expected_exit=spec.expected_exit,
                behaviour_tag="edge",
                raw_source=_spec_block(
                    op_name,
                    command_prefix,
                    command,
                    op_doc,
                    member_lines,
                    errors,
                    kind="edge",
                    detail=spec.description,
                ),
                state_calls=list(spec.state_calls),
            )
        )
    return out


def _mutate_cmdline_for_kind(
    model: dict,
    members: dict,
    required: list[str],
    command_prefix: str,
    command: str,
    *,
    kind: str,
) -> list[str] | None:
    base = [command_prefix, command]
    for m in required:
        ph = _placeholder_for_shape(model, members.get(m, {}).get("shape", ""))
        base.extend([_member_to_flag(m), ph])
    if kind == "unknown_flag":
        return [*base, "--not-a-real-flag", "x"]
    if kind == "empty_value":
        if not required:
            return None
        out = [command_prefix, command]
        for m in required:
            ph = _placeholder_for_shape(model, members.get(m, {}).get("shape", ""))
            if m == required[0]:
                out.extend([_member_to_flag(m), ""])
            else:
                out.extend([_member_to_flag(m), ph])
        return out
    if kind == "malformed_json":
        return [*base, "--attribute-definitions", "{not valid json"]
    if kind == "duplicate_flag":
        if not required:
            return None
        out = list(base)
        first = required[0]
        ph = _placeholder_for_shape(model, members.get(first, {}).get("shape", ""))
        out.extend([_member_to_flag(first), ph])
        return out
    if kind == "too_long_value":
        if not required:
            return None
        out = [command_prefix, command]
        for m in required:
            if m == required[0]:
                out.extend([_member_to_flag(m), "x" * 512])
            else:
                ph = _placeholder_for_shape(model, members.get(m, {}).get("shape", ""))
                out.extend([_member_to_flag(m), ph])
        return out
    return None
