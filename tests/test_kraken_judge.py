"""Tests for the rubric judge and the corpus validator.

These functions decide reward. A citation that verifies when it should not, or an
evidence window that hides the half of a trajectory a criterion asks about, changes
the score without changing anything visible in the run.
"""

from __future__ import annotations

import json
import random
import sys

import pytest

from repo2rlenv.kraken import judge as J
from repo2rlenv.kraken import validate as V

# --- verdict parsing ---------------------------------------------------------


def test_an_award_needs_a_citation_that_is_really_in_the_evidence():
    ev = "the agent ran pytest and it passed"
    got = J.parse_verdict('{"verdict":"award","citation":"ran pytest"}', ev)
    assert got["verdict"] == "award" and got["cited"] is True


def test_an_award_whose_citation_is_absent_does_not_count():
    got = J.parse_verdict('{"verdict":"award","citation":"never happened"}', "some evidence")
    assert got["verdict"] is None
    assert got["reason"] == "award_without_verifiable_citation"


def test_a_withhold_needs_no_citation_because_it_asserts_an_absence():
    got = J.parse_verdict('{"verdict":"withhold","citation":""}', "evidence")
    assert got["verdict"] == "withhold"


def test_an_unparsable_reply_is_not_a_verdict():
    assert J.parse_verdict("I think it probably passed", "evidence") is None
    assert J.parse_verdict(None, "evidence") is None
    assert J.parse_verdict('{"verdict":"maybe"}', "evidence") is None


def test_a_verdict_is_found_even_when_the_model_wraps_it_in_prose():
    got = J.parse_verdict('Sure! {"verdict":"withhold","citation":""} hope that helps', "evidence")
    assert got["verdict"] == "withhold"


# --- citation grounding ------------------------------------------------------


def test_a_citation_spanning_lines_survives_json_escaping():
    """The trajectory is raw JSON, so its newlines are the two characters \\n.

    A judge quoting two lines writes a real newline. Rejecting that would discard an
    honest verdict for a formatting difference it cannot control.
    """
    evidence = "Mean: 0.0032\\nStd Dev: 0.0001"
    assert J._citation_grounded("Mean: 0.0032\nStd Dev: 0.0001", evidence)


def test_normalisation_does_not_admit_a_fabricated_citation():
    assert not J._citation_grounded("the agent deleted the test suite", "unrelated evidence")


def test_a_verbatim_citation_still_matches():
    assert J._citation_grounded("616 passed", "output: 616 passed, 28 skipped")


# --- evidence window ---------------------------------------------------------


def test_short_evidence_passes_through_untouched():
    assert J.evidence_window("short", budget=100) == "short"


def test_evidence_at_exactly_the_budget_is_untouched():
    text = "x" * 100
    assert J.evidence_window(text, budget=100) == text


def test_the_window_keeps_both_ends_not_just_the_opening():
    """Localisation happens early in a trajectory; running the tests happens late.

    A head-only clip makes every criterion about verification unanswerable no matter
    what the agent did.
    """
    text = "HEAD" + ("m" * 5000) + "TAIL"
    out = J.evidence_window(text, budget=400)
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")


def test_the_window_respects_its_budget_including_the_marker():
    text = "y" * 9000
    out = J.evidence_window(text, budget=500)
    assert len(out) <= 500


def test_the_window_says_that_something_was_dropped():
    out = J.evidence_window("z" * 9000, budget=500)
    assert "elided" in out


# --- inter-rater agreement ---------------------------------------------------


def test_agreement_needs_at_least_two_usable_votes():
    assert J.agreement([None, None])["pairs"] == 0
    assert J.agreement(["award"])["raw"] is None


def test_unanimous_judges_agree_completely():
    got = J.agreement(["award", "award", "award"])
    assert got["raw"] == 1.0 and got["pairs"] == 3


def test_a_split_panel_reports_partial_agreement():
    got = J.agreement(["award", "withhold"])
    assert got["raw"] == 0.0 and got["pairs"] == 1


def test_unusable_votes_are_excluded_rather_than_counted():
    assert J.agreement(["award", "award", None])["pairs"] == 1


# --- criterion scoring -------------------------------------------------------


