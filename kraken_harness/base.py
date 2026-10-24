"""The shared evaluation interface and the orchestration every benchmark inherits.

A benchmark implements three duties: prepare instances from the resident bundles, prepare
a per-instance workspace, and evaluate one instance. The two run loops below are final:
a benchmark inherits them as they are and never reimplements them, and the loops hand all
environment, agent and verifier work to the pinned Harbor release.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, final

from kraken_harness.config import BenchmarkConfig
from kraken_harness.harbor_bridge import Harbor
from kraken_harness.lanes import Instance
from kraken_harness.workspace import Workspace, carried_digest, environment_digest

ROLLOUTS = "rollouts.jsonl"
EVALUATIONS = "evaluations.jsonl"
# Harbor's oracle agent runs a bundle's reference answer, so it never stands in for the agent under test.
ORACLE_AGENT = "oracle"


@dataclass(frozen=True, slots=True)
class Rollout:
    instance: Instance
    attempt: int
    trial_name: str
    trial_dir: Path


def _append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def checked_agent(agent: dict[str, Any]) -> dict[str, Any]:
    """The agent table of the agent under test, refused when it names no agent or the oracle."""
    name, import_path = agent.get("name"), agent.get("import_path")
    if not name and not import_path:
        raise ValueError("the agent table names no agent: set name or import_path")
    if name == ORACLE_AGENT:
        raise ValueError("the oracle agent is not an agent under test")
    return dict(agent)


class Benchmark(abc.ABC):
    """One benchmark: its three duties, its configuration defaults, and the pinned Harbor."""

    def __init__(self, config: BenchmarkConfig) -> None:
        self.config = config
        self.harbor = Harbor(config.harbor_release, config.harbor_commit)

    @abc.abstractmethod
    def prepare_instances(
        self, root: Path, lanes: tuple[str, ...], only: frozenset[str]
    ) -> list[Instance]:
        """Find the instances to run among the resident bundles under the lane roots."""

    @abc.abstractmethod
    def prepare_workspace(self, instance: Instance, work_dir: Path) -> Workspace:
        """Build the per-instance sandboxed workspace Harbor runs the agent in."""

    @abc.abstractmethod
    def evaluate_instance(self, rollout: Rollout, work_dir: Path) -> list[str]:
        """Return the Harbor command that scores one rollout with the bundle's own tests."""

    @final
    def run_inference(
        self,
        root: Path,
        work_dir: Path,
        agent: dict[str, Any],
        *,
        lanes: tuple[str, ...] | None = None,
        only: frozenset[str] = frozenset(),
        rollouts: int | None = None,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        """Run the agent under test on each instance through Harbor with verification off."""
        self.harbor.require_lock(root)
        self.harbor.require_installed()
        agent = checked_agent(agent)
        count = self.config.rollouts if rollouts is None else rollouts
        if count < 1:
            raise ValueError("rollouts must be at least 1")
        trials_dir = work_dir / "trials"
        records: list[dict[str, Any]] = []
        for instance in self.prepare_instances(root, lanes or self.config.lanes, only):
            workspace = self.prepare_workspace(instance, work_dir)
            self.harbor.validate_task(workspace.task_dir, disable_verification=True)
            for attempt in range(1, count + 1):
                trial_name = f"{instance.uuid}-r{attempt}"
                layer = {
                    "task": {"path": str(workspace.task_dir)},
                    "trial_name": trial_name,
                    "trials_dir": str(trials_dir),
                    "agent": agent,
                    "verifier": {"disable": True},
                }
                self.harbor.validate_trial(layer)
                layer_path = workspace.manifest.parent / f"trial-r{attempt}.json"
                layer_path.write_text(
                    json.dumps(layer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                command = self.harbor.trial_start(layer_path)
                record = {
                    "benchmark": self.config.name,
                    "bundle_uuid": instance.uuid,
                    "lane": instance.lane,
                    "attempt": attempt,
                    "trial_name": trial_name,
                    "trial_dir": str(trials_dir / trial_name),
                    "workspace_digest": workspace.digest,
                    "environment_digest": workspace.environment_digest,
                    "harbor_release": self.config.harbor_release,
                    "agent": {
                        key: agent.get(key)
                        for key in ("name", "import_path", "model_name")
                    },
                    "command": command,
                    "dry_run": dry_run,
                    "exit_code": None if dry_run else self.harbor.run(command),
                }
                _append(work_dir / ROLLOUTS, record)
                records.append(record)
        return records

    @final
    def run_evaluation(
        self, root: Path, work_dir: Path, *, dry_run: bool = False
    ) -> list[dict[str, Any]]:
        """Score every recorded rollout by regrading its trial through Harbor."""
        self.harbor.require_lock(root)
        self.harbor.require_installed()
        records: list[dict[str, Any]] = []
        for rollout in self._recorded_rollouts(root, work_dir, dry_run=dry_run):
            command = self.evaluate_instance(rollout, work_dir)
            record = {
                "benchmark": self.config.name,
                "bundle_uuid": rollout.instance.uuid,
                "lane": rollout.instance.lane,
                "attempt": rollout.attempt,
                "rollout_trial_dir": str(rollout.trial_dir),
                "command": command,
                "dry_run": dry_run,
                "exit_code": None if dry_run else self.harbor.run(command),
            }
            _append(work_dir / EVALUATIONS, record)
            records.append(record)
        return records

    def _recorded_rollouts(
        self, root: Path, work_dir: Path, *, dry_run: bool
    ) -> list[Rollout]:
        path = work_dir / ROLLOUTS
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} records no rollout; run kraken-infer first"
            )
        out: list[Rollout] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record["benchmark"] != self.config.name or (
                record["dry_run"] and not dry_run
            ):
                continue
            trial_dir = Path(record["trial_dir"])
            if not dry_run and not trial_dir.is_dir():
                raise FileNotFoundError(
                    f"{trial_dir}: the rollout's trial directory is absent"
                )
            found = self.prepare_instances(
                root, (record["lane"],), frozenset({record["bundle_uuid"]})
            )
            if len(found) != 1:
                raise LookupError(
                    f"bundle {record['bundle_uuid']} is no longer resident in {record['lane']}"
                )
            instance = found[0]
            if carried_digest(instance.bundle) != record["workspace_digest"]:
                raise ValueError(
                    f"{instance.bundle}: carried bytes moved since inference; rerun kraken-infer"
                )
            if environment_digest(instance.bundle) != record["environment_digest"]:
                raise ValueError(
                    f"{instance.bundle}: environment moved since inference; rerun kraken-infer"
                )
            out.append(
                Rollout(
                    instance, int(record["attempt"]), record["trial_name"], trial_dir
                )
            )
        return out
