"""SimulationBackend registry for the cli_app pipeline.

Backends register themselves at import time via `@register_backend(...)`.
Callers should always go through `get_backend(name)` rather than importing
concrete backend classes directly.
"""

from .base import PromptBundle, SimulationBackend, get_backend, register_backend
from .simulation import dynamodb_local as _dynamodb_local  # noqa: F401
from .simulation import kwok as _kwok  # noqa: F401
from .simulation import minio as _minio  # noqa: F401
from .source import aws_botocore as _aws_botocore_source  # noqa: F401
from .source import aws_tests as _aws_tests_source  # noqa: F401
from .source import kubectl_cobra_yaml as _kubectl_cobra_yaml_source  # noqa: F401

__all__ = ["PromptBundle", "SimulationBackend", "get_backend", "register_backend"]
