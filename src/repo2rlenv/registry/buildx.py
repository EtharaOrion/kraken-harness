"""docker buildx wrapper for multi-arch image builds.

`docker build` + `docker commit` (used elsewhere in this codebase) cannot
produce multi-arch manifest lists. `docker buildx build --platform a,b --push`
does — buildx will push per-arch child images and stitch them into a single
manifest list at the target tag in one shot.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class BuildxError(Exception):
    """Raised when a docker buildx operation fails."""


def buildx_available() -> bool:
    """True iff `docker buildx version` succeeds."""
    if shutil.which("docker") is None:
        return False
    proc = subprocess.run(
        ["docker", "buildx", "version"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return proc.returncode == 0


def manifest_exists(image_ref: str, *, timeout: int = 30) -> bool:
    """True iff `docker manifest inspect image_ref` succeeds (image already pushed)."""
    if shutil.which("docker") is None:
        return False
    proc = subprocess.run(
        ["docker", "manifest", "inspect", image_ref],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode == 0


def build_and_push_multiarch(
    *,
    context_dir: Path | str,
    image_ref: str,
    platforms: list[str],
    dockerfile: Path | str | None = None,
    build_args: dict[str, str] | None = None,
    timeout: int = 1800,
) -> None:
    """Run `docker buildx build --platform <p1>,<p2> --push -t image_ref context_dir`.

    Pushing multi-platform always emits a manifest list at `image_ref` and child
    images at the same tag suffixed by `-<arch>` on the registry side.
    """
    if not buildx_available():
        raise BuildxError("docker buildx is not available on PATH")
    if not platforms:
        raise BuildxError("platforms must be non-empty")

    ctx = str(context_dir)
    args = [
        "docker",
        "buildx",
        "build",
        "--platform",
        ",".join(platforms),
        "--push",
        "-t",
        image_ref,
    ]
    if dockerfile is not None:
        args += ["-f", str(dockerfile)]
    for k, v in (build_args or {}).items():
        args += ["--build-arg", f"{k}={v}"]
    args.append(ctx)

    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise BuildxError(
            f"docker buildx build --push {image_ref} failed: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


__all__ = [
    "BuildxError",
    "build_and_push_multiarch",
    "buildx_available",
    "manifest_exists",
]
