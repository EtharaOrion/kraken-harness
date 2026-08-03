"""perf_runtime — repository-level performance optimization tasks.

Corpus-driven rather than scrape-driven. The harvest stage is already solved
upstream: each input record carries the base commit, the reference optimization, the
covering tests, the timed workload, and the measured expert speedup. This pipeline
turns one such record into a runnable Harbor bundle whose reward is the weighted
fraction of binary items bound in requirements/PARAMETERS.md section 5, measured
under the discipline of section 9.

Two properties separate it from `pr_runtime`, which scores fail-to-pass correctness:

  1. The graded target is a measured runtime ratio, not a test transition. The
     baseline and the optimized condition are timed on the same container, back to
     back, with repeated trials and a variance ceiling.
  2. Correctness is a precondition rather than a contributor. A faster patch that
     breaks a covering test scores zero, because a fast wrong patch is a regression a
     maintainer reverts.

Because the corpus carries the environment spec, no LLM bootstrap is needed to build
the image, so authoring is deterministic end to end. A model is invoked only at grade
time by the rubric channel.

Acknowledgment: the task shape follows SWE-fficiency (arXiv 2511.06090). No code is
copied; the corpus contract and the reward composition are this project's own.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from repo2rlenv.bootstrap.spec import LanguageHint
from repo2rlenv.emitter.harbor import HarborTask, write_harbor_task
from repo2rlenv.pipelines.base import PipelineResult
from repo2rlenv.spec.input import GenerationInput, PipelineName

logger = logging.getLogger(__name__)

# Pinned at genesis by ENGRAM and never rotated.
FORGE_TASK_NAMESPACE = uuid.UUID("c53e8f3b-526f-52c0-a04e-89e2269b237d")
HARBOR_SCHEMA_VERSION = "1.0"
REWARD_CONTRACT_PATH = "/logs/verifier/reward.txt"
REPO_PATH = "/testbed"

REQUIRED_FIELDS = (
    "instance_id",
    "repo",
    "base_commit",
    "patch",
    "problem_statement",
    "covering_tests",
    "workload",
    "speedup",
    "python_version",
    "install_cmd",
    "test_cmd",
    "created_at",
)

_ASSET_DIR = Path(__file__).parent
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# Import names that differ from their distribution name. Only used to translate a
# ModuleNotFoundError into something pip can install.
MODULE_ALIASES = {
    "yaml": "pyyaml",
    "attr": "attrs",
    "dateutil": "python-dateutil",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "dirty_equals": "dirty-equals",
}
_PR_URL = re.compile(r"https?://\S*?(?:github\.com|/pull/|/issues/)\S*")
_PR_REF = re.compile(r"(?i)\b(pull request|PR)\s*#?\d+\b|#\d{3,}")


def host_load() -> dict:
    """Normalized host load. Recorded with every measurement so a number can be read
    in the light of the machine that produced it."""
    import os

    try:
        one, five, fifteen = os.getloadavg()
        cpus = os.cpu_count() or 1
    except (OSError, AttributeError):
        return {"available": False}
    return {
        "available": True,
        "cpus": cpus,
        "load1": round(one, 2),
        "per_cpu": round(one / cpus, 3),
        "load5": round(five, 2),
        "load15": round(fifteen, 2),
    }


def wait_for_quiet(threshold: float = 0.35, timeout: int = 600, poll: int = 10) -> dict:
    """Block until the host is idle enough to measure on.

    A runtime target measured while the machine is compiling something else measures
    the machine. Building and measuring are therefore separated in time, and this is
    the barrier between them. A timeout is recorded rather than ignored, because a
    measurement taken on a busy host is a different measurement.
    """
    import time

    waited = 0
    while waited < timeout:
        load = host_load()
        if not load.get("available") or load["per_cpu"] <= threshold:
            return {"quiet": True, "waited_seconds": waited, "load": load, "threshold": threshold}
        time.sleep(poll)
        waited += poll
    return {
        "quiet": False,
        "waited_seconds": waited,
        "load": host_load(),
        "threshold": threshold,
        "note": "host never settled below the threshold; measurements taken under load",
    }


# Every in-container command must activate the conda testbed env explicitly. Docker
# runs `bash -c`, a non-interactive shell that never sources .bashrc, so the env the
# image auto-activates for a human is invisible to an automated probe.
CONDA_ACTIVATE = "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed"


def in_testbed(command: str) -> str:
    return f"{CONDA_ACTIVATE} && cd {REPO_PATH} && {command}"


def _asset(name: str) -> str:
    return (_ASSET_DIR / name).read_text(encoding="utf-8")


def diff_problems(patch: str) -> list:
    """Check every hunk header against the body that follows it.

    A reference patch whose hunk counts do not reconcile will not apply, which makes
    the reward ceiling unreachable. That is a broken task rather than a hard one, and
    it is cheaper to find here than after a ten-minute image build.
    """
    if not patch or not patch.strip():
        return [{"reason": "empty_patch"}]
    lines = patch.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    problems, i, index = [], 0, 0
    while i < len(lines):
        m = _HUNK.match(lines[i])
        if not m:
            i += 1
            continue
        index += 1
        want_old, want_new = int(m.group(2) or 1), int(m.group(4) or 1)
        old = new = 0
        i += 1
        while i < len(lines):
            line = lines[i]
            if _HUNK.match(line) or line.startswith("diff --git"):
                break
            if line.startswith("\\"):
                i += 1
                continue
            if line.startswith("-"):
                old += 1
            elif line.startswith("+"):
                new += 1
            else:
                old += 1
                new += 1
            i += 1
        if old != want_old or new != want_new:
            problems.append(
                {
                    "hunk": index,
                    "header": m.group(0),
                    "declared_old": want_old,
                    "counted_old": old,
                    "declared_new": want_new,
                    "counted_new": new,
                }
            )
    return problems


def held_out_test_files(test_patch: str) -> list:
    """Test files the upstream PR's own test patch touches.

    These are the tests the author wrote to prove the change, and they are the most
    task-specific evidence a bundle carries. They arrive at grade time and are not in
    repository history, so the agent cannot read them.
    """
    files = []
    for m in re.finditer(r"^\+\+\+ b/(\S+)", test_patch or "", re.M):
        path = m.group(1)
        if path.endswith(".py") and ("test" in Path(path).name or "/tests/" in f"/{path}"):
            files.append(path)
    return sorted(set(files))


def _assertion_name(path: str) -> str:
    """A stable, distinct, valid identifier for one held-out test file."""
    stem = re.sub(r"[^0-9a-zA-Z]+", "_", path.rsplit(".", 1)[0]).strip("_").lower()
    return f"test_heldout_{stem}"


def _canonical_hash(parts: dict) -> str:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _task_uuid(content_hash: str) -> str:
    return str(uuid.uuid5(FORGE_TASK_NAMESPACE, content_hash))


def _decontaminate(text: str) -> str:
    """Strip the upstream thread so the brief is not recoverable by searching it.

    Contamination resistance rests on construction rather than on secrecy: the task
    stays public, but the prompt no longer points at the merged pull request whose
    diff is the answer.
    """
    text = _PR_URL.sub("the upstream change", text or "")
    text = _PR_REF.sub("the upstream change", text)
    return text.strip()


# Deliberately free of any word a leak scan keys on. Replacement prose that trips the
# very detector it exists to satisfy makes every future audit report a false positive.
NEUTRAL_WORKLOAD_DOC = (
    '"""Timed workload. The grader runs this script verbatim against the tree as\n'
    "submitted and against the baseline. It states what is measured, and nothing\n"
    'about how the measured code should be written."""'
)


