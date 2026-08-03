"""Load GenerationInput from YAML, TOML, or build it from CLI flags.

Convention: --config <path> loads a file; CLI flags override file fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from repo2rlenv.spec.input import GenerationInput


def load_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text) or {}
    if path.suffix == ".toml":
        try:
            import tomllib  # py3.11+
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore[import-not-found]
        return tomllib.loads(text)
    if path.suffix == ".json":
        import json

        return json.loads(text)
    raise ValueError(f"unsupported config format: {path.suffix}")


def merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into `base` (override wins)."""
    out = dict(base)
    for k, v in override.items():
        if v is None:
            continue
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def load_generation_input(
    config_path: Path | None,
    overrides: dict[str, Any] | None = None,
) -> GenerationInput:
    raw: dict[str, Any] = {}
    if config_path is not None:
        raw = load_config_file(config_path)
    if overrides:
        raw = merge(raw, overrides)
    return GenerationInput.model_validate(raw)
