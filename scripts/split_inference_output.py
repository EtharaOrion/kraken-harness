#!/usr/bin/env python3
"""Split inference output.jsonl into per-instance directories.

Creates structure:
    <run_dir>/openhands/<instance_id>/
        output.json            - full trajectory for this instance
        predictions.json       - prediction entry for eval harness
        metrics.json           - raw LLM metrics (token usage, cost)
        run_metadata.json      - run-level config + instance_id
        instance_metadata.json - computed summary (cost, tokens, status, patch_bytes)
        patch.diff             - git patch (already exists from inference)
        instance.log           - per-instance log (already exists)
"""

import json
import sys
from pathlib import Path


def split_output(run_dir: str) -> None:
    base = Path(run_dir) / "openhands"
    output_jsonl = base / "output.jsonl"
    predictions_jsonl = base / "predictions.jsonl"
    metadata_json = base / "metadata.json"

    if not output_jsonl.exists():
        print(f"No output.jsonl found in {base}")
        sys.exit(1)

    # Load run-level metadata (written during inference start)
    run_metadata: dict = {}
    if metadata_json.exists():
        run_metadata = json.loads(metadata_json.read_text())

    preds_by_id: dict = {}
    if predictions_jsonl.exists():
        for line in predictions_jsonl.open():
            line = line.strip()
            if line:
                d = json.loads(line)
                preds_by_id[d["instance_id"]] = d

    count = 0
    for line in output_jsonl.open():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        iid = record["instance_id"]
        inst_dir = base / iid
        inst_dir.mkdir(parents=True, exist_ok=True)

        # 1. output.json — full trajectory for this instance
        (inst_dir / "output.json").write_text(
            json.dumps(record, indent=2, default=str)
        )

        # 2. predictions.json — per-instance prediction
        if iid in preds_by_id:
            (inst_dir / "predictions.json").write_text(
                json.dumps(preds_by_id[iid], indent=2)
            )

        # 3. metrics.json — raw LLM metrics
        metrics = record.get("metrics", {})
        if metrics:
            (inst_dir / "metrics.json").write_text(
                json.dumps(metrics, indent=2, default=str)
            )

        # 4. run_metadata.json — copy of run-level metadata + instance-specific fields
        inst_run_meta = {
            **run_metadata,
            "instance_id": iid,
        }
        (inst_dir / "run_metadata.json").write_text(
            json.dumps(inst_run_meta, indent=2)
        )

        # 5. instance_metadata.json — computed summary
        meta = record.get("metadata", {})
        token_summary: dict = {}
        if isinstance(metrics, dict):
            token_usages = metrics.get("token_usages", [])
            if isinstance(token_usages, list):
                token_summary = {
                    "accumulated_cost": metrics.get("accumulated_cost", 0),
                    "prompt_tokens": sum(
                        t.get("prompt_tokens", 0)
                        for t in token_usages
                        if isinstance(t, dict)
                    ),
                    "completion_tokens": sum(
                        t.get("completion_tokens", 0)
                        for t in token_usages
                        if isinstance(t, dict)
                    ),
                    "total_tokens": sum(
                        t.get("prompt_tokens", 0) + t.get("completion_tokens", 0)
                        for t in token_usages
                        if isinstance(t, dict)
                    ),
                }

        instance_meta = {
            "instance_id": iid,
            "model_name": meta.get("model_name", ""),
            "run_id": run_metadata.get("run_id", ""),
            "cost_usd": meta.get("cost", 0),
            "timestamp": meta.get("timestamp", ""),
            "has_patch": bool(record.get("test_result", {}).get("git_patch", "")),
            "status": "success" if record.get("error") is None else "error",
            "patch_bytes": len(record.get("test_result", {}).get("git_patch", "")),
            "num_events": len(record.get("history", [])),
            "llm_model": run_metadata.get("llm_model", ""),
            "max_iterations": run_metadata.get("max_iterations", 0),
            **token_summary,
        }
        (inst_dir / "instance_metadata.json").write_text(
            json.dumps(instance_meta, indent=2)
        )

        count += 1
        print(f"  [{count}] {iid}: cost=${instance_meta['cost_usd']:.4f}, "
              f"events={instance_meta['num_events']}, "
              f"patch={instance_meta['patch_bytes']}B, "
              f"has_patch={instance_meta['has_patch']}")

    print(f"\nSplit {count} instances into per-instance directories under {base}/")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <run_dir>")
        print(f"  e.g.: {sys.argv[0]} logs/run_inference/glm5_full_20")
        sys.exit(1)
    split_output(sys.argv[1])
