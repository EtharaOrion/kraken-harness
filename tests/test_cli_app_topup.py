"""Free (no LLM, no Docker) smoke tests for the team-guarantee cli_app upgrade:
the per-subset top-up loop, the >=N grounded floor, and the reject-when-short path.

Grounding, intent-expansion, translation and emit are mocked at their module seams
so the loop's control flow (reach floor -> emit; stuck -> _TaskRejected; disabled ->
no floor) is exercised deterministically and for free.
"""

from __future__ import annotations

import itertools

import pytest

import repo2rlenv.pipelines._cli_app_synthesis as S
from repo2rlenv.pipelines._cli_app_extract import CliSpec, CommandSpec
from repo2rlenv.pipelines._cli_app_extract import TestIntent as _TI
from repo2rlenv.spec.options import CodeInstructOptions

_FAKE_TEST = (
    "def test_x(cli):\n    r = cli('kinesis', 'create-stream')\n    assert r.returncode == 0\n"
)
_ctr = itertools.count()


class _LLM:
    qualified_name = "stub/model"


class _Out:
    org = "default"


class _Repo:
    access = "public"


class _In:
    output = _Out()
    repo = _Repo()


class _Pipe:
    def __init__(self) -> None:
        self._llm_cost_usd = 0.0
        self._llm = _LLM()
        self.input = _In()
        self.events: list[tuple] = []

    def _emit_progress(self, *a) -> None:
        self.events.append(a)


def _spec() -> CliSpec:
    return CliSpec(
        name="aws_cli_kinesis",
        command_prefix="kinesis",
        repo="aws/aws-cli",
        git_sha="d" * 40,
        entry_point="kinesis/service-2.json",
        tests_dir="",
        commands=[CommandSpec(name="create-stream"), CommandSpec(name="describe-stream")],
        spec_sha256="sha",
    )


def _intent(cmd: str = "create-stream") -> _TI:
    n = next(_ctr)
    return _TI(
        source_file="kinesis/service-2.json",
        test_name=f"model_{cmd}_{n}",
        source_method_sha256=f"sha{n}",
        command=cmd,
        cmdline_template=["kinesis", cmd],
        expected_exit=0,
        behaviour_tag="edge",
    )


def _opts(**kw) -> CodeInstructOptions:
    base = dict(
        mode="cli_app",
        cli_app_command_prefix="kinesis",
        cli_app_backend="kinesalite",
        cli_app_reference_grounding=True,
        cli_app_docker_gauntlet=False,
        cli_app_antihack_scan="off",
        cli_app_workflow_tests=0,
        cli_app_oracle="llm",
    )
    base.update(kw)
    return CodeInstructOptions(**base)


class _Ground:
    """Grounds up to ``cap`` of the provided tests (None = all), simulating survival."""

    def __init__(self, cap: int | None) -> None:
        self.cap = cap

    def __call__(self, *, test_files, oracle_code, **kw):
        names = list(test_files)
        n = len(names) if self.cap is None else min(self.cap, len(names))
        kept = {f: test_files[f] for f in names[:n]}
        rg = {
            "skipped": False,
            "grounded_files": set(kept),
            "reference_pass": set(test_files),
            "oracle_pass": set(kept),
            "empty_pass": set(),
            "oracle_out": "",
            "n_reference": len(test_files),
            "n_oracle": len(kept),
            "n_empty": 0,
            "n_grounded": len(kept),
        }
        return rg, kept, oracle_code


def _patch(mp, grounder) -> None:
    mp.setattr(S, "_translate_intent", lambda pipeline, options, spec, it: _FAKE_TEST)
    mp.setattr(S, "_synthesise_oracle", lambda *a, **k: "def main():\n    pass\n")
    mp.setattr(S, "_assert_no_test_leakage", lambda *a, **k: None)
    mp.setattr(S, "write_harbor_task", lambda task, out, **k: out / "task")
    mp.setattr(S, "_apply_reference_grounding", grounder)
    mp.setattr(
        S,
        "_topup_more_intents",
        lambda model, cmd_specs, options, seen, attempt, deficit: [
            _intent() for _ in range(max(deficit * 2, 4))
        ],
    )


