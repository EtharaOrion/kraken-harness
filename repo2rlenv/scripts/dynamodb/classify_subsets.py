#!/usr/bin/env python3
"""Classify every non-empty DynamoDB command subset by difficulty.

Enumerates the powerset of the 8 pilot DynamoDB CLI verbs
(`_DDB_TARGET_OPS_DEFAULT` in `src/repo2rlenv/pipelines/_cli_app_extract.py`)
and bins each subset into `easy` / `medium` / `hard` using the heuristic
below. It ALSO prints the top-N hardest combinations.

Difficulty heuristic (tune the constants at the top of the file):

    score(subset) = sum(per_op_weight)
                  + max(0, |subset| - 2) * SIZE_BONUS_PER_STEP
                  + count(hard_ops in subset) * HARD_OP_BONUS

    tiers:  easy    if score <= EASY_MAX
            medium  if score <= MEDIUM_MAX
            hard    otherwise

Per-op weights reflect required-argument surface in the AWS CLI:
    list-tables  (1) — no required args
    delete-table (2) — only --table-name
    get-item     (3) — --table-name --key
    delete-item  (3) — --table-name --key
    put-item     (4) — --table-name --item (full JSON)
    create-table (5) — --attribute-definitions --key-schema --billing-mode
    query        (6) — --key-condition-expression + EAV
    update-item  (7) — --update-expression + EAV + EAN

Usage:

    python scripts/dynamodb/classify_subsets.py                       # summary + top-15 hardest
    python scripts/dynamodb/classify_subsets.py --print-all           # dump every subset per tier
    python scripts/dynamodb/classify_subsets.py --hardest 30          # top-30 hardest
    python scripts/dynamodb/classify_subsets.py --json out.json       # write full classification to JSON
    python scripts/dynamodb/classify_subsets.py --emit-tier hard      # print JSON array of CSVs
                                                                      #   (drop straight into
                                                                      #    --pipeline-opt cli_app_subsets=...)

JSON output schema (--json):

    {
      "easy":   [{"commands": [...], "csv": "a,b", "score": N}, ...],
      "medium": [...],
      "hard":   [...],
      "meta": {
        "ops": [...], "weights": {op: w}, "hard_ops": [...],
        "min_size": 2, "max_size": 8, "total_subsets": 247,
        "counts": {"easy": N, "medium": N, "hard": N}
      }
    }
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

OPS: dict[str, int] = {
    "list-tables": 1,
    "delete-table": 2,
    "get-item": 3,
    "delete-item": 3,
    "put-item": 4,
    "create-table": 5,
    "query": 6,
    "update-item": 7,
}

HARD_OPS: frozenset[str] = frozenset({"query", "update-item"})

SIZE_BONUS_PER_STEP = 2
HARD_OP_BONUS = 3

EASY_MAX = 10
MEDIUM_MAX = 20


def score(subset: tuple[str, ...]) -> int:
    base = sum(OPS[c] for c in subset)
    size_bonus = max(0, len(subset) - 2) * SIZE_BONUS_PER_STEP
    hard_bonus = sum(HARD_OP_BONUS for c in subset if c in HARD_OPS)
    return base + size_bonus + hard_bonus


def classify(s: int) -> str:
    if s <= EASY_MAX:
        return "easy"
    if s <= MEDIUM_MAX:
        return "medium"
    return "hard"


def enumerate_subsets(min_size: int, max_size: int) -> list[tuple[str, ...]]:
    ops = list(OPS.keys())
    out: list[tuple[str, ...]] = []
    for k in range(min_size, max_size + 1):
        out.extend(itertools.combinations(ops, k))
    return out


def size_breakdown(
    buckets: dict[str, list[tuple[tuple[str, ...], int]]],
    min_size: int,
    max_size: int,
) -> str:
    lines = [f"{'size':>4} | {'easy':>5} | {'medium':>6} | {'hard':>4} | {'total':>5}"]
    lines.append("-" * len(lines[0]))
    per_size: dict[int, dict[str, int]] = {
        n: {"easy": 0, "medium": 0, "hard": 0} for n in range(min_size, max_size + 1)
    }
    for tier, items in buckets.items():
        for subset, _ in items:
            per_size[len(subset)][tier] += 1
    for n in range(min_size, max_size + 1):
        row = per_size[n]
        total = row["easy"] + row["medium"] + row["hard"]
        lines.append(
            f"{n:>4} | {row['easy']:>5} | {row['medium']:>6} | {row['hard']:>4} | {total:>5}"
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Enumerate DynamoDB command subsets and classify by difficulty.",
    )
    ap.add_argument(
        "--min-size",
        type=int,
        default=2,
        help="Minimum subset size (pipeline requires >=2; use 1 to include singletons).",
    )
    ap.add_argument(
        "--max-size",
        type=int,
        default=len(OPS),
        help=f"Maximum subset size (default {len(OPS)} = all pilot ops).",
    )
    ap.add_argument(
        "--hardest",
        type=int,
        default=15,
        help="Print the top-N hardest subsets to stdout (0 to skip).",
    )
    ap.add_argument(
        "--print-all",
        action="store_true",
        help="Print every subset per tier (verbose).",
    )
    ap.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write the full classification to a JSON file.",
    )
    ap.add_argument(
        "--emit-tier",
        choices=["easy", "medium", "hard"],
        default=None,
        help="Emit only a JSON array of CSV strings for one tier "
        "(feed directly into --pipeline-opt cli_app_subsets=...).",
    )
    args = ap.parse_args()

    if args.min_size < 1 or args.max_size > len(OPS) or args.min_size > args.max_size:
        raise SystemExit(
            f"invalid size range: min_size={args.min_size}, max_size={args.max_size}, ops={len(OPS)}"
        )

    subsets = enumerate_subsets(args.min_size, args.max_size)
    scored: list[tuple[tuple[str, ...], int]] = sorted(
        ((s, score(s)) for s in subsets),
        key=lambda x: (-x[1], x[0]),
    )

    buckets: dict[str, list[tuple[tuple[str, ...], int]]] = {"easy": [], "medium": [], "hard": []}
    for subset, s in scored:
        buckets[classify(s)].append((subset, s))

    if args.emit_tier:
        csvs = [",".join(subset) for subset, _ in buckets[args.emit_tier]]
        print(json.dumps(csvs))
        return

    print(
        f"Enumerated {len(subsets)} subsets (size {args.min_size}..{args.max_size}) "
        f"over {len(OPS)} pilot ops."
    )
    print(f"  easy   (score <= {EASY_MAX}): {len(buckets['easy']):4d}")
    print(f"  medium (score <= {MEDIUM_MAX}): {len(buckets['medium']):4d}")
    print(f"  hard   (score >  {MEDIUM_MAX}): {len(buckets['hard']):4d}")
    print()
    print("Distribution by subset size:")
    print(size_breakdown(buckets, args.min_size, args.max_size))
    print()

    if args.hardest > 0:
        print(f"Top {min(args.hardest, len(scored))} hardest subsets:")
        for subset, s in scored[: args.hardest]:
            print(f"  [score={s:3d}] ({len(subset)}) {','.join(subset)}")
        print()

    if args.print_all:
        for tier in ("easy", "medium", "hard"):
            print(f"--- {tier.upper()} ({len(buckets[tier])}) ---")
            for subset, s in buckets[tier]:
                print(f"  [score={s:3d}] ({len(subset)}) {','.join(subset)}")
            print()

    if args.json:
        payload: dict[str, object] = {
            tier: [
                {"commands": list(subset), "csv": ",".join(subset), "score": s}
                for subset, s in items
            ]
            for tier, items in buckets.items()
        }
        payload["meta"] = {
            "ops": list(OPS.keys()),
            "weights": OPS,
            "hard_ops": sorted(HARD_OPS),
            "size_bonus_per_step": SIZE_BONUS_PER_STEP,
            "hard_op_bonus": HARD_OP_BONUS,
            "tier_thresholds": {"easy_max": EASY_MAX, "medium_max": MEDIUM_MAX},
            "min_size": args.min_size,
            "max_size": args.max_size,
            "total_subsets": len(subsets),
            "counts": {tier: len(items) for tier, items in buckets.items()},
        }
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"Wrote classified subsets to {args.json}")


if __name__ == "__main__":
    main()
