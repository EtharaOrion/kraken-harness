"""C6+C7+C8: runtime dispatch of the kwok backend via ``_cli_app_synthesis``.

The byte-identity ratchet (``test_cli_app_byte_identity``) and prompt-snapshot
ratchet (``test_cli_app_prompt_snapshot``) prove the aws paths are unchanged.
This file covers the kwok-specific behaviours those ratchets can't see:

* ``_build_dockerfile`` / ``_build_conftest`` dispatch to
  ``KwokSimulationBackend`` when ``backend="kwok"`` (Dockerfile and conftest
  bytes differ from the MinIO/DDB variants).
* ``_gauntlet_static`` accepts kubectl exit codes (``{0, 1, 2}``) and the
  ``k8s_client`` / ``kubectl_bin`` fixture regex when driven by the
  kubectl_cobra_yaml source + kwok backend.
* The ``cli_app_backend`` Literal validator on ``CodeInstructOptions`` accepts
  ``"kwok"`` and rejects ``aws_mode=True`` in combination with kwok.
"""

from __future__ import annotations

import pytest

import repo2rlenv.pipelines._cli_app_synthesis as S
from repo2rlenv.pipelines._cli_app_backends import get_backend
from repo2rlenv.pipelines._cli_app_backends.source.base import get_source
from repo2rlenv.spec.options import CodeInstructOptions


class TestDockerfileDispatch:
    def test_dockerfile_base_differs_between_backends(self) -> None:
        minio_df = get_backend("minio").dockerfile_base(None)
        kwok_df = get_backend("kwok").dockerfile_base(None)
        assert minio_df != kwok_df, "kwok and minio Dockerfiles must differ"
        assert "kwok" in kwok_df.lower() or "kubectl" in kwok_df.lower()
        assert "minio" in minio_df.lower()

    def test_build_dockerfile_routes_kwok(self) -> None:
        df = S._build_dockerfile(backend="kwok")
        expected = get_backend("kwok").dockerfile_base(None)
        assert df == expected

    def test_build_dockerfile_kwok_golden_uses_golden_layer(self) -> None:
        df = S._build_dockerfile(backend="kwok", golden=True, golden_deps=("foo==1.0",))
        expected = get_backend("kwok").dockerfile_golden_layer(("foo==1.0",))
        assert df == expected


class TestConftestDispatch:
    def test_build_conftest_kwok_routes_to_backend(self) -> None:
        conf = S._build_conftest(backend="kwok", golden=False)
        expected = get_backend("kwok").build_conftest(golden=False)
        assert conf == expected

    def test_build_conftest_kwok_differs_from_minio(self) -> None:
        kwok_conf = S._build_conftest(backend="kwok", golden=False)
        minio_conf = S._build_conftest(backend="minio", golden=False)
        assert kwok_conf != minio_conf
        assert "kwokctl" in kwok_conf
        assert "minio" in minio_conf.lower()

    def test_kwok_conftest_carries_anti_nop_guards(self) -> None:
        conf = get_backend("kwok").build_conftest(golden=False)
        assert "def pytest_configure" in conf
        assert 'shutil.which("kubectl")' in conf
        assert 'shutil.which("kwokctl")' in conf
        assert "Anti-NOP guard" in conf


