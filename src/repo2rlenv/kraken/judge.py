"""Phase B of grading: the rubric channel, run outside the hermetic container.

The graded container has no network, so it writes the deterministic reward from the
measured and pytest channels and leaves every rubric criterion unscored. This pass
reads what that run recorded, scores the criteria with the judge council, and
recomposes the final reward.

Discipline, bound by requirements/PARAMETERS.md section 10:

  - three judges of the Claude family, per-criterion majority vote
  - every criterion binary
  - every verdict cites the workspace or trajectory bytes it rests on, and a verdict
    whose citation does not appear in the evidence does not count
  - position randomization, so a judge that simply prefers the first option is caught
  - inter-rater agreement reported per task, chance-corrected as well as raw, because
    raw agreement overstates reliability (arXiv 2606.19544)

A criterion with fewer than two valid cited verdicts stays unscored. An unscored
criterion leaves the denominator: it awards nothing and costs nothing.

Usage:
    uv run --project seed python scripts/judge_pass.py --bundle <dir> --logs <dir>
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from itertools import combinations
from pathlib import Path

from repo2rlenv.kraken import find_root

ROOT = find_root()
PROXY = "http://localhost:8765/v1/messages"
JUDGES = ("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5")
MAX_EVIDENCE = 12000

PROMPT = """You are grading one binary criterion for a performance-optimization task.

CRITERION
{description}

EVIDENCE ({evidence_kind}), verbatim. This is the only thing you may reason from:
<evidence>
{evidence}
</evidence>

Answer with a single JSON object and nothing else:
{{"verdict": "{first}" | "{second}", "citation": "<a short exact substring copied from the evidence that justifies the verdict>"}}

Rules:
- "award" means the criterion is satisfied. "withhold" means it is not.
- The citation must be an exact substring of the evidence above. If you cannot cite
  the evidence, answer "withhold" with an empty citation.
- Do not explain. Return only the JSON object.
"""


def call_judge(model: str, prompt: str, timeout: int = 120) -> str | None:
    body = json.dumps({
        "model": model,
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        PROXY, data=body,
        headers={"content-type": "application/json", "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    parts = payload.get("content") or []
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text") or None


def parse_verdict(text: str | None, evidence: str) -> dict | None:
    """Accept a verdict only when its citation is really in the evidence."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        doc = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    verdict = str(doc.get("verdict", "")).strip().lower()
    if verdict not in ("award", "withhold"):
        return None
    citation = str(doc.get("citation") or "").strip()
    cited = bool(citation) and _citation_grounded(citation, evidence)
    if verdict == "award" and not cited:
        # An award with no verifiable citation does not count. A withhold needs no
        # citation, because it asserts an absence rather than a fact in the bytes.
        return {"verdict": None, "citation": citation, "cited": False,
                "reason": "award_without_verifiable_citation"}
    return {"verdict": verdict, "citation": citation, "cited": cited}


def _normalize_for_citation(text: str) -> str:
    r"""Collapse the differences a judge cannot be expected to reproduce byte for byte.

    The trajectory is handed over as raw JSON, so a newline inside a captured command is
    the two characters `\n` rather than a line break. A judge quoting two lines of test
    output writes a real newline, and a literal substring test then rejects a citation
    that is genuinely present in the evidence. That failure is indistinguishable from a
    fabricated citation and silently drops honest verdicts: it discarded all three judges
    on one criterion in this run.

    Unescape the JSON forms and flatten runs of whitespace, so grounding still means the
    words are really there while formatting stops deciding the vote.
    """
    for escaped, plain in (("\\r\\n", " "), ("\\n", " "), ("\\t", " "), ("\\\"", '"')):
        text = text.replace(escaped, plain)
    return " ".join(text.split())


def _citation_grounded(citation: str, evidence: str) -> bool:
    """A citation counts when it appears verbatim, or once formatting is normalized."""
    if citation in evidence:
        return True
    return _normalize_for_citation(citation) in _normalize_for_citation(evidence)


def agreement(votes: list) -> dict:
    """Raw pairwise agreement and a chance-corrected companion."""
    usable = [v for v in votes if v is not None]
    if len(usable) < 2:
        return {"pairs": 0, "raw": None, "chance_corrected": None}
    pairs = list(combinations(usable, 2))
    raw = sum(1 for a, b in pairs if a == b) / len(pairs)
    p_award = sum(1 for v in usable if v == "award") / len(usable)
    chance = p_award ** 2 + (1 - p_award) ** 2
    kappa = (raw - chance) / (1 - chance) if chance < 1 else None
    return {"pairs": len(pairs), "raw": round(raw, 4),
            "chance_corrected": None if kappa is None else round(kappa, 4)}


def evidence_window(evidence: str, budget: int = MAX_EVIDENCE) -> str:
    """Keep both ends of the evidence rather than only its opening.

    A head-only clip is not a neutral truncation. Localization and planning happen at
    the start of a trajectory, but running the covering tests and re-measuring happen
    at the end, so clipping the tail makes every criterion about verification
    unanswerable no matter what the agent did. It also inverts the incentive: the more
    thoroughly an agent works, the further its proof is pushed past the window, while
    an agent that immediately declares success fits inside it whole. Keep the head and
    the tail, and mark the elision so a judge can see that something was dropped.
    """
    if len(evidence) <= budget:
        return evidence
    # The marker is part of what the judge reads, so it comes out of the budget rather
    # than being added on top of it. Otherwise the window quietly exceeds the ceiling it
    # is supposed to enforce.
    marker = "\n\n... [{n} characters elided from the middle of this evidence] ...\n\n"
    room = max(0, budget - len(marker.format(n=len(evidence))))
    head = room // 2
    tail = room - head
    elided = len(evidence) - head - tail
    return evidence[:head] + marker.format(n=elided) + evidence[-tail:]


