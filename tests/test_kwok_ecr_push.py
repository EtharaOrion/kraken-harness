from __future__ import annotations

import pytest

from repo2rlenv.pipelines import _cli_app_synthesis as cas


@pytest.fixture(autouse=True)
def _clear_subset_cache():
    cas._KWOK_SUBSET_IMAGE_CACHE.clear()
    yield
    cas._KWOK_SUBSET_IMAGE_CACHE.clear()


KUBECTL = "v1.31.0"
BASE = "python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28"
REG = "426628337772.dkr.ecr.ap-south-1.amazonaws.com"


def test_subset_hash_order_insensitive():
    assert cas._kwok_subset_hash(
        ["get", "apply", "delete"], KUBECTL, BASE
    ) == cas._kwok_subset_hash(["delete", "get", "apply"], KUBECTL, BASE)


def test_subset_hash_differs_by_command_set():
    a = cas._kwok_subset_hash(["get", "apply"], KUBECTL, BASE)
    b = cas._kwok_subset_hash(["get", "delete"], KUBECTL, BASE)
    assert a != b


def test_subset_hash_differs_by_kubectl_version():
    a = cas._kwok_subset_hash(["get"], "v1.31.0", BASE)
    b = cas._kwok_subset_hash(["get"], "v1.32.0", BASE)
    assert a != b


def test_subset_hash_differs_by_kwok_base_image():
    a = cas._kwok_subset_hash(["get"], KUBECTL, BASE)
    b = cas._kwok_subset_hash(["get"], KUBECTL, "registry.k8s.io/kwok/cluster:v0.8.0-k8s.v1.31.0")
    assert a != b


def test_subset_hash_length_is_8_hex_chars():
    h = cas._kwok_subset_hash(["get"], KUBECTL, BASE)
    assert len(h) == 8
    int(h, 16)


def test_preflight_ecr_env_ok_with_profile():
    cas._preflight_ecr_env("myprofile")


