"""Resource-limited Docker workspace for OpenHands inference.

Extends the SDK's ``DockerWorkspace`` to enforce CPU/memory limits
via ``docker update`` after the container starts (matching the
openhands-benchmarks approach).
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from pydantic import Field, PrivateAttr

from openhands.workspace import DockerWorkspace

logger = logging.getLogger(__name__)


class ResourceLimitedDockerWorkspace(DockerWorkspace):
    """DockerWorkspace with post-start resource capping.

    The base DockerWorkspace creates and starts the container (which
    includes the agent-server HTTP process).  We then run
    ``docker update`` to pin CPU sets and memory limits—identical to
    what openhands-benchmarks/workspace.py does.
    """

    # ── Extra fields for resource limits ──────────────────────────────
    cpuset_cpus: str | None = Field(default=None, description="e.g. '0,1,2,3'")
    nano_cpus: int | None = Field(default=None, description="1e9 = 1 CPU")
    mem_limit_str: str | None = Field(default="16g", alias="mem_limit_override")

    # ── Private bookkeeping for cleanup ───────────────────────────────
    _cpu_group: list[int] | None = PrivateAttr(default=None)
    _cpu_groups_queue: Any = PrivateAttr(default=None)
    _images_to_cleanup: list[str] = PrivateAttr(default_factory=list)
    _prune_buildkit_cache_on_cleanup: bool = PrivateAttr(default=False)

    def _start_container(self, image: str, context: Any) -> None:
        """Start container via parent, then apply resource limits."""
        super()._start_container(image, context)
        self._apply_resource_limits()

    def _apply_resource_limits(self) -> None:
        """Run ``docker update`` on the live container."""
        container_id = self._container_id  # type: ignore[attr-defined]
        if not container_id:
            logger.warning("No container ID; skipping resource limits")
            return

        cmd = ["docker", "update"]
        if self.cpuset_cpus:
            cmd.extend(["--cpuset-cpus", self.cpuset_cpus])
        if self.nano_cpus is not None:
            cpus = self.nano_cpus / 1e9
            cmd.extend(["--cpus", str(cpus)])
        if self.mem_limit_str:
            cmd.extend(["--memory", self.mem_limit_str])
            cmd.extend(["--memory-swap", self.mem_limit_str])
        cmd.append(container_id)

        if len(cmd) > 3:  # only run if there are flags
            logger.info("Applying resource limits: %s", " ".join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning(
                    "docker update failed (rc=%d): %s",
                    result.returncode,
                    result.stderr.strip(),
                )

    def cleanup(self) -> None:
        """Clean up container, return CPU group, remove images."""
        try:
            super().cleanup()
        except Exception:
            logger.exception("Error during workspace cleanup")

        # Return CPU group to the pool
        if self._cpu_group is not None and self._cpu_groups_queue is not None:
            try:
                self._cpu_groups_queue.put(self._cpu_group)
            except Exception:
                logger.exception("Failed to return CPU group to queue")

        # Remove images
        for image in self._images_to_cleanup:
            try:
                subprocess.run(
                    ["docker", "rmi", "-f", image],
                    capture_output=True,
                    text=True,
                )
                logger.info("Removed image: %s", image)
            except Exception:
                logger.exception("Failed to remove image: %s", image)

        # Prune buildkit cache
        if self._prune_buildkit_cache_on_cleanup:
            try:
                subprocess.run(
                    ["docker", "buildx", "prune", "--all", "--force"],
                    capture_output=True,
                    text=True,
                )
            except Exception:
                logger.exception("Failed to prune buildkit cache")
