"""Output handling for OpenHands inference mode.

Writes BOTH:
1. Official-format files: ``patch.diff``, logs per instance
2. OpenHands-format: ``output.jsonl`` with full trajectory

Also provides conversion to prediction JSONL for downstream evaluation.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Thread lock for safe JSONL writes from parallel workers
_output_lock = threading.Lock()


@dataclass
class OpenHandsResult:
    """Per-instance result combining official + OpenHands output data."""

    instance_id: str
    status: str  # "success", "error", "skipped"
    patch_path: str | None = None
    git_patch: str | None = None
    error: str | None = None

    # OpenHands trajectory data
    instruction: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0
    model_name: str = ""
    attempt: int = 1
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def write_eval_output(
    result: OpenHandsResult,
    output_jsonl: Path,
) -> None:
    """Append one result to the output.jsonl file (thread-safe)."""
    record = {
        "instance_id": result.instance_id,
        "attempt": result.attempt,
        "test_result": {"git_patch": result.git_patch or ""},
        "instruction": result.instruction,
        "error": result.error,
        "history": result.history,
        "metrics": result.metrics,
        "metadata": {
            "model_name": result.model_name,
            "cost": result.cost,
            "timestamp": result.timestamp,
        },
    }
    line = json.dumps(record, default=str) + "\n"

    with _output_lock:
        with open(output_jsonl, "a") as f:
            f.write(line)


def write_error_output(
    instance_id: str,
    error: str,
    output_errors_jsonl: Path,
) -> None:
    """Append one error record to output_errors.jsonl (thread-safe)."""
    record = {
        "instance_id": instance_id,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    line = json.dumps(record, default=str) + "\n"

    with _output_lock:
        with open(output_errors_jsonl, "a") as f:
            f.write(line)


def convert_to_predictions_jsonl(
    output_jsonl: Path,
    predictions_jsonl: Path,
    model_name: str,
) -> int:
    """Convert output.jsonl → predictions.jsonl for ``swefficiency eval``.

    Reads each line from output.jsonl, extracts the git_patch, and writes
    a prediction record in the format expected by the evaluation harness.

    Returns:
        Number of predictions written.
    """
    count = 0
    with open(output_jsonl) as fin, open(predictions_jsonl, "w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line")
                continue

            git_patch = record.get("test_result", {}).get("git_patch", "")
            instance_id = record.get("instance_id", "")

            if not instance_id:
                continue

            prediction = {
                "instance_id": instance_id,
                "model_patch": git_patch,
                "model_name_or_path": model_name,
            }
            fout.write(json.dumps(prediction) + "\n")
            count += 1

    logger.info(
        "Converted %d predictions to %s",
        count,
        predictions_jsonl,
    )
    return count
