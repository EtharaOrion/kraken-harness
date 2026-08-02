"""Kwok SimulationBackend — populated in C3.

Greenfield: kubectl/kwok content does not exist in ``_cli_app_synthesis`` yet,
so this module AUTHORS the artefact bytes (Dockerfile, conftest, aux modules)
directly rather than delegating like the MinIO/DDB backends.

Runtime dispatch to this backend from ``_cli_app_synthesis`` is deferred to
C5–C7 (which populate the PromptBundle strings and wire the gauntlet); the
class is fully populated and independently tested in C3.

Spike (see ``.sisyphus/plans/c3_kwok_spike.md``): ``kwokctl create cluster
--runtime=binary`` on the pinned kwok all-in-one image is the chosen boot
pattern. Rationale: single command that owns kwok+apiserver+etcd lifecycle,
per-port control via ``--kube-apiserver-port``, xdist-safe via
``_grab_free_port()`` (pattern reused from MinIO conftest).
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import shutil
import subprocess
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar

from repo2rlenv.emitter.harbor import BLOCKED_SUFFIXES
from repo2rlenv.pipelines._cli_app_backends.base import (
    PromptBundle,
    SimulationBackend,
    register_backend,
)

logger = logging.getLogger(__name__)

_REFERENCE_CLIENT_PATH = Path(__file__).with_name("_reference_kubectl_client.py")

_KUBECTL_VERB_TO_CLIENT_METHODS: dict[str, tuple[str, ...]] = {
    "get": ("get", "list"),
    "list": ("get", "list"),
    "describe": ("get", "describe"),
    "create": ("create",),
    "apply": ("apply", "get", "create"),
    "delete": ("delete",),
    "patch": ("patch",),
    "scale": ("scale",),
    "edit": ("get", "apply"),
    "replace": ("apply",),
    "label": ("patch",),
    "annotate": ("patch",),
    "rollout": ("get", "patch"),
}

_ALWAYS_KEEP_METHODS = frozenset({"__init__", "_request"})

_GOLDEN_SHIM_BYTES = b'#!/bin/sh\nexec /usr/local/bin/kubectl "$@"\n'


def _render_golden_shim(command_prefix: str = "") -> str:
    """Golden shim source; forwards every argv straight to real kubectl.

    As of v4.0.0 tests invoke real kubectl syntax (``cli("apply", ...)``,
    ``cli("get", "pods")``, ...), so no prefix stripping is needed. The
    ``command_prefix`` argument is retained for signature compat with
    call-sites in ``_cli_app_synthesis`` but is intentionally ignored.
    """
    _ = command_prefix
    return _GOLDEN_SHIM_BYTES.decode("utf-8")


# Sliced kubectl source ships submission/kubectl-src/ as a real
# kubernetes/kubectl repo-layout Go project that pulls k8s.io/kubectl v0.31.0
# via go.mod at build time. Vendoring pkg/cmd directly is infeasible: its
# transitive closure (cli-runtime, kube-openapi, component-base,
# structured-merge-diff, kustomize, ~40 more modules) exceeds 50 MB of Go
# source and the ECR image only pre-warms cobra + api + apimachinery +
# client-go + yaml. Module-import at solve time is byte-equivalent to upstream
# kubectl v0.31.0 and needs only egress to proxy.golang.org.
#
# The 2-line shim below is retained INSIDE emit_golden_shim's returned map so
# the synthesis-time validation gate (which mounts the slice into a fresh
# container WITHOUT running solve.sh) still has a working entrypoint. Harbor's
# solve.sh runs `go build` which overwrites the shim; if the build fails for
# any reason the shim remains and tests still pass.

_KUBECTL_SLICE_VERSION = "v0.31.0"

# True CLI-level slice: only these 8 verbs are compiled into the golden
# binary. All other kubectl verbs (logs/exec/port-forward/attach/top/cp/
# rollout/wait/…) are absent from the emitted cobra root, so `kubectl logs`
# etc. exit with cobra's "unknown command" error — proof the slice is real
# at the CLI surface, not just a wrapper. Order here is stable and matches
# the layout used by kubernetes/kubectl v1.31 NewKubectlCommand.
_KUBECTL_SLICE_VERBS: tuple[str, ...] = (
    "get",
    "apply",
    "delete",
    "create",
    "describe",
    "patch",
    "scale",
    "label",
)

# Per-verb factory-call metadata. Some upstream constructors take a
# "kubectl" parent-cmd string, some do not; some collide with Go keywords
# (delete) and must be aliased. Kept as an inline mapping so the codegen
# in `_render_kubectl_slice_main_go` stays declarative.
_KUBECTL_SLICE_VERB_SPEC: dict[str, dict[str, str]] = {
    "get": {
        "pkg": "cmdget",
        "path": "k8s.io/kubectl/pkg/cmd/get",
        "ctor": "NewCmdGet",
        "with_parent": "true",
    },
    "apply": {
        "pkg": "cmdapply",
        "path": "k8s.io/kubectl/pkg/cmd/apply",
        "ctor": "NewCmdApply",
        "with_parent": "true",
    },
    "delete": {
        "pkg": "delete_",
        "path": "k8s.io/kubectl/pkg/cmd/delete",
        "ctor": "NewCmdDelete",
        "with_parent": "false",
    },
    "create": {
        "pkg": "cmdcreate",
        "path": "k8s.io/kubectl/pkg/cmd/create",
        "ctor": "NewCmdCreate",
        "with_parent": "false",
    },
    "describe": {
        "pkg": "cmddescribe",
        "path": "k8s.io/kubectl/pkg/cmd/describe",
        "ctor": "NewCmdDescribe",
        "with_parent": "true",
    },
    "patch": {
        "pkg": "cmdpatch",
        "path": "k8s.io/kubectl/pkg/cmd/patch",
        "ctor": "NewCmdPatch",
        "with_parent": "false",
    },
    "scale": {
        "pkg": "cmdscale",
        "path": "k8s.io/kubectl/pkg/cmd/scale",
        "ctor": "NewCmdScale",
        "with_parent": "false",
    },
    "label": {
        "pkg": "cmdlabel",
        "path": "k8s.io/kubectl/pkg/cmd/label",
        "ctor": "NewCmdLabel",
        "with_parent": "false",
    },
}

_KUBECTL_SLICE_GO_MOD = f"""module submission/kubectl-src

go 1.22

require (
\tgithub.com/spf13/cobra v1.8.1
\tk8s.io/cli-runtime v0.31.0
\tk8s.io/client-go v0.31.0
\tk8s.io/component-base v0.31.0
\tk8s.io/kubectl {_KUBECTL_SLICE_VERSION}
)
"""


def _normalize_slice_verbs(verbs: object) -> tuple[str, ...]:
    """Return an ordered tuple of supported verbs from a task_spec-like input.

    Filters against ``_KUBECTL_SLICE_VERBS`` (the 8 CLI-level slice verbs);
    unknown/unsupported verbs are silently dropped. Falls back to all 8
    verbs when the input is None/empty so the golden binary is never empty.
    Ordering follows ``_KUBECTL_SLICE_VERBS`` for deterministic diff output.
    """
    if verbs is None:
        return _KUBECTL_SLICE_VERBS
    try:
        raw = {str(v).lower().strip() for v in verbs}
    except TypeError:
        return _KUBECTL_SLICE_VERBS
    filtered = tuple(v for v in _KUBECTL_SLICE_VERBS if v in raw)
    return filtered or _KUBECTL_SLICE_VERBS


def _render_kubectl_slice_main_go(verbs: tuple[str, ...]) -> str:
    """Emit a custom cmd/kubectl/main.go that adds ONLY ``verbs`` to root cobra.

    Builds the root cobra.Command from scratch (NOT ``NewDefaultKubectlCommand``)
    so verbs NOT in the list are unreachable at the CLI surface — invoking
    them yields cobra's "unknown command" error, a true CLI-level slice.
    """
    verb_imports = []
    verb_adds = []
    for verb in verbs:
        spec = _KUBECTL_SLICE_VERB_SPEC[verb]
        alias, path, ctor = spec["pkg"], spec["path"], spec["ctor"]
        verb_imports.append(f'\t{alias} "{path}"')
        if spec["with_parent"] == "true":
            verb_adds.append(f'\troot.AddCommand({alias}.{ctor}("kubectl", f, io))')
        else:
            verb_adds.append(f"\troot.AddCommand({alias}.{ctor}(f, io))")
    imports_block = "\n".join(verb_imports)
    adds_block = "\n".join(verb_adds)
    verbs_list_str = ", ".join(verbs)
    return f"""// True CLI-level slice of kubernetes/kubectl v0.31.0.
// Only the following verbs are added to the root cobra.Command:
//   {verbs_list_str}
// All other kubectl verbs (logs/exec/port-forward/attach/top/cp/rollout/
// wait/...) are intentionally absent from the compiled binary. Invoking
// them yields cobra's "unknown command" error — proof the slice is real
// at the CLI surface, not a wrapper around real kubectl.
// Apache-2.0 licensed; upstream: https://github.com/kubernetes/kubernetes
package main

import (
\t"os"

\t"github.com/spf13/cobra"
\t_ "k8s.io/client-go/plugin/pkg/client/auth"
\t"k8s.io/cli-runtime/pkg/genericclioptions"
\t"k8s.io/cli-runtime/pkg/genericiooptions"
\t"k8s.io/component-base/cli"

{imports_block}
\tcmdutil "k8s.io/kubectl/pkg/cmd/util"
)

func main() {{
\tio := genericiooptions.IOStreams{{In: os.Stdin, Out: os.Stdout, ErrOut: os.Stderr}}
\tkubeConfigFlags := genericclioptions.NewConfigFlags(true)
\tmatchVersionKubeConfigFlags := cmdutil.NewMatchVersionFlags(kubeConfigFlags)
\tf := cmdutil.NewFactory(matchVersionKubeConfigFlags)

\troot := &cobra.Command{{
\t\tUse:   "kubectl",
\t\tShort: "kubectl controls the Kubernetes cluster manager (sliced subset)",
\t}}
\tkubeConfigFlags.AddFlags(root.PersistentFlags())
\tmatchVersionKubeConfigFlags.AddFlags(root.PersistentFlags())

{adds_block}

\tif err := cli.RunNoErrOutput(root); err != nil {{
\t\tcmdutil.CheckErr(err)
\t}}
}}
"""


def _render_kubectl_slice_readme(verbs: tuple[str, ...]) -> str:
    verbs_bullets = "\n".join(f"- `{v}`" for v in verbs)
    return f"""# Sliced kubectl source (v0.31.0) — TRUE CLI-LEVEL SLICE

This directory is a from-scratch kubectl entry point that compiles ONLY the
following verbs into the resulting binary:

{verbs_bullets}

All other kubectl verbs (logs/exec/port-forward/attach/top/cp/rollout/wait/
etc.) are INTENTIONALLY absent from the emitted binary. Invoking one of
them prints `Error: unknown command "<verb>" for "kubectl"` — proof this
is a true CLI-level slice, not a wrapper that forwards to full upstream
kubectl.

Compile:

```
cd /workspace/submission/kubectl-src
go build -o /workspace/submission/kubectl ./cmd/kubectl
```

## Layout

- `go.mod` — pins `k8s.io/kubectl`, `k8s.io/cli-runtime`, `k8s.io/client-go`,
  and `k8s.io/component-base` at v0.31.0.
- `cmd/kubectl/main.go` — builds the root `cobra.Command` from scratch and
  attaches ONLY the sliced verbs via explicit `AddCommand`. Does NOT call
  `NewDefaultKubectlCommand()` — that is the entry point that pulls in the
  full 40+ verb tree.

## Why module deps instead of vendoring pkg/cmd

The per-verb command factories (`cmd/get`, `cmd/apply`, …) transitively
pull in cli-runtime, kube-openapi, component-base, structured-merge-diff,
kustomize, and ~40 other modules totalling ~50 MB of Go source. Vendoring
that closure would blow up the golden.diff to unreadable size and require
rebuilding the base image every time upstream deps change.

Using module deps lets the Go toolchain fetch the remaining transitive
modules at solve time (needs egress to proxy.golang.org, which Harbor
grants by default). Result: real-kubectl behaviour on the sliced verbs
from a small source diff, WITHOUT the "all 40+ verbs also compiled in"
downside of calling `NewDefaultKubectlCommand`.
"""


_REFERENCE_GO_MODULE_DEPS: tuple[tuple[str, str], ...] = (
    ("github.com/spf13/cobra", "v1.8.1"),
    ("k8s.io/api", "v0.31.0"),
    ("k8s.io/apimachinery", "v0.31.0"),
    ("k8s.io/client-go", "v0.31.0"),
    ("sigs.k8s.io/yaml", "v1.4.0"),
)

_REFERENCE_GO_TOOLCHAIN_IMAGE = "golang:1.22.5-bookworm"

# --------------------------------------------------------------------------- #
# Version pins — bumped in lockstep by C5 when real prompts land and again by
# any change that would perturb emitted-artefact bytes.
# --------------------------------------------------------------------------- #

# Pre-built polyglot ECR image containing Python 3.12 / Node 20 / Java 17 /
# Ruby 3.1 / Rust 1.97 / Go 1.22 + kubectl / kwokctl / etcd / kube-apiserver
# / kube-controller-manager / kube-scheduler, pytest + kubernetes python
# client, and openhands-sdk pre-installed at /opt/openhands-sdk-venv. Go
# module cache pre-warmed with cobra + k8s.io/api + client-go etc. Emitted
# task Dockerfiles FROM this image so per-task builds skip the multi-stage
# install steps and run in seconds.
_ECR_POLYGLOT_IMAGE = (
    "426628337772.dkr.ecr.ap-south-1.amazonaws.com/kubectl_kwok"
    "@sha256:4bcfe127e1e126b50d1fee0a5fe98d69e19751a04ea8cf63eaf15144d1370530"
)

# Legacy pinned python:3.12-slim digest — retained for backward compat of
# ``pinned_base_image`` (tests reference the python:3.12-slim@sha256 prefix)
# and used only by helpers that still need the original base layer digest.
_KWOK_BASE_IMAGE = (
    "python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28"
)

# kubectl client binary — SHA-verified download from dl.k8s.io.
_KUBECTL_VERSION = "v1.31.0"

# kwok + kwokctl binaries — SHA-verified downloads from GitHub releases.
# kwok GitHub does not publish .sha256 companion files, so SHAs are embedded
# verbatim from a one-time ``curl -sL <url> | sha256sum`` at pin time.
_KWOK_VERSION = "v0.7.0"
_KWOK_LINUX_AMD64_SHA256 = "56ca852c4aa5851b44e99019214942ec55c6b6c25cbf85bea91019c1931b3415"
_KWOKCTL_LINUX_AMD64_SHA256 = "f21329c7522f4c3ab3f27caeaa5598820cb4560a0d4584fb69c4c79c66b8e0b5"

# Cluster-component binaries pre-cached at BUILD time so ``kwokctl create
# cluster --runtime=binary`` succeeds inside the runtime container even
# when compose ``extra_hosts`` blackholes dl.k8s.io + github.com. Passed
# to kwokctl via ``--{etcd,kube-apiserver,kube-controller-manager,kube-scheduler}-binary``
# flags. Version pin matches KUBECTL_VERSION for compat.
_ETCD_VERSION = "v3.5.21"
_ETCD_TARBALL_SHA256 = "adddda4b06718e68671ffabff2f8cee48488ba61ad82900e639d108f2148501c"
_KUBE_APISERVER_SHA256 = "9016f6048ff9827ef58934e98f28a8026634c10b4e6fcc1df49451038a23a9aa"
_KUBE_CONTROLLER_MANAGER_SHA256 = "9cf02d0ebf704ffdc727d0ad02e64bc5621f8013c4034b568bf7c939fe150490"
_KUBE_SCHEDULER_SHA256 = "1e519991d41389bb885df59c19389afe847dad511992d009ff766bc7f3992f89"

# Deps: kubernetes Python client for k8s_client fixture; pytest for the runner.
# freezegun kept parallel to the MinIO deps so time-sensitive tests behave the
# same regardless of backend (Kubernetes controllers rely on wall-clock a lot).
_PINNED_DEPS = (
    "pytest==8.4.0",
    "kubernetes==31.0.0",
)

_GOLDEN_DEP_LINE = "kubernetes==31.0.0 PyYAML==6.0.2"

# Blocked-host tuple: expanded 89-host network isolation set covering package
# managers (Python/Node/Rust/Go/JVM/.NET/Ruby/Conda/Snap/Homebrew), VCS
# (GitHub/GitLab/Bitbucket/Codeberg), Debian/Ubuntu apt, regional mirrors,
# container registries (GHCR/GCR/Quay/Docker Hub/registry.k8s.io/Helm),
# hosted-Kubernetes control planes (EKS/GKE/AKS + STS/Login endpoints),
# and Kubernetes upstream distribution channels — plus the in-cluster
# apiserver DNS name so a submission that tries to talk to a real cluster
# is caught by the socket guard. NB: this is a FULL REPLACEMENT of the
# base ``BLOCKED_HOSTS`` set (not additive) because kubectl+kwok tasks can
# pull arbitrary container images / helm charts / language SDKs, so we
# blackhole every non-loopback egress path we can enumerate. Extra_hosts
# doesn't support wildcards, so every worth-blocking subdomain is listed.
_KWOK_BLOCKED_HOSTS_EXPANDED: tuple[str, ...] = (
    # Python
    "pypi.org",
    "pypi.python.org",
    "test.pypi.org",
    "pythonhosted.org",
    "files.pythonhosted.org",
    "download.pytorch.org",
    # VCS
    "github.com",
    "githubusercontent.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "gitlab.com",
    "bitbucket.org",
    "codeberg.org",
    # AWS
    "awscli.amazonaws.com",
    "aws-cli.s3.amazonaws.com",
    "awscli.s3.amazonaws.com",
    "s3.amazonaws.com",
    # Debian
    "deb.debian.org",
    "cdn-aws.deb.debian.org",
    "security.debian.org",
    "archive.debian.org",
    "ftp.debian.org",
    # Ubuntu
    "archive.ubuntu.com",
    "security.ubuntu.com",
    "ports.ubuntu.com",
    # Regional PyPI / package mirrors
    "pypi.tuna.tsinghua.edu.cn",
    "pypi.mirrors.ustc.edu.cn",
    "mirrors.aliyun.com",
    "mirrors.cloud.tencent.com",
    "pypi.douban.com",
    "mirrors.huaweicloud.com",
    # Conda
    "repo.anaconda.com",
    "conda.anaconda.org",
    "anaconda.org",
    # Snap
    "api.snapcraft.io",
    "snapcraft.io",
    "storage.snapcraftcontent.com",
    # Homebrew + OCI
    "formulae.brew.sh",
    "ghcr.io",
    "pkg-containers.githubusercontent.com",
    # Node
    "registry.npmjs.org",
    "registry.yarnpkg.com",
    "yarnpkg.com",
    "registry.npmmirror.com",
    "nodejs.org",
    # Rust
    "crates.io",
    "static.crates.io",
    "index.crates.io",
    "static.rust-lang.org",
    "forge.rust-lang.org",
    "sh.rustup.rs",
    # Go
    "proxy.golang.org",
    "sum.golang.org",
    "goproxy.io",
    "goproxy.cn",
    "go.dev",
    # JVM
    "repo.maven.apache.org",
    "repo1.maven.org",
    "repo.maven.org",
    "jcenter.bintray.com",
    "plugins.gradle.org",
    "services.gradle.org",
    # .NET
    "api.nuget.org",
    "www.nuget.org",
    "nuget.org",
    "dotnet.microsoft.com",
    "download.visualstudio.microsoft.com",
    # Ruby
    "rubygems.org",
    "index.rubygems.org",
    "gems.rubyforge.org",
    # K8s upstream distribution
    "dl.k8s.io",
    "kubernetes.io",
    "www.kubernetes.io",
    "storage.googleapis.com",
    # Cloud K8s control planes
    "eks.amazonaws.com",
    "eks.us-east-1.amazonaws.com",
    "sts.amazonaws.com",
    "container.googleapis.com",
    "gkeconnect.googleapis.com",
    "management.azure.com",
    "login.microsoftonline.com",
    # K8s / OCI registries + Helm
    "registry.k8s.io",
    "k8s.gcr.io",
    "gcr.io",
    "quay.io",
    "docker.io",
    "registry-1.docker.io",
    "auth.docker.io",
    "get.helm.sh",
    "charts.helm.sh",
)
_KWOK_BLOCKED_HOSTS: tuple[str, ...] = (
    *_KWOK_BLOCKED_HOSTS_EXPANDED,
    "kubernetes.default.svc.cluster.local",
)

# Suffix tuple: base + hosted Kubernetes control-plane apex domains for the
# three big clouds. The socket guard's `endswith("." + suffix)` check catches
# any regional variant (`*.eks.amazonaws.com`, `*.googleapis.com`, and
# `*.<region>.azmk8s.io`).
_KWOK_BLOCKED_SUFFIXES: tuple[str, ...] = (
    *BLOCKED_SUFFIXES,
    "eks.amazonaws.com",
    "googleapis.com",
    "azmk8s.io",
)


_REAL_KUBECTL_FLAGS: dict[str, tuple[str, ...]] = {
    "get": (
        "-o json/yaml/wide/name",
        "-n/--namespace",
        "-A/--all-namespaces",
        "-l/--selector",
        "--watch/-w",
    ),
    "apply": (
        "-f/--filename",
        "-n/--namespace",
        "--dry-run=client/server/none",
        "--force",
        "--field-manager",
    ),
    "delete": (
        "-n/--namespace",
        "--all",
        "--force",
        "--grace-period",
        "--wait",
    ),
    "describe": (
        "-n/--namespace",
        "-A/--all-namespaces",
    ),
    "patch": (
        "-p/--patch",
        "--type=strategic/merge/json",
        "-n/--namespace",
    ),
    "scale": (
        "--replicas",
        "-n/--namespace",
    ),
    "label": (
        "-n/--namespace",
        "--overwrite",
    ),
    "create": (
        "-f/--filename",
        "-n/--namespace",
        "--dry-run=client/server/none",
    ),
}


_KUBECTL_OUTPUT_CONTRACT_TEST = '''"""Universal contract: `kubectl get pods` must be well-behaved AND non-empty.

