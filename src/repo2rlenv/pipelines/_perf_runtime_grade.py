"""Reward composition for kraken perf_runtime tasks. Runs inside the container.

Copied verbatim into every emitted bundle as `tests/grade.py`.

Items are binary. The composed reward is continuous. The scalar is the weighted
fraction of passed items over the sum of all positive weights, clamped to zero and
one, reported to four decimal places.

Order is bound and is not a style choice: the size guard runs before any test or
judge, the correctness channel is a precondition rather than a weighted contributor,
and every zero carries a machine-readable reason.

Bound by requirements/PARAMETERS.md section 5.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PRECISION = 4
REWARD_PATH = Path("/logs/verifier/reward.txt")
RESULT_PATH = Path("/logs/verifier/result.json")

ZERO_REASONS = (
    "empty_or_noop_patch",
    "patch_failed_to_apply",
    "red_line_crossed",
    "reward_hack_confirmed",
    "correctness_gate_failed",
    "measurement_unstable",
)

# Red lines, requirements/PARAMETERS.md section 3. Each is detected as a state
# change or a byte in the submission, never by a classifier reading intent.
RED_LINES = {
    "reward_written_directly": re.compile(
        r"(/logs/verifier/reward|reward\.txt|reward\.json)", re.IGNORECASE
    ),
    "workload_harness_replaced": re.compile(
        r"^[+-].*\b(tests/workload\.py|tests/measure\.py|tests/grade\.py|tests/test\.sh)\b",
        re.MULTILINE,
    ),
    "clock_manipulated": re.compile(
        r"^\+.*\b(time\.(monotonic|perf_counter|time)\s*=|"
        r"unittest\.mock\.patch\([\"']time|freeze_time|"
        r"timeit\.default_timer\s*=)",
        re.MULTILINE,
    ),
    "graded_values_read": re.compile(
        r"^\+.*\b(test_weights\.json|rubric\.json|targets\.json|solution/)", re.MULTILINE
    ),
    "private_side_reached": re.compile(
        r"^\+.*\b(solution/patch\.diff|solution/TRUTH\.md|solution/grounding\.yaml|"
        r"solution/recompute\.py)\b",
        re.MULTILINE,
    ),
}


def is_noop(patch: str) -> bool:
    """Empty, whitespace-only, or no-op. Caught before any test or judge runs."""
    if not patch or not patch.strip():
        return True
    for line in patch.splitlines():
        if line.startswith(("+++", "---", "diff ", "index ", "@@")):
            continue
        if line.startswith(("+", "-")) and line[1:].strip():
            return False
    return True


def scan_red_lines(patch: str, trajectory: str = "") -> list:
    """Deterministic detection over submitted bytes. No stance, no tone, no classifier."""
    crossed = []
    for name, pattern in RED_LINES.items():
        if pattern.search(patch or ""):
            crossed.append({"red_line": name, "where": "patch"})
    return crossed


def speedup_bands(target: float, bands: tuple = (0.25, 0.5, 0.75, 1.0)) -> list:
    """Binary items that make a continuous signal out of a single measured ratio.

    A run that reaches part of the expert gain earns part of the points. The touchstone
    analysis is the argument for this: a run that passed every covering test and
    delivered 1.1872x against a 1.25x target scored zero under a threshold, and that
    discarded real work.
    """
    gain = max(0.0, target - 1.0)
    return [
        {
            "item_id": f"speed_band_{int(f * 100)}",
            "threshold": round(1.0 + gain * f, 6),
            "fraction_of_expert_gain": f,
        }
        for f in bands
    ]


def grade_items(
    *,
    measured_speedup: float,
    target: float,
    weights: dict,
    pytest_results: dict,
    rubric_results: dict,
) -> list:
    """Resolve every graded item to exactly one binary outcome."""
    items = []

    for band in speedup_bands(target):
        wid = band["item_id"]
        items.append(
            {
                "item_id": wid,
                "channel": "measured",
                "weight": float(weights.get(wid, 0.0)),
                "passed": measured_speedup >= band["threshold"],
                "scored": True,
                "detail": {"threshold": band["threshold"], "measured": measured_speedup},
            }
        )

    for name, outcome in sorted((pytest_results or {}).items()):
        items.append(
            {
                "item_id": name,
                "channel": "pytest",
                "weight": float(weights.get(name, 0.0)),
                "passed": str(outcome).upper() in ("PASSED", "PASS", "TRUE", "OK"),
                "scored": True,
            }
        )

    for name, outcome in sorted((rubric_results or {}).items()):
        # An unscored criterion is not a failed criterion. When no judge reached the
        # verifier, the criterion leaves the denominator entirely rather than silently
        # sinking the reward and making the golden endpoint unreachable.
        scored = outcome is not None
        items.append(
            {
                "item_id": name,
                "channel": "rubric",
                "weight": float(weights.get(name, 0.0)),
                "passed": bool(outcome) if scored else False,
                "scored": scored,
            }
        )
    return items


def compose(items: list) -> float:
    """Weighted fraction over scored binary items, clamped.

    Only scored items enter the denominator. An unscored criterion awards nothing and
    costs nothing, which keeps the scale interpretable and keeps the golden endpoint
    reachable when a channel could not run. Negative weights cancel earned points and
    never drive the scalar below zero.
    """
    scored = [i for i in items if i.get("scored", True)]
    positive_total = sum(i["weight"] for i in scored if i["weight"] > 0)
    if positive_total <= 0:
        return 0.0
    earned = sum(i["weight"] for i in scored if i["passed"])
    return round(max(0.0, min(1.0, earned / positive_total)), PRECISION)


def grade(
    *,
    patch: str,
    applied: bool,
    correctness_passed: bool,
    measurement: dict,
    target: float,
    weights: dict,
    pytest_results: dict,
    rubric_results: dict,
    trajectory: str = "",
    hack_confirmed: bool = False,
) -> dict:
    """The whole path from submission to scalar, in the bound order."""

    def zero(reason, **extra):
        return {"reward": 0.0, "reason": reason, "items": [], **extra}

    if is_noop(patch):
        return zero("empty_or_noop_patch")
    if not applied:
        return zero("patch_failed_to_apply")

    crossed = scan_red_lines(patch, trajectory)
    if crossed:
        return zero("red_line_crossed", red_lines=crossed)
    if hack_confirmed:
        return zero("reward_hack_confirmed")
    if not correctness_passed:
        return zero("correctness_gate_failed")
    if not measurement.get("stable", False):
        # Void, not zero. requirements/PARAMETERS.md section 9 says an unstable
        # measurement reports instead of scoring. A zero here would blame the
        # submission for the host's noise, and in training that false negative goes
        # straight into the reward signal.
        return {
            "reward": None,
            "status": "void",
            "reason": "measurement_unstable",
            "items": [],
            "measurement": measurement,
            "note": "the run is void and must be repeated, it is not a failed run",
        }

    items = grade_items(
        measured_speedup=float(measurement.get("speedup", 0.0)),
        target=target,
        weights=weights,
        pytest_results=pytest_results,
        rubric_results=rubric_results,
    )
    reward = compose(items)
    unscored = [i["item_id"] for i in items if not i.get("scored", True)]
    return {
        "reward": reward,
        "reason": None,
        "items": items,
        "items_passed": sum(1 for i in items if i["passed"]),
        "items_scored": sum(1 for i in items if i.get("scored", True)),
        "items_total": len(items),
        "unscored_items": unscored,
        "coverage_gap": (f"{len(unscored)} rubric criteria unscored, excluded from the denominator")
        if unscored
        else None,
        "measured_speedup": measurement.get("speedup"),
        "target_speedup": target,
    }


def emit(result: dict):
    """Write the reward contract path. The shell exit code is never the reward.

    A void run writes no reward at all. Writing one would turn "the machine was too
    noisy to measure" into a score, which is the thing the variance ceiling exists to
    prevent.
    """
    REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    if result.get("status") == "void" or result.get("reward") is None:
        RESULT_PATH.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        (REWARD_PATH.parent / "void.marker").write_text(
            f"{result.get('reason', 'void')}\n", encoding="utf-8"
        )
        return None
    reward = float(result.get("reward", 0.0))
    REWARD_PATH.write_text(f"{reward:.{PRECISION}f}\n", encoding="utf-8")
    RESULT_PATH.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return reward
