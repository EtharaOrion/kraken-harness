"""Compute the full transitive Go source closure for a kubectl slice.

Runs ``go mod vendor`` inside a pinned ``golang:1.22.5-bookworm`` container to
produce the exact minimal Go source closure needed to compile a ``main.go``
that imports ONLY the given kubectl verb packages. Returns a
``git apply --binary``-compatible unified diff string that creates the full
tree under ``submission/kubectl-src/``:

- ``go.mod`` + ``go.sum``
- ``cmd/kubectl/main.go`` (root cobra with explicit ``AddCommand`` per verb)
- ``vendor/modules.txt``
- ``vendor/**/*`` — every transitively reachable Go source file, plus the
  binary assets (``*.mo`` i18n catalogs, ``*.binpb`` protobuf defaults) that
  the vendored packages ``//go:embed`` at build time.

The synthesis pipeline embeds this diff verbatim as ``solution/golden.diff``.
Harbor's ``solve.sh`` applies it and then compiles offline with
``GOFLAGS=-mod=vendor go build``: no ``proxy.golang.org`` egress needed at
solve time — proof the slice is fully vendored, not an import-time wrapper.

Result is cached under ``$XDG_CACHE_HOME/repo2rlenv/kubectl_slicer/`` keyed
on ``(image, verb-set)``. First run is ~6 minutes (module download);
subsequent runs are file reads (<50 ms).

Returns ``None`` (with a warning log) when Docker is unavailable, the image
pull fails, or ``go mod vendor`` fails — the caller falls back to the
text-only shim design and the resulting task uses module-import at solve
time.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_log = logging.getLogger(__name__)

# Pinned Go toolchain — must match kwok._REFERENCE_GO_TOOLCHAIN_IMAGE
# so vendored bytes are reproducible across host machines. Bump both
# constants in lockstep.
_SLICER_IMAGE = "golang:1.22.5-bookworm"

# Kubectl module version. Tied to _KUBECTL_SLICE_VERSION in kwok.py; do not
# reset one without the other or the slice will target a different upstream.
_KUBECTL_VERSION = "v0.31.0"

# Per-verb factory-call metadata. Mirrors kwok._KUBECTL_SLICE_VERB_SPEC —
# duplicated here so this file has no import-time dependency on kwok.py
# (which itself imports from this module).
#
# Tuple: (Go import alias, module path, constructor name, needs "kubectl"
# parent-command string as first arg).
_VERB_SPEC: dict[str, tuple[str, str, str, bool]] = {
    "get": ("cmdget", "k8s.io/kubectl/pkg/cmd/get", "NewCmdGet", True),
    "apply": ("cmdapply", "k8s.io/kubectl/pkg/cmd/apply", "NewCmdApply", True),
    "delete": ("delete_", "k8s.io/kubectl/pkg/cmd/delete", "NewCmdDelete", False),
    "create": ("cmdcreate", "k8s.io/kubectl/pkg/cmd/create", "NewCmdCreate", False),
    "describe": ("cmddescribe", "k8s.io/kubectl/pkg/cmd/describe", "NewCmdDescribe", True),
    "patch": ("cmdpatch", "k8s.io/kubectl/pkg/cmd/patch", "NewCmdPatch", False),
    "scale": ("cmdscale", "k8s.io/kubectl/pkg/cmd/scale", "NewCmdScale", False),
    "label": ("cmdlabel", "k8s.io/kubectl/pkg/cmd/label", "NewCmdLabel", False),
}

_GO_MOD = f"""\
module submission/kubectl-src

go 1.22

require (
\tgithub.com/spf13/cobra v1.8.1
\tk8s.io/cli-runtime {_KUBECTL_VERSION}
\tk8s.io/client-go {_KUBECTL_VERSION}
\tk8s.io/component-base {_KUBECTL_VERSION}
\tk8s.io/kubectl {_KUBECTL_VERSION}
)
"""


def _cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "repo2rlenv" / "kubectl_slicer"


def _cache_key(verbs: tuple[str, ...]) -> str:
    payload = f"{_SLICER_IMAGE}|{_KUBECTL_VERSION}|{','.join(verbs)}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _render_main_go(verbs: tuple[str, ...]) -> str:
    """Emit a minimal main.go that imports ONLY ``verbs``.

    Deliberately does NOT call ``NewDefaultKubectlCommand`` — building the
    root cobra command from scratch and calling ``AddCommand`` verb-by-verb
    means unlisted verbs are unreachable at the CLI surface: ``kubectl
    logs`` yields cobra's "unknown command" error. Proof the slice is
    real at the CLI level, not a wrapper that forwards to full kubectl.
    """
    import_lines: list[str] = []
    add_lines: list[str] = []
    for verb in verbs:
        alias, path, ctor, has_parent = _VERB_SPEC[verb]
        import_lines.append(f'\t{alias} "{path}"')
        if has_parent:
            add_lines.append(f'\troot.AddCommand({alias}.{ctor}("kubectl", f, io))')
        else:
            add_lines.append(f"\troot.AddCommand({alias}.{ctor}(f, io))")

    verb_imports = "\n".join(import_lines)
    verb_adds = "\n".join(add_lines)
    verbs_list = ", ".join(verbs)
    return f"""// True CLI-level slice of kubernetes/kubectl {_KUBECTL_VERSION}.
