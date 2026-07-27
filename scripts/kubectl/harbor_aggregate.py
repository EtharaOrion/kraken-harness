#!/usr/bin/env python3
"""Aggregate rewards + test-failure counts from scoring/*/*/result.json.
Usage: harbor_aggregate.py [ROOT]"""
import json, sys, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else
            "/Users/anshkataria/Desktop/23-july/Repo2RLEnv/datasets/kubectl-kinds-v1")
VARIANTS = ("oracle-golden", "oracle-reference", "nop")


def extract_reward(result_json: Path):
    d = json.loads(result_json.read_text())
    stats = d.get("stats", {})
    evals = stats.get("evals") or {}
    if not evals:
        return None, stats.get("n_errored_trials", 0)
    ev = next(iter(evals.values()))
    metrics = ev.get("metrics") or []
    reward = metrics[0].get("mean") if metrics else None
    return reward, stats.get("n_errored_trials", 0)


def extract_tests(job_dir: Path):
    failed_total = 0
    tests_total = 0
    found = False
    for xml in job_dir.rglob("verifier/results.xml"):
        try:
            root = ET.parse(xml).getroot()
        except ET.ParseError:
            continue
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is None:
            continue
        f = int(suite.get("failures", "0"))
        e = int(suite.get("errors", "0"))
        t = int(suite.get("tests", "0"))
        failed_total += f + e
        tests_total += t
        found = True
    return (failed_total, tests_total) if found else (None, None)


rows = []
for task_parent in sorted(ROOT.glob("task-*")):
    if not task_parent.is_dir():
        continue
    task_dirs = [p for p in task_parent.iterdir() if p.is_dir() and (p / "task.toml").is_file()]
    if not task_dirs:
        continue
    task_dir = task_dirs[0]
    row = {"task": task_parent.name}
    for v in VARIANTS:
        vdir = task_dir / "scoring" / v
        row[f"{v}_reward"] = "-"
        row[f"{v}_fails"] = "-"
        if not vdir.exists():
            continue
        jobs = sorted([p for p in vdir.iterdir() if p.is_dir()])
        if not jobs:
            continue
        job = jobs[-1]
        rj = job / "result.json"
        if not rj.exists():
            row[f"{v}_reward"] = "..."
            row[f"{v}_fails"] = "..."
            continue
        try:
            reward, errs = extract_reward(rj)
        except Exception as e:
            row[f"{v}_reward"] = f"err"
            row[f"{v}_fails"] = "-"
            continue
        marker = "!" if errs else ""
        row[f"{v}_reward"] = f"{reward:.3f}{marker}" if reward is not None else "?"
        f, t = extract_tests(job)
        row[f"{v}_fails"] = f"{f}/{t}" if t else "-"
    rows.append(row)


COLS = [
    ("task", "task", "<", 20),
    ("oracle-golden_reward", "gold-reward", ">", 11),
    ("oracle-golden_fails", "gold-fail/tot", ">", 13),
    ("oracle-reference_reward", "ref-reward", ">", 10),
    ("oracle-reference_fails", "ref-fail/tot", ">", 12),
    ("nop_reward", "nop-reward", ">", 10),
    ("nop_fails", "nop-fail/tot", ">", 12),
]

for i, (key, hdr, align, minw) in enumerate(COLS):
    w = max(minw, len(hdr), max(len(str(r.get(key, ""))) for r in rows))
    COLS[i] = (key, hdr, align, w)


def fmt_row(r):
    return "  ".join(f"{str(r.get(k, '')):{a}{w}}" for k, _, a, w in COLS)


header = "  ".join(f"{h:{a}{w}}" for _, h, a, w in COLS)
print(header)
print("-" * len(header))
for r in rows:
    print(fmt_row(r))


def to_float(x):
    try:
        return float(str(x).rstrip("!"))
    except (ValueError, TypeError):
        return None


print()
print("Summary (mean over completed runs):")
for v in VARIANTS:
    rewards = [to_float(r[f"{v}_reward"]) for r in rows]
    rewards = [x for x in rewards if x is not None]
    fails = []
    for r in rows:
        s = r.get(f"{v}_fails", "-")
        if "/" in str(s):
            f, t = s.split("/")
            try:
                fails.append((int(f), int(t)))
            except ValueError:
                pass
    if rewards:
        mean = sum(rewards) / len(rewards)
        line = f"  {v:<17} n={len(rewards):<3} mean={mean:.3f}  min={min(rewards):.3f}  max={max(rewards):.3f}"
        if fails:
            tot_f = sum(f for f, _ in fails)
            tot_t = sum(t for _, t in fails)
            line += f"  |  total fails: {tot_f}/{tot_t} ({tot_f/tot_t*100:.1f}%)"
        print(line)
    else:
        print(f"  {v:<17} n=0")
print()
print("Legend: '-' variant not started | '...' running (no result.json yet) | '!' had errored trials")
