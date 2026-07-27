"""DynamoDB-Local SimulationBackend — populated in C1c.

Mirrors the delegation pattern established in ``minio.py``: this module is a
thin facade that forwards to ``repo2rlenv.pipelines._cli_app_synthesis`` so
relocating logic here in future refactors cannot drift from the shipped bytes
captured by the byte-identity + prompt-snapshot regression gates.
"""

from __future__ import annotations

from typing import ClassVar

from repo2rlenv.emitter.harbor import (
    BLOCKED_HOSTS_DDB,
    BLOCKED_SUFFIXES_DDB,
    _build_disallow_compose,
)
from repo2rlenv.pipelines import _cli_app_synthesis as _S
from repo2rlenv.pipelines._cli_app_backends.base import (
    PromptBundle,
    SimulationBackend,
    register_backend,
)


@register_backend("dynamodb_local")
class DynamodbLocalSimulationBackend(SimulationBackend):
    name: ClassVar[str] = "dynamodb_local"
    compatible_sources: ClassVar[frozenset[str]] = frozenset({"aws_tests", "aws_botocore"})
    prompt_template_version: ClassVar[str] = _S.PROMPT_TEMPLATE_VERSION_DDB
    pinned_deps: ClassVar[tuple[str, ...]] = _S.PINNED_DEPS_DDB
    pinned_base_image: ClassVar[str] = _S.PINNED_DDB_BASE_IMAGE
    blocked_hosts: ClassVar[tuple[str, ...]] = BLOCKED_HOSTS_DDB
    blocked_suffixes: ClassVar[tuple[str, ...]] = BLOCKED_SUFFIXES_DDB
    fixture_client_names: ClassVar[tuple[str, ...]] = ("ddb_client",)
    entry_point: ClassVar[str] = "submission/aws"
    prompts: ClassVar[PromptBundle] = PromptBundle(
        translation_system=_S.TRANSLATION_SYSTEM_DDB,
        translation_user_template=_S.TRANSLATION_USER_TEMPLATE_DDB,
        oracle_single_system=_S.ORACLE_SYSTEM_DDB,
        oracle_single_user_template=_S.ORACLE_USER_TEMPLATE_DDB,
        oracle_subset_system=_S.ORACLE_SUBSET_SYSTEM_DDB,
        oracle_subset_user_template=_S.ORACLE_SUBSET_USER_TEMPLATE_DDB,
        workflow_system=_S.WORKFLOW_SYSTEM_DDB,
        workflow_user_template=_S.WORKFLOW_USER_TEMPLATE_DDB,
    )

    @classmethod
    def dockerfile_base(cls, base_image: str | None = None) -> str:
        """DDB app-layer Dockerfile on the polyglot DDB task_env base image."""
        return _S._build_dockerfile(base_image=base_image, backend="dynamodb_local")

    @classmethod
    def dockerfile_gauntlet_layers(cls) -> str:
        """DDB Local baked into the gauntlet image (loopback endpoint, no sidecar)."""
        return _S._DDB_GAUNTLET_LAYERS

    @classmethod
    def dockerfile_golden_layer(cls, deps: tuple[str, ...]) -> str:
        """DDB app-layer Dockerfile with golden slice deps in place of PINNED_DEPS_DDB."""
        return _S._build_dockerfile(backend="dynamodb_local", golden=True, golden_deps=deps)

    @classmethod
    def build_conftest(cls, *, golden: bool = False) -> str:
        """DDB conftest bytes (compose-sidecar client + drop-all-tables reset)."""
        return _S._build_conftest(backend="dynamodb_local", golden=golden)

    @classmethod
    def build_test_sh(cls) -> str:
        """Shared JUnit-XML reward parser test.sh (backend-agnostic)."""
        return _S._build_test_script()

    @classmethod
    def compose_overlay(cls) -> str | None:
        """Compose overlay adding the DDB sidecar + DDB-flavoured disallow-list."""
        return _build_disallow_compose(BLOCKED_HOSTS_DDB, ddb_sidecar=True)

    @classmethod
    def aux_test_modules(cls) -> dict[str, str]:
        """Stdlib-only DynamoDB HTTP helper shipped under tests/ (no boto3)."""
        return {"_ddb_http.py": _S._DDB_HTTP_HELPER}

    @classmethod
    def workflow_preamble(cls) -> str:
        """Import preamble prepended to each split workflow-test module."""
        return _S._WF_IMPORT_PREAMBLE_DDB

    @classmethod
    def command_state_model(cls) -> dict[tuple[str, str], str]:
        """DynamoDB subset of the shared _COMMAND_STATE_MODEL."""
        return {k: v for k, v in _S._COMMAND_STATE_MODEL.items() if k[0] == "dynamodb"}

    @classmethod
    def cross_command_invariants(cls, names: list[str]) -> str:
        """Render DynamoDB cross-command invariant bullets for a subset task."""
        return _S._cross_command_invariants_ddb(names)