def test_a_criterion_with_no_evidence_is_unscored_not_failed():
    got = J.score_criterion(
        {"id": "c", "description": "d", "check": "trajectory"}, "   ", random.Random(0)
    )
    assert got["result"] is None
    assert "no_trajectory_evidence_recorded" in got["reason"]


def test_fewer_than_two_valid_verdicts_leaves_the_criterion_unscored(monkeypatch):
    monkeypatch.setattr(J, "call_judge", lambda *a, **k: None)
    got = J.score_criterion({"id": "c", "description": "d"}, "evidence", random.Random(0))
    assert got["result"] is None
    assert got["reason"] == "fewer_than_two_valid_verdicts"


def test_a_majority_of_awards_carries_the_criterion(monkeypatch):
    monkeypatch.setattr(
        J, "call_judge", lambda *a, **k: '{"verdict":"award","citation":"evidence"}'
    )
    got = J.score_criterion({"id": "c", "description": "d"}, "evidence", random.Random(0))
    assert got["result"] is True


def test_a_majority_of_withholds_denies_it(monkeypatch):
    monkeypatch.setattr(J, "call_judge", lambda *a, **k: '{"verdict":"withhold"}')
    got = J.score_criterion({"id": "c", "description": "d"}, "evidence", random.Random(0))
    assert got["result"] is False


# --- corpus validation -------------------------------------------------------


def test_a_well_formed_hunk_reports_no_problem():
    patch = (
        "diff --git a/m.py b/m.py\n"
        "--- a/m.py\n"
        "+++ b/m.py\n"
        "@@ -1,3 +1,3 @@\n"
        " keep\n"
        "-old\n"
        "+new\n"
        " keep\n"
    )
    assert V.check_patch(patch) == []


def test_a_header_that_overcounts_its_body_is_caught():
    """git computes the header from the body, so a mismatch means the patch was cut."""
    patch = (
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1,48 +1,38 @@\n keep\n-old\n+new\n"
    )
    problems = V.check_patch(patch)
    assert problems
    assert problems[0]["declared_old"] == 48
    assert problems[0]["counted_old"] != 48


def test_an_empty_patch_is_itself_a_defect():
    """A record whose reference patch is empty cannot produce an oracle."""
    assert V.check_patch("") == [{"reason": "empty_patch"}]


# --- the grade stage end to end ----------------------------------------------


def _bundle(tmp_path, criteria):
    """A bundle holding just the four files the grade stage reads."""
    tests = tmp_path / "bundle" / "tests"
    tests.mkdir(parents=True)
    (tests / "rubric.json").write_text(json.dumps({"criteria": criteria}))
    (tests / "test_weights.json").write_text(json.dumps({"rubric_quality": 1.0}))
    (tests / "targets.json").write_text(json.dumps({"target_speedup": 5.0}))
    # The bundle ships its own reward composition; the judge imports whatever is there
    # rather than reimplementing it, so the two cannot drift apart.
    (tests / "grade.py").write_text(
        "def grade(**kw):\n"
        "    scored = [v for v in kw['rubric_results'].values() if v is not None]\n"
        "    return {'reward': sum(1 for v in scored if v) / len(scored) if scored else 0.0,\n"
        "            'rubric_results': kw['rubric_results']}\n"
    )
    return tmp_path / "bundle"


def _logs(tmp_path, result, trajectory="the agent ran pytest and 616 passed"):
    verifier = tmp_path / "run" / "verifier"
    verifier.mkdir(parents=True)
    (verifier / "result.json").write_text(json.dumps(result))
    (verifier / "agent_patch.diff").write_text("diff --git a/m.py b/m.py\n+fast\n")
    (tmp_path / "run" / "trajectory.json").write_text(trajectory)
    return tmp_path / "run"


@pytest.fixture(autouse=True)
def _forget_bundle_grade_module():
    """Each bundle ships its own grade.py, imported by path injection."""
    yield
    sys.modules.pop("grade", None)


