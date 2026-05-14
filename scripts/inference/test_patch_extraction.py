#!/usr/bin/env python3
"""Unit tests for patch extraction and related helpers.

Tests critical code paths fixed for the GLM-5 inference re-run.
All tests mock workspace.execute_command() — no OpenHands SDK needed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Stub unavailable SDK modules so openhands_mode can import ──────────

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parents[1]

# swefficiency.observability is inside the nested swefficiency/ package;
# not importable from this location without full install. Stub it.
_obs_stub = types.ModuleType("swefficiency.observability")
_obs_stub.setup_helicone = lambda *a, **kw: None  # type: ignore[attr-defined]

_swe_stub = sys.modules.setdefault("swefficiency", types.ModuleType("swefficiency"))
_swe_stub.__path__ = [str(_PROJECT_ROOT / "swefficiency")]  # type: ignore[attr-defined]
sys.modules.setdefault("swefficiency.observability", _obs_stub)

sys.path.insert(0, str(_SCRIPTS_DIR))

from openhands_mode import (  # noqa: E402
    WorkspaceCommandError,
    _PATCH_SIZE_WARN_BYTES,
    _SHA_RE,
    _extract_patch,
    _run_cmd,
)
from openhands_output import (  # noqa: E402
    OpenHandsResult,
    _validate_result,
    convert_to_predictions_jsonl,
    write_eval_output,
)


@dataclass
class MockCommandResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    timeout_occurred: bool = False


def _make_workspace(_side_effect=None, **call_map) -> MagicMock:
    ws = MagicMock()
    if _side_effect:
        ws.execute_command.side_effect = _side_effect
    elif call_map:

        def _dispatch(cmd: str) -> MockCommandResult:
            for key, result in call_map.items():
                if key in cmd:
                    return result
            return MockCommandResult(exit_code=0, stdout="", stderr="")

        ws.execute_command.side_effect = _dispatch
    else:
        ws.execute_command.return_value = MockCommandResult()
    return ws


FAKE_SHA = "a" * 40
WORKING_DIR = "/workspace/pallets__flask__3.0"
SAMPLE_DIFF = (
    "diff --git a/src/flask/app.py b/src/flask/app.py\n"
    "index abc1234..def5678 100644\n"
    "--- a/src/flask/app.py\n"
    "+++ b/src/flask/app.py\n"
    "@@ -100,6 +100,7 @@ class Flask:\n"
    "     def __init__(self):\n"
    "         self.debug = False\n"
    "+        self.new_field = True\n"
)


def _happy_dispatch(cmd: str) -> MockCommandResult:
    if "test -f" in cmd and ".git/HEAD" in cmd:
        return MockCommandResult(exit_code=0)
    if "grep -qF '__pycache__/'" in cmd:
        return MockCommandResult(exit_code=0)
    if "git add -A" in cmd:
        return MockCommandResult(exit_code=0)
    if "git status --porcelain" in cmd:
        return MockCommandResult(exit_code=0, stdout=" M src/flask/app.py\n")
    if "git --no-pager diff --no-color" in cmd:
        return MockCommandResult(exit_code=0, stdout=SAMPLE_DIFF)
    return MockCommandResult(exit_code=0, stdout="")


# ── _run_cmd tests ─────────────────────────────────────────────────────

class TestRunCmd:

    def test_success_returns_stripped_stdout(self):
        ws = _make_workspace()
        ws.execute_command.return_value = MockCommandResult(
            exit_code=0, stdout="  hello world  \n"
        )
        assert _run_cmd(ws, "echo hello") == "hello world"

    def test_critical_failure_raises(self):
        ws = _make_workspace()
        ws.execute_command.return_value = MockCommandResult(
            exit_code=128, stderr="fatal: not a git repo"
        )
        with pytest.raises(WorkspaceCommandError) as exc_info:
            _run_cmd(ws, "git status", critical=True)
        assert exc_info.value.exit_code == 128
        assert "not a git repo" in exc_info.value.stderr

    def test_non_critical_failure_returns_empty(self):
        ws = _make_workspace()
        ws.execute_command.return_value = MockCommandResult(
            exit_code=1, stderr="some error"
        )
        assert _run_cmd(ws, "git config foo", critical=False) == ""

    def test_timeout_critical_raises(self):
        ws = _make_workspace()
        ws.execute_command.return_value = MockCommandResult(
            timeout_occurred=True, exit_code=0, stdout=""
        )
        with pytest.raises(WorkspaceCommandError) as exc_info:
            _run_cmd(ws, "slow command", critical=True)
        assert exc_info.value.exit_code == -1

    def test_timeout_non_critical_returns_empty(self):
        ws = _make_workspace()
        ws.execute_command.return_value = MockCommandResult(
            timeout_occurred=True, exit_code=0
        )
        assert _run_cmd(ws, "slow command", critical=False) == ""


# ── WorkspaceCommandError tests ────────────────────────────────────────

class TestWorkspaceCommandError:

    def test_attributes(self):
        err = WorkspaceCommandError("git diff", 128, "fatal error")
        assert err.cmd == "git diff"
        assert err.exit_code == 128
        assert err.stderr == "fatal error"
        assert "128" in str(err)

    def test_is_runtime_error(self):
        assert isinstance(WorkspaceCommandError("cmd", 1, ""), RuntimeError)


# ── SHA regex tests ────────────────────────────────────────────────────

class TestShaRegex:

    def test_valid_40_hex(self):
        assert _SHA_RE.match("a" * 40)
        assert _SHA_RE.match("0123456789abcdef" * 2 + "01234567")

    def test_too_short(self):
        assert not _SHA_RE.match("a" * 39)

    def test_too_long(self):
        assert not _SHA_RE.match("a" * 41)

    def test_uppercase_rejected(self):
        assert not _SHA_RE.match("A" * 40)

    def test_non_hex_rejected(self):
        assert not _SHA_RE.match("g" * 40)

    def test_empty_rejected(self):
        assert not _SHA_RE.match("")


# ── _extract_patch tests ──────────────────────────────────────────────

class TestExtractPatch:

    def test_happy_path(self):
        ws = _make_workspace(_side_effect=_happy_dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert "diff --git" in patch
        assert "flask/app.py" in patch
        assert len(warnings) == 0

    def test_no_git_head_returns_empty(self):
        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=1, stderr="not found")
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert patch == ""
        assert any("No .git/HEAD" in w for w in warnings)

    def test_git_add_failure_warns_but_continues(self):
        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=0)
            if "grep -qF '__pycache__/'" in cmd:
                return MockCommandResult(exit_code=0)
            if "git add -A" in cmd:
                return MockCommandResult(
                    exit_code=128, stderr="fatal: unable to create index"
                )
            if "git status --porcelain" in cmd:
                return MockCommandResult(exit_code=0, stdout=" M file.py\n")
            if "git --no-pager diff --no-color" in cmd:
                return MockCommandResult(exit_code=0, stdout=SAMPLE_DIFF)
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert "diff --git" in patch
        assert any("git add -A failed" in w for w in warnings)

    def test_git_diff_failure_returns_empty(self):
        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=0)
            if "grep -qF '__pycache__/'" in cmd:
                return MockCommandResult(exit_code=0)
            if "git add -A" in cmd:
                return MockCommandResult(exit_code=0)
            if "git status --porcelain" in cmd:
                return MockCommandResult(exit_code=0, stdout="")
            if "git --no-pager diff --no-color" in cmd:
                return MockCommandResult(
                    exit_code=128, stderr="fatal: bad revision"
                )
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert patch == ""
        assert any("git diff exited" in w for w in warnings)

    def test_git_diff_exception_returns_empty(self):
        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=0)
            if "grep -qF '__pycache__/'" in cmd:
                return MockCommandResult(exit_code=0)
            if "git add -A" in cmd:
                return MockCommandResult(exit_code=0)
            if "git status --porcelain" in cmd:
                return MockCommandResult(exit_code=0, stdout="")
            if "git --no-pager diff --no-color" in cmd:
                raise ConnectionError("Docker container disconnected")
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert patch == ""
        assert any("exception" in w.lower() for w in warnings)

    def test_no_changes_no_warnings(self):
        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=0)
            if "grep -qF '__pycache__/'" in cmd:
                return MockCommandResult(exit_code=0)
            if "git add -A" in cmd:
                return MockCommandResult(exit_code=0)
            if "git status --porcelain" in cmd:
                return MockCommandResult(exit_code=0, stdout="")
            if "git --no-pager diff --no-color" in cmd:
                return MockCommandResult(exit_code=0, stdout="")
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert patch == ""
        assert len(warnings) == 0

    def test_empty_diff_but_dirty_status_warns(self):
        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=0)
            if "grep -qF '__pycache__/'" in cmd:
                return MockCommandResult(exit_code=0)
            if "git add -A" in cmd:
                return MockCommandResult(exit_code=0)
            if "git status --porcelain" in cmd:
                return MockCommandResult(exit_code=0, stdout=" M src/flask/app.py\n")
            if "git --no-pager diff --no-color" in cmd:
                return MockCommandResult(exit_code=0, stdout="")
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert patch == ""
        assert any("git diff is empty but git status shows changes" in w for w in warnings)

    def test_oversized_patch_warns_but_returns(self):
        huge_diff = "+" * (1_048_576 + 100)

        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=0)
            if "grep -qF '__pycache__/'" in cmd:
                return MockCommandResult(exit_code=0)
            if "git add -A" in cmd:
                return MockCommandResult(exit_code=0)
            if "git status --porcelain" in cmd:
                return MockCommandResult(exit_code=0, stdout=" M big.py\n")
            if "git --no-pager diff --no-color" in cmd:
                return MockCommandResult(exit_code=0, stdout=huge_diff)
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert len(patch) > 1_048_576
        assert any("MiB" in w for w in warnings)

    def test_exclude_append_failure_non_critical(self):
        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=0)
            if "grep -qF '__pycache__/'" in cmd:
                return MockCommandResult(exit_code=1, stderr="permission denied")
            if "git add -A" in cmd:
                return MockCommandResult(exit_code=0)
            if "git status --porcelain" in cmd:
                return MockCommandResult(exit_code=0, stdout=" M file.py\n")
            if "git --no-pager diff --no-color" in cmd:
                return MockCommandResult(exit_code=0, stdout=SAMPLE_DIFF)
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert "diff --git" in patch

    def test_stdout_none_treated_as_empty(self):
        def dispatch(cmd):
            if "test -f" in cmd and ".git/HEAD" in cmd:
                return MockCommandResult(exit_code=0)
            if "grep -qF '__pycache__/'" in cmd:
                return MockCommandResult(exit_code=0)
            if "git add -A" in cmd:
                return MockCommandResult(exit_code=0)
            if "git status --porcelain" in cmd:
                return MockCommandResult(exit_code=0, stdout="")
            if "git --no-pager diff --no-color" in cmd:
                r = MockCommandResult(exit_code=0)
                r.stdout = None  # type: ignore[assignment]
                return r
            return MockCommandResult(exit_code=0, stdout="")

        ws = _make_workspace(_side_effect=dispatch)
        patch, warnings = _extract_patch(ws, FAKE_SHA, WORKING_DIR)
        assert patch == ""


# ── _validate_result tests ─────────────────────────────────────────────

class TestValidateResult:

    def test_valid_result_no_errors(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="success",
            git_patch="diff", instruction="Fix bug", cost=3.50,
        )
        assert _validate_result(result) == []

    def test_empty_instance_id(self):
        result = OpenHandsResult(
            instance_id="", status="success",
            git_patch="p", instruction="Fix it", cost=1.0,
        )
        assert any("instance_id" in e for e in _validate_result(result))

    def test_none_git_patch(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="success",
            git_patch=None, instruction="Fix it", cost=1.0,
        )
        assert any("git_patch is None" in e for e in _validate_result(result))

    def test_empty_git_patch_is_ok(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="success",
            git_patch="", instruction="Fix it", cost=1.0,
        )
        assert not any("git_patch" in e for e in _validate_result(result))

    def test_empty_instruction(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="success",
            git_patch="p", instruction="", cost=1.0,
        )
        assert any("instruction" in e for e in _validate_result(result))

    def test_invalid_status(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="bogus",
            git_patch="p", instruction="Fix it", cost=1.0,
        )
        assert any("invalid status" in e for e in _validate_result(result))

    @pytest.mark.parametrize("status", ["success", "error", "skipped", "max_iterations"])
    def test_valid_statuses(self, status):
        result = OpenHandsResult(
            instance_id="flask-5426", status=status,
            git_patch="p", instruction="Fix it",
            cost=1.0 if status == "success" else 0.0,
        )
        assert not any("invalid status" in e for e in _validate_result(result))

    def test_zero_cost_on_success(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="success",
            git_patch="p", instruction="Fix it", cost=0.0,
        )
        assert any("non-positive" in e for e in _validate_result(result))

    def test_zero_cost_on_error_is_ok(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="error",
            git_patch="", instruction="Fix it", cost=0.0,
        )
        assert not any("cost" in e for e in _validate_result(result))

    def test_negative_cost_on_success(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="success",
            git_patch="p", instruction="Fix it", cost=-1.5,
        )
        assert any("non-positive" in e for e in _validate_result(result))

    def test_multiple_errors(self):
        result = OpenHandsResult(
            instance_id="", status="bogus",
            git_patch=None, instruction="", cost=0.0,
        )
        errors = _validate_result(result)
        assert len(errors) >= 3


# ── write_eval_output integration tests ────────────────────────────────

class TestWriteOutput:

    def test_includes_extraction_warnings(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="success",
            git_patch="diff", instruction="Fix bug", cost=2.0,
            extraction_warnings=["Patch is large"],
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            out_path = Path(f.name)
        try:
            write_eval_output(result, out_path)
            record = json.loads(out_path.read_text().strip())
            assert record["extraction_warnings"] == ["Patch is large"]
            assert "validation_errors" in record
        finally:
            out_path.unlink(missing_ok=True)

    def test_includes_validation_errors(self):
        result = OpenHandsResult(
            instance_id="flask-5426", status="success",
            git_patch="p", instruction="", cost=2.0,
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            out_path = Path(f.name)
        try:
            write_eval_output(result, out_path)
            record = json.loads(out_path.read_text().strip())
            assert len(record["validation_errors"]) > 0
        finally:
            out_path.unlink(missing_ok=True)

    def test_convert_to_predictions(self):
        record = {
            "instance_id": "flask-5426",
            "test_result": {"git_patch": "diff --git a/f.py b/f.py\n+hello\n"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(record) + "\n")
            input_path = Path(f.name)
        output_path = input_path.with_name("predictions.jsonl")
        try:
            count = convert_to_predictions_jsonl(input_path, output_path, "glm-5")
            assert count == 1
            pred = json.loads(output_path.read_text().strip())
            assert pred["instance_id"] == "flask-5426"
            assert pred["model_name_or_path"] == "glm-5"
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    def test_convert_skips_empty_instance_id(self):
        record = {"instance_id": "", "test_result": {"git_patch": "some patch"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(record) + "\n")
            input_path = Path(f.name)
        output_path = input_path.with_name("predictions.jsonl")
        try:
            assert convert_to_predictions_jsonl(input_path, output_path, "glm-5") == 0
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)


# ── Constants ──────────────────────────────────────────────────────────

class TestConstants:

    def test_patch_size_warn_is_1mb(self):
        assert _PATCH_SIZE_WARN_BYTES == 1_048_576


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