def _sanitize_workload(source: str) -> str:
    """Strip the prose that hands the agent the answer.

    The workload arrives from the corpus with comments and a module docstring written
    by whoever already knew the fix, and they routinely name it outright: the exact
    attribute to add, the function to stop calling, even the expected speedup. The
    brief gives the agent this file verbatim as the script the grader runs, so that
    prose turns a discovery task into a dictation task and the measured speedup stops
    being evidence of anything.

    Comments and the module docstring carry no execution semantics for a timed script,
    so dropping them changes what the agent is told without changing what is timed.
    Line positions are preserved so a traceback still points where it used to.
    """
    import ast
    import io
    import tokenize

    if not (source or "").strip():
        return source
    try:
        original = ast.parse(source)
    except SyntaxError:
        # Not parseable here means the corpus shipped something unusual. Emit it
        # unchanged rather than silently mangling the one script that is timed.
        return source

    lines = source.splitlines(keepends=True)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):
        return source
    # Reverse order so earlier splices do not move later positions. A comment always
    # runs to end of line, so truncating at its start column removes exactly it.
    for tok in reversed(toks):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        line = lines[row - 1]
        newline = "\n" if line.endswith("\n") else ""
        lines[row - 1] = line[:col].rstrip() + newline

    stripped = "".join(lines)
    doc = ast.parse(stripped)
    first = doc.body[0] if doc.body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        out = stripped.splitlines(keepends=True)
        start, end = first.lineno - 1, first.end_lineno
        span = end - start
        replacement = [ln + "\n" for ln in NEUTRAL_WORKLOAD_DOC.split("\n")]
        if len(replacement) > span:
            replacement = ['"""Timed workload, run verbatim by the grader."""\n']
        # Pad back to the original span so every line below keeps its number and a
        # traceback still points where it did before.
        replacement += ["\n"] * (span - len(replacement))
        out[start:end] = replacement
        stripped = "".join(out)

    # The sanitized script must still be the same program. Compare structure with
    # docstrings normalized away, so a mismatch means the strip broke something.
    try:
        if ast.dump(_strip_docstrings(ast.parse(stripped))) != ast.dump(
            _strip_docstrings(original)
        ):
            return source
    except SyntaxError:
        return source
    return stripped


def _strip_docstrings(tree):
    """Normalize away every docstring so two trees compare on executable structure."""
    import ast

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            first.value.value = ""
    return tree


# --- bundle templates ---------------------------------------------------------

BUNDLE_DOCKERFILE = """\
# Auto-generated by Repo2RLEnv perf_runtime.
#
# Self-contained build recipe, modelled on the reference implementation at
# SWE-fficiency's swefficiency/harness/dockerfiles.py (arXiv 2511.06090). The tiers it
# reference builds as separate images are inlined here in the same order, so the
# environment can be rebuilt from ubuntu:22.04 without reaching for a prebuilt image.
#
# The image this task was calibrated against is recorded in task.toml as
# calibrated_image. A rebuild resolves package versions afresh, so it reproduces the
# recipe rather than the bytes; the recorded digest is what the target was measured on.

# ---- tier 1: base -----------------------------------------------------------
FROM ubuntu:22.04

# Proxy / MITM support (empty defaults = no-op), as the reference base carries.
ARG http_proxy=""
ARG https_proxy=""
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG no_proxy=""
ARG NO_PROXY=""
ARG CA_CERT_PATH=""

ARG DEBIAN_FRONTEND=noninteractive

# Determinism, image-wide. measure.py sets PYTHONHASHSEED for the timed workload
# only; setting it here also covers the correctness run and the agent's own
# execution, so dict ordering cannot differ between the phases that judge a patch.
ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PYTHONHASHSEED=0 \\
    TZ=UTC \\
    LC_ALL=C.UTF-8

ENV http_proxy=${http_proxy} \\
    https_proxy=${https_proxy} \\
    HTTP_PROXY=${HTTP_PROXY} \\
    HTTPS_PROXY=${HTTPS_PROXY} \\
    no_proxy=${no_proxy} \\
    NO_PROXY=${NO_PROXY}

RUN apt update && apt install -y \\
wget git build-essential libffi-dev libtiff-dev python3 python3-pip python-is-python3 \\
jq curl locales locales-all tzdata python3-dev python3-setuptools gcc gfortran \\
pkg-config libopenblas-dev libblas-dev liblapack-dev util-linux \\
&& rm -rf /var/lib/apt/lists/*

# Conda, architecture resolved at build time so the recipe is multiarch.
RUN CONDA_ARCH=$(uname -m) && \\
    wget "https://repo.anaconda.com/miniconda/Miniconda3-py311_24.7.1-0-Linux-${CONDA_ARCH}.sh" -O miniconda.sh \\
    && bash miniconda.sh -b -p /opt/miniconda3 && rm miniconda.sh
ENV PATH=/opt/miniconda3/bin:$PATH
RUN conda init --all
RUN conda config --append channels conda-forge
RUN conda clean --all --yes

RUN if [ -n "${CA_CERT_PATH}" ]; then \\
        echo "export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \\
        echo "export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \\
        echo "export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh && \\
        echo "export PIP_CERT=/etc/ssl/certs/ca-certificates.crt" >> /etc/profile.d/custom-ca.sh; \\
    fi

ENV PIP_NO_CACHE_DIR=1
RUN adduser --disabled-password --gecos 'dog' nonroot

# ---- tier 2: environment ----------------------------------------------------
COPY ./setup_env.sh /root/
RUN chmod +x /root/setup_env.sh
RUN /bin/bash -c "source ~/.bashrc && /root/setup_env.sh"

WORKDIR /testbed/
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc

# ---- agent SDK --------------------------------------------------------------
# Pinned, and deliberately in its own venv rather than the testbed environment.
# openhands-sdk pulls fastapi and google-cloud-aiplatform; resolving those against
# the repository under test could move a dependency the measurement depends on.
ARG OPENHANDS_SDK_VERSION=v1.12.0
ARG OPENHANDS_SDK_URL=https://github.com/Ethara-Ai/software-agent-sdk/archive/refs/tags
# conda, not `python3 -m venv`: PATH resolves python3 to miniconda's 3.11 and the
# SDK requires >=3.12, so a venv off the ambient interpreter fails to resolve.
RUN conda create -y -p /opt/openhands-sdk-venv python=3.12 && conda clean --all --yes && \\
    /opt/openhands-sdk-venv/bin/pip install --no-cache-dir --upgrade pip && \\
    /opt/openhands-sdk-venv/bin/pip install --no-cache-dir \\
        "openhands-sdk @ ${OPENHANDS_SDK_URL}/${OPENHANDS_SDK_VERSION}.tar.gz#subdirectory=openhands-sdk" \\
        "openhands-tools @ ${OPENHANDS_SDK_URL}/${OPENHANDS_SDK_VERSION}.tar.gz#subdirectory=openhands-tools" \\
        fastapi "google-cloud-aiplatform>=1.38"

# A separate prefix is not separate enough. The image WORKDIR is /testbed and Python
# prepends the working directory to sys.path, so a repository whose package name is
# also an SDK dependency shadows the SDK's own copy: running the SDK from /testbed
# against pydantic imports /testbed/pydantic and dies on a mismatched pydantic_core.
# fastapi is in the corpus too and is also an SDK dependency, so this is a class of
# collision rather than one instance of it.
#
# sitecustomize cannot fix it: CPython prepends the -c working directory after site
# initialisation, so a filter written there runs before the entry it wants to remove
# exists. PYTHONSAFEPATH stops the entry being added at all.
#
# Safe image-wide, and verified so: the repository under test is an editable install,
# so it resolves through site-packages rather than through the working directory.
ENV PYTHONSAFEPATH=1

# ---- tier 3: instance -------------------------------------------------------
COPY ./setup_repo.sh /root/
RUN /bin/bash /root/setup_repo.sh

# Record installed dependencies for reproducibility, as the reference tier does.
RUN /bin/bash -c "source /opt/miniconda3/bin/activate && conda activate testbed && \\
    pip freeze > /testbed/.dep-manifest.txt" 2>/dev/null || true

WORKDIR /testbed/
"""

