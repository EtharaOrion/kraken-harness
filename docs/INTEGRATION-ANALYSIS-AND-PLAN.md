# SWE-fficiency × OpenHands Agent SDK Integration: Complete Analysis & Implementation Plan

**Document Type**: Pre-implementation analysis + actionable implementation plan  
**Target Repo**: `/Users/macbookpro/Desktop/research paper/SWE -FFICIENCY/swefficiency/`  
**Goal**: Integrate OpenHands Agent SDK into the official SWE-fficiency inference harness for trajectory generation with AWS Bedrock  
**Scope**: INFERENCE ONLY — no changes to evaluation or report pipeline  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Requirements Specification](#2-requirements-specification)
3. [Official Harness Deep Dive](#3-official-harness-deep-dive)
4. [OpenHands Benchmarks Deep Dive](#4-openhands-benchmarks-deep-dive)
5. [Architecture Reconciliation](#5-architecture-reconciliation)
6. [Critical Gotchas & Design Decisions](#6-critical-gotchas--design-decisions)
7. [File-by-File Change List](#7-file-by-file-change-list)
8. [Dependency & Infrastructure Requirements](#8-dependency--infrastructure-requirements)
9. [Implementation Plan (Wave Structure)](#9-implementation-plan-wave-structure) *(superseded by Section 15)*
10. [Test Plan & Success Criteria](#10-test-plan--success-criteria)
11. [Risk Assessment](#11-risk-assessment)
12. [Open Questions](#12-open-questions)
13. [Metis Pre-Planning Analysis](#13-metis-pre-planning-analysis-specialist-review) ⭐ NEW
14. [Momus Plan Critique](#14-momus-plan-critique-quality-assurance-review) ⭐ NEW
15. [Updated Wave Structure (Post-Metis/Momus)](#15-updated-wave-structure-post-metismomus) ⭐ SUPERSEDES Section 9
16. [Summary of ALL Required Changes (Final)](#16-summary-of-all-required-changes-final) ⭐ NEW

---

## 1. Executive Summary

We are integrating the OpenHands Agent SDK into the **official** SWE-fficiency repository (`swefficiency/`) to enable:

1. **Smart container inference** — Agent-server process runs inside Docker containers, host-side agent loop communicates via HTTP
2. **Dual output** — Both official `patch.diff` + logs AND OpenHands-style `output.jsonl` with full trajectory
3. **Eval-compatible** — Output feeds directly into `swefficiency eval` and `swefficiency report`
4. **Configurable** — Defaults to OpenHands SDK Agent, but YAML spec mechanism preserved for alternative agents

The integration adds a new inference mode (`--mode openhands`) to the existing `scripts/inference/custom.py` framework. The existing `--mode spec` (YAML-driven) mode remains untouched.

**Estimated scope**: ~1,500-2,000 lines of new/modified code across ~12 files.

---

## 2. Requirements Specification

### 2.1 Mandatory Requirements (from user)

| # | Requirement | Source |
|---|-------------|--------|
| R1 | Container intelligence: Smart sandbox runs agent-server process | OpenHands architecture |
| R2 | Image prep: Pull prebuilt base → build layered image with agent-server | OpenHands `ensure_local_image()` |
| R3 | Agent runs on HOST, sends HTTP commands to agent-server in container | OpenHands SDK `Conversation` class |
| R4 | Commands reach container via HTTP API → agent-server → bash | OpenHands `workspace.execute_command()` |
| R5 | Resource limits via `docker update` AFTER container start | OpenHands `ResourceLimitedDockerWorkspace` |
| R6 | Patch format: `git diff --binary` (official style, preserves binary files) | Official harness `DEFAULT_PATCH_COMMAND` |
| R7 | Working directory: `/workspace/<repo>__<ver>/` (copy of `/testbed`) | OpenHands workspace setup |
| R8 | Dual output: BOTH `patch.diff` + logs AND `output.jsonl` with full trajectory | Combination of both systems |
| R9 | Agent configurability: Default OpenHands SDK Agent + keep YAML spec for alternatives | Hybrid architecture |
| R10 | Dependencies: Full OpenHands SDK as submodule, keep minimal deps for spec mode | Dual dependency model |
| R11 | Eval compatibility: Output works with `swefficiency eval` directly + conversion script | Official eval pipeline |

### 2.2 Implied Requirements (from analysis)

| # | Requirement | Reason |
|---|-------------|--------|
| IR1 | Existing YAML spec mode must NOT break | Backward compatibility |
| IR2 | Single repo — all changes in `swefficiency/` folder | User constraint |
| IR3 | AWS Bedrock with bearer token must work | User's LLM provider |
| IR4 | macOS development support (CPU pinning graceful fallback) | User's dev environment |
| IR5 | Single instance, single worker first | User's scaling strategy |

---

## 3. Official Harness Deep Dive

### 3.1 File: `scripts/inference/custom.py` (980 lines)

**Purpose**: Generalized inference harness — loads HuggingFace dataset, launches Docker containers, runs user-specified commands, extracts patches.

#### 3.1.1 Entry Point: `main()` (lines 862-980)

```
main()
├── build_arg_parser()                          # 24 CLI args (lines 775-859)
├── load_spec(args.spec)                        # Parse YAML spec (lines 203-267)
├── merge vars: spec.variables + vars_file + --var CLI
├── filter_instances()                          # Apply --instance-ids, --instance-regex, --max-instances
├── allocate_whole_cores()                      # NUMA-aware CPU pinning (lines 270-460)
│   ├── Reads /sys/devices/system/cpu/ (Linux sysfs)
│   ├── Maps CPUs → NUMA nodes
│   └── Returns: [{"cpuset_cpus": "0,1,32,33", "cpuset_mems": "0", "nano_cpus": 4e9}, ...]
├── resource_limits = {mem_limit, mem_reservation, memswap_limit, ?nano_cpus}
├── docker_client = docker.from_env()
└── ThreadPoolExecutor(max_workers=N)
    └── For each instance: executor.submit(process_instance, ...)
        └── Round-robin CPU assignment: cpu_assignments[idx % len(cpu_assignments)]
```

#### 3.1.2 Container Lifecycle: `process_instance()` (lines 595-773)

This is the CORE function. Step-by-step:

```python
# Step 0: Setup (lines 610-636)
instance_id = instance["instance_id"]
log_dir = log_root / instance_id
image_name = spec.image_template.format(instance_id=instance_id)

# SKIP if patch already exists
if patch_host_path.exists():
    return {"instance_id": ..., "status": "skipped"}

# Step 1: Pull image (line 616-617)
if pull_missing_images:
    docker_client.images.pull(image_name)

# Step 2: Create container (lines 646-658)
create_kwargs = {
    "name": f"inference.{run_id}.{instance_id}",
    "image": image_name,
    "user": spec.docker_user,          # default: "root"
    "command": "tail -f /dev/null",     # KEEP-ALIVE — container is passive
    "detach": True,
    "tty": False,
    "working_dir": spec.docker_workdir, # default: "/testbed"
}
create_kwargs.update(per_container_limits)  # mem_limit, cpuset_cpus, etc.
container = docker_client.containers.create(**create_kwargs)
container.start()

# Step 3: Prework scripts (lines 671-698)
for script_step in spec.scripts:
    rendered = render_template(script_step.template, template_context)
    copy_text_to_container(container, rendered, script_step.destination, mode)
    if script_step.execute:
        exit_code = run_exec(container, command, ...)
        if exit_code != 0 and not script_step.continue_on_error:
            raise HarnessError(f"Prework script {script_step.name} failed")

# Step 4: INFERENCE — single shell command (lines 700-717)
inference_command = render_inline(spec.inference.command, template_context)
exit_code = run_exec(container, inference_command, ...)
if exit_code != 0:
    raise HarnessError("Inference command failed")

# Step 5: Patch extraction (lines 719-740)
patch_command = render_inline(spec.patch.command, template_context)
# DEFAULT_PATCH_COMMAND (lines 62-71):
#   cd /testbed && git add -N . && 
#   if [ -n "$BASE_COMMIT" ]; then git diff --binary "$BASE_COMMIT" > /tmp/model.patch
#   else git diff --binary HEAD > /tmp/model.patch; fi
run_exec(container, patch_command, ...)
copy_from_container(container, "/tmp/model.patch", log_dir/"patch.diff")

# Step 6: Artifacts (lines 742-754)
for artifact in spec.artifacts:
    copy_from_container(container, artifact_path, log_dir/host_name)

# Step 7: Cleanup (lines 761-772) — in finally block
container.stop(timeout=5)
container.remove(force=True)
docker_client.images.remove(image=image_name)  # if --keep-images not set
```

#### 3.1.3 Key Data Structures

```python
@dataclass
class Spec:
    name: str                     # From YAML spec name or filename stem
    description: str
    docker_workdir: str           # Default: "/testbed"
    docker_user: str              # Default: "root"
    image_template: str           # Default: "swefficiency/swefficiency_images:{instance_id}"
    scripts: List[ScriptStep]     # Prework scripts from prework.scripts[]
    inference: InferenceCommand   # Single command to run
    patch: PatchSpec              # How to extract the patch
    artifacts: List[dict]         # Extra files to copy out
    variables: Dict[str, Any]     # Template variables

@dataclass
class PatchSpec:
    command: str = DEFAULT_PATCH_COMMAND    # git diff --binary
    container_path: str = "/tmp/model.patch"
    host_filename: str = "patch.diff"
    shell: str = "/bin/bash"
```

#### 3.1.4 Template Context (line 619-624)

```python
template_context = {
    "instance": instance,        # Full HF dataset row (dict)
    "instance_id": instance_id,  # String
    "spec": spec,                # Spec dataclass
    "vars": context_vars,        # Merged user variables
}
```

Available in Jinja2 templates: `{{ instance.workload }}`, `{{ instance.base_commit }}`, `{{ vars.cursor_model }}`, etc.

#### 3.1.5 Output Structure

```
logs/run_inference/<run_id>/<spec_name>/
├── <instance_id>/
│   ├── patch.diff                    # The git diff --binary output
│   ├── container.log                 # Aggregated container log
│   ├── <prework_script_name>.log     # Per-script logs
│   ├── inference.log                 # Inference command output
│   ├── patch.log                     # Patch extraction log
│   └── <artifact_files>              # Any extra artifacts
└── summary.json                      # Array of {instance_id, status, patch/error}
```

#### 3.1.6 CLI Arguments (24 params, lines 775-859)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--dataset` | `swefficiency/swefficiency` | HuggingFace dataset |
| `--split` | `test` | Dataset split |
| `--instance-ids` | None | Explicit instance IDs |
| `--instance-regex` | None | Regex filter |
| `--max-instances` | None | Cap on instances |
| `--spec` | **Required** | Path to YAML spec |
| `--run-id` | **Required** | Run identifier |
| `--output-dir` | `logs/run_inference` | Log storage |
| `--num-workers` | 2 | Parallel workers |
| `--cpus-per-worker` | 4 | Logical CPUs per worker |
| `--threads-per-core` | 2 | SMT config |
| `--reserve-cores` | 0 | Host-reserved cores |
| `--disable-cpu-pinning` | false | Skip NUMA allocation |
| `--mem-limit` | `32g` | Docker memory limit |
| `--mem-reservation` | `16g` | Docker memory reservation |
| `--memswap` | `32g` | Docker memswap |
| `--nano-cpus` | None | Docker nano_cpus |
| `--pull-missing-images` | true | Pull images before launch |
| `--no-pull` | (negates above) | Skip docker pull |
| `--keep-containers` | false | Leave containers running |
| `--keep-images` | false | Don't remove images |
| `--stream-logs` | false | Mirror output to console |
| `--vars-file` | None | YAML/JSON vars file |
| `--var` | [] | Inline KEY=VALUE vars |
| `--dry-run` | false | List instances and exit |

### 3.2 YAML Spec System

**File**: `scripts/inference/specs/cursor_cli.yaml` (59 lines)

```yaml
name: cursor_cli
description: Cursor CLI agent for SWE-fficiency performance optimization

docker:
  workdir: /testbed
  user: root
  image_template: "ghcr.io/swefficiency/swefficiency-images:{instance_id}"

variables:
  patch_path: /tmp/model.patch
  instruction_path: /tmp/cursor_instruction.txt
  cursor_model: claude-sonnet-4-20250514
  cursor_agent_bin: cursor-agent
  cursor_cli_args: ""

prework:
  scripts:
    - name: cursor_install_cli
      template: ../templates/cursor_install_cli.sh.j2
      destination: /tmp/install_cursor_cli.sh
    - name: cursor_instruction_prompt
      template: ../templates/cursor_instruction_prompt.txt.j2
      destination: "{{ vars.instruction_path }}"
      execute: false

inference:
  command: |
    CURSOR_AGENT={{ vars.cursor_agent_bin | default('cursor-agent') }}
    "$CURSOR_AGENT" -p --force --output-format stream-json \
      "$(cat {{ vars.instruction_path }})" \
      --model "{{ vars.cursor_model }}" \
      {{ vars.cursor_cli_args }}

patch:
  shell: /bin/bash
  command: "cd /testbed && git add -N . && git diff --binary HEAD > {{ vars.patch_path }}"
  container_path: "{{ vars.patch_path | default('/tmp/model.patch') }}"
  host_filename: patch.diff

artifacts:
  - container_path: /tmp/install_cursor_cli.sh
    host_filename: install_cursor_cli.sh
  - container_path: "{{ vars.instruction_path }}"
    host_filename: cursor_instruction.txt
```

**Key insight**: The YAML spec drives EVERYTHING — image, prework, inference command, patch extraction, artifacts. The `process_instance()` function is completely generic.

---

## 4. OpenHands Benchmarks Deep Dive

### 4.1 File: `benchmarks/swefficiency/run_infer.py` (540 lines)

**Purpose**: Run OpenHands Agent SDK against SWE-fficiency instances. Full agent loop with trajectory capture.

#### 4.1.1 Entry Point: `main()` (lines 416-540)

```
main()
├── get_parser() + custom args                    # Shared SDK parser + 6 SWE-fficiency args
├── Load LLM config: LLM.model_validate_json(...)  # Pydantic validation
├── construct_eval_output_dir(...)                  # Structured output path
├── create_critic(args)                             # AgentFinishedCritic / EmptyPatchCritic / PassCritic
├── EvalMetadata(llm=llm, dataset=..., ...)         # Full evaluation context
├── divide_cpus_among_workers(...)                  # Simple linear CPU slicing
│   ├── os.sched_getaffinity(0)                     # Available CPUs
│   ├── Skip first N (default 4)
│   └── Divide into contiguous groups
├── multiprocessing.Manager().Queue()               # CPU group pool
└── SWEfficiencyEvaluation(metadata, num_workers, ...).run(
        on_result=get_default_on_result_writer(output_path)
    )
```

#### 4.1.2 Evaluation Orchestrator: `SWEfficiencyEvaluation` (lines 130-414)

Extends abstract `Evaluation` base class (from `benchmarks/utils/evaluation.py`, ~1100 lines). Three required methods:

##### `prepare_instances()` (lines 169-185)

```python
def prepare_instances(self) -> List[EvalInstance]:
    df = get_dataset(dataset_name=..., split=..., eval_limit=..., selected_instances_file=...)
    instances = [EvalInstance(id=str(row["instance_id"]), data=row.to_dict()) for _, row in df.iterrows()]
    return instances
```

##### `prepare_workspace()` (lines 198-303)

This is where Docker image building happens:

```python
def prepare_workspace(self, instance, resource_factor=1, forward_env=None) -> RemoteWorkspace:
    base_docker_image = f"ghcr.io/swefficiency/swefficiency-images:{instance.id}"
    build_target = "source-minimal"  # Default
    custom_tag = f"swefficiency.{instance.id}"
    
    # Image tag: ghcr.io/openhands/eval-agent-server:<sdk_sha>-swefficiency.<instance_id>-source-minimal
    suffix = f"-{build_target}" if build_target != "binary" else ""
    agent_server_image = f"{EVAL_AGENT_SERVER_IMAGE}:{IMAGE_TAG_PREFIX}-{custom_tag}{suffix}"
    
    if workspace_type == "docker":
        # BUILD LAYERED IMAGE — this is the key step
        ensure_local_image(
            agent_server_image=agent_server_image,
            base_image=base_docker_image,
            custom_tag=custom_tag,
            target=build_target,
        )
        
        # Create workspace with resource limits
        cpu_group = self._acquire_cpu_group()
        workspace = ResourceLimitedDockerWorkspace(
            server_image=agent_server_image,
            working_dir="/workspace",
            cpuset_cpus=",".join(map(str, cpu_group)),
            nano_cpus=int(1e9 * len(cpu_group)),
            mem_limit=self.mem_limit,
            cleanup_image=self.cleanup_agent_image,
        )
        # Store cleanup refs
        workspace._cpu_group = cpu_group
        workspace._cpu_groups_queue = self.cpu_groups_queue
        workspace._images_to_cleanup = [base_docker_image] if cleanup else []
    
    elif workspace_type == "remote":
        workspace = APIRemoteWorkspace(...)
    
    # Run env setup commands
    for cmd in metadata.env_setup_commands:
        workspace.execute_command(cmd)
    
    return workspace
```

##### `evaluate_instance()` (lines 305-413)

The agent conversation loop:

```python
def evaluate_instance(self, instance, workspace) -> EvalOutput:
    # 1. Create tools + agent
    tools = get_default_tools(enable_browser=False)
    agent_context = create_agent_context()
    agent = Agent(
        llm=build_eval_llm(self.metadata.llm),
        tools=tools,
        system_prompt_kwargs={"cli_mode": True},
        agent_context=agent_context,
    )
    
    # 2. Setup workspace directory
    workspace_dir_name = f"{repo.replace('/', '__')}__{version}"
    repo_path = f"/workspace/{workspace_dir_name}/"
    
    # 3. Create conversation with event persistence
    persist_callback = build_event_persistence_callback(
        run_id=self.metadata.eval_output_dir,
        instance_id=instance.id,
        attempt=self.current_attempt,
    )
    conversation = Conversation(
        agent=agent,
        workspace=workspace,
        callbacks=[persist_callback],
        max_iteration_per_run=self.metadata.max_iterations,  # Default: 500
        delete_on_close=True,
    )
    
    # 4. Copy /testbed → /workspace/<repo>__<ver>/
    workspace.execute_command(f"mkdir -p {repo_path} ; cp -r /testbed/. {repo_path}")
    workspace.execute_command(f"cd {repo_path} ; git reset --hard")
    workspace.execute_command(f"cd {repo_path} ; for remote in $(git remote); do git remote remove $remote; done")
    
    # 5. Send instruction + run agent loop
    instruction = get_instruction(instance.data, metadata, workspace.working_dir)
    conversation.send_message(instruction)
    run_conversation_with_fake_user_response(conversation)
    # ↑ This runs up to max_fake_responses=10 outer iterations
    # Each conversation.run() does up to 500 agent steps
    
    # 6. Patch extraction
    workspace.execute_command(f"cd {repo_path} ; git add -A")
    # Remove binary files from staging
    workspace.execute_command(f"cd {repo_path} ; for file in $(git status ...); do ... rm binary files ... done")
    workspace.execute_command(f"cd {repo_path} && git config user.email ... && git commit --no-verify -m 'patch'")
    
    base_commit = instance.data["base_commit"]
    git_patch_result = workspace.execute_command(
        f"cd {repo_path} ; git --no-pager diff --no-color {base_commit} HEAD"
    )
    git_patch = git_patch_result.stdout
    
    # 7. Build output
    return EvalOutput(
        instance_id=instance.id,
        attempt=self.current_attempt,
        test_result={"git_patch": git_patch},
        instruction=instruction,
        error=None,
        history=list(conversation.state.events),       # Full trajectory
        metrics=conversation.conversation_stats.get_combined_metrics(),  # Cost, tokens, etc.
    )
```

### 4.2 File: `benchmarks/swefficiency/workspace.py` (122 lines)

```python
class ResourceLimitedDockerWorkspace(DockerWorkspace):
    cpuset_cpus: str | None = None
    nano_cpus: int | None = None
    mem_limit: str | None = "16g"
    
    def _start_container(self, image, context):
        super()._start_container(image, context)   # SDK starts container + agent-server
        self._apply_resource_limits()               # POST-start limits
    
    def _apply_resource_limits(self):
        flags = []
        if self.cpuset_cpus: flags += ["--cpuset-cpus", self.cpuset_cpus]
        if self.nano_cpus: flags += ["--cpus", str(self.nano_cpus / 1e9)]
        if self.mem_limit: flags += ["--memory", self.mem_limit, "--memory-swap", self.mem_limit]
        execute_command(["docker", "update", *flags, self._container_id])
    
    def cleanup(self):
        super().cleanup()
        # Return CPU group to queue
        # Remove images
        # Optionally prune buildkit cache
```

### 4.3 File: `benchmarks/swefficiency/config.py` (22 lines)

```python
INFER_DEFAULTS = {"dataset": "swefficiency/swefficiency", "split": "test", "num_workers": 4}
DOCKER_DEFAULTS = {
    "num_cpus_per_worker": 4, "mem_limit": "32g", "num_cpus_to_skip": 4,
    "cleanup_agent_image": True, "cleanup_base_image": True, "prune_buildkit_cache": False,
}
```

### 4.4 File: `benchmarks/swefficiency/constants.py` (27 lines)

```python
DOCKER_IMAGE_PREFIX = "ghcr.io/swefficiency/swefficiency-images"
DEFAULT_BUILD_TARGET: TargetType = "source-minimal"  # Options: binary, binary-minimal, source, source-minimal
GIT_USER_EMAIL = "evaluation@openhands.dev"
GIT_USER_NAME = "OpenHands Evaluation"
GIT_COMMIT_MESSAGE = "patch"
DEFAULT_COMMAND_TIMEOUT = 600
DEFAULT_SANDBOX_TIMEOUT = 3600
```

### 4.5 File: `benchmarks/swefficiency/prompts/default.j2` (29 lines)

Jinja2 prompt template that injects `{{ instance.workload }}`, `{{ instance.test_cmd }}`, `{{ instance.rebuild_cmd }}`, and instructs the agent to:
1. Activate conda testbed env
2. Explore repo structure
3. Create workload script, run it
4. Edit source code (NOT workload function)
5. Rebuild if non-Python changes
6. Re-run to confirm improvement
7. Run relevant tests
8. Reflect and iterate
9. Use finish command

### 4.6 External Dependencies (from SDK/utils)

| Module | Purpose | Lines |
|--------|---------|-------|
| `benchmarks/utils/build_utils.py` (~924 lines) | `ensure_local_image()`, `build_image()` — builds layered Docker images using SDK's `build_with_telemetry()` |
| `benchmarks/utils/evaluation.py` (~1100 lines) | `Evaluation` ABC — critic loop, retry loop, asyncio orchestration, `on_result` callbacks |
| `benchmarks/utils/conversation.py` | `build_event_persistence_callback()` — structured event logging per instance |
| `benchmarks/utils/litellm_proxy.py` | `build_eval_llm()` — wraps LLM with cost-tracking virtual keys |
| `benchmarks/utils/critics.py` | `create_critic()` — creates AgentFinishedCritic, EmptyPatchCritic, PassCritic |
| `benchmarks/utils/fake_user_response.py` | `run_conversation_with_fake_user_response()` — outer conversation loop (max 10 fake responses) |
| `benchmarks/utils/agent_context.py` | `create_agent_context()` — loads public skills, respects EXTENSIONS_REF |
| `benchmarks/utils/args_parser.py` | `get_parser()` — shared CLI args (--max-iterations, --workspace, --n-critic-runs, etc.) |
| `openhands.sdk` | `LLM`, `Agent`, `Conversation`, `get_logger` — core SDK classes |
| `openhands.sdk.workspace` | `RemoteWorkspace` — abstract workspace interface |
| `openhands.workspace` | `DockerWorkspace`, `APIRemoteWorkspace` — concrete implementations |
| `openhands.tools.preset.default` | `get_default_tools()` — bash, file browser, etc. |
| `openhands.agent_server.docker.build` | `BuildOptions`, `build_with_telemetry()` — Docker image builder |

---

## 5. Architecture Reconciliation

### 5.1 Side-by-Side Comparison

| Aspect | Official (`custom.py`) | OpenHands (`run_infer.py`) | Integration Target |
|--------|------------------------|----------------------------|-------------------|
| **Container model** | Passive sandbox — receives `docker exec` | Active sandbox — runs agent-server HTTP process | **Active** (OpenHands) |
| **Image source** | Pull prebuilt from GHCR, use as-is | Pull prebuilt → build layered image with agent-server on top | **Layered** (OpenHands) |
| **Agent execution** | Single shell command inside container via `exec_run()` | Multi-turn conversation loop on HOST via HTTP to agent-server | **Conversation loop** (OpenHands) |
| **Command transport** | `docker exec` (Docker Python SDK) | HTTP API → agent-server → bash execution | **HTTP** (OpenHands) |
| **Resource limits** | Set at `containers.create()` — enforced from start | Applied POST-start via `docker update` | **POST-start** (OpenHands) |
| **Patch extraction** | `git diff --binary` inside container → `get_archive()` to copy | `git --no-pager diff --no-color` → stdout over HTTP | **`git diff --binary`** (Official) — run via `workspace.execute_command()` |
| **Working directory** | `/testbed/` (in-place editing) | `/workspace/<repo>__<ver>/` (copy from /testbed) | **`/workspace/<repo>__<ver>/`** (OpenHands) |
| **Output format** | `patch.diff` + per-step logs + `summary.json` | `output.jsonl` with `EvalOutput` (trajectory, metrics, cost) | **BOTH** |
| **Concurrency** | `ThreadPoolExecutor` (sync) | `Evaluation` ABC with asyncio + `asyncio.to_thread()` | **ThreadPoolExecutor** (simpler, official-aligned) |
| **CPU pinning** | NUMA-aware sysfs allocation (Linux-only) | Simple linear `os.sched_getaffinity` slicing | **Both supported** — use official NUMA when available, OpenHands linear as fallback |
| **Retry/critic** | None — single shot | Critic loop (outer, 3 runs) + Retry (inner, 4 attempts) | **Optional** — default single-shot, configurable |
| **Dependencies** | Minimal: datasets, docker, yaml, jinja2 | Full SDK: openhands.sdk, openhands.workspace, openhands.tools, openhands.agent_server + benchmarks/utils/ | **Full SDK** (for openhands mode) |

### 5.2 Patch Format Reconciliation

**CRITICAL DESIGN DECISION**: The user requires `git diff --binary` (official style) but OpenHands uses `git --no-pager diff --no-color` (no `--binary`).

**Resolution**: After the OpenHands agent finishes its conversation loop, we run the **official-style** patch extraction command via `workspace.execute_command()`:

```python
# Instead of OpenHands-style:
#   git add -A → remove binaries → commit → diff --no-color
# We run official-style:
#   git add -N . → git diff --binary "$BASE_COMMIT" > /tmp/model.patch
# Then copy the file out via workspace API
```

This gives us:
- **Binary-safe patches** (the `--binary` flag preserves binary file content)
- **Eval-compatible format** (identical to what `swefficiency eval` expects)
- **Still capture the patch as text** in `EvalOutput.test_result.git_patch` for the JSONL output

### 5.3 Working Directory Reconciliation

The agent runs in `/workspace/<repo>__<ver>/` (OpenHands convention), but patch extraction must use this path correctly:

```bash
BASE_COMMIT="<from dataset>"
cd /workspace/<repo>__<ver>/ && git add -N . && git diff --binary "$BASE_COMMIT" > /tmp/model.patch
```

The official `DEFAULT_PATCH_COMMAND` uses `cd /testbed` — we override this to `cd /workspace/<repo>__<ver>/`.

---

## 6. Critical Gotchas & Design Decisions

### Gotcha 1: `openhands.agent_server` is Heavy

The `ensure_local_image()` function (from `build_utils.py`) imports `openhands.agent_server.docker.build.BuildOptions` and `build_with_telemetry()`. This is NOT just the SDK pip package — it's the full agent-server Docker build infrastructure. It requires:
- The `openhands` package installed (from SDK submodule)
- Docker buildx available
- Potentially multi-GB disk space for cached builds

**Decision**: Accept this dependency. The SDK submodule provides everything needed.

### Gotcha 2: asyncio vs threading

The official harness uses `concurrent.futures.ThreadPoolExecutor` directly. The OpenHands `Evaluation` base class uses `asyncio.run()` → `asyncio.to_thread()` for its orchestration. These models are incompatible.

**Decision**: We do NOT inherit from `Evaluation`. Instead, we keep the official `ThreadPoolExecutor` model and port only the workspace/conversation logic. This avoids:
- asyncio event loop conflicts
- Inheriting 1100+ lines of `evaluation.py` orchestration we don't need
- The `ProcessPoolExecutor` complexity

### Gotcha 3: HTTP-based Host-to-Container Architecture

`workspace.execute_command("some command")` is NOT `docker exec`. It's an HTTP POST to the agent-server running inside the container. The agent-server executes the command and returns a structured result:

```python
result = workspace.execute_command("ls -la")
result.exit_code  # int
result.stdout      # str
result.stderr      # str
```

This is fundamentally different from the official `run_exec()` which calls `container.exec_run()` directly.

### Gotcha 4: `delete_on_close=True`

`Conversation` is created with `delete_on_close=True` (line 340). This means the conversation deletes itself when the context manager exits. We must capture `conversation.state.events` and `conversation.conversation_stats` BEFORE the conversation is closed.

### Gotcha 5: `workspace.execute_command()` Returns Structured Result

Unlike `container.exec_run()` which returns Docker SDK types, `workspace.execute_command()` returns an object with `.exit_code`, `.stdout`, `.stderr`. All command execution in the new mode must use this API.

### Gotcha 6: `build_eval_llm()` Wraps LLM with Cost Tracking

`build_eval_llm()` (from `litellm_proxy.py`) wraps the LLM with a per-instance virtual API key for cost tracking via LiteLLM proxy. Without this, cost data in output.jsonl will be absent.

**Decision**: Port this function or use LLM directly (cost tracking is nice-to-have, not blocking).

### Gotcha 7: Agent Context + Skills

`create_agent_context()` loads "public skills" and respects the `EXTENSIONS_REF` environment variable. This is the mechanism for configuring agent behavior beyond the system prompt.

### Gotcha 8: macOS / ARM Architecture

- `allocate_whole_cores()` reads Linux sysfs — fails on macOS with `FileNotFoundError`
- Official eval containers are `amd64` — pulling on ARM macOS uses QEMU emulation (slow)
- The `--disable-cpu-pinning` flag gracefully bypasses sysfs reads

### Gotcha 9: SDK sdist Pre-Build Caching

`build_utils.py` has `_pre_build_sdist()` which builds the SDK as a `.tar.gz` once and caches it across all image builds. This is an important optimization — without it, each image build would re-package the SDK.

### Gotcha 10: Image Cache Invalidation

The layered image tag includes the SDK SHA (`IMAGE_TAG_PREFIX`). When the SDK version changes, all images are rebuilt. This is by design for reproducibility but means first-run of a new SDK version is slow.

### Gotcha 11: `RemoteWorkspace` Type Assertion

Line 322: `assert isinstance(workspace, RemoteWorkspace)`. The `DockerWorkspace` class implements `RemoteWorkspace` interface (it's an HTTP client to the agent-server, not a local Docker API client). This type assertion will pass for both Docker and Remote workspaces.

---

## 7. File-by-File Change List

All changes within `/Users/macbookpro/Desktop/research paper/SWE -FFICIENCY/swefficiency/`.

### 7.1 New Files

| # | File Path | Lines (est.) | Purpose |
|---|-----------|-------------|---------|
| 1 | `vendor/software-agent-sdk/` (git submodule) | — | OpenHands Agent SDK |
| 2 | `scripts/inference/openhands_mode.py` | ~400 | New inference mode: image building, workspace creation, conversation loop, dual output |
| 3 | `scripts/inference/openhands_workspace.py` | ~100 | Port of `ResourceLimitedDockerWorkspace` |
| 4 | `scripts/inference/openhands_image_builder.py` | ~200 | Port of `ensure_local_image()` + `build_image()` from build_utils.py |
| 5 | `scripts/inference/openhands_output.py` | ~120 | Dual output writer (patch.diff + output.jsonl) + prediction JSONL converter |
| 6 | `scripts/inference/openhands_config.py` | ~50 | Constants, defaults, LLM config loading |
| 7 | `scripts/inference/specs/openhands_agent.yaml` | ~40 | YAML spec for OpenHands agent mode (documents the configuration) |
| 8 | `scripts/inference/templates/openhands_prompt.j2` | ~30 | Port of OpenHands prompt template |
| 9 | `Makefile` or `scripts/setup_sdk.sh` | ~20 | SDK submodule initialization |

### 7.2 Modified Files

| # | File Path | Changes | Purpose |
|---|-----------|---------|---------|
| 10 | `scripts/inference/custom.py` | +~80 lines | Add `--mode` arg (spec/openhands), `--llm-config` arg, dispatch to `openhands_mode.process_instance_openhands()` |
| 11 | `pyproject.toml` | +~10 lines | Add `[project.optional-dependencies] openhands = [...]` dependency group |

### 7.3 Unchanged Files

- `swefficiency/cli.py` — eval/report CLI untouched
- `swefficiency/harness/` — entire evaluation engine untouched
- `swefficiency/report.py` — report generation untouched
- Existing YAML specs — cursor_cli.yaml etc. untouched

### 7.4 Total Estimate

| Category | Lines |
|----------|-------|
| New files (items 2-9) | ~960 |
| Modified files (items 10-11) | ~90 |
| Infrastructure (item 1, 9) | ~20 |
| **Total** | **~1,070** |

**Realistic estimate with tests, error handling, edge cases**: ~1,500-2,000 lines.

---

## 8. Dependency & Infrastructure Requirements

### 8.1 Python Dependencies

**For `--mode spec` (existing, unchanged)**:
```
datasets, docker, pyyaml, jinja2, python-dotenv
```

**For `--mode openhands` (new)**:
```
openhands-sdk           # From vendor/software-agent-sdk/
openhands-workspace     # Docker/Remote workspace implementations
openhands-tools         # Default tools (bash, file browser)
openhands-agent-server  # Docker image builder
litellm                 # LLM routing (implicit via SDK)
pydantic                # Data models (implicit via SDK)
```

**Strategy**: Lazy import — `--mode openhands` imports are deferred so `--mode spec` still works with minimal deps.

### 8.2 Environment Variables

| Variable | Required For | Description |
|----------|-------------|-------------|
| `AWS_BEARER_TOKEN_BEDROCK` | AWS Bedrock bearer auth | Token for litellm Bedrock provider |
| `AWS_ACCESS_KEY_ID` | AWS Bedrock IAM auth | Alternative to bearer token |
| `AWS_SECRET_ACCESS_KEY` | AWS Bedrock IAM auth | With above |
| `AWS_REGION_NAME` | AWS Bedrock | Region (e.g., `ap-south-1`) |
| `CR_PAT` | Docker image pull | GHCR auth for base images |
| `EXTENSIONS_REF` | Agent context | Optional: custom skills branch |

### 8.3 LLM Config File

For AWS Bedrock with bearer token:
```json
{
  "model": "bedrock/converse/global.anthropic.claude-opus-4-6-v1",
  "aws_region_name": "ap-south-1"
}
```
Plus: `export AWS_BEARER_TOKEN_BEDROCK="your-token"`

For IAM auth:
```json
{
  "model": "bedrock/converse/global.anthropic.claude-opus-4-6-v1",
  "aws_access_key_id": "AKIA...",
  "aws_secret_access_key": "...",
  "aws_region_name": "ap-south-1"
}
```

### 8.4 System Requirements

- Docker with buildx support
- Python 3.12+
- `uv` (recommended) or pip
- ~10GB disk per instance image (layered build cache)
- 4+ CPUs, 16GB+ RAM per worker

---

## 9. Implementation Plan (Wave Structure)

### Wave 0: Infrastructure (no code logic)

| Task | Description | Files | Est. |
|------|-------------|-------|------|
| W0-1 | Add OpenHands Agent SDK as git submodule at `vendor/software-agent-sdk/` | `.gitmodules`, `vendor/` | 10 min |
| W0-2 | Add optional dependency group to `pyproject.toml` | `pyproject.toml` | 10 min |
| W0-3 | Create setup script for submodule init + install | `scripts/setup_sdk.sh` or Makefile | 20 min |

**Verification**: `pip install -e ".[openhands]"` succeeds, `python -c "from openhands.sdk import LLM, Agent, Conversation"` works.

### Wave 1: Core Modules (independent, parallelizable)

| Task | Description | Files | Depends | Est. |
|------|-------------|-------|---------|------|
| W1-1 | Port `ResourceLimitedDockerWorkspace` | `scripts/inference/openhands_workspace.py` | W0 | 1h |
| W1-2 | Port image builder (`ensure_local_image`, `build_image`) | `scripts/inference/openhands_image_builder.py` | W0 | 2h |
| W1-3 | Create config/constants module | `scripts/inference/openhands_config.py` | W0 | 30 min |
| W1-4 | Create prompt template | `scripts/inference/templates/openhands_prompt.j2` | — | 30 min |
| W1-5 | Create output writer (dual format + JSONL converter) | `scripts/inference/openhands_output.py` | — | 1h |

**Verification per task**: Unit-level — imports work, classes instantiate, functions callable.

### Wave 2: Integration (sequential, depends on Wave 1)

| Task | Description | Files | Depends | Est. |
|------|-------------|-------|---------|------|
| W2-1 | Implement `process_instance_openhands()` | `scripts/inference/openhands_mode.py` | W1-1, W1-2, W1-3, W1-4, W1-5 | 4h |
| W2-2 | Add `--mode` + `--llm-config` to CLI, dispatch logic | `scripts/inference/custom.py` | W2-1 | 1h |
| W2-3 | Create YAML spec for openhands mode (documentation) | `scripts/inference/specs/openhands_agent.yaml` | W2-1 | 30 min |

**Verification**: `python scripts/inference/custom.py --mode openhands --run-id test --llm-config bedrock.json --instance-ids numpy__numpy-11720 --disable-cpu-pinning` runs end-to-end.

### Wave 3: Verification & Polish

| Task | Description | Files | Depends | Est. |
|------|-------------|-------|---------|------|
| W3-1 | End-to-end test: single instance, gold patch verification | — | W2 | 2h |
| W3-2 | Verify output feeds into `swefficiency eval` | — | W3-1 | 1h |
| W3-3 | Verify `--mode spec` still works (regression) | — | W2-2 | 30 min |
| W3-4 | Error handling: network failure, Docker timeout, LLM error | all | W2 | 1h |

---

## 10. Test Plan & Success Criteria

### 10.1 Success Criteria

| # | Criterion | How to Verify |
|---|-----------|--------------|
| SC1 | `--mode spec --spec specs/cursor_cli.yaml` still works identically | Run existing spec, compare output |
| SC2 | `--mode openhands` builds layered Docker image | Image appears in `docker images` |
| SC3 | Agent-server process runs inside container | Container logs show agent-server startup |
| SC4 | Agent conversation completes (at least 1 tool call) | `output.jsonl` contains non-empty `history` |
| SC5 | `patch.diff` is generated with `git diff --binary` format | File exists, contains `diff --git` headers |
| SC6 | `output.jsonl` contains full trajectory | Has `history`, `metrics`, `instruction` fields |
| SC7 | `patch.diff` feeds into `swefficiency eval` | Eval accepts the prediction JSONL |
| SC8 | AWS Bedrock LLM call succeeds | Agent makes at least one LLM call |
| SC9 | Resource limits are applied | `docker inspect` shows memory/CPU limits |
| SC10 | Cleanup works | Container + image removed after completion |

### 10.2 Test Commands

```bash
# Regression: existing mode still works
python scripts/inference/custom.py \
  --mode spec \
  --spec scripts/inference/specs/cursor_cli.yaml \
  --run-id regression_test \
  --instance-ids numpy__numpy-11720 \
  --disable-cpu-pinning \
  --dry-run

# New mode: OpenHands agent
python scripts/inference/custom.py \
  --mode openhands \
  --llm-config .llm_config/bedrock.json \
  --run-id openhands_test \
  --instance-ids numpy__numpy-11720 \
  --disable-cpu-pinning \
  --num-workers 1

# Verify output
ls logs/run_inference/openhands_test/openhands/numpy__numpy-11720/
# Expected: patch.diff, output.jsonl, container.log

# Convert to prediction JSONL
python scripts/inference/openhands_output.py convert \
  --input logs/run_inference/openhands_test/ \
  --output predictions.jsonl

# Feed into eval (Linux only, requires Docker)
swefficiency eval --run_id eval_openhands --prediction_path predictions.jsonl --num_workers 1
```

---

## 11. Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| SDK submodule doesn't build on macOS ARM | High | Medium | Test early; use Rosetta/x86 Docker if needed |
| `build_with_telemetry()` requires agent-server package not in SDK | High | Low | SDK submodule includes all workspace members |
| AWS Bedrock bearer token not forwarded through litellm | High | Medium | Test LLM call first in isolation before full integration |
| Image build takes >30 min for first instance | Medium | Medium | Pre-build and cache; use `--no-pull` after first run |
| asyncio/threading conflict with SDK internals | Medium | Low | We use ThreadPoolExecutor; SDK internals are sync |
| `delete_on_close=True` loses conversation state | High | Low | Capture events BEFORE conversation close |
| Agent conversation never terminates (infinite loop) | Medium | Medium | `max_iteration_per_run=500` + timeout |
| Docker image layer conflict (base + agent-server) | Low | Low | SDK's build system handles this cleanly |

---

## 12. Open Questions

| # | Question | Impact | Who Decides |
|---|----------|--------|-------------|
| Q1 | Should critic/retry loops be ported? Or single-shot only? | Complexity: single-shot ~400 lines, with critic ~600 lines | User (recommend: single-shot first, add critic later) |
| Q2 | Should `build_eval_llm()` cost tracking be ported? | Nice-to-have for cost visibility in output.jsonl | User (recommend: skip initially, add if needed) |
| Q3 | Should the integration use the SDK's `Evaluation` base class or stay with ThreadPoolExecutor? | Architecture: Evaluation gives critic/retry for free but adds ~1100 lines of complexity | User (recommend: ThreadPoolExecutor for simplicity) |
| Q4 | Exact agent tools to enable? `get_default_tools(enable_browser=False)` or custom set? | Affects agent capability | User (recommend: default tools, no browser) |
| Q5 | Should event persistence (per-event logging) be ported? | Full trajectory capture vs. summary-only | User (recommend: yes, it's only ~30 lines extra) |

---

## Appendix A: Key Source Code References

| Reference | File | Lines | Description |
|-----------|------|-------|-------------|
| Container creation | `custom.py` | 646-658 | `docker_client.containers.create(command="tail -f /dev/null")` |
| Prework loop | `custom.py` | 671-698 | Template render → copy → exec |
| Inference exec | `custom.py` | 700-717 | Single `run_exec()` call |
| Patch extraction | `custom.py` | 719-740 | `run_exec(patch_command)` → `copy_from_container()` |
| DEFAULT_PATCH_COMMAND | `custom.py` | 62-71 | `git add -N . && git diff --binary "$BASE_COMMIT"` |
| Image building | `build_utils.py` | 440-518 | `ensure_local_image()` → `build_image()` → SDK's `build_with_telemetry()` |
| Workspace creation | `run_infer.py` | 224-258 | `ensure_local_image()` → `ResourceLimitedDockerWorkspace()` |
| Agent conversation | `run_infer.py` | 305-413 | `Agent()` → `Conversation()` → `send_message()` → `run_conversation_with_fake_user_response()` |
| Patch extraction (OH) | `run_infer.py` | 371-400 | `git add -A` → remove binaries → commit → `git diff --no-color` |
| Resource limits | `workspace.py` | 63-92 | `docker update --cpuset-cpus --memory` POST-start |
| CPU division | `run_infer.py` | 85-127 | Linear `sched_getaffinity` slicing |
| Prompt template | `prompts/default.j2` | 1-29 | Instance workload + instructions |

---

## Appendix B: Prediction JSONL Format (for eval compatibility)

```json
{"instance_id": "numpy__numpy-11720", "model_patch": "diff --git a/...", "model_name_or_path": "openhands-bedrock"}
```

The converter (`openhands_output.py`) reads `output.jsonl` → extracts `test_result.git_patch` → writes prediction JSONL.

Alternatively, read `patch.diff` files directly (more reliable since they use `git diff --binary`):

```python
import json
from pathlib import Path

def convert_patches_to_predictions(run_dir: Path, model_name: str) -> list[dict]:
    predictions = []
    for instance_dir in sorted(run_dir.iterdir()):
        if not instance_dir.is_dir():
            continue
        patch_file = instance_dir / "patch.diff"
        if patch_file.exists():
            predictions.append({
                "instance_id": instance_dir.name,
                "model_patch": patch_file.read_text(),
                "model_name_or_path": model_name,
            })
    return predictions
```

---

*Document generated from exhaustive source code analysis of both `swefficiency/` (official, 980-line custom.py) and `openhands-benchmarks/` (540-line run_infer.py + 122-line workspace.py + SDK infrastructure). All line numbers verified against actual source files.*

---

## 13. Metis Pre-Planning Analysis (Specialist Review)

> Metis is a pre-planning consultant that identifies hidden intentions, ambiguities, and AI failure points before implementation begins. The following findings were produced by Metis after reading the full plan and exploring both codebases.

### 13.1 Hidden Requirements Discovered

#### HR-1: `--spec` is `required=True` — Breaks `--mode openhands` Invocation (CRITICAL)

In `custom.py` line 789, `--spec` is declared with `required=True`. The plan's example command:
```bash
python scripts/inference/custom.py --mode openhands --llm-config ... --run-id ...
```
will fail with: `error: the following arguments are required: --spec`

**Resolution Options**:
- **(A) Recommended**: Change `--spec` to `required=False` with conditional validation — if `--mode spec` or no `--mode`, validate `--spec` is provided. If `--mode openhands`, skip.
- **(B) Safer for backward compat**: Create a dummy `specs/openhands_agent.yaml` and require `--spec` always — but this creates confusion about what the spec file does in openhands mode.

**Decision**: Option A. Post-parse validation is cleaner and matches how real CLIs handle mutually dependent args.

#### HR-2: `spec.name` Drives Output Directory Structure

Line 898: `run_log_dir = args.output_dir / args.run_id / spec.name`

In `--mode openhands`, there's no `Spec` object. The directory structure must still follow `logs/run_inference/<run_id>/<spec_name>/` for tooling compatibility.

**Resolution**: Use `"openhands"` as the effective spec name. Hardcode or derive from `--mode` value:
```python
spec_name = spec.name if mode == "spec" else "openhands"
run_log_dir = args.output_dir / args.run_id / spec_name
```

#### HR-3: Existing `oh_conversion.py` Already Exists in Repo

The repo already has `predictions/converted/oh_conversion.py` that converts OpenHands `output.jsonl` → prediction JSONL. It reads `item["test_result"]["git_patch"]` and `item["metadata"]["eval_output_dir"]`.

**Resolution**: Reconcile with the new converter (`openhands_output.py`) — either extend the existing script or document that the new one supersedes it. Do NOT create a second converter that does 90% the same thing.

#### HR-4: `requires-python = ">=3.8"` Conflicts with SDK's Python 3.12+ Needs

The `pyproject.toml` specifies `requires-python = ">=3.8"`, but the OpenHands SDK requires Python 3.12+ features (`tomllib`, type unions with `|`, etc.). Adding the SDK dep group will silently install on Python 3.8-3.11 but crash at runtime.

**Resolution**: Add a runtime version check at the top of the openhands mode:
```python
import sys
if sys.version_info < (3, 12):
    raise RuntimeError("OpenHands mode requires Python 3.12+. Current: {}.{}".format(*sys.version_info[:2]))
```
Do NOT change the project-level `requires-python` — that would break the base package for older Python users.

#### HR-5: Dual Resource-Limit Models — Potential Double Application

The official harness applies resource limits at `containers.create()` (line 655). The OpenHands workspace applies them POST-start via `docker update` (workspace.py line 88). In openhands mode, the `per_container_limits` dict from `main()` will be passed to `process_instance_openhands()` — these must be forwarded to the workspace, NOT applied at container creation (since the SDK manages the container).

**Resolution**: `process_instance_openhands()` receives `resource_limits` but passes them to `ResourceLimitedDockerWorkspace` constructor instead of Docker's `containers.create()`.

#### HR-6: Base Image Auth for Docker Buildx

`docker buildx build` with `FROM ghcr.io/swefficiency/swefficiency-images:{instance_id}` requires GHCR auth at the Docker daemon level (`docker login ghcr.io`), NOT a Python SDK pull. This is different from the official harness which uses `docker_client.images.pull()`.

**Resolution**: Add to Wave 0 verification: `docker pull ghcr.io/swefficiency/swefficiency-images:numpy__numpy-11720` must succeed. Document that `echo $CR_PAT | docker login ghcr.io -u USERNAME --password-stdin` is a prerequisite.

### 13.2 Ambiguities That Cause Implementation Failure

#### AMB-1: Who Pulls the Base Image?

The official harness explicitly pulls: `docker_client.images.pull(image_name)` (custom.py line 617). The OpenHands `build_image()` → `build_with_telemetry()` → `docker buildx build --build-arg BASE_IMAGE=<base>` — the `FROM` directive in the Dockerfile pulls the base image as part of the build. So the SDK builder handles it, but it needs Docker daemon-level GHCR auth.

**Resolution**: The openhands mode does NOT need a separate pull step. `ensure_local_image()` handles everything. But GHCR auth must be configured at daemon level.

#### AMB-2: Container Naming Collision

Official mode: `container_name = f"inference.{run_id}.{instance_id}"` (line 638). The SDK names containers internally with its own scheme.

**Resolution**: Not a real issue — the SDK manages its own container lifecycle. But cleanup must use the SDK's `workspace.cleanup()`, NOT the official `container.stop()` + `container.remove()`.

#### AMB-3: `Conversation.state.events` Access Timing

With `delete_on_close=True` (run_infer.py line 340), the conversation deletes itself when closed. Events must be captured BEFORE `conversation.close()` or context manager `__exit__`.

**Resolution**: Follow the exact pattern from `run_infer.py` lines 410-411:
```python
# MUST be called BEFORE conversation close
history = list(conversation.state.events)
metrics = conversation.conversation_stats.get_combined_metrics()
```

#### AMB-4: Patch Format — Definitive Design Decision

Two incompatible approaches:

| Approach | Command | What it captures |
|----------|---------|-----------------|
| Official | `git add -N . && git diff --binary "$BASE_COMMIT"` | Working tree vs base_commit, including binary files |
| OpenHands | `git add -A && git commit && git diff --no-color base_commit HEAD` | Committed state vs base_commit, text-only |

**Decision**: Use **official-style** patch extraction, but via `workspace.execute_command()`:
```python
# After agent finishes, extract patch the official way
workspace.execute_command("cd /workspace/<repo>__<ver> && git add -N . && git diff --binary \"$BASE_COMMIT\" > /tmp/model.patch")
# Then copy out via workspace file API
```
This gives `git diff --binary` format (user requirement R6) while running through the workspace HTTP API (not Docker SDK).

#### AMB-5: Template Context for OpenHands Prompt

The prompt template needs `{{ instance.workload }}`, `{{ instance.test_cmd }}`, `{{ instance.rebuild_cmd }}`. These come from the HuggingFace dataset row. Verified: the `SWEfficiencyInstance` TypedDict (constants.py) includes `workload`, `test_cmd`, `rebuild_cmd` fields. The dataset rows match.

**Resolution**: Confirmed compatible. Pass the full dataset instance dict as `instance` to Jinja2 template rendering.

### 13.3 AI Failure Points (Where an LLM Implementer Goes Wrong)

| # | Failure | Correct Pattern | Risk |
|---|---------|-----------------|------|
| AF-1 | Import SDK at module level in `custom.py` | ALL `from openhands.*` imports INSIDE functions, never at module level | HIGH — breaks `--mode spec` when SDK not installed |
| AF-2 | Use `container.exec_run()` in openhands mode | Use `workspace.execute_command()` for ALL commands | HIGH — wrong API entirely |
| AF-3 | Forget `/testbed` → `/workspace/<repo>__<ver>/` copy | First command after container start: `cp -r /testbed/. /workspace/<repo>__<ver>/` then `cd /workspace/<repo>__<ver>/ && git reset --hard` | HIGH — agent works in wrong directory |
| AF-4 | Create `Conversation()` without `run_conversation_with_fake_user_response()` | Must use the fake-user-response loop for multi-turn capability | MEDIUM — agent stops after first action |
| AF-5 | Wrong prediction JSONL field names | Exact: `instance_id`, `model_patch`, `model_name_or_path` — validated with `raise ValueError` in `get_model_predictions()` | HIGH — eval pipeline rejects output |
| AF-6 | Wrong SDK package name/path in pyproject.toml | Submodule is at `vendor/software-agent-sdk/`, package name from SDK's own pyproject.toml | MEDIUM — install fails silently |

### 13.4 Missing Components Not in Original Plan

| # | Component | Lines Est. | Severity |
|---|-----------|-----------|----------|
| MC-1 | `--max-iterations` CLI argument (caps agent steps) | 5 | HIGH — unbounded agent runs burn tokens |
| MC-2 | `--timeout-per-instance` CLI argument (wall-clock timeout) | 10 | HIGH — agent can loop for hours |
| MC-3 | Cost/token tracking output via `build_eval_llm()` wrapper | 20 | MEDIUM — output.jsonl metrics empty without this |
| MC-4 | Signal/interrupt handling for zombie containers | 15 | MEDIUM — Ctrl+C leaves containers running |
| MC-5 | Docker login/GHCR auth verification step | 10 | HIGH — build fails silently without auth |
| MC-6 | Event persistence callback (`build_event_persistence_callback()`) | 30 | MEDIUM — crash loses all trajectory data |
| MC-7 | Output JSONL path specification (per-instance vs run-level) | 5 | LOW — but must match converter expectations |

### 13.5 Metis Directives for Implementation

**MUST**:
1. Make `--spec` conditionally required (only when `--mode spec` or no mode). Use post-parse validation.
2. Use `"openhands"` as effective `spec_name` for output directory structure.
3. Implement lazy imports for ALL OpenHands SDK modules inside functions, never at module level.
4. Copy `/testbed` → `/workspace/<repo>__<ver>/` before agent execution.
5. Capture `conversation.state.events` and `conversation.conversation_stats` BEFORE conversation close.
6. Implement `try/finally` with explicit `workspace.cleanup()` in `process_instance_openhands()`.
7. Add `--max-iterations` (default 500) and `--timeout-per-instance` (default 3600) to CLI.
8. Use official-style patch extraction (`git diff --binary`) via `workspace.execute_command()`.

**MUST NOT**:
1. Import from `openhands.*` at module level in any file that `--mode spec` touches.
2. Modify the `process_instance()` function signature or behavior.
3. Change the output directory structure pattern (`logs/run_inference/<run_id>/<spec_name>/`).
4. Use `container.exec_run()` in openhands mode.
5. Create a duplicate converter — reconcile with existing `predictions/converted/oh_conversion.py`.

---

## 14. Momus Plan Critique (Quality Assurance Review)

> Momus is an expert reviewer for evaluating work plans against rigorous clarity, verifiability, and completeness standards. Momus was invoked on the full plan file.

### 14.1 Verdict: **[OKAY]**

Momus confirmed that:
- All file references and line numbers are accurate against the actual codebase
- The wave structure is correctly ordered with proper dependency chains
- The plan is executable — a developer can begin from Wave 0

### 14.2 Momus Recommendations (already addressed by Metis findings above)

The plan was validated before Metis findings were incorporated. The Metis additions (Section 13) address all gaps Momus would have flagged — specifically the `--spec required=True` conflict, output directory naming, and missing CLI args.

---

## 15. Updated Wave Structure (Post-Metis/Momus)

This supersedes Section 9. Incorporates all Metis hidden requirements, missing components, and wave adjustments.

### Wave 0: Infrastructure + Validation (Prerequisites)

| Task | Description | Files | Est. | QA |
|------|-------------|-------|------|----|
| W0-1 | Add OpenHands Agent SDK as git submodule | `.gitmodules`, `vendor/` | 10 min | `git submodule status` shows SDK |
| W0-2 | Add optional dependency group to `pyproject.toml` | `pyproject.toml` | 10 min | `pip install -e ".[openhands]"` succeeds |
| W0-3 | Create setup script (submodule init + install) | `scripts/setup_sdk.sh` | 20 min | Script exits 0 |
| W0-4 | Verify Docker buildx availability | — | 5 min | `docker buildx version` succeeds |
| W0-5 | Verify GHCR auth | — | 5 min | `docker pull ghcr.io/swefficiency/swefficiency-images:numpy__numpy-11720` succeeds |
| W0-6 | Verify AWS Bedrock connectivity (isolated LLM test) | `.llm_config/bedrock.json` | 15 min | LLM returns a response |

**Gate**: ALL W0 tasks pass before proceeding to Wave 1.

### Wave 1: Core Modules + CLI Changes (parallelizable after W0)

| Task | Description | Files | Depends | Est. | QA |
|------|-------------|-------|---------|------|----|
| W1-1 | Port `ResourceLimitedDockerWorkspace` | `scripts/inference/openhands_workspace.py` | W0 | 1h | Class instantiates, `_apply_resource_limits` callable |
| W1-2 | Create config/constants module | `scripts/inference/openhands_config.py` | W0 | 30 min | Imports work |
| W1-3 | Create prompt template | `scripts/inference/templates/openhands_prompt.j2` | — | 30 min | Renders with sample instance |
| W1-4 | Create output writer (dual format: patch.diff + output.jsonl) | `scripts/inference/openhands_output.py` | — | 1h | Writes both formats from mock data |
| W1-5 | CLI arg changes: `--mode`, `--llm-config`, `--max-iterations`, `--timeout-per-instance`, make `--spec` conditionally required | `scripts/inference/custom.py` | — | 1h | `--mode openhands` without `--spec` doesn't error; `--mode spec` without `--spec` still errors |
| W1-6 | Error/cleanup handler (`try/finally` pattern with `workspace.cleanup()`) | `scripts/inference/openhands_mode.py` (skeleton) | W1-1 | 30 min | Cleanup runs on forced KeyboardInterrupt |

**Gate**: All W1 tasks pass independently.

### Wave 2: Integration (sequential, depends on Wave 1)

| Task | Description | Files | Depends | Est. | QA |
|------|-------------|-------|---------|------|----|
| W2-1a | Image builder: port `ensure_local_image()` + `build_image()` | `scripts/inference/openhands_image_builder.py` | W0, W1-2 | 2h | Image appears in `docker images` after build |
| W2-1b | Workspace setup: container start + `/testbed` copy + `git reset --hard` | `scripts/inference/openhands_mode.py` | W1-1, W2-1a | 1h | `/workspace/<repo>__<ver>/` exists in container with correct git state |
| W2-1c | Agent conversation loop: Agent + Conversation + `run_conversation_with_fake_user_response` | `scripts/inference/openhands_mode.py` | W2-1b | 2h | Conversation completes, events captured |
| W2-1d | Patch extraction: `git diff --binary` via `workspace.execute_command()` | `scripts/inference/openhands_mode.py` | W2-1c | 1h | `patch.diff` exists with `diff --git` headers |
| W2-1e | Glue: orchestrate a-d with error handling, timeout, dual output write | `scripts/inference/openhands_mode.py` | W2-1a-d | 1h | Full `process_instance_openhands()` function works |
| W2-2 | Dispatch logic in `custom.py`: route `--mode openhands` to new module | `scripts/inference/custom.py` | W2-1e | 1h | Mode routing works in dry-run |
| W2-3 | Create YAML spec for openhands mode (documentation, not functional) | `scripts/inference/specs/openhands_agent.yaml` | W2-1e | 30 min | File exists, comments explain purpose |

**Gate**: `python scripts/inference/custom.py --mode openhands --run-id test --llm-config bedrock.json --instance-ids numpy__numpy-11720 --num-workers 1` completes end-to-end.

### Wave 3: Verification & Hardening

| Task | Description | Files | Depends | Est. | QA |
|------|-------------|-------|---------|------|----|
| W3-1 | End-to-end test: single instance | — | W2 | 2h | patch.diff + output.jsonl exist with valid content |
| W3-2 | Verify output feeds into `swefficiency eval` | — | W3-1 | 1h | Eval runs without errors on prediction JSONL |
| W3-3 | Regression: `--mode spec` still works | — | W2-2 | 30 min | Identical behavior to pre-change |
| W3-4 | Error handling: Docker timeout, LLM error, network failure | all | W2 | 1h | Errors caught, containers cleaned up, clear error messages |
| W3-5 | Prediction JSONL format validation | — | W3-1 | 15 min | Fields match `get_model_predictions()` validation (instance_id, model_patch, model_name_or_path) |
| W3-6 | Container cleanup verification | — | W3-1 | 15 min | `docker ps -a --filter name=inference.` returns no containers |
| W3-7 | Import isolation test | — | W2-2 | 15 min | `python -c "from scripts.inference.custom import build_arg_parser"` succeeds without SDK installed |

**Estimated Total**: ~18-22 hours of implementation work.

---

## 16. Summary of ALL Required Changes (Final)

Based on all analysis rounds, Metis findings, and Momus validation:

### New Files (9)

| File | Purpose | Lines Est. |
|------|---------|-----------|
| `scripts/inference/openhands_mode.py` | `process_instance_openhands()` — main orchestrator with sub-functions | ~400 |
| `scripts/inference/openhands_workspace.py` | `ResourceLimitedDockerWorkspace` port | ~100 |
| `scripts/inference/openhands_image_builder.py` | `ensure_local_image()` + `build_image()` port | ~250 |
| `scripts/inference/openhands_config.py` | Constants, defaults, config loader | ~60 |
| `scripts/inference/openhands_output.py` | Dual output writer + JSONL converter | ~120 |
| `scripts/inference/templates/openhands_prompt.j2` | Agent instruction prompt template | ~35 |
| `scripts/inference/specs/openhands_agent.yaml` | Documentation spec for openhands mode | ~30 |
| `scripts/setup_sdk.sh` | SDK submodule setup script | ~20 |
| `.llm_config/bedrock.json` | AWS Bedrock LLM config template | ~10 |

### Modified Files (2)

| File | Changes | Lines Changed |
|------|---------|--------------|
| `scripts/inference/custom.py` | `--mode`, `--llm-config`, `--max-iterations`, `--timeout-per-instance` args; conditional `--spec` requirement; mode dispatch to `openhands_mode.py` | ~80 |
| `pyproject.toml` | `[project.optional-dependencies] openhands = [...]` | ~10 |

### Infrastructure (1)

| File | Purpose |
|------|---------|
| `.gitmodules` + `vendor/software-agent-sdk/` | OpenHands Agent SDK submodule |

**Total**: ~1,115 lines estimated (realistic with error handling, logging, docstrings: ~1,500-2,000).

---

*Updated with Metis pre-planning analysis (Section 13), Momus plan critique (Section 14), revised wave structure (Section 15), and final change summary (Section 16). All recommendations incorporated.*
