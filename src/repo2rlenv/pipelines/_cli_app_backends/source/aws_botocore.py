"""AwsBotocoreSource — populated in C2.

Mirrors the delegation pattern established in ``aws_tests.py``: this module
is a thin facade that forwards to ``repo2rlenv.pipelines._cli_app_extract``
so relocating logic here in future refactors cannot drift from the shipped
bytes captured by the byte-identity + prompt-snapshot regression gates.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from repo2rlenv.pipelines import _cli_app_extract as _E
from repo2rlenv.pipelines._cli_app_backends.source.base import (
    CommandSourceBackend,
    register_source,
)


@register_source("aws_botocore")
class AwsBotocoreSource(CommandSourceBackend):
    name: ClassVar[str] = "aws_botocore"
    compatible_sims: ClassVar[frozenset[str]] = frozenset({"minio", "dynamodb_local"})
    accepted_exit_codes: ClassVar[frozenset[int]] = frozenset({252, 254, 255})
    stdout_shape_regex: ClassVar[str] = r"^[a-z_]+:\s+\S"
    reference_binary: ClassVar[str] = "aws"
    unsupported_verbs: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def extract_spec(
        cls,
        clone_dir: Path,
        command_prefix: str,
        *,
        repo: str,
        git_sha: str,
        target_operations: tuple[str, ...] = _E._DDB_TARGET_OPS_DEFAULT,
        model_path_override: str | None = None,
    ) -> tuple[_E.CliSpec, dict]:
        """Build a CliSpec from a vendored botocore service-2.json model."""
        return _E.extract_cli_spec_from_model(
            clone_dir,
            command_prefix,
            repo=repo,
            git_sha=git_sha,
            target_operations=target_operations,
            model_path_override=model_path_override,
        )

    @classmethod
    def extract_intents(
        cls,
        spec: _E.CliSpec,
        command: str,
        *,
        model: dict,
        target_operations: tuple[str, ...] = _E._DDB_TARGET_OPS_DEFAULT,
        max_intents: int | None = None,
    ) -> list[_E.TestIntent]:
        """Synthesise TestIntents from the botocore service model shapes."""
        return _E.synthesize_intents_from_model(
            model,
            command,
            spec.command_prefix,
            target_operations=target_operations,
            max_intents=max_intents,
        )
