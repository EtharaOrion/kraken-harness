# Output Format Comparison: Three SWE-fficiency Codebases

> **Date**: April 23, 2026  
> **Scope**: Detailed comparison of output files, schemas, and compatibility across three codebases  
> **Methodology**: Source code analysis + live run validation + Metis/Oracle verification

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [System A — OpenHands Benchmarks](#3-system-a--openhands-benchmarks)
4. [System B — Official SWE-fficiency](#4-system-b--official-swe-fficiency)
5. [System C — Our Modified Code](#5-system-c--our-modified-code)
6. [Side-by-Side Schema Comparison](#6-side-by-side-schema-comparison)
7. [Compatibility Matrix](#7-compatibility-matrix)
8. [Detailed Field-Level Comparison](#8-detailed-field-level-comparison)
9. [Silent Incompatibilities](#9-silent-incompatibilities)
10. [File Production Differences](#10-file-production-differences)
11. [Evaluation Bridge Analysis](#11-evaluation-bridge-analysis)
12. [Key Takeaways](#12-key-takeaways)
13. [Recommendations](#13-recommendations)

---

## 1. Executive Summary

| Aspect | System A (OpenHands Benchmarks) | System B (Official SWE-fficiency) | System C (Our Modified Code) |
|--------|------|------|------|
| **Primary output** | `output.jsonl` (full trajectory) | `patch.diff` + evaluation logs | `output.jsonl` + `predictions.jsonl` + `patch.diff` |
| **Trajectory data** | ✅ Full agent history + metrics | ❌ None (black-box inference) | ✅ Full agent history + metrics |
| **Eval-ready predictions** | ❌ Requires `oh_conversion.py` | ✅ Native via `--prediction_path` | ✅ Auto-generated `predictions.jsonl` |
| **Report generation** | ❌ None built-in | ✅ `swefficiency report` CLI | ✅ Uses System B's report pipeline |
| **Conversation archive** | ✅ `conversations/*.tar.gz` | ❌ Not applicable | ✅ `conversations/*.tar.gz` |
| **Per-instance logs** | ✅ `logs/instance_*.log` | ✅ `run_instance.log` | ✅ `instance.log` per dir |

---

## 2. System Overview

### 2.1 What Each System Does

```
System A (OpenHands Benchmarks)
├── INFERENCE ONLY — runs OpenHands agent against SWE-fficiency instances
├── Output: Trajectory JSONL + conversation archives
└── Eval: Must use System B's eval harness via oh_conversion.py bridge

System B (Official SWE-fficiency)
├── INFERENCE — runs any agent via YAML spec (black-box docker exec)
├── EVALUATION — Docker-based perf + correctness testing
├── REPORT — Harmonic mean Speedup Ratio (SR) calculation
└── Output: Patches, eval logs, perf summaries, CSV/JSON reports

System C (Our Modified Code = System B + OpenHands agent mode)
├── INFERENCE — adds --mode openhands to System B's custom.py
├── Output: System A-style trajectory + System B-compatible predictions
├── EVALUATION — Uses System B's eval harness unchanged
└── REPORT — Uses System B's report pipeline unchanged
```

### 2.2 Source Files

| System | Key Files | Total LOC |
|--------|-----------|-----------|
| A | `run_infer.py` (540), `workspace.py` (122), `config.py` (22), `constants.py` (27), `build_utils.py` (924) | ~1,635 |
| B | `custom.py` (980), `run_validation.py` (1,809), `report.py` (274), `cli.py` (280) | ~3,343 |
| C | `openhands_mode.py` (537), `openhands_workspace.py` (109), `openhands_image_builder.py` (220), `openhands_output.py` (136), `openhands_config.py` (43) + modified `custom.py` | ~1,045 new + ~70 modified |

---

## 3. System A — OpenHands Benchmarks

### 3.1 Output Directory Structure

```
eval_outputs/{dataset}-{split}/{model}_sdk_{sha}_maxiter_{N}[_N_{note}]/
├── metadata.json                           # Full EvalMetadata (25+ fields)
├── output.jsonl                            # Final aggregated results (best per instance)
├── output_errors.jsonl                     # Error records only
├── output.critic_attempt_{N}.jsonl         # Per-attempt results (when n_critic_runs > 1)
├── ERROR_LOGS.txt                          # Human-readable error summary (rare)
├── logs/
│   ├── instance_{id}.log                   # Logging framework output per instance
│   └── instance_{id}.output.log            # stdout/stderr capture per instance
└── conversations/
    └── {instance_id}.tar.gz                # Container conversation archive
```

### 3.2 `metadata.json` Schema

```json
{
  "dataset": "swefficiency/swefficiency",
  "dataset_split": "test",
  "model": "anthropic/claude-sonnet-4-20250514",
  "agent_class": "CodeActAgent",
  "max_iterations": 500,
  "eval_output_dir": "eval_outputs/swefficiency-test/claude_sdk_abc123_maxiter_500",
  "start_time": "2026-04-20T10:30:00Z",
  "git_commit": "abc123def456",
  "num_workers": 4,
  "workspace_type": "docker",
  "llm": {
    "model": "anthropic/claude-sonnet-4-20250514",
    "api_key": "***",
    "temperature": 0.0,
    "max_output_tokens": 4096,
    "top_p": 1.0
  },
  "critic": {
    "critic_names": ["finish_with_patch"],
    "n_critic_runs": 3
  },
  "base_resource_factor": 1,
  "max_retries": 3,
  "sandbox_base_image": "ghcr.io/swefficiency/swefficiency-images:{instance_id}",
  "runtime_startup_timeout": 120,
  "conversation_timeout": 3600,
  "enable_browser": false
}
```

> **Type**: Serialized Pydantic `EvalMetadata` model from `models.py:20-151` (25+ fields).  
> **Produced by**: `Evaluation._save_metadata()` at run start.

### 3.3 `output.jsonl` Record Schema (Per Line)

```json
{
  "instance_id": "pandas-dev__pandas-38248",
  "attempt": 1,
  "test_result": {
    "git_patch": "diff --git a/pandas/core/... (full unified diff text)"
  },
  "instruction": "Your task is to optimize the performance of...",
  "metadata": { /* Full EvalMetadata object — same as metadata.json */ },
  "history": [
    {
      "id": 1,
      "source": "agent",
      "action": "CmdRunAction",
      "args": {"command": "ls -la", "timeout": 120},
      "timestamp": "2026-04-20T10:31:00Z"
    },
    {
      "id": 2,
      "source": "agent",
      "observation": "CmdOutputObservation",
      "content": "total 128\ndrwxr-xr-x  12 root root...",
      "extras": {"exit_code": 0}
    }
  ],
  "metrics": {
    "accumulated_cost": 0.0542,
    "accumulated_token_usage": {
      "prompt_tokens": 15234,
      "completion_tokens": 3456,
      "cache_read_tokens": 0
    },
    "costs": [{"model": "anthropic/claude-sonnet-4-20250514", "cost": 0.0542}]
  },
  "error": null,
  "instance": {
    "repo": "pandas-dev/pandas",
    "instance_id": "pandas-dev__pandas-38248",
    "base_commit": "abc123",
    "patch": "diff --git a/...",
    "workload": "import pandas as pd\n..."
  },
  "runtime_runs": null
}
```

> **Key types**:  
> - `metadata`: Full `EvalMetadata` Pydantic model (25+ fields)  
> - `history`: `list[Event]` — Pydantic discriminated union objects (CmdRunAction, CmdOutputObservation, MessageAction, etc.)  
> - `metrics`: `Metrics` Pydantic model from SDK  
> - `instance`: Raw dataset row (full `SWEfficiencyInstance` dict)  
> - `runtime_runs`: `list[RemoteRuntimeAllocation] | None`  
> **Produced by**: `get_default_on_result_writer()` in `evaluation_utils.py:39-67` with `fcntl.flock` thread safety.

### 3.4 `output.critic_attempt_{N}.jsonl`

Same schema as `output.jsonl`. Only produced when `n_critic_runs > 1`. Each file captures results from a single critic evaluation pass. The final `output.jsonl` is the aggregated best result across all attempts.

### 3.5 `conversations/{instance_id}.tar.gz`

**Content**: Compressed archive of `/workspace/conversations/` from inside the runtime container.  
**Production**: `_capture_conversation_archive()` in `evaluation.py:247-299` — runs `tar -czf - /workspace/conversations/ | base64` inside container, decodes base64 stream, writes to host.  
**Contains**: SDK conversation state files, event logs, agent interaction records.

### 3.6 Diff Format

```bash
git --no-pager diff --no-color {base_commit} HEAD
```

- **NO** `--binary` flag
- Uses `--no-color` to strip ANSI escape codes
- Uses `--no-pager` to prevent interactive pager
- Preceded by: `git add -A` → remove binary files (*.o, *.so, *.pyc, etc.) → `git commit --no-verify`

---

## 4. System B — Official SWE-fficiency

### 4.1 Inference Output Directory Structure

```
logs/run_inference/{run_id}/{spec_name}/{instance_id}/
├── patch.diff                              # Git diff from container
├── container.log                           # Aggregate log of all steps
├── {prework_script_name}.log               # Per-prework-script execution log
├── inference.log                           # Inference command stdout/stderr
├── patch.log                               # Patch extraction log
├── {artifact_name}                         # Additional spec-defined artifacts
└── (no JSONL trajectory — black-box paradigm)
```

**Run-level**:
```
logs/run_inference/{run_id}/{spec_name}/
└── summary.json                            # Array of per-instance status
```

### 4.2 `summary.json` Schema

```json
[
  {
    "instance_id": "psf__requests-7342",
    "status": "success",
    "patch": "logs/run_inference/my_run/cursor-cli/psf__requests-7342/patch.diff",
    "error": null
  }
]
```

> **Produced by**: `custom.py` at end of `process_instance()`.  
> **No trajectory data**: The agent runs as a single shell command inside the container — System B doesn't know what the agent did internally.

### 4.3 Diff Format

```bash
git add -N . && git diff --binary "$BASE_COMMIT" > /tmp/model.patch
# Fallback: git diff --binary HEAD > /tmp/model.patch (when no BASE_COMMIT)
```

- **YES** `--binary` flag — includes base85-encoded binary content
- Uses `git add -N .` to track new files without staging content
- Extracted via `container.get_archive()` (Docker API tar stream)

### 4.4 Evaluation Output Directory Structure

```
logs/run_evaluation/{run_id}/{model_name}/{instance_id}/
├── run_instance.log                        # Main evaluation log
├── report.json                             # Skip marker / status
├── patch.diff                              # Applied patch copy
├── image_build_dir -> (symlink)            # Link to Docker build artifacts
│
├── # COVERAGE STAGE (--run_coverage true)
├── treesitter_compare.py                   # AST comparison script
├── ast.sh / ast_output.txt                 # AST analysis
├── coverage_ast.py                         # Coverage + AST intersection
├── coverage.sh / coverage_output.txt       # Coverage collection
├── coverage_analysis.py                    # Coverage analysis script
├── test_status.tar                         # Test results archive
├── coverage_files.tar                      # Coverage data archive
├── covering_tests.txt                      # Discovered test file paths
│
├── # PERFORMANCE STAGE (--run_perf true)
├── workload.py                             # Benchmark script (from dataset)
├── workload_raw.py                         # Unmodified workload (before isolation)
├── perf.sh                                 # Performance test shell script
├── perf_output_preedit.txt                 # Pre-edit benchmark output
├── perf_output_postedit.txt                # Post-edit benchmark output
├── perf_summary.txt                        # 5-line summary (see below)
├── flag_bad_workload.txt                   # Workload validity flag
│
├── # PROFILING STAGE (--run_perf_profiling true)
├── perf_profiling.sh                       # Profiling shell script
├── perf_profiling_output_preedit.txt       # Pre-edit profiling output
├── perf_profiling_output_postedit.txt      # Post-edit profiling output
├── workload_preedit_cprofile.prof          # cProfile binary data (pre-edit)
├── workload_postedit_cprofile.prof         # cProfile binary data (post-edit)
│
├── # CORRECTNESS STAGE (--run_correctness true)
├── covering_tests.txt                      # Test files to run
├── single_thread_tests.txt                 # Single-threaded test list
├── introspection_patch_check.py            # Stack introspection guard
├── introspection_guard.sh                  # Guard execution script
├── correctness.sh                          # Correctness test runner
├── correctness_output.txt                  # Test execution output
├── test_status.tar                         # Test results archive
├── raw_correctness_output/                 # Per-test raw output
│   └── {idx}.txt
└── covering_test_status.json               # Per-test pass/fail status
```

### 4.5 `perf_summary.txt` Format

```
Before Mean: 0.0100
Before SD: 0.0003
After Mean: 0.0054
After SD: 0.0001
Improvement: 186.42%
```

> **Formula**: `Improvement = (Before Mean / After Mean) × 100`  
> **Produced by**: `run_validation.py` lines 717-727.

### 4.6 Report Output

```
eval_reports/
├── eval_report_{pred_run_name}.csv         # Per-instance metrics
└── eval_report_{pred_run_name}.json        # Aggregate metrics
```

**CSV Columns** (9 total):

| Column | Type | Description |
|--------|------|-------------|
| `instance_id` | str | Instance identifier |
| `raw_pred_speedup_ratio` | float | Unadjusted model speedup (before correctness check) |
| `pred_speedup_ratio` | float | Adjusted — forced to 1.0 if correctness fails |
| `gold_speedup_ratio` | float | Expert patch speedup (T_pre / T_post_gold) |
| `human_speedup_ratio` | float | `pred_speedup_ratio / gold_speedup_ratio` |
| `correctness` | float | Binary: 1.0 = all pass, 0.0 = at least one failure |
| `correctness_pct` | float | Fraction of PASS_TO_PASS tests passed (0.0–1.0) |
| `pre_edit_runtime` | float | Pre-edit workload runtime (seconds) |
| `patch_length` | int | Lines in expert (gold) patch from dataset |

**JSON Fields** (7 total):

```json
{
  "total_instances": 3,
  "overall_score": 0.835,
  "proportion_incorrect": 1.0,
  "proportion_correct_but_no_speedup": 0.0,
  "proportion_correct_with_speedup_but_human_no_speedup": 0.0,
  "proportion_human_speedup_or_better": 0.6667,
  "report": "eval_report_nova-2-lite.csv"
}
```

> **Scoring**: `overall_score` = harmonic mean of `human_speedup_ratio` values, floored at 0.001.  
> **Produced by**: `report.py:generate_report()`.

### 4.7 Predictions Input Format (for eval)

```json
{"instance_id": "psf__requests-7342", "model_patch": "diff --git a/...", "model_name_or_path": "nova-2-lite"}
```

> **Required keys**: `instance_id`, `model_patch` (diff text), `model_name_or_path` (model identifier).  
> **Read by**: `run_validation.py:get_model_predictions()` using `KEY_INSTANCE_ID`, `KEY_PREDICTION`, `KEY_MODEL` from `constants.py:1474-1476`.

---

## 5. System C — Our Modified Code

### 5.1 Output Directory Structure

```
logs/run_inference/{run_id}/openhands/
├── metadata.json                           # Run configuration (flat dict, 12 fields)
├── output.jsonl                            # Full trajectory per instance
├── output_errors.jsonl                     # Error records only
├── predictions.jsonl                       # AUTO-GENERATED eval-ready predictions
├── summary.json                            # Per-instance status array
├── conversations/
│   └── {instance_id}.tar.gz               # Container conversation archive
└── {instance_id}/
    ├── patch.diff                          # Git diff --binary
    ├── instance.log                        # DEBUG-level per-instance log
    └── openhands_prompt.txt                # Rendered instruction template
```

### 5.2 `metadata.json` Schema

```json
{
  "run_id": "nova2lite_single",
  "model_name": "nova-2-lite",
  "llm_config": "bedrock.json",
  "max_iterations": 100,
  "max_fake_responses": 5,
  "num_workers": 1,
  "cpus_per_worker": 4,
  "mem_limit": "12g",
  "build_target": "source-minimal",
  "num_instances": 1,
  "instance_ids": ["psf__requests-7342"],
  "timestamp": "2026-04-23T14:30:00Z",
  "llm_model": "bedrock/converse/global.anthropic.claude-opus-4-6-v1"
}
```

> **Type**: Flat Python dict (12 fields).  
> **Produced by**: `openhands_mode.py` at `run_openhands_inference()` start.  
> **Critical difference from System A**: System A uses full `EvalMetadata` Pydantic model with 25+ fields.

### 5.3 `output.jsonl` Record Schema (Per Line)

```json
{
  "instance_id": "psf__requests-7342",
  "attempt": 1,
  "test_result": {
    "git_patch": "diff --git a/src/requests/models.py b/src/requests/models.py\n..."
  },
  "instruction": "## Performance Optimization Task\n\nYou are working on...",
  "error": null,
  "history": [
    {
      "id": 1,
      "source": "agent",
      "action": "CmdRunAction",
      "args": {"command": "find /testbed -name '*.py' | head -20"},
      "timestamp": "2026-04-23T14:31:00Z"
    },
    {
      "id": 2,
      "source": "agent",
      "observation": "CmdOutputObservation",
      "content": "/testbed/setup.py\n/testbed/src/requests/__init__.py\n...",
      "extras": {"exit_code": 0}
    }
  ],
  "metrics": {
    "accumulated_cost": 0.0,
    "accumulated_token_usage": {
      "prompt_tokens": 12500,
      "completion_tokens": 2800
    }
  },
  "metadata": {
    "model_name": "nova-2-lite",
    "cost": 0.0,
    "timestamp": "2026-04-23T14:40:00Z"
  }
}
```

> **Key types**:  
> - `metadata`: Flat dict with **3 fields only** (model_name, cost, timestamp)  
> - `history`: `list[dict]` — manually serialized via `model_dump()` with `str()` fallback  
> - `metrics`: `dict` — raw dict from SDK's `get_combined_metrics()`  
> - **Missing**: `instance` field (raw dataset row), `runtime_runs` field  
> **Produced by**: `write_eval_output()` in `openhands_output.py:53-90` with `fcntl.flock` thread safety.

### 5.4 `predictions.jsonl` Schema (Auto-Generated)

```json
{"instance_id": "psf__requests-7342", "model_patch": "diff --git a/...", "model_name_or_path": "nova-2-lite"}
```

> **DIRECTLY COMPATIBLE** with System B's eval harness. No conversion needed.  
> **Produced by**: `convert_to_predictions_jsonl()` in `openhands_output.py:123-136`, called automatically after inference.

### 5.5 `summary.json` Schema

```json
[
  {
    "instance_id": "psf__requests-7342",
    "status": "success",
    "patch": "logs/run_inference/nova2lite_single/openhands/psf__requests-7342/patch.diff",
    "cost": 0.0,
    "elapsed_seconds": 540.8,
    "error": null
  }
]
```

> **Extra fields vs System B**: `cost`, `elapsed_seconds` (not present in System B's summary.json).

### 5.6 Diff Format

```bash
git --no-pager diff --binary {base_commit} HEAD
```

- **YES** `--binary` flag (matches System B)
- Preceded by: `git add -A` → remove binary files → `git commit --no-verify --allow-empty -m 'agent patch'`
- Extracted via `workspace.execute_command()` (HTTP API to agent-server inside container)

### 5.7 `conversations/{instance_id}.tar.gz`

**Content**: Same as System A — compressed archive of `/workspace/conversations/` from inside the runtime container.  
**Production**: Mirrors System A's `_capture_conversation_archive()` — runs `tar -czf - /workspace/conversations/ | base64` inside container via `workspace.execute_command()`, decodes and writes locally.

---

## 6. Side-by-Side Schema Comparison

### 6.1 `output.jsonl` — Field-by-Field

| Field | System A | System C | Match? |
|-------|----------|----------|--------|
| `instance_id` | `str` | `str` | ✅ Identical |
| `attempt` | `int` (≥1) | `int` | ✅ Identical |
| `test_result` | `{"git_patch": str}` | `{"git_patch": str}` | ✅ Identical |
| `instruction` | `str \| None` | `str` | ✅ Compatible |
| `error` | `str \| None` | `str \| None` | ✅ Identical |
| `history` | `list[Event]` (Pydantic discriminated union) | `list[dict]` (manual serialization) | ⚠️ **Structurally similar, not deserializable as Event** |
| `metrics` | `Metrics` (Pydantic model) | `dict` (raw dict) | ⚠️ **Same data, different type** |
| `metadata` | `EvalMetadata` (25+ field Pydantic model) | `{"model_name", "cost", "timestamp"}` (3 fields) | ❌ **CRITICAL MISMATCH** |
| `instance` | `dict` (full dataset row) | **MISSING** | ❌ **Missing field** |
| `runtime_runs` | `list[RemoteRuntimeAllocation] \| None` | **MISSING** | ❌ **Missing field** |

### 6.2 `metadata.json` — Field Comparison

| Field | System A | System C | Present in Both? |
|-------|----------|----------|-----------------|
| `dataset` | ✅ `"swefficiency/swefficiency"` | ❌ | No |
| `dataset_split` | ✅ `"test"` | ❌ | No |
| `model` | ✅ Full model string | ❌ (has `llm_model`) | Partial |
| `agent_class` | ✅ `"CodeActAgent"` | ❌ | No |
| `max_iterations` | ✅ | ✅ | Yes |
| `eval_output_dir` | ✅ Full path | ❌ | No |
| `num_workers` | ✅ | ✅ | Yes |
| `workspace_type` | ✅ `"docker"` | ❌ | No |
| `llm` | ✅ Full LLM config object | ❌ (has `llm_config` filename) | Partial |
| `critic` | ✅ Critic config | ❌ | No |
| `max_retries` | ✅ | ❌ | No |
| `run_id` | ❌ | ✅ | No |
| `model_name` | ❌ | ✅ | No |
| `mem_limit` | ❌ | ✅ | No |
| `build_target` | ❌ | ✅ | No |
| `instance_ids` | ❌ | ✅ | No |
| `timestamp` | ✅ `start_time` | ✅ `timestamp` | Partial |

> **Only 2 fields have exact overlap**: `max_iterations`, `num_workers`. All others are either missing or have different names/schemas.

### 6.3 `predictions.jsonl` — Field Comparison

| Field | System B (Eval Input) | System C (Auto-Generated) | Match? |
|-------|----------------------|---------------------------|--------|
| `instance_id` | ✅ Required | ✅ Present | ✅ **EXACT** |
| `model_patch` | ✅ Required (diff text) | ✅ Present (diff text) | ✅ **EXACT** |
| `model_name_or_path` | ✅ Required | ✅ Present | ✅ **EXACT** |

> **Perfect compatibility** — System C's `predictions.jsonl` can be fed directly to `swefficiency eval --prediction_path`.

---

## 7. Compatibility Matrix

### 7.1 Cross-System Compatibility

| Operation | Status | Detail |
|-----------|--------|--------|
| C's `predictions.jsonl` → B's eval harness | ✅ **WORKS** | Same 3 required keys |
| C's `output.jsonl` → A's `oh_conversion.py` | ❌ **CRASHES** | `KeyError: 'eval_output_dir'` at line 86 |
| C's `output.jsonl` → A's `EvalOutput.model_validate()` | ❌ **FAILS** | Missing `instance`, `runtime_runs`; wrong `metadata` type |
| A's `output.jsonl` → B's eval harness | ⚠️ **NEEDS CONVERSION** | Requires `oh_conversion.py` to extract predictions |
| C's `patch.diff` → B's `git apply` | ⚠️ **RISK** | `--binary` hunks may behave differently |
| A's `patch.diff` → B's `git apply` | ✅ **WORKS** | `--no-color` is standard format |
| C's `summary.json` → B's `summary.json` consumers | ✅ **COMPATIBLE** | Extra fields (`cost`, `elapsed_seconds`) are ignored |

### 7.2 `oh_conversion.py` Crash Analysis

The official `oh_conversion.py` in `predictions/converted/` reads System A's `output.jsonl` and extracts predictions:

```python
# oh_conversion.py lines 66-87 (simplified)
for item in raw_predictions:
    if not item["metadata"]:        # Line 68: truthy check
        continue
    eval_entry = {
        "instance_id": item["instance_id"],
        "model_patch": item["test_result"].get("git_patch", ""),
        "model_name_or_path": item["metadata"]["eval_output_dir"].split("/")[-1],  # LINE 86
    }
```

**On System C's output**:
1. `item["metadata"]` = `{"model_name": "nova-2-lite", "cost": 0.0, "timestamp": "..."}` → truthy ✅ (doesn't skip)
2. `item["metadata"]["eval_output_dir"]` → **`KeyError`** ❌ (field doesn't exist)

**Fix**: System C already auto-generates `predictions.jsonl`, making `oh_conversion.py` unnecessary.

---

## 8. Detailed Field-Level Comparison

### 8.1 `history` Field

| Aspect | System A | System C |
|--------|----------|----------|
| **Type** | `list[Event]` — Pydantic discriminated union | `list[dict]` — manual serialization |
| **Serialization** | `Event.model_dump(mode="json")` | `model_dump()` → `dict(vars(v))` → `str(v)` fallback chain |
| **Round-trippable** | ✅ `Event.model_validate(data)` works | ❌ `str()` fallback destroys Pydantic types |
| **Event types** | CmdRunAction, CmdOutputObservation, MessageAction, FileEditAction, etc. | Same types but serialized as flat dicts |
| **Nested objects** | Preserved via Pydantic serialization | May be stringified via `str()` fallback |

**Impact**: Downstream tools that deserialize history back into `Event` objects (e.g., trajectory analysis, replay) will fail on System C output.

### 8.2 `metrics` Field

| Aspect | System A | System C |
|--------|----------|----------|
| **Type** | `Metrics` Pydantic model | `dict` (raw from `get_combined_metrics()`) |
| **Fields** | `accumulated_cost`, `accumulated_token_usage`, `costs` | Same fields (dict mirrors Pydantic structure) |
| **Validation** | `Metrics.model_validate(data)` works | ⚠️ Will work if all required fields present |

**Impact**: Generally compatible since the data is the same — only fails if strict Pydantic validation is applied.

### 8.3 `metadata` Field — The Critical Mismatch

**System A** (25+ fields):
```json
{
  "dataset": "swefficiency/swefficiency",
  "dataset_split": "test",
  "model": "anthropic/claude-sonnet-4-20250514",
  "agent_class": "CodeActAgent",
  "max_iterations": 500,
  "eval_output_dir": "eval_outputs/...",
  "llm": {"model": "...", "api_key": "***", "temperature": 0.0},
  "critic": {"critic_names": ["finish_with_patch"], "n_critic_runs": 3},
  "workspace_type": "docker",
  "max_retries": 3,
  "base_resource_factor": 1,
  "sandbox_base_image": "ghcr.io/...",
  "runtime_startup_timeout": 120,
  "conversation_timeout": 3600,
  "enable_browser": false,
  "start_time": "2026-04-20T10:30:00Z",
  "git_commit": "abc123"
}
```

**System C** (3 fields):
```json
{
  "model_name": "nova-2-lite",
  "cost": 0.0,
  "timestamp": "2026-04-23T14:40:00Z"
}
```

**Missing from C**: `dataset`, `dataset_split`, `model` (full string), `agent_class`, `eval_output_dir`, `llm` (full config), `critic`, `workspace_type`, `max_retries`, `base_resource_factor`, `sandbox_base_image`, `runtime_startup_timeout`, `conversation_timeout`, `enable_browser`, `start_time`, `git_commit`, and ~8 more fields.

---

## 9. Silent Incompatibilities

### 9.1 Diff Format: `--binary` vs `--no-color`

| System | Command | Binary content | Color codes |
|--------|---------|----------------|-------------|
| A | `git --no-pager diff --no-color {base_commit} HEAD` | ❌ Not included | ❌ Stripped |
| B | `git diff --binary "$BASE_COMMIT"` | ✅ Base85-encoded | ✅ May include |
| C | `git --no-pager diff --binary {base_commit} HEAD` | ✅ Base85-encoded | ❌ Stripped (via --no-pager) |

**Risk**: If the eval harness applies patches using `git apply` (without `--binary`), base85-encoded binary hunks from Systems B and C may be rejected or cause unexpected behavior for binary file changes.

### 9.2 Empty Commit Handling

| System | Commit command | Empty patch behavior |
|--------|---------------|---------------------|
| A | `git commit --no-verify -m 'agent patch'` | ❌ Fails if no changes → no commit → empty diff |
| C | `git commit --no-verify --allow-empty -m 'agent patch'` | ✅ Creates empty commit → empty diff silently passes |

**Risk**: System C produces valid-looking but empty patches when the agent makes no changes, while System A would error and produce no output. Empty patches silently score as "no speedup" (SR = 1.0/gold_speedup) in the eval pipeline.

### 9.3 History Serialization Lossy Chain

System C's fallback serialization in `openhands_mode.py:386-398`:

```python
for event in conversation.state.events:
    try:
        history.append(event.model_dump())           # Attempt 1: Pydantic
    except:
        try:
            history.append(dict(vars(event)))         # Attempt 2: vars()
        except:
            history.append({"raw": str(event)})       # Attempt 3: str() — LOSSY
```

**Risk**: The `str()` fallback destroys nested Pydantic types, making events non-round-trippable. Any downstream tool attempting `Event.model_validate()` on stringified records will fail.

---

## 10. File Production Differences

### 10.1 Files System A Produces but System C Does NOT

| File | Purpose | Impact |
|------|---------|--------|
| `output.critic_attempt_{N}.jsonl` | Per-critic-attempt results | N/A — System C is single-shot (no critic loop) |
| `logs/instance_{id}.log` | Structured log directory | System C uses `{id}/instance.log` instead (same data, different path) |
| `logs/instance_{id}.output.log` | stdout/stderr capture | Not produced — captured in `instance.log` |
| Full `EvalMetadata` in `metadata.json` | Complete run configuration | System C has simplified 12-field metadata |
| `ERROR_LOGS.txt` | Human-readable error summary | Not produced (rare in System A too) |

### 10.2 Files System C Produces but System A Does NOT

| File | Purpose | Impact |
|------|---------|--------|
| `predictions.jsonl` | Eval-harness-ready predictions | **KEY ADVANTAGE** — no conversion needed |
| `{id}/patch.diff` | Explicit patch file per instance | System A stores patch only in `test_result.git_patch` |
| `{id}/openhands_prompt.txt` | Rendered instruction for debugging | Useful for prompt engineering iteration |
| `summary.json` with `cost`/`elapsed_seconds` | Per-instance performance tracking | Extra observability |

### 10.3 Files System B Produces that Neither A nor C Has

| File | Purpose |
|------|---------|
| `perf_summary.txt` | 5-line performance benchmark summary |
| `perf_output_preedit.txt` / `perf_output_postedit.txt` | Raw benchmark output |
| `workload.py` / `workload_raw.py` | Benchmark scripts |
| `covering_tests.txt` | Discovered test file paths |
| `correctness_output.txt` | Test execution results |
| `*.cprofile.prof` | cProfile binary profiling data |
| `eval_report_*.csv` / `eval_report_*.json` | Final evaluation report |

> **Note**: These are EVALUATION outputs, not inference outputs. Systems A and C are inference-only — they produce patches that are then fed to System B's eval harness.

---

## 11. Evaluation Bridge Analysis

### 11.1 How Each System's Output Reaches the Eval Harness

```
System A (OpenHands Benchmarks)
    output.jsonl
        │
        ▼ oh_conversion.py (extracts git_patch → predictions.jsonl)
        │
        ▼
    predictions.jsonl ──────────────────────────────────┐
                                                         │
System B (Official SWE-fficiency)                        ▼
    patch.diff ─── (manual assembly into JSONL) ──► swefficiency eval
                                                    --prediction_path
System C (Our Modified Code)                             ▲
    predictions.jsonl ──────────────────────────────────┘
    (auto-generated, no conversion needed)
```

### 11.2 Conversion Requirements

| From → To | Tool Required | Effort |
|-----------|---------------|--------|
| System A → Eval | `oh_conversion.py` | Automated (but crashes on System C output) |
| System B → Eval | Manual JSONL assembly or `--prediction_path` CLI flag | Script needed |
| System C → Eval | **None** — `predictions.jsonl` auto-generated | Zero effort ✅ |

### 11.3 Why System C is the Easiest Path to Eval

System C auto-generates `predictions.jsonl` with exactly the 3 fields the eval harness expects (`instance_id`, `model_patch`, `model_name_or_path`). The command to evaluate is simply:

```bash
# Gold baseline (expert patches)
swefficiency eval --run_id my_eval --dataset artifacts/final/requests-dataset.jsonl \
    --num_workers 1

# Agent predictions
swefficiency eval --run_id my_eval --dataset artifacts/final/requests-dataset.jsonl \
    --prediction_path logs/run_inference/my_run/openhands/predictions.jsonl \
    --num_workers 1

# Report
swefficiency report --gold_run logs/run_evaluation/my_eval/gold \
    --pred_run logs/run_evaluation/my_eval/nova-2-lite \
    --dataset artifacts/final/requests-dataset.jsonl
```

---

## 12. Key Takeaways

### 12.1 For Researchers Using This Pipeline

1. **System C is the most practical** — it produces BOTH trajectory data (for analysis) AND eval-ready predictions (for benchmarking) in a single run. No conversion scripts needed.

2. **System C's `output.jsonl` is NOT interchangeable with System A's** — different metadata schema, missing fields, lossy history serialization. Don't assume tools written for System A will work on System C output.

3. **The `predictions.jsonl` format is the universal bridge** — all three systems ultimately produce or convert to this format for evaluation. It's the only truly compatible interchange format.

4. **Diff format matters** — System C uses `--binary` (matching System B), while System A uses `--no-color` (no binary). For pure Python changes this doesn't matter, but for repos with binary artifacts (compiled extensions, images), the diff format can affect patch application.

5. **Empty patches are silent in System C** — the `--allow-empty` flag means the agent can produce a "successful" run with no actual changes. Always check `patch.diff` size.

### 12.2 For Developers Extending This Code

1. **Don't try to make System C output match System A exactly** — the `EvalMetadata` Pydantic model has 25+ fields that are tightly coupled to the OpenHands evaluation framework. Replicating it would mean importing the entire `Evaluation` base class.

2. **System C's conversation archive is compatible with System A** — both capture the same `/workspace/conversations/` directory via the same tar+base64 mechanism.

3. **The critic system is an optional extension** — System C does single-shot inference. Adding critic support would require porting the critic loop from `evaluation.py:480-530` and adding `output.critic_attempt_N.jsonl` writers.

4. **System B's eval harness is format-agnostic** — it only reads `predictions.jsonl` and the dataset. It doesn't care about trajectory format, conversation archives, or metadata. This is the correct abstraction boundary.

### 12.3 Format Decision Matrix

| If you need... | Use... |
|----------------|--------|
| Full agent trajectory for analysis | System C's `output.jsonl` or System A's `output.jsonl` |
| Eval-ready predictions (fastest path) | System C's auto-generated `predictions.jsonl` |
| Performance benchmarking results | System B's `perf_summary.txt` (via eval harness) |
| Conversation replay/debugging | `conversations/*.tar.gz` (Systems A and C) |
| Official leaderboard submission | System B's `eval_report_*.json` (via `swefficiency report`) |
| Cross-model comparison | System B's `eval_report_*.csv` (standard tabular format) |

---

## 13. Recommendations

### 13.1 Short-Term (No Code Changes)

1. **Always use System C's `predictions.jsonl`** for evaluation — skip `oh_conversion.py` entirely.
2. **Check `patch.diff` size** after inference — if 0 bytes, the agent made no changes.
3. **Use `summary.json`** for quick run status checks — it has `elapsed_seconds` and `cost` that `output.jsonl` doesn't surface as top-level fields.

### 13.2 Medium-Term (Optional Improvements)

1. **Enrich System C's `metadata` field** — add `eval_output_dir`, `dataset`, `llm` config to match System A's schema, enabling `oh_conversion.py` compatibility.
2. **Fix history serialization** — use SDK's native `Event.model_dump(mode="json")` instead of the lossy fallback chain.
3. **Remove `--allow-empty`** from git commit — force the agent to make actual changes or report failure explicitly.

### 13.3 Long-Term (If Cross-System Interop Needed)

1. **Define a common trajectory schema** — a minimal subset that all three systems can produce: `{instance_id, attempt, git_patch, instruction, error, cost, elapsed_seconds}`.
2. **Add critic support to System C** — port the critic loop and produce `output.critic_attempt_N.jsonl` files.
3. **Standardize diff format** — decide on `--binary` vs `--no-color` project-wide and document the choice.

---

*Generated from source code analysis of all 3 codebases + live run validation on psf__requests-7342 + Metis/Oracle verification.*
