# SWE-Fficiency Pipeline Guide

## Overview

`run_pipeline.sh` is the end-to-end orchestrator for the SWE-fficiency benchmark pipeline. It scrapes GitHub PRs, filters for performance-related changes, builds Docker containers, evaluates gold patches, runs agent inference, and generates comparison reports.

When using a **pre-built dataset** (recommended for our `psf/requests` work), stages 1–5 are skipped automatically.

## Quick Start

```bash
# Activate the virtual environment first
source .venv/bin/activate

# Full pipeline: eval + pred_eval + report + inference (all 3 instances)
./run_pipeline.sh \
  --dataset artifacts/final/requests-dataset.jsonl \
  --run-id <YOUR_RUN_ID> \
  --mode openhands \
  --max-workers 1 \
  --timeout 1800

# Eval-only (no inference)
./run_pipeline.sh \
  --dataset artifacts/final/requests-dataset.jsonl \
  --run-id <YOUR_RUN_ID> \
  --stages eval,pred_eval,report \
  --max-workers 1 \
  --timeout 1800

# Inference-only
./run_pipeline.sh \
  --dataset artifacts/final/requests-dataset.jsonl \
  --run-id <YOUR_RUN_ID> \
  --mode openhands \
  --stages inference \
  --max-workers 1 \
  --timeout 1800
```

## Pipeline Stages

| # | Stage Name | Description | Key Output |
|---|---|---|---|
| 1–3 | `scrape` | Scrape GitHub PRs, build task instances | `artifacts/tasks/` |
| 4 | `perf_filter` | Filter for performance-related PRs | `artifacts/perf_filtered/` |
| 5 | `versioning` | Detect Python versions per instance | `artifacts/versioned/` |
| 6 | `detect_specs` | Auto-detect install cmd, test cmd, deps | `artifacts/enriched/` |
| 7 | `workload` | LLM-generated performance workloads (Bedrock) | `logs/workload_generation/` |
| 8 | `eval` | Gold patch evaluation (perf + correctness) | `logs/run_evaluation/<RUN_ID>/gold/` |
| 8.5 | `pred_eval` | Gold-as-prediction evaluation | `logs/run_evaluation/<RUN_ID>/gold_as_pred/` |
| 9 | `report` | Generate comparison CSV + JSON | `eval_reports/eval_report_gold_as_pred.*` |
| 10 | `inference` | OpenHands agent generates optimization patches | `logs/run_inference/<RUN_ID>_inference/` |

**When `--dataset` is provided**: Stages 1–7 are skipped. The pipeline starts at stage 8 (eval).

**When `--mode openhands` is NOT set**: Stage 10 (inference) is skipped.

### What Each Stage Does

**Stage 8 (eval)**: For each instance in the dataset, spins up a Docker container with the repo at the base commit. Applies the gold patch. Runs the workload script before/after patch to measure speedup. Runs covering tests for correctness. Outputs `perf_summary.txt`, `covering_test_status.json`, etc.

**Stage 8.5 (pred_eval)**: Creates a "gold-as-prediction" JSONL (gold patches pretending to be agent predictions). Runs the same eval as stage 8. This establishes the upper bound — what a perfect agent would score.

**Stage 9 (report)**: Compares gold eval vs pred eval. Computes `human_speedup_ratio`, binary correctness, and the overall harmonic mean score. Outputs CSV + JSON to `eval_reports/`.

**Stage 10 (inference)**: Runs the OpenHands agent against each instance. The agent reads the code, understands the performance issue, and generates an optimization patch. Outputs patches, trajectories, and metadata.

## CLI Parameters

### Core Options

| Parameter | Default | Description |
|---|---|---|
| `--repo OWNER/NAME` | `psf/requests` | Target GitHub repository |
| `--run-id NAME` | auto-timestamp | Unique identifier for this run. Used in output directory names. |
| `--dataset PATH` | — | Path to pre-built dataset JSONL. **Skips stages 1–7.** |
| `--mode MODE` | `default` | Set to `openhands` to enable inference (stage 10) |
| `--max-workers N` | `1` | Parallel workers for Docker eval containers |
| `--timeout N` | `1800` | Eval timeout in seconds per instance |
| `--dry-run` | false | Print commands without executing |

