#!/usr/bin/env python3
"""OpenHands agent inference mode for SWE-fficiency.

Integrates the OpenHands Agent SDK into the official inference harness.
Instead of running a single shell command inside a Docker container,
this mode:

1. Builds a layered agent-server image on the base SWE-fficiency image
2. Creates a ResourceLimitedDockerWorkspace with CPU/mem limits
3. Runs a multi-turn Agent conversation loop
4. Extracts the git patch using the official diff format
5. Writes both official output (patch.diff + logs) and OpenHands
   trajectory output (output.jsonl)

Usage (via custom.py):
    python scripts/inference/custom.py \\
        --mode openhands \\
        --run-id my_run \\
        --llm-config scripts/inference/llm_configs/bedrock.json \\
        --instance-ids numpy__numpy-11720
"""

from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import multiprocessing
import os
import platform as platform_mod
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Template

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parents[1]

sys.path.insert(0, str(SCRIPTS_DIR))

from openhands_config import (
    CONVERSATION_TIMEOUT,
    DEFAULT_BUILD_TARGET,
    DEFAULT_CPUS_PER_WORKER,
    DEFAULT_CPUS_TO_SKIP,
    DEFAULT_MAX_FAKE_RESPONSES,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MEM_LIMIT,
    ENV_SETUP_COMMANDS,
    GIT_SETUP_COMMANDS,
)
from openhands_image_builder import cleanup_sdist, ensure_image
from openhands_output import (
    OpenHandsResult,
    convert_to_predictions_jsonl,
    write_error_output,
    write_eval_output,
)

from swefficiency.observability import setup_helicone


def _load_llm(config_path: Path):
    """Load LLM from a JSON config file using Pydantic validation."""
    from openhands.sdk import LLM

    return LLM.model_validate_json(config_path.read_text())


def _render_prompt(instance: dict, prompt_template_path: Path) -> str:
    """Render the Jinja2 instruction prompt for the agent."""
    template_text = prompt_template_path.read_text()
    template = Template(template_text)

    repo = instance.get("repo", "")
    version = instance.get("version", "")
    repo_dir = f"{repo.replace('/', '__')}__{version}" if repo else "testbed"

    return template.render(
        repo_dir=repo_dir,
        workload=instance.get("workload", ""),
        test_cmd=instance.get("test_cmd", ""),
        rebuild_cmd=instance.get("rebuild_cmd", ""),
        conda_env="testbed",
    )


def _fake_user_response(conversation, fake_count: int) -> str:
    """Generate a fake user response to keep the agent going."""
    msg = (
        "Please continue working on the task. "
        "If you think you have completed the task, use the finish tool. "
        "NEVER ASK FOR HUMAN HELP."
    )
    if fake_count >= 2:
        msg += ' If you want to give up, use the "finish" tool and explain why.'
    return msg


def _agent_finished_with_finish_action(events) -> bool:
    """Check if the agent's last action was a FinishAction (walks events in reverse)."""
    for event in reversed(list(events)):
        event_cls = type(event).__name__
        if "ActionEvent" in event_cls or "Action" in event_cls:
            return (
                "FinishAction" in event_cls
                or "finish" in str(getattr(event, "action", "")).lower()
            )
        if "ObservationEvent" in event_cls or "Observation" in event_cls:
            continue
        break
    return False


def _agent_sent_message(events) -> bool:
    """Check if the agent's last event was a message (walks events in reverse)."""
    for event in reversed(list(events)):
        event_cls = type(event).__name__
        if "Message" in event_cls:
            return True
        if "Action" in event_cls or "Observation" in event_cls:
            return False
    return False


# ── Git helper ─────────────────────────────────────────────────────────
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PATCH_SIZE_WARN_BYTES = 1_048_576  # 1 MiB soft cap


class WorkspaceCommandError(RuntimeError):
    """Raised when a workspace command fails with a non-zero exit code."""

    def __init__(self, cmd: str, exit_code: int, stderr: str) -> None:
        self.cmd = cmd
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"Command failed (exit {exit_code}): {cmd}\nstderr: {stderr}")


