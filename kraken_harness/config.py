"""The configuration defaults a benchmark directory carries in its ``benchmark.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = "benchmark.toml"


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    name: str
    description: str
    harbor_release: str
    harbor_commit: str
    lanes: tuple[str, ...]
    rollouts: int

    @classmethod
    def load(cls, path: Path) -> BenchmarkConfig:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        try:
            config = cls(
                name=str(document["benchmark"]["name"]),
                description=str(document["benchmark"]["description"]),
                harbor_release=str(document["harbor"]["release"]),
                harbor_commit=str(document["harbor"]["commit"]),
                lanes=tuple(str(lane) for lane in document["lanes"]["resident"]),
                rollouts=int(document["inference"]["rollouts"]),
            )
        except KeyError as missing:
            raise ValueError(f"{path}: missing field {missing}") from None
        if path.parent.name != config.name:
            raise ValueError(
                f"{path}: names benchmark {config.name!r} in directory {path.parent.name!r}"
            )
        if not config.lanes:
            raise ValueError(f"{path}: [lanes] resident names no lane")
        if config.rollouts < 1:
            raise ValueError(f"{path}: [inference] rollouts must be at least 1")
        return config
