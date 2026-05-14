#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Translate Google Benchmark JSON to the ``Mean:``/``Std Dev:`` contract.

The C++ pipeline writes the workload binary's ``--benchmark_format=json`` output
to a file, then a wrapper script invokes this module to emit two lines:

    PERF_START:
    Mean: <seconds>
    Std Dev: <seconds>
    PERF_END:

These exact sentinels match ``parse_perf_output`` in ``test_spec.py`` so that
``run_evaluation_cpp.py`` can reuse the Python pipeline's perf parser unchanged.

Usage:
    python3 parse_gbench.py <gbench_output.json> [--filter-name PATTERN]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


_TIME_TO_SECONDS: dict[str, float] = {
    "s": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "ns": 1e-9,
}


def _to_seconds(value: float, unit: str) -> float:
    factor = _TIME_TO_SECONDS.get(unit)
    if factor is None:
        raise ValueError(f"Unknown time_unit: {unit!r}")
    return value * factor


def extract_mean_stddev(data: dict[str, Any], name_filter: str | None = None) -> tuple[float, float]:
    """Pull ``(mean_s, stddev_s)`` from Google Benchmark JSON.

    Strategy:
      1. Prefer ``run_type == 'aggregate'`` rows with ``aggregate_name`` in
         {``mean``, ``stddev``}. Standard when the binary was invoked with
         ``--benchmark_repetitions=N`` and ``--benchmark_display_aggregates_only``.
      2. Fall back to computing the mean/stddev across iteration rows if no
         aggregate rows are present (single-shot run).
    """
    benchmarks = data.get("benchmarks", []) or []
    if name_filter:
        pat = re.compile(name_filter)
        benchmarks = [b for b in benchmarks if pat.search(b.get("name", ""))]
    if not benchmarks:
        raise ValueError("No benchmarks matched the requested filter")

    mean_s: float | None = None
    stddev_s: float | None = None

    for b in benchmarks:
        if b.get("run_type") != "aggregate":
            continue
        agg = b.get("aggregate_name", "")
        unit = b.get("time_unit", "ns")
        rt = b.get("real_time")
        if rt is None:
            continue
        if agg == "mean" and mean_s is None:
            mean_s = _to_seconds(float(rt), unit)
        elif agg == "stddev" and stddev_s is None:
            stddev_s = _to_seconds(float(rt), unit)

    if mean_s is not None and stddev_s is not None:
        return mean_s, stddev_s

    iters = [b for b in benchmarks if b.get("run_type") == "iteration"]
    if not iters:
        raise ValueError("No aggregate or iteration rows found")

    samples = [
        _to_seconds(float(b["real_time"]), b.get("time_unit", "ns"))
        for b in iters
        if "real_time" in b
    ]
    if not samples:
        raise ValueError("Iteration rows missing real_time field")

    n = len(samples)
    m = sum(samples) / n
    if n == 1:
        return m, 0.0
    var = sum((s - m) ** 2 for s in samples) / (n - 1)
    return m, var ** 0.5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to Google Benchmark JSON output")
    parser.add_argument("--filter-name", default=None, help="Regex on benchmark name")
    parser.add_argument(
        "--no-sentinels",
        action="store_true",
        help="Skip PERF_START/PERF_END sentinels (debug)",
    )
    args = parser.parse_args(argv)

    with open(args.input) as f:
        data = json.load(f)

    mean_s, stddev_s = extract_mean_stddev(data, args.filter_name)

    if not args.no_sentinels:
        print("PERF_START:")
    print(f"Mean: {mean_s:.9f}")
    print(f"Std Dev: {stddev_s:.9f}")
    if not args.no_sentinels:
        print("PERF_END:")
    return 0


if __name__ == "__main__":
    sys.exit(main())
