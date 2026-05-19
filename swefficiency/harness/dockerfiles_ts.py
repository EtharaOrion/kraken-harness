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

"""Dockerfile templates for the TypeScript harness pipeline.

Mirrors :mod:`swefficiency.harness.dockerfiles` (Python). Three layers:

* base    -- toolchain (node:20-bookworm-slim, corepack-enabled pnpm/yarn
             shims, global TypeScript 5 + Vitest, git/curl/jq/xz-utils for
             repo + tarball plumbing). Tag: ``sweb.base.ts:latest``.
* env     -- per-(repo,version) layer. Runs ``setup_env.sh`` to install
             repo-specific system packages (e.g. libvips-dev for sharp).
             Tag: ``sweb.env.ts.<env_key>:latest``.
* instance-- per-instance layer. Clones the repo at ``base_commit`` via
             ``setup_repo.sh``. Tag: ``sweb.eval.ts.<instance_id>:latest``.

When the multi-arch path runs through ``docker buildx``, the ``--platform``
flag is supplied at build time; templates DON'T hardcode platform.
"""

# Phase 1 toolchain pin -- see plan section 3.5 + 10b.5.
_NODE_VERSION = "20"
_TYPESCRIPT_VERSION = "5"
_VITEST_VERSION = "latest"


_DOCKERFILE_BASE_TS = r"""
FROM node:20-bookworm-slim

# Proxy / MITM support (empty defaults = no-op)
ARG http_proxy=""
ARG https_proxy=""
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG no_proxy=""
ARG NO_PROXY=""
ARG CA_CERT_PATH=""

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# Propagate proxy to all build steps
ENV http_proxy=${{http_proxy}} \
    https_proxy=${{https_proxy}} \
    HTTP_PROXY=${{HTTP_PROXY}} \
    HTTPS_PROXY=${{HTTPS_PROXY}} \
    no_proxy=${{no_proxy}} \
    NO_PROXY=${{NO_PROXY}}

# Core toolchain. Must succeed unconditionally on every supported arch.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates curl jq xz-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends locales \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8 || true
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# Inject custom CA certificate if CA_CERT_PATH is set (for MITM proxies)
# Users building behind MITM proxy should volume-mount the cert at runtime
RUN if [ -n "${{CA_CERT_PATH}}" ]; then \
        echo "CA_CERT_PATH is set but cert must be injected at runtime via volume mount" && \
        echo "export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export NPM_CONFIG_CAFILE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh; \
    fi

# Enable corepack so per-repo pnpm/yarn shims resolve without extra installs.
RUN corepack enable

# Global TypeScript + Vitest so workload validation can run without a
# per-repo install (mirrors the system-wide test-toolchain install pattern).
RUN npm install -g typescript@{typescript_version} vitest@{vitest_version}

# Cap V8 heap so vitest/tsc don't OOM mid-run (mirrors how the C++ image
# bounded CMAKE_BUILD_PARALLEL_LEVEL).
ENV NODE_OPTIONS=--max-old-space-size=4096

WORKDIR /testbed
"""


_DOCKERFILE_ENV_TS = r"""FROM sweb.base.ts:latest

ARG NODE_VERSION={node_version}

COPY ./setup_env.sh /root/
RUN chmod +x /root/setup_env.sh
RUN /bin/bash -c "/root/setup_env.sh"

WORKDIR /testbed/
"""


_DOCKERFILE_INSTANCE_TS = r"""FROM {env_image_name}

COPY ./setup_repo.sh /root/
RUN /bin/bash /root/setup_repo.sh

WORKDIR /testbed/
"""


_DOCKERFILE_ANNOTATE_INSTANCE_TS = r"""FROM {instance_image_name}

COPY ./annotate_repo.sh /root/
RUN /bin/bash /root/annotate_repo.sh

WORKDIR /testbed/
"""


# Workload validation Dockerfile fragments: type-check (cheap) or
# bench-run (full) the workload module before promoting it.
_DOCKERFILE_WORKLOAD_VALIDATE_TS_CHEAP = r"""FROM sweb.base.ts:latest

COPY workload.bench.ts /workload/workload.bench.ts
WORKDIR /workload
RUN npx --yes tsc --noEmit workload.bench.ts
"""