def test_grade_scores_the_rubric_and_rewrites_the_reward(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, [{"id": "verified", "description": "d", "check": "trajectory"}])
    logs = _logs(tmp_path, {"reward": 0.5, "measured_speedup": 6.0, "items": []})
    monkeypatch.setattr(
        J, "call_judge", lambda *a, **k: '{"verdict":"award","citation":"616 passed"}'
    )

    assert J.run(bundle=bundle, logs=logs) == 0

    report = json.loads((logs / "verifier" / "rubric_results.json").read_text())
    assert report["criteria_total"] == 1
    assert report["criteria_scored"] == 1
    assert report["unscored"] == []
    assert report["reward_before_rubric"] == 0.5
    assert report["reward_after_rubric"] == 1.0
    assert report["judges"] == list(J.JUDGES)


def test_grade_writes_the_recomposed_reward_back_for_the_runtime(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, [{"id": "c", "description": "d", "check": "trajectory"}])
    logs = _logs(tmp_path, {"reward": 0.0, "measured_speedup": 6.0, "items": []})
    monkeypatch.setattr(J, "call_judge", lambda *a, **k: '{"verdict":"withhold"}')

    J.run(bundle=bundle, logs=logs)

    assert (logs / "verifier" / "reward.txt").read_text().strip() == "0.0000"
    result = json.loads((logs / "verifier" / "result.json").read_text())
    assert result["rubric_phase"] == "two_phase_judge_pass"
    assert result["reward"] == 0.0


def test_a_capped_run_is_not_sent_to_the_judges(tmp_path, monkeypatch):
    """A void or unapplied run is already 0.0. Paying three judges cannot change it."""
    bundle = _bundle(tmp_path, [{"id": "c", "description": "d"}])
    logs = _logs(tmp_path, {"reward": 0.0, "reason": "patch_did_not_apply"})

    def refuse(*a, **k):
        raise AssertionError("judges were consulted for a capped run")

    monkeypatch.setattr(J, "call_judge", refuse)
    assert J.run(bundle=bundle, logs=logs) == 0
    assert not (logs / "verifier" / "rubric_results.json").exists()


def test_an_unreachable_judge_leaves_the_criterion_unscored_not_failed(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, [{"id": "c", "description": "d", "check": "trajectory"}])
    logs = _logs(tmp_path, {"reward": 0.3, "measured_speedup": 6.0, "items": []})
    monkeypatch.setattr(J, "call_judge", lambda *a, **k: None)

    J.run(bundle=bundle, logs=logs)

    report = json.loads((logs / "verifier" / "rubric_results.json").read_text())
    assert report["unscored"] == ["c"]
    assert report["criteria_scored"] == 0


def test_run_restores_argv_so_the_caller_is_not_disturbed(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path, [{"id": "c", "description": "d"}])
    logs = _logs(tmp_path, {"reward": 0.0, "reason": "capped"})
    before = list(sys.argv)
    J.run(bundle=bundle, logs=logs)
    assert sys.argv == before


# --- the corpus validation report --------------------------------------------


def test_validate_main_reports_every_malformed_patch(tmp_path, monkeypatch, capsys):
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "PARAMETERS.md").write_text("#\n")
    for d in ("seed", "memory", "audit"):
        (tmp_path / d).mkdir()
    monkeypatch.setenv("KRAKEN_ROOT", str(tmp_path))

    good = "@@ -1,2 +1,2 @@\n keep\n-old\n+new\n"
    bad = "@@ -1,9 +1,9 @@\n keep\n"
    (tmp_path / "harvest").mkdir()
    (tmp_path / "harvest" / "o__n.jsonl").write_text(
        json.dumps(
            {
                "instance_id": "o__n-1",
                "repo": "o/n",
                "speedup": 2.0,
                "patch": good,
                "test_patch": good,
            }
        )
        + "\n"
        + "\n"
        + json.dumps({"instance_id": "o__n-2", "repo": "o/n", "speedup": 3.0, "patch": bad})
        + "\n"
    )

    assert V.main() == 0

    report = json.loads((tmp_path / "harvest" / "validation.json").read_text())
    assert report["records"] == 2, "a blank line is not a record"
    assert report["malformed"] == 1
    by_id = {r["instance_id"]: r for r in report["instances"]}
    assert by_id["o__n-1"]["patch_ok"] and by_id["o__n-1"]["test_patch_ok"]
    assert not by_id["o__n-2"]["patch_ok"]
    assert by_id["o__n-2"]["test_patch_ok"], "a record with no test_patch has nothing to fail"
    assert "o__n-2" in capsys.readouterr().out
