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

"""Synthetic Vitest bench workload generation for the TypeScript pipeline.

Sibling of ``run_synthetic_generation.py`` but emits Vitest ``.bench.ts``
files instead of Python ``timeit`` scripts. Adds an optional in-container
validation step (``tsc --noEmit`` cheap, or ``vitest bench --run`` full)
so that broken workloads are fed back to the LLM (within MAX_LLM_RETRIES)
and ultimately DLQ'd.
"""

import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple

import requests
from litellm import completion
from tqdm import tqdm

from swefficiency.collect.utils import write_to_dlq
from swefficiency.harness.constants_ts import SWEfficiencyInstanceTs
from swefficiency.harness.utils import load_swefficiency_dataset
from swefficiency.observability import helicone_metadata, safe_completion_cost, setup_helicone
from swefficiency.workload.cost_tracker import CostLimitExceeded, CostTracker
from swefficiency.workload.rate_limiter import get_default_bucket

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

WORKLOAD_GENERATION_DIR_TS = Path("logs/workload_generation_ts")

# Retry settings (kept symmetric with Python pipeline).
MAX_LLM_RETRIES = 5
LLM_BACKOFF_BASE = 2
HTTP_TIMEOUT = 30
HTTP_MAX_RETRIES = 3

# Validation. Disabled by default to avoid Docker dependency at generation
# time. Set ``SWEFF_VALIDATE_TS_WORKLOAD=cheap`` for ``tsc --noEmit`` or
# ``SWEFF_VALIDATE_TS_WORKLOAD=full`` for ``vitest bench --run``.
_VALIDATE_ENV_FLAG = "SWEFF_VALIDATE_TS_WORKLOAD"
_VALIDATION_IMAGE_ENV = "SWEFF_TS_VALIDATION_IMAGE"
_VALIDATION_IMAGE_DEFAULT = "sweb.base.ts:latest"
_VALIDATION_TIMEOUT_S = 120


SYSTEM_MSG_TS = """You are a performance testing expert specialising in TypeScript. You will be provided a code edit as a git diff and the pre-edit source files. You need to generate a **self-contained Vitest bench TypeScript workload file** that measures the performance of the code paths or APIs changed in the diff.

Guidelines for the workload contents.

- Write a single file ``/tmp/workload.bench.ts``. Only one ``.bench.ts`` file; no helper files.

- Import { bench, describe } from 'vitest'.

- Use TypeScript syntax compilable under a strict ``tsc --noEmit`` check (target ES2022, module ESNext). Only import from the standard library, the repository under test (its public entry points), or ``vitest``.

- Wrap measurements in ``bench('name', () => { ... })`` (optionally grouped inside ``describe(...)`` blocks).
  - Place all expensive setup (data generation, file IO, model loading) **outside** the ``bench`` body — at module scope or inside ``beforeAll``/``beforeEach`` — so that it does not contaminate the measured region.
  - The workload itself must reflect a **representative and challenging real-world use case** of the API or library under test.
  - Inputs should be varied with deterministic seeding (e.g., a small PRNG class) to prevent caching, constant folding, or dead-code elimination from affecting the measurement.

- Do NOT use ``Date.now`` / ``performance.now`` manually — vitest measures.

- No ``console.log`` inside ``bench`` bodies.

- Default export is NOT required.

- Configure the benchmark to be stable.
  - The harness will run with ``vitest bench --run`` and read the JSON report, so your bench functions do not need to set iterations explicitly.

- The output must be a **complete TypeScript source file** containing only:
  1. ``import`` directives (including ``import { bench, describe } from 'vitest'``)
  2. module-scope helpers (optional, deterministic-seeded RNGs, fixture data)
  3. one or more ``bench('name', () => { ... })`` registrations (optionally inside ``describe(...)``)

Do NOT print anything yourself; the surrounding harness parses the Vitest JSON output.

Example workload to follow (please strictly follow this format of imports, module-scope helpers, and ``bench`` registration). The harness will invoke ``vitest bench --run`` on the resulting file.

```ts
import { bench, describe } from 'vitest';

class Lcg {
  private state: number;
  constructor(seed: number) { this.state = seed >>> 0; }
  next(): number {
    this.state = (Math.imul(this.state, 1664525) + 1013904223) >>> 0;
    return this.state;
  }
}

function makeData(n: number): number[] {
  const rng = new Lcg(42);
  const out: number[] = new Array(n);
  for (let i = 0; i < n; i++) out[i] = rng.next() % 1_000_000;
  return out;
}

const DATA = makeData(1 << 16);

describe('FormatIntegers', () => {
  bench('format-integers-65k', () => {
    let out = '';
    for (const x of DATA) {
      out += x.toString() + '\\n';
    }
    // Prevent dead-code elimination by referencing the result length.
    if (out.length < 0) throw new Error('unreachable');
  });
});
```
"""


