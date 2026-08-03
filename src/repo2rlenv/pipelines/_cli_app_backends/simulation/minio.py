"""MinIO SimulationBackend — populated in C1b.

Delegates to ``repo2rlenv.pipelines._cli_app_synthesis`` for artefact
byte-identity: this module is a thin facade so relocating logic here in
future refactors cannot drift from the shipped bytes captured by the
byte-identity + prompt-snapshot regression gates.
"""

from __future__ import annotations

from typing import ClassVar

from repo2rlenv.emitter.harbor import BLOCKED_HOSTS, BLOCKED_SUFFIXES
from repo2rlenv.pipelines import _cli_app_synthesis as _S
from repo2rlenv.pipelines._cli_app_backends.base import (
    PromptBundle,
    SimulationBackend,
    register_backend,
)


@register_backend("minio")
class MinioSimulationBackend(SimulationBackend):
    name: ClassVar[str] = "minio"
    compatible_sources: ClassVar[frozenset[str]] = frozenset({"aws_tests", "aws_botocore"})
    prompt_template_version: ClassVar[str] = _S.PROMPT_TEMPLATE_VERSION
    pinned_deps: ClassVar[tuple[str, ...]] = _S.PINNED_DEPS
    pinned_base_image: ClassVar[str] = _S.PINNED_BASE_IMAGE
    blocked_hosts: ClassVar[tuple[str, ...]] = BLOCKED_HOSTS
    blocked_suffixes: ClassVar[tuple[str, ...]] = BLOCKED_SUFFIXES
    fixture_client_names: ClassVar[tuple[str, ...]] = ("s3_client", "minio_client")
    entry_point: ClassVar[str] = "submission/aws"
    prompts: ClassVar[PromptBundle] = PromptBundle(
        translation_system=_S.TRANSLATION_SYSTEM,
        translation_user_template=_S.TRANSLATION_USER_TEMPLATE,
        oracle_single_system=_S.ORACLE_SYSTEM,
        oracle_single_user_template=_S.ORACLE_USER_TEMPLATE,
        oracle_subset_system=_S.ORACLE_SUBSET_SYSTEM,
        oracle_subset_user_template=_S.ORACLE_SUBSET_USER_TEMPLATE,
        workflow_system=_S.WORKFLOW_SYSTEM,
        workflow_user_template=_S.WORKFLOW_USER_TEMPLATE,
    )

    @classmethod
    def dockerfile_base(cls, base_image: str | None = None) -> str:
        """MinIO Dockerfile app-layer (non-golden)."""
        return _S._build_dockerfile(base_image=base_image, backend="minio")

    @classmethod
    def dockerfile_gauntlet_layers(cls) -> str:
        """MinIO has no gauntlet-only overlay; DDB does (baked DDB Local)."""
        return ""

    @classmethod
    def dockerfile_golden_layer(cls, deps: tuple[str, ...]) -> str:
        """MinIO Dockerfile app-layer with golden slice deps + no aws-cli closure."""
        return _S._build_dockerfile(backend="minio", golden=True, golden_deps=deps)

    @classmethod
    def build_conftest(cls, *, golden: bool = False) -> str:
        """MinIO conftest bytes (subprocess-launched MinIO + iterate-and-delete reset)."""
        return _S._build_conftest(backend="minio", golden=golden)

    @classmethod
    def build_test_sh(cls) -> str:
        """Shared JUnit-XML reward parser test.sh (backend-agnostic)."""
        return _S._build_test_script()

    @classmethod
    def compose_overlay(cls) -> str | None:
        """MinIO runs loopback-only inside `main`; no compose sidecar needed."""
        return None

    @classmethod
    def aux_test_modules(cls) -> dict[str, str]:
        """MinIO ships no aux test modules (the `minio` SDK is a real package)."""
        return {}

    @classmethod
    def workflow_preamble(cls) -> str:
        """Import preamble prepended to each split workflow-test module."""
        return _S._WF_IMPORT_PREAMBLE

    @classmethod
    def command_state_model(cls) -> dict[tuple[str, str], str]:
        """S3 subset of the shared _COMMAND_STATE_MODEL."""
        return {k: v for k, v in _S._COMMAND_STATE_MODEL.items() if k[0] == "s3"}

    @classmethod
    def cross_command_invariants(cls, names: list[str]) -> str:
        """Render S3 cross-command invariant bullets for a subset task."""
        return _S._cross_command_invariants("s3", names)
