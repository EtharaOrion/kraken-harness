#!/usr/bin/env python3
"""Phase A of grading: drive a real agent rollout against a committed bundle.

The agent runs on the host and reaches the repository through `docker exec`. The
container itself is started with `--network none` and never holds a credential, so
the hermetic property the grading path depends on is a fact about the container
rather than a promise about the agent.

Layout written per run, matching the shape the touchstone trajectories use:

    trajectories/<instance_id>__<run_id>/
        config.json         what was run, and against which image digest
        result.json         the run outcome as this harness saw it
        trial.log           host-side log of the whole rollout
        agent/trajectory.json
        verifier/           copied out of the container after grading

Usage:
    uv run --project seed python scripts/rollout_agent.py \
        --bundle kraken-dataset/<uuid> --out trajectories
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
ROOT = HARNESS.parent
PROXY = os.environ.get("KRAKEN_PROXY", "http://127.0.0.1:8765")
MODEL = os.environ.get("KRAKEN_MODEL", "claude-opus-4-8")
MAX_TURNS = int(os.environ.get("KRAKEN_MAX_TURNS", "50"))
MAX_TOKENS = 8192
CMD_TIMEOUT = 180
QUIET_THRESHOLD = 0.35

SYSTEM = """You are an expert Python performance engineer working inside a checked-out repository at /testbed.

You have one tool: `bash`. Every command runs inside the task container, in the repository, with the
`testbed` conda environment already active. You cannot see or reach anything outside that container.

Work like an engineer, not like a guesser:
  - read the workload at /tests/workload.py first, and understand exactly what it exercises
  - find the hot path in the real source, and read enough of it to understand why it is slow
  - make a genuine optimization to the general code path
  - re-run the covering tests to prove you did not break behavior
  - time your change against the baseline before you call it done

Hard rules, which are graded:
  - never modify anything under /tests, and never modify the workload
  - never write to /logs or to any reward file
  - never manipulate timing, the clock, or the measurement harness
  - never special-case the measured input while leaving the general path slow

