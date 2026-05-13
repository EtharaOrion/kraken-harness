<div align="center">
<div align="center">
  <img src="docs/assets/logos/kraken.png" alt="Kraken Logo" width="500"/>
</div>
  <p><em>Evaluation framework for benchmarking LLM coding agents on real-world performance optimization</em></p>
  <p>
    <a href="https://arxiv.org/abs/2511.06090"><img src="https://img.shields.io/badge/Paper-arXiv%3A2511.06090-b31b1b?logo=arxiv&logoColor=white" alt="Paper"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-lightgrey.svg" alt="License"></a>
  </p>
</div>

---

Kraken is a repository-level RL environment for training LLM coding agents on **performance optimization**. Each task provides an agent with a full codebase snapshot, a targeted performance workload to speed up, and a set of correctness tests that must remain green. The agent is scored using the **Harmonic Speedup Ratio (HSR)**, jointly measuring correctness and runtime efficiency.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Agent Integration](#agent-integration)
- [Pipeline](#pipeline)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Kraken frames *pass-to-pass* performance engineering as an RL problem: start from a codebase and a slow workload, improve runtime, and don't break behavior. The focus is on investigation (profiling/localization) and correctness-preserving edits — mirroring how performance engineers work day-to-day.

Unlike traditional coding benchmarks that measure only functional correctness, Kraken jointly rewards **correctness and efficiency**. An agent that breaks tests receives zero reward, regardless of speed.

### Key Features

- **Performance-Aware Reward** — Jointly scores functional correctness and runtime speedup via HSR. Patches that break tests score zero.
- **Docker-Isolated Environment** — Every run uses a prebuilt container with CPU/memory pinning for reproducible training runs.
- **Flexible Agent Support** — Works with OpenHands, SWE-agent, Cursor CLI, or any agent that produces git patches.
- **Full Pipeline Automation** — `run_pipeline.sh` handles the entire workflow from data collection to reward computation.
- **Rich Analysis Toolkit** — Scripts for flamegraph profiling, workload analysis, difficulty classification, and model comparison.
- **Extensible** — Add new repositories via auto-detect pipeline with version discovery and Docker image building.

---

## Installation

Requires Python 3.8+. Linux host recommended.

```bash
git clone https://github.com/Ethara-Ai/kraken.git
cd kraken

# Using uv (recommended)
uv venv --python 3.12
source .venv/bin/activate
uv sync

# Or using pip
pip install -e .
```

---

## Quick Start

### 1. Run the gold baseline

Establishes reference performance using expert (human) patches:

```bash
swefficiency eval --run_id my_run --num_workers 12
```

Results stored in `logs/run_evaluation/my_run/gold/`.

### 2. Run an agent

```bash
swefficiency eval --run_id my_run --num_workers 12 --prediction_path agent_predictions.jsonl
```

Prediction format (JSONL):

```json
{"instance_id": "<id>", "model_patch": "<patch_text>", "model_name_or_path": "<agent_name>"}
```

Results stored in `logs/run_evaluation/my_run/<agent_name>/`.

### 3. Score the agent

```bash
swefficiency report \
    --gold_run logs/run_evaluation/my_run/gold \
    --pred_run logs/run_evaluation/my_run/<agent_name>
```

Outputs `eval_reports/eval_report_<agent_name>.csv` (per-instance results) and `.json` (summary metrics including HSR).

### Reproducibility Setup

For reproducible training runs, use a dedicated machine (GCP `n2-standard-64` recommended) with Docker CPU pinning:

```bash
bash scripts/vm/setup_vm.sh
sudo scripts/vm/setup_docker.sh MEM_MAX MEM_HIGH
```

Use `--num_workers 12` for 4 vCPUs / 16 GB RAM per worker.

---

## CLI Reference

### `swefficiency eval`

| Flag | Default | Description |
|:---|:---|:---|
| `--num_workers` | `4` | Parallel workers |
| `--run_id` | auto-generated | Run identifier for output directories |
| `--dataset` | `swefficiency/swefficiency` | HuggingFace dataset or local JSONL path |
| `--prediction_path` | — | Path to agent predictions JSONL (omit for gold baseline) |
| `--instances_regex` | — | Filter instances by regex pattern (e.g. `"numpy.*"`) |
| `--force_rerun` | `false` | Re-run even if cached results exist |

### `swefficiency report`

| Flag | Description |
|:---|:---|
| `--gold_run` (required) | Path to gold run directory |
| `--pred_run` (required) | Path to agent prediction run directory |
| `--report_output` | Output directory (default: `eval_reports/`) |
| `--num_workers` | Parallel workers (default: `4`) |

---

## Agent Integration

Kraken provides a Docker-based inference harness at `scripts/inference/custom.py` for running agents against environment tasks.

### OpenHands

```bash
python scripts/inference/custom.py \
  --run-id openhands_run \
  --spec scripts/inference/specs/openhands_agent.yaml \
  --num-workers 4 \
  --max-instances 10
```

### Cursor CLI

```bash
python scripts/inference/custom.py \
  --run-id cursor_run \
  --spec scripts/inference/specs/cursor_cli.yaml \
  --num-workers 4 \
  --var cursor_cli_args="--max-steps 75"
```

Each instance produces a git patch at `logs/run_inference/<run_id>/<instance_id>/patch.diff`, ready for scoring via `swefficiency eval`.

---

## Pipeline

The `run_pipeline.sh` orchestrator automates the full workflow:

```
Scrape PRs → Filter Performance PRs → Version Detection → Detect Specs
→ Workload Generation → Assemble Dataset → Build Docker → Agent Run
→ Score Patches → Generate Report
```

```bash
# Full pipeline from scratch
./run_pipeline.sh --repo owner/repo --run-id my_run

# Use existing dataset (skips stages 1-6)
./run_pipeline.sh --dataset artifacts/final/dataset.jsonl --run-id my_run --stages eval,pred_eval,report

# With agent inference
./run_pipeline.sh --dataset artifacts/final/dataset.jsonl --run-id my_run --mode openhands
```

---

## Project Structure

```
.
├── pyproject.toml              # Package configuration
├── run_pipeline.sh             # Pipeline orchestrator
├── swefficiency/               # Python package
│   ├── cli.py                  # CLI entrypoint
│   ├── report.py               # Report generation (HSR scoring)
│   ├── harness/                # Docker-based environment
│   ├── collect/                # Dataset collection
│   ├── versioning/             # Version detection
│   ├── perf_filter/            # Performance PR filtering
│   └── workload/               # Workload generation
├── scripts/
│   ├── eval/                   # Scoring scripts
│   ├── inference/              # Agent harness
│   ├── perf/                   # Performance analysis
│   ├── vm/                     # Docker/VM setup
│   └── slurm/                  # Cluster support
├── analysis/                   # Research scripts + plots
├── tests/                      # Test suite
└── docs/                       # Documentation + figures
```

---

## Contributing

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines. This codebase began as a fork from [SWE-Gym's SWE-Bench fork](https://github.com/SWE-Gym/SWE-Bench-Fork) and extends the pipeline with performance-specific commit filtering, workload evaluation, and additional training tooling.

---

## License

Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

This is not an officially supported Google product.