CONTEXT_MSG_TS = """Here's a commit and its information that does some optimization in the {repo_name} repository that might be relevant to writing the test:
## Commit Diff:
```
{commit_diff}
```

## Pre-edit source files:
{pre_edit_code}
"""


def extract_code_block(text: Optional[str]) -> Optional[str]:
    """Extract the first fenced code block from ``text``.

    Returns the inner text (no trailing newline) or ``None`` if no fenced
    block is present. Language tag (``ts``/``typescript``/empty) is ignored.
    """
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
                return None
        except requests.RequestException as e:
            logger.warning(
                f"Request failed for {url}: {e} (attempt {attempt + 1}/{HTTP_MAX_RETRIES})"
            )
        if attempt < HTTP_MAX_RETRIES - 1:
            time.sleep(2 ** attempt)
    return None


def _resolve_workload_model() -> str:
    """Resolve the LLM model name with the fallback chain.

    Precedence:
      1. ``WORKLOAD_MODEL_TS`` env (TypeScript override)
      2. ``WORKLOAD_MODEL`` env (shared default)
      3. ``bedrock/converse/global.anthropic.claude-opus-4-7`` (constant)
    """
    return (
        os.environ.get("WORKLOAD_MODEL_TS")
        or os.environ.get("WORKLOAD_MODEL")
        or "bedrock/converse/global.anthropic.claude-opus-4-7"
    )


def _validation_mode() -> str:
    """Return the validation mode: 'off', 'cheap', or 'full'.

    Legacy truthy values (``1``/``true``/``yes``/``on``) map to ``cheap``
    so existing scripts that only flipped the flag still get a meaningful
    check.
    """
    val = os.environ.get(_VALIDATE_ENV_FLAG, "0").strip().lower()
    if val in ("cheap",):
        return "cheap"
    if val in ("full",):
        return "full"
    if val in ("1", "true", "yes", "on"):
        return "cheap"
    return "off"


