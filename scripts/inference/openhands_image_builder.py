"""Docker image builder for OpenHands agent-server layers.

Ports the image-building logic from openhands-benchmarks/build_utils.py
into the official SWE-fficiency harness.

The key idea: take a prebuilt ``swefficiency/swefficiency-images:<instance>``
base image and layer the OpenHands agent-server + SDK on top using
``build_with_telemetry`` from the SDK.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from openhands_config import (
    DEFAULT_BUILD_TARGET,
    EVAL_AGENT_SERVER_IMAGE,
    SDK_ROOT,
)

logger = logging.getLogger(__name__)

# ── Cache for the pre-built SDK sdist ─────────────────────────────────
_cached_sdist_path: Path | None = None


def _get_sdk_info() -> dict[str, str]:
    """Read git ref, SHA, and version from the vendored SDK submodule."""
    try:
        git_ref = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=SDK_ROOT,
            text=True,
        ).strip()
    except Exception:
        git_ref = "unknown"

    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=SDK_ROOT,
            text=True,
        ).strip()
    except Exception:
        git_sha = "unknown"

    # Try to read version from pyproject.toml
    sdk_version = "0.0.0"
    pyproject = SDK_ROOT / "openhands-sdk" / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text().splitlines():
            if line.strip().startswith("version"):
                sdk_version = line.split("=")[1].strip().strip('"').strip("'")
                break

    return {"git_ref": git_ref, "git_sha": git_sha, "sdk_version": sdk_version}


def _pre_build_sdist() -> Path:
    """Build the SDK as a .tar.gz sdist once for reuse across image builds.

    Returns the path to the .tar.gz file.
    The caller should call ``cleanup_sdist()`` when done with all builds.
    """
    global _cached_sdist_path
    if _cached_sdist_path is not None and _cached_sdist_path.exists():
        return _cached_sdist_path

    sdist_dir = Path(tempfile.mkdtemp(prefix="sweff-sdist-")).resolve()
    logger.info("Building SDK sdist in %s ...", sdist_dir)

    # Build from the openhands-sdk sub-package, NOT the monorepo workspace root.
    # Building from workspace root produces a broken "unknown-0.0.0.tar.gz".
    sdk_package_dir = SDK_ROOT / "openhands-sdk"
    if not sdk_package_dir.exists():
        raise RuntimeError(
            f"SDK sub-package not found at {sdk_package_dir}. "
            "Run: bash scripts/inference/setup_sdk.sh"
        )

    result = subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(sdist_dir)],
        cwd=sdk_package_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to build SDK sdist:\n{result.stderr}"
        )

    # Find the .tar.gz
    tar_files = list(sdist_dir.glob("*.tar.gz"))
    if not tar_files:
        raise RuntimeError(f"No .tar.gz found in {sdist_dir}")

    _cached_sdist_path = tar_files[0]
    logger.info("SDK sdist built: %s", _cached_sdist_path)
    return _cached_sdist_path


def cleanup_sdist() -> None:
    """Remove the cached sdist temp directory."""
    global _cached_sdist_path
    if _cached_sdist_path is not None:
        parent = _cached_sdist_path.parent
        _cached_sdist_path = None
        shutil.rmtree(parent, ignore_errors=True)


def local_image_exists(tag: str) -> bool:
    """Check whether a Docker image tag exists locally."""
    result = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def build_agent_server_image(
    base_image: str,
    custom_tag: str,
    target: str = DEFAULT_BUILD_TARGET,
    force_build: bool = False,
) -> str:
    """Build a layered agent-server image on top of a base SWE-fficiency image.

    Args:
        base_image: The prebuilt swefficiency image, e.g.
            ``ghcr.io/swefficiency/swefficiency-images:numpy__numpy-11720``.
        custom_tag: A string to include in the image tag, typically
            ``swefficiency.<instance_id>``.
        target: Build target (default: ``source-minimal``).
        force_build: Rebuild even if the image already exists locally.

    Returns:
        The full image tag of the built agent-server image.
    """
    # Deferred import — only needed when actually building
    from openhands.agent_server.docker.build import (
        BuildOptions,
        build_with_telemetry,
    )

    sdk_info = _get_sdk_info()
    short_sha = sdk_info["git_sha"][:12]

    # Construct the expected image tag
    suffix = f"-{target}" if target != "binary" else ""
    image_tag = f"{EVAL_AGENT_SERVER_IMAGE}:{short_sha}-{custom_tag}{suffix}"

    # Check if already exists locally
    force = force_build or os.environ.get("FORCE_BUILD") == "1"
    if not force and local_image_exists(image_tag):
        logger.info("Image already exists locally: %s", image_tag)
        return image_tag

    # Pre-build sdist for reuse
    sdist_path = _pre_build_sdist()

    logger.info("Building agent-server image: %s", image_tag)
    logger.info("  Base image: %s", base_image)
    logger.info("  SDK SHA: %s", short_sha)
    logger.info("  Target: %s", target)

    opts = BuildOptions(
        base_image=base_image,
        custom_tags=custom_tag,
        image=EVAL_AGENT_SERVER_IMAGE,
        target=target,
        platforms=["linux/amd64"],
        push=False,
        git_ref=sdk_info["git_ref"],
        git_sha=sdk_info["git_sha"],
        prebuilt_sdist=sdist_path,
        sdk_version=sdk_info["sdk_version"],
        sdk_project_root=SDK_ROOT,
    )

    output = build_with_telemetry(opts)

    # Verify the expected tag was produced
    if image_tag not in (output.tags if hasattr(output, "tags") else []):
        # The build may use slightly different tag format — check availability
        if not local_image_exists(image_tag):
            # Try to find the actual tag
            for tag in getattr(output, "tags", []):
                if custom_tag in tag:
                    image_tag = tag
                    break
            else:
                raise RuntimeError(
                    f"Build completed but expected tag {image_tag} not found. "
                    f"Available tags: {getattr(output, 'tags', 'unknown')}"
                )

    logger.info("Image built successfully: %s", image_tag)
    return image_tag


def ensure_image(
    instance_id: str,
    target: str = DEFAULT_BUILD_TARGET,
    force_build: bool = False,
) -> tuple[str, str]:
    """Ensure the agent-server image exists for a given instance.

    Returns:
        (agent_server_image_tag, base_image_tag)
    """
    from openhands_config import DOCKER_IMAGE_PREFIX

    base_image = f"{DOCKER_IMAGE_PREFIX}:{instance_id}"
    custom_tag = f"swefficiency.{instance_id}"

    agent_server_image = build_agent_server_image(
        base_image=base_image,
        custom_tag=custom_tag,
        target=target,
        force_build=force_build,
    )

    return agent_server_image, base_image
