# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import os
import random
import re
import time
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
from litellm import completion
from tqdm import tqdm

from swefficiency.harness.constants import SWEfficiencyInstance
from swefficiency.harness.utils import load_swefficiency_dataset
from swefficiency.observability import helicone_metadata, safe_completion_cost, setup_helicone
from swefficiency.workload.cost_tracker import CostLimitExceeded, CostTracker
from swefficiency.workload.rate_limiter import get_default_bucket

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

WORKLOAD_GENERATION_DIR = Path("logs/workload_generation")

# Retry settings
MAX_LLM_RETRIES = 5
LLM_BACKOFF_BASE = 2  # exponential backoff: 2, 4, 8, 16, 32 seconds
HTTP_TIMEOUT = 30  # seconds for fetching source files
HTTP_MAX_RETRIES = 3

SYSTEM_MSG = """You are a performance testing expert. You will be provided a code edit as a git diff and the pre-edit source files. You need to generate a **self-contained Python performance workload script** that measures perfomance of code paths or APIs changed in the diff.

Guidelines for the workload script contents.

- Use a `setup()` function to prepare any realistic, non-trivial data or environment needed for the test.
  - Data must be representative of real-world usage (avoid trivial arrays or easily optimizable patterns).
  - Prefer real datasets or realistic synthetic data with reproducibility (set a random seed).
  - All expensive or one-time setup (e.g., file download, preprocessing) must be in `setup()`, not in the workload.

- Use a `workload()` function to run the actual operation(s) being timed.
  - The workload should reflect a **representative and challenging real-world use case** of the API or library under test.
  - Avoid corner cases that could be trivially optimized.
  - Inputs should be varied enough to prevent caching or constant-folding from affecting results.

- Run the benchmark using `timeit.repeat(workload, number=..., repeat=..., setup=setup)`.
  - `number` should match a realistic single-run execution count (do not batch multiple runs for cumulative timing).
  - `repeat` should be high enough to gather stable statistics.

- Print the mean and standard deviation of the last set of runtimes using `statistics.mean()` and `statistics.stdev()`.
  - Output should be clear and ready for performance comparison.

- The output must be a **complete Python script** containing only:
  1. import statements
  2. `setup()` function
  3. `workload()` function
  4. the `timeit.repeat()` call
  5. mean/stddev printing

The script should only print two lines at the end: the mean of measured runtimes and the standard deviation of runtimes.

Example workload to follow (please strictly follow this format of imports, setup function, workload function, timeit call, and print statements). In particular, make sure the mean and standard deviation print statements are exactly as shown below.

```python
import timeit
import statistics
import numpy as np

def setup():
    global arr
    np.random.seed(42)
    arr = np.random.rand(5000, 5000)

def workload():
    global arr
    _ = arr @ arr.T

runtimes = timeit.repeat(workload, number=1, repeat=10, setup=setup)

print("Mean:", statistics.mean(runtimes))
print("Std Dev:", statistics.stdev(runtimes))
```
"""


CONTEXT_MSG = """Here's a commit and it's information that does some optimization in the {repo_name} repository that might be relevant to writing the test:
## Commit Diff:
```
{commit_diff}
```

## Pre-edit source files:
{pre_edit_code}
"""


