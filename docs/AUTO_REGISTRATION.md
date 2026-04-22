# Auto-Registration: Adding Arbitrary Repos to SWE-fficiency

This guide covers how to add support for **new repos not in the original 9** (numpy, pandas, scipy, scikit-learn, matplotlib, xarray, sympy, dask, astropy) to the SWE-fficiency benchmark harness.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  OFFLINE: detect_repo_specs.py                              │
│  clone repo → detect python/install/test/deps/version/      │
│  license → write enriched JSONL                             │
└──────────────────────────┬──────────────────────────────────┘
                           │ enriched JSONL
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  RUNTIME: harness/dynamic_specs.py                          │
│  get_or_create_specs(instance, repo, version) →             │
│    1. Check hardcoded MAP_REPO_VERSION_TO_SPECS             │
│    2. Synthesize from instance's auto-detected fields       │
│    3. Raise NotImplementedError                             │
└──────────────────────────┬──────────────────────────────────┘
                           │ specs dict
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  test_spec.py / docker_build.py / log_parsers.py            │
│  (all crash points patched with dynamic fallback)           │
└─────────────────────────────────────────────────────────────┘
```

---

## Step 1: Prepare Your Dataset

Your JSONL must have the standard SWE-bench fields:

| Field | Type | Required |
|---|---|---|
| `repo` | str | yes |
| `instance_id` | str | yes |
| `base_commit` | str | yes |
| `patch` | str | yes |
| `test_patch` | str | yes |
| `problem_statement` | str | yes |
| `version` | str | yes (can be auto-detected) |
| `PASS_TO_PASS` | str (JSON list) | yes |
| `FAIL_TO_PASS` | str (JSON list) | yes |
| `environment_setup_commit` | str | yes |
| `workload` | str | for SWE-fficiency eval |

---

## Step 2: Run Auto-Detection

```bash
python scripts/detect_repo_specs.py \
    --input your_dataset.jsonl \
    --output enriched_dataset.jsonl \
    --workers 4 \
    --license-filter MIT Apache-2.0 BSD-3-Clause BSD-2-Clause ISC MIT-0
```

### What it detects (per repo):

| Field | Detection Priority |
|---|---|
| `python_version` | .python-version → pyproject.toml → setup.py → setup.cfg → tox.ini → "3.10" |
| `install_cmd` | pyproject.toml build-system → setup.py → fallback "pip install -e ." |
| `test_cmd_override` | pyproject.toml pytest → setup.cfg → tox.ini → tests/ dir → "pytest {test_files}" |
| `packages_source` | environment.yml → requirements.txt → requirements/ dir → pyproject.toml deps → "" |
| `pip_packages` | extracted from pyproject.toml [project.dependencies] when no requirements.txt |
| `pre_install_cmds` | C extensions → meson.build → Fortran → BLAS/LAPACK → build-essential |
| `version` | pyproject.toml → setup.py → setup.cfg → \_\_init\_\_.py → VERSION file |
| `license` | LICENSE file → pyproject.toml license/classifiers (used for filtering) |

### CLI Parameters

| Parameter | Default | Description |
|---|---|---|
| `--input` | (required) | Input JSONL or HuggingFace dataset name |
| `--output` | (required) | Output enriched JSONL file path |
| `--clone-dir` | `/tmp/repo_clones` | Temp directory for cloning repos |
| `--workers` | 1 | Parallel workers (increase for 100+ repos) |
| `--dry-run` | false | Print detections without writing output |
| `--validate` | false | Check existing JSONL has all required fields |
| `--cache-file` | `.specs_cache.json` | Cache for incremental runs |
| `--license-filter` | (none) | Allowlist: only include repos with these licenses |
| `--split` | `test` | HF dataset split (when input is HF name) |
| `--verbose` / `-v` | false | Verbose logging |

### Modes

**Detection mode** (default):
```bash
python scripts/detect_repo_specs.py --input data.jsonl --output enriched.jsonl
```

**Dry-run mode** (print detections, don't write):
```bash
python scripts/detect_repo_specs.py --input data.jsonl --output /dev/null --dry-run
```

**Validate mode** (check existing enriched JSONL):
```bash
python scripts/detect_repo_specs.py --input enriched.jsonl --output /dev/null --validate
```

**With license filter** (only MIT/Apache/BSD):
```bash
python scripts/detect_repo_specs.py --input data.jsonl --output enriched.jsonl \
    --license-filter MIT Apache-2.0 BSD-3-Clause
