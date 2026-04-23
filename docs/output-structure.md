# SWE-Fficiency Pipeline Output Structure

This document describes the directory layout and file formats produced by `run_pipeline.sh`.

## Directory Layout

After a full pipeline run with `--run-id <RUN_ID> --mode openhands`:

```
swefficiency/
├── logs/
│   ├── run_evaluation/<RUN_ID>/
│   │   ├── gold/                                      # Gold patch evaluation
│   │   │   ├── validation_report_<RUN_ID>.json        # Aggregated perf + correctness
│   │   │   └── <instance_id>/                         # Per-instance directory
│   │   │       ├── patch.diff                         # Gold patch applied
│   │   │       ├── perf.sh                            # Workload timing script
│   │   │       ├── perf_output_preedit.txt            # Pre-edit perf stdout
│   │   │       ├── perf_output_postedit.txt           # Post-edit perf stdout
│   │   │       ├── perf_summary.txt                   # Human-readable before/after summary
│   │   │       ├── perf_profiling.sh                  # cProfile script for workload
│   │   │       ├── workload_raw.py                    # Original workload script
│   │   │       ├── workload.py                        # Processed workload (stripped whitespace)
│   │   │       ├── correctness.sh                     # Covering test runner script
│   │   │       ├── correctness_output.txt             # Full stdout from correctness run
│   │   │       ├── covering_tests.txt                 # Test file paths (newline-separated)
│   │   │       ├── covering_test_status.json          # Per-test pass/fail results
│   │   │       ├── raw_correctness_output/            # Per-test-file stdout
│   │   │       │   └── {0..N}.txt
│   │   │       ├── test_status.tar                    # Tar archive of raw_correctness_output/
│   │   │       ├── single_thread_tests.txt            # Tests requiring single-threaded execution
│   │   │       ├── introspection_guard.sh             # AST introspection check script
│   │   │       ├── introspection_patch_check.py       # Patch validity checker (AST-based)
│   │   │       ├── flag_bad_workload.txt              # Present if gold patch worsens perf
│   │   │       └── run_instance.log                   # Docker execution log
│   │   │
│   │   └── gold_as_pred/                              # Gold-as-prediction evaluation
│   │       ├── validation_report_<RUN_ID>.json
│   │       └── <instance_id>/                         # Same structure as gold/
│   │
│   └── run_inference/<RUN_ID>_inference/openhands/
│       ├── metadata.json                              # Run configuration
│       ├── output.jsonl                               # Full agent trajectory per instance
│       ├── predictions.jsonl                          # Extracted patches per instance
│       ├── summary.json                               # Run summary (status, cost, timing)
│       ├── conversations/
│       │   └── <instance_id>.tar.gz                   # OpenHands event archive
│       └── <instance_id>/
│           ├── instance.log                           # Agent execution log
│           ├── openhands_prompt.txt                   # Prompt sent to agent
│           └── patch.diff                             # Generated optimization patch
│
├── eval_reports/
│   ├── eval_report_gold_as_pred.csv                   # Per-instance metrics table
│   └── eval_report_gold_as_pred.json                  # Aggregated scoring summary
│
└── pipeline_run.log                                   # Full pipeline stdout
```

## File Formats

### Evaluation Files

#### `validation_report_<RUN_ID>.json`

Per-instance performance and correctness data from the Docker evaluation harness.

```json
{
  "<instance_id>": {
    "perf_report": {
      "before_mean": 0.013818845999776386,
      "before_sd": 0.01153650949057966,
      "after_mean": 0.02053392099969642,
      "after_sd": 0.012521273820217511,
      "improvement": 0.6729764860778752
    },
    "correctness_report": {
      "test_results": {
        "tests/test_help.py::test_system_ssl": "PASSED",
        "tests/test_requests.py::TestRequests::test_entry_points": "PASSED"
      }
    }
  }
}
```

- `improvement` = `before_mean / after_mean` (higher is better; >1.0 means the patch sped things up)
- `test_results` values: `"PASSED"`, `"FAILED"`, `"SKIPPED"`, `"ERROR"`, `"XFAIL"`

#### `perf_summary.txt`

Human-readable performance summary.

```
Before Mean: 0.013818845999776386
Before SD: 0.01153650949057966
After Mean: 0.02053392099969642
After SD: 0.012521273820217511
Improvement: 67.30%
```

#### `covering_test_status.json`

Maps each test case to its outcome. Used by `report.py` to compute correctness.

```json
{
  "tests/test_help.py::test_system_ssl": "PASSED",
  "tests/test_requests.py::TestRequests::test_invalid_url[MissingSchema-hiwpefhipowhefopw]": "PASSED",
  "tests/test_requests.py::TestRequests::test_use_proxy_from_environment[http-socks5h://proxy.example.com]": "FAILED"
}
```

#### `flag_bad_workload.txt`

Present only when the gold patch does not improve performance. Contains a message like:

```
Improvement is 67.30%, which is not a performance improvement.
```

### Report Files

#### `eval_report_gold_as_pred.json`

Aggregated scores across all instances.

```json
{
  "total_instances": 1,
  "overall_score": 1.7904,
  "proportion_incorrect": 0.0,
  "proportion_correct_but_no_speedup": 0.0,
  "proportion_correct_with_speedup_but_human_no_speedup": 0.0,
  "proportion_human_speedup_or_better": 1.0,
  "report": "eval_report_gold_as_pred.csv"
}
```

