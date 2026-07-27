"""C3 sanity checks that KwokSimulationBackend is populated (not stub).

Mirrors the shape of ``test_minio_backend_populated.py`` /
``test_ddb_backend_populated.py`` but asserts against greenfield-authored
kwok bytes (no ``_cli_app_synthesis`` delegation).
"""

from __future__ import annotations

from repo2rlenv.emitter.harbor import BLOCKED_SUFFIXES
from repo2rlenv.pipelines._cli_app_backends import get_backend
from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
    _ECR_POLYGLOT_IMAGE,
    KwokSimulationBackend,
)


def test_backend_is_registered():
    assert get_backend("kwok") is KwokSimulationBackend


def test_prompt_template_version_is_bumped_for_c5():
    assert KwokSimulationBackend.prompt_template_version == "kwok-v7.5.0-workflow-syspath-fix"


def test_compatible_sources_covers_kubectl_cobra_yaml():
    assert "kubectl_cobra_yaml" in KwokSimulationBackend.compatible_sources


def test_pinned_deps_include_kubernetes_client_and_pytest():
    deps = KwokSimulationBackend.pinned_deps
    assert isinstance(deps, tuple)
    assert any("kubernetes" in d for d in deps)
    assert any("pytest==" in d for d in deps)


def test_pinned_base_image_is_ecr_polyglot_digest_pinned():
    img = KwokSimulationBackend.pinned_base_image
    assert img == _ECR_POLYGLOT_IMAGE
    assert img.startswith("426628337772.dkr.ecr.ap-south-1.amazonaws.com/kubectl_kwok@sha256:")
    assert len(img.split("@sha256:")[1]) == 64


def test_pinned_kwok_version_is_v_prefixed():
    assert KwokSimulationBackend.pinned_kwok_version.startswith("v")


def test_blocked_hosts_include_kubernetes_default_svc():
    hosts = KwokSimulationBackend.blocked_hosts
    assert "kubernetes.default.svc.cluster.local" in hosts


def test_blocked_hosts_expanded_covers_all_categories():
    hosts = set(KwokSimulationBackend.blocked_hosts)
    for expected in (
        "pypi.org",
        "download.pytorch.org",
        "github.com",
        "gitlab.com",
        "bitbucket.org",
        "codeberg.org",
        "awscli.amazonaws.com",
        "s3.amazonaws.com",
        "deb.debian.org",
        "cdn-aws.deb.debian.org",
        "archive.ubuntu.com",
        "pypi.tuna.tsinghua.edu.cn",
        "repo.anaconda.com",
        "api.snapcraft.io",
        "formulae.brew.sh",
        "ghcr.io",
        "registry.npmjs.org",
        "nodejs.org",
        "crates.io",
        "sh.rustup.rs",
        "proxy.golang.org",
        "go.dev",
        "repo.maven.apache.org",
        "plugins.gradle.org",
        "api.nuget.org",
        "dotnet.microsoft.com",
        "rubygems.org",
        "dl.k8s.io",
        "kubernetes.io",
        "storage.googleapis.com",
        "eks.amazonaws.com",
        "container.googleapis.com",
        "management.azure.com",
        "login.microsoftonline.com",
        "registry.k8s.io",
        "k8s.gcr.io",
        "quay.io",
        "docker.io",
        "get.helm.sh",
        "charts.helm.sh",
    ):
        assert expected in hosts, f"missing {expected!r} from expanded blocklist"


def test_blocked_hosts_count_meets_expanded_floor():
    hosts = KwokSimulationBackend.blocked_hosts
    assert len(set(hosts)) == len(hosts), "blocked_hosts contains duplicates"
    assert len(hosts) >= 89, f"blocked_hosts has {len(hosts)} entries, expected >= 89"


def test_blocked_suffixes_include_hosted_control_plane_apex():
    sfx = KwokSimulationBackend.blocked_suffixes
    assert "eks.amazonaws.com" in sfx
    assert "googleapis.com" in sfx
    assert "azmk8s.io" in sfx
    for s in BLOCKED_SUFFIXES:
        assert s in sfx


def test_fixture_client_names_are_k8s_client_and_kubectl_bin():
    assert KwokSimulationBackend.fixture_client_names == ("k8s_client", "kubectl_bin")


def test_prompt_bundle_strings_are_populated_after_c5():
    p = KwokSimulationBackend.prompts
    assert p.translation_system
    assert p.translation_user_template
    assert p.oracle_single_system
    assert p.oracle_single_user_template
    assert p.oracle_subset_system
    assert p.oracle_subset_user_template
    assert p.workflow_system
    assert p.workflow_user_template


def test_dockerfile_base_froms_ecr_polyglot_image():
    body = KwokSimulationBackend.dockerfile_base(None)
    assert "# syntax=docker/dockerfile:1" in body
    assert f"ARG BASE_IMAGE={_ECR_POLYGLOT_IMAGE}" in body
    assert "FROM ${BASE_IMAGE}" in body
    assert _ECR_POLYGLOT_IMAGE.startswith(
        "426628337772.dkr.ecr.ap-south-1.amazonaws.com/kubectl_kwok@sha256:"
    )
    assert "sha256:4bcfe127e1e126b50d1fee0a5fe98d69e19751a04ea8cf63eaf15144d1370530" in body


