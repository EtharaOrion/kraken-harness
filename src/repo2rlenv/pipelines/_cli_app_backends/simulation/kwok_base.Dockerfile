# kwok_base.Dockerfile — hand-authored reconstruction of the opaque ECR base
# image used by kwok-backed kubectl tasks.
#
# The actual base image is pinned by digest in each emitted task's
# environment/Dockerfile:
#   426628337772.dkr.ecr.ap-south-1.amazonaws.com/kubectl_kwok@sha256:4bcfe...
#
# That image is baked externally and its Dockerfile is not published, so this
# file is a best-effort description of what it contains — useful for readers
# who want to reproduce the environment locally without ECR access, and for
# auditing what tools live in the sandbox at task-solve time.
#
# NOT USED AT BUILD TIME. environment/Dockerfile pins the ECR digest directly.
# ---------------------------------------------------------------------------

FROM debian:bookworm-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    TZ=UTC \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    KUBECONFIG=/etc/kubeconfig \
    PATH=/usr/local/go/bin:/root/.cargo/bin:/usr/local/kwok:/usr/local/bin:/usr/bin:/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git jq unzip xz-utils tar gnupg \
        build-essential pkg-config \
        openssl libssl-dev libffi-dev libyaml-dev \
        bash coreutils procps iproute2 dnsutils \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python  python  /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

ARG GO_VERSION=1.22.5
RUN curl -fsSL https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz \
      | tar -C /usr/local -xz \
    && go version

RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs npm \
        default-jdk-headless \
        ruby ruby-dev \
    && rm -rf /var/lib/apt/lists/*
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --default-toolchain stable --profile minimal \
    && /root/.cargo/bin/rustup --version

ARG KUBECTL_VERSION=v1.31.0
RUN curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
      -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && kubectl version --client=true --output=yaml >/dev/null

ARG KWOK_VERSION=v0.6.1
RUN curl -fsSL "https://github.com/kubernetes-sigs/kwok/releases/download/${KWOK_VERSION}/kwokctl-linux-amd64" \
      -o /usr/local/bin/kwokctl \
    && curl -fsSL "https://github.com/kubernetes-sigs/kwok/releases/download/${KWOK_VERSION}/kwok-linux-amd64" \
      -o /usr/local/bin/kwok \
    && chmod +x /usr/local/bin/kwokctl /usr/local/bin/kwok \
    && kwokctl --version

# /root/.kwok/cache is pre-warmed by the opaque ECR image with etcd +
# kube-apiserver + kube-controller-manager + kube-scheduler binaries so
# kwokctl doesn't hit github.com/etcd-io at run time (network is disallowed).
RUN mkdir -p /root/.kwok/cache /etc/kubeconfig /var/log/kwok /var/run/kwok

RUN pip3 install --no-cache-dir --break-system-packages \
        pytest==8.4.0 \
        pytest-timeout \
        pyyaml \
        requests \
        kubernetes==31.0.0

WORKDIR /workspace
RUN mkdir -p /workspace/submission && touch /workspace/submission/.gitkeep
ENV PATH=/workspace/submission:$PATH
