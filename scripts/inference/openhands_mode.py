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

import concurrent.futures
import json
import logging
import multiprocessing
import os
import sys
import time
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
            return "FinishAction" in event_cls or "finish" in str(
                getattr(event, "action", "")
            ).lower()
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


def _extract_patch(workspace, instance: dict, working_dir: str) -> str:
    """Extract git patch from the workspace using official diff format.

    Uses ``git diff --binary`` against base_commit for eval compatibility.
    """
    base_commit = instance.get("base_commit", "")

    commands = [
        f"cd {working_dir} && git add -A",
    ]

    binary_extensions = ("*.o", "*.so", "*.a", "*.dylib", "*.dll", "*.pyc", "*.pyo")
    for ext in binary_extensions:
        commands.append(
            f"cd {working_dir} && git diff --cached --name-only --diff-filter=A "
            f"| grep '{ext}$' | xargs -r git reset HEAD -- 2>/dev/null || true"
        )

    commands.append(
        f"cd {working_dir} && git commit --no-verify --allow-empty -m 'agent patch'"
    )

    if base_commit:
        diff_cmd = f"cd {working_dir} && git --no-pager diff --no-color {base_commit} HEAD"
    else:
        diff_cmd = f"cd {working_dir} && git --no-pager diff --no-color HEAD~1 HEAD"
    commands.append(diff_cmd)

    for cmd in commands[:-1]:
        try:
            result = workspace.execute_command(cmd)
            if hasattr(result, "exit_code") and result.exit_code != 0:
                logger.debug("Command returned %d: %s", result.exit_code, cmd)
        except Exception:
            logger.debug("Command failed (non-critical): %s", cmd)

    try:
        result = workspace.execute_command(commands[-1])
        patch_text = result.stdout if hasattr(result, "stdout") else str(result)
        return patch_text.strip() if patch_text else ""
    except Exception:
        logger.exception("Failed to extract patch")
        return ""


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

    patch_path = log_dir / "patch.diff"
    if patch_path.exists():
        logger.info("[SKIP] %s: patch already exists", instance_id)
        return {"instance_id": instance_id, "status": "skipped", "patch": str(patch_path)}

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
            forward_env=["DEBUG"],
            cleanup_image=cleanup_images,
            platform="linux/amd64",
            cpuset_cpus=cpuset_str,
            nano_cpus=nano_cpus,
            mem_limit_override=mem_limit,
        )
        workspace._cpu_group = cpu_group
        workspace._cpu_groups_queue = cpu_groups_queue
        if cleanup_images:
            workspace._images_to_cleanup = [agent_server_image]

        repo = instance.get("repo", "")
        version = instance.get("version", "")
        repo_dir = f"{repo.replace('/', '__')}__{version}" if repo else "testbed"
        working_dir = f"/workspace/{repo_dir}"

        setup_commands = [
            f"cp -r /testbed/. {working_dir}/",
            f"cd {working_dir} && git reset --hard",
            f"cd {working_dir} && git remote remove origin 2>/dev/null || true",
        ]
        for cmd in GIT_SETUP_COMMANDS + ENV_SETUP_COMMANDS + setup_commands:
            try:
                workspace.execute_command(cmd)
            except Exception:
                logger.debug("Setup command failed (non-critical): %s", cmd)

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
        _run_conversation_loop(conversation, max_fake_responses)

        git_patch = _extract_patch(workspace, instance, working_dir)

        if git_patch:
            patch_path.write_text(git_patch)

        cost = llm.metrics.accumulated_cost if hasattr(llm, "metrics") else 0.0
        metrics = {}
        if hasattr(conversation, "conversation_stats"):
            stats = conversation.conversation_stats
            if hasattr(stats, "get_combined_metrics"):
                metrics = stats.get_combined_metrics()

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

        result = OpenHandsResult(
            instance_id=instance_id,
            status="success",
            patch_path=str(patch_path),
            git_patch=git_patch,
            instruction=instruction,
            history=history_serialized,
            metrics=metrics,
            cost=cost,
            model_name=model_name,
        )
        write_eval_output(result, output_jsonl)

        elapsed = time.time() - start_time
        logger.info("[OK] %s: %.1fs, patch=%d bytes", instance_id, elapsed, len(git_patch))

        try:
            conversation.close()
        except Exception:
            pass

        return {
            "instance_id": instance_id,
            "status": "success",
            "patch": str(patch_path),
            "cost": cost,
            "elapsed_seconds": elapsed,
        }

    except Exception as exc:
        logger.exception("[ERR] %s: %s", instance_id, exc)
        write_error_output(instance_id, str(exc), output_errors_jsonl)
        return {"instance_id": instance_id, "status": "error", "error": str(exc)}

    finally:
        if workspace is not None:
            try:
                workspace.cleanup()
            except Exception:
                logger.debug("Workspace cleanup failed for %s", instance_id)


def _divide_cpus(num_workers: int, cpus_per_worker: int, cpus_to_skip: int) -> list[list[int]]:
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
    run_log_dir = output_dir / run_id / "openhands"
    run_log_dir.mkdir(parents=True, exist_ok=True)

    output_jsonl = run_log_dir / "output.jsonl"
    output_errors_jsonl = run_log_dir / "output_errors.jsonl"
    predictions_jsonl = run_log_dir / "predictions.jsonl"

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
                    print(f"[ERR] {iid}: {result.get('error', 'unknown')}", file=sys.stderr)
            except Exception as exc:
                print(f"[ERR] {iid}: {exc}", file=sys.stderr)
                results.append({"instance_id": iid, "status": "error", "error": str(exc)})

    cleanup_sdist()

    summary_path = run_log_dir / "summary.json"
    summary_path.write_text(json.dumps(results, indent=2))

    if output_jsonl.exists():
        count = convert_to_predictions_jsonl(output_jsonl, predictions_jsonl, model_name)
        print(f"Predictions JSONL: {predictions_jsonl} ({count} entries)")

    print(f"Summary: {summary_path}")
    print(f"Trajectories: {output_jsonl}")

    return results
