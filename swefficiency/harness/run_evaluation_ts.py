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

"""TypeScript analog of ``run_evaluation.py``.

Per-instance flow inside a fresh container built from the ts instance image:
    1. copy ``patch.diff``, ``workload.bench.ts``, ``perf.sh``, ``parse_vitest_bench.py``
    2. run ``perf.sh`` (pre-edit) -> Mean/StdDev sentinels
    3. ``git apply`` the patch (with ``patch -p1`` fallback)
    4. write + run ``eval.sh`` -> Vitest JSON+JUnit at /tmp/vitest_results.*
    5. run ``perf.sh`` (post-edit)
    6. grade via :func:`get_eval_report_ts` -> ``report.json``
"""

from __future__ import annotations
import json
import logging
import os
import resource
import sys
import traceback
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import docker
from tqdm import tqdm

from swefficiency.harness.constants import (
    APPLY_PATCH_FAIL,
    APPLY_PATCH_PASS,
    INSTANCE_IMAGE_BUILD_DIR,
    KEY_INSTANCE_ID,
)
from swefficiency.harness.constants_ts import RUN_EVAL_LOG_DIR_TS
from swefficiency.harness.docker_build import (
    BuildImageError,
    build_container,
    close_logger,
    setup_logger,
)
from swefficiency.harness.docker_utils import (
    cleanup_container,
    copy_to_container,
    exec_run_with_timeout,
    list_images,
    remove_image,
    should_remove,
)
from swefficiency.harness.grading_ts import get_eval_report_ts
from swefficiency.harness.log_parsers_ts import parse_perf_log_ts
from swefficiency.harness.run_evaluation import get_docker_client
from swefficiency.harness.test_spec_ts import (
    WORKLOAD_SRC_PATH,
    TestSpecTs,
    make_test_spec_ts,
)
from swefficiency.harness.utils import load_swefficiency_dataset

logger = logging.getLogger(__name__)


class EvaluationErrorTs(Exception):
    def __init__(self, instance_id, message, log_obj):
        super().__init__(message)
        self.super_str = super().__str__()
        self.instance_id = instance_id
        self.log_file = log_obj.log_file
        self.logger = log_obj

    def __str__(self):
        return (
            f"Evaluation error for {self.instance_id}: {self.super_str}\n"
            f"Check ({self.log_file}) for more information."
        )


def _resolve_parse_vitest_bench_path() -> Path:
    """Locate the ``parse_vitest_bench.py`` helper bundled with the repo.

    Tries, in order: the SWEFF_PARSE_VITEST_BENCH_PATH override, the
    editable-install repo layout (parents[2]/scripts), and the current
    working directory — so it resolves under editable installs, non-editable
    site-packages installs, and direct script runs.
    """
    candidates: list[Path] = []
    override = os.environ.get("SWEFF_PARSE_VITEST_BENCH_PATH")
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "scripts" / "parse_vitest_bench.py")
    candidates.append(Path.cwd() / "scripts" / "parse_vitest_bench.py")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "scripts/parse_vitest_bench.py not found (looked in: "
        + ", ".join(str(c) for c in candidates)
        + ") — required for ts perf parsing; set SWEFF_PARSE_VITEST_BENCH_PATH"
    )


# Ts eval logs live under a ts-specific dir so they never collide with the
# Python pipeline AND so run_pipeline_ts.sh's EVAL_DIR (logs/run_evaluation_ts)
# matches where we actually write. The shared RUN_EVALUATION_LOG_DIR is
# logs/run_evaluation, which the ts pipeline driver does not look in.
RUN_EVALUATION_LOG_DIR_TS = Path(RUN_EVAL_LOG_DIR_TS)