// Only the following verbs are added to the root cobra.Command:
//   {verbs_list}
// All other kubectl verbs are absent from the compiled binary; invoking one
// prints cobra's "unknown command" error. Vendor tree is populated by the
// synthesis-time slicer, so `go build -mod=vendor` succeeds offline.
// Apache-2.0 licensed; upstream: https://github.com/kubernetes/kubectl
package main

import (
\t"os"

\t"github.com/spf13/cobra"
\t_ "k8s.io/client-go/plugin/pkg/client/auth"
\t"k8s.io/cli-runtime/pkg/genericclioptions"
\t"k8s.io/cli-runtime/pkg/genericiooptions"
\t"k8s.io/component-base/cli"

{verb_imports}
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

{verb_adds}

\tif err := cli.RunNoErrOutput(root); err != nil {{
\t\tcmdutil.CheckErr(err)
\t}}
}}
"""


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            check=True,
            timeout=10,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def slice_kubectl_vendor(
    verbs: tuple[str, ...],
    *,
    timeout_sec: float = 900.0,
    force: bool = False,
) -> str | None:
    """Return a ``git apply --binary``-compatible diff for a vendored kubectl slice.

    Runs ``go mod vendor`` in Docker to compute the exact minimal transitive
    Go source closure for a main.go importing ONLY ``verbs``. Emits
    ``submission/kubectl-src/{go.mod,go.sum,vendor/**,cmd/kubectl/main.go}``
    as one binary-safe unified diff.

    Result cached under ``$XDG_CACHE_HOME/repo2rlenv/kubectl_slicer/`` keyed
    on ``(image, verb-set)``. Pass ``force=True`` to bypass the cache.

    Returns ``None`` on any failure (docker missing, network offline, module
    resolution fail, timeout). Callers should fall back to the text-only
    shim + module-import design.
    """
    if not verbs:
        _log.warning("kubectl slicer: empty verb list")
        return None
    for v in verbs:
        if v not in _VERB_SPEC:
            _log.warning("kubectl slicer: unknown verb %r", v)
            return None

    verbs = tuple(v for v in _VERB_SPEC if v in verbs)

    cache_file = _cache_root() / f"{_cache_key(verbs)}.diff"
    if not force and cache_file.is_file():
        _log.info(
            "kubectl slicer cache hit: %s (%.1f MB)", cache_file, cache_file.stat().st_size / 1e6
        )
        return cache_file.read_text(encoding="utf-8")

    if not _docker_available():
        _log.warning("kubectl slicer: docker unavailable; skipping vendor")
        return None

    with tempfile.TemporaryDirectory(prefix="r2e_kubectl_slice_") as tmp:
        workdir = Path(tmp)
        _write_slice_inputs(workdir, verbs)

        try:
            _run_vendor_in_docker(workdir, timeout_sec=timeout_sec)
        except subprocess.TimeoutExpired:
            _log.warning("kubectl slicer: `go mod vendor` timed out after %.0fs", timeout_sec)
            return None
        except subprocess.CalledProcessError as e:
            _log.warning(
                "kubectl slicer: docker step failed (exit %d): %s",
                e.returncode,
                (e.stderr or b"").decode("utf-8", "replace")[-2000:],
            )
            return None
        except OSError as e:
            _log.warning("kubectl slicer: OS error running docker: %s", e)
            return None

        diff_path = workdir / "golden.diff"
        if not diff_path.is_file() or diff_path.stat().st_size < 1024:
            _log.warning("kubectl slicer: diff not produced or empty")
            return None

        diff_text = diff_path.read_text(encoding="utf-8")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(diff_text, encoding="utf-8")
    _log.info(
        "kubectl slicer produced diff: %s (%.1f MB, %d files)",
        cache_file,
        len(diff_text) / 1e6,
        diff_text.count("\ndiff --git ") + (1 if diff_text.startswith("diff --git ") else 0),
    )
    return diff_text


def _write_slice_inputs(workdir: Path, verbs: tuple[str, ...]) -> None:
    src = workdir / "build" / "submission" / "kubectl-src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "go.mod").write_text(_GO_MOD, encoding="utf-8")
    cmd_dir = src / "cmd" / "kubectl"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    (cmd_dir / "main.go").write_text(_render_main_go(verbs), encoding="utf-8")


def _run_vendor_in_docker(workdir: Path, *, timeout_sec: float) -> None:
    script = r"""
set -euo pipefail
cd /work/build/submission/kubectl-src
export GOFLAGS='-mod=mod'
export GOMODCACHE=/root/go/pkg/mod
go mod tidy
go mod vendor

cd /work/build
git config --global user.email r2e@local
git config --global user.name r2e
git config --global --add safe.directory /work/build
git init -q -b main

mkdir -p .git/info
cat > .git/info/attributes <<'GITATTR'
*.pb binary
*.binpb binary
*.mo binary
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.ico binary
*.pdf binary
*.zip binary
*.tar binary
*.gz binary
*.bz2 binary
*.xz binary
*.woff binary
*.woff2 binary
*.ttf binary
*.otf binary
*.eot binary
GITATTR

git commit -q --allow-empty -m init
git add -A
git diff --cached --binary --full-index --no-color > /work/golden.diff
echo "diff bytes: $(wc -c < /work/golden.diff)"
"""

    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "-v",
            f"{workdir}:/work",
            "-w",
            "/work",
            _SLICER_IMAGE,
            "bash",
            "-c",
            script,
        ],
        check=True,
        capture_output=True,
        timeout=timeout_sec,
    )
