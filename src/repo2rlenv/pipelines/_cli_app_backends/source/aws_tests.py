"""AwsTestsSource — populated in C2.

Delegates to ``repo2rlenv.pipelines._cli_app_extract`` for aws-cli white-box
test-derived extraction: this module is a thin facade so relocating logic
here in future refactors cannot drift from the shipped bytes captured by
the byte-identity + prompt-snapshot regression gates.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from repo2rlenv.pipelines import _cli_app_extract as _E
from repo2rlenv.pipelines._cli_app_backends.source.base import (
    CommandSourceBackend,
    register_source,
)


@register_source("aws_tests")
class AwsTestsSource(CommandSourceBackend):
    name: ClassVar[str] = "aws_tests"
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
        entry_point_override: str | None = None,
        tests_dir_override: str | None = None,
    ) -> _E.CliSpec:
        """Build a CliSpec from aws-cli test_*_command.py file names."""
        return _E.extract_cli_spec(
            clone_dir,
            command_prefix,
            repo=repo,
            git_sha=git_sha,
            entry_point_override=entry_point_override,
            tests_dir_override=tests_dir_override,
        )

    @classmethod
    def extract_intents(
        cls,
        spec: _E.CliSpec,
        command: str,
        *,
        tests_dir: Path,
        max_intents: int | None = None,
    ) -> list[_E.TestIntent]:
        """Extract TestIntents from the aws-cli white-box test corpus."""
        return _E.extract_test_intents(
            tests_dir,
            spec,
            command_filter=command,
            max_intents=max_intents,
        )