class TestGauntletKubectl:
    def test_kubectl_source_accepts_012(self) -> None:
        codes = get_source("kubectl_cobra_yaml").accepted_exit_codes
        assert {0, 1, 2} <= codes

    def test_kwok_fixture_names_expose_k8s_client(self) -> None:
        names = get_backend("kwok").fixture_client_names
        assert "k8s_client" in names
        assert "kubectl_bin" in names

    def test_gauntlet_static_kwok_accepts_k8s_state_check(self) -> None:
        test_code = (
            "def test_it(cli, k8s_client):\n"
            "    result = cli('apply', '-f', 'x.yaml')\n"
            "    assert result.returncode == 0\n"
            "    k8s_client.list_namespace()\n"
        )
        ok, reason = S._gauntlet_static(
            test_code,
            expected_behaviour_tag="happy_path",
            source_name="kubectl_cobra_yaml",
            backend_name="kwok",
        )
        assert ok, f"expected pass, got: {reason}"

    def test_gauntlet_static_kwok_rejects_missing_state_check(self) -> None:
        test_code = (
            "def test_it(cli):\n"
            "    result = cli('apply', '-f', 'x.yaml')\n"
            "    assert result.returncode == 0\n"
        )
        ok, reason = S._gauntlet_static(
            test_code,
            expected_behaviour_tag="happy_path",
            source_name="kubectl_cobra_yaml",
            backend_name="kwok",
        )
        assert not ok
        assert "G2d_state" in reason
        assert "k8s_client" in reason

    def test_gauntlet_static_kwok_accepts_pinned_exit_1(self) -> None:
        test_code = (
            "def test_it(cli):\n"
            "    result = cli('get', 'ns', 'nope')\n"
            "    assert result.returncode == 1\n"
        )
        ok, reason = S._gauntlet_static(
            test_code,
            expected_behaviour_tag="error",
            source_name="kubectl_cobra_yaml",
            backend_name="kwok",
        )
        assert ok, f"expected pass on returncode==1, got: {reason}"

    def test_gauntlet_static_aws_default_still_rejects_kubectl_exit_1(self) -> None:
        test_code = (
            "def test_it(cli):\n"
            "    result = cli('get', 'ns', 'nope')\n"
            "    assert result.returncode == 1\n"
        )
        ok, reason = S._gauntlet_static(test_code, expected_behaviour_tag="error")
        assert not ok
        assert "G2c_signal" in reason


class TestOptionsValidator:
    def test_cli_app_backend_accepts_kwok(self) -> None:
        opts = CodeInstructOptions(mode="cli_app", cli_app_backend="kwok")
        assert opts.cli_app_backend == "kwok"

    def test_aws_mode_with_kwok_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="aws_mode=True requires"):
            CodeInstructOptions(mode="cli_app", cli_app_backend="kwok", aws_mode=True)

    def test_aws_mode_with_minio_is_allowed(self) -> None:
        opts = CodeInstructOptions(mode="cli_app", cli_app_backend="minio", aws_mode=True)
        assert opts.aws_mode is True

    def test_aws_mode_with_ddb_is_allowed(self) -> None:
        opts = CodeInstructOptions(mode="cli_app", cli_app_backend="dynamodb_local", aws_mode=True)
        assert opts.aws_mode is True


class TestPromptTemplateVersionDispatch:
    def test_kwok_prompt_template_version_is_distinct(self) -> None:
        opts = CodeInstructOptions(mode="cli_app", cli_app_backend="kwok")
        assert S._prompt_template_version(opts) == get_backend("kwok").prompt_template_version
        opts_m = CodeInstructOptions(mode="cli_app", cli_app_backend="minio")
        assert S._prompt_template_version(opts_m) != S._prompt_template_version(opts)


class TestBackendMetadataDispatch:
    def test_repo2env_pinned_deps_come_from_backend(self) -> None:
        kwok_deps = tuple(get_backend("kwok").pinned_deps)
        minio_deps = tuple(get_backend("minio").pinned_deps)
        ddb_deps = tuple(get_backend("dynamodb_local").pinned_deps)
        assert kwok_deps != minio_deps
        assert kwok_deps != ddb_deps
        assert "minio" not in " ".join(kwok_deps)
        assert any("kubernetes" in d for d in kwok_deps)

    def test_backend_pinned_base_image_distinct(self) -> None:
        images = {
            get_backend("minio").pinned_base_image,
            get_backend("dynamodb_local").pinned_base_image,
            get_backend("kwok").pinned_base_image,
        }
        assert len(images) == 3
