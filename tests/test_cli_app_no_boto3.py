"""Regression suite locking the MinIO-only end-state of the cli_app pipeline.

Phase 8 of plans/minio_migration_plan.md. These tests guard against
accidental boto3/botocore/moto re-introduction in any of the artifacts the
cli_app pipeline ships to consumers: pinned deps, Dockerfile, conftest, the
workflow-tests import preamble, and the three LLM prompts (translation,
oracle, workflow).

Additional tests (added post-audit) guard the upstream-alignment invariants
surfaced by the Ethara-Pilot-Feedback client review:

  * B — exit-code contract accepts ``252`` (real aws-cli usage-error code)
  * C — no invented ``--tags`` flag on ``aws s3 mb``
  * D — substring-anywhere stdout matching (real aws-cli progress preamble)
  * E — error-category assertions instead of verbatim reference-impl strings
  * F — no client-side bucket-name validation (defer to server, like real S3)

They inspect prompt strings and the source of the instruction.md builders via
``inspect.getsource`` — no Docker, no LLM, ~1s to run.
"""

from __future__ import annotations

import inspect

import repo2rlenv.pipelines._cli_app_synthesis as S

_FORBIDDEN_PACKAGE_TOKENS = ("boto3", "botocore")
_FORBIDDEN_MOTO_TOKENS = ("ThreadedMotoServer", "mock_aws", "from moto", "import moto")

_ALL_PROMPT_NAMES = (
    "TRANSLATION_SYSTEM",
    "ORACLE_SYSTEM",
    "ORACLE_SUBSET_SYSTEM",
    "WORKFLOW_SYSTEM",
)
_INSTRUCTION_MD_BUILDERS = ("_build_instruction_md", "_build_subset_instruction_md")


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
    # mc (MinIO client) is intentionally NOT shipped — the pipeline grades via the
    # `minio` Python SDK, never the mc CLI. The server binary is SHA256-pinned per arch.
    assert S.PINNED_MINIO_SHA256_AMD64 in out
    assert S.PINNED_MINIO_SHA256_ARM64 in out
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
    for token in ("boto3", "botocore", "moto", "@mock_aws"):
        assert token in prompt, f"forbidden-tokens block must mention {token}"


def test_oracle_prompts_teach_minio_sdk() -> None:
    for prompt_name in ("ORACLE_SYSTEM", "ORACLE_SUBSET_SYSTEM"):
        prompt = getattr(S, prompt_name)
        assert "Minio(" in prompt, f"{prompt_name} missing Minio() constructor example"
        assert "MINIO_ENDPOINT" in prompt, f"{prompt_name} missing MINIO_ENDPOINT env reference"
        assert "minio.error.S3Error" in prompt, f"{prompt_name} missing S3Error handling"
        for token in ("boto3", "botocore", "moto"):
            assert token in prompt, f"{prompt_name} forbidden block missing {token}"


# ---------------------------------------------------------------------------
# Post-audit tests — upstream-alignment invariants (Ethara-Pilot-Feedback B-F)
# ---------------------------------------------------------------------------


def test_instruction_md_documents_252_and_255_exit_codes() -> None:
    src = inspect.getsource(S._build_instruction_md)
    assert "252" in src, "_build_instruction_md missing 252 (real aws-cli usage-error code)"
    assert "255" in src, "_build_instruction_md missing 255"


def test_prompts_forbid_returncode_equality_with_specific_error_code() -> None:
    for prompt_name in ("TRANSLATION_SYSTEM", "WORKFLOW_SYSTEM"):
        prompt = getattr(S, prompt_name)
        assert "returncode == 255" in prompt, (
            f"{prompt_name} must call out `returncode == 255` as forbidden"
        )
        assert "NEVER" in prompt or "Never" in prompt, (
            f"{prompt_name} missing NEVER-style directive against equality asserts"
        )
        assert "252" in prompt, f"{prompt_name} must mention real aws-cli code 252"


def test_prompts_forbid_tags_on_mb() -> None:
    for prompt_name in _ALL_PROMPT_NAMES:
        prompt = getattr(S, prompt_name)
        assert "--tags" in prompt, f"{prompt_name} must name --tags as forbidden"
        assert "mb" in prompt, f"{prompt_name} must call out mb specifically"
    for fn_name in _INSTRUCTION_MD_BUILDERS:
        src = inspect.getsource(getattr(S, fn_name))
        assert "--tags" in src, f"{fn_name} must name --tags as forbidden"


def test_prompts_teach_substring_anywhere_stdout() -> None:
    for prompt_name in ("TRANSLATION_SYSTEM", "WORKFLOW_SYSTEM"):
        prompt = getattr(S, prompt_name)
        assert "splitlines()[0]" in prompt, (
            f"{prompt_name} must explicitly forbid stdout.splitlines()[0]"
        )
        assert "in result.stdout" in prompt or "in stdout" in prompt, (
            f"{prompt_name} must teach `pattern in result.stdout` semantics"
        )
    src = inspect.getsource(S._build_instruction_md)
    assert "progress" in src.lower(), "instruction.md must document progress-preamble handling"
    assert "splitlines()[0]" in src, "instruction.md must warn against splitlines()[0]"


def test_prompts_teach_error_category_not_verbatim() -> None:
    for prompt_name in ("TRANSLATION_SYSTEM", "WORKFLOW_SYSTEM"):
        prompt = getattr(S, prompt_name)
        assert "CATEGORY" in prompt or "category" in prompt, (
            f"{prompt_name} must teach error-category matching"
        )
        for keyword in ("NoSuchBucket", "NoSuchKey"):
            assert keyword in prompt, f"{prompt_name} missing category keyword {keyword}"


def test_prompts_forbid_client_side_bucket_name_validation() -> None:
    for prompt_name in _ALL_PROMPT_NAMES:
        prompt = getattr(S, prompt_name)
        low = prompt.lower()
        assert "client-side" in low, (
            f"{prompt_name} must call out client-side rejection as forbidden"
        )
        assert "bucket name" in low, f"{prompt_name} must mention bucket-name context"
    for fn_name in _INSTRUCTION_MD_BUILDERS:
        src = inspect.getsource(getattr(S, fn_name))
        assert "InvalidBucketName" in src, (
            f"{fn_name} must reference server-returned InvalidBucketName"
        )


def test_g2c_rejects_farmable_generic_error_test() -> None:
    loose = (
        "def test_e(cli):\n"
        "    r = cli('kinesis', 'create-stream')\n"
        "    assert r.returncode != 0\n"
        "    assert 'Error' in r.stderr or 'error' in r.stderr\n"
    )
    ok, reason = S._gauntlet_static(loose, expected_behaviour_tag="error_invalid_args")
    assert ok is False and "G2c" in reason


def test_g2c_accepts_specific_error_code_test() -> None:
    specific = (
        "def test_e(cli):\n"
        "    r = cli('kinesis', 'describe-stream', '--stream-name', 'nope')\n"
        "    assert r.returncode != 0\n"
        "    assert 'ResourceNotFoundException' in r.stderr\n"
    )
    ok, reason = S._gauntlet_static(specific, expected_behaviour_tag="error_nonexistent")
    assert ok is True, reason
