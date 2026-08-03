"""Unit tests for the cli_app orchestrator helpers.

Covers the three functions extracted from run_cli_app_pipeline during the
CMP-001 complexity refactor: _try_emit_task (the shared try/except around a
single build) and the two mode loops (_run_subset_mode, _run_per_command_mode).
Each previously had only transitive coverage via the full pipeline; these tests
exercise their skip-reason bookkeeping, limit handling, and dispatch directly.
All LLM/IO is mocked so they run free and deterministically.
"""

from __future__ import annotations

from pathlib import Path

import repo2rlenv.pipelines._cli_app_synthesis as S
from repo2rlenv.pipelines._cli_app_extract import (
    CliSpec,
    CommandSpec,
)
from repo2rlenv.pipelines._cli_app_extract import (
    TestIntent as _TestIntent,  # aliased so pytest doesn't collect it as a test class
)
from repo2rlenv.spec.options import CodeInstructOptions


class _Pipe:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def _emit_progress(self, *args) -> None:
        self.events.append(args)


def _spec(commands: list[str]) -> CliSpec:
    return CliSpec(
        name="aws_cli_s3",
        command_prefix="s3",
        repo="aws/aws-cli",
        git_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        entry_point="x.py",
        tests_dir="tests/functional/s3",
        commands=[CommandSpec(name=c) for c in commands],
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


def _opts(**kw) -> CodeInstructOptions:
    return CodeInstructOptions(mode="cli_app", cli_app_command_prefix="s3", **kw)


def test_try_emit_task_success_returns_path_and_no_skip(monkeypatch, tmp_path: Path) -> None:
    expected = tmp_path / "task-1"
    monkeypatch.setattr(S, "_build_one_task", lambda **kw: expected)
    skip: dict[str, int] = {}

    result = S._try_emit_task(
        pipeline=_Pipe(),
        options=_opts(),
        spec=_spec(["mb"]),
        cmd_specs=[CommandSpec(name="mb")],
        intents=[_intent("mb")],
        out_dir=tmp_path,
        intent_idx=None,
        label="aws/aws-cli:mb",
        skip_reasons=skip,
    )

    assert result == expected
    assert skip == {}


def test_try_emit_task_rejected_records_reason(monkeypatch, tmp_path: Path) -> None:
    def boom(**kw):
        raise S._TaskRejected("oracle_empty")

    monkeypatch.setattr(S, "_build_one_task", boom)
    pipe = _Pipe()
    skip: dict[str, int] = {}

    result = S._try_emit_task(
        pipeline=pipe,
        options=_opts(),
        spec=_spec(["mb"]),
        cmd_specs=[CommandSpec(name="mb")],
        intents=[_intent("mb")],
        out_dir=tmp_path,
        intent_idx=None,
        label="aws/aws-cli:mb",
        skip_reasons=skip,
    )

    assert result is None
    assert skip == {"oracle_empty": 1}
    assert pipe.events == [("aws/aws-cli:mb", "skip", "oracle_empty")]


def test_try_emit_task_generic_exception_records_synthesis_error(
    monkeypatch, tmp_path: Path
) -> None:
    def boom(**kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(S, "_build_one_task", boom)
    pipe = _Pipe()
    skip: dict[str, int] = {}

    result = S._try_emit_task(
        pipeline=pipe,
        options=_opts(),
        spec=_spec(["mb"]),
        cmd_specs=[CommandSpec(name="mb")],
        intents=[_intent("mb")],
        out_dir=tmp_path,
        intent_idx=None,
        label="aws/aws-cli:mb",
        skip_reasons=skip,
    )

    assert result is None
    assert skip == {"synthesis_error": 1}
    assert pipe.events[0][0] == "aws/aws-cli:mb"
    assert pipe.events[0][1] == "skip"
    assert pipe.events[0][2].startswith("synthesis_error:")


def test_try_emit_task_rejected_reason_accumulates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        S, "_build_one_task", lambda **kw: (_ for _ in ()).throw(S._TaskRejected("dup"))
    )
    skip = {"dup": 2}

    S._try_emit_task(
        pipeline=_Pipe(),
        options=_opts(),
        spec=_spec(["mb"]),
        cmd_specs=[CommandSpec(name="mb")],
        intents=[_intent("mb")],
        out_dir=tmp_path,
        intent_idx=None,
        label="lbl",
        skip_reasons=skip,
    )

    assert skip == {"dup": 3}


def test_run_subset_mode_emits_valid_subset(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [_intent("mb")])
    monkeypatch.setattr(S, "_build_one_task", lambda **kw: tmp_path / "task-mb+rb")
    pipe = _Pipe()
    skip: dict[str, int] = {}

    seen, emitted = S._run_subset_mode(
        pipeline=pipe,
        options=_opts(),
        spec=_spec(["mb", "rb"]),
        subsets=["mb,rb"],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons=skip,
    )

    assert (seen, emitted) == (1, 1)
    assert skip == {}
    assert ("task-mb+rb", "emit") in pipe.events


def test_run_subset_mode_skips_too_small(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [_intent("mb")])
    pipe = _Pipe()
    skip: dict[str, int] = {}

    seen, emitted = S._run_subset_mode(
        pipeline=pipe,
        options=_opts(),
        spec=_spec(["mb", "rb"]),
        subsets=["mb"],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons=skip,
    )

    assert (seen, emitted) == (1, 0)
    assert skip == {"subset_too_small": 1}


def test_run_subset_mode_skips_no_intents(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [])
    pipe = _Pipe()
    skip: dict[str, int] = {}

    seen, emitted = S._run_subset_mode(
        pipeline=pipe,
        options=_opts(),
        spec=_spec(["mb", "rb"]),
        subsets=["mb,rb"],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons=skip,
    )

    assert (seen, emitted) == (1, 0)
    assert skip == {"no_intents_extracted": 1}


def test_run_subset_mode_dedupes_and_drops_unknown(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, list] = {}

    def fake_build(**kw):
        captured["cmd_specs"] = kw["cmd_specs"]
        return tmp_path / "task"

    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [_intent("mb")])
    monkeypatch.setattr(S, "_build_one_task", fake_build)

    # "mb,mb,rb,nope": dup mb collapsed, unknown "nope" dropped -> group {mb, rb}
    seen, emitted = S._run_subset_mode(
        pipeline=_Pipe(),
        options=_opts(),
        spec=_spec(["mb", "rb"]),
        subsets=["mb,mb,rb,nope"],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons={},
    )

    assert (seen, emitted) == (1, 1)
    assert sorted(c.name for c in captured["cmd_specs"]) == ["mb", "rb"]


