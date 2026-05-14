#!/usr/bin/env python3
"""Build and validate Tier 3 instance Docker images for SWE-fficiency.

This script:
1. Loads the dataset JSONL
2. Validates all instances
3. Builds Tier 3 instance images (sweb.eval.{id}:latest) using existing build_instance_images()
4. Validates each built image has /testbed/.git/HEAD and correct base_commit
5. Tags each as ghcr.io/swefficiency/swefficiency-images:{id} (replacing broken Tier 2 images)
6. Optionally pushes multiarch to GHCR

Usage:
    python scripts/build_and_validate_images.py \
        --dataset artifacts/final/new-repos-inference-ready.jsonl \
        [--max-workers 4] [--force-rebuild] [--skip-push] [--validate-only]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "swefficiency"))

GHCR_PREFIX = "ghcr.io/swefficiency/swefficiency-images"


def load_dataset(jsonl_path: Path) -> list[dict]:
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def validate_image(instance_id: str, base_commit: str, image_name: str) -> list[str]:
    """Validate a single Docker image has correct /testbed/ contents."""
    errors: list[str] = []

    checks = [
        ("test -f /testbed/.git/HEAD", f"/testbed/.git/HEAD missing in {image_name}"),
        ("test -d /testbed/.git/objects", f"/testbed/.git/objects missing in {image_name}"),
        (
            f'bash -c "cd /testbed && git rev-parse HEAD"',
            f"Cannot run git rev-parse HEAD in {image_name}",
        ),
    ]

    for cmd, err_msg in checks:
        try:
            result = subprocess.run(
                ["docker", "run", "--rm", "--entrypoint", "bash", image_name, "-c", cmd],
                capture_output=True, text=True, timeout=60,
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
            ["docker", "run", "--rm", "--entrypoint", "bash", image_name,
             "-c", "cd /testbed && git rev-parse HEAD"],
            capture_output=True, text=True, timeout=60,
        )
        actual_commit = result.stdout.strip()
        if actual_commit != base_commit:
            errors.append(
                f"[{instance_id}] HEAD mismatch: expected {base_commit}, got {actual_commit}"
            )
        else:
            logger.info(f"[{instance_id}] HEAD matches base_commit: {actual_commit[:12]}")
    except Exception as e:
        errors.append(f"[{instance_id}] Error checking HEAD: {e}")

    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "bash", image_name,
             "-c", "ls /testbed/"],
            capture_output=True, text=True, timeout=60,
        )
        files = result.stdout.strip().split("\n")
        if len(files) < 3:
            errors.append(
                f"[{instance_id}] /testbed/ has too few files ({len(files)}): {files}"
            )
        else:
            logger.info(f"[{instance_id}] /testbed/ has {len(files)} top-level entries")
    except Exception as e:
        errors.append(f"[{instance_id}] Error listing /testbed/: {e}")

    return errors


def tag_for_ghcr(instance_id: str, eval_image: str) -> bool:
    """Tag sweb.eval.{id}:latest as ghcr.io/swefficiency/swefficiency-images:{id}."""
    ghcr_tag = f"{GHCR_PREFIX}:{instance_id}"
    try:
        result = subprocess.run(
            ["docker", "tag", eval_image, ghcr_tag],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.error(f"Failed to tag {eval_image} as {ghcr_tag}: {result.stderr}")
            return False
        logger.info(f"Tagged {eval_image} -> {ghcr_tag}")
        return True
    except Exception as e:
        logger.error(f"Error tagging {eval_image}: {e}")
        return False


def build_multiarch_instance(
    test_spec,
    ghcr_tag: str,
    build_dir: Path,
    push: bool = True,
) -> bool:
    """Build multiarch instance image and push to GHCR.

    IMPORTANT: For --push to work, the env image (FROM line) must already exist
    in the buildx builder cache. Run with --build-multiarch-full to build the
    entire base→env→instance chain.
    """
    from swefficiency.harness.docker_build import build_multiarch_image
    from swefficiency.harness.dockerfiles import get_dockerfile_instance_multiarch

    env_image_name = test_spec.env_image_key
    dockerfile = get_dockerfile_instance_multiarch(env_image_name)

    try:
        build_multiarch_image(
            image_name=ghcr_tag,
            setup_scripts={"setup_repo.sh": test_spec.install_repo_script},
            dockerfile=dockerfile,
            build_dir=build_dir,
            push=push,
        )
        logger.info(f"Multiarch {'pushed' if push else 'built'}: {ghcr_tag}")
        return True
    except Exception as e:
        logger.error(f"Multiarch build failed for {test_spec.instance_id}: {e}")
        return False


def build_multiarch_full_chain(
    dataset: list[dict],
    push: bool = True,
    registry: str = "",
) -> bool:
    """Build the full multiarch chain: base → env → instance, pushing to registry.

    Args:
        dataset: List of instance records from dataset JSONL.
        push: If True, --push to registry. If False, --load to local daemon (native only).
        registry: Registry prefix for push (e.g. "localhost:5555" or "ghcr.io/swefficiency").
                  If empty, uses GHCR_PREFIX for instance images and bare names for base/env.
    """
    from swefficiency.harness.docker_build import (
        build_multiarch_image,
        ensure_buildx_builder,
    )
    from swefficiency.harness.dockerfiles import (
        get_dockerfile_base_multiarch,
        get_dockerfile_env_multiarch,
        get_dockerfile_instance_multiarch,
    )
    from swefficiency.harness.test_spec import make_test_spec
    from swefficiency.harness.constants import (
        BASE_IMAGE_BUILD_DIR,
        ENV_IMAGE_BUILD_DIR,
        INSTANCE_IMAGE_BUILD_DIR,
    )

    def _reg(name: str) -> str:
        """Prefix image name with registry if set."""
        if registry:
            return f"{registry}/{name}"
        return name

    builder = ensure_buildx_builder()

    # Step 1: Base image
    base_name = _reg("sweb.base:latest")
    logger.info(f"Step 1/3: Building multiarch base image -> {base_name}")
    try:
        build_multiarch_image(
            image_name=base_name,
            setup_scripts={},
            dockerfile=get_dockerfile_base_multiarch(),
            build_dir=BASE_IMAGE_BUILD_DIR / "multiarch_base",
            push=push,
            builder=builder,
        )
    except Exception as e:
        logger.error(f"Base multiarch build failed: {e}")
        return False

    # Step 2: Env images
    logger.info("Step 2/3: Building multiarch env images")
    specs = [make_test_spec(rec) for rec in dataset]
    env_specs: dict = {}
    for spec in specs:
        if spec.env_image_key not in env_specs:
            env_specs[spec.env_image_key] = spec

    for env_name, spec in env_specs.items():
        reg_env_name = _reg(env_name)
        logger.info(f"  Building env: {reg_env_name}")
        # The Dockerfile FROM line references sweb.base:latest — which must match registry
        dockerfile_env = get_dockerfile_env_multiarch()
        if registry:
            # Rewrite FROM to point to registry base image
            dockerfile_env = dockerfile_env.replace(
                "FROM sweb.base:latest",
                f"FROM {_reg('sweb.base:latest')}",
            )
        try:
            build_multiarch_image(
                image_name=reg_env_name,
                setup_scripts={"setup_env.sh": spec.setup_env_script},
                dockerfile=dockerfile_env,
                build_dir=ENV_IMAGE_BUILD_DIR / f"multiarch_{env_name.replace(':', '__')}",
                push=push,
                builder=builder,
            )
        except Exception as e:
            logger.error(f"Env multiarch build failed for {env_name}: {e}")
            return False

    # Step 3: Instance images
    logger.info("Step 3/3: Building multiarch instance images")
    for i, (spec, rec) in enumerate(zip(specs, dataset), 1):
        iid = rec["instance_id"]
        if registry:
            instance_tag = f"{registry}/swefficiency-images:{iid}"
        else:
            instance_tag = f"{GHCR_PREFIX}:{iid}"
        logger.info(f"  [{i}/{len(dataset)}] Building instance: {instance_tag}")

        # Instance Dockerfile FROM line references env image — must match registry
        env_name = spec.env_image_key
        reg_env_name = _reg(env_name)
        dockerfile_inst = get_dockerfile_instance_multiarch(reg_env_name)

        try:
            build_multiarch_image(
                image_name=instance_tag,
                setup_scripts={"setup_repo.sh": spec.install_repo_script},
                dockerfile=dockerfile_inst,
                build_dir=INSTANCE_IMAGE_BUILD_DIR / f"multiarch_{iid}",
                push=push,
                builder=builder,
            )
        except Exception as e:
            logger.error(f"Instance multiarch build failed for {iid}: {e}")
            return False

    logger.info(f"Full multiarch chain complete: 1 base + {len(env_specs)} envs + {len(dataset)} instances")
    return True


def main():
    parser = argparse.ArgumentParser(description="Build and validate SWE-fficiency instance images")
    parser.add_argument("--dataset", required=True, type=Path, help="Path to dataset JSONL")
    parser.add_argument("--max-workers", type=int, default=4, help="Parallel build workers")
    parser.add_argument("--force-rebuild", action="store_true", help="Force rebuild even if images exist")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing images, don't build")
    parser.add_argument("--skip-tag", action="store_true", help="Skip GHCR tagging")
    parser.add_argument("--build-multiarch", action="store_true", help="Build multiarch (arm64+amd64) and push to registry")
    parser.add_argument("--registry", default="", help="Registry prefix for multiarch push (e.g. localhost:5555)")
    parser.add_argument("--instance-ids", nargs="*", help="Only build/validate specific instances")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    logger.info(f"Loaded {len(dataset)} instances from {args.dataset}")

    if args.instance_ids:
        dataset = [d for d in dataset if d["instance_id"] in args.instance_ids]
        logger.info(f"Filtered to {len(dataset)} instances: {[d['instance_id'] for d in dataset]}")

    if not dataset:
        logger.error("No instances to process")
        return 1

    if not args.validate_only:
        logger.info("=" * 60)
        logger.info("STAGE 1: Building Tier 3 instance images")
        logger.info("=" * 60)

        import docker
        from swefficiency.harness.docker_build import build_instance_images
        from swefficiency.harness.test_spec import make_test_spec

        client = docker.from_env()

        successful, failed = build_instance_images(
            client=client,
            dataset=dataset,
            force_rebuild=args.force_rebuild,
            max_workers=args.max_workers,
        )

        logger.info(f"Build results: {len(successful)} succeeded, {len(failed)} failed")
        if failed:
            for spec in failed:
                logger.error(f"FAILED: {spec.instance_id}")
            logger.error("Cannot proceed — some images failed to build")
            return 1

    logger.info("=" * 60)
    logger.info("STAGE 2: Validating all instance images")
    logger.info("=" * 60)

    all_errors: list[str] = []
    for rec in dataset:
        iid = rec["instance_id"]
        base_commit = rec["base_commit"]
        eval_image = f"sweb.eval.{iid}:latest"

        img_check = subprocess.run(
            ["docker", "image", "inspect", eval_image],
            capture_output=True, text=True,
        )
        if img_check.returncode != 0:
            all_errors.append(f"[{iid}] Image {eval_image} not found locally")
            continue

        errors = validate_image(iid, base_commit, eval_image)
        all_errors.extend(errors)

    if all_errors:
        logger.error(f"VALIDATION FAILED: {len(all_errors)} errors")
        for err in all_errors:
            logger.error(f"  {err}")
        return 1

    logger.info(f"VALIDATION PASSED: All {len(dataset)} images valid")

    if not args.skip_tag and not args.validate_only:
        logger.info("=" * 60)
        logger.info("STAGE 3: Tagging images for GHCR")
        logger.info("=" * 60)

        tag_failures = []
        for rec in dataset:
            iid = rec["instance_id"]
            eval_image = f"sweb.eval.{iid}:latest"
            if not tag_for_ghcr(iid, eval_image):
                tag_failures.append(iid)

        if tag_failures:
            logger.error(f"Tagging failed for {len(tag_failures)} images: {tag_failures}")
            return 1

        logger.info(f"All {len(dataset)} images tagged for GHCR")

    if args.build_multiarch:
        logger.info("=" * 60)
        logger.info("STAGE 4: Building full multiarch chain (base → env → instance) and pushing to GHCR")
        logger.info("=" * 60)

        if not build_multiarch_full_chain(dataset, push=True, registry=args.registry):
            logger.error("Multiarch build chain failed")
            return 1

        logger.info(f"All {len(dataset)} multiarch images pushed to {args.registry or 'GHCR'}")

    logger.info("=" * 60)
    logger.info("ALL DONE")
    logger.info(f"  Images built: {len(dataset)}")
    logger.info(f"  All validated: /testbed/.git/HEAD present, base_commit matches")
    if not args.skip_tag and not args.validate_only:
        logger.info(f"  All tagged: {GHCR_PREFIX}:{{instance_id}}")
    if args.build_multiarch:
        logger.info(f"  All multiarch: pushed arm64+amd64 to {args.registry or 'GHCR'}")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