def extract_code_block(text):
    if text is None:
        return None
    match = re.search(r"```(?:[^\n]*)\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _fetch_file_with_retry(url: str) -> Optional[str]:
    """Fetch a file from GitHub with retry and timeout."""
    for attempt in range(HTTP_MAX_RETRIES):
        try:
            response = requests.get(url, timeout=HTTP_TIMEOUT)
            if response.status_code == 200:
                return response.text
            if response.status_code == 404:
                return None  # File doesn't exist at this commit
        except requests.RequestException as e:
            logger.warning(f"Request failed for {url}: {e} (attempt {attempt + 1}/{HTTP_MAX_RETRIES})")
        if attempt < HTTP_MAX_RETRIES - 1:
            time.sleep(2 ** attempt)
    return None


def worker_function(
    datum: SWEfficiencyInstance,
    run_id: str,
    cost_tracker: Optional[CostTracker] = None,
):
    output_file = WORKLOAD_GENERATION_DIR / run_id / f"{datum['instance_id']}.py"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Resume: skip if output already exists, is non-empty, and is NOT a poisoned file
    if output_file.exists() and output_file.stat().st_size > 0:
        content_check = output_file.read_text(errors='replace')[:100]
        if content_check.startswith('# WARNING: No code block extracted'):
            logger.info(f"[{datum['instance_id']}] Found poisoned workload, regenerating")
        else:
            logger.info(f"[{datum['instance_id']}] Already generated, skipping (resume)")
            return {
                "instance_id": datum["instance_id"],
                "run_id": run_id,
                "workload": output_file.read_text(),
                "workload_generation_cost": {
                    "model": "cached",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                },
                "resumed": True,
            }

    # Get relevant files from the patch.
    patch = datum["patch"]
    diff_pattern = r"diff --git a/.* b/(.*)"
    directives = re.findall(diff_pattern, patch)

    owner, repo = datum["repo"].split("/")
    commit_hash = datum["base_commit"]

    file_contents = []

    for file_path in directives:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_hash}/{file_path}"
        content = _fetch_file_with_retry(url)
        if content is not None:
            file_contents.append(f"File: {file_path}")
            file_contents.append(f"```\n{content}\n```\n")
        else:
            logger.warning(f"[{datum['instance_id']}] Could not fetch {file_path}")

    # Combine all file contents into a single string
    commit_diff = patch.strip()
    all_preedit_file_contents = "\n".join(file_contents)

    # LLM call with bounded retries and exponential backoff
    response = None
    last_error = None
    for attempt in range(MAX_LLM_RETRIES):
        get_default_bucket().acquire()
        try:
            model_name = os.environ.get(
                "WORKLOAD_MODEL",
                "bedrock/converse/global.anthropic.claude-opus-4-7",
            )
            api_base = os.environ.get("AWS_BEDROCK_RUNTIME_ENDPOINT")
            response = completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_MSG},
                    {
                        "role": "user",
                        "content": CONTEXT_MSG.format(
                            repo_name=repo,
                            commit_diff=commit_diff,
                            pre_edit_code=all_preedit_file_contents,
                        ),
                    },
                    {
                        "role": "user",
                        "content": "Can you write a workload in same style as the example?",
                    },
                ],
                api_base=api_base,
                metadata=helicone_metadata(
                    call_type="synthetic",
                    model_id=model_name,
                    extra={"InstanceId": datum["instance_id"]},
                ),
            )
            break
        except Exception as e:
            last_error = e
            backoff = LLM_BACKOFF_BASE ** attempt
            logger.warning(
                f"[{datum['instance_id']}] LLM error (attempt {attempt + 1}/{MAX_LLM_RETRIES}): {e}. "
                f"Retrying in {backoff}s..."
            )
            time.sleep(backoff)

    if response is None:
        logger.error(
            f"[{datum['instance_id']}] Failed after {MAX_LLM_RETRIES} attempts. Last error: {last_error}"
        )
        return {
            "instance_id": datum["instance_id"],
            "run_id": run_id,
            "workload": None,
            "error": str(last_error),
            "workload_generation_cost": {
                "model": model_name,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            },
        }

    result = response.choices[0].message.content
    code_block_content = extract_code_block(result)

    if code_block_content is None:
        logger.warning(
            f"[{datum['instance_id']}] No code block found in LLM response. "
            f"Response length: {len(result) if result else 0} chars"
        )

    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    total_tokens = getattr(usage, "total_tokens", 0) if usage else 0

    cost_usd = safe_completion_cost(response)
    if cost_tracker is not None:
        try:
            cost_tracker.add(cost_usd)
        except CostLimitExceeded:
            raise

    with open(output_file, "w") as f:
        if code_block_content:
            f.write(code_block_content)
        else:
            # Write raw response as fallback so file exists for resume
            f.write(f"# WARNING: No code block extracted from LLM response\n# Raw response saved below\n")
            f.write(f'"""\n{result}\n"""' if result else "# Empty response\n")

    return {
        "instance_id": datum["instance_id"],
        "run_id": run_id,
        "workload": code_block_content if code_block_content else result,
        "workload_generation_cost": {
            "model": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": round(cost_usd, 6),
        },
    }


