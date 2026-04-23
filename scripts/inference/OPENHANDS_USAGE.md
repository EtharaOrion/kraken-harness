# OpenHands Agent Mode — Usage Guide

## Overview

The OpenHands agent mode integrates the OpenHands Agent SDK into the official
SWE-fficiency inference harness. Instead of running a single shell command
inside a Docker container, it runs a multi-turn LLM agent conversation that
can explore code, edit files, run tests, and iteratively optimize performance.

```
┌─────────────────────────────────────────────────────────────────┐
│                    WORKFLOW DIAGRAM                              │
│                                                                 │
│  ┌──────────┐    ┌───────────┐    ┌──────────────┐             │
│  │ HuggingFace│──▶│ Filter    │──▶│ For each     │             │
│  │ Dataset   │    │ Instances │    │ instance:    │             │
│  └──────────┘    └───────────┘    └──────┬───────┘             │
│                                          │                      │
│                    ┌─────────────────────▼──────────────┐       │
│                    │ 1. Pull base SWE-fficiency image   │       │
│                    │ 2. Build agent-server layer on top │       │
│                    │ 3. Create ResourceLimitedWorkspace │       │
│                    │ 4. Copy /testbed → /workspace/     │       │
│                    │ 5. Render instruction prompt       │       │
│                    └─────────────────────┬──────────────┘       │
│                                          │                      │
│                    ┌─────────────────────▼──────────────┐       │
│                    │ AGENT CONVERSATION LOOP             │       │
│                    │                                     │       │
│                    │  Agent ←HTTP→ Agent-Server ←→ Bash  │       │
│                    │                                     │       │
│                    │  • Explore code                     │       │
│                    │  • Edit files                       │       │
│                    │  • Run benchmarks                   │       │
│                    │  • Run tests                        │       │
│                    │  • Iterate until done               │       │
│                    │                                     │       │
│                    │  Max: 500 iters × 10 fake responses │       │
│                    └─────────────────────┬──────────────┘       │
│                                          │                      │
│                    ┌─────────────────────▼──────────────┐       │
│                    │ PATCH EXTRACTION                    │       │
│                    │  git diff --binary <base> HEAD      │       │
│                    │                                     │       │
│                    │ OUTPUT (dual format):               │       │
│                    │  • patch.diff (official format)     │       │
│                    │  • output.jsonl (trajectory)        │       │
│                    │  • predictions.jsonl (for eval)     │       │
│                    └────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | ≥3.12 | SDK requires 3.12+ |
| Docker | Any recent | With buildx support |
| uv | ≥0.8 | For SDK installation |
| Disk | 50+ GB | Docker images are large |
| RAM | 32+ GB recommended | Per-worker: 32g default |

## Setup

### 1. Clone and enter the repo

```bash
git clone https://github.com/swefficiency/swefficiency.git
cd swefficiency
```

### 2. Create Python environment

```bash
uv venv --python 3.12
source .venv/bin/activate
uv sync
```

### 3. Install the OpenHands Agent SDK

```bash
bash scripts/inference/setup_sdk.sh
```

This script:
- Clones the SDK to `vendor/software-agent-sdk/`
- Installs all 4 SDK packages (openhands-sdk, openhands-tools, openhands-workspace, openhands-agent-server)
- Verifies imports

### 4. Authenticate with Docker registries

```bash
echo $CR_PAT | docker login ghcr.io -u YOUR_USERNAME --password-stdin
```

### 5. Configure your LLM

Create a JSON config file at `scripts/inference/llm_configs/`:

**AWS Bedrock (Bearer Token)**:
```json
{
    "model": "bedrock/converse/global.anthropic.claude-opus-4-6-v1",
    "aws_region_name": "ap-south-1"
}
```
Then set: `export AWS_BEARER_TOKEN_BEDROCK="your-token"`

**AWS Bedrock (IAM)**:
```json
{
    "model": "bedrock/converse/global.anthropic.claude-opus-4-6-v1",
    "aws_access_key_id": "AKIA...",
    "aws_secret_access_key": "...",
    "aws_region_name": "ap-south-1"
}
```

**Anthropic**:
```json
{
    "model": "anthropic/claude-sonnet-4-5-20250929",
    "api_key": "sk-ant-..."
}
```

**OpenAI**:
```json
{
    "model": "openai/gpt-4o",
    "api_key": "sk-..."
}
```

## Running Inference

### Single instance (recommended for first test)

```bash
python scripts/inference/custom.py \
    --mode openhands \
    --run-id my_first_run \
    --llm-config scripts/inference/llm_configs/bedrock.json \
    --instance-ids numpy__numpy-11720 \
    --num-workers 1 \
    --disable-cpu-pinning
```

### Multiple instances

```bash
python scripts/inference/custom.py \
    --mode openhands \
    --run-id full_run \
    --llm-config scripts/inference/llm_configs/bedrock.json \
    --num-workers 4 \
    --max-instances 10
```

### Subset by regex

```bash
python scripts/inference/custom.py \
    --mode openhands \
    --run-id pandas_only \
    --llm-config scripts/inference/llm_configs/bedrock.json \
    --instance-regex "pandas.*"
```

### Dry run (list instances without running)

```bash
python scripts/inference/custom.py \
    --mode openhands \
    --run-id test \
    --llm-config scripts/inference/llm_configs/bedrock.json \
    --dry-run
