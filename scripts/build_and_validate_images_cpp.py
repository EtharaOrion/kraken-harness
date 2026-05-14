#!/usr/bin/env python3
"""Build and validate Tier 3 C++ instance Docker images for SWE-fficiency.

Sibling of ``build_and_validate_images.py`` that targets the C++ pipeline.
It expects instance images named ``sweb.eval.cpp.{id}:latest`` (produced
by :mod:`swefficiency.harness.docker_build_cpp`) and pushes them to a
separate GHCR repository so the Python images are untouched.

Stages:
1. Load dataset JSONL.
2. Build Tier-3 instance images (sweb.eval.cpp.{id}:latest) via
   :func:`build_instance_images_cpp`.
3. Validate each image has ``/testbed/.git/HEAD`` and matching
   ``base_commit``.
4. Tag each as ``ghcr.io/swefficiency/swefficiency-images-cpp:{id}``.
5. Optionally build the full multiarch chain
   (base -> env -> instance) and ``--push`` to GHCR.
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

GHCR_PREFIX_CPP = "ghcr.io/swefficiency/swefficiency-images-cpp"


def load_dataset(jsonl_path: Path) -> list:
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def validate_image(instance_id: str, base_commit: str, image_name: str) -> list:
    """Validate a single Docker image has correct ``/testbed/`` contents."""
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

    return errors


def tag_for_ghcr(instance_id: str, eval_image: str) -> bool:
    """Tag ``sweb.eval.cpp.{id}:latest`` as ``{GHCR_PREFIX_CPP}:{id}``."""
    ghcr_tag = f"{GHCR_PREFIX_CPP}:{instance_id}"
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


def build_multiarch_full_chain_cpp(
    dataset: list,
    push: bool = True,
    registry: str = "",
) -> bool:
    """Build the full C++ multiarch chain: base -> env -> instance.

    Args:
        dataset: instance records from dataset JSONL.
        push: when True ``--push`` to registry; when False ``--load``
            to local daemon (native arch only).
        registry: optional registry prefix for push (e.g.
            ``localhost:5555``). When empty, uses :data:`GHCR_PREFIX_CPP`
            for instance images and bare names for base/env.
    """
    from swefficiency.harness.docker_build import (
        build_multiarch_image,
        ensure_buildx_builder,
    )
    from swefficiency.harness.dockerfiles_cpp import (
        get_dockerfile_base_multiarch_cpp,
        get_dockerfile_env_multiarch_cpp,
        get_dockerfile_instance_multiarch_cpp,
    )
    from swefficiency.harness.test_spec_cpp import make_test_spec_cpp
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

    base_name = _reg("sweb.base.cpp:latest")
    logger.info(f"Step 1/3: Building multiarch cpp base image -> {base_name}")
    try:
        build_multiarch_image(
            image_name=base_name,
            setup_scripts={},
            dockerfile=get_dockerfile_base_multiarch_cpp(),
            build_dir=BASE_IMAGE_BUILD_DIR / "multiarch_base_cpp",
            push=push,
            builder=builder,
        )
    except Exception as e:
        logger.error(f"Base cpp multiarch build failed: {e}")
        return False

    logger.info("Step 2/3: Building multiarch cpp env images")
    specs = [make_test_spec_cpp(rec) for rec in dataset]
    env_specs: dict = {}
    for spec in specs:
        if spec.env_image_key not in env_specs:
            env_specs[spec.env_image_key] = spec

    for env_name, spec in env_specs.items():
        reg_env_name = _reg(env_name)
        logger.info(f"  Building cpp env: {reg_env_name}")
        dockerfile_env = get_dockerfile_env_multiarch_cpp()
        if registry:
            dockerfile_env = dockerfile_env.replace(
                "FROM sweb.base.cpp:latest",
                f"FROM {_reg('sweb.base.cpp:latest')}",
            )
        try:
            build_multiarch_image(
                image_name=reg_env_name,
                setup_scripts={"setup_env.sh": spec.setup_env_script},
                dockerfile=dockerfile_env,
                build_dir=ENV_IMAGE_BUILD_DIR
                / f"multiarch_cpp_{env_name.replace(':', '__')}",
                push=push,
                builder=builder,
            )
        except Exception as e:
            logger.error(f"Env cpp multiarch build failed for {env_name}: {e}")
            return False

    logger.info("Step 3/3: Building multiarch cpp instance images")
    for i, (spec, rec) in enumerate(zip(specs, dataset), 1):
        iid = rec["instance_id"]
        if registry:
            instance_tag = f"{registry}/swefficiency-images-cpp:{iid}"
        else:
            instance_tag = f"{GHCR_PREFIX_CPP}:{iid}"
        logger.info(
            f"  [{i}/{len(dataset)}] Building cpp instance: {instance_tag}"
        )

        env_name = spec.env_image_key
        reg_env_name = _reg(env_name)
        dockerfile_inst = get_dockerfile_instance_multiarch_cpp(reg_env_name)

        try:
            build_multiarch_image(
                image_name=instance_tag,
                setup_scripts={"setup_repo.sh": spec.install_repo_script},
                dockerfile=dockerfile_inst,
                build_dir=INSTANCE_IMAGE_BUILD_DIR / f"multiarch_cpp_{iid}",
                push=push,
                builder=builder,
            )
        except Exception as e:
            logger.error(f"Instance cpp multiarch build failed for {iid}: {e}")
            return False

    logger.info(
        f"Full cpp multiarch chain complete: 1 base + {len(env_specs)} envs "
        f"+ {len(dataset)} instances"
    )
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Build and validate SWE-fficiency C++ instance images"
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

    dataset = load_dataset(args.dataset)
    logger.info(f"Loaded {len(dataset)} cpp instances from {args.dataset}")

    if args.instance_ids:
        dataset = [d for d in dataset if d["instance_id"] in args.instance_ids]
        logger.info(
            f"Filtered to {len(dataset)} cpp instances: "
            f"{[d['instance_id'] for d in dataset]}"
        )

    if not dataset:
        logger.error("No cpp instances to process")
        return 1

    if not args.validate_only:
        logger.info("=" * 60)
        logger.info("STAGE 1: Building Tier 3 C++ instance images")
        logger.info("=" * 60)

        import docker

        from swefficiency.harness.docker_build_cpp import build_instance_images_cpp

        client = docker.from_env()

        successful, failed = build_instance_images_cpp(
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
            logger.error("Cannot proceed -- some cpp images failed to build")
            return 1

    logger.info("=" * 60)
    logger.info("STAGE 2: Validating all C++ instance images")
    logger.info("=" * 60)

    all_errors: list = []
    for rec in dataset:
        iid = rec["instance_id"].lower()
        base_commit = rec["base_commit"]
        eval_image = f"sweb.eval.cpp.{iid}:latest"

        img_check = subprocess.run(
            ["docker", "image", "inspect", eval_image],
            capture_output=True,
            text=True,
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

    logger.info(f"VALIDATION PASSED: All {len(dataset)} cpp images valid")

    if not args.skip_tag and not args.validate_only:
        logger.info("=" * 60)
        logger.info("STAGE 3: Tagging C++ images for GHCR")
        logger.info("=" * 60)

        tag_failures = []
        for rec in dataset:
            iid = rec["instance_id"].lower()
            eval_image = f"sweb.eval.cpp.{iid}:latest"
            if not tag_for_ghcr(iid, eval_image):
                tag_failures.append(iid)

        if tag_failures:
            logger.error(
                f"Tagging failed for {len(tag_failures)} images: {tag_failures}"
            )
            return 1

        logger.info(f"All {len(dataset)} cpp images tagged for GHCR")

    if args.build_multiarch:
        logger.info("=" * 60)
        logger.info(
            "STAGE 4: Building full multiarch cpp chain "
            "(base -> env -> instance) and pushing to GHCR"
        )
        logger.info("=" * 60)

        if not build_multiarch_full_chain_cpp(
            dataset, push=True, registry=args.registry
        ):
            logger.error("Multiarch cpp build chain failed")
            return 1

        logger.info(
            f"All {len(dataset)} multiarch cpp images pushed to "
            f"{args.registry or 'GHCR'}"
        )

    logger.info("=" * 60)
    logger.info("ALL DONE (cpp)")
    logger.info(f"  Images built: {len(dataset)}")
    logger.info(
        "  All validated: /testbed/.git/HEAD present, base_commit matches"
    )
    if not args.skip_tag and not args.validate_only:
        logger.info(f"  All tagged: {GHCR_PREFIX_CPP}:{{instance_id}}")
    if args.build_multiarch:
        logger.info(
            f"  All multiarch: pushed arm64+amd64 to {args.registry or 'GHCR'}"
        )
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
