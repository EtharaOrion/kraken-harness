"""Regression suite locking the MinIO-only end-state of the cli_app pipeline.

Phase 8 of plans/minio_migration_plan.md. These tests guard against
accidental boto3/botocore/moto re-introduction in any of the artifacts the
cli_app pipeline ships to consumers: pinned deps, Dockerfile, conftest, the
workflow-tests import preamble, and the three LLM prompts (translation,
oracle, workflow).
"""

from __future__ import annotations

import repo2rlenv.pipelines._cli_app_synthesis as S

_FORBIDDEN_PACKAGE_TOKENS = ("boto3", "botocore")
_FORBIDDEN_MOTO_TOKENS = ("ThreadedMotoServer", "mock_aws", "from moto", "import moto")


def test_pinned_deps_is_minio_only() -> None:
    deps = " ".join(S.PINNED_DEPS)
    assert "minio==" in deps
    for token in _FORBIDDEN_PACKAGE_TOKENS:
        assert token not in deps, f"{token} leaked into PINNED_DEPS"
    assert "moto" not in deps


def test_build_dockerfile_emits_minio_no_boto3() -> None:
    out = S._build_dockerfile()
    assert "minio==" in out
    assert "/usr/local/bin/minio" in out
    assert "/usr/local/bin/mc" in out
    assert S.PINNED_MINIO_SHA256 in out
    assert S.PINNED_MC_SHA256 in out
    assert "sha256sum -c -" in out
    for token in _FORBIDDEN_PACKAGE_TOKENS:
        assert token not in out, f"{token} leaked into Dockerfile"
    assert "moto" not in out


def test_build_conftest_emits_minio_no_boto3() -> None:
    out = S._build_conftest()
    assert "from minio import Minio" in out
    assert "from minio.error import S3Error" in out
    assert "subprocess.Popen(" in out and '"minio"' in out and '"server"' in out
    assert "Minio(" in out
    assert "/minio/health/live" in out
    for token in _FORBIDDEN_PACKAGE_TOKENS:
        assert token not in out, f"{token} leaked into conftest"
    for token in _FORBIDDEN_MOTO_TOKENS:
        assert token not in out, f"{token} leaked into conftest"


def test_workflow_import_preamble_is_minio() -> None:
    assert S._WF_IMPORT_PREAMBLE == (
        "from minio import Minio\nfrom minio.error import S3Error\nfrom io import BytesIO\n\n\n"
    )
    for token in _FORBIDDEN_PACKAGE_TOKENS:
        assert token not in S._WF_IMPORT_PREAMBLE


def test_translation_prompt_teaches_minio_sdk() -> None:
    prompt = S.TRANSLATION_SYSTEM
    assert "minio" in prompt.lower()
    assert "minio.error.S3Error" in prompt
    for sdk_method in ("make_bucket", "stat_object", "remove_object", "list_objects"):
        assert sdk_method in prompt, f"mapping-table target {sdk_method} missing"
    # Inverted-polarity check: each banned name must APPEAR in the prompt
    # because the prompt's forbidden-tokens block names them explicitly.
    for token in ("boto3", "botocore", "moto", "@mock_aws"):
        assert token in prompt, f"forbidden-tokens block must mention {token}"


def test_oracle_prompts_teach_minio_sdk() -> None:
    for prompt_name in ("ORACLE_SYSTEM", "ORACLE_SUBSET_SYSTEM"):
        prompt = getattr(S, prompt_name)
        assert "Minio(" in prompt, f"{prompt_name} missing Minio() constructor example"
        assert "MINIO_ENDPOINT" in prompt, f"{prompt_name} missing MINIO_ENDPOINT env reference"
        assert "minio.error.S3Error" in prompt, f"{prompt_name} missing S3Error handling"
        # Forbidden-tokens block must explicitly name the banned libraries.
        for token in ("boto3", "botocore", "moto"):
            assert token in prompt, f"{prompt_name} forbidden block missing {token}"
