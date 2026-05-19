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

"""Translate Vitest bench JSON to the ``Mean:``/``Std Dev:`` contract.

The TypeScript workload pipeline writes ``vitest bench --reporter=json`` output
to a file, then a wrapper script invokes this module to emit:

    PERF_START:
    Mean: <seconds>
    Std Dev: <seconds>
    PERF_END:

For multi-benchmark files, one PERF block is emitted per benchmark with a
``Name: <name>`` line between the ``PERF_START:`` sentinel and ``Mean:``,
matching the cpp pipeline's multi-bench convention. The single-bench layout
is byte-compatible with ``parse_gbench.py`` so ``parse_perf_output`` in
``test_spec.py`` works unchanged for both pipelines.

Vitest reports ``mean`` and ``sd`` in MILLISECONDS; values are divided by
1000 here to emit seconds.

Usage:
    python3 parse_vitest_bench.py <vitest_bench.json> [--filter-name PATTERN]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


def _collect_benchmarks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk both Vitest schema variants and return ``{name, mean_ms, sd_ms}`` rows.

    Supported layouts:
      * ``files[i].groups[j].benchmarks[k]`` (classic ``describe`` grouping).
      * ``files[i].benchmarks[k]`` (newer vitest versions, no ``describe`` wrap).

    Rows missing ``result.mean`` or ``result.sd`` are skipped silently; the
    caller is responsible for raising if zero rows survive.
    """
    rows: list[dict[str, Any]] = []

    def _take(b: dict[str, Any]) -> None:
        # Vitest 4.x emits mean/sd FLAT on the benchmark dict; earlier
        # docs/spec'd shape nested them under "result". Try result-wrapped
        # first (legacy/fixtures), fall back to flat (real vitest 4.x).
        result = b.get("result") or {}
        mean = result.get("mean")
        sd = result.get("sd")
        if mean is None:
            mean = b.get("mean")
        if sd is None:
            sd = b.get("sd")
        if mean is None or sd is None:
            return
        rows.append(
            {
                "name": b.get("name", ""),
                "mean_ms": float(mean),
                "sd_ms": float(sd),
            }
        )

    for f in data.get("files", []) or []:
        for b in f.get("benchmarks", []) or []:
            _take(b)
        for g in f.get("groups", []) or []:
            for b in g.get("benchmarks", []) or []:
                _take(b)

    return rows


def extract_benchmarks(
    data: dict[str, Any], name_filter: str | None = None
) -> list[dict[str, Any]]:
    rows = _collect_benchmarks(data)
    if not rows:
        raise ValueError(
            "No benchmarks found in vitest bench JSON "
            "(expected files[].benchmarks or files[].groups[].benchmarks "
            "with result.mean and result.sd)"
        )
    if name_filter:
        pat = re.compile(name_filter)
        rows = [r for r in rows if pat.search(r["name"])]
        if not rows:
            raise ValueError("No benchmarks matched the requested filter")
    return [
        {
            "name": r["name"],
            "mean_s": r["mean_ms"] / 1000.0,
            "stddev_s": r["sd_ms"] / 1000.0,
        }
        for r in rows
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to Vitest bench JSON output")
    parser.add_argument("--filter-name", default=None, help="Regex on benchmark name")
    parser.add_argument(
        "--no-sentinels",
        action="store_true",
        help="Skip PERF_START/PERF_END sentinels (debug)",
    )
    args = parser.parse_args(argv)

    try:
        with open(args.input) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: failed to read {args.input}: {e}", file=sys.stderr)
        return 2

    try:
        rows = extract_benchmarks(data, args.filter_name)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    row = rows[0]
    if not args.no_sentinels:
        print("PERF_START:")
    print(f"Mean: {row['mean_s']:.9f}")
    print(f"Std Dev: {row['stddev_s']:.9f}")
    if not args.no_sentinels:
        print("PERF_END:")
    return 0


if __name__ == "__main__":
    sys.exit(main())
