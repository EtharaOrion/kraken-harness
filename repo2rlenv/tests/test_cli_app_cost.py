"""cli_app per-task LLM cost accounting.

Guards the fix where each emitted task records its OWN incremental LLM cost
(`llm_cost_usd`) rather than the run-cumulative total, while `run_llm_cost_usd`
preserves the cumulative for bill reconciliation. Mocks all LLM/IO so it runs
free and deterministically in CI.
"""

from __future__ import annotations

from pathlib import Path

import repo2rlenv.pipelines._cli_app_synthesis as S
from repo2rlenv.pipelines._cli_app_extract import (
    CliSpec,
    CommandSpec,
)
from repo2rlenv.pipelines._cli_app_extract import (
    TestIntent as _TestIntent,  # aliased so pytest doesn't try to collect it as a test class
)
from repo2rlenv.spec.options import CodeInstructOptions


class _LLM:
    qualified_name = "fake/model"


class _Out:
    org = "default"


class _Repo:
    access = "auto"


class _Input:
    llm = _LLM()
    output = _Out()
    repo = _Repo()


class _Pipe:
    def __init__(self) -> None:
        self._llm_cost_usd = 0.0
        self._llm = _LLM()
        self.input = _Input()


def _spec() -> CliSpec:
    return CliSpec(
        name="aws_cli_s3",
        command_prefix="s3",
        repo="aws/aws-cli",
        git_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        entry_point="x.py",
        tests_dir="tests/functional/s3",
        commands=[CommandSpec(name="mb"), CommandSpec(name="rb")],
        spec_sha256="specsha",
    )


def _intent(cmd: str) -> _TestIntent:
    return _TestIntent(
        source_file=f"test_{cmd}_command.py",
        test_name=f"test_{cmd}",
        source_method_sha256="x",
        command=cmd,
        cmdline_template=["s3", cmd, "s3://bucket"],
        expected_exit=0,
        behaviour_tag="happy_path",
    )


def test_per_task_cost_is_delta_not_cumulative(monkeypatch, tmp_path: Path) -> None:
    S._ORACLE_CACHE.clear()  # module-global; isolate the test

    # Each LLM step bumps the shared run counter by a known amount.
    def fake_translate(pipeline, options, spec, intent):
        pipeline._llm_cost_usd += 0.10
        return "def test_x(cli, s3_client):\n    assert cli('s3', 'mb', 's3://buk').returncode == 0\n    assert 'buk' in {b['Name'] for b in s3_client.list_buckets()['Buckets']}\n"

    def fake_oracle(pipeline, options, spec, cmd_specs, intents):
        pipeline._llm_cost_usd += 0.20
        return "import sys\nprint('ok')\n"

    captured = []

    def fake_write(task, out_dir, **_kwargs):
        captured.append(task)
        return out_dir

    monkeypatch.setattr(S, "_translate_intent", fake_translate)
    monkeypatch.setattr(S, "_synthesise_oracle", fake_oracle)
    monkeypatch.setattr(S, "write_harbor_task", fake_write)

    opts = CodeInstructOptions(
        mode="cli_app",
        cli_app_command_prefix="s3",
        cli_app_oracle="llm",
        cli_app_docker_gauntlet=False,
    )
    spec = _spec()
    pipe = _Pipe()

    # Task 1 (mb): 1 translate (0.10) + 1 oracle (0.20) = 0.30
    S._build_one_task(
        pipeline=pipe,
        options=opts,
        spec=spec,
        cmd_specs=[CommandSpec(name="mb")],
        intents=[_intent("mb")],
        out_dir=tmp_path,
    )
    # Task 2 (rb): different command -> oracle cache miss -> another 0.30
    S._build_one_task(
        pipeline=pipe,
        options=opts,
        spec=spec,
        cmd_specs=[CommandSpec(name="rb")],
        intents=[_intent("rb")],
        out_dir=tmp_path,
    )

    t1 = captured[0].repo2env["code_instruct"]
    t2 = captured[1].repo2env["code_instruct"]

    # Each task records ITS OWN cost (~0.30), not the running total.
    assert t1["llm_cost_usd"] == 0.3
    assert t2["llm_cost_usd"] == 0.3, "second task must NOT be cumulative (was the bug)"

    # run_llm_cost_usd keeps the cumulative so the dataset reconciles to the bill.
    assert t1["run_llm_cost_usd"] == 0.3
    assert t2["run_llm_cost_usd"] == 0.6

    # Cost basis is recorded for auditability (estimate vs native).
    assert "llm_cost_method" in t1


def test_rejected_task_cost_not_folded_into_next(monkeypatch, tmp_path: Path) -> None:
    """A task that fails after spending LLM budget must not inflate the next."""
    S._ORACLE_CACHE.clear()

    def fake_translate(pipeline, options, spec, intent):
        pipeline._llm_cost_usd += 0.10
        return "def test_x(cli, s3_client):\n    assert cli('s3', 'mb', 's3://buk').returncode == 0\n    assert 'buk' in {b['Name'] for b in s3_client.list_buckets()['Buckets']}\n"

    # First call: spend then fail (oracle returns None -> _TaskRejected).
    # Second call: succeed.
    calls = {"n": 0}

    def fake_oracle(pipeline, options, spec, cmd_specs, intents):
        pipeline._llm_cost_usd += 0.20
        calls["n"] += 1
        return None if calls["n"] == 1 else "import sys\nprint('ok')\n"

    captured = []
    monkeypatch.setattr(S, "_translate_intent", fake_translate)
    monkeypatch.setattr(S, "_synthesise_oracle", fake_oracle)
    monkeypatch.setattr(
        S, "write_harbor_task", lambda task, out, **_kw: captured.append(task) or out
    )

    opts = CodeInstructOptions(
        mode="cli_app",
        cli_app_command_prefix="s3",
        cli_app_oracle="llm",
        cli_app_docker_gauntlet=False,
    )
    spec = _spec()
    pipe = _Pipe()

    # Task A (mb): translate 0.10 + oracle 0.20 then REJECTED (oracle None).
    import pytest

    with pytest.raises(S._TaskRejected):
        S._build_one_task(
            pipeline=pipe,
            options=opts,
            spec=spec,
            cmd_specs=[CommandSpec(name="mb")],
            intents=[_intent("mb")],
            out_dir=tmp_path,
        )
    # Task B (rb): its own 0.30 only — the rejected 0.30 must NOT fold in.
    S._build_one_task(
        pipeline=pipe,
        options=opts,
        spec=spec,
        cmd_specs=[CommandSpec(name="rb")],
        intents=[_intent("rb")],
        out_dir=tmp_path,
    )
    tB = captured[0].repo2env["code_instruct"]
    assert tB["llm_cost_usd"] == 0.3, "rejected task's cost must not fold into the next"
    assert tB["run_llm_cost_usd"] == 0.6, "cumulative still reflects total spend incl. rejected"