def _validate_compile_in_container(
    workload_src: str, instance_id: str
) -> Tuple[bool, str]:
    """Best-effort in-container validation of a generated workload.

    Returns ``(ok, message)``. ``ok=True`` means the validation succeeded;
    ``ok=False`` returns the validator's stderr (truncated) which can be
    fed back to the LLM as a corrective message.

    Skipped (returns ``(True, "validation_skipped")``) if Docker is not
    available, the image is missing, or validation is disabled.
    """
    mode = _validation_mode()
    if mode == "off":
        return True, "validation_disabled"

    if shutil.which("docker") is None:
        logger.info(
            f"[{instance_id}] docker not on PATH; skipping ts workload validation"
        )
        return True, "docker_unavailable"

    image = os.environ.get(_VALIDATION_IMAGE_ENV, _VALIDATION_IMAGE_DEFAULT)

    tmpdir = tempfile.mkdtemp(prefix="sweff_ts_workload_")
    src_path = Path(tmpdir) / "workload.bench.ts"
    src_path.write_text(workload_src)
    try:
        if mode == "full":
            inner_cmd = (
                "cd /work && "
                "npx vitest bench --run workload.bench.ts 2>&1"
            )
        else:
            inner_cmd = (
                "cd /work && "
                "npx tsc --noEmit --target ES2022 --module ESNext "
                "--moduleResolution Bundler --strict workload.bench.ts 2>&1"
            )
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{tmpdir}:/work:ro",
            image,
            "bash",
            "-lc",
            inner_cmd,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_VALIDATION_TIMEOUT_S,
                check=False,
            )
        except FileNotFoundError:
            return True, "docker_unavailable"
        except subprocess.TimeoutExpired:
            return False, f"validation_timeout_after_{_VALIDATION_TIMEOUT_S}s"

        if proc.returncode == 0:
            return True, "ok"
        err = (proc.stdout or "") + "\n" + (proc.stderr or "")
        # The base image may not be built yet when stage_workload runs before
        # stage_eval. Treat 'image missing' as 'validation skipped' rather
        # than 'compile failure' so we don't burn LLM budget retrying with
        # phantom error messages.
        err_lower = err.lower()
        image_missing_markers = (
            "unable to find image",
            "pull access denied",
            "no such image",
            "manifest unknown",
            "repository does not exist",
        )
        if any(marker in err_lower for marker in image_missing_markers):
            logger.info(
                "[%s] ts validation image %r unavailable; skipping check",
                instance_id, image,
            )
            return True, "image_not_available_skipped"
        # Missing-module errors are inconclusive: the base validation image
        # lacks the repo's own sources and any env-installed packages — those
        # exist only in the per-instance eval image. Treat them as a skip so
        # a workload that would run in real eval is not rejected (and we
        # don't burn LLM retries on a phantom error).
        missing_module_markers = (
            "cannot find module",
            "cannot find name",
            "module not found",
            "no such file or directory",
        )
        if any(marker in err_lower for marker in missing_module_markers):
            logger.info(
                "[%s] workload validation inconclusive (missing module at "
                "base-image stage); deferring to eval", instance_id,
            )
            return True, "validation_inconclusive_missing_module"
        return False, err.strip()[-4000:]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def worker_function(
    datum: SWEfficiencyInstanceTs,
    run_id: str,
    cost_tracker: Optional[CostTracker] = None,
):
    output_file = (
        WORKLOAD_GENERATION_DIR_TS / run_id / f"{datum['instance_id']}.bench.ts"
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if output_file.exists() and output_file.stat().st_size > 0:
        content_check = output_file.read_text(errors="replace")[:100]
        if content_check.startswith("// WARNING: No code block extracted"):
            logger.info(
                f"[{datum['instance_id']}] Found poisoned ts workload, regenerating"
            )
        else:
            logger.info(
                f"[{datum['instance_id']}] Already generated, skipping (resume)"
            )
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
                "language": "ts",
            }

    patch = datum["patch"]
    diff_pattern = r"diff --git a/.* b/(.*)"
    directives = re.findall(diff_pattern, patch)

    owner, repo = datum["repo"].split("/")
    commit_hash = datum["base_commit"]

    file_contents = []
    for file_path in directives:
        url = (
            f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_hash}/{file_path}"
        )
        content = _fetch_file_with_retry(url)
        if content is not None:
            file_contents.append(f"File: {file_path}")
            file_contents.append(f"```\n{content}\n```\n")
        else:
            logger.warning(f"[{datum['instance_id']}] Could not fetch {file_path}")

    commit_diff = patch.strip()
    all_preedit_file_contents = "\n".join(file_contents)

    model_name = _resolve_workload_model()
    api_base = os.environ.get("AWS_BEDROCK_RUNTIME_ENDPOINT")

    response = None
    last_error: Optional[BaseException] = None
    last_compile_error: Optional[str] = None
    code_block_content: Optional[str] = None
    final_result_text: Optional[str] = None
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost_usd = 0.0

    base_messages = [
        {"role": "system", "content": SYSTEM_MSG_TS},
        {
            "role": "user",
            "content": CONTEXT_MSG_TS.format(
                repo_name=repo,
                commit_diff=commit_diff,
                pre_edit_code=all_preedit_file_contents,
            ),
        },
        {
            "role": "user",
            "content": "Can you write a Vitest bench workload in the same style as the example?",
        },
    ]

    for attempt in range(MAX_LLM_RETRIES):
        get_default_bucket().acquire()
        messages = list(base_messages)
        if last_compile_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous workload failed validation. Validator output:\n"
                        f"```\n{last_compile_error}\n```\n"
                        "Please fix the issues and emit a corrected complete TypeScript "
                        "source file inside a ```ts fenced code block. Do not include any "
                        "prose outside the code block."
                    ),
                }
            )
        try:
            response = completion(
                model=model_name,
                messages=messages,
                api_base=api_base,
                metadata=helicone_metadata(
                    call_type="synthetic_ts",
                    model_id=model_name,
                    extra={"InstanceId": datum["instance_id"]},
                ),
            )
        except Exception as e:
            last_error = e
            backoff = LLM_BACKOFF_BASE ** attempt
            logger.warning(
                f"[{datum['instance_id']}] LLM error "
                f"(attempt {attempt + 1}/{MAX_LLM_RETRIES}): {e}. Retrying in {backoff}s..."
            )
            time.sleep(backoff)
            continue

        try:
            final_result_text = response.choices[0].message.content
        except (AttributeError, IndexError) as e:
            last_error = e
            time.sleep(LLM_BACKOFF_BASE ** attempt)
            continue

        code_block_content = extract_code_block(final_result_text)

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
        attempt_cost = safe_completion_cost(response)
        cost_usd += attempt_cost
        if cost_tracker is not None:
            cost_tracker.add(attempt_cost)  # raises CostLimitExceeded

        if code_block_content is None:
            logger.warning(
                f"[{datum['instance_id']}] No code block in ts LLM response "
                f"(attempt {attempt + 1}/{MAX_LLM_RETRIES})"
            )
            last_compile_error = (
                "Your previous reply did not contain a ```ts fenced code block."
            )
            continue

        ok, msg = _validate_compile_in_container(code_block_content, datum["instance_id"])
        if ok:
            last_compile_error = None
            break

        last_compile_error = msg
        logger.warning(
            f"[{datum['instance_id']}] ts workload failed validation "
            f"(attempt {attempt + 1}/{MAX_LLM_RETRIES}): {msg[:200]}..."
        )

    if response is None and last_error is not None:
        logger.error(
            f"[{datum['instance_id']}] ts workload generation failed after "
            f"{MAX_LLM_RETRIES} attempts. Last error: {last_error}"
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
            "language": "ts",
        }

    if last_compile_error and code_block_content is not None:
        write_to_dlq(
            "workload_uncompilable_ts.jsonl",
            {
                "instance_id": datum["instance_id"],
                "run_id": run_id,
                "repo": datum.get("repo"),
                "base_commit": datum.get("base_commit"),
                "stage": "workload_generation_ts",
                "error_type": "ValidationError",
                "error": last_compile_error[:4000],
            },
        )

    with open(output_file, "w") as f:
        if code_block_content:
            f.write(code_block_content)
        else:
            f.write(
                "// WARNING: No code block extracted from LLM response\n"
                "// Raw response saved below\n"
            )
            f.write(
                f"/*\n{final_result_text}\n*/" if final_result_text else "// Empty response\n"
            )

    return {
        "instance_id": datum["instance_id"],
        "run_id": run_id,
        "workload": code_block_content if code_block_content else final_result_text,
        "workload_generation_cost": {
            "model": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": round(cost_usd, 6),
        },
        "compile_validated": last_compile_error is None and code_block_content is not None,
        "language": "ts",
    }