- `overall_score` = harmonic mean of `human_speedup_ratio` across all instances (floored at 0.001 per instance)
- `proportion_incorrect` = fraction of instances where any PASS_TO_PASS test fails
- `proportion_human_speedup_or_better` = fraction where `human_speedup_ratio >= 1.0`

#### `eval_report_gold_as_pred.csv`

Per-instance metrics table.

| Column | Description |
|---|---|
| `instance_id` | Instance identifier (e.g., `psf__requests-7342`) |
| `raw_pred_speedup_ratio` | `pre_edit_runtime / post_edit_runtime` (predicted patch) |
| `pred_speedup_ratio` | Same as raw, unless correctness fails → forced to `1.0` |
| `gold_speedup_ratio` | `pre_edit_runtime / post_edit_runtime` (gold patch) |
| `human_speedup_ratio` | `pred_speedup_ratio / gold_speedup_ratio` |
| `correctness` | Binary: `1.0` if all PASS_TO_PASS tests pass, else `0.0` |
| `correctness_pct` | Fraction of PASS_TO_PASS tests that pass |
| `pre_edit_runtime` | Baseline mean runtime (seconds) |
| `patch_length` | Number of changed lines in the patch |

Example:

```csv
instance_id,raw_pred_speedup_ratio,pred_speedup_ratio,gold_speedup_ratio,human_speedup_ratio,correctness,correctness_pct,pre_edit_runtime,patch_length
psf__requests-7342,1.2049,1.2049,0.6730,1.7904,1.0,1.0,0.0138,21
```

### Inference Files

#### `metadata.json`

Run configuration metadata.

```json
{
  "run_id": "requests_full_inference",
  "model_name": "openhands-agent",
  "llm_config": "scripts/inference/llm_configs/bedrock.json",
  "max_iterations": 100,
  "max_fake_responses": 5,
  "num_workers": 1,
  "cpus_per_worker": 4,
  "mem_limit": "12g",
  "build_target": "source-minimal",
  "num_instances": 1,
  "instance_ids": ["psf__requests-7342"],
  "timestamp": "2026-04-23T09:29:21.733355+00:00",
  "llm_model": "bedrock/converse/arn:aws:bedrock:us-east-1:..."
}
```

#### `predictions.jsonl`

One JSON object per line — the extracted patch for each instance.

```json
{"instance_id": "psf__requests-7342", "model_patch": "diff --git a/...", "model_name_or_path": "openhands-agent"}
```

#### `output.jsonl`

Full agent trajectory. One JSON object per line per instance.

```json
{
  "instance_id": "psf__requests-7342",
  "attempt": 1,
  "test_result": {"git_patch": "diff --git a/..."},
  "instruction": "You are a software performance engineer...",
  "error": null,
  "history": [
    {"id": 0, "timestamp": "...", "source": "user", "key": "message", "value": "...", "kind": "MessageAction"},
    {"id": 1, "timestamp": "...", "source": "agent", "key": "thought", "value": "...", "kind": "ThinkAction"}
  ],
  "metrics": "model_name='default' accumulated_cost=0.0 ...",
  "metadata": {
    "model_name": "openhands-agent",
    "cost": 0.0,
    "timestamp": "2026-04-23T09:32:27.679834+00:00"
  }
}
```

- `history` contains the full action/observation trace (typically 30-150 entries)
- `metrics` is a stringified `Metrics` object with token usage and latency data

#### `summary.json`

Run summary with status and timing.

```json
[
  {
    "instance_id": "psf__requests-7342",
    "status": "success",
    "patch": "/path/to/patch.diff",
    "cost": 0.0,
    "elapsed_seconds": 181.9
  }
]
```

#### `conversations/<instance_id>.tar.gz`

Compressed archive of OpenHands event JSONs. Contains `events/` directory with numbered JSON files representing each agent action/observation.

## Pipeline Stages

When invoked with `--dataset <path> --mode openhands`:

| Stage | Description | Key Outputs |
|---|---|---|
| 8 | Gold Eval | `logs/run_evaluation/<RUN_ID>/gold/` |
| 8.5 | Pred Eval (gold-as-pred) | `logs/run_evaluation/<RUN_ID>/gold_as_pred/` |
| 9 | Report | `eval_reports/eval_report_gold_as_pred.{csv,json}` |
| 10 | Inference | `logs/run_inference/<RUN_ID>_inference/openhands/` |

Stages 1-7 (scraping, workload generation, Docker builds) are skipped when `--dataset` is provided with a pre-built dataset.

## Scoring Logic

From `report.py`:

1. **Correctness** (binary): `1.0` if **all** PASS_TO_PASS tests pass; `0.0` otherwise
2. **Pred speedup**: If correctness = 0, forced to `1.0` (no credit)
3. **Human speedup ratio**: `pred_speedup / gold_speedup` — measures how well the predicted patch compares to the human gold patch
4. **Overall score**: Harmonic mean of `human_speedup_ratio` across instances (each floored at `0.001`)

Categories:
- **incorrect**: Any PASS_TO_PASS test fails
- **correct-no-speedup**: All tests pass but `pred_speedup <= 1.0`
- **correct-with-speedup-but-human-no-speedup**: Pred speeds up but gold doesn't
- **human-speedup-or-better**: `human_speedup_ratio >= 1.0`
