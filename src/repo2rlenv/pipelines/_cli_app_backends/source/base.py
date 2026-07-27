"""CommandSourceBackend Protocol — cli_app command + intent extractor.

Encapsulates: which commands exist under the target prefix (CliSpec) and
the per-command TestIntent list (happy_path / error / edge / workflow),
plus the per-CLI grammar (accepted exit codes, stdout shape, reference
binary name, unsupported verbs) that downstream renderers rely on.

Populated in C2 (aws_tests, aws_botocore) and C4 (kubectl_cobra_yaml).
Wired into ``_cli_app_synthesis.py`` in C2.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable


@runtime_checkable
class CommandSourceBackend(Protocol):
    """Command + intent extractor for cli_app-mode source repos.

    Extract CLI grammar (which commands exist, what flags they take, what
    exit codes are valid) and TestIntent list (per-command test scenarios
    covering happy_path / error / edge / workflow).
    """

    name: ClassVar[str]
    compatible_sims: ClassVar[frozenset[str]]
    accepted_exit_codes: ClassVar[frozenset[int]]
    stdout_shape_regex: ClassVar[str]
    reference_binary: ClassVar[str]
    unsupported_verbs: ClassVar[frozenset[str]]

    @classmethod
    def extract_spec(cls, clone_dir: Path, command_prefix: str, **overrides): ...

    @classmethod
    def extract_intents(cls, spec, command: str, *, max_intents: int | None = None): ...


_SOURCES: dict[str, type[CommandSourceBackend]] = {}


def register_source(name: str):
    """Decorator: register a source backend class under `name`."""

    def _decorate(cls):
        if name in _SOURCES:
            raise RuntimeError(f"cli_app source {name!r} already registered")
        _SOURCES[name] = cls
        return cls

    return _decorate


def get_source(name: str) -> type[CommandSourceBackend]:
    """Return the registered source backend class for `name`; raise if unknown."""
    if name not in _SOURCES:
        registered = sorted(_SOURCES)
        raise ValueError(f"unknown cli_app source {name!r}; registered: {registered}")
    return _SOURCES[name]