def test_preflight_ecr_env_ok_with_env_profile(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.setenv("AWS_PROFILE", "prod")
    cas._preflight_ecr_env(None)


def test_preflight_ecr_env_ok_with_access_key(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA...")
    cas._preflight_ecr_env(None)


def test_preflight_ecr_env_raises_without_credentials(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with pytest.raises(RuntimeError, match="AWS_ACCESS_KEY_ID"):
        cas._preflight_ecr_env(None)


def _install_push_stubs(monkeypatch):
    calls: dict[str, list] = {
        "ensure_repo": [],
        "login": [],
        "build_push": [],
        "manifest_exists": [],
        "digest": [],
    }

    def _fake_ensure_repo(image_ref, *, profile=None):
        calls["ensure_repo"].append((image_ref, profile))

    def _fake_login(registry, region, *, profile=None):
        calls["login"].append((registry, region, profile))

    def _fake_manifest_exists(image_ref):
        calls["manifest_exists"].append(image_ref)
        return False

    def _fake_build_and_push(*, context_dir, image_ref, platforms):
        calls["build_push"].append((str(context_dir), image_ref, tuple(platforms)))

    def _fake_digest(image_ref, *, timeout=60):
        calls["digest"].append(image_ref)
        return "sha256:" + ("a" * 64)

    monkeypatch.setattr(cas, "ensure_ecr_repository", _fake_ensure_repo)
    monkeypatch.setattr(cas, "ensure_docker_login_ecr", _fake_login)
    monkeypatch.setattr(cas, "manifest_exists", _fake_manifest_exists)
    monkeypatch.setattr(cas, "build_and_push_multiarch", _fake_build_and_push)
    monkeypatch.setattr(cas, "_get_manifest_digest", _fake_digest)
    return calls


def test_build_and_push_returns_sha_pinned_digest_ref(monkeypatch):
    _install_push_stubs(monkeypatch)
    ref = cas._build_and_push_kwok_subset_image(
        registry=REG,
        profile=None,
        platforms=["linux/amd64"],
        cmd_names=["get", "apply"],
        kubectl_version=KUBECTL,
        kwok_base_image=BASE,
        dockerfile="FROM scratch\n",
        git_sha="deadbeef",
    )
    sha8 = cas._kwok_subset_hash(["get", "apply"], KUBECTL, BASE)
    assert ref == f"{REG}/r2e-kubectl-{sha8}@sha256:" + ("a" * 64)


def test_build_and_push_passes_expected_docker_args(monkeypatch):
    calls = _install_push_stubs(monkeypatch)
    cas._build_and_push_kwok_subset_image(
        registry=REG,
        profile="ci",
        platforms=["linux/amd64", "linux/arm64"],
        cmd_names=["get"],
        kubectl_version=KUBECTL,
        kwok_base_image=BASE,
        dockerfile="FROM scratch\n",
        git_sha="deadbeef",
    )
    sha8 = cas._kwok_subset_hash(["get"], KUBECTL, BASE)
    expected_tag = f"{REG}/r2e-kubectl-{sha8}:vdeadbeef"

    assert calls["ensure_repo"] == [(expected_tag, "ci")]
    assert calls["login"] == [(REG, "ap-south-1", "ci")]
    assert calls["manifest_exists"] == [expected_tag]
    assert len(calls["build_push"]) == 1
    _, pushed_ref, platforms = calls["build_push"][0]
    assert pushed_ref == expected_tag
    assert platforms == ("linux/amd64", "linux/arm64")
    assert calls["digest"] == [expected_tag]


def test_build_and_push_is_cached_per_subset(monkeypatch):
    calls = _install_push_stubs(monkeypatch)
    for _ in range(3):
        cas._build_and_push_kwok_subset_image(
            registry=REG,
            profile=None,
            platforms=["linux/amd64"],
            cmd_names=["get", "apply"],
            kubectl_version=KUBECTL,
            kwok_base_image=BASE,
            dockerfile="FROM scratch\n",
            git_sha="deadbeef",
        )
    assert len(calls["build_push"]) == 1
    assert len(calls["ensure_repo"]) == 1
    assert len(calls["digest"]) == 1


def test_build_and_push_different_subsets_push_separately(monkeypatch):
    calls = _install_push_stubs(monkeypatch)
    for subset in (["get"], ["apply"], ["delete"]):
        cas._build_and_push_kwok_subset_image(
            registry=REG,
            profile=None,
            platforms=["linux/amd64"],
            cmd_names=subset,
            kubectl_version=KUBECTL,
            kwok_base_image=BASE,
            dockerfile="FROM scratch\n",
            git_sha="deadbeef",
        )
    assert len(calls["build_push"]) == 3
    pushed_refs = {call[1] for call in calls["build_push"]}
    assert len(pushed_refs) == 3


def test_build_and_push_skips_when_manifest_exists(monkeypatch):
    calls = _install_push_stubs(monkeypatch)
    monkeypatch.setattr(cas, "manifest_exists", lambda ref: True)
    ref = cas._build_and_push_kwok_subset_image(
        registry=REG,
        profile=None,
        platforms=["linux/amd64"],
        cmd_names=["get"],
        kubectl_version=KUBECTL,
        kwok_base_image=BASE,
        dockerfile="FROM scratch\n",
        git_sha="deadbeef",
    )
    assert calls["build_push"] == []
    assert ref.endswith(":" + ("a" * 64))
    assert "@sha256:" in ref


def test_build_and_push_rejects_non_ecr_registry(monkeypatch):
    _install_push_stubs(monkeypatch)
    with pytest.raises(cas._TaskRejected, match="cli_app_ecr_unsupported_registry"):
        cas._build_and_push_kwok_subset_image(
            registry="ghcr.io/example",
            profile=None,
            platforms=["linux/amd64"],
            cmd_names=["get"],
            kubectl_version=KUBECTL,
            kwok_base_image=BASE,
            dockerfile="FROM scratch\n",
            git_sha="deadbeef",
        )


def test_sha_pinning_lands_in_emitted_dockerfile_from_line(monkeypatch):
    from repo2rlenv.emitter import harbor as harbor_emitter

    _install_push_stubs(monkeypatch)
    ref = cas._build_and_push_kwok_subset_image(
        registry=REG,
        profile=None,
        platforms=["linux/amd64"],
        cmd_names=["get", "apply"],
        kubectl_version=KUBECTL,
        kwok_base_image=BASE,
        dockerfile="FROM scratch\n",
        git_sha="deadbeef",
    )
    emitted_dockerfile = (
        f"# syntax=docker/dockerfile:1\n# Shared kwok subset image (SHA-pinned).\nFROM {ref}\n"
    )

    import re

    m = re.search(r"^(\s*FROM\s+)(\S+)", emitted_dockerfile, re.IGNORECASE | re.MULTILINE)
    assert m is not None
    assert m.group(2) == ref
    assert "@sha256:" in m.group(2)
    assert harbor_emitter is not None


def test_get_manifest_digest_hashes_raw_manifest_bytes(monkeypatch):
    import subprocess

    class _P:
        returncode = 0
        stdout = b'{"schemaVersion":2}'
        stderr = b""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _P())
    digest = cas._get_manifest_digest("registry/repo:tag")
    import hashlib

    assert digest == "sha256:" + hashlib.sha256(b'{"schemaVersion":2}').hexdigest()


def test_get_manifest_digest_raises_on_failure(monkeypatch):
    import subprocess

    class _P:
        returncode = 1
        stdout = b""
        stderr = b"manifest unknown"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _P())
    with pytest.raises(RuntimeError, match="manifest unknown"):
        cas._get_manifest_digest("registry/repo:tag")


def test_kwok_backend_exposes_pinned_kubectl_version():
    from repo2rlenv.pipelines._cli_app_backends.simulation.kwok import (
        KwokSimulationBackend,
    )

    assert KwokSimulationBackend.pinned_kubectl_version.startswith("v")
    assert "." in KwokSimulationBackend.pinned_kubectl_version
