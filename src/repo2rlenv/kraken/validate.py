"""Deterministic admissibility check over the harvested corpus.

Every reference patch must be a well-formed unified diff whose hunk headers agree
with their bodies. A patch that does not apply makes the reward ceiling unreachable,
which is a broken task rather than a hard one.

This runs before any image is built, because rejecting a malformed instance after a
ten-minute build is a waste of the build.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def check_patch(patch: str) -> list:
    """Verify every hunk header against the lines that follow it."""
    problems = []
    lines = patch.split("\n")
    # Trailing empties are artifacts of the final newline and of blank lines after the
    # last hunk. Neither is diff content, and counting them as context inflates the
    # final hunk. An empty context line inside a hunk is a single space, not nothing.
    while lines and lines[-1] == "":
        lines.pop()
    i, hunk_index = 0, 0
    while i < len(lines):
        m = HUNK.match(lines[i])
        if not m:
            i += 1
            continue
        hunk_index += 1
        want_old = int(m.group(2) or 1)
        want_new = int(m.group(4) or 1)
        old = new = 0
        i += 1
        while i < len(lines):
            line = lines[i]
            if HUNK.match(line) or line.startswith("diff --git"):
                break
            if line.startswith("\\"):  # "\ No newline at end of file"
                i += 1
                continue
            if line.startswith("-"):
                old += 1
            elif line.startswith("+"):
                new += 1
            elif line.startswith(" ") or line == "":
                old += 1
                new += 1
            i += 1
        if old != want_old or new != want_new:
            problems.append(
                {
                    "hunk": hunk_index,
                    "header": m.group(0),
                    "declared_old": want_old,
                    "counted_old": old,
                    "declared_new": want_new,
                    "counted_new": new,
                }
            )
    if not patch.strip():
        problems.append({"reason": "empty_patch"})
    return problems


def main() -> int:
    rows, bad = [], 0
    for path in sorted((ROOT / "harvest").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            problems = check_patch(rec["patch"])
            test_problems = check_patch(rec["test_patch"]) if rec.get("test_patch") else []
            rows.append(
                {
                    "instance_id": rec["instance_id"],
                    "repo": rec["repo"],
                    "corpus_speedup": rec["speedup"],
                    "patch_ok": not problems,
                    "patch_problems": problems,
                    "test_patch_ok": not test_problems,
                    "test_patch_problems": test_problems,
                }
            )
            if problems or test_problems:
                bad += 1

    out = ROOT / "harvest" / "validation.json"
    out.write_text(
        json.dumps({"records": len(rows), "malformed": bad, "instances": rows}, indent=2),
        encoding="utf-8",
    )
    print(f"records {len(rows)}  malformed {bad}\n")
    for row in rows:
        if row["patch_ok"] and row["test_patch_ok"]:
            continue
        print(
            f"  {row['instance_id']:34} patch_ok={row['patch_ok']} "
            f"test_patch_ok={row['test_patch_ok']}"
        )
        for p in row["patch_problems"] + row["test_patch_problems"]:
            print(f"      {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