def _run_cmd(workspace, cmd: str, *, critical: bool = True) -> str:
    """Execute *cmd* in the workspace, return stdout.

    If *critical* is True (default), raises WorkspaceCommandError on failure.
    If False, logs a warning and returns empty string.
    """
    result = workspace.execute_command(cmd)

    if result.timeout_occurred:
        msg = f"Command timed out: {cmd}"
        if critical:
            raise WorkspaceCommandError(cmd, -1, msg)
        logger.warning(msg)
        return ""

    if result.exit_code != 0:
        if critical:
            raise WorkspaceCommandError(cmd, result.exit_code, result.stderr)
        logger.warning(
            "Non-critical command failed (exit %d): %s\nstderr: %s",
            result.exit_code,
            cmd,
            result.stderr,
        )
        return ""

    return result.stdout.strip()


def _run_conversation_loop(conversation, max_fake_responses: int) -> None:
    """Multi-turn conversation loop with fake user responses.

    Mirrors openhands-benchmarks' fake_user_response.py logic:
    run → check FINISHED → check FinishAction → check message → fake respond.
    """
    fake_count = 0
    while True:
        conversation.run(timeout=CONVERSATION_TIMEOUT)

        status = conversation.state.execution_status
        if status.name != "FINISHED":
            logger.info("Conversation ended with status: %s", status.name)
            break

        events = list(conversation.state.events)
        if not events:
            break

        if _agent_finished_with_finish_action(events):
            logger.info("Agent finished with FinishAction")
            break

        if not _agent_sent_message(events):
            logger.info("Agent did not send a message, stopping")
            break

        if fake_count >= max_fake_responses:
            logger.info("Max fake responses reached (%d)", max_fake_responses)
            break

        fake_msg = _fake_user_response(conversation, fake_count)
        conversation.send_message(fake_msg)
        fake_count += 1

    logger.info("Conversation completed after %d fake responses", fake_count)


def _extract_patch(
    workspace, pre_agent_commit: str, working_dir: str
) -> tuple[str, list[str]]:
    """Extract git patch of agent-only changes.

    Returns (patch_text, warnings). Diffs the working tree against the
    pre-agent commit so only the agent's edits are captured.
    """
    warnings: list[str] = []

    head_check = workspace.execute_command(f"test -f {working_dir}/.git/HEAD")
    if head_check.exit_code != 0:
        warnings.append("No .git/HEAD found — workspace git repo may be corrupted")
        logger.warning("_extract_patch: %s", warnings[-1])
        return "", warnings

    _run_cmd(
        workspace,
        f"cd {working_dir} && grep -qF '__pycache__/' .git/info/exclude 2>/dev/null"
        f" || printf '__pycache__/\\n*.pyc\\n*.pyo\\n.pytest_cache/\\n' >> .git/info/exclude",
        critical=False,
    )

    add_result = workspace.execute_command(f"cd {working_dir} && git add -A")
    if add_result.exit_code != 0:
        warnings.append(
            f"git add -A failed (exit {add_result.exit_code}): {add_result.stderr}"
        )
        logger.warning("_extract_patch: %s", warnings[-1])

    status_output = _run_cmd(
        workspace, f"cd {working_dir} && git status --porcelain", critical=False
    )

    try:
        diff_result = workspace.execute_command(
            f"cd {working_dir} && git --no-pager diff --no-color {pre_agent_commit}"
        )
    except Exception as e:
        warnings.append(f"git diff raised exception: {e}")
        logger.error("_extract_patch: %s", warnings[-1])
        return "", warnings

    if diff_result.exit_code != 0:
        warnings.append(
            f"git diff exited {diff_result.exit_code}: {diff_result.stderr}"
        )
        logger.error("_extract_patch: %s", warnings[-1])
        return "", warnings

    patch_text = diff_result.stdout.strip() if diff_result.stdout else ""

    if not patch_text and status_output:
        warnings.append(
            f"git diff is empty but git status shows changes: {status_output[:500]}"
        )
        logger.warning("_extract_patch: %s", warnings[-1])

    patch_bytes = len(patch_text.encode("utf-8"))
    if patch_bytes > _PATCH_SIZE_WARN_BYTES:
        warnings.append(
            f"Patch is {patch_bytes:,} bytes ({patch_bytes / 1_048_576:.1f} MiB) — "
            "may include non-agent changes"
        )
        logger.warning("_extract_patch: %s", warnings[-1])

    return patch_text, warnings