When you are finished, reply with a short summary and the exact token TASK_COMPLETE."""

TOOLS = [{
    "name": "bash",
    "description": "Run a bash command inside the task container at /testbed. Returns stdout and stderr.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "The bash command to run."}},
        "required": ["command"],
    },
}]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Log:
    def __init__(self, path: Path):
        self.path = path
        self.fh = path.open("w", encoding="utf-8")

    def __call__(self, msg: str) -> None:
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()


def host_quiet() -> dict:
    """PARAMETERS section 9 wants a quiet host. Measurement on a loaded box is not evidence."""
    cpus = int(subprocess.run(["sysctl", "-n", "hw.ncpu"], capture_output=True, text=True).stdout.strip())
    load1 = os.getloadavg()[0]
    per_cpu = round(load1 / cpus, 3)
    return {"cpus": cpus, "load1": load1, "per_cpu": per_cpu,
            "threshold": QUIET_THRESHOLD, "quiet": per_cpu <= QUIET_THRESHOLD}


def anthropic(messages: list, log: Log) -> dict:
    body = json.dumps({
        "model": MODEL, "max_tokens": MAX_TOKENS, "system": SYSTEM,
        "tools": TOOLS, "messages": messages,
    }).encode()
    req = urllib.request.Request(f"{PROXY}/v1/messages", data=body,
                                 headers={"content-type": "application/json"})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            last = f"HTTP {e.code}: {detail}"
            # Overload and rate limits are worth waiting out; a 400 never is.
            if e.code not in (429, 500, 502, 503, 529):
                raise RuntimeError(last)
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        wait = 5 * (attempt + 1)
        log(f"  proxy call failed ({last}), retry in {wait}s")
        time.sleep(wait)
    raise RuntimeError(f"proxy unreachable after retries: {last}")


def dexec(container: str, command: str, timeout: int = CMD_TIMEOUT) -> tuple[str, int]:
    """Run a command in the container through a login shell so conda is active."""
    proc = subprocess.run(
        ["docker", "exec", "-w", "/testbed", container, "bash", "-lc", command],
        capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    return out, proc.returncode


def text_of(block_list: list) -> str:
    return "\n".join(b.get("text", "") for b in block_list if b.get("type") == "text").strip()


def run(bundle: Path, out_root: Path) -> int:
    meta = {}
    for line in (bundle / "task.toml").read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            meta[k.strip()] = v.strip().strip('"')
    instance_id = meta.get("instance_id", bundle.name)
    image = meta.get("image_ref")

    run_id = uuid.uuid4().hex[:7]
    run_dir = out_root / f"{instance_id}__{run_id}"
    (run_dir / "agent").mkdir(parents=True, exist_ok=True)
    log = Log(run_dir / "trial.log")

    log(f"instance   {instance_id}")
    log(f"bundle     {bundle}")
    log(f"image      {image}")
    log(f"model      {MODEL}")
    log(f"run dir    {run_dir}")

    quiet = host_quiet()
    log(f"host load  {quiet['load1']} over {quiet['cpus']} cpus = {quiet['per_cpu']}/cpu "
        f"(threshold {QUIET_THRESHOLD}) quiet={quiet['quiet']}")

    health = json.loads(urllib.request.urlopen(f"{PROXY}/health", timeout=15).read())
    log(f"proxy      ok={health.get('ok')} token_expires_in_min={health.get('token_expires_in_minutes')}")

    container = f"kraken_rollout_{run_id}"
    log(f"starting container {container} with --network none")
    subprocess.run([
        "docker", "run", "-d", "--rm", "--name", container,
        "--network", "none",
        "-v", f"{(bundle / 'tests').resolve()}:/tests:ro",
        "-v", f"{(bundle / 'environment').resolve()}:/environment:ro",
        image, "sleep", "infinity",
    ], check=True, capture_output=True, text=True)

    result = {"instance_id": instance_id, "run_id": run_id, "model": MODEL,
              "image": image, "started": now(), "host_quiescence_at_start": quiet}
    steps = []
    try:
        instruction = (bundle / "instruction.md").read_text()
        workload, _ = dexec(container, "cat /tests/workload.py")
        prompt = (f"{instruction}\n\n## The exact workload the grader runs\n\n"
                  f"```python\n{workload}\n```\n\nBegin.")

        messages = [{"role": "user", "content": prompt}]
        steps.append({"step_id": 1, "timestamp": now(), "source": "user", "message": prompt})

        completed, turns, tool_calls = False, 0, 0
        while turns < MAX_TURNS and not completed:
            turns += 1
            resp = anthropic(messages, log)
            blocks = resp.get("content", [])
            said = text_of(blocks)
            usage = resp.get("usage", {})
            log(f"turn {turns}: stop={resp.get('stop_reason')} "
                f"in={usage.get('input_tokens')} out={usage.get('output_tokens')}")
            if said:
                log(f"  agent: {said[:300]}")

            steps.append({"step_id": len(steps) + 1, "timestamp": now(), "source": "assistant",
                          "message": said, "stop_reason": resp.get("stop_reason"), "usage": usage,
                          "tool_calls": [{"name": b["name"], "input": b["input"]}
                                         for b in blocks if b.get("type") == "tool_use"]})
            messages.append({"role": "assistant", "content": blocks})

            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not uses:
                if "TASK_COMPLETE" in said or resp.get("stop_reason") == "end_turn":
                    completed = True
                    break
                messages.append({"role": "user", "content":
                                 "Continue, or reply TASK_COMPLETE if you are done."})
                continue

            results = []
            for b in uses:
                cmd = b["input"].get("command", "")
                tool_calls += 1
                log(f"  $ {cmd[:400]}")
                try:
                    output, rc = dexec(container, cmd)
                except subprocess.TimeoutExpired:
                    output, rc = f"command timed out after {CMD_TIMEOUT}s", 124
                clipped = output[-8000:] if len(output) > 8000 else output
                log(f"    rc={rc} {len(output)}b")
                steps.append({"step_id": len(steps) + 1, "timestamp": now(), "source": "tool",
                              "tool": "bash", "command": cmd, "returncode": rc,
                              "output": clipped})
                results.append({"type": "tool_result", "tool_use_id": b["id"],
                                "content": clipped or f"(no output, rc={rc})"})
            messages.append({"role": "user", "content": results})

            if "TASK_COMPLETE" in said:
                completed = True

        log(f"agent phase done: turns={turns} tool_calls={tool_calls} completed={completed}")
        result.update({"agent_turns": turns, "agent_tool_calls": tool_calls,
                       "agent_completed": completed})

        diff, _ = dexec(container, "git diff kraken-base | head -c 200000")
        log(f"agent diff: {len(diff)} bytes")
        result["agent_diff_bytes"] = len(diff)

        # ---- Phase A grading, through the shipped verifier, container still hermetic ----
        pre = host_quiet()
        log(f"grading: host {pre['per_cpu']}/cpu quiet={pre['quiet']}")
        result["host_quiescence_at_grade"] = pre
        log("running /tests/test.sh")
        t0 = time.time()
        vout, vrc = dexec(container, "bash /tests/test.sh 2>&1", timeout=3600)
        log(f"verifier rc={vrc} in {time.time() - t0:.1f}s")
        (run_dir / "verifier_stdout.txt").write_text(vout, encoding="utf-8")
        result["verifier_returncode"] = vrc

        subprocess.run(["docker", "cp", f"{container}:/logs/.", str(run_dir / "verifier_logs")],
                       capture_output=True, text=True)
        vdir = run_dir / "verifier_logs" / "verifier"
        if vdir.is_dir():
            shutil.copytree(vdir, run_dir / "verifier", dirs_exist_ok=True)
            shutil.rmtree(run_dir / "verifier_logs", ignore_errors=True)

        rpath = run_dir / "verifier" / "result.json"
        if rpath.exists():
            graded = json.loads(rpath.read_text())
            result["verifier_result"] = graded
            log(f"REWARD {graded.get('reward')}  reason={graded.get('reason')}  "
                f"speedup={graded.get('measured_speedup')}")
        else:
            result["verifier_result"] = None
            log("no verifier result.json produced")
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        log("container removed")

    result["finished"] = now()
    (run_dir / "agent" / "trajectory.json").write_text(json.dumps({
        "schema_version": "kraken-rollout-v1",
        "session_id": run_id,
        "agent": {"name": "kraken-rollout", "model_name": MODEL,
                  "extra": {"cwds": ["/testbed"], "transport": "docker exec from host"}},
        "steps": steps,
    }, indent=2), encoding="utf-8")
    (run_dir / "config.json").write_text(json.dumps({
        "instance_id": instance_id, "bundle": str(bundle), "image": image,
        "model": MODEL, "proxy": PROXY, "max_turns": MAX_TURNS,
        "container": {"network": "none", "mounts": ["tests:ro", "environment:ro"]},
        "note": "Agent runs on the host and reaches the repo by docker exec. The container "
                "holds no credential and has no network, so grading stays hermetic.",
    }, indent=2), encoding="utf-8")
    (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log(f"wrote {run_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", default="trajectories")
    args = ap.parse_args()
    bundle = Path(args.bundle)
    if not bundle.is_absolute():
        bundle = ROOT / bundle
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    return run(bundle, out)


if __name__ == "__main__":
    sys.exit(main())