def main(
    dataset_name: str,
    split: str,
    instance_ids: list,
    max_workers: int,
    run_id: str,
    no_resume: bool = False,
):
    setup_helicone()
    dataset = load_swefficiency_dataset(dataset_name, split)
    random.shuffle(dataset)

    WORKLOAD_GENERATION_DIR_TS.mkdir(parents=True, exist_ok=True)
    output_dir = WORKLOAD_GENERATION_DIR_TS / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    cost_tracker = CostTracker.for_run(run_id=run_id)
    if cost_tracker.cap_usd is not None:
        logger.info(
            "LLM cost cap: $%.2f (prior spend $%.4f)",
            cost_tracker.cap_usd,
            cost_tracker.total,
        )
    output_path = output_dir / "workload_generation_ts.json"

    if instance_ids:
        dataset = [d for d in dataset if d["instance_id"] in instance_ids]

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
            logger.info(
                f"Resume: skipping {before - len(dataset)} already-completed ts instances"
            )

    if not dataset:
        logger.info("All ts instances already completed. Nothing to do.")
        return

    logger.info(
        f"Processing {len(dataset)} ts instances with {max_workers} workers"
    )

    if len(dataset) > 100:
        est_cost_low = len(dataset) * 0.03
        est_cost_high = len(dataset) * 0.15
        logger.warning(
            f"Cost estimate for {len(dataset)} ts instances: "
            f"${est_cost_low:.0f}-${est_cost_high:.0f} (depends on model). "
            f"Set WORKLOAD_MODEL_TS env var to control model choice."
        )

    results = []
    failed = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(worker_function, datum, run_id, cost_tracker): datum["instance_id"]
            for datum in dataset
        }
        for future in tqdm(
            as_completed(futures), total=len(futures), desc="Generating ts workloads"
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
                results.append(
                    {
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
                        "language": "ts",
                    }
                )

    total_cost = sum(
        r.get("workload_generation_cost", {}).get("cost_usd", 0.0) for r in results
    )
    total_tokens = sum(
        r.get("workload_generation_cost", {}).get("total_tokens", 0) for r in results
    )
    resumed_count = sum(1 for r in results if r.get("resumed"))

    logger.info(
        f"TypeScript workload generation complete: {len(results)} instances "
        f"({resumed_count} resumed, {len(failed)} failed), "
        f"{total_tokens:,} tokens, ${total_cost:.4f} USD"
    )
    if failed:
        logger.warning(f"Failed ts instances: {failed}")

    mode = "a" if output_path.exists() and not no_resume else "w"
    with open(output_path, mode) as f:
        for result in results:
            if not result.get("resumed"):
                f.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--dataset_name",
        default="swefficiency/swefficiency-ts",
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
