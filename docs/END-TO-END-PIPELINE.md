# SWE-fficiency: End-to-End Pipeline — Scraper → Build → Trajectory → Evaluation

> Complete command sequence to go from **zero** to **evaluated agent trajectories with speedup scores**.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [Prerequisites & Environment Variables](#2-prerequisites--environment-variables)
3. [Stage 1: Scrape Pull Requests from GitHub](#3-stage-1-scrape-pull-requests-from-github)
4. [Stage 2: Filter Performance-Related PRs](#4-stage-2-filter-performance-related-prs)
5. [Stage 3: Add Version Information](#5-stage-3-add-version-information)
6. [Stage 4: Auto-Detect Repo Specifications (New Repos)](#6-stage-4-auto-detect-repo-specifications-new-repos)
7. [Stage 5: Generate Workload Benchmarks (LLM)](#7-stage-5-generate-workload-benchmarks-llm)
8. [Stage 6: Assemble Final Dataset](#8-stage-6-assemble-final-dataset)
9. [Stage 7: Build Docker Images](#9-stage-7-build-docker-images)
10. [Stage 8: Run Agent Inference (Trajectories)](#10-stage-8-run-agent-inference-trajectories)
11. [Stage 9: Evaluate Predictions](#11-stage-9-evaluate-predictions)
12. [Stage 10: Generate Report](#12-stage-10-generate-report)
13. [Gaps & Manual Steps](#13-gaps--manual-steps)
14. [Quick Reference Card](#14-quick-reference-card)

---

## 1. Pipeline Overview

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Stage 1: Scrape  │────▶│ Stage 2: Filter  │────▶│ Stage 3: Version │
│   GitHub PRs     │     │   Perf PRs       │     │   Detection      │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         │                                                  │
         ▼                                                  ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Stage 4: Auto-   │────▶│ Stage 5: LLM     │────▶│ Stage 6: Assemble│
│  Detect Specs    │     │  Workload Gen    │     │  Final Dataset   │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Stage 7: Build   │────▶│ Stage 8: Agent   │────▶│ Stage 9: Eval    │
│  Docker Images   │     │  Inference       │     │  + Report        │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

**Stages 1–6** = Dataset creation (one-time per dataset).  
**Stages 7–9** = Evaluation loop (repeat per agent/model).  
**Stage 4** = Only needed for repos NOT in the hardcoded 9.

---

## 2. Prerequisites & Environment Variables

### Software

| Tool | Version | Purpose |
|------|---------|---------|
| Python | ≥3.12 | Runtime (SDK requires 3.12+) |
| uv | any | Package manager |
| Docker | ≥24.0 | Container runtime |
| Git | ≥2.30 | Version control |
| conda/miniforge | any | Required for versioning stage |

### Environment Variables

Create a `.env` file in the repo root. **Which tokens you need depends on your workflow** — see the two options below.

#### Option A: Local Build (new repos — no GHCR needed)

If you're building Docker images locally for new repos (not pulling prebuilt images), you only need:

```bash
# REQUIRED for Stages 1-3 (scraping, build_dataset, versioning)
GITHUB_TOKENS=ghp_token1,ghp_token2,ghp_token3   # Comma-separated GitHub PATs (3-5 recommended)
GITHUB_TOKEN=ghp_single_token                      # Single GitHub PAT (for versioning)

# REQUIRED for Stage 5 (workload generation) — Opus 4.6 via AWS Bedrock
AWS_BEARER_TOKEN_BEDROCK=your_bedrock_bearer_token
WORKLOAD_MODEL=bedrock/converse/arn:aws:bedrock:us-east-1:426628337772:application-inference-profile/4w7tmk1iplxi

# OPTIONAL
DEBUG=1                                            # Enable debug logging
```

> **No `CR_PAT` or `GH_USERNAME` needed.** You're building images locally, not pulling from GHCR.

#### Option B: Pull Pre-Built Images (original 9 repos from GHCR)

If you're using the original 498-task dataset with prebuilt Docker images on GHCR, you also need:

```bash
# All from Option A, PLUS:

# REQUIRED for Docker image pull from GHCR (one-time login)
CR_PAT=ghp_container_registry_token                # GitHub PAT with read:packages scope
GH_USERNAME=your_github_username                    # GHCR login username
```

#### Token Reference Table

| Token | Scope | Count | Used By | Need for Local Build? |
|-------|-------|-------|---------|-----------------------|
| `GITHUB_TOKENS` | `repo` | 3-5 recommended | PR scraping (Stage 1), parallelized via `multiprocessing.Pool` | **YES** |
| `GITHUB_TOKEN` | `repo` | 1 | Versioning (Stage 3), workload source fetch (Stage 5) | **YES** |
| `AWS_BEARER_TOKEN_BEDROCK` | — | 1 | Opus 4.6 LLM calls (Stages 5, 8) | **YES** |
| `CR_PAT` | `read:packages` | 1 | One-time `docker login ghcr.io` for prebuilt image pull | **NO** (local build) |
| `GH_USERNAME` | — | 1 | GHCR login username | **NO** (local build) |

#### How to Get GitHub Tokens

1. Go to **https://github.com/settings/tokens**
2. Click **"Generate new token (classic)"**
3. Select scopes:
   - **`repo`** — required for reading PR data from public repos
   - **`read:packages`** — only if pulling prebuilt GHCR images (Option B)
4. Click Generate, copy the `ghp_xxxxxxxxxxxx` string
5. Create 3-5 tokens for `GITHUB_TOKENS` (can be from the same account — each gets its own 5,000 req/hr rate limit)

**Shortcut** (single token from GitHub CLI):
```bash
export GITHUB_TOKENS=$(gh auth token)
export GITHUB_TOKEN=$(gh auth token)
```

#### Why Multiple Tokens?

GitHub API rate limit is **5,000 requests/hour per token**. Scraping thousands of PRs across many repos exhausts one token fast. The scraping pipeline (`get_tasks_pipeline.py`) splits repos across tokens — each `multiprocessing.Pool` worker gets its own token with its own rate limit budget. For 10K+ instances across hundreds of repos, 3-5 tokens prevent rate-limit stalls.

### Initial Setup

```bash
cd swefficiency/
uv venv --python 3.12
source .venv/bin/activate
uv sync

# Verify CLI works
swefficiency --help

# ONLY if pulling prebuilt images (Option B):
# echo $CR_PAT | docker login ghcr.io -u $GH_USERNAME --password-stdin

# HuggingFace auth (if dataset is gated)
huggingface-cli login
```

---

## 3. Stage 1: Scrape Pull Requests from GitHub

**Script**: `swefficiency/collect/get_tasks_pipeline.py`  
**Purpose**: Scrape merged PRs from target GitHub repos and convert them to candidate task instances.

### Command

```bash
python -m swefficiency.collect.get_tasks_pipeline \
    --repos owner1/repo1 owner2/repo2 owner3/repo3 \
    --path_prs artifacts/0_prs \
    --path_tasks artifacts/0_tasks \
    --max_pulls 3000 \
    --cutoff_date 20260101
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--repos` | Yes | — | Space-separated list of GitHub repos (e.g., `numpy/numpy pandas-dev/pandas`) |
| `--path_prs` | Yes | — | Directory to save raw PR JSONL files |
| `--path_tasks` | Yes | — | Directory to save task instance JSONL files |
| `--max_pulls` | No | None (all) | Maximum number of PRs to scrape per repo |
| `--cutoff_date` | No | None | Only PRs created before this date (format: `YYYYMMDD`) |

### Environment Variables Required

- `GITHUB_TOKENS` — Comma-separated GitHub PATs. The script splits repos across tokens for parallel scraping via `multiprocessing.Pool`.

### Input

- None (scrapes directly from GitHub API).

### Output

```
artifacts/0_prs/
  <repo_name>-prs.jsonl              # Raw PR data (one JSON per line)
  <repo_name>-prs-<cutoff>.jsonl     # If --cutoff_date is set

artifacts/0_tasks/
  <repo_name>-task-instances.jsonl       # Task instances (with test patches)
  <repo_name>-task-instances.jsonl.all   # ALL instances (including those without tests)
```

### Output Fields (per task instance)

| Field | Type | Description |
|-------|------|-------------|
| `repo` | str | `owner/repo` (e.g., `numpy/numpy`) |
| `pull_number` | int | PR number |
| `instance_id` | str | `owner__repo-<PR#>` (e.g., `numpy__numpy-18065`) |
| `issue_numbers` | list | Resolved issue numbers |
| `base_commit` | str | SHA of the base commit the PR targets |
| `patch` | str | Full unified diff of the PR (the "gold" fix) |
| `test_patch` | str | Unified diff of test changes (empty string if no tests) |
| `problem_statement` | str | PR title + body |
| `hints_text` | str | Comment text from the PR |
| `created_at` | str | ISO timestamp of PR creation |

### How It Works

1. For each repo, calls `print_pulls()` to fetch merged PRs via GitHub API → writes `<repo>-prs.jsonl`
2. For each PR in the JSONL, calls `build_dataset()` → extracts patches, problem statement, hints → filters for valid instances (must have non-empty `patch`) → writes task instances
3. Instances WITH test patches go to the main output file; ALL instances go to `.all` file
4. Skips already-processed PRs (resume-friendly via `.all` file)

---

## 4. Stage 2: Filter Performance-Related PRs

**Script**: `swefficiency/perf_filter/attributes/filter.py`  
**Purpose**: Keep only PRs related to performance optimization. Uses repo-specific label/keyword filters plus a default keyword filter.

### Command

```bash
python -m swefficiency.perf_filter.attributes.filter \
    --prs_path artifacts/0_prs/<repo_name>-prs.jsonl \
    --instances_path artifacts/0_tasks/<repo_name>-task-instances.jsonl \
    --output_dir artifacts/1_attributes
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--prs_path` | Yes | — | Path to raw PRs JSONL from Stage 1 |
| `--instances_path` | Yes | — | Path to task instances JSONL from Stage 1 |
| `--output_dir` | Yes | — | Directory to save filtered instances |

### Input

- `artifacts/0_prs/<repo_name>-prs.jsonl` — Raw PR data
- `artifacts/0_tasks/<repo_name>-task-instances.jsonl` — Task instances

### Output

```
artifacts/1_attributes/
  <repo_name>-task-instances_attribute.jsonl   # Performance-filtered instances
```

### How It Works

1. Loads PRs and filters for merged-only
2. Applies **repo-specific** filter (label matching, e.g., "performance" label for numpy) if available
3. Applies **default** keyword filter (searches PR title/body for perf keywords like "speed", "performance", "optimize")
4. Takes the union of both filter results
5. Removes markdown-only changes and lock file changes
6. Writes filtered instances

### Filter Logic

- Repo-specific filters defined in `perf_filter/attributes/constants.py` → `REPO_PERF_FILTERS` dict
- Default filter: regex match on PR title/body for performance keywords
- Two tiers: "guaranteed" (repo-specific) and "possible" (default keywords) — unioned together

---

## 5. Stage 3: Add Version Information

**Script**: `swefficiency/versioning/get_versions.py` (or wrapper `scripts/run_get_versions.sh`)  
**Purpose**: Detect the library version at each instance's `base_commit`. Needed for Docker image building.

### Command (via shell wrapper)

```bash
bash scripts/run_get_versions.sh <repo_name>
# e.g.: bash scripts/run_get_versions.sh numpy__numpy
```

### Command (direct)

```bash
python swefficiency/versioning/get_versions.py \
    --instances_path artifacts/1_attributes/<repo_name>-task-instances_attribute.jsonl \
    --retrieval_method github \
    --conda_env temp \
    --num_workers 4 \
    --path_conda ~/miniforge3/condabin/conda \
    --output_dir artifacts/2_versioning \
    --testbed ~/scratch/testbed
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--instances_path` | Yes | — | Path to filtered instances from Stage 2 |
| `--retrieval_method` | Yes | — | `github` (GitHub raw URL), `build` (clone+install), or `mix` (github first, build fallback) |
| `--conda_env` | No | None | Conda env name (needed for `build`/`mix` methods) |
| `--path_conda` | No | None | Path to conda executable |
| `--num_workers` | No | 1 | Parallel workers |
| `--output_dir` | No | None | Output directory |
| `--testbed` | No | None | Path for repo clones (needed for `build`/`mix`) |
| `--cleanup` | No | False | Remove cloned repos and conda envs after |

### Input

- `artifacts/1_attributes/<repo_name>-task-instances_attribute.jsonl`

### Output

```
artifacts/2_versioning/
  <repo_name>-task-instances_attribute_versions.json  # Instances with version field added
```

### How It Works

1. **`github` method**: Fetches version files (e.g., `numpy/__init__.py`) from `raw.githubusercontent.com` at `base_commit`, applies regex patterns from `MAP_REPO_TO_VERSION_PATTERNS`
2. **`build` method**: Clones repo, checks out `base_commit`, installs in conda env, imports package to get `__version__`
3. **`mix` method**: Tries `github` first, falls back to `build` for failures
4. Post-processing: `scripts/filter_empty_version.py` removes instances where version detection failed

### Repo Registration

Version patterns are in `swefficiency/versioning/constants.py`:
- `MAP_REPO_TO_VERSION_PATHS` — Maps repo → list of file paths containing version info
- `MAP_REPO_TO_VERSION_PATTERNS` — Maps repo → list of regex patterns to extract version

For **new repos** not in these maps: use `scripts/detect_repo_specs.py` (Stage 4) which auto-detects versions.

---

## 6. Stage 4: Auto-Detect Repo Specifications (New Repos)

**Script**: `scripts/detect_repo_specs.py`  
**Purpose**: For repos NOT in the hardcoded 9, auto-detect Python version, install command, test command, dependencies, and license. Enriches the dataset JSONL with fields needed for Docker image building.

### Command

```bash
python scripts/detect_repo_specs.py \
    --input artifacts/2_versioning/<repo_name>-task-instances_attribute_versions.json \
    --output artifacts/3_enriched/<repo_name>-enriched.jsonl \
    --clone-dir /tmp/detect_clones \
    --workers 4 \
    --license-filter \
    --cache-file .specs_cache.json
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--input` | Yes | — | Input JSONL (or HuggingFace dataset name) |
| `--output` | Yes | — | Output enriched JSONL |
| `--clone-dir` | No | `/tmp/detect_clones` | Where to clone repos temporarily |
| `--workers` | No | 1 | Parallel workers for detection |
| `--license-filter` | No | False | Only keep repos with open licenses (MIT, Apache-2.0, BSD-3, BSD-2, ISC) |
| `--cache-file` | No | None | JSON cache for incremental runs |
| `--dry-run` | No | False | Print detections without writing |
| `--validate` | No | False | Validate existing JSONL has all required fields |

### Input

- JSONL with at least: `repo`, `base_commit`, `instance_id`

### Output

- Enriched JSONL with 9 additional fields per instance:

| Field | Example | Detection Source |
|-------|---------|------------------|
| `python_version` | `"3.9"` | .python-version → pyproject.toml → setup.py → fallback "3.10" |
| `install_cmd` | `"pip install -e ."` | pyproject.toml build-system → setup.py → fallback |
| `test_cmd_override` | `"pytest {test_files}"` | pyproject.toml pytest config → tox.ini → fallback |
| `packages_source` | `"requirements.txt"` | environment.yml → requirements.txt → pyproject.toml deps |
| `pip_packages` | `["pytest", "cython"]` | Extracted from pyproject.toml [project.dependencies] |
| `pre_install_cmds` | `["apt-get install -y libopenblas-dev"]` | C extensions, meson.build, Fortran detection |
| `reqs_paths` | `["requirements.txt"]` | Found requirements*.txt files |
| `env_yml_paths` | `["environment.yml"]` | Found environment*.yml files |
| `log_parser_type` | `"pytest"` | Always "pytest" (default) |
| `version` | `"1.5.3"` | pyproject.toml → setup.py → __init__.py → VERSION file |
| `license` | `"MIT"` | LICENSE file regex → pyproject.toml license field |

### How It Works

1. Groups instances by `(repo, base_commit)` — clones each unique pair once
2. Checks out `base_commit`, runs 7 detection functions
3. Caches results in `.specs_cache.json` for incremental runs
4. License filter: rejects repos without MIT, Apache-2.0, BSD-3-Clause, BSD-2-Clause, ISC, MIT-0

> **Note**: Skip this stage entirely for the original 9 repos (numpy, pandas, scipy, scikit-learn, matplotlib, xarray, sympy, dask, astropy) — they're already in the hardcoded `MAP_REPO_VERSION_TO_SPECS`.

---

## 7. Stage 5: Generate Workload Benchmarks (LLM)

**Script**: `swefficiency/workload/run_synthetic_generation.py`  
**Purpose**: Use an LLM (Gemini 2.5 Flash) to generate `timeit`-based workload scripts for each instance. The workload exercises the code paths changed by the PR.

### Command

```bash
python -m swefficiency.workload.run_synthetic_generation \
    --dataset_name artifacts/3_enriched/<repo_name>-enriched.jsonl \
    --split test \
    --run_id workload_v1 \
    --max_workers 16
```

Or using the existing HuggingFace dataset:

```bash
python -m swefficiency.workload.run_synthetic_generation \
    --dataset_name swefficiency/swefficiency \
    --split test \
    --run_id workload_v1 \
    --max_workers 16 \
    --instance_ids numpy__numpy-18065 pandas-dev__pandas-38248
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--dataset_name` | No | `swefficiency/swefficiency` | HuggingFace dataset name or path to JSONL |
| `--split` | No | `test` | Dataset split |
| `--run_id` | **Yes** | — | Unique run identifier |
| `--max_workers` | No | 16 | Parallel LLM API calls |
| `--instance_ids` | No | all | Space-separated instance IDs to process |

### Environment Variables Required

- `AWS_BEARER_TOKEN_BEDROCK` — Bearer token for Bedrock. The script uses `litellm` with the model set by `WORKLOAD_MODEL` env var (default: Opus 4.6 ARN `bedrock/converse/arn:aws:bedrock:us-east-1:...4w7tmk1iplxi`).
- `WORKLOAD_MODEL` — (Optional) Override the LLM model. If not set, defaults to the Opus 4.6 ARN.

### Input

- Dataset instances with `repo`, `base_commit`, `patch` fields

### Output

```
logs/workload_generation/<run_id>/
  workload_generation.json          # JSONL: {instance_id, run_id, workload}
  <instance_id>.py                  # Individual workload scripts
```

### Output Fields (per line in workload_generation.json)

| Field | Type | Description |
|-------|------|-------------|
| `instance_id` | str | Instance identifier |
| `run_id` | str | Run identifier |
| `workload` | str | Python code for the workload script |

### How It Works

1. For each instance, fetches pre-edit source files from `raw.githubusercontent.com`
2. Sends PR diff + source files to Gemini 2.5 Flash with a system prompt instructing it to write a `timeit.repeat()` benchmark
3. Extracts code block from LLM response
4. Saves both individual `.py` files and aggregated JSONL
5. Retries on API errors with 5-second backoff

### Workload Script Format

```python
import timeit
import statistics

def setup():
    # Prepare data, set random seed, etc.
    ...

def workload():
    # Exercise the optimized code path
    ...

runtimes = timeit.repeat(workload, number=1, repeat=10, setup=setup)
print("Mean:", statistics.mean(runtimes))
print("Std Dev:", statistics.stdev(runtimes))
```

---

## 8. Stage 6: Assemble Final Dataset

**Purpose**: Merge workload scripts + version info + test fields into a final dataset JSONL suitable for Docker builds and evaluation.

### ⚠️ No Automated Script Exists

This step currently requires **manual assembly**. You need to merge:

1. **Versioned instances** (from Stage 3) — has `repo`, `instance_id`, `base_commit`, `patch`, `test_patch`, `version`
2. **Auto-detected specs** (from Stage 4) — has `python_version`, `install_cmd`, etc.
3. **Workloads** (from Stage 5) — has `workload` field per instance
4. **Test fields** — `PASS_TO_PASS`, `FAIL_TO_PASS` (require manual curation or extraction from test_patch)

### Assembly Script (inline)

```python
#!/usr/bin/env python3
"""Merge enriched instances with generated workloads into final dataset."""
import json
from pathlib import Path

def merge_dataset(
    enriched_jsonl: str,
    workload_jsonl: str,
    output_jsonl: str,
):
    # Load enriched instances
    instances = {}
    with open(enriched_jsonl) as f:
        for line in f:
            inst = json.loads(line)
            instances[inst["instance_id"]] = inst

    # Load workloads
    with open(workload_jsonl) as f:
        for line in f:
            wl = json.loads(line)
            iid = wl["instance_id"]
            if iid in instances:
                instances[iid]["workload"] = wl["workload"]

    # Write final dataset
    with open(output_jsonl, "w") as f:
        for inst in instances.values():
            # Add required fields with defaults if missing
            inst.setdefault("PASS_TO_PASS", "[]")
            inst.setdefault("FAIL_TO_PASS", "[]")
            inst.setdefault("environment_setup_commit", inst.get("base_commit", ""))
            inst.setdefault("workload", "")
            inst.setdefault("speedup", "")
            f.write(json.dumps(inst) + "\n")

    print(f"Wrote {len(instances)} instances to {output_jsonl}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--enriched", required=True)
    p.add_argument("--workloads", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    merge_dataset(args.enriched, args.workloads, args.output)
```

### Command

```bash
python merge_dataset.py \
    --enriched artifacts/3_enriched/<repo_name>-enriched.jsonl \
    --workloads logs/workload_generation/<run_id>/workload_generation.json \
    --output artifacts/final/<repo_name>-dataset.jsonl
```

### Required Fields in Final Dataset

| Field | Required For | Source |
|-------|-------------|--------|
| `repo` | All stages | Stage 1 |
| `instance_id` | All stages | Stage 1 |
| `base_commit` | Docker build, eval | Stage 1 |
| `patch` | Eval (gold patch) | Stage 1 |
| `test_patch` | Eval (correctness) | Stage 1 |
| `version` | Docker build | Stage 3 or 4 |
| `workload` | Eval (performance) | Stage 5 |
| `PASS_TO_PASS` | Eval (correctness) | Manual curation |
| `FAIL_TO_PASS` | Eval (correctness) | Manual curation |
| `environment_setup_commit` | Docker build | Defaults to `base_commit` |
| `python_version` | Docker build (new repos) | Stage 4 |
| `install_cmd` | Docker build (new repos) | Stage 4 |
| `test_cmd_override` | Docker build (new repos) | Stage 4 |
| `packages_source` | Docker build (new repos) | Stage 4 |

---

## 9. Stage 7: Build Docker Images

**Purpose**: Build Docker containers for each instance. Two paths depending on whether you're using the original dataset or new repos.

### Option A: Pull Pre-Built Images (Original 9 Repos)

> **Requires**: `CR_PAT` + `GH_USERNAME` (see Section 2, Option B).

```bash
# One-time GHCR login:
echo $CR_PAT | docker login ghcr.io -u $GH_USERNAME --password-stdin

# Images are automatically pulled during eval/inference
# Manual pull:
docker pull ghcr.io/swefficiency/swefficiency-images:<instance_id>
# e.g.:
docker pull ghcr.io/swefficiency/swefficiency-images:numpy__numpy-18065
```

### Option B: Build Locally (New Repos — No GHCR Auth Needed)

> **No `CR_PAT` or `GH_USERNAME` needed.** Everything builds from Ubuntu base image + conda + git clone from public GitHub repos.

```bash
# Build from the harness (builds base → env → instance layers)
python -m swefficiency.harness.docker_build \
    --dataset_path artifacts/final/<repo_name>-dataset.jsonl \
    --num_workers 4
```

**Local image naming convention** (from `test_spec.py`):

| Layer | Local Tag | Example |
|-------|-----------|---------|
| Base | `sweb.base.{arch}:latest` | `sweb.base.x86_64:latest` |
| Env | `sweb.env.{arch}.{sha256_22}:latest` | `sweb.env.x86_64.a1b2c3d4e5f6g7h8i9j0kl:latest` |
| Instance | `sweb.eval.{arch}.{instance_id}:latest` | `sweb.eval.x86_64.numpy__numpy-18065:latest` |
| Annotate | `sweb.eval.{arch}.{instance_id}.annotate:latest` | `sweb.eval.x86_64.numpy__numpy-18065.annotate:latest` |

Where `{arch}` is:
- `x86_64` — on x86_64 hosts (or ARM hosts for repos in `USE_X86` set)
- `arm64` — on ARM hosts (aarch64/arm64) for repos NOT in `USE_X86`

**To use locally-built images with inference/eval**, tag them to match the GHCR pattern the harness expects:

```bash
# For x86_64 builds:
docker tag sweb.eval.x86_64.<instance_id>:latest \
    ghcr.io/swefficiency/swefficiency-images:<instance_id>

# For arm64 builds:
docker tag sweb.eval.arm64.<instance_id>:latest \
    ghcr.io/swefficiency/swefficiency-images:<instance_id>
```

> **Tip**: The eval harness (`run_validation.py`) uses `ghcr.io/swefficiency/swefficiency-images:{instance_id}` as its image key regardless of source. Tagging your local build to this name avoids any GHCR pull — Docker finds it locally.

### 4-Layer Image Hierarchy

```
Layer 1: BASE      (sweb.base.x86_64:latest)
  └─ Ubuntu 22.04 + Miniconda + build tools (gcc, gfortran, libopenblas)

Layer 2: ENV       (sweb.env.x86_64.<sha256>:latest)
  └─ FROM base + conda env + repo dependencies (SHA-256 for cache key)

Layer 3: INSTANCE  (sweb.eval.x86_64.<instance_id>:latest)
  └─ FROM env + git clone at base_commit + pip install

Layer 4: ANNOTATE  (optional, for manual curation)
  └─ FROM instance + patch.diff + workload perf.sh
```

> **⚠️ Linux-only**: Docker image building reads `/sys/devices/system/cpu/` for NUMA topology. Will fail on macOS with `FileNotFoundError`. Use a Linux VM or GCP instance.

---

## 10. Stage 8: Run Agent Inference (Trajectories)

**Purpose**: Run an AI agent against each instance to produce optimization patches.

### Option A: OpenHands Agent (Recommended)

```bash
python scripts/inference/custom.py \
    --mode openhands \
    --run-id my_agent_run \
    --llm-config scripts/inference/llm_configs/bedrock.json \
    --dataset artifacts/final/<repo_name>-dataset.jsonl \
    --num-workers 2 \
    --max-iterations 100 \
    --instance-ids numpy__numpy-18065
```

### Option B: Custom Agent via YAML Spec (Default Mode)

```bash
python scripts/inference/custom.py \
    --run-id my_cursor_run \
    --spec scripts/inference/specs/cursor_cli.yaml \
    --dataset swefficiency/swefficiency \
    --num-workers 2 \
    --instance-ids numpy__numpy-18065
```

### Key Parameters (OpenHands Mode)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--mode` | No | `default` | `default` (YAML spec) or `openhands` (agent SDK) |
| `--run-id` | **Yes** | — | Unique run identifier |
| `--llm-config` | Yes (openhands) | — | Path to LLM config JSON |
| `--dataset` | No | `swefficiency/swefficiency` | HuggingFace name or JSONL path |
| `--split` | No | `test` | Dataset split |
| `--num-workers` | No | 2 | Parallel Docker workers |
| `--instance-ids` | No | all | Space-separated instance IDs |
| `--instance-regex` | No | all | Regex filter on instance IDs |
| `--max-instances` | No | all | Cap on instances to process |
| `--max-iterations` | No | 100 | Max agent conversation iterations |
| `--max-fake-responses` | No | 10 | Max "continue" nudges to agent |
| `--cpus-per-worker` | No | 4 | vCPUs per Docker container |
| `--mem-limit` | No | `32g` | Memory limit per container |
| `--dry-run` | No | False | Show what would run without executing |
| `--stream-logs` | No | False | Stream container logs to stdout |
| `--keep-containers` | No | False | Don't remove containers after |

### Environment Variables Required

- `AWS_BEARER_TOKEN_BEDROCK` — For Bedrock LLM auth

### LLM Config JSON (`bedrock.json`)

```json
{
  "model": "bedrock/arn:aws:bedrock:ap-south-1:426628337772:application-inference-profile/f0v1auqubh66",
  "aws_region_name": "ap-south-1",
  "temperature": 0.0,
  "max_output_tokens": 16384
}
```

### Output (OpenHands Mode)

```
logs/run_inference/<run_id>/openhands/<instance_id>/
  patch.diff                    # Git diff (for evaluation)
  container.log                 # Full container output
  patch.log                     # Patch extraction log
  workspace_setup.log           # Workspace initialization log
  agent_conversation.log        # Agent conversation transcript
  openhands_prompt.txt          # Rendered instruction prompt

logs/run_inference/<run_id>/openhands/
  output.jsonl                  # All results (EvalOutput format with trajectories)
  output_errors.jsonl           # Error cases
  predictions.jsonl             # Auto-generated for eval pipeline
```

### Output (Default Mode)

```
logs/run_inference/<run_id>/<spec_name>/<instance_id>/
  patch.diff                    # Git diff
  container.log                 # Container output
  inference.log                 # Agent execution log
  prework_*.log                 # Setup script logs
```

---

## 11. Stage 9: Evaluate Predictions

**Purpose**: Apply model patches to Docker containers, run correctness tests and performance benchmarks, measure speedup.

### Step 1: Run Gold Baseline (Expert Patches)

```bash
swefficiency eval \
    --run_id my_eval \
    --dataset artifacts/final/<repo_name>-dataset.jsonl \
    --num_workers 12
```

This runs the **expert (gold) patches** from the dataset. Results go to `logs/run_evaluation/my_eval/gold/`.

### Step 2: Run Model Predictions

```bash
swefficiency eval \
    --run_id my_eval \
    --dataset artifacts/final/<repo_name>-dataset.jsonl \
    --prediction_path logs/run_inference/<run_id>/openhands/predictions.jsonl \
    --num_workers 12
```

This runs your **agent's patches**. Results go to `logs/run_evaluation/my_eval/<model_name>/`.

### Prediction JSONL Format

Each line:

```json
{
  "instance_id": "numpy__numpy-18065",
  "model_patch": "diff --git a/numpy/core/...\n...",
  "model_name_or_path": "openhands-bedrock-v1"
}
```

### Converting Inference Output → Prediction JSONL

If using OpenHands mode, `predictions.jsonl` is auto-generated. If using default mode:

```python
import json, os
from pathlib import Path

run_dir = Path("logs/run_inference/<run_id>/<spec_name>")
predictions = []

for inst_dir in sorted(run_dir.iterdir()):
    if not inst_dir.is_dir():
        continue
    patch_file = inst_dir / "patch.diff"
    if patch_file.exists():
        patch_text = patch_file.read_text()
        if patch_text.strip():
            predictions.append({
                "instance_id": inst_dir.name,
                "model_patch": patch_text,
                "model_name_or_path": "my-agent"
            })

with open("predictions.jsonl", "w") as f:
    for p in predictions:
        f.write(json.dumps(p) + "\n")

print(f"Wrote {len(predictions)} predictions")
```

### Eval Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--run_id` | No | auto-generated | Unique run identifier |
| `--dataset` | No | `swefficiency/swefficiency` | HuggingFace name or JSONL path |
| `--num_workers` | No | 4 | Parallel Docker workers |
| `--prediction_path` | No | None (gold baseline) | Path to prediction JSONL |
| `--instances_regex` | No | all | Regex filter on instance IDs |
| `--force_rerun` | No | False | Force re-evaluation |

### Eval Output Structure

```
logs/run_evaluation/<run_id>/<model_name>/<instance_id>/
  report.json                   # pass/fail per test
  test_output.txt               # Raw test stdout/stderr
  perf_summary.txt              # Performance measurements
  patch.diff                    # Applied patch
```

### perf_summary.txt Format

```
Before Mean: 1.234
Before SD: 0.012
After Mean: 0.567
After SD: 0.008
Improvement: 217.64%
```

> **Note**: `Improvement = (Before Mean / After Mean) × 100` — it's a speedup multiplier as percent, NOT a percentage reduction.

> **⚠️ Linux-only**: Evaluation reads `/sys/devices/system/cpu/` for NUMA-aware CPU pinning. Must run on Linux. Recommended: GCP `n2-standard-64` with 12 workers.

---

## 12. Stage 10: Generate Report

**Purpose**: Compare gold baseline vs. model predictions, compute Speedup Ratio (SR) and aggregate metrics.

### Command

```bash
swefficiency report \
    --gold_run logs/run_evaluation/my_eval/gold \
    --pred_run logs/run_evaluation/my_eval/<model_name> \
    --report_output eval_reports \
    --num_workers 4
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--gold_run` | **Yes** | — | Path to gold baseline eval directory |
| `--pred_run` | **Yes** | — | Path to model prediction eval directory |
| `--report_output` | No | `eval_reports` | Output directory |
| `--num_workers` | No | 4 | Parallel workers |

### Output

```
eval_reports/
  eval_report_<model_name>.csv    # Per-instance metrics
  eval_report_<model_name>.json   # Aggregate metrics
```

### CSV Columns (Per Instance)

| Column | Description |
|--------|-------------|
| `instance_id` | Instance identifier |
| `raw_pred_speedup_ratio` | Unadjusted model speedup (T_pre / T_post) before correctness check |
| `pred_speedup_ratio` | Adjusted — forced to 1.0 if correctness fails |
| `gold_speedup_ratio` | Expert patch speedup (T_pre / T_post_gold) |
| `human_speedup_ratio` | SR = pred_speedup_ratio / gold_speedup_ratio |
| `correctness` | Binary flag: 1.0 = all PASS_TO_PASS tests pass, 0.0 = at least one failure |
| `correctness_pct` | Fraction of PASS_TO_PASS tests that passed (0.0–1.0) |
| `pre_edit_runtime` | Pre-edit workload runtime (seconds) — used as T_pre |
| `patch_length` | Total number of lines in the expert (gold) patch from the dataset |

### JSON Output Fields

| Field | Description |
|-------|-------------|
| `total_instances` | Number of instances evaluated |
| `overall_score` | **Harmonic mean** of human_speedup_ratio across all instances |
| `proportion_incorrect` | Fraction of instances where correctness < 100% |
| `proportion_correct_but_no_speedup` | Correct but pred_speedup ≤ 1.0 |
| `proportion_correct_with_speedup_but_human_no_speedup` | Correct + faster, but still below expert |
| `proportion_human_speedup_or_better` | Correct + matches or exceeds expert speedup |
| `report` | CSV filename |

### Scoring Rules

| Scenario | Effect |
|----------|--------|
| Patch fails correctness | `pred_speedup_ratio` forced to 1.0 → SR = 1.0 / gold_speedup |
| Patch correct, no speedup | SR = 1.0 / gold_speedup (below 1.0 if expert was faster) |
| Patch correct, matches expert | SR ≈ 1.0 |
| Patch correct, exceeds expert | SR > 1.0 |
| Empty/failed patch | Treated as "no speedup" (pred_speedup = 1.0) |

Aggregate `overall_score` = harmonic mean of all SRs, floored at 0.001 per instance.

---

## 13. Gaps & Manual Steps

| Gap | Description | Workaround |
|-----|-------------|------------|
| **No automated merge script** | No built-in tool to combine Stages 3-5 outputs into final dataset | Use the inline script in Stage 6 |
| **PASS_TO_PASS / FAIL_TO_PASS** | These test fields need manual curation — extracting which tests should pass before/after the fix | Parse `test_patch` diff, or run tests on base_commit to establish baseline |
| **Workload quality** | LLM-generated workloads may be incorrect or non-representative | Manual review recommended; the paper used human annotation |
| **Docker build = Linux-only** | Image building and evaluation read `/sys/devices/system/cpu/` (sysfs) | Use GCP VM, not macOS |
| **ARM64 hosts** | Docker images are amd64 — ARM64 hosts need Rosetta/QEMU emulation | Enable Rosetta in Docker Desktop settings |
| **perf_filter for new repos** | Filter keywords are tuned for the original repos | Define custom `REPO_PERF_FILTERS` entries or skip filtering |
| **Versioning for new repos** | `MAP_REPO_TO_VERSION_PATHS/PATTERNS` only covers ~55 repos | Use `detect_repo_specs.py` (Stage 4) for auto-detection |

---

## 14. Quick Reference Card

### Full Pipeline (Copy-Paste)

```bash
# ── Setup ──
cd swefficiency/
source .venv/bin/activate
export GITHUB_TOKENS="ghp_t1,ghp_t2"
export GITHUB_TOKEN="ghp_t1"
export AWS_BEARER_TOKEN_BEDROCK="your_token"
# ONLY if pulling prebuilt GHCR images (not needed for local builds):
# export CR_PAT="ghp_cr_token"
# export GH_USERNAME="you"
# echo $CR_PAT | docker login ghcr.io -u $GH_USERNAME --password-stdin

# ── Stage 1: Scrape PRs ──
mkdir -p artifacts/{0_prs,0_tasks,1_attributes,2_versioning,3_enriched,final}

python -m swefficiency.collect.get_tasks_pipeline \
    --repos owner/repo \
    --path_prs artifacts/0_prs \
    --path_tasks artifacts/0_tasks

# ── Stage 2: Filter perf PRs ──
python -m swefficiency.perf_filter.attributes.filter \
    --prs_path artifacts/0_prs/repo-prs.jsonl \
    --instances_path artifacts/0_tasks/repo-task-instances.jsonl \
    --output_dir artifacts/1_attributes

# ── Stage 3: Version detection ──
python swefficiency/versioning/get_versions.py \
    --instances_path artifacts/1_attributes/repo-task-instances_attribute.jsonl \
    --retrieval_method github \
    --output_dir artifacts/2_versioning

# ── Stage 4: Auto-detect specs (new repos only) ──
python scripts/detect_repo_specs.py \
    --input artifacts/2_versioning/repo-task-instances_attribute_versions.json \
    --output artifacts/3_enriched/repo-enriched.jsonl \
    --license-filter \
    --workers 4

# ── Stage 5: Generate workloads ──
python -m swefficiency.workload.run_synthetic_generation \
    --dataset_name artifacts/3_enriched/repo-enriched.jsonl \
    --run_id wl_v1 \
    --max_workers 16

# ── Stage 6: Merge into final dataset ──
python merge_dataset.py \
    --enriched artifacts/3_enriched/repo-enriched.jsonl \
    --workloads logs/workload_generation/wl_v1/workload_generation.json \
    --output artifacts/final/repo-dataset.jsonl

# ── Stage 7: Build Docker (new repos, Linux only) ──
# No GHCR auth needed for local builds.
# After building, tag to match GHCR naming:
# docker tag sweb.eval.x86_64.<instance_id>:latest ghcr.io/swefficiency/swefficiency-images:<instance_id>
# Skip this stage if using pre-built GHCR images for original 9 repos

# ── Stage 8: Agent inference ──
python scripts/inference/custom.py \
    --mode openhands \
    --run-id agent_v1 \
    --llm-config scripts/inference/llm_configs/bedrock.json \
    --dataset artifacts/final/repo-dataset.jsonl \
    --num-workers 2 \
    --max-iterations 100

# ── Stage 9: Gold baseline + model eval (Linux only) ──
swefficiency eval --run_id eval_v1 \
    --dataset artifacts/final/repo-dataset.jsonl --num_workers 12

swefficiency eval --run_id eval_v1 \
    --dataset artifacts/final/repo-dataset.jsonl \
    --prediction_path logs/run_inference/agent_v1/openhands/predictions.jsonl \
    --num_workers 12

# ── Stage 10: Report ──
swefficiency report \
    --gold_run logs/run_evaluation/eval_v1/gold \
    --pred_run logs/run_evaluation/eval_v1/openhands-bedrock-v1 \
    --report_output eval_reports
```

### Using Pre-Existing HuggingFace Dataset (Skip Stages 1–6)

```bash
# Just run inference + eval on the official 498-task dataset:

python scripts/inference/custom.py \
    --mode openhands \
    --run-id quick_test \
    --llm-config scripts/inference/llm_configs/bedrock.json \
    --num-workers 2 \
    --instance-ids numpy__numpy-18065

swefficiency eval --run_id quick_test --num_workers 4
swefficiency eval --run_id quick_test --num_workers 4 \
    --prediction_path logs/run_inference/quick_test/openhands/predictions.jsonl

swefficiency report \
    --gold_run logs/run_evaluation/quick_test/gold \
    --pred_run logs/run_evaluation/quick_test/openhands-bedrock-v1
```
