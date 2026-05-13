<div align="center">
<div align="center">
  <img src="docs/assets/logos/kraken.png" alt="Kraken Logo" width="500"/>
</div>
  <p><em>Evaluation framework for benchmarking LLM coding agents on real-world performance optimization</em></p>

  <p>
    <a href="https://huggingface.co/datasets/ethara/Kraken"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Dataset-blue" alt="Dataset"></a>
    <a href="https://arxiv.org/abs/2511.06090"><img src="https://img.shields.io/badge/Paper-arXiv%3A2511.06090-b31b1b?logo=arxiv&logoColor=white" alt="Paper"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-lightgrey.svg" alt="License"></a>
  </p>
</div>

---

Kraken is a repository-level evaluation framework for benchmarking LLM coding agents on **performance optimization**. Each task ships a full codebase snapshot, a targeted performance workload to speed up, and the subset of repository correctness tests that must remain green. Patches are scored using the **Harmonic Speedup Ratio (HSR)**, jointly measuring correctness and runtime efficiency.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Dataset](#dataset)
- [Evaluation](#evaluation)
- [Agent Integration](#agent-integration)
- [Pipeline](#pipeline)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Kraken evaluates *pass-to-pass* performance engineering: start from a codebase and a slow workload, improve runtime, and don't break behavior. The focus is on investigation (profiling/localization) and correctness-preserving edits — mirroring how performance engineers work day-to-day.

Unlike traditional SWE benchmarks that measure only functional correctness, Kraken jointly evaluates **correctness and efficiency**. A patch that breaks tests scores zero, even if it's fast.

### Key Capabilities

- **Performance-Aware Evaluation** — Jointly measures functional correctness and runtime speedup using HSR
- **Docker-Isolated Runs** — Every evaluation runs in a prebuilt container with CPU/memory pinning for reproducibility
- **Flexible Agent Integration** — Works with OpenHands, SWE-agent, Cursor CLI, or any agent that produces git patches
- **Full Pipeline Automation** — `run_pipeline.sh` orchestrates PR scraping → dataset construction → evaluation → report
- **Rich Analysis Toolkit** — Scripts for flamegraph profiling, workload analysis, difficulty classification, and model comparison
- **Extensible** — Add new repositories via auto-detect pipeline with version discovery and Docker image building

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
swefficiency eval --run_id my_eval --num_workers 12
```

Results stored in `logs/run_evaluation/my_eval/gold/`.

### 2. Evaluate model predictions

```bash
swefficiency eval --run_id my_eval --num_workers 12 --prediction_path predictions.jsonl
```

Prediction format (JSONL):

```json
{"instance_id": "<id>", "model_patch": "<patch_text>", "model_name_or_path": "<model_name>"}
```

Results stored in `logs/run_evaluation/my_eval/<model_name>/`.

### 3. Generate report

```bash
swefficiency report \
    --gold_run logs/run_evaluation/my_eval/gold \
    --pred_run logs/run_evaluation/my_eval/<model_name>
```

Outputs `eval_reports/eval_report_<model_name>.csv` (per-instance) and `.json` (summary metrics).

### Reproducibility Setup

For faithful reproduction, use a dedicated machine (GCP `n2-standard-64` recommended) with Docker CPU pinning:

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
| `--num_workers` | `4` | Parallel evaluation workers |
| `--run_id` | auto-generated | Run identifier for output directories |
| `--dataset` | `swefficiency/swefficiency` | HuggingFace dataset or local JSONL path |
| `--prediction_path` | — | Path to predictions JSONL (omit for gold baseline) |
| `--instances_regex` | — | Filter instances by regex pattern (e.g. `"numpy.*"`) |
| `--force_rerun` | `false` | Re-run even if cached results exist |

### `swefficiency report`

| Flag | Description |
|:---|:---|
| `--gold_run` (required) | Path to gold run directory |
| `--pred_run` (required) | Path to prediction run directory |
| `--report_output` | Output directory (default: `eval_reports/`) |
| `--num_workers` | Parallel workers (default: `4`) |

---

## Dataset

The Kraken benchmark is available on **[Hugging Face](https://huggingface.co/datasets/ethara/Kraken)** (20 instances, 6 repositories).

### Statistics

| Property | Value |
|:---|:---|
| Total Instances | 20 |
| Source Repositories | 6 |
| Gold Speedup Range | 1.02× – 26.92× |
| Mean Gold Speedup | 4.22× |
| Median Gold Speedup | 1.49× |
| Primary Metric | Harmonic Speedup Ratio (HSR) |

### Repository Breakdown

| Repository | Instances | Domain | Speedup Range |
|:---|---:|:---|---:|
| `networkx/networkx` | 10 | Graph algorithms | 1.02× – 13.09× |
| `pallets/flask` | 4 | Web framework | 1.10× – 2.50× |
| `fastapi/fastapi` | 2 | Async web framework | 1.61× – 9.36× |
| `pydantic/pydantic` | 2 | Data validation | 1.67× – 6.51× |
| `encode/httpx` | 1 | HTTP client | 26.92× |
| `pallets/jinja` | 1 | Template engine | 1.25× |

### Loading

```python
from datasets import load_dataset

dataset = load_dataset("ethara/Kraken", split="test")
instance = dataset[0]
print(f"{instance['instance_id']} — {instance['speedup']:.2f}× speedup")
```

---

## Evaluation

### Metric: HSR

The **Harmonic Speedup Ratio (HSR)** balances correctness and speedup into a single score. For each instance:

1. **Apply** — apply the candidate patch at `base_commit`
2. **Test** — run `FAIL_TO_PASS` + `PASS_TO_PASS` test suites
3. **Benchmark** — measure runtime before and after the patch under the declared workload
4. **Score** — derive correctness (binary), speedup ratio, and HSR

Patches that fail to apply or break tests score zero.

### Baseline Results

| Model | Correctness | HSR (Harmonic) | Mean HSR | Mean Speedup |
|:---|:---:|:---:|:---:|:---:|
| GLM-5 | 14 / 20 (70%) | 0.313 | 0.984 | 2.84× |
| Kimi K2.5 | 12 / 20 (60%) | 0.268 | 0.606 | 1.62× |

### Per-Difficulty Correctness

| Difficulty | GLM-5 | Kimi K2.5 |
|:---|---:|---:|
| Easy | 4 / 4 (100%) | 4 / 4 (100%) |
| Medium | 4 / 5 (80%) | 4 / 5 (80%) |
| Hard | 5 / 9 (56%) | 3 / 9 (33%) |
| Expert | 1 / 2 (50%) | 1 / 2 (50%) |

Both models achieve perfect correctness on Easy instances but struggle with Hard problems requiring deep framework knowledge and multi-step reasoning.

### Visualizations

<table>
  <tr>
    <td width="50%"><img src="docs/assets/figures/swefficiency_overview.png" alt="Overview"/><br/><b>Fig 1.</b> Benchmark overview</td>
    <td width="50%"><img src="docs/assets/figures/correctness_breakdown.png" alt="Correctness"/><br/><b>Fig 2.</b> Correctness by difficulty</td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/assets/figures/scaling_trends.png" alt="Scaling"/><br/><b>Fig 3.</b> Scaling trends</td>
    <td width="50%"><img src="docs/assets/figures/diff_classification_counts.png" alt="Diff Classification"/><br/><b>Fig 4.</b> Diff classification</td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/assets/figures/flamegraph.png" alt="Flamegraph"/><br/><b>Fig 5.</b> Flamegraph analysis</td>
    <td width="50%"><img src="docs/assets/figures/workload_distribution.png" alt="Workload"/><br/><b>Fig 6.</b> Workload distribution</td>
  </tr>
</table>

---

## Agent Integration

Kraken provides a Docker-based inference harness at `scripts/inference/custom.py` for running agents against benchmark instances.

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

Each instance produces a git patch at `logs/run_inference/<run_id>/<instance_id>/patch.diff`, ready for `swefficiency eval`.

---

## Pipeline

The `run_pipeline.sh` orchestrator automates the full workflow:

```
Scrape PRs → Filter Performance PRs → Version Detection → Detect Specs
→ Workload Generation → Assemble Dataset → Build Docker → Agent Inference
→ Evaluate Patches → Generate Report
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
│   ├── report.py               # Report generation
│   ├── harness/                # Docker-based evaluation
│   ├── collect/                # Dataset collection
│   ├── versioning/             # Version detection
│   ├── perf_filter/            # Performance PR filtering
│   └── workload/               # Workload generation
├── scripts/
│   ├── eval/                   # Evaluation scripts
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

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines. This codebase began as a fork from [SWE-Gym's SWE-Bench fork](https://github.com/SWE-Gym/SWE-Bench-Fork) and extends the pipeline with performance-specific commit filtering, workload evaluation, and additional analysis tooling.

### Methodology

Kraken builds on the SWE-fficiency methodology (Ma et al., 2025), which extends SWE-Bench with performance workloads and the Harmonic Speedup Ratio (HSR) metric.

---

## License

Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

This is not an officially supported Google product.
