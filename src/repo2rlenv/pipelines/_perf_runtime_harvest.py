"""Harvest stage for perf_runtime: mine merged PRs into candidate corpus records.

The rest of the pipeline is corpus-driven and takes `harvest/*.jsonl` as a given
input. That is fine when someone else already produced the corpus, and useless when
they have not: without this stage the dataset can never grow past whatever records
happen to be lying in the tree.

What a scrape can and cannot supply, stated plainly because the difference is what
makes a record admissible:

  Deterministic from GitHub and the checkout
    instance_id, repo, base_commit, patch, problem_statement, created_at, pr_url,
    pull_number, covering_tests, test_cmd, python_version, install_cmd

  Not derivable by scraping
    workload   a timed script exercising the changed path. Synthesized here, and
               synthesized WITHOUT the reference diff in the prompt, so the workload
               cannot describe the fix it is meant to measure.
    speedup    a measurement. Left null. perf_runtime calibrates its own target in
               the graded container and treats any corpus speedup as a cross-check
               rather than as the graded value, so a null here costs nothing.

A record that reaches the emitter incomplete is rejected by REQUIRED_FIELDS with the
field named. That is the intended behaviour: this stage produces candidates, and
admission stays with the measurement gates.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from repo2rlenv.github import PullRequestSummary, fetch_pr_diff, list_merged_prs

log = logging.getLogger(__name__)

# A merged PR is a performance candidate when it says so. Title and body only: the
# diff is deliberately not consulted, because a keyword scan over a diff selects on
# the shape of the fix and biases the corpus toward one kind of optimization.
PERF_CUES = re.compile(
    r"\b(perf|performance|speed ?up|speedup|faster|optimi[sz]e[ds]?|optimi[sz]ation|"
    r"latency|throughput|slow(?:ness)?|bottleneck|hot ?path|O\(n\^?2\)|quadratic|"
    r"vectori[sz]e[d]?|cache[ds]?|memoi[sz]e[ds]?)\b",
    re.I,
)
# Changes that are only about build metadata are never performance tasks even when
# the title says "faster CI".
NOISE_CUES = re.compile(r"\b(ci|workflow|lint|typo|docs?|changelog|bump|pre-commit)\b", re.I)

TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]+\.py$|_test\.py$")


@dataclass
class Candidate:
    """One mined PR, before enrichment."""
    record: dict
    reasons: list[str]          # why it was kept
    missing: list[str]          # fields a scrape cannot fill


def is_perf_candidate(pr: PullRequestSummary) -> tuple[bool, list[str]]:
    """Select on what the author said, not on what the diff looks like."""
    text = f"{pr.title}\n{pr.body or ''}"
    hits = sorted({m.group(0).lower() for m in PERF_CUES.finditer(text)})
    if not hits:
        return False, []
    py = [f for f in pr.changed_files if f.endswith(".py")]
    if not py:
        return False, []
    # Every touched Python file being a test means the PR changed no library path.
    if all(TEST_PATH.search(f) for f in py):
        return False, []
    if NOISE_CUES.search(pr.title) and len(hits) == 1:
        return False, []
    return True, hits


def covering_tests(pr: PullRequestSummary) -> list[str]:
    """Test files the PR itself touched, which is the honest first guess at coverage.

    A PR that changes a hot path and its tests names its own covering set. When it
    names none, the record stays incomplete rather than guessing a path that may not
    exist, because a wrong test_cmd fails the correctness gate for the wrong reason.
    """
    return sorted(f for f in pr.changed_files if f.endswith(".py") and TEST_PATH.search(f))


def detect_env(repo_dir: Path) -> dict:
    """Read the environment spec out of the checkout rather than assuming one."""
    spec: dict = {"python_version": None, "install_cmd": None}
    pyproject = repo_dir / "pyproject.toml"
    setup_py = repo_dir / "setup.py"

    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'requires-python\s*=\s*"[^"]*?(\d+\.\d+)', text)
        if m:
            spec["python_version"] = m.group(1)
        spec["install_cmd"] = "python -m pip install -e ."
    elif setup_py.exists():
        spec["install_cmd"] = "python -m pip install -e ."

    # A floor, not a guess: 3.11 is the oldest interpreter the emitted images ship.
    if not spec["python_version"]:
        spec["python_version"] = "3.11"
    return spec


def clone_at(repo: str, sha: str, dest: Path, *, depth: int = 1) -> Path | None:
    """Shallow-clone one commit. Returns None when the commit is unreachable."""
    dest.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{repo}.git"
    try:
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=dest,
                       check=True, capture_output=True)
        subprocess.run(["git", "fetch", "-q", "--depth", str(depth), "origin", sha],
                       cwd=dest, check=True, capture_output=True, timeout=300)
        subprocess.run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest,
                       check=True, capture_output=True)
        return dest
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("clone failed for %s@%s: %s", repo, sha[:12], exc)
        return None


WORKLOAD_SYSTEM = (
    "You write timed micro-benchmarks. You produce a single self-contained Python "
    "script and nothing else: no prose, no markdown fence, no commentary."
)

WORKLOAD_PROMPT = """Write a timed workload script that exercises this code path.

Repository: {repo}
Module surface under test:
{surface}

Public entry points the workload may call:
{entrypoints}