def test_topup_reaches_floor_and_emits(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, _Ground(cap=None))
    out = S._build_one_task(
        pipeline=_Pipe(),
        options=_opts(cli_app_min_grounded_final=30, cli_app_topup_max_attempts=5),
        spec=_spec(),
        cmd_specs=_spec().commands,
        intents=[_intent() for _ in range(10)],
        out_dir=tmp_path,
        model={"operations": {}},
    )
    assert out == tmp_path / "task"


def test_topup_exhausted_rejects(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, _Ground(cap=8))
    with pytest.raises(S._TaskRejected, match="topup_exhausted"):
        S._build_one_task(
            pipeline=_Pipe(),
            options=_opts(cli_app_min_grounded_final=30, cli_app_topup_max_attempts=3),
            spec=_spec(),
            cmd_specs=_spec().commands,
            intents=[_intent() for _ in range(10)],
            out_dir=tmp_path,
            model={"operations": {}},
        )


def test_topup_disabled_by_default_no_reject(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, _Ground(cap=3))
    out = S._build_one_task(
        pipeline=_Pipe(),
        options=_opts(),
        spec=_spec(),
        cmd_specs=_spec().commands,
        intents=[_intent() for _ in range(10)],
        out_dir=tmp_path,
        model={"operations": {}},
    )
    assert out == tmp_path / "task"


def test_golden_mode_without_source_root_rejects(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, _Ground(cap=None))
    with pytest.raises(S._TaskRejected, match="golden_slice_unavailable_no_source_root"):
        S._build_one_task(
            pipeline=_Pipe(),
            options=_opts(cli_app_oracle="both"),
            spec=_spec(),
            cmd_specs=_spec().commands,
            intents=[_intent() for _ in range(3)],
            out_dir=tmp_path,
            model={"operations": {}},
        )


def test_effective_grounded_floor_override_precedence() -> None:
    assert S._effective_grounded_floor(_opts()) == 0
    assert S._effective_grounded_floor(_opts(cli_app_min_grounded_final=50)) == 50
    assert (
        S._effective_grounded_floor(
            _opts(
                cli_app_min_grounded_final=50,
                cli_app_min_grounded_final_overrides={"kinesalite": 100},
            )
        )
        == 100
    )


def test_topup_budget_ok_caps() -> None:
    over_cost = _Pipe()
    over_cost._llm_cost_usd = 10.0
    assert not S._topup_budget_ok(over_cost, _opts(cli_app_topup_max_cost_usd=1.0), 0.0, 0.0)
    assert not S._topup_budget_ok(_Pipe(), _opts(cli_app_topup_max_wall_sec=0), 0.0, 0.0)
    assert S._topup_budget_ok(_Pipe(), _opts(), 0.0, 0.0)


def test_noskip_gate_rejects_skip_and_xfail() -> None:
    skip_dec = (
        "import pytest\n@pytest.mark.skip\ndef test_x(cli):\n"
        "    assert cli('kinesis', 'x').returncode == 0\n"
    )
    skip_call = (
        "import pytest\ndef test_x(cli):\n    pytest.skip('no')\n"
        "    assert cli('kinesis', 'x').returncode == 0\n"
    )
    for src in (skip_dec, skip_call):
        ok, reason = S._gauntlet_static(src, expected_behaviour_tag="edge", forbid_skips=True)
        assert not ok and "noskip" in reason
        ok2, _ = S._gauntlet_static(src, expected_behaviour_tag="edge", forbid_skips=False)
        assert ok2


def test_refine_oracle_no_failing_returns_none() -> None:
    profile = S.resolve_profile("kinesalite")
    assert S._refine_oracle_against_failures(_Pipe(), _opts(), profile, "OLD", {}, "") is None