def _capture_conversation_archive(workspace, instance_id: str, log_dir: Path) -> None:
    """Capture /workspace/conversations/ from runtime as tar.gz.

    Mirrors openhands-benchmarks' _capture_conversation_archive() logic:
    runs tar+base64 inside container, decodes on host.
    """
    try:
        conv_cmd = (
            "cd / && "
            "if [ -d workspace/conversations ]; then "
            "tar -czf - workspace/conversations | base64; "
            "else echo ''; fi"
        )
        result = workspace.execute_command(conv_cmd)

        if result.exit_code == 0 and result.stdout.strip():
            conv_dir = log_dir.parent / "conversations"
            conv_dir.mkdir(parents=True, exist_ok=True)
            conv_tar = conv_dir / f"{instance_id}.tar.gz"
            conv_tar.write_bytes(base64.b64decode(result.stdout.strip()))
            logger.info("Saved conversation archive: %s", conv_tar)
        else:
            logger.debug("No conversation archive for %s", instance_id)
    except Exception as e:
        logger.warning(
            "Failed to capture conversation archive for %s: %s", instance_id, e
        )


def process_instance_openhands(
    *,
    instance: dict,
    llm_config_path: Path,
    log_root: Path,
    cpu_group: list[int] | None,
    cpu_groups_queue: Any | None,
    max_iterations: int,
    max_fake_responses: int,
    mem_limit: str,
    cpus_per_worker: int,
    build_target: str,
    force_build: bool,
    cleanup_images: bool,
    prompt_template_path: Path,
    model_name: str,
    output_jsonl: Path,
    output_errors_jsonl: Path,
) -> dict:
    """Process a single SWE-fficiency instance using OpenHands agent."""
    from openhands.sdk import Agent, Conversation
    from openhands.tools.preset.default import get_default_tools
    from openhands.workspace import DockerWorkspace

    instance_id = instance["instance_id"]
    log_dir = log_root / instance_id
    log_dir.mkdir(parents=True, exist_ok=True)

    instance_log_file = log_dir / "instance.log"
    file_handler = logging.FileHandler(instance_log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(file_handler)

    patch_path = log_dir / "patch.diff"
    if patch_path.exists():
        logger.info("[SKIP] %s: patch already exists", instance_id)
        return {
            "instance_id": instance_id,
            "status": "skipped",
            "patch": str(patch_path),
        }

    logger.info("[START] %s", instance_id)
    start_time = time.time()

    workspace = None
    try:
        agent_server_image, base_image = ensure_image(
            instance_id, target=build_target, force_build=force_build
        )

        cpuset_str = ",".join(str(c) for c in cpu_group) if cpu_group else None
        nano_cpus = int(cpus_per_worker * 1e9) if cpu_group else None

        from openhands_workspace import ResourceLimitedDockerWorkspace

        workspace = ResourceLimitedDockerWorkspace(
            server_image=agent_server_image,
            working_dir="/workspace",
            forward_env=[
                "DEBUG",
                "AWS_BEARER_TOKEN_BEDROCK",
                "AWS_BEDROCK_RUNTIME_ENDPOINT",
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN",
                "AWS_DEFAULT_REGION",
                "AWS_REGION",
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "GEMINI_API_KEY",
                "HELICONE_API_KEY",
                "HELICONE_API_BASE",
                "HELICONE_USER",
            ],
            cleanup_image=cleanup_images,
            platform=f"linux/{'arm64' if __import__('platform').machine() in ('aarch64', 'arm64') else 'amd64'}",
            cpuset_cpus=cpuset_str,
            nano_cpus=nano_cpus,
            mem_limit_override=mem_limit,
            health_check_timeout=300.0,
        )
        workspace._cpu_group = cpu_group
        workspace._cpu_groups_queue = cpu_groups_queue
        if cleanup_images:
            workspace._images_to_cleanup = [agent_server_image]

        repo = instance.get("repo", "")
        version = instance.get("version", "")
        repo_dir = f"{repo.replace('/', '__')}__{version}" if repo else "testbed"
        working_dir = f"/workspace/{repo_dir}"

        # ── Non-critical setup (git config, env vars) ──────────────
        for cmd in GIT_SETUP_COMMANDS + ENV_SETUP_COMMANDS:
            _run_cmd(workspace, cmd, critical=False)

        # ── Critical setup (workspace copy + git state) ────────────
        # Fix permissions on /testbed/ files created during image build
        # (e.g. .pdm-build owned by root with 700 perms) before copying.
        _run_cmd(workspace, "chmod -R a+rX /testbed/ 2>/dev/null || true", critical=False)
        # cp may exit 1 due to permission-denied on non-essential dirs
        # (e.g. .pdm-build), so we make it non-critical and verify .git below.
        _run_cmd(workspace, f"cp -r /testbed/. {working_dir}/", critical=False)
        _run_cmd(workspace, f"cd {working_dir} && git reset --hard")
        _run_cmd(
            workspace,
            f"cd {working_dir} && git remote remove origin 2>/dev/null || true",
            critical=False,
        )

        # ── Verify .git/HEAD exists (proves git repo is intact) ────
        _run_cmd(workspace, f"test -f {working_dir}/.git/HEAD")

        # ── Capture pre-agent commit for accurate diff later ───────
        raw_sha = _run_cmd(workspace, f"cd {working_dir} && git rev-parse HEAD")
        if not _SHA_RE.match(raw_sha):
            raise WorkspaceCommandError(
                "git rev-parse HEAD",
                -1,
                f"Expected 40-char hex SHA, got: {raw_sha!r}",
            )
        pre_agent_commit = raw_sha
        logger.info("[SETUP] %s: pre_agent_commit=%s", instance_id, pre_agent_commit)

        llm = _load_llm(llm_config_path)

        tools = get_default_tools(enable_browser=False)

        agent = Agent(
            llm=llm,
            tools=tools,
            system_prompt_kwargs={"cli_mode": True},
        )

        events_log: list[Any] = []

        def on_event(event: Any) -> None:
            events_log.append(event)

        conversation = Conversation(
            agent=agent,
            workspace=workspace,
            callbacks=[on_event],
            max_iteration_per_run=max_iterations,
            delete_on_close=False,
        )

        instruction = _render_prompt(instance, prompt_template_path)
        (log_dir / "openhands_prompt.txt").write_text(instruction)

        conversation.send_message(instruction)
        conversation_error = None
        try:
            _run_conversation_loop(conversation, max_fake_responses)
        except Exception as conv_exc:
            conversation_error = str(conv_exc)
            logger.warning(
                "[WARN] %s: conversation ended with: %s",
                instance_id,
                conversation_error,
            )

        git_patch, extraction_warnings = _extract_patch(
            workspace, pre_agent_commit, working_dir
        )

        if git_patch:
            patch_path.write_text(git_patch, encoding="utf-8")
            written_size = patch_path.stat().st_size
            expected_size = len(git_patch.encode("utf-8"))
            if written_size != expected_size:
                extraction_warnings.append(
                    f"Patch file size mismatch: wrote {written_size}, "
                    f"expected {expected_size}"
                )
                logger.error(
                    "[PATCH] %s: %s", instance_id, extraction_warnings[-1]
                )

        cost = llm.metrics.accumulated_cost if hasattr(llm, "metrics") else 0.0
        metrics = {}
        if hasattr(conversation, "conversation_stats"):
            stats = conversation.conversation_stats
            if hasattr(stats, "get_combined_metrics"):
                raw_metrics = stats.get_combined_metrics()
                # Serialize Pydantic model to dict (avoids string serialization bug)
                if hasattr(raw_metrics, "model_dump"):
                    metrics = raw_metrics.model_dump()
                elif isinstance(raw_metrics, dict):
                    metrics = raw_metrics
                else:
                    metrics = {}
                # Prefer conversation_stats cost over llm.metrics cost
                # (they may be different Metrics objects)
                stats_cost = getattr(raw_metrics, "accumulated_cost", None)
                if stats_cost and stats_cost > 0:
                    cost = stats_cost

        history_serialized = []
        for evt in events_log:
            try:
                if hasattr(evt, "model_dump"):
                    history_serialized.append(evt.model_dump())
                elif hasattr(evt, "__dict__"):
                    history_serialized.append(
                        {k: str(v) for k, v in evt.__dict__.items()}
                    )
                else:
                    history_serialized.append(str(evt))
            except Exception:
                history_serialized.append(str(evt))

        status = "success" if not conversation_error else "max_iterations"
        result = OpenHandsResult(
            instance_id=instance_id,
            status=status,
            patch_path=str(patch_path),
            git_patch=git_patch,
            instruction=instruction,
            history=history_serialized,
            metrics=metrics,
            cost=cost,
            model_name=model_name,
            extraction_warnings=extraction_warnings,
        )
        write_eval_output(result, output_jsonl)

        elapsed = time.time() - start_time
        logger.info(
            "[OK] %s: %.1fs, patch=%d bytes", instance_id, elapsed, len(git_patch)
        )

        try:
            conversation.close()
        except Exception:
            pass

        _capture_conversation_archive(workspace, instance_id, log_dir)

        return {
            "instance_id": instance_id,
            "status": status,
            "patch": str(patch_path),
            "cost": cost,
            "elapsed_seconds": elapsed,
        }

    except Exception as exc:
        logger.exception("[ERR] %s: %s", instance_id, exc)
        write_error_output(instance_id, str(exc), output_errors_jsonl)
        return {"instance_id": instance_id, "status": "error", "error": str(exc)}

    finally:
        logging.getLogger().removeHandler(file_handler)
        file_handler.close()
        if workspace is not None:
            try:
                workspace.cleanup()
            except Exception:
                logger.debug("Workspace cleanup failed for %s", instance_id)


def _divide_cpus(
    num_workers: int, cpus_per_worker: int, cpus_to_skip: int
) -> list[list[int]]:
    """Divide available CPUs among workers (simple linear, not NUMA-aware)."""
    try:
        available = sorted(os.sched_getaffinity(0))
    except AttributeError:
        available = list(range(multiprocessing.cpu_count()))
    usable = [c for c in available if c >= cpus_to_skip]

    if len(usable) < num_workers * cpus_per_worker:
        logger.warning(
            "Not enough CPUs: need %d, have %d usable. Falling back to no pinning.",
            num_workers * cpus_per_worker,
            len(usable),
        )
        return []

    groups = []
    for i in range(num_workers):
        start = i * cpus_per_worker
        groups.append(usable[start : start + cpus_per_worker])
    return groups


def run_openhands_inference(
    *,
    instances: list[dict],
    llm_config_path: Path,
    run_id: str,
    output_dir: Path,
    num_workers: int = 2,
    cpus_per_worker: int = DEFAULT_CPUS_PER_WORKER,
    cpus_to_skip: int = DEFAULT_CPUS_TO_SKIP,
    mem_limit: str = DEFAULT_MEM_LIMIT,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_fake_responses: int = DEFAULT_MAX_FAKE_RESPONSES,
    build_target: str = DEFAULT_BUILD_TARGET,
    force_build: bool = False,
    cleanup_images: bool = True,
    prompt_template: Path | None = None,
    model_name: str = "openhands-agent",
    disable_cpu_pinning: bool = False,
) -> list[dict]:
    """Run OpenHands agent inference on a list of SWE-fficiency instances."""
    setup_helicone()

    run_log_dir = output_dir / run_id / "openhands"
    run_log_dir.mkdir(parents=True, exist_ok=True)

    output_jsonl = run_log_dir / "output.jsonl"
    output_errors_jsonl = run_log_dir / "output_errors.jsonl"
    predictions_jsonl = run_log_dir / "predictions.jsonl"

    metadata = {
        "run_id": run_id,
        "model_name": model_name,
        "llm_config": str(llm_config_path),
        "max_iterations": max_iterations,
        "max_fake_responses": max_fake_responses,
        "num_workers": num_workers,
        "cpus_per_worker": cpus_per_worker,
        "mem_limit": mem_limit,
        "build_target": build_target,
        "num_instances": len(instances),
        "instance_ids": [inst["instance_id"] for inst in instances],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        llm_cfg = json.loads(llm_config_path.read_text())
        metadata["llm_model"] = llm_cfg.get("model", "")
    except Exception:
        pass
    (run_log_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    if prompt_template is None:
        prompt_template = SCRIPTS_DIR / "templates" / "openhands_prompt.j2"

    cpu_groups: list[list[int]] = []
    cpu_groups_queue = None

    if not disable_cpu_pinning:
        try:
            cpu_groups = _divide_cpus(num_workers, cpus_per_worker, cpus_to_skip)
        except Exception as exc:
            logger.warning("CPU division failed, disabling pinning: %s", exc)

    if cpu_groups:
        manager = multiprocessing.Manager()
        cpu_groups_queue = manager.Queue()
        for group in cpu_groups:
            cpu_groups_queue.put(group)

    logger.info(
        "Starting OpenHands inference: %d instances, %d workers, model=%s",
        len(instances),
        num_workers,
        model_name,
    )

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_map = {}
        for instance in instances:
            cpu_group = None
            if cpu_groups_queue is not None:
                try:
                    cpu_group = cpu_groups_queue.get_nowait()
                except Exception:
                    pass

            future = executor.submit(
                process_instance_openhands,
                instance=instance,
                llm_config_path=llm_config_path,
                log_root=run_log_dir,
                cpu_group=cpu_group,
                cpu_groups_queue=cpu_groups_queue,
                max_iterations=max_iterations,
                max_fake_responses=max_fake_responses,
                mem_limit=mem_limit,
                cpus_per_worker=cpus_per_worker,
                build_target=build_target,
                force_build=force_build,
                cleanup_images=cleanup_images,
                prompt_template_path=prompt_template,
                model_name=model_name,
                output_jsonl=output_jsonl,
                output_errors_jsonl=output_errors_jsonl,
            )
            future_map[future] = instance["instance_id"]

        for future in concurrent.futures.as_completed(future_map):
            iid = future_map[future]
            try:
                result = future.result()
                results.append(result)
                status = result.get("status", "unknown")
                if status == "success":
                    print(f"[OK] {iid}: {result.get('patch', 'no patch')}")
                elif status == "skipped":
                    print(f"[SKIP] {iid}")
                else:
                    print(
                        f"[ERR] {iid}: {result.get('error', 'unknown')}",
                        file=sys.stderr,
                    )
            except Exception as exc:
                print(f"[ERR] {iid}: {exc}", file=sys.stderr)
                results.append(
                    {"instance_id": iid, "status": "error", "error": str(exc)}
                )

    cleanup_sdist()

    summary_path = run_log_dir / "summary.json"
    summary_path.write_text(json.dumps(results, indent=2))

    if output_jsonl.exists():
        count = convert_to_predictions_jsonl(
            output_jsonl, predictions_jsonl, model_name
        )
        print(f"Predictions JSONL: {predictions_jsonl} ({count} entries)")

    print(f"Summary: {summary_path}")
    print(f"Trajectories: {output_jsonl}")

    return results