def score_criterion(crit: dict, evidence: str, rng: random.Random) -> dict:
    kind = crit.get("check", "final_answer")
    if not evidence.strip():
        return {"id": crit["id"], "result": None, "reason": f"no_{kind}_evidence_recorded",
                "votes": []}

    shown = evidence_window(evidence)
    votes, detail = [], []
    for model in JUDGES:
        # Position randomization: the two options are presented in a random order per
        # judge, so a judge that simply prefers whatever comes first is visible.
        first, second = ("award", "withhold") if rng.random() < 0.5 else ("withhold", "award")
        prompt = PROMPT.format(description=crit["description"], evidence_kind=kind,
                               evidence=shown, first=first, second=second)
        # Verify the citation against what the judge was actually shown, not against the
        # full evidence. Checking the full text would accept a citation drawn from the
        # elided middle, which the judge could not have read and therefore did not cite.
        parsed = parse_verdict(call_judge(model, prompt), shown)
        detail.append({"judge": model, "order": [first, second],
                       **(parsed or {"verdict": None, "reason": "unparsable_or_unreachable"})})
        votes.append((parsed or {}).get("verdict"))

    usable = [v for v in votes if v in ("award", "withhold")]
    if len(usable) < 2:
        return {"id": crit["id"], "result": None, "reason": "fewer_than_two_valid_verdicts",
                "votes": detail, "agreement": agreement(votes)}
    awards = sum(1 for v in usable if v == "award")
    return {"id": crit["id"], "result": awards * 2 > len(usable), "votes": detail,
            "agreement": agreement(votes)}


def run(*, bundle: Path, logs: Path, seed: int = 17) -> int:
    """Importable entry. `kraken grade` calls this rather than re-entering argparse."""
    import sys as _sys
    argv = _sys.argv
    _sys.argv = ["kraken-judge", "--bundle", str(bundle), "--logs", str(logs),
                 "--seed", str(seed)]
    try:
        return main()
    finally:
        _sys.argv = argv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--logs", required=True)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    bundle, logs = Path(args.bundle), Path(args.logs)
    rubric = json.loads((bundle / "tests" / "rubric.json").read_text())
    weights = json.loads((bundle / "tests" / "test_weights.json").read_text())
    targets = json.loads((bundle / "tests" / "targets.json").read_text())
    verifier = logs / "verifier"
    result = json.loads((verifier / "result.json").read_text())

    if result.get("reason"):
        print(f"run capped at 0.0 by {result['reason']}; the rubric channel is not consulted")
        return 0

    patch = (verifier / "agent_patch.diff").read_text() if (verifier / "agent_patch.diff").exists() else ""
    trajectory = ""
    for candidate in ("trajectory.json", "trajectory.txt", "agent/trajectory.json"):
        p = logs / candidate
        if p.exists():
            trajectory = p.read_text(errors="replace")
            break

    rng = random.Random(args.seed)
    scored = []
    for crit in rubric["criteria"]:
        evidence = patch if crit.get("check") == "final_answer" else trajectory
        scored.append(score_criterion(crit, evidence, rng))

    rubric_results = {row["id"]: row["result"] for row in scored}
    unscored = [row["id"] for row in scored if row["result"] is None]

    sys.path.insert(0, str(bundle / "tests"))
    import grade as G  # noqa: E402

    recomposed = G.grade(
        patch=patch, applied=True, correctness_passed=True,
        measurement={"speedup": result.get("measured_speedup"), "stable": True},
        target=targets["target_speedup"], weights=weights,
        pytest_results={i["item_id"]: ("PASSED" if i["passed"] else "FAILED")
                        for i in result.get("items", []) if i.get("channel") == "pytest"},
        rubric_results=rubric_results)

    agreements = [row["agreement"]["raw"] for row in scored
                  if row.get("agreement", {}).get("raw") is not None]
    corrected = [row["agreement"]["chance_corrected"] for row in scored
                 if row.get("agreement", {}).get("chance_corrected") is not None]
    report = {
        "judges": list(JUDGES),
        "aggregation": "per-criterion majority vote over valid cited verdicts",
        "criteria_total": len(scored),
        "criteria_scored": len(scored) - len(unscored),
        "unscored": unscored,
        "inter_rater_agreement": {
            "raw_mean": round(sum(agreements) / len(agreements), 4) if agreements else None,
            "chance_corrected_mean": round(sum(corrected) / len(corrected), 4) if corrected else None,
            "note": "Raw agreement overstates reliability. The chance-corrected figure is the "
                    "one to read (arXiv 2606.19544).",
        },
        "criteria": scored,
        "reward_before_rubric": result.get("reward"),
        "reward_after_rubric": recomposed["reward"],
    }
    (verifier / "rubric_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (verifier / "reward.txt").write_text(f"{recomposed['reward']:.4f}\n", encoding="utf-8")
    recomposed["rubric_phase"] = "two_phase_judge_pass"
    (verifier / "result.json").write_text(json.dumps(recomposed, indent=2, default=str),
                                          encoding="utf-8")

    print(f"criteria {report['criteria_scored']}/{report['criteria_total']} scored, "
          f"unscored {len(unscored)}")
    print(f"agreement raw {report['inter_rater_agreement']['raw_mean']} "
          f"chance-corrected {report['inter_rater_agreement']['chance_corrected_mean']}")
    print(f"reward {report['reward_before_rubric']} -> {report['reward_after_rubric']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
