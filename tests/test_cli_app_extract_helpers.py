"""Unit tests for helpers extracted from _extract_intent_from_method."""

from __future__ import annotations

import ast

from repo2rlenv.pipelines._cli_app_extract import (
    _collect_operation_names,
    _resolve_cmdline_with_fallbacks,
    _try_cmdline_and_rc_from_call,
    _try_cmdline_from_assignment,
)


def _parse_first(source: str) -> ast.AST:
    return ast.parse(source).body[0]


def _parse_call(source: str) -> ast.Call:
    stmt = _parse_first(source)
    assert isinstance(stmt, ast.Expr)
    assert isinstance(stmt.value, ast.Call)
    return stmt.value


def test_cmdline_from_assignment_matches_cmdline_var():
    stmt = _parse_first("cmdline = 'mb s3://bucket'")
    assert _try_cmdline_from_assignment(stmt, "s3 ") == ["s3", "mb", "s3://bucket"]


def test_cmdline_from_assignment_matches_command_var():
    stmt = _parse_first("command = 'rb s3://bucket'")
    assert _try_cmdline_from_assignment(stmt, "s3 ") == ["s3", "rb", "s3://bucket"]


def test_cmdline_from_assignment_ignores_other_vars():
    stmt = _parse_first("foo = 'mb s3://bucket'")
    assert _try_cmdline_from_assignment(stmt, "s3 ") is None


def test_cmdline_from_assignment_ignores_non_assign():
    call = _parse_call("print('hello')")
    assert _try_cmdline_from_assignment(call, "s3 ") is None


def test_cmdline_from_assignment_ignores_non_string_value():
    stmt = _parse_first("cmdline = 42")
    assert _try_cmdline_from_assignment(stmt, "s3 ") is None


def test_cmdline_and_rc_run_cmd_with_rc():
    call = _parse_call("self.run_cmd('mb s3://bucket', expected_rc=1)")
    cmdline, rc = _try_cmdline_and_rc_from_call(call, "s3 ")
    assert cmdline == ["s3", "mb", "s3://bucket"]
    assert rc == 1


def test_cmdline_and_rc_run_cmd_no_rc():
    call = _parse_call("self.run_cmd('mb s3://bucket')")
    cmdline, rc = _try_cmdline_and_rc_from_call(call, "s3 ")
    assert cmdline == ["s3", "mb", "s3://bucket"]
    assert rc is None


def test_cmdline_and_rc_assert_params():
    call = _parse_call("self.assert_params_for_cmd('cp s3://a s3://b')")
    cmdline, rc = _try_cmdline_and_rc_from_call(call, "s3 ")
    assert cmdline == ["s3", "cp", "s3://a", "s3://b"]
    assert rc is None


def test_cmdline_and_rc_wrong_method():
    call = _parse_call("self.other_method('arg')")
    assert _try_cmdline_and_rc_from_call(call, "s3 ") == (None, None)


def test_cmdline_and_rc_no_args():
    call = _parse_call("self.run_cmd()")
    cmdline, rc = _try_cmdline_and_rc_from_call(call, "s3 ")
    assert cmdline is None
    assert rc is None


def test_collect_operation_names_camelcase():
    call = _parse_call("self.assertEqual(x, 'CreateBucket')")
    assert _collect_operation_names(call) == ["CreateBucket"]


def test_collect_operation_names_assertEquals():
    call = _parse_call("self.assertEquals(x, 'DeleteObject')")
    assert _collect_operation_names(call) == ["DeleteObject"]


def test_collect_operation_names_rejects_lowercase():
    call = _parse_call("self.assertEqual(x, 'lowercase')")
    assert _collect_operation_names(call) == []


def test_collect_operation_names_wrong_method():
    call = _parse_call("self.assertTrue(x)")
    assert _collect_operation_names(call) == []


def test_collect_operation_names_too_few_args():
    call = _parse_call("self.assertEqual(x)")
    assert _collect_operation_names(call) == []


def test_resolve_fallbacks_returns_primary():
    method = _parse_first("def test_x():\n    pass")
    assert isinstance(method, ast.FunctionDef)
    result = _resolve_cmdline_with_fallbacks(method, "s3 ", "mb", "", ["s3", "mb", "s3://bucket"])
    assert result == ["s3", "mb", "s3://bucket"]


def test_resolve_fallbacks_binop_s3_url():
    source = "def test_x():\n    cmd = self.prefix + 's3://bucket/key'\n"
    method = ast.parse(source).body[0]
    assert isinstance(method, ast.FunctionDef)
    result = _resolve_cmdline_with_fallbacks(method, "s3 ", "mb", source, None)
    assert result == ["s3", "s3://bucket/key"]


def test_resolve_fallbacks_binop_flag():
    source = "def test_x():\n    cmd = self.prefix + '--recursive'\n"
    method = ast.parse(source).body[0]
    assert isinstance(method, ast.FunctionDef)
    result = _resolve_cmdline_with_fallbacks(method, "s3 ", "cp", source, None)
    assert result == ["s3", "--recursive"]


def test_resolve_fallbacks_regex_on_source():
    source = "def test_x():\n    x = 's3 mb myarg'\n"
    method = ast.parse(source).body[0]
    assert isinstance(method, ast.FunctionDef)
    result = _resolve_cmdline_with_fallbacks(method, "s3 ", "mb", source, None)
    assert result == ["s3", "mb", "myarg"]


def test_resolve_fallbacks_gives_up():
    source = "def test_x():\n    pass\n"
    method = ast.parse(source).body[0]
    assert isinstance(method, ast.FunctionDef)
    result = _resolve_cmdline_with_fallbacks(method, "s3 ", "mb", source, None)
    assert result == ["mb"]
