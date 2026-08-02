#!/usr/bin/env python3
"""kraken — the one harness. Every stage from a merged pull request to a reward.

    uv run --project kraken-harness/repo2rlenv python kraken-harness/kraken.py harvest --repo networkx/networkx
    uv run --project kraken-harness/repo2rlenv python kraken-harness/kraken.py author  --instances <id>
    uv run --project kraken-harness/repo2rlenv python kraken-harness/kraken.py run     --bundle kraken-dataset/<uuid>
    uv run --project kraken-harness/repo2rlenv python kraken-harness/kraken.py grade   --bundle <b> --logs <run>
    uv run --project kraken-harness/repo2rlenv python kraken-harness/kraken.py status

There is one harness and it lives here. Harvest mines pull requests, author builds the
image and calibrates the target, run drives an agent, grade scores the rubric channel
and recomposes the reward. Nothing in this chain lives at the knowledge root.

Two things sit outside on purpose, and neither is a second harness:

  harbor/  the runtime. `trinity/FORGE.md` binds the verifier entry point to Harbor's
           `tests/test.sh`, so it is contract, not duplication. `run` calls it.
  pilot/   the external pilot. FORGE Phase 4 is out-of-band only and the repository
           may never self-produce trusted difficulty proof, so keeping it out of the
           harness is what makes its externality structural rather than promised.

Stages stay separate because harvest loads the network while author needs a quiet
host. One button would run measurement under load and hide which stage failed.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS / "repo2rlenv" / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kraken")


def cmd_harvest(args: argparse.Namespace) -> int:
    from repo2rlenv.pipelines._perf_runtime_harvest import harvest_repo, write_jsonl

    spec = None
    if args.model:
        from repo2rlenv.spec.options import LLMSpec  # type: ignore
        spec = LLMSpec(model=args.model)

    total = {"written": 0, "complete": 0, "incomplete": 0}
    for repo in args.repo:
        cands = harvest_repo(repo, limit=args.limit, llm_spec=spec)
        if not cands:
            log.info("harvest: %s produced no performance candidates", repo)
            continue
        shard = ROOT / args.out / (repo.replace("/", "__") + ".jsonl")
        rep = write_jsonl(cands, shard)
        log.info("harvest: %s -> %s", repo, json.dumps(rep))
        for k in total:
            total[k] += rep[k]

    print(json.dumps({"stage": "harvest", **total, "corpus": args.out}, indent=2))
    if total["incomplete"]:
        print(f"\n{total['incomplete']} record(s) are incomplete and will be rejected by the\n"
              f"emitter until enriched. Pass --model to synthesize the missing workload.")
    return 0


def cmd_author(args: argparse.Namespace) -> int:
    from repo2rlenv.pipelines.perf_runtime import PerfRuntimePipeline
    from repo2rlenv.spec.options import PerfRuntimeOptions

    opts = PerfRuntimeOptions(
        corpus=str(ROOT / args.corpus),
        instances=args.instances or [],
        repos=args.repos or [],
        limit=args.limit or 0,
    )
    out = ROOT / args.out
    res = PerfRuntimePipeline(gen_input=None, options=opts).run(out)
    print(json.dumps({"stage": "author", "candidates": res.candidates,
                      "emitted": res.emitted, "skipped": res.skipped,
                      "skip_reasons": res.skip_reasons, "out": str(out)},
                     indent=2, default=str))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Drive one agent rollout against one bundle.

    Prefers Harbor when it is checked out, because Harbor is the runtime this family
    of projects standardises on and it already handles agents, adapters and result
    layout. Falls back to the local rollout driver otherwise.
    """
    bundle = Path(args.bundle)
    if not bundle.is_absolute():
        bundle = ROOT / bundle
    harbor = HARNESS / "harbor"

    if harbor.is_dir() and not args.local:
        cmd = ["uv", "run", "--project", str(harbor), "harbor", "run",
               "-p", str(bundle), "-a", args.agent, "-m", args.model, "--env", "docker"]
        log.info("run: %s", " ".join(cmd))
        return subprocess.run(cmd, cwd=ROOT).returncode

    log.info("run: harbor not available or --local given, using the local rollout driver")
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "kraken_rollout.py"),
         "--bundle", str(bundle), "--out", args.out], cwd=ROOT).returncode


def cmd_grade(args: argparse.Namespace) -> int:
    """Phase B: score the rubric channel outside the container and recompose the reward.

    The graded container has no network by design, so it writes the deterministic
    reward and leaves every rubric criterion unscored. This closes that half.
    """
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "kraken_judge.py"),
         "--bundle", args.bundle, "--logs", args.logs],
        cwd=ROOT).returncode


def cmd_status(args: argparse.Namespace) -> int:
    corpus = sorted((ROOT / "harvest").glob("*.jsonl"))
    records = sum(1 for f in corpus for ln in f.read_text().splitlines() if ln.strip())
    bundles = [p for p in (ROOT / "kraken-dataset").iterdir()
               if p.is_dir() and (p / "task.toml").exists()] if (ROOT / "kraken-dataset").is_dir() else []
    trajs = [p for p in (ROOT / "trajectories").iterdir() if p.is_dir()] \
        if (ROOT / "trajectories").is_dir() else []
    print(json.dumps({
        "corpus_shards": len(corpus), "corpus_records": records,
        "authored_bundles": len(bundles), "trajectories": len(trajs),
        "harbor_present": (HARNESS / "harbor").is_dir(),
        "harness_present": (HARNESS / "repo2rlenv" / "src").is_dir(),
        "pilot_present": (ROOT / "pilot" / "run_pilot.py").exists(),
        "harness_stages": ["harvest", "author", "run", "grade"],
    }, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="kraken", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="mine merged PRs into candidate corpus records")
    h.add_argument("--repo", action="append", required=True, help="owner/name, repeatable")
    h.add_argument("--limit", type=int, default=25, help="candidates per repo")
    h.add_argument("--out", default="harvest")
    h.add_argument("--model", default=None,
                   help="LiteLLM model for workload synthesis; omit to leave workloads empty")
    h.set_defaults(func=cmd_harvest)

    a = sub.add_parser("author", help="emit graded bundles from corpus records")
    a.add_argument("--corpus", default="harvest")
    a.add_argument("--out", default="kraken-dataset")
    a.add_argument("--instances", nargs="*", default=None)
    a.add_argument("--repos", nargs="*", default=None)
    a.add_argument("--limit", type=int, default=0)
    a.set_defaults(func=cmd_author)

    r = sub.add_parser("run", help="drive one agent rollout against one bundle")
    r.add_argument("--bundle", required=True)
    r.add_argument("--agent", default="claude-code")
    r.add_argument("--model", default="claude-opus-4-8")
    r.add_argument("--out", default="trajectories")
    r.add_argument("--local", action="store_true", help="force the local driver over Harbor")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("grade", help="score the rubric channel and recompose the reward")
    g.add_argument("--bundle", required=True)
    g.add_argument("--logs", required=True, help="a run directory produced by `run`")
    g.set_defaults(func=cmd_grade)

    s = sub.add_parser("status", help="what exists right now")
    s.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