def test_refine_oracle_returns_fixed_code(monkeypatch) -> None:
    class _Resp:
        content = "```python\ndef main():\n    return 1\n```"
        cost_usd = 0.001

    monkeypatch.setattr(S, "complete", lambda *a, **k: _Resp())
    profile = S.resolve_profile("kinesalite")
    out = S._refine_oracle_against_failures(
        _Pipe(), _opts(), profile, "OLD", {"t.py": "def test_x():\n    assert True\n"}, "stderr"
    )
    assert "def main" in out


def test_reference_grounding_refine_loop_improves(monkeypatch) -> None:
    def fake_ground(
        *, dockerfile_content, tests_aux, test_script, oracle_code, timeout_sec, backend
    ):
        grounded = {"a.py", "b.py", "c.py"} if oracle_code == "REFINED" else {"a.py"}
        return {
            "skipped": False,
            "image_tag": "t",
            "grounded_files": set(grounded),
            "reference_pass": {"a.py", "b.py", "c.py"},
            "oracle_pass": set(grounded),
            "empty_pass": set(),
            "oracle_out": "",
            "n_reference": 3,
            "n_oracle": len(grounded),
            "n_empty": 0,
            "n_grounded": len(grounded),
        }

    monkeypatch.setattr(S, "_run_reference_grounding", fake_ground)
    monkeypatch.setattr(S, "_refine_oracle_against_failures", lambda *a, **k: "REFINED")
    profile = S.resolve_profile("kinesalite")
    _rg, kept, oracle = S._apply_reference_grounding(
        options=_opts(cli_app_oracle_refine_max_attempts=2),
        dockerfile="D",
        conftest="C",
        test_files={"a.py": "A", "b.py": "B", "c.py": "C"},
        test_script="T",
        oracle_code="ORIG",
        pipeline=_Pipe(),
        profile=profile,
    )
    assert oracle == "REFINED"
    assert set(kept) == {"a.py", "b.py", "c.py"}


def test_both_mode_ships_golden_slice_and_reference_with_provenance(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, _Ground(cap=None))
    fake_gold_files = {
        "submission/aws": "#!/usr/bin/env python3\n",
        "submission/awscli/__init__.py": "x = 1\n",
    }
    fake_gold_diff = (
        "diff --git a/submission/aws b/submission/aws\nnew file\n+#!/usr/bin/env python3\n"
    )
    fake_prov = {"awscli/__init__.py": "deadbeef", "awscli/clidriver.py": "cafef00d"}
    monkeypatch.setattr(
        S,
        "build_slice_gold",
        lambda root, commands=None, service="s3": (
            fake_gold_files,
            fake_gold_diff,
            fake_prov,
            ("colorama",),
        ),
    )
    monkeypatch.setattr(
        S,
        "_certify_golden",
        lambda **k: {"skipped": False, "passed": 10, "total": 10, "pass_rate": 1.0, "summary": ""},
    )
    captured: dict = {}
    monkeypatch.setattr(
        S, "write_harbor_task", lambda task, out, **k: captured.update(task=task) or (out / "task")
    )
    S._build_one_task(
        pipeline=_Pipe(),
        options=_opts(cli_app_oracle="both", cli_app_docker_gauntlet=True),
        spec=_spec(),
        cmd_specs=_spec().commands,
        intents=[_intent() for _ in range(6)],
        out_dir=tmp_path,
        model={"operations": {}},
        source_root=tmp_path,
    )
    task = captured["task"]
    assert task.oracle_diff == fake_gold_diff
    assert "submission/main.py" in task.reference_diff
    g = task.repo2env["code_instruct"]["golden"]
    assert g["awscli_version"] == S.PINNED_AWSCLI_VERSION
    assert g["entry_point"] == "submission/aws"
    assert g["n_slice_files"] == 2
    assert len(g["provenance_sha256"]) == 64
    assert g["certified_pass_rate"] == 1.0
