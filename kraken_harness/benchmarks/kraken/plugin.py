"""The Kraken benchmark's three duties."""

from __future__ import annotations

import tomllib
from pathlib import Path

from kraken_harness import workspace
from kraken_harness.base import Benchmark, Rollout
from kraken_harness.lanes import Instance, resident_instances


def _declared_uuid(task_toml: Path) -> str | None:
    metadata = tomllib.loads(task_toml.read_text(encoding="utf-8")).get("metadata", {})
    declared = metadata.get("bundle_uuid") if isinstance(metadata, dict) else None
    return declared if isinstance(declared, str) else None


class KrakenBenchmark(Benchmark):
    """Kraken bundles live in lane directories named by their uuid, which task.toml restates."""

    def prepare_instances(
        self, root: Path, lanes: tuple[str, ...], only: frozenset[str]
    ) -> list[Instance]:
        instances = resident_instances(root, lanes, only)
        for instance in instances:
            declared = _declared_uuid(instance.bundle / "task.toml")
            if declared is not None and declared != instance.uuid:
                raise ValueError(
                    f"{instance.bundle}: task.toml names bundle {declared}"
                )
        return instances

    def prepare_workspace(
        self, instance: Instance, work_dir: Path
    ) -> workspace.Workspace:
        return workspace.prepare(instance, work_dir)

    def evaluate_instance(self, rollout: Rollout, work_dir: Path) -> list[str]:
        # Harbor's regrade runs no agent: it reads the bundle's tests/ itself and leaves the
        # source trial unchanged, so the harness opens no verifier or oracle byte.
        return self.harbor.trial_regrade(
            rollout.trial_dir,
            rollout.instance.bundle,
            f"{rollout.trial_name}-eval",
            work_dir / "evaluations",
        )


BENCHMARK = KrakenBenchmark
