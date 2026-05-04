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

# IF you change the base image, you need to rebuild all images (run with --force_rebuild)
_DOCKERFILE_BASE = r"""
FROM --platform={platform} ubuntu:22.04

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

RUN apt update && apt install -y \
wget \
git \
build-essential \
libffi-dev \
libtiff-dev \
python3 \
python3-pip \
python-is-python3 \
jq \
curl \
locales \
locales-all \
tzdata \
python3-dev \
python3-setuptools \
gcc \
gfortran \
pkg-config \
libopenblas-dev \
libblas-dev \
liblapack-dev \
&& rm -rf /var/lib/apt/lists/*

# Download and install conda (arch derived from platform at template time)
RUN wget "https://repo.anaconda.com/miniconda/Miniconda3-py311_24.7.1-0-Linux-{conda_arch}.sh" -O miniconda.sh \
    && bash miniconda.sh -b -p /opt/miniconda3
# Add conda to PATH
ENV PATH=/opt/miniconda3/bin:$PATH
# Add conda to shell startup scripts like .bashrc (DO NOT REMOVE THIS)
RUN conda init --all
RUN conda config --append channels conda-forge
RUN conda clean --all --yes

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

RUN adduser --disabled-password --gecos 'dog' nonroot
"""

_DOCKERFILE_ENV = r"""FROM --platform={platform} sweb.base:latest

COPY ./setup_env.sh /root/
RUN chmod +x /root/setup_env.sh
RUN /bin/bash -c "source ~/.bashrc && /root/setup_env.sh"

WORKDIR /testbed/

# Automatically activate the testbed environment
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc
"""

_DOCKERFILE_INSTANCE = r"""FROM --platform={platform} {env_image_name}

COPY ./setup_repo.sh /root/
RUN /bin/bash /root/setup_repo.sh

# Record installed dependencies for reproducibility
RUN /bin/bash -c "source /opt/miniconda3/bin/activate && conda activate testbed && pip freeze > /testbed/.dep-manifest.txt" 2>/dev/null || true

WORKDIR /testbed/
"""

_DOCKERFILE_ANNOTATE_INSTANCE = r"""
FROM --platform={platform} {instance_image_name}

COPY ./patch.diff /tmp/patch.diff
COPY ./perf.sh /perf.sh

WORKDIR /testbed/
"""


def get_dockerfile_base(platform):
    conda_arch = "aarch64" if "arm64" in platform or "aarch64" in platform else "x86_64"
    return _DOCKERFILE_BASE.format(platform=platform, conda_arch=conda_arch)


def get_dockerfile_env(platform):
    return _DOCKERFILE_ENV.format(platform=platform)


def get_dockerfile_instance(platform, env_image_name):
    return _DOCKERFILE_INSTANCE.format(platform=platform, env_image_name=env_image_name)


def get_dockerfile_annotate_instance(platform, instance_image_name):
    return _DOCKERFILE_ANNOTATE_INSTANCE.format(
        platform=platform, instance_image_name=instance_image_name
    )


# ---------------------------------------------------------------------------
# Multiarch-aware Dockerfile generators
# ---------------------------------------------------------------------------
# These omit --platform= from FROM lines so buildx can inject the target
# platform automatically. The Miniconda URL uses runtime arch detection
# via $(uname -m) instead of a template-time {conda_arch} value.

_DOCKERFILE_BASE_MULTIARCH = r"""
FROM ubuntu:22.04

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

ENV http_proxy=${http_proxy} \
    https_proxy=${https_proxy} \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    no_proxy=${no_proxy} \
    NO_PROXY=${NO_PROXY}

RUN apt update && apt install -y \
wget \
git \
build-essential \
libffi-dev \
libtiff-dev \
python3 \
python3-pip \
python-is-python3 \
jq \
curl \
locales \
locales-all \
tzdata \
python3-dev \
python3-setuptools \
gcc \
gfortran \
pkg-config \
libopenblas-dev \
libblas-dev \
liblapack-dev \
&& rm -rf /var/lib/apt/lists/*

# Download and install conda — arch auto-detected at build time
RUN CONDA_ARCH=$(uname -m) && \
    wget "https://repo.anaconda.com/miniconda/Miniconda3-py311_24.7.1-0-Linux-${CONDA_ARCH}.sh" -O miniconda.sh \
    && bash miniconda.sh -b -p /opt/miniconda3
# Add conda to PATH
ENV PATH=/opt/miniconda3/bin:$PATH
# Add conda to shell startup scripts like .bashrc (DO NOT REMOVE THIS)
RUN conda init --all
RUN conda config --append channels conda-forge
RUN conda clean --all --yes

# Inject custom CA certificate if CA_CERT_PATH is set (for MITM proxies)
# Users building behind MITM proxy should volume-mount the cert at runtime
RUN if [ -n "${CA_CERT_PATH}" ]; then \
        echo "CA_CERT_PATH is set but cert must be injected at runtime via volume mount" && \
        echo "export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \
        echo "export PIP_CERT=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh; \
    fi

ENV PIP_NO_CACHE_DIR=1

RUN adduser --disabled-password --gecos 'dog' nonroot
"""

_DOCKERFILE_ENV_MULTIARCH = r"""FROM sweb.base:latest

COPY ./setup_env.sh /root/
RUN chmod +x /root/setup_env.sh
RUN /bin/bash -c "source ~/.bashrc && /root/setup_env.sh"

WORKDIR /testbed/

# Automatically activate the testbed environment
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc
"""


def get_dockerfile_base_multiarch():
    """Return a base Dockerfile without --platform pin (buildx resolves it)."""
    return _DOCKERFILE_BASE_MULTIARCH


_DOCKERFILE_INSTANCE_MULTIARCH = r"""FROM {env_image_name}

COPY ./setup_repo.sh /root/
RUN /bin/bash /root/setup_repo.sh

# Record installed dependencies for reproducibility
RUN /bin/bash -c "source /opt/miniconda3/bin/activate && conda activate testbed && pip freeze > /testbed/.dep-manifest.txt" 2>/dev/null || true

WORKDIR /testbed/
"""

_DOCKERFILE_ANNOTATE_INSTANCE_MULTIARCH = r"""
FROM {instance_image_name}

COPY ./patch.diff /tmp/patch.diff
COPY ./perf.sh /perf.sh

WORKDIR /testbed/
"""


def get_dockerfile_env_multiarch():
    """Return an env Dockerfile without --platform pin (buildx resolves it)."""
    return _DOCKERFILE_ENV_MULTIARCH


def get_dockerfile_instance_multiarch(env_image_name: str) -> str:
    """Return an instance Dockerfile without --platform pin (buildx resolves it)."""
    return _DOCKERFILE_INSTANCE_MULTIARCH.format(env_image_name=env_image_name)


def get_dockerfile_annotate_instance_multiarch(instance_image_name: str) -> str:
    """Return an annotate Dockerfile without --platform pin (buildx resolves it)."""
    return _DOCKERFILE_ANNOTATE_INSTANCE_MULTIARCH.format(
        instance_image_name=instance_image_name
    )