### Stage Control

| Parameter | Description |
|---|---|
| `--stages LIST` | Comma-separated list of stages to run. Example: `--stages eval,report` |
| `--start-from STAGE` | Start from this stage, skip all prior stages |
| `--stop-after STAGE` | Stop after this stage, skip all later stages |
| `--skip-scrape` | Skip stages 1–6 (use existing enriched data) |
| `--skip-workload` | Skip stage 7 (workload generation) |

**Stage names** (for `--stages`, `--start-from`, `--stop-after`):
`scrape`, `perf_filter`, `versioning`, `detect_specs`, `workload`, `eval`, `pred_eval`, `report`, `inference`

### Scrape Options (stages 1–5)

| Parameter | Default | Description |
|---|---|---|
| `--cutoff-date YYYYMMDD` | `20180101` | Only scrape PRs after this date |
| `--max-pulls N` | unlimited | Max PRs to scrape |

## Eval Execution Flow

When `--stages eval` runs:

1. **Docker build**: If Docker image `sweb.eval.<instance_id>:latest` doesn't exist, builds it (base → env → instance layers).
2. **Container launch**: Creates container from instance image, mounts workload scripts.
3. **Pre-edit perf**: Runs `timeit.repeat()` workload on unpatched code → `perf_output_preedit.txt`.
4. **Apply gold patch**: `git apply patch.diff` inside container.
5. **Post-edit perf**: Runs same workload on patched code → `perf_output_postedit.txt`.
6. **Correctness**: Runs covering tests (`pytest --no-header -rA --tb=no ...`) → `covering_test_status.json`.
7. **Process isolation** (if enabled): Each timeit repeat runs in a forked subprocess to prevent cache contamination.

## Scoring Logic

From `report.py`:

1. **Correctness** (binary): `1.0` if ALL `PASS_TO_PASS` tests pass; `0.0` otherwise
2. **Pred speedup**: If correctness = 0, forced to `1.0` (no credit for broken patches)
3. **Human speedup ratio**: `pred_speedup / gold_speedup` — how well predicted patch compares to gold
4. **Overall score**: Harmonic mean of `human_speedup_ratio` across instances (each floored at `0.001`)

Categories:
- **incorrect**: Any PASS_TO_PASS test fails
- **correct-no-speedup**: All tests pass but pred_speedup ≤ 1.0
- **correct-with-speedup-but-human-no-speedup**: Pred speeds up but gold doesn't
- **human-speedup-or-better**: human_speedup_ratio ≥ 1.0

## Dataset Format

Each line in the JSONL dataset contains:

| Field | Type | Description |
|---|---|---|
| `instance_id` | string | e.g., `psf__requests-7342` |
| `repo` | string | e.g., `psf/requests` |
| `version` | string | e.g., `2.33` |
| `base_commit` | string | Git SHA of the pre-patch state |
| `patch` | string | Gold patch (unified diff) |
| `test_patch` | string | Test-only changes (if any) |
| `workload` | string | Python `timeit.repeat()` workload script |
| `PASS_TO_PASS` | list | Test IDs that must pass before and after |
| `FAIL_TO_PASS` | list | Test IDs that the patch should fix |
| `covering_tests` | list | All test files to run for correctness |
| `install_cmd` | string | How to install the project in Docker |
| `test_cmd_override` | string | Pytest command for this repo/version |
| `speedup` | number | Gold patch speedup ratio from eval |
| `environment_setup_commit` | string | Commit for env setup |

## Docker Images

The pipeline creates a layered Docker image stack:

