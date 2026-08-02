"""Service-agnostic command-subset enumeration + difficulty sampling.

A model-driven sampler usable by ANY AWS CLI service: difficulty is derived from each
command's discovered surface (``CommandSpec.flags`` + optional ``flag_arity``), so no
per-service constants are needed. Subsets are tercile-tiered (hardest third = ``hard``)
and sampled hardest-first under a cap, avoiding the full 2**N powerset for wide services.

Leaf module: imports only ``CommandSpec`` from ``_cli_app_extract``, never the synthesis
engine, so the engine may import it (for auto-subset generation) without a cycle.
"""

from __future__ import annotations

import itertools

from repo2rlenv.pipelines._cli_app_extract import CommandSpec

# botocore shape types that take a structured (JSON) argument — the params models most
# often get wrong, so they raise a command's difficulty weight.
_STRUCTURED_TYPES = frozenset({"structure", "list", "map"})


def command_weight(cmd: CommandSpec) -> int:
    """Model-derived difficulty proxy: ``1 + flag count + 2 per structured (JSON) flag``.

    ``flag_arity`` is optional (absent on test-mined CommandSpecs); when missing the
    weight degrades cleanly to a flag-count proxy.
    """
    weight = 1 + len(cmd.flags)
    weight += sum(2 for t in getattr(cmd, "flag_arity", {}).values() if t in _STRUCTURED_TYPES)
    return weight


def score_subset(subset: tuple[CommandSpec, ...]) -> int:
    """Sum of command weights plus a bonus for each command beyond two."""
    return sum(command_weight(c) for c in subset) + max(0, len(subset) - 2) * 2


def _default_max_size(n_commands: int) -> int:
    """Bound the powerset: full subsets for a narrow surface, pairs-only when wide."""
    return min(n_commands, 6) if n_commands <= 10 else 2


def enumerate_subsets(
    commands: list[CommandSpec], *, min_size: int = 2, max_size: int | None = None
) -> list[tuple[CommandSpec, ...]]:
    """All command combinations of size ``min_size..max_size`` (deterministic order)."""
    n = len(commands)
    top = min(max_size if max_size is not None else _default_max_size(n), n)
    out: list[tuple[CommandSpec, ...]] = []
    for k in range(max(2, min_size), top + 1):
        out.extend(itertools.combinations(commands, k))
    return out


def _tier(rank: int, total: int) -> str:
    """Tercile by descending-score rank: hardest third -> hard, then medium, easy."""
    if total <= 0:
        return "medium"
    p = rank / total
    if p < 1 / 3:
        return "hard"
    if p < 2 / 3:
        return "medium"
    return "easy"


def sample_subsets(
    commands: list[CommandSpec],
    *,
    min_size: int = 2,
    max_size: int | None = None,
    max_subsets: int = 0,
    tiers: list[str] | None = None,
) -> list[str]:
    """Enumerate command subsets, tier by difficulty, return comma-joined names.

    Output is the ``cli_app_subsets`` wire format (``"cmd_a,cmd_b"`` strings), sampled
    hardest-first, restricted to ``tiers`` (None = all), and truncated to ``max_subsets``
    (0 = unbounded). Returns [] when fewer than two commands.
    """
    if len(commands) < 2:
        return []
    subsets = enumerate_subsets(commands, min_size=min_size, max_size=max_size)
    scored = sorted(subsets, key=lambda s: (-score_subset(s), tuple(c.name for c in s)))
    total = len(scored)
    want = set(tiers) if tiers else None
    picked: list[str] = []
    for rank, subset in enumerate(scored):
        if want is not None and _tier(rank, total) not in want:
            continue
        picked.append(",".join(c.name for c in subset))
        if max_subsets and len(picked) >= max_subsets:
            break
    return picked
