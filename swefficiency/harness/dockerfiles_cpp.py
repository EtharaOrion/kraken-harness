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

"""Dockerfile templates for the C++ harness pipeline.

Mirrors :mod:`swefficiency.harness.dockerfiles` (Python). Three layers:

* base    -- toolchain (gcc-12, clang-15, cmake, ninja, ccache, gcov, lcov,
             gcovr, GoogleTest 1.14, Google Benchmark 1.8.3, python3, perf).
             Tag: ``sweb.base.cpp:latest``.
* env     -- per-(repo,version) layer. Runs ``setup_env.sh`` to install
             repo-specific system packages (e.g. libopenblas-dev for eigen).
             Tag: ``sweb.env.cpp.<env_key>:latest``.
* instance-- per-instance layer. Clones the repo at ``base_commit`` via
             ``setup_repo.sh``. Tag: ``sweb.eval.cpp.<instance_id>:latest``.

When the multi-arch path runs through ``docker buildx``, the ``--platform``
flag is supplied at build time; templates DON'T hardcode platform.
"""

# Phase 1 toolchain pin -- see plan section 3.5 + 10b.5.
_GTEST_VERSION = "v1.14.0"
_GOOGLE_BENCHMARK_VERSION = "v1.8.3"


_DOCKERFILE_BASE_CPP = r"""
FROM ubuntu:22.04

ARG http_proxy=""
ARG https_proxy=""
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG no_proxy=""
ARG NO_PROXY=""
ARG CA_CERT_PATH=""

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

ENV http_proxy=${{http_proxy}} \
    https_proxy=${{https_proxy}} \
    HTTP_PROXY=${{HTTP_PROXY}} \
    HTTPS_PROXY=${{HTTPS_PROXY}} \
    no_proxy=${{no_proxy}} \
    NO_PROXY=${{NO_PROXY}}

# Core toolchain. Must succeed unconditionally on every supported arch.
# (Previously fused with the optional linux-perf install via `A || B && C`,
#  whose precedence silently skipped the core toolchain on arches where
#  linux-perf is unavailable, e.g., linux/arm64.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc-12 g++-12 \
    clang-15 \
    cmake ninja-build make pkg-config \
    ccache \
    gcovr lcov \
    git curl wget ca-certificates \
    libssl-dev libdw-dev libunwind-dev \
    libopenblas-dev liblapack-dev \
    python3 python3-minimal python3-pip \
    xz-utils unzip zip \
    locales \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Optional: perf profiling tools. linux-perf is missing on arm64 / older Ubuntu;
# linux-tools-generic is the historical fallback; both may be unavailable in
# minimal base images, so make the whole step best-effort.
RUN apt-get update \
    && (apt-get install -y --no-install-recommends linux-perf \
        || apt-get install -y --no-install-recommends linux-tools-generic \
        || true) \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8 || true
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# Pin gcc-12 / g++-12 as default toolchain.
RUN update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 100 && \
    update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-12 100 && \
    update-alternatives --install /usr/bin/cc cc /usr/bin/gcc-12 100 && \
    update-alternatives --install /usr/bin/c++ c++ /usr/bin/g++-12 100

# GoogleTest 1.14 (system-wide install).
RUN cd /tmp && git clone --depth 1 --branch {gtest_version} https://github.com/google/googletest.git gtest && \
    cmake -S gtest -B gtest/build -DCMAKE_BUILD_TYPE=Release -GNinja && \
    cmake --build gtest/build --target install && \
    rm -rf /tmp/gtest

# Google Benchmark 1.8.3 (system-wide install).
RUN cd /tmp && git clone --depth 1 --branch {benchmark_version} https://github.com/google/benchmark.git gbench && \
    cmake -S gbench -B gbench/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DBENCHMARK_ENABLE_TESTING=OFF \
        -DBENCHMARK_DOWNLOAD_DEPENDENCIES=ON \
        -GNinja && \
    cmake --build gbench/build --target install && \
    rm -rf /tmp/gbench

# ccache config: 10G persistent cache mounted from host via /root/.cache/ccache.
RUN mkdir -p /root/.cache/ccache && ccache --set-config max_size=10G && ccache --set-config compression=true
ENV CCACHE_DIR=/root/.cache/ccache \
    CMAKE_C_COMPILER_LAUNCHER=ccache \
    CMAKE_CXX_COMPILER_LAUNCHER=ccache \
    PATH=/usr/lib/ccache:${{PATH}}

# Inject custom CA certificate if CA_CERT_PATH is set (for MITM proxies)
# Users building behind MITM proxy should volume-mount the cert at runtime
RUN if [ -n "${{CA_CERT_PATH}}" ]; then \
        echo "CA_CERT_PATH is set but cert must be injected at runtime via volume mount" && \
        echo "export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export PIP_CERT=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh; \
    fi

ENV PIP_NO_CACHE_DIR=1

WORKDIR /testbed
"""