def test_dockerfile_base_sets_python_env_and_kubeconfig():
    body = KwokSimulationBackend.dockerfile_base(None)
    assert "PYTHONDONTWRITEBYTECODE=1" in body
    assert "PYTHONUNBUFFERED=1" in body
    assert "PYTHONHASHSEED=0" in body
    assert "LC_ALL=C.UTF-8" in body
    assert "KUBECONFIG=/etc/kubeconfig" in body


def test_dockerfile_base_prepares_submission_workdir_and_git_baseline():
    body = KwokSimulationBackend.dockerfile_base(None)
    assert "WORKDIR /workspace" in body
    assert "mkdir -p /workspace/submission" in body
    assert "/workspace/submission/.gitkeep" in body
    assert "PATH=/workspace/submission:$PATH" in body
    assert "git init -q /workspace" in body
    assert "user.email raiden@local" in body
    assert "user.name raiden" in body
    assert "raiden: baseline" in body


def test_dockerfile_base_is_short_raiden_style():
    body = KwokSimulationBackend.dockerfile_base(None)
    line_count = body.count("\n")
    assert line_count <= 20, f"expected ~15 lines, got {line_count}"
    assert "apt-get install" not in body
    assert "pip install" not in body
    assert "curl -fsSL" not in body
    assert "sha256sum -c -" not in body
    assert "openhands-sdk" not in body


def test_dockerfile_base_respects_override_image():
    body = KwokSimulationBackend.dockerfile_base("myrepo/custom:latest")
    assert "ARG BASE_IMAGE=myrepo/custom:latest" in body


def test_dockerfile_gauntlet_layers_is_empty_pending_c7():
    assert KwokSimulationBackend.dockerfile_gauntlet_layers() == ""


def test_dockerfile_golden_layer_installs_kubernetes_and_pyyaml():
    body = KwokSimulationBackend.dockerfile_golden_layer(())
    assert "kubernetes==31.0.0" in body
    assert "PyYAML==6.0.2" in body


def test_dockerfile_golden_layer_appends_extra_deps():
    body = KwokSimulationBackend.dockerfile_golden_layer(("foobar==1.2.3",))
    assert "foobar==1.2.3" in body


def test_build_conftest_non_golden_accepts_both_entrypoints():
    body = KwokSimulationBackend.build_conftest(golden=False)
    assert 'shutil.which("kubectl")' in body
    assert 'shutil.which("kwokctl")' in body
    assert "pytest.exit" in body
    assert "KUBECONFIG" in body
    assert "127.0.0.1" in body
    assert "kubernetes" in body
    assert "kwokctl" in body
    # Dual-entrypoint: conftest accepts EITHER kubectl shim OR main.py at runtime.
    assert "/workspace/submission/kubectl" in body
    assert "/workspace/submission/main.py" in body
    assert "_R2E_CLI_PREFIX" in body


def test_build_conftest_golden_accepts_both_entrypoints():
    body = KwokSimulationBackend.build_conftest(golden=True)
    # Golden mode also emits the dual-entrypoint conftest: agents may write
    # either the kubectl shim or a Python main.py; runtime picks whichever
    # exists.
    assert "/workspace/submission/kubectl" in body
    assert "/workspace/submission/main.py" in body
    assert "_R2E_CLI_PREFIX" in body
    assert 'shutil.which("kubectl")' in body
    assert "pytest.exit" in body


def test_build_conftest_defines_all_required_fixtures():
    body = KwokSimulationBackend.build_conftest(golden=False)
    assert "def kwok_cluster" in body
    assert "def k8s_client" in body
    assert "def _reset_kwok" in body
    assert "def cli" in body
    assert "def kubectl_bin" in body


def test_build_conftest_bakes_all_blocked_suffixes():
    body = KwokSimulationBackend.build_conftest(golden=False)
    for suffix in KwokSimulationBackend.blocked_suffixes:
        assert repr(suffix) in body


def test_build_test_sh_ships_junit_reward_parser():
    body = KwokSimulationBackend.build_test_sh()
    assert body.startswith("#!/bin/bash")
    assert "pytest" in body
    assert "reward" in body
    assert "junit-xml=/logs/verifier/results.xml" in body


def test_compose_overlay_is_none_for_kwok():
    assert KwokSimulationBackend.compose_overlay() is None


def test_aux_test_modules_ships_k8s_client_helper():
    mods = KwokSimulationBackend.aux_test_modules()
    assert set(mods) == {"_k8s_client.py"}
    helper = mods["_k8s_client.py"]
    assert "KubectlBuilder" in helper
    assert "NewKubectlCommand" in helper
    assert "WithStdinData" in helper
    assert "WithTimeout" in helper
    assert "run_or_die" in helper
    assert "assert_namespace_exists" in helper
    assert "assert_deployment_replicas" in helper


def test_workflow_preamble_imports_k8s_client_and_kubectl_bin():
    p = KwokSimulationBackend.workflow_preamble()
    assert "k8s_client" in p
    assert "kubectl_bin" in p
    assert "import pytest" in p
    assert "import subprocess" in p


def test_command_state_model_is_empty_pending_c5():
    assert KwokSimulationBackend.command_state_model() == {}


def test_cross_command_invariants_returns_non_empty_placeholder():
    body = KwokSimulationBackend.cross_command_invariants(["apply", "get"])
    assert isinstance(body, str)
    assert body.strip()
    assert "Kubernetes" in body


def test_pinned_deps_are_deterministic_tuple():
    a = KwokSimulationBackend.pinned_deps
    b = KwokSimulationBackend.pinned_deps
    assert a is b
    assert isinstance(a, tuple)