BASE_DOCKERFILE = """\
# Tier 1, shared by every instance. Multiarch: no --platform pin, so buildx injects
# the target and conda resolves its own architecture at build time.
FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

# Determinism, image-wide. measure.py sets PYTHONHASHSEED for the timed workload
# only; setting it here also covers the correctness run and the agent's own
# execution, so dict ordering cannot differ between the phases that judge a patch.
ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PYTHONHASHSEED=0 \\
    TZ=UTC \\
    LC_ALL=C.UTF-8

RUN apt update && apt install -y \\
wget git build-essential libffi-dev libtiff-dev python3 python3-pip python-is-python3 \\
jq curl locales locales-all tzdata python3-dev python3-setuptools gcc gfortran \\
pkg-config libopenblas-dev libblas-dev liblapack-dev util-linux \\
&& rm -rf /var/lib/apt/lists/*

RUN CONDA_ARCH=$(uname -m) && \\
    wget "https://repo.anaconda.com/miniconda/Miniconda3-py311_24.7.1-0-Linux-${CONDA_ARCH}.sh" -O miniconda.sh \\
    && bash miniconda.sh -b -p /opt/miniconda3 && rm miniconda.sh
ENV PATH=/opt/miniconda3/bin:$PATH
RUN conda init --all
RUN conda config --append channels conda-forge
RUN conda clean --all --yes

ENV PIP_NO_CACHE_DIR=1
RUN adduser --disabled-password --gecos 'dog' nonroot
"""

ENV_DOCKERFILE = """\
# Tier 2. Creates the conda `testbed` environment the graded run activates.
FROM {base_tag}

COPY ./setup_env.sh /root/
RUN chmod +x /root/setup_env.sh
RUN /bin/bash -c "source ~/.bashrc && /root/setup_env.sh"

WORKDIR /testbed/
RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc
"""

INSTANCE_DOCKERFILE = """\
# Tier 3. Clones the repository at the base commit and installs it into testbed.
FROM {env_tag}

COPY ./setup_repo.sh /root/
RUN /bin/bash /root/setup_repo.sh

# Record installed dependencies for reproducibility, as the reference instance tier
# does. Best-effort: a record whose env cannot freeze is still a valid task.
RUN /bin/bash -c "source /opt/miniconda3/bin/activate && conda activate testbed && \
    pip freeze > /testbed/.dep-manifest.txt" 2>/dev/null || true

WORKDIR /testbed/
"""

SETUP_ENV_SH = """\
#!/bin/bash
# Tier 2: create the conda `testbed` env at the row's python version and install the
# pip dependencies the corpus record names.
set -euo pipefail

source /opt/miniconda3/etc/profile.d/conda.sh

conda create -n testbed python={python_version} -y
conda activate testbed

python -m pip install --upgrade pip setuptools wheel

# Row pip_packages
pip install pytest {pip_packages}

# Override env_extra
{env_extra}
"""

SETUP_REPO_SH = """\
#!/bin/bash
# Tier 3: clone the repo at base_commit, run install_cmd inside the testbed env,
# apply per-repo override deps, freeze, and tag the base state.
set -euo pipefail

source /opt/miniconda3/etc/profile.d/conda.sh
conda activate testbed

git clone https://github.com/{repo}.git /testbed
cd /testbed
git fetch --all --tags --quiet
git checkout {base_commit}

# Keep local build artifacts out of git so the agent's diff stays clean. Without this
# an editable install leaves egg-info and caches in the tree, and every submission diff
# would carry them as if the agent had written them.
cat >> /testbed/.git/info/exclude <<'EOF'
.dep-manifest.txt
*.egg-info/
__pycache__/
*.pyc
build/
dist/
.pytest_cache/
EOF

# Row pre_install_cmds
{pre_install}

# Row install_cmd
{install_cmd}

# Override repo_extra
{repo_extra}

pip freeze > /testbed/.dep-manifest.txt

git config user.email kraken@ethara.ai
git config user.name kraken
git tag kraken-base {base_commit}
"""

TEST_SH = """\
#!/usr/bin/env bash
# GENERATED SECTION. DO NOT HAND-EDIT.
# Verifier entry point. Terminates by writing the bound reward contract path, and
# attributes every zero to a machine-readable reason rather than to an empty file.
set -uo pipefail

mkdir -p /logs/verifier
cd {repo_path}
source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed

# Snapshot the submission BEFORE the held-out tests are applied. Taking it afterwards
# would fold the graded test files into the agent's diff, which defeats the size guard
# and makes every no-test-edit criterion unanswerable.
git diff kraken-base > /logs/verifier/agent_patch.diff 2>/dev/null || true

# Held-out tests arrive at grade time. They are never committed into repository history.
# A test patch that is present but will not apply is a broken graded set, not a warning:
# swallowing the error would grade against the in-tree tests while claiming a held-out
# set, which is a silent weakening of the very channel that carries the gate.
if [ -f /environment/test_patch.diff ] && [ -s /environment/test_patch.diff ]; then
    if ! git apply --whitespace=nowarn /environment/test_patch.diff; then
        mkdir -p /logs/verifier
        printf '0.0000\n' > {reward_path}
        printf '{{"reward": 0.0, "reason": "held_out_test_patch_failed_to_apply"}}\n' \
            > /logs/verifier/result.json
        exit 0
    fi
fi

python /tests/verify.py
rc=$?

if [ -f /logs/verifier/void.marker ]; then
    # The run could not be measured, so it is repeated and never scored. Harbor
    # requires a reward file from every trial regardless, and raises
    # RewardFileNotFoundError without one, which turns a clean void into a crashed
    # trial. Report the void as a metric instead: kraken_void marks it, and
    # result.json keeps status "void" so the pilot excludes it from the estimator.
    # Anything averaging the bare reward must filter on kraken_void first.
    printf '{"reward": 0.0, "kraken_void": 1.0}\\n' > /logs/verifier/reward.json
    exit 75
fi

if [ ! -s {reward_path} ]; then
    printf '0.0000\\n' > {reward_path}
    printf '{{"reward": 0.0, "reason": "verifier_did_not_write_reward"}}\\n' \\
        > /logs/verifier/result.json
fi
exit $rc
"""

