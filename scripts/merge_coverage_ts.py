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

"""TypeScript analog of ``merge_coverage.py``.

Reads per-test Vitest v8 ``coverage-final.json`` files plus the instance's
git diff, then writes ``covering_tests.txt`` (one ``test_name<TAB>file:line``
row per pair). Stage III of the TypeScript pipeline consumes this to drop
instances whose patched code is not exercised by any test (Paper App. C.3).

Input layout (per instance):
    <coverage_root>/<instance_id>/
        diff.patch                 # full unified diff of the gold patch
        per_test/<test_name>.json  # vitest --coverage --coverage.reporter=json
                                   # output (istanbul-format coverage-final.json)

Output:
    <coverage_root>/<instance_id>/covering_tests.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_modified_lines(diff_text: str) -> dict[str, set[int]]:
    """Return ``{file_path: {line_numbers_added_or_modified}}`` from a unified diff."""
    result: dict[str, set[int]] = {}
    current_file: str | None = None
    new_lineno = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            m = _DIFF_FILE_RE.match(line)
            current_file = m.group(1) if m else None
            continue
        if current_file is None:
            continue
        if line.startswith("@@"):
            m = _HUNK_HEADER_RE.match(line)
            if m:
                new_lineno = int(m.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.setdefault(current_file, set()).add(new_lineno)
            new_lineno += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            new_lineno += 1
    return result


def parse_v8_coverage_json(path: Path) -> dict[str, set[int]]:
    """Return ``{file_path: {executed_line_numbers}}`` for a single Vitest v8 coverage-final.json file.

    Vitest's v8 coverage provider emits istanbul-format JSON:
        {
          "<abs_path>": {
            "path": "<abs_path>",
            "statementMap": {"0": {"start": {"line": 1, "column": 0}, "end": ...}},
            "s": {"0": 3, "1": 0, ...}   # hit counts per statement index
            ...
          },
          ...
        }
    A statement is executed iff ``s[i] > 0``; its line is ``statementMap[i].start.line``.
    """
    with open(path) as f:
        data = json.load(f)
    out: dict[str, set[int]] = {}
    for file_key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        file_path = entry.get("path") or file_key
        if not file_path:
            continue
        statement_map = entry.get("statementMap") or {}
        hits = entry.get("s") or {}
        executed: set[int] = set()
        for stmt_id, count in hits.items():
            try:
                if int(count) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            stmt = statement_map.get(stmt_id)
            if not isinstance(stmt, dict):
                continue
            start = stmt.get("start")
            if not isinstance(start, dict):
                continue
            line = start.get("line")
            if isinstance(line, int):
                executed.add(line)
        if executed:
            out[file_path] = executed
    return out


def _normalize(path: str) -> str:
    return path.lstrip("./")


def write_covering_tests(
    diff_path: Path,
    per_test_dir: Path,
    output_path: Path,
) -> int:
    """Compute covering tests for ``diff_path`` against every JSON in ``per_test_dir``."""
    diff_text = diff_path.read_text(errors="ignore")
    modified = parse_modified_lines(diff_text)
    modified_norm = {_normalize(k): v for k, v in modified.items()}
    if not modified_norm:
        logger.warning("No modified lines parsed from %s", diff_path)
        output_path.write_text("")
        return 0

    rows: list[str] = []
    for json_file in sorted(per_test_dir.glob("*.json")):
        test_name = json_file.stem
        covered = parse_v8_coverage_json(json_file)
        for file_path, lines in covered.items():
            norm_file = _normalize(file_path)
            target_lines = modified_norm.get(norm_file)
            if not target_lines:
                # Also try matching by basename suffix (vitest emits absolute
                # paths, diffs are repo-relative).
                for diff_file, dlines in modified_norm.items():
                    if norm_file.endswith("/" + diff_file) or norm_file == diff_file:
                        target_lines = dlines
                        norm_file = diff_file
                        break
            if not target_lines:
                continue
            hit_lines = sorted(target_lines & lines)
            for ln in hit_lines:
                rows.append(f"{test_name}\t{norm_file}:{ln}")

    output_path.write_text("\n".join(rows))
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-root", required=True, type=Path)
    parser.add_argument("--instance-id", required=True)
    args = parser.parse_args(argv)

    inst_dir = args.coverage_root / args.instance_id
    diff_path = inst_dir / "diff.patch"
    per_test_dir = inst_dir / "per_test"
    output_path = inst_dir / "covering_tests.txt"

    if not diff_path.exists():
        print(f"Missing {diff_path}", file=sys.stderr)
        return 1
    if not per_test_dir.exists():
        print(f"Missing {per_test_dir}", file=sys.stderr)
        return 1

    n = write_covering_tests(diff_path, per_test_dir, output_path)
    print(f"Wrote {n} covering-test rows to {output_path}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