def test_run_subset_mode_honours_limit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [_intent("mb")])
    monkeypatch.setattr(S, "_build_one_task", lambda **kw: tmp_path / "task")

    seen, emitted = S._run_subset_mode(
        pipeline=_Pipe(),
        options=_opts(limit=1),
        spec=_spec(["mb", "rb", "cp", "ls"]),
        subsets=["mb,rb", "cp,ls"],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons={},
    )

    assert emitted == 1
    assert seen == 1


def test_run_per_command_mode_one_task_per_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [_intent("mb")])
    monkeypatch.setattr(S, "_build_one_task", lambda **kw: tmp_path / "task")

    seen, emitted = S._run_per_command_mode(
        pipeline=_Pipe(),
        options=_opts(),
        spec=_spec(["mb", "rb"]),
        target_commands=[CommandSpec(name="mb"), CommandSpec(name="rb")],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons={},
    )

    assert (seen, emitted) == (2, 2)


def test_run_per_command_mode_skips_no_intents(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [])
    skip: dict[str, int] = {}

    seen, emitted = S._run_per_command_mode(
        pipeline=_Pipe(),
        options=_opts(),
        spec=_spec(["mb"]),
        target_commands=[CommandSpec(name="mb")],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons=skip,
    )

    assert (seen, emitted) == (1, 0)
    assert skip == {"no_intents_extracted": 1}


def test_run_per_command_mode_per_intent_fans_out(monkeypatch, tmp_path: Path) -> None:
    labels: list = []

    def fake_build(**kw):
        labels.append(kw["intent_idx"])
        return tmp_path / "task"

    monkeypatch.setattr(
        S, "extract_test_intents", lambda *a, **k: [_intent("mb"), _intent("mb"), _intent("mb")]
    )
    monkeypatch.setattr(S, "_build_one_task", fake_build)

    seen, emitted = S._run_per_command_mode(
        pipeline=_Pipe(),
        options=_opts(cli_app_per_intent=True),
        spec=_spec(["mb"]),
        target_commands=[CommandSpec(name="mb")],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons={},
    )

    # 3 intents -> 3 separate tasks, each with its own intent_idx
    assert (seen, emitted) == (3, 3)
    assert labels == [0, 1, 2]


def test_run_per_command_mode_honours_limit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [_intent("mb")])
    monkeypatch.setattr(S, "_build_one_task", lambda **kw: tmp_path / "task")

    _seen, emitted = S._run_per_command_mode(
        pipeline=_Pipe(),
        options=_opts(limit=1),
        spec=_spec(["mb", "rb", "cp"]),
        target_commands=[CommandSpec(name=c) for c in ("mb", "rb", "cp")],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons={},
    )

    assert emitted == 1


def test_run_per_command_mode_per_command_label_has_no_index(monkeypatch, tmp_path: Path) -> None:
    seen_idx: list = []
    monkeypatch.setattr(S, "extract_test_intents", lambda *a, **k: [_intent("mb"), _intent("mb")])
    monkeypatch.setattr(
        S, "_build_one_task", lambda **kw: seen_idx.append(kw["intent_idx"]) or (tmp_path / "t")
    )

    S._run_per_command_mode(
        pipeline=_Pipe(),
        options=_opts(),
        spec=_spec(["mb"]),
        target_commands=[CommandSpec(name="mb")],
        tests_dir_path=tmp_path,
        out_dir=tmp_path,
        owner_name="aws/aws-cli",
        skip_reasons={},
    )

    # default (per-command) mode bundles all intents into one task, intent_idx=None
    assert seen_idx == [None]
