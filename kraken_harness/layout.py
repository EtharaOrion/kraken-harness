"""Which bundle bytes an inference workspace carries, by Harbor layout class.

The classes follow the Trinity Harbor path inventory (ADR 0165). Agent-visible and
config paths are carried. The oracle-only tree, the verifier-only tree and every
unclassed path are never descended into, so the harness reads none of their bytes and
no workspace an agent reaches can hold them.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePosixPath

AGENT_VISIBLE_FILES = ("instruction.md", "trajectory.json")
AGENT_VISIBLE_DIRS = ("environment",)
CONFIG_FILES = ("task.toml", "README.md")
STEPS_DIR = "steps"
STEP_VISIBLE_FILES = ("instruction.md", "trajectory.json", "setup.sh")
STEP_VISIBLE_DIRS = ("workdir",)


def _regular_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path}: a carried file must be a regular file")
    return path


def _tree(directory: Path) -> Iterator[Path]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"{directory}: a carried tree must be a regular directory")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"{path}: a carried tree holds no symbolic link")
        if path.is_file():
            yield path


def _step_files(steps: Path) -> Iterator[Path]:
    for step in sorted(steps.iterdir()):
        if step.is_symlink() or not step.is_dir():
            continue
        for item in sorted(step.iterdir()):
            if item.name in STEP_VISIBLE_FILES:
                yield _regular_file(item)
            elif item.name in STEP_VISIBLE_DIRS:
                yield from _tree(item)


def carried_files(bundle: Path) -> list[PurePosixPath]:
    """Every bundle-relative file the inference workspace carries, in sorted order."""
    out: list[Path] = []
    for entry in sorted(bundle.iterdir()):
        if entry.name in AGENT_VISIBLE_FILES or entry.name in CONFIG_FILES:
            out.append(_regular_file(entry))
        elif entry.name in AGENT_VISIBLE_DIRS:
            out.extend(_tree(entry))
        elif entry.name == STEPS_DIR and entry.is_dir() and not entry.is_symlink():
            out.extend(_step_files(entry))
    return [PurePosixPath(path.relative_to(bundle).as_posix()) for path in out]
