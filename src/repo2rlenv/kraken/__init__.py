"""kraken — the harness command surface.

Every stage from a merged pull request to a reward lives behind one entry point:
`kraken harvest | author | run | grade | status`.

The stages need to know where the knowledge root is, and they must not learn it by
counting parent directories. This package sits five levels below the harness and the
harness has already moved three times; a hard-coded depth is a bug waiting for the
fourth move. `find_root` looks for the markers that define a kraken tree instead.
"""

from __future__ import annotations

import os
from pathlib import Path

# A kraken knowledge root is the directory that owns the requirements and the three
# instruments. Any one of these alone could appear elsewhere; together they do not.
ROOT_MARKERS = ("requirements/PARAMETERS.md", "seed", "memory", "audit")


def find_root(start: Path | None = None) -> Path:
    """Locate the knowledge root by its markers, walking up from a starting point.

    Order of resolution: an explicit KRAKEN_ROOT, then upward from the caller's
    working directory, then upward from this file. The environment variable exists
    so a run from outside the tree, or a relocated checkout, has a way to say where
    the root is without editing code.
    """
    env = os.environ.get("KRAKEN_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if _is_root(p):
            return p
        raise SystemExit(
            f"KRAKEN_ROOT={env} does not look like a kraken tree "
            f"(expected {', '.join(ROOT_MARKERS)})"
        )

    for origin in (start or Path.cwd(), Path(__file__).resolve()):
        for candidate in (origin, *origin.parents):
            if _is_root(candidate):
                return candidate

    raise SystemExit(
        "cannot locate the kraken knowledge root. Run from inside the tree, or set "
        "KRAKEN_ROOT to the directory holding requirements/, seed/, memory/ and audit/."
    )


def _is_root(p: Path) -> bool:
    return all((p / m).exists() for m in ROOT_MARKERS)


def harness_dir(root: Path | None = None) -> Path:
    """The harness directory, which owns the runtime and the rollout driver."""
    return (root or find_root()) / "kraken-harness"
