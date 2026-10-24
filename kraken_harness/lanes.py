"""Find resident bundles through the parent project's lane root indirection.

A lane is a name such as ``samples`` or ``delivery``. The parent's ``.trinity/project.json``
maps each lane name to its directory; a lane it does not map resolves to ``<root>/<lane>``.
A resident bundle is a direct child directory named by a lowercase version 5 UUID that
holds a ``task.toml``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_FILE = Path(".trinity") / "project.json"
BUNDLE_NAME = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)


@dataclass(frozen=True, slots=True)
class Instance:
    uuid: str
    lane: str
    bundle: Path


def lane_root(root: Path, lane: str) -> Path:
    """The directory ``lane`` names under ``root``, never a directory outside it."""
    base = root.resolve()
    mapped: object = None
    project = root / PROJECT_FILE
    if project.is_file():
        paths = json.loads(project.read_text(encoding="utf-8")).get("paths", {})
        mapped = paths.get(lane) if isinstance(paths, dict) else None
    resolved = (
        (base / mapped).resolve() if isinstance(mapped, str) and mapped else base / lane
    )
    if base not in resolved.parents:
        raise ValueError(f"lane {lane!r} resolves outside {base}: {resolved}")
    return resolved


def resident_instances(
    root: Path, lanes: tuple[str, ...], only: frozenset[str] = frozenset()
) -> list[Instance]:
    """Every resident bundle in ``lanes``, in lane then name order, optionally narrowed."""
    found: list[Instance] = []
    seen: dict[str, str] = {}
    for lane in lanes:
        base = lane_root(root, lane)
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if (
                entry.is_symlink()
                or not entry.is_dir()
                or BUNDLE_NAME.fullmatch(entry.name) is None
            ):
                continue
            if not (entry / "task.toml").is_file():
                continue
            if entry.name in seen:
                raise ValueError(
                    f"bundle {entry.name} is resident in both {seen[entry.name]} and {lane}"
                )
            seen[entry.name] = lane
            if not only or entry.name in only:
                found.append(Instance(entry.name, lane, entry))
    return found