_DOCKERFILE_WORKLOAD_VALIDATE_TS_FULL = r"""FROM sweb.base.ts:latest

COPY workload.bench.ts /workload/workload.bench.ts
WORKDIR /workload
RUN npm init -y && npm i -D vitest typescript && npx tsc --noEmit workload.bench.ts
RUN npx vitest bench --run --no-coverage workload.bench.ts
"""


def get_dockerfile_base_multiarch_ts() -> str:
    """Return the TypeScript base-image Dockerfile (node:20-bookworm-slim).

    The multi-arch ``docker buildx`` driver supplies ``--platform`` at build
    time; the template doesn't hardcode it.
    """
    return _DOCKERFILE_BASE_TS.format(
        typescript_version=_TYPESCRIPT_VERSION,
        vitest_version=_VITEST_VERSION,
    )


def get_dockerfile_env_multiarch_ts() -> str:
    """Return the TypeScript env-image Dockerfile (FROM sweb.base.ts:latest)."""
    return _DOCKERFILE_ENV_TS.format(node_version=_NODE_VERSION)


def get_dockerfile_instance_multiarch_ts(env_image_name: str) -> str:
    """Return the TypeScript instance-image Dockerfile (FROM <env_image_name>)."""
    return _DOCKERFILE_INSTANCE_TS.format(env_image_name=env_image_name)


def get_dockerfile_annotate_instance_multiarch_ts(instance_image_name: str) -> str:
    """Return the TypeScript annotation Dockerfile (FROM <instance_image_name>)."""
    return _DOCKERFILE_ANNOTATE_INSTANCE_TS.format(
        instance_image_name=instance_image_name,
    )


def get_dockerfile_base_ts(platform: str) -> str:
    """Single-arch variant: bake ``--platform`` into the FROM line."""
    template = _DOCKERFILE_BASE_TS.replace(
        "FROM node:20-bookworm-slim",
        "FROM --platform=" + platform + " node:20-bookworm-slim",
    )
    return template.format(
        typescript_version=_TYPESCRIPT_VERSION,
        vitest_version=_VITEST_VERSION,
    )


def get_dockerfile_env_ts(platform: str) -> str:
    template = _DOCKERFILE_ENV_TS.replace(
        "FROM sweb.base.ts:latest",
        "FROM --platform=" + platform + " sweb.base.ts:latest",
    )
    return template.format(node_version=_NODE_VERSION)


def get_dockerfile_instance_ts(platform: str, env_image_name: str) -> str:
    template = _DOCKERFILE_INSTANCE_TS.replace(
        "FROM {env_image_name}",
        "FROM --platform=" + platform + " {env_image_name}",
    )
    return template.format(env_image_name=env_image_name)


def get_dockerfile_annotate_instance_ts(platform: str, instance_image_name: str) -> str:
    template = _DOCKERFILE_ANNOTATE_INSTANCE_TS.replace(
        "FROM {instance_image_name}",
        "FROM --platform=" + platform + " {instance_image_name}",
    )
    return template.format(instance_image_name=instance_image_name)


def get_dockerfile_workload_validate_ts(mode: str = "cheap") -> str:
    """Return the workload-validation Dockerfile.

    ``mode='cheap'`` (default, ``SWEFF_VALIDATE_TS_WORKLOAD=cheap``) only
    runs ``tsc --noEmit`` against ``workload.bench.ts``. ``mode='full'``
    (``SWEFF_VALIDATE_TS_WORKLOAD=full``) additionally runs the vitest
    benchmark to confirm the workload actually executes.
    """
    if mode == "full":
        return _DOCKERFILE_WORKLOAD_VALIDATE_TS_FULL
    return _DOCKERFILE_WORKLOAD_VALIDATE_TS_CHEAP


def get_image_tag_base_ts() -> str:
    """Return the canonical base image tag."""
    return "sweb.base.ts:latest"


def get_image_tag_env_ts(env_key: str) -> str:
    """Return the canonical env image tag for ``env_key`` (repo/version hash)."""
    return "sweb.env.ts." + env_key


def get_image_tag_eval_ts(instance_id: str) -> str:
    """Return the canonical eval (instance) image tag for ``instance_id``."""
    return "sweb.eval.ts." + instance_id
