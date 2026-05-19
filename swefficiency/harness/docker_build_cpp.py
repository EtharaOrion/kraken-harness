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

"""C++ Docker build orchestration.

Mirrors ``docker_build.py``'s base/env/instance tier model but routes
``build_image`` and multiarch helpers from ``docker_build`` (reuse — those are
language-agnostic Docker SDK wrappers). All Python-specific dockerfile
generators are swapped for their ``_cpp`` analogs and ECR pull-first uses the
``swefficiency-images-cpp`` repository.
"""

from __future__ import annotations

import logging
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Optional

import docker
import docker.errors

from swefficiency.harness.constants import (
    BASE_IMAGE_BUILD_DIR,
    ENV_IMAGE_BUILD_DIR,
    INSTANCE_IMAGE_BUILD_DIR,
)
from swefficiency.harness.constants_cpp import SWEfficiencyInstanceCpp
from swefficiency.harness.docker_build import (
    BuildImageError,
    build_image,
    build_multiarch_image,
    push_multiarch_to_ecr,
    try_pull_from_ecr,
)
from swefficiency.harness.dockerfiles_cpp import (
    get_dockerfile_base_multiarch_cpp,
    get_dockerfile_env_multiarch_cpp,
    get_dockerfile_instance_multiarch_cpp,
)
from swefficiency.harness.test_spec_cpp import TestSpecCpp, make_test_spec_cpp

logger = logging.getLogger(__name__)

ECR_REPO_CPP = "swefficiency-images-cpp"


def _ecr_registry() -> str:
    return os.environ.get("ECR_REGISTRY", "")


def _pull_first_enabled() -> bool:
    return os.environ.get("SWEFF_ECR_PULL_FIRST", "1").lower() not in ("0", "false", "no")


def build_base_images_cpp(
    client: docker.DockerClient,
    force_rebuild: bool = False,
    multiarch: bool = False,
    push_to_ecr: bool = False,
) -> str:
    """Build (or pull) the C++ base image.

    Returns the image tag that downstream env images should ``FROM``.
    """
    image_name = "sweb.base.cpp:latest"
    if not force_rebuild:
        try:
            client.images.get(image_name)
            logger.info("Base cpp image %s already present locally", image_name)
            return image_name
        except docker.errors.ImageNotFound:
            pass
        if _pull_first_enabled() and _ecr_registry():
            if try_pull_from_ecr(client, image_name, ecr_repo=ECR_REPO_CPP):
                logger.info("Pulled base cpp image from ECR")
                return image_name

    build_dir = BASE_IMAGE_BUILD_DIR / image_name.replace(":", "__")
    build_dir.mkdir(parents=True, exist_ok=True)
    if multiarch:
        dockerfile = get_dockerfile_base_multiarch_cpp()
        build_multiarch_image(
            image_name=image_name,
            setup_scripts=[],
            dockerfile=dockerfile,
            platforms=["linux/amd64"],
            client=client,
            build_dir=build_dir,
        )
        if push_to_ecr and _ecr_registry():
            push_multiarch_to_ecr(image_name, ecr_repo=ECR_REPO_CPP)
    else:
        from swefficiency.harness.dockerfiles_cpp import get_dockerfile_base_cpp

        dockerfile = get_dockerfile_base_cpp("linux/amd64")
        build_image(
            image_name=image_name,
            setup_scripts={},
            dockerfile=dockerfile,
            platform="linux/amd64",
            client=client,
            build_dir=build_dir,
        )
    return image_name


def _build_one_env(
    client: docker.DockerClient,
    test_spec: TestSpecCpp,
    force_rebuild: bool,
    multiarch: bool,
    push_to_ecr: bool,
) -> Optional[BuildImageError]:
    env_image = test_spec.env_image_key
    if not force_rebuild:
        try:
            client.images.get(env_image)
            return None
        except docker.errors.ImageNotFound:
            pass
        if _pull_first_enabled() and _ecr_registry():
            if try_pull_from_ecr(client, env_image, ecr_repo=ECR_REPO_CPP):
                return None

    try:
        setup_scripts = {"setup_env.sh": test_spec.setup_env_script}
        build_dir = ENV_IMAGE_BUILD_DIR / env_image.replace(":", "__")
        build_dir.mkdir(parents=True, exist_ok=True)
        if multiarch:
            build_multiarch_image(
                image_name=env_image,
                setup_scripts=setup_scripts,
                dockerfile=get_dockerfile_env_multiarch_cpp(),
                platforms=["linux/amd64"],
                client=client,
                build_dir=build_dir,
            )
            if push_to_ecr and _ecr_registry():
                push_multiarch_to_ecr(env_image, ecr_repo=ECR_REPO_CPP)
        else:
            from swefficiency.harness.dockerfiles_cpp import get_dockerfile_env_cpp

            build_image(
                image_name=env_image,
                setup_scripts=setup_scripts,
                dockerfile=get_dockerfile_env_cpp("linux/amd64"),
                platform="linux/amd64",
                client=client,
                build_dir=build_dir,
            )
        return None
    except BuildImageError as e:
        logger.error("Failed to build env image %s: %s", env_image, e)
        return e


