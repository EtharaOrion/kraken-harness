"""Runtime emission gate — kwok backend actually emits reference_client + golden shim."""

from __future__ import annotations

import pytest

import repo2rlenv.pipelines._cli_app_synthesis as S
from repo2rlenv.pipelines._cli_app_extract import CliSpec, CommandSpec
from repo2rlenv.pipelines._cli_app_extract import TestIntent as _Intent
from repo2rlenv.spec.options import CodeInstructOptions


class _FakeLLM:
    qualified_name = "fake/model-kwok"


class _FakePipeline:
    def __init__(self):
        self._llm = _FakeLLM()
        self._llm_cost_usd = 0.0
        self.events: list = []

    def _emit_progress(self, *args):
        self.events.append(args)


_CANNED_TEST = (
    "def test_it(cli, k8s_client, kubectl_bin):\n"
    "    r = cli(['get', 'pods'])\n"
    "    assert r.returncode in (0, 1, 2)\n"
)
_CANNED_ORACLE = (
    "#!/usr/bin/env python3\n"
    "import sys\n"
    "def main():\n"
    "    if len(sys.argv) < 2: sys.exit(2)\n"
    "    return 0\n"
    "if __name__ == '__main__': sys.exit(main())\n"
)


class _Resp:
    def __init__(self, content: str):
        self.content = content
        self.cost_usd = 0.0


def _make_fake_complete():
    def fake_complete(llm, *, system, user, **kw):
        upper = system.upper()
        if "REFERENCE PYTHON IMPLEMENTATION" in upper or "ORACLE" in upper:
            return _Resp(_CANNED_ORACLE)
        return _Resp(_CANNED_TEST)

    return fake_complete


@pytest.fixture(autouse=True)
def _clear_oracle_cache():
    S._ORACLE_CACHE.clear()
    yield
    S._ORACLE_CACHE.clear()


def _kwok_case(command: str):
    spec = CliSpec(
        name="kubernetes_kubectl",
        command_prefix="pods",
        repo="kubernetes/kubectl",
        git_sha="d" * 40,
        entry_point="n/a",
        tests_dir="n/a",
        commands=[CommandSpec(name=command)],
        spec_sha256="k" * 64,
    )
    intents = [
        _Intent(
            source_file=f"test_{command}_pods.py",
            test_name=f"test_{command}",
            source_method_sha256="deadbeef",
            command=command,
            cmdline_template=["kubectl", command, "pods"],
            expected_exit=0,
            behaviour_tag="happy_path",
        )
    ]
    opts = CodeInstructOptions(
        mode="cli_app",
        cli_app_command_prefix="pods",
        cli_app_backend="kwok",
        cli_app_skip_gauntlet=True,
        cli_app_translate_workers=1,
    )
    return spec, intents, opts


def test_kwok_backend_emit_reference_client_returns_valid_python():
    from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
        KwokSimulationBackend,
    )

    spec, intents, _ = _kwok_case("get")
    task_spec = S._build_kwok_task_spec(spec.commands, intents)
    ref_body = KwokSimulationBackend.emit_reference_client(task_spec)
    assert "class KubectlClient" in ref_body
    assert "resourceVersion" in ref_body
    assert "creationTimestamp" in ref_body
    compile(ref_body, "<emit>", "exec")


def test_kwok_backend_emit_golden_shim_returns_correct_path_and_content():
    from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
        KwokSimulationBackend,
    )

    shim_map = KwokSimulationBackend.emit_golden_shim()
    assert "submission/kubectl" in shim_map
    body = shim_map["submission/kubectl"]
    assert body.startswith("#!/bin/sh")
    assert "/usr/local/bin/kubectl" in body
    assert "exec" in body


def test_kwok_backend_emit_golden_shim_ships_sliced_kubectl_source():
    from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
        KwokSimulationBackend,
    )

    shim_map = KwokSimulationBackend.emit_golden_shim()

    assert "submission/kubectl-src/go.mod" in shim_map
    go_mod = shim_map["submission/kubectl-src/go.mod"]
    assert "module submission/kubectl-src" in go_mod
    assert "go 1.22" in go_mod
    assert "k8s.io/kubectl v0.31.0" in go_mod
    assert "k8s.io/cli-runtime v0.31.0" in go_mod
    assert "k8s.io/component-base v0.31.0" in go_mod

    assert "submission/kubectl-src/cmd/kubectl/main.go" in shim_map
    main_go = shim_map["submission/kubectl-src/cmd/kubectl/main.go"]
    assert "package main" in main_go
    assert "NewDefaultKubectlCommand" not in main_go
    assert "NewCmdGet" in main_go
    assert "NewCmdApply" in main_go
    assert "NewCmdDelete" in main_go

    assert "submission/kubectl-src/README.md" in shim_map
    assert "Sliced kubectl source" in shim_map["submission/kubectl-src/README.md"]


def test_kwok_backend_emit_golden_shim_diff_is_multi_file():
    from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
        KwokSimulationBackend,
    )
    from repo2rlenv.pipelines._oss_instruct import make_multi_file_diff

    shim_map = KwokSimulationBackend.emit_golden_shim()
    diff = make_multi_file_diff(shim_map)

    assert diff.count("diff --git a/submission/") >= 4
    assert "submission/kubectl-src/cmd/kubectl/main.go" in diff
    assert "submission/kubectl-src/go.mod" in diff
    assert "submission/kubectl" in diff


def test_kwok_backend_task_spec_helper_shapes():
    from types import SimpleNamespace

    spec, intents, _ = _kwok_case("apply")
    result = S._build_kwok_task_spec(spec.commands, intents)
    assert isinstance(result, SimpleNamespace)
    assert result.commands == ["apply"]
    assert result.kinds == ["pods"]


def test_kwok_backend_task_spec_helper_empty_intents():
    spec, _, _ = _kwok_case("get")
    result = S._build_kwok_task_spec(spec.commands, [])
    assert result.commands == ["get"]
    assert result.kinds == []


def test_validate_backend_pairing_rejects_kwok_with_aws_source():
    with pytest.raises(ValueError, match="not compatible"):
        S.validate_backend_pairing(sim_name="kwok", source_name="aws_tests")


def test_validate_backend_pairing_accepts_kwok_with_kubectl_source():
    S.validate_backend_pairing(sim_name="kwok", source_name="kubectl_cobra_yaml")
