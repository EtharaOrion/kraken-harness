#!/usr/bin/env python3
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC_ROOT = Path("/Users/anshkataria/Desktop/23-july/Repo2RLEnv/datasets/kubectl-kinds-v1")
DST_ROOT = Path("/Users/anshkataria/Desktop/23-july/24-july/kubectl-kinds-v1")
VARIANTS = ("oracle-golden", "oracle-reference")
KNOWN_TAGS = ("error-invalid-args", "error-nonexistent", "happy-path", "workflow")


def find_task_dirs():
    out = []
    for task in sorted(SRC_ROOT.glob("task-*")):
        if not task.is_dir():
            continue
        for sub in task.iterdir():
            if sub.is_dir() and (sub / "task.toml").exists():
                out.append((task.name, sub))
                break
    return out


def latest_results_xml(task_uuid_dir: Path, variant: str):
    variant_dir = task_uuid_dir / "scoring" / variant
    if not variant_dir.exists():
        return None
    ts_dirs = sorted([d for d in variant_dir.iterdir() if d.is_dir()])
    if not ts_dirs:
        return None
    latest_ts = ts_dirs[-1]
    xmls = list(latest_ts.glob("*/verifier/results.xml"))
    return xmls[0] if xmls else None


def failing_classnames(xml_path: Path):
    if not xml_path or not xml_path.exists():
        return set()
    fails = set()
    for tc in ET.parse(xml_path).iter("testcase"):
        for child in tc:
            if child.tag in ("failure", "error"):
                cls = tc.get("classname")
                if cls:
                    fails.add(cls)
                break
    return fails


def tag_of(filename: str):
    for t in KNOWN_TAGS:
        if f"_{t}_" in filename:
            return t
    return None


def update_toml(toml_path: Path, new_total: int, new_tag_counts: dict):
    text = toml_path.read_text()
    text = re.sub(r"(?m)^(\s*tests_shipped\s*=\s*)\d+", rf"\g<1>{new_total}", text)
    lines = text.splitlines()
    in_counts = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[metadata.behaviour_tag_counts]"):
            in_counts = True
            continue
        if in_counts and stripped.startswith("[") and stripped.endswith("]"):
            in_counts = False
        if in_counts:
            m = re.match(r"(\s*)([A-Za-z0-9_-]+)(\s*=\s*)\d+", line)
            if m and m.group(2) in new_tag_counts:
                lines[i] = f"{m.group(1)}{m.group(2)}{m.group(3)}{new_tag_counts[m.group(2)]}"
    toml_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""))


def process_task(task_name: str, src_uuid: Path):
    fails = set()
    for v in VARIANTS:
        fails |= failing_classnames(latest_results_xml(src_uuid, v))

    dst_uuid = DST_ROOT / task_name / src_uuid.name
    if dst_uuid.exists():
        shutil.rmtree(dst_uuid)
    dst_uuid.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_uuid, dst_uuid, ignore=shutil.ignore_patterns("scoring"))

    tests_dir = dst_uuid / "tests"
    all_test_files = sorted(tests_dir.glob("test_kubectl_*.py"))
    original_total = len(all_test_files)

    removed = []
    for tf in all_test_files:
        if tf.stem in fails:
            tf.unlink()
            removed.append(tf.name)

    kept = sorted(tests_dir.glob("test_kubectl_*.py"))
    new_total = len(kept)
    new_tag_counts = {t: 0 for t in KNOWN_TAGS}
    for tf in kept:
        t = tag_of(tf.name)
        if t:
            new_tag_counts[t] += 1

    update_toml(dst_uuid / "task.toml", new_total, new_tag_counts)

    return {
        "task": task_name,
        "fails": len(fails),
        "removed": len(removed),
        "original_total": original_total,
        "new_total": new_total,
        "new_tag_counts": new_tag_counts,
    }


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    tasks = find_task_dirs()

    if not (SRC_ROOT / "task-12-no-ing-pvc").exists():
        print(f"src root not found: {SRC_ROOT}", file=sys.stderr)
        sys.exit(1)

    scored = []
    for name, sub in tasks:
        has_golden = latest_results_xml(sub, "oracle-golden") is not None
        has_ref = latest_results_xml(sub, "oracle-reference") is not None
        if has_golden and has_ref:
            scored.append((name, sub))

    print(f"tasks with both golden+ref scores: {len(scored)}")

    results = []
    for name, sub in scored:
        if only and name != only:
            continue
        r = process_task(name, sub)
        results.append(r)
        print(f"  {name:30s} fails={r['fails']:2d} removed={r['removed']:2d} "
              f"tests: {r['original_total']} -> {r['new_total']}")

    if results:
        totals = {
            "n": len(results),
            "orig_sum": sum(r["original_total"] for r in results),
            "new_sum": sum(r["new_total"] for r in results),
            "removed_sum": sum(r["removed"] for r in results),
        }
        print(f"\nprocessed {totals['n']} tasks | "
              f"tests: {totals['orig_sum']} -> {totals['new_sum']} "
              f"(-{totals['removed_sum']})")


if __name__ == "__main__":
    main()