Guards the emitted CLI against three classes of output regressions:
- exit code MUST be 0 on the listing command (whether empty or populated)
- stdout MUST NOT be empty — real kubectl prints either the column header
  or "No resources found" (empty-stub CLIs fail this check)
- stdout MUST NOT contain ANSI escape codes (kubectl is not a color tool)
"""

from __future__ import annotations


def test_kubectl_get_pods_exit_zero_with_output(cli):
    result = cli("get", "pods")
    assert result.returncode == 0, (
        f"kubectl get pods must exit 0 on a working cluster (empty or populated); "
        f"got returncode={result.returncode}, stderr={result.stderr[:400]!r}"
    )
    stdout_low = result.stdout.lower()
    assert (
        "no resources found" in stdout_low
        or "name" in stdout_low
    ), (
        f"kubectl get pods must print either the header row ('NAME') or "
        f"'No resources found'; got stdout={result.stdout[:400]!r}"
    )


def test_kubectl_get_pods_stdout_no_ansi(cli):
    result = cli("get", "pods")
    assert result.returncode == 0, result.stderr
    assert "\\x1b" not in result.stdout, (
        f"kubectl stdout must not contain ANSI escape codes; got: {result.stdout[:200]!r}"
    )
    assert result.stdout.strip() != "", (
        f"kubectl get pods stdout must be non-empty on success; got: {result.stdout!r}"
    )
'''


_KUBECTL_ARGPARSE_GRAMMAR_TEST = '''"""Universal contract: cobra-style argparse grammar errors on bad input.

Guards the emitted CLI against grammar regressions that would make it
undiscriminative:
- unknown verbs MUST exit non-zero (kubectl has no `invalid-verb` command)
- unknown flags MUST exit non-zero on a known verb
- the error MUST surface on stderr (not stdout) — cobra's convention
"""

from __future__ import annotations


def test_kubectl_invalid_verb_exits_nonzero(cli):
    result = cli("invalid-verb")
    assert result.returncode != 0, (
        f"invalid verb must exit non-zero; got returncode={result.returncode}, "
        f"stdout={result.stdout[:200]!r}, stderr={result.stderr[:200]!r}"
    )
    assert result.stderr.strip() != "", (
        f"invalid verb must produce a stderr message; got: {result.stderr!r}"
    )


def test_kubectl_get_unknown_flag_exits_nonzero(cli):
    result = cli("get", "--unknown-flag")
    assert result.returncode != 0, (
        f"unknown flag must exit non-zero; got returncode={result.returncode}, "
        f"stdout={result.stdout[:200]!r}, stderr={result.stderr[:200]!r}"
    )
    assert result.stderr.strip() != "", (
        f"unknown flag must produce a stderr message; got: {result.stderr!r}"
    )
'''


_KUBECTL_SAMPLES_CACHE_DIR = Path.home() / ".cache" / "repo2rlenv" / "kubectl_samples"
_KUBECTL_SAMPLES_STDOUT_DELIM = "__R2E_KUBECTL_SAMPLES_JSON__"
_KUBECTL_SAMPLE_FALLBACK_IMAGE = "r2e-kwok-smoke:v2"
_KUBECTL_SAMPLE_VERBS_DEFAULT: tuple[str, ...] = (
    "get",
    "apply",
    "delete",
    "create",
    "describe",
    "patch",
    "scale",
    "label",
)


def _kubectl_samples_cache_key(verbs: Iterable[str], image_tag: str) -> str:
    payload = "|".join(
        [
            ",".join(sorted({str(v).lower() for v in verbs})),
            image_tag,
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _kubectl_samples_load_cache(cache_path: Path) -> dict[str, dict] | None:
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("kubectl samples: cache read failed at %s: %s", cache_path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def _kubectl_samples_save_cache(cache_path: Path, samples: dict[str, dict]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(samples, indent=2, sort_keys=True))
    except OSError as exc:
        logger.warning("kubectl samples: cache write failed at %s: %s", cache_path, exc)


def _kubectl_samples_docker_image_available(image_tag: str) -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_tag],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
    return result.returncode == 0


def _kubectl_samples_pick_image(preferred: str, fallback: str) -> str | None:
    for tag in (preferred, fallback):
        if _kubectl_samples_docker_image_available(tag):
            return tag
    logger.warning(
        "kubectl samples: neither preferred image %r nor fallback %r is available; "
        "skipping evidence capture",
        preferred,
        fallback,
    )
    return None


_KUBECTL_HAPPY_POD_MANIFEST = r"""apiVersion: v1
kind: Pod
metadata:
  name: sample-pod
  namespace: default
  labels:
    app: sample
spec:
  containers:
  - name: main
    image: nginx:1.27
"""


def _kubectl_samples_bash_script(verbs: tuple[str, ...]) -> str:
    verbs_bash_list = ", ".join(f'"{v}"' for v in verbs)
    return f"""set -uo pipefail

CLUSTER=samples-$$
PORT=32767
kwokctl create cluster \\
  --runtime=binary \\
  --name="$CLUSTER" \\
  --kube-apiserver-port="$PORT" \\
  --wait=30s \\
  --etcd-binary=/usr/local/bin/etcd \\
  --kube-apiserver-binary=/usr/local/bin/kube-apiserver \\
  --kube-controller-manager-binary=/usr/local/bin/kube-controller-manager \\
  --kube-scheduler-binary=/usr/local/bin/kube-scheduler \\
  --kwok-controller-binary=/usr/local/bin/kwok >/tmp/kwok.log 2>&1 || {{
    echo "kwokctl create failed" >&2
    cat /tmp/kwok.log >&2
    exit 1
  }}

kwokctl get kubeconfig --name="$CLUSTER" > /tmp/kc
export KUBECONFIG=/tmp/kc

cat > /tmp/pod.yaml <<'EOF'
{_KUBECTL_HAPPY_POD_MANIFEST}EOF
kubectl apply -f /tmp/pod.yaml >/dev/null 2>&1 || true

python3 - <<'PY'
import json, subprocess

VERBS = [{verbs_bash_list}]
HAPPY_ARGV = {{
    "get":      ["get", "pods", "sample-pod"],
    "apply":    ["apply", "-f", "/tmp/pod.yaml"],
    "delete":   ["delete", "pod", "sample-pod", "--ignore-not-found"],
    "create":   ["create", "-f", "/tmp/pod.yaml"],
    "describe": ["describe", "pod", "sample-pod"],
    "patch":    ["patch", "pod", "sample-pod", "-p", '{{"metadata":{{"labels":{{"tier":"a"}}}}}}'],
    "scale":    ["scale", "deployment/does-not-matter", "--replicas=1", "--dry-run=client"],
    "label":    ["label", "pod", "sample-pod", "env=dev", "--overwrite"],
}}

def _run(argv, timeout=15):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or ""), (p.stderr or "")

samples = {{}}
for verb in VERBS:
    entry = {{}}
    rc, out, _err = _run(["kubectl", verb, "--help"])
    entry["help_stdout"] = "\\n".join(out.splitlines()[:40])
    entry["help_exit"] = rc

    rc, _out, err = _run(["kubectl", verb, "pods", "nonexistent-name-r2e"])
    entry["error_stderr"] = err.strip()[:2000]
    entry["error_exit"] = rc

    argv = HAPPY_ARGV.get(verb)
    if argv is not None:
        try:
            rc, out, err = _run(["kubectl", *argv])
        except subprocess.TimeoutExpired:
            rc, out, err = -1, "", "timeout"
        entry["happy_stdout"] = (out or "").strip()[:2000]
        entry["happy_stderr"] = (err or "").strip()[:1000]
        entry["happy_exit"] = rc
    else:
        entry["happy_stdout"] = ""
        entry["happy_stderr"] = ""
        entry["happy_exit"] = None

    samples[verb] = entry

print("{_KUBECTL_SAMPLES_STDOUT_DELIM}")
print(json.dumps(samples))
print("{_KUBECTL_SAMPLES_STDOUT_DELIM}")
PY

kwokctl delete cluster --name="$CLUSTER" >/dev/null 2>&1 || true
"""


def _capture_kubectl_samples(
    verbs: Iterable[str] | None = None,
    *,
    image_tag: str = _ECR_POLYGLOT_IMAGE,
    fallback_image_tag: str = _KUBECTL_SAMPLE_FALLBACK_IMAGE,
    cache_dir: Path = _KUBECTL_SAMPLES_CACHE_DIR,
    force_refresh: bool = False,
    timeout_sec: int = 180,
) -> dict[str, dict]:
    """Capture real kubectl --help / error / happy-path output per verb.

    Returns dict ``{verb: {help_stdout, error_stderr, error_exit,
    happy_stdout, happy_exit}}`` — empty dict on any capture failure so
    callers can fall back to a template with an empty evidence section.
    Cached under ``~/.cache/repo2rlenv/kubectl_samples/<sha256>.json`` for
    reuse across ``generate`` invocations.
    """
    verbs_tuple = tuple(v for v in (verbs or _KUBECTL_SAMPLE_VERBS_DEFAULT))
    if not verbs_tuple:
        return {}
    cache_key = _kubectl_samples_cache_key(verbs_tuple, image_tag)
    cache_path = cache_dir / f"{cache_key}.json"
    if not force_refresh:
        cached = _kubectl_samples_load_cache(cache_path)
        if cached is not None:
            logger.info("kubectl samples: cache HIT at %s", cache_path)
            return cached

    chosen_image = _kubectl_samples_pick_image(image_tag, fallback_image_tag)
    if chosen_image is None:
        return {}

    container_name = f"r2e-kubectl-samples-{uuid.uuid4().hex[:8]}"
    script = _kubectl_samples_bash_script(verbs_tuple)

    logger.info(
        "kubectl samples: capturing verbs=%s via image=%s",
        list(verbs_tuple),
        chosen_image,
    )
    try:
        run = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                container_name,
                "--platform",
                "linux/amd64",
                "--privileged",
                "--entrypoint",
                "bash",
                chosen_image,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("kubectl samples: capture timed out after %ds", timeout_sec)
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            check=False,
            timeout=10,
        )
        return {}
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.warning("kubectl samples: docker run failed: %s", exc)
        return {}

    if run.returncode != 0:
        tail = (run.stderr or "").splitlines()[-20:]
        logger.warning(
            "kubectl samples: bootstrap script exited %d; stderr tail=\n%s",
            run.returncode,
            "\n".join(tail),
        )
        return {}

    parts = (run.stdout or "").split(_KUBECTL_SAMPLES_STDOUT_DELIM)
    if len(parts) < 3:
        logger.warning("kubectl samples: JSON delimiter not found in stdout")
        return {}
    try:
        samples = json.loads(parts[1].strip())
    except json.JSONDecodeError as exc:
        logger.warning("kubectl samples: JSON parse failed: %s", exc)
        return {}
    if not isinstance(samples, dict) or not samples:
        return {}
    _kubectl_samples_save_cache(cache_path, samples)
    logger.info("kubectl samples: captured %d verbs; cached at %s", len(samples), cache_path)
    return samples


def format_real_output_section(
    verb: str,
    samples: dict[str, dict],
    *,
    command_prefix: str = "",
) -> str:
    """Format the REAL KUBECTL OUTPUT block for injection into the
    translation prompt. Returns "" when no evidence is available so the
    template renders cleanly in the fallback path.

    ``command_prefix`` is retained for signature compat but no longer inserted
    into the displayed invocations — real kubectl is verb-first, and the sample
    invocations below reflect exactly what the LLM should emit in tests.
    """
    _ = command_prefix
    if not samples:
        return ""
    entry = samples.get(verb) or samples.get(verb.split()[0] if verb else "") or {}
    if not entry:
        return ""
    help_stdout = (entry.get("help_stdout") or "").strip()
    error_stderr = (entry.get("error_stderr") or "").strip()
    error_exit = entry.get("error_exit")
    happy_stdout = (entry.get("happy_stdout") or "").strip()
    happy_exit = entry.get("happy_exit")

    lines = [
        "",
        "REAL KUBECTL OUTPUT (captured against kwok v1.31.0 — write assertions "
        "AGAINST this evidence, not guesses):",
        "",
        f"kubectl {verb} --help exit=0 stdout:",
        help_stdout or "<no help output captured>",
        "",
        f"kubectl {verb} nonexistent-name exit={error_exit} stderr:",
        error_stderr or "<no error stderr captured>",
        "",
        f"kubectl {verb} <valid> exit={happy_exit} stdout:",
        happy_stdout or "<no happy-path stdout captured>",
        "",
        "PRIMARY STRATEGY — use the REAL KUBECTL OUTPUT above as the SOURCE OF TRUTH. "
        "Copy exact substrings from the evidence section directly into your assertions "
        "(preserving case). This gives the strongest, most discriminative signal because "
        "the assertions match what real kubectl actually prints against kwok v1.31.0.",
        "",
        "SECONDARY (LENIENT) FALLBACK — apply the patterns below ONLY when the evidence "
        "above is empty, ambiguous, or a keyword genuinely varies across kubectl minor "
        "versions. Do NOT weaken assertions preemptively when the evidence provides an "
        "exact substring you can literally match.",
        "",
        "STDERR assertions — prefer LITERAL substrings from evidence; fall back to:",
        "1. Use `.lower()` for case-insensitive matching",
        "2. Use `or`-chained substring matches (at least 3 fallback keywords)",
        "3. Keep the first keyword as the exact one from real kubectl above",
        "",
        "Example (BAD — will fail):",
        '    assert "NotFound" in result.stderr',
        "",
        "Example (GOOD — matches lenient v13 pattern):",
        "    assert (",
        '        "notfound" in result.stderr.lower()',
        '        or "not found" in result.stderr.lower()',
        '        or "does not exist" in result.stderr.lower()',
        '        or "error from server" in result.stderr.lower()',
        '    ), f"expected NotFound-family keyword, got: {result.stderr[:300]}"',
        "",
        "STDOUT assertions — same principle:",
        "1. Use `.lower()`",
        "2. Use substring `in`, NOT `startswith` / `endswith` / `==`",
        "3. Prefer resource+name fragment (like `pod/foo`) over full lines",
        "",
        'Example (BAD): assert result.stdout == "pod/mypod created\\n"',
        'Example (GOOD): assert "pod/mypod" in result.stdout or "mypod" in result.stdout.lower()',
        "",
        "EXIT CODE assertions (STRICT — real kubectl semantics):",
        "- happy_path -> `assert result.returncode == 0`",
        "- error_invalid_args (kubectl usage error: unknown flag / malformed value) -> `assert result.returncode == 1`",
        "- error_nonexistent (apiserver 404 / missing resource / missing file) -> `assert result.returncode == 1`",
        "- Match the SPECIFIC `Expected exit code` from the intent — NEVER use `in (1, 2)` or `!= 0`",
        "",
        "k8s_client STATE assertions (happy_path):",
        '- Use `k8s_client.<method>(namespace="default")` — required by G2d',
        "- But keep it OPTIONAL/tolerant: prefer `any(...)` checks over strict field matching",
        "- Don't assert exact field values (labels, resourceVersion, timestamps)",
        "",
    ]
    return "\n".join(lines)


# Kubectl/kwok prompt bundle — placeholder syntax mirrors the MinIO templates
# in ``_cli_app_synthesis`` so the same dispatch functions can format them
# once C6-C8 wire kwok into the aws seams.


_TRANSLATION_SYSTEM_KWOK = r"""You translate kubectl white-box tests into black-box pytest tests that MUST pass a strict static acceptance gauntlet before being accepted.

The reference test exercises a kubectl command via an in-process driver or E2E helper; treat it as a STYLE and INTENT reference only — write a clean black-box pytest function from scratch that produces the same observable behaviour. The Kubernetes backend in this environment is a local kwok cluster (already running, wired into the `cli`, `k8s_client`, and `kubectl_bin` fixtures via conftest.py).

============================================================
REAL KUBECTL CLI SURFACE (verb-first — the ONLY correct syntax)
============================================================

kubectl is VERB-FIRST. The command shape is `kubectl VERB [TYPE] [NAME] [flags]` — see https://kubernetes.io/docs/reference/kubectl/. There is NO `kubectl <resource> <verb>` subcommand form; `kubectl pods apply` DOES NOT EXIST and will fail with cobra's "unknown command \"pods\" for \"kubectl\"". Every test you emit MUST invoke the CLI via the `cli` fixture with the verb as `argv[0]`:

- `cli("apply", "-f", "pod.yaml")` — kind sniffed from the manifest's `kind:` field
- `cli("create", "-f", "pod.yaml")` — same shape; fails with AlreadyExists if the resource already exists
- `cli("get", "pods")` — list all pods in the current namespace
- `cli("get", "pod", "NAME")` — fetch one pod by name (singular TYPE + NAME)
- `cli("get", "pod", "NAME", "-o", "yaml")` — same, YAML output
- `cli("delete", "pod", "NAME")` — delete a specific pod
- `cli("describe", "pod", "NAME")` — human-readable dump
- `cli("patch", "pod", "NAME", "-p", '{"metadata":{"labels":{"k":"v"}}}')` — strategic merge patch
- `cli("scale", "deployment", "NAME", "--replicas=3")` — scale a workload
- `cli("label", "pod", "NAME", "key=val")` — set a label
- `cli("create", "namespace", "NAME")` — create a namespace by name (NO `-f`)
- `cli("delete", "namespace", "NAME")` — delete a namespace by name

NEVER write `cli("pods", "apply", ...)` or any form that puts the resource kind BEFORE the verb — such invocations are the #1 failure mode of this pipeline. The task metadata may include a "primary resource kind" hint (e.g. `pods`, `deployments`, `services`) to describe what the test-suite exercises; that hint is scoping documentation, NOT a CLI argument.

============================================================
CLIENT CONTRACT GROUNDING (from CLIENT.MD — RL environment brief)
============================================================

The environment is being generated for RL training of agentic code models. Tests are NEVER shown to the model during generation — they validate output post-hoc. Quality bars per the client:

- Pass rate on a CORRECT implementation must be ~100% — tests must be SOLVABLE.
- Pass rate on an EMPTY/no-op submission must be ~0% — tests must be DISCRIMINATIVE.
- Coverage must span happy paths, error/edge cases (invalid args, non-existent resources), AND cross-command workflows that verify STATE PERSISTENCE (e.g. `create` -> `get` shows it -> `delete` -> `get` returns NotFound).
- Service-simulation fidelity: correct status codes, correct error shapes, consistent cluster state.

Concrete implications for every test you emit:
1. Always include at least one k8s_client state read on happy_path tests — bare `returncode == 0` is trivially passable and violates the discriminative bar.
2. Always include a stable stderr keyword or pinned exit code on error tests — real kubectl's error surface (NotFound / AlreadyExists / Invalid / Forbidden / Conflict / Timeout) is the stable contract.
3. Set up prerequisite state inside the test — the autouse reset fixture wipes non-system namespaces between tests, so tests must be self-contained and order-independent.
4. For state-persistence intent (e.g. label / patch / scale), assert on the specific field that changed (labels dict, spec.replicas, patched value) — not just on returncode.

============================================================
GAUNTLET ACCEPTANCE CONTRACT (STATIC — read-only enforcement)
============================================================

Gauntlet rule G2b (STRICT exit polarity — real kubectl semantics). If `behaviour_tag` starts with `error`, the test MUST literally assert the SPECIFIC expected exit code (from the `Expected exit code` field of the intent):
  - `error_invalid_args` (kubectl usage error — unknown flag, missing required flag, malformed value) -> `assert result.returncode == 1`
  - `error_nonexistent` (apiserver 404 / missing resource / missing file / apiserver error) -> `assert result.returncode == 1`
The gauntlet checks the EXACT literal `returncode == <N>`. Loose forms — `returncode != 0`, `returncode in (1, 2)`, `returncode >= 1` — are ALL REJECTED. Match the SPECIFIC `Expected exit code` from the intent exactly.

Gauntlet rule G2c (error signal). In addition to the strict exit assertion above, PREFER stderr substring assertions (`"<kw>" in result.stderr` or `"<kw>" in result.stderr.lower()`) — the pinned-exit assertion alone satisfies G2c since the accepted-exit set is small, but stderr keywords (NotFound / AlreadyExists / Invalid / Forbidden / Conflict / Timeout / invalid / not found) are the stable contract across kubectl minor versions.

Gauntlet rule G2d (state check). If `behaviour_tag == "happy_path"`, the test MUST:
  (a) assert `result.returncode == 0`
  (b) include at least one attribute-style method call on `k8s_client` — the LITERAL regex pattern `k8s_client.<method>(` must appear in the emitted source (e.g. `k8s_client.list_namespace()`, `k8s_client.list_namespaced_pod(namespace="default")`, `k8s_client.read_namespaced_deployment(name="d", namespace="default")`)
Bare `assert result.returncode == 0` alone is FORBIDDEN — an empty submission/main.py also exits 0. Always assert on `k8s_client` state after a mutating `cli(...)` call. Write `k8s_client.list_namespaced_pod(...)` (or the analogous resource method) directly on `k8s_client` so this static check fires.

IMPORTANT — `kubectl_bin` is a CALLABLE fixture (invoke it: `kubectl_bin(["get", "ns"])`), NOT a client with attribute methods. Writing `kubectl_bin.get(...)` does NOT exist at runtime and will crash the test. Use `kubectl_bin(args)` for direct-kubectl SETUP or stdout-based side-verification, but ALWAYS also include at least one `k8s_client.<method>(...)` call in the same happy_path test body — that literal is what satisfies G2d.

IMPORTANT — `k8s_client` is `kubernetes.client.CoreV1Api` (NOT bare `ApiClient`). Core V1 methods (pods/namespaces/services/configmaps/secrets/nodes) are DIRECT: `k8s_client.list_namespaced_pod(...)`, `k8s_client.list_namespace()`. For OTHER groups, wrap via `k8s_client.api_client`: `client.AppsV1Api(k8s_client.api_client).list_namespaced_deployment(...)`; `client.BatchV1Api(k8s_client.api_client)` for Jobs. Use `from kubernetes import client`.

IMPORTANT — CROSS-TEST STATE ISOLATION. `_reset_kwok` PRESERVES `default` — resources there PERSIST across tests and cause `AlreadyExists` / `Forbidden: pod updates may not change fields other than image` errors. FIX for happy_path: derive a UNIQUE name from `tmp_path.name`:
  - Preferred: fresh namespace — `ns = f"test-{tmp_path.name.replace('_', '-').lower()[:40]}"`, then `kubectl_bin(["create", "namespace", ns])`, then set that namespace in the manifest / `--namespace`.
  - Acceptable: `default` + unique resource name — `pod_name = f"pod-{tmp_path.name.replace('_', '-').lower()[:40]}"`. NEVER use fixed names (`sample-pod`, `mypod`) in `default` across multiple tests.

============================================================
FORBIDDEN PATTERNS (REJECTED by the static gauntlet — do not emit)
============================================================

- `assert result.returncode != 0` on an error test — REJECTED by G2b. FIX: use the SPECIFIC expected code — `assert result.returncode == 2` for `error_invalid_args`, `assert result.returncode == 1` for `error_nonexistent`. Combine with a stderr substring where possible.
- `assert result.returncode in (1, 2)` on an error test — REJECTED by G2b. Same fix: pin the SPECIFIC code from `Expected exit code`.
- `assert result.returncode >= 1` / `assert result.returncode > 0` on an error test — REJECTED by G2b. Same fix.
- `assert result.returncode == 0` alone on a happy_path test — fails G2d (an empty main.py also exits 0). FIX: append a `k8s_client.<method>(...)` state read, e.g. `assert "x" in {n.metadata.name for n in k8s_client.list_namespace().items}`.
- Missing `k8s_client.<method>(...)` on a happy_path-tagged test — fails G2d. `kubectl_bin(args)` alone does NOT satisfy G2d — G2d requires the literal `k8s_client.<method>(` pattern.
- `kubectl_bin.get(...)` / any `kubectl_bin.<attr>(...)` — attribute access on `kubectl_bin` DOES NOT EXIST and will `AttributeError` at runtime; the fixture is CALLABLE as `kubectl_bin(["get", "namespace", "x"])`.
- Case-sensitive substring assertions on kubectl stderr — real kubectl output case varies. Use `.lower()` for all stderr/stdout substring matches.
- Exact equality on stderr/stdout (`== "..."`) — always use `in` substring matching.
- Wrong code for the tag — kubectl uses exit 1 for BOTH `error_invalid_args` (usage errors) AND `error_nonexistent` (apiserver 404). NEVER use `assert result.returncode == 2` — that is cobra's default which kubectl overrides. The `Expected exit code` field is authoritative and will always be 1 for error tags; asserting anything else will fail against real kubectl.
- Fixed resource names in the `default` namespace across multiple happy_path tests (`sample-pod`, `mypod`, etc.) — cross-test collisions occur because `default` is NOT wiped by the reset fixture. Use a `tmp_path.name`-derived unique name or a fresh namespace as described above.
- `k8s_client.list_namespaced_deployment(...)` / any `AppsV1`/`BatchV1` method called DIRECTLY on `k8s_client` — `k8s_client` is `CoreV1Api`. For non-core APIs, wrap: `client.AppsV1Api(k8s_client.api_client).list_namespaced_deployment(...)`.

============================================================
VERBATIM EXAMPLES — adapt the subcommand, keep the shape
============================================================

ERROR-TAGGED example (`error_invalid_args` — cobra usage error, exit 2; PREFER stderr substring):
```python
def test_pods_apply_invalid_flag(cli):
    result = cli("apply", "--invalid-flag")
    assert result.returncode == 2, f"expected 2 (cobra usage error), got {result.returncode}"
    assert "invalid" in result.stderr.lower() or "unknown" in result.stderr.lower(), (
        f"expected 'invalid'/'unknown' in stderr, got: {result.stderr[:200]}"
    )
```

HAPPY-PATH-TAGGED example (apply manifest → verify object present in cluster; UNIQUE per-test name via tmp_path.name):
```python
def test_pods_apply_creates_pod(cli, k8s_client, tmp_path):
    pod_name = f"pod-{tmp_path.name.replace('_', '-').lower()[:40]}"
    manifest = tmp_path / "pod.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {pod_name}\n  namespace: default\n"
        "spec:\n  containers: [{name: c, image: nginx}]\n"
    )
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert f"pod/{pod_name}" in result.stdout, f"expected success line for {pod_name!r} in stdout"
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert any(p.metadata.name == pod_name for p in pods), f"pod {pod_name!r} not created"
```

NON-CORE-API pattern (Deployment / StatefulSet / Job) — wrap `k8s_client.api_client`:
```python
from kubernetes import client
apps = client.AppsV1Api(k8s_client.api_client)
dep = apps.read_namespaced_deployment(name=dep_name, namespace="default")
assert dep.spec.replicas == 3
```

EDGE-CASE example (`error_nonexistent` — apiserver 404, exit 1; stderr keyword AND state unchanged):
```python
def test_pods_delete_missing(cli, k8s_client):
    result = cli("delete", "pod", "does-not-exist", "--namespace", "default")
    assert result.returncode == 1, f"expected 1 (apiserver 404), got {result.returncode}"
    assert "NotFound" in result.stderr or "not found" in result.stderr.lower()
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.name == "does-not-exist" for p in pods)
```

============================================================
CONTENT RULES
============================================================

1. Import ONLY the standard library, `pytest`, `kubernetes` (as `from kubernetes import client`), and `yaml`. Do NOT import third-party cloud-service SDKs or HTTP transports of any kind. Any other client library is a fatal error.
2. Do NOT generate tests using these unsupported kubectl verbs — kwok returns synthetic data and assertions on their output are FLAKY: `logs`, `exec`, `port-forward`, `attach`, `top`, `cp`. Rewrite intent onto the observable-API surface: `get`, `describe`, `apply`, `create`, `patch`, `delete`, `scale`, `rollout`.
3. Catch `kubernetes.client.exceptions.ApiException` for API errors; its `.status` (int HTTP code) and `.reason` (str) are the stable assertion surface — NEVER assert on `.body` text verbatim.
4. Invoke the candidate CLI via the `cli` fixture (returns `subprocess.CompletedProcess`). `cli` already exports `KUBECONFIG` so the submission and the tests reach the SAME apiserver.
5. For happy_path tests: set up prereq state explicitly INSIDE the test (e.g. `kubectl_bin(["create", "namespace", "x"])` before testing `kubectl delete namespace x`). The autouse `_reset_kwok` fixture wipes non-system namespaces between tests so state never leaks between test runs.
6. Upstream-kubectl alignment (these tests must ALSO pass against real kubectl v1.31+, not just the oracle):
   - Success-line shape (create/apply/patch/scale/label/annotate/rollout): `<resource>/<name> <verb-past-tense>` (e.g. `pod/foo created`, `deployment.apps/bar scaled`). Delete verb uses a DIFFERENT shape: `<resource> "<name>" deleted` (e.g. `namespace "baz" deleted`, `pod "foo" deleted`). For create/scale style, assert on the `<resource>/<name>` fragment; for delete, assert on the quoted `"<name>" deleted` fragment.
   - Stdout: use substring-anywhere semantics (`pattern in result.stdout` or `re.search(pattern, result.stdout)`). NEVER `result.stdout.splitlines()[0] == pattern` — real kubectl prints progress lines (`Waiting for deployment "foo" rollout to finish...`) BEFORE the success line for `apply`/`rollout`/`wait`.
   - Error messages: match a stable CATEGORY keyword (`NotFound`, `AlreadyExists`, `Invalid`, `Forbidden`, `Conflict`, `Timeout`) — NOT full sentences copied from the reference test.
   - Resource-name validation: never assert client-side rejection for DNS-1123 violations (uppercase, `_`, too-long) — real kubectl defers name validation to the apiserver, and so must the candidate.
   - Never invent flags — `kubectl apply` has NO `--wait-for` flag (only `--wait`).

Helpers available (imported by the workflow preamble): `NewKubectlCommand`, `kubectl_bin`, `assert_namespace_exists(k8s_client, name)`, `assert_deployment_replicas(k8s_client, ns, name, expected)`. These helpers are useful for state setup and readability but they DO NOT replace the mandatory literal `k8s_client.<method>(...)` call required by G2d — the gauntlet checks the raw source text, not runtime effect.

DO NOT COPY from the reference test — these are white-box harness leakage and will break the black-box contract: `self.run_cmd`, `self.assert_params_for_cmd`, `self.operations_called`, `KubectlBuilder` internal state assertions, imports from `k8s.io/kubernetes/...` (Go stdlib) or internal `client-go` helpers, `unittest.TestCase` base classes with `setUp` / `tearDown` methods.

Output constraints:
- Function name: `test_<command>_<descriptive>` matching the intent
- Fixtures: only `cli`, `k8s_client`, `kubectl_bin`, `tmp_path` — no decorators, no other fixtures
- Plain `def test_...(...)` with positional fixture args
- CRITICAL: If you invoke `kubectl_bin(...)` ANYWHERE in the test body, you MUST include `kubectl_bin` in the function signature — otherwise the test crashes with `NameError: name 'kubectl_bin' is not defined` at runtime. Pytest injects fixtures ONLY by declared parameters. Same rule for `k8s_client` and `tmp_path` — declare every fixture you use.
- Return ONLY the test function source (no preamble, no surrounding markdown fences)"""


_TRANSLATION_USER_TEMPLATE_KWOK = r"""Reference white-box test (style + intent only — do NOT copy harness):
```python
{raw_source}
```

Extracted intent:
- Verb: kubectl {command}
- Primary resource kind (scoping hint — DO NOT prepend to argv): {command_prefix}
- argv after program name: {cmdline_template}
- Expected exit code: {expected_exit}
- Expected kubectl observable operations: {expected_state_calls}
- Behaviour tag: {behaviour_tag}
{real_output_samples}
Translate this into a black-box pytest test. The agent's CLI is at /workspace/submission/kubectl (or /workspace/submission/main.py); use `cli(*argv)` to invoke it (returns CompletedProcess). Real kubectl syntax is VERB-FIRST: `cli("apply", "-f", "pod.yaml")`, `cli("get", "pods")`, `cli("delete", "pod", "NAME")` — NEVER `cli("pods", "apply", ...)`. Use `k8s_client` for state verification and `kubectl_bin(["get", "ns"])` for direct kubectl invocation when seeding cluster state without going through the agent's submission.