def run_instance_ts(
    test_spec: TestSpecTs,
    pred: dict,
    rm_image: bool,
    force_rebuild: bool,
    client: docker.DockerClient,
    run_id: str,
    timeout: int | None = None,
):
    """TypeScript analog of ``run_instance``."""
    instance_id = test_spec.instance_id
    model_name_or_path = pred.get("model_name_or_path", "None").replace("/", "__")
    log_dir = RUN_EVALUATION_LOG_DIR_TS / run_id / model_name_or_path / instance_id
    log_dir.mkdir(parents=True, exist_ok=True)

    build_dir = INSTANCE_IMAGE_BUILD_DIR / test_spec.instance_image_key.replace(":", "__")
    image_build_link = log_dir / "image_build_dir"
    if not image_build_link.exists():
        try:
            image_build_link.symlink_to(build_dir.absolute(), target_is_directory=True)
        except (OSError, FileExistsError) as _symlink_err:
            print(
                f"warning: failed to create symlink {image_build_link} -> {build_dir}: {_symlink_err}",
                file=sys.stderr,
            )
    log_file = log_dir / "run_instance.log"

    report_path = log_dir / "report.json"
    if report_path.exists():
        return instance_id, json.loads(report_path.read_text())

    log_obj = setup_logger(instance_id, log_file)
    container = None
    parse_vitest_bench_src = _resolve_parse_vitest_bench_path()

    try:
        container = build_container(
            test_spec, client, run_id, log_obj, rm_image, force_rebuild
        )
        container.start()
        log_obj.info(f"ts container for {instance_id} started: {container.id}")

        patch_file = Path(log_dir / "patch.diff")
        patch_file.write_text(pred["model_patch"] or "")
        # patch.diff is intentionally NOT copied to the container yet. The
        # pre-edit perf run below must measure the unpatched base. We copy the
        # patch in only after pre-perf completes; until then `_apply_patch_block`
        # sees no /tmp/patch.diff and falls through the `[ -s ... ]` test.

        if not test_spec.workload:
            raise EvaluationErrorTs(
                instance_id,
                "Instance has no workload — cannot run ts performance eval",
                log_obj,
            )
        workload_file = Path(log_dir / "workload.bench.ts")
        workload_file.write_text(test_spec.workload)
        copy_to_container(container, workload_file, Path(WORKLOAD_SRC_PATH))

        copy_to_container(container, parse_vitest_bench_src, Path("/tmp/parse_vitest_bench.py"))

        perf_workload_file = Path(log_dir / "perf.sh")
        perf_workload_file.write_text(test_spec.performance_script)
        copy_to_container(container, perf_workload_file, Path("/perf.sh"))

        pre_perf_out, timed_out, pre_perf_runtime = exec_run_with_timeout(
            container, "/bin/bash /perf.sh", timeout
        )
        pre_perf_path = log_dir / "perf_output_preedit.txt"
        log_obj.info(f"Pre-edit perf runtime: {pre_perf_runtime:_.2f} seconds")
        with open(pre_perf_path, "w") as f:
            f.write(pre_perf_out)
            if timed_out:
                f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
                raise EvaluationErrorTs(
                    instance_id,
                    f"Pre-edit perf timed out after {timeout} seconds.",
                    log_obj,
                )
        preedit_mean, preedit_sd = parse_perf_log_ts(pre_perf_out)

        # Now stage the patch into the container. eval.sh and the post-edit
        # perf run both reset to base_commit and apply via _apply_patch_block,
        # so they will see this file.
        copy_to_container(container, patch_file, Path("/tmp/patch.diff"))

        val = container.exec_run(
            "git apply --allow-empty -v /tmp/patch.diff",
            workdir="/testbed",
            user="root",
        )
        if val.exit_code != 0:
            log_obj.info("git apply failed; trying patch -p1 ...")
            val = container.exec_run(
                "patch --batch --fuzz=5 -p1 -i /tmp/patch.diff",
                workdir="/testbed",
                user="root",
            )
            if val.exit_code != 0:
                log_obj.info(f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}")
                raise EvaluationErrorTs(
                    instance_id,
                    f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}",
                    log_obj,
                )
            else:
                log_obj.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")
        else:
            log_obj.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")

        eval_file = Path(log_dir / "eval.sh")
        eval_file.write_text(test_spec.eval_script)
        copy_to_container(container, eval_file, Path("/eval.sh"))

        test_output, timed_out, total_runtime = exec_run_with_timeout(
            container, "/bin/bash /eval.sh", timeout
        )
        test_output_path = log_dir / "test_output.txt"
        log_obj.info(f"Test runtime: {total_runtime:_.2f} seconds")
        with open(test_output_path, "w") as f:
            f.write(test_output)
            if timed_out:
                f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
                raise EvaluationErrorTs(
                    instance_id,
                    f"Test timed out after {timeout} seconds.",
                    log_obj,
                )

        post_perf_out, timed_out, post_perf_runtime = exec_run_with_timeout(
            container, "/bin/bash /perf.sh", timeout
        )
        post_perf_path = log_dir / "perf_output_postedit.txt"
        log_obj.info(f"Post-edit perf runtime: {post_perf_runtime:_.2f} seconds")
        with open(post_perf_path, "w") as f:
            f.write(post_perf_out)
            if timed_out:
                f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
                raise EvaluationErrorTs(
                    instance_id,
                    f"Post-edit perf timed out after {timeout} seconds.",
                    log_obj,
                )
        postedit_mean, postedit_sd = parse_perf_log_ts(post_perf_out)

        improvement = (
            (preedit_mean - postedit_mean) / preedit_mean if preedit_mean else 0.0
        )
        perf_report = {
            "improvement": improvement,
            "preedit_runtime_mean": preedit_mean,
            "preedit_runtime_sd": preedit_sd,
            "post_edit_runtime_mean": postedit_mean,
            "post_edit_runtime_sd": postedit_sd,
        }

        # Write perf_summary.txt so scripts/significance_filter.py (shared with
        # the Python pipeline) can find the Before/After Mean/SD it expects.
        # Without this file, every ts instance is silently dropped by the
        # significance filter as 'no perf data'.
        perf_summary_path = log_dir / "perf_summary.txt"
        perf_summary_path.write_text(
            f"Before Mean: {preedit_mean}\n"
            f"Before SD: {preedit_sd}\n"
            f"After Mean: {postedit_mean}\n"
            f"After SD: {postedit_sd}\n"
        )

        log_obj.info(f"Grading ts answer for {instance_id}...")
        report = get_eval_report_ts(
            test_spec=test_spec,
            prediction=pred,
            log_path=str(test_output_path),
            include_tests_status=True,
            repo=test_spec.repo,
        )
        log_obj.info(
            f"Result for {instance_id}: resolved={report[instance_id]['resolved']}"
        )

        report = {**report, **perf_report}
        with open(report_path, "w") as f:
            f.write(json.dumps(report, indent=4))
        return instance_id, report

    except EvaluationErrorTs as e:
        log_obj.info(traceback.format_exc())
        print(e)
    except BuildImageError as e:
        log_obj.info(traceback.format_exc())
        print(e)
    except Exception as e:
        log_obj.error(
            f"Error in ts eval for {instance_id}: {e}\n{traceback.format_exc()}"
        )
    finally:
        cleanup_container(client, container, log_obj)
        if rm_image:
            remove_image(client, test_spec.instance_image_key, log_obj)
        close_logger(log_obj)
    return None


