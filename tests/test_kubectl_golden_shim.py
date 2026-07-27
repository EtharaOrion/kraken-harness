"""C10 gate: kubectl golden slice (shim + sliced kubectl-src)."""

from __future__ import annotations

from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
    KwokSimulationBackend,
)


def test_shim_is_dict_returning_repo_relative_paths():
    shim = KwokSimulationBackend.emit_golden_shim()
    assert isinstance(shim, dict)
    assert "submission/kubectl" in shim
    assert "submission/kubectl-src/go.mod" in shim
    assert "submission/kubectl-src/cmd/kubectl/main.go" in shim


def test_shim_path_is_submission_kubectl():
    shim = KwokSimulationBackend.emit_golden_shim()
    assert "submission/kubectl" in shim
    assert "submission/main.py" not in shim


def test_shim_content_is_exact_shebang_exec_kubectl():
    shim = KwokSimulationBackend.emit_golden_shim()
    content = shim["submission/kubectl"]
    expected = '#!/bin/sh\nexec /usr/local/bin/kubectl "$@"\n'
    assert content == expected


def test_shim_entry_is_short_under_100_bytes():
    shim = KwokSimulationBackend.emit_golden_shim()
    content = shim["submission/kubectl"]
    assert len(content.encode("utf-8")) < 100, (
        "golden shim entry must be minimal (< 100 bytes) — heavy content lives in kubectl-src/"
    )


def test_shim_has_trailing_newline():
    shim = KwokSimulationBackend.emit_golden_shim()
    content = shim["submission/kubectl"]
    assert content.endswith("\n")


def test_shim_starts_with_posix_shebang():
    shim = KwokSimulationBackend.emit_golden_shim()
    content = shim["submission/kubectl"]
    assert content.startswith("#!/bin/sh")


def test_shim_uses_absolute_kubectl_path():
    shim = KwokSimulationBackend.emit_golden_shim()
    content = shim["submission/kubectl"]
    assert "/usr/local/bin/kubectl" in content


def test_shim_forwards_all_argv():
    shim = KwokSimulationBackend.emit_golden_shim()
    content = shim["submission/kubectl"]
    assert '"$@"' in content


def test_shim_is_deterministic_across_calls():
    a = KwokSimulationBackend.emit_golden_shim()
    b = KwokSimulationBackend.emit_golden_shim()
    assert a == b


def test_kubectl_src_go_mod_pins_v0_31_0():
    shim = KwokSimulationBackend.emit_golden_shim()
    go_mod = shim["submission/kubectl-src/go.mod"]
    assert "module submission/kubectl-src" in go_mod
    assert "k8s.io/kubectl v0.31.0" in go_mod
    assert "k8s.io/cli-runtime v0.31.0" in go_mod
    assert "k8s.io/component-base v0.31.0" in go_mod
    assert "go 1.22" in go_mod


def test_kubectl_src_main_go_is_true_slice_not_new_default():
    shim = KwokSimulationBackend.emit_golden_shim()
    main_go = shim["submission/kubectl-src/cmd/kubectl/main.go"]
    assert "package main" in main_go
    assert "NewDefaultKubectlCommand" not in main_go
    assert '"k8s.io/cli-runtime/pkg/genericclioptions"' in main_go
    assert '"k8s.io/component-base/cli"' in main_go
    for ctor in (
        "NewCmdGet",
        "NewCmdApply",
        "NewCmdDelete",
        "NewCmdCreate",
        "NewCmdDescribe",
        "NewCmdPatch",
        "NewCmdScale",
        "NewCmdLabel",
    ):
        assert ctor in main_go, f"missing subcommand ctor {ctor} in default slice main.go"


def test_kubectl_src_main_go_respects_task_spec_subset():
    from types import SimpleNamespace

    spec = SimpleNamespace(commands=["get", "apply"], kinds=["pods"])
    shim = KwokSimulationBackend.emit_golden_shim(spec)
    main_go = shim["submission/kubectl-src/cmd/kubectl/main.go"]
    assert "NewCmdGet" in main_go
    assert "NewCmdApply" in main_go
    for absent in ("NewCmdDelete", "NewCmdScale", "NewCmdLabel", "NewCmdPatch"):
        assert absent not in main_go, f"verb {absent} should NOT be in 2-verb slice"


def test_kubectl_src_main_go_falls_back_to_all_eight_on_empty_spec():
    from types import SimpleNamespace

    spec = SimpleNamespace(commands=[], kinds=[])
    shim = KwokSimulationBackend.emit_golden_shim(spec)
    main_go = shim["submission/kubectl-src/cmd/kubectl/main.go"]
    for ctor in (
        "NewCmdGet",
        "NewCmdApply",
        "NewCmdDelete",
        "NewCmdCreate",
        "NewCmdDescribe",
        "NewCmdPatch",
        "NewCmdScale",
        "NewCmdLabel",
    ):
        assert ctor in main_go