def build_env_images_cpp(
    client: docker.DockerClient,
    dataset: Iterable[SWEfficiencyInstanceCpp],
    force_rebuild: bool = False,
    max_workers: int = 4,
    multiarch: bool = False,
    push_to_ecr: bool = False,
) -> tuple[list[TestSpecCpp], list[BuildImageError]]:
    """Build env images for each unique env hash in the dataset."""
    test_specs = [make_test_spec_cpp(inst) for inst in dataset]
    seen: dict[str, TestSpecCpp] = {}
    for ts in test_specs:
        seen.setdefault(ts.env_image_key, ts)

    successes: list[TestSpecCpp] = []
    failures: list[BuildImageError] = []
    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futs = {
            exe.submit(_build_one_env, client, ts, force_rebuild, multiarch, push_to_ecr): ts
            for ts in seen.values()
        }
        for fut in as_completed(futs):
            ts = futs[fut]
            err = fut.result()
            if err is None:
                successes.append(ts)
            else:
                failures.append(err)
    return successes, failures


def _build_one_instance(
    client: docker.DockerClient,
    test_spec: TestSpecCpp,
    force_rebuild: bool,
    multiarch: bool,
    push_to_ecr: bool,
) -> Optional[BuildImageError]:
    image_name = test_spec.instance_image_key
    if not force_rebuild:
        try:
            client.images.get(image_name)
            return None
        except docker.errors.ImageNotFound:
            pass
        if _pull_first_enabled() and _ecr_registry():
            if try_pull_from_ecr(client, image_name, ecr_repo=ECR_REPO_CPP):
                return None

    try:
        setup_scripts = {"setup_repo.sh": test_spec.install_repo_script}
        build_dir = INSTANCE_IMAGE_BUILD_DIR / image_name.replace(":", "__")
        build_dir.mkdir(parents=True, exist_ok=True)
        if multiarch:
            build_multiarch_image(
                image_name=image_name,
                setup_scripts=setup_scripts,
                dockerfile=get_dockerfile_instance_multiarch_cpp(test_spec.env_image_key),
                platforms=["linux/amd64"],
                client=client,
                build_dir=build_dir,
            )
            if push_to_ecr and _ecr_registry():
                push_multiarch_to_ecr(image_name, ecr_repo=ECR_REPO_CPP)
        else:
            from swefficiency.harness.dockerfiles_cpp import get_dockerfile_instance_cpp

            build_image(
                image_name=image_name,
                setup_scripts=setup_scripts,
                dockerfile=get_dockerfile_instance_cpp(
                    "linux/amd64", test_spec.env_image_key
                ),
                platform="linux/amd64",
                client=client,
                build_dir=build_dir,
            )
        return None
    except BuildImageError as e:
        logger.error("Failed to build instance image %s: %s", image_name, e)
        return e
    except Exception as e:
        traceback.print_exc()
        return BuildImageError(image_name, str(e), traceback.format_exc())


def build_instance_images_cpp(
    client: docker.DockerClient,
    dataset: Iterable[SWEfficiencyInstanceCpp],
    force_rebuild: bool = False,
    max_workers: int = 4,
    multiarch: bool = False,
    push_to_ecr: bool = False,
) -> tuple[list[TestSpecCpp], list[BuildImageError]]:
    """Build instance images for every instance after env images are ready."""
    # The base image is the FROM root of every env and instance image. A bare
    # uncaught raise here would crash the caller with a traceback; instead we
    # surface the failure through the same (successes, failures) contract the
    # caller already inspects, so it can exit cleanly with a clear cause.
    try:
        base_tag = build_base_images_cpp(
            client, force_rebuild=force_rebuild, multiarch=multiarch, push_to_ecr=push_to_ecr
        )
    except BuildImageError as e:
        logger.error("Base cpp image build failed; skipping all downstream builds: %s", e)
        return [], [e]
    except Exception as e:  # noqa: BLE001 - any base failure becomes a clean result
        logger.error("Base cpp image build failed unexpectedly: %s", e)
        return [], [
            BuildImageError("sweb.base.cpp:latest", str(e), traceback.format_exc())
        ]
    logger.info("Base image ready: %s", base_tag)

    env_specs, env_failures = build_env_images_cpp(
        client, dataset, force_rebuild=force_rebuild, max_workers=max_workers,
        multiarch=multiarch, push_to_ecr=push_to_ecr,
    )
    if env_failures:
        logger.warning("%d env build failures; skipping their instances", len(env_failures))

    test_specs = [make_test_spec_cpp(inst) for inst in dataset]
    successes: list[TestSpecCpp] = []
    failures: list[BuildImageError] = list(env_failures)
    failed_env_keys = {e.image_name for e in env_failures}
    eligible = [ts for ts in test_specs if ts.env_image_key not in failed_env_keys]

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futs = {
            exe.submit(_build_one_instance, client, ts, force_rebuild, multiarch, push_to_ecr): ts
            for ts in eligible
        }
        for fut in as_completed(futs):
            ts = futs[fut]
            err = fut.result()
            if err is None:
                successes.append(ts)
            else:
                failures.append(err)

    return successes, failures