```

## CLI Parameters (OpenHands Mode)

| Parameter | Default | Description |
|---|---|---|
| `--mode openhands` | `default` | **Required** to activate OpenHands mode |
| `--llm-config PATH` | — | **Required** Path to LLM config JSON |
| `--run-id STRING` | — | **Required** Unique run identifier |
| `--num-workers N` | 2 | Parallel Docker workers |
| `--max-iterations N` | 500 | Max agent steps per conversation.run() |
| `--max-fake-responses N` | 10 | Max fake user messages in multi-turn loop |
| `--cpus-per-worker N` | 4 | Logical CPUs per container |
| `--cpus-to-skip N` | 4 | Host CPUs to reserve |
| `--mem-limit STRING` | `32g` | Docker memory limit |
| `--disable-cpu-pinning` | off | Skip CPU pinning (use on macOS/non-Linux) |
| `--build-target STRING` | `source-minimal` | Docker image build target |
| `--force-build` | off | Force rebuild of agent-server images |
| `--no-cleanup-images` | off | Keep agent-server images after completion |
| `--model-name STRING` | `openhands-agent` | Name in prediction JSONL output |
| `--prompt-template PATH` | built-in | Custom Jinja2 instruction template |
| `--instance-ids ID ...` | all | Specific instance IDs to run |
| `--instance-regex REGEX` | — | Regex filter on instance IDs |
| `--max-instances N` | — | Cap on number of instances |
| `--dataset STRING` | `swefficiency/swefficiency` | HuggingFace dataset |
| `--split STRING` | `test` | Dataset split |
| `--dry-run` | off | List selected instances and exit |

## Output Structure

```
logs/run_inference/<run_id>/openhands/
├── output.jsonl              # Full trajectory per instance (OpenHands format)
├── output_errors.jsonl       # Error records
├── predictions.jsonl         # Auto-converted for swefficiency eval
├── summary.json              # Per-instance status summary
├── <instance_id>/
│   ├── patch.diff            # Git patch (official format)
│   └── openhands_prompt.txt  # Rendered instruction sent to agent
└── <instance_id>/
    ├── patch.diff
    └── openhands_prompt.txt
```

### output.jsonl format (per line)

```json
{
    "instance_id": "numpy__numpy-11720",
    "attempt": 1,
    "test_result": {"git_patch": "diff --git a/..."},
    "instruction": "You are a software performance engineer...",
    "error": null,
    "history": [...],
    "metrics": {...},
    "metadata": {
        "model_name": "openhands-agent",
        "cost": 0.42,
        "timestamp": "2026-04-22T14:30:00+00:00"
    }
}
```

### predictions.jsonl format (auto-generated, for eval)

```json
{"instance_id": "numpy__numpy-11720", "model_patch": "diff --git a/...", "model_name_or_path": "openhands-agent"}
```

## Evaluation Pipeline

After inference completes, evaluate using the official harness:

### Step 1: Run gold baseline

```bash
swefficiency eval --run_id my_eval --num_workers 12
```

### Step 2: Evaluate your predictions

```bash
swefficiency eval \
    --run_id my_eval \
    --num_workers 12 \
    --prediction_path logs/run_inference/<run_id>/openhands/predictions.jsonl
```

### Step 3: Generate report

```bash
swefficiency report \
    --gold_run logs/run_evaluation/my_eval/gold \
    --pred_run logs/run_evaluation/my_eval/<model_name>
```

## Architecture

### File Layout

```
scripts/inference/
├── custom.py                 # Main CLI (modified: added --mode openhands)
├── openhands_mode.py         # Orchestrator: run_openhands_inference()
├── openhands_workspace.py    # ResourceLimitedDockerWorkspace
├── openhands_image_builder.py # Agent-server image builder
├── openhands_config.py       # Constants and defaults
├── openhands_output.py       # Dual output writer + JSONL converter
├── setup_sdk.sh              # SDK installation script
├── llm_configs/
│   └── bedrock.json          # LLM config template
├── templates/
│   └── openhands_prompt.j2   # Agent instruction template
└── specs/
    └── openhands_agent.yaml  # Default YAML spec for openhands mode
```

### How it works

1. **`custom.py`** parses CLI args. If `--mode openhands`, delegates to `openhands_mode.run_openhands_inference()`
2. **`openhands_mode.py`** sets up CPU division, creates ThreadPoolExecutor, dispatches `process_instance_openhands()` per instance
3. **`process_instance_openhands()`** for each instance:
   - Calls `ensure_image()` to build/check the agent-server Docker image
   - Creates `ResourceLimitedDockerWorkspace` with CPU/mem limits
   - Copies `/testbed/` to `/workspace/<repo>__<version>/`
   - Loads LLM from JSON config, creates Agent + Conversation
   - Runs multi-turn conversation loop with fake user responses
   - Extracts patch via `git diff --binary` (official format)
   - Writes both `patch.diff` and trajectory to `output.jsonl`
4. After all instances, converts `output.jsonl` → `predictions.jsonl` for eval

## Troubleshooting

### "No such file or directory: '/sys/devices/system/cpu'"
You're on macOS. Use `--disable-cpu-pinning`.

### SDK import errors
Run `bash scripts/inference/setup_sdk.sh` to reinstall.

### Docker image build fails
Ensure `docker buildx` is installed and GHCR auth is configured.

### Agent runs out of iterations
Increase `--max-iterations` (default 500) or `--max-fake-responses` (default 10).

### Empty patches
The agent may not have found optimizations. Check `openhands_prompt.txt` in the instance log dir.