```

### Output

The output JSONL preserves all original fields and adds:
```json
{
  "python_version": "3.11",
  "install_cmd": "pip install -e .",
  "test_cmd_override": "pytest tests/ -x",
  "packages_source": "requirements.txt",
  "pip_packages": [],
  "pre_install_cmds": ["apt-get install -y build-essential"],
  "reqs_paths": ["requirements.txt"],
  "env_yml_paths": [],
  "log_parser_type": "pytest"
}
```

---

## Step 3: Build Docker Images

Use the standard SWE-fficiency Docker build pipeline with the enriched dataset:

```bash
python swefficiency/harness/docker_build.py \
    --dataset_path enriched_dataset.jsonl \
    --num_workers 4
```

The harness automatically:
1. Reads `python_version`, `install_cmd`, etc. from instance fields
2. Generates conda environment with detected Python version
3. Installs using detected install command
4. Registers `reqs_paths` / `env_yml_paths` dynamically
5. Falls back to `parse_log_pytest` for test output parsing

---

## Step 4: Run Evaluation

Use the enriched dataset for evaluation:

```bash
swefficiency eval \
    --run_id my_eval \
    --dataset enriched_dataset.jsonl \
    --num_workers 4
```

Or with the inference harness:

```bash
python scripts/inference/custom.py \
    --run-id my_inference \
    --spec specs/openhands_agent.yaml \
    --mode openhands \
    --llm-config llm_configs/bedrock.json \
    --dataset enriched_dataset.jsonl
```

---

## How Dynamic Specs Work

### Three-Tier Fallback

`get_or_create_specs(instance, repo, version)`:

1. **Tier 1 — Hardcoded**: If `repo` + `version` is in `MAP_REPO_VERSION_TO_SPECS` → return that entry unchanged (backward compat for all 20+ existing repos)
2. **Tier 2 — Synthesize**: If instance has `python_version` or `install_cmd` → build specs dict from instance fields
3. **Tier 3 — Error**: Neither found → raise `NotImplementedError` with message to run `detect_repo_specs.py`

### Backward Compatibility

All existing repos (numpy, pandas, scipy, etc.) continue to use their hardcoded specs. The dynamic system is purely additive — it activates only when a repo is NOT in the hardcoded map.

### Thread Safety

The dynamic specs cache uses `threading.Lock` for safe concurrent access from `ThreadPoolExecutor` workers.

### Log Parser Fallback

`MAP_REPO_TO_PARSER` uses a custom `_ParserMapWithFallback(dict)` class where `__missing__` returns `parse_log_pytest`. Any unknown repo key returns the pytest parser instead of raising `KeyError`.

---

## Instance Fields Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `python_version` | str | "3.10" | Conda Python version (e.g. "3.9", "3.11") |
| `install_cmd` | str | "pip install -e ." | Install command |
| `test_cmd_override` | str | "pytest {test_files}" | Test runner command |
| `packages_source` | str | "" | "requirements.txt" or "environment.yml" or "" |
| `pip_packages` | list[str] | [] | Extra pip packages to install |
| `pre_install_cmds` | list[str] | [] | System-level apt-get commands |
| `reqs_paths` | list[str] | [] | Paths to requirements.txt files in repo |
| `env_yml_paths` | list[str] | [] | Paths to environment.yml files in repo |
| `log_parser_type` | str | "pytest" | Override test log parser type |

---

## Troubleshooting

### "NotImplementedError: Repo X version Y not in MAP_REPO_VERSION_TO_SPECS"

Your dataset instances don't have the auto-detected fields. Run:
```bash
python scripts/detect_repo_specs.py --input your_data.jsonl --output enriched.jsonl
```

### Detection produces wrong Python version

Override manually in the JSONL:
```json
{"python_version": "3.9", "install_cmd": "pip install -e .[dev]", ...}
```

### Repo has exotic build system (CMake, Meson, Fortran)

The detector adds pre_install_cmds for known patterns. For unsupported build systems, manually add:
```json
{"pre_install_cmds": ["apt-get install -y cmake libfoo-dev"]}
```

### Cache stale after repo changes

Delete the cache: `rm .specs_cache.json` and re-run detection.

### License filter too aggressive

Check available licenses with `--dry-run` first, then adjust `--license-filter`.

---

## Test Coverage

60 tests covering the auto-registration pipeline:

```
tests/test_dynamic_specs.py          — 18 tests (unit: spec resolution, caching, thread safety)
tests/test_detect_repo_specs.py      — 28 tests (unit: all 7 detection functions)
tests/test_integration_dynamic_repo.py — 14 tests (e2e: backward compat, edge cases)
```

Run: `python -m pytest tests/ -v`