Requirements, all mandatory:
- Define `setup()` that prepares state, and `workload()` that does the timed work.
- `workload()` must call only public API of the repository. Do not import private
  modules or reach into internals.
- Make it deterministic: fixed seeds, fixed sizes, no wall-clock branching, no network.
- Size it so one `workload()` call takes roughly 1 to 50 milliseconds.
- Use only the standard library plus the repository under test.
- Write NO comments and NO docstrings describing how the code could be made faster.
  Describe only what is being measured.

Output the script only."""


def synthesize_workload(repo: str, surface: str, entrypoints: list[str], spec) -> str | None:
    """Ask a model for a timed workload, with the reference diff withheld.

    The diff is deliberately not in the prompt. A model shown the fix writes a
    workload whose comments explain the fix, and the brief hands that workload to the
    agent verbatim, which turns the task into dictation. Withholding it at the source
    is cheaper and more reliable than scrubbing the prose afterwards.
    """
    from repo2rlenv.llm import complete

    try:
        resp = complete(
            spec,
            system=WORKLOAD_SYSTEM,
            user=WORKLOAD_PROMPT.format(
                repo=repo, surface=surface[:4000],
                entrypoints="\n".join(f"- {e}" for e in entrypoints[:40]) or "- (none detected)"),
            max_tokens=2048,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("workload synthesis failed for %s: %s", repo, exc)
        return None

    body = (resp.content or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n", "", body)
        body = re.sub(r"\n```\s*$", "", body)
    if "def workload" not in body:
        log.warning("workload synthesis for %s produced no workload(), discarding", repo)
        return None
    return body


def _surface(repo_dir: Path, changed: list[str], limit: int = 3) -> tuple[str, list[str]]:
    """Signatures of the non-test Python files the PR touched."""
    parts, entry = [], []
    for rel in [f for f in changed if f.endswith(".py") and not TEST_PATH.search(f)][:limit]:
        p = repo_dir / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        sigs = re.findall(r"^\s*(?:async )?def ([a-zA-Z_]\w*)\(", text, re.M)
        cls = re.findall(r"^class ([A-Z]\w*)", text, re.M)
        entry += [f"{rel}::{s}" for s in sigs if not s.startswith("_")][:12]
        entry += [f"{rel}::{c}" for c in cls][:8]
        parts.append(f"# {rel}\n" + "\n".join(f"class {c}" for c in cls[:8])
                     + "\n" + "\n".join(f"def {s}(...)" for s in sigs[:20]))
    return "\n\n".join(parts), entry


def harvest_repo(repo: str, *, limit: int = 25, llm_spec=None,
                 workdir: Path | None = None) -> list[Candidate]:
    """Mine one repository into candidate records, newest merged PR first."""
    owner, name = repo.split("/", 1)
    log.info("harvest: listing merged PRs for %s", repo)
    prs = list_merged_prs(owner, name, limit=limit * 4)

    out: list[Candidate] = []
    tmp = Path(workdir or tempfile.mkdtemp(prefix="kraken_harvest_"))
    for pr in prs:
        if len(out) >= limit:
            break
        ok, cues = is_perf_candidate(pr)
        if not ok:
            continue

        tests = covering_tests(pr)
        try:
            patch = fetch_pr_diff(owner, name, pr.number)
        except Exception as exc:  # noqa: BLE001
            log.warning("diff fetch failed for %s#%s: %s", repo, pr.number, exc)
            continue

        rec = {
            "instance_id": f"{owner}__{name}-{pr.number}",
            "repo": repo,
            "pull_number": pr.number,
            "pr_url": pr.url,
            "base_commit": pr.base_sha,
            "patch": patch,
            "problem_statement": f"{pr.title}\n\n{(pr.body or '').strip()}".strip(),
            "created_at": pr.merged_at,
            "covering_tests": tests,
            "test_cmd": f"pytest {' '.join(tests)}" if tests else None,
            "speedup": None,
            "workload": None,
        }

        checkout = clone_at(repo, pr.base_sha, tmp / rec["instance_id"])
        if checkout:
            rec.update(detect_env(checkout))
            surface, entrypoints = _surface(checkout, pr.changed_files)
            if llm_spec is not None and surface:
                rec["workload"] = synthesize_workload(repo, surface, entrypoints, llm_spec)
        else:
            rec.update({"python_version": "3.11", "install_cmd": "python -m pip install -e ."})

        missing = [k for k in ("covering_tests", "test_cmd", "workload") if not rec.get(k)]
        out.append(Candidate(record=rec, reasons=cues, missing=missing))
        log.info("harvest: %s kept (cues=%s, missing=%s)",
                 rec["instance_id"], ",".join(cues[:3]), ",".join(missing) or "none")
    return out


def write_jsonl(candidates: list[Candidate], path: Path) -> dict:
    """Append candidates to a corpus shard and report what is still incomplete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    complete_recs = [c for c in candidates if not c.missing]
    with path.open("a", encoding="utf-8") as fh:
        for c in candidates:
            fh.write(json.dumps(c.record) + "\n")
    return {
        "written": len(candidates),
        "complete": len(complete_recs),
        "incomplete": len(candidates) - len(complete_recs),
        "missing_counts": {
            k: sum(1 for c in candidates if k in c.missing)
            for k in ("covering_tests", "test_cmd", "workload")
        },
        "path": str(path),
    }
