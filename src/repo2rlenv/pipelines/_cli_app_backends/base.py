"""SimulationBackend Protocol — cli_app runtime abstraction.

Encapsulates: Dockerfile fragments, conftest content, blocked-hosts
tuples, LLM prompt bundle, and per-task auxiliary modules for one
simulated backend (MinIO for S3, DynamoDB-Local for DDB, Kwok for k8s).

Populated in C1b (MinIO), C1c (DDB), and C3 (Kwok). Wired into
_cli_app_synthesis.py in C1d.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable


@dataclass(frozen=True)
class PromptBundle:
    """LLM prompt bundle (translation, oracle single/subset, workflow) per backend."""

    translation_system: str
    translation_user_template: str
    oracle_single_system: str
    oracle_single_user_template: str
    oracle_subset_system: str
    oracle_subset_user_template: str
    workflow_system: str
    workflow_user_template: str


@runtime_checkable
class SimulationBackend(Protocol):
    """Runtime simulation backend for cli_app-mode tasks.

    Two co-varying invariants callers rely on:
      1. blocked_hosts + blocked_suffixes bytes are baked into emitted
         conftest — mutating them across a release perturbs every task's
         content_hash. Grow via PARALLEL tuples per backend, never shared.
      2. prompt_template_version MUST be a per-subclass ClassVar override.
         Sharing a single value flips every existing task's task_id.
    """

    name: ClassVar[str]
    compatible_sources: ClassVar[frozenset[str]]
    prompt_template_version: ClassVar[str]
    pinned_deps: ClassVar[tuple[str, ...]]
    pinned_base_image: ClassVar[str]
    blocked_hosts: ClassVar[tuple[str, ...]]
    blocked_suffixes: ClassVar[tuple[str, ...]]
    fixture_client_names: ClassVar[tuple[str, ...]]
    prompts: ClassVar[PromptBundle]
    runtime_cpus: ClassVar[float] = 1.0
    runtime_memory_mb: ClassVar[int] = 1024
    entry_point: ClassVar[str] = "submission/main.py"

    @classmethod
    def dockerfile_base(cls, base_image: str | None) -> str: ...

    @classmethod
    def dockerfile_gauntlet_layers(cls) -> str: ...

    @classmethod
    def dockerfile_golden_layer(cls, deps: tuple[str, ...]) -> str: ...

    @classmethod
    def build_conftest(cls, *, golden: bool) -> str: ...

    @classmethod
    def build_test_sh(cls) -> str: ...

    @classmethod
    def compose_overlay(cls) -> str | None: ...

    @classmethod
    def aux_test_modules(cls) -> dict[str, str]: ...

    @classmethod
    def workflow_preamble(cls) -> str: ...

    @classmethod
    def command_state_model(cls) -> dict[tuple[str, str], str]: ...

    @classmethod
    def cross_command_invariants(cls, names: list[str]) -> str: ...


_BACKENDS: dict[str, type[SimulationBackend]] = {}


def register_backend(name: str):
    """Decorator: register a backend class under `name`."""

    def _decorate(cls):
        if name in _BACKENDS:
            raise RuntimeError(f"cli_app backend {name!r} already registered")
        _BACKENDS[name] = cls
        return cls

    return _decorate


def get_backend(name: str) -> type[SimulationBackend]:
    """Return the registered backend class for `name`; raise if unknown."""
    if name not in _BACKENDS:
        registered = sorted(_BACKENDS)
        raise ValueError(f"unknown cli_app backend {name!r}; registered: {registered}")
    return _BACKENDS[name]