def main(
    dataset_name: str,
    split: str,
    instance_ids: list[str],
    max_workers: int,
    run_id: str,
    no_resume: bool = False,
):
    setup_helicone()
    dataset = load_swefficiency_dataset(dataset_name, split)
    random.shuffle(dataset)  # Shuffle dataset for randomness

    WORKLOAD_GENERATION_DIR.mkdir(parents=True, exist_ok=True)
    output_dir = WORKLOAD_GENERATION_DIR / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    cost_tracker = CostTracker.for_run(run_id=run_id)
    if cost_tracker.cap_usd is not None:
        logger.info(
            "LLM cost cap: $%.2f (prior spend $%.4f)",
            cost_tracker.cap_usd, cost_tracker.total,
        )
    output_path = output_dir / "workload_generation.json"

    # Filter dataset by instance_ids if provided
    if instance_ids:
        dataset = [d for d in dataset if d["instance_id"] in instance_ids]

    # Resume: filter out already-completed instances (unless --no-resume)
    if not no_resume and output_path.exists():
        existing_ids = set()
        with open(output_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("workload") is not None:
                        existing_ids.add(entry["instance_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
        if existing_ids:
            before = len(dataset)
            dataset = [d for d in dataset if d["instance_id"] not in existing_ids]
            logger.info(f"Resume: skipping {before - len(dataset)} already-completed instances")

    if not dataset:
        logger.info("All instances already completed. Nothing to do.")
        return

    logger.info(f"Processing {len(dataset)} instances with {max_workers} workers")

    # Cost estimation warning for large runs
    if len(dataset) > 100:
        est_cost_low = len(dataset) * 0.03  # ~$0.03/instance with Haiku
        est_cost_high = len(dataset) * 0.15  # ~$0.15/instance with Opus
        logger.warning(
            f"Cost estimate for {len(dataset)} instances: "
            f"${est_cost_low:.0f}-${est_cost_high:.0f} (depends on model). "
            f"Set WORKLOAD_MODEL env var to control model choice."
        )

    results = []
    failed = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(worker_function, datum, run_id, cost_tracker): datum["instance_id"]
            for datum in dataset
        }
        for future in tqdm(
            as_completed(futures), total=len(futures), desc="Generating workloads"
        ):
            instance_id = futures[future]
            try:
                result = future.result()
                results.append(result)
                if result.get("error"):
                    failed.append(instance_id)
            except CostLimitExceeded as e:
                logger.error(
                    f"[{instance_id}] Cost cap hit ({e}). Cancelling remaining work."
                )
                for pending in futures:
                    pending.cancel()
                failed.append(instance_id)
                break
            except Exception as e:
                logger.error(f"[{instance_id}] Unhandled exception: {e}")
                failed.append(instance_id)
                results.append({
                    "instance_id": instance_id,
                    "run_id": run_id,
                    "workload": None,
                    "error": str(e),
                    "workload_generation_cost": {
                        "model": "unknown",
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "cost_usd": 0.0,
                    },
                })

    total_cost = sum(
        r.get("workload_generation_cost", {}).get("cost_usd", 0.0) for r in results
    )
    total_tokens = sum(
        r.get("workload_generation_cost", {}).get("total_tokens", 0) for r in results
    )
    resumed_count = sum(1 for r in results if r.get("resumed"))

    logger.info(
        f"Workload generation complete: {len(results)} instances "
        f"({resumed_count} resumed, {len(failed)} failed), "
        f"{total_tokens:,} tokens, ${total_cost:.4f} USD"
    )
    if failed:
        logger.warning(f"Failed instances: {failed}")

    # Append to output file (supports resume across runs)
    mode = "a" if output_path.exists() and not no_resume else "w"
    with open(output_path, mode) as f:
        for result in results:
            if not result.get("resumed"):  # Don't re-write cached entries
                f.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--dataset_name",
        default="swefficiency/swefficiency",
        type=str,
        help="Name of dataset or path to JSON file.",
    )
    parser.add_argument(
        "--split", type=str, default="test", help="Split of the dataset"
    )
    parser.add_argument(
        "--instance_ids",
        nargs="+",
        type=str,
        help="Instance IDs to run (space separated)",
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=16,
        help="Maximum number of workers (should be <= 75%% of CPU cores)",
    )
    parser.add_argument(
        "--run_id", type=str, required=True, help="Run ID - identifies the run"
    )
    parser.add_argument(
        "--no_resume",
        action="store_true",
        help="Disable resume mode (re-generate all instances from scratch)",
    )
    args = parser.parse_args()

    main(
        dataset_name=args.dataset_name,
        split=args.split,
        instance_ids=args.instance_ids,
        max_workers=args.max_workers,
        run_id=args.run_id,
        no_resume=args.no_resume,
    )
