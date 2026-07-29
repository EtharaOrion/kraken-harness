"""Write Harbor-compliant task directories.

The minimal (text-only) path emits:
  task.toml + instruction.md + solution/patch.diff
No environment/, no tests/. Reward kind = "diff_similarity".

When a pipeline supplies `task.environment_dockerfile` + `task.test_script`
(pr_diff with emit_harbor_env=True, and all _runtime pipelines), the writer
also emits environment/Dockerfile + tests/test.sh and seeds the
[metadata.repo2env.reproducibility] subtable.

----------------------------------------------------------------------------
Acknowledgment
----------------------------------------------------------------------------
The output FORMAT (task.toml schema, directory layout, /logs/verifier/reward.txt
contract, [metadata] tables) is defined by:

  Harbor Framework (Laude Institute / Terminal-Bench creators)
  https://github.com/Ethara-Ai/harbor    (Apache-2.0)
  https://www.harborframework.com/docs/tasks

We emit Harbor's format directly so any Harbor-compatible runtime, agent
harness, or downstream framework (OpenReward, SkyRL via Harbor, etc.) can
consume our datasets unchanged. We do NOT depend on the `harbor` Python
package — we generate the file format from scratch. The format itself is a
spec (data layout); using it does not require a license grant. Repo2RLEnv-
specific provenance lives inside Harbor's free-form `[metadata]` table under
the namespaced subtable `[metadata.repo2env]`.

Released under Apache-2.0.
----------------------------------------------------------------------------
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import tomli_w

logger = logging.getLogger(__name__)

# Anti-reward-hacking disallow-list. BLOCKED_HOSTS is the canonical set of
# hosts we blackhole at the DNS layer via Docker `extra_hosts -> 0.0.0.0`.
# BLOCKED_SUFFIXES is the suffix-form that the generated conftest socket
# guard imports verbatim, so the agent-phase (Docker) and verifier-phase
# (Python) layers enforce exactly the same policy. Adding a host here
# flows to both layers automatically. See raiden/REWARD_HACKING.md.
BLOCKED_HOSTS: tuple[str, ...] = (
    # PyPI (official)
    "pypi.org",
    "pythonhosted.org",
    "files.pythonhosted.org",
    # GitHub
    "github.com",
    "githubusercontent.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    # AWS (defense in depth on top of moto/MinIO sandbox)
    "awscli.amazonaws.com",
    "s3.amazonaws.com",
    # MinIO release infra (forecloses agent swapping the pinned binary or
    # phoning home for telemetry/updates even if MINIO_UPDATE env is bypassed)
    "dl.min.io",
    "update.min.io",
    "subnet.min.io",
    "min.io",
    # Debian apt repos (closes `apt-get install awscli` on debian-based images)
    "deb.debian.org",
    "security.debian.org",
    "archive.debian.org",
    "ftp.debian.org",
    # Ubuntu apt repos (future-proof if base image moves to ubuntu)
    "archive.ubuntu.com",
    "security.ubuntu.com",
    "ports.ubuntu.com",
    # Alternate PyPI mirrors (APAC + global, blocks `pip install -i <mirror> awscli`)
    "pypi.tuna.tsinghua.edu.cn",
    "pypi.mirrors.ustc.edu.cn",
    "mirrors.aliyun.com",
    "mirrors.cloud.tencent.com",
    "pypi.douban.com",
    "mirrors.huaweicloud.com",
    # Conda channels (defense in depth; no conda in default base, but future-proof)
    "repo.anaconda.com",
    "conda.anaconda.org",
)
# Registrable-domain suffix-form used by the Python socket guard:
# `host == suffix or host.endswith("." + suffix)` covers apex + arbitrary
# subdomains, so `files.pythonhosted.org` is matched by the
# `pythonhosted.org` entry.
BLOCKED_SUFFIXES: tuple[str, ...] = (
    "pypi.org",
    "pythonhosted.org",
    "github.com",
    "githubusercontent.com",
    "awscli.amazonaws.com",
    "s3.amazonaws.com",
    "min.io",
    "debian.org",
    "ubuntu.com",
    "pypi.tuna.tsinghua.edu.cn",
    "pypi.mirrors.ustc.edu.cn",
    "mirrors.aliyun.com",
    "mirrors.cloud.tencent.com",
    "pypi.douban.com",
    "mirrors.huaweicloud.com",
    "anaconda.com",
    "anaconda.org",
)


def _build_disallow_compose(hosts: tuple[str, ...], *, ddb_sidecar: bool = False) -> str:
    # Service name 'main' is Harbor's standard task-runner service,
    # confirmed via harbor/src/harbor/environments/docker/docker-compose-no-network.yaml.
    extra_hosts = "\n".join(f'      - "{h}:0.0.0.0"' for h in hosts)
    if not ddb_sidecar:
        return f"services:\n  main:\n    extra_hosts:\n{extra_hosts}\n"
    # DynamoDB backend variant: adds a `ddb` sidecar (DynamoDB Local) that the
    # `main` container talks to via AWS_ENDPOINT_URL over compose-internal DNS.
    # Digest is parallel-pinned with pipelines/_cli_app_synthesis.py:
    # PINNED_DDB_LOCAL_DIGEST — keep both in sync.
    return (
        "services:\n"
        "  ddb:\n"
        "    image: amazon/dynamodb-local:2.5.4"
        "@sha256:cf8cebd061f988628c02daff10fdb950a54478feff9c52f6ddf84710fe3c3906\n"
        '    command: ["-jar", "DynamoDBLocal.jar", "-inMemory", "-sharedDb", "-port", "8000"]\n'
        "    working_dir: /home/dynamodblocal\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "curl -s -o /dev/null http://localhost:8000 || exit 1"]\n'
        "      interval: 2s\n"
        "      timeout: 2s\n"
        "      retries: 20\n"
        "      start_period: 3s\n"
        "  main:\n"
        "    depends_on:\n"
        "      ddb:\n"
        "        condition: service_healthy\n"
        "    environment:\n"
        "      - AWS_ENDPOINT_URL=http://ddb:8000\n"
        "      - AWS_ENDPOINT_URL_DYNAMODB=http://ddb:8000\n"
        "      - AWS_PAGER=\n"
        "      - AWS_EC2_METADATA_DISABLED=true\n"
        "    extra_hosts:\n"
        f"{extra_hosts}\n"
    )


def _verify_blocklist_alignment(hosts: tuple[str, ...], suffixes: tuple[str, ...]) -> None:
    """Every BLOCKED_HOSTS entry must be matched by some BLOCKED_SUFFIXES entry."""
    for host in hosts:
        lowered = host.lower()
        if not any(lowered == s or lowered.endswith("." + s) for s in suffixes):
            raise RuntimeError(
                f"network blocklist invariant broken: host {host!r} is not "
                "covered by any BLOCKED_SUFFIXES entry \u2014 keep BLOCKED_HOSTS "
                "and BLOCKED_SUFFIXES in sync (see emitter/harbor.py)."
            )


_verify_blocklist_alignment(BLOCKED_HOSTS, BLOCKED_SUFFIXES)

# DynamoDB-backend variant of the disallow-list. The DynamoDB Local task
# backend runs on loopback, so the only additional egress worth blackholing is
# the real DynamoDB service endpoint (defense in depth, mirroring the S3
# entries). Regional endpoints (`dynamodb.<region>.amazonaws.com`) resolve to
# public IPs and are already rejected by the conftest socket guard's public-IP
# check, so only the apex suffix is listed here.
#
# Kept as PARALLEL tuples rather than mutating BLOCKED_HOSTS/BLOCKED_SUFFIXES:
# the generated S3 conftest bakes BLOCKED_SUFFIXES into its bytes, so growing
# the base set would change every shipped S3 task's content_hash. The DynamoDB
# pipeline branch imports these _DDB tuples and bakes them into the DynamoDB
# conftest + compose overlay instead.
BLOCKED_HOSTS_DDB: tuple[str, ...] = (*BLOCKED_HOSTS, "dynamodb.amazonaws.com")
BLOCKED_SUFFIXES_DDB: tuple[str, ...] = (*BLOCKED_SUFFIXES, "dynamodb.amazonaws.com")
_verify_blocklist_alignment(BLOCKED_HOSTS_DDB, BLOCKED_SUFFIXES_DDB)

# Kwok-backend variant. Kwok tasks don't touch AWS or MinIO, so those entries
# would be dead weight (and confuse a reader inspecting the emitted compose).
# We swap them for k8s-native release infra so the agent can't re-download
# kubectl / kwok binaries at test time and shadow the pinned base image.
_KWOK_STRIP_SUFFIXES = ("amazonaws.com", "min.io")
_KWOK_ADD_HOSTS: tuple[str, ...] = (
    "dl.k8s.io",
    "storage.googleapis.com",
    "registry.k8s.io",
)
_KWOK_ADD_SUFFIXES: tuple[str, ...] = (
    "k8s.io",
    "storage.googleapis.com",
)
BLOCKED_HOSTS_KWOK: tuple[str, ...] = (
    tuple(h for h in BLOCKED_HOSTS if not h.endswith(_KWOK_STRIP_SUFFIXES)) + _KWOK_ADD_HOSTS
)
BLOCKED_SUFFIXES_KWOK: tuple[str, ...] = (
    tuple(s for s in BLOCKED_SUFFIXES if not s.endswith(_KWOK_STRIP_SUFFIXES)) + _KWOK_ADD_SUFFIXES
)
_verify_blocklist_alignment(BLOCKED_HOSTS_KWOK, BLOCKED_SUFFIXES_KWOK)

# Compose overlay emitted next to every sandbox task's Dockerfile. Harbor's
# docker.py picks it up via `_environment_docker_compose_path` and appends
# it to the compose stack, so extra_hosts merge with the base stack.
NETWORK_DISALLOW_COMPOSE = _build_disallow_compose(BLOCKED_HOSTS)
NETWORK_DISALLOW_COMPOSE_KWOK = _build_disallow_compose(BLOCKED_HOSTS_KWOK)


@dataclass(slots=True)
class HarborTask:
    name: str
    org: str
    description: str
    instruction: str
    oracle_diff: str
    repo2env: dict[str, Any]
    difficulty: str = "medium"
    category: str = "bugfix"
    keywords: list[str] = field(default_factory=list)
    # Optional — only set for sandbox-required pipelines (e.g. pr_runtime).
    # Lite tasks (pr_diff) leave these as None; Harbor falls back to its own
    # default env / test runner for those.
    environment_dockerfile: str | None = None
    test_script: str | None = None
    # Extra files written under the task dir (relative path -> content), e.g.
    # {"tests/verifier.py": ..., "tests/f2p.json": ...}. Harbor exposes tests/
    # at /tests in the container so test.sh can read them.
    aux_files: dict[str, str] = field(default_factory=dict)
    # UUID-based directory name (Final/ convention). When set, the task dir is
    # named after this UUID instead of the human-readable slug in ``name``.
    # When None, ``write_harbor_task`` auto-generates a UUID.  The slug is
    # always preserved in task.toml as ``task.name = "<org>/<slug>"``.
    task_uuid: str | None = None
    # Optional LLM-synthesised reference oracle, shipped alongside the golden
    # slice as `solution/reference.diff`. When set, the emitter writes
    # `solution/golden.diff` + `solution/reference.diff` instead of a single
    # `solution/patch.diff`. Solve.sh always applies the golden.
    reference_diff: str | None = None


def _content_hash(task: HarborTask) -> str:
    h = hashlib.sha256()
    h.update(task.instruction.encode("utf-8"))
    h.update(b"\0")
    h.update(task.oracle_diff.encode("utf-8"))
    if task.reference_diff is not None:
        h.update(b"\0")
        h.update(task.reference_diff.encode("utf-8"))
    return f"sha256:{h.hexdigest()}"


def _samples_image_uri(bootstrap_image: str) -> str:
    """Derive the samples-style ``<host>/<repo>:task_env_rl`` tag.

    Samples task.toml uses the short alias tag ``:task_env_rl`` for
    ``[metadata.image].uri`` regardless of the actual pushed tag
    (e.g. ``task_env_rl_minio_2025_04``). We strip the digest suffix
    from the Dockerfile FROM line and append the samples alias.
    Digest form is preserved separately in ``[environment].docker_image``.
    """
    if not bootstrap_image or bootstrap_image.startswith("local/"):
        return bootstrap_image or "local/r2e-bootstrap:unknown"
    repo_only = bootstrap_image.split("@", 1)[0]
    if ":" in repo_only.rsplit("/", 1)[-1]:
        repo_only = repo_only.rsplit(":", 1)[0]
    return f"{repo_only}:task_env_rl"


def _build_samples_payload(
    *,
    task: HarborTask,
    qualified_name: str,
    repo2env: dict[str, Any],
    bootstrap_image: str,
) -> dict[str, Any]:
    """Assemble the flat Ethara-Ai/raiden-samples task.toml payload.

    Reads scalars from ``repo2env['code_instruct']`` (the cli_app pipeline's
    per-task provenance sub-dict) and promotes them to top-level ``[metadata]``
    fields + ``[metadata.runtime]`` + ``[metadata.image]`` + top-level
    ``[environment]``. Drops ``difficulty``, ``[metadata.repo2env]``, ``[agent]``,
    ``[verifier]``. Dict insertion order chosen so tomli_w emits scalars before
    sub-tables under ``[metadata]`` (TOML requires this: sub-tables shadow
    trailing scalars in the parent table).
    """
    ci = repo2env.get("code_instruct", {})
    metadata: dict[str, Any] = {
        "category": task.category,
        "keywords": list(task.keywords),
    }
    if "commands" in ci:
        metadata["commands"] = ci["commands"]
    if "behaviour_tags" in ci:
        metadata["behaviour_tags"] = ci["behaviour_tags"]
    if ci.get("subset"):
        metadata["subset"] = ci["subset"]
    if "workflow_tests" in ci:
        metadata["workflow_tests"] = ci["workflow_tests"]
    if "tests_shipped" in ci:
        metadata["tests_shipped"] = ci["tests_shipped"]
    elif "tests_in_task" in ci:
        metadata["tests_shipped"] = ci["tests_in_task"]
    if "behaviour_tag_counts" in ci:
        metadata["behaviour_tag_counts"] = ci["behaviour_tag_counts"]

    _rg = ci.get("reference_grounding")
    if isinstance(_rg, dict) and _rg:
        metadata["reference_grounding"] = dict(_rg)

    metadata["runtime"] = {
        "python_version": ci.get("python_version", "3.12"),
        "simulation_backend": ci.get("simulation_backend", "minio"),
        "entry_point": ci.get("entry_point", "submission/aws"),
        "cpus": ci.get("runtime_cpus", 1.0),
        "memory_mb": ci.get("runtime_memory_mb", 1024),
        "timeout_sec": ci.get("runtime_timeout_sec", 300),
        "pinned_deps": list(ci.get("pinned_deps", [])),
    }
    metadata["image"] = {"uri": _samples_image_uri(bootstrap_image)}

    payload: dict[str, Any] = {
        "version": "1.0",
        "task": {"name": qualified_name, "description": task.description},
        "metadata": metadata,
    }
    if bootstrap_image:
        payload["environment"] = {"docker_image": bootstrap_image}
    return payload


def write_harbor_task(
    task: HarborTask,
    dest_dir: Path,
    *,
    emit_samples_format: bool = False,
) -> Path:
    """Materialize the task directory under *dest_dir* and return the path.

    The directory is named after ``task.task_uuid`` (or an auto-generated UUID
    when the field is *None*).  ``task.toml`` inside it still carries the
    human-readable slug via ``task.name``.

    ``emit_samples_format=True`` emits the flat Ethara-Ai/raiden-samples task.toml
    schema instead of the nested ``[metadata.repo2env]`` extension: promotes
    ``code_instruct`` scalars to ``[metadata]``, adds ``[metadata.image]`` +
    ``[metadata.runtime]`` + top-level ``[environment]``, and drops
    ``difficulty`` / ``[agent]`` / ``[verifier]`` blocks. Used by the cli_app
    pipeline for samples-compatible batches.
    """
    dir_name = task.task_uuid if task.task_uuid else str(uuid4())
    task_path = dest_dir / dir_name
    task_path.mkdir(parents=True, exist_ok=True)

    # task.toml
    repo2env = dict(task.repo2env)
    # v0.2.0: introduces [metadata.repo2env.reproducibility] subtable; the bump
    # is additive — old readers ignore the new subtable, new readers see it.
    repo2env.setdefault("spec_version", "0.2.0")
    repo2env.setdefault("content_hash", _content_hash(task))
    # Default reward kinds — sandbox-required tasks override with
    # test_execution as the primary signal
    if task.test_script is not None:
        repo2env.setdefault("reward_kinds", ["test_execution", "diff_similarity"])
    else:
        repo2env.setdefault("reward_kinds", ["diff_similarity"])

    # Bootstrap image extracted from the Dockerfile's first FROM. Anchored on
    # the same regex used by `registry.integration._FROM_LINE_RE`. Both output
    # paths (default nested + samples-format flat) need this, and the samples
    # format also derives an [metadata.image].uri tag from it.
    bootstrap_image = ""
    if task.environment_dockerfile is not None:
        df = task.environment_dockerfile
        # Dockerfile ARG defaults referenced by ${NAME} / $NAME in FROM must be
        # resolved here so [environment].docker_image and [metadata.image].uri
        # carry the actual pinned digest, not the literal placeholder.
        arg_defaults: dict[str, str] = {}
        for arg_m in re.finditer(
            r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S+)",
            df,
            re.IGNORECASE | re.MULTILINE,
        ):
            arg_defaults[arg_m.group(1)] = arg_m.group(2).strip()
        _from_matches = list(re.finditer(r"^(\s*FROM\s+)(\S+)", df, re.IGNORECASE | re.MULTILINE))
        if _from_matches:
            raw = _from_matches[-1].group(2).strip()
            var_m = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", raw)
            if var_m and var_m.group(1) in arg_defaults:
                bootstrap_image = arg_defaults[var_m.group(1)]
            else:
                bootstrap_image = raw

    # For sandbox-required tasks (those that emit environment/Dockerfile),
    # seed [metadata.repo2env.reproducibility] with mode=local_only and the
    # un-pullable local image ref. `repo2rlenv push` rewrites this in-place
    # to mode=registry / inline_dockerfile after the push step.
    if task.environment_dockerfile is not None and "reproducibility" not in repo2env:
        repo2env["reproducibility"] = {
            "mode": "local_only",
            "image_ref": bootstrap_image or "local/r2e-bootstrap:unknown",
            "image_tag": bootstrap_image or "local/r2e-bootstrap:unknown",
            "image_visibility": "private",
        }

    # Harbor's task.toml requires `task.name` in `<org>/<name>` format —
    # validated at load-time by harbor.models.task.config.PackageInfo. The
    # directory is a UUID; task.toml keeps the human-readable `org/slug`
    # form so harbor accepts the task.
    qualified_name = f"{task.org}/{task.name}"
    if emit_samples_format:
        payload = _build_samples_payload(
            task=task,
            qualified_name=qualified_name,
            repo2env=repo2env,
            bootstrap_image=bootstrap_image,
        )
    else:
        payload = {
            "version": "1.0",
            "task": {
                "name": qualified_name,
                "description": task.description,
            },
            "metadata": {
                "difficulty": task.difficulty,
                "category": task.category,
                "keywords": task.keywords,
                "repo2env": repo2env,
            },
            "agent": {"timeout_sec": 1800.0},
            "verifier": {"timeout_sec": 300.0},
        }
    (task_path / "task.toml").write_bytes(tomli_w.dumps(payload).encode("utf-8"))

    # instruction.md
    (task_path / "instruction.md").write_text(task.instruction, encoding="utf-8")

    sol_dir = task_path / "solution"
    sol_dir.mkdir(exist_ok=True)
    if task.reference_diff is not None:
        (sol_dir / "golden.diff").write_text(task.oracle_diff, encoding="utf-8")
        (sol_dir / "reference.diff").write_text(task.reference_diff, encoding="utf-8")
        _sim_backend = (task.repo2env.get("code_instruct") or {}).get("simulation_backend", "")
        _aws_shim_block = (
            ""
            if _sim_backend == "kwok"
            else (
                "if [ ! -f /workspace/submission/aws ] && [ -f /workspace/submission/main.py ]; then\n"
                "  cat > /workspace/submission/aws <<'EOF'\n"
                "#!/bin/bash\n"
                'exec python /workspace/submission/main.py "$@"\n'
                "EOF\n"
                "fi\n"
                "chmod +x /workspace/submission/aws 2>/dev/null || true\n"
            )
        )
        (sol_dir / "solve.sh").write_text(
            "#!/bin/bash\n"
            "set -euxo pipefail\n"
            "mkdir -p /workspace/submission\n"
            "cd /workspace\n"
            "git config --global --add safe.directory /workspace\n"
            'DIR="$(dirname "$0")"\n'
            'GOLDEN="$DIR/golden.diff"\n'
            'REFERENCE="$DIR/reference.diff"\n'
            'CHOICE="${SOLVE_PATCH:-auto}"\n'
            'case "$CHOICE" in\n'
            "  golden)\n"
            '    PATCH="$GOLDEN"\n'
            "    ;;\n"
            "  reference)\n"
            '    PATCH="$REFERENCE"\n'
            "    ;;\n"
            "  auto|*)\n"
            '    if [ -s "$GOLDEN" ]; then\n'
            '      PATCH="$GOLDEN"\n'
            '    elif [ -s "$REFERENCE" ]; then\n'
            '      PATCH="$REFERENCE"\n'
            "    else\n"
            '      echo "solve.sh: no non-empty patch found (golden.diff or reference.diff)" >&2\n'
            "      exit 1\n"
            "    fi\n"
            "    ;;\n"
            "esac\n"
            'if [ ! -s "$PATCH" ]; then\n'
            '  echo "solve.sh: requested patch is empty: $PATCH" >&2\n'
            "  exit 1\n"
            "fi\n"
            'git apply --verbose --reject "$PATCH"\n'
            + _aws_shim_block
            + "if [ -f /workspace/submission/kubectl.go ] && [ ! -x /workspace/submission/kubectl ]; then\n"
            "  ( cd /workspace/submission && go build -o kubectl . )\n"
            "  chmod +x /workspace/submission/kubectl\n"
            "fi\n"
            "if [ -f /workspace/submission/kubectl-src/vendor/modules.txt ]; then\n"
            "  ( cd /workspace/submission/kubectl-src && GOFLAGS=-mod=vendor go build -o /workspace/submission/kubectl ./cmd/kubectl ) || echo 'solve.sh: kubectl-src vendored go build failed; retaining pre-existing /workspace/submission/kubectl' >&2\n"
            "  chmod +x /workspace/submission/kubectl 2>/dev/null || true\n"
            "elif [ -f /workspace/submission/kubectl-src/go.mod ]; then\n"
            "  ( cd /workspace/submission/kubectl-src && go build -o /workspace/submission/kubectl ./cmd/kubectl ) || echo 'solve.sh: kubectl-src go build failed; retaining pre-existing /workspace/submission/kubectl' >&2\n"
            "  chmod +x /workspace/submission/kubectl 2>/dev/null || true\n"
            "fi\n",
            encoding="utf-8",
        )
    else:
        (sol_dir / "patch.diff").write_text(task.oracle_diff, encoding="utf-8")
        (sol_dir / "solve.sh").write_text(
            "#!/bin/bash\n"
            "set -euxo pipefail\n"
            "mkdir -p /workspace/submission\n"
            "cd /workspace\n"
            "git config --global --add safe.directory /workspace\n"
            'PATCH="$(dirname "$0")/patch.diff"\n'
            'git apply --verbose --reject "$PATCH"\n',
            encoding="utf-8",
        )
    (sol_dir / "solve.sh").chmod(0o755)

    # Optional environment/Dockerfile + tests/test.sh — written only for
    # sandbox-required tasks (pr_runtime, future commit_runtime, etc.).
    if task.environment_dockerfile is not None:
        env_dir = task_path / "environment"
        env_dir.mkdir(exist_ok=True)
        (env_dir / "Dockerfile").write_text(task.environment_dockerfile, encoding="utf-8")
        # Disallow-list compose overlay sits next to the Dockerfile. Always
        # written here; the aux_files loop below runs last, so a pipeline
        # that ships its own `environment/docker-compose.yaml` via aux_files
        # overrides this default. Harbor's docker.py picks the file up via
        # _environment_docker_compose_path and appends it to the compose
        # stack, so extra_hosts merge with the base stack.
        _is_kwok_base = bootstrap_image and "kubectl_kwok" in bootstrap_image
        _compose = NETWORK_DISALLOW_COMPOSE_KWOK if _is_kwok_base else NETWORK_DISALLOW_COMPOSE
        (env_dir / "docker-compose.yaml").write_text(_compose, encoding="utf-8")
        if _is_kwok_base and not os.environ.get("R2E_SKIP_BASE_DOCKERFILE"):
            try:
                _kwok_base_path = (
                    Path(__file__).resolve().parent.parent
                    / "pipelines"
                    / "_cli_app_backends"
                    / "simulation"
                    / "kwok_base.Dockerfile"
                )
                _base_content = _kwok_base_path.read_text(encoding="utf-8")
                base_dir = env_dir / "base"
                base_dir.mkdir(exist_ok=True)
                (base_dir / "Dockerfile").write_text(_base_content, encoding="utf-8")
            except Exception as exc:
                logger.info("harbor: skipping kwok base Dockerfile (%s)", exc)
        elif bootstrap_image and not os.environ.get("R2E_SKIP_BASE_DOCKERFILE"):
            try:
                from repo2rlenv.registry.image_dockerfile import (
                    reconstruct_base_dockerfile,
                )

                _base_content = reconstruct_base_dockerfile(bootstrap_image)
                base_dir = env_dir / "base"
                base_dir.mkdir(exist_ok=True)
                (base_dir / "Dockerfile").write_text(_base_content, encoding="utf-8")
            except Exception as exc:
                logger.info(
                    "harbor: skipping environment/base/Dockerfile for %s (%s)",
                    bootstrap_image,
                    exc,
                )
    if task.test_script is not None:
        tests_dir = task_path / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test.sh").write_text(task.test_script, encoding="utf-8")
        # mark executable; harbor expects test.sh to be runnable
        (tests_dir / "test.sh").chmod(0o755)

    # Auxiliary task files (relative paths under the task dir). Harbor mounts
    # the task's tests/ dir into the container at /tests, so a pipeline can
    # ship e.g. tests/verifier.py + tests/f2p.json + tests/p2p.json as plain,
    # inspectable artifacts and have test.sh read them — instead of baking
    # everything as base64 blobs inside test.sh.
    for rel_path, content in (task.aux_files or {}).items():
        # Defensive: keep aux files inside the task dir.
        target = (task_path / rel_path).resolve()
        try:
            target.relative_to(task_path.resolve())
        except ValueError:
            raise ValueError(f"aux_file path escapes task dir: {rel_path!r}") from None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    return task_path
