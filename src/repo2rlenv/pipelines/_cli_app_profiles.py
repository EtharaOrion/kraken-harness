"""Service profiles: the plug-and-play card for one ``aws <service>`` CLI backend.

A :class:`ServiceProfile` bundles everything service-specific about generating tasks
for one AWS CLI service -- the verifier backend, wire protocol, LLM prompt set, the
shipped stdlib raw-HTTP client, and the conftest / Dockerfile / instruction builders --
so the synthesis engine can dispatch on a profile instead of hardcoded ``is_ddb``
branches. Adding a new service means registering a new profile; the engine core is not
edited.

Dependency direction: this module is a leaf. It imports nothing from the synthesis or
extract engine, so both may import it without a cycle. The engine owns the concrete
prompt constants and builder functions, and registers the profiles via :func:`register`
once those are defined. DynamoDB is simply the first registered profile, not a special
case in the engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceProfile:
    """Declarative, service-specific card consumed by the synthesis engine.

    Every field here is something that currently lives behind an ``is_ddb`` /
    ``backend == "dynamodb_local"`` branch. Model-derived backends (DynamoDB and the
    future services) fill the wire/prompt/client fields; a test-mined backend such as
    S3/MinIO leaves them empty and relies on its builder hooks. Builder hooks are
    engine-provided callables so the profile stays free of engine imports.
    """

    # --- identity -------------------------------------------------------------
    backend_key: str  # options.cli_app_backend value, e.g. "dynamodb_local" / "minio"
    service: str  # golden-slice service name, e.g. "dynamodb" / "s3"
    simulation_backend: str  # task.toml [metadata] label

    # --- extraction -----------------------------------------------------------
    extract_mode: str = "botocore_model"  # "botocore_model" | "tests"
    default_target_ops: tuple[str, ...] = ()  # CamelCase ops for botocore_model mode

    # --- wire protocol (model-derived backends; empty for test-mined) ---------
    target_prefix: str = ""  # X-Amz-Target prefix, e.g. "DynamoDB_20120810"
    json_version: str = ""  # AWS JSON protocol version, e.g. "1.0"

    # --- LLM prompt set -------------------------------------------------------
    translation_system: str = ""
    translation_user: str = ""
    oracle_system: str = ""
    oracle_user: str = ""
    oracle_subset_system: str = ""
    oracle_subset_user: str = ""
    workflow_system: str = ""
    workflow_user: str = ""
    wf_preamble: str = ""

    # --- shipped stdlib raw-HTTP client (e.g. tests/_ddb_http.py); None if unused ---
    client_module_path: str | None = None  # aux path, e.g. "tests/_ddb_http.py"
    client_module_src: str | None = None  # module source

    # --- engine-provided builder hooks (keep the profile import-free) ---------
    build_conftest: Callable[..., str] | None = None
    build_dockerfile: Callable[..., str] | None = None
    build_instruction_single: Callable[..., str] | None = None
    build_instruction_subset: Callable[..., str] | None = None

    # --- image + deps ---------------------------------------------------------
    base_image: str = ""
    pinned_deps: tuple[str, ...] = ()

    # --- optional compose overlay (generic sidecar backends only) -------------
    build_compose_overlay: Callable[..., str] | None = None

    # --- reference-grounding labels (surface in task.toml metadata) -----------
    reference_label: str = "aws-cli"
    reference_version_key: str = "awscli_version"
    reference_version_value: str = ""

    def validate(self) -> None:
        """Fail-fast structural check; raises ValueError naming the offending field."""
        if not self.backend_key:
            raise ValueError("ServiceProfile.backend_key is required")
        if not self.service:
            raise ValueError(f"ServiceProfile({self.backend_key!r}).service is required")
        if self.extract_mode not in ("botocore_model", "tests"):
            raise ValueError(
                f"ServiceProfile({self.backend_key!r}).extract_mode invalid: {self.extract_mode!r}"
            )


_REGISTRY: dict[str, ServiceProfile] = {}


def register_profile(profile: ServiceProfile) -> ServiceProfile:
    """Validate and register a profile under its ``backend_key``. Returns it for chaining."""
    profile.validate()
    _REGISTRY[profile.backend_key] = profile
    return profile


def resolve_profile(backend_key: str) -> ServiceProfile | None:
    """Return the registered profile for ``backend_key``, or None if not registered."""
    return _REGISTRY.get(backend_key)


def registered_backends() -> tuple[str, ...]:
    """Sorted tuple of all registered backend keys (drives the options validation)."""
    return tuple(sorted(_REGISTRY))
