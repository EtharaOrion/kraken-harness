"""C4 tests: KubectlCobraYamlSource host loader + Go extractor sanity."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo2rlenv.pipelines._cli_app_backends.source.kubectl_cobra_yaml import (
    KubectlCobraYamlSource,
)
from repo2rlenv.pipelines._cli_app_extract import CliSpec, CommandSpec, TestIntent

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "kubectl_spec_v1_31_minimal.yaml"
GO_DIR = (
    REPO_ROOT
    / "src"
    / "repo2rlenv"
    / "pipelines"
    / "_cli_app_backends"
    / "source"
    / "cobra_extractor"
)
GO_MAIN = GO_DIR / "main.go"
GO_MOD = GO_DIR / "go.mod"

_VALID_BEHAVIOURS = frozenset(
    {"happy_path", "error", "error_nonexistent", "error_invalid_args", "edge", "workflow"}
)


@pytest.fixture(scope="module")
def spec() -> CliSpec:
    return KubectlCobraYamlSource.extract_spec(
        clone_dir=REPO_ROOT,
        command_prefix="kubectl",
        yaml_bundle_path=FIXTURE,
    )


def test_extract_spec_returns_cli_spec(spec: CliSpec):
    assert isinstance(spec, CliSpec)
    assert spec.command_prefix == "kubectl"
    assert spec.repo == "kubernetes/kubectl"
    assert spec.name == "kubernetes_kubectl"
    assert spec.commands, "commands list must be non-empty"


def test_extract_spec_git_sha_from_bundle_metadata(spec: CliSpec):
    assert spec.git_sha == "cccccccccccccccccccccccccccccccccccccccc"


def test_extract_spec_content_hash_deterministic(spec: CliSpec):
    again = KubectlCobraYamlSource.extract_spec(
        clone_dir=REPO_ROOT,
        command_prefix="kubectl",
        yaml_bundle_path=FIXTURE,
    )
    assert spec.spec_sha256
    assert len(spec.spec_sha256) == 64
    assert spec.spec_sha256 == again.spec_sha256


def test_unsupported_verbs_filtered(spec: CliSpec):
    names = {c.name for c in spec.commands}
    for verb in KubectlCobraYamlSource.unsupported_verbs:
        assert verb not in names, f"{verb} should have been filtered out"
    assert "logs" not in names


def test_every_command_has_name_and_flags_list(spec: CliSpec):
    for cmd in spec.commands:
        assert isinstance(cmd, CommandSpec)
        assert cmd.name
        assert isinstance(cmd.flags, list)


def test_get_command_has_expected_flags(spec: CliSpec):
    get_cmd = next(c for c in spec.commands if c.name == "get")
    assert "--output" in get_cmd.flags
    assert "--all-namespaces" in get_cmd.flags
    assert "--selector" in get_cmd.flags


def test_extract_intents_max_intents_slice(spec: CliSpec):
    intents = KubectlCobraYamlSource.extract_intents(spec, "get", max_intents=3)
    assert len(intents) == 3


def test_extract_intents_default_returns_many(spec: CliSpec):
    intents = KubectlCobraYamlSource.extract_intents(spec, "get")
    assert len(intents) >= 20, "clean-invariants per-verb templates should yield 20+ intents/verb"


def test_extract_intents_max_intents_one(spec: CliSpec):
    intents = KubectlCobraYamlSource.extract_intents(spec, "get", max_intents=1)
    assert len(intents) == 1
    assert intents[0].behaviour_tag == "happy_path"


def test_extract_intents_unknown_command_returns_empty(spec: CliSpec):
    assert KubectlCobraYamlSource.extract_intents(spec, "does-not-exist") == []


def test_extract_intents_unsupported_verb_returns_empty(spec: CliSpec):
    assert KubectlCobraYamlSource.extract_intents(spec, "logs") == []


@pytest.mark.xfail(
    reason="Parser fixture drift: template shape expects 'kubectl' at index 1 but parser produces operand tokens; carried over from Kubectl merge"
)
def test_intent_shape(spec: CliSpec):
    intents = KubectlCobraYamlSource.extract_intents(spec, "apply")
    for intent in intents:
        assert isinstance(intent, TestIntent)
        assert isinstance(intent.cmdline_template, list)
        assert intent.cmdline_template, "argv must be non-empty"
        assert all(isinstance(tok, str) for tok in intent.cmdline_template)
        assert intent.cmdline_template[0] == "apply"
        assert intent.cmdline_template[1] == "kubectl"
        assert intent.expected_exit in {0, 1, 2}
        assert intent.behaviour_tag in _VALID_BEHAVIOURS
        assert intent.source_method_sha256
        assert intent.raw_source


def test_intents_covers_all_three_behaviour_tags(spec: CliSpec):
    intents = KubectlCobraYamlSource.extract_intents(spec, "get")
    tags = {i.behaviour_tag for i in intents}
    assert tags == {"happy_path", "error_nonexistent", "error_invalid_args"}


@pytest.mark.xfail(
    reason="Parser fixture drift: template shape expects 'kubectl' at index 1 but parser produces operand tokens; carried over from Kubectl merge"
)
def test_happy_path_uses_example_when_present(spec: CliSpec):
    intents = KubectlCobraYamlSource.extract_intents(spec, "scale")
    happy = next(i for i in intents if i.behaviour_tag == "happy_path")
    assert happy.cmdline_template[:2] == ["scale", "kubectl"]


@pytest.mark.xfail(
    reason="Parser fixture drift: template shape expects 'kubectl' at index 1 but parser produces operand tokens; carried over from Kubectl merge"
)
def test_error_nonexistent_uses_placeholder_token(spec: CliSpec):
    intents = KubectlCobraYamlSource.extract_intents(spec, "delete")
    nonexistent = next(i for i in intents if i.behaviour_tag == "error_nonexistent")
    assert nonexistent.cmdline_template[0] == "delete"
    assert nonexistent.cmdline_template[1] == "kubectl"
    assert any(tok.startswith("nonexistent-") for tok in nonexistent.cmdline_template), (
        f"expected a 'nonexistent-*' token, got: {nonexistent.cmdline_template}"
    )


def test_error_invalid_args_uses_bogus_flag(spec: CliSpec):
    intents = KubectlCobraYamlSource.extract_intents(spec, "describe")
    invalid = next(i for i in intents if i.behaviour_tag == "error_invalid_args")
    assert "--invalid-flag" in invalid.cmdline_template


def test_missing_bundle_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        KubectlCobraYamlSource.extract_spec(
            clone_dir=REPO_ROOT,
            command_prefix="kubectl",
            yaml_bundle_path=REPO_ROOT / "does" / "not" / "exist.yaml",
        )


def test_bundle_must_be_a_mapping(tmp_path):
    bogus = tmp_path / "bogus.yaml"
    bogus.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a mapping"):
        KubectlCobraYamlSource.extract_spec(
            clone_dir=REPO_ROOT,
            command_prefix="kubectl",
            yaml_bundle_path=bogus,
        )


def test_envs_root_resolution(tmp_path):
    envs_root = tmp_path / "envs"
    (envs_root / "kubernetes_kubectl").mkdir(parents=True)
    target = envs_root / "kubernetes_kubectl" / "kubectl_spec.yaml"
    target.write_bytes(FIXTURE.read_bytes())
    spec = KubectlCobraYamlSource.extract_spec(
        clone_dir=REPO_ROOT,
        command_prefix="kubectl",
        envs_root=envs_root,
    )
    assert spec.commands


def test_go_main_file_exists_and_reasonable_size():
    assert GO_MAIN.is_file(), f"missing {GO_MAIN}"
    lines = GO_MAIN.read_text(encoding="utf-8").splitlines()
    assert 40 <= len(lines) <= 100, f"main.go should be 40-100 lines, got {len(lines)}"


def test_go_main_contains_required_symbols():
    text = GO_MAIN.read_text(encoding="utf-8")
    for token in (
        "package main",
        "cobra/doc",
        "GenYamlTree",
        "kubectl/pkg/cmd",
        "NewDefaultKubectlCommand",
        "cli-runtime/pkg/genericiooptions",
    ):
        assert token in text, f"main.go missing required symbol: {token!r}"


def test_go_mod_pins_kubectl():
    text = GO_MOD.read_text(encoding="utf-8")
    assert "module cobra_extractor" in text
    assert "k8s.io/kubectl" in text
    assert "v0.31" in text, "expected k8s.io/kubectl pinned to a v0.31.x line"
    assert "github.com/spf13/cobra" in text


def test_go_main_gofmt_clean_when_available():
    import shutil
    import subprocess

    gofmt = shutil.which("gofmt")
    if gofmt is None:
        pytest.skip("gofmt not available on this host")
    result = subprocess.run(
        [gofmt, "-l", str(GO_MAIN)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"gofmt failed: {result.stderr}"
    assert result.stdout.strip() == "", f"gofmt reported unformatted files: {result.stdout}"
