"""Language-backend registry for the code_instruct pipeline.

Backends register themselves at import time via `@register_backend(...)`.
Callers should always go through `get_backend(hint)` rather than importing
concrete backend classes directly.
"""

from repo2rlenv.bootstrap.spec import LanguageHint

from .base import LanguageBackend, SandboxDelivery

_BACKENDS: dict[LanguageHint, LanguageBackend] = {}


def register_backend(hint: LanguageHint):
    def wrapper(cls: type[LanguageBackend]) -> type[LanguageBackend]:
        _BACKENDS[hint] = cls()
        return cls

    return wrapper


def get_backend(hint: LanguageHint) -> LanguageBackend:
    if hint not in _BACKENDS:
        raise NotImplementedError(
            f"No code_instruct backend for language {hint!r}; "
            f"registered backends: {sorted(str(k) for k in _BACKENDS)}"
        )
    return _BACKENDS[hint]


from . import go as _go  # noqa: E402, F401
from . import python as _python  # noqa: E402, F401

__all__ = ["LanguageBackend", "SandboxDelivery", "get_backend", "register_backend"]
