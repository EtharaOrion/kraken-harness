#!/usr/bin/env python3
"""Build and validate Tier 3 TypeScript instance Docker images for SWE-fficiency.

Sibling of ``build_and_validate_images.py`` that targets the TypeScript
pipeline. It expects instance images named ``sweb.eval.ts.{id}:latest``
(produced by :mod:`swefficiency.harness.docker_build_ts`) and pushes them
to a separate GHCR repository so the Python images are untouched.

Stages:
1. Load dataset JSONL.
2. Build Tier-3 instance images (sweb.eval.ts.{id}:latest) via
   :func:`build_instance_images_ts`.
3. Validate each image has ``/testbed/.git/HEAD``, matching
   ``base_commit``, and a working Node/Vitest/TypeScript toolchain.
4. Validate the base image can run a synthetic Vitest workload (heredoc
   ``/tmp/workload.bench.ts``). When ``SWEFF_VALIDATE_TS_WORKLOAD=cheap``
   only ``tsc --noEmit`` is exercised; otherwise ``vitest bench --run``.
5. Tag each as ``ghcr.io/swefficiency/swefficiency-images-ts:{id}``.
6. Optionally build the full multiarch chain
   (base -> env -> instance) and ``--push`` to GHCR.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "swefficiency"))

GHCR_PREFIX_TS = "ghcr.io/swefficiency/swefficiency-images-ts"

BASE_IMAGE_TS = "sweb.base.ts:latest"


def load_dataset(jsonl_path: Path) -> list:
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def validate_image(instance_id: str, base_commit: str, image_name: str) -> list:
    """Validate a single Docker image has correct ``/testbed/`` contents
    and a working TypeScript toolchain."""
    errors: list = []

    checks = [
        ("test -f /testbed/.git/HEAD", f"/testbed/.git/HEAD missing in {image_name}"),
        ("test -d /testbed/.git/objects", f"/testbed/.git/objects missing in {image_name}"),
        (
            'bash -c "cd /testbed && git rev-parse HEAD"',
            f"Cannot run git rev-parse HEAD in {image_name}",
        ),
    ]

    for cmd, err_msg in checks:
        try:
            result = subprocess.run(
                ["docker", "run", "--rm", "--entrypoint", "bash", image_name, "-c", cmd],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                errors.append(f"[{instance_id}] {err_msg} (exit {result.returncode})")
        except subprocess.TimeoutExpired:
            errors.append(f"[{instance_id}] Timeout running: {cmd}")
        except Exception as e:
            errors.append(f"[{instance_id}] Error: {e}")

    if errors:
        return errors

    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "bash",
                image_name,
                "-c",
                "cd /testbed && git rev-parse HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        actual_commit = result.stdout.strip()
        if actual_commit != base_commit:
            errors.append(
                f"[{instance_id}] HEAD mismatch: expected {base_commit}, got {actual_commit}"
            )
        else:
            logger.info(
                f"[{instance_id}] HEAD matches base_commit: {actual_commit[:12]}"
            )
    except Exception as e:
        errors.append(f"[{instance_id}] Error checking HEAD: {e}")

    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "bash",
                image_name,
                "-c",
                "ls /testbed/",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        files = result.stdout.strip().split("\n")
        if len(files) < 3:
            errors.append(
                f"[{instance_id}] /testbed/ has too few files ({len(files)}): {files}"
            )
        else:
            logger.info(
                f"[{instance_id}] /testbed/ has {len(files)} top-level entries"
            )
    except Exception as e:
        errors.append(f"[{instance_id}] Error listing /testbed/: {e}")

    # Toolchain smoke check: confirms corepack + npm + tsc + vitest are
    # all reachable inside the image. TypeScript instances have no
    # native compiler step, so this stands in for the sibling pipeline's
    # native-toolchain probe.
    toolchain_cmd = (
        "corepack enable && npx tsc --version && npx vitest --version"
    )
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "bash",
                image_name,
                "-c",
                toolchain_cmd,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            errors.append(
                f"[{instance_id}] TypeScript toolchain smoke failed "
                f"(exit {result.returncode}): {result.stderr.strip()[:200]}"
            )
        else:
            logger.info(
                f"[{instance_id}] TypeScript toolchain OK "
                f"({result.stdout.strip().splitlines()[-2:]})"
            )
    except subprocess.TimeoutExpired:
        errors.append(f"[{instance_id}] Timeout running toolchain smoke")
    except Exception as e:
        errors.append(f"[{instance_id}] Error running toolchain smoke: {e}")

    return errors


def validate_workload_ts(base_image: str = BASE_IMAGE_TS) -> list:
    """Run a synthetic Vitest bench workload inside ``sweb.base.ts:latest``.

    The workload module is materialised via ``cat <<EOF`` heredoc to keep
    the validation hermetic (no host file mount). ``SWEFF_VALIDATE_TS_WORKLOAD``
    selects the dispatch:
      * ``cheap`` -> ``npx tsc --noEmit workload.bench.ts``
      * anything else (default ``full``) -> ``npx vitest bench --run --no-coverage workload.bench.ts``
    """
    mode = os.environ.get("SWEFF_VALIDATE_TS_WORKLOAD", "full").strip().lower()
    if mode == "cheap":
        validate_cmd = "npx --yes tsc --noEmit workload.bench.ts"
    else:
        validate_cmd = "npx vitest bench --run --no-coverage workload.bench.ts"

    # Heredoc the workload module verbatim. Quoted 'EOF' prevents shell
    # expansion of template-like fragments inside the TS source.
    script = (
        "set -euo pipefail; "
        "mkdir -p /tmp/workload && cd /tmp/workload && "
        "cat > workload.bench.ts <<'EOF'\n"
        "import { bench, describe } from 'vitest';\n"
        "\n"
        "describe('sweff-workload-smoke', () => {\n"
        "  bench('noop', () => {});\n"
        "});\n"
        "EOF\n"
        f"{validate_cmd}"
    )

    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "bash",
                base_image,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=900 if mode != "cheap" else 180,
        )
        if result.returncode != 0:
            return [
                f"[workload] Vitest workload validate ({mode}) failed in "
                f"{base_image} (exit {result.returncode}): "
                f"{result.stderr.strip()[:300]}"
            ]
        logger.info(
            f"[workload] Vitest workload validate ({mode}) passed in {base_image}"
        )
        return []
    except subprocess.TimeoutExpired:
        return [f"[workload] Timeout running workload validate ({mode})"]
    except Exception as e:
        return [f"[workload] Error running workload validate ({mode}): {e}"]


def tag_for_ghcr(instance_id: str, eval_image: str) -> bool:
    """Tag ``sweb.eval.ts.{id}:latest`` as ``{GHCR_PREFIX_TS}:{id}``."""
    ghcr_tag = f"{GHCR_PREFIX_TS}:{instance_id}"
    try:
        result = subprocess.run(
            ["docker", "tag", eval_image, ghcr_tag],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(
                f"Failed to tag {eval_image} as {ghcr_tag}: {result.stderr}"
            )
            return False
        logger.info(f"Tagged {eval_image} -> {ghcr_tag}")
        return True
    except Exception as e:
        logger.error(f"Error tagging {eval_image}: {e}")
        return False


def build_multiarch_full_chain_ts(
    dataset: list,
    push: bool = True,
    registry: str = "",
) -> bool:
    """Build the full TypeScript multiarch chain: base -> env -> instance.

    Args:
        dataset: instance records from dataset JSONL.
        push: when True ``--push`` to registry; when False ``--load``
            to local daemon (native arch only).
        registry: optional registry prefix for push (e.g.
            ``localhost:5555``). When empty, uses :data:`GHCR_PREFIX_TS`
            for instance images and bare names for base/env.
    """
    from swefficiency.harness.docker_build import (
        build_multiarch_image,
        ensure_buildx_builder,
    )
    from swefficiency.harness.dockerfiles_ts import (
        get_dockerfile_base_multiarch_ts,
        get_dockerfile_env_multiarch_ts,
        get_dockerfile_instance_multiarch_ts,
    )
    from swefficiency.harness.test_spec_ts import make_test_spec_ts
    from swefficiency.harness.constants import (
        BASE_IMAGE_BUILD_DIR,
        ENV_IMAGE_BUILD_DIR,
        INSTANCE_IMAGE_BUILD_DIR,
    )

    def _reg(name: str) -> str:
        if registry:
            return f"{registry}/{name}"
        return name

    builder = ensure_buildx_builder()

    base_name = _reg("sweb.base.ts:latest")
    logger.info(f"Step 1/3: Building multiarch ts base image -> {base_name}")
    try:
        build_multiarch_image(
            image_name=base_name,
            setup_scripts={},
            dockerfile=get_dockerfile_base_multiarch_ts(),
            build_dir=BASE_IMAGE_BUILD_DIR / "multiarch_base_ts",
            push=push,
            builder=builder,
        )
    except Exception as e:
        logger.error(f"Base ts multiarch build failed: {e}")
        return False

    logger.info("Step 2/3: Building multiarch ts env images")
    specs = [make_test_spec_ts(rec) for rec in dataset]
    env_specs: dict = {}
    for spec in specs:
        if spec.env_image_key not in env_specs:
            env_specs[spec.env_image_key] = spec

    for env_name, spec in env_specs.items():
        reg_env_name = _reg(env_name)
        logger.info(f"  Building ts env: {reg_env_name}")
        dockerfile_env = get_dockerfile_env_multiarch_ts()
        if registry:
            dockerfile_env = dockerfile_env.replace(
                "FROM sweb.base.ts:latest",
                f"FROM {_reg('sweb.base.ts:latest')}",
            )
        try:
            build_multiarch_image(
                image_name=reg_env_name,
                setup_scripts={"setup_env.sh": spec.setup_env_script},
                dockerfile=dockerfile_env,
                build_dir=ENV_IMAGE_BUILD_DIR
                / f"multiarch_ts_{env_name.replace(':', '__')}",
                push=push,
                builder=builder,
            )
        except Exception as e:
            logger.error(f"Env ts multiarch build failed for {env_name}: {e}")
            return False

    logger.info("Step 3/3: Building multiarch ts instance images")
    for i, (spec, rec) in enumerate(zip(specs, dataset), 1):
        iid = rec["instance_id"]
        if registry:
            instance_tag = f"{registry}/swefficiency-images-ts:{iid}"
        else:
            instance_tag = f"{GHCR_PREFIX_TS}:{iid}"
        logger.info(
            f"  [{i}/{len(dataset)}] Building ts instance: {instance_tag}"
        )

        env_name = spec.env_image_key
        reg_env_name = _reg(env_name)
        dockerfile_inst = get_dockerfile_instance_multiarch_ts(reg_env_name)

        try:
            build_multiarch_image(
                image_name=instance_tag,
                setup_scripts={"setup_repo.sh": spec.install_repo_script},
                dockerfile=dockerfile_inst,
                build_dir=INSTANCE_IMAGE_BUILD_DIR / f"multiarch_ts_{iid}",
                push=push,
                builder=builder,
            )
        except Exception as e:
            logger.error(f"Instance ts multiarch build failed for {iid}: {e}")
            return False

    logger.info(
        f"Full ts multiarch chain complete: 1 base + {len(env_specs)} envs "
        f"+ {len(dataset)} instances"
    )
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Build and validate SWE-fficiency TypeScript instance images"
    )
    parser.add_argument("--dataset", required=True, type=Path, help="Path to dataset JSONL")
    parser.add_argument("--max-workers", type=int, default=4, help="Parallel build workers")
    parser.add_argument(
        "--force-rebuild", action="store_true", help="Force rebuild even if images exist"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate existing images, don't build",
    )
    parser.add_argument(
        "--skip-tag", action="store_true", help="Skip GHCR tagging"
    )
    parser.add_argument(
        "--skip-workload-validate",
        action="store_true",
        help="Skip the synthetic Vitest workload validation on sweb.base.ts:latest",
    )
    parser.add_argument(
        "--build-multiarch",
        action="store_true",
        help="Build multiarch (arm64+amd64) and push to registry",
    )
    parser.add_argument(
        "--registry",
        default="",
        help="Registry prefix for multiarch push (e.g. localhost:5555)",
    )
    parser.add_argument(
        "--instance-ids",
        nargs="*",
        help="Only build/validate specific instances",
    )
    args = parser.parse_args()

    if args.build_multiarch and not args.registry:
        parser.error(
            "--build-multiarch requires --registry: pushing an unqualified "
            "image name (sweb.base.ts:latest) targets docker.io/library and "
            "will fail with 401/403"
        )

    dataset = load_dataset(args.dataset)
    logger.info(f"Loaded {len(dataset)} ts instances from {args.dataset}")

    if args.instance_ids:
        dataset = [d for d in dataset if d["instance_id"] in args.instance_ids]
        logger.info(
            f"Filtered to {len(dataset)} ts instances: "
            f"{[d['instance_id'] for d in dataset]}"
        )

    if not dataset:
        logger.error("No ts instances to process")
        return 1

    if not args.validate_only:
        logger.info("=" * 60)
        logger.info("STAGE 1: Building Tier 3 TypeScript instance images")
        logger.info("=" * 60)

        import docker

        from swefficiency.harness.docker_build_ts import build_instance_images_ts

        client = docker.from_env()

        successful, failed = build_instance_images_ts(
            client=client,
            dataset=dataset,
            force_rebuild=args.force_rebuild,
            max_workers=args.max_workers,
        )

        logger.info(
            f"Build results: {len(successful)} succeeded, {len(failed)} failed"
        )
        if failed:
            for err in failed:
                logger.error(f"FAILED: {getattr(err, 'image_name', err)}")
            logger.error("Cannot proceed -- some ts images failed to build")
            return 1

    if not args.skip_workload_validate:
        logger.info("=" * 60)
        logger.info("STAGE 2: Validating Vitest workload on sweb.base.ts:latest")
        logger.info("=" * 60)

        workload_errors = validate_workload_ts(BASE_IMAGE_TS)
        if workload_errors:
            for err in workload_errors:
                logger.error(f"  {err}")
            logger.error("Workload validation FAILED on ts base image")
            return 1
        logger.info("Workload validation PASSED on ts base image")

    logger.info("=" * 60)
    logger.info("STAGE 3: Validating all TypeScript instance images")
    logger.info("=" * 60)

    def _validate_one(rec: dict) -> list:
        iid = rec["instance_id"].lower()
        base_commit = rec["base_commit"]
        eval_image = f"sweb.eval.ts.{iid}:latest"
        img_check = subprocess.run(
            ["docker", "image", "inspect", eval_image],
            capture_output=True,
            text=True,
        )
        if img_check.returncode != 0:
            return [f"[{iid}] Image {eval_image} not found locally"]
        return validate_image(iid, base_commit, eval_image)

    # Validation is N independent docker invocations; run them in parallel.
    # The build step already uses max_workers — the validate loop used to be
    # serial (~3s/instance docker startup x 10k instances = hours).
    all_errors: list = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as _val_exe:
        for errs in _val_exe.map(_validate_one, dataset):
            all_errors.extend(errs)

    if all_errors:
        logger.error(f"VALIDATION FAILED: {len(all_errors)} errors")
        for err in all_errors:
            logger.error(f"  {err}")
        return 1

    logger.info(f"VALIDATION PASSED: All {len(dataset)} ts images valid")

    if not args.skip_tag and not args.validate_only:
        logger.info("=" * 60)
        logger.info("STAGE 4: Tagging TypeScript images for GHCR")
        logger.info("=" * 60)

        tag_failures = []
        for rec in dataset:
            iid = rec["instance_id"].lower()
            eval_image = f"sweb.eval.ts.{iid}:latest"
            if not tag_for_ghcr(iid, eval_image):
                tag_failures.append(iid)

        if tag_failures:
            logger.error(
                f"Tagging failed for {len(tag_failures)} images: {tag_failures}"
            )
            return 1

        logger.info(f"All {len(dataset)} ts images tagged for GHCR")

    if args.build_multiarch:
        logger.info("=" * 60)
        logger.info(
            "STAGE 5: Building full multiarch ts chain "
            "(base -> env -> instance) and pushing to GHCR"
        )
        logger.info("=" * 60)

        if not build_multiarch_full_chain_ts(
            dataset, push=True, registry=args.registry
        ):
            logger.error("Multiarch ts build chain failed")
            return 1

        logger.info(
            f"All {len(dataset)} multiarch ts images pushed to "
            f"{args.registry or 'GHCR'}"
        )

    logger.info("=" * 60)
    logger.info("ALL DONE (ts)")
    logger.info(f"  Images built: {len(dataset)}")
    logger.info(
        "  All validated: /testbed/.git/HEAD present, base_commit matches, "
        "TypeScript toolchain OK"
    )
    if not args.skip_tag and not args.validate_only:
        logger.info(f"  All tagged: {GHCR_PREFIX_TS}:{{instance_id}}")
    if args.build_multiarch:
        logger.info(
            f"  All multiarch: pushed arm64+amd64 to {args.registry or 'GHCR'}"
        )
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
