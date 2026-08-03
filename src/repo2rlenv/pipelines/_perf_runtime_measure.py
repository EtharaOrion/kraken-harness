"""Measurement discipline for kraken perf_runtime tasks. Runs inside the container.

Copied verbatim into every emitted bundle as `tests/measure.py`.

A runtime target is never graded off a single unrepeated measurement. Every value
this module returns comes from repeated trials with a declared aggregation, warmup
discarded, one process per repetition, and a variance ceiling above which the run
reports unstable rather than scoring. The baseline and the optimized condition are
timed on the same container back to back, so the ratio is not confounded by host
noise between image builds.

Bound by requirements/PARAMETERS.md section 9.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

# --- bound parameters, requirements/PARAMETERS.md section 9 -------------------
FLAKINESS_TRIALS = 5
AGGREGATION = "median"
WARMUP_INVOCATIONS = 3
CV_CEILING = 0.05
WINDOW_CEILING_SECONDS = 60
LOAD_PROFILE = "single process pinned to one physical core"

# Pinning to one core is only half of "single process". A threaded BLAS will still
# spawn one worker per host core and pile them onto that single pinned core, which
# produces bimodal timings that look like a noisy workload but are contention. Every
# numeric backend is therefore held to one thread for the duration of a measurement.
SINGLE_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    "RAYON_NUM_THREADS": "1",
}

UNSTABLE = "measurement_unstable"


def _pin_prefix() -> list:
    """Pin to one physical core where the platform supports it.

    Absence of a pinning tool is recorded by the caller as a coverage gap rather
    than silently ignored, because an unpinned measurement is a different
    measurement.
    """
    if sys.platform.startswith("linux"):
        from shutil import which

        if which("taskset"):
            return ["taskset", "-c", "0"]
    return []


def _run_once(workload: Path, cwd: Path, timeout: int) -> float:
    """One isolated invocation. A fresh process every repetition, never a loop in-process.

    Interpreter state does not carry between repetitions, so no repetition inherits a
    warmed cache, an import graph, or a JIT state from the one before it.
    """
    proc = subprocess.run(
        [*_pin_prefix(), sys.executable, str(workload)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "PYTHONHASHSEED": "0", **SINGLE_THREAD_ENV},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"workload failed rc={proc.returncode}: {proc.stderr[-800:]}")
    return parse_timing(proc.stdout)


# Labelled forms the harvested workloads emit, most specific first. `Mean:` is the
# corpus convention and must be matched by name: the last line of that output is the
# standard deviation, so a naive last-number parse would time the noise instead of
# the workload.
_LABELLED = ("mean", "median", "elapsed", "seconds", "duration", "time")


def parse_timing(stdout: str) -> float:
    """Read one elapsed-seconds value out of a workload's stdout.

    Accepts a labelled line, a JSON object, or a bare float, and refuses to guess
    when none of those is present rather than returning a number it cannot justify.
    """
    lines = [ln.strip() for ln in (stdout or "").strip().splitlines() if ln.strip()]

    for label in _LABELLED:
        for line in lines:
            head, sep, tail = line.partition(":")
            if sep and head.strip().lower() == label:
                try:
                    return float(tail.strip().split()[0])
                except (ValueError, IndexError):
                    continue

    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            for key in _LABELLED:
                if key in payload:
                    return float(payload[key])

    for line in reversed(lines):
        try:
            return float(line.split()[-1])
        except (ValueError, IndexError):
            continue

    raise RuntimeError("workload emitted no parsable timing on stdout")


def time_condition(workload: Path, cwd: Path, *, trials: int = FLAKINESS_TRIALS,
                   warmup: int = WARMUP_INVOCATIONS,
                   timeout: int = WINDOW_CEILING_SECONDS) -> dict:
    """Time one condition under the full discipline and report its stability."""
    for _ in range(warmup):
        try:
            _run_once(workload, cwd, timeout)
        except Exception:
            break  # a warmup failure is surfaced by the measured trials below

    samples = [_run_once(workload, cwd, timeout) for _ in range(trials)]
    med = statistics.median(samples)
    mean = statistics.fmean(samples)
    stdev = statistics.stdev(samples) if len(samples) > 1 else 0.0
    cv = (stdev / mean) if mean > 0 else float("inf")
    return {
        "samples": samples,
        "trials": trials,
        "aggregation": AGGREGATION,
        "value": med,
        "mean": mean,
        "stdev": stdev,
        "cv": cv,
        "stable": cv <= CV_CEILING,
        "warmup_discarded": warmup,
        "pinned": bool(_pin_prefix()),
        "single_threaded": sorted(SINGLE_THREAD_ENV),
        "load_profile": LOAD_PROFILE,
    }


def measure_speedup(workload: Path, repo: Path, *, baseline_ref: str,
                    trials: int = FLAKINESS_TRIALS) -> dict:
    """Time the optimized tree, reset to base, time the baseline, and ratio them.

    Order matters: both conditions run on the same container, back to back, with the
    optimized condition first so a slow baseline cannot warm the cache for it.
    """
    optimized = time_condition(workload, repo, trials=trials)

    with tempfile.TemporaryDirectory() as stash:
        patch = Path(stash) / "submission.diff"
        subprocess.run(["git", "-C", str(repo), "diff", baseline_ref],
                       stdout=patch.open("w"), text=True, check=False)
        subprocess.run(["git", "-C", str(repo), "checkout", "--", "."], check=False,
                       capture_output=True)
        baseline = time_condition(workload, repo, trials=trials)
        if patch.stat().st_size:
            subprocess.run(["git", "-C", str(repo), "apply", str(patch)], check=False,
                           capture_output=True)

    ratio = (baseline["value"] / optimized["value"]) if optimized["value"] > 0 else 0.0
    stable = optimized["stable"] and baseline["stable"]
    return {
        "baseline": baseline,
        "optimized": optimized,
        "speedup": ratio,
        "stable": stable,
        "status": "measured" if stable else UNSTABLE,
        "cv_ceiling": CV_CEILING,
        "discipline": {
            "flakiness_trials": trials,
            "aggregation": AGGREGATION,
            "warmup_discarded": WARMUP_INVOCATIONS,
            "isolation": "fork per repetition",
            "load_profile": LOAD_PROFILE,
            "window_ceiling_seconds": WINDOW_CEILING_SECONDS,
            "baseline_retimed_on_same_container": True,
        },
    }