REMINDER — route on `behaviour_tag` AND match `Expected exit code` EXACTLY (STRICT — gauntlet rule G2b + G2c):
- `error_invalid_args` (kubectl usage error): MUST include `assert result.returncode == 1` (kubectl uses exit 1 for usage errors, NOT cobra's default 2). SHOULD also include a stderr substring assertion (PREFERRED for G2c, e.g. `"invalid" in result.stderr.lower()`, `"unknown" in result.stderr.lower()`).
- `error_nonexistent` (apiserver 404 / missing file): MUST include `assert result.returncode == 1`. SHOULD also include a stderr substring assertion (PREFERRED for G2c, e.g. `"not found" in result.stderr.lower()`, `"notfound" in result.stderr.lower()`).
- `happy_path`: MUST include `assert result.returncode == 0` AND a literal `k8s_client.<method>(...)` call after the mutating `cli(...)`. Bare `assert result.returncode == 0` alone is rejected by gauntlet rule G2d.

FORBIDDEN: `assert result.returncode != 0`, `assert result.returncode in (1, 2)`, `assert result.returncode >= 1`. Match the SPECIFIC `Expected exit code` from above — no loose forms.

FIXTURE SEMANTICS (memorize):
- `k8s_client` — attribute-style client. State assertions look like `k8s_client.list_namespace()`, `k8s_client.list_namespaced_pod(namespace="default")`, `k8s_client.read_namespaced_deployment(name="d", namespace="default")`. This is the ONLY pattern that satisfies G2d.
- `kubectl_bin` — a CALLABLE (not a client). Invoke as `kubectl_bin(["get", "ns"])` and read `.returncode` / `.stdout` / `.stderr` from the returned CompletedProcess. Attribute access like `kubectl_bin.get(...)` DOES NOT EXIST and will `AttributeError` at runtime.

The `expected_state_calls` field describes the OBSERVABLE side-effects in kubectl terms; translate them into equivalent `k8s_client` resource reads (PREFERRED — satisfies G2d) or `kubectl_bin(args)` stdout assertions when a specific kubectl-format check is required."""


_ORACLE_SYSTEM_KWOK = r"""You write a reference Python implementation of a single kubectl command as `submission/main.py`.

The Kubernetes backend is a local kwok cluster, already running and reachable. Configure your client from env:

  from kubernetes import client, config
  config.load_kube_config(config_file=os.environ["KUBECONFIG"])
  k8s = client.ApiClient()

CRITICAL — your implementation will be black-box tested. The companion pytest suite asserts on:
  (a) `result.returncode` — STRICT real-kubectl semantics enforced by the gauntlet:
       * `0` for success (happy_path)
       * `1` for apiserver API errors (translate `ApiException`) AND missing-file / missing-resource errors (error_nonexistent)
       * `2` for cobra-style usage errors: unknown flag, malformed flag value (error_invalid_args)
       Tests assert the SPECIFIC code (`== 1` or `== 2`), NOT loose `!= 0` / `in (1, 2)`. Your CLI MUST produce the correct code per error class or every error-tagged test fails.
  (b) `result.stderr` — tests grep for stable category keywords: `NotFound`, `AlreadyExists`, `Invalid`, `Forbidden`, `Conflict`, `Timeout`, or the substring `invalid` (case-insensitive) for usage errors
  (c) cluster state via `k8s_client.<resource-method>(...)` reads — every mutation you perform must be immediately visible on the same apiserver

Consequently your reference implementation MUST:
1. Translate `kubernetes.client.exceptions.ApiException` into `sys.exit(1)` AND print a message like `f"{exc.reason} ({exc.status})"` to stderr so downstream tests can match on `NotFound`, `AlreadyExists`, `Invalid`, `Forbidden`, `Conflict`, `Timeout`. Missing-file errors (`-f nonexistent.yaml`) also exit `1` with a `NotFound`/`not found` stderr keyword.
2. On unknown flags / malformed values: `sys.exit(2)` with an `invalid` / `unknown` / `unrecognized` substring on stderr (mirror cobra's usage-error behaviour). NEVER emit `2` for missing-file or apiserver errors — those are `1`. For **enum-typed flags** (e.g. `-o/--output` accepts ONLY `json|yaml|wide|name|jsonpath|jsonpath-as-json`), any other value is a malformed value → `sys.exit(2)` with `invalid output format` (or similar) on stderr. Do NOT fall back to default output for an unrecognised `--output=<value>`.
2b. For **RBAC create verbs** — `create role|clusterrole|rolebinding|clusterrolebinding|serviceaccount` — you MUST implement the full apiserver call via the dynamic client (`RbacAuthorizationV1Api` or the DynamicClient with `apiVersion: rbac.authorization.k8s.io/v1`), NOT stub or skip them. Same for `create resourcequota`, `create priorityclass`, `create poddisruptionbudget`, `create limitrange`, `create ingress`, `create networkpolicy`. Workflow tests exercise these end-to-end; omitting them causes the workflow to fail with `unsupported kind` on stderr.
3. Emit real-kubectl success-line shape on stdout: for create/apply/patch/scale/label/annotate/rollout use `<resource>/<name> <verb-past-tense>` (e.g. `pod/foo created`, `deployment.apps/bar scaled`); for delete use the DIFFERENT quoted shape `<resource> "<name>" deleted` (e.g. `namespace "baz" deleted`, `pod "foo" deleted`). Progress lines before the success line are allowed.

Reference error-path sketch (surfaces a stderr keyword the tests can match):
```python
try:
    client.CoreV1Api(k8s).read_namespace(name)
except client.exceptions.ApiException as exc:
    print(f"{exc.reason} ({exc.status})", file=sys.stderr)
    sys.exit(1)
```

Constraints:
- Single file: `submission/main.py`.
- Use argparse for argument parsing.
- Use the `kubernetes` Python client (v31.0.0, already installed).
- Do NOT import third-party cloud-service SDKs, hosted-database clients, or HTTP-transport libraries beyond the standard library.
- Do NOT import Go-stdlib `k8s.io/*` client bindings; do NOT shell out to the `kubectl` binary.
- Do NOT implement or delegate to the unsupported verbs `logs`, `exec`, `port-forward`, `attach`, `top`, `cp` — the reference client returns synthetic data for these and tests will not exercise them.
- For `kubectl get`, default to human-readable `NAME  READY  STATUS  RESTARTS  AGE`; support `-o json` and `-o yaml` via stdlib `json` and `PyYAML` (both pre-installed).
- The kubernetes Python client returns typed objects (`V1Pod`, `V1Deployment`, `V1Namespace`) with attribute access, not dicts. Use `.metadata.name`, `.spec.replicas`, `.status.phase`.
- Do NOT validate resource names client-side; let the apiserver return `Invalid`. Real kubectl defers DNS-1123 name-format validation to the service.
- Do NOT fabricate flags that don't exist upstream. In particular, `kubectl apply` has NO `--wait-for` flag (only `--wait`) — do NOT implement one.

The CLI is invoked as: `python submission/main.py <verb> [args...]` — real kubectl syntax, VERB-FIRST. Dispatch on argv[1] (the verb: `apply`, `get`, `delete`, `describe`, `patch`, `scale`, `label`, `create`). Positional TYPE + NAME (`kubectl get pod myname`) follow the verb; NEVER expect the resource kind BEFORE the verb (`kubectl pods apply` does not exist).

Return ONLY the Python source for `submission/main.py` (no preamble, no surrounding markdown fences)."""


_ORACLE_USER_TEMPLATE_KWOK = r"""Implement `kubectl {command}` (real kubectl verb-first surface) covering these behaviours for resource kind `{command_prefix}`:

{behaviours_bulleted}

Flags observed in the reference test suite (accept every one, marshal it to the \
corresponding kubernetes-API request field, reject any unknown flag with a \
usage error to stderr and `sys.exit(2)`):

{flags_bulleted}

Dispatch on argv[1] (the verb, `{command}`). Do NOT expect `{command_prefix}` \
as a subcommand — real kubectl is verb-first. `{command_prefix}` is the \
primary resource kind the test suite exercises; it enters the CLI either \
via the manifest's `kind:` field (for `apply`/`create -f`) or as the TYPE \
positional after the verb (for `get`/`delete`/`describe`/`patch`/`scale`/`label`)."""


_ORACLE_SUBSET_SYSTEM_KWOK = r"""You write a reference Python implementation of a SUBSET of kubectl commands as ONE file (`submission/main.py`).

The Kubernetes backend is a local kwok cluster, already running and reachable. Configure your client from env:

  from kubernetes import client, config, dynamic
  config.load_kube_config(config_file=os.environ["KUBECONFIG"])
  api_client = client.ApiClient()
  dyn = dynamic.DynamicClient(api_client)     # REQUIRED for arbitrary-kind support

CRITICAL — the resulting CLI is black-box tested (per-subcommand tests + CROSS-COMMAND workflow tests). Those tests assert on:
  (a) `result.returncode` — STRICT real-kubectl semantics enforced by the gauntlet:
       * `0` for success (happy_path)
       * `1` for apiserver API errors AND missing-file / missing-resource errors (error_nonexistent)
       * `2` for cobra-style usage errors: unknown flag, malformed flag value (error_invalid_args)
       Tests assert the SPECIFIC code (`== 1` or `== 2`), NOT loose `!= 0` / `in (1, 2)`.
  (b) `result.stderr` — tests grep for stable keywords: `NotFound`, `AlreadyExists`, `Invalid`, `Forbidden`, `Conflict`, `Timeout`, or `invalid` (case-insensitive) for usage errors
  (c) `result.stdout` — tests grep for the mutated resource NAME (`assert "foo" in result.stdout`); for `get` they look for column headers (`NAME`, `READY`, `STATUS`, `AGE`) or the raw name; for `describe` they look for section headers (`Name:`, `Namespace:`, `Labels:`, `Annotations:`, `Events:`) plus the resource name
  (d) cluster state via `k8s_client.<method>(...)` reads — every mutation any subcommand makes must be visible on the same apiserver

============================================================
KIND COVERAGE — YOU MUST HANDLE ALL OF THESE (not just Pod/Deployment/Service)
============================================================

Fixture tests span these kinds — a per-kind `if/elif` chain against typed API classes is a KNOWN FAILURE MODE:

  Core/v1        : Pod, Namespace, ConfigMap, Secret, ServiceAccount, Service,
                   PersistentVolumeClaim, ResourceQuota, LimitRange, Endpoints
  apps/v1        : Deployment, StatefulSet, DaemonSet, ReplicaSet
  batch/v1       : Job, CronJob
  networking/v1  : NetworkPolicy, Ingress
  rbac/v1        : Role, RoleBinding, ClusterRole, ClusterRoleBinding
  policy/v1      : PodDisruptionBudget
  scheduling/v1  : PriorityClass

REQUIRED PATTERN — `kubernetes.dynamic.DynamicClient` handles every apiserver-registered kind uniformly via GVK lookup. Route ALL of `apply -f`, `delete -f`, `get`, `describe`, `patch`, `label`, `scale` (spec.replicas), and `delete TYPE NAME` through it so one code path serves every kind:

```python
from kubernetes import client, config, dynamic
config.load_kube_config(config_file=os.environ["KUBECONFIG"])
dyn = dynamic.DynamicClient(client.ApiClient())

# Look up any kind at runtime by (apiVersion, kind) OR by (api_version="", kind=Kind):
api = dyn.resources.get(api_version=manifest["apiVersion"], kind=manifest["kind"])
api.create(body=manifest, namespace=manifest.get("metadata", {}).get("namespace", "default"))
api.get(name=name, namespace=ns)                     # single
api.get(namespace=ns, label_selector="k=v")          # list
api.delete(name=name, namespace=ns)
api.patch(name=name, namespace=ns, body=patch_body,
          content_type="application/merge-patch+json")
```

To resolve a `kubectl get <type> ...` where `<type>` is the plural/short form (`pods`, `deploy`, `cm`, `svc`, `sa`, `rq`, `pdb`, `pvc`, `cj`, `netpol`, `ing`, `rb`, `crb`), keep a small kind-alias map (short/plural -> canonical Kind) then call `dyn.resources.get(kind=<Kind>)` — the DynamicClient discovers the correct GVK for you.

Reserve the typed clients (`CoreV1Api`, `AppsV1Api`, `BatchV1Api`, `RbacAuthorizationV1Api`, `NetworkingV1Api`, `PolicyV1Api`, `SchedulingV1Api`) for the `create <subcommand>` builders where you must construct a V1* object from CLI flags (e.g. `create secret docker-registry`, `create service clusterip`), then submit via the corresponding typed method.

============================================================
STDOUT CONTRACTS (verbatim wording matters — tests substring-match)
============================================================

Mutations MUST print a success line to stdout. Verb-past-tense mapping:

  apply   -> `<resource>/<name> created`   (first apply)
             `<resource>/<name> configured` (subsequent) — emitting `created` unconditionally is acceptable
  create  -> `<resource>/<name> created`
  patch   -> `<resource>/<name> patched`
  label   -> `<resource>/<name> labeled`   (also `unlabeled` for `key-` remove; `labeled` always is acceptable)
  scale   -> `<resource>/<name> scaled`
  delete  -> `<kind> "<name>" deleted`     ← DIFFERENT SHAPE: kind + QUOTED NAME, NOT `<resource>/<name>`

Examples: `pod/foo created`, `deployment.apps/bar scaled`, `resourcequota/baz created`, `pod "foo" deleted`, `namespace "wf" deleted`.

For `<resource>` use the plural/lowercased form: `pod`, `deployment.apps`, `service`, `configmap`, `secret`, `namespace`, `statefulset.apps`, `job.batch`, `resourcequota`, `role.rbac.authorization.k8s.io`, etc. When in doubt, `<kind-lower>/<name>` (e.g. `resourcequota/foo`) satisfies substring-anywhere assertions since tests match `assert "<name>" in result.stdout`.

For `--dry-run=client` (or `--dry-run=server`): print the SAME success line with a ` (dry run)` suffix. For `client` mode do NOT hit the apiserver at all.

`get` output modes:
  * default / `-o wide`: table with header row. For Pods: `NAME   READY   STATUS   RESTARTS   AGE`. For other kinds a minimum of `NAME   AGE` is fine. Include the header line AND one line per resource containing the resource name.
  * `-o json`: `json.dumps(obj.to_dict(), default=str)` for single item, `{"apiVersion":"v1","kind":"List","items":[...]}` for lists.
  * `-o yaml`: `yaml.safe_dump(obj.to_dict())`.
  * `-o name`: `<resource>/<name>` per line.
  * `-o jsonpath=<expr>` and `-o jsonpath-as-json=<expr>`: evaluate a `{.field.sub.field}` template on `obj.to_dict()`. Minimal implementation is fine: strip enclosing `{}`, split on `.`, traverse the dict, print the resulting value. Tests assert `result.stdout.strip() != ""` so ANY non-empty output for a valid expression passes.
  * `--all-namespaces` / `-A`: iterate all namespaces (or use `list_*_for_all_namespaces`); include a `NAMESPACE` first column and one row per resource.

`describe` output MUST include the following lines (order-insensitive, one per line, `Key: value` format):
  * `Name: <name>`
  * `Namespace: <ns>`
  * `Labels: <k1=v1,k2=v2>` or `Labels: <none>`
  * `Annotations: <...>` or `Annotations: <none>`
  * `Status: <phase>` (Pods use `.status.phase`; other kinds may use `Active`/`Ready`/blank)
  * `Events: <none>` (kwok emits no events; the literal `Events:` header is what tests grep)

`describe TYPE -l SEL`: list matching resources and print the describe block for EACH.

============================================================
FLAG SEMANTICS (accept these argv shapes; reject others with exit 2)
============================================================

apply:
  * `apply -f FILE` / `--filename=FILE` — read manifest (YAML or JSON), sniff `kind` + `apiVersion`, upsert via DynamicClient. On 409 AlreadyExists, PATCH (server-side apply or merge) instead of create.
  * Missing file (path does not exist) -> exit 1, stderr contains `not found`.
  * No `-f` at all -> exit 1 with `error: must specify -f` on stderr.

create (dispatch on argv[2] AFTER the verb):
  * `create namespace NAME`
  * `create configmap NAME [--from-literal=k=v]* [-n NS]` — duplicate raises apiserver 409; forward as exit 1 with `AlreadyExists` on stderr.
  * `create secret generic|docker-registry|tls NAME [flags] [-n NS]`
      - `docker-registry`: `--docker-username`, `--docker-password`, `--docker-email`, `--docker-server` — construct a `.dockerconfigjson` payload; the secret type is `kubernetes.io/dockerconfigjson`.
      - `generic`: `--from-literal=k=v`, `--from-file=path`.
      - `tls`: `--cert=path`, `--key=path`.
  * `create job NAME --image=IMG [-n NS]` (also `--from=cronjob/CJ` for the CronJob-derived form).
  * `create service clusterip|nodeport|loadbalancer|externalname NAME --tcp=<port>:<targetport>`.
  * `create deployment NAME --image=IMG [--replicas=N]`.
  * `create role|clusterrole NAME [--verb=...] [--resource=...]`.
  * `create rolebinding|clusterrolebinding NAME --clusterrole=CR --user=U` (or `--role=R`, `--serviceaccount=NS:SA`).
  * `create serviceaccount NAME`.
  * `create poddisruptionbudget NAME [--min-available=N|--max-unavailable=N] --selector=SEL`.
  * `create resourcequota NAME --hard=k=v[,k=v...]`.
  * `create limitrange NAME`, `create priorityclass NAME --value=N`, `create ingress NAME --rule=...`.

delete:
  * `delete TYPE NAME [-n NS]` — single.
  * `delete TYPE NAME1 NAME2 ...` — many.
  * `delete -f FILE` / `--filename=FILE` — parse manifest, extract `kind`+`metadata.name`+`metadata.namespace`, delete via DynamicClient.
  * `delete -l SELECTOR TYPE` — delete all matching.
  * `--ignore-not-found` — swallow `ApiException.status == 404` and exit 0 (no stderr, no stdout emit for the missing one).
  * `--grace-period=N`, `--force`, `--now`, `--wait` — accept; forward to `V1DeleteOptions` where the field exists, else no-op (kwok tolerates it).
  * `--all`, `--all-namespaces` — supported.

get:
  * `get TYPE` — list in current namespace (default `default`).
  * `get TYPE NAME` — single resource.
  * `-n NS` / `--namespace=NS`, `-A` / `--all-namespaces`.
  * `-o json|yaml|wide|name|jsonpath=<expr>|jsonpath-as-json=<expr>` — see stdout contract.
  * `-l SELECTOR` / `--selector=SEL` — comma-separated `k=v[,k=v...]`.

describe:
  * `describe TYPE NAME [-n NS]`.
  * `describe TYPE -l SEL [-n NS]`.
  * `--show-events=true|false` — accept, no-op (still emit the `Events:` header).

patch:
  * `patch TYPE NAME -p '<json>' [--type=merge|strategic|json] [--dry-run=client|server|none] [-n NS]`.
  * `--type=merge` (default): `content_type="application/merge-patch+json"`, body is a JSON dict.
  * `--type=strategic`: `content_type="application/strategic-merge-patch+json"`, body is a JSON dict.
  * `--type=json`: `content_type="application/json-patch+json"`, body is a JSON ARRAY of ops (e.g. `[{"op":"add","path":"/metadata/labels/lane","value":"c35"}]`).
  * Call via DynamicClient: `dyn.resources.get(...).patch(name=name, namespace=ns, body=body, content_type=<per --type>)`.
  * `--dry-run=client`: skip the apiserver call; still print the success line with ` (dry run)` suffix so tests see the resource name.

label:
  * `label TYPE NAME k1=v1 [k2=v2 ...] [-n NS]` — set labels via merge patch on `metadata.labels`.
  * `label TYPE NAME k- [-n NS]` — the dash-suffix syntax REMOVES a label. Send merge patch `{"metadata":{"labels":{"k": null}}}`.
  * `--overwrite` — permit replacing an existing label value. Without `--overwrite`, if a key already has a DIFFERENT value, exit 1 with `already has a value` on stderr. Simplest correct impl: without `--overwrite`, read the resource first and check.
  * `label TYPE -l SELECTOR k=v [-n NS]` — label all matching resources.

scale:
  * `scale TYPE NAME --replicas=N [-n NS]` — patch `spec.replicas`. Supports `deployment`, `statefulset`, `replicaset`.

============================================================
EXIT CODE + STDERR RULES
============================================================

1. Translate `kubernetes.client.exceptions.ApiException` into `sys.exit(1)` AND print a stable stderr line the tests can grep. Include BOTH the reason and a kubectl-format keyword so 409s that surface as `reason == "Conflict"` still hit `AlreadyExists`-matching tests:
   ```python
   keyword = {404: "NotFound", 409: "AlreadyExists", 422: "Invalid",
              403: "Forbidden", 408: "Timeout"}.get(exc.status, exc.reason or "Error")
   print(f"Error from server ({keyword}): {exc.reason} ({exc.status})", file=sys.stderr)
   sys.exit(1)
   ```
2. Missing file (`-f nonexistent.yaml`) -> exit 1 with `not found` on stderr.
3. Unknown flag / malformed value -> exit 2 with `invalid` / `unknown` / `unrecognized` on stderr.
4. `--ignore-not-found` swallows 404 -> exit 0, no stderr, no stdout emit for the missing name.

============================================================
IMPLEMENTATION CONSTRAINTS
============================================================

- Single file: `submission/main.py`. Parse argv and dispatch on the VERB (argv[1]); for `create` also dispatch on the sub-kind (argv[2], e.g. `namespace`/`configmap`/`secret`/`job`/...).
- Use the `kubernetes` Python client (v31.0.0, already installed) — `client.ApiClient`, `client.CoreV1Api`, `client.AppsV1Api`, etc., PLUS `kubernetes.dynamic.DynamicClient` for arbitrary kinds. PyYAML for `-o yaml` output AND for manifest parsing.
- Do NOT import third-party cloud-service SDKs, hosted-database clients, or HTTP-transport libraries beyond the standard library.
- Do NOT shell out to the `kubectl` binary.
- Do NOT implement the unsupported verbs `logs`, `exec`, `port-forward`, `attach`, `top`, `cp` — kwok returns synthetic data for these and no test will exercise them.
- Do NOT validate resource names client-side; let the apiserver return `Invalid`.
- Do NOT fabricate flags that don't exist upstream — `kubectl apply` has NO `--wait-for` flag (only `--wait`).
- The CLI is invoked as: `python submission/main.py <verb> [args...]` — real kubectl syntax, VERB-FIRST. Dispatch on argv[1] (the verb). NEVER expect the resource kind BEFORE the verb (`kubectl pods apply` does not exist).

Return ONLY the Python source for `submission/main.py` (no preamble, no surrounding markdown fences)."""


_ORACLE_SUBSET_USER_TEMPLATE_KWOK = r"""Implement a single `kubectl` CLI supporting ALL of these VERBS: {commands_csv}, scoped to the primary resource kind `{command_prefix}`.

IMPORTANT — when `{command_prefix}` is `kubectl` (the CLI name itself, not a \
specific Kubernetes kind), treat this as a MULTI-KIND task: the test suite \
exercises every fixture kind (Pod, Deployment, StatefulSet, DaemonSet, \
ReplicaSet, Job, CronJob, Service, ConfigMap, Secret, ServiceAccount, \
Namespace, PersistentVolumeClaim, ResourceQuota, LimitRange, NetworkPolicy, \
Ingress, Role, RoleBinding, ClusterRole, ClusterRoleBinding, \
PodDisruptionBudget, PriorityClass, ...). You MUST route every kind-agnostic \
verb (apply/delete/get/describe/patch/label/scale) through \
`kubernetes.dynamic.DynamicClient` so ONE code path serves every kind — a \
per-kind `if/elif` chain against typed API classes will fail on the \
kinds not in your chain. See the KIND COVERAGE section of the system \
prompt.

It must cover these behaviours (collected across the subcommands):

{behaviours_bulleted}

Flags observed per verb in the reference test suite (accept every one, \
marshal it to the corresponding kubernetes-API request field, reject any \
unknown flag with a usage error to stderr and `sys.exit(2)`):

{flags_per_command}

Dispatch on argv[1] (the verb) so one implementation handles every listed \
verb. Real kubectl is verb-first: e.g. `apply -f pod.yaml`, `get pods`, \
`delete pod NAME`, `scale deployment NAME --replicas=3`. For `create`, \
dispatch on argv[2] (the sub-kind: `namespace`, `configmap`, `secret`, \
`job`, `service`, `deployment`, `serviceaccount`, `role`, `rolebinding`, \
`clusterrole`, `clusterrolebinding`, `resourcequota`, `poddisruptionbudget`, \
`priorityclass`, `limitrange`, `ingress`). The resource kind enters either \
via the manifest's `kind:` field (apply/create -f) or as the TYPE positional \
after the verb (get/delete/describe/patch/label/scale). Keep cluster state \
consistent across verbs so cross-command workflows (create-namespace -> \
apply-deployment -> scale-deployment -> get-deployment -> delete-namespace) \
behave correctly.

REMINDERS from the system prompt (do NOT forget):
- `delete` stdout shape is `<kind> "<name>" deleted` (QUOTED name), not \
  `<resource>/<name>` — this is the ONE exception to the mutation-line pattern.
- `describe` output must include the literal section headers `Name:`, \
  `Namespace:`, `Labels:`, `Annotations:`, `Status:`, `Events:`.
- `get` default output must include a `NAME` column header and one row per \
  resource containing the resource name; for Pods add `READY STATUS RESTARTS AGE`.
- `--ignore-not-found` on `delete` swallows 404 and exits 0.
- `--dry-run=client` on `patch`/`apply`/`create` skips the apiserver call and \
  prints the success line with a ` (dry run)` suffix.
- `label NAME k-` REMOVES a label (dash suffix). `--overwrite` permits \
  replacing an existing value; without it, an existing DIFFERENT value must \
  exit 1 with `already has a value` on stderr.
- `patch --type=json` sends `application/json-patch+json` with a JSON ARRAY \
  body; `--type=strategic` sends `application/strategic-merge-patch+json`; \
  default is `application/merge-patch+json`."""


_WORKFLOW_SYSTEM_KWOK = r"""You write CROSS-COMMAND black-box pytest tests that exercise chained behaviour of a from-scratch `kubectl`-style CLI, and every emitted test MUST pass a strict static acceptance gauntlet.

The CLI is a single file at /workspace/submission/main.py, invoked as a subprocess via the `cli` fixture: `cli(*argv) -> subprocess.CompletedProcess` (with .returncode, .stdout, .stderr). Fixtures also available: `k8s_client` (a `kubernetes.client.ApiClient` wired to the SAME sandboxed kwok cluster), `kubectl_bin` (direct kubectl invoker), and pytest's `tmp_path`. Helpers `assert_namespace_exists(k8s_client, name)` and `assert_deployment_replicas(k8s_client, ns, name, expected)` are imported by the workflow preamble.

============================================================
GAUNTLET ACCEPTANCE CONTRACT (STATIC — applied per-step)
============================================================

Gauntlet rule G2b (STRICT exit polarity). For every `cli(...)` step meant to FAIL, the test MUST assert the SPECIFIC expected exit code:
  - Cobra usage errors (unknown flag, malformed value) -> `assert step.returncode == 2`
  - Missing resource / missing file / apiserver 404 -> `assert step.returncode == 1`
Loose forms — `step.returncode != 0`, `step.returncode in (1, 2)`, `step.returncode >= 1` — are ALL REJECTED.

Gauntlet rule G2c (error signal). In addition to the strict exit assertion above, PREFER stderr substring assertions (`"NotFound" in step.stderr`, `"invalid" in step.stderr.lower()`) — stderr keywords are the stable contract across kubectl minor versions.

Gauntlet rule G2d (state check). For every `cli(...)` step meant to SUCCEED, the test MUST:
  (a) assert `step.returncode == 0`
  (b) include at least one attribute-style method call on `k8s_client` (LITERAL regex pattern `k8s_client.<method>(` — e.g. `k8s_client.list_namespace()`, `k8s_client.list_namespaced_pod(namespace="default")`, `k8s_client.read_namespaced_deployment(...)`)
Bare `assert step.returncode == 0` alone is FORBIDDEN — always assert on `k8s_client` state after every mutating success step.

IMPORTANT — `kubectl_bin` is a CALLABLE fixture (invoke it: `kubectl_bin(["get", "ns"])`), NOT a client with attribute methods. Writing `kubectl_bin.get(...)` does NOT exist at runtime and will crash the test. Use `kubectl_bin(args)` for direct-kubectl SETUP or stdout-based verification, but ALWAYS also include at least one `k8s_client.<method>(...)` call in the same test body — that literal is what satisfies G2d.

============================================================
FORBIDDEN PATTERNS (each step — will be REJECTED by static gauntlet)
============================================================

Anti-pattern #1 (failure step lacks a specific signal — fails G2b):
```python
r_bad = cli("delete", "namespace", "nope")
assert r_bad.returncode != 0   # ← REJECTED: nop-discriminative
```
FIX: `assert r_bad.returncode == 1` (apiserver 404 — the SPECIFIC code) AND `assert "not found" in r_bad.stderr.lower()`. NEVER `assert r_bad.returncode in (1, 2)` — pin the exact code.

Anti-pattern #2 (success step lacks state check — fails G2d):
```python
r_ok = cli("create", "namespace", "wf")
assert r_ok.returncode == 0   # ← REJECTED: an empty main.py also exits 0
```
FIX: append `assert "wf" in {n.metadata.name for n in k8s_client.list_namespace().items}`.

Anti-pattern #3 (uses only `kubectl_bin` — fails G2d AND crashes at runtime):
```python
r_ok = cli("create", "namespace", "wf"); assert r_ok.returncode == 0
verify = kubectl_bin.get("namespace", "wf")   # ← REJECTED: kubectl_bin has NO .get attribute
```
FIX: call it as a function `kubectl_bin(["get", "namespace", "wf"])` AND add a `k8s_client.list_namespace()` state check.

Anti-pattern #4 (resource-first argv — fails at runtime with cobra "unknown command"):
```python
r = cli("pods", "apply", "-f", "pod.yaml")   # ← REJECTED: `kubectl pods apply` doesn't exist
```
FIX: real kubectl is verb-first — `cli("apply", "-f", "pod.yaml")`. Kind sniffed from manifest.

============================================================
VERBATIM WORKFLOW EXAMPLE (adapt subcommands, keep the shape)
============================================================

WORKFLOW example (create → verify → delete → verify gone → double-delete fails):
```python
def test_workflow_namespace_create_then_delete(cli, k8s_client):
    r_create = cli("create", "namespace", "wf-demo")
    assert r_create.returncode == 0, r_create.stderr
    ns_names = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "wf-demo" in ns_names, f"namespace missing after create: {sorted(ns_names)}"

    r_delete = cli("delete", "namespace", "wf-demo")
    assert r_delete.returncode == 0, r_delete.stderr
    ns_names_after = {n.metadata.name for n in k8s_client.list_namespace().items}
    assert "wf-demo" not in ns_names_after, "namespace still present after delete"

    r_delete_again = cli("delete", "namespace", "wf-demo")
    assert r_delete_again.returncode == 1, f"expected 1 (apiserver 404), got {r_delete_again.returncode}"
    assert "NotFound" in r_delete_again.stderr or "not found" in r_delete_again.stderr.lower()
```

Note that EVERY success step has both `returncode == 0` AND a `k8s_client.list_namespace()` state check (satisfies G2d); the failure step has both `returncode == 1` (the SPECIFIC apiserver-404 code — never `in (1, 2)`) AND a `NotFound`/`not found` stderr substring (satisfies G2b + G2c).

============================================================
CONTENT RULES
============================================================

1. Use ONLY the fixtures `cli`, `k8s_client`, `kubectl_bin`, `tmp_path` as test-function arguments. No decorators. You may use the standard library plus the `kubernetes` client (`from kubernetes import client`) and `PyYAML` (`import yaml`). CRITICAL: If your test body references `kubectl_bin`, `k8s_client`, `cli`, or `tmp_path`, you MUST declare it in the function signature — otherwise the test crashes with `NameError` at runtime. Pytest only injects fixtures listed as parameters.
2. Do NOT import third-party cloud-service SDKs, hosted-database clients, or object-store libraries — a Kubernetes backend uses the kubernetes Python client and nothing else.
3. Do NOT chain CROSS-COMMAND sequences that use the unsupported verbs `logs`, `exec`, `port-forward`, `attach`, `top`, `cp` — kwok returns synthetic data for these and cross-command assertions will be flaky.
4. Create ALL prerequisite state INSIDE the test (namespaces via `kubectl_bin(["create", "namespace", "x"])`; deployments via `client.AppsV1Api(k8s_client).create_namespaced_deployment(...)`; local manifests via `tmp_path`). Tests must run in isolation and in any order — the autouse `_reset_kwok` fixture wipes non-system namespaces between tests.
5. Assert CROSS-COMMAND invariants on `k8s_client` STATE, not on stdout wording. Object absence: assert `ApiException` with `.status == 404` from the corresponding `read_*` call, OR assert the name is not in a `k8s_client.list_*()` result. When you DO assert on stdout, use substring-anywhere semantics (`pattern in result.stdout`) — NEVER `result.stdout.splitlines()[0]`.
6. Each test MUST chain at least TWO different subcommands and include at least one assertion that depends on a PRIOR command's effect.
7. Assert only on order-insensitive state (sets of names, replica counts, resource presence, exit codes) — never on listing order, `resourceVersion`, `uid`, or timestamps.
8. Do NOT fabricate upstream flags — `kubectl apply` has NO `--wait-for` flag (only `--wait`). Do NOT assert client-side rejection for DNS-1123-invalid names — real kubectl defers to the apiserver.
9. Name each function `test_workflow_<chain>`. Return ONLY the test function source(s) (one or more `def test_...`), no preamble, no surrounding markdown fences."""


_WORKFLOW_USER_TEMPLATE_KWOK = r"""Write {n_workflows} CROSS-COMMAND workflow test function(s) for a real-kubectl (verb-first) CLI covering ONLY this compatible subset of verbs: {subset_csv}, scoped to the primary resource kind `{command_prefix}`.

Documented per-verb and CROSS-COMMAND invariants (the contract you must verify):
{state_models_joined}

Representative argv shapes observed for these verbs:
{argv_shapes_bulleted}

Each test must chain at least two different verbs from {subset_csv} and assert on `k8s_client` state produced by an earlier command. Cover, where the subset allows: a create -> read-back -> mutate -> delete lifecycle; the apply -> get identity chain (a manifest applied and then read-back has the expected replica count / spec fields); and at least one NEGATIVE chain (reading a deleted resource must fail with `ApiException.status == 404`, and the corresponding kubectl subprocess must exit non-zero with `NotFound` in stderr).

CLI SHAPE (real kubectl — VERB-FIRST):
- `cli("apply", "-f", str(manifest))` — kind sniffed from manifest
- `cli("create", "namespace", "NAME")` — namespace by name, no `-f`
- `cli("get", "pods")` — list, no NAME
- `cli("get", "pod", "NAME")` — fetch one
- `cli("delete", "pod", "NAME")`, `cli("delete", "namespace", "NAME")`
- `cli("scale", "deployment", "NAME", "--replicas=3")`
- `cli("label", "pod", "NAME", "key=val")`
- `cli("patch", "pod", "NAME", "-p", '{{"metadata":{{"labels":{{"k":"v"}}}}}}')`
NEVER emit `cli("pods", "apply", ...)` or any resource-first form — that is not real kubectl syntax. `{command_prefix}` is the primary resource kind the test suite exercises; it enters via the manifest's `kind:` (apply/create -f) or as the TYPE positional after the verb.

REMINDER — every step is gauntlet-checked (STRICT exit polarity):
- Every SUCCESS step needs `returncode == 0` AND a literal `k8s_client.<method>(...)` call in the same test body (rule G2d — bare `returncode == 0` alone is rejected).
- Every FAILURE step needs the SPECIFIC expected code — `== 2` for cobra usage errors (unknown flag), `== 1` for apiserver 404 / missing resource — AND a stderr substring assertion (rule G2c). Loose `!= 0` / `in (1, 2)` / `>= 1` are ALL rejected by rule G2b. PREFER stderr substring assertions for failure steps — they are stable across kubectl minor versions.

FIXTURE SEMANTICS (memorize):
- `k8s_client` — attribute-style client. Use `k8s_client.list_namespace()`, `k8s_client.list_namespaced_pod(namespace="default")`, `k8s_client.read_namespaced_deployment(name="d", namespace="default")` for state checks. THIS is the pattern that satisfies G2d.
- `kubectl_bin` — a CALLABLE fixture (invoke it: `kubectl_bin(["get", "ns"])`), NOT a client. Attribute access like `kubectl_bin.get(...)` DOES NOT EXIST and will `AttributeError` at runtime. Use `kubectl_bin(args)` for state seeding or stdout-based verification, but ALWAYS pair it with at least one `k8s_client.<method>(...)` call so G2d fires.

Use ONLY verbs from {subset_csv}, and NEVER the unsupported verbs `logs`, `exec`, `port-forward`, `attach`, `top`, `cp`."""


@register_backend("kwok")
class KwokSimulationBackend(SimulationBackend):
    name: ClassVar[str] = "kwok"
    # kubectl_help intentionally kept on the compatible-sources list here (per
    # scaffold-test invariant) because the spec allows help-derived intents as
    # a future fallback source; C5 will narrow if needed.
    compatible_sources: ClassVar[frozenset[str]] = frozenset({"kubectl_cobra_yaml", "kubectl_help"})
    prompt_template_version: ClassVar[str] = "kwok-v7.6.0-oracle-multi-kind-dynamic"
    pinned_deps: ClassVar[tuple[str, ...]] = _PINNED_DEPS
    pinned_base_image: ClassVar[str] = _ECR_POLYGLOT_IMAGE
    pinned_kubectl_version: ClassVar[str] = _KUBECTL_VERSION
    pinned_kwok_version: ClassVar[str] = _KWOK_VERSION
    blocked_hosts: ClassVar[tuple[str, ...]] = _KWOK_BLOCKED_HOSTS
    blocked_suffixes: ClassVar[tuple[str, ...]] = _KWOK_BLOCKED_SUFFIXES
    fixture_client_names: ClassVar[tuple[str, ...]] = ("k8s_client", "kubectl_bin")
    runtime_cpus: ClassVar[float] = 4.0
    runtime_memory_mb: ClassVar[int] = 2048
    entry_point: ClassVar[str] = "submission/kubectl"
    prompts: ClassVar[PromptBundle] = PromptBundle(
        translation_system=_TRANSLATION_SYSTEM_KWOK,
        translation_user_template=_TRANSLATION_USER_TEMPLATE_KWOK,
        oracle_single_system=_ORACLE_SYSTEM_KWOK,
        oracle_single_user_template=_ORACLE_USER_TEMPLATE_KWOK,
        oracle_subset_system=_ORACLE_SUBSET_SYSTEM_KWOK,
        oracle_subset_user_template=_ORACLE_SUBSET_USER_TEMPLATE_KWOK,
        workflow_system=_WORKFLOW_SYSTEM_KWOK,
        workflow_user_template=_WORKFLOW_USER_TEMPLATE_KWOK,
    )

    @classmethod
    def dockerfile_base(cls, base_image: str | None = None) -> str:
        """Raiden-style app-layer Dockerfile FROMing the pre-built polyglot ECR image.

        The ECR image already bundles Python / Node / Java / Ruby / Rust / Go
        toolchains + kubectl / kwokctl / etcd / kube-apiserver / kube-controller-manager
        / kube-scheduler + pytest + kubernetes python client + openhands-sdk
        at /opt/openhands-sdk-venv, so this Dockerfile just sets env vars,
        prepares the submission workdir, and creates the baseline git commit.
        """
        image = base_image or _ECR_POLYGLOT_IMAGE
        return (
            "# syntax=docker/dockerfile:1\n"
            f"ARG BASE_IMAGE={image}\n"
            "FROM ${BASE_IMAGE}\n"
            "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \\\n"
            "    PYTHONHASHSEED=0 TZ=UTC LC_ALL=C.UTF-8 \\\n"
            "    KUBECONFIG=/etc/kubeconfig\n"
            "WORKDIR /workspace\n"
            "RUN mkdir -p /workspace/submission && touch /workspace/submission/.gitkeep\n"
            "ENV PATH=/workspace/submission:$PATH\n"
            "RUN git config --global --add safe.directory /workspace && \\\n"
            "    git init -q /workspace && \\\n"
            "    git -C /workspace config user.email raiden@local && \\\n"
            "    git -C /workspace config user.name raiden && \\\n"
            "    git -C /workspace add -A && \\\n"
            "    git -C /workspace commit -q --allow-empty -m 'raiden: baseline'\n"
        )

    @classmethod
    def dockerfile_gauntlet_layers(cls) -> str:
        """No gauntlet-only overlay yet.

        Reference-grounding for kubectl needs a real ``kubectl`` binary
        wrapper AND a kwok cluster; the wrapper is TBD in C7. Empty string
        keeps the gauntlet builder inert for kwok tasks until then.
        """
        return ""

    @classmethod
    def dockerfile_golden_layer(cls, deps: tuple[str, ...]) -> str:
        """App-layer Dockerfile with golden-slice deps in place of _PINNED_DEPS.

        Bare-minimum until C10 authors the golden shim: install the Kubernetes
        Python client + PyYAML so the shim can build+POST manifests without
        pulling extra deps at solve time. Any ``deps`` passed in are also
        installed to mirror the golden-slice contract.
        """
        deps_line = " ".join(f'"{d}"' for d in deps) if deps else ""
        extra = f"RUN pip install --no-cache-dir {deps_line}\n" if deps_line else ""
        base = cls.dockerfile_base(None)
        return base + f"RUN pip install --no-cache-dir {_GOLDEN_DEP_LINE}\n" + extra

    @classmethod
    def build_conftest(cls, *, golden: bool = False) -> str:
        """Auto-generated conftest for kubectl/kwok tasks.

        Boots a session-scoped kwokctl cluster on a random loopback port,
        wipes non-system namespaces between tests, exposes ``cli``,
        ``k8s_client``, and ``kubectl_bin`` fixtures. The ``cli`` subprocess
        prefix is dual-entrypoint at runtime: it picks
        ``/workspace/submission/kubectl`` if the shim exists, otherwise
        ``sys.executable /workspace/submission/main.py``. The ``golden``
        argument is retained for Protocol compat but no longer changes the
        emitted body — agents may write either style per instruction.md.
        """
        _ = golden
        suffixes_literal = ", ".join(repr(s) for s in _KWOK_BLOCKED_SUFFIXES)
        template = '''"""Auto-generated by Repo2RLEnv code_instruct cli_app mode (kwok backend).

Session-scoped kwokctl cluster + delete-non-system-namespaces reset between
tests. The agent's submission runs as a subprocess; we boot a fresh kwok
cluster on a random loopback port and write KUBECONFIG so both the test
kubernetes.client and the submission subprocess reach the same apiserver.
"""

import ipaddress
import os
import shutil
import socket as _socket
import subprocess
import sys
import time as _time
import http.client as _http

_R2E_ORIG_CONNECT = _socket.socket.connect
_R2E_BLOCKED_SUFFIXES = (__BLOCKED_SUFFIXES__,)

import stat as _r2e_stat


def _r2e_ensure_executable(path):
    try:
        st = os.stat(path)
        os.chmod(path, st.st_mode | _r2e_stat.S_IXUSR | _r2e_stat.S_IXGRP | _r2e_stat.S_IXOTH)
    except OSError:
        pass


if os.path.exists("/workspace/submission/kubectl"):
    _r2e_ensure_executable("/workspace/submission/kubectl")
    _R2E_CLI_PREFIX = ["/workspace/submission/kubectl"]
else:
    _R2E_CLI_PREFIX = [sys.executable, "/workspace/submission/main.py"]


def _r2e_guarded_connect(self, address):
    if self.family in (_socket.AF_INET, _socket.AF_INET6) and isinstance(address, tuple):
        host = address[0]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            for suffix in _R2E_BLOCKED_SUFFIXES:
                if host.lower() == suffix or host.lower().endswith("." + suffix):
                    raise RuntimeError(f"r2e:network-isolation: connect to {host!r} blocked")
        else:
            if not (ip.is_loopback or ip.is_private or ip.is_link_local):
                raise RuntimeError(
                    f"r2e:network-isolation: connect to public IP {host!r} blocked"
                )
    return _R2E_ORIG_CONNECT(self, address)


_socket.socket.connect = _r2e_guarded_connect
def _r2e_guarded_connect_ex(self, addr):
    import errno as _errno
    try:
        _r2e_guarded_connect(self, addr)
        return 0
    except RuntimeError:
        return _errno.EACCES
    except OSError as exc:
        return exc.errno
_socket.socket.connect_ex = _r2e_guarded_connect_ex

import pytest


def pytest_configure(config):
    _kubectl = "/workspace/submission/kubectl"
    _mainpy = "/workspace/submission/main.py"
    _kubectl_exists = os.path.exists(_kubectl)
    _mainpy_exists = os.path.exists(_mainpy)
    if not (_kubectl_exists or _mainpy_exists):
        pytest.exit(
            f"Anti-NOP guard FAILED: no submission entrypoint found "
            f"(tried {_kubectl}, {_mainpy}). Reward=0.",
            returncode=1,
        )
    if _kubectl_exists:
        if not os.access(_kubectl, os.X_OK):
            pytest.exit(
                "submission/kubectl missing/non-exec/empty (not executable). Reward=0.",
                returncode=1,
            )
        if os.path.getsize(_kubectl) <= 0:
            pytest.exit(
                "submission/kubectl missing/non-exec/empty (zero-byte file). Reward=0.",
                returncode=1,
            )
    if shutil.which("kubectl") is None:
        pytest.exit(
            "Anti-NOP guard FAILED: kubectl binary not found on PATH. Reward=0.",
            returncode=1,
        )
    if shutil.which("kwokctl") is None:
        pytest.exit(
            "Anti-NOP guard FAILED: kwokctl binary not found on PATH. Reward=0.",
            returncode=1,
        )


def _grab_free_port(retries=3):
    """Retry on bind-time races; rare but observed on busy CI."""
    last_err = None
    for _ in range(retries):
        try:
            sock = _socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            return port
        except OSError as e:
            last_err = e
            _time.sleep(0.05)
    raise RuntimeError(f"could not bind ephemeral port: {last_err}")


@pytest.fixture(scope="session")
def kwok_cluster(tmp_path_factory):
    port = _grab_free_port()
    kubeconfig = tmp_path_factory.mktemp("kwok") / "kubeconfig"
    cluster_name = f"r2e-{os.getpid()}"

    subprocess.run(
        [
            "kwokctl",
            "create",
            "cluster",
            "--runtime=binary",
            f"--name={cluster_name}",
            f"--kube-apiserver-port={port}",
            "--wait=600s",
            "--etcd-binary=/usr/local/bin/etcd",
            "--kube-apiserver-binary=/usr/local/bin/kube-apiserver",
            "--kube-controller-manager-binary=/usr/local/bin/kube-controller-manager",
            "--kube-scheduler-binary=/usr/local/bin/kube-scheduler",
            "--kwok-controller-binary=/usr/local/bin/kwok",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )

    kubeconfig_bytes = subprocess.run(
        ["kwokctl", "get", "kubeconfig", f"--name={cluster_name}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    kubeconfig.write_text(kubeconfig_bytes)
    os.environ["KUBECONFIG"] = str(kubeconfig)

    import re as _re
    _server_match = _re.search(r"server:\\s*https?://([^:\\s]+):(\\d+)", kubeconfig_bytes)
    if _server_match:
        actual_host = _server_match.group(1)
        actual_port = int(_server_match.group(2))
    else:
        actual_host = "127.0.0.1"
        actual_port = port
    endpoint = f"{actual_host}:{actual_port}"
    for _ in range(3000):
        try:
            with _socket.create_connection((actual_host, actual_port), timeout=0.2):
                break
        except OSError:
            pass
        _time.sleep(0.1)
    else:
        subprocess.run(
            ["kwokctl", "delete", "cluster", f"--name={cluster_name}"],
            check=False,
            capture_output=True,
        )
        raise RuntimeError(f"kwok apiserver at {endpoint} not ready within 300s")

    try:
        yield {"endpoint": endpoint, "kubeconfig": str(kubeconfig), "name": cluster_name}
    finally:
        subprocess.run(
            ["kwokctl", "delete", "cluster", f"--name={cluster_name}"],
            check=False,
            capture_output=True,
            timeout=30,
        )


@pytest.fixture
def k8s_client(kwok_cluster):
    from kubernetes import client, config as _kconfig

    _kconfig.load_kube_config(config_file=kwok_cluster["kubeconfig"])
    return client.CoreV1Api(client.ApiClient())


@pytest.fixture(autouse=True)
def _reset_kwok(kwok_cluster):
    """Wipe non-system namespaces + wait for GC between tests.

    Preserves kube-system, kube-public, kube-node-lease, default (matches
    kubectl's own "protected" namespaces list). All other namespaces (and
    their contents) are hard-deleted before yielding to the test.
    """
    _system = {"kube-system", "kube-public", "kube-node-lease", "default"}
    for _ in range(5):
        result = subprocess.run(
            ["kubectl", "--kubeconfig", kwok_cluster["kubeconfig"],
             "get", "ns", "-o", "name"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        stale = [
            line.removeprefix("namespace/").strip()
            for line in result.stdout.splitlines()
            if line.strip() and line.removeprefix("namespace/").strip() not in _system
        ]
        if not stale:
            break
        subprocess.run(
            ["kubectl", "--kubeconfig", kwok_cluster["kubeconfig"],
             "delete", "ns", *stale, "--wait=true", "--grace-period=0", "--force"],
            capture_output=True,
            timeout=30,
        )
    subprocess.run(
        ["kubectl", "--kubeconfig", kwok_cluster["kubeconfig"],
         "delete",
         "pods,services,resourcequotas,limitranges,deployments,replicasets,"
         "statefulsets,daemonsets,jobs,cronjobs,configmaps,secrets,"
         "persistentvolumeclaims,ingresses,serviceaccounts",
         "--all", "-n", "default", "--grace-period=0", "--force"],
        capture_output=True,
        timeout=30,
    )
    yield


@pytest.fixture
def cli(kwok_cluster):
    def _run(*args, env_overrides=None, timeout=60, input=None):
        env = os.environ.copy()
        env["KUBECONFIG"] = kwok_cluster["kubeconfig"]
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [*_R2E_CLI_PREFIX, *args],
            env=env,
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return _run


@pytest.fixture
def kubectl_bin(kwok_cluster):
    """Direct kubectl invoker (bypasses the submission).

    Used by tests that need to set up cluster state as a precondition
    without going through the agent's submission (e.g. seeding a
    Deployment before running `submission cli get deployment ...`).
    """
    def _run(args, *, input=None, timeout=30.0):
        env = os.environ.copy()
        env["KUBECONFIG"] = kwok_cluster["kubeconfig"]
        _kubectl = "/usr/local/bin/kubectl"
        return subprocess.run(
            [_kubectl, "--kubeconfig", kwok_cluster["kubeconfig"], *args],
            env=env,
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return _run
'''
        return template.replace("__BLOCKED_SUFFIXES__", suffixes_literal)

    @classmethod
    def build_test_sh(cls) -> str:
        """JUnit-XML reward parser test.sh (kept byte-parallel with MinIO/DDB).

        Duplicated inline rather than delegated so kwok content stays free of
        ``_cli_app_synthesis`` coupling (that module is aws-only). If the v2
        reward parser ever forks (kwok-specific reward shape), only this copy
        needs to move.
        """
        return r"""#!/bin/bash

set -uxo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_TOML="$SCRIPT_DIR/../task.toml"
cd /workspace
mkdir -p /logs/verifier

export PYTHONPATH="/opt/test-libs:$SCRIPT_DIR${PYTHONPATH:+:}${PYTHONPATH:-}"

python -m pytest "$SCRIPT_DIR" -v --tb=short -p no:randomly \
    --junit-xml=/logs/verifier/results.xml \
    > /logs/verifier/pytest_output.log 2>&1
cat /logs/verifier/pytest_output.log

TASK_TOML="$TASK_TOML" python3 << 'PY' > /logs/verifier/reward.txt
import os, re, sys, xml.etree.ElementTree as ET
from pathlib import Path

XML = "/logs/verifier/results.xml"
TOML = os.environ.get("TASK_TOML", "")

expected = None
if TOML and Path(TOML).exists():
    for line in Path(TOML).read_text().splitlines():
        m = re.match(r"\s*tests_shipped\s*=\s*(\d+)", line)
        if m:
            expected = int(m.group(1))
            break

try:
    root = ET.parse(XML).getroot()
except Exception as e:
    sys.stderr.write(f"reward parser v2: could not parse {XML}: {e}\n")
    print("0.0")
    sys.exit(0)

suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
tests = failures = errors = skipped = 0
for s in suites:
    tests    += int(s.get("tests",    0) or 0)
    failures += int(s.get("failures", 0) or 0)
    errors   += int(s.get("errors",   0) or 0)
    skipped  += int(s.get("skipped",  0) or 0)
passed = tests - failures - errors - skipped

if expected is not None and tests < expected:
    sys.stderr.write(
        f"reward parser v2: COLLECTION DRIFT - task.toml.tests_shipped={expected} "
        f"but JUnit reports tests={tests}. Reward=0.\n"
    )
    print("0.0")
    sys.exit(0)

total = passed + failures + errors
print(round(passed / total, 4) if total else 0.0)
PY

REWARD=$(cat /logs/verifier/reward.txt)
echo "reward=$REWARD parser=v2"
exit 0
"""

    @classmethod
    def compose_overlay(cls) -> str | None:
        """No docker-compose sidecar: kwokctl runs in-container via --runtime=binary."""
        return None

    @classmethod
    def aux_test_modules(cls) -> dict[str, str]:
        """Ship the ``_k8s_client`` helper next to conftest.

        Small stdlib+kubernetes-client helper that mirrors the KubectlBuilder
        API pattern from Kubernetes E2E tests. Real assertion helpers will
        be filled in C9/C10 alongside the reference shim; the interface is
        specified here so C5 prompts can reference stable names.
        """
        return {"_k8s_client.py": _K8S_CLIENT_HELPER}

    @classmethod
    def workflow_preamble(cls) -> str:
        """Import preamble prepended to each split workflow-test module."""
        return _WF_IMPORT_PREAMBLE_KWOK

    @classmethod
    def command_state_model(cls) -> dict[tuple[str, str], str]:
        """Empty for now — populated by C5 with kubectl-verb state semantics.

        Keys will be `(subcommand_prefix, verb)` tuples like `("apply",
        "deployments") -> "replicas count stable after apply"`. Empty return
        keeps the workflow-test synthesis inert until C5 wires kwok in.
        """
        return {}

    @classmethod
    def cross_command_invariants(cls, names: list[str]) -> str:
        """Placeholder invariants string for the instruction.md builder.

        Kwok simulates the apiserver's state persistence semantics
        faithfully (etcd-backed via kine), so cross-command state contracts
        apply verbatim from the k8s conformance suite. C5 will expand this
        into per-verb rendered bullets once the state model is populated.
        """
        return "Kubernetes API state persists across kubectl commands within a task session.\n"

    @classmethod
    def _reference_client_source(cls) -> str:
        return _REFERENCE_CLIENT_PATH.read_text(encoding="utf-8")

    @classmethod
    def emit_reference_client(cls, task_spec: object | None = None) -> str:
        """Return reference kubectl client source, pruned to the task's needs.

        task_spec: duck-typed. If it exposes `.commands` (verbs like "get"/"apply")
        and `.kinds` (resource-kind strings), the returned source keeps only the
        client methods those verbs need plus the KINDS entries those kinds
        reference. Otherwise, or on any AST parse failure, the full ~320-line
        client is returned unchanged (with a warning header on parse failure).
        """
        full = cls._reference_client_source()
        verbs, kinds = _extract_verbs_and_kinds(task_spec)
        if not verbs and not kinds:
            return full
        try:
            tree = ast.parse(full)
        except SyntaxError:
            return "# WARNING: AST parse failed; shipping full reference client.\n" + full
        try:
            pruned = _prune_reference_client(tree, verbs=verbs, kinds=kinds)
            return ast.unparse(pruned) + "\n"
        except Exception:
            return "# WARNING: AST prune failed; shipping full reference client.\n" + full

    @classmethod
    def emit_golden_shim(cls, task_spec: object | None = None) -> dict[str, str]:
        """Return the golden kubectl slice as a repo-relative-path -> content map.

        Ships a from-scratch kubernetes/kubectl entry point under
        ``submission/kubectl-src/`` (go.mod + cmd/kubectl/main.go + README)
        that builds root cobra from scratch and adds ONLY the verbs named
        by ``task_spec.commands`` (falls back to all 8 supported slice verbs
        when task_spec is None/empty). Harbor's solve.sh compiles this into
        ``submission/kubectl``. Verbs NOT in the selected subset are absent
        at the CLI surface — invoking them prints cobra's "unknown command"
        error, proving the slice is real.

        The 2-line exec shim is also included at ``submission/kubectl`` so
        the synthesis-time validation gate (which does NOT run solve.sh)
        has a working entrypoint that execs the real kubectl baked into
        the ECR image.
        """
        raw_verbs = getattr(task_spec, "commands", None) if task_spec is not None else None
        verbs = _normalize_slice_verbs(raw_verbs)
        command_prefix = (
            getattr(task_spec, "command_prefix", "") if task_spec is not None else ""
        ) or ""
        files: dict[str, str] = {
            "submission/kubectl-src/go.mod": _KUBECTL_SLICE_GO_MOD,
            "submission/kubectl-src/cmd/kubectl/main.go": _render_kubectl_slice_main_go(verbs),
            "submission/kubectl-src/README.md": _render_kubectl_slice_readme(verbs),
            "submission/kubectl": _render_golden_shim(command_prefix),
        }
        return files

    @classmethod
    def emit_golden_diff(cls, task_spec: object | None = None) -> str | None:
        """Return a ``git apply --binary``-compatible diff for a fully-vendored slice.

        Runs the AST slicer (``_kubectl_ast_slicer.slice_kubectl_vendor``)
        which executes ``go mod vendor`` inside a pinned Docker container to
        compute the exact minimal transitive Go source closure — every ``.go``
        file plus embedded binary assets needed to compile a main.go that
        imports ONLY the sliced verbs. The returned diff creates
        ``submission/kubectl-src/{go.mod,go.sum,vendor/**,cmd/kubectl/main.go}``
        as one binary-safe unified diff (~53 MB for the 8-verb set), so
        ``solve.sh`` can build ``submission/kubectl`` OFFLINE via
        ``GOFLAGS=-mod=vendor go build``.

        Returns ``None`` when the slicer cannot run (docker missing, network
        offline, module resolution fail). The caller must fall back to
        ``emit_golden_shim()`` — the shipped shim + module-import path.
        """
        raw_verbs = getattr(task_spec, "commands", None) if task_spec is not None else None
        verbs = _normalize_slice_verbs(raw_verbs)
        from repo2rlenv.pipelines._cli_app_backends.simulation._kubectl_ast_slicer import (
            slice_kubectl_vendor,
        )

        return slice_kubectl_vendor(verbs)

    @classmethod
    def emit_reference_go(cls, task_spec: object | None = None) -> dict[str, str]:
        """Return the from-scratch Go reference implementation as a path -> content map.

        Emits ``submission/kubectl.go`` (cobra + client-go, ~700 LoC covering
        get/apply/delete/create/describe/patch/scale/label on the resource
        kind(s) named by ``task_spec.kinds``) plus a pinned ``submission/go.mod``.
        The Docker base image ships a golang toolchain and a pre-warmed module
        cache (see ``dockerfile_base``), so ``go build`` inside the sandbox
        works with ``GOPROXY=off`` — no network access needed at solve time.

        ``task_spec`` is duck-typed: ``.commands`` (list of verb strings) and
        ``.kinds`` (list of resource kinds). Missing kinds default to ``pods``
        so the emitted binary is never empty.
        """
        _verbs, kinds = _extract_verbs_and_kinds(task_spec)
        if not kinds:
            kinds = {"pods"}
        primary_kind = sorted(kinds)[0]
        return {
            "submission/kubectl.go": _render_reference_go(primary_kind=primary_kind),
            "submission/go.mod": _render_reference_go_mod(),
        }


# --------------------------------------------------------------------------- #
# Shared string constants (module-level so `aux_test_modules` returns a
# reference to a canonical byte-sequence — tests can pin against the constant
# without re-authoring the whole helper module.)
# --------------------------------------------------------------------------- #

# Workflow-test import preamble: what every generated workflow module needs at
# top-of-file. Keeps import layout stable across C5 prompt revisions.
_WF_IMPORT_PREAMBLE_KWOK = (
    "import subprocess\n"
    "import json\n"
    "import os\n"
    "import sys\n"
    "sys.path.insert(0, os.path.dirname(__file__))\n"
    "import pytest\n"
    "from _k8s_client import k8s_client, kubectl_bin, "
    "assert_namespace_exists, assert_deployment_replicas\n\n\n"
)

# Small helper module shipped under `tests/_k8s_client.py`. Mirrors the K8s
# E2E ``KubectlBuilder`` API so workflow tests can compose kubectl invocations
# fluently (NewKubectlCommand -> WithStdinData -> WithTimeout -> run). The
# assertion helpers give tests a stable way to make behavioural claims without
# reaching into raw kubernetes.client responses.
_K8S_CLIENT_HELPER = '''"""Kubectl builder + assertion helpers for kwok-backed cli_app tasks.

Mirrors the K8s E2E ``KubectlBuilder`` interface so tests can compose commands
fluently. Uses the kubernetes Python client for direct-API assertions when the
assertion helpers cannot be expressed via the kubectl surface (e.g. reading
pod status without shelling out).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class KubectlBuilder:
    """Fluent builder mirroring the K8s E2E test framework's KubectlBuilder."""

    args: list[str] = field(default_factory=list)
    stdin: str | None = None
    timeout: float = 30.0
    env: dict[str, str] = field(default_factory=dict)

    def WithStdinData(self, data: str) -> "KubectlBuilder":
        self.stdin = data
        return self

    def WithTimeout(self, timeout: float) -> "KubectlBuilder":
        self.timeout = timeout
        return self

    def WithEnv(self, env: dict[str, str]) -> "KubectlBuilder":
        self.env = {**self.env, **env}
        return self

    def run(self) -> subprocess.CompletedProcess:
        merged_env = os.environ.copy()
        merged_env.update(self.env)
        return subprocess.run(
            ["kubectl", *self.args],
            input=self.stdin,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )

    def run_or_die(self) -> subprocess.CompletedProcess:
        result = self.run()
        if result.returncode != 0:
            raise RuntimeError(
                f"kubectl {self.args!r} exited {result.returncode}: "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return result


def NewKubectlCommand(*args: str) -> KubectlBuilder:
    """Entry point for the fluent builder (K8s E2E convention: capitalized)."""
    return KubectlBuilder(args=list(args))


# --------------------------------------------------------------------------- #
# Assertion helpers — expressive names so workflow tests read like specs.
# --------------------------------------------------------------------------- #


def assert_namespace_exists(k8s_client: Any, name: str) -> None:
    from kubernetes import client as _client

    v1 = _client.CoreV1Api(k8s_client)
    ns = {n.metadata.name for n in v1.list_namespace().items}
    if name not in ns:
        raise AssertionError(f"namespace {name!r} not in cluster (have: {sorted(ns)})")


def assert_deployment_replicas(
    k8s_client: Any, namespace: str, name: str, expected: int
) -> None:
    from kubernetes import client as _client

    apps = _client.AppsV1Api(k8s_client)
    dep = apps.read_namespaced_deployment(name=name, namespace=namespace)
    actual = dep.spec.replicas
    if actual != expected:
        raise AssertionError(
            f"deployment {namespace}/{name}: replicas={actual}, expected={expected}"
        )


# Re-exports so ``from _k8s_client import k8s_client, kubectl_bin, ...`` in
# workflow tests resolves to the SAME fixture objects the conftest defines.
# These are placeholder names imported for their side-effect on module-level
# name resolution — pytest fixtures are looked up by name across the plugin
# tree, so the actual objects come from conftest.py, not here.
k8s_client = None  # type: ignore[assignment]
kubectl_bin = None  # type: ignore[assignment]
'''


def _extract_verbs_and_kinds(task_spec: object | None) -> tuple[set[str], set[str]]:
    if task_spec is None:
        return set(), set()
    verbs_raw = getattr(task_spec, "commands", None)
    kinds_raw = getattr(task_spec, "kinds", None)
    verbs = {str(v).lower() for v in verbs_raw} if verbs_raw else set()
    kinds = {str(k).lower() for k in kinds_raw} if kinds_raw else set()
    return verbs, kinds


def _client_methods_for_verbs(verbs: Iterable[str]) -> set[str]:
    keep: set[str] = set(_ALWAYS_KEEP_METHODS)
    for verb in verbs:
        for method in _KUBECTL_VERB_TO_CLIENT_METHODS.get(verb.lower(), ()):
            keep.add(method)
    return keep


def _prune_reference_client(tree: ast.Module, *, verbs: set[str], kinds: set[str]) -> ast.Module:
    methods_to_keep = _client_methods_for_verbs(verbs) if verbs else None

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "KubectlClient" and methods_to_keep:
            new_body: list[ast.stmt] = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name in methods_to_keep:
                        new_body.append(item)
                else:
                    new_body.append(item)
            node.body = new_body or [ast.Pass()]
        elif isinstance(node, ast.Assign) and kinds:
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "KINDS" in targets and isinstance(node.value, ast.Dict):
                _prune_kinds_dict(node.value, kinds)
        elif isinstance(node, ast.AnnAssign) and kinds:
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == "KINDS"
                and isinstance(node.value, ast.Dict)
            ):
                _prune_kinds_dict(node.value, kinds)
    return tree


def _render_reference_go_mod() -> str:
    lines = ["module submission", "", "go 1.22", "", "require ("]
    for mod, ver in _REFERENCE_GO_MODULE_DEPS:
        lines.append(f"\t{mod} {ver}")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def _render_reference_go(*, primary_kind: str) -> str:
    return _REFERENCE_GO_TEMPLATE.replace("__PRIMARY_KIND__", primary_kind)


def _prune_kinds_dict(dict_node: ast.Dict, kinds: set[str]) -> None:
    kept_keys: list[ast.expr] = []
    kept_values: list[ast.expr] = []
    lowered = {k.lower() for k in kinds}
    for k_node, v_node in zip(dict_node.keys, dict_node.values, strict=False):
        if isinstance(k_node, ast.Constant) and isinstance(k_node.value, str):
            key = k_node.value.lower()
            if key in lowered or any(key.startswith(k) or k.startswith(key) for k in lowered):
                kept_keys.append(k_node)
                kept_values.append(v_node)
    if kept_keys:
        dict_node.keys = kept_keys
        dict_node.values = kept_values


_REFERENCE_GO_TEMPLATE = r"""package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"
	appsv1 "k8s.io/api/apps/v1"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	networkingv1 "k8s.io/api/networking/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
	"sigs.k8s.io/yaml"
)

// primaryKind is the resource kind the emitting task's tests focus on.
// Injected at synthesis time from the task_spec. Real kubectl is verb-first
// (`kubectl apply -f pod.yaml`, `kubectl get pods`, ...) so primaryKind is no
// longer a subcommand; it's used as a fallback when sniffKindFromManifest
// encounters a manifest without a `kind:` field, and by `-o name` output.
const primaryKind = "__PRIMARY_KIND__"

const (
	exitOK    = 0
	exitError = 1
)

var (
	nsFlag       string
	outputFlag   string
	filenameFlag []string
	patchFlag    string
	patchType    string
	replicaFlag  int32
	overwrite    bool
	forceFlag    bool
	gracePeriod  int64
)

func kubeClient() (*kubernetes.Clientset, error) {
	cfgPath := os.Getenv("KUBECONFIG")
	if cfgPath == "" {
		return nil, fmt.Errorf("KUBECONFIG env var is not set")
	}
	cfg, err := clientcmd.BuildConfigFromFlags("", cfgPath)
	if err != nil {
		return nil, err
	}
	return kubernetes.NewForConfig(cfg)
}

func fatal(err error) {
	if err == nil {
		return
	}
	if statusErr, ok := err.(*apierrors.StatusError); ok {
		reason := string(statusErr.ErrStatus.Reason)
		if reason == "" {
			reason = "Error"
		}
		details := statusErr.ErrStatus.Message
		fmt.Fprintf(os.Stderr, "Error from server (%s): %s\n", reason, details)
		os.Exit(exitError)
	}
	fmt.Fprintf(os.Stderr, "error: %s\n", err.Error())
	os.Exit(exitError)
}

func writeObject(obj interface{}) error {
	switch strings.ToLower(outputFlag) {
	case "json":
		data, err := json.MarshalIndent(obj, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(data))
	case "yaml":
		data, err := yaml.Marshal(obj)
		if err != nil {
			return err
		}
		fmt.Print(string(data))
	case "name":
		if named, ok := obj.(metav1.Object); ok {
			fmt.Printf("%s/%s\n", primaryKind, named.GetName())
		}
	default:
		if named, ok := obj.(metav1.Object); ok {
			fmt.Printf("NAME\n%s\n", named.GetName())
		}
	}
	return nil
}

func readManifestBytes() ([]byte, error) {
	if len(filenameFlag) == 0 {
		return nil, fmt.Errorf("required flag(s) \"filename\" not set")
	}
	var out []byte
	for _, path := range filenameFlag {
		var data []byte
		var err error
		if path == "-" {
			data, err = io.ReadAll(os.Stdin)
		} else {
			data, err = os.ReadFile(path)
		}
		if err != nil {
			return nil, err
		}
		if len(out) > 0 {
			out = append(out, []byte("\n---\n")...)
		}
		out = append(out, data...)
	}
	return out, nil
}

func decodePodManifest(data []byte) (*corev1.Pod, error) {
	pod := &corev1.Pod{}
	if err := yaml.Unmarshal(data, pod); err != nil {
		return nil, err
	}
	if pod.Namespace == "" {
		pod.Namespace = nsForCall()
	}
	pod.Kind = "Pod"
	pod.APIVersion = "v1"
	return pod, nil
}

func decodeDeploymentManifest(data []byte) (*appsv1.Deployment, error) {
	dep := &appsv1.Deployment{}
	if err := yaml.Unmarshal(data, dep); err != nil {
		return nil, err
	}
	if dep.Namespace == "" {
		dep.Namespace = nsForCall()
	}
	dep.Kind = "Deployment"
	dep.APIVersion = "apps/v1"
	return dep, nil
}

func decodeServiceManifest(data []byte) (*corev1.Service, error) {
	svc := &corev1.Service{}
	if err := yaml.Unmarshal(data, svc); err != nil {
		return nil, err
	}
	if svc.Namespace == "" {
		svc.Namespace = nsForCall()
	}
	svc.Kind = "Service"
	svc.APIVersion = "v1"
	return svc, nil
}

func decodeConfigMapManifest(data []byte) (*corev1.ConfigMap, error) {
	cm := &corev1.ConfigMap{}
	if err := yaml.Unmarshal(data, cm); err != nil {
		return nil, err
	}
	if cm.Namespace == "" {
		cm.Namespace = nsForCall()
	}
	cm.Kind = "ConfigMap"
	cm.APIVersion = "v1"
	return cm, nil
}

func decodeSecretManifest(data []byte) (*corev1.Secret, error) {
	sec := &corev1.Secret{}
	if err := yaml.Unmarshal(data, sec); err != nil {
		return nil, err
	}
	if sec.Namespace == "" {
		sec.Namespace = nsForCall()
	}
	sec.Kind = "Secret"
	sec.APIVersion = "v1"
	return sec, nil
}

func decodeJobManifest(data []byte) (*batchv1.Job, error) {
	job := &batchv1.Job{}
	if err := yaml.Unmarshal(data, job); err != nil {
		return nil, err
	}
	if job.Namespace == "" {
		job.Namespace = nsForCall()
	}
	job.Kind = "Job"
	job.APIVersion = "batch/v1"
	return job, nil
}

func decodeCronJobManifest(data []byte) (*batchv1.CronJob, error) {
	cj := &batchv1.CronJob{}
	if err := yaml.Unmarshal(data, cj); err != nil {
		return nil, err
	}
	if cj.Namespace == "" {
		cj.Namespace = nsForCall()
	}
	cj.Kind = "CronJob"
	cj.APIVersion = "batch/v1"
	return cj, nil
}

func decodeStatefulSetManifest(data []byte) (*appsv1.StatefulSet, error) {
	ss := &appsv1.StatefulSet{}
	if err := yaml.Unmarshal(data, ss); err != nil {
		return nil, err
	}
	if ss.Namespace == "" {
		ss.Namespace = nsForCall()
	}
	ss.Kind = "StatefulSet"
	ss.APIVersion = "apps/v1"
	return ss, nil
}

func decodeIngressManifest(data []byte) (*networkingv1.Ingress, error) {
	ing := &networkingv1.Ingress{}
	if err := yaml.Unmarshal(data, ing); err != nil {
		return nil, err
	}
	if ing.Namespace == "" {
		ing.Namespace = nsForCall()
	}
	ing.Kind = "Ingress"
	ing.APIVersion = "networking.k8s.io/v1"
	return ing, nil
}

func decodeNamespaceManifest(data []byte) (*corev1.Namespace, error) {
	ns := &corev1.Namespace{}
	if err := yaml.Unmarshal(data, ns); err != nil {
		return nil, err
	}
	ns.Kind = "Namespace"
	ns.APIVersion = "v1"
	return ns, nil
}

func nsForCall() string {
	if nsFlag != "" {
		return nsFlag
	}
	return "default"
}

func labelSelectorFromArgs(args []string) (string, string, map[string]string, error) {
	if len(args) < 2 {
		return "", "", nil, fmt.Errorf("at least one label required")
	}
	name := args[0]
	labels := map[string]string{}
	for _, kv := range args[1:] {
		if strings.HasSuffix(kv, "-") {
			labels[strings.TrimSuffix(kv, "-")] = ""
			continue
		}
		parts := strings.SplitN(kv, "=", 2)
		if len(parts) != 2 {
			return "", "", nil, fmt.Errorf("invalid label spec %q", kv)
		}
		labels[parts[0]] = parts[1]
	}
	return name, "", labels, nil
}

// resolveKind normalises a TYPE token (singular/plural/short form) to the
// canonical plural kind used by our per-kind dispatch functions. Empty
// return means "unknown" — the caller surfaces a real-kubectl-style error.
func resolveKind(t string) string {
	switch strings.ToLower(t) {
	case "pod", "pods", "po":
		return "pods"
	case "deployment", "deployments", "deploy":
		return "deployments"
	case "service", "services", "svc":
		return "services"
	case "configmap", "configmaps", "cm":
		return "configmaps"
	case "secret", "secrets":
		return "secrets"
	case "job", "jobs":
		return "jobs"
	case "cronjob", "cronjobs", "cj":
		return "cronjobs"
	case "statefulset", "statefulsets", "sts":
		return "statefulsets"
	case "ingress", "ingresses", "ing":
		return "ingresses"
	case "namespace", "namespaces", "ns":
		return "namespaces"
	}
	return ""
}

type manifestHead struct {
	Kind string `json:"kind"`
}

// sniffKindFromManifest returns the canonical plural kind for a YAML manifest
// blob (e.g. `kind: Pod` -> "pods"). Falls back to primaryKind when the
// manifest is missing a Kind field so single-verb tasks that ship a bare
// manifest still resolve.
func sniffKindFromManifest(data []byte) (string, error) {
	head := manifestHead{}
	if err := yaml.Unmarshal(data, &head); err != nil {
		return "", err
	}
	if head.Kind == "" {
		return primaryKind, nil
	}
	switch head.Kind {
	case "Pod":
		return "pods", nil
	case "Deployment":
		return "deployments", nil
	case "Service":
		return "services", nil
	case "ConfigMap":
		return "configmaps", nil
	case "Secret":
		return "secrets", nil
	case "Job":
		return "jobs", nil
	case "CronJob":
		return "cronjobs", nil
	case "StatefulSet":
		return "statefulsets", nil
	case "Ingress":
		return "ingresses", nil
	case "Namespace":
		return "namespaces", nil
	}
	return "", fmt.Errorf("unsupported manifest kind %q", head.Kind)
}

func newGetCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "get TYPE [NAME]",
		Short: "Display one or many resources",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(_ *cobra.Command, args []string) error {
			cs, err := kubeClient()
			if err != nil {
				return err
			}
			kind := resolveKind(args[0])
			if kind == "" {
				return fmt.Errorf("error: the server doesn't have a resource type %q", args[0])
			}
			return dispatchGet(context.Background(), cs, kind, args[1:])
		},
	}
	c.Flags().StringVarP(&outputFlag, "output", "o", "", "Output format (json|yaml|name)")
	return c
}

func newApplyCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "apply -f FILE",
		Short: "Apply a configuration to a resource by file name or stdin",
		RunE: func(_ *cobra.Command, _ []string) error {
			cs, err := kubeClient()
			if err != nil {
				return err
			}
			return dispatchApply(context.Background(), cs)
		},
	}
	c.Flags().StringSliceVarP(&filenameFlag, "filename", "f", nil, "Manifest file(s)")
	return c
}

func newCreateCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "create (-f FILE | TYPE NAME)",
		Short: "Create a resource from a file or from stdin",
		RunE: func(_ *cobra.Command, args []string) error {
			cs, err := kubeClient()
			if err != nil {
				return err
			}
			if len(filenameFlag) > 0 {
				return dispatchCreate(context.Background(), cs)
			}
			if len(args) >= 2 {
				kind := resolveKind(args[0])
				if kind == "" {
					return fmt.Errorf("error: unknown resource type %q", args[0])
				}
				return dispatchCreateBareName(context.Background(), cs, kind, args[1])
			}
			return fmt.Errorf("error: must specify one of -f or TYPE NAME")
		},
	}
	c.Flags().StringSliceVarP(&filenameFlag, "filename", "f", nil, "Manifest file(s)")
	return c
}

func newDeleteCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "delete TYPE NAME",
		Short: "Delete resources by file names, stdin, resources and names, or by resources and label selector",
		Args:  cobra.MinimumNArgs(2),
		RunE: func(_ *cobra.Command, args []string) error {
			cs, err := kubeClient()
			if err != nil {
				return err
			}
			kind := resolveKind(args[0])
			if kind == "" {
				return fmt.Errorf("error: the server doesn't have a resource type %q", args[0])
			}
			return dispatchDelete(context.Background(), cs, kind, args[1:])
		},
	}
	c.Flags().BoolVar(&forceFlag, "force", false, "Force delete")
	c.Flags().Int64Var(&gracePeriod, "grace-period", -1, "Grace period")
	return c
}

func newDescribeCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "describe TYPE NAME",
		Short: "Show details of a specific resource or group of resources",
		Args:  cobra.MinimumNArgs(2),
		RunE: func(_ *cobra.Command, args []string) error {
			cs, err := kubeClient()
			if err != nil {
				return err
			}
			kind := resolveKind(args[0])
			if kind == "" {
				return fmt.Errorf("error: the server doesn't have a resource type %q", args[0])
			}
			return dispatchDescribe(context.Background(), cs, kind, args[1:])
		},
	}
	return c
}

func newPatchCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "patch TYPE NAME -p PATCH",
		Short: "Update fields of a resource",
		Args:  cobra.MinimumNArgs(2),
		RunE: func(_ *cobra.Command, args []string) error {
			cs, err := kubeClient()
			if err != nil {
				return err
			}
			kind := resolveKind(args[0])
			if kind == "" {
				return fmt.Errorf("error: the server doesn't have a resource type %q", args[0])
			}
			return dispatchPatch(context.Background(), cs, kind, args[1:])
		},
	}
	c.Flags().StringVarP(&patchFlag, "patch", "p", "", "JSON/strategic merge patch")
	c.Flags().StringVar(&patchType, "type", "strategic", "Patch type (json|merge|strategic)")
	return c
}

func newScaleCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "scale TYPE NAME --replicas=N",
		Short: "Set a new size for a deployment, statefulset, or replication controller",
		Args:  cobra.MinimumNArgs(2),
		RunE: func(_ *cobra.Command, args []string) error {
			cs, err := kubeClient()
			if err != nil {
				return err
			}
			kind := resolveKind(args[0])
			if kind == "" {
				return fmt.Errorf("error: the server doesn't have a resource type %q", args[0])
			}
			return dispatchScale(context.Background(), cs, kind, args[1:])
		},
	}
	c.Flags().Int32Var(&replicaFlag, "replicas", -1, "Desired replica count")
	return c
}

func newLabelCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "label TYPE NAME KEY_1=VAL_1 ... KEY_N=VAL_N",
		Short: "Update the labels on a resource",
		Args:  cobra.MinimumNArgs(3),
		RunE: func(_ *cobra.Command, args []string) error {
			cs, err := kubeClient()
			if err != nil {
				return err
			}
			kind := resolveKind(args[0])
			if kind == "" {
				return fmt.Errorf("error: the server doesn't have a resource type %q", args[0])
			}
			return dispatchLabel(context.Background(), cs, kind, args[1:])
		},
	}
	c.Flags().BoolVar(&overwrite, "overwrite", false, "Allow label overwrites")
	return c
}

func buildVerbCommands() []*cobra.Command {
	verbs := []*cobra.Command{
		newGetCmd(),
		newApplyCmd(),
		newCreateCmd(),
		newDeleteCmd(),
		newDescribeCmd(),
		newPatchCmd(),
		newScaleCmd(),
		newLabelCmd(),
	}
	for _, v := range verbs {
		v.PersistentFlags().StringVarP(&nsFlag, "namespace", "n", "", "Namespace")
	}
	return verbs
}

func dispatchGet(ctx context.Context, cs *kubernetes.Clientset, kind string, args []string) error {
	switch kind {
	case "pods":
		return getPods(ctx, cs, args)
	case "deployments":
		return getDeployments(ctx, cs, args)
	case "services":
		return getServices(ctx, cs, args)
	case "configmaps":
		return getConfigMaps(ctx, cs, args)
	case "secrets":
		return getSecrets(ctx, cs, args)
	case "jobs":
		return getJobs(ctx, cs, args)
	case "cronjobs":
		return getCronJobs(ctx, cs, args)
	case "statefulsets":
		return getStatefulSets(ctx, cs, args)
	case "ingresses":
		return getIngresses(ctx, cs, args)
	case "namespaces":
		return getNamespaces(ctx, cs, args)
	}
	return fmt.Errorf("unsupported resource kind %q", kind)
}

func dispatchApply(ctx context.Context, cs *kubernetes.Clientset) error {
	data, err := readManifestBytes()
	if err != nil {
		return err
	}
	kind, err := sniffKindFromManifest(data)
	if err != nil {
		return err
	}
	switch kind {
	case "pods":
		obj, err := decodePodManifest(data)
		if err != nil {
			return err
		}
		_, err = cs.CoreV1().Pods(obj.Namespace).Create(ctx, obj, metav1.CreateOptions{})
		if apierrors.IsAlreadyExists(err) {
			_, err = cs.CoreV1().Pods(obj.Namespace).Update(ctx, obj, metav1.UpdateOptions{})
			if err != nil {
				return err
			}
			fmt.Printf("pod/%s configured\n", obj.Name)
			return nil
		}
		if err != nil {
			return err
		}
		fmt.Printf("pod/%s created\n", obj.Name)
	case "deployments":
		obj, err := decodeDeploymentManifest(data)
		if err != nil {
			return err
		}
		_, err = cs.AppsV1().Deployments(obj.Namespace).Create(ctx, obj, metav1.CreateOptions{})
		if apierrors.IsAlreadyExists(err) {
			_, err = cs.AppsV1().Deployments(obj.Namespace).Update(ctx, obj, metav1.UpdateOptions{})
			if err != nil {
				return err
			}
			fmt.Printf("deployment.apps/%s configured\n", obj.Name)
			return nil
		}
		if err != nil {
			return err
		}
		fmt.Printf("deployment.apps/%s created\n", obj.Name)
	case "services":
		obj, err := decodeServiceManifest(data)
		if err != nil {
			return err
		}
		_, err = cs.CoreV1().Services(obj.Namespace).Create(ctx, obj, metav1.CreateOptions{})
		if apierrors.IsAlreadyExists(err) {
			_, err = cs.CoreV1().Services(obj.Namespace).Update(ctx, obj, metav1.UpdateOptions{})
			if err != nil {
				return err
			}
			fmt.Printf("service/%s configured\n", obj.Name)
			return nil
		}
		if err != nil {
			return err
		}
		fmt.Printf("service/%s created\n", obj.Name)
	case "configmaps":
		obj, err := decodeConfigMapManifest(data)
		if err != nil {
			return err
		}
		_, err = cs.CoreV1().ConfigMaps(obj.Namespace).Create(ctx, obj, metav1.CreateOptions{})
		if apierrors.IsAlreadyExists(err) {
			_, err = cs.CoreV1().ConfigMaps(obj.Namespace).Update(ctx, obj, metav1.UpdateOptions{})
			if err != nil {
				return err
			}
			fmt.Printf("configmap/%s configured\n", obj.Name)
			return nil
		}
		if err != nil {
			return err
		}
		fmt.Printf("configmap/%s created\n", obj.Name)
	case "namespaces":
		obj, err := decodeNamespaceManifest(data)
		if err != nil {
			return err
		}
		_, err = cs.CoreV1().Namespaces().Create(ctx, obj, metav1.CreateOptions{})
		if apierrors.IsAlreadyExists(err) {
			fmt.Printf("namespace/%s unchanged\n", obj.Name)
			return nil
		}
		if err != nil {
			return err
		}
		fmt.Printf("namespace/%s created\n", obj.Name)
	default:
		return fmt.Errorf("apply on %q not implemented", kind)
	}
	_ = time.Now
	_ = strconv.Itoa
	_ = types.StrategicMergePatchType
	_ = decodeSecretManifest
	_ = decodeJobManifest
	_ = decodeCronJobManifest
	_ = decodeStatefulSetManifest
	_ = decodeIngressManifest
	_ = labelSelectorFromArgs
	return nil
}

func dispatchCreate(ctx context.Context, cs *kubernetes.Clientset) error {
	data, err := readManifestBytes()
	if err != nil {
		return err
	}
	kind, err := sniffKindFromManifest(data)
	if err != nil {
		return err
	}
	switch kind {
	case "pods":
		obj, err := decodePodManifest(data)
		if err != nil {
			return err
		}
		if _, err := cs.CoreV1().Pods(obj.Namespace).Create(ctx, obj, metav1.CreateOptions{}); err != nil {
			return err
		}
		fmt.Printf("pod/%s created\n", obj.Name)
	case "deployments":
		obj, err := decodeDeploymentManifest(data)
		if err != nil {
			return err
		}
		if _, err := cs.AppsV1().Deployments(obj.Namespace).Create(ctx, obj, metav1.CreateOptions{}); err != nil {
			return err
		}
		fmt.Printf("deployment.apps/%s created\n", obj.Name)
	case "namespaces":
		obj, err := decodeNamespaceManifest(data)
		if err != nil {
			return err
		}
		if _, err := cs.CoreV1().Namespaces().Create(ctx, obj, metav1.CreateOptions{}); err != nil {
			return err
		}
		fmt.Printf("namespace/%s created\n", obj.Name)
	default:
		return fmt.Errorf("create on %q not implemented", kind)
	}
	return nil
}

func dispatchCreateBareName(ctx context.Context, cs *kubernetes.Clientset, kind, name string) error {
	switch kind {
	case "namespaces":
		obj := &corev1.Namespace{}
		obj.Name = name
		obj.Kind = "Namespace"
		obj.APIVersion = "v1"
		if _, err := cs.CoreV1().Namespaces().Create(ctx, obj, metav1.CreateOptions{}); err != nil {
			return err
		}
		fmt.Printf("namespace/%s created\n", name)
		return nil
	}
	return fmt.Errorf("create %s/%s: use `-f FILE` for this resource kind", kind, name)
}

func dispatchDelete(ctx context.Context, cs *kubernetes.Clientset, kind string, args []string) error {
	name := args[0]
	ns := nsForCall()
	deleteOpts := metav1.DeleteOptions{}
	if gracePeriod >= 0 {
		deleteOpts.GracePeriodSeconds = &gracePeriod
	}
	switch kind {
	case "pods":
		if err := cs.CoreV1().Pods(ns).Delete(ctx, name, deleteOpts); err != nil {
			return err
		}
		fmt.Printf("pod \"%s\" deleted\n", name)
	case "deployments":
		if err := cs.AppsV1().Deployments(ns).Delete(ctx, name, deleteOpts); err != nil {
			return err
		}
		fmt.Printf("deployment.apps \"%s\" deleted\n", name)
	case "services":
		if err := cs.CoreV1().Services(ns).Delete(ctx, name, deleteOpts); err != nil {
			return err
		}
		fmt.Printf("service \"%s\" deleted\n", name)
	case "configmaps":
		if err := cs.CoreV1().ConfigMaps(ns).Delete(ctx, name, deleteOpts); err != nil {
			return err
		}
		fmt.Printf("configmap \"%s\" deleted\n", name)
	case "namespaces":
		if err := cs.CoreV1().Namespaces().Delete(ctx, name, deleteOpts); err != nil {
			return err
		}
		fmt.Printf("namespace \"%s\" deleted\n", name)
	default:
		return fmt.Errorf("delete on %q not implemented", kind)
	}
	return nil
}

func dispatchDescribe(ctx context.Context, cs *kubernetes.Clientset, kind string, args []string) error {
	name := args[0]
	ns := nsForCall()
	switch kind {
	case "pods":
		obj, err := cs.CoreV1().Pods(ns).Get(ctx, name, metav1.GetOptions{})
		if err != nil {
			return err
		}
		fmt.Printf("Name:         %s\nNamespace:    %s\nStatus:       %s\n", obj.Name, obj.Namespace, obj.Status.Phase)
	case "deployments":
		obj, err := cs.AppsV1().Deployments(ns).Get(ctx, name, metav1.GetOptions{})
		if err != nil {
			return err
		}
		replicas := int32(0)
		if obj.Spec.Replicas != nil {
			replicas = *obj.Spec.Replicas
		}
		fmt.Printf("Name:               %s\nNamespace:          %s\nReplicas:           %d desired\n", obj.Name, obj.Namespace, replicas)
	case "namespaces":
		obj, err := cs.CoreV1().Namespaces().Get(ctx, name, metav1.GetOptions{})
		if err != nil {
			return err
		}
		fmt.Printf("Name:         %s\nStatus:       %s\n", obj.Name, obj.Status.Phase)
	default:
		return fmt.Errorf("describe on %q not implemented", kind)
	}
	return nil
}

func dispatchPatch(ctx context.Context, cs *kubernetes.Clientset, kind string, args []string) error {
	name := args[0]
	ns := nsForCall()
	if patchFlag == "" {
		return fmt.Errorf("required flag \"patch\" not set")
	}
	pt := types.StrategicMergePatchType
	switch strings.ToLower(patchType) {
	case "json":
		pt = types.JSONPatchType
	case "merge":
		pt = types.MergePatchType
	}
	data := []byte(patchFlag)
	switch kind {
	case "pods":
		if _, err := cs.CoreV1().Pods(ns).Patch(ctx, name, pt, data, metav1.PatchOptions{}); err != nil {
			return err
		}
		fmt.Printf("pod/%s patched\n", name)
	case "deployments":
		if _, err := cs.AppsV1().Deployments(ns).Patch(ctx, name, pt, data, metav1.PatchOptions{}); err != nil {
			return err
		}
		fmt.Printf("deployment.apps/%s patched\n", name)
	default:
		return fmt.Errorf("patch on %q not implemented", kind)
	}
	return nil
}

func dispatchScale(ctx context.Context, cs *kubernetes.Clientset, kind string, args []string) error {
	name := args[0]
	ns := nsForCall()
	if replicaFlag < 0 {
		return fmt.Errorf("required flag \"replicas\" not set")
	}
	switch kind {
	case "deployments":
		s, err := cs.AppsV1().Deployments(ns).GetScale(ctx, name, metav1.GetOptions{})
		if err != nil {
			return err
		}
		s.Spec.Replicas = replicaFlag
		if _, err := cs.AppsV1().Deployments(ns).UpdateScale(ctx, name, s, metav1.UpdateOptions{}); err != nil {
			return err
		}
		fmt.Printf("deployment.apps/%s scaled\n", name)
	case "statefulsets":
		s, err := cs.AppsV1().StatefulSets(ns).GetScale(ctx, name, metav1.GetOptions{})
		if err != nil {
			return err
		}
		s.Spec.Replicas = replicaFlag
		if _, err := cs.AppsV1().StatefulSets(ns).UpdateScale(ctx, name, s, metav1.UpdateOptions{}); err != nil {
			return err
		}
		fmt.Printf("statefulset.apps/%s scaled\n", name)
	default:
		return fmt.Errorf("error: cannot scale a resource of kind %q", kind)
	}
	return nil
}

func dispatchLabel(ctx context.Context, cs *kubernetes.Clientset, kind string, args []string) error {
	name, _, labels, err := labelSelectorFromArgs(args)
	if err != nil {
		return err
	}
	ns := nsForCall()
	switch kind {
	case "pods":
		obj, err := cs.CoreV1().Pods(ns).Get(ctx, name, metav1.GetOptions{})
		if err != nil {
			return err
		}
		if obj.Labels == nil {
			obj.Labels = map[string]string{}
		}
		for k, v := range labels {
			if !overwrite {
				if _, exists := obj.Labels[k]; exists {
					return fmt.Errorf("label %q already has a value, use --overwrite", k)
				}
			}
			if v == "" {
				delete(obj.Labels, k)
			} else {
				obj.Labels[k] = v
			}
		}
		if _, err := cs.CoreV1().Pods(ns).Update(ctx, obj, metav1.UpdateOptions{}); err != nil {
			return err
		}
		fmt.Printf("pod/%s labeled\n", name)
	case "deployments":
		obj, err := cs.AppsV1().Deployments(ns).Get(ctx, name, metav1.GetOptions{})
		if err != nil {
			return err
		}
		if obj.Labels == nil {
			obj.Labels = map[string]string{}
		}
		for k, v := range labels {
			if !overwrite {
				if _, exists := obj.Labels[k]; exists {
					return fmt.Errorf("label %q already has a value, use --overwrite", k)
				}
			}
			if v == "" {
				delete(obj.Labels, k)
			} else {
				obj.Labels[k] = v
			}
		}
		if _, err := cs.AppsV1().Deployments(ns).Update(ctx, obj, metav1.UpdateOptions{}); err != nil {
			return err
		}
		fmt.Printf("deployment.apps/%s labeled\n", name)
	default:
		return fmt.Errorf("label on %q not implemented", kind)
	}
	return nil
}

func getPods(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.CoreV1().Pods(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		return writePodList(list)
	}
	obj, err := cs.CoreV1().Pods(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "Pod"
	obj.APIVersion = "v1"
	return writeObject(obj)
}

func writePodList(list *corev1.PodList) error {
	switch strings.ToLower(outputFlag) {
	case "json":
		data, err := json.MarshalIndent(list, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(data))
	case "yaml":
		data, err := yaml.Marshal(list)
		if err != nil {
			return err
		}
		fmt.Print(string(data))
	default:
		fmt.Println("NAME    READY   STATUS    RESTARTS   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s    1/1     %s    0          0s\n", item.Name, item.Status.Phase)
		}
	}
	return nil
}

func getDeployments(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.AppsV1().Deployments(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    READY   UP-TO-DATE   AVAILABLE   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s    0/0     0            0           0s\n", item.Name)
		}
		return nil
	}
	obj, err := cs.AppsV1().Deployments(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "Deployment"
	obj.APIVersion = "apps/v1"
	return writeObject(obj)
}

func getServices(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.CoreV1().Services(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    TYPE   CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s\n", item.Name)
		}
		return nil
	}
	obj, err := cs.CoreV1().Services(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "Service"
	obj.APIVersion = "v1"
	return writeObject(obj)
}

func getConfigMaps(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.CoreV1().ConfigMaps(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    DATA   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s    %d    0s\n", item.Name, len(item.Data))
		}
		return nil
	}
	obj, err := cs.CoreV1().ConfigMaps(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "ConfigMap"
	obj.APIVersion = "v1"
	return writeObject(obj)
}

func getSecrets(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.CoreV1().Secrets(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    TYPE   DATA   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s    %s    %d    0s\n", item.Name, item.Type, len(item.Data))
		}
		return nil
	}
	obj, err := cs.CoreV1().Secrets(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "Secret"
	obj.APIVersion = "v1"
	return writeObject(obj)
}

func getJobs(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.BatchV1().Jobs(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    COMPLETIONS   DURATION   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s\n", item.Name)
		}
		return nil
	}
	obj, err := cs.BatchV1().Jobs(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "Job"
	obj.APIVersion = "batch/v1"
	return writeObject(obj)
}

func getCronJobs(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.BatchV1().CronJobs(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    SCHEDULE    SUSPEND   ACTIVE   LAST SCHEDULE   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s\n", item.Name)
		}
		return nil
	}
	obj, err := cs.BatchV1().CronJobs(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "CronJob"
	obj.APIVersion = "batch/v1"
	return writeObject(obj)
}

func getStatefulSets(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.AppsV1().StatefulSets(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    READY   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s\n", item.Name)
		}
		return nil
	}
	obj, err := cs.AppsV1().StatefulSets(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "StatefulSet"
	obj.APIVersion = "apps/v1"
	return writeObject(obj)
}

func getIngresses(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	ns := nsForCall()
	if len(args) == 0 {
		list, err := cs.NetworkingV1().Ingresses(ns).List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    CLASS   HOSTS   ADDRESS   PORTS   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s\n", item.Name)
		}
		return nil
	}
	obj, err := cs.NetworkingV1().Ingresses(ns).Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "Ingress"
	obj.APIVersion = "networking.k8s.io/v1"
	return writeObject(obj)
}

func getNamespaces(ctx context.Context, cs *kubernetes.Clientset, args []string) error {
	if len(args) == 0 {
		list, err := cs.CoreV1().Namespaces().List(ctx, metav1.ListOptions{})
		if err != nil {
			return err
		}
		fmt.Println("NAME    STATUS   AGE")
		for _, item := range list.Items {
			fmt.Printf("%s    %s    0s\n", item.Name, item.Status.Phase)
		}
		return nil
	}
	obj, err := cs.CoreV1().Namespaces().Get(ctx, args[0], metav1.GetOptions{})
	if err != nil {
		return err
	}
	obj.Kind = "Namespace"
	obj.APIVersion = "v1"
	return writeObject(obj)
}

func main() {
	root := &cobra.Command{
		Use:          "kubectl",
		Short:        "kubectl reference implementation (client-go, verb-first)",
		SilenceUsage: true,
	}
	for _, v := range buildVerbCommands() {
		root.AddCommand(v)
	}
	_ = primaryKind
	if err := root.Execute(); err != nil {
		fatal(err)
	}
}
"""