def run_instances_ts(
    predictions: dict,
    instances: list,
    cache_level: str,
    clean: bool,
    force_rebuild: bool,
    max_workers: int,
    run_id: str,
    timeout: int,
):
    """Run all ts instances in parallel."""
    client = get_docker_client()
    test_specs = [make_test_spec_ts(inst) for inst in instances]

    instance_image_ids = {ts.instance_image_key for ts in test_specs}
    existing_images = {
        tag
        for img in client.images.list(all=True)
        for tag in img.tags
        if tag in instance_image_ids
    }
    if not force_rebuild and existing_images:
        print(f"Found {len(existing_images)} existing ts instance images. Reusing.")

    print(f"Running {len(test_specs)} ts instances...")
    with tqdm(total=len(test_specs), smoothing=0) as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futs = {
                exe.submit(
                    run_instance_ts,
                    ts,
                    predictions[ts.instance_id],
                    should_remove(ts.instance_image_key, cache_level, clean, existing_images),
                    force_rebuild,
                    client,
                    run_id,
                    timeout,
                ): ts.instance_id
                for ts in test_specs
                if ts.instance_id in predictions
            }
            for fut in as_completed(futs):
                pbar.update(1)
                try:
                    fut.result()
                except Exception:
                    print(
                        f"[run_instances_ts] worker raised:\n{traceback.format_exc()}",
                        file=sys.stderr,
                    )
                    continue
    print("All ts instances run.")


def main():
    parser = ArgumentParser(description="Run ts evaluation harness.")
    parser.add_argument("--dataset-name", default="swefficiency/swefficiency-ts")
    parser.add_argument("--split", default="test")
    parser.add_argument("--instance-ids", nargs="+", default=None)
    parser.add_argument("--predictions-path", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--cache-level", default="env", choices=["none", "base", "env", "instance"])
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    try:
        _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        _target = min(_hard, max(_soft, 4096)) if _hard > 0 else max(_soft, 4096)
        if _target > _soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (_target, _hard))
    except (ValueError, OSError) as _rlimit_err:
        print(
            f"warning: could not raise RLIMIT_NOFILE: {_rlimit_err}",
            file=sys.stderr,
        )

    if args.predictions_path.suffix == ".jsonl":
        predictions = {}
        for line in args.predictions_path.read_text().splitlines():
            if not line.strip():
                continue
            pred = json.loads(line)
            # make_test_spec_ts lowercases instance_id for Docker-tag safety;
            # key predictions the same way so lookups never silently miss.
            predictions[pred[KEY_INSTANCE_ID].lower()] = pred
    else:
        predictions = {
            k.lower(): v
            for k, v in json.loads(args.predictions_path.read_text()).items()
        }

    dataset = load_swefficiency_dataset(args.dataset_name, args.split)
    if args.instance_ids:
        wanted = {i.lower() for i in args.instance_ids}
        dataset = [i for i in dataset if i[KEY_INSTANCE_ID].lower() in wanted]

    run_instances_ts(
        predictions=predictions,
        instances=dataset,
        cache_level=args.cache_level,
        clean=args.clean,
        force_rebuild=args.force_rebuild,
        max_workers=args.max_workers,
        run_id=args.run_id,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
