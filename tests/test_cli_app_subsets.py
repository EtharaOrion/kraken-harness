"""Unit tests for the service-agnostic command-subset sampler.

Pure logic: no Docker, LLM, or network. Exercises difficulty weighting, the
bounded powerset enumeration, tercile tiering, and the ``cli_app_subsets`` wire
format produced by :mod:`repo2rlenv.pipelines._cli_app_subsets`.
"""

from __future__ import annotations

from types import SimpleNamespace

from repo2rlenv.pipelines._cli_app_extract import CommandSpec
from repo2rlenv.pipelines._cli_app_subsets import (
    command_weight,
    enumerate_subsets,
    sample_subsets,
    score_subset,
)


def _cmd(name: str, n_flags: int = 0) -> CommandSpec:
    return CommandSpec(name=name, flags=[f"--f{i}" for i in range(n_flags)])


def test_command_weight_is_one_plus_flags() -> None:
    assert command_weight(_cmd("a")) == 1
    assert command_weight(_cmd("a", 2)) == 3


def test_command_weight_adds_two_per_structured_flag() -> None:
    cmd = SimpleNamespace(
        name="put",
        flags=["--item"],
        flag_arity={"--item": "structure", "--keys": "list", "--name": "string"},
    )
    # 1 base + 1 flag + 2 (structure) + 2 (list) + 0 (scalar string)
    assert command_weight(cmd) == 6


def test_score_subset_rewards_size_beyond_two() -> None:
    a, b, c = _cmd("a"), _cmd("b", 1), _cmd("c", 2)
    assert score_subset((a,)) == 1
    # weights 1 + 2 + 3 = 6, plus (3 - 2) * 2 size bonus
    assert score_subset((a, b, c)) == 8


def test_enumerate_bounds_powerset_for_wide_surface() -> None:
    narrow = [_cmd(f"c{i}") for i in range(3)]
    assert any(len(s) == 3 for s in enumerate_subsets(narrow))
    wide = [_cmd(f"c{i}") for i in range(11)]
    assert all(len(s) == 2 for s in enumerate_subsets(wide))


def test_enumerate_respects_explicit_max_size() -> None:
    cmds = [_cmd("a"), _cmd("b"), _cmd("c")]
    assert len(enumerate_subsets(cmds)) == 4  # 3 pairs + 1 triple
    assert len(enumerate_subsets(cmds, max_size=2)) == 3  # pairs only


def test_sample_subsets_needs_at_least_two_commands() -> None:
    assert sample_subsets([]) == []
    assert sample_subsets([_cmd("solo")]) == []


def test_sample_subsets_hardest_first_wire_format() -> None:
    a, b, c = _cmd("a"), _cmd("b", 1), _cmd("c", 2)
    # scores: (a,b,c)=8 > (b,c)=5 > (a,c)=4 > (a,b)=3
    assert sample_subsets([a, b, c]) == ["a,b,c", "b,c", "a,c", "a,b"]


def test_sample_subsets_truncates_to_max() -> None:
    a, b, c = _cmd("a"), _cmd("b", 1), _cmd("c", 2)
    assert sample_subsets([a, b, c], max_subsets=2) == ["a,b,c", "b,c"]


def test_sample_subsets_filters_by_tier() -> None:
    a, b, c = _cmd("a"), _cmd("b", 1), _cmd("c", 2)
    # 4 ranked subsets: ranks 0-1 = hard, 2 = medium, 3 = easy
    assert sample_subsets([a, b, c], tiers=["hard"]) == ["a,b,c", "b,c"]
    assert sample_subsets([a, b, c], tiers=["easy"]) == ["a,b"]