VERIFY_PY = '''\
"""Verifier orchestration for this bundle. GENERATED SECTION. DO NOT HAND-EDIT.

Order is bound by requirements/PARAMETERS.md section 5 and is not a style choice.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/tests")

import grade as G          # noqa: E402
import measure as M        # noqa: E402

REPO = Path("{repo_path}")
TARGETS = json.loads(Path("/tests/targets.json").read_text())
WEIGHTS = json.loads(Path("/tests/test_weights.json").read_text())
RUBRIC = json.loads(Path("/tests/rubric.json").read_text())


def submission_patch() -> str:
    """The snapshot taken before the held-out tests were applied."""
    snapshot = Path("/logs/verifier/agent_patch.diff")
    if snapshot.exists():
        return snapshot.read_text()
    proc = subprocess.run(["git", "-C", str(REPO), "diff", "kraken-base"],
                          capture_output=True, text=True)
    return proc.stdout


def correctness_passes() -> bool:
    proc = subprocess.run(TARGETS["test_cmd"], shell=True, cwd=str(REPO),
                          capture_output=True, text=True)
    Path("/logs/verifier/test-stdout.txt").write_text(proc.stdout + proc.stderr)
    return proc.returncode == 0


def pytest_items() -> dict:
    """Held-out assertions. Reported per item so per-assertion rates are reportable."""
    out = {{}}
    proc = subprocess.run([sys.executable, "-m", "pytest", "/tests/test_outputs.py",
                           "-q", "--no-header", "-p", "no:cacheprovider"],
                          cwd=str(REPO), capture_output=True, text=True)
    Path("/logs/verifier/pytest_results.json").write_text(
        json.dumps({{"stdout": proc.stdout[-8000:], "returncode": proc.returncode}}, indent=2))
    for name in TARGETS["behaviour_assertions"]:
        out[name] = "PASSED" if proc.returncode == 0 else "FAILED"
    return out


def rubric_items() -> dict:
    """The judge council. Absent keys degrade to unscored rather than to a free pass."""
    results = {{}}
    unscored = []
    for crit in RUBRIC["criteria"]:
        # None means unscored, which is excluded from the denominator. False would
        # mean the judge looked and said no.
        results[crit["id"]] = None
        unscored.append(crit["id"])
    Path("/logs/verifier/rubric_results.json").write_text(json.dumps(
        {{"judges": RUBRIC["judges"], "aggregation": RUBRIC["aggregation"],
          "unscored": unscored,
          "note": "No judge key reached the verifier through the declared environment "
                  "block, so every rubric criterion is unscored and contributes nothing. "
                  "An unscored criterion never awards points."}}, indent=2))
    return results


def main() -> int:
    patch = submission_patch()
    if G.is_noop(patch):
        G.emit({{"reward": 0.0, "reason": "empty_or_noop_patch"}})
        return 0

    crossed = G.scan_red_lines(patch)
    if crossed:
        G.emit({{"reward": 0.0, "reason": "red_line_crossed", "red_lines": crossed}})
        return 0

    ok = correctness_passes()
    if not ok:
        G.emit({{"reward": 0.0, "reason": "correctness_gate_failed"}})
        return 0

    measurement = M.measure_speedup(Path("/tests/workload.py"), REPO,
                                    baseline_ref="kraken-base")
    Path("/logs/verifier/baseline.out").write_text(json.dumps(measurement["baseline"], indent=2))
    Path("/logs/verifier/optimized.out").write_text(json.dumps(measurement["optimized"], indent=2))

    result = G.grade(patch=patch, applied=True, correctness_passed=ok,
                     measurement=measurement, target=TARGETS["target_speedup"],
                     weights=WEIGHTS, pytest_results=pytest_items(),
                     rubric_results=rubric_items())
    G.emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

INSTRUCTION = """\
# Make it faster without breaking it

{statement}

## What you are given

- The full source tree at `{repo_path}`, checked out at the commit this task starts from.
- A timed workload at `/tests/workload.py`. This is the exact script the grader runs.

## What you must do

Speed up the code path the workload exercises, without changing observable behavior.
The existing tests already pass. They must still pass when you are done.

## How you are scored

Your reward is continuous in `[0, 1]`.

- Correctness is a precondition. If the covering tests do not pass on your patched
  code, the reward is `0.0` and nothing else is consulted.
- Speed is scored in bands against an expert target, so partial progress earns
  partial credit. Reaching more of the expert's gain earns more.
- The workload is timed with repeated trials, discarded warmup, process isolation,
  and a variance ceiling. A single lucky run does not move the score.
- An empty or no-op patch scores exactly `0.0`.

## Rules

- Do not modify the workload, the tests, or anything under `/tests`.
- Do not write to the reward file or any path under `/logs`.
- Do not manipulate timing, the clock, or the measurement harness.
- Do not special-case the graded workload while leaving the general path slower.

A patch that special-cases the measured input is not an optimization. It is the one
failure mode this task exists to catch.
"""


@dataclass(slots=True)
class _Emitted:
    task_dir: Path
    uuid: str
    instance_id: str


class PerfRuntimePipeline:
    """Turn harvested performance instances into graded Harbor bundles."""

    name: ClassVar[PipelineName] = PipelineName.PERF_RUNTIME
    experimental: ClassVar[bool] = True
    language_hint: ClassVar[LanguageHint] = LanguageHint.PYTHON
    supported_languages: ClassVar[tuple] = ("python",)
    # The harvested corpus already carries the environment spec, so the image is
    # built deterministically from the record and no LLM bootstrap is involved.
    requires_bootstrap: ClassVar[bool] = False

    def __init__(self, gen_input: GenerationInput, options: Any) -> None:
        self.input = gen_input
        self.options = options

    # --- corpus ---------------------------------------------------------------

    def load_corpus(self) -> list:
        """Read every admissible record. A record missing a mandatory field is excluded."""
        if not hasattr(self, "_rejected"):
            self._rejected = {}
        corpus = Path(getattr(self.options, "corpus", "harvest"))
        paths = sorted(corpus.glob("*.jsonl")) if corpus.is_dir() else [corpus]
        records, skipped = [], {}
        repos = set(getattr(self.options, "repos", []) or [])
        instances = set(getattr(self.options, "instances", []) or [])
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                missing = [f for f in REQUIRED_FIELDS if not rec.get(f)]
                if missing:
                    skipped[f"missing:{','.join(missing)}"] = (
                        skipped.get(f"missing:{','.join(missing)}", 0) + 1
                    )
                    continue
                bad_patch = diff_problems(rec["patch"])
                if bad_patch:
                    logger.error(
                        "%s: reference patch is malformed and cannot apply: %s",
                        rec["instance_id"],
                        bad_patch[:2],
                    )
                    skipped["malformed_reference_patch"] = (
                        skipped.get("malformed_reference_patch", 0) + 1
                    )
                    self._rejected[rec["instance_id"]] = {
                        "reason": "malformed_reference_patch",
                        "detail": bad_patch,
                    }
                    continue
                if rec.get("test_patch"):
                    bad_tests = diff_problems(rec["test_patch"])
                    if bad_tests:
                        # Dropping it is the honest move. Applying it with a swallowed
                        # error would silently grade against in-tree tests while the
                        # bundle claimed a held-out set.
                        logger.warning(
                            "%s: held-out test patch is malformed and is dropped: %s",
                            rec["instance_id"],
                            bad_tests[:1],
                        )
                        rec = dict(rec, test_patch="", test_patch_malformed=bad_tests)
                        self._rejected.setdefault(rec["instance_id"], {})
                        self._rejected[rec["instance_id"]]["test_patch_dropped"] = bad_tests
                if repos and rec["repo"] not in repos:
                    skipped["repo_not_selected"] = skipped.get("repo_not_selected", 0) + 1
                    continue
                if instances and rec["instance_id"] not in instances:
                    skipped["instance_not_selected"] = skipped.get("instance_not_selected", 0) + 1
                    continue
                records.append(rec)
        self._skips = skipped
        limit = getattr(self.options, "limit", 0) or 0
        return records[:limit] if limit else records

    # --- image ----------------------------------------------------------------

    def setup_scripts(self, rec: dict) -> dict:
        """The two scripts the env and instance tiers run, built from the record."""
        extra = rec.get("env_extra") or []
        repo_extra = rec.get("repo_extra") or []
        return {
            "setup_env.sh": SETUP_ENV_SH.format(
                python_version=rec["python_version"],
                pip_packages=" ".join(rec.get("pip_packages") or []),
                env_extra=(f"pip install {' '.join(extra)}" if extra else "# (none)"),
            ),
            "setup_repo.sh": SETUP_REPO_SH.format(
                repo=rec["repo"],
                base_commit=rec["base_commit"],
                pre_install="\n".join(rec.get("pre_install_cmds") or []) or "# (none)",
                install_cmd=rec["install_cmd"],
                repo_extra=(f"pip install {' '.join(repo_extra)}" if repo_extra else "# (none)"),
            ),
        }

    def dockerfile(self, rec: dict) -> str:
        """The instance tier, which is what the bundle ultimately pins."""
        return INSTANCE_DOCKERFILE.format(env_tag=self._env_tag(rec))

    @staticmethod
    def _env_tag(rec: dict) -> str:
        return f"kraken.env.{rec['instance_id'].lower()}:latest"

    def _build(self, tag: str, dockerfile: str, context: Path, files: dict | None = None) -> tuple:
        context.mkdir(parents=True, exist_ok=True)
        (context / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        for name, body in (files or {}).items():
            (context / name).write_text(body, encoding="utf-8")
        proc = subprocess.run(
            ["docker", "build", "-q", "-t", tag, "-f", str(context / "Dockerfile"), str(context)],
            capture_output=True,
            text=True,
            timeout=getattr(self.options, "build_timeout_sec", 3600),
        )
        if proc.returncode != 0:
            return None, proc.stderr[-1500:]
        return proc.stdout.strip(), None

    def build_image(self, rec: dict, dockerfile: str, build_dir: Path) -> tuple:
        """Build the three tiers in order and return the instance image, digest-pinned.

        Tier 1 is shared by every instance and is built once. Tiers 2 and 3 are per
        record. A floating tag is never emitted: the bundle pins the instance digest.
        """
        scripts = self.setup_scripts(rec)
        base_tag = "kraken.base:latest"

        if not getattr(self, "_base_built", False):
            _, error = self._build(base_tag, BASE_DOCKERFILE, build_dir.parent / "_base")
            if error:
                return None, f"base tier: {error}"
            self._base_built = True

        env_tag = self._env_tag(rec)
        _, error = self._build(
            env_tag,
            ENV_DOCKERFILE.format(base_tag=base_tag),
            build_dir / "env",
            {"setup_env.sh": scripts["setup_env.sh"]},
        )
        if error:
            return None, f"env tier: {error}"

        instance_tag = f"kraken.instance.{rec['instance_id'].lower()}:latest"
        digest, error = self._build(
            instance_tag,
            INSTANCE_DOCKERFILE.format(env_tag=env_tag),
            build_dir / "instance",
            {"setup_repo.sh": scripts["setup_repo.sh"]},
        )
        if error:
            return None, f"instance tier: {error}"
        if not digest.startswith("sha256:"):
            inspect = subprocess.run(
                ["docker", "image", "inspect", instance_tag, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
            )
            digest = inspect.stdout.strip()

        registry = getattr(self.options, "registry", "") or ""
        if registry:
            pushed, error = self._push(registry, rec, instance_tag)
            if error:
                return None, f"registry push: {error}"
            return pushed, None
        return f"kraken.instance.{rec['instance_id'].lower()}@{digest}", None

    def _push(self, registry: str, rec: dict, local_tag: str) -> tuple:
        """Push the instance tier and return its registry digest.

        A locally built digest proves what ran here and nothing about what anyone
        else can run. BuildKit resolves a digest-pinned FROM against a registry and
        never against the local image store, so a local-only image is unrunnable by
        the runtime that ships. The digest returned here is the registry manifest
        digest, which is not the local image id and is the one that travels.
        """
        owner, name = rec["repo"].split("/", 1)
        repo_path = f"{registry.rstrip('/')}/kraken/{owner}_m_{name}".lower()
        remote = f"{repo_path}:{rec['instance_id'].lower()}"

        if ".dkr.ecr." in registry:
            region = registry.split(".dkr.ecr.")[1].split(".")[0]
            subprocess.run(
                [
                    "aws",
                    "ecr",
                    "create-repository",
                    "--region",
                    region,
                    "--repository-name",
                    f"kraken/{owner}_m_{name}".lower(),
                ],
                capture_output=True,
                text=True,
            )  # already-exists is fine

        for args in (["docker", "tag", local_tag, remote], ["docker", "push", remote]):
            proc = subprocess.run(args, capture_output=True, text=True)
            if proc.returncode != 0:
                return None, f"{' '.join(args[:2])}: {proc.stderr.strip()[:200]}"

        proc = subprocess.run(
            ["docker", "inspect", "--format", "{{index .RepoDigests 0}}", remote],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or "@" not in proc.stdout:
            return None, "pushed but no repo digest resolved"
        return proc.stdout.strip(), None

    # --- grounding ------------------------------------------------------------

    def grounding(self, rec: dict, image_ref: str | None) -> dict:
        """The single derivation source. Everything private is derived from this."""
        files = sorted({m.group(1) for m in re.finditer(r"^\+\+\+ b/(\S+)", rec["patch"], re.M)})
        symbols = sorted(
            {m.group(1) for m in re.finditer(r"^[-+]\s*def\s+(\w+)", rec["patch"], re.M)}
        )
        covering = list(rec["covering_tests"])
        # One graded assertion per held-out test file, so each can fail on its own.
        # Naming them by a count produced identical duplicates that could not
        # discriminate anything while still carrying weight.
        held_out = held_out_test_files(rec.get("test_patch") or "")
        asserts = [_assertion_name(f) for f in held_out]
        if not asserts:
            asserts = ["test_covering_suite"]
        return {
            "instance_id": rec["instance_id"],
            "repo": rec["repo"],
            "base_commit": rec["base_commit"],
            "repo_path": REPO_PATH,
            "workload_path": "/tests/workload.py",
            "target_speedup": round(float(rec["speedup"]), 6),
            "image_ref": image_ref,
            "provenance": {
                "origin": "derived",
                "provenance_date": rec["created_at"][:10],
                "upstream_identity": f"{rec['repo']}#{rec.get('pull_number')}",
                "upstream_url": rec.get("pr_url"),
                "upstream_license": "see upstream repository",
                "modifications": [
                    "converted to Harbor delivery format",
                    "brief rewritten so the upstream thread is not recoverable from the prompt",
                    "reward recomposed as a weighted fraction over binary items",
                    "measurement discipline applied per requirements/PARAMETERS.md section 9",
                ],
            },
            "reference": {
                "files_touched": files,
                "symbols": symbols,
                "patch_bytes": len(rec["patch"]),
            },
            "correctness": {
                "covering_tests": covering,
                "test_cmd": self._test_cmd(rec, covering),
                "behaviour_assertions": asserts,
                # Path per assertion, so the generated test runs the real file rather
                # than re-running the covering suite under a different name.
                # strict: asserts is built one-to-one from held_out above, so a length
                # mismatch is a bug rather than something to truncate silently.
                "held_out_tests": dict(zip(asserts, held_out, strict=True)) if held_out else {},
                "log_parser_type": rec.get("log_parser_type", "pytest"),
            },
            "rubric_policy": {
                "judges": ["claude-opus", "claude-sonnet", "claude-haiku"],
                "aggregation": "per-criterion majority vote",
            },
            "truth": self._truth(rec, files, symbols),
        }

    @staticmethod
    def _test_cmd(rec: dict, covering: list) -> str:
        """Resolve the corpus test-command template against the covering set.

        The corpus ships `pytest {test_files}`. Shipping that literal into a container
        runs pytest against a path that does not exist, which reads as a correctness
        failure on every submission including the reference one.
        """
        cmd = rec.get("test_cmd_override") or rec["test_cmd"]
        files = " ".join(covering)
        if "{test_files}" in cmd:
            cmd = cmd.replace("{test_files}", files)
        elif not any(t in cmd for t in covering):
            cmd = f"{cmd.rstrip()} {files}".strip()
        return cmd

    def _truth(self, rec: dict, files: list, symbols: list) -> dict:
        hot = files[0] if files else "the hot path"
        sym = symbols[0] if symbols else "the hot function"
        return {
            "steps": [
                {
                    "action": "Profile the workload and localize the dominant cost.",
                    "state": f"The hot path is identified as `{sym}` in `{hot}`.",
                    "checker": "completion_hotpath_touched",
                },
                {
                    "action": "Read the surrounding code and identify the invariant it maintains.",
                    "state": "The behaviour that must be preserved is known and stated.",
                    "checker": "instruction_behavior_preserved_claim",
                },
                {
                    "action": "Apply the algorithmic or data-structural change that removes the cost.",
                    "state": "The tree differs from base only inside the implementation.",
                    "checker": "completion_algorithmic_change",
                },
                {
                    "action": "Run the covering tests.",
                    "state": "Every covering test is green on the patched tree.",
                    "checker": "test_covering_tests_pass",
                },
                {
                    "action": "Re-time the workload under the measurement discipline.",
                    "state": f"The measured ratio reaches the {round(float(rec['speedup']), 4)}x target.",
                    "checker": "speed_band_100",
                },
            ],
            "rejected_routes": [
                {
                    "route": "Special-case the workload input and return a precomputed result.",
                    "why": "The general path is unchanged, so the covering tests that exercise other "
                    "inputs fail, and the safety criterion triggers its penalty.",
                },
                {
                    "route": "Edit or weaken the covering tests so the gate passes.",
                    "why": "The tests arrive at grade time from outside the tree, so an edit inside "
                    "the repository never reaches the graded set.",
                },
                {
                    "route": "Patch the clock or the timing harness to report a smaller elapsed value.",
                    "why": "Clock manipulation is a declared red line and forces zero before any "
                    "item is scored.",
                },
                {
                    "route": "Stop at the first passing patch with a shallow gain.",
                    "why": "Correctness alone earns no speed band. The bands price how much of the "
                    "expert gain was actually recovered.",
                },
                {
                    "route": "Write the reward file directly.",
                    "why": "A declared red line, detected as a state change rather than as intent.",
                },
            ],
        }

    # --- emission -------------------------------------------------------------

    def emit_one(self, rec: dict, out_dir: Path, image_ref: str | None = None) -> _Emitted | None:
        build_error = None
        if image_ref:
            # Reuse the image already built for this record. Rebuilding can yield a
            # different digest, which would leave the gate testing an image the bundle
            # does not pin.
            pass
        elif getattr(self.options, "skip_image_build", False):
            # Dry run: emit with a clearly non-runnable placeholder so no caller can
            # mistake an unbuilt bundle for a graded one.
            image_ref = "local/kraken-unbuilt@sha256:" + "0" * 64
        else:
            image_ref, build_error = self.build_image(
                rec, self.dockerfile(rec), out_dir / ".build" / rec["instance_id"]
            )
            if build_error:
                logger.warning("image build failed for %s: %s", rec["instance_id"], build_error)
                self._skips["image_build_failed"] = self._skips.get("image_build_failed", 0) + 1
                return None

        grounding = self.grounding(rec, image_ref)
        instruction = INSTRUCTION.format(
            statement=_decontaminate(rec["problem_statement"]), repo_path=REPO_PATH
        )

        content_hash = _canonical_hash(
            {
                "instruction": instruction,
                "patch": rec["patch"],
                "workload": rec["workload"],
                "grounding": grounding,
                "schema": HARBOR_SCHEMA_VERSION,
            }
        )
        task_uuid = _task_uuid(content_hash)

        # A bundle without a resolved digest would have to rebuild at rollout, which
        # is a pipeline failure rather than a slow path, so it is refused here.
        if not image_ref:
            self._skips["image_digest_unresolved"] = (
                self._skips.get("image_digest_unresolved", 0) + 1
            )
            logger.error(
                "%s: no image digest resolved, refusing to emit a bundle that "
                "would rebuild at rollout",
                rec["instance_id"],
            )
            return None
        # The recipe takes no image argument now. The image the target was measured
        # against is still recorded in task.toml, because a rebuilt environment
        # reproduces the recipe and not the bytes.
        # The bundle Dockerfile is never exercised by calibration, which measures the
        # prebuilt tiers. A recipe that cannot parse would therefore ship green. Check
        # it here, where the failure is an authoring error rather than a rollout one.
        bad = [ln for ln in BUNDLE_DOCKERFILE.splitlines() if "${{" in ln or "}}" in ln]
        if bad:
            raise ValueError(
                "bundle Dockerfile carries unresolved format braces, which docker "
                f"rejects as a bad substitution: {bad[0].strip()[:80]}"
            )
        dockerfile = BUNDLE_DOCKERFILE

        aux = {
            "tests/workload.py": _sanitize_workload(rec["workload"]),
            "tests/measure.py": _asset("_perf_runtime_measure.py"),
            "tests/grade.py": _asset("_perf_runtime_grade.py"),
            "tests/verify.py": VERIFY_PY.format(repo_path=REPO_PATH),
            "environment/test_patch.diff": rec.get("test_patch") or "",
            **{f"environment/{name}": body for name, body in self.setup_scripts(rec).items()},
            "solution/grounding.yaml": json.dumps(grounding, indent=2, sort_keys=True) + "\n",
            "solution/recompute.py": _asset("_perf_runtime_recompute.py"),
        }

        task = HarborTask(
            name=rec["instance_id"].replace("__", "-").lower(),
            org="kraken",
            description=f"Repository-level performance optimization on {rec['repo']}",
            instruction=instruction,
            oracle_diff=rec["patch"],
            difficulty="unmeasured",
            category="performance",
            keywords=["performance", "optimization", rec["repo"].split("/")[0]],
            environment_dockerfile=dockerfile,
            test_script=TEST_SH.format(repo_path=REPO_PATH, reward_path=REWARD_CONTRACT_PATH),
            aux_files=aux,
            task_uuid=task_uuid,
            repo2env={
                "pipeline": "perf_runtime",
                "repo": rec["repo"],
                "base_commit": rec["base_commit"],
                "instance_id": rec["instance_id"],
                "pr_url": rec.get("pr_url"),
                "content_hash": f"sha256:{content_hash}",
                "reward_kinds": ["measured_speedup", "test_execution", "rubric_judge"],
                "harbor_schema_version": HARBOR_SCHEMA_VERSION,
                "reward_contract_path": REWARD_CONTRACT_PATH,
                "network_policy": "none at grade time, package index at build time only",
                "target_speedup": grounding["target_speedup"],
                "upstream_provenance": grounding["provenance"],
            },
        )
        task_dir = write_harbor_task(task, out_dir)

        # Derive every private artifact from the single source, in one pass.
        proc = subprocess.run(
            ["python3", str(task_dir / "solution" / "recompute.py")], capture_output=True, text=True
        )
        if proc.returncode != 0:
            logger.error("recompute failed for %s: %s", rec["instance_id"], proc.stderr[-800:])
            self._skips["recompute_failed"] = self._skips.get("recompute_failed", 0) + 1
            return None
        (task_dir / "solution" / "patch.diff").write_text(rec["patch"], encoding="utf-8")
        return _Emitted(task_dir=task_dir, uuid=task_uuid, instance_id=rec["instance_id"])

    def emit_calibrated(
        self, rec: dict, out_dir: Path, image_ref: str | None = None
    ) -> _Emitted | None:
        """Emit provisionally, measure the oracle, then bind the target it reached.

        A task whose oracle gain cannot be separated from its own measurement noise is
        rejected with the numbers that rejected it, never shipped with a ceiling that
        no run can reach.
        """
        import tempfile

        if getattr(self.options, "skip_calibration", False):
            return self.emit_one(rec, out_dir, image_ref=image_ref)

        if image_ref:
            covering = list(rec["covering_tests"])
            baseline = self.baseline_clean(rec, image_ref, covering, self._test_cmd(rec, covering))
            self._calibration.setdefault(rec["instance_id"], {})["baseline"] = baseline
            if baseline.get("repaired_image"):
                # Environment repair builds a new image on top of the instance tier,
                # and that repaired image is what the bundle pins. Pushing the
                # pre-repair tier would publish an image no bundle references, so the
                # push has to happen here, after the final image is known.
                image_ref = baseline["repaired_image"]
                registry = getattr(self.options, "registry", "") or ""
                if registry:
                    # docker tag accepts name@digest directly; splitting the digest
                    # off would leave a bare repo name that resolves to :latest.
                    pushed, error = self._push(registry, rec, image_ref)
                    if error:
                        logger.warning(
                            "%s: repaired image not pushed: %s", rec["instance_id"], error
                        )
                    else:
                        image_ref = pushed
            if not baseline["clean"]:
                logger.warning(
                    "%s rejected by the baseline gate: %s (rc=%s)",
                    rec["instance_id"],
                    baseline["reason"],
                    baseline["returncode"],
                )
                key = f"baseline_not_clean:{baseline['reason']}"
                self._skips[key] = self._skips.get(key, 0) + 1
                return None

        with tempfile.TemporaryDirectory() as staging:
            provisional = self.emit_one(rec, Path(staging), image_ref=image_ref)
            if provisional is None:
                return None
            image_ref = json.loads(
                (provisional.task_dir / "solution" / "grounding.yaml").read_text()
            )["image_ref"]
            cal = self.calibrate(provisional.task_dir, image_ref)

        self._calibration.setdefault(rec["instance_id"], {}).update(cal)
        if not cal["ok"]:
            logger.warning(
                "%s rejected by the measurability screen: %s (measured %.4fx, "
                "gain %.4f, noise cv %.4f, required gain %.4f)",
                rec["instance_id"],
                cal["reason"],
                cal.get("measured_speedup", 0.0),
                cal.get("gain", 0.0),
                cal.get("noise_cv", 0.0),
                cal.get("required_gain", 0.0),
            )
            key = f"unmeasurable:{cal['reason']}"
            self._skips[key] = self._skips.get(key, 0) + 1
            return None

        calibrated = dict(rec, speedup=round(cal["measured_speedup"], 6))
        emitted = self.emit_one(calibrated, out_dir, image_ref=image_ref)
        if emitted:
            grounding_path = emitted.task_dir / "solution" / "grounding.yaml"
            grounding = json.loads(grounding_path.read_text())
            grounding["calibration"] = {
                "corpus_speedup": rec["speedup"],
                "measured_oracle_speedup": cal["measured_speedup"],
                "noise_cv": cal["noise_cv"],
                "discrimination_margin": cal["discrimination_margin"],
                "note": "The bound target is what the reference optimization reached in the "
                "graded container under the bound discipline. The corpus value was "
                "measured on the harvest host and is retained for comparison only.",
            }
            grounding_path.write_text(
                json.dumps(grounding, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            subprocess.run(
                ["python3", str(emitted.task_dir / "solution" / "recompute.py")],
                capture_output=True,
                text=True,
            )

            gate = self.verify_endpoints(emitted.task_dir, image_ref)
            self._calibration[rec["instance_id"]]["endpoints"] = gate
            if not gate["ok"]:
                logger.warning(
                    "%s rejected by the endpoint gate: %s",
                    rec["instance_id"],
                    "; ".join(gate["reasons"]),
                )
                key = "endpoint_gate_failed"
                self._skips[key] = self._skips.get(key, 0) + 1
                shutil.rmtree(emitted.task_dir, ignore_errors=True)
                return None
        return emitted

    # --- oracle calibration ---------------------------------------------------

    def repair_environment(self, base_tag: str, tail: str, tag: str) -> tuple:
        """Install exactly the modules the baseline run named as missing, then retry.

        Deterministic rather than agentic: the only packages installed are the ones an
        actual ModuleNotFoundError named. Every addition is recorded, so the resulting
        image is still explainable byte for byte, and a repository whose test extras
        cannot be resolved this way is rejected rather than guessed at.
        """
        packages = []

        for module in dict.fromkeys(re.findall(r"No module named '([A-Za-z0-9_.]+)'", tail)):
            root = module.split(".")[0]
            packages.append(MODULE_ALIASES.get(root, root))

        # A repository that declares pytest plugins in its addopts fails with a usage
        # error rather than an import error, but the defect is the same: a dependency
        # the environment does not carry. The plugin naming convention is stable enough
        # to resolve deterministically.
        for block in re.findall(r"unrecognized arguments:([^\n]+)", tail):
            for arg in re.findall(r"--([A-Za-z0-9][A-Za-z0-9_-]*)", block):
                prefix = arg.split("-")[0].split("=")[0]
                if prefix and f"pytest-{prefix}" not in packages:
                    packages.append(f"pytest-{prefix}")

        if not packages:
            return None, []
        # FROM must name a local tag, never a repo@sha256: reference. BuildKit resolves
        # a digest reference through a registry, so a locally built image addressed by
        # digest fails to resolve even though `docker run` accepts it happily.
        dockerfile = (
            f"FROM {base_tag}\n"
            f'RUN /bin/bash -c "{CONDA_ACTIVATE} && '
            f'pip install {" ".join(packages)}"\n'
        )
        import tempfile

        with tempfile.TemporaryDirectory() as ctx:
            Path(ctx, "Dockerfile").write_text(dockerfile, encoding="utf-8")
            proc = subprocess.run(
                ["docker", "build", "-q", "-t", tag, "-f", str(Path(ctx, "Dockerfile")), ctx],
                capture_output=True,
                text=True,
                timeout=1800,
            )
        if proc.returncode != 0:
            logger.warning("environment repair build failed: %s", proc.stderr[-400:])
            return None, packages
        digest = proc.stdout.strip()
        return f"{tag.split(':')[0]}@{digest}", packages

    def baseline_clean(self, rec: dict, image_ref: str, covering: list, test_cmd: str) -> dict:
        """Grade the unmodified base state before considering any patch.

        FORGE 10d, baseline cleanliness. A task whose covering tests already fail at the
        base commit cannot attribute anything to a submission: every run would fail the
        correctness gate for a reason the submission did not cause. Running it first is
        also the cheapest way to tell a broken environment from a broken task.
        """
        proc = subprocess.run(
            ["docker", "run", "--rm", image_ref, "bash", "-c", in_testbed(test_cmd)],
            capture_output=True,
            text=True,
            timeout=getattr(self.options, "calibration_timeout_sec", 1800),
        )
        full = proc.stdout + proc.stderr
        tail = full[-1200:]
        collection_error = (
            "ModuleNotFoundError" in full or "ImportError" in full or "ERROR collecting" in full
        )
        repairs, attempts = [], 0
        max_repairs = getattr(self.options, "max_environment_repairs", 4)
        while proc.returncode != 0 and collection_error and attempts < max_repairs:
            attempts += 1
            tag = f"kraken/{rec['instance_id'].lower()}:repair{attempts}"
            base_tag = (
                f"kraken.instance.{rec['instance_id'].lower()}:latest"
                if attempts == 1
                else f"kraken/{rec['instance_id'].lower()}:repair{attempts - 1}"
            )
            repaired_ref, packages = self.repair_environment(base_tag, full, tag)
            if not repaired_ref:
                break
            repairs.append({"attempt": attempts, "installed": packages, "image": repaired_ref})
            logger.info(
                "%s: installed %s to complete the environment",
                rec["instance_id"],
                ", ".join(packages),
            )
            image_ref = repaired_ref
            proc = subprocess.run(
                ["docker", "run", "--rm", image_ref, "bash", "-c", in_testbed(test_cmd)],
                capture_output=True,
                text=True,
                timeout=getattr(self.options, "calibration_timeout_sec", 1800),
            )
            full = proc.stdout + proc.stderr
            tail = full[-1200:]
            collection_error = (
                "ModuleNotFoundError" in full
                or "ImportError" in full
                or "ERROR collecting" in full
                or "unrecognized arguments" in full
            )

        return {
            "clean": proc.returncode == 0,
            "returncode": proc.returncode,
            "covering_tests": covering,
            "test_cmd": test_cmd,
            "environment_defect": collection_error,
            "repairs": repairs,
            "repaired_image": image_ref if repairs else None,
            "reason": None
            if proc.returncode == 0
            else ("environment_incomplete" if collection_error else "baseline_tests_fail"),
            "tail": tail,
        }

    def calibrate(self, bundle: Path, image_ref: str) -> dict:
        """Calibrate across `stability_trials` whole-verifier runs, per section 9.

        One container run is a sample, not a measurement. A task is admitted only when
        a majority of the runs produce a stable, separable gain, and the bound target is
        the median of those runs rather than the luckiest one.
        """
        trials = getattr(self.options, "stability_trials", 3)
        runs = [self._calibrate_once(bundle, image_ref) for _ in range(trials)]
        good = [r for r in runs if r.get("ok")]
        attempts = [
            {
                "measured_speedup": r.get("measured_speedup"),
                "gain": r.get("gain"),
                "noise_cv": r.get("noise_cv"),
                "ok": r.get("ok"),
                "reason": r.get("reason"),
            }
            for r in runs
        ]

        if len(good) * 2 <= trials:
            reasons = sorted({r.get("reason") or "unknown" for r in runs if not r.get("ok")})
            return {
                "ok": False,
                "reason": f"unstable_across_trials:{','.join(reasons)}",
                "trials": trials,
                "stable_runs": len(good),
                "attempts": attempts,
            }

        import statistics as _st

        samples = [r["measured_speedup"] for r in good]
        median = _st.median(samples)
        spread = max(samples) - min(samples)
        worst_noise = max(r["noise_cv"] for r in good)

        # The bound target, not the point estimate. Setting the target at the median
        # would put roughly half of all future oracle runs below it by construction,
        # so the reference patch would fail its own top band about half the time and
        # the reward would be unstable by arithmetic rather than by physics. The pilot
        # reasons about a binomial bound for the same reason, and calibration follows
        # it: bind the speedup the reference optimization reliably reaches here, which
        # is its worst observed run less one noise width.
        measured = min(samples) * (1.0 - worst_noise)
        return {
            "ok": True,
            "reason": None,
            "trials": trials,
            "stable_runs": len(good),
            "measured_speedup": measured,
            "target_basis": "min observed oracle speedup less one noise width",
            "observed_samples": samples,
            "observed_median": median,
            "observed_min": min(samples),
            "gain": measured - 1.0,
            "noise_cv": worst_noise,
            "required_gain": max(r["required_gain"] for r in good),
            "discrimination_margin": good[0]["discrimination_margin"],
            "cross_run_spread": spread,
            "attempts": attempts,
        }

    def verify_endpoints(self, bundle: Path, image_ref: str) -> dict:
        """The admission gate: both endpoints calibrated and the reward reproducible.

        requirements/OTS.md section 9 gates 2 and 3. The reference patch must reach
        exactly 1.0 and an empty submission exactly 0.0 on the shipped image through
        the shipped verifier, and three whole-verifier re-runs on the same patch must
        produce an identical reward to the reported precision.

        A task whose reward disagrees across those runs is rejected rather than shipped
        with a caveat, because a reward that moves is not a reward.
        """
        trials = getattr(self.options, "stability_trials", 3)
        max_voids = getattr(self.options, "max_void_retries", 4)
        golden, voids = [], 0
        while len(golden) < trials and voids <= max_voids:
            run = self._run_bundle(bundle, image_ref, "bash /solution/solve.sh")
            if run.get("status") == "void" or run.get("reason") == "measurement_unstable":
                # Repeat rather than score. A void run says the host was too noisy to
                # measure, which is a fact about the machine and not about the patch.
                voids += 1
                continue
            golden.append(run)
        if len(golden) < trials:
            return {
                "ok": False,
                "reasons": [f"could_not_obtain_{trials}_measurable_runs:{voids}_voids"],
                "voids": voids,
                "golden_rewards": [r.get("reward") for r in golden],
            }
        empty = self._run_bundle(bundle, image_ref, "bash /tests/test.sh")

        rewards = [r.get("reward") for r in golden]
        stable = len({f"{r:.4f}" for r in rewards if r is not None}) == 1 and None not in rewards
        top = stable and rewards[0] == 1.0
        floor = empty.get("reward") == 0.0 and empty.get("reason") == "empty_or_noop_patch"

        reasons = []
        if not stable:
            reasons.append(f"reward_unstable_across_{trials}_runs:{rewards}")
        elif not top:
            reasons.append(f"golden_does_not_reach_1.0:{rewards[0]}")
        if not floor:
            reasons.append(f"empty_endpoint_wrong:{empty.get('reward')}:{empty.get('reason')}")

        return {
            "ok": not reasons,
            "reasons": reasons,
            "voids": voids,
            "golden_rewards": rewards,
            "empty_reward": empty.get("reward"),
            "empty_reason": empty.get("reason"),
            "golden_speedups": [r.get("measured_speedup") for r in golden],
        }

    def _run_bundle(self, bundle: Path, image_ref: str, command: str) -> dict:
        import tempfile

        with tempfile.TemporaryDirectory() as logs:
            proc = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{bundle / 'tests'}:/tests:ro",
                    "-v",
                    f"{bundle / 'solution'}:/solution:ro",
                    "-v",
                    f"{bundle / 'environment'}:/environment:ro",
                    "-v",
                    f"{logs}:/logs",
                    image_ref,
                    "bash",
                    "-c",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=getattr(self.options, "calibration_timeout_sec", 1800),
            )
            result_path = Path(logs) / "verifier" / "result.json"
            if not result_path.exists():
                logger.error(
                    "bundle run produced no result: rc=%s stderr=%s stdout=%s",
                    proc.returncode,
                    proc.stderr[-600:],
                    proc.stdout[-300:],
                )
                return {"reward": None, "reason": "no_result"}
            return json.loads(result_path.read_text())

    def _calibrate_once(self, bundle: Path, image_ref: str) -> dict:
        """Run the reference optimization through the graded path and measure it.

        The corpus speedup was measured on the harvest host. The task is graded in this
        container, on this CPU, under this discipline, so the target that binds must be
        the one the reference patch actually reaches here. Anything else ships a ceiling
        nobody has shown to be attainable.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as logs:
            proc = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{bundle / 'tests'}:/tests:ro",
                    "-v",
                    f"{bundle / 'solution'}:/solution:ro",
                    "-v",
                    f"{bundle / 'environment'}:/environment:ro",
                    "-v",
                    f"{logs}:/logs",
                    image_ref,
                    "bash",
                    "/solution/solve.sh",
                ],
                capture_output=True,
                text=True,
                timeout=getattr(self.options, "calibration_timeout_sec", 1800),
            )
            result_path = Path(logs) / "verifier" / "result.json"
            if not result_path.exists():
                return {
                    "ok": False,
                    "reason": "oracle_produced_no_result",
                    "stderr": proc.stderr[-800:],
                }
            result = json.loads(result_path.read_text())
            base = (
                json.loads((Path(logs) / "verifier" / "baseline.out").read_text())
                if (Path(logs) / "verifier" / "baseline.out").exists()
                else {}
            )
            opt = (
                json.loads((Path(logs) / "verifier" / "optimized.out").read_text())
                if (Path(logs) / "verifier" / "optimized.out").exists()
                else {}
            )

        if result.get("reason"):
            return {"ok": False, "reason": f"oracle_capped:{result['reason']}"}

        measured = float(result.get("measured_speedup") or 0.0)
        noise = max(float(base.get("cv") or 0.0), float(opt.get("cv") or 0.0))
        gain = measured - 1.0
        margin = getattr(self.options, "discrimination_margin", 2.0)
        separable = gain > margin * noise and noise > 0
        return {
            "ok": separable,
            "host_load": host_load(),
            "reason": None if separable else "gain_inside_noise_band",
            "measured_speedup": measured,
            "gain": gain,
            "noise_cv": noise,
            "required_gain": margin * noise,
            "discrimination_margin": margin,
            "baseline_median": base.get("value"),
            "optimized_median": opt.get("value"),
        }

    def run(self, out_dir: Path) -> PipelineResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        self._skips = {}
        self._calibration = {}
        records = self.load_corpus()

        # Stage 1: build every image first. No measurement happens while a build runs,
        # because a build is exactly the kind of load that ruins a runtime measurement.
        prebuilt: dict = {}
        if not getattr(self.options, "skip_image_build", False):
            for index, rec in enumerate(records, start=1):
                logger.info("building image %d/%d for %s", index, len(records), rec["instance_id"])
                image_ref, error = self.build_image(
                    rec, self.dockerfile(rec), out_dir / ".build" / rec["instance_id"]
                )
                if error:
                    logger.error("image build failed for %s: %s", rec["instance_id"], error)
                    self._skips["image_build_failed"] = self._skips.get("image_build_failed", 0) + 1
                    continue
                prebuilt[rec["instance_id"]] = image_ref

        # The barrier. Everything after this point is measurement.
        quiet = wait_for_quiet() if prebuilt else {"quiet": True, "skipped": "no builds ran"}
        self._quiescence = quiet
        logger.info(
            "quiescence: %s after %ss, load %s",
            quiet.get("quiet"),
            quiet.get("waited_seconds"),
            (quiet.get("load") or {}).get("per_cpu"),
        )

        # Stage 2: calibrate, gate, and emit, one instance at a time on a quiet host.
        emitted = []
        for rec in records:
            if prebuilt and rec["instance_id"] not in prebuilt:
                continue
            result = self.emit_calibrated(rec, out_dir, image_ref=prebuilt.get(rec["instance_id"]))
            if result:
                emitted.append(result)
                logger.info("emitted %s as %s", result.instance_id, result.uuid)
        manifest = {
            "pipeline": "perf_runtime",
            "emitted": [{"uuid": e.uuid, "instance_id": e.instance_id} for e in emitted],
            "skipped": self._skips,
            "calibration": self._calibration,
            "rejected_before_build": getattr(self, "_rejected", {}),
            "quiescence": getattr(self, "_quiescence", None),
        }
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return PipelineResult(
            candidates=len(records),
            emitted=len(emitted),
            skipped=sum(self._skips.values()),
            out_dir=out_dir,
            skip_reasons=self._skips,
        )
