"""Reconstruct a Dockerfile-like representation from an OCI image's config history.

Docker images do not preserve their originating Dockerfile. This module reads the
image config `history[]` array (recorded by BuildKit / legacy builder for every
layer) and rebuilds a Dockerfile that reproduces the essential shape of the
source: FROM / RUN / COPY / ADD / CMD / ENTRYPOINT / EXPOSE / ENV / LABEL / etc.

Fetches metadata via `docker buildx imagetools inspect --raw`, which reads
directly from the registry and is architecture-agnostic - no local image pull
needed. That sidesteps the linux/arm64 vs linux/amd64 manifest mismatch that
`docker pull` hits on Apple Silicon when the image was pushed as amd64-only.

The reconstruction is an approximation. Multi-stage build boundaries, ARG
defaults, comments, and BuildKit heredocs are NOT recoverable from image
config alone.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_INSPECT_CMD = ("docker", "buildx", "imagetools", "inspect", "--raw")
_NOP_PREFIX = "/bin/sh -c #(nop) "
_SHELL_PREFIX = "/bin/sh -c "


def reconstruct_base_dockerfile(image_ref: str, *, timeout_sec: float = 60.0) -> str:
    """Return a Dockerfile-like reconstruction of `image_ref`.

    Cached at ``$XDG_CACHE_HOME/repo2rlenv/base_dockerfiles/<key>.Dockerfile``.
    Raises ``RuntimeError`` if docker is unavailable, the registry rejects the
    request, the manifest is malformed, or the config blob lacks a history.
    """
    cache_key = hashlib.sha256(image_ref.encode("utf-8")).hexdigest()[:16]
    cache_path = _cache_dir() / f"{cache_key}.Dockerfile"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    content = _reconstruct_from_registry(image_ref, timeout_sec=timeout_sec)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(content, encoding="utf-8")
    return content


def _cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "repo2rlenv" / "base_dockerfiles"


def _reconstruct_from_registry(image_ref: str, *, timeout_sec: float) -> str:
    manifest = _inspect_raw(image_ref, timeout_sec=timeout_sec)
    if isinstance(manifest.get("manifests"), list):
        arch_digest = _pick_linux_amd64(manifest["manifests"])
        if arch_digest is None:
            raise RuntimeError(f"no linux/amd64 entry in manifest list for {image_ref!r}")
        manifest = _inspect_raw(
            _rebase_with_digest(image_ref, arch_digest), timeout_sec=timeout_sec
        )
    config_digest = (manifest.get("config") or {}).get("digest")
    if not config_digest:
        raise RuntimeError(f"manifest for {image_ref!r} has no config digest")
    config_json = _inspect_raw(
        _rebase_with_digest(image_ref, config_digest), timeout_sec=timeout_sec
    )
    history = config_json.get("history") or []
    if not history:
        raise RuntimeError(f"image config for {image_ref!r} has no history array")

    lines: list[str] = [
        "# Reconstructed from OCI image config history.",
        f"# Source image: {image_ref}",
        f"# Config digest: {config_digest}",
        "#",
        "# Approximation only. Multi-stage boundaries, ARG defaults, comments,",
        "# and BuildKit heredocs are NOT preserved.",
        "",
    ]
    for entry in history:
        directive = _to_dockerfile_directive(entry)
        if directive is not None:
            lines.append(directive)
    return "\n".join(lines).rstrip() + "\n"


def _pick_linux_amd64(manifests: list[dict]) -> str | None:
    for m in manifests:
        plat = m.get("platform") or {}
        if plat.get("architecture") == "amd64" and plat.get("os") == "linux":
            digest = m.get("digest")
            if isinstance(digest, str):
                return digest
    return None


def _inspect_raw(ref: str, *, timeout_sec: float) -> dict:
    try:
        result = subprocess.run(
            [*_INSPECT_CMD, ref],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "docker CLI not found; base Dockerfile reconstruction requires docker"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"docker buildx imagetools inspect timed out after {timeout_sec}s for {ref!r}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"docker buildx imagetools inspect failed for {ref!r}: "
            f"exit={result.returncode}, stderr={result.stderr.strip()[:400]}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"docker buildx imagetools inspect returned non-JSON for {ref!r}: {exc}"
        ) from exc


def _rebase_with_digest(ref: str, digest: str) -> str:
    at = ref.find("@")
    if at >= 0:
        base = ref[:at]
    else:
        # Strip a trailing `:tag`, guarding registry-port colons like `host:443/repo`.
        slash = ref.rfind("/")
        colon = ref.rfind(":")
        base = ref[:colon] if colon > slash else ref
    return f"{base}@{digest}"


def _to_dockerfile_directive(entry: dict) -> str | None:
    created_by = (entry.get("created_by") or "").strip()
    if not created_by:
        return None
    if created_by.startswith(_NOP_PREFIX):
        return created_by[len(_NOP_PREFIX) :].strip()
    if created_by.startswith(_SHELL_PREFIX):
        return f"RUN {created_by[len(_SHELL_PREFIX) :].strip()}"
    return created_by


__all__ = ["reconstruct_base_dockerfile"]
