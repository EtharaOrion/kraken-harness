"""Benchmark directories: one self-describing directory per benchmark.

Each directory carries its configuration defaults in ``benchmark.toml`` and its duties in
``plugin.py``, whose ``BENCHMARK`` names the class that implements them.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from kraken_harness.base import Benchmark
from kraken_harness.config import CONFIG_FILE, BenchmarkConfig

DIRECTORY = Path(__file__).resolve().parent
NAME = re.compile(r"[a-z][a-z0-9_]*\Z")


def available() -> list[str]:
    """The name of every benchmark directory here, in sorted order."""
    return sorted(
        entry.name
        for entry in DIRECTORY.iterdir()
        if entry.is_dir()
        and NAME.fullmatch(entry.name)
        and (entry / CONFIG_FILE).is_file()
    )


def config_of(name: str) -> BenchmarkConfig:
    if name not in available():
        raise LookupError(
            f"no benchmark {name!r}; available: {', '.join(available()) or 'none'}"
        )
    return BenchmarkConfig.load(DIRECTORY / name / CONFIG_FILE)


def load(name: str) -> Benchmark:
    """The benchmark ``name`` with the configuration defaults its directory carries."""
    config = config_of(name)
    benchmark = importlib.import_module(f"{__name__}.{name}.plugin").BENCHMARK
    if not (isinstance(benchmark, type) and issubclass(benchmark, Benchmark)):
        raise TypeError(f"{name}/plugin.py names no Benchmark subclass as BENCHMARK")
    return benchmark(config)