```
sweb.base:latest              ← Base image (miniconda + Python)
  └── sweb.env.<hash>:latest  ← Repo dependencies installed
      └── sweb.eval.<instance_id>:latest  ← Repo at specific commit
```

Images are cached — if they already exist, the build is skipped.

**Important**: If you previously used `docker buildx` with a `docker-container` driver (e.g., for multiarch builds), switch back to the default builder before running the pipeline:

```bash
docker context use default
docker buildx use default
```

The `docker-container` driver cannot access host-local images and will fail with "image not found" errors.

## Environment Requirements

- **Python**: 3.12+ (via `.venv`)
- **Docker**: Docker Desktop running
- **swefficiency**: `pip install -e .` in the venv
- **AWS credentials**: Required for inference (Bedrock LLM config at `scripts/inference/llm_configs/bedrock.json`)
- **GitHub token**: Required for scrape stages (set `GITHUB_TOKENS` or `GITHUB_TOKEN` env var)

## Troubleshooting

### `pytest: command not found` in correctness output
The dataset's `install_cmd` doesn't install test dependencies. Fix: use `pip install -e . && pip install pytest <other-test-deps>`.

### `covering_test_status.json` is empty `{}`
The pytest output format doesn't match the log parser. The parser expects `-rA` flag output (lines starting with `PASSED`/`FAILED`). Fix: ensure `test_cmd_override` includes `--no-header -rA --tb=no -p no:cacheprovider --continue-on-collection-errors`.

### correctness = 0.0 despite tests passing
Correctness is BINARY — ALL `PASS_TO_PASS` tests must pass. Check for environment-specific test failures (e.g., proxy tests that need network access). Filter `PASS_TO_PASS` to only include tests that actually pass in Docker.

### Wild perf variance between runs
Expected. Docker container scheduling, CPU thermal throttling, and background processes cause 2-4x variance. The `process_isolation` flag helps by forking each timeit repeat into a separate subprocess.

### Images not found during eval
Ensure you're using the `default` Docker buildx builder (not a `docker-container` driver builder). Run `docker buildx use default`.

## Run History (psf/requests dataset)

| Run | Instances | Correctness | Gold Speedup | Notes |
|---|---|---|---|---|
| run1 | 3 | 0.0 (all) | 1.26/0.96/0.99 | pytest missing in Docker |
| run2 | 3 | 0.0 (all) | 1.04/0.68/1.06 | Parser format mismatch |
| run3 | 3 | 0.0 (7342 only) | 1.08/0.65/1.06 | PEP 735 + cache collision |
| run4 | 3 | 0.0 (7342) | — | Cache collision (shared repo+version key) |
| run5 | 1 (7342) | 1.0 ✅ | 3.81 | PASS_TO_PASS filtered |
| requests_full | 1 (7342) | 1.0 ✅ | 0.67 | Full pipeline with inference |
| requests_7245v2 | 1 (7245) | 1.0 ✅ | 1.04 | After all fixes |
| requests_inference | 3 | — | — | Inference only, all patches generated |

### Fixes Applied (cumulative)

1. **Fix #5**: `run_pipeline.sh` — `--run_correctness` and `--process_isolation` changed from `false` to `true`
2. **Fix #6**: `install_cmd` — explicit `pip install pytest` + test deps (pytest not in `[test]` extras for some commits)
3. **Fix #7**: `test_cmd_override` — added `-rA --no-header --tb=no` flags for parser compatibility
4. **Fix #8/9**: Unified `install_cmd` across instances (PEP 735 `[dependency-groups]` + dynamic_specs cache collision)
5. **Fix #10**: `PASS_TO_PASS` stored as native JSON list, filtered to actually-passing tests in Docker
6. **Universal U1**: `dynamic_specs.py` — cache key includes `instance_id` (prevents cache collision)
7. **Universal U2**: `report.py` — parses `PASS_TO_PASS` string→list robustly
8. **Universal U3**: `test_spec.py` — auto-injects `-rA` flags when test_cmd uses pytest
