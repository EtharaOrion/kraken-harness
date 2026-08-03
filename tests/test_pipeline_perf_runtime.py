"""perf_runtime: the deterministic half, provable without Docker.

Every check here proves both halves of its decision: it accepts a well-formed input
and rejects a planted defect. A test that only ever proves the clean half cannot tell
a working instrument from an inert one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from repo2rlenv.pipelines import PIPELINES
from repo2rlenv.pipelines._perf_runtime_measure import parse_timing
from repo2rlenv.pipelines.perf_runtime import PerfRuntimePipeline, diff_problems
from repo2rlenv.spec.options import OPTIONS_REGISTRY, PerfRuntimeOptions

ASSETS = Path(__file__).parents[1] / "src" / "repo2rlenv" / "pipelines"

WELL_FORMED = """\
diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,3 +1,3 @@
 a
-b
+c
 d
"""

TRUNCATED = """\
diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,8 +1,8 @@
 a
-b
+c
"""


# --- registration -------------------------------------------------------------


def test_pipeline_is_registered():
    assert PIPELINES["perf_runtime"] is PerfRuntimePipeline
    assert OPTIONS_REGISTRY["perf_runtime"] is PerfRuntimeOptions


def test_declares_no_bootstrap():
    """The corpus carries the environment spec, so no LLM builds the image."""
    assert PerfRuntimePipeline.requires_bootstrap is False


# --- diff validation ----------------------------------------------------------


def test_well_formed_patch_accepted():
    assert diff_problems(WELL_FORMED) == []


def test_trailing_blank_lines_are_not_hunk_content():
    """A trailing newline must not be counted as a context line."""
    assert diff_problems(WELL_FORMED + "\n\n") == []


def test_truncated_patch_rejected():
    problems = diff_problems(TRUNCATED)
    assert problems, "a hunk shorter than its header must not pass"
    # The body carries one context line and one removed line, so it accounts for two
    # of the eight old lines the header declares.
    assert problems[0]["declared_old"] == 8
    assert problems[0]["counted_old"] == 2


def test_empty_patch_rejected():
    assert diff_problems("")[0]["reason"] == "empty_patch"


# --- timing parser ------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("Mean: 0.026431\nStd Dev: 0.000812", 0.026431),  # the corpus convention
        ('{"elapsed": 1.5}', 1.5),
        ("Median: 2.25\nStd Dev: 9.9", 2.25),
        ("ran\n0.9931", 0.9931),
    ],
)
def test_parse_timing_reads_the_value_not_the_noise(stdout, expected):
    assert parse_timing(stdout) == expected


def test_parse_timing_refuses_to_guess():
    with pytest.raises(RuntimeError):
        parse_timing("no numbers here")


# --- reward composition -------------------------------------------------------


@pytest.fixture()
def grade_module():
    sys.path.insert(0, str(ASSETS))
    import importlib

    module = importlib.import_module("_perf_runtime_grade")
    yield module
    sys.path.remove(str(ASSETS))


def _weights():
    return {
        "speed_band_25": 6.0,
        "speed_band_50": 8.0,
        "speed_band_75": 10.0,
        "speed_band_100": 14.0,
        "test_behaviour_1": 5.0,
        "rub_ok": 2.0,
        "rub_pen": -6.0,
    }


def _grade(
    G, speedup, *, target=2.0, correctness=True, patch="+ real\n", stable=True, rubric=None, **kw
):
    return G.grade(
        patch=patch,
        applied=True,
        correctness_passed=correctness,
        measurement={"speedup": speedup, "stable": stable},
        target=target,
        weights=_weights(),
        pytest_results={"test_behaviour_1": "PASSED" if correctness else "FAILED"},
        rubric_results=rubric if rubric is not None else {},
        **kw,
    )


def test_golden_endpoint_is_exactly_one(grade_module):
    assert _grade(grade_module, 2.0)["reward"] == 1.0


def test_empty_endpoint_is_exactly_zero(grade_module):
    result = grade_module.grade(
        patch="",
        applied=True,
        correctness_passed=True,
        measurement={"speedup": 2.0, "stable": True},
        target=2.0,
        weights=_weights(),
        pytest_results={},
        rubric_results={},
    )
    assert result["reward"] == 0.0
    assert result["reason"] == "empty_or_noop_patch"


def test_partial_progress_lands_strictly_between(grade_module):
    reward = _grade(grade_module, 1.5)["reward"]
    assert 0.0 < reward < 1.0


def test_more_speedup_never_scores_less(grade_module):
    rewards = [_grade(grade_module, s)["reward"] for s in (1.0, 1.25, 1.5, 1.75, 2.0)]
    assert rewards == sorted(rewards)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"correctness": False}, "correctness_gate_failed"),
        ({"patch": "+ open('/logs/verifier/reward.txt','w')\n"}, "red_line_crossed"),
        ({"patch": "+ import freeze_time\n"}, "red_line_crossed"),
    ],
)
def test_zero_overrides_fire_with_a_machine_readable_reason(grade_module, kwargs, reason):
    result = _grade(grade_module, 2.0, **kwargs)
    assert result["reward"] == 0.0
    assert result["reason"] == reason


def test_unstable_measurement_is_void_not_zero(grade_module):
    """An unstable measurement is a fact about the host, never a score.

    requirements/PARAMETERS.md section 9 says it reports instead of scoring. Scoring it
    zero would blame the submission for the machine's noise, and would feed a false
    negative into the training signal.
    """
    result = _grade(grade_module, 2.0, stable=False)
    assert result["reward"] is None
    assert result["status"] == "void"
    assert result["reason"] == "measurement_unstable"


def test_void_run_writes_no_reward(grade_module, tmp_path, monkeypatch):
    """A void run must not leave a number behind for a runner to read as a score."""
    monkeypatch.setattr(grade_module, "REWARD_PATH", tmp_path / "verifier" / "reward.txt")
    monkeypatch.setattr(grade_module, "RESULT_PATH", tmp_path / "verifier" / "result.json")
    out = grade_module.emit(_grade(grade_module, 2.0, stable=False))
    assert out is None
    assert not (tmp_path / "verifier" / "reward.txt").exists()
    assert (tmp_path / "verifier" / "void.marker").exists()


def test_unscored_rubric_is_excluded_rather_than_failed(grade_module):
    """An unscored criterion must not sink the reward or block the golden endpoint."""
    scored = _grade(grade_module, 2.0, rubric={"rub_ok": True})
    unscored = _grade(grade_module, 2.0, rubric={"rub_ok": None})
    assert scored["reward"] == 1.0
    assert unscored["reward"] == 1.0
    assert unscored["unscored_items"] == ["rub_ok"]


def test_penalty_criterion_cancels_earned_points(grade_module):
    clean = _grade(grade_module, 2.0, rubric={"rub_ok": True, "rub_pen": False})
    tripped = _grade(grade_module, 2.0, rubric={"rub_ok": True, "rub_pen": True})
    assert clean["reward"] == 1.0
    assert tripped["reward"] < clean["reward"]


def test_reward_never_falls_below_zero(grade_module):
    result = grade_module.grade(
        patch="+ x\n",
        applied=True,
        correctness_passed=True,
        measurement={"speedup": 1.0, "stable": True},
        target=2.0,
        weights={"rub_pen": -100.0, "speed_band_25": 1.0},
        pytest_results={},
        rubric_results={"rub_pen": True},
    )
    assert result["reward"] == 0.0


def test_grading_is_deterministic(grade_module):
    rewards = {_grade(grade_module, 1.6)["reward"] for _ in range(5)}
    assert len(rewards) == 1


# --- recompute determinism ----------------------------------------------------


def test_recompute_regenerates_byte_identically(tmp_path):
    """The generated truth, fixtures, weights, and oracle must not drift on re-run."""
    bundle = tmp_path / "b"
    (bundle / "solution").mkdir(parents=True)
    (bundle / "tests").mkdir()
    grounding = {
        "instance_id": "demo-1",
        "repo": "demo/repo",
        "base_commit": "abc123",
        "repo_path": "/testbed",
        "workload_path": "/tests/workload.py",
        "target_speedup": 1.5,
        "image_ref": "demo@sha256:" + "a" * 64,
        "provenance": {"origin": "derived", "provenance_date": "2025-01-01"},
        "reference": {"files_touched": ["pkg/mod.py"], "symbols": ["hot"], "patch_bytes": 10},
        "correctness": {
            "covering_tests": ["tests/test_a.py"],
            "test_cmd": "pytest tests/test_a.py",
            "behaviour_assertions": ["test_behaviour_1"],
            "log_parser_type": "pytest",
        },
        "rubric_policy": {"judges": ["a", "b", "c"], "aggregation": "per-criterion majority vote"},
        "truth": {
            "steps": [{"action": "a", "state": "s", "checker": "c"}],
            "rejected_routes": [{"route": "r", "why": "w"}],
        },
    }
    (bundle / "solution" / "grounding.yaml").write_text(json.dumps(grounding), encoding="utf-8")
    (bundle / "solution" / "recompute.py").write_text(
        (ASSETS / "_perf_runtime_recompute.py").read_text(encoding="utf-8"), encoding="utf-8"
    )

    def run():
        proc = subprocess.run(
            [sys.executable, str(bundle / "solution" / "recompute.py")],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        return {p.name: p.read_bytes() for p in sorted(bundle.rglob("*")) if p.is_file()}

    first, second = run(), run()
    assert first == second

    rubric = json.loads((bundle / "tests" / "rubric.json").read_text())
    assert 15 <= len(rubric["criteria"]) <= 25, "PARAMETERS section 10 bounds the criterion count"
    assert all(c["binary"] for c in rubric["criteria"])
    assert {c["check"] for c in rubric["criteria"]} <= {"final_answer", "trajectory"}
    truth = (bundle / "solution" / "TRUTH.md").read_text()
    assert "GENERATED SECTION. DO NOT HAND-EDIT." in truth