_DOCKERFILE_ENV_CPP = r"""FROM sweb.base.cpp:latest

COPY ./setup_env.sh /root/
RUN chmod +x /root/setup_env.sh
RUN /bin/bash -c "/root/setup_env.sh"

WORKDIR /testbed/
"""


_DOCKERFILE_INSTANCE_CPP = r"""FROM {env_image_name}

COPY ./setup_repo.sh /root/
RUN /bin/bash /root/setup_repo.sh

WORKDIR /testbed/
"""


_DOCKERFILE_ANNOTATE_INSTANCE_CPP = r"""FROM {instance_image_name}

COPY ./annotate_repo.sh /root/
RUN /bin/bash /root/annotate_repo.sh

WORKDIR /testbed/
"""


def get_dockerfile_base_multiarch_cpp() -> str:
    """Return the C++ base-image Dockerfile (Ubuntu 22.04 + toolchain).

    The multi-arch ``docker buildx`` driver supplies ``--platform`` at build
    time; the template doesn't hardcode it.
    """
    return _DOCKERFILE_BASE_CPP.format(
        gtest_version=_GTEST_VERSION,
        benchmark_version=_GOOGLE_BENCHMARK_VERSION,
    )


def get_dockerfile_env_multiarch_cpp() -> str:
    """Return the C++ env-image Dockerfile (FROM sweb.base.cpp:latest)."""
    return _DOCKERFILE_ENV_CPP


def get_dockerfile_instance_multiarch_cpp(env_image_name: str) -> str:
    """Return the C++ instance-image Dockerfile (FROM <env_image_name>)."""
    return _DOCKERFILE_INSTANCE_CPP.format(env_image_name=env_image_name)


def get_dockerfile_annotate_instance_multiarch_cpp(instance_image_name: str) -> str:
    """Return the C++ annotation Dockerfile (FROM <instance_image_name>)."""
    return _DOCKERFILE_ANNOTATE_INSTANCE_CPP.format(
        instance_image_name=instance_image_name,
    )


def get_dockerfile_base_cpp(platform: str) -> str:
    """Single-arch variant: bake ``--platform`` into the FROM line."""
    template = _DOCKERFILE_BASE_CPP.replace(
        "FROM ubuntu:22.04", "FROM --platform=" + platform + " ubuntu:22.04"
    )
    return template.format(
        gtest_version=_GTEST_VERSION,
        benchmark_version=_GOOGLE_BENCHMARK_VERSION,
    )


def get_dockerfile_env_cpp(platform: str) -> str:
    return _DOCKERFILE_ENV_CPP.replace(
        "FROM sweb.base.cpp:latest",
        "FROM --platform=" + platform + " sweb.base.cpp:latest",
    )


def get_dockerfile_instance_cpp(platform: str, env_image_name: str) -> str:
    template = _DOCKERFILE_INSTANCE_CPP.replace(
        "FROM {env_image_name}",
        "FROM --platform=" + platform + " {env_image_name}",
    )
    return template.format(env_image_name=env_image_name)


def get_dockerfile_annotate_instance_cpp(platform: str, instance_image_name: str) -> str:
    template = _DOCKERFILE_ANNOTATE_INSTANCE_CPP.replace(
        "FROM {instance_image_name}",
        "FROM --platform=" + platform + " {instance_image_name}",
    )
    return template.format(instance_image_name=instance_image_name)
